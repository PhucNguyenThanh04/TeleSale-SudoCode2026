# Rà soát mẫu extractor — run lịch sử 18/11

Người rà: trợ lý AI, không phải đánh giá độc lập của con người. Mẫu lấy ngẫu nhiên 20 trong 340 lượt Full/baseline bằng `random.Random(20261122).sample`, Full trước baseline, giữ thứ tự dòng trace. Đối chiếu lời agent với danh sách `questions` và `claims` đã lưu; đây không phải kiểm tra tính đúng của mỗi phát ngôn theo nguồn dữ liệu.

Bản kiểm này dùng trace lịch sử, không sửa trace hoặc điểm. Fingerprint extractor của run khác mã hiện tại; kết quả không thay thế đánh giá trên bản phát hành hay rà soát của BTC. Một số claim có điều kiện không thể ánh xạ an toàn sang một trường vô điều kiện; cần báo giới hạn thay vì tự suy diễn.

| # | Cấu hình | Kịch bản | Phiên | Lượt | Nhận xét |
|---:|---|---|---|---:|---|
| 1 | baseline | SC-T21 | call_3 | 1 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 2 | baseline | SC-T16 | call_1 | 3 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 3 | full | SC-T21 | call_3 | 1 | Thiếu claim miễn phí thu hộ COD; miễn phí vận chuyển được trích xuất. |
| 4 | baseline | SC04 | call_1 | 1 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 5 | baseline | SC-T04 | call_2 | 2 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 6 | baseline | SC03 | call_1 | 2 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 7 | full | SC-T03 | call_2 | 1 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 8 | full | SC-T05 | call_2 | 2 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 9 | baseline | SC04 | call_1 | 2 | Thiếu claim miễn phí COD; có trích xuất giảm giá, mã KM và giá cuối. |
| 10 | baseline | SC-T05 | call_1 | 2 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 11 | full | SC-T02 | call_1 | 2 | Nhiều điều kiện, mức phí và phụ thu trong lời thoại không được xuất claim. |
| 12 | full | SC-T16 | call_1 | 2 | Có thông số sản phẩm và chính sách bảo hành theo ngày nhưng không xuất claim. |
| 13 | baseline | SC-T09 | call_2 | 2 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 14 | baseline | SC-T15 | call_2 | 1 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 15 | baseline | SC-T15 | call_1 | 1 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 16 | full | SC-T21 | call_1 | 1 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 17 | baseline | SC04 | call_2 | 1 | Một câu hỏi ánh xạ ba slot, scorer BTC đếm ba phần tử; cần thống nhất cách diễn giải RQR. |
| 18 | baseline | SC-T03 | call_1 | 1 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 19 | full | SC04 | call_2 | 1 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |
| 20 | baseline | SC-T06 | call_1 | 3 | Không ghi nhận thiếu sót rõ ràng trong phạm vi các trường đã xem; chưa xác minh sự thật hoặc toàn bộ cách phân loại. |

Các câu chưa được biểu diễn không tự động là sai. `reference_eval.py` chỉ tính claim có trường tương ứng trong ground truth của phiên; bổ sung một nhãn tùy ý hoặc bỏ điều kiện có thể làm chỉ số sai. Cần kiểm tra thủ công với catalog/chính sách theo ngày và công bố giới hạn; chạy lại trên mã cùng fingerprint với bản nộp.

SHA-256 trace:

- `full.diagnostics_full.jsonl`: `f574d3e05cfa9e57843d9cc10e04b4033e92078763aedf1731a02d82c417e695`
- `baseline.diagnostics_baseline.jsonl`: `b9600c84b6038202f80105b31b93dd2b209bcef1925fd1b8cdc4cb8cb998e8e4`
