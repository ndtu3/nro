"""Bảng điều khiển treo game NgocRongViet (kiểu Zang VPS): quản lý mọi cửa sổ game đang chạy trên máy.

- Mỗi game là một dòng: nhân vật, map - khu, HP, MP, CPU, RAM, số món đã nhặt, các cờ MOD.
- Ẩn: giấu cửa sổ khỏi màn hình + taskbar và game thôi vẽ (ép ngủ, cần GameAssembly.dll vá bằng patch_vqmm.py).
- Bật/tắt Tàn sát, Tự nhặt, Tự đánh, Tự hồi sinh cho các dòng đang chọn.
- Tự mở lại game bị thoát (văng / crash); đăng nhập lại nhờ "Tự động đăng nhập" của MOD.

Chạy: run_panel.bat (hoặc python control_panel.py). Đóng bảng thì mọi game đang ẩn được hiện lại.
Không dùng Frida (frida-agent làm game văng trên Windows Server cũ): đọc/ghi thẳng bộ nhớ game bằng
ReadProcessMemory/WriteProcessMemory; việc phải chạy trong game (đổi FPS) do cave trong DLL vá làm.
"""

import ctypes
import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import filedialog, messagebox, ttk

if sys.stdout:  # bản .exe không cửa sổ console thì không có stdout
    sys.stdout.reconfigure(encoding="utf-8")

from auto_helper import find_default_exe_path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# bản .exe (PyInstaller): cấu hình nằm cạnh file .exe
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else BASE_DIR
CONFIG_PATH = os.path.join(APP_DIR, "panel_config.json")
PROCESS_NAME = "NgocRongViet.exe"
GAME_ARGS = ["-screen-fullscreen", "0", "-screen-width", "400", "-screen-height", "240"]
BELOW_NORMAL_PRIORITY_CLASS = 0x4000
FLAG_NAMES = [("ts", "Tàn sát"), ("nhat", "Tự nhặt"), ("ak", "Tự đánh"), ("ahs", "Hồi sinh")]

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.K32EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
kernel32.K32EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
kernel32.K32GetModuleBaseNameW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD]
GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x80, 0x40000
SWP_MOVE_ONLY = 0x0001 | 0x0004 | 0x0010  # NOSIZE | NOZORDER | NOACTIVATE


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                       "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                                       "PagefileUsage", "PeakPagefileUsage")]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD)] + [
        (n, ctypes.c_ulonglong) for n in ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
                                          "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")]


def ft64(f):
    return (f.dwHighDateTime << 32) | f.dwLowDateTime


def system_times():
    idle, kern, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
    return ft64(idle), ft64(kern) + ft64(user)  # kernel đã gồm idle


def process_usage(pid):
    """(thời gian CPU 100ns, RAM MB) của tiến trình, None nếu đã thoát"""
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        t = [wintypes.FILETIME() for _ in range(4)]
        kernel32.GetProcessTimes(h, *[ctypes.byref(x) for x in t])
        pmc = PROCESS_MEMORY_COUNTERS(cb=ctypes.sizeof(PROCESS_MEMORY_COUNTERS))
        kernel32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
        return ft64(t[2]) + ft64(t[3]), pmc.WorkingSetSize / 2**20
    finally:
        kernel32.CloseHandle(h)


def memory_status():
    m = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
    kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return (m.ullTotalPhys - m.ullAvailPhys) / 2**20, m.ullTotalPhys / 2**20


def game_windows():
    """{pid: hwnd} cửa sổ Unity của từng game (kể cả đang bị ẩn)"""
    out = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value == "UnityWndClass":
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in out or user32.IsWindowVisible(hwnd):  # có cửa sổ đang hiện thì ưu tiên nó
                out[pid.value] = hwnd
        return True

    user32.EnumWindows(cb, 0)
    return out


def hide_window(hwnd):
    """Đẩy cửa sổ ra ngoài màn hình + bỏ khỏi taskbar. Không dùng SW_HIDE: cửa sổ ẩn thì Unity ngừng gọi OnGUI,
    mà game này xử lý gói tin server và hoạt ảnh ra chiêu trong OnGUI -> đứng im, không đánh. Trả về để khôi phục."""
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.ShowWindow(hwnd, 0)  # đổi kiểu taskbar chỉ có tác dụng khi ẩn rồi hiện lại
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
    user32.SetWindowPos(hwnd, None, -32000, -32000, 0, 0, SWP_MOVE_ONLY)
    user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
    return r.left, r.top, ex


