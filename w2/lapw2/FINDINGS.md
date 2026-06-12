# KẾT QUẢ NGHIÊN CỨU & ĐÁNH GIÁ (FINDINGS)

## 1. Hàm tính độ tương đồng (Similarity function) ở Layer 2 và lý do lựa chọn

Chúng tôi sử dụng hàm tính độ tương đồng lai có trọng số (weighted hybrid similarity) kết hợp 4 tín hiệu chính:
- `0.40 * log_sim` (Độ tương đồng của log)
- `0.35 * trace_sim` (Độ tương đồng của trace)
- `0.15 * svc_sim` (Độ tương đồng của danh sách service bị ảnh hưởng)
- `0.10 * metric_sim` (Độ tương đồng của các số liệu metric delta)

**Phương án thay thế đã xem xét:** So khớp mẫu log chính xác (exact template matching).
- **Lý do loại bỏ:** Phương án này quá cứng nhắc do có sự khác biệt về cấu trúc (schema mismatch) giữa dữ liệu sự cố thực tế (dòng log thô) và dữ liệu lịch sử (các mẫu log đã được làm sạch).
- **Minh chứng thực tế:** Ở sự cố `E01`, việc khớp mẫu chính xác trả về `log_sim = 0.0` đối với cả hai tiền lệ bị cạn kiệt tài nguyên kết nối (`INC-2025-11-08` và `INC-2025-09-05`). Lý do là mẫu log thực tế của `E01` chứa các chuỗi như `failed to forward request to t24-service: pool exhausted` và `connectionpool: timeout acquiring connection (waited var ) attempt var`, trong khi lịch sử lưu trữ các mẫu ngắn gọn hơn.
- **Giải pháp:** Sử dụng bộ so khớp từ trùng lặp (word-overlap matcher) (yêu cầu trùng lặp ≥ 2 từ) giúp giữ lại các tín hiệu tương đồng quan trọng, giúp hệ thống đạt kết quả đánh giá tuyệt đối `8/8` trong bài kiểm tra.

---

## 2. So sánh giữa bỏ phiếu có trọng số theo kết quả (Outcome-weighted voting) và bỏ phiếu theo độ tương đồng thuần túy (Pure similarity)

Ví dụ thực tế rõ ràng nhất là sự cố `E05`.

**Nếu bỏ phiếu theo độ tương đồng thuần túy (Pure similarity):**
- `rollback_service = 0.785`
- `increase_pool_size = 0.555`
- `restart_pod = 0.225`

**Khi áp dụng bỏ phiếu có trọng số theo kết quả (Outcome-weighted):**
- `rollback_service = 0.670`
- `increase_pool_size = 0.555`
- `restart_pod = 0.225`

**Giải thích sự thay đổi:**
Sự sụt giảm điểm số của `rollback_service` bắt nguồn từ sự cố lịch sử `INC-2026-05-10` vốn có kết quả xử lý chỉ là một phần (`partial`), do đó hệ số trọng số chỉ được tính bằng `0.5x` thay vì `1.0x` (thành công). 
Mặc dù sự thay đổi này chưa làm đảo lộn vị trí dẫn đầu của `rollback_service` trên bộ dữ liệu kiểm thử, nó đã thu hẹp khoảng cách giữa `rollback_service` và `increase_pool_size` từ `0.230` xuống còn `0.115`. Chính sự mơ hồ (ambiguity) này là căn cứ để bộ máy quyết định leo thang sự cố `E05` lên nhóm trực vận hành (`page_oncall`) thay vì tự động thực hiện hành động thiếu an toàn.

---

## 3. Giải thích chi tiết phép tính Giá trị Kỳ vọng (Expected Value - EV) cho một sự cố cụ thể

Chúng tôi chọn sự cố `E01` (lỗi cạn kiệt pool kết nối của `payment-svc`) làm ví dụ vì hệ thống đã tự động đưa ra quyết định xử lý thành công.

Sau giai đoạn truy vấn dữ liệu (retrieval), danh sách hành động ứng viên gồm:
- `increase_pool_size`: `vote_score = 0.573333`, `confidence = 0.396770`
- `rollback_service`: `vote_score = 0.679999`, `confidence = 0.470588`

**Các thông số tính toán Giá trị Kỳ vọng (EV):**
- Xác suất thành công ($P_{success}$ = success_votes / total_votes):
  - `increase_pool_size`: $P_{success} = 0.573333 / 0.573333 = 1.0$; Chi phí (cost) = $1$
  - `rollback_service`: $P_{success} = 0.573333 / 0.679999 = 0.843138$; Chi phí (cost) = $10$

