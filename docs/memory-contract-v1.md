# Hợp đồng memory đa phiên v1

Ngày tham chiếu BTC: `2026-10-15`. Fixture tổng hợp:
`ai-services/test/fixtures/memory_contract_v1.json`. Tên ca và các trường
`expected_after_turn`/`forbidden` chỉ dùng trong test, không vào runtime.

| Ca | Hành vi bắt buộc | Mock/unit | PostgreSQL | MCP HTTP | LLM/public sample |
|---|---|---|---|---|---|
| Đổi ý giữa cuộc | Fact mới thay fact cũ; câu hỏi giả định không ghi đè | Qua: `set` → `supersede`, giả định giữ nguyên | Chưa chạy | Chưa chạy | Chưa chạy |
| Hai người chung số | Không đọc memory của ứng viên; chỉ gắn sau xác minh | Qua: ambiguous và verified control | Chưa chạy | Chưa chạy | Chưa chạy |
| Fanpage → hotline | Cùng `customer_id` đọc đúng ngữ cảnh cũ | Qua: fact phòng 12 m² | Chưa chạy | Chưa chạy | Chưa chạy |
| 16 lượt, 4 sản phẩm | Không lẫn quote/KM/tồn kho giữa SKU; giữ riêng nhu cầu của hai phòng; giá cũ chỉ là lịch sử | Qua 11/11 contract methods: room theo phạm vi, quote/KM/stock theo SKU, episode còn 4 mẫu | Migration scoped và read/write thật qua trên DB test tạm; chưa chạy ca 16 lượt qua PostgreSQL | Chưa chạy | Chưa chạy |
| Quay lại sau tám tháng | Giữ sở thích có nguồn; kiểm lại dữ liệu có ngày; không dùng địa chỉ cũ chưa xác thực | Qua: gọi lại stock/quote theo `on`, chặn claim giá cũ; lọc địa chỉ legacy khỏi profile, prompt và Call Brief trong các dạng đã kiểm | Chưa chạy | Chưa chạy | Chưa chạy |
| Yêu cầu xóa dữ liệu | Không tuyên bố đã xóa khi chưa có thao tác có thẩm quyền; không lộ PII | Qua: chặn lời nhận đã xóa; handoff `queued`/ticket; request nội bộ có xác minh chặn đọc/ghi memory. Chưa có purge toàn hệ thống | Barrier và purge riêng `ai_memory` qua trên DB test tạm; chưa chạy DB nghiệp vụ | Chưa chạy | Chưa chạy |

## Cách chạy

Từ `ai-services/`, `python -m unittest discover -s test -v` chạy gate hồi quy,
gồm fixture/oracle và hai nhóm an toàn đã sửa (`test_memory_freshness_contract.py`,
`test_memory_erasure_contract.py`). Các file `contract_*.py` chạy tường minh
bằng `unittest discover -s test -p 'contract_*.py' -v`; chúng chưa được tính
vào gate mặc định vì tên file khác `test*.py`.

## Kết quả khảo sát và nguyên nhân

Ngày chạy: 2026-10-20. `test_memory_contract_fixture.py`: 7/7 qua;
freshness 7/7 và erasure 11/11 qua trong gate mặc định.
`contract_*.py` có 11 test methods, hiện 11 qua trên fake harness/mock. Lệnh
kiểm: `cd ai-services && .venv/bin/python -m unittest discover -s test -p
'contract_*.py' -v`. Các test này vẫn chạy tường minh, chưa đưa vào gate
`test*.py` và chưa thay thế kiểm PostgreSQL/MCP/LLM end-to-end.

1. **Đã sửa trong phạm vi test an toàn:** `load_context` loại fact không thuộc
   registry và giá trị có PII nhận diện được trước khi đưa vào state/Call Brief;
   history và episode được che lại trước khi vào prompt. Đã kiểm địa chỉ dạng
   đường/phố, ngõ và căn hộ theo các thứ tự thông dụng, cùng tên riêng ba
   thành phần có họ phổ biến, kể cả PII nằm trong slot free-text hợp lệ;
   sở thích không chứa PII vẫn được giữ. Bộ che PII theo mẫu không bảo đảm nhận
   mọi cách viết địa chỉ; kho `address_ref` vẫn cần thiết.
