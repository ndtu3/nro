"""Bảng điều khiển treo game NgocRongViet (kiểu Zang VPS): quản lý mọi cửa sổ game đang chạy trên máy.

- Mỗi game là một dòng: nhân vật, map - khu, HP, MP, CPU, RAM, số món đã nhặt, các cờ MOD.
- Ẩn: giấu cửa sổ khỏi màn hình + taskbar và game thôi vẽ (ép ngủ, cần GameAssembly.dll vá bằng patch_vqmm.py).
- Bật/tắt Tàn sát, Tự nhặt, Tự đánh, Tự hồi sinh cho các dòng đang chọn.
- Tự mở lại game bị thoát (văng / crash); đăng nhập lại nhờ "Tự động đăng nhập" của MOD.

Chạy: run_panel.bat (hoặc python control_panel.py). Đóng bảng thì mọi game đang ẩn được hiện lại.
"""

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from tkinter import filedialog, messagebox, ttk

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".deps"))  # frida cài bởi run_panel.bat
try:
    import frida
except ImportError:
    print("[LỖI] Chưa cài frida. Chạy run_panel.bat để tự cài.")
    sys.exit(1)

from auto_helper import find_default_exe_path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_PATH = os.path.join(BASE_DIR, "panel_agent.js")
CONFIG_PATH = os.path.join(BASE_DIR, "panel_config.json")
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
    """{pid: hwnd} các cửa sổ Unity đang hiện"""
    out = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value == "UnityWndClass" and user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out[pid.value] = hwnd
        return True

    user32.EnumWindows(cb, 0)
    return out


def load_config():
    cfg = {"exePath": find_default_exe_path(), "hiddenFps": 10, "watchdog": False}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)


class Game:
    """Một tiến trình game đã gắn agent"""

    def __init__(self, pid, session, script, exe):
        self.pid, self.session, self.script, self.exe = pid, session, script, exe
        self.hwnd = None
        self.hidden = False
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
        self.device = frida.get_local_device()
        self.agent_src = open(AGENT_PATH, encoding="utf-8").read()
        self.sys_prev = system_times()
        self.last_relaunch = 0.0
        self.stop = False
        self.rpc_pool = ThreadPoolExecutor(max_workers=4)

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
        ttk.Spinbox(bar2, from_=1, to=60, width=4, textvariable=self.var_fps, command=self.save_opts).pack(side="left")
        ttk.Label(bar2, text="(thấp = nhẹ máy nhưng đánh chậm; 10 là vừa)").pack(side="left", padx=4)
        self.var_watch = tk.BooleanVar(value=self.cfg["watchdog"])
        ttk.Checkbutton(bar2, text="Tự mở lại game bị thoát", variable=self.var_watch, command=self.save_opts).pack(side="right")

        threading.Thread(target=self.poll_loop, daemon=True).start()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(500, self.refresh_ui)

    # ---------- luồng nền: gắn game mới, đọc trạng thái ----------
    def attach(self, pid, exe):
        session = self.device.attach(pid)
        script = session.create_script(self.agent_src)
        script.load()
        game = Game(pid, session, script, exe)
        session.on("detached", lambda reason, *_: self.events.put(("detached", pid)))
        return game

    def poll_loop(self):
        while not self.stop:
            try:
                self.poll_once()
            except Exception as e:  # không để luồng nền chết vì 1 lỗi lẻ
                self.events.put(("error", str(e)))
            time.sleep(1)

    def poll_once(self):
        procs = {p.pid: p for p in self.device.enumerate_processes() if p.name.lower() == PROCESS_NAME.lower()}
        for pid in procs:
            if pid not in self.games:
                try:
                    game = self.attach(pid, self.exe_of(pid))
                except Exception as e:
                    self.events.put(("error", f"Không gắn được PID {pid}: {e}"))
                    continue
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
            if not g.hidden and g.pid in wins:
                g.hwnd = wins[g.pid]
            usage = process_usage(g.pid)
            if usage:
                cpu, g.ram_mb = usage
                now = time.monotonic()
                if g.cpu_prev:
                    g.cpu_pct = (cpu - g.cpu_prev[0]) / 1e7 / (now - g.cpu_prev[1]) / ncpu * 100
                g.cpu_prev = (cpu, now)
            try:
                # game thoát giữa chừng có thể làm lời gọi treo -> giới hạn 3s để luồng nền không kẹt
                g.status = self.rpc_pool.submit(g.script.exports_sync.status).result(timeout=3)
            except Exception:
                pass  # game đang thoát; sự kiện detached sẽ dọn
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
            elif ev[0] == "detached":
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
            name, where, hp, mp = ("Lỗi agent" if s.get("error") else "Đang đăng nhập..."), "", "", ""
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

    def run_bg(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def set_hidden(self, pids, hide):
        if not pids:
            return
        fps = max(1, min(60, self.var_fps.get()))
        for pid in pids:
            g = self.games.get(pid)
            if not g:
                continue
            if hide and not (g.status or {}).get("canHide", True):
                messagebox.showwarning("Ẩn game", "GameAssembly.dll chưa vá bản mới (chạy patch_vqmm.bat rồi mở lại game).")
                return
            if g.hwnd:
                user32.ShowWindow(g.hwnd, 0 if hide else 5)  # SW_HIDE / SW_SHOW
            g.hidden = hide
            self.run_bg(lambda g=g: g.script.exports_sync.set_hidden(hide, fps))

    def toggle_flag(self, key):
        pids = self.selected()
        if not pids:
            return
        first = (self.games[pids[0]].status.get("flags") or {}).get(key)
        for pid in pids:
            g = self.games.get(pid)
            if g:
                self.run_bg(lambda g=g: g.script.exports_sync.set_flag(key, not first))

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
            self.cfg["hiddenFps"] = max(1, min(60, self.var_fps.get()))
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
                    user32.ShowWindow(g.hwnd, 5)
                try:
                    g.script.exports_sync.set_hidden(False, 0)
                    time.sleep(0.3)  # chờ FixedUpdate chạy lệnh trước khi tách agent
                except Exception:
                    pass
            try:
                g.session.detach()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    PanelApp(root)
    root.mainloop()
