# ASR B0/B1/B2

| Run | Model | Thiết bị | WER | CER | WER thô | Entity | Oracle entity | RTF | Giây ASR/phút audio (p50/p95) |
| :---- | :---- | :---- | ----: | ----: | ----: | ----: | ----: | ----: | ----: |
| B0 | whisper-turbo | cpu/int8 | 38.3 | 31.6 | 38.3 | 63.3 | 84.2 | 1.4618584008094495 | 87.7 (82.3/140.2) |
| B1 | whisper-turbo | cpu/int8 | 19.3 | 14.9 | 38.3 | 64.7 | 84.2 | 1.4619438654336678 | 87.7 (82.3/140.2) |
| B2 | whisper-turbo | cpu/int8 | 14.1 | 10.0 | 36.3 | 74.8 | 84.2 | 1.5350248802563518 | 92.1 (84.2/139.1) |

&nbsp;

| Run | T01 WER (entity) | T02 WER (entity) | T03 WER (entity) | T04 WER (entity) | T05 WER (entity) | T06 WER (entity) | T07 WER (entity) | T08 WER (entity) | T09 WER (entity) | T10 WER (entity) | T11 WER (entity) | T12 WER (entity) | T13 WER (entity) | T14 WER (entity) | T15 WER (entity) | T16 WER (entity) | T17 WER (entity) | T18 WER (entity) | T19 WER (entity) | T20 WER (entity) | T21 WER (entity) | T22 WER (entity) |
| :---- | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: |
| B0 | 27.8 (5/6) | 25.3 (7/8) | 32.5 (6/7) | 36.3 (4/5) | 34.9 (5/6) | 33.2 (4/7) | 36.3 (6/10) | 29.2 (6/7) | 33.0 (3/7) | 42.6 (1/6) | 37.9 (3/4) | 36.1 (3/4) | 62.8 (4/8) | 52.2 (4/6) | 26.1 (5/6) | 36.1 (4/5) | 42.7 (2/6) | 35.0 (2/5) | 47.9 (2/7) | 34.8 (6/7) | 39.9 (5/7) | 61.9 (1/5) |
| B1 | 8.0 (5/6) | 9.4 (7/8) | 7.0 (6/7) | 12.6 (4/5) | 8.5 (5/6) | 14.5 (4/7) | 20.1 (6/10) | 11.4 (6/7) | 17.0 (3/7) | 30.6 (1/6) | 20.9 (3/4) | 21.4 (3/4) | 55.0 (4/8) | 17.3 (4/6) | 12.3 (5/6) | 19.1 (5/5) | 18.6 (2/6) | 10.9 (3/5) | 35.9 (2/7) | 18.2 (6/7) | 13.6 (5/7) | 46.0 (1/5) |
| B2 | 8.0 (6/6) | 7.6 (8/8) | 6.6 (6/7) | 10.7 (5/5) | 8.5 (5/6) | 12.4 (5/7) | 16.2 (7/10) | 9.6 (6/7) | 9.2 (5/7) | 17.0 (2/6) | 6.3 (3/4) | 20.6 (3/4) | 17.8 (6/8) | 12.4 (5/6) | 9.4 (6/6) | 18.6 (5/5) | 10.6 (4/6) | 10.4 (3/5) | 25.5 (2/7) | 16.0 (6/7) | 13.1 (5/7) | 46.0 (1/5) |

&nbsp;

| Comparison (right \- left, pp) | WER | CER | Entity |
| :---- | ----: | ----: | ----: |
| B0-\>B1 | \-19.0 | \-16.7 | 1.4 |
| B1-\>B2 | \-5.2 | \-4.9 | 10.1 |
| B0-\>B2 | \-24.2 | \-21.6 | 11.5 |

Negative WER/CER and positive Entity deltas are improvements.

- B0 includes VAD/cleanup; its WER includes representation mismatch.  
- B0/B1 share no-hotword decode; B2 includes hotword echo filtering.  
- Subsets are re-scored by BTC; no averaging of per-dataset percentages.  
- Split labels do not prove unseen holdout. No memory metrics measured.

| Group | Profile | Files | Entities | WER | CER | Entity |
| :---- | :---- | ----: | ----: | ----: | ----: | ----: |
| all | B0 | 22 | 139 | 38.3 | 31.6 | 63.3 |
| all | B1 | 22 | 139 | 19.3 | 14.9 | 64.7 |
| all | B2 | 22 | 139 | 14.1 | 10.0 | 74.8 |
| dataset:team22-edge-clone | B0 | 11 | 70 | 42.4 | 36.1 | 60.0 |
| dataset:team22-edge-clone | B1 | 11 | 70 | 23.1 | 19.0 | 62.9 |
| dataset:team22-edge-clone | B2 | 11 | 70 | 17.0 | 13.2 | 72.9 |
| dataset:team22-edge-synth | B0 | 11 | 69 | 34.6 | 27.7 | 66.7 |
| dataset:team22-edge-synth | B1 | 11 | 69 | 15.8 | 11.2 | 66.7 |
| dataset:team22-edge-synth | B2 | 11 | 69 | 11.5 | 7.1 | 76.8 |
| split:dev | B0 | 2 | 14 | 26.6 | 20.0 | 85.7 |
| split:dev | B1 | 2 | 14 | 8.7 | 5.2 | 85.7 |
| split:dev | B2 | 2 | 14 | 7.8 | 4.9 | 100.0 |
| split:holdout | B0 | 20 | 125 | 39.3 | 32.7 | 60.8 |
| split:holdout | B1 | 20 | 125 | 20.2 | 15.7 | 62.4 |
| split:holdout | B2 | 20 | 125 | 14.6 | 10.4 | 72.0 |
| noisy:False | B0 | 15 | 97 | 40.9 | 33.6 | 61.9 |
| noisy:False | B1 | 15 | 97 | 21.5 | 17.0 | 62.9 |
| noisy:False | B2 | 15 | 97 | 16.1 | 11.7 | 71.1 |
| noisy:True | B0 | 7 | 42 | 32.6 | 27.3 | 66.7 |
| noisy:True | B1 | 7 | 42 | 14.1 | 9.9 | 69.0 |
| noisy:True | B2 | 7 | 42 | 9.4 | 5.9 | 83.3 |

