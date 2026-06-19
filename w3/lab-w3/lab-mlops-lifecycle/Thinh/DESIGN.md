# DESIGN.md — MLOps Lifecycle: Anomaly Detection Pipeline

## Tổng quan

Pipeline phát hiện drift trong metrics payment gateway (latency_p99, error_rate, rps), trigger retrain model IsolationForest, và swap phiên bản mới qua MLflow Registry alias. Hệ thống bao gồm 4 thành phần chính: `pipeline.py` (training), `serve.py` (serving), `drift_detector.py` (monitoring), và `retrain.py` (orchestration).

---

## Sub-checkpoint 1: Drift Threshold

**Giá trị đã chọn: 0.15** (15% features bị drift theo Evidently DataDriftPreset).

**Cách chọn:** Trước tiên chạy `drift_detector.py` trên chính `baseline.csv`, chia 70/30 (3 tuần đầu làm reference, tuần cuối làm current). Kết quả drift score = 0.04 — đây là "noise floor" khi không có drift thực sự, phản ánh biến động intraday (sáng/tối traffic khác nhau). Từ đó chọn threshold = 0.15, tức gấp 3.75× noise floor. Khi test với `drifted.csv`, drift score thực đo được là **0.67** (2/3 features drifted: latency_p99 và rps đều vượt statistical test), vượt threshold rõ ràng.

**Rủi ro nếu threshold quá thấp (ví dụ 0.05):** False positive — retrain sẽ trigger sau mỗi seasonal fluctuation bình thường. Với 6 drift checks mỗi ngày, threshold 0.05 sẽ fire ít nhất 2-3 lần/tuần chỉ do intraday pattern, tốn compute (~30s mỗi retrain cycle) và gây alert fatigue cho on-call team.

**Rủi ro nếu threshold quá cao (ví dụ 0.50):** False negative — bỏ sót drift giai đoạn đầu khi chỉ 1/3 features bắt đầu dịch (ví dụ chỉ error_rate tăng nhưng latency và rps vẫn ổn). Model tiếp tục serve với phân phối không còn phù hợp, precision/recall giảm âm thầm trước khi system phát hiện.

---

## Sub-checkpoint 2: Loại Drift

**Loại được detect: Data drift** — P(X) thay đổi, tức phân phối input features (latency_p99, error_rate, rps) đã dịch chuyển so với training data.

**Evidently DataDriftPreset detect:** Statistical test trên từng feature. Mặc định dùng Wasserstein distance cho numerical features, và Jensen-Shannon divergence cho category features. Khi `share_of_drifted_columns` > threshold → flag drift. Trong dữ liệu lab: latency mean tăng từ 120ms lên ~156ms (+30%), error_rate từ 0.8% lên ~1.6% (gấp đôi), rps từ 450 lên ~630 (+40%).

**Tại sao data drift phù hợp với bài toán này:** Payment gateway anomaly detection cần biết khi nào "bình thường mới" (new normal) khác với "bình thường cũ". Sau campaign, latency baseline tăng lên 156ms — model v1 train với baseline 120ms sẽ coi 156ms là anomaly dù thực ra là normal trong context mới. Detect data drift cho phép retrain model với distribution mới trước khi precision giảm đáng kể.

**Concept drift (P(Y|X) thay đổi) không được detect trực tiếp** bởi DataDriftPreset vì không có ground truth labels trong production real-time. Tuy nhiên, `drift_detector.py` hỗ trợ `--check-mode combined` để evaluate precision/recall trên labeled holdout — đây là proxy cho concept drift detection. Performance drift (anomaly rate trend) cũng được log vào MLflow mỗi lần drift check.

---

## Sub-checkpoint 3: Retrain Trigger Configuration

**Trigger type: Manual approval gate** — semi-automatic.

**Cadence:** Không có schedule cố định. Drift check được gọi khi có batch data mới (có thể integrate vào daily batch job). Nhưng promotion từ `staging` → `production` luôn yêu cầu human approval qua prompt `[y/N]`.

**Lý do chọn manual:** Model anomaly detection trong payment system ảnh hưởng trực tiếp đến on-call SLA. Một model tệ hơn được promote tự động có thể gây false negatives trên incident thực (miss một outage → tài chính bị ảnh hưởng), hoặc alert storm từ false positives (200+ false alerts/giờ → on-call fatigue). Approval gate đảm bảo ML engineer review metrics (anomaly_rate của v2 vs v1, drift score, holdout precision) trước khi cutover.

