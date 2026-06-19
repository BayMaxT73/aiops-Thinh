# Postmortem: Sự cố Regex trên Edge theo mẫu Cloudflare (tái hiện ngày 2026-06-19)

**Trạng thái:** hoàn tất  
**Ngày:** 2026-06-19  
**Tác giả:** Thinh  
**Mức độ:** SEV2  
**Thời lượng:** 31 giây (2026-06-19 10:26:34 UTC -> 2026-06-19 10:27:04 UTC)

## Tóm tắt
Một regex kiểu WAF có hiện tượng catastrophic backtracking được kích hoạt trên đường đi request ở edge và ngay lập tức đẩy độ trễ xử lý lên vượt ngưỡng timeout nhìn thấy từ phía người dùng. Dịch vụ edge trong môi trường mô phỏng trở nên chậm trước khi detector phát cảnh báo, qua đó tái hiện đúng failure mode của sự cố Cloudflare ngày 2019-07-02 trong một Docker lab tối giản. Hệ thống phục hồi sau khi rule lỗi bị tắt.

## Ảnh hưởng
- Người dùng bị ảnh hưởng: tất cả request đi qua dịch vụ edge được mô phỏng trong cửa sổ inject.
- Services affected: `regex-edge`, synthetic client path đi qua edge filter.
- Tác động doanh thu: không đo trong môi trường lab.
- Error budget SLO bị tiêu hao: xấp xỉ một đợt timeout nhìn thấy từ phía người dùng trên budget availability của frontend.
- Truyền thông bên ngoài: không có trong môi trường lab.

## Timeline (UTC)
| Thời gian | Sự kiện |
|-----------|---------|
| 10:26:34 | Fault injection bật rule regex theo kiểu Cloudflare trên đường đi request ở edge. |
| 10:26:34 | Dịch vụ edge bắt đầu đánh giá regex gây backtracking dưới luồng traffic đang chạy. |
| 10:26:34 | Request synthetic đầu tiên vượt ngưỡng timeout với độ trễ 2600 ms. |
| 10:26:35 | Pipeline AIOps phát cảnh báo `HighLatencyRegex` cho `regex-edge`. |
| 10:26:35 | Pipeline trả kết quả RCA chỉ ra `regex-edge`. |
| 10:27:02 | On-call chính xác nhận đã nhận page. |
| 10:27:03 | Bộ lọc request được xác nhận là nguồn gây khuếch đại CPU. |
| 10:27:04 | Biện pháp giảm thiểu được áp dụng: tắt rule lỗi. |
| 10:27:04 | Hệ thống phục hồi hoàn toàn và độ trễ trở về mức nền. |

## Nguyên nhân gốc
Một regex có catastrophic backtracking được phép đi vào đường đi request đang phục vụ traffic thật, khiến một mẫu input đối nghịch có thể tiêu tốn CPU quá mức và làm nghẽn xử lý request.

## Yếu tố góp phần
- Pipeline reproduction không có cơ chế kiểm tra độ an toàn của regex trước khi deploy, nên việc phòng ngừa phụ thuộc hoàn toàn vào runtime detection.
- Detector dựa trên triệu chứng độ trễ sau khi ảnh hưởng đã xảy ra, thay vì dựa vào tín hiệu liên quan đến thay đổi khi rollout.
- RCA đã gọi đúng tên `regex-edge`, nhưng thiếu thông tin về phạm vi rollout và không tách bạch rõ một policy push lỗi với một sự cố saturation tổng quát ở edge.

## Phát hiện
- Hệ thống được phát hiện như thế nào? Pipeline AIOps phát hiện sự cố thông qua cảnh báo latency mức nghiêm trọng trên dịch vụ edge.
- Có thể phát hiện sớm hơn không? Có. Một bước lint regex hoặc ReDoS screening trước deploy có thể chặn rule này trước khi kích hoạt.
- MTTD: khoảng 1 giây từ timeout đầu tiên nhìn thấy từ phía người dùng đến lúc có cảnh báo.
- Các gap của pipeline quan sát được trong lúc reproduction:
  - Gap 1: detection có tính phản ứng, phải đợi đến khi latency ảnh hưởng đến người dùng rồi mới cảnh báo.
  - Gap 2: payload RCA thiếu change-event context, nên mới giải thích được dịch vụ lỗi, chưa giải thích được cơ chế rollout gây ra sự cố.

## Ứng phó
- First responder action: on-call chính xác nhận page, đối chiếu spike latency với request path ở edge rồi xác nhận rule regex mới là nghi phạm chính.
- Time to mitigate: khoảng `30` giây từ lúc inject đến lúc tắt rule lỗi.
- Time to fully resolve: khoảng `30` giây từ lúc inject đến khi latency trở về mức nền.
- Điều làm tốt: detector phát nhanh, RCA gọi đúng service, và rollback rất đơn giản.
- Điều chưa tốt: detector hiện tại vẫn là symptom-based, nên người dùng đã bị ảnh hưởng trước khi page được gửi.
- Điều may mắn: biện pháp giảm thiểu chỉ cần tắt rule lỗi, và lab stack không có phần phục hồi dữ liệu hay multi-region consistency phức tạp.

## Hành động cần làm
| Hạng mục | Phụ trách | Loại | Hạn | Ưu tiên |
|----------|-----------|------|-----|---------|
| Bổ sung ReDoS screening tĩnh cho regex rule trước deploy | Platform Eng | preventive | 2026-06-26 | P0 |
| Gắn thêm metadata về deployment vào alert và payload RCA | Detection Eng | detective | 2026-06-28 | P1 |
| Thêm guardrail rollout theo từng giai đoạn cho edge policy | SRE | preventive | 2026-07-03 | P1 |
| Thêm detector cho sự tăng chi phí đánh giá regex trước khi timeout lan rộng | Detection Eng | detective | 2026-07-05 | P2 |