&nbsp;
---

# Bổ sung: nhóm 1 trên GPU (RTX 3050 4 GB, cuda/float16)

Cùng 22 file và 139 entity của team22-edge-synth và team22-edge-clone; VAD, lexicon và hotword giữ nguyên. whisper-turbo được chạy lại trên GPU để có mốc so sánh cùng máy.

## Tóm tắt B2

| Model | Thiết bị | WER | CER | Entity | Oracle | Giây ASR/phút audio | VRAM đỉnh (MiB) |
| :---- | :---- | ----: | ----: | ----: | ----: | ----: | ----: |
| whisper-turbo | cpu/int8 (report trên) | 14.1 | 10.0 | 74.8 | 84.2 | 92.1 | – |
| whisper-turbo | cuda/float16 | 13.6 | 9.5 | 74.1 | 84.2 | 7.2 | 3527 |
| whisper-large-v3 | cuda/float16 | 13.6 | 10.4 | 74.1 | 84.2 | 118.7 | 3939 |
| phowhisper-large | cuda/float16 | 14.3 | 9.8 | 65.5 | 84.2 | 86.9 | 3920 |
| phowhisper-medium | cuda/float16 | 17.4 | 11.3 | 54.7 | 84.2 | 11.6 | 3214 |

## Nhận xét

- **Khuyến nghị: giữ whisper-turbo + B2.** Model này có Entity cao nhất (bằng large-v3), CER thấp nhất và nhanh hơn large-v3 khoảng 16 lần.
- **PhoWhisper:**
  - WER thô ở B0 thấp hơn (khoảng 20% so với 35–38% của Whisper).
  - Entity B0 chỉ đạt 14–17%: số, mã SKU và tên riêng được viết theo dạng mà bộ trích entity hiện tại không nhận ra.
  - Muốn dùng thì cần lexicon/ITN riêng.
- **Giới hạn của phép đo:**
  - Hai model large dùng gần hết 4 GB VRAM, nhiều khả năng bị tràn sang bộ nhớ chia sẻ, nên tốc độ đo được có thể chậm hơn thực tế.
  - Với 139 entity, chênh lệch dưới khoảng 3 điểm chưa có ý nghĩa thống kê.

## Chi tiết: whisper-turbo (cuda/float16)


| Run | Model | Thiết bị | WER | CER | WER thô | Entity | Oracle entity | RTF | Giây ASR/phút audio (p50/p95) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| B0 | whisper-turbo | cuda/float16 | 38.5 | 31.9 | 38.5 | 62.6 | 84.2 | 0.12056179343991492 | 7.2 (6.4/13.8) |
| B1 | whisper-turbo | cuda/float16 | 19.7 | 15.5 | 38.5 | 64.0 | 84.2 | 0.12063069631610807 | 7.2 (6.4/13.8) |
| B2 | whisper-turbo | cuda/float16 | 13.6 | 9.5 | 35.8 | 74.1 | 84.2 | 0.12050207299950129 | 7.2 (6.4/12.3) |

| Run | T01 WER (entity) | T02 WER (entity) | T03 WER (entity) | T04 WER (entity) | T05 WER (entity) | T06 WER (entity) | T07 WER (entity) | T08 WER (entity) | T09 WER (entity) | T10 WER (entity) | T11 WER (entity) | T12 WER (entity) | T13 WER (entity) | T14 WER (entity) | T15 WER (entity) | T16 WER (entity) | T17 WER (entity) | T18 WER (entity) | T19 WER (entity) | T20 WER (entity) | T21 WER (entity) | T22 WER (entity) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 27.3 (5/6) | 24.7 (7/8) | 32.5 (6/7) | 32.6 (4/5) | 34.4 (5/6) | 31.6 (4/7) | 36.8 (7/10) | 30.1 (6/7) | 29.1 (4/7) | 41.7 (1/6) | 37.4 (3/4) | 36.1 (3/4) | 62.8 (4/8) | 52.2 (4/6) | 26.6 (5/6) | 37.2 (4/5) | 42.2 (2/6) | 36.6 (2/5) | 47.4 (2/7) | 34.3 (6/7) | 53.5 (2/7) | 61.9 (1/5) |
| B1 | 7.5 (5/6) | 8.8 (7/8) | 7.0 (6/7) | 10.2 (4/5) | 8.5 (5/6) | 13.0 (4/7) | 18.1 (7/10) | 11.4 (6/7) | 11.2 (4/7) | 29.8 (1/6) | 21.4 (3/4) | 21.0 (3/4) | 55.0 (4/8) | 17.3 (4/6) | 11.8 (5/6) | 20.2 (5/5) | 18.1 (2/6) | 12.0 (3/5) | 38.0 (2/7) | 17.7 (6/7) | 34.8 (2/7) | 46.0 (1/5) |
| B2 | 7.0 (5/6) | 8.2 (8/8) | 7.0 (6/7) | 8.4 (5/5) | 8.0 (5/6) | 11.9 (5/7) | 15.7 (7/10) | 8.2 (6/7) | 8.7 (5/7) | 17.0 (2/6) | 7.8 (3/4) | 20.6 (3/4) | 17.8 (6/8) | 12.4 (5/6) | 10.3 (6/6) | 13.1 (5/5) | 9.0 (4/6) | 13.1 (3/5) | 24.5 (2/7) | 14.9 (6/7) | 12.1 (5/7) | 45.0 (1/5) |