**Approval timeout:** Không implement timeout trong lab. Trong production, recommend 24h timeout — nếu không có approval trong 24h, staging version bị archive và drift check reset. Tránh trạng thái "staging model treo mãi không ai review". Flag `--auto-approve` chỉ dùng cho CI/testing.

**Nếu tự động hoàn toàn:** Có thể dùng anomaly_rate delta giữa v2 và v1 (xem Sub-checkpoint 5 trong SUBMIT.md). Điều kiện auto-promote: `abs(v2_rate - v1_rate) < 0.05` VÀ `v2_rate ∈ [0.01, 0.10]`. Ngưỡng 5% delta là conservative cho payment domain.

---

## Sub-checkpoint 4: Versioning và Rollback

**Chiến lược versioning:** MLflow Registry với aliases, không phụ thuộc vào version numbers.

- `production` alias → version đang serve
- `staging` alias → version candidate sau retrain
- `archived` alias → version bị demote sau auto-rollback
- Version numbers (1, 2, 3…) là immutable audit trail — không bao giờ bị xóa

**Tại sao alias tốt hơn version number trong code serve.py:** `mlflow.pyfunc.load_model("models:/anomaly-detector@production")` không thay đổi khi swap. Nếu hardcode version number (ví dụ `models:/anomaly-detector/2`), phải redeploy serve.py mỗi lần retrain — vi phạm principle "no code change for model swap".

**Rollback path:**
1. Phát hiện v2 underperform (precision giảm, alert storm): `MlflowClient.set_registered_model_alias("anomaly-detector", "production", "1")` — swap alias về v1.
2. Gọi `POST /reload` trên serve.py — load lại v1 từ registry.
3. Toàn bộ quá trình < 30 giây, không cần redeploy container.

**Ai có quyền rollback:** ML engineer on-call (có MLflow admin access). Trong production, rollback được wrap thành Runbook command với audit log tại `outputs/audit_log.jsonl`.

**Retention policy:** Giữ tất cả registered versions vô thời hạn. Model IsolationForest < 1MB — storage cost negligible. Không xóa version cũ vì cần cho audit trail và rollback bất kỳ lúc nào.

---

## Sub-checkpoint 5: Cơ chế phát hiện drift — tại sao cần combined mode

Chỉ dùng `DataDriftPreset` (data drift) là **chưa đủ** cho production. Data drift phát hiện khi P(X) thay đổi — tức phân phối input features dịch chuyển. Nhưng trong tình huống payment gateway, có thể xảy ra **concept drift**: P(Y|X) thay đổi mà P(X) vẫn ổn định.

**Ví dụ cụ thể:** Trong `drifted.csv`, 25% labels đã bị flip (concept drift injection). Cùng một mức latency 180ms — với rule cũ là "normal", nhưng sau khi payment processor mới rollout, mối quan hệ feature→anomaly đã thay đổi. Nếu chỉ chạy `--check-mode data`, Evidently sẽ phát hiện drift score = 0.67 nhưng **hoàn toàn không biết** precision của model đã giảm từ 0.91 xuống khoảng 0.58 trên labeled holdout. Chạy `--check-mode combined` sẽ output **cả hai**: `Drift score: 0.67` VÀ `Perf precision: 0.58` — cho phép engineer thấy rõ cả data drift lẫn performance degradation.

Điều kiện trigger trong combined mode: `is_drift = True` **HOẶC** `perf_is_degraded = True`. Tức nếu data distribution ổn nhưng precision giảm → vẫn trigger retrain. Đây là cơ chế "defense in depth" cho model monitoring.

---

## Sub-checkpoint 6: Data selection strategy — sliding window vs alternatives

Khi retrain chỉ trên drift window (7 ngày gần nhất, 1008 rows), model v2 **overfit vào phân phối mới**: nó học rằng latency 156ms là "bình thường" nhưng quên rằng hệ thống vẫn phải xử lý các batch job chạy theo pattern cũ. Thực nghiệm: train trên drift window only → v2 precision trên `holdout.csv` (old pattern, 500 rows) giảm đáng kể so với v1.

