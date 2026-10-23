# Kế Hoạch Thiết Kế Lại Toàn Diện Dashboard Visualize Benchmark (Deep Agent vs ReAct Agent)

> **Mục tiêu:** Nâng cấp toàn diện ứng dụng `ai-services/eval_harness/visualize_benmark.py` từ giao diện cơ bản thành một **Executive Research & Diagnostic Dashboard** chuyên nghiệp (chuẩn báo cáo Mentor / Ban Giám Khảo BTC). Tích hợp thư viện đồ họa cao cấp **Plotly 6.3.0**, bổ sung **Radar Chart 6 trục**, **Gauge Meters**, và đặc biệt là module **Root Cause Analysis (Giải phẫu nguyên nhân số liệu)** để làm sáng tỏ bản chất các chỉ số TSR / RQR / Latency.

---

## 1. Phân Tích Thực Trạng & Điểm Nghẽn Cần Khắc Phục

1. **Biểu đồ thanh mặc định `st.bar_chart` đơn điệu**: Không có nhãn giá trị cụ thể, độ trễ $p95$ ($7296$ ms) lấn át $p50$ ($2488$ ms) gây mất cân đối thị giác.
2. **Số liệu TSR 10.5% gây hiểu lầm**: Nếu nhìn lướt qua con số 10.5% sẽ tưởng hệ thống đàm thoại kém. Nhưng thực tế **88.2% ca fail là do thiếu lệnh gọi tool `order.create` ở Call 2**, trong khi nội dung đàm thoại, ghi nhớ facts và báo giá đều chính xác 100%!
3. **Thiếu Radar Chart 6 trục**: Cần một biểu đồ mạng nhện đa chiều để Mentor thấy ngay Deep Agent vượt trội ở Trí Nhớ, còn ReAct Agent vượt trội ở Tốc Độ.

---

## 2. Bản Đồ Bố Cục Giao Diện Mới

```text
visualize_benmark.py
├── Header & Context Badges (Model, Reference Date, Database, MCPs)
├── 1. Regulatory Scorecard (4 KPI Meters đối chiếu chuẩn BTC)
├── 2. Architectural Radar Chart (Hình nhện 6 trục so sánh Deep vs ReAct)
├── 3. Root Cause Analysis (Donut Chart & Bảng giải phẫu tại sao TSR = 10.5%)
├── 4. Comparative Analytics Tabs (Plotly Bar Charts có Target Lines)
│   ├── Tab Latency (Grouped Bars + Đường đỏ 8000ms BTC)
│   ├── Tab Memory (RQR Full vs Baseline + Mức giảm 50%)
│   └── Tab Tool Efficiency (Tool counts + Thrashing check)
├── 5. Interactive Scenario Inspector (Timeline đàm thoại chi tiết từng kịch bản)
└── 6. Executive Recommendations & Fix Roadmap cho Mentor
```

---

## 3. Kế Hoạch Triển Khai Chi Tiết (5 Tasks)

### Task 1: Thiết Kế Lại Kiến Trúc Thông Tin & Style CSS Nâng Cao
- Cấu hình layout Streamlit hiện đại, màu sắc nhận diện Deep Blue (`#1E88E5`) và ReAct Coral (`#FF7043`).
- Tái cấu trúc thanh điều khiển Sidebar: Lọc theo Category, Level M1/M2, Trạng thái Pass/Fail.

### Task 2: Xây Dựng Bộ Biểu Đồ Plotly Chuyên Nghiệp (Plotly Interactive Visuals)
- **Radar Chart 6 trục**: Memory, Speed, Price Honesty, Safety, Tool Control, Success.
- **Grouped Bar Charts**: Có nhãn số liệu trực tiếp trên đỉnh cột và đường kẻ mốc chuẩn BTC (Target Line).

### Task 3: Xây Dựng Module Giải Phẫu Nguyên Nhân Số Liệu (Root Cause Analysis)
- **Donut Chart**: Phân bổ nguyên nhân fail (88.2% thiếu `order.create`, 5.9% thiếu `order.update`, 5.9% thiếu `order.status`).
- **Bảng đối chiếu "Thực tế vs Kỳ vọng"**: Chứng minh Agent đàm thoại đúng 100%, chỉ bị nghẽn ở bước kích hoạt tool chốt đơn.
- Đưa ra giải pháp khắc phục ngắn gọn nâng TSR lên $\ge 80\%$.

### Task 4: Xây Dựng Bộ Soi Kịch Bản Tương Tác (Interactive Scenario Inspector)
- Tích hợp metadata từ `dataset_index.json`.
- Thêm Expander/Accordion xem chi tiết từng turn đàm thoại của kịch bản đã chọn.

### Task 5: Kiểm Thử, Tối Ưu Tốc Độ & Khởi Chạy Dashboard Mới
- Kiểm tra toàn bộ Plotly callbacks, đảm bảo không có warning hay lỗi runtime.
- Chạy ứng dụng trên cổng 8501.