| Comparison (right - left, pp) | WER | CER | Entity |
|---|---:|---:|---:|
| B0->B1 | -18.8 | -16.4 | 1.4 |
| B1->B2 | -6.1 | -6.0 | 10.1 |
| B0->B2 | -24.9 | -22.4 | 11.5 |

Negative WER/CER and positive Entity deltas are improvements.

- B0 includes VAD/cleanup; its WER includes representation mismatch.
- B0/B1 share no-hotword decode; B2 includes hotword echo filtering.
- Subsets are re-scored by BTC; no averaging of per-dataset percentages.
- Split labels do not prove unseen holdout. No memory metrics measured.

| Group | Profile | Files | Entities | WER | CER | Entity |
|---|---|---:|---:|---:|---:|---:|
| all | B0 | 22 | 139 | 38.5 | 31.9 | 62.6 |
| all | B1 | 22 | 139 | 19.7 | 15.5 | 64.0 |
| all | B2 | 22 | 139 | 13.6 | 9.5 | 74.1 |
| dataset:team22-edge-clone | B0 | 11 | 70 | 43.8 | 37.7 | 55.7 |
| dataset:team22-edge-clone | B1 | 11 | 70 | 25.3 | 21.6 | 58.6 |
| dataset:team22-edge-clone | B2 | 11 | 70 | 16.3 | 12.4 | 72.9 |
| dataset:team22-edge-synth | B0 | 11 | 69 | 33.8 | 26.9 | 69.6 |
| dataset:team22-edge-synth | B1 | 11 | 69 | 14.6 | 10.1 | 69.6 |
| dataset:team22-edge-synth | B2 | 11 | 69 | 11.1 | 6.8 | 75.4 |
| split:dev | B0 | 2 | 14 | 26.1 | 19.7 | 85.7 |
| split:dev | B1 | 2 | 14 | 8.1 | 4.9 | 85.7 |
| split:dev | B2 | 2 | 14 | 7.6 | 4.5 | 92.9 |
| split:holdout | B0 | 20 | 125 | 39.6 | 33.0 | 60.0 |
| split:holdout | B1 | 20 | 125 | 20.7 | 16.4 | 61.6 |
| split:holdout | B2 | 20 | 125 | 14.1 | 9.9 | 72.0 |
| noisy:False | B0 | 15 | 97 | 41.7 | 34.6 | 59.8 |
| noisy:False | B1 | 15 | 97 | 22.8 | 18.5 | 60.8 |
| noisy:False | B2 | 15 | 97 | 15.3 | 10.9 | 70.1 |
| noisy:True | B0 | 7 | 42 | 31.3 | 26.0 | 69.0 |
| noisy:True | B1 | 7 | 42 | 12.7 | 8.6 | 71.4 |
| noisy:True | B2 | 7 | 42 | 9.7 | 6.2 | 83.3 |

## Chi tiết: whisper-large-v3 (cuda/float16)


| Run | Model | Thiết bị | WER | CER | WER thô | Entity | Oracle entity | RTF | Giây ASR/phút audio (p50/p95) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| B0 | whisper-large-v3 | cuda/float16 | 35.1 | 28.9 | 35.1 | 66.2 | 84.2 | 1.517403727631419 | 91.0 (85.2/137.9) |
| B1 | whisper-large-v3 | cuda/float16 | 14.5 | 10.6 | 35.1 | 68.3 | 84.2 | 1.5174914314769232 | 91.0 (85.3/137.9) |
| B2 | whisper-large-v3 | cuda/float16 | 13.6 | 10.4 | 35.5 | 74.1 | 84.2 | 1.9783067756286103 | 118.7 (113.7/159.5) |

| Run | T01 WER (entity) | T02 WER (entity) | T03 WER (entity) | T04 WER (entity) | T05 WER (entity) | T06 WER (entity) | T07 WER (entity) | T08 WER (entity) | T09 WER (entity) | T10 WER (entity) | T11 WER (entity) | T12 WER (entity) | T13 WER (entity) | T14 WER (entity) | T15 WER (entity) | T16 WER (entity) | T17 WER (entity) | T18 WER (entity) | T19 WER (entity) | T20 WER (entity) | T21 WER (entity) | T22 WER (entity) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 27.8 (5/6) | 24.7 (7/8) | 32.1 (6/7) | 32.1 (4/5) | 35.8 (4/6) | 32.1 (4/7) | 34.3 (5/10) | 28.3 (6/7) | 30.1 (4/7) | 36.2 (1/6) | 26.2 (3/4) | 37.0 (3/4) | 32.8 (7/8) | 49.1 (4/6) | 27.1 (6/6) | 35.5 (3/5) | 42.2 (4/6) | 33.9 (2/5) | 43.2 (2/7) | 34.8 (6/7) | 40.9 (5/7) | 53.4 (1/5) |
| B1 | 7.0 (5/6) | 8.8 (7/8) | 6.6 (6/7) | 8.8 (5/5) | 10.8 (4/6) | 12.4 (4/7) | 15.2 (5/10) | 8.2 (6/7) | 13.1 (4/7) | 17.0 (1/6) | 3.4 (3/4) | 22.3 (3/4) | 16.7 (7/8) | 16.8 (4/6) | 7.4 (6/6) | 19.1 (4/5) | 16.1 (4/6) | 9.3 (3/5) | 31.2 (2/7) | 18.2 (6/7) | 14.6 (5/7) | 37.6 (1/5) |
| B2 | 4.3 (6/6) | 9.4 (7/8) | 4.1 (7/7) | 6.5 (5/5) | 7.1 (4/6) | 9.3 (5/7) | 10.8 (7/10) | 8.7 (6/7) | 10.2 (5/7) | 26.0 (2/6) | 3.4 (3/4) | 21.4 (4/4) | 15.6 (7/8) | 10.2 (5/6) | 10.3 (6/6) | 16.4 (4/5) | 10.6 (5/6) | 7.7 (3/5) | 25.0 (2/7) | 17.7 (6/7) | 25.3 (3/7) | 41.8 (1/5) |

