# W2-D3 Submission

## Cau 1 - Latency endpoint

Khi chay endpoint tren dataset 20 alert, em do latency bang header `X-Response-Time-Ms` cua middleware. Ve mat kien truc, validate request va serialize response la fixed cost nho, trong khi correlate va RCA chiem phan lon hon cua request time. Trong pipeline hien tai, phase co xu huong scale gan linear khi input alert gap 10x la correlation session grouping, topology grouping, va graph ranking cua cluster lon nhat, vi chung deu duyet theo alert/service trong batch. Cac phan nhu load graph, load incident history, va khoi tao app la fixed cost vi duoc cache o module-level luc start service. Do dataset benchmark nho, em ky vong p50 va p99 khong cach nhau qua xa khi chay single-worker local.

## Cau 2 - Concurrency va fallback

Em chay service voi `--workers 1` de phu hop may yeu va de han che phuc tap shared state. Trong truong hop 4 request dong thoi, bottleneck dau tien em ky vong la CPU Python cho correlation + RCA graph, vi hien tai em khong goi LLM hay external API. Pipeline co fallback path ro rang o layer RCA: neu output validation fail thi service tra ve `graph-only-fallback` voi `class = other` va `recommended_actions = ["Investigate manually"]`, thay vi crash. Vi app khong phu thuoc network call ben ngoai, rui ro hang request thap hon, nhung trade-off la single worker se bi gioi han thong luong neu traffic tang.

## Cau 3 - /healthz va /readyz

`/healthz` cua em chi check process con song va luon tra `{"status":"ok"}` neu app dang chay. `/readyz` thi check 3 dieu kien thiet thuc hon: undirected graph phai co du node, directed graph phai load xong, incident history phai khong rong, va output D1 local phai ton tai hop le. Em tach 2 endpoint vi process “con song” khong dong nghia voi service “san sang nhan traffic that”. Neu sau nay co LLM provider ben ngoai bi down, em van uu tien de `/readyz` pass neu graph va history local van san sang, vi endpoint cua em hien tai khong phu thuoc bat buoc vao external API de tra ket qua co ich.
