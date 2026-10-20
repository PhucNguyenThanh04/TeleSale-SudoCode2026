# Hợp đồng xử lý yêu cầu xóa dữ liệu khách hàng — đề xuất để duyệt

Hợp đồng này tách **tiếp nhận yêu cầu** khỏi **xóa dữ liệu**. Agent hiện chỉ
chuyển `handoff.transfer`; ticket `queued` không chứng minh đã xóa. Mọi thao tác
xóa toàn hồ sơ phải do người có thẩm quyền xác minh chủ thể và khởi chạy bằng
`customer_id` đã xác nhận. Số điện thoại, kể cả số của hotline, không đủ để
chọn hồ sơ khi có người dùng chung số.

## Ma trận theo kho

| Kho / chủ quản | Dữ liệu và cách chọn | Cách xử lý đề xuất | Điều kiện xác nhận |
|---|---|---|---|
| `ai_memory.facts`, `episodes`, `order_links`, `pending_facts` / MCP memory | `customer_id`; `pending_facts` còn phải nối qua session/turn đã được xác minh | Xóa vật lý dữ liệu thuộc khách sau khi đặt chặn đọc/ghi | Truy vấn lại bằng `customer_id` trả 0; không xóa lượt vô danh hay khách khác chung số |
| `ai_memory.turns` / MCP memory | Chỉ lượt có `customer_id` bằng chủ thể; cùng session có thể có lượt vô danh | Xóa lượt đã quy chủ; không xóa cả session theo số điện thoại | Không còn lượt đã quy chủ; lượt vô danh được kiểm riêng |
| `ai_memory.write_operations` / MCP memory | Operation key và JSON `result` có thể chứa fact/ID | Xóa hoặc làm rỗng các thao tác nối được tới turn/fact của chủ thể; giữ khóa chống replay trong bảng chặn riêng | Retry cũ không trả lại fact cũ hoặc ghi lại sau khi đã chặn |
| `app_runtime.chat_sessions`, `chat_messages` / backend | `chat_sessions.customer_id` đã xác minh, message nối theo session | Xóa phiên đã quy chủ và message theo cascade; phiên `unknown`/`ambiguous` không bị chọn theo số chung | Truy vấn lại bằng customer ID và session ID trả 0 |
| `app_runtime.tool_orders`, `tool_updates`, `tool_callbacks`, `tool_handoffs`, `promo_uses`, `tool_operations` / MCP order và backend DB | Order có `customer_id`; các bảng khác có phone, order ID hoặc JSON, không có khóa chủ sở hữu thống nhất | Chỉ xóa/ẩn danh khi nối được bằng bằng chứng sở hữu và quy tắc lưu giữ đã duyệt; bản chưa nối chắc chắn vào danh sách xử lý thủ công | Không báo hoàn tất toàn phạm vi khi còn hàng chưa xử lý; không xóa hàng của người chung số |
| `btc_source.customers`, `crm_orders`, CRM sessions / gói BTC và bản nhập | Seed được nhập từ gói BTC; `customer_id` là khóa đọc CRM | Giữ gói gốc; chặn đọc runtime đối với ID đang/xong xóa, và chặn tái nhập tạo lại profile dùng được. Quyền xóa bản nhập phải chốt với người quản lý dữ liệu | Đọc CRM của ID đã chặn không trả PII; thử tái nhập không mở lại quyền đọc |
| Trace JSONL cục bộ, Langfuse nếu bật / vận hành | Có thể chứa session ID, nội dung đã che hoặc thuộc tính truy vết | Kiểm cấu hình triển khai; xóa trace có thể nối chính xác hoặc giữ trạng thái `pending` để người vận hành xử lý | Có kết quả truy vấn/xác nhận riêng; không suy ra rằng trace không tồn tại chỉ vì mặc định tắt |
| Redis / backend | Code hiện chỉ mở kết nối; chưa thấy ghi trạng thái khách | Xác nhận cấu hình triển khai; nếu không có key khách thì `not_applicable` | Kiểm keyspace/cấu hình thực tế, không chỉ dựa vào code |
| Backup PostgreSQL, volume và trace / vận hành | Bản sao có thể chứa dữ liệu trước xóa | Ghi thời điểm sao lưu và thời hạn/hình thức xử lý do chủ quản duyệt; sau restore phải tái áp dụng chặn và erasure trước khi phục vụ | Biên bản restore rehearsal; không gọi là đã xóa mọi bản sao khi backup còn tồn tại |

