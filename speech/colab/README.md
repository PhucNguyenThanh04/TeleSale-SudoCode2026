# ASR trên Google Colab

[`asr_colab.ipynb`](asr_colab.ipynb) dựng một API ASR tạm thời trên Colab (GPU T4) để thử các model đã benchmark trong [`speech/report.md`](../report.md): whisper-turbo, whisper-large-v3, PhoWhisper. API dùng lại pipeline B2 của `speech/asr.py` (VAD → Whisper + hotword → lexicon/ITN → entity → `turns[]` theo người nói) và mở ra internet qua Cloudflare quick tunnel.

## Cách chạy

1. Trên Colab: File → Upload notebook → chọn `asr_colab.ipynb`. Runtime → Change runtime type → **T4 GPU**.
2. (Không bắt buộc) Đặt `BTC-Data-Vong1-TEAMS` lên Google Drive và mount Drive trước cell 4 để trích được `sku`.
3. Chạy lần lượt cell 1 → 6. Cell 5 in ra `PUBLIC_URL`; mở `PUBLIC_URL/docs` để thử API trên trình duyệt.

Đổi model, thiết bị hoặc đường dẫn BTC: sửa các hằng số ở đầu cell 3 (`MODELS`, `DEVICE`, `COMPUTE_TYPE`, `BTC_DIR`), rồi chạy lại cell 3–4.

Tài liệu endpoint nằm ở cell cuối của notebook.

## Giới hạn

- Dùng để demo/thử nghiệm ngắn (phiên Colab khoảng 90 phút). Link đổi mỗi lần chạy lại tunnel.
- **Không có xác thực.** Chỉ gửi audio TTS hoặc audio đã được đồng ý, không gửi ghi âm khách hàng thật.
- Colab hiện không có sẵn CUDA 12; notebook cài `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` và nạp chúng bằng `ctypes` trong server.
- Đây không phải dịch vụ speech chính của repo; dịch vụ đó (Gipformer + TTS) nằm ở [`speech/serving`](../serving/README.md).
- Để chấm WER/CER chính thức, dùng `python -m speech baseline` thay vì gọi qua API.
