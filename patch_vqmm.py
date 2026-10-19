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
        # Vá lệnh jmp để thoát hàm cập nhật lastTime, chờ nhịp kế tiếp (500ms sau) mới gửi getItem(2, 0).
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

    with open(dll_path, "wb") as f:
        f.write(data)
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
