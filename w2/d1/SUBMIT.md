# W2-D1 Submission

## Tong quan

Bai nop nay cai dat mot alert correlator nho co tinh den topology cho bai tap Week 2 Day 1. Notebook doc `alerts_sample.jsonl` va `services.json`, gom alert theo session window dua tren do gan nhau theo thoi gian, sau do tach tiep theo khoang cach giua cac service tren graph dependency. Muc tieu cua bai khong phai tim root cause. Muc tieu la giam noise de nguoi on-call nhin vao vai cluster co y nghia thay vi mot danh sach alert bi flood.

Dataset dang dung trong submission nay den tu file `alerts_sample.jsonl` va topology `services.json` cua scenario GeekShop. Em giu logic cot loi cua bai, nhung them hai heuristic nho de output hop ly hon voi du lieu cu the. Thu nhat, cac edge `kafka` duoc bo khoi synchronous correlation vi notification la async path, khong nen mac dinh merge vao blast radius cua checkout hoac payment. Thu hai, neu `labels.note` chua cac tu nhu `unrelated`, `independent`, hoac `noise` thi alert do duoc tach rieng thay vi merge chi vi no xuat hien cung khung gio.

## Lua chon thiet ke

Em chon `gap_sec = 120` vi day la trade-off mac dinh hop ly nhat theo bai hoc va phu hop voi kieu incident dang burst trong production. Neu chon nho hon, vi du `30` giay, payment incident trong sample se bi cat thanh nhieu cluster nho hon vi giua cac alert co nhung khoang nghi ngan nhung van thuoc cung su co. Neu chon lon hon, vi du `600` giay, he thong de merge nham hai incident khong lien quan chi vi chung xay ra trong cung mot khoang thoi gian rong.

Em chon `max_hop = 2` vi no bat duoc ban kinh cascade pho bien trong microservice graph ma khong can hai service phai lien ket truc tiep 1 hop. Trong topology nay, gia tri do du de noi `payment-svc`, `checkout-svc`, `edge-lb`, va `cart-svc` vao cung nhom su co chinh. Tuy nhien, neu chi dung `max_hop = 2` thi graph quanh edge tier van de bi merge qua tay, nen hai heuristic o tren rat quan trong de giu cho cluster con y nghia van hanh. Day cung la design trade-off chinh: output sach hon nhung phai chap nhan them mot chut logic domain-specific.

## Alert bi miss / orphan

Alert `a-0016` duoc co y xem la mot miss so voi payment cluster chinh va tro thanh cluster size `1`. Alert nay thuoc `search-svc`, va trong dataset no duoc ghi chu ro la `noise - independent slow query`. Neu khong co thong tin nay, mot phuong phap qua don gian chi dua vao time-window hoac chi dua vao topology rat de merge no vao incident lon hon vi no xuat hien trong cung burst va service van nam kha gan edge tier. Giu no tach rieng phan anh dung hon y nghia cua scenario.

## Neu scale len 10,000 alert

Neu co `10,000` alert thay vi `20`, diem cham nhat cua cai dat hien tai se nam o buoc topology grouping. Code dang so sanh cac cap service trong tung session, roi chay bounded breadth-first search de kiem tra duong di co nho hon hoac bang `max_hop` hay khong. Cach nay on voi session nho, nhung se tang chi phi rat nhanh neu mot burst lon co nhieu service khac nhau. O moi truong production, nen precompute neighborhood den muc `max_hop`, toi uu adjacency structure theo type edge, index alert theo service, va co TTL eviction neu chay theo kieu streaming lau dai.

## EOD Checkpoint

Fingerprint khong nen include `timestamp` hay `value` vi hai field nay thay doi gan nhu moi lan alert fire. Neu dua chung vao fingerprint thi ngay ca alert lap lai cung service va cung metric van tao ra fingerprint moi, lam cho dedup gan nhu vo dung. Vi du hai alert `payment-svc latency_p99_ms crit` tai `09:42:26Z` va `09:42:35Z` se bi coi la hai loai khac nhau thay vi hai lan phat cua cung mot alert type.

`Duplicate` alert va `correlated` alert la hai khai niem khac nhau. Duplicate la nhung lan lap lai cua cung mot fingerprint, vi du cac lan xuat hien lap lai cua `payment-svc|latency_p99_ms|crit` trong payment burst. Correlated la nhieu alert khac nhau nhung van thuoc cung mot incident, vi du `checkout-svc downstream_payment_error_rate`, `edge-lb upstream_5xx_rate`, va `cart-svc latency_p99_ms` cung xuat hien trong mot session va trong mot synchronous dependency neighborhood.

Neu `gap_sec = 30` thi payment incident nhieu kha nang se bi vo thanh nhieu cluster hon vi co vai khoang cach alert lon hon 30 giay. Neu `gap_sec = 600` thi he thong tolerant hon voi pause dai, nhung cung de merge nham viec khong lien quan, nhat la khi hai service doc lap cung alert trong cung cua so 10 phut.

Correlator khong nen merge `recommender-svc` vao payment cluster chinh du alert cua no trung thoi gian. Trung thoi gian mot minh la chua du. Trong dataset nay, `labels.note` ghi ro `unrelated - concurrent batch retrain`, nen cai dat giu no thanh singleton cluster rieng. Day la mot vi du rat tot cho thay time-window cong topology van chi la proxy, chua phai chan ly tuyet doi ve incident relatedness.

Han che lon nhat cua topology grouping la graph distance chi la xap xi cho quan he nhan qua. Hai service co the gan nhau tren graph nhung alert vi ly do khong lien quan, hoac xa nhau tren graph nhung van chung mot infrastructure issue nhu shared database, queue, hay cloud dependency ma service graph chua model hoa. Mot huong cai tien la bo sung infrastructure node, edge weight, va ket hop them metric similarity hoac semantic similarity thay vi dua hoan toan vao hop count.

## Cac file nop

- `assignment.ipynb`
- `dataset/alerts_sample.jsonl`
- `dataset/services.json`
- `results/cluster_summary.json`
- `SUBMIT.md`
