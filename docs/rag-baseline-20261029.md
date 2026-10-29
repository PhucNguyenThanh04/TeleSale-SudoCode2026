# Baseline truy hồi chính sách trước khi bật RAG

Ngày đo: 2026-10-29. Nguồn: `BTC-Data-Vong1-TEAMS/rag/qa_labeled.json` (60 câu), policy cùng gói BTC trong workspace. Lệnh: `python eval/policy_retrieval_baseline.py`. Ngày gọi và ngày đơn giả định cho phép đo này: `2026-10-15`.

| Loại câu | Số câu đủ điều kiện | Hit@3 | Hit@5 | Full@5 |
|---|---:|---:|---:|---:|
| Single | 24 | 20 | 20 | 20 |
| Multi-hop | 11 | 10 | 10 | 5 |
| Version conflict | 5 | 3 | 4 | 2 |
| Unanswerable có chunk công khai | 6 | 6 | 6 | 6 |
| Numeric | 4 | 4 | 4 | 3 |
| **Tổng** | **50** | **43** | **44** | **36** |

Đây là phép đo **offline của thứ hạng từ khóa**, không phải điểm RAG hay chất lượng câu trả lời. 10 câu bị loại: một single, một multi-hop, một version conflict, hai unanswerable và năm restricted. Lý do: không có ID liên quan, ID không công khai hoặc ID không có hiệu lực với ngày giả định. Bộ QA có câu version conflict về đơn cũ và câu restricted gán ID tài liệu nội bộ; runtime phải giữ ranh giới quyền/ngày, không mở nguồn để tăng điểm. Chạy lại với `--order-date` khi kiểm đúng một ngày đơn cũ và báo riêng trường hợp đó.

Mốc tiếp theo: đo cùng tập đủ điều kiện sau khi nạp Qdrant và bật `POLICY_RAG_ENABLED=true`; báo Hit@3/@5, full recall multi-hop, thời gian truy hồi, lỗi fallback và đánh giá câu trả lời. Chưa có kết quả hệ thống PostgreSQL + Qdrant + MCP + LLM thật.
