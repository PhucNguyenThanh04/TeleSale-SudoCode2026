# TeleSale SudoCode 2026

Trợ lý telesale tiếng Việt qua chat và thoại, có bộ nhớ giữa các cuộc gọi.

## Chạy dự án

Cần Python 3.12+, Docker Compose 2.20+ và gói dữ liệu BTC đã giải nén tại `../BTC-Data-Vong1-TEAMS`. Từ thư mục dự án, chạy trong Bash (Linux, macOS hoặc Windows WSL2).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r config/requirements/host.txt
cp -n .env.example .env
```

Điền `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, `CLOUDFLARE_ACCOUNT_ID` và `CLOUDFLARE_API_TOKEN` trong `.env`, rồi khởi động và nạp dữ liệu.

```bash
python scripts/compose_up.py
python seed_btc.py --data-dir ../BTC-Data-Vong1-TEAMS
```

Mở [Chat](http://127.0.0.1:8000/chat) hoặc [Thoại](http://127.0.0.1:8000/). Đăng nhập bằng `demo1` / `demo1-btc-2026`.

Chạy `python run_eval.py` để đánh giá **Full/Baseline**. Runner đặt lại dữ liệu runtime trước mỗi cấu hình và lưu kết quả trong `results-submission/`.

Dùng `docker compose down` để dừng.

[Kiến trúc](docs/tai-lieu-kien-truc.md) · [Báo cáo đánh giá](docs/bao-cao-danh-gia.md) · [Bộ kịch bản](eval/scenario_final/README.md)
