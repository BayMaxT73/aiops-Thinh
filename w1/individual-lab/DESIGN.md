# Detection Approach - DESIGN.md

## Approach toi dung
Toi dung detector rule-based cho streaming data, gom 3 phan: baseline truot, suspicion counter, va cooldown.

## Tai sao chon approach nay
Generator chi tao 3 fault co pattern ro rang va lap lai theo logic co dinh. Rule-based detector phu hop hon ML vi:
- Khong can du lieu train.
- Giai thich duoc tai sao alert bi fire.
- Cai dat nhanh, nhe, va du PASS trong bai lab 3 gio.

## Cach hoat dong
Pipeline nhan tung POST tai `/ingest`, doc `metrics` va `logs`, sau do cap nhat detector:

1. Warm-up:
Bo qua detect trong vai tick dau de co baseline on dinh. Toi dung `warmup_samples = 8`.

2. Baseline truot:
Luu `12` sample gan nhat trong `deque` va tinh trung binh cho tung metric. Baseline nay dai dien cho trang thai binh thuong gan day.

3. Rule theo tung fault:
- `memory_leak`:
  Can memory utilization cao, memory usage vuot baseline, va `jvm_gc_pause_ms_avg` tang manh. Sau do xac nhan them bang CPU, latency, 5xx, hoac log `OutOfMemoryWarning` / `GC pause exceeded threshold`.
- `traffic_spike`:
  Can `http_requests_per_sec` tang dot bien, queue depth tang, latency tang, va `upstream_timeout_rate` van tuong doi thap. Dieu nay tach no khoi `dependency_timeout`.
- `dependency_timeout`:
  Dat trong tam vao `upstream_timeout_rate` vi day la metric tang som va manh nhat trong generator. Sau do xac nhan them bang 5xx, latency, retry traffic, hoac log `Circuit breaker OPEN`.

4. Suspicion counter:
Khong fire alert ngay khi gap 1 tick le. Moi fault phai dat dieu kien trong `2` tick lien tiep moi duoc ghi alert. Cach nay giam false positive do noise.

5. Cooldown:
Sau khi fire, cung mot `type` se bi khoa trong `6` tick de tranh spam `alerts.jsonl`.

## Parameters toi chon
- `baseline_window = 12`:
  Du dai de lam muot noise, nhung van phan ung nhanh voi bien dong moi.
- `warmup_samples = 8`:
  Giam nguy co baseline sai luc moi start pipeline.
- `suspicion_threshold = 2`:
  Can bang giua toc do detect va false alert.
- `cooldown_ticks = 6`:
  Han che alert lap lai cho cung mot su co.

Threshold duoc chon tu signature thuc te trong `stream_generator.py`:
- `memory_leak` tang dan memory + GC + CPU, ve sau moi day latency va 5xx.
- `traffic_spike` day RPS, queue, latency len rat nhanh.
- `dependency_timeout` lam `upstream_timeout_rate` tang truoc va ro nhat.

## Cai thien neu co them thoi gian
- Them rolling median / MAD thay vi mean de baseline robust hon.
- Them score-based arbitration khi 2 fault cung co dau hieu giao nhau.
- Luu them state theo xu huong (slope) de detect `memory_leak` som hon nua.
- Viet script replay payload de test ca 3 fault co he thong.