| Comparison (right - left, pp) | WER | CER | Entity |
|---|---:|---:|---:|
| B0->B1 | -20.6 | -18.3 | 2.1 |
| B1->B2 | -0.9 | -0.2 | 5.8 |
| B0->B2 | -21.5 | -18.5 | 7.9 |

Negative WER/CER and positive Entity deltas are improvements.

- B0 includes VAD/cleanup; its WER includes representation mismatch.
- B0/B1 share no-hotword decode; B2 includes hotword echo filtering.
- Subsets are re-scored by BTC; no averaging of per-dataset percentages.
- Split labels do not prove unseen holdout. No memory metrics measured.

| Group | Profile | Files | Entities | WER | CER | Entity |
|---|---|---:|---:|---:|---:|---:|
| all | B0 | 22 | 139 | 35.1 | 28.9 | 66.2 |
| all | B1 | 22 | 139 | 14.5 | 10.6 | 68.3 |
| all | B2 | 22 | 139 | 13.6 | 10.4 | 74.1 |
| dataset:team22-edge-clone | B0 | 11 | 70 | 38.3 | 32.4 | 67.1 |
| dataset:team22-edge-clone | B1 | 11 | 70 | 17.8 | 14.2 | 70.0 |
| dataset:team22-edge-clone | B2 | 11 | 70 | 17.2 | 13.9 | 70.0 |
| dataset:team22-edge-synth | B0 | 11 | 69 | 32.1 | 25.9 | 65.2 |
| dataset:team22-edge-synth | B1 | 11 | 69 | 11.5 | 7.4 | 66.7 |
| dataset:team22-edge-synth | B2 | 11 | 69 | 10.4 | 7.2 | 78.3 |
| split:dev | B0 | 2 | 14 | 26.3 | 21.4 | 85.7 |
| split:dev | B1 | 2 | 14 | 7.8 | 5.0 | 85.7 |
| split:dev | B2 | 2 | 14 | 6.7 | 4.2 | 92.9 |
| split:holdout | B0 | 20 | 125 | 35.8 | 29.6 | 64.0 |
| split:holdout | B1 | 20 | 125 | 15.1 | 11.1 | 66.4 |
| split:holdout | B2 | 20 | 125 | 14.2 | 10.9 | 72.0 |
| noisy:False | B0 | 15 | 97 | 37.5 | 30.9 | 63.9 |
| noisy:False | B1 | 15 | 97 | 16.9 | 12.6 | 64.9 |
| noisy:False | B2 | 15 | 97 | 16.1 | 12.7 | 71.1 |
| noisy:True | B0 | 7 | 42 | 29.5 | 24.5 | 71.4 |
| noisy:True | B1 | 7 | 42 | 9.0 | 6.0 | 76.2 |
| noisy:True | B2 | 7 | 42 | 8.1 | 5.1 | 81.0 |

## Chi tiết: phowhisper-large (cuda/float16)


| Run | Model | Thiết bị | WER | CER | WER thô | Entity | Oracle entity | RTF | Giây ASR/phút audio (p50/p95) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| B0 | phowhisper-large | cuda/float16 | 19.7 | 12.8 | 19.7 | 17.3 | 84.2 | 0.9830262945059105 | 59.0 (53.0/96.7) |
| B1 | phowhisper-large | cuda/float16 | 15.7 | 11.1 | 19.7 | 63.3 | 84.2 | 0.9830910517239837 | 59.0 (53.0/96.7) |
| B2 | phowhisper-large | cuda/float16 | 14.3 | 9.8 | 19.1 | 65.5 | 84.2 | 1.4487172921012341 | 86.9 (89.1/127.2) |

| Run | T01 WER (entity) | T02 WER (entity) | T03 WER (entity) | T04 WER (entity) | T05 WER (entity) | T06 WER (entity) | T07 WER (entity) | T08 WER (entity) | T09 WER (entity) | T10 WER (entity) | T11 WER (entity) | T12 WER (entity) | T13 WER (entity) | T14 WER (entity) | T15 WER (entity) | T16 WER (entity) | T17 WER (entity) | T18 WER (entity) | T19 WER (entity) | T20 WER (entity) | T21 WER (entity) | T22 WER (entity) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 17.6 (2/6) | 14.1 (2/8) | 14.4 (1/7) | 20.0 (1/5) | 22.6 (0/6) | 20.7 (2/7) | 20.6 (2/10) | 21.5 (2/7) | 14.6 (1/7) | 14.0 (0/6) | 13.6 (0/4) | 17.2 (1/4) | 17.2 (1/8) | 29.6 (2/6) | 19.7 (0/6) | 14.8 (1/5) | 21.6 (2/6) | 16.9 (0/5) | 26.0 (0/7) | 24.3 (3/7) | 27.8 (1/7) | 25.4 (0/5) |
| B1 | 11.2 (5/6) | 11.8 (6/8) | 9.1 (6/7) | 13.0 (5/5) | 18.9 (4/6) | 19.7 (4/7) | 19.1 (5/10) | 14.2 (6/7) | 13.6 (4/7) | 13.6 (1/6) | 7.8 (0/4) | 16.8 (3/4) | 14.4 (7/8) | 10.6 (5/6) | 15.3 (4/6) | 13.1 (5/5) | 21.1 (3/6) | 14.8 (3/5) | 24.5 (1/7) | 22.7 (4/7) | 21.2 (5/7) | 21.7 (2/5) |
| B2 | 4.3 (6/6) | 11.2 (5/8) | 5.3 (6/7) | 14.9 (4/5) | 10.4 (5/6) | 14.0 (4/7) | 16.7 (5/10) | 11.0 (6/7) | 15.0 (4/7) | 13.2 (2/6) | 9.2 (1/4) | 16.8 (3/4) | 13.9 (7/8) | 11.5 (5/6) | 16.3 (4/6) | 12.0 (5/5) | 19.6 (3/6) | 14.2 (3/5) | 25.0 (2/7) | 22.1 (5/7) | 23.2 (4/7) | 16.9 (2/5) |

