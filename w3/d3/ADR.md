# ADR-001: Bổ sung context rollout vào Detection và RCA cho thay đổi edge policy

## Trạng thái
Đã chấp nhận

## Bối cảnh
Qua reproduction của outage theo kiểu Cloudflare cho thấy detection chỉ dựa trên latency vẫn có thể tìm ra service đang lỗi, nhưng cảnh báo vẫn đến sau khi người dùng đã bị ảnh hưởng. Pipeline hiện tại đã phát `HighLatencyRegex` và trả về `regex-edge` là root service, nhưng chưa giải thích được outage này bắt nguồn từ một edge policy rollout mới. Với lớp failure này, metric ở mức service là chưa đủ; platform cần có thêm context về change event để phân biệt deploy lỗi với load bất thường hoặc host pressure thông thường.

## Quyết định
Nền tảng AIOps sẽ kết hợp runtime anomaly detection với correlation dựa trên sự kiện rollout cho edge policy, và payload RCA sẽ trả về cả service đang lỗi lẫn tín hiệu rollout kích hoạt sự cố nếu có đủ bằng chứng.

## Các phương án đã cân nhắc
- Phương án A: chỉ dùng ngưỡng latency đơn. Ưu điểm: đơn giản, chi phí vận hành thấp. Nhược điểm: chỉ phản ứng sau khi sự cố đã ảnh hưởng người dùng, không cho biết có phải deploy mới là tác nhân hay không. Bị loại vì quá bị động.
- Phương án B: chỉ xếp hạng alert theo số lượng. Ưu điểm: nhanh, dễ triển khai trên nhiều service. Nhược điểm: xếp hạng triệu chứng thay vì nguyên nhân, và bỏ qua hoàn toàn rollout metadata. Bị loại vì yếu trong các sự cố kiểu cascading hoặc policy-driven.
- Phương án C: RCA topology-aware ở mức service nhưng không có deploy context. Ưu điểm: attribution tốt hơn so với count-only. Nhược điểm: vẫn dừng lại ở biên service và bỏ lỡ operational trigger. Bị loại khi dùng độc lập vì reproduction này đã lộ rõ khoảng trống đó.

## Hệ quả
- Tích cực 1: detection có thể liên kết độ lệch latency đột ngột với một policy push mới, qua đó rút ngắn thời gian chẩn đoán.
- Tích cực 2: RCA trở nên dễ hành động hơn vì người ứng trực thấy được cả service bị ảnh hưởng lẫn rollout trigger khả nghi.
- Đánh đổi 1: pipeline phải ingest dữ liệu deployment event và giữ metadata này ổn định.
- Đánh đổi 2: logic correlation phức tạp hơn, chi phí implementation và test tăng lên.
- Rủi ro 1: deployment metadata nhiễu nhiều có thể tạo liên kết nhầm. Giảm thiểu: chỉ dùng rollout context như một tín hiệu bổ trợ, không dùng làm quyết định duy nhất.
