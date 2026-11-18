# Bộ held-out BTC: 20 kịch bản, 50 phiên

Bộ `btc-held-out-20-v1` có **10 kịch bản hai phiên + 10 kịch bản ba phiên =
50 phiên, 150 lượt khách**. Dữ liệu nằm riêng trong `scenarios/`, không tự nhập
vào bộ eval thường, CRM, RAG hay Knowledge Gap Loop. Không sửa agent để làm các
ca này pass và chưa chạy model trên bộ này.

Khách hàng, tên, cách xưng hô, số điện thoại và ID kênh lấy nguyên từ
`catalog/crm_seed.json` của BTC. Cả 20 số điện thoại khác bộ 29 scenario của team;
cô Loan/C034 dùng Facebook `fb.hải.186` để phân biệt với Dung/C035 chung số.
SKU/biến thể, giá và khuyến mãi theo ngày, tồn kho, quyền sử dụng ưu đãi và
ngày giao dự kiến được đối chiếu dữ liệu cùng mock tham chiếu BTC.
Không tạo thêm khách, sửa catalog hoặc giả lập đơn lịch sử không tồn tại.
Đơn mới trong kịch bản dùng mã do `order.create` thực sự sinh, không gán trước mã.

Nhu cầu, ngân sách, địa điểm giao mới và câu hỏi hộ người nhà là **lời thoại tổng
hợp**, không phải thông tin vốn có trong CRM. Lời khách về máy của người khác
không chứng minh sở hữu; không tự thay trạng thái giao hàng trong tool/DB.

## Phạm vi

| ID | Phiên | Tình huống cần phân biệt |
|---|---:|---|
| HO-01 | 2 | Hai máy cùng SKU, chỉ một máy nhận giảm 50% |
| HO-02 | 2 | Ba máy khác giá, một ưu đãi và tổng đơn vượt COD |
| HO-03 | 2 | RUN-10 còn ngày hiệu lực nhưng khách đã sử dụng |
| HO-04 | 2 | Đổi size 43 sang 42 làm thay đổi quyền khuyến mãi |
| HO-05 | 2 | Không lộ sale tương lai; áp đúng khi đến ngày mở bán |
| HO-06 | 2 | Combo không trả riêng thành phần; nhận diện Facebook của C034 |
| HO-07 | 2 | Tải trọng bé 18kg không được bỏ khi xe phù hợp hết hàng |
| HO-08 | 2 | Khách sửa nguồn nước; kết luận phù hợp UF/RO phải cập nhật |
| HO-09 | 2 | Màng lọc của khách khác máy được hỏi hộ người nhà |
| HO-10 | 2 | Giả định và phủ định có từ “mua/lên đơn” không phải đồng ý |
| HO-11 | 3 | Đổi địa chỉ giao làm thay đổi quyền freeship theo vùng |
| HO-12 | 3 | Nhu cầu mới khác CRM cũ; giá trước, trong và sau sale |
| HO-13 | 3 | Tính lại ETA qua cuối tuần/nghỉ 26/10 khi ngày đặt thay đổi |
| HO-14 | 3 | Bảo hành ưu tiên catalog; máy dưới ngưỡng không có gói mở rộng |
| HO-15 | 3 | Không suy tương thích ghế với xe; khách đổi người dùng/cân nặng |
| HO-16 | 3 | Trần ngân sách cả giỏ, giảm số lượng, bỏ phụ kiện sai công nghệ |
| HO-17 | 3 | Rơi vỡ của người nhà khác lỗi nhà sản xuất/đơn mới của khách |
| HO-18 | 3 | Hai nhu cầu song song trên Facebook/hotline, quay về chủ đề đầu |
| HO-19 | 3 | Ngân sách tổng và yêu cầu remote khi sửa số lượng quạt |
| HO-20 | 3 | Không chuyển quyền trade-in từ người nhà/khách CRM khác |

## Nhãn và căn cứ

- `scenarios/HO-*.json`: định dạng runner BTC hiện có; có `success_if`, ground
  truth, nhãn carry-over và câu hỏi không được hỏi lại. Runtime chỉ nhận từng
  lời khách, ngày và định danh kênh, không nhận các nhãn này.
- `review.json`: nguồn policy theo section ID, SKU, căn cứ mới của từng kịch bản,
  tiêu chí nội dung cho **từng phiên** và các phép đối chiếu mock BTC offline.
