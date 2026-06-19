# AIOps Mini-Platform Spec - Thinh

## 1. Tong quan nen tang
Nen tang mini nay giam sat mot stack web nho gom frontend, API va cac dich vu phia sau; sau do thuc hien phat hien bat thuong, correlation alert va RCA o muc service. Pham vi cua bai gom theo doi SLO, validation bang chaos, reproduction outage va bo tai lieu operational cua tuan 3. Nen tang khong nham muc tieu tu dong remediaton cap production.

## 2. Dinh nghia SLO (tu W3-D1)
Nen tang theo doi 3 service chinh duoc dinh nghia trong `../d1/slo_spec.yaml`.

- `api`: SLI availability dua tren cac HTTP outcome thanh cong va nhanh, SLO `99.9%`, error budget thang `8,887` su kien loi hoac khoang `43` phut.
- `db`: SLI thanh cong va do tre truy van, SLO `99.95%`, error budget thang `369` su kien loi hoac khoang `22` phut.
- `frontend`: SLI availability cua page-load, SLO `99.0%`, error budget thang `22,217` su kien loi hoac khoang `432` phut.
- Burn-rate alert tiers: tier 1 `14.4x` tren cap `5m/1h`, tier 2 `6x` tren cap `30m/6h`, tier 3 `1x` tren cap `6h/3d` theo `../d1/burn_rate_alerts.yaml`.

## 3. Stack Detection + Correlation + RCA (tu W1+W2)
Core platform cua em van ke thua cac artifact W1/W2/W3-D2, nhung reproduction D3 nay su dung mot adapter local toi gian trong `pipeline/mock_pipeline_api.py` de giu failure mode determinist va de quan sat duoc signal can thiet.

- Detector: threshold latency detector doc `edge_last_latency_ms` tu reproduction metrics endpoint va phat alert JSON co cac truong `fire_ts`, `alertname`, `service`, `severity`.
- Correlator: adapter D3 gom cac alert trong cua so `60s` theo service qua endpoint `/correlate`, de mot fault inject tren `regex-edge` tao thanh 1 incident group duy nhat.
- RCA: adapter D3 tra ve RCA o muc service qua `/rca` voi schema `root_cause_service`, `confidence`, `failure_mode`, `reason`. Topology-aware RCA van thuoc core stack da validate o W3-D2, nhung khong phai co che chinh dang duoc stress trong repro edge-policy nay.

Tham chieu ADR: `ADR.md` mo rong stack dich den bang cach bo sung correlation dua tren rollout metadata cho edge policy, vi reproduction o D3 cho thay RCA chi dua tren service van chua du trong outage do rollout gay ra.

## 4. Kiem chung do tin cay (tu W3-D2)
Bo D2 chaos suite da chay `10` experiment tren Docker stack va cho bang ket qua sau:

- Detected: `10/10`
- RCA correct: `10/10`
- Precision: `1.00`
- Recall: `1.00`
- False alarms: `0`
- MTTD p50/p95: `1s / 1s`
- Chaos run cadence: `weekly` cho stack chinh va bat buoc chay lai truoc khi doi detector/RCA logic.
- Detected/total ratio target: `>= 0.90` tren full suite; ket qua hien tai dat `1.00`.
- Steady-state signal: `both` — synthetic probe cho user path va internal metric cho latency / saturation.

Top gap con lai sau khi ghep D2 va D3:
- Pipeline lab van phu thuoc nhieu vao trieu chung phan ung, chua ngan duoc edge-rule deploy khong an toan.
- Split-brain va monitoring-dependency-loop chua duoc dai dien manh nhu cac failure mode don service.
- Payload RCA can change-event context tot hon de giai thich operational trigger, khong chi ten service bi loi.

## 5. Mo hinh van hanh (tu W3-D3)
Outage duoc reproduction la failure mode regex cua Cloudflare ngay 2019-07-02, duoc trien khai bang Docker trong `reproduction/` va duoc tai lieu hoa trong `postmortem.md`. Bai hoc chinh la RCA nhanh van chua du neu detector chi fire sau khi nguoi dung da cam nhan anh huong; voi he thong edge policy, detection can biet den context cua rollout. `ADR.md` ghi lai quyet dinh bo sung rollout metadata vao detection va RCA.

- Postmortem template: `postmortem.md`, duoc dien theo khung trong `templates/postmortem_template.md`.
- On-call rotation: mo hinh `primary/secondary` theo tuan; primary nhan page va ack, secondary duoc keu vao neu mitigation vuot qua runbook co san.
- ADR repository: `ADR.md` cho decision hien tai; co the mo rong thanh mot thu muc ADR neu stack co them thay doi kien truc.

## 6. Mo hinh chi phi (tu W3-D3)
`cost_model.py` implement dung ham break-even theo de bai.

Voi kich ban stack nho kieu internal SaaS hien tai:
- Monthly value: `6300.0`
- Monthly cost: `12000`
- Break-even avoided incidents/month: `5.72` neu giu nguyen gia dinh `0.75h/incident`, `35%` MTTR reduction va `8000 USD/h` downtime cost.
- ROI: `0.525`
- Payback: `1.90` thang
- Verdict: `not_worth_it`

Dien giai: voi mot stack quy mo vua va tan suat incident khong cao, dau tu vao observability tot va ky luat SRE van cho leverage cao hon viec day nang chi phi AIOps.

## 7. Rui ro con mo
- Cao: chua co static ReDoS validation truoc rollout regex rule. Giam thieu: bat buoc pre-deploy scanning va canary promotion.
- Cao: RCA thieu deployment-event context. Giam thieu: ingest CI/CD va policy-push metadata vao pipeline.
- Trung binh: split-brain chua duoc reproduction trong implementation D3 hien tai. Giam thieu: them template GitHub 2018 lam validation track thu hai.
- Trung binh: monitoring dependency loop chua duoc cover trong stack hien tai. Giam thieu: them bai test kieu Roblox voi service-discovery dependency.
- Trung binh: chat luong detector phu thuoc vao threshold hand-tuned. Giam thieu: ket hop threshold voi temporal baseline va drift features.
