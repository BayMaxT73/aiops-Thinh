# W1 Day-B Submission

## Du lieu su dung

Submission nay su dung du lieu Loghub that, da duoc copy vao `w1/day-b/data` de bai nop tu chua day du:

- du lieu chinh: `data/BGL_2k.log`
- du lieu de so sanh: `data/HDFS_2k.log`

Ly do chon BGL lam du lieu chinh:

- log raw cua BGL co nhan alert o cot dau tien
- dieu do cho phep tinh precision, recall va F1 tren du lieu that

Ly do dung HDFS de so sanh:

- HDFS van la dataset rat phu hop cho bai toan khai pha template
- ban subset Loghub duoc copy vao workspace nay co `HDFS_2k.log`, nhung khong co `anomaly_label.csv` di kem
- vi vay, neu dung HDFS de tinh precision/recall trong trang thai repo hien tai thi se thieu nhan
- do do notebook tinh metric anomaly tren BGL co nhan, dong thoi van dung HDFS that cho phan parse va so sanh hai dataset

Luu y ve wording cua de:

- de goi y HDFS vi HDFS duoc biet den la co label trong Loghub
- nhung trong ban clone/local subset hien tai, BGL la tap co nhan dung ngay duoc, con HDFS subset dang khong co file label di kem
- de giu cho bai nop chay duoc hoan toan trong workspace hien tai va khong tu tao label, metric anomaly duoc tinh tren BGL, con HDFS duoc dung cho parsing va cross-dataset comparison

## Phase 1: Parse log voi Drain3

### Tom tat du lieu chinh

- dataset: `BGL_2k.log`
- tong so dong log: `2,000`
- so template unique voi `sim_th=0.5`: `151`

### Top-10 templates

Da export ra `results/top_templates.csv`.

| template_id | count | template |
|---|---:|---|
| 73 | 180 | `- <*> 2005.07.09 <*> <*> <*> RAS KERNEL INFO generating <*>` |
| 85 | 121 | `- <*> <*> <*> <*> <*> RAS KERNEL INFO <*> floating point alignment exceptions` |
| 2 | 109 | `- <*> <*> <*> <*> <*> RAS KERNEL INFO <*> double-hummer alignment exceptions` |
| 3 | 92 | `- <*> <*> <*> <*> <*> RAS KERNEL INFO CE sym <*> at <*> mask <*>` |
| 77 | 87 | `- <*> 2005.07.13 <*> <*> <*> RAS KERNEL INFO generating <*>` |
| 138 | 71 | `- <*> 2005.12.01 <*> <*> <*> RAS KERNEL INFO <*> total interrupts ...` |
| 119 | 61 | `- <*> 2005.11.04 <*> <*> <*> RAS KERNEL INFO iar <*> dear <*>` |
| 14 | 60 | `KERNDTLB <*> 2005.06.11 R30-M0-N9-C:J16-U01 <*> ... data TLB error interrupt` |
| 118 | 59 | `- <*> 2005.11.03 <*> <*> <*> RAS KERNEL INFO iar <*> dear <*>` |
| 137 | 51 | `- <*> 2005.12.01 <*> <*> <*> RAS KERNEL INFO 0 microseconds spent ...` |

### Tune sim_th

Da luu vao `results/tuning_results.csv`.

| sim_th | so template | avg_cluster_size |
|---|---:|---:|
| 0.3 | 73 | 27.40 |
| 0.5 | 151 | 13.25 |
| 0.7 | 1459 | 1.37 |

Gia tri duoc chon: `0.5`

Ly do:

- `0.3` gom cum qua tay
- `0.7` lam vo cum thanh qua nhieu template nho
- `0.5` la diem can bang tot nhat giua grouping va interpretability

## Phase 2: Anomaly detection tren log

### Template count time series

- dataset: `BGL_2k.log`
- kich thuoc cua so: `30 minutes`
- chuoi baseline dung de detect anomaly: `unique template count per window`
- file plot: `results/template_count_timeseries.png`

Plot:

![Template Count Time Series](results/template_count_timeseries.png)

### Cach detect

- gom log theo cua so 30 phut
- tao time series tu so template unique trong moi cua so
- chay `3-sigma`
- chay `Isolation Forest`
- coi mot cua so la anomalous neu trong cua so do co bat ky BGL alert label nao xuat hien

### Ket qua

- so anomaly do `3-sigma` phat hien: `4`
- ket qua `Isolation Forest`: duoc ghi trong `assignment.ipynb`

Danh gia voi BGL alert labels:

- `3-sigma`: precision `0.500`, recall `0.035`, f1 `0.066`
- `Isolation Forest`: precision `0.167`, recall `0.035`, f1 `0.058`

Nhan xet:

- viec chuyen tu tong so log sang so template unique theo window lam tin hieu anomaly sat hon voi y de bai
- tuy vay, du lieu BGL that van kho doi voi cac detector don gian o muc window
- template diversity mang nhieu tin hieu hon raw volume, nhung van chua du de dat recall cao

### Spike va new template

- mot so template spike o cac window cu the, dac biet la cac nhom kernel va fatal event
- so template moi xuat hien trong 10% cuoi cua chuoi log: `15`

## Phase 3: Embedding va cross-signal

### Cum template bang TF-IDF

- vectorization: character n-grams `(2, 3)`
- nguong similarity de tao cum: `0.7`
- so cum tim duoc tren nguong nay: `4`

Chu de cac cum quan sat duoc:

1. cac ho kernel info lap lai
2. cac ho loi fatal o muc application hoac kernel
3. cac pattern lien quan toi hardware / interrupt
4. cac pattern generated-status lap lai

### Inject log la

Dong log da inject:

```text
GPUFAIL 1119999999 2005.06.20 R99-M9-N9-C:J99-U99 2005-06-20-23.59.59.999999 R99-M9-N9-C:J99-U99 RAS APP FATAL accelerator parity fault on memory controller
```

Ket qua:

- Drain3 tra ve change type: `cluster_created`
- he thong tao ra mot template moi thanh cong

## Phase 4: Mini Log Analyzer

### Script

File: `scripts/log_analyzer.py`

Cach chay:

```powershell
python scripts\log_analyzer.py data\BGL_2k.log
python scripts\log_analyzer.py data\HDFS_2k.log
```

Script in ra:

- tong so dong
- so template unique
- top-5 template voi count va percentage
- template spike trong 1 gio gan nhat
- new template trong 1 gio gan nhat

### So sanh hai dataset

Da luu vao `results/dataset_comparison.csv`.

| dataset | total_logs | unique_templates | avg_cluster_size |
|---|---:|---:|---:|
| BGL | 2000 | 151 | 13.25 |
| HDFS | 2000 | 21 | 95.24 |

Ly do BGL co nhieu template hon trong lan chay nay:

- BGL subset chua nhieu ho su kien kernel va error khac nhau
- HDFS subset lap lai nhieu hon nen Drain3 gom thanh it cluster hon va cluster to hon

## Reflection

- Drain3 parse tot tren ca BGL va HDFS, nhung rat nhay voi `sim_th`
- cac template `RAS APP FATAL`, `RAS KERNEL FATAL`, va cac template moi xuat hien mang nhieu insight nhat
- metric cho biet xu huong tong quat, con log cho biet su kien cu the; ket hop ca hai se tot hon cho phan root-cause analysis

## Files Included

- `assignment.ipynb`
- `results/top_templates.csv`
- `results/tuning_results.csv`
- `results/template_count_timeseries.png`
- `results/dataset_comparison.csv`
- `scripts/log_analyzer.py`
- `SUBMIT.md`
