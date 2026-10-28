# Bản đồ speech — đọc trước khi quét code

Chỉ mục để tìm đúng file, không thay việc kiểm `git status` và đọc phần sắp sửa.
Không quét toàn bộ `data`, cache, model hoặc harness để làm việc trong speech.

```text
dialogues ──tts.py──► datasets (wav + segments + GT + manifest)
                          │
                       audio.py
                          │
                        asr.py ──► raw segments
                          │
                     normalize.py ──► spoken (WER), written (agent)
                          │
                      entities.py
                          │
                    hypotheses.json ──evaluate.py/btc.py──► điểm BTC

baseline.py: cùng audio → B0 / B1 / B2 → bảng điểm
replay.py: mốc A/C → clip khách → ASR B2 → turns.jsonl dùng chung cho hai mode memory
```

## Tra nhanh: đang làm việc gì?

| Việc | Chỉ đọc những phần này trước |
|---|---|
| Chạy/chỉnh baseline | `baseline.py`: `PROFILES`, `run_baselines`, `verify_experiment`, `compare_baselines`; `asr.py`: `decode_segments`, `finalize` |
| Thêm lệnh/cờ | `__main__.py`: `build_parser`, hàm `cmd_*` tương ứng |
| Điểm hoặc tổng hợp sai | `evaluate.py`: `score_run`, `coverage`, `asr_time`; `baseline.py`: `compare_baselines`; evaluator BTC qua `btc.py` |
| Lỗi từ Việt–Anh/hotwords | `lexicon.py`, mục liên quan trong `lexicon.json`, `asr.py` |
| Lỗi số/TN–ITN | `normalize.py`, `vi_numbers.py`, `test\test_text.py` |
| Chữ đúng nhưng entity sai | `entities.py`, `test\test_entities.py` |
| Cắt audio hoặc phone/noise | `audio.py`; cần biết nguồn timestamp mới đọc `tts.py`: `synth_dataset` |
| Bàn giao lượt khách | `replay.py`: `prepare_replay`, `export_replay`, `validate_turns`, `verify_bundle`; `examples\replay_sessions.example.json` |
| Kiểm giao diện backend | `..\backend\app\schemas\chat.py`, `..\backend\CHAT_API_CONTRACT.md` — chỉ đọc, không cần quét graph/MCP |
| Tạo thêm audio | `dialogues`, `tts.py`; ElevenLabs nhập file mới đọc `manual.py`, clone giọng mới đọc `team.py` |
| Kiểm kịch bản/nguồn BTC | `validate.py`, `btc.py`; không sửa dữ liệu BTC gốc |
| Kiểm hồi quy mới | `test\test_baseline.py`, `test\test_replay.py`; các test cũ theo tên module |
| Hướng dẫn/điểm thực nghiệm | `README.md` §10/§11; §8 là benchmark lịch sử |

`normalize.py` điều phối; `textutil.py` làm sạch text; `btc.py` tìm data/nạp evaluator.
`requirements.txt` là dependency riêng cho speech, không phải dependency manifest gốc.

## Dữ liệu: đọc metadata trước, không mở cả thư mục

| Artifact | Mục đích |
|---|---|
| `data\datasets\<tập>\manifest.json` | Nguồn audio, engine, noise, hash GT |
| `audio\<id>.segments.json` | Timestamp/nhãn A–C biết trước, không phải diarization dự đoán |
| `ground_truth.json` | Đáp án để chấm; không dùng sửa transcript runtime |
| `data\runs\<experiment>\experiment.json` | Khóa input/model/rules/catalog/evaluator cho B0/B1/B2 |
| `B0`, `B1`, `B2`: `run.json` → `score.json` | Đọc config và điểm trước khi đọc hypothesis |
| `hypotheses.json`, `raw.json` | Chi tiết ca lỗi; raw giữ cả đoạn bị cleanup loại |
| `comparison.json`, `report.md` | Bảng điểm, nhóm tập con, delta điểm phần trăm |
| `data\replays\<gói>\manifest.json` | Hash, số lượt, nguồn boundary, trạng thái gói |
| `clips.json` / `turns.jsonl` | Mapping clip chuẩn bị / lượt ASR bàn giao |
| `tts_cache`, `inbox`, `voice_refs` | Bỏ qua nếu không làm TTS; dữ liệu cục bộ có kiểm soát |

`speech\data` bị Git ignore. Tên `team22-edge-clone` là template nguồn; engine thực tế là edge.
Audio/PII/giọng không tự được phép chia sẻ chỉ vì có file.

## Các bẫy cần nhớ

- B0/B1/B2 đo **ASR**, không phải có/không memory. Harness phải dùng cùng transcript B2 ở cả hai mode.
- B0 vẫn có VAD/cleanup; không gọi là Whisper hoàn toàn thô. Chữ số/phiên âm cũng ảnh hưởng WER.
- `asr_segments` là đoạn VAD, không phải lượt khách. Hypothesis cả hội thoại chứa cả A và C.
- Entity là ứng viên từ chữ, không phải giá/tồn kho đúng từ tool.
- Run baseline/replay đã khóa không được `renormalize` ghi đè; tạo experiment mới.
- Ngày nghiệp vụ từ metadata, không lấy ngày máy. Cùng khách quay lại cần phiên mới do nhóm harness ánh xạ.
- `btc-edge` là TTS dựng từ lời BTC, không thay audio BTC chính thức.
- Split ghi “holdout” không tự chứng minh chưa từng xem lỗi.

Cho AI ở phiên sau: **đọc FILE_MAP trước, chọn hàng đúng việc, rồi chỉ đọc file/hàm liên quan**.
Đây là chỉ mục, không phải cơ chế tự động buộc mọi công cụ AI đọc file.