**Sliding window strategy** (baseline 4320 rows + drift window 1008 rows = 5328 rows) cho kết quả tốt hơn vì model thấy cả 2 regime. IsolationForest với 5328 rows không bị dominated bởi phân phối mới (baseline chiếm 81% training set). Acceptance criterion: v2 precision và recall trên `holdout.csv` phải ≥ v1 precision/recall đo trên cùng tập đó.

**Các alternative và so sánh:**

| Strategy | Ưu điểm | Nhược điểm |
|---|---|---|
| **Pure drift window** (1008 rows) | Đơn giản, train nhanh | Overfit new distribution, precision giảm trên old pattern |
| **Sliding window** (5328 rows) ✅ | Balance cả 2 regimes, robust | Training set lớn hơn (nhưng vẫn < 1s cho IsolationForest) |
| **Weighted sampling** (oversample baseline) | Tốt khi drift window rất nhỏ | Phức tạp hơn, cần tune sampling ratio |
| **Full historical concat** | An toàn nhất | Tốn compute khi data tích lũy nhiều tháng, irrelevant old patterns |

Sliding window là trade-off tốt nhất: đủ đơn giản để implement, đủ robust để không overfit, và train time vẫn < 1 giây.

---

## Sub-checkpoint 7: Auto-rollback — threshold và policy

Sau khi v2 được promote lên `@production`, `post_deploy_monitor` trong `retrain.py` chạy **24 polling cycles** đánh giá precision trên `post_deploy_eval.csv` (200 rows có nhãn rõ ràng: 60% clear-normal, 40% clear-anomaly).

**Ngưỡng auto-rollback: precision < 0.65.**

**Tại sao 0.65?** Đây là ngưỡng bảo thủ — thấp hơn baseline 91% nhưng đủ xa để không trigger false rollback do sampling noise trên 200 rows. Tính toán: với 80 anomaly rows (40% của 200), nếu model miss 30 → precision ≈ 0.88; nếu model hoàn toàn confused → precision ≈ 0.40. Ngưỡng 0.65 nằm ở điểm "model rõ ràng đang sai lệch nghiêm trọng" — không phải noise.

**Rollback flow:**
1. `client.set_registered_model_alias(MODEL_NAME, "archived", v2_version)` — demote v2
2. `client.set_registered_model_alias(MODEL_NAME, "production", v1_version)` — restore v1
3. `POST /reload` trên serve.py — load lại v1
4. Toàn bộ < 5 giây

**Audit log:** Mọi sự kiện được append vào `outputs/audit_log.jsonl` với event key `auto_rollback_v2_to_v1`, bao gồm:
- `demoted_version`: version bị demote (v2)
- `restored_version`: version được restore (v1)
- `trigger_precision`: precision value khi trigger rollback
- `cycle`: cycle number khi rollback xảy ra

---

## Kiến trúc component

```
baseline.csv (reference)
     │
     ├──► pipeline.py ──► MLflow Run ──► Registry v1 @production
     │
drifted.csv (current window)
     │
     ├──► drift_detector.py (combined mode)
     │         │ data drift score=0.67 > threshold=0.15
     │         │ perf precision check on labeled data
     │         ▼
     └──► retrain.py
              │
              ├── sliding window: baseline + drifted = 5328 rows
              ├── train IsoForest on combined data
              ├── holdout validation: v2 precision ≥ v1
              ├── MLflow Run → Registry v2 @staging
              ├── [HUMAN APPROVAL]
              ├── set alias production → v2
              ├── POST /reload → serve.py
              └── post_deploy_monitor: 24 cycles
                    └── if precision < 0.65 → auto-rollback v2→@archived, v1→@production
```

---

## Trade-offs đã chấp nhận

| Quyết định | Được | Mất |
|---|---|---|
| Manual approval gate | An toàn, human oversight | Latency trong retrain loop (hours, không phải minutes) |
| Combined mode (data + performance drift) | Detect cả 2 loại drift | Cần labeled data cho performance check |
| Sliding window (baseline + drift) | Robust, không overfit | Training set lớn hơn (vẫn < 1s) |
| Auto-rollback threshold 0.65 | Bảo thủ, tránh false rollback | Có thể miss degradation nhẹ (precision 0.66-0.70) |
| IsolationForest (không LSTM-AE) | Train < 1s, explainable, no GPU | Không capture temporal patterns, mỗi row độc lập |
| Local artifact store | Không cần S3 setup | Không scale multi-node, artifacts mất khi volume bị xóa |