def show_window(hwnd, saved=None):
    """Đưa cửa sổ game về màn hình. Không có vị trí cũ (bảng mở lại khi game đang ẩn) -> đặt ở góc trên trái."""
    if saved:
        x, y, ex = saved
    else:
        x, y = 100, 100
        ex = (user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
    user32.ShowWindow(hwnd, 0)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)
    user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_MOVE_ONLY)
    user32.ShowWindow(hwnd, 5)  # SW_SHOW
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE (phòng khi đang thu nhỏ)


def load_config():
    beside = os.path.join(APP_DIR, "NgocRongViet.exe")
    cfg = {"exePath": beside if os.path.exists(beside) else find_default_exe_path(), "hiddenFps": 5, "watchdog": False}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)


def list_game_pids():
    """PID các tiến trình NgocRongViet.exe"""
    arr = (wintypes.DWORD * 4096)()
    needed = wintypes.DWORD()
    kernel32.K32EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed))
    out = []
    for pid in arr[: needed.value // 4]:
        exe = PanelApp.exe_of(pid) if pid else None
        if exe and os.path.basename(exe).lower() == PROCESS_NAME.lower():
            out.append(pid)
    return out


# Địa chỉ trong GameAssembly.dll (RVA) - dịch ngược từ client hiện tại, client cập nhật thì phải dò lại
SLOT = {"bh": 0xC08BB8, "fg": 0xC09530, "ft": 0xC09650, "jb": 0xC09E90, "rs": 0xBF61D0}  # ô TypeInfo của class
FLAGS = {"ts": ("rs", 0x10), "nhat": ("rs", 0x40), "ak": ("fg", 0x0), "ahs": ("fg", 0x20)}  # Tàn sát, Tự nhặt, Tự đánh, Tự hồi sinh
CAVE, FPS_APPLY, LOGIC_HOOK = 0x330CE0, 0x331180, 0x5087D5  # cave ngủ / áp FPS / FixedUpdate chạy hoạt ảnh chiêu - xem patch_vqmm.py
D_PICKED, D_FORCE, D_FPS_REQ = 0xEFBD20, 0xEFBD80, 0xEFBD84


class GameMemory:
    """Đọc/ghi bộ nhớ một tiến trình game"""

    def __init__(self, pid):
        self.h = kernel32.OpenProcess(0x0010 | 0x0020 | 0x0008 | 0x0400, False, pid)  # VM_READ/WRITE/OPERATION, QUERY_INFORMATION
        if not self.h:
            raise OSError(f"Không mở được tiến trình {pid} (thử chạy bảng bằng quyền Administrator)")
        self.base = self.module_base("GameAssembly.dll")
        if not self.base:
            kernel32.CloseHandle(self.h)
            raise OSError("Game chưa nạp xong GameAssembly.dll")
        self.saved_fps = None

    def module_base(self, name):
        mods = (ctypes.c_void_p * 1024)()
        needed = wintypes.DWORD()
        if not kernel32.K32EnumProcessModulesEx(self.h, mods, ctypes.sizeof(mods), ctypes.byref(needed), 2):  # LIST_MODULES_64
            return None
        buf = ctypes.create_unicode_buffer(260)
        for m in mods[: needed.value // ctypes.sizeof(ctypes.c_void_p)]:
            if m and kernel32.K32GetModuleBaseNameW(self.h, m, buf, 260) and buf.value.lower() == name.lower():
                return m
        return None

    def read(self, addr, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not addr or not kernel32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
            raise OSError("đọc bộ nhớ lỗi")
        return buf.raw

    def write(self, addr, data):
        if not kernel32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data), None):
            raise OSError("ghi bộ nhớ lỗi")

    def num(self, addr, fmt):
        return struct.unpack(fmt, self.read(addr, struct.calcsize(fmt)))[0]

    def ptr(self, addr):
        return self.num(addr, "<Q")

    def string(self, addr):
        p = self.ptr(addr)
        if not p:
            return ""
        n = self.num(p + 0x10, "<i")
        return self.read(p + 0x14, n * 2).decode("utf-16-le", "replace") if 0 < n < 200 else ""

    def statics(self, cls):
        klass = self.ptr(self.base + SLOT[cls])
        return self.ptr(klass + 0xB8) if klass else 0  # 0 khi class chưa khởi tạo

    def can_hide(self):
        return (self.read(self.base + CAVE, 1) == b"\xe8" and self.read(self.base + FPS_APPLY, 2) == b"\x8b\x05"
                and self.read(self.base + LOGIC_HOOK, 5) == bytes.fromhex("e8e689e2ff"))  # bản có hoạt ảnh chiêu theo logic

    def status(self):
        s = {"ready": False, "canHide": self.can_hide(), "flags": {}}
        if s["canHide"]:
            s["hidden"] = self.read(self.base + D_FORCE, 1) != b"\0"
            s["picked"] = self.num(self.base + D_PICKED, "<Q")
        ft = self.statics("ft")
        s["fps"] = self.num(ft + 0x1A, "<h") if ft else 0
        for key, (cls, off) in FLAGS.items():
            st = self.statics(cls)
            s["flags"][key] = bool(self.read(st + off, 1)[0]) if st else None
        bh, jb = self.statics("bh"), self.statics("jb")
        me = self.ptr(bh + 0xA8) if bh else 0
        if not me or not jb:
            return s  # màn hình đăng nhập / đang tải
        name = self.string(me + 0x190)
        if not name:
            return s
        s.update(ready=True, name=name, hp=self.num(me + 0xD0, "<q"), hpFull=self.num(me + 0x108, "<q"),
                 mp=self.num(me + 0xC8, "<q"), mpFull=self.num(me + 0x110, "<q"), dead=self.num(me + 0x88, "<i") == 14,
                 map=self.string(jb + 0x70), zone=self.num(jb + 0x84, "<i"))
        return s

    def set_flag(self, key, on):
        cls, off = FLAGS[key]
        st = self.statics(cls)
        if st:
            self.write(st + off, b"\x01" if on else b"\x00")

    def set_fps(self, fps):
        ft = self.statics("ft")
        if ft:
            self.write(ft + 0x1A, struct.pack("<h", fps))  # số FPS MOD hiển thị
        self.write(self.base + D_FPS_REQ, struct.pack("<i", fps))  # cave gọi set_targetFrameRate ở lần vẽ tới

    def set_hidden(self, on, fps):
        """Ẩn: ép ngủ (không vẽ gì) + hạ FPS; hiện: thôi ép ngủ + trả FPS cũ"""
        hidden = self.read(self.base + D_FORCE, 1) != b"\0"
        if on:
            if not hidden:
                ft = self.statics("ft")
                self.saved_fps = self.num(ft + 0x1A, "<h") if ft else 60
            self.write(self.base + D_FORCE, b"\x01")
            self.set_fps(fps)
        elif hidden:
            self.write(self.base + D_FORCE, b"\x00")
            self.set_fps(self.saved_fps if self.saved_fps and self.saved_fps > 5 else 60)

    def close(self):
        kernel32.CloseHandle(self.h)


class Game:
    """Một tiến trình game đang theo dõi"""

    def __init__(self, pid, mem, exe):
        self.pid, self.mem, self.exe = pid, mem, exe
        self.hwnd = None
        self.hidden = False
        self.saved_win = None  # (x, y, exstyle) trước khi ẩn
        self.hidden_fps = 0
        self.status = {}
        self.cpu_prev = None
        self.cpu_pct = 0.0
        self.ram_mb = 0.0
        self.closing = False  # tắt bằng bảng -> không tự mở lại


class PanelApp:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.games = {}  # pid -> Game
        self.lock = threading.Lock()
        self.events = queue.Queue()
        self.sys_prev = system_times()
        self.last_relaunch = 0.0
        self.stop = False

        root.title("Bảng điều khiển treo game - NgocRongViet")
        root.geometry("1060x420")
        top = ttk.Frame(root, padding=6)
        top.pack(fill="x")
        self.lbl_machine = ttk.Label(top, text="Máy: ...", font=("Segoe UI", 10, "bold"))
        self.lbl_machine.pack(side="left")
        ttk.Button(top, text="Mở thêm game", command=self.launch_game).pack(side="right")
        ttk.Button(top, text="Chọn file game...", command=self.pick_exe).pack(side="right", padx=4)

        cols = ("pid", "name", "map", "hp", "mp", "cpu", "ram", "picked", "flags", "view")
        heads = ("PID", "Nhân vật", "Map - khu", "HP", "MP", "CPU", "RAM", "Đã nhặt", "Đang bật", "Hiển thị")
        widths = (60, 120, 170, 120, 120, 55, 60, 65, 160, 70)
        self.tree = ttk.Treeview(root, columns=cols, show="headings", selectmode="extended")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w" if c in ("name", "map", "flags") else "center")
        self.tree.pack(fill="both", expand=True, padx=6)

        bar = ttk.Frame(root, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="Dòng đang chọn:").pack(side="left")
        ttk.Button(bar, text="Ẩn", command=lambda: self.set_hidden(self.selected(), True)).pack(side="left", padx=2)
        ttk.Button(bar, text="Hiện", command=lambda: self.set_hidden(self.selected(), False)).pack(side="left", padx=2)
        for key, label in FLAG_NAMES:
            ttk.Button(bar, text=label, command=lambda k=key: self.toggle_flag(k)).pack(side="left", padx=2)
        ttk.Button(bar, text="Tắt game", command=self.kill_selected).pack(side="left", padx=(10, 2))

        bar2 = ttk.Frame(root, padding=(6, 0, 6, 6))
        bar2.pack(fill="x")
        ttk.Button(bar2, text="Ẩn tất cả", command=lambda: self.set_hidden(list(self.games), True)).pack(side="left", padx=2)
        ttk.Button(bar2, text="Hiện tất cả", command=lambda: self.set_hidden(list(self.games), False)).pack(side="left", padx=2)
        ttk.Label(bar2, text="   FPS khi ẩn:").pack(side="left")
        self.var_fps = tk.IntVar(value=self.cfg["hiddenFps"])
        ttk.Spinbox(bar2, from_=3, to=60, width=4, textvariable=self.var_fps, command=self.save_opts).pack(side="left")
        ttk.Label(bar2, text="(5 = nhẹ nhất mà vẫn đánh đủ nhanh; dưới 3 game chạy chậm lại)").pack(side="left", padx=4)
        self.var_watch = tk.BooleanVar(value=self.cfg["watchdog"])
        ttk.Checkbutton(bar2, text="Tự mở lại game bị thoát", variable=self.var_watch, command=self.save_opts).pack(side="right")

        threading.Thread(target=self.poll_loop, daemon=True).start()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(500, self.refresh_ui)

    # ---------- luồng nền: nhận game mới, đọc trạng thái ----------
    def poll_loop(self):
        while not self.stop:
            try:
                self.poll_once()
            except Exception as e:  # không để luồng nền chết vì 1 lỗi lẻ
                self.events.put(("error", str(e)))
            time.sleep(1)

    def poll_once(self):
        pids = list_game_pids()
        for pid in list(self.games):
            if pid not in pids:
                self.events.put(("exited", pid))
        for pid in pids:
            if pid not in self.games:
                try:
                    game = Game(pid, GameMemory(pid), self.exe_of(pid))
                    # bảng mở lại khi game đang ẩn -> nhận lại trạng thái để nút Hiện còn tác dụng
                    if game.mem.can_hide() and game.mem.read(game.mem.base + D_FORCE, 1) != bytes(1):
                        game.hidden, game.hidden_fps = True, max(3, self.cfg["hiddenFps"])
                except OSError:
                    continue  # game vừa mở, chưa nạp xong -> thử lại lần sau
                with self.lock:
                    self.games[pid] = game
        wins = game_windows()
        idle, total = system_times()
        d_total = total - self.sys_prev[1]
        machine_cpu = 100 * (1 - (idle - self.sys_prev[0]) / d_total) if d_total > 0 else 0
        self.sys_prev = (idle, total)
        ncpu = os.cpu_count() or 1
        with self.lock:
            games = list(self.games.values())
        for g in games:
            if g.pid in wins:
                g.hwnd = wins[g.pid]
            usage = process_usage(g.pid)
            if usage:
                cpu, g.ram_mb = usage
                now = time.monotonic()
                if g.cpu_prev:
                    g.cpu_pct = (cpu - g.cpu_prev[0]) / 1e7 / (now - g.cpu_prev[1]) / ncpu * 100
                g.cpu_prev = (cpu, now)
            try:
                if g.hidden:
                    g.mem.set_fps(g.hidden_fps)  # nhắc lại mỗi giây: lệnh đổi FPS có thể lỡ lúc cửa sổ đang ẩn/hiện
                g.status = g.mem.status()
            except OSError:
                pass  # đang đổi màn hình / game đang thoát
        self.events.put(("machine", machine_cpu, *memory_status()))

    @staticmethod
    def exe_of(pid):
        h = kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            return buf.value if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
        finally:
            kernel32.CloseHandle(h)

    # ---------- giao diện ----------
    def refresh_ui(self):
        while not self.events.empty():
            ev = self.events.get()
            if ev[0] == "machine":
                _, cpu, used, total = ev
                self.lbl_machine.config(text=f"Máy: CPU {cpu:.0f}%  |  RAM {used:.0f}/{total:.0f} MB  |  {len(self.games)} game")
            elif ev[0] == "exited":
                self.on_game_exit(ev[1])
            elif ev[0] == "error":
                print("[LỖI]", ev[1])
        with self.lock:
            games = dict(self.games)
        for pid in self.tree.get_children():
            if int(pid) not in games:
                self.tree.delete(pid)
        for pid, g in games.items():
            self.tree_row(g)
        self.root.after(1000, self.refresh_ui)

    def tree_row(self, g):
        s = g.status or {}
        if s.get("ready"):
            name = s["name"] + (" (chết)" if s.get("dead") else "")
            where = f'{s["map"]} - khu {s["zone"]}'
            hp = f'{s["hp"]:,}/{s["hpFull"]:,}'
            mp = f'{s["mp"]:,}/{s["mpFull"]:,}'
        else:
            name, where, hp, mp = "Đang đăng nhập...", "", "", ""
        flags = ", ".join(label for key, label in FLAG_NAMES if (s.get("flags") or {}).get(key))
        picked = "" if s.get("picked") is None else s["picked"]
        view = "Ẩn" if g.hidden else "Hiện"
        vals = (g.pid, name, where, hp, mp, f"{g.cpu_pct:.0f}%", f"{g.ram_mb:.0f} MB", picked, flags, view)
        if self.tree.exists(str(g.pid)):
            self.tree.item(str(g.pid), values=vals)
        else:
            self.tree.insert("", "end", iid=str(g.pid), values=vals)

    def selected(self):
        return [int(i) for i in self.tree.selection()]

    def set_hidden(self, pids, hide):
        if not pids:
            return
        fps = max(3, min(60, self.var_fps.get()))
        for pid in pids:
            g = self.games.get(pid)
            if not g:
                continue
            if hide and not g.mem.can_hide():
                messagebox.showwarning("Ẩn game", "GameAssembly.dll chưa vá bản mới (chạy patch_vqmm.bat rồi mở lại game).")
                return
            if g.hwnd and hide and not g.hidden:
                g.saved_win = hide_window(g.hwnd)
            elif g.hwnd and not hide:
                show_window(g.hwnd, g.saved_win)  # luôn kéo cửa sổ về, kể cả khi bảng không nhớ vị trí cũ
                g.saved_win = None
            g.hidden = hide
            g.hidden_fps = fps
            try:
                g.mem.set_hidden(hide, fps)
            except OSError:
                pass  # game vừa thoát

    def toggle_flag(self, key):
        pids = self.selected()
        if not pids:
            return
        first = (self.games[pids[0]].status.get("flags") or {}).get(key)
        for pid in pids:
            g = self.games.get(pid)
            if g:
                try:
                    g.mem.set_flag(key, not first)
                except OSError:
                    pass

    def kill_selected(self):
        pids = self.selected()
        if not pids or not messagebox.askyesno("Tắt game", f"Tắt {len(pids)} game đang chọn?"):
            return
        for pid in pids:
            g = self.games.get(pid)
            if g:
                g.closing = True
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)

    def on_game_exit(self, pid):
        with self.lock:
            g = self.games.pop(pid, None)
        if g:
            g.mem.close()
        if g and not g.closing and self.var_watch.get() and g.exe and time.monotonic() - self.last_relaunch > 30:
            self.last_relaunch = time.monotonic()  # chặn mở dồn khi game văng liên tục
            print(f"[MỞ LẠI] Game PID {pid} đã thoát, đang mở lại")
            self.launch_game(g.exe)

    def launch_game(self, exe=None):
        exe = exe or self.cfg["exePath"]
        if not os.path.exists(exe):
            messagebox.showerror("Mở game", f"Không thấy file game:\n{exe}\nBấm 'Chọn file game...'")
            return
        subprocess.Popen([exe, *GAME_ARGS], cwd=os.path.dirname(exe), creationflags=BELOW_NORMAL_PRIORITY_CLASS)

    def pick_exe(self):
        path = filedialog.askopenfilename(title="Chọn NgocRongViet.exe", filetypes=[("NgocRongViet", "*.exe")])
        if path:
            self.cfg["exePath"] = os.path.abspath(path)
            save_config(self.cfg)

    def save_opts(self):
        try:
            self.cfg["hiddenFps"] = max(3, min(60, self.var_fps.get()))
        except tk.TclError:
            return
        self.cfg["watchdog"] = self.var_watch.get()
        save_config(self.cfg)

    def on_close(self):
        # hiện lại game đang ẩn, không thì đóng bảng xong là mất cửa sổ game
        self.stop = True
        for g in list(self.games.values()):
            if g.hidden:
                if g.hwnd:
                    show_window(g.hwnd, g.saved_win)
                try:
                    g.mem.set_hidden(False, 0)
                except OSError:
                    pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    PanelApp(root)
    root.mainloop()