| Comparison (right - left, pp) | WER | CER | Entity |
|---|---:|---:|---:|
| B0->B1 | -4.0 | -1.7 | 46.0 |
| B1->B2 | -1.4 | -1.3 | 2.2 |
| B0->B2 | -5.4 | -3.0 | 48.2 |

Negative WER/CER and positive Entity deltas are improvements.

- B0 includes VAD/cleanup; its WER includes representation mismatch.
- B0/B1 share no-hotword decode; B2 includes hotword echo filtering.
- Subsets are re-scored by BTC; no averaging of per-dataset percentages.
- Split labels do not prove unseen holdout. No memory metrics measured.

| Group | Profile | Files | Entities | WER | CER | Entity |
|---|---|---:|---:|---:|---:|---:|
| all | B0 | 22 | 139 | 19.7 | 12.8 | 17.3 |
| all | B1 | 22 | 139 | 15.7 | 11.1 | 63.3 |
| all | B2 | 22 | 139 | 14.3 | 9.8 | 65.5 |
| dataset:team22-edge-clone | B0 | 11 | 70 | 21.9 | 14.8 | 17.1 |
| dataset:team22-edge-clone | B1 | 11 | 70 | 17.3 | 12.8 | 64.3 |
| dataset:team22-edge-clone | B2 | 11 | 70 | 16.9 | 12.3 | 64.3 |
| dataset:team22-edge-synth | B0 | 11 | 69 | 17.8 | 11.1 | 17.4 |
| dataset:team22-edge-synth | B1 | 11 | 69 | 14.2 | 9.6 | 62.3 |
| dataset:team22-edge-synth | B2 | 11 | 69 | 11.9 | 7.6 | 66.7 |
| split:dev | B0 | 2 | 14 | 16.0 | 10.2 | 28.6 |
| split:dev | B1 | 2 | 14 | 11.5 | 8.5 | 78.6 |
| split:dev | B2 | 2 | 14 | 7.6 | 5.7 | 78.6 |
| split:holdout | B0 | 20 | 125 | 20.0 | 13.1 | 16.0 |
| split:holdout | B1 | 20 | 125 | 16.1 | 11.3 | 61.6 |
| split:holdout | B2 | 20 | 125 | 14.9 | 10.2 | 64.0 |
| noisy:False | B0 | 15 | 97 | 20.9 | 13.7 | 18.6 |
| noisy:False | B1 | 15 | 97 | 16.6 | 11.8 | 63.9 |
| noisy:False | B2 | 15 | 97 | 14.6 | 10.3 | 68.0 |
| noisy:True | B0 | 7 | 42 | 17.2 | 10.9 | 14.3 |
| noisy:True | B1 | 7 | 42 | 13.7 | 9.5 | 61.9 |
| noisy:True | B2 | 7 | 42 | 13.6 | 8.6 | 59.5 |

## Chi tiết: phowhisper-medium (cuda/float16)


| Run | Model | Thiết bị | WER | CER | WER thô | Entity | Oracle entity | RTF | Giây ASR/phút audio (p50/p95) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| B0 | phowhisper-medium | cuda/float16 | 19.8 | 12.7 | 19.8 | 14.4 | 84.2 | 0.18665332771872603 | 11.2 (11.4/15.5) |
| B1 | phowhisper-medium | cuda/float16 | 17.0 | 11.8 | 19.8 | 53.2 | 84.2 | 0.18674527320478498 | 11.2 (11.4/15.5) |
| B2 | phowhisper-medium | cuda/float16 | 17.4 | 11.3 | 20.1 | 54.7 | 84.2 | 0.19293133349985112 | 11.6 (12.0/15.2) |

| Run | T01 WER (entity) | T02 WER (entity) | T03 WER (entity) | T04 WER (entity) | T05 WER (entity) | T06 WER (entity) | T07 WER (entity) | T08 WER (entity) | T09 WER (entity) | T10 WER (entity) | T11 WER (entity) | T12 WER (entity) | T13 WER (entity) | T14 WER (entity) | T15 WER (entity) | T16 WER (entity) | T17 WER (entity) | T18 WER (entity) | T19 WER (entity) | T20 WER (entity) | T21 WER (entity) | T22 WER (entity) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 21.9 (2/6) | 21.2 (2/8) | 20.6 (0/7) | 20.9 (0/5) | 20.3 (0/6) | 16.6 (2/7) | 22.5 (2/10) | 23.3 (2/7) | 16.5 (1/7) | 14.0 (0/6) | 10.7 (0/4) | 16.0 (1/4) | 16.1 (1/8) | 27.4 (1/6) | 18.2 (0/6) | 14.2 (1/5) | 23.6 (2/6) | 16.9 (0/5) | 28.1 (0/7) | 28.2 (2/7) | 18.2 (1/7) | 21.7 (0/5) |
| B1 | 16.6 (5/6) | 20.0 (3/8) | 14.4 (5/7) | 18.1 (4/5) | 14.6 (3/6) | 16.6 (4/7) | 22.5 (3/10) | 16.9 (5/7) | 15.0 (4/7) | 13.6 (1/6) | 8.3 (2/4) | 16.0 (3/4) | 15.0 (6/8) | 18.6 (3/6) | 15.8 (2/6) | 12.6 (4/5) | 22.6 (2/6) | 15.8 (3/5) | 28.1 (2/7) | 26.5 (2/7) | 11.6 (6/7) | 16.9 (2/5) |
| B2 | 16.0 (4/6) | 20.0 (4/8) | 12.8 (5/7) | 18.6 (4/5) | 16.0 (3/6) | 18.7 (4/7) | 23.5 (3/10) | 17.8 (4/7) | 15.5 (4/7) | 13.6 (1/6) | 8.3 (2/4) | 16.8 (3/4) | 13.9 (6/8) | 21.2 (3/6) | 19.2 (2/6) | 14.8 (4/5) | 18.6 (4/6) | 20.2 (3/5) | 25.5 (2/7) | 23.2 (3/7) | 12.6 (6/7) | 18.0 (2/5) |

