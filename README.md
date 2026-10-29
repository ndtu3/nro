# NgocRongViet Auto & Vá lỗi Vòng Quay May Mắn (VQMM)

Bộ công cụ hỗ trợ tự động hóa và sửa lỗi kẹt **Rương phụ** khi chạy Auto Vòng Quay May Mắn (`vqmm`) trên Thượng Đế (`45.Thần điện`) cho client **NgocRongViet**.

## Danh sách file
- `patch_vqmm.py` / `patch_vqmm.bat`: Script vá trực tiếp `GameAssembly.dll` (tự động tạo bản sao lưu `GameAssembly.dll.bak`), khắc phục triệt để 3 lỗi trong client gốc:
  1. Không tắt sớm cờ `isLayDoRuongPhu` trước khi hoàn tất đủ 4 bước mở menu Thượng Đế -> Vòng quay May mắn -> Rương phụ -> Nhận tất.
  2. Sửa lỗi dò menu bị thoát sớm ở nút `0` (*Vòng quay vàng*) để bấm chính xác vào nút `2` (*Rương phụ*).
  3. Tự động chuyển màn hình về `GameScr` sau khi nhận hết đồ trong Rương phụ để tự mở lại Vòng quay vàng quay tiếp, đồng thời bỏ giới hạn tự ngắt khi vàng dưới 200 triệu.
- `auto_helper.py` / `run_auto.bat`: Bảng điều khiển GUI hỗ trợ kích hoạt nhanh lệnh `vqmm`, các phím tắt MOD có sẵn (`X`, `T`, `N`, `H`, `F`, `C`, `M`, `E`, `J`, `K`, `L`, `B`) và Auto lặp phím kỹ năng (`1` -> `8`, `Enter`, `Space`) bằng phím tắt `F8`.
- `boss_hunter.py` / `run_boss_hunter.bat` / `boss_hunter_agent.js` / `boss_clusters.json`: Bảng điều khiển **Săn Cụm BOSS** tự động (xem bên dưới).

