import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")


def rva_to_foff(rva):
    # il2cpp section: VA=0x17D000, RA=0x17B600
    return 0x17B600 + (rva - 0x17D000)


def find_dll_path():
    # 1. Nếu truyền đường dẫn qua tham số dòng lệnh
    if len(sys.argv) > 1:
        arg = os.path.abspath(sys.argv[1])
        if os.path.isdir(arg):
            candidate = os.path.join(arg, "GameAssembly.dll")
            if os.path.exists(candidate):
                return candidate
        elif os.path.exists(arg):
            if os.path.basename(arg).lower() == "ngocrongviet.exe":
                candidate = os.path.join(os.path.dirname(arg), "GameAssembly.dll")
                if os.path.exists(candidate):
                    return candidate
            return arg

    # 2. Tự động dò tìm ở các thư mục phổ biến trên mọi máy tính
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, "GameAssembly.dll"),
        os.path.join(os.path.dirname(script_dir), "GameAssembly.dll"),
        os.path.expanduser(r"~\Downloads\GameAssembly.dll"),
        os.path.expanduser(r"~\Desktop\GameAssembly.dll"),
        os.path.expanduser(r"~\Downloads\NgocRongViet\GameAssembly.dll"),
        os.path.expanduser(r"~\Desktop\NgocRongViet\GameAssembly.dll"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return os.path.abspath(path)

    # 3. Mở hộp thoại chọn file nếu đặt game ở thư mục khác
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askopenfilename(
            title="Chọn file GameAssembly.dll hoặc NgocRongViet.exe trong thư mục game",
            filetypes=[("Game Files", "GameAssembly.dll NgocRongViet.exe"), ("All Files", "*.*")],
        )
        root.destroy()
        if selected:
            if os.path.basename(selected).lower() == "ngocrongviet.exe":
                selected = os.path.join(os.path.dirname(selected), "GameAssembly.dll")
            if os.path.exists(selected):
                return os.path.abspath(selected)
    except Exception:
        pass

    return None


def patch_dll(dll_path=None):
    if not dll_path:
        dll_path = find_dll_path()
    if not dll_path or not os.path.exists(dll_path):
        raise FileNotFoundError("Không tìm thấy GameAssembly.dll! Hãy đặt cùng thư mục game hoặc chọn đường dẫn.")

    bak_path = dll_path + ".bak"

    patches = [
        # 1. Sửa hàm FindMenuButtonIndex (Tab1: 0x39A5C2, Tab2: 0x530D72)
        # Không thoát vòng lặp sớm khi gặp nút "Vòng quay vàng" (nút 0) để tìm tiếp nút "Rương phụ" (nút 2)
        (
            "Tab1_FindMenu_RuongPhu",
            0x39A5C2,
            bytes.fromhex("eb 05"),
            bytes.fromhex("eb ed"),
        ),
        (
            "Tab2_FindMenu_RuongPhu",
            0x530D72,
            bytes.fromhex("eb 05"),
            bytes.fromhex("eb ed"),
        ),
        # 2. Bỏ giới hạn tự tắt Auto VQMM khi vàng <= 200 triệu (Tab1: 0x39AEA0, Tab2: 0x530933)
        (
            "Tab1_Remove_200M_Gold_Limit",
            0x39AEA0,
            bytes.fromhex("0f 8e be 00 00 00"),
            bytes.fromhex("90 90 90 90 90 90"),
        ),
        (
            "Tab2_Remove_200M_Gold_Limit",
            0x530933,
            bytes.fromhex("0f 8e bc 00 00 00"),
            bytes.fromhex("90 90 90 90 90 90"),
        ),
        # 3. Sửa lỗi trong LayDoRuongPhu: ở step == 2 sau khi chọn "Rương phụ (X món)" và gán step = -1,
        # code gốc nhảy thẳng vào khối kiểm tra (step == -1) trong cùng 1 frame khiến gửi gói getItem(2, 0)
        # trước khi server kịp mở Rương phụ và làm reset step = 0 ngay lập tức.
        # Vá lệnh jmp để thoát hàm cập nhật lastTime, chờ nhịp kế tiếp mới gửi getItem(2, 0).
        (
            "Tab1_Fix_Step2_Fallthrough",
            0x39A75F,
            bytes.fromhex("e9 0c 01 00 00"),
            bytes.fromhex("e9 c4 01 00 00"),
        ),
        (
            "Tab2_Fix_Step2_Fallthrough",
            0x530F04,
            bytes.fromhex("e9 06 01 00 00"),
            bytes.fromhex("e9 ba 01 00 00"),
        ),
        # 4. Sửa lỗi tắt cờ isLayDoRuongPhu ngay ở step 0 trước khi hoàn tất mở Rương phụ và Nhận tất.
        # Chỉ đặt isLayDoRuongPhu = 0 khi biến trạng thái step ([static_fields + 0x58]) đã hoàn tất về 0,
        # đồng thời gọi GameScr.gI().switchToMe() để thoát màn hình CrackBallScr và tự mở lại VQMM.
        (
            "Tab1_Keep_LayDoRuongPhu_Until_Step0",
            0x39AFF5,
            bytes.fromhex(
                "48 8b 05 54 fa 86 00 83 b8 e0 00 00 00 00 75 0f 48 8b c8 e8 c3 a3 cf ff 48 8b 05 3c fa 86 00 48 8b 80 b8 00 00 00 c6 40 43 00"
            ),
            bytes.fromhex(
                "83 79 58 00 "           # cmp dword ptr [rcx + 0x58], 0 (step == 0?)
                "75 22 "                 # jne +0x22 (nhảy tới 0x39B01F nếu chưa xong các bước)
                "c6 41 43 00 "           # mov byte ptr [rcx + 0x43], 0 (đã nhận đồ xong -> tắt cờ lấy đồ)
                "33 c9 "                 # xor ecx, ecx
                "e8 8a 71 fa ff "        # call 0x342190 (GameScr.gI())
                "48 8b 10 "              # mov rdx, [rax]
                "48 8b c8 "              # mov rcx, rax
                "4c 8b 82 78 01 00 00 "  # mov r8, [rdx + 0x178]
                "48 8b 92 80 01 00 00 "  # mov rdx, [rdx + 0x180]
                "41 ff d0 "              # call r8 (GameScr.gI().switchToMe())
                "90 90"                  # nop; nop
            ),
        ),
        (
            "Tab2_Keep_LayDoRuongPhu_Until_Step0",
            0x530AA0,
            bytes.fromhex("48 8b 05 89 8a 6d 00 48 8b 88 b8 00 00 00 c6 41 4a 00"),
            bytes.fromhex(
                "83 79 58 00 "           # cmp dword ptr [rcx + 0x58], 0 (step == 0?)
                "75 0c "                 # jne +0x0C (nhảy tới 0x530AB2 nếu chưa xong các bước)
                "c6 41 4a 00 "           # mov byte ptr [rcx + 0x4A], 0 (đã nhận đồ xong -> tắt cờ lấy đồ)
                + "90 " * 8
            ),
        ),
        (
            "Tab2_SwitchToGameScr_After_RuongPhu",
            0x53109B,
            bytes.fromhex(
                "48 8b 05 8e 84 6d 00 39 98 e0 00 00 00 75 0f 48 8b c8 e8 1e 43 b6 ff 48 8b 05 77 84 6d 00 48 8b 80 b8 00 00 00 89 58 58"
            ),
            bytes.fromhex(
                "48 8b 05 8e 84 6d 00 "  # mov rax, [rip + 0x6d848e] (Tab2_ModClass)
                "48 8b 80 b8 00 00 00 "  # mov rax, [rax + 0xb8]
                "89 58 58 "              # mov [rax + 0x58], ebx (step = 0)
                "33 c9 "                 # xor ecx, ecx
                "e8 fd 78 f9 ff "        # call 0x4C89B0 (GameScr.gI())
                "48 8b 10 "              # mov rdx, [rax]
                "48 8b c8 "              # mov rcx, rax
                "4c 8b 82 78 01 00 00 "  # mov r8, [rdx + 0x178]
                "41 ff d0"               # call r8 (GameScr.gI().switchToMe())
            ),
        ),
        # 5. Chuyển nút Auto ở giữa màn hình VQMM (CrackBallScr idAction == 2) sang kích hoạt
        # cơ chế AutoVQMM có tự nhận Rương phụ thay vì luồng CrackBallScr.Auto cũ bị kẹt khi đầy rương.
        (
            "Tab1_Redirect_CrackBall_AutoBtn",
            0x2DE68D,
            bytes.fromhex(
                "48 8b 15 3c bb 92 00 48 8b 82 b8 00 00 00 80 78 38 00 0f 94 c1 88 48 38 48 8b 0d 24 bb 92 00 48 8b 81 b8 00 00 00 80 78 38 00 75 0f c6 40 39 01"
            ),
            bytes.fromhex(
                "48 8b 05 bc c3 92 00 "  # mov rax, [rip + 0x92c3bc] (Tab1_ModClass)
                "48 8b 80 b8 00 00 00 "  # mov rax, [rax + 0xb8]
                "c6 40 42 01 "           # mov byte ptr [rax + 0x42], 1 (isAutoVQMM = 1)
                "c6 40 43 00 "           # mov byte ptr [rax + 0x43], 0 (isLayDoRuongPhu = 0)
                "c7 40 58 00 00 00 00 "  # mov dword ptr [rax + 0x58], 0 (step = 0)
                + "90 " * 19
            ),
        ),
        (
            "Tab2_Redirect_CrackBall_AutoBtn",
            0x49FF9D,
            bytes.fromhex(
                "48 8b 15 74 8d 76 00 48 8b 82 b8 00 00 00 80 78 38 00 0f 94 c1 88 48 38 48 8b 0d 5c 8d 76 00 48 8b 81 b8 00 00 00 80 78 38 00 75 0f c6 40 39 01"
            ),
            bytes.fromhex(
                "48 8b 05 8c 95 76 00 "  # mov rax, [rip + 0x76958c] (Tab2_ModClass)
                "48 8b 80 b8 00 00 00 "  # mov rax, [rax + 0xb8]
                "c6 40 49 01 "           # mov byte ptr [rax + 0x49], 1 (isAutoVQMM = 1)
                "c6 40 4a 00 "           # mov byte ptr [rax + 0x4a], 0 (isLayDoRuongPhu = 0)
                "c7 40 58 00 00 00 00 "  # mov dword ptr [rax + 0x58], 0 (step = 0)
                + "90 " * 19
            ),
        ),
        # 6. Tăng tốc độ quay VQMM & nhận Rương phụ gấp 2.5 lần:
        # Giảm delay giữa mỗi nhịp từ 500ms (0x1F4) xuống 200ms (0xC8) cho cả Tab1 (0x39ADC1) và Tab2 (0x53084C).
        (
            "Tab1_SpeedUp_VQMM_200ms",
            0x39ADC1,
            bytes.fromhex("ba f4 01 00 00"),
            bytes.fromhex("ba c8 00 00 00"),
        ),
        (
            "Tab2_SpeedUp_VQMM_200ms",
            0x53084C,
            bytes.fromhex("ba f4 01 00 00"),
            bytes.fromhex("ba c8 00 00 00"),
        ),
        # 7. Chống Auto VQMM bấm nhầm nút làm nhân vật nhảy lên Kaio: khi menu của server chưa kịp về,
        # fg.cnl (dò nút menu) trả 0 và bước 2 của fg.cnn bấm mù nút 0 -> bấm trúng "Đến Kaio" của Thượng Đế.
        # Code mới nằm trong ln.epj() (hàm của bản GameScr chết, không ai gọi):
        # - fg.cnl chỉ trả chỉ số khi menu đang hiện (showMenu) và có nút khớp, còn lại trả 255 (bấm không có tác dụng).
        # - Bước 2 của fg.cnn dùng fg.cnl thay vì luôn bấm nút 0.
        (
            "VQMM_Cave_SafeMenuIndex",
            0x330C70,
            bytes.fromhex(
                "405641564883ec58803d2613920000488bf10f8557010000488d0d491d8d00e88c44d6ff488d0da5468d00e88044d6ff"
                "488d0d816a8d00e87444d6ff488d0dcd638c00e86844d6ff488d0dd1f68c00e85c44d6ff488d0d75648c00e85044d6ff"
                "488d0d29658c00e8"
            ),
            bytes.fromhex(
                "40b6ff"              # mov sil, 0xff            (mặc định: không bấm)
                "4088742448"          # mov [rsp+0x48], sil
                "488b0559838d00"      # mov rax, [TypeInfo GameCanvas]
                "488b80b8000000"      # mov rax, [rax+0xb8]      (static fields)
                "488b80d0000000"      # mov rax, [rax+0xd0]      (GameCanvas.menu)
                "4885c0"              # test rax, rax
                "0f84e3002000"        # je 0x530d79              (không có menu -> trả 255)
                "807810" "00"         # cmp byte [rax+0x10], 0   (showMenu)
                "0f84d9002000"        # je 0x530d79              (menu đã đóng/cũ -> trả 255)
                "e9c2fe1f00"          # jmp 0x530b67             (dò nút như cũ)
                "cccccccccccccccccccccccccccccccccccccccccccccccccccccc"
                # cave2 (bước 2): bấm nút 0 "Vòng quay vàng" như gốc nhưng CHỈ khi menu đang hiện
                # (không dùng fg.cnl: nó ưu tiên nút "Rương phụ ... món" nên sẽ mở rương thay vì quay)
                "31c0"                # xor eax, eax             (nút 0)
                "baff000000"          # mov edx, 255             (không bấm)
                "8079100" "0"         # cmp byte [rcx+0x10], 0   (Menu.showMenu)
                "0f44c2"              # cmove eax, edx           (menu đóng/chưa về -> 255)
                "894120"              # mov [rcx+0x20], eax      (Menu.selected)
                "c3"                  # ret
                "cccccccccccc"
            ),
        ),
        (
            "VQMM_FindMenu_ShownMenuOnly",
            0x530B5F,
            bytes.fromhex("40 32 f6 40 88 74 24 48"),
            bytes.fromhex("e9 0c 01 e0 ff 90 90 90"),  # jmp cave1
        ),
        (
            "VQMM_Step2_NoBlindClick",
            0x5311D3,
            bytes.fromhex("c7 41 20 00 00 00 00"),
            bytes.fromhex("e8 e8 fa df ff 90 90"),  # call cave2
        ),
        # 8. Chế độ ngủ cho VPS yếu: nhập FPS (menu MOD "Nhập FPS") từ 1 đến 5 thì game không vẽ hình nữa,
        # chỉ còn nền đen + bảng thông tin MOD (HP, MP, map - khu, vàng/ngọc, thông báo boss); logic vẫn chạy.
        # Mở lại game thì không ngủ (phải nhập lại FPS 5). Đang ngủ bấm X mở menu MOD là hiện lại, nhập FPS >= 6 để thôi ngủ.
        (
            "SleepMode_Cave",
            0x330CE0,
            bytes.fromhex(
                "208d00e83844d6ff488d0dd1638c00e82c44d6ff488d0d65648c00e82044d6ff488d0df9638c00e81444d6ff488d0d8d"
                "638c00e80844d6ff488d0d01648c00e8fc43d6ff488d0db5648c00e8f043d6ff488d0da9638c00e8e443d6ff488d0d3d"
                "648c00e8d843d6ff488d0dd1648c00e8cc43d6ff488d0df5928d00e8c043d6ff488d0d09938d00e8b443d6ff488d0d1d"
                "948d00e8a843d6ff488d0d11978d00e89c43d6ff488d0d85978d00e89043d6ff488d0dd9988d00e88443d6ff488d0dad"
                "9c8d00e87843d6ff488d0d619d8d00e86c43d6ff488d0d559e8d00e86043d6ff488d0de9a08d00e85443d6ff488d0d5d"
                "a48d00e84843d6ffc605c611920001488b05aa938d004533f6664489b424880000004439b0e0000000750f488bc8e8cd"
                "45d6ff488b0586938d00488b80b80000004438700d0f85fe0b0000488b0d2e928d004439b1e00000007505e8a045d6ff"
                "48895c247033c948896c245048897c24484c896424404c896c24384c897c2430e82b55f4ff4885c00f84a04900004438"
                "70320f85930b0000488b0de1918d004439b1e00000007505e85345d6ff33c9e8fc54f4ff4885c00f84714900004438b0"
                "ca0600000f85610b0000488b05cf978d00488b88b80000004438711c0f85490b0000488b05d7958d004439b0e0000000"
                "750f488bc8e80645d6ff488b05bf958d00488b80b800000044387015745c33c9e8db96f8ff4885c00f84104900004438"
                "70187546488b0595958d004439b0e0000000750f488bc8e8c444d6ff488b057d958d00488b80b8000000488b88d00000"
                "004885c90f84d448000044387110750a33d2488bcee8f6ed010033d2488bcee8bca50100488b0d45958d004439b1e000"
                "00007505e87744d6ff488b0de0618c004533c033d2e87668e5ff488b0dff908d004439b1e0000000750ce85144d6ff48"
                "8b0dea908d00488b81b8000000bd1900000041bf050000004c3970100f85d706000033c9e81796f8ff4885c00f844c48"
                "0000443870180f84a102000033c9e8fd95f8ff4885c00f84324800004c3970300f84b4000000488b05b3948d004439b0"
                "e0000000750f488bc8e8e243d6ff488b059b948d00488b80b8000000488b48304885c90f84f54700008379180c0f86e5"
                "4700004438712c753733c9e8a095f8ff4885c00f84d5470000488b0de09a8d00488b58304439b1e00000007505e88e43"
                "d6ff33d2488bcbe8a4e80c0084c0743a33c9e86995f8ff4885c00f849e4700004c397030742433c9e85395f8ff4885c0"
                "0f8488470000488b48304885c90f847b47000033d2e866f2f8ff33c9e82f95f8ff4885c00f84644700004c3970400f84"
                "b4000000488b05e5938d004439b0e0000000750f488bc8e81443d6ff488b05cd938d00488b80b8000000488b48304885"
                "c90f84274700008379180d0f86174700004438712d753733c9e8d294f8ff4885c00f8407470000488b0d129a8d00488b"
                "58404439b1e00000007505e8c042d6ff"
            ),
            # FPS MOD <= 5 và không có menu / panel / ô nhập (ChatTextField) đang mở -> nền đen + bảng thông tin MOD
            # + 2 dòng "CPU máy: x%" (GetSystemTimes, toàn máy) và "Đã nhặt: N món"; ngược lại -> GameCanvas.paint như thường.
            # 0x330CE0 cave ngủ, 0x330E00 vẽ CPU/số món, 0x331100 bộ đếm nhặt đồ; biến lưu ở phần thừa .data 0xEFBD00
            bytes.fromhex(
                "488b0569898d00488b80b80000000fbf401a83f8050f8f95f61c00488b05d6828d00488b80b80000004c8b88d0000000"
                "4d85c9740b41807910000f8570f61c004c8b88d80000004d85c9740b41807910000f8559f61c004c8b88e00000004d85"
                "c9740b41807910000f8542f61c00488b05a37e8d00a80175234885c0741e488b80b80000004885c07412488b004885c0"
                "740a807818000f8514f61c00534883ec304889d34889d931d24531c0e8ff2f05004889d931d24531c041b9b80b0000c7"
                "442420b80b000048c744242800000000e86b211f004889d931d2e8917c2000e83c0000004883c4305bc3cccccccccccc"
                "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
                "4154415556574883ec484c8d25efaebc00498d4c2428498d5424304d8d442438ff15f2726800498b442430492b442408"
                "498b4c2438492b4c24104801c8483d404b4c00724d498b4c2428492b0c244989c04929c873034531c04989c1496bc064"
                "31d249f7f14883f8647605b8640000004989442418498b44242849890424498b4424304989442408498b442438498944"
                "2410498d7c2440c6074348ffc7c6075048ffc7c6075548ffc7c6072048ffc7c6076d48ffc7c607c348ffc7c607a148ff"
                "c7c6077948ffc7c6073a48ffc7c6072048ffc7498b442418488d74244741bd0a00000031d249f7f580c230881648ffce"
                "4885c075ee48ffc6488d4c24474839ce77098a06880748ffc7ebeac6072548ffc7c6070048ffc7498d4c2440e80f9bdd"
                "ff4989c0488b0525858d00488b80b8000000488b88e00000008b500489542428c74424208800000048c7442430000000"
                "004885c9740e4889da41b904000000e8bcf91e00498d7c2440c607c448ffc7c6079048ffc7c607c348ffc7c607a348ff"
                "c7c6072048ffc7c6076e48ffc7c6076848ffc7c607e148ffc7c607ba48ffc7c607b748ffc7c6077448ffc7c6073a48ff"
                "c7c6072048ffc7498b442420488d74244741bd0a00000031d249f7f580c230881648ffce4885c075ee48ffc6488d4c24"
                "474839ce77098a06880748ffc7ebeac6072048ffc7c6076d48ffc7c607c348ffc7c607b348ffc7c6076e48ffc7c60700"
                "48ffc7498d4c2440e8139addff4989c0488b0529848d00488b80b8000000488b88e00000008b500489542428c7442420"
                "9400000048c7442430000000004885c9740e4889da41b904000000e8c0f81e004883c4485f5e415d415cc3cccccccccc"
                "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
                "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
                "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
                "f048ff0518acbc00488b0dc97e8d00c3"
            ),
        ),
        (
            "SleepMode_PickupCounter_Hook",
            0x321EA7,  # đầu xử lý gói -20 (mình nhặt được đồ)
            bytes.fromhex("488b0d2a718e00"),  # mov rcx, [TypeInfo dd]
            bytes.fromhex("e854f200009090"),  # call bộ đếm (đếm + chạy lại lệnh gốc)
        ),
        (
            "SleepMode_OnGUI_Hook",
            0x508FE0,
            bytes.fromhex("e8 ab 73 ff ff"),  # call GameCanvas.paint
            bytes.fromhex("e8 fb 7c e2 ff"),  # call SleepMode_Cave
        ),
        # MOD chỉ nhận FPS 30..240 -> cho phép nhập 1..240. Lúc nạp cài đặt vẫn giữ 30..240:
        # FPS ngủ (<= 5) đã lưu bị bỏ qua -> mở game luôn hiện hình, muốn ngủ thì nhập lại FPS 5.
        ("FPS_Range_Input_Max", 0x5410A8, bytes.fromhex("b9 d2 00 00 00"), bytes.fromhex("b9 ef 00 00 00")),
        ("FPS_Range_Input_Min", 0x5410AD, bytes.fromhex("8d 43 e2"), bytes.fromhex("8d 43 ff")),
    ]

    source_path = bak_path if os.path.exists(bak_path) else dll_path
    with open(source_path, "rb") as f:
        data = bytearray(f.read())

    # Tạo bản sao lưu .bak nếu chưa có và file gốc chưa bị vá
    if not os.path.exists(bak_path):
        first_foff = rva_to_foff(patches[0][1])
        if bytes(data[first_foff : first_foff + len(patches[0][2])]) == patches[0][2]:
            shutil.copy2(dll_path, bak_path)
            print(f"[BACKUP] Đã tạo bản sao lưu gốc tại: {bak_path}")

    for name, rva, expected, replacement in patches:
        foff = rva_to_foff(rva)
        actual = bytes(data[foff : foff + len(expected)])
        if actual == replacement:
            print(f"[SKIP] {name} đã được vá sẵn.")
            continue
        if actual != expected:
            raise RuntimeError(f"[{name}] Sai lệch dữ liệu tại RVA 0x{rva:X}")
        if len(expected) != len(replacement):
            raise RuntimeError(f"[{name}] Độ dài bản vá không khớp!")
        data[foff : foff + len(replacement)] = replacement
        print(f"[OK] Đã vá {name} ({len(replacement)} bytes)")

    try:
        with open(dll_path, "wb") as f:
            f.write(data)
    except PermissionError:
        # Windows cho phép đổi tên DLL đang chạy và tạo file mới vào đúng vị trí cũ
        old_path = dll_path + ".old"
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass
        os.replace(dll_path, old_path)
        with open(dll_path, "wb") as f:
            f.write(data)
        print("[THÔNG BÁO] Game đang mở nên đã ghi sẵn bản vá mới. Hãy khởi động lại NgocRongViet.exe để áp dụng!")

    print(f"[HOÀN TẤT] Đã cập nhật thành công: {dll_path}")
    return dll_path


if __name__ == "__main__":
    try:
        patch_dll()
    except PermissionError:
        print("[LỖI] Không thể ghi đè GameAssembly.dll vì NgocRongViet.exe đang chạy! Hãy tắt game trước khi vá.")
        sys.exit(1)
    except Exception as e:
        print(f"[LỖI] {e}")
        sys.exit(1)