| Comparison (right - left, pp) | WER | CER | Entity |
|---|---:|---:|---:|
| B0->B1 | -2.8 | -0.9 | 38.8 |
| B1->B2 | 0.4 | -0.5 | 1.5 |
| B0->B2 | -2.4 | -1.4 | 40.3 |

Negative WER/CER and positive Entity deltas are improvements.

- B0 includes VAD/cleanup; its WER includes representation mismatch.
- B0/B1 share no-hotword decode; B2 includes hotword echo filtering.
- Subsets are re-scored by BTC; no averaging of per-dataset percentages.
- Split labels do not prove unseen holdout. No memory metrics measured.

| Group | Profile | Files | Entities | WER | CER | Entity |
|---|---|---:|---:|---:|---:|---:|
| all | B0 | 22 | 139 | 19.8 | 12.7 | 14.4 |
| all | B1 | 22 | 139 | 17.0 | 11.8 | 53.2 |
| all | B2 | 22 | 139 | 17.4 | 11.3 | 54.7 |
| dataset:team22-edge-clone | B0 | 11 | 70 | 21.4 | 14.1 | 14.3 |
| dataset:team22-edge-clone | B1 | 11 | 70 | 18.5 | 13.2 | 50.0 |
| dataset:team22-edge-clone | B2 | 11 | 70 | 18.9 | 12.6 | 55.7 |
| dataset:team22-edge-synth | B0 | 11 | 69 | 18.4 | 11.5 | 14.5 |
| dataset:team22-edge-synth | B1 | 11 | 69 | 15.6 | 10.6 | 56.5 |
| dataset:team22-edge-synth | B2 | 11 | 69 | 16.1 | 10.2 | 53.6 |
| split:dev | B0 | 2 | 14 | 21.6 | 13.2 | 28.6 |
| split:dev | B1 | 2 | 14 | 18.2 | 12.1 | 57.1 |
| split:dev | B2 | 2 | 14 | 17.9 | 11.4 | 57.1 |
| split:holdout | B0 | 20 | 125 | 19.7 | 12.7 | 12.8 |
| split:holdout | B1 | 20 | 125 | 16.9 | 11.7 | 52.8 |
| split:holdout | B2 | 20 | 125 | 17.3 | 11.3 | 54.4 |
| noisy:False | B0 | 15 | 97 | 21.0 | 13.5 | 15.5 |
| noisy:False | B1 | 15 | 97 | 17.6 | 12.4 | 53.6 |
| noisy:False | B2 | 15 | 97 | 17.5 | 11.7 | 54.6 |
| noisy:True | B0 | 7 | 42 | 17.2 | 10.8 | 11.9 |
| noisy:True | B1 | 7 | 42 | 15.6 | 10.3 | 52.4 |
| noisy:True | B2 | 7 | 42 | 17.1 | 10.5 | 54.8 |


---

# Bổ sung 2: nhóm 1 trên btc-edge (lời thoại BTC D01–D04, audio do team tự đọc bằng Edge TTS)

Gói BTC không phát audio (thư mục `asr/` chỉ có `ground_truth.json`; audio của 12 hội thoại phát vào ngày chấm). Bộ `btc-edge` là lời thoại D01–D04 của BTC, được team tự đọc thành audio bằng Edge TTS: 4 file, 167 giây, 29 entity, 35 entity theo lượt. Kết quả chỉ để tham khảo, chưa phải số của ngày chấm.

Máy chạy: RTX 3050 4 GB, cuda/float16. Chấm bằng `wer_cer()` của `reference_eval.py` bản BTC 11/2026.

| Model | Profile | WER | CER | Entity | Entity theo lượt | Diarization | WER nhiễu / sạch | Giây ASR/phút audio | VRAM đỉnh (MiB) |
| :---- | :---- | ----: | ----: | ----: | ----: | ----: | ----: | ----: | ----: |
| whisper-turbo | B2 | 7.0 | 3.5 | **93.1** | **85.7** | 91.2 | 8.6 / 6.2 | **10.0** | 3509 |
| whisper-large-v3 | B2 | **6.4** | **3.1** | **93.1** | 82.9 | 91.2 | 6.8 / 6.0 | 92.7 | 3811 |
| phowhisper-medium | B2 | 9.2 | 4.7 | 75.9 | 68.6 | 91.2 | 8.0 / 9.5 | 18.7 | 3706 |
| phowhisper-large | B2 | 18.1 | 15.8 | 69.0 | 68.6 | 91.2 | 16.0 / 18.6 | 195.9 | 3940 |

| Model | B0 WER / Entity | B1 WER / Entity | B2 WER / Entity |
| :---- | ----: | ----: | ----: |
| whisper-turbo | 27.4 / 79.3 | 8.4 / 79.3 | 7.0 / 93.1 |
| whisper-large-v3 | 26.9 / 75.9 | 7.6 / 79.3 | 6.4 / 93.1 |
| phowhisper-medium | 32.1 / 27.6 | 30.1 / 69.0 | 9.2 / 75.9 |
| phowhisper-large | 9.0 / 20.7 | 7.6 / 72.4 | 18.1 / 69.0 |

Oracle entity (trích từ lời thoại chuẩn) đạt 100% trên D01–D04, nên mọi entity sai ở bảng trên đều do ASR.

**Nhận xét:**