- `manifest.json`: SHA-256 của 20 kịch bản, review, nguồn BTC và các bộ so sánh.
  Dùng để phát hiện thay đổi, không phải chữ ký hay chứng nhận người đã review.
- `test_dataset.py`: kiểm quy mô, identity/kênh/persona, nguồn policy, SKU,
  replay mock theo thứ tự phiên, tính khả thi của nhãn tool, carry-over và hash.

Nhãn do assistant soạn từ tài liệu BTC, **chưa được người độc lập duyệt**.
Assistant tác giả đã xem implementation trong phiên làm việc trước; đây là bộ
chưa dùng để tuning, không phải bộ test bí mật do BTC hoặc người độc lập cung cấp.

Đã đối chiếu mô típ với 29 ca team, 19 ca benchmark và 7 mẫu public BTC. Kiểm
trùng từ vựng dùng Jaccard trên cụm bốn từ, ngưỡng 0,35; nó chỉ phát hiện sao
chép gần nguyên văn, không chứng minh độc lập ngữ nghĩa. `novelty` trong
`review.json` giải thích khác biệt về hành trình/ràng buộc, không chỉ đổi tên.
Các luật nghiệp vụ chung vẫn được dùng lại vì đều thuộc cùng domain BTC.

## Kiểm tra offline

Từ root repo, không gọi model, embedding, MCP hay database:

```bash
ai-services/.venv/bin/python ai-services/eval_harness/offline_tests.py -q \
  eval/held_out/test_dataset.py --tb=short

PYTHONPATH=.:ai-services ai-services/.venv/bin/python -m eval_harness.preflight \
  --offline-check --scenarios eval/held_out/scenarios \
  --btc-root ../BTC-Data-Vong1-TEAMS
```

Mặc định lấy nguồn từ thư mục BTC bên cạnh repo. Có thể đổi nguồn kiểm thử bằng
`HELD_OUT_BTC_ROOT=/duong/dan/BTC-Data-Vong1-TEAMS` cho lệnh test.
Hash không khớp thì kiểm nguyên nhân trước, không tự cập nhật manifest để bỏ lỗi.

Replay mock chỉ xác nhận **dữ kiện và nhãn có căn cứ**, không xác nhận agent giải
được bài. Các trạng thái trong mock chỉ ở RAM của test, tách riêng mỗi kịch bản;
quyền dùng một lần được giữ giữa các phiên của cùng kịch bản.
HO-13 dùng ETA của mock BTC cho nội thành Hà Nội, không coi ngày dự kiến là
cam kết giao chắc chắn hay tự suy thời điểm nhận hàng.

## Khi chủ động chạy eval thật

Đóng băng code/settings/release trước khi chạy, giữ nguyên corpus BTC hợp lệ.
Không nạp câu thoại hoặc nhãn của bộ này vào knowledge để chuẩn bị đáp án.
Lệnh sau **gọi model và reset runtime/memory trên DB đích**, không được thực
hiện chỉ để kiểm tra dữ liệu:

```bash
AGENT_GUARDRAILS_ENABLED=true KNOWLEDGE_ENABLED=true \
python3 run_system.py eval --expected-database telesale -- \
  --seed 7 --scenarios eval/held_out/scenarios \
  --btc-root ../BTC-Data-Vong1-TEAMS
```

Tên DB phải khớp môi trường eval đã cấu hình. Chạy Full và Baseline tương đương
100 phiên thực thi; số phiên của dataset vẫn là 50.

Sau run, đọc trace và đối chiếu **tất cả tiêu chí `manual_checks` của từng phiên**
trước khi kết luận thành công ngữ nghĩa. BTC TSR theo tool/từ khóa không thay
cho việc kiểm đúng, đủ, liên quan và điều kiện áp dụng. Ghi người review,
bằng chứng và các ca chưa xác minh; không tự báo đã có review độc lập.

Nếu dùng lỗi của bộ này để sửa prompt/rules/retrieval, chuyển nó thành bộ phát
triển và giữ một bộ mới cho lần kiểm chứng tiếp theo. Với chỉ 20 kịch bản độc
lập và nhiều ca khó được chọn có chủ đích, điểm trên bộ này không phải ước lượng
chính xác xác suất vượt test ẩn BTC.
