# W3-D3 Submission - Thịnh

## Outage đã chọn

- ID: `3`
- Tên: `Cloudflare WAF regex`
- Lý do chọn: Em muốn chọn một failure mode vừa thực tế, vừa có public postmortem rõ ràng, lại có thể reproduce được trong một Docker lab tối giản. Failure mode này cũng rất phù hợp để stress stack AIOps vì adapter reproduction có thể phát hiện nhanh ở mức symptom, nhưng phần prevention và context để chẩn đoán operational trigger vẫn còn thiếu.
- Failure mode: `catastrophic_backtracking`

## 3 điều em học được từ outage này

1. Một lỗi policy được rollout toàn cục có thể tạo outage trên diện rộng nhanh hơn rất nhiều so với các lỗi hạ tầng thông thường, vì blast radius xảy ra gần như ngay lập tức.

2. RCA nhanh ở mức service là hữu ích, nhưng vẫn chưa đủ nếu payload RCA không liên kết được incident với change event đã kích hoạt sự cố.

3. Với hệ thống edge phụ thuộc vào regex, việc phòng ngừa bằng static safety check và staged rollout quan trọng hơn việc chỉ tối ưu detector sau khi người dùng đã bị ảnh hưởng.

## 1 điều pipeline của em vẫn sẽ miss nếu outage này xảy ra ngoài đời thực

- Pattern: Edge policy rollout không an toàn nhưng pipeline không có deploy-context correlation.
- Why miss: Adapter reproduction hiện tại có thể gọi đúng service sau khi latency tăng vọt, nhưng nó không tự biết một policy push mới là tác nhân operational đã kích hoạt sự cố.
- Mitigation idea: Ingest rollout event vào correlation và đưa deploy metadata vào payload RCA.

## 1 quyết định trong ADR mà em chưa hoàn toàn chắc

Em chưa chắc mức trọng số phù hợp của deployment-context evidence so với runtime metrics. Nếu đặt trọng số quá cao, những deploy event nhiễu hoặc không liên quan có thể làm RCA lệch sang sai change window.

## Kết luận cost model cho stack của em

- Monthly value: `6300.0`
- Monthly cost: `12000`
- Break-even avoided incidents/month: `5.72`
- ROI: `0.525`
- Payback: `1.90` tháng
- Verdict: `not_worth_it`
