# W3-D1 Submission — Nguyễn Tiến Hoàng Thịnh

## 3 thứ em học được
1. **Bản chất của Multi-Window Multi-Burn-Rate (MWMBR):** Em đã hiểu cách kết hợp hai cửa sổ thời gian (Long window và Short window) bằng toán tử `AND`. Cửa sổ dài giúp xác định mức độ thâm hụt nghiêm trọng của Error Budget, còn cửa sổ ngắn đảm bảo sự cố vẫn đang thực sự tiếp diễn ở hiện tại, từ đó triệt tiêu các cảnh báo giả do mạng chập chờn nhất thời.
2. **Cách bóc tách dữ liệu cấu hình của script chấm điểm:** Em học được rằng các hệ thống tự động kiểm thử thường sử dụng biểu thức chính quy (Regex) cố định để quét chuỗi. Việc viết đúng cú pháp mẫu như cấu trúc mẫu số `(1 - SLO)` và phân chia chính xác các nhóm `group` theo dịch vụ (`api-slo`, `db-slo`, `frontend-slo`) là bắt buộc để script nhận diện được luật.
3. **Tầm quan trọng của việc loại trừ mã lỗi phía Client:** Em biết cách lọc bỏ các mã lỗi `4xx` (như 401, 403, 404) ra khỏi chỉ số lỗi của SLI vì chúng phản ánh hành vi sai sót của người dùng cuối chứ không phải lỗi hệ thống, đồng thời biết giữ lại lỗi `429` để giám sát trạng thái quá tải lưu lượng.

## 1 thứ vẫn chưa rõ
Em vẫn chưa hoàn toàn rõ về cách script kiểm thử `validate.py` đánh giá các luật Tier 3 (cửa sổ dài ngày `3d` / `6h`). Khi em cấu hình đầy đủ 9 rules bao gồm cả Tier 3, hệ thống chấm điểm mô phỏng tĩnh chỉ ghi nhận và tính toán số liệu trên `rules_count: 2` khẩn cấp của layer API. Em muốn tìm hiểu sâu hơn xem trong môi trường chạy live thực tế của Prometheus, việc tích lũy dữ liệu cho các cửa sổ dài ngày như vậy sẽ ảnh hưởng thế nào đến bộ nhớ và hiệu năng của server giám sát.

## 1 trade-off trong SLO decision của em mà em không chắc
Một đánh đổi (trade-off) mà em còn phân vân là việc đặt ngưỡng Latency Threshold P99 cho dịch vụ API ở mốc `500ms`. Việc chọn mốc 500ms giúp em có một khoảng đệm an toàn lớn, triệt tiêu hoàn toàn cảnh báo giả (`fp: 0`) và đạt tỷ lệ giảm nhiễu rất cao (86.4%). Tuy nhiên, đổi lại là thời gian phát hiện lỗi bị trễ hơn so với cấu hình tĩnh cũ đúng 60 giây (`mttd_delta_s: 60`). Em không chắc chắn liệu trong các hệ thống tài chính hoặc giao dịch thời gian thực cao cấp, độ trễ 60 giây này có bị coi là quá chậm và gây thiệt hại lớn cho doanh nghiệp trước khi đội ngũ SRE kịp nhận thông báo hay không.

## Validation report
- noise_reduction_pct: 86.4%
- mttd_delta_s: 60s
- false_negative: 0
- verdict: pass