- Thứ hạng giống trên team22. Turbo và large-v3 ngang nhau về Entity (93,1%). Large-v3 có WER thấp hơn 0,6 điểm, nhưng chậm hơn khoảng 9 lần. Turbo có entity theo lượt cao nhất (85,7%). **Vẫn khuyến nghị whisper-turbo + B2.**
- **phowhisper-large B2 tệ hơn B1** (WER từ 7,6 lên 18,1; tốc độ 196 giây/phút audio). Hotword làm model này lặp chữ hoặc sinh lan man, nên với PhoWhisper-large phải tắt hotword. Ở B1, PhoWhisper-large có WER tốt nhất bảng (7,6) nhưng Entity chỉ 72,4%.
- Diarization 91,2% ở cả 4 model, vì phần tách người nói không phụ thuộc model ASR.
- 4 hội thoại, 29 entity: mỗi entity tương đương 3,4 điểm %, nên chênh lệch dưới khoảng 7 điểm chưa có ý nghĩa.

---

# Bổ sung 3: xuất `turns[]` theo lượt (sửa `speech/asr.py`)

**Vì sao phải sửa:** từ bản 11/2026, `reference_eval.py` tính thêm `entity_accuracy_per_turn`. Chỉ số này so entity của từng lượt theo `idx`, và chỉ chạy khi `hypotheses.json` có `turns[]`. Trước đây pipeline chỉ xuất `asr_segments` theo đoạn VAD, không có `idx`/`speaker`, nên chỉ số này ra `null`. `diarization_turn_accuracy` (M2) cũng cần `turns[]` có `speaker`/`start`/`end`.

**Đã làm:**

1. File mới `speech/diarize.py`, tách 2 người nói:
   - VAD mịn (khoảng lặng 200 ms) để cắt đoạn.
   - Nhúng giọng bằng **WeSpeaker ResNet34 (ONNX, 26 MB, chạy bằng onnxruntime, không cần torch)**.
   - Chia 2 cụm bằng k-means.
2. **Gán vai A/C: agent là người nói nhiều hơn.** Tiêu chí này đúng ở 26/26 hội thoại BTC và team. Không dùng tiêu chí "người nói trước", vì D02–D04 của BTC là khách nói trước.
3. `asr.py` vẫn giải mã nguyên đoạn VAD như cũ. Đoạn nào chứa 2 người thì bật `word_timestamps` và chia từng từ cho người nói theo mốc giữa của từ, nhờ đó không mất ngữ cảnh. Cách đầu tiên (cắt audio theo người nói trước khi giải mã) làm WER team22 tăng 13,6 → 14,9, nên đã bỏ.
4. Các đoạn liền nhau cùng người nói được gộp thành lượt `{idx, speaker, start, end, text, entities}`, và entity được trích trên cả lượt. Có thể tắt bằng `DecodeConfig(diarize=False)`; khi tắt, định dạng đầu ra giữ như cũ.

**Kết quả trên team22 (22 file, 139 entity, 231 entity theo lượt), whisper-turbo, cuda/float16:**

| Profile | WER | CER | Entity | Entity theo lượt | Diarization | WER nhiễu / sạch | Giây ASR/phút audio |
| :---- | ----: | ----: | ----: | ----: | ----: | ----: | ----: |
| B2 trước khi sửa | 13.6 | 9.5 | 74.1 | – (null) | – | – | 7.2 |
| B0 sau khi sửa | 38.0 | 31.2 | 61.9 | 50.6 | 87.6 | 31.1 / 41.3 | 10.0 |
| B1 sau khi sửa | 19.4 | 14.9 | 63.3 | 51.5 | 87.6 | 12.6 / 22.9 | 10.0 |
| B2 sau khi sửa | 13.7 | 9.6 | 73.4 | 60.6 | 88.9 | 9.6 / 15.8 | 10.0 |

- WER và Entity gần như không đổi (Entity −0,7 điểm, tức 1 entity). Tốc độ chậm thêm khoảng 2,8 giây/phút audio do nhúng giọng chạy trên CPU.
- Entity theo lượt (60,6%) thấp hơn entity cả hội thoại (73,4%), vì nói đúng giá trị nhưng ở lượt khác lượt được gắn nhãn thì vẫn bị tính sai.
- **Lỗi diarization còn lại** tập trung ở 4 file clone dùng hai giọng nam (`bac_m`/`nam_m`: T13, T16, T19, T22). Edge TTS tiếng Việt chỉ có 1 giọng nam, nên hai "người" này gần như là cùng một giọng: độ giống nhau cosine giữa hai người là 0,68–0,72, gần bằng mức trong cùng một người (0,73–0,75). Đây là giới hạn của dataset, không phải lỗi của model. Audio BTC dùng TTS khác (Gemini/ElevenLabs/F5) nên sẽ không gặp chuyện này.
- Kiểm thử: thêm `speech/test/test_diarize.py` (5 test, đều qua). Toàn bộ test speech: 147 test, còn 3 test `test_replay` lỗi; 3 lỗi này đã có từ trước khi sửa (đã kiểm bằng `git stash`).

---

# Bổ sung 4: vì sao số điện thoại "2/2" chưa nói lên gì (cần sinh thêm test)

Đề (mục D, dòng WER/CER) yêu cầu báo **độ chính xác riêng cho số tiền và số điện thoại**. Phụ lục A.5 nhấn mạnh: sai 1 chữ số của SĐT là hỏng cả entity. Hiện dữ liệu có quá ít SĐT để đo việc này.

| Bộ dữ liệu | Hội thoại | Entity `phone` | Kết quả turbo B2 |
| :---- | ----: | ----: | :---- |
| team22 | 22 | 2 (T02, T07) | 2/2 đúng, cả cấp hội thoại lẫn cấp lượt |
| BTC D01–D04 | 4 | 1 (D03) | đúng |
| `order_id` (cũng là chuỗi số) | 22 + 4 | 4 + 2 | team22 4/4 |

**Vì sao chưa kết luận được:**