**Tính toán độ thỏa dụng (Utility = P_success * confidence - 0.005 * cost):**
- `increase_pool_size`: $1.0 \times 0.396770 - 0.005 \times 1 = 0.391770$
- `rollback_service`: $0.843138 \times 0.470588 - 0.005 \times 10 = 0.346771$

**Điểm số kết hợp cuối cùng (Combined Score = Utility + 0.05 * vote_score):**
- `increase_pool_size`: $0.391770 + 0.05 \times 0.573333 = 0.420437$
- `rollback_service`: $0.346771 + 0.05 \times 0.679999 = 0.380771$

**Kết luận:** Hành động `increase_pool_size` giành chiến thắng với khoảng cách là `0.039666`, và quyết định tự động thực thi này hoàn toàn trùng khớp với kết quả mong đợi trong `eval/expected.json`.

---

## 4. Các trường hợp hệ thống quyết định leo thang (page_oncall) thay vì tự động xử lý

Hệ thống quyết định leo thang lên con người (`page_oncall`) trong 6 sự cố sau:
- `E02` ở độ tin cậy `0.33` với lý do `conflicting_evidence` (Bằng chứng xung đột)
- `E04` ở độ tin cậy `0.30` với lý do `ood` (Dữ liệu ngoài phân phối / Chưa từng gặp trong lịch sử)
- `E05` ở độ tin cậy `0.325` với lý do `near_tie` (Điểm số quá sát sao giữa các hành động)
- `E06` ở độ tin cậy `0.334286` với lý do `conflicting_evidence` (Bằng chứng xung đột)
- `E07` ở độ tin cậy `0.60` với lý do `ood` (Dữ liệu ngoài phân phối)
- `E08` ở độ tin cậy `0.30` với lý do `ood` (Dữ liệu ngoài phân phối)

**Đánh giá độ chính xác:** 
Tất cả 6 quyết định leo thang này đều **hoàn toàn chính xác** khi đối chiếu với `eval/expected.json`, vì tất cả các trường hợp này đều chấp nhận hành động `page_oncall`. Đồng thời, 2 trường hợp tự động xử lý còn lại cũng chính xác (`E01 -> increase_pool_size` và `E03 -> rollback_service`).

---

## 5. Loại sự cố dễ khiến hệ thống đưa ra quyết định sai sót nhất và đề xuất cải tiến

**Loại sự cố dễ gây lỗi nhất:** 
Các sự cố xảy ra ở tầng hạ tầng mới (novel infra) hoặc mặt điều khiển (control-plane) có cách biểu diễn topo liên kết dịch vụ (service edges) tương tự các lỗi quen thuộc nhưng mang ngữ nghĩa và nguyên nhân gốc hoàn toàn mới (điển hình như sự cố dạng `E07`).
Trong quá trình chạy thử nghiệm, `E07` đạt điểm tương đồng cao nhất `best_sim = 0.60` vì chia sẻ chung liên kết `checkout-svc -> inventory-svc` và cùng các dịch vụ bị ảnh hưởng, dù nguyên nhân gốc thực tế là do nghẽn API Kubernetes (`k8s_api_throttle`) kết hợp lỗi bộ nhớ đệm lỗi thời (`informer-cache-stale`).

**Đề xuất cải tiến cụ thể:**
Xây dựng một bộ tái xếp hạng ngữ nghĩa dựa trên topo (topology-aware semantic reranker) để chấm điểm các từ khóa kích hoạt cảnh báo (trigger-rule tokens) và các vector đặc trưng (embeddings) của mẫu log ngay sau bước lọc thô bằng trọng số tương đồng.

**Lý do chưa triển khai trong giới hạn thời gian:**
Tập dữ liệu lịch sử sự cố quá nhỏ (chỉ khoảng 30 sự cố). Việc tích hợp một bộ tái xếp hạng dựa trên mô hình học máy phức tạp hoặc embedding sẽ cực kỳ khó hiệu chuẩn (calibrate), dễ dẫn đến hiện tượng quá khớp (overfitting), và tốn kém hơn nhiều so với các quy tắc tường minh, dễ kiểm toán hiện tại.

---

## Lưu ý về trạng thái hiện tại của Repo

Repository hiện có thêm các khung mã nguồn hỗ trợ chế độ hoạt động thực tế (live-mode scaffolding) cho Kafka, Redis, Qdrant, PostgreSQL và Kubernetes. Những phần bổ sung này không nằm trong phạm vi đánh giá điểm số của Lab nêu trên; các phát hiện và ví dụ số liệu trong tài liệu này đề cập trực tiếp đến luồng đánh giá ngoại tuyến (offline eval) được điều khiển bởi `engine.py` / `engine_compat.py` và các sự cố từ `eval/E01` đến `eval/E08`.
