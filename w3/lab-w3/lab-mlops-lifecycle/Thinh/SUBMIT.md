# SUBMIT.md — Reflection: MLOps Lifecycle Lab

## Câu 1: Drift threshold bạn chọn là bao nhiêu và tại sao?

Threshold là **0.15** (15% features drifted). Cách chọn: chạy `drift_detector.py` trên chính `baseline.csv`, split 70/30 (3 tuần đầu làm reference, tuần cuối làm current) — noise floor đo được là 0.04. Threshold 0.15 = 3.75× noise floor, đủ xa để không bị false positive từ seasonal variation (sáng/tối traffic khác nhau), nhưng đủ thấp để catch drift thực khi 1-2 features bắt đầu dịch chuyển. Khi test với `drifted.csv`, score thực đo được = **0.67** (2/3 features drifted: latency_p99 tăng từ 120ms lên 156ms, error_rate từ 0.8% lên 1.6%, rps từ 450 lên 630) — vượt threshold rõ ràng. Nếu chọn 0.05, drift check sẽ fire mỗi ngày do intraday traffic pattern biến động tự nhiên. Nếu chọn 0.50, sẽ bỏ sót drift giai đoạn đầu khi chỉ error_rate bắt đầu tăng nhưng latency và rps vẫn ổn.

---

## Câu 2: Điều gì xảy ra nếu model v2 sau retrain lại tệ hơn v1?

Pipeline có **3 tầng bảo vệ** chống v2 underperform. Tầng 1: **holdout validation** — trước khi register, `retrain.py` evaluate v2 trên `holdout.csv` (500 rows old pattern) và print precision/recall; nếu precision giảm quá nhiều, engineer sẽ thấy ngay. Tầng 2: **manual approval gate** — ML engineer xem anomaly_rate của v2 (so với v1) trước khi promote; nếu bất thường, từ chối promote bằng `N`, v2 ở lại alias `staging`. Tầng 3: **auto-rollback** — sau khi promote, `post_deploy_monitor` chạy 24 cycles trên `post_deploy_eval.csv`; nếu v2 precision < 0.65, hệ thống tự động demote v2 sang `@archived` và restore v1 về `@production`, gọi `POST /reload` trên serve.py. Toàn bộ rollback < 5 giây vì chỉ swap alias trong MLflow Registry, không cần redeploy container. Mọi sự kiện rollback được log vào `outputs/audit_log.jsonl` với event `auto_rollback_v2_to_v1` kèm demoted_version, restored_version, trigger_precision, và cycle number.

---

## Câu 3: Sự khác biệt giữa data drift và concept drift?

**Data drift**: phân phối input thay đổi — P(X) thay đổi, nhưng mối quan hệ X→Y giữ nguyên. Ví dụ trong lab: latency baseline tăng từ 120ms lên 156ms vì thêm 3rd-party integration. Model IsolationForest train với mean 120ms sẽ coi 156ms là outlier (anomaly), dù thực ra đó chỉ là "new normal" — precision giảm vì false positives tăng.

**Concept drift**: mối quan hệ input-output thay đổi — P(Y|X) thay đổi. Ví dụ: cùng latency 200ms, trước đây là anomaly, nhưng sau khi scale up infra thì 200ms là bình thường. Feature distribution có thể không đổi nhiều, nhưng ý nghĩa của mỗi data point đã khác — model hoàn toàn sai.

Evidently DataDriftPreset trong lab này detect **data drift** bằng statistical test (Wasserstein distance) trên feature values. Concept drift **không được detect trực tiếp** bởi DataDriftPreset — trong `drifted.csv` có 25% labels bị flip (concept drift injection) nhưng `--check-mode data` sẽ không thấy. Chỉ `--check-mode combined` mới surface precision drop bằng cách evaluate model trên labeled data. Proxy cho production (không có labels): monitor anomaly_rate trend qua thời gian trong MLflow.

---

## Câu 4: Tại sao blue-green swap quan trọng hơn replace file trực tiếp?

Replace file trực tiếp (overwrite model artifact trên disk) tạo ra **race condition**: serve.py đang xử lý request sử dụng model cũ, đồng thời file bị ghi đè → corrupted read → crash hoặc wrong prediction. Không có rollback path — version cũ đã bị overwrite, nếu model mới có vấn đề phải retrain từ đầu.

Blue-green qua MLflow alias: alias `production` được swap **atomically** từ v1 → v2 trong MLflow Registry (chỉ thay đổi pointer, không thay đổi artifact). Serve.py chỉ load model mới khi nhận lệnh `POST /reload` — tất cả in-flight request trước đó hoàn thành với model v1 (no downtime, no corrupted prediction). Nếu v2 có vấn đề, swap alias về v1 + `POST /reload` = **rollback tức thì** trong < 5 giây, không cần redeploy container. Cả 2 versions tồn tại song song trong registry — zero data loss. Endpoint `/health/active-version` cho phép verify version trước khi cutover hoàn toàn — essential cho on-call team khi debug.

---

## Câu 5: Nếu automate approval gate, dùng metric gì và threshold nào?

Dùng **anomaly_rate delta** giữa v2 và v1 trên cùng một validation window (20% cuối của current window làm holdout). Điều kiện auto-promote:

- `abs(v2_anomaly_rate - v1_anomaly_rate) < 0.05` — v2 không thay đổi behavior quá 5% so với v1 trên cùng data
- `v2_anomaly_rate < 0.10` — không bị degenerate (flag toàn bộ data là anomaly)
- `v2_anomaly_rate > 0.01` — không bị quá conservative (không phát hiện gì)

Ngưỡng 5% delta là conservative cho payment domain — sai lệch 5% trên 1000 requests/phút = 50 missed anomalies hoặc 50 false alerts mỗi phút, có impact trực tiếp tới SLA. Ngoài ra cần kiểm tra holdout precision ≥ 0.70 (tức v2 không overfit vào distribution mới mà quên pattern cũ). Nếu cả điều kiện thỏa → auto-promote + start post-deploy monitor (24 cycles). Nếu không thỏa → push alert cho ML engineer review trong 4h. Timeout 4h đảm bảo staging model không treo vô hạn.