1. **Cỡ mẫu.** 2 mẫu thì khoảng tin cậy 95% của tỉ lệ đúng là khoảng 16–100%. Muốn sai số khoảng ±10 điểm cần cỡ 60–100 SĐT.
2. **Cả 3 mẫu đều là trường hợp dễ.** Tất cả đọc từng chữ số, đủ 10 số, đầu `0`, không ngập ngừng: "không chín không bảy ba một hai tám bốn năm". Bộ trích hiện tại chỉ nhận chuỗi `0…` dài 9–11 số (`_PHONE_RE` trong `speech/entities.py`), nên chưa có gì kiểm được các cách đọc khó.
3. **Chưa có SĐT nào trong audio nhiễu hoặc đọc nhanh.** T02 là file nhiễu, nhưng SĐT được đọc chậm và rõ.

**Đề xuất sinh thêm test (khoảng 60–80 câu SĐT, rải trong 15–20 hội thoại mới):**

| Nhóm | Ví dụ cách nói | Kiểm điều gì |
| :---- | :---- | :---- |
| Đọc theo cụm 4-3-3 hoặc 3-3-4 | "không chín không bảy, ba một hai, tám bốn năm" | ITN gộp cụm, ngắt nghỉ của VAD |
| Đọc theo số hàng chục/trăm | "không chín không bảy, ba trăm mười hai, tám trăm bốn lăm" | ITN số có hàng, "lăm"/"mốt"/"tư" |
| "linh"/"lẻ" | "chín không linh bảy…" | biến thể miền Bắc |
| Đầu số +84 / 84 | "cộng tám tư chín không…" | chuẩn hóa về `0…` |
| Tự sửa giữa chừng | "…tám bốn năm, à nhầm, tám bốn sáu" | lấy giá trị sau cùng |
| Khách đọc, agent đọc lại để xác nhận | agent: "số của chị là … đúng không ạ" | entity theo lượt: nhãn ở lượt nào |
| Hai số trong một cuộc (số nhận hàng khác số gọi) | "giao về số của chồng chị…" | không ghi đè nhầm |
| Đọc nhanh, nhiễu đường phố, kênh 8 kHz | như trên + SNR 5–10 dB | độ bền của ASR |
| Giọng miền Trung | (Edge TTS không có giọng Trung, cần F5-TTS/ElevenLabs) | vùng miền |
| Đầu số cũ 11 số / số bàn | "không hai bốn…" (số bàn 10–11 số) | không nhận nhầm thành SĐT di động |

Cũng nên tăng `order_id` theo cách tương tự (đọc "ô đê" + số theo hàng hoặc từng chữ số), vì đây cũng là entity khớp tuyệt đối.

Khi báo cáo nên tách riêng 3 chỉ số: `phone` accuracy, `money` accuracy (gồm `price_vnd`, `budget_vnd`, `*_fee_vnd`, `min_free_ship_vnd`, `competitor_price_vnd`) và `order_id` accuracy, mỗi chỉ số ghi kèm số mẫu.


# Bổ sung 5: 120 hội thoại, một công cụ TTS (VieNeu), run `team-all-vieneu-baseline-v3` (19/11/2026)

Tạo lại toàn bộ audio bằng VieNeu-TTS 3.8.4 (v3 Turbo) để cả bộ dùng chung một model TTS: phiên 1 (22 cuộc), phiên 2 (22), phiên 3 (8) và 68 cuộc của 17 khách mới T30–T46 (`speech/dialogues/team_new_customers.json`). whisper-turbo, cpu/int8, bản chấm BTC tháng 11, lexicon và bộ luật hiện hành (đã gồm sửa "1 triệu 990.000"). Mỗi lượt đọc sạch được Whisper large-v3 nghe lại, lượt lệch trên 10% tạo lại 3 bản (xem `work/KET-QUA-AUDIO-ASR.md` trong gói bàn giao).

| Cấu hình | WER | CER | Entity (520) |
| :---- | ----: | ----: | ----: |
| B0 | 21.5 | 17.5 | 65.2 |
| B1 | 10.8 | 7.4 | 71.3 |
| B2 | 8.4 | 5.2 | 78.1 |

Oracle entity 93.1. B2 theo nhóm:

| Nhóm | Số file | WER | CER | Entity |
| :---- | ----: | ----: | ----: | ----: |
| Sạch | 89 | 7.0 | 4.1 | 80.7 |
| Nhiễu | 31 | 12.5 | 8.3 | 70.8 |
| Phiên 1 synthetic | 11 | 10.0 | 6.6 | 76.8 |
| Phiên 1 clone (bản xem trước) | 11 | 10.1 | 5.9 | 72.9 |
| Phiên 2 | 22 | 7.6 | 5.0 | 74.6 |
| Phiên 3 | 8 | 5.4 | 3.1 | 83.3 |
| Khách mới T30–T46 | 68 | 8.8 | 5.3 | 80.1 |

- **Số tiền** (B2): 113/149 đúng. **Mã đơn:** 4/4. **Số điện thoại:** 1/2 (vẫn chưa đủ mẫu, xem Bổ sung 4).
- Dữ liệu BTC D01–D04 đọc bằng VieNeu, chạy riêng (`btc-vieneu-baseline-v1`): B2 WER 10.7, CER 5.8, Entity 75.9 (4 hội thoại, 29 entity; chỉ để tham khảo).
- Không so trực tiếp với các bảng trên: khác công cụ TTS, khác máy, khác bản chấm.
- Chưa ai nghe audio bằng tai. Nhiễu vẫn là nhiễu hồng tổng hợp 10 dB, chỉ trộn vào lượt khách.
- Sửa kèm theo: `vi_numbers.py` ("N triệu DDD.000" → một số tiền, PR 30), nhãn phiên 2–3 (bỏ `size_new` ở T06-S02/T17-S02, "air piu" → "e pia", PR 34), giọng khách T21-S02 từ Trung sang Nam.
