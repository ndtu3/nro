# NgocRongViet Auto & Vá lỗi Vòng Quay May Mắn (VQMM)

Bộ công cụ hỗ trợ tự động hóa và sửa lỗi kẹt **Rương phụ** khi chạy Auto Vòng Quay May Mắn (`vqmm`) trên Thượng Đế (`45.Thần điện`) cho client **NgocRongViet**.

## Danh sách file
- `patch_vqmm.py` / `patch_vqmm.bat`: Script vá trực tiếp `GameAssembly.dll` (tự động tạo bản sao lưu `GameAssembly.dll.bak`), khắc phục triệt để 3 lỗi trong client gốc:
  1. Không tắt sớm cờ `isLayDoRuongPhu` trước khi hoàn tất đủ 4 bước mở menu Thượng Đế -> Vòng quay May mắn -> Rương phụ -> Nhận tất.
  2. Sửa lỗi dò menu bị thoát sớm ở nút `0` (*Vòng quay vàng*) để bấm chính xác vào nút `2` (*Rương phụ*).
  3. Tự động chuyển màn hình về `GameScr` sau khi nhận hết đồ trong Rương phụ để tự mở lại Vòng quay vàng quay tiếp, đồng thời bỏ giới hạn tự ngắt khi vàng dưới 200 triệu.
- `auto_helper.py` / `run_auto.bat`: Bảng điều khiển GUI hỗ trợ kích hoạt nhanh lệnh `vqmm`, các phím tắt MOD có sẵn (`X`, `T`, `N`, `H`, `F`, `C`, `M`, `E`, `J`, `K`, `L`, `B`) và Auto lặp phím kỹ năng (`1` -> `8`, `Enter`, `Space`) bằng phím tắt `F8`.

## Cách chạy trên máy khác
1. Cài đặt **Python 3** (tích chọn *Add Python to PATH*).
2. **Bước 1 — Vá lỗi VQMM (chỉ cần chạy 1 lần cho mỗi bản client):**
   - Đóng game `NgocRongViet.exe` nếu đang mở.
   - Nhấp đúp vào `patch_vqmm.bat` (hoặc chạy `python patch_vqmm.py`).
   - Công cụ sẽ tự động tìm `GameAssembly.dll` trong thư mục `Downloads`, `Desktop`, cùng thư mục chứa tool, hoặc mở hộp thoại để bạn chọn file `GameAssembly.dll` / `NgocRongViet.exe`.
3. **Bước 2 — Sử dụng trong game:**
   - Mở lại `NgocRongViet.exe`, đi lên **45.Thần điện** và chat lệnh `vqmm` (hoặc mở `run_auto.bat` rồi bấm nút **BẬT / TẮT AUTO VÒNG QUAY MAY MẮN**).