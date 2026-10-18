import ctypes
from ctypes import wintypes
import os
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from patch_vqmm import patch_dll

# ==========================================
# CẤU HÌNH WIN32 API CHUẨN 64-BIT CHO UNITY
# ==========================================
user32 = ctypes.WinDLL("user32", use_last_error=True)

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_ACTIVATE = 0x0006
WA_ACTIVE = 1

INPUT_KEYBOARD = 1
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002
MAPVK_VK_TO_VSC = 0

VK_F8 = 0x77  # Phím tắt bật/tắt nhanh

# Bảng mã Virtual-Key giải mã trực tiếp từ global-metadata.dat của NgocRongViet.exe
VK_MAP = {
    "1": 0x31,
    "2": 0x32,
    "3": 0x33,
    "4": 0x34,
    "5": 0x35,
    "6": 0x36,
    "7": 0x37,
    "8": 0x38,
    "Enter": 0x0D,
    "Space": 0x20,
    "x": 0x58,  # Mở Menu MOD
    "t": 0x54,  # Tàn sát
    "n": 0x4E,  # Tự động nhặt vật phẩm
    "h": 0x48,  # Tự động hồi sinh
    "u": 0x55,  # Tự động cập nhật khu
    "e": 0x45,  # Mở tab đệ tử
    "f": 0x46,  # Dùng Porata
    "c": 0x43,  # Dùng Capsule
    "m": 0x4D,  # Mở bảng Khu vực
    "b": 0x42,  # Đổi Focus Boss
    "j": 0x4A,  # Dịch map trái
    "k": 0x4B,  # Dịch map giữa
    "l": 0x4C,  # Dịch map phải
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


def find_default_exe_path():
    """Tự động tìm NgocRongViet.exe ở các vị trí phổ biến trên mọi máy tính."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, "NgocRongViet.exe"),
        os.path.join(os.path.dirname(script_dir), "NgocRongViet.exe"),
        os.path.expanduser(r"~\Downloads\NgocRongViet.exe"),
        os.path.expanduser(r"~\Desktop\NgocRongViet.exe"),
        os.path.expanduser(r"~\Downloads\NgocRongViet\NgocRongViet.exe"),
        os.path.expanduser(r"~\Desktop\NgocRongViet\NgocRongViet.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return os.path.abspath(path)
    return os.path.expanduser(r"~\Downloads\NgocRongViet.exe")


def find_game_window(window_title="NgocRongViet"):
    """Tìm HWND của cửa sổ game Unity NgocRongViet."""
    hwnd = user32.FindWindowW("UnityWndClass", window_title)
    if not hwnd:
        hwnd = user32.FindWindowW(None, window_title)
    return hwnd


def is_game_foreground(hwnd):
    if not hwnd:
        return False
    return user32.GetForegroundWindow() == hwnd


def focus_game_window(hwnd):
    """Đưa cửa sổ NgocRongViet lên tiền cảnh để Unity nhận bàn phím."""
    if not hwnd:
        return
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.05)


def make_lparam(vk, is_keyup=False):
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    lparam = 1 | (scan << 16)
    if is_keyup:
        lparam |= (1 << 30) | (1 << 31)
    return lparam


def send_key_to_unity(hwnd, key_name, force_focus=False):
    """Gửi phím chuẩn tới Unity (kết hợp cả VK, ScanCode và WM_CHAR)."""
    if not hwnd or key_name not in VK_MAP:
        return
    vk = VK_MAP[key_name]
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)

    if force_focus and not is_game_foreground(hwnd):
        focus_game_window(hwnd)

    if is_game_foreground(hwnd):
        # Gửi cả Virtual-Key + Hardware ScanCode chuẩn 64-bit cho Unity InputLegacyModule
        inp_down = INPUT(type=INPUT_KEYBOARD)
        inp_down.union.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=0, time=0, dwExtraInfo=None)

        inp_up = INPUT(type=INPUT_KEYBOARD)
        inp_up.union.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)

        user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
        time.sleep(0.04)
        user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))
    else:
        # Gửi thông điệp kích hoạt cửa sổ + phím ngầm
        lparam_down = make_lparam(vk, is_keyup=False)
        lparam_up = make_lparam(vk, is_keyup=True)
        user32.PostMessageW(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
        user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lparam_down)
        if len(key_name) == 1:
            user32.PostMessageW(hwnd, WM_CHAR, ord(key_name.lower()), lparam_down)
        time.sleep(0.04)
        user32.PostMessageW(hwnd, WM_KEYUP, vk, lparam_up)


class NgocRongAutoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NgocRongViet Auto & Giải Mã MOD")
        self.root.geometry("530x685+180+70")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        self.exe_path = find_default_exe_path()
        self.is_running = False
        self.hwnd = 0
        self.last_triggered = {}

        self._build_ui()
        self.root.after(100, self._force_show_window)
        self._start_background_threads()

    def _force_show_window(self):
        self.root.update_idletasks()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        tk_hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        if tk_hwnd:
            user32.ShowWindow(tk_hwnd, 9)
            user32.ShowWindow(tk_hwnd, 5)
            user32.SetForegroundWindow(tk_hwnd)

    def _toggle_topmost(self):
        self.root.attributes("-topmost", self.topmost_var.get())

    def _send_quick_mod_key(self, key_name):
        if not self.hwnd:
            messagebox.showwarning("Chưa mở game", "Hãy mở cửa sổ NgocRongViet trước!")
            return
        threading.Thread(target=send_key_to_unity, args=(self.hwnd, key_name, True), daemon=True).start()

    def _send_chat_command(self, cmd_text):
        """Tự động mở khung chat trong game, nhập lệnh (ví dụ: vqmm) và nhấn Enter."""
        if not self.hwnd:
            messagebox.showwarning("Chưa mở game", "Hãy mở cửa sổ NgocRongViet trước!")
            return

        def _worker():
            focus_game_window(self.hwnd)
            time.sleep(0.1)
            # Nhấn Enter để mở khung chat
            send_key_to_unity(self.hwnd, "Enter", force_focus=True)
            time.sleep(0.15)
            for ch in cmd_text:
                vk = VK_MAP.get(ch.lower(), ord(ch.upper()))
                scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
                inp_down = INPUT(type=INPUT_KEYBOARD)
                inp_down.union.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=0, time=0, dwExtraInfo=None)
                inp_up = INPUT(type=INPUT_KEYBOARD)
                inp_up.union.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
                user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
                time.sleep(0.03)
                user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))
                time.sleep(0.03)
            time.sleep(0.1)
            # Nhấn Enter lần 2 để gửi lệnh
            send_key_to_unity(self.hwnd, "Enter", force_focus=True)

        threading.Thread(target=_worker, daemon=True).start()

    def apply_vqmm_patch_ui(self):
        """Vá lỗi Rương phụ VQMM trực tiếp từ giao diện trên máy mới."""
        dll_candidate = None
        if self.exe_path and os.path.exists(self.exe_path):
            cand = os.path.join(os.path.dirname(self.exe_path), "GameAssembly.dll")
            if os.path.exists(cand):
                dll_candidate = cand
        try:
            patched_path = patch_dll(dll_candidate)
            messagebox.showinfo(
                "Vá lỗi thành công",
                f"Đã vá lỗi kẹt Rương phụ VQMM thành công tại:\n{patched_path}\n\n"
                "Hãy đóng và mở lại game NgocRongViet.exe để áp dụng!",
            )
        except PermissionError:
            messagebox.showerror(
                "Game đang chạy",
                "Không thể ghi đè GameAssembly.dll vì NgocRongViet.exe đang mở!\n"
                "Hãy tắt cửa sổ game trước rồi bấm Vá lỗi lại.",
            )
        except Exception as e:
            messagebox.showerror("Lỗi khi vá GameAssembly.dll", str(e))

    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

        # 1. Trạng thái kết nối
        status_frame = ttk.LabelFrame(self.root, text="Trạng thái Client NgocRongViet")
        status_frame.pack(fill="x", **pad)

        self.status_label = ttk.Label(
            status_frame, text="Đang tìm cửa sổ NgocRongViet...", foreground="#d9534f", font=("Segoe UI", 9, "bold")
        )
        self.status_label.pack(side="left", padx=8, pady=5)

        self.launch_btn = ttk.Button(status_frame, text="Mở Game", command=self.launch_game)
        self.launch_btn.pack(side="right", padx=6, pady=5)

        self.patch_btn = ttk.Button(status_frame, text="Vá Lỗi VQMM", command=self.apply_vqmm_patch_ui)
        self.patch_btn.pack(side="right", padx=4, pady=5)

        self.topmost_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self.root,
            text="Ghim bảng Auto luôn nổi trên màn hình",
            variable=self.topmost_var,
            command=self._toggle_topmost,
        ).pack(anchor="w", padx=14, pady=2)

        # 2. Bảng Tính Năng MOD Có Sẵn Trong Client
        mod_frame = ttk.LabelFrame(
            self.root, text="Tính năng MOD trong NgocRongViet (Bấm là kích hoạt trong game)"
        )
        mod_frame.pack(fill="x", **pad)

        vqmm_btn = tk.Button(
            mod_frame,
            text="BẬT / TẮT AUTO VÒNG QUAY MAY MẮN & TỰ NHẬN RƯƠNG PHỤ (Lệnh: vqmm)",
            bg="#fd7e14",
            fg="white",
            font=("Segoe UI", 9, "bold"),
            command=lambda: self._send_chat_command("vqmm"),
        )
        vqmm_btn.grid(row=0, column=0, columnspan=3, sticky="ew", padx=4, pady=4)

        mod_buttons = [
            ("Mở Menu MOD (Phím X)", "x"),
            ("Bật/Tắt Tàn Sát (Phím T)", "t"),
            ("Auto Nhặt Đồ (Phím N)", "n"),
            ("Auto Hồi Sinh (Phím H)", "h"),
            ("Dùng Bông Tai (Phím F)", "f"),
            ("Dùng Capsule (Phím C)", "c"),
            ("Đổi Khu Vực (Phím M)", "m"),
            ("Tab Đệ Tử (Phím E)", "e"),
            ("Qua Map Trái (Phím J)", "j"),
            ("Qua Map Giữa (Phím K)", "k"),
            ("Qua Map Phải (Phím L)", "l"),
            ("Focus Boss (Phím B)", "b"),
        ]

        for idx, (btn_text, key_str) in enumerate(mod_buttons):
            r = (idx // 3) + 1
            c = idx % 3
            btn = ttk.Button(mod_frame, text=btn_text, command=lambda k=key_str: self._send_quick_mod_key(k))
            btn.grid(row=r, column=c, sticky="ew", padx=4, pady=3)
        for c in range(3):
            mod_frame.columnconfigure(c, weight=1)

        # 3. Auto Kỹ Năng & Đậu Thần (Ô 1 -> 8)
        skill_frame = ttk.LabelFrame(self.root, text="Auto Liên Tục Kỹ Năng & Đậu Thần (Phím 1 -> 8)")
        skill_frame.pack(fill="x", **pad)

        self.skill_vars = []
        default_intervals = ["500", "2000", "3000", "5000", "8000", "10000", "15000", "30000"]

        for i in range(8):
            row = i // 2
            col = (i % 2) * 3
            key_str = str(i + 1)

            enabled_var = tk.BooleanVar(value=(i == 0))
            interval_var = tk.StringVar(value=default_intervals[i])

            ttk.Checkbutton(skill_frame, text=f"Ô {key_str}", variable=enabled_var).grid(
                row=row, column=col, sticky="w", padx=(10, 2), pady=3
            )
            ttk.Entry(skill_frame, textvariable=interval_var, width=8, justify="right").grid(
                row=row, column=col + 1, padx=2, pady=3
            )
            ttk.Label(skill_frame, text="ms").grid(row=row, column=col + 2, sticky="w", padx=(0, 18), pady=3)

            self.skill_vars.append((key_str, enabled_var, interval_var))

        # 4. Auto Tiện ích
        extra_frame = ttk.LabelFrame(self.root, text="Auto Lặp Lại (Khi cửa sổ Game đang được chọn)")
        extra_frame.pack(fill="x", **pad)

        self.extra_vars = []
        extras = [
            ("Tự động Đánh / Chọn (Phím Enter)", "Enter", True, "600"),
            ("Tự động Nhặt đồ / Nhảy (Phím Space)", "Space", False, "1500"),
        ]

        for idx, (label_txt, key_str, def_checked, def_ms) in enumerate(extras):
            en_var = tk.BooleanVar(value=def_checked)
            ms_var = tk.StringVar(value=def_ms)

            ttk.Checkbutton(extra_frame, text=label_txt, variable=en_var).grid(
                row=idx, column=0, sticky="w", padx=10, pady=3
            )
            ttk.Entry(extra_frame, textvariable=ms_var, width=8, justify="right").grid(
                row=idx, column=1, padx=4, pady=3
            )
            ttk.Label(extra_frame, text="ms").grid(row=idx, column=2, sticky="w", pady=3)

            self.extra_vars.append((key_str, en_var, ms_var))

        # 5. Nút điều khiển Bật / Tắt
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill="x", padx=10, pady=8)

        self.toggle_btn = tk.Button(
            ctrl_frame,
            text="BẮT ĐẦU AUTO LẶP PHÍM (Phím tắt: F8)",
            bg="#28a745",
            fg="white",
            font=("Segoe UI", 11, "bold"),
            height=2,
            command=self.toggle_auto,
        )
        self.toggle_btn.pack(fill="x")

        note_lbl = ttk.Label(
            self.root,
            text="Lưu ý: Sau khi bật F8, hãy CLICK CHUỘT VÀO CỬA SỔ GAME để cửa sổ game được chọn (Unity chỉ nhận phím khi đang chọn cửa sổ game).",
            foreground="#d9534f",
            font=("Segoe UI", 8, "bold"),
            wraplength=500,
        )
        note_lbl.pack(padx=10, pady=2)

    def launch_game(self):
        if not os.path.exists(self.exe_path):
            selected = filedialog.askopenfilename(
                title="Chọn file NgocRongViet.exe",
                filetypes=[("NgocRongViet", "NgocRongViet.exe"), ("Executable", "*.exe")],
            )
            if not selected:
                return
            self.exe_path = os.path.abspath(selected)
        try:
            subprocess.Popen([self.exe_path], cwd=os.path.dirname(self.exe_path))
        except Exception as e:
            messagebox.showerror("Lỗi khi mở game", str(e))

    def toggle_auto(self):
        self.is_running = not self.is_running
        if self.is_running:
            self.last_triggered.clear()
            self.toggle_btn.config(text="ĐANG CHẠY AUTO - BẤM ĐỂ DỪNG (F8)", bg="#dc3545")
            if self.hwnd:
                focus_game_window(self.hwnd)
        else:
            self.toggle_btn.config(text="BẮT ĐẦU AUTO LẶP PHÍM (Phím tắt: F8)", bg="#28a745")

    def _auto_loop(self):
        f8_was_down = False
        while True:
            f8_state = user32.GetAsyncKeyState(VK_F8)
            is_f8_down = (f8_state & 0x8000) != 0
            if is_f8_down and not f8_was_down:
                self.root.after(0, self.toggle_auto)
            f8_was_down = is_f8_down

            current_hwnd = find_game_window("NgocRongViet")
            if current_hwnd != self.hwnd:
                self.hwnd = current_hwnd
                if self.hwnd:
                    self.root.after(
                        0,
                        lambda h=self.hwnd: self.status_label.config(
                            text=f"Đã kết nối NgocRongViet (HWND: {h})", foreground="#28a745"
                        ),
                    )
                else:
                    self.root.after(
                        0,
                        lambda: self.status_label.config(
                            text="Chưa mở NgocRongViet (Bấm 'Mở Game')", foreground="#d9534f"
                        ),
                    )

            if self.is_running and self.hwnd:
                now_ms = time.perf_counter() * 1000.0
                all_items = self.skill_vars + self.extra_vars
                for key_str, enabled_var, interval_var in all_items:
                    if enabled_var.get():
                        try:
                            interval = max(150.0, float(interval_var.get().strip()))
                        except ValueError:
                            interval = 1000.0
                        last_time = self.last_triggered.get(key_str, 0.0)
                        if now_ms - last_time >= interval:
                            self.last_triggered[key_str] = now_ms
                            send_key_to_unity(self.hwnd, key_str, force_focus=False)

            time.sleep(0.02)

    def _start_background_threads(self):
        t = threading.Thread(target=self._auto_loop, daemon=True)
        t.start()


if __name__ == "__main__":
    root = tk.Tk()
    app = NgocRongAutoApp(root)
    root.mainloop()