## Săn Cụm BOSS tự động
Công cụ gắn vào game đang chạy bằng [Frida](https://frida.re) (không sửa `GameAssembly.dll`), tắt cửa sổ là game trở lại bình thường.

1. Mở game, vào nhân vật, nhấp đúp `run_boss_hunter.bat` (lần đầu tự cài `frida`).
2. Tích các cụm boss muốn săn rồi bấm **BẬT AUTO SĂN CỤM**. Công cụ sẽ:
   - lấy boss thuộc cụm đã chọn từ danh sách **Thông báo Boss** (ưu tiên thông báo mới nhất),
   - XMAP tới map boss; map chưa mở được (ví dụ Tương lai) thì bỏ qua 10 phút,
   - xin danh sách khu và dò **khu đông người trước**, bỏ qua khu đầy (mỗi lần đổi khu cách nhau 15 giây vì server chặn đổi khu ~12 giây, đổi dồn sẽ bị kick),
   - thấy boss của cụm thì khóa mục tiêu, bật tự đánh `ak`, dịch chuyển áp sát và đánh lần lượt hết cả cụm,
   - tự dùng skill hỗ trợ theo hành tinh (Thái Dương Hạ San / Đẻ trứng / Biến khỉ), hết cụm thì nhặt đồ rồi mới sang cụm kế tiếp,
   - chết thì tự hồi sinh tại chỗ (tốn ngọc/vàng) và đánh tiếp tới khi hết cụm; tuỳ chọn đổi khu chạy trốn khi HP thấp (mặc định tắt).
3. Sửa cụm boss trong `boss_clusters.json`: `members` là tên boss (khớp chính xác; `"Fide Đại Ca *"` = Fide Đại Ca 1/2/3), `maps` / `excludeMaps` giới hạn map (dạng `"63-83"`). Boss chưa thuộc cụm nào được ghi vào `boss_seen.txt`.
   Ví dụ Tiểu Đội Sát Thủ được tách thành phía **Nappa** (map 63–83) và phía **Namếc** (các map còn lại) vì hai bên trùng tên boss.

## Tự động làm nhiệm vụ
Trong cùng cửa sổ, bấm **BẬT TỰ LÀM NHIỆM VỤ**. Công cụ đọc nhiệm vụ hiện tại (bước, số lượng, NPC/map đích do server gửi) và tự làm từng bước:
- **Gặp NPC / báo cáo**: XMAP tới map, dịch chuyển tới NPC, mở menu, bấm qua các khung chat, chọn mục có chữ "nhiệm vụ / nhận / đồng ý / báo cáo".
- **Tiêu diệt boss** (vd. Tiểu Đội Sát Thủ): dùng bộ săn boss ở trên — boss đang ở khu thì đánh luôn, chưa có thì chờ thông báo boss rồi đi săn (tự hồi sinh, nhặt đồ).
- **Đánh N con quái**: XMAP tới map, nhận ra loại quái theo tên trong nhiệm vụ, bật **Tàn sát** của MOD cho đúng loại đó (kèm tự nhặt) tới khi đủ.
- **Tới địa điểm**: XMAP tới map và tới điểm nhấp nháy nếu có.
Bước chưa hỗ trợ hoặc làm 3 lần không xong thì công cụ **tự tạm dừng** và báo lý do (không làm bừa).

Lưu ý: địa chỉ hàm trong `boss_hunter_agent.js` dịch ngược từ bản client hiện tại (Unity 2022.3.37f1); client cập nhật thì phải dò lại.
Nên bật **Tự động ăn đậu** trong menu MOD để hồi máu khi chạy trốn.

## Cách chạy trên máy khác
1. Cài đặt **Python 3** (tích chọn *Add Python to PATH*).
2. **Bước 1 — Vá lỗi VQMM (chỉ cần chạy 1 lần cho mỗi bản client):**
   - Đóng game `NgocRongViet.exe` nếu đang mở.
   - Nhấp đúp vào `patch_vqmm.bat` (hoặc chạy `python patch_vqmm.py`).
   - Công cụ sẽ tự động tìm `GameAssembly.dll` trong thư mục `Downloads`, `Desktop`, cùng thư mục chứa tool, hoặc mở hộp thoại để bạn chọn file `GameAssembly.dll` / `NgocRongViet.exe`.
3. **Bước 2 — Sử dụng trong game:**
   - Mở lại `NgocRongViet.exe`, đi lên **45.Thần điện** và chat lệnh `vqmm` (hoặc mở `run_auto.bat` rồi bấm nút **BẬT / TẮT AUTO VÒNG QUAY MAY MẮN**).


## Auto Ấp Trứng Nhanh & Mua Đá Linh Lực (Karin & Trứng Linh Thú)
Tính năng tự động hóa chu trình nuôi/ấp trứng Linh Thú khép kín trên `control_panel.py`:
1. **Ấp trứng nhanh mốc 1 ngày:** Tự động tương tác với **Trứng Linh thú** (NPC 80), chọn mốc giảm **1 ngày** (tiêu hao 30 Đá Linh Lực + 3 Thỏi vàng).
2. **Tự mua Đá Linh Lực:** Khi Đá Linh Lực trong hành trang dưới 30 viên, tự động chuyển sang tương tác với **Thần mèo Karin** (NPC 18) và mua gói **99 Đá Linh Lực** (giá 14 Thỏi vàng), sau đó quay lại ấp trứng tiếp.
3. **Tự nở trứng:** Khi thời gian ấp đếm lùi về 0 (hoàn tất), tự động chọn **Nở trứng / Nhận** để thu hoạch Linh Thú.
4. **Tự mua trứng mới & sử dụng:** Tự mở Cửa hàng Karin để mua quả trứng mới, sau đó tự bấm **Sử dụng** trong hành trang để đưa trứng vào ổ ấp.
5. **Vòng lặp liên tục:** Tự động lặp lại quy trình trên không ngừng cho đến khi bạn bấm dừng hoặc cài đặt mục tiêu số ngày giảm.
- Kèm theo các phím bấm nhanh tiện lợi: **Mua 99 Đá LL ngay**, **Giảm 1 ngày ngay**, **Nở trứng ngay**.
