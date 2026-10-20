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
        # 7. Bảng Điều Khiển Săn Cụm BOSS tự động (Menu MOD -> Boss -> Bảng Săn Cụm BOSS):
        # Tự động XMAP tới map, dò khu 0..14, dịch chuyển & tiêu diệt lần lượt cả cụm Boss, tự nhặt đồ rồi chuyển sang cụm tiếp theo.
        (
            "BossCluster_Cave_OnBossClick",
            0x398CE0,
            bytes.fromhex("40534883ec20803d30948b0000488bd97513488d0d27358600e822c4cfffc60518948b00014885db743883bb90000000007d2f80bb95020000057526488b8b900100004885c97422488b15f13486004533c0e85972380084c00f94c04883c4205bc332c04883c4205bc3e8e1c5cfffcc"),
            bytes.fromhex("c6462001c6462101c6465001c6465101488d05092bb60080780200750cc6400201c640013fc6402001c6400300894804c7400800000000c7400c00000000e9cd7e0c00909090909042e1baa36e672053c4836e2043e1bba56d0a424f5353203e3e009090909090909090909090909090"),
        ),
        (
            "BossCluster_Menu_Button_Label",
            0x3938DA,
            bytes.fromhex("488b3d1f93860080b80003000000480f453de8928600"),
            bytes.fromhex("488d0d47540000e84a71d7ff4889c790909090909090"),
        ),
        (
            "BossCluster_Perform_Route_0x700",
            0x396441,
            bytes.fromhex("0f8762baffff"),
            bytes.fromhex("0f879ad6ffff"),
        ),
        (
            "BossCluster_Perform_Menu_Handler",
            0x393AE1,
            bytes.fromhex("488b0d686f87004439b1e0000000750ce8da18d0ff488b0d536f8700488b81b80000004438b0000300000f85870100004439b1e0000000750ce8b118d0ff488b0d2a6f8700488b81b8000000488b88f80200004885c90f841d2f0000488b05e43b87004533c0488b90b8000000488b12e84a6b380084c00f85ed000000488b0deb6e87004439b1e0000000750ce85d18d0ff488b0dd66e8700488b81b8000000488b90f80200004885d20f84c92e0000443972100f84b00000004439b1e0000000750ce82718d0ff488b0da06e8700488b81b8000000c6800003000001488b054b6987004439b0e0000000750f488bc8e8fa17d0ff488b0533698700488b80b8000000488b88b00200004885c90f84662e0000488b15dd8f86004533c94533c0e88a95fdff488b05036987004533c94c8b0579d98600488b88b8000000488b052b6e8700488b99b0020000488b90b8000000488b0d4e0c8700488b92f8020000e83a3f3800e92eecffff488b05be6887004439b0e0000000750f488bc8e86d17d0ff488b05a6688700488b80b8000000488b88b00200004885c90f84d92d0000488b15407087004533c94533c0e8fd94fdffe911e2ffff4439b1e0000000750ce82a17d0ff488b0da36d8700488b81b80000004488b000030000488b054e6887004439b0e0000000750f488bc8e8fd16d0ff488b0536688700488b80b8000000488b88b00200004885c90f84692d0000488b15088f86004533c94533c0e88d94fdff"),
            bytes.fromhex("4c8d25187db60041807c240200751b41c64424020141c64424013f41c64424200141c7442404ffffffff83ff360f84880000008d8700f9ffff83f8060f8786e3ffff41fe442420750541fe44242085c0755d418034240141c64424030041c7442404ffffffff41803c24007439c6462001c6462101c6465001c6465101488b05eb6e8700488b80b8000000c6401801488b0599698700488b80b8000000c680b801000001eb1531c9e802d10c00eb0c8d48ffb201d2e24130542401488b0d6d708700e83817d0ff4989c64889c131d2e82b0607004531ed4c8d3db30000004c89f9e8696ed7ff4889c34585ed7507410fb60424eb0f410fb6442401418d4dffd3e883e001488d0d7400000085c07407488d0d72000000e8346ed7ff4889d94889c24531c0e8964138004889c7488b0d5c658700e8c716d0ff4889c34889c14889fa458d85000700004531c9e8dfc2f2ff4c89f14889da4531c0e8918ce7ff49ffc741807fff0075f641ffc54183fd070f8c69ffffffe9c6fcffff90909090900a5b54e1baaf745d000a5b42e1baad745d004175746f2053c4836e2043e1bba56d005469e1bb837520c490e1bb99692053c3a174205468e1bba70043e1bba56d204669646520c490e1baa1692043610043e1bba56d20426f7373204e617070610043e1bba56d20416e64726f69640043e1bba56d2058c3aa6e2042e1bb8d2048756e6700426c61636b20476f6b752026204b68c3a16300909090909090909090909090"),
        ),
        (
            "BossCluster_FocusBoss_HP_Current",
            0x398A8A,
            bytes.fromhex("488b0dbf1f8700488b98c802000083b9e0000000007505e82ac9cfff"),
            bytes.fromhex("488b98c80200004885db746a4883bbd0000000007e60909090909090"),
        ),
        (
            "BossCluster_FocusBoss_HP_Loop",
            0x398BD0,
            bytes.fromhex("488b0d791e870083b9e0000000007505e8ebc7cfff"),
            bytes.fromhex("4885db742f4883bbd0000000000f8e980000009090"),
        ),
        (
            "BossCluster_AutoAttack_Teleport",
            0x398746,
            bytes.fromhex("488b0d632787008b706c8b6b6c83b9e0000000007505e86fcccfff2bf533d28bcee8240bdfff488b8b300200004885c90f84940000008b493803c93bc17d56"),
            bytes.fromhex("4883b8d0000000000f8e8700000083b890000000007d288b486c8b507089ce2b736c83c62883fe50770d89d62b737083c62883fe5076084531c0e8fbf6ffff"),
        ),
        (
            "BossCluster_ClickBossList_Hook",
            0x39574A,
            bytes.fromhex("e8a1b40c00"),
            bytes.fromhex("e891350000"),
        ),
        (
            "BossCluster_Cave_MatchCluster",
            0x3993F0,
            bytes.fromhex("4883ec28803d268d8b00007513488d0d4c0c8700e817bdcfffc605118d8b0001488b0d390c870083b9e0000000007505e8abbfcfff33c9e854cfedff4885c0747d4883b8d0000000007e54488b0d0e0c870083b9e0000000007505e880bfcfff33c9e829cfedff4885c0745280b8de05000000752a488b0de40b870083b9e0000000007505e856bfcfff33c9e8ffceedff4885c0742883b8880000000e751a33c9e85ab208004885c0741333d2488bc84883c428e9e72209004883c428c3e87dbecfffcccccccccccccccccccccccccc"),
            bytes.fromhex("5356574883ec2031d2e8027738004885c0743e4889c6488d1d430000000fb63b81ffff0000007429488d4b01e80f16d7ff4889f14889c24531c0e811ee370084c0751348ffc348ffc3807bff0075f7ebccbf0500000089f84883c4205f5e5bc30073e1bb912000007469e1bb837520c491e1bb996900016669646500026b756b7500026de1baad70000272616d626f0003616e64726f696400036bc3b472c3aa00037069630003706f6300036b696e67000478c3aa6e000462e1bb8d2068756e6700ff90909090909090909090909090"),
        ),
        (
            "BossCluster_Cave_FindNextCluster",
            0x52D540,
            bytes.fromhex("4883ec28803d5d527200007513488d0d5cbf6d00e8c77bb6ffc60548527200014c8b0549bf6d00498b90b80000008b4a08394a0c745d488bc28bd12b500cc1e2028950144c8b0525bf6d00498b80b80000008b5014035010895010488b150ebf6d00488b82b80000008b4810c1f90403480c89480c488b15f4be6d00488b82b80000008b481083e10f8948104c8b05ddbe6d00498b90b80000008b4a18394a1c745d488bc28bd12b501cc1e2028950244c8b05b9be6d00498b80b80000008b5024035020895020488b15a2be6d00488b82b80000008b4820c1f90403481c89481c488b1588be6d00488b82b80000008b482083e10f8948204c8b0571be6d00498b80b80000008b4834ffc1894834488b0d5bbe6d00488b81b80000008378340575354533c044894034488b1540be6d00488b82b80000008b4838ffc1894838488b0d2abe6d00488b81b8000000837838027e04448940384883c428c3cccccccc"),
            bytes.fromhex("535657415441554883ec204c8d25aee29c00488b05f7d26d0083b8e000000000750f4889c1e8667eb6ff488b05dfd26d00488b80b8000000488b70204885f60f84800000004889f131d2e8a1f3cdff89c7ffcf78704889f189fa4531c0e8bef3cdff4889c34885db74e7448b6b204585ed7ede418a44242038432474d4488b4b104885c974cbe825bee6ff410fb64c24010fa3c173bb4489e9e83700000041c64424030045896c240441c74424080000000041c744240c000000004489e931d2e8eb35f3ff4883c420415d415c5f5e5bc3909090905356574883ec2089cb488b052bd26d00488b80b8000000488b70204885f674364889f131d2e8f1f2cdff89c7ffcf78264889f189fa4531c0e80ef3cdff4885c074ea39582075e5488d0d9de19c008a4920884824ebd64883c4205f5e5bc3909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090"),
        ),
        (
            "BossCluster_Cave_Update_PartC",
            0x38D710,
            bytes.fromhex("40534883ec20803de1498c0000488bd97513488d0da7d28700e8f279d0ffc605c9498c0001488b0d94d2870083b9e000000000750ce8867cd0ff488b0d7fd28700488b81b8000000488b104885d2746b486383e00000003b4218736548837cc22000744f83b9e000000000750ce84e7cd0ff488b0d47d28700488b81b8000000488b084885c97433486383e00000003b4118732d488b54c1204885d2741d48837a2000740e837b70007408b0014883c4205bc332c04883c4205bc3e8607bd0ffcce84a7bd0ffcccc"),
            bytes.fromhex("41807c24030074304889f1492b4c24184881f97c1500000f8c80000000418b4c2404e8defe190041c64424030041c7442404ffffffffeb654889f1492b4c24104881f9b00400007c544989742410418b44240c83f80f7c0b41c7442404ffffffffeb3affc0418944240c418b7c24088d470183f80f7c0231c0418944240831c9e85b6f09004885c074134889c189fa41b8ffffffff4531c9e863b609004889e931d24883c420415c5f5e5b5de9cf4501009090909090909090909090909090909090909090909090"),
        ),
        (
            "BossCluster_Cave_Update_PartB",
            0x52AB40,
            bytes.fromhex("40534883ec20803d517c720000488bd97513488d0d37e96d00e8c2a5b6ffc605397c720001488b0d24e96d0083b9e000000000750ce856a8b6ff488b0d0fe96d00488b81b8000000488b104885d2746b486383e00000003b4218736548837cc22000744f83b9e000000000750ce81ea8b6ff488b0dd7e86d00488b81b8000000488b084885c97433486383e00000003b4118732d488b54c1204885d2741d48837a2000740e837b70007408b0014883c4205bc332c04883c4205bc3e830a7b6ffcce81aa7b6ffcccc"),
            bytes.fromhex("488b05c9f96d00488b80b8000000488b98f00000004885db0f84b22be6ff4889d931d2e8c81dceff89c7ffcf0f889e2be6ff4889d989fa4531c0e8e11dceff4885c074e683b890000000007ddd4883b8d0000000007ed3488b88900100004885c974c766817914100174bf668379142474b841c6442403014989742418e9eb2be6ff90909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090"),
        ),
        (
            "BossCluster_Cave_Update_PartA",
            0x38E910,
            bytes.fromhex("4883ec28803dee378c00007513488d0dccc08700e8f767d0ffc605d9378c00014c8b05b9c08700498b90b80000008b4a08394a0c745d488bc28bd12b500cc1e2028950144c8b0595c08700498b80b80000008b5014035010895010488b157ec08700488b82b80000008b4810c1f90403480c89480c488b1564c08700488b82b80000008b481083e10f8948104c8b054dc08700498b90b80000008b4a18394a1c745d488bc28bd12b501cc1e2028950244c8b0529c08700498b80b80000008b5024035020895020488b1512c08700488b82b80000008b4820c1f90403481c89481c488b15f8bf8700488b82b80000008b482083e10f8948204c8b05e1bf8700498b80b80000008b4834ffc1894834488b0dcbbf8700488b81b80000008378340575354533c044894034488b15b0bf8700488b82b80000008b4838ffc1894838488b0d9abf8700488b81b8000000837838027e04448940384883c428c3cccccccc"),
            bytes.fromhex("5553565741544883ec204889cd4c8d25dcceb60041807c240200751b41c64424020141c64424013f41c64424200141c7442404ffffffff41803c24007425c6452001c6452101c6455001c6455101488b05abbb8700488b80b8000000c680b801000001418b5c240485db7d2f41803c24000f848300000031c9e8a22c07004889c1492b4c24104881f9e80300007c6b4989442410e897eb1900eb5f31c9e87e2c07004889c6488b0574778600488b80b80000004885c0740c80380074074989742410eb36488b0575c88700488b80b800000039587c0f8455c119004889f1492b4c24104881f9dc0500007c0e498974241089d931d2e8e6210d00e99eedffff90909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090909090"),
        ),
        (
            "BossCluster_Update_Hook",
            0x39D224,
            bytes.fromhex("e9674b0000"),
            bytes.fromhex("e9e716ffff"),
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