Không có thời hạn lưu giữ được BTC quy định trong các tài liệu đã kiểm. Vì vậy
plan không tự đặt số ngày cho đơn hàng, trace hoặc backup. Các hàng chỉ có số
điện thoại hay JSON không rõ chủ sở hữu phải để `pending`, không suy chủ từ số.

## Quy trình và trạng thái

1. Agent ghi nhận và chuyển ticket; chỉ nói đã **chuyển yêu cầu** khi tool trả
   `queued` cùng ticket ID. Nếu tool lỗi hoặc thiếu kênh liên hệ đáng tin cậy,
   hướng dẫn khách xác minh qua tổng đài.
2. Nhân sự có thẩm quyền xác minh người yêu cầu, quyết định `customer_id`, các
   session liên quan và phạm vi từng kho. Bằng chứng và người duyệt lưu ở hệ
   thống nội bộ có kiểm soát; log/trace chỉ giữ mã tham chiếu đã che.
3. Tạo yêu cầu nội bộ idempotent bằng `request_key`; chặn đọc và ghi memory,
   CRM runtime trước khi xóa. Lệnh của sales agent không có quyền gọi executor.
4. Executor xử lý từng kho bằng khóa sở hữu; lưu kết quả `completed`, `pending`
   hoặc `failed` theo kho. Retry giữ kết quả kho đã xử lý và tiếp tục kho còn
   thiếu. Khi lỗi, chặn đọc/ghi tiếp tục có hiệu lực.
5. Kiểm lại từng kho và khả năng tái xuất hiện sau restore/import. Chỉ phát
   receipt `completed` cho **phạm vi đã duyệt và đã xác nhận**; nếu còn bản
   sao, nguồn BTC hoặc hàng chờ thủ công thì receipt phải nêu rõ phạm vi còn
   lại bằng ngôn ngữ không chứa PII.

Lời khách được phép nhận: “Đã chuyển yêu cầu xử lý dữ liệu” sau ticket queued;
“Đang xử lý, chưa xác nhận xóa xong” khi pending/partial; “Đã xử lý trong phạm
vi ...” chỉ khi có receipt của executor. Không dùng câu “đã xóa toàn bộ dữ liệu”
trong các trạng thái trên nếu còn BTC seed, trace hoặc backup nằm ngoài phạm vi.

## Quyết định cần xác nhận trước khi chạy xóa thật

- Chủ sở hữu dữ liệu quyết định cách xử lý đơn hàng và bản ghi có thể phải giữ,
  gồm điều kiện kết thúc việc giữ; plan không tự suy nghĩa vụ pháp lý.
- Chủ sở hữu gói BTC và DB nhập quyết định có được xóa bản nhập hay chỉ chặn
  runtime; gói BTC gốc của dự án không sửa.
- Người vận hành xác nhận trace/backup đang bật ở môi trường đích và cách
  chứng minh đã xử lý chúng.

Mặc định an toàn cho code khi các quyết định này còn mở: chặn đọc/ghi, chỉ xóa
những hàng có quyền sở hữu chắc chắn trong môi trường thử nghiệm, giữ các kho
khác ở `pending`, và không phát xác nhận xóa toàn bộ.

## Trạng thái triển khai hiện tại

- Đã có request nội bộ theo `customer_id` đã xác minh, barrier đọc/ghi memory,
  và executor cho riêng kho `ai_memory`. Test PostgreSQL tạo DB riêng, áp
  migration, kiểm xóa khách đã quy chủ, giữ khách khác và lượt vô danh, thử
  chạy lại rồi xóa DB thử nghiệm. Chưa chạy executor trên DB nghiệp vụ.
- Executor chỉ trả `completed` khi scope của request là riêng `ai_memory` và
  không còn `pending_facts` mơ hồ. Nếu scope có kho khác, trạng thái là
  `partial` và từng kho đó là `pending`. Bảng request tối thiểu còn được giữ
  làm chặn tái xuất hiện; đây là ngoại lệ phải nêu trong receipt.
- Backend đã có service xóa phiên `known` theo `customer_id` và bảng chặn tái tạo
  phiên đã xác minh từ CRM seed. Đã thử bằng PostgreSQL tạm, kể cả ca hai
  khách chung số. Service này chưa được điều phối từ request ở `ai_memory`;
  receipt chung vì thế vẫn để `backend_chats` ở `pending`.
- Order/callback/handoff, BTC seed ngoài cửa đọc của backend, trace, Langfuse
  và backup chưa có executor nối vào workflow; không được báo xóa toàn hồ sơ.