2. **Đã sửa luồng yêu cầu xóa:** harness nhận yêu cầu xóa toàn hồ sơ và gọi
   `handoff.transfer` bằng số tin cậy của hotline/khách đã xác minh. Chỉ trả
   `needs_handoff` khi tool trả `status=queued` và `ticket_id`; thiếu số hoặc
   lỗi tool thì hướng dẫn xác minh/xử lý lại. Guardrail chặn lời xác nhận đã
   xóa dữ liệu kể cả khi tắt kiểm câu trả lời tùy chọn. Xóa một sở thích cụ thể
   vẫn đi luồng thường. `delete_customer` chưa có; `op=delete` chỉ là một fact.
3. **Đã sửa trong phạm vi mock:** fact mang `scope_type/scope_id`; PostgreSQL
   có unique active theo khách, scope và key. Quote/KM/stock được ràng vào SKU
   của tool và câu cuối; diện tích gắn phòng được nêu cùng giá trị, không lấy
   nhầm `thứ` làm cue giả định `thử`. Episode giữ fact có cấu trúc trước và
   lượt khách trong giới hạn ký tự. Context và Call Brief tách sản phẩm/phòng;
   chỉ SKU được nhắc rõ hoặc SKU duy nhất được refresh theo ngày cuộc gọi.
   Test harness dùng model giả lập chủ động gọi quote, không đo chất lượng
   quyết định tool của LLM thật. Phân giải tên phòng theo lời tự nhiên rộng
   hơn các dạng đã kiểm vẫn cần đánh giá.
4. **Đã đạt trong phạm vi mock:** sửa sở thích rõ ràng tạo `supersede`, câu
   giả định không ghi đè; người chung số không thấy ứng viên; định danh cùng
   khách xuyên kênh nạp fact; xác minh muộn không nhận lượt ẩn danh; giá và
   tồn kho được hỏi lại với `on` của cuộc mới; guardrail chặn claim giá cũ
   không khớp quote mới. Ca giá dùng `mock_tools.py` của BTC với SKU ngoài
   public sample. Chưa chứng minh câu trả lời tự do của LLM luôn chọn giá mới.

Thứ tự còn lại: duyệt [ma trận xóa](erasure-contract.md) → executor xóa từng
kho và kiểm chống tái xuất hiện → kiểm MCP HTTP/LLM và full/baseline trên DB
eval. Không triển khai purge bằng việc mở rộng `op=delete` của fact.

## Giới hạn chưa giải quyết

Ca xác minh muộn trong cùng phiên cũng qua ở MCP service fake: lượt ẩn danh
không đi vào history/episode của C102. Các ca này chưa chứng minh kết nối HTTP
hoặc dữ liệu PostgreSQL thật.

- `address_ref` và xóa toàn bộ dữ liệu khách chưa có trong runtime. Handoff là
  tiếp nhận yêu cầu; barrier và executor chỉ xử lý riêng kho `ai_memory` khi
  đã có request xác minh. Backend có service xóa chat riêng nhưng chưa có
  điều phối và receipt chung; các kho còn lại pending.
- Migration 0006 chỉ tái dựng được ranh giới của claim cũ có bản ghi thao tác;
  claim trực tiếp qua MCP không có operation key cần audit hoặc cách ly riêng.
- Điểm public sample không thay thế hợp đồng trên; cần DB eval tách biệt và
  trace thật mới có thể kết luận về LLM/MCP chạy end-to-end.

## Kiểm thêm trong đợt scoped memory (2026-10-20)

- AI unit mặc định: 178 test chạy, 171 qua, 7 skip; contract tường minh:
  11/11 qua. Backend: 9 test chạy, 6 qua, 3 skip; eval: 9/9 qua.
- PostgreSQL: migration 0008 qua trên `pg_temp`; một ca read/write scoped và
  barrier qua trên DB test tạo riêng rồi xóa. Các ca erasure memory và backend
  cũng qua trên DB PostgreSQL tạm. Chưa áp migration lên DB nghiệp vụ. Không
  coi thử nghiệm này là kiểm MCP HTTP.
- Nếu phần fact bắt buộc vượt `summary_max_chars`, episode lưu chỉ dẫn ngắn;
  các fact có cấu trúc vẫn nằm trong bảng facts và được `memory.read` trả riêng.

## Gate đã chạy

- AI unit (gồm safety contract): 156 test chạy, 154 qua, 2 skip; backend:
  6 qua; eval: 8 qua.
- Migration 0006: 1 test qua trên `pg_temp` trong transaction rollback.
- `git diff --check` qua. Chưa chạy MCP HTTP, LLM thật, full/baseline public
  sample hoặc áp migration lên DB nghiệp vụ.
