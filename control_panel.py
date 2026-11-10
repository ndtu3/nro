"""Bảng điều khiển treo game, Tự làm Nhiệm Vụ Chính Tuyến & Săn Cụm BOSS NgocRongViet (kiểu Zang VPS).

- Mỗi game là một dòng: nhân vật, map - khu, HP, MP, CPU, RAM, đã nhặt, hành trang SKH, đã lọc, nhiệm vụ chính tuyến, săn boss, các cờ MOD.
- Ẩn: giấu cửa sổ khỏi màn hình + taskbar và game thôi vẽ (ép ngủ, cần GameAssembly.dll vá bằng patch_vqmm.py).
- Bật/tắt Tàn sát, Tự nhặt, Tự đánh, Tự hồi sinh, Lọc đồ rác (giữ SKH), Tự làm Nhiệm Vụ Chính Tuyến, Săn Cụm BOSS cho các dòng đang chọn.
- Tự mở lại game bị thoát (văng / crash); đăng nhập lại nhờ "Tự động đăng nhập" của MOD.

Chạy: run_panel.bat (hoặc ControlPanel.exe). Đóng bảng thì mọi game đang ẩn được hiện lại.
Không dùng Frida (frida-agent làm game văng trên Windows Server cũ): đọc/ghi thẳng bộ nhớ game bằng
ReadProcessMemory/WriteProcessMemory; gọi hàm trong luồng chính của game qua Command delegate gadget.
"""

import ctypes
import json
import os
import queue
import re
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import unicodedata
from ctypes import wintypes
from tkinter import filedialog, messagebox, ttk

if sys.stdout:  # bản .exe không cửa sổ console thì không có stdout
    sys.stdout.reconfigure(encoding="utf-8")

from auto_helper import find_default_exe_path
from patch_vqmm import get_vqmm_v2_patches, patch_dll

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# bản .exe (PyInstaller): cấu hình nằm cạnh file .exe
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else BASE_DIR
CONFIG_PATH = os.path.join(APP_DIR, "panel_config.json")
BOSS_CONFIG_PATH = os.path.join(APP_DIR, "boss_clusters.json")
SEEN_BOSS_PATH = os.path.join(APP_DIR, "boss_seen.txt")
PROCESS_NAME = "NgocRongViet.exe"
GAME_ARGS = ["-screen-fullscreen", "0", "-screen-width", "400", "-screen-height", "240"]
BELOW_NORMAL_PRIORITY_CLASS = 0x4000
FLAG_NAMES = [("ts", "Tàn sát"), ("nhat", "Tự nhặt"), ("ak", "Tự đánh"), ("ahs", "Hồi sinh"), ("al", "Tự ĐN")]
RMS_DIR = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    "AppData", "LocalLow", "NgocRongViet", "NgocRongViet",
)
AUTO_ITEM_DEFS = [
    ("cn", "Cuồng nộ", [381], ["cuồng nộ"], True),
    ("cn2", "Cuồng nộ 2", [1150], ["cuồng nộ 2"], False),
    ("co", "Cỏ may mắn (4 lá)", [1635], ["cỏ bốn lá", "cỏ may mắn"], True),
    ("cg", "Cơm gà MM", [1481], ["cơm gà may mắn"], False),
    ("bh", "Bổ huyết", [382], ["bổ huyết"], False),
    ("bh2", "Bổ huyết 2", [1152], ["bổ huyết 2"], False),
    ("bk", "Bổ khí", [383], ["bổ khí"], False),
    ("bk2", "Bổ khí 2", [1151], ["bổ khí 2"], False),
    ("gx", "Giáp Xên", [384], ["giáp xên bọ hung"], False),
    ("gx2", "Giáp Xên 2", [1153], ["giáp xên bọ hung 2"], False),
    ("cs", "Cuồng Sát", [1304], ["cuồng sát"], False),
    ("x2", "Bình x2 Exp", [1900], ["bình tăng x2 exp"], False),
    ("bua2", "Bùa x2 Đệ", [1628], ["bùa x2 tnsm đệ tử"], False),
    ("bua3", "Bùa x3 Đệ", [1985], ["bùa x3 tnsm đệ tử"], False),
    ("ad", "Ẩn danh", [385, 1154], ["ẩn danh", "ẩn danh 2"], False),
    ("xh", "Xuyên Huyết", [1306], ["xuyên huyết"], False),
    # thức ăn: mỗi món 1 ô - hiệu ứng thức ăn chỉ giữ được 1 món, tích cả 5 thì MOD ăn liền cả 5
    ("ta1", "Bánh Pudding", [663], ["bánh pudding"], False),
    ("ta2", "Xúc xích", [664], ["xúc xích"], False),
    ("ta3", "Kem dâu", [665], ["kem dâu"], False),
    ("ta4", "Mì ly", [666], ["mì ly"], False),
    ("ta5", "Sushi", [667], ["sushi"], False),
]

DEFAULT_BOSS_CFG = {
    "maxZone": 15,
    "zoneDelayMs": 15000,
    "zoneLoadMs": 2500,
    "zoneTimeoutMs": 5000,
    "arriveDelayMs": 2500,
    "waitNextMs": 10000,
    "teleport": True,
    "fleeHpPct": 0,
    "resumeHpPct": 90,
    "autoRevive": True,
    "reviveMaxPerTarget": 0,
    "reviveDelayMs": 3000,
    "reviveRetryMs": 6000,
    "reviveAttemptsPerDeath": 3,
    "lootMaxMs": 12000,
    "xmapRetryMs": 90000,
    "badMapMs": 600000,
    "useBuffSkills": True,
    "buffSkills": [6, 12, 13, "khiên năng lượng"],  # Thái dương hạ san, Đẻ trứng, Biến khỉ, Khiên
    "clusters": [
        {"name": "Tiểu Đội Sát Thủ (Nappa)", "enabled": False, "maps": ["63-83"], "members": ["Số 4", "Số 3", "Số 2", "Số 1", "Tiểu đội trưởng"]},
        {"name": "Tiểu Đội Sát Thủ (Namếc)", "enabled": True, "excludeMaps": ["63-83"], "members": ["Số 4", "Số 3", "Số 2", "Số 1", "Tiểu đội trưởng"]},
        {"name": "Fide Đại Ca (Núi Khỉ Vàng)", "enabled": False, "maps": [80], "members": ["Fide đại ca 1", "Fide đại ca 2", "Fide đại ca 3", "Fide Đại Ca *"]},
        {"name": "Fide Vàng", "enabled": False, "members": ["Fide Vàng", "Fide Gold"]},
        {"name": "Black Fide", "enabled": False, "members": ["Black Fide"]},
        {"name": "King Cold", "enabled": False, "members": ["King Cold"]},
        {"name": "Android 19 & Dr.Kôrê", "enabled": False, "members": ["Android 19", "Dr.Kôrê"]},
        {"name": "Android 13-14-15", "enabled": False, "members": ["Android 13", "Android 14", "Android 15"]},
        {"name": "Pic Poc King Kong", "enabled": False, "members": ["Pic", "Poc", "King Kong"]},
        {"name": "Android 21", "enabled": False, "members": ["Android 21 *"]},
        {"name": "Xên Bọ Hung", "enabled": False, "members": ["Xên Bọ Hung *", "Xên hoàn thiện"]},
        {"name": "Xên con", "enabled": False, "members": ["Xên con *"]},
        {"name": "Siêu Bọ Hung", "enabled": False, "members": ["Siêu bọ hung"]},
        {"name": "Bojack", "enabled": True, "members": ["Bojack", "Bido", "Zangya", "Kogu", "Bujin"]},
        {"name": "Super Bojack", "enabled": False, "members": ["Super Bojack"]},
        {"name": "Cooler", "enabled": False, "members": ["Cooler", "Cooler 2"]},
        {"name": "Golden Cooler", "enabled": False, "members": ["Golden Cooler"]},
        {"name": "Black Goku", "enabled": False, "members": ["Black Goku", "Super Black Goku"]},
        {"name": "Fusion Zamasu", "enabled": False, "members": ["Fusion Zamasu"]},
        {"name": "Kid Bư", "enabled": False, "members": ["Kid Bư"]},
        {"name": "Baby", "enabled": False, "members": ["Baby *"]},
        {"name": "Kamin Oren", "enabled": False, "members": ["Kamin", "Oren", "Kamioren"]},
        {"name": "Cumber", "enabled": False, "members": ["Cumber"]},
        {"name": "Janemba Quỷ Đỏ", "enabled": False, "members": ["Janemba Quỷ Đỏ"]},
        {"name": "Ác Ma Picolo", "enabled": False, "members": ["Ác Ma Picolo"]},
        {"name": "Boss Nappa (Kuku, Mập đầu đinh, Rambo)", "enabled": False, "members": ["Kuku", "Mập đầu đinh", "Rambo"]},
    ],
}

STATE_SHORT = {
    "IDLE": "Chờ boss",
    "TRAVEL": "XMAP",
    "ARRIVE": "Vào map",
    "SCAN": "Dò khu",
    "FIGHT": "Đánh boss",
    "LOOT": "Nhặt đồ",
    "FLEE": "Chạy trốn",
    "RETURN": "Quay lại",
}

QUEST_MENU_WORDS = ["nhiệm vụ", "nhận", "đồng ý", "báo cáo", "hoàn thành", "ok", "tiếp tục", "thách đấu"]

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
kernel32.VirtualProtectEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
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
    return ft64(idle), ft64(kern) + ft64(user)


def process_usage(pid):
    """(thời gian CPU 100ns, RAM MB) của tiến trình, None nếu đã thoát"""
    h = kernel32.OpenProcess(0x1000, False, pid)
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
            if pid.value not in out or user32.IsWindowVisible(hwnd):
                out[pid.value] = hwnd
        return True

    user32.EnumWindows(cb, 0)
    return out


def hide_window(hwnd):
    """Đẩy cửa sổ ra ngoài màn hình + bỏ khỏi taskbar."""
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.ShowWindow(hwnd, 0)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
    user32.SetWindowPos(hwnd, None, -32000, -32000, 0, 0, SWP_MOVE_ONLY)
    user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
    return r.left, r.top, ex


def show_window(hwnd, saved=None):
    """Đưa cửa sổ game về màn hình."""
    if saved:
        x, y, ex = saved
    else:
        x, y = 100, 100
        ex = (user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
    user32.ShowWindow(hwnd, 0)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)
    user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_MOVE_ONLY)
    user32.ShowWindow(hwnd, 5)
    user32.ShowWindow(hwnd, 9)


def read_rms_string(name):
    p = os.path.join(RMS_DIR, name)
    if not os.path.exists(p):
        return ""
    try:
        with open(p, "rb") as fh:
            data = fh.read()
        if len(data) >= 2:
            n = struct.unpack(">H", data[:2])[0]
            return data[2 : 2 + n].decode("utf-8", "replace")
    except Exception:
        pass
    return ""


def write_rms_string(name, text):
    os.makedirs(RMS_DIR, exist_ok=True)
    raw = (text or "").encode("utf-8")
    with open(os.path.join(RMS_DIR, name), "wb") as fh:
        fh.write(struct.pack(">H", len(raw)) + raw)


def load_rms_accounts():
    """Đọc danh sách tài khoản {user: pass} từ Rms accManager + acc/pass của game"""
    out = {}
    mgr = read_rms_string("accManager")
    for part in mgr.split("|"):
        if "$" in part:
            u, pw = part.split("$", 1)
            if u.strip():
                out[u.strip()] = pw.strip()
    u0, p0 = read_rms_string("acc").strip(), read_rms_string("pass").strip()
    if u0 and (u0 not in out or p0):
        out[u0] = p0
    return out


LOGIN_LOCK = threading.Lock()
BOSS_APPEAR_RE = re.compile(r"boss (.+?) vừa xuất hiện tại (.+?)(?: khu vực.*)?$")


def read_rms_login():
    """Đọc (username, password) hiện tại từ Rms acc/pass (hoặc accManager)"""
    u = read_rms_string("acc").strip()
    pw = read_rms_string("pass").strip()
    if u and not pw:
        pw = load_rms_accounts().get(u, "")
    return u, pw


def save_rms_login(username, password):
    """Lưu tài khoản & mật khẩu vào Rms của game (acc, pass, accManager) để đăng nhập ngay"""
    username = (username or "").strip()
    password = (password or "").strip()
    if not username:
        return
    write_rms_string("acc", username)
    write_rms_string("pass", password)
    mgr = read_rms_string("accManager")
    entries = []
    seen = False
    for part in mgr.split("|"):
        if "$" in part:
            u, pw = part.split("$", 1)
            if u == username:
                entries.append(f"{username}${password}")
                seen = True
            elif u:
                entries.append(f"{u}${pw}")
    if not seen:
        entries.append(f"{username}${password}")
    write_rms_string("accManager", "|".join(entries))


def load_config():
    beside = os.path.join(APP_DIR, "NgocRongViet.exe")
    rms_accs = load_rms_accounts()
    default_user = read_rms_string("acc").strip()
    default_pass = read_rms_string("pass").strip() or rms_accs.get(default_user, "")
    cfg = {
        "exePath": beside if os.path.exists(beside) else find_default_exe_path(),
        "hiddenFps": 5,
        "watchdog": True,
        "filterJunk": True,
        "lastUser": default_user,
        "lastPass": default_pass,
        "accounts": rms_accs,
        "loginHideBg": True,
        "loginAutoItem": False,
        "autoItems": {k: d for k, _, _, _, d in AUTO_ITEM_DEFS},
        "customAutoItems": "",
        "swordMinNew": 5,
        "swordMaxLevel": 6,
        "swordMinFinal": 30,
        "eggDelayMs": 120,
        "eggAutoBuyStone": True,
        "eggAutoBuyEgg": True,
        "eggAutoUseEgg": True,
        "eggTargetDays": 0,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded.get("accounts"), dict):
                rms_accs.update(loaded["accounts"])
            loaded["accounts"] = rms_accs
            auto_items = dict(cfg["autoItems"])
            if isinstance(loaded.get("autoItems"), dict):
                auto_items.update(loaded["autoItems"])
            loaded["autoItems"] = auto_items
            cfg.update(loaded)
            for k in ("coffinThreads", "coffinQty", "coffinDelayMs", "autoCoffin"):  # tính năng đã bỏ
                cfg.pop(k, None)
        except Exception:
            pass
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)


def load_boss_config():
    cfg = json.loads(json.dumps(DEFAULT_BOSS_CFG))
    for path in (BOSS_CONFIG_PATH, os.path.join(BASE_DIR, "boss_clusters.json")):
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    cfg.update(json.load(fh))
                break
            except Exception:
                pass
    for c in cfg.get("clusters", []):
        if c.get("name") == "Fide Đại Ca":
            c["name"] = "Fide Đại Ca (Núi Khỉ Vàng)"
            c["maps"] = [80]
            c["members"] = ["Fide đại ca 1", "Fide đại ca 2", "Fide đại ca 3", "Fide Đại Ca *"]
    return cfg


def save_boss_config(cfg):
    with open(BOSS_CONFIG_PATH, "w", encoding="utf-8") as fh:
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


# Địa chỉ trong GameAssembly.dll (RVA)
SLOT = {
    "bh": 0xC08BB8, "bj": 0xC08BD8, "dd": 0xC08FD8, "dg": 0xC09038,
    "eq": 0xC09390, "fa": 0xC09490, "fe": 0xC09510, "fg": 0xC09530,
    "fq": 0xC09610, "ft": 0xC09650, "fz": 0xC096B0, "hu": 0xC09B70,
    "hx": 0xC09BB0, "if": 0xC09C30, "jb": 0xC09E90,
    "rs": 0xBF61D0, "ru": 0xBF61F0, "rv": 0xBF6210, "autobuy": 0xBF62B0,
    "Main": 0xC05320, "String": 0xC07728,
}
FLAGS = {"ts": ("rs", 0x10), "nhat": ("rs", 0x40), "ak": ("fg", 0x0), "ahs": ("fg", 0x20), "al": ("fg", 0x21)}
SKH_OPT_IDS = set(range(127, 145)) | {224, 225}
CAVE, FPS_APPLY, LOGIC_HOOK = 0x330CE0, 0x331180, 0x5087D5
D_PICKED, D_FORCE, D_FPS_REQ, D_ACTION_BUF = 0xEFBD20, 0xEFBD80, 0xEFBD84, 0xEFBDA0

# RVA các hàm trong GameAssembly.dll dùng cho Săn Cụm BOSS, Nhiệm Vụ, Đăng Nhập, Tự dùng Item & Kiếm Z
RVA_CLASS_INIT = 0x953D0
RVA_XMAP_START = 0x46E5F0
RVA_XMAP_STOP = 0x46E690
RVA_CHANGE_ZONE = 0x230C70
RVA_CHAR_MOVE = 0x230DF0
RVA_OPEN_ZONE_UI = 0x232000
RVA_REVIVE_HERE = 0x2335F0
RVA_RETURN_HOME = 0x233490
RVA_USE_SKILL_NOT_FOCUS = 0x4D5620
RVA_SELECT_SKILL_SRV = 0x231C50
RVA_PANEL_HIDE = 0x1EDFA0
RVA_TELEPORT = 0x537F10
RVA_REQUEST_CHANGE_MAP = 0x230B20  # hx.dql(): Service.requestChangeMap (gói -23) - xin qua cửa map đang đứng
RVA_CMD_PERFORM = 0x4892A0         # Command.performAction - kích hoạt lệnh cửa map (waypoint.popup.command) như XMAP sa.hrw
# map XMAP của MOD không biết đường: map đích -> (map kề XMAP tới được, cửa cần đi qua ở map kề)
EXTRA_ROUTES = {170: (0, "giữa")}  # Đồng Bằng Aru: cửa giữa map Làng Aru (Làng Aru ở bên phải Nhà Gôhan)
RVA_FOCUS_TO = 0x19AA70
RVA_OPEN_NPC_MENU = 0x232340
RVA_MENU_CLOSE = 0x50D360
RVA_MENU_SELECT = 0x50D680
RVA_USE_ITEM_BY_TID = 0x536B90
RVA_MOD_INSTANCE = 0x549BA0
RVA_LOGIN_RELOAD_RMS = 0x51BDB0
RVA_LOGIN_DO_LOGIN = 0x51CC40
RVA_LOAD_ACC_MGR = 0x52DAF0
RVA_AUTO_ITEM_SET = 0x52F820
RVA_AUTOBUY_ALLOC = 0x477510
RVA_AUTOBUY_START = 0x477AF0
RVA_AUTOBUY_DELAY_IMM = 0x476CAA
RVA_AUTOBUY_CMP_INS = 0x476C3D
NPC_ID_BUNMA_HOME = 37            # Bunma tại Nhà Bunma (map 101: Cửa hàng bán Trứng Linh Thú / 99 Đá Linh Lực)
NPC_ID_KARIN = 18                 # Thần Mèo Karin (hỗ trợ song song cùng Bunma)
NPC_ID_MABU_EGG = 50              # Trứng Mabu / Trứng Linh Thú tại Nhà Bunma (map 101)
NPC_ID_EGG = 80                   # Trứng Linh Thú (ổ ấp trứng Linh Thú dự phòng)
EGG_SHOP_NPC_IDS = (NPC_ID_BUNMA_HOME, NPC_ID_KARIN)
EGG_INCUBATOR_NPC_IDS = (NPC_ID_MABU_EGG, NPC_ID_EGG)
MAP_ID_SIEU_THI = 84              # Map Siêu Thị (kề bên phải Nhà Bunma map 101)
MAP_ID_NHA_BUNMA = 101            # Map Nhà Bunma (nơi đặt và ấp Trứng Linh Thú)
ITEM_ID_DA_LINH_LUC = 700         # Đá Linh Lực (tid = 700)
ITEM_ID_THOI_VANG = 457           # Thỏi vàng (tid = 457)


def norm_str(s):
    return unicodedata.normalize("NFC", s or "").lower().strip()


def in_map_list(lst, map_id):
    for m in lst:
        if isinstance(m, int):
            if m == map_id:
                return True
        else:
            parts = str(m).split("-")
            try:
                if len(parts) == 2:
                    if int(parts[0]) <= map_id <= int(parts[1]):
                        return True
                elif int(parts[0]) == map_id:
                    return True
            except ValueError:
                pass
    return False


def cluster_allows_map(c, map_id):
    if c.get("maps") and not in_map_list(c["maps"], map_id):
        return False
    if c.get("excludeMaps") and in_map_list(c["excludeMaps"], map_id):
        return False
    return True


# boss con do boss chính sinh ra, phải hạ trước (boss chính bất tử khi còn con) - dùng khi cụm không ghi "minions"
# boss chính -> boss con nó sinh ra; tra theo tên boss trong cụm (cụm "Xên Bọ Hung" có Xên hoàn thiện), không theo tên cụm
DEFAULT_MINIONS = {"xên hoàn thiện": ["Xên con *"], "siêu bọ hung": ["Xên con *"]}


def cluster_minions(cluster):
    if cluster.get("minions"):
        return cluster["minions"]
    out = []
    for boss, minions in DEFAULT_MINIONS.items():
        if any(member_matches(m, boss) for m in cluster.get("members", [])):
            out += [x for x in minions if x not in out]
    return out


def member_matches(m, name_norm):
    k = norm_str(m)
    if not k.endswith("*"):
        return name_norm == k
    prefix = k[:-1].strip()
    return name_norm == prefix or name_norm.startswith(prefix + " ")


def boss_name_of_quest(title):
    m = re.match(r"^(tiêu diệt|diệt|đánh bại|hạ gục|hạ|thách đấu)\s+(.+)$", (title or "").strip(), re.I)
    return m.group(2).strip() if m else None


def parse_zone_cooldown(text):
    """Trích xuất số giây hồi đổi khu từ thông báo server (trả về float giây hoặc None)"""
    t = norm_str(text)
    if not t or t.startswith("|") or "sao" in t:
        return None
    if not any(w in t for w in ("khu", "chờ", "đợi", "còn", "sau", "nhanh")):
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:giây|giay|s\b)", t)
    if not m and "khu" in t:
        m = re.search(r"(?:trong|còn|chờ|đợi|sau)\s*(\d+(?:[.,]\d+)?)", t)
    if m:
        sec = float(m.group(1).replace(",", "."))
        if 0 < sec <= 180:
            return sec
    return None


# ---------- Kiếm Z: đổi ở Tổ Sư Kaio (Thánh địa Kaio), nâng cấp + mua nguyên liệu ở NPC Mai (Hành tinh ngục tù 2) ----------
ITEM_ID_KIEM_Z = 1986
ITEM_ID_TINH_THE = 1987
ITEM_ID_DA_NGUC_TU = 1988
NPC_ID_TO_SU_KAIO = 43
NPC_ID_OSIN = 44
NPC_ID_MAI = 76
MAP_ID_KAIO = 48                  # Hành tinh Kaio (Thần Vũ Trụ đưa xuống Thánh địa Kaio)
NPC_ID_THAN_VU_TRU = 20
MAP_ID_THANH_DIA_KAIO = 50
MAP_ID_BILL = 154
MAP_ID_NGUC_TU_1 = 155
MAP_ID_NGUC_TU_2 = 166
OPT_ID_SUC_DANH = 50              # "Sức đánh+#%"
OPT_ID_CAP = 72                   # "Cấp #" (đã nâng +N)
SWORD_COST_TINH_THE = 99          # đổi 1 Kiếm Z vĩnh viễn: 99 Tinh thể + 100 Thỏi vàng
SWORD_COST_THOI_VANG = 100
SWORD_BUY_QTY = 10000             # mỗi lần hết nguyên liệu thì mua 10000 cái (1 Thỏi vàng / cái)
SWORD_MIN_MAT = 200               # Tinh thể / Đá ngục tù còn dưới ngần này thì đi mua (mỗi lần nâng tốn vài cái mỗi loại)


def sword_action(dmg, level, min_new=5, max_level=6, min_final=30):
    """Việc cần làm với 1 Kiếm Z: "vứt" (mới đổi mà sức đánh < min_new%, hoặc đã +max_level mà sức đánh <= min_final%),
    "giữ" (đã +max_level và sức đánh > min_final%), còn lại "nâng"."""
    if level >= max_level:
        return "giữ" if dmg > min_final else "vứt"
    if level <= 0 and dmg < min_new:
        return "vứt"
    return "nâng"


class GameMemory:
    """Đọc/ghi bộ nhớ và gọi hàm trên luồng chính của một tiến trình game"""

    def __init__(self, pid):
        self.h = kernel32.OpenProcess(0x0010 | 0x0020 | 0x0008 | 0x0400, False, pid)
        if not self.h:
            raise OSError(f"Không mở được tiến trình {pid} (thử chạy bảng bằng quyền Administrator)")
        self.base = self.module_base("GameAssembly.dll")
        if not self.base:
            kernel32.CloseHandle(self.h)
            raise OSError("Game chưa nạp xong GameAssembly.dll")
        try:
            dd_st = self.statics("dd")
        except OSError:
            dd_st = 0
        if not dd_st:
            kernel32.CloseHandle(self.h)
            raise OSError("Game chưa khởi tạo xong GameCanvas")
        self.saved_fps = None
        self.panel_auto_ids = set()  # item bảng đã thêm vào Auto Item của MOD (chỉ được xoá những item này)
        self.panel_auto_flag = False  # cờ tự dùng item do bảng bật (người chơi chưa bật trong game)
        self.auto_item_tried = {}  # id -> lúc gọi fg.cnf gần nhất
        self.dropped_junk = 0
        self.call_lock = threading.Lock()
        self.apply_vqmm_v2_hotpatch()

    def apply_vqmm_v2_hotpatch(self):
        """Vá nóng bản sửa lỗi Auto VQMM (tránh bấm nhầm 'Đến Kaio' & giữ nhịp Rương phụ) trực tiếp vào bộ nhớ"""
        try:
            for _, rva, _, new_bytes in get_vqmm_v2_patches():
                addr = self.base + rva
                if self.read(addr, len(new_bytes)) != new_bytes:
                    old_prot = wintypes.DWORD()
                    if kernel32.VirtualProtectEx(self.h, ctypes.c_void_p(addr), len(new_bytes), 0x40, ctypes.byref(old_prot)):
                        self.write(addr, new_bytes)
                        kernel32.VirtualProtectEx(self.h, ctypes.c_void_p(addr), len(new_bytes), old_prot.value, ctypes.byref(old_prot))
            fg_st = self.statics("fg")
            if fg_st and self.read(fg_st + 0x4A, 1) == b"\x00" and self.num(fg_st + 0x58, "<i") == -1:
                self.write(fg_st + 0x58, struct.pack("<i", 0))
        except Exception:
            pass

    def module_base(self, name):
        mods = (ctypes.c_void_p * 1024)()
        needed = wintypes.DWORD()
        if not kernel32.K32EnumProcessModulesEx(self.h, mods, ctypes.sizeof(mods), ctypes.byref(needed), 2):
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

    def klass(self, cls):
        p = self.ptr(self.base + SLOT[cls])
        return p if p > 0x100000000 else 0

    def statics(self, cls, init=False):
        kl = self.klass(cls)
        if not kl:
            return 0
        st = self.ptr(kl + 0xB8)
        if not st and init:
            self.call_fn(RVA_CLASS_INIT, kl, 0)
            st = self.ptr(kl + 0xB8)
        return st

    def vec_items(self, vec):
        if not vec:
            return []
        al = self.ptr(vec + 0x10)
        if not al:
            return []
        n = self.num(al + 0x18, "<i")
        arr = self.ptr(al + 0x10)
        if not arr or n <= 0 or n > 500:
            return []
        out = []
        for i in range(n):
            e = self.ptr(arr + 0x20 + 8 * i)
            if e:
                out.append(e)
        return out

    def int_array(self, p):
        if not p:
            return []
        n = self.num(p + 0x18, "<i")
        if n <= 0 or n > 200:
            return []
        raw = self.read(p + 0x20, 4 * n)
        return list(struct.unpack(f"<{n}i", raw))

    def short_array(self, p):
        if not p:
            return []
        n = self.num(p + 0x18, "<i")
        if n <= 0 or n > 200:
            return []
        raw = self.read(p + 0x20, 2 * n)
        return list(struct.unpack(f"<{n}h", raw))

    def str_array(self, p):
        if not p:
            return []
        n = self.num(p + 0x18, "<i")
        if n <= 0 or n > 200:
            return []
        return [self.string(p + 0x20 + 8 * i) for i in range(n)]

    def read_quest_info(self, me):
        """Đọc thông tin nhiệm vụ chính tuyến hiện tại của nhân vật"""
        t = self.ptr(me + 0x238)
        if not t:
            return None
        step = self.num(t + 0x10, "<i")
        q_id = self.num(t + 0x20, "<h")
        progress = self.num(t + 0x48, "<h")
        titles = self.str_array(self.ptr(t + 0x38))
        counts = self.short_array(self.ptr(t + 0x18))
        dg_st = self.statics("dg")
        npcs = self.int_array(self.ptr(dg_st + 0x1B0)) if dg_st else []
        maps = self.int_array(self.ptr(dg_st + 0x1B8)) if dg_st else []
        q = {"id": q_id, "step": step, "total": len(titles), "progress": progress}
        if step < 0 or step >= len(titles):
            q.update(done=True, title="", npc=-1, map=-1, need=-1)
            return q
        title = ""
        for i in range(step, -1, -1):
            if titles[i]:
                title = titles[i]
                break
        npc_raw = npcs[step] if step < len(npcs) else -1
        npc = struct.unpack("<b", struct.pack("<B", npc_raw & 0xFF))[0] if step < len(npcs) else -1
        map_id = maps[step] if step < len(maps) else -1
        need = counts[step] if step < len(counts) else -1
        q.update(done=False, title=title, npc=npc, map=map_id, need=need)
        return q

    def gadget_cmd(self, msgdlg):
        """Command mượn làm "nút bấm" để chạy lệnh trên luồng chính: của hộp thoại -> GameScr -> màn hình chọn server.
        Mất kết nối xong game chỉ còn màn hình chọn server (không hộp thoại, không GameScr) -> phải lấy nút của nó."""
        cmd = self.ptr(msgdlg + 0x10)
        if cmd:
            return cmd
        dg_st = self.statics("dg")
        gscr = self.ptr(dg_st + 0x18) if dg_st else 0
        cmd = self.ptr(gscr + 0x48) if gscr else 0
        if not cmd:
            dd_st = self.statics("dd")
            srv = self.ptr(dd_st + 0x398) if dd_st else 0
            cmd = self.ptr(srv + 0x40) if srv else 0  # hu.ong (Command)
            arr = self.ptr(srv + 0x30) if (srv and not cmd) else 0  # hu.oml (Command[])
            n = self.num(arr + 0x18, "<i") if arr else 0
            for i in range(min(max(n, 0), 16)):
                cmd = self.ptr(arr + 0x20 + 8 * i)
                if cmd:
                    break
        if cmd:
            self.write(msgdlg + 0x10, struct.pack("<Q", cmd))
        return cmd

    def call_fn(self, fn_rva_or_va, rcx_arg=0, rdx_arg=0):
        """Gọi hàm fn(rcx, rdx) ngay trên luồng chính Unity qua Command+0x90 Action delegate gadget"""
        with self.call_lock:
            dd_st, main_st = self.statics("dd"), self.statics("Main")
            if not (dd_st and main_st):
                return False
            msgdlg = self.ptr(dd_st + 0x108)
            panel = self.ptr(dd_st + 0xD8)
            if not (msgdlg and panel):
                return False
            cmd = self.gadget_cmd(msgdlg)
            if not cmd:
                return False

            fn_va = fn_rva_or_va if fn_rva_or_va >= self.base else (self.base + fn_rva_or_va)
            buf_addr = self.base + D_ACTION_BUF
            cmd_klass = self.ptr(cmd)
            # Đặt bit 0 = 1 (đã đánh dấu GC) kèm Il2CppClass* hợp lệ tại buf_addr+0x00 để GC (0x80090) bỏ qua ngay, không bao giờ crash tại 0x800BA
            self.write(buf_addr + 0x00, struct.pack("<Q", (cmd_klass | 1) if cmd_klass else 1))
            self.write(buf_addr + 0x18, struct.pack("<Q", fn_va))
            self.write(buf_addr + 0x28, struct.pack("<Q", rdx_arg & 0xFFFFFFFFFFFFFFFF))
            self.write(buf_addr + 0x40, struct.pack("<Q", rcx_arg & 0xFFFFFFFFFFFFFFFF))

            old_dlg = self.ptr(dd_st + 0x100)
            old_id = self.num(cmd + 0x38, "<i")
            old_listener = self.ptr(cmd + 0x30)
            self.write(cmd + 0x30, struct.pack("<Q", panel))
            self.write(cmd + 0x38, struct.pack("<i", 0))
            self.write(cmd + 0x90, struct.pack("<Q", buf_addr))
            self.write(dd_st + 0x100, struct.pack("<Q", msgdlg))
            self.write(main_st + 0x4C, struct.pack("<i", 1))

            t0 = time.monotonic()
            ok = False
            while time.monotonic() - t0 < 1.0:
                if self.num(main_st + 0x4C, "<i") == 0:
                    ok = True
                    break
                time.sleep(0.01)
            self.write(main_st + 0x4C, struct.pack("<i", 0))
            if self.ptr(dd_st + 0x100) == msgdlg:
                self.write(dd_st + 0x100, struct.pack("<Q", old_dlg if old_dlg != msgdlg else 0))
            self.write(cmd + 0x90, struct.pack("<Q", 0))
            self.write(cmd + 0x38, struct.pack("<i", old_id))
            self.write(cmd + 0x30, struct.pack("<Q", old_listener))
            return ok

    def perform_action(self, listener, id_action, p_obj=0):
        """Gọi IActionListener.perform(id_action, p_obj) trên luồng chính Unity qua Command"""
        with self.call_lock:
            dd_st, main_st = self.statics("dd"), self.statics("Main")
            if not (dd_st and main_st and listener):
                return False
            msgdlg = self.ptr(dd_st + 0x108)
            if not msgdlg:
                return False
            cmd = self.gadget_cmd(msgdlg)
            if not cmd:
                return False

            old_dlg = self.ptr(dd_st + 0x100)
            old_id = self.num(cmd + 0x38, "<i")
            old_listener = self.ptr(cmd + 0x30)
            old_p = self.ptr(cmd + 0x70)
            self.write(cmd + 0x90, struct.pack("<Q", 0))
            self.write(cmd + 0x30, struct.pack("<Q", listener))
            self.write(cmd + 0x38, struct.pack("<i", id_action))
            self.write(cmd + 0x70, struct.pack("<Q", p_obj))
            self.write(dd_st + 0x100, struct.pack("<Q", msgdlg))
            self.write(main_st + 0x4C, struct.pack("<i", 1))

            t0 = time.monotonic()
            ok = False
            while time.monotonic() - t0 < 1.0:
                if self.num(main_st + 0x4C, "<i") == 0:
                    ok = True
                    break
                time.sleep(0.01)
            self.write(main_st + 0x4C, struct.pack("<i", 0))
            self.write(cmd + 0x38, struct.pack("<i", old_id))
            self.write(cmd + 0x30, struct.pack("<Q", old_listener))
            self.write(cmd + 0x70, struct.pack("<Q", old_p))
            if self.ptr(dd_st + 0x100) == msgdlg:
                self.write(dd_st + 0x100, struct.pack("<Q", old_dlg if old_dlg != msgdlg else 0))
            return ok

    def mod_instance(self):
        fz_st = self.statics("fz", init=True)
        if not fz_st:
            return 0
        inst = self.ptr(fz_st)
        if not inst:
            self.call_fn(RVA_MOD_INSTANCE, 0, 0)
            inst = self.ptr(fz_st)
        return inst

    def can_hide(self):
        return (self.read(self.base + CAVE, 1) == b"\xe8" and self.read(self.base + FPS_APPLY, 2) == b"\x8b\x05"
                and self.read(self.base + LOGIC_HOOK, 5) == bytes.fromhex("e8e689e2ff"))

    def scan_bag(self, me):
        """Quét hành trang (arrItemBag): trả về (số ô có đồ, số món SKH, danh sách index đồ rác cần vứt)"""
        bag = self.ptr(me + 0x250)
        if not bag:
            return 0, 0, []
        n = self.num(bag + 0x18, "<i")
        used, skh, junk = 0, 0, []
        for idx in range(min(max(n, 0), 200)):
            it = self.ptr(bag + 0x20 + 8 * idx)
            if not it:
                continue
            tpl = self.ptr(it + 0x18)
            if not tpl:
                continue
            used += 1
            itype = self.num(tpl + 0x12, "<b")
            # Chỉ xét các loại trang bị đeo lên người (0..4: Áo/Quần/Găng/Giày/Rada, 5: Cải trang,
            # 11: Phụ kiện đeo lưng, 21: Linh thú/Pet, 23/24: Thú cưỡi, 32: Giáp tập luyện, 35/36/39/72: Phụ kiện)
            # Tuyệt đối không đụng tới vật phẩm tiêu thụ / sự kiện / nguyên liệu (type 6, 12, 14, 15, 27, 29...)
            if itype not in (0, 1, 2, 3, 4, 5, 11, 21, 23, 24, 32, 35, 36, 39, 72):
                continue
            ilvl = self.num(tpl + 0x30, "<b")   # >= 13 là đồ Thần Linh / Hủy Diệt -> luôn giữ lại
            opts = self.ptr(it + 0x10)
            if not opts:
                continue  # chưa tải xong option -> tuyệt đối không vứt
            olen = self.num(opts + 0x18, "<i")
            if olen <= 0 or olen > 30:
                continue
            is_skh = False
            is_valuable = ilvl >= 13  # đồ Thần Linh / Hủy Diệt / Thiên Sứ
            has_expiry = False
            for j in range(olen):
                opt = self.ptr(opts + 0x20 + 8 * j)
                if not opt:
                    continue
                otpl = self.ptr(opt + 0x18)
                if not otpl:
                    continue
                oid = self.num(otpl + 0x10, "<i")
                param = self.num(opt + 0x10, "<i")
                oname = self.string(otpl + 0x18).lower()
                if oid in SKH_OPT_IDS or oname.startswith("set ") or "$(5 món" in oname:
                    is_skh = True
                    break
                if oid == 93 or "hsd" in oname or "hạn sử dụng" in oname or "hạn dùng" in oname:
                    has_expiry = True
                # Giữ lại đồ đã đập cấp [+1..], đã ép Sao Pha Lê, hoặc đồ >= 4 sao trống
                if oid in (72, 102) or (oid == 107 and param >= 4):
                    is_valuable = True
            if is_skh:
                skh += 1
            elif has_expiry or (0 <= itype <= 4 and not is_valuable):
                junk.append(idx)
        return used, skh, junk

    def throw_bag_item(self, slot_idx):
        """Vứt 1 món đồ tại ô slot_idx trong hành trang ra đất (2 bước: gửi 2003 -> xác nhận 2004)"""
        with self.call_lock:
            bh, dd_st, main_st = self.statics("bh"), self.statics("dd"), self.statics("Main")
            if not (bh and dd_st and main_st):
                return False
            me = self.ptr(bh + 0xA8)
            panel = self.ptr(dd_st + 0xD8)
            menu = self.ptr(dd_st + 0xD0)
            msgdlg = self.ptr(dd_st + 0x108)
            if not (me and panel and msgdlg):
                return False
            if menu and self.read(menu + 0x10, 1) != b"\x00":
                return False
            cur_dlg = self.ptr(dd_st + 0x100)
            if cur_dlg and cur_dlg != msgdlg:
                return False
            bag = self.ptr(me + 0x250)
            old_item = self.ptr(bag + 0x20 + 8 * slot_idx) if bag else 0
            if not old_item:
                return False

            body = self.ptr(me + 0x260)
            body_len = self.num(body + 0x18, "<i") if body else 10
            cmd = self.gadget_cmd(msgdlg)
            if not cmd:
                return False

            old_page = self.num(panel + 0x238, "<i")
            old_sel = self.num(panel + 0x230, "<i")
            self.write(panel + 0x238, struct.pack("<i", 0))
            self.write(panel + 0x230, struct.pack("<i", slot_idx + body_len + 1))
            self.write(cmd + 0x90, struct.pack("<Q", 0))
            self.write(cmd + 0x30, struct.pack("<Q", panel))
            self.write(cmd + 0x38, struct.pack("<i", 2003))
            self.write(dd_st + 0x100, struct.pack("<Q", msgdlg))
            self.write(main_st + 0x4C, struct.pack("<i", 1))

            # Bước 1: Chờ frame Unity thực thi xong lệnh 2003 (khi ẩn 5 FPS cần ~200ms)
            t0 = time.monotonic()
            step1_ok = False
            while time.monotonic() - t0 < 1.0:
                if self.num(main_st + 0x4C, "<i") == 0:
                    step1_ok = True
                    break
                time.sleep(0.015)
            self.write(panel + 0x238, struct.pack("<i", old_page))
            self.write(panel + 0x230, struct.pack("<i", old_sel))
            if not step1_ok:
                self.write(main_st + 0x4C, struct.pack("<i", 0))
                self.write(cmd + 0x38, struct.pack("<i", 0))
                self.write(dd_st + 0x100, struct.pack("<Q", 0))
                return False

            # Bước 2: Chờ server trả về hộp thoại xác nhận (idAction == 2004) rồi chờ frame kế tiếp bấm Đồng ý
            t1 = time.monotonic()
            while time.monotonic() - t1 < 1.5:
                time.sleep(0.02)
                left_cmd = self.ptr(msgdlg + 0x10)
                if left_cmd and self.num(left_cmd + 0x38, "<i") == 2004:
                    self.write(left_cmd + 0x90, struct.pack("<Q", 0))
                    self.write(dd_st + 0x100, struct.pack("<Q", msgdlg))
                    self.write(main_st + 0x4C, struct.pack("<i", 1))
                    t2 = time.monotonic()
                    step2_ok = False
                    while time.monotonic() - t2 < 1.0:
                        if self.num(main_st + 0x4C, "<i") == 0:
                            step2_ok = True
                            break
                        time.sleep(0.015)
                    self.write(main_st + 0x4C, struct.pack("<i", 0))
                    self.write(left_cmd + 0x38, struct.pack("<i", 0))
                    if not step2_ok:
                        self.write(dd_st + 0x100, struct.pack("<Q", 0))
                        return False
                    t3 = time.monotonic()
                    while time.monotonic() - t3 < 0.6:
                        if self.ptr(bag + 0x20 + 8 * slot_idx) != old_item:
                            break
                        time.sleep(0.02)
                    self.dropped_junk += 1
                    return True
            self.write(dd_st + 0x100, struct.pack("<Q", 0))
            return False

    def current_username(self):
        """Đọc tên tài khoản đang gắn với phiên game hiện tại"""
        fg_st = self.statics("fg")
        if fg_st:
            mju = self.ptr(fg_st + 0x28)
            if mju:
                u = self.string(mju + 0x20).strip()
                if u:
                    return u
        dd_st = self.statics("dd")
        if dd_st:
            login_scr = self.ptr(dd_st + 0xF0)
            if login_scr:
                tf_user = self.ptr(login_scr + 0x30)
                if tf_user:
                    u = self.string(tf_user + 0x28).strip()
                    if u:
                        return u
        return ""

    def sync_login_box(self, username, password=""):
        """Đồng bộ ô Tài khoản / Mật khẩu (loginScr.tfUser/tfPass) trong bộ nhớ của chính tiến trình game này"""
        username = (username or "").strip()
        if not username:
            return False
        dd_st = self.statics("dd")
        login_scr = self.ptr(dd_st + 0xF0) if dd_st else 0
        if not login_scr:
            return False
        tf_user, tf_pass = self.ptr(login_scr + 0x30), self.ptr(login_scr + 0x38)
        cur_u = self.string(tf_user + 0x28).strip() if tf_user else ""
        cur_p = self.string(tf_pass + 0x28).strip() if tf_pass else ""
        if cur_u == username and (not password or cur_p == password):
            return True
        with LOGIN_LOCK:
            save_rms_login(username, password if password else cur_p)
            self.call_fn(RVA_LOAD_ACC_MGR, 0, 0)
            self.call_fn(RVA_LOGIN_RELOAD_RMS, login_scr, 0)
        return True

    def ensure_auto_login_bound(self, username=None, password=None):
        """Khi cờ Tự ĐN (fg+0x21) đang bật và nhân vật đã vào game, đảm bảo fg.mju (fg+0x28) đã gắn đúng tài khoản & nhân vật"""
        fg_st, bh_st, dd_st = self.statics("fg"), self.statics("bh"), self.statics("dd")
        if not (fg_st and bh_st and dd_st):
            return False
        if self.read(fg_st + 0x21, 1) == b"\x00":
            return False
        me = self.ptr(bh_st + 0xA8)
        login_scr = self.ptr(dd_st + 0xF0)
        if not (me and login_scr):
            return False
        if username:
            self.sync_login_box(username, password or "")
        char_id = self.num(me + 0x90, "<i")
        mju = self.ptr(fg_st + 0x28)
        mju_user = self.string(mju + 0x20).strip() if mju else ""
        if mju and self.num(mju + 0x28, "<i") == char_id and mju_user and (not username or mju_user == username):
            return True
        self.call_fn(RVA_LOAD_ACC_MGR, 0, 0)
        tf_user = self.ptr(login_scr + 0x30)
        if tf_user and not self.string(tf_user + 0x28).strip():
            self.call_fn(RVA_LOGIN_RELOAD_RMS, login_scr, 0)
        self.write(fg_st + 0x21, b"\x00")
        mod = self.mod_instance()
        if mod:
            self.perform_action(mod, 67, 0)
        self.write(fg_st + 0x21, b"\x01")
        return True

    def login_now(self, username=None, password=None):
        """Thực hiện đăng nhập ngay lập tức trên tiến trình game đang ở màn hình chờ / đăng nhập"""
        with LOGIN_LOCK:  # Rms dùng chung: tab khác không được ghi đè acc/pass giữa lúc tab này đang nạp
            return self._login_now(username, password)

    def _login_now(self, username, password):
        if username:
            save_rms_login(username, password or "")
        dd_st = self.statics("dd")
        if not dd_st:
            return False
        cur_scr = self.ptr(dd_st + 0xC8)
        srv_scr = self.ptr(dd_st + 0x398)
        login_scr = self.ptr(dd_st + 0xF0)
        self.call_fn(RVA_LOAD_ACC_MGR, 0, 0)
        if login_scr:
            self.call_fn(RVA_LOGIN_RELOAD_RMS, login_scr, 0)
        if srv_scr and cur_scr == srv_scr:
            # mất kết nối xong game về màn hình chọn server: nút "Đăng nhập" (3) đọc acc/pass vừa nạp vào loginScr & Rms
            return self.perform_action(srv_scr, 3, 0)
        if login_scr:
            return self.call_fn(RVA_LOGIN_DO_LOGIN, login_scr, 0)
        if srv_scr:
            return self.perform_action(srv_scr, 3, 0)
        return False

    def login_cooldown(self):
        """(ptr, giây) nếu hộp thoại đang báo "Bạn chỉ có thể đăng nhập lại sau N giây nữa", không thì None"""
        dd_st = self.statics("dd")
        msgdlg = self.ptr(dd_st + 0x108) if dd_st else 0
        arr = self.ptr(msgdlg + 0x30) if msgdlg else 0
        if not arr:
            return None
        hit = re.search(r"đăng nhập lại sau (\d+) giây", norm_str(" ".join(self.str_array(arr))))
        return (arr, float(hit.group(1))) if hit else None

    def get_mod_auto_item_ids(self):
        """Đọc danh sách ID các vật phẩm đang nằm trong danh sách tự dùng (fg.mjr) của MOD"""
        fg_st = self.statics("fg")
        if not fg_st or self.read(fg_st + 0x11, 1) == b"\x00":
            return []
        mjr = self.ptr(fg_st + 0x18)
        if not mjr:
            return []
        n = self.num(mjr + 0x18, "<i")
        arr = self.ptr(mjr + 0x10)
        if not arr or n <= 0 or n > 100:
            return []
        raw = self.read(arr + 0x20, 8 * n)
        return [struct.unpack_from("<ii", raw, 8 * i)[1] for i in range(n)]

    def _mod_auto_list(self, fg_st):
        """(mjr, arr, [(iconID, id)]) của danh sách tự dùng item trong MOD"""
        mjr = self.ptr(fg_st + 0x18)
        n = self.num(mjr + 0x18, "<i") if mjr else 0
        arr = self.ptr(mjr + 0x10) if mjr else 0
        if not arr or not 0 < n <= 100:
            return mjr, arr, []
        raw = self.read(arr + 0x20, 8 * n)
        return mjr, arr, [struct.unpack_from("<ii", raw, 8 * i) for i in range(n)]

    def sync_auto_items(self, enabled, target_ids, target_names):
        """Đồng bộ danh sách tự dùng item (fg.mjr) của MOD theo item đã tích trên bảng.
        Chỉ thêm/bớt item do chính bảng thêm vào - item và cờ tự dùng người chơi tự bật trong game giữ nguyên."""
        fg_st = self.statics("fg")
        if not fg_st:
            return 0
        bh_st = self.statics("bh")
        me = self.ptr(bh_st + 0xA8) if bh_st else 0
        bag = self.ptr(me + 0x250) if (me and enabled) else 0
        n_bag = self.num(bag + 0x18, "<i") if bag else 0
        bag_matches = {}  # item đã tích đang có trong hành trang: id -> Item*
        for idx in range(min(max(n_bag, 0), 200)):
            it = self.ptr(bag + 0x20 + 8 * idx)
            if not it:
                continue
            tpl = self.ptr(it + 0x18)
            if not tpl:
                continue
            tid = self.num(tpl + 0x10, "<h")
            if tid in bag_matches:
                continue
            tname = norm_str(self.string(tpl + 0x18))
            if tid in target_ids or (tname and tname in target_names):
                bag_matches[tid] = it
        mjr, arr, pairs = self._mod_auto_list(fg_st)
        # bỏ item do bảng thêm mà giờ bị bỏ tích (hoặc tắt Tự dùng Item trên bảng); item người chơi tự thêm thì giữ
        allowed = (set(target_ids) | set(bag_matches)) if enabled else set()
        drop = {iid for _ic, iid in pairs if iid in self.panel_auto_ids and iid not in allowed}
        if drop and mjr:
            kept = [(ic, iid) for ic, iid in pairs if iid not in drop]
            if kept:
                self.write(arr + 0x20, b"".join(struct.pack("<ii", ic, iid) for ic, iid in kept))
            self.write(mjr + 0x18, struct.pack("<i", len(kept)))
            self.panel_auto_ids -= drop
            pairs = kept
        if not enabled:
            if self.panel_auto_flag and not pairs:  # cờ do bảng bật mà danh sách đã rỗng -> trả lại như cũ
                self.write(fg_st + 0x11, b"\x00")
                self.panel_auto_flag = False
            return len(pairs)
        if self.read(fg_st + 0x11, 1) == b"\x00":
            self.write(fg_st + 0x11, b"\x01")
            self.panel_auto_flag = True
        have = {iid for _ic, iid in pairs}
        now = time.monotonic()
        for tid, it_ptr in bag_matches.items():
            # fg.cnf(item) là BẬT/TẮT: có rồi mà gọi lại là bị xoá -> chỉ gọi khi chưa có, và không gọi lại trong 5s
            if tid not in have and now - self.auto_item_tried.get(tid, 0) > 5:
                self.auto_item_tried[tid] = now
                self.call_fn(RVA_AUTO_ITEM_SET, it_ptr, 1)
        _mjr, _arr, pairs = self._mod_auto_list(fg_st)
        added = {iid for _ic, iid in pairs} & set(bag_matches)
        self.panel_auto_ids |= added - have  # chỉ ghi nhận item do bảng thêm (không nhận item người chơi đã có)
        return len(pairs)

    def patch_code_bytes(self, rva, new_bytes):
        """Ghi đè các byte mã máy tại RVA trong bộ nhớ GameAssembly.dll (dùng VirtualProtectEx)"""
        addr = self.base + rva
        if self.read(addr, len(new_bytes)) == new_bytes:
            return True
        old_prot = wintypes.DWORD()
        if kernel32.VirtualProtectEx(self.h, ctypes.c_void_p(addr), len(new_bytes), 0x40, ctypes.byref(old_prot)):
            self.write(addr, new_bytes)
            kernel32.VirtualProtectEx(self.h, ctypes.c_void_p(addr), len(new_bytes), old_prot.value, ctypes.byref(old_prot))
            return True
        return False

    def set_autobuy_delay(self, delay_ms):
        """Chỉnh thời gian nghỉ giữa mỗi lần mua của từng luồng Auto Mua (mặc định game là 400ms tại 0x476CA6)"""
        ms = max(20, min(2000, int(delay_ms)))
        return self.patch_code_bytes(RVA_AUTOBUY_DELAY_IMM, struct.pack("<i", ms))

    def find_shop_item(self, me, target_tid):
        """Tìm vật phẩm có templateId == target_tid trong cửa hàng đang mở (me.arrItemShop tại me+0x270)"""
        shop = self.ptr(me + 0x270) if me else 0
        if not shop:
            return 0
        n_tabs = self.num(shop + 0x18, "<i")
        for t_idx in range(min(max(n_tabs, 0), 12)):
            tab = self.ptr(shop + 0x20 + 8 * t_idx)
            if not tab:
                continue
            n_items = self.num(tab + 0x18, "<i")
            for i_idx in range(min(max(n_items, 0), 100)):
                it = self.ptr(tab + 0x20 + 8 * i_idx)
                if not it:
                    continue
                tpl = self.ptr(it + 0x18)
                if tpl and self.num(tpl + 0x10, "<h") == target_tid:
                    return it
        return 0

    def count_bag_item(self, me, target_tid):
        """Đếm tổng số lượng vật phẩm target_tid trong hành trang (me+0x250) và số ô trống còn lại"""
        bag = self.ptr(me + 0x250) if me else 0
        if not bag:
            return 0, 0
        n = self.num(bag + 0x18, "<i")
        total_qty, empty_slots = 0, 0
        for idx in range(min(max(n, 0), 200)):
            it = self.ptr(bag + 0x20 + 8 * idx)
            if not it:
                empty_slots += 1
                continue
            tpl = self.ptr(it + 0x18)
            if tpl and self.num(tpl + 0x10, "<h") == target_tid:
                q = self.num(it + 0x38, "<i")
                total_qty += q if q > 0 else 1
        return total_qty, empty_slots

    def list_swords(self, me):
        """Các Kiếm Z trong hành trang: [(ô, % sức đánh, cấp)]; % sức đánh = None nếu chưa đọc được chỉ số (không được vứt)"""
        bag = self.ptr(me + 0x250) if me else 0
        out = []
        for idx in range(min(max(self.num(bag + 0x18, "<i"), 0), 200) if bag else 0):
            it = self.ptr(bag + 0x20 + 8 * idx)
            tpl = self.ptr(it + 0x18) if it else 0
            if not tpl or self.num(tpl + 0x10, "<h") != ITEM_ID_KIEM_Z:
                continue
            opts = self.ptr(it + 0x10)
            dmg, level = None, 0
            for j in range(min(max(self.num(opts + 0x18, "<i"), 0), 30) if opts else 0):
                opt = self.ptr(opts + 0x20 + 8 * j)
                otpl = self.ptr(opt + 0x18) if opt else 0
                oid = self.num(otpl + 0x10, "<i") if otpl else -1
                if oid == OPT_ID_SUC_DANH:
                    dmg = self.num(opt + 0x10, "<i")
                elif oid == OPT_ID_CAP:
                    level = self.num(opt + 0x10, "<i")
            out.append((idx, dmg, level))
        return out

    def find_egg_in_bag(self, me):
        """Tìm vị trí quả trứng linh thú trong hành trang (me+0x250)"""
        bag = self.ptr(me + 0x250) if me else 0
        if not bag:
            return -1, 0, ""
        n = self.num(bag + 0x18, "<i")
        for idx in range(min(max(n, 0), 200)):
            it = self.ptr(bag + 0x20 + 8 * idx)
            if not it:
                continue
            tpl = self.ptr(it + 0x18)
            if not tpl:
                continue
            tid = self.num(tpl + 0x10, "<h")
            name = norm_str(self.string(tpl + 0x18))
            if ("trứng" in name or "trung" in name) and tid != ITEM_ID_DA_LINH_LUC:
                return idx, tid, name
        return -1, 0, ""

    def find_egg_in_shop(self, me):
        """Tìm quả trứng linh thú trong cửa hàng đang mở (me.arrItemShop tại me+0x270)"""
        shop = self.ptr(me + 0x270) if me else 0
        if not shop:
            return 0, -1, ""
        n_tabs = self.num(shop + 0x18, "<i")
        for t_idx in range(min(max(n_tabs, 0), 12)):
            tab = self.ptr(shop + 0x20 + 8 * t_idx)
            if not tab:
                continue
            n_items = self.num(tab + 0x18, "<i")
            for i_idx in range(min(max(n_items, 0), 100)):
                it = self.ptr(tab + 0x20 + 8 * i_idx)
                if not it:
                    continue
                tpl = self.ptr(it + 0x18)
                if not tpl:
                    continue
                tid = self.num(tpl + 0x10, "<h")
                name = norm_str(self.string(tpl + 0x18))
                if "trứng" in name or "trung" in name:
                    return it, tid, name
        return 0, -1, ""

    def is_panel_open(self):
        """Kiểm tra Panel cửa hàng/hành trang có đang mở hay không"""
        dd_st = self.statics("dd")
        if not dd_st:
            return False
        for off in (0xD8, 0xE0):
            panel = self.ptr(dd_st + off)
            if panel and self.read(panel + 0x10, 1) != b"\x00":
                return True
        return False

    def is_shop_open(self):
        """Cửa hàng NPC đang mở: lúc đó có thêm Panel thứ 2 (dd+0xE0); chỉ mở hành trang thì không có"""
        dd_st = self.statics("dd")
        panel2 = self.ptr(dd_st + 0xE0) if dd_st else 0
        return bool(panel2) and self.read(panel2 + 0x10, 1) != b"\x00"

    def hide_panels(self):
        """Đóng các Panel đang mở trên màn hình"""
        dd_st = self.statics("dd")
        if not dd_st:
            return False
        closed = False
        for off in (0xD8, 0xE0):
            panel = self.ptr(dd_st + off)
            if panel and self.read(panel + 0x10, 1) != b"\x00":
                self.call_fn(RVA_PANEL_HIDE, panel, 0)
                closed = True
        return closed

    def buy_shop_item(self, it_shop, retry=0):
        """Mua 1 vật phẩm it_shop trong cửa hàng đang mở qua Panel.perform (3000/3001/3004)"""
        if not it_shop:
            return False
        dd_st = self.statics("dd")
        panel = self.ptr(dd_st + 0xD8) if dd_st else 0
        if not panel:
            return False
        buy_spec = self.num(it_shop + 0x40, "<q")
        buy_coin = self.num(it_shop + 0x54, "<i")
        buy_gold = self.num(it_shop + 0x5C, "<i")
        if buy_spec != 0:
            actions = [3004, 3000, 3001]
        elif buy_coin > 0 and buy_gold <= 0:
            actions = [3000, 3004, 3001]
        elif buy_gold > 0 and buy_coin <= 0:
            actions = [3001, 3004, 3000]
        else:
            actions = [3004, 3000, 3001]
        act = actions[retry % len(actions)]
        ok = self.perform_action(panel, act, it_shop)
        if ok:
            t_wait = time.monotonic()
            while time.monotonic() - t_wait < 0.25:
                if self.confirm_msgdlg_if_open():
                    break
                time.sleep(0.03)
        return ok

    def confirm_msgdlg_if_open(self):
        """Nếu đang có hộp thoại xác nhận (msgdlg) trên màn hình thì bấm nút xác nhận/đóng"""
        dd_st = self.statics("dd")
        if not dd_st:
            return False
        cur_dlg = self.ptr(dd_st + 0x100)
        msgdlg = self.ptr(dd_st + 0x108)
        if not (cur_dlg and msgdlg and cur_dlg == msgdlg):
            return False
        for cmd_off in (0x10, 0x18):
            cmd = self.ptr(msgdlg + cmd_off)
            if cmd:
                id_act = self.num(cmd + 0x38, "<i")
                listener = self.ptr(cmd + 0x30)
                p_obj = self.ptr(cmd + 0x70)
                if id_act > 0 and listener:
                    return self.perform_action(listener, id_act, p_obj)
        self.write(dd_st + 0x100, struct.pack("<Q", 0))
        return True

    def use_bag_slot(self, slot_idx):
        """Bấm "Sử dụng" đúng ô slot_idx của hành trang qua Panel (lệnh 2001), không đóng cửa hàng đang mở"""
        bh, dd_st = self.statics("bh"), self.statics("dd")
        me = self.ptr(bh + 0xA8) if bh else 0
        panel = self.ptr(dd_st + 0xD8) if dd_st else 0
        if not (me and panel):
            return False
        body = self.ptr(me + 0x260)
        body_len = self.num(body + 0x18, "<i") if body else 10
        old_page = self.num(panel + 0x238, "<i")
        old_sel = self.num(panel + 0x230, "<i")
        self.write(panel + 0x238, struct.pack("<i", 0))
        self.write(panel + 0x230, struct.pack("<i", slot_idx + body_len + 1))
        # perform_action xoá vật phẩm còn dính trên nút mượn (sau khi vứt đồ nút còn giữ món vừa vứt -> lệnh 2001 dùng nhầm món đó)
        ok = self.perform_action(panel, 2001, 0)
        self.write(panel + 0x238, struct.pack("<i", old_page))
        self.write(panel + 0x230, struct.pack("<i", old_sel))
        return ok

    def use_bag_item(self, slot_idx):
        """Sử dụng 1 món đồ tại ô slot_idx trong hành trang (ưu tiên gọi RVA_USE_ITEM_BY_TID trực tiếp)"""
        if slot_idx < 0:
            return False
        self.close_menu()
        self.hide_panels()
        bh, dd_st, main_st = self.statics("bh"), self.statics("dd"), self.statics("Main")
        if not (bh and dd_st and main_st):
            return False
        me = self.ptr(bh + 0xA8)
        bag = self.ptr(me + 0x250) if me else 0
        it = self.ptr(bag + 0x20 + 8 * slot_idx) if bag else 0
        if not it:
            return False
        tpl = self.ptr(it + 0x18)
        tid = self.num(tpl + 0x10, "<h") if tpl else -1
        ok = False
        if tid >= 0:
            ok = self.call_fn(RVA_USE_ITEM_BY_TID, tid & 0xFFFFFFFF, 0)
        if not ok:
            ok = self.use_bag_slot(slot_idx)
        if ok:
            t_wait = time.monotonic()
            while time.monotonic() - t_wait < 0.55:
                if self.confirm_msgdlg_if_open():
                    break
                caps = self.read_current_menu()
                if caps and any(w in caps[0] for w in ("đồng ý", "dong y", "ok", "xác nhận", "xac nhan")):
                    self.select_menu_option(0)
                    break
                time.sleep(0.03)
        return ok

    def read_current_menu(self):
        """Đọc danh sách các mục (text) của menu đang hiển thị (nếu có)"""
        dd_st = self.statics("dd")
        menu = self.ptr(dd_st + 0xD0) if dd_st else 0
        if not menu or self.read(menu + 0x10, 1) == b"\x00":
            return []
        items = self.vec_items(self.ptr(menu + 0x18))
        caps = []
        for c in items:
            sub = [x for x in self.str_array(self.ptr(c + 0x28)) if x]
            txt = norm_str(" ".join(sub) if sub else self.string(c + 0x20))
            caps.append(txt.replace("\n", " "))
        return caps

    def close_menu(self):
        """Đóng menu đang hiển thị mà không kích hoạt chọn mục"""
        dd_st = self.statics("dd")
        menu = self.ptr(dd_st + 0xD0) if dd_st else 0
        if not menu or self.read(menu + 0x10, 1) == b"\x00":
            return False
        self.write(menu + 0x85, b"\x00")
        self.write(menu + 0x84, b"\x00")
        self.call_fn(RVA_MENU_CLOSE, menu, 0)
        return True

    def select_menu_option(self, pick_index):
        """Chọn option pick_index trong menu đang hiển thị và kích hoạt callback qua Menu.doCloseMenu (menu+0x84 = 1)"""
        dd_st = self.statics("dd")
        menu = self.ptr(dd_st + 0xD0) if dd_st else 0
        if not menu or self.read(menu + 0x10, 1) == b"\x00":
            return False
        self.write(menu + 0x20, struct.pack("<i", pick_index))
        self.write(menu + 0x85, b"\x00")
        self.write(menu + 0x84, b"\x01")
        self.call_fn(RVA_MENU_CLOSE, menu, 0)
        return True

    def start_autobuy(self, item_id, threads=10, qty_per_thread=100, delay_ms=80):
        """Khởi chạy song song N luồng Auto Mua (như bấm Auto Mua + nhập 100 liên tiếp N lần) kèm vá giảm delay"""
        threads = max(1, min(30, int(threads)))
        qty_per_thread = max(1, min(1000, int(qty_per_thread)))
        total_qty = threads * qty_per_thread
        self.set_fps(60)
        self.patch_code_bytes(RVA_AUTOBUY_CMP_INS, b"\x39\x70\x14")
        self.set_autobuy_delay(delay_ms)
        ab_st = self.statics("autobuy", init=True)
        if not ab_st:
            return []
        it_ptr = self.ptr(ab_st + 0x08) or self.ptr(ab_st + 0x10)
        if not it_ptr:
            if not self.call_fn(RVA_AUTOBUY_ALLOC, 0, 0):
                return []
            it_ptr = self.ptr(ab_st + 0x10)
            if not it_ptr:
                return []
        self.write(ab_st + 0x08, struct.pack("<Q", it_ptr))
        self.write(ab_st + 0x10, struct.pack("<Q", it_ptr))
        payload = struct.pack("<iiiBBBBqq", item_id, total_qty, -1, item_id & 0xFF, 0, 1, 0, 0, 0)
        self.write(it_ptr + 0x10, payload)
        spawned = []
        for _ in range(threads):
            # Giữ q_rem luôn đầy trong lúc đang mở từng luồng để không luồng nào kết thúc sớm
            self.write(it_ptr + 0x14, struct.pack("<i", total_qty))
            if self.call_fn(RVA_AUTOBUY_START, it_ptr, 0):
                spawned.append(it_ptr)
        return spawned

    def remaining_autobuy_count(self, tracked_items=None):
        """Tổng số lượt mua còn lại của các luồng Auto Mua đang chạy"""
        total = 0
        seen = set()
        for it_ptr in (tracked_items or []):
            if it_ptr and it_ptr not in seen:
                seen.add(it_ptr)
                try:
                    q = self.num(it_ptr + 0x14, "<i")
                    if 0 < q <= 100000:
                        total += q
                except OSError:
                    pass
        try:
            ab_st = self.statics("autobuy")
            if ab_st:
                for off in (0x08, 0x10):
                    p = self.ptr(ab_st + off)
                    if p and p not in seen:
                        seen.add(p)
                        q = self.num(p + 0x14, "<i")
                        if 0 < q <= 100000:
                            total += q
        except OSError:
            pass
        return total

    def stop_all_autobuy(self, tracked_items=None):
        """Dừng tức thì 100% các luồng Auto Mua đang chạy (cả luồng bắn từ bảng lẫn luồng bấm tay trong game)"""
        zero_i = struct.pack("<i", 0)
        seen = set()
        for it_ptr in (tracked_items or []):
            if it_ptr and it_ptr not in seen:
                seen.add(it_ptr)
                try:
                    self.write(it_ptr + 0x14, zero_i)
                except OSError:
                    pass
        try:
            ab_st = self.statics("autobuy")
            if ab_st:
                for off in (0x08, 0x10):
                    p = self.ptr(ab_st + off)
                    if p and p not in seen:
                        seen.add(p)
                        self.write(p + 0x14, zero_i)
        except OSError:
            pass
        try:
            fg_st = self.statics("fg")
            if fg_st:
                self.write(fg_st + 0xB0, struct.pack("<Q", 0))
                self.write(fg_st + 0xB8, zero_i)
        except OSError:
            pass
        try:
            if self.patch_code_bytes(RVA_AUTOBUY_CMP_INS, b"\x39\xc0\x90"):
                time.sleep(0.02)
                self.patch_code_bytes(RVA_AUTOBUY_CMP_INS, b"\x39\x70\x14")
        except OSError:
            pass

    def status(self):
        s = {"ready": False, "canHide": self.can_hide(), "flags": {}, "dropped": self.dropped_junk,
             "username": self.current_username(), "autoItemCount": len(self.get_mod_auto_item_ids())}
        if s["canHide"]:
            s["hidden"] = self.read(self.base + D_FORCE, 1) != b"\0"
            s["picked"] = self.num(self.base + D_PICKED, "<Q")
        ft = self.statics("ft")
        s["fps"] = self.num(ft + 0x1A, "<h") if ft else 0
        for key, (cls, off) in FLAGS.items():
            st = self.statics(cls)
            s["flags"][key] = bool(self.read(st + off, 1)[0]) if st else None
        dd_st = self.statics("dd")
        cur_scr = self.ptr(dd_st + 0xC8) if dd_st else 0
        login_scr = self.ptr(dd_st + 0xF0) if dd_st else 0
        srv_scr = self.ptr(dd_st + 0x398) if dd_st else 0
        s["onLoginScr"] = bool(cur_scr and login_scr and cur_scr == login_scr)
        bh, jb = self.statics("bh"), self.statics("jb")
        me = self.ptr(bh + 0xA8) if bh else 0
        if not me or not jb:
            return s
        name = self.string(me + 0x190)
        if not name:
            return s
        bag_used, skh_count, junk_slots = self.scan_bag(me)
        q = self.read_quest_info(me)
        s["offline"] = bool(cur_scr) and cur_scr in (login_scr, srv_scr)
        fg_st = self.statics("fg")
        mju = self.ptr(fg_st + 0x28) if fg_st else 0
        if mju and self.num(mju + 0x28, "<i") == self.num(me + 0x90, "<i"):  # chỉ tin khi gắn đúng id nhân vật đang chơi
            s["boundUser"] = self.string(mju + 0x20).strip()
        if login_scr and not s["offline"]:
            # ô Tài khoản / Mật khẩu của CHÍNH tab này: game chỉ nạp từ Rms chung ngay trước lúc đăng nhập (eq.cgi),
            # nên khi đã vào game thì đây đúng là tài khoản tab vừa dùng
            tf_user, tf_pass = self.ptr(login_scr + 0x30), self.ptr(login_scr + 0x38)
            s["loginUser"] = self.string(tf_user + 0x28).strip() if tf_user else ""
            s["loginPass"] = self.string(tf_pass + 0x28).strip() if tf_pass else ""
        s.update(ready=True, name=name, hp=self.num(me + 0xD0, "<q"), hpFull=self.num(me + 0x108, "<q"),
                 mp=self.num(me + 0xC8, "<q"), mpFull=self.num(me + 0x110, "<q"), dead=self.num(me + 0x88, "<i") == 14,
                 map=self.string(jb + 0x70), mapId=self.num(jb + 0x7C, "<i"), zone=self.num(jb + 0x84, "<i"),
                 bagUsed=bag_used, skhCount=skh_count, junkSlots=junk_slots, quest=q)
        return s

    def set_flag(self, key, on):
        cls, off = FLAGS[key]
        st = self.statics(cls)
        if st:
            self.write(st + off, b"\x01" if on else b"\x00")
            if key == "al":
                if on:
                    self.ensure_auto_login_bound()
                else:
                    self.write(st + 0x28, struct.pack("<Q", 0))

    def set_fps(self, fps):
        ft = self.statics("ft")
        if ft:
            self.write(ft + 0x1A, struct.pack("<h", fps))
        self.write(self.base + D_FPS_REQ, struct.pack("<i", fps))

    def set_hidden(self, on, fps):
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


class BossHunter:
    """Bộ máy trạng thái Săn Cụm BOSS & Tự làm Nhiệm Vụ Chính Tuyến cho từng nhân vật (không dùng Frida)"""

    MOD_FLAGS = [
        ("fg", 0x10),   # fgFocusBoss
        ("fg", 0xC9),   # fgKeepFocus
        ("rs", 0x10),   # rsKillMobs (Tàn sát)
        ("rs", 0x11),   # rsKillChars
        ("rs", 0x15),   # rsGoback
        ("rs", 0x40),   # rsAutoPick (Tự nhặt)
        ("rs", 0x41),   # rsPickOthers
        ("rs", 0x42),   # rsPickFar
        ("dg", 0x364),  # dgAutoPlay
    ]

    def __init__(self, mem, get_cfg, log_cb):
        self.mem = mem
        self.get_cfg = get_cfg
        self.log_cb = log_cb
        self.enabled = False
        self.quest_mode = False
        self.state = "IDLE"
        self.cluster = None
        self.target_map = -1
        self.target_name = ""
        self.notice_ptr = 0
        self.zone = -1
        self.t = 0.0
        self.last_move = 0.0
        self.xmap_at = 0.0
        self.xmap_tries = 0
        self.done = set()
        self.bad_maps = {}
        self.seen_names = set()
        self.visited = set()
        self.zone_req = -1
        self.last_zone_at = 0.0
        self.next_zone_at = 0.0
        self.info1_before = set()
        self.seen_chat_ptrs = set()
        self.retry_zone = -1
        self.same_fails = 0
        self.total_fails = 0
        self.list_zone = -1
        self.list_at = 0.0
        self.list_arr = 0
        self.zone_info = ""
        self.boss_zone = -1
        self.revives_this_target = 0
        self.dead = False
        self.dead_since = 0.0
        self.revive_attempts = 0
        self.last_revive_at = 0.0
        self.went_home = False
        self.last_seen = 0.0
        self.last_fight_log = 0.0
        self.last_buff_try = 0.0
        self.map_names = {}  # tên map (chuẩn hoá) -> id
        self.hop_at = 0.0  # lần gần nhất tự đi qua cửa map (EXTRA_ROUTES)
        self.empty_zone = False  # Khu trống: có người khác vào khu thì tự chuyển sang khu không người
        self.ez_phase = "WATCH"
        self.ez_seen_at = 0.0    # lúc bắt đầu thấy người khác trong khu
        self.ez_check_at = 0.0
        self.ez_t = 0.0
        self.ez_req = -1
        self.ez_arr = 0
        self.ez_next_at = 0.0    # không đổi khu trước lúc này (hồi đổi khu / không có khu vắng hơn)
        self.loot_empty = 0
        self.last_loot_poll = 0.0
        self.attack_skill = 0
        self.mod_saved = None
        self.locate_saved = 0
        self.ak_before = 0
        # Trạng thái Tự làm Nhiệm Vụ Chính Tuyến
        self.q_key = ""
        self.q_action = ""
        self.q_t = 0.0
        self.q_tries = 0
        self.q_phase = ""
        self.q_talk_at = 0.0
        self.q_kill_tpl = -1
        self.q_xmap_map = -1
        self.q_xmap_tries = 0
        self.q_xmap_at = 0.0
        self.q_last_popup_at = 0.0
        # Trạng thái tự đổi + nâng cấp Kiếm Z
        self.sword_active = False
        self.sword_phase = "BUY"        # BUY (mua nguyên liệu ở Mai), EXCHANGE (đổi ở Tổ Sư Kaio), UPGRADE (nâng ở Mai)
        self.sword_at = 0.0             # chưa tới lúc này thì chưa làm bước kế
        self.sword_fail = 0
        self.sword_buy = None
        self.sword_last = None
        self.sword_xmap_at = 0.0
        self.sword_door_n = (-1, 0)
        self.sword_min_new, self.sword_max_level, self.sword_min_final = 5, 6, 30
        self.sword_status_text = "Đang dừng"
        # Trạng thái Auto Ấp Trứng & Mua Đá Linh Lực
        self.egg_active = False
        self.egg_phase = "INIT"         # INIT, SPEEDUP, BUY_STONE, HATCH, BUY_EGG, USE_EGG, RELOAD_MAP
        self.egg_phase_t = 0.0
        self.egg_delay = 120            # ms
        self.egg_days_reduced = 0
        self.egg_stones_bought = 0
        self.egg_hatched_count = 0
        self.egg_target_days = 0
        self.egg_auto_buy_stone = True
        self.egg_auto_buy_egg = True
        self.egg_auto_use_egg = True
        self.egg_status_text = "Đang dừng"
        self.egg_last_action_at = 0.0
        self.egg_single_action = None
        self.egg_shop_opened = False
        self.egg_buy_tries = 0
        self.egg_stone_needed = 30
        self.egg_home_map = MAP_ID_NHA_BUNMA
        self.egg_visited_sieu_thi = False
        self.egg_reload_started_at = 0.0

    def log(self, msg):
        bh = self.mem.statics("bh")
        me = self.mem.ptr(bh + 0xA8) if bh else 0
        char_name = self.mem.string(me + 0x190) if me else "PID"
        self.log_cb(f"[{char_name}] {msg}")

    def set_state(self, st, extra=None):
        self.state = st
        self.t = time.monotonic() * 1000.0
        if extra:
            self.log(extra)

    def summary_text(self):
        if self.egg_active or self.egg_single_action:
            if self.egg_single_action:
                return f"Ấp: {self.egg_single_action}"
            return f"Ấp trứng ({self.egg_status_text})"
        if self.sword_active:
            return f"Kiếm Z ({self.sword_phase})"
        if not self.enabled and not self.quest_mode:
            return "Tắt"
        st = STATE_SHORT.get(self.state, self.state)
        if self.state == "TRAVEL" and self.target_map >= 0:
            return f"XMAP -> map {self.target_map}"
        if self.state in ("SCAN", "FLEE", "RETURN"):
            now = time.monotonic() * 1000.0
            if self.next_zone_at > now:
                rem = max(1, int((self.next_zone_at - now + 999) // 1000))
                z_tgt = self.retry_zone if self.retry_zone >= 0 else self.zone
                return f"Chờ {rem}s -> khu {z_tgt}" if z_tgt >= 0 else f"Chờ đổi khu {rem}s"
            if self.state == "SCAN" and self.zone >= 0:
                return f"Dò khu {self.zone}"
        if self.state == "FIGHT" and self.target_name:
            return f"Đánh {self.target_name}"
        if self.quest_mode and self.state == "IDLE":
            return f"Làm NV ({self.q_action or '...'})"
        return st

    def set_enabled(self, on):
        if on and not self.enabled:
            if not self.quest_mode:
                fg_st = self.mem.statics("fg")
                self.ak_before = self.mem.read(fg_st + 0x0, 1)[0] if fg_st else 0
                self.save_mod_flags()
            self.done.clear()
            self.enabled = True
            self.set_state("IDLE", "Bắt đầu săn cụm BOSS")
        elif not on and self.enabled:
            self.enabled = False
            self.release_target()
            if not self.quest_mode:
                fg_st = self.mem.statics("fg")
                if fg_st:
                    self.mem.write(fg_st + 0x0, bytes([self.ak_before]))
                self.restore_mod_flags()
            self.cluster = None
            self.target_map = -1
            self.set_state("IDLE", "Dừng săn cụm BOSS")

    def set_quest_mode(self, on):
        if on and not self.quest_mode:
            if not self.enabled:
                fg_st = self.mem.statics("fg")
                self.ak_before = self.mem.read(fg_st + 0x0, 1)[0] if fg_st else 0
                self.save_mod_flags()
            self.q_key = ""
            self.done.clear()
            self.quest_mode = True
            self.set_state("IDLE", "Bắt đầu tự làm Nhiệm Vụ Chính Tuyến")
        elif not on and self.quest_mode:
            self.quest_mode = False
            self.stop_kill_mobs()
            self.release_target()
            if not self.enabled:
                fg_st = self.mem.statics("fg")
                if fg_st:
                    self.mem.write(fg_st + 0x0, bytes([self.ak_before]))
                self.restore_mod_flags()
            self.cluster = None
            self.target_map = -1
            self.set_state("IDLE", "Dừng tự làm Nhiệm Vụ Chính Tuyến")

    def skip_current(self):
        if (self.enabled or self.quest_mode) and self.state != "IDLE":
            self.finish_target("bỏ qua theo yêu cầu")

    def set_egg_auto(self, enabled, delay_ms=120, target_days=0, buy_stone=True, buy_egg=True, use_egg=True):
        self.egg_active = bool(enabled)
        self.egg_delay = max(40, min(2000, int(delay_ms)))
        self.egg_target_days = max(0, int(target_days))
        self.egg_auto_buy_stone = bool(buy_stone)
        self.egg_auto_buy_egg = bool(buy_egg)
        self.egg_auto_use_egg = bool(use_egg)
        self.egg_phase = "INIT"
        self.egg_phase_t = time.monotonic() * 1000.0
        self.egg_shop_opened = False
        self.egg_buy_tries = 0
        self.egg_visited_sieu_thi = False
        self.egg_reload_started_at = 0.0
        self.egg_status_text = "Đang chạy" if enabled else "Đã dừng"
        self.log(f"{'BẬT' if enabled else 'TẮT'} Auto Ấp Trứng & Mua Đá Linh Lực (delay={self.egg_delay}ms)")

    def stop_egg_auto(self, reason="Đã dừng Auto Ấp Trứng"):
        self.egg_active = False
        self.egg_single_action = None
        self.egg_shop_opened = False
        self.egg_buy_tries = 0
        self.egg_visited_sieu_thi = False
        self.egg_status_text = "Đã dừng"
        self.log(reason)

    # ---------- Tự đổi + nâng cấp Kiếm Z ----------
    def set_sword_auto(self, enabled, min_new=5, max_level=6, min_final=30):
        if not enabled:
            self.stop_sword_auto("TẮT tự đổi Kiếm Z")
            return
        self.sword_min_new, self.sword_max_level, self.sword_min_final = int(min_new), int(max_level), int(min_final)
        self.sword_active = True
        self.sword_phase = "BUY"
        self.sword_at = 0.0
        self.sword_fail = 0
        self.sword_buy = None
        self.sword_xmap_at = 0.0
        self.sword_status_text = "Đang chạy"
        self.log(f"BẬT tự đổi Kiếm Z (giữ kiếm mới >= {min_new}%, nâng tới +{max_level}, giữ +{max_level} khi > {min_final}%)")

    def stop_sword_auto(self, reason="Đã dừng tự đổi Kiếm Z"):
        if self.sword_active:
            self.mem.stop_all_autobuy(self.sword_buy[2] if self.sword_buy else None)
            self.mem.call_fn(RVA_XMAP_STOP, 0, 0)
        self.sword_active = False
        self.sword_buy = None
        self.sword_status_text = f"Đã dừng: {reason}" if reason else "Đã dừng"
        if reason:
            self.log(reason)

    def sword_retry(self, reason, now):
        """Trục trặc tạm thời (lag, bị đóng cửa hàng, kẹt menu...): không dừng hẳn, dọn màn hình rồi 10 giây sau làm lại"""
        self.log(f"Kiếm Z: {reason}, 10 giây nữa thử lại")
        self.mem.close_menu()
        self.mem.hide_panels()
        self.sword_fail = 0
        self.sword_buy = None
        self.sword_at = now + 10000
        return True

    def sword_make_room(self, todo, now):
        """Hành trang đầy nên không mua được nguyên liệu: vứt 1 Kiếm Z kém nhất trong số chưa đủ cấp (không đụng kiếm đang giữ)"""
        if not todo:
            return False
        slot, dmg, lvl = min(todo, key=lambda sw: (sw[2], sw[1]))
        self.mem.close_menu()
        self.mem.hide_panels()
        if not self.mem.throw_bag_item(slot):
            return False
        self.log(f"Kiếm Z: hành trang đầy không mua được nguyên liệu, vứt kiếm +{lvl} sức đánh {dmg}%")
        self.sword_at = now + 500
        return True

    def sword_set_phase(self, phase):
        self.sword_phase = phase
        self.sword_fail = 0
        self.sword_buy = None

    def sword_npc_pick(self, npc_tpl_id, words, now):
        """Mở menu NPC rồi chọn dòng đầu tiên chứa 1 trong các từ (mỗi lần gọi làm 1 bước)"""
        caps = self.mem.read_current_menu()
        if caps:
            idx = next((i for w in words for i, c in enumerate(caps) if w in c), -1)
            if idx >= 0:
                self.mem.select_menu_option(idx)
            else:
                self.mem.close_menu()
        else:
            self.interact_npc(npc_tpl_id)
        self.sword_at = now + 700

    def sword_goto(self, target_map, cur_map, now):
        """Đi tới Thánh địa Kaio (50) hoặc Hành tinh ngục tù 2 (166); True khi đã tới.
        50 -Ôsin-> Hành tinh Bill (154) -Ôsin-> ngục tù 1 (155) -cửa phải-> ngục tù 2 (166); XMAP của MOD không biết 154/155/166."""
        if cur_map == target_map:
            return True
        to_prison = target_map == MAP_ID_NGUC_TU_2
        if cur_map == MAP_ID_NGUC_TU_1 and to_prison or cur_map == MAP_ID_NGUC_TU_2:
            self.mem.close_menu()
            self.sword_door(to_prison, cur_map)
            self.sword_at = now + 4000
        elif cur_map == MAP_ID_NGUC_TU_1:
            self.sword_npc_pick(NPC_ID_OSIN, ["bill"], now)
        elif cur_map == MAP_ID_BILL and to_prison:
            self.sword_npc_pick(NPC_ID_OSIN, ["ngục tù"], now)
        elif cur_map == MAP_ID_THANH_DIA_KAIO:
            self.sword_npc_pick(NPC_ID_OSIN, ["bill"], now)
        elif cur_map == MAP_ID_KAIO:
            # XMAP của MOD kẹt ở menu 2 tầng của Thần Vũ Trụ ("Di chuyển" -> "Thánh địa Kaio"): tự chọn
            rv_st = self.mem.statics("rv", init=True)
            if rv_st and self.mem.read(rv_st, 1)[0]:
                self.mem.call_fn(RVA_XMAP_STOP, 0, 0)
            self.sword_npc_pick(NPC_ID_THAN_VU_TRU, ["thánh địa", "di chuyển"], now)
        else:
            caps = self.mem.read_current_menu()
            idx = next((i for w in ("thánh địa", "đến kaio", "di chuyển") for i, c in enumerate(caps) if w in c), -1)
            if idx >= 0:  # menu NPC dọc đường (Thượng Đế, Thần Vũ Trụ): XMAP hay đứng chờ ở đây
                self.mem.select_menu_option(idx)
                self.sword_at = now + 1500
                return False
            rv_st = self.mem.statics("rv", init=True)
            if self.sword_xmap_at == 0.0 or (not (rv_st and self.mem.read(rv_st, 1)[0]) and now - self.sword_xmap_at > 8000):
                self.sword_fail += 1
                if self.sword_fail > 5:
                    self.sword_xmap_at = 0.0
                    self.sword_retry(f"không tới được Thánh địa Kaio từ map {cur_map}", now)
                    return False
                self.sword_xmap_at = now
                self.show_game_scr()
                self.mem.call_fn(RVA_XMAP_START, MAP_ID_THANH_DIA_KAIO, 0)
            self.sword_at = now + 1000
        return False

    def sword_door(self, right, cur_map):
        """Qua cửa ở mép phải/trái map ngục tù: dịch vào cửa, game tự đổi map khi đứng trong cửa.
        Không bấm lệnh của cửa như go_waypoint: ở 2 map này làm vậy game văng ngay sau khi sang map (2 lần liền)."""
        jb, hx_st = self.mem.statics("jb"), self.mem.statics("hx")
        wps = self.mem.vec_items(self.mem.ptr(jb + 0xA0)) if jb else []
        if not wps:
            return
        min_x = lambda w: self.mem.num(w + 0x10, "<h")  # noqa: E731
        w = max(wps, key=min_x) if right else min(wps, key=min_x)
        x = self.mem.num(jb + 0x8, "<i") - 15 if right else 15
        self.mem.call_fn(RVA_TELEPORT, x, self.mem.num(w + 0x16, "<h"))  # dịch xa có khi dừng ngoài cửa, lần sau mới vào hẳn
        n = self.sword_door_n[1] + 1 if self.sword_door_n[0] == cur_map else 1
        self.sword_door_n = (cur_map, n)
        if n % 3 == 0 and hx_st:  # đứng trong cửa 2 lần mà chưa đổi map: xin đổi map (gói -23)
            time.sleep(0.3)
            self.mem.call_fn(RVA_REQUEST_CHANGE_MAP, self.mem.ptr(hx_st), 0)

    def sword_dodge_cumber(self, cur_zone, now):
        """Map ngục tù 2 hay có boss Cumber: thấy nó trong khu thì đổi sang khu khác. True = vừa xin đổi khu."""
        if not any("cumber" in norm_str(self.char_info(c)["name"]) for c in self.chars_in_map()):
            return False
        zones = [z["id"] for z in self.zone_list() if z["id"] != cur_zone and not (z["max"] > 0 and z["num"] >= z["max"])]
        self.request_zone(zones[int(now) % len(zones)] if zones else cur_zone + 1, now)
        self.log("Kiếm Z: khu có Cumber, đổi khu")
        self.sword_at = now + 3000
        return True

    def sword_open_shop(self, now):
        """Mở cửa hàng NPC Mai (mỗi lần gọi làm 1 bước); True khi cửa hàng đã mở"""
        if self.mem.is_shop_open():
            return True
        self.sword_npc_pick(NPC_ID_MAI, ["cửa hàng"], now)
        return False

    def sword_tick(self, me, cur_map, cur_zone, now):
        if now < self.sword_at:
            return True
        mem = self.mem
        if mem.num(me + 0x88, "<i") == 14 or mem.num(me + 0xD0, "<q") <= 0:  # chết: hồi sinh tại chỗ rồi làm tiếp
            hx_st = mem.statics("hx")
            mem.call_fn(RVA_REVIVE_HERE, mem.ptr(hx_st) if hx_st else 0, 0)
            self.sword_buy = None
            self.sword_at = now + 6000
            return True
        swords = mem.list_swords(me)
        if any(dmg is None for _slot, dmg, _lvl in swords):
            self.sword_at = now + 1000  # chỉ số chưa tải xong: chờ, tuyệt đối không vứt
            return True
        act = lambda sw: sword_action(sw[1], sw[2], self.sword_min_new, self.sword_max_level, self.sword_min_final)  # noqa: E731
        bad = [sw for sw in swords if act(sw) == "vứt"]
        if bad and not self.sword_buy:
            slot, dmg, lvl = bad[0]
            mem.close_menu()
            mem.hide_panels()
            if mem.throw_bag_item(slot):
                self.sword_fail = 0
                self.log(f"Kiếm Z: vứt kiếm +{lvl} sức đánh {dmg}%")
            else:
                self.sword_fail += 1
                if self.sword_fail > 10:
                    return self.sword_retry("không vứt được kiếm", now)
            self.sword_at = now + 400
            return True
        tinh, empty = mem.count_bag_item(me, ITEM_ID_TINH_THE)
        da, _ = mem.count_bag_item(me, ITEM_ID_DA_NGUC_TU)
        tv, _ = mem.count_bag_item(me, ITEM_ID_THOI_VANG)
        todo = [sw for sw in swords if act(sw) == "nâng"]
        self.sword_status_text = f"{self.sword_phase} | {len(swords)} kiếm ({len(todo)} cần nâng) | {tinh} tinh thể, {da} đá, {tv} TV"

        if self.sword_phase == "BUY":
            need = next((t for t, have, low in ((ITEM_ID_TINH_THE, tinh, SWORD_MIN_MAT), (ITEM_ID_DA_NGUC_TU, da, SWORD_MIN_MAT))
                         if have < low), 0)
            if self.sword_buy:  # đang mua: [tid, số lúc bắt đầu, các luồng, số lần xem gần nhất, lúc số tăng gần nhất]
                tid, start, items, last_have, last_t = self.sword_buy
                have = tinh if tid == ITEM_ID_TINH_THE else da
                if have != last_have:
                    self.sword_buy[3:] = [have, now]
                # cửa hàng bị đóng (mở hành trang, đổi khu...) hoặc 8 giây không mua thêm được cái nào: dừng lượt này, thiếu thì mua lại
                elif have - start >= SWORD_BUY_QTY or mem.remaining_autobuy_count(items) <= 0 or not mem.is_shop_open() or now - last_t > 8000:
                    mem.stop_all_autobuy(items)
                    time.sleep(0.5)  # chờ server trả nốt các lượt mua cuối rồi mới đếm
                    have = mem.count_bag_item(me, tid)[0]
                    self.log(f"Kiếm Z: đã mua {have - start} {'Tinh thể' if tid == ITEM_ID_TINH_THE else 'Đá ngục tù'}")
                    self.sword_buy = None
                    if have - start <= 0:
                        if empty <= 0 and self.sword_make_room(todo, now):
                            return True  # hành trang đầy thì không mua được: bỏ bớt 1 kiếm rồi mua lại (chưa được thì bỏ tiếp)
                        return self.sword_retry("không mua được nguyên liệu ở NPC Mai", now)
                self.sword_at = now + 500
                return True
            if not need:
                mem.hide_panels()
                self.sword_set_phase("EXCHANGE" if empty > 0 else "UPGRADE")
                return True
            if tv < SWORD_BUY_QTY:
                self.stop_sword_auto(f"Kiếm Z: không đủ {SWORD_BUY_QTY} Thỏi vàng để mua nguyên liệu")
                return False
            if not self.sword_goto(MAP_ID_NGUC_TU_2, cur_map, now) or self.sword_dodge_cumber(cur_zone, now):
                return True
            if empty <= 0 and (tinh if need == ITEM_ID_TINH_THE else da) <= 0 and self.sword_make_room(todo, now):
                return True  # hết sạch loại này + hành trang đầy: không có ô cho món mua về
            if not self.sword_open_shop(now):
                return True
            items = mem.start_autobuy(need, 10, SWORD_BUY_QTY // 10, 80)
            if not items:
                return self.sword_retry("không chạy được Auto Mua của MOD", now)
            have = tinh if need == ITEM_ID_TINH_THE else da
            self.sword_buy = [need, have, items, have, now]
            self.log(f"Kiếm Z: mua {SWORD_BUY_QTY} {'Tinh thể' if need == ITEM_ID_TINH_THE else 'Đá ngục tù'} ở NPC Mai")
            self.sword_at = now + 1000
            return True

        if self.sword_phase == "EXCHANGE":
            if empty <= 0:
                mem.close_menu()
                self.sword_set_phase("UPGRADE")
                return True
            if tinh < SWORD_MIN_MAT:
                self.sword_set_phase("BUY")
                return True
            if tv < SWORD_COST_THOI_VANG:
                self.stop_sword_auto("Kiếm Z: hết Thỏi vàng")
                return False
            if not self.sword_goto(MAP_ID_THANH_DIA_KAIO, cur_map, now):
                return True
            self.sword_fail += 1  # về 0 mỗi khi vứt được kiếm xấu; kiếm tốt thì túi đầy dần -> sang UPGRADE
            if self.sword_fail > 60 + 3 * empty:
                return self.sword_retry("Tổ Sư Kaio không đổi được kiếm", now)
            self.sword_npc_pick(NPC_ID_TO_SU_KAIO, ["vĩnh viễn", "trao đổi"], now)
            self.sword_at = now + 350
            return True

        # UPGRADE
        if not todo:
            mem.hide_panels()
            if empty <= 0:
                self.stop_sword_auto(f"Kiếm Z: hành trang đầy, đang giữ {len(swords)} kiếm +{self.sword_max_level}")
                return False
            self.sword_set_phase("EXCHANGE")
            return True
        if da < SWORD_MIN_MAT or tinh < SWORD_MIN_MAT:
            self.sword_set_phase("BUY")
            return True
        if not self.sword_goto(MAP_ID_NGUC_TU_2, cur_map, now) or self.sword_dodge_cumber(cur_zone, now):
            return True
        if not self.sword_open_shop(now):
            return True
        slot, dmg, lvl = todo[0]
        self.sword_fail += 1
        if self.sword_fail > 40:
            return self.sword_retry("nâng cấp không có tác dụng", now)
        if self.sword_last != (slot, lvl, da):
            self.sword_last = (slot, lvl, da)
            self.sword_fail = 0
        caps = mem.read_current_menu()
        if "đồng ý" in caps:  # menu xác nhận nâng cấp: "Đồng ý x100", "Đồng ý x10", "Đồng ý", "Từ chối" -> nâng từng lần
            mem.select_menu_option(caps.index("đồng ý"))
        elif caps:
            mem.close_menu()
        elif self.sword_fail % 6 == 5:
            mem.hide_panels()  # bấm mấy lần không ra menu nâng cấp: đóng hết, mở lại cửa hàng
        else:
            mem.use_bag_slot(slot)  # đang mở cửa hàng Mai mà bấm Sử dụng Kiếm Z = nâng cấp đúng thanh đó
        self.sword_at = now + 350
        return True

    def trigger_buy_stone_once(self):
        self.egg_single_action = "BUY_STONE"
        self.egg_phase_t = time.monotonic() * 1000.0
        self.log("Bấm mua 99 Đá Linh Lực (1 lần)...")

    def trigger_speedup_once(self):
        self.egg_single_action = "SPEEDUP"
        self.egg_phase_t = time.monotonic() * 1000.0
        self.log("Bấm giảm 1 ngày (1 lần)...")

    def trigger_hatch_once(self):
        self.egg_single_action = "HATCH"
        self.egg_phase_t = time.monotonic() * 1000.0
        self.log("Bấm nở trứng (1 lần)...")

    def find_egg_npc(self):
        """Tìm NPC Trứng trong ổ ấp ở map hiện tại (hỗ trợ cả Trứng Mabu ID 50 tại Nhà Bunma và Trứng Linh Thú ID 80)"""
        for tpl_id in EGG_INCUBATOR_NPC_IDS:
            npc = self.find_npc(tpl_id)
            if npc:
                return npc, tpl_id
        return 0, -1

    def find_egg_shop_npc(self):
        """Tìm NPC bán Trứng & Đá Linh Lực ở map hiện tại (hỗ trợ cả Bunma ID 37 tại Nhà Bunma và Thần mèo Karin ID 18)"""
        for tpl_id in EGG_SHOP_NPC_IDS:
            npc = self.find_npc(tpl_id)
            if npc:
                return npc, tpl_id
        return 0, -1

    def interact_egg_npc(self):
        _, tpl_id = self.find_egg_npc()
        if tpl_id < 0:
            return False
        return self.interact_npc(tpl_id)

    def interact_egg_shop_npc(self):
        _, tpl_id = self.find_egg_shop_npc()
        if tpl_id < 0:
            return False
        return self.interact_npc(tpl_id)

    def interact_npc(self, npc_tpl_id):
        self.close_dialogs()
        self.mem.hide_panels()
        self.mem.close_menu()
        bh_st = self.mem.statics("bh")
        me = self.mem.ptr(bh_st + 0xA8) if bh_st else 0
        npc = self.find_npc(npc_tpl_id)
        if not npc or not me:
            return False
        nx = self.mem.num(npc + 0x6C, "<i")
        ny = self.mem.num(npc + 0x70, "<i")
        mx = self.mem.num(me + 0x6C, "<i")
        my = self.mem.num(me + 0x70, "<i")
        hx_st = self.mem.statics("hx")
        svc = self.mem.ptr(hx_st) if hx_st else 0
        if abs(mx - nx) > 50 or abs(my - ny) > 50:
            self.mem.call_fn(RVA_TELEPORT, nx, (ny - 1) & 0xFFFFFFFF)
            time.sleep(0.18)  # chờ server nhận vị trí charMove mới trước khi gửi openMenu
        elif svc:
            self.mem.call_fn(RVA_CHAR_MOVE, svc, 0)
        self.mem.call_fn(RVA_FOCUS_TO, me, npc)
        if svc:
            self.mem.call_fn(RVA_OPEN_NPC_MENU, svc, npc_tpl_id & 0xFFFFFFFF)
            return True
        return False

    def egg_tick(self, me, cur_map, cur_zone, now):
        if not self.egg_active and not self.egg_single_action:
            return False

        if now - self.egg_last_action_at < self.egg_delay:
            return True

        if self.close_dialogs() or self.mem.confirm_msgdlg_if_open():
            self.egg_last_action_at = now + 200
            return True

        da_ll, _ = self.mem.count_bag_item(me, ITEM_ID_DA_LINH_LUC)
        thoi_vang, _ = self.mem.count_bag_item(me, ITEM_ID_THOI_VANG)

        # Xử lý các lệnh đơn lẻ (chạy 1 lần)
        if self.egg_single_action:
            act = self.egg_single_action
            caps = self.mem.read_current_menu()
            if act == "BUY_STONE":
                if caps:
                    pick = -1
                    for idx, c in enumerate(caps):
                        if "99 đá linh lực" in c or "đá linh lực" in c or "da linh luc" in c:
                            pick = idx
                            break
                    if pick >= 0:
                        self.mem.select_menu_option(pick)
                        self.egg_stones_bought += 99
                        self.log("Đã mua 99 Đá Linh Lực thành công!")
                        self.egg_single_action = None
                        self.egg_last_action_at = now + 450
                        return True
                    self.mem.close_menu()
                    self.egg_last_action_at = now + 200
                    return True
                if not self.interact_egg_shop_npc():
                    self.log("Không tìm thấy NPC Bunma / Karin ở map hiện tại!")
                    self.egg_single_action = None
                self.egg_last_action_at = now + 450
                return True

            elif act == "SPEEDUP":
                if caps:
                    # Bước xác nhận cuối ('ok', 'từ chối') sau khi bấm '30 Đá LL +3 TV 1 ngày'
                    if caps[0] == "ok" and not any("cửa hàng" in x or "cua hang" in x for x in caps):
                        self.mem.select_menu_option(0)
                        self.egg_days_reduced += 1
                        self.log("Đã truyền linh lực giảm 1 ngày thành công!")
                        self.egg_single_action = None
                        self.egg_last_action_at = now + 350
                        return True
                    pick = -1
                    for idx, c in enumerate(caps):
                        if any(w in c for w in ["1 ngày", "1 ngay", "30 đá ll", "30 da ll", "30 đá linh lực"]):
                            pick = idx
                            break
                    if pick >= 0:
                        self.mem.select_menu_option(pick)
                        self.egg_last_action_at = now + 350
                        return True
                    inter = -1
                    for idx, c in enumerate(caps):
                        if any(w in c for w in ["truyền linh lực", "truyen linh luc", "tăng tốc", "tang toc", "ấp nhanh"]):
                            inter = idx
                            break
                    if inter >= 0:
                        self.mem.select_menu_option(inter)
                        self.egg_last_action_at = now + 350
                        return True
                    self.mem.close_menu()
                    self.egg_last_action_at = now + 200
                    return True
                if not self.interact_egg_npc():
                    self.log("Không tìm thấy Trứng Linh Thú ở map hiện tại!")
                    self.egg_single_action = None
                self.egg_last_action_at = now + 450
                return True

            elif act == "HATCH":
                if caps:
                    pick = -1
                    for idx, c in enumerate(caps):
                        if any(w in c for w in ["nở trứng", "no trung", "nở", "nhận", "nhan", "hoàn thành", "ấp trứng xong"]):
                            pick = idx
                            break
                    if pick >= 0:
                        is_first_hatch_menu = any("hủy bỏ" in x or "huy bo" in x for x in caps)
                        self.mem.select_menu_option(pick)
                        if is_first_hatch_menu:
                            self.egg_last_action_at = now + 350
                            return True
                        self.egg_hatched_count += 1
                        self.log("Đã nở trứng thành công!")
                        self.egg_single_action = None
                        self.egg_last_action_at = now + 600
                        return True
                    self.mem.close_menu()
                    self.egg_last_action_at = now + 200
                    return True
                if not self.interact_egg_npc():
                    self.log("Không tìm thấy Trứng Linh Thú ở map hiện tại!")
                    self.egg_single_action = None
                self.egg_last_action_at = now + 450
                return True

        # ---- XỬ LÝ TOÀN BỘ VÒNG LẶP AUTO CHÍNH ----
        caps = self.mem.read_current_menu()

        # 0. Khi đang trong pha RELOAD_MAP (sang Siêu Thị rồi quay lại Nhà Bunma để load trứng): xác nhận menu 'đồng ý' nếu còn, đóng menu cản đường
        if self.egg_phase == "RELOAD_MAP":
            if caps:
                confirm_pick = -1
                for idx, c in enumerate(caps):
                    if any(w in c for w in ("đồng ý", "dong y", "xác nhận", "xac nhan")):
                        confirm_pick = idx
                        break
                if confirm_pick >= 0:
                    self.mem.select_menu_option(confirm_pick)
                    self.egg_last_action_at = now + 350
                else:
                    self.mem.close_menu()
                    self.egg_last_action_at = now + 150
                return True
            self.mem.hide_panels()
            if not self.egg_visited_sieu_thi:
                if cur_map == MAP_ID_SIEU_THI:
                    self.egg_visited_sieu_thi = True
                    self.mem.call_fn(RVA_XMAP_STOP, 0, 0)
                    self.egg_status_text = "Quay lại Nhà Bunma..."
                    self.log("Đã sang map Siêu Thị -> Quay trở lại Nhà Bunma để ấp trứng...")
                    self.egg_last_action_at = now + 700
                    return True
                # Nếu ở map khác (vd unit test không có waypoint sang Siêu Thị) mà trứng đã xuất hiện ngay trong ổ ấp
                if cur_map != MAP_ID_NHA_BUNMA and self.find_egg_npc()[0]:
                    self.egg_phase = "SPEEDUP"
                    self.egg_last_action_at = now + 200
                    return True
                self.egg_status_text = "Sang map Siêu Thị..."
                if not self.go_waypoint("phải"):
                    if self.find_egg_npc()[0]:
                        self.egg_phase = "SPEEDUP"
                        self.egg_last_action_at = now + 200
                        return True
                self.egg_last_action_at = now + 800
                return True
            else:
                if cur_map == self.egg_home_map or cur_map == MAP_ID_NHA_BUNMA:
                    if self.find_egg_npc()[0]:
                        self.log("Đã quay lại Nhà Bunma, phát hiện Trứng trong ổ ấp -> Bắt đầu ấp trứng nhanh!")
                        self.egg_phase = "SPEEDUP"
                        self.egg_status_text = "Bắt đầu ấp trứng nhanh"
                        self.egg_last_action_at = now + 300
                        return True
                    if now - self.egg_reload_started_at > 12000:
                        # Đã về lại Nhà Bunma quá lâu nhưng chưa thấy trứng -> thử sang Siêu Thị lại 1 lần hoặc về SPEEDUP
                        self.egg_phase = "SPEEDUP"
                    self.egg_last_action_at = now + 500
                    return True
                self.egg_status_text = "Về lại Nhà Bunma..."
                self.go_waypoint("trái")
                self.egg_last_action_at = now + 800
                return True

        # 1. Nếu menu đang hiển thị trên màn hình:
        if caps:
            # 1.1. Khi đang ở pha BUY_EGG: ưu tiên tìm nút "Cửa hàng" (không để mục "99 Đá Linh Lực" của Bunma/Karin cướp quyền)
            if self.egg_phase == "BUY_EGG":
                shop_pick = -1
                for idx, c in enumerate(caps):
                    if "cửa hàng" in c or "cua hang" in c or "shop" in c:
                        shop_pick = idx
                        break
                if shop_pick >= 0:
                    self.mem.select_menu_option(shop_pick)
                    self.egg_shop_opened = True
                    self.egg_buy_tries = 0
                    self.egg_status_text = "Mở Cửa hàng tìm Trứng"
                    self.egg_last_action_at = now + 550
                    return True
                confirm_pick = -1
                for idx, c in enumerate(caps):
                    if any(w in c for w in ["đồng ý", "dong y", "xác nhận", "xac nhan", "mua"]):
                        confirm_pick = idx
                        break
                if confirm_pick >= 0:
                    self.mem.select_menu_option(confirm_pick)
                    self.egg_last_action_at = now + 450
                    return True
                self.mem.close_menu()
                self.egg_last_action_at = now + 200
                return True

            # 1.2. Khi đang ở pha BUY_STONE: tìm nút "99 Đá Linh Lực" trên menu Bunma / Karin
            if self.egg_phase == "BUY_STONE":
                stone_pick = -1
                for idx, c in enumerate(caps):
                    if "99 đá linh lực" in c or "đá linh lực" in c or "da linh luc" in c:
                        stone_pick = idx
                        break
                if stone_pick >= 0:
                    if thoi_vang < 14:
                        self.stop_egg_auto(f"Hết Thỏi vàng để mua 99 Đá LL (còn {thoi_vang} < 14 TV)")
                        return True
                    self.mem.select_menu_option(stone_pick)
                    self.egg_stones_bought += 99
                    self.egg_status_text = f"Đã mua {self.egg_stones_bought} Đá LL"
                    self.log(f"Đã mua 99 Đá Linh Lực (tốn 14 Thỏi vàng). Tổng mua: {self.egg_stones_bought}")
                    if da_ll + 99 >= self.egg_stone_needed:
                        self.egg_stone_needed = 30
                        self.egg_phase = "SPEEDUP"
                    self.egg_last_action_at = now + 450
                    return True
                confirm_pick = -1
                for idx, c in enumerate(caps):
                    if any(w in c for w in ["đồng ý", "dong y", "xác nhận", "xac nhan"]):
                        confirm_pick = idx
                        break
                if confirm_pick >= 0:
                    self.mem.select_menu_option(confirm_pick)
                    self.egg_last_action_at = now + 400
                    return True
                self.mem.close_menu()
                self.egg_last_action_at = now + 200
                return True

            # 1.3. Menu có nút "Nở" / "Nở trứng" / "Nhận" (hỗ trợ menu 2 bước: ['nở', 'hủy bỏ trứng'] -> ['nở', 'từ chối'], cần >= 200 Đá LL)
            hatch_pick = -1
            for idx, c in enumerate(caps):
                if any(w in c for w in ["nở trứng", "no trung", "nở", "nhận", "nhan", "hoàn thành", "ấp trứng xong"]):
                    hatch_pick = idx
                    break
            if hatch_pick >= 0:
                if da_ll < 200:
                    if self.egg_auto_buy_stone:
                        self.mem.close_menu()
                        self.egg_stone_needed = 200
                        self.egg_phase = "BUY_STONE"
                        self.egg_status_text = "Thiếu Đá LL nở trứng -> Mua Đá LL"
                        self.log(f"Đá Linh Lực còn {da_ll} (< 200 để đánh thức nở trứng) -> Chuyển sang mua 99 Đá LL...")
                        self.egg_last_action_at = now + 250
                        return True
                    else:
                        self.stop_egg_auto(f"Hết Đá Linh Lực để nở trứng (còn {da_ll} < 200)")
                        return True
                is_first_hatch_menu = any("hủy bỏ" in x or "huy bo" in x for x in caps)
                self.mem.select_menu_option(hatch_pick)
                if is_first_hatch_menu:
                    self.egg_status_text = "Xác nhận nở trứng..."
                    self.egg_last_action_at = now + 380
                    return True
                self.egg_hatched_count += 1
                self.egg_status_text = f"Đã nở quả thứ {self.egg_hatched_count}"
                self.log(f"Trứng đã nở thành công! (Tổng số trứng đã nở: {self.egg_hatched_count})")
                self.egg_last_action_at = now + 1500
                slot, _, _ = self.mem.find_egg_in_bag(me)
                if slot >= 0 and self.egg_auto_use_egg:
                    self.egg_phase = "USE_EGG"
                elif self.egg_auto_buy_egg:
                    self.egg_phase = "BUY_EGG"
                    self.egg_shop_opened = False
                    self.egg_buy_tries = 0
                elif self.egg_auto_use_egg:
                    self.egg_phase = "USE_EGG"
                else:
                    self.stop_egg_auto("Trứng đã nở xong!")
                return True

            # 1.4. Menu có nút "1 ngày" (Menu Trứng bước 2: '30 đá ll +3 tv 1 ngày')
            speedup_pick = -1
            for idx, c in enumerate(caps):
                if any(w in c for w in ["1 ngày", "1 ngay", "30 đá ll", "30 da ll", "30 đá linh lực"]):
                    speedup_pick = idx
                    break
            if speedup_pick >= 0:
                # Kiểm tra Đá Linh Lực
                if da_ll < 30:
                    if self.egg_auto_buy_stone:
                        self.mem.close_menu()
                        self.egg_phase = "BUY_STONE"
                        self.egg_status_text = "Hết Đá LL -> Mua 99 Đá LL"
                        self.log(f"Đá Linh Lực còn {da_ll} (< 30) -> Chuyển sang mua 99 Đá LL (14 TV)...")
                        self.egg_last_action_at = now + 250
                        return True
                    else:
                        self.stop_egg_auto(f"Hết Đá Linh Lực (còn {da_ll} < 30)")
                        return True

                if thoi_vang < 3:
                    self.stop_egg_auto(f"Hết Thỏi vàng (còn {thoi_vang} < 3 TV để giảm 1 ngày)")
                    return True

                # Bấm giảm 1 ngày
                self.mem.select_menu_option(speedup_pick)
                self.egg_days_reduced += 1
                self.egg_status_text = f"Đang ấp (-{self.egg_days_reduced} ngày)"
                self.egg_last_action_at = now + max(self.egg_delay, 280)
                if self.egg_target_days > 0 and self.egg_days_reduced >= self.egg_target_days and not self.mem.read_current_menu():
                    self.stop_egg_auto(f"Đã hoàn thành mục tiêu giảm {self.egg_days_reduced} ngày!")
                return True

            # 1.5. Menu trung gian / xác nhận (vd: "Truyền linh lực", ['ok', 'từ chối'], "Đồng ý", "Xác nhận")
            inter_pick = -1
            is_shop_menu = any("cửa hàng" in x or "cua hang" in x for x in caps)
            for idx, c in enumerate(caps):
                if any(w in c for w in ["truyền linh lực", "truyen linh luc", "tăng tốc", "tang toc", "ấp nhanh", "ap nhanh", "đồng ý", "dong y", "xác nhận", "xac nhan"]):
                    inter_pick = idx
                    break
                if c == "ok" and not is_shop_menu:
                    inter_pick = idx
                    break
            if inter_pick >= 0:
                self.mem.select_menu_option(inter_pick)
                self.egg_last_action_at = now + max(self.egg_delay, 280)
                return True

            # 1.6. Nếu menu đang mở không khớp mục nào (vd menu Bunma/Karin cũ còn sót): đóng menu
            self.mem.close_menu()
            if self.egg_phase == "SPEEDUP":
                slot, _, _ = self.mem.find_egg_in_bag(me)
                if slot >= 0 and self.egg_auto_use_egg:
                    self.egg_phase = "USE_EGG"
                elif self.egg_auto_buy_egg:
                    self.egg_phase = "BUY_EGG"
                    self.egg_shop_opened = False
                    self.egg_buy_tries = 0
            self.egg_last_action_at = now + 250
            return True

        # 2. Nếu không có menu nào đang hiển thị:
        if self.egg_phase == "INIT":
            if cur_map == MAP_ID_SIEU_THI:
                self.egg_home_map = MAP_ID_NHA_BUNMA
                self.egg_visited_sieu_thi = True
                self.egg_reload_started_at = now
                self.egg_phase = "RELOAD_MAP"
                self.egg_last_action_at = now + 100
                return True
            if self.find_egg_npc()[0]:
                if da_ll < 30 and self.egg_auto_buy_stone:
                    self.egg_phase = "BUY_STONE"
                else:
                    self.egg_phase = "SPEEDUP"
            else:
                slot, _, _ = self.mem.find_egg_in_bag(me)
                if slot >= 0 and self.egg_auto_use_egg:
                    self.egg_phase = "USE_EGG"
                elif self.egg_auto_buy_egg:
                    self.egg_phase = "BUY_EGG"
                    self.egg_shop_opened = False
                    self.egg_buy_tries = 0
                else:
                    self.egg_phase = "SPEEDUP"
            self.egg_last_action_at = now + 100
            return True

        elif self.egg_phase == "BUY_STONE":
            if da_ll >= self.egg_stone_needed:
                self.egg_stone_needed = 30
                self.egg_phase = "SPEEDUP"
                self.egg_last_action_at = now + 100
                return True
            if thoi_vang < 14:
                self.stop_egg_auto("Hết Thỏi vàng (cần ít nhất 14 Thỏi vàng để mua 99 Đá LL)")
                return True
            self.egg_status_text = "Mở Bunma/Karin mua Đá LL"
            if not self.interact_egg_shop_npc():
                self.egg_status_text = "Chờ gặp Bunma / Karin..."
                self.egg_last_action_at = now + 800
                return True
            self.egg_last_action_at = now + 450
            return True

        elif self.egg_phase == "SPEEDUP":
            if not self.find_egg_npc()[0]:
                slot, _, name = self.mem.find_egg_in_bag(me)
                if slot >= 0 and self.egg_auto_use_egg:
                    self.log(f"Ổ ấp chưa có trứng, phát hiện {name} trong hành trang -> Sử dụng 1 quả trứng...")
                    self.egg_phase = "USE_EGG"
                    self.egg_last_action_at = now + 150
                    return True
                if self.egg_auto_buy_egg and self.find_egg_shop_npc()[0]:
                    self.log("Ổ ấp & hành trang chưa có trứng -> Chuyển sang mua 1 Trứng tại Cửa hàng...")
                    self.egg_phase = "BUY_EGG"
                    self.egg_shop_opened = False
                    self.egg_buy_tries = 0
                    self.egg_last_action_at = now + 150
                    return True
                self.egg_status_text = "Chờ Trứng Linh Thú..."
                self.egg_last_action_at = now + 800
                return True
            if da_ll < 30:
                if self.egg_auto_buy_stone:
                    self.egg_stone_needed = 30
                    self.egg_phase = "BUY_STONE"
                    self.egg_last_action_at = now + 100
                    return True
                else:
                    self.stop_egg_auto(f"Hết Đá Linh Lực (còn {da_ll} < 30)")
                    return True
            self.egg_status_text = f"Mở Trứng Linh thú (-{self.egg_days_reduced} ngày)"
            self.interact_egg_npc()
            self.egg_last_action_at = now + 400
            return True

        elif self.egg_phase == "BUY_EGG":
            slot, tid, name = self.mem.find_egg_in_bag(me)
            if slot >= 0:
                self.mem.hide_panels()
                self.egg_shop_opened = False
                self.egg_buy_tries = 0
                self.log(f"Trong hành trang đã có {name} (ô {slot}) -> Chuyển sang Sử dụng 1 quả trứng...")
                self.egg_phase = "USE_EGG"
                self.egg_last_action_at = now + 250
                return True

            if self.egg_shop_opened or self.mem.is_panel_open():
                it_shop, tid_shop, name_shop = self.mem.find_egg_in_shop(me)
                if it_shop and tid_shop > 0:
                    self.log(f"Tìm thấy {name_shop} (ID {tid_shop}) trong Cửa hàng -> Đang mua 1 quả...")
                    self.egg_status_text = f"Đang mua {name_shop}..."
                    self.mem.buy_shop_item(it_shop, retry=self.egg_buy_tries)
                    self.egg_buy_tries += 1
                    if self.egg_buy_tries >= 4:
                        self.egg_shop_opened = False
                        self.egg_buy_tries = 0
                    self.egg_last_action_at = now + 750
                    return True
                self.egg_buy_tries += 1
                if self.egg_buy_tries < 3:
                    self.egg_last_action_at = now + 350
                    return True
                self.egg_shop_opened = False
                self.egg_buy_tries = 0

            self.egg_status_text = "Mở Cửa hàng mua Trứng"
            if not self.interact_egg_shop_npc():
                self.egg_status_text = "Chờ gặp Bunma / Karin..."
                self.egg_last_action_at = now + 800
                return True
            self.egg_last_action_at = now + 500
            return True

        elif self.egg_phase == "USE_EGG":
            if not self.egg_auto_use_egg:
                self.stop_egg_auto("Đã mua trứng mới. Tự dùng trứng đang tắt.")
                return True
            slot, tid, name = self.mem.find_egg_in_bag(me)
            if slot >= 0:
                self.egg_status_text = f"Dùng 1 {name} vào ổ ấp"
                self.log(f"Đang sử dụng 1 {name} từ hành trang (ô {slot})...")
                if self.mem.use_bag_item(slot):
                    self.log(
                        f"Đã dùng 1 {name}! Sang map Siêu Thị rồi quay lại Nhà Bunma để load trứng và bắt đầu ấp..."
                    )
                    self.egg_home_map = cur_map if cur_map > 0 else MAP_ID_NHA_BUNMA
                    self.egg_visited_sieu_thi = False
                    self.egg_reload_started_at = now
                    self.egg_phase = "RELOAD_MAP"
                    self.egg_status_text = "Sang Siêu Thị load trứng..."
                    self.egg_last_action_at = now + 500
                    return True
                else:
                    self.egg_last_action_at = now + 450
                    return True
            else:
                if self.find_egg_npc()[0]:
                    self.egg_phase = "SPEEDUP"
                elif self.egg_auto_buy_egg:
                    self.egg_phase = "BUY_EGG"
                    self.egg_shop_opened = False
                    self.egg_buy_tries = 0
                else:
                    self.stop_egg_auto("Không còn trứng trong hành trang!")
                self.egg_last_action_at = now + 300
                return True

        return True

    def save_mod_flags(self):
        saved = []
        for cls, off in self.MOD_FLAGS:
            st = self.mem.statics(cls)
            saved.append(self.mem.read(st + off, 1)[0] if st else 0)
        self.mod_saved = saved
        fg_st = self.mem.statics("fg")
        self.locate_saved = self.mem.ptr(fg_st + 0xC0) if fg_st else 0

    def restore_mod_flags(self):
        if not self.mod_saved:
            return
        for (cls, off), val in zip(self.MOD_FLAGS, self.mod_saved):
            st = self.mem.statics(cls)
            if st:
                self.mem.write(st + off, bytes([val]))
        fg_st = self.mem.statics("fg")
        if fg_st and self.locate_saved:
            self.mem.write(fg_st + 0xC0, struct.pack("<Q", self.locate_saved))
        self.mod_saved = None

    def quiet_mod(self):
        for cls, off in [("fg", 0x10), ("rs", 0x10), ("rs", 0x11), ("rs", 0x15), ("dg", 0x364), ("rs", 0x41)]:
            st = self.mem.statics(cls)
            if st:
                self.mem.write(st + off, b"\x00")
        loot = b"\x01" if self.state == "LOOT" else b"\x00"
        rs_st = self.mem.statics("rs")
        if rs_st:
            self.mem.write(rs_st + 0x40, loot)
            self.mem.write(rs_st + 0x42, loot)
        fg_st = self.mem.statics("fg")
        if fg_st:
            self.mem.write(fg_st + 0xC9, b"\x01" if self.state == "FIGHT" else b"\x00")
            str_st = self.mem.statics("String")
            if str_st:
                empty_str = self.mem.ptr(str_st)
                if empty_str:
                    self.mem.write(fg_st + 0xC0, struct.pack("<Q", empty_str))

    def release_target(self):
        bh = self.mem.statics("bh")
        me = self.mem.ptr(bh + 0xA8) if bh else 0
        if me:
            self.mem.write(me + 0x2C8, struct.pack("<Q", 0))
        fg_st = self.mem.statics("fg")
        if fg_st:
            self.mem.write(fg_st + 0x0, b"\x00")

    def show_game_scr(self):
        dd_st = self.mem.statics("dd")
        if dd_st:
            menu = self.mem.ptr(dd_st + 0xD0)
            if menu:
                self.mem.write(menu + 0x10, b"\x00")
            for off in (0xD8, 0xE0):
                panel = self.mem.ptr(dd_st + off)
                if panel and self.mem.read(panel + 0x10, 1) != b"\x00":
                    self.mem.call_fn(RVA_PANEL_HIDE, panel, 0)
        dg_st = self.mem.statics("dg")
        scr = self.mem.ptr(dg_st + 0x18) if dg_st else 0
        if scr:
            kl = self.mem.ptr(scr)
            fn = self.mem.ptr(kl + 0x178)
            mi = self.mem.ptr(kl + 0x180)
            if fn:
                self.mem.call_fn(fn, scr, mi)

    # ---------- Tự động làm Nhiệm Vụ Chính Tuyến ----------
    def classify_quest_step(self, q):
        if q["done"]:
            return "DONE"
        if q["npc"] >= 0:
            return "TALK"
        if q["need"] > 1:
            return "KILL"
        if boss_name_of_quest(q["title"]):
            return "BOSS"
        if q["map"] >= 0:
            return "GOTO"
        return "UNKNOWN"

    def close_dialogs(self):
        bj_st = self.mem.statics("bj")
        if bj_st:
            cur = self.mem.ptr(bj_st + 0x10)
            if cur:
                self.mem.write(bj_st + 0x3C, struct.pack("<i", 0))
                self.mem.perform_action(cur, 8000, 0)
                return True
            srv = self.mem.ptr(bj_st + 0x18)
            if srv:
                self.mem.perform_action(srv, 1001, 0)
                return True
        bh_st = self.mem.statics("bh")
        if bh_st:
            self.mem.write(bh_st + 0xE2, b"\x00")
        return False

    def find_npc(self, npc_tpl_id):
        dg_st = self.mem.statics("dg")
        if not dg_st:
            return 0
        for n in self.mem.vec_items(self.mem.ptr(dg_st + 0x118)):
            t = self.mem.ptr(n + 0x760)
            if t and self.mem.num(t + 0x10, "<i") == npc_tpl_id and self.mem.read(n + 0x774, 1) == b"\x00":
                return n
        return 0

    def mob_template_name(self, tpl_id):
        fa_st = self.mem.statics("fa")
        arr = self.mem.ptr(fa_st) if fa_st else 0
        if not arr or tpl_id < 0 or tpl_id >= self.mem.num(arr + 0x18, "<i"):
            return ""
        t = self.mem.ptr(arr + 0x20 + 8 * tpl_id)
        return self.mem.string(t + 0x18) if t else ""

    def quest_mob_template(self, title):
        t_norm = norm_str(title)
        dg_st = self.mem.statics("dg")
        if not dg_st:
            return -1, 0
        mobs = self.mem.vec_items(self.mem.ptr(dg_st + 0x110))
        best_id, best_len, best_mob = -1, 0, 0
        for m in mobs:
            mid = self.mem.num(m + 0xE0, "<i")
            mname = norm_str(self.mob_template_name(mid))
            if mname and len(mname) > best_len and mname in t_norm:
                best_id, best_len, best_mob = mid, len(mname), m
        # Bước nhặt vật phẩm rơi từ quái trong map (vd: "Thu thập 10 đùi gà"): chọn quái đầu tiên trong map
        if best_id < 0 and mobs:
            first_mob = mobs[0]
            return self.mem.num(first_mob + 0xE0, "<i"), first_mob
        return best_id, best_mob

    def handle_npc_menu(self):
        dd_st = self.mem.statics("dd")
        menu = self.mem.ptr(dd_st + 0xD0) if dd_st else 0
        if not menu or self.mem.read(menu + 0x10, 1) == b"\x00":
            return False
        items = self.mem.vec_items(self.mem.ptr(menu + 0x18))
        caps = []
        for c in items:
            sub = [x for x in self.mem.str_array(self.mem.ptr(c + 0x28)) if x]
            txt = " ".join(sub) if sub else self.mem.string(c + 0x20)
            caps.append(norm_str(txt.replace("\n", " ")))
        pick = -1
        for w in QUEST_MENU_WORDS:
            for idx, cap in enumerate(caps):
                if w in cap:
                    pick = idx
                    break
            if pick >= 0:
                break
        self.mem.write(menu + 0x20, struct.pack("<i", pick if pick >= 0 else 0))
        self.mem.write(menu + 0x85, b"\x00")
        self.mem.write(menu + 0x84, b"\x01" if pick >= 0 else b"\x00")
        self.mem.call_fn(RVA_MENU_CLOSE, menu, 0)
        self.log(f'Chọn menu NPC: "{caps[pick]}"' if pick >= 0 else f'Đóng menu NPC ({ " | ".join(caps) })')
        return True

    def stop_kill_mobs(self):
        rs_st = self.mem.statics("rs")
        if rs_st:
            self.mem.write(rs_st + 0x10, b"\x00")
        if self.q_kill_tpl >= 0:
            fz = self.mem.mod_instance()
            if fz:
                self.mem.perform_action(fz, 18, 0)
            self.q_kill_tpl = -1

    def pause_quest(self, reason):
        self.stop_kill_mobs()
        self.quest_mode = False
        self.log("Tạm dừng tự làm nhiệm vụ: " + reason)

    def quest_travel(self, target_map, cur_map, now):
        if target_map < 0 or cur_map == target_map:
            return True
        if self.q_xmap_map != target_map:
            self.q_xmap_map = target_map
            self.q_xmap_tries = 0
            self.q_xmap_at = 0.0
        rv_st = self.mem.statics("rv", init=True)
        xmap_running = bool(self.mem.read(rv_st, 1)[0]) if rv_st else False
        if self.q_xmap_at == 0.0 or (not xmap_running and now - self.q_xmap_at > 8000):
            if self.q_xmap_tries >= 3:
                self.pause_quest(f"XMAP không tới được map {target_map}")
                return False
            self.q_xmap_tries += 1
            self.q_xmap_at = now
            self.show_game_scr()
            self.mem.call_fn(RVA_XMAP_START, target_map, 0)
            self.log(f"Nhiệm vụ: XMAP tới map {target_map}")
        return False

    def quest_tick(self, me, cur_map, cur_zone, now):
        q = self.mem.read_quest_info(me)
        if not q:
            return
        key = f'{q["id"]}:{q["step"]}'
        if key != self.q_key:
            self.stop_kill_mobs()
            self.q_key = key
            self.q_action = self.classify_quest_step(q)
            self.q_t = now
            self.q_tries = 0
            self.q_phase = ""
            self.log(f'Nhiệm vụ {q["id"]} bước {q["step"] + 1}/{q["total"]}: {q["title"] or "(hoàn thành)"} [{self.q_action}]')

        if now - self.q_last_popup_at > 400 and self.close_dialogs():
            self.q_last_popup_at = now
            return

        if self.q_action == "DONE":
            return
        if self.q_action == "UNKNOWN":
            self.pause_quest(f'chưa hỗ trợ bước "{q["title"]}"')
            return

        if self.q_action == "BOSS":
            if self.state != "IDLE":
                return
            bname = boss_name_of_quest(q["title"])
            cluster = {"name": "Nhiệm vụ", "enabled": True, "members": [bname]}
            for c in self.chars_in_map():
                info = self.char_info(c)
                if info["id"] < 0 and info["hp"] > 0 and member_matches(bname, norm_str(info["name"])):
                    self.cluster = cluster
                    self.target_map = cur_map
                    self.target_name = info["name"]
                    self.boss_zone = cur_zone
                    self.revives_this_target = 0
                    self.last_seen = now
                    self.set_state("FIGHT", f"Nhiệm vụ: đánh {bname} ngay tại khu {cur_zone}")
                    return
            # Nếu bước nhiệm vụ có chỉ định map cố định (vd: Kuku, Mập đầu đinh, Rambo, Tàu Pảy Pảy)
            if q["map"] >= 0:
                self.cluster = cluster
                self.target_map = q["map"]
                self.target_name = bname
                self.notice_ptr = 0
                self.zone = -1
                self.xmap_tries = 0
                self.zone_req = -1
                self.last_zone_at = 0.0
                self.next_zone_at = 0.0
                self.retry_zone = -1
                self.same_fails = 0
                self.total_fails = 0
                self.visited = set()
                self.list_zone = -1
                self.zone_info = ""
                self.boss_zone = -1
                self.revives_this_target = 0
                self.show_game_scr()
                self.set_state("TRAVEL", f'Nhiệm vụ: tới map {q["map"]} tìm diệt {bname}')
                self.xmap_at = 0.0
                return
            for b in self.all_boss_notices():
                if b["mapId"] > 0 and member_matches(bname, norm_str(b["name"])) and b["ptr"] not in self.done and now >= self.bad_maps.get(b["mapId"], 0):
                    self.cluster = cluster
                    self.target_map = b["mapId"]
                    self.target_name = b["name"]
                    self.notice_ptr = b["ptr"]
                    self.zone = -1
                    self.xmap_tries = 0
                    self.zone_req = -1
                    self.last_zone_at = 0.0
                    self.next_zone_at = 0.0
                    self.retry_zone = -1
                    self.same_fails = 0
                    self.total_fails = 0
                    self.visited = set()
                    self.list_zone = -1
                    self.zone_info = ""
                    self.boss_zone = -1
                    self.revives_this_target = 0
                    self.show_game_scr()
                    self.set_state("TRAVEL", f'Nhiệm vụ: săn {bname} tại {b["map"]} (map {b["mapId"]})')
                    self.xmap_at = 0.0
                    return
            if self.q_phase != "wait":
                self.q_phase = "wait"
                self.log(f"Nhiệm vụ: đang chờ boss {bname} xuất hiện...")
            return

        if self.q_action == "GOTO":
            if not self.quest_travel(q["map"], cur_map, now):
                return
            hx = self.mem.num(me + 0x3A8, "<h")
            hy = self.mem.num(me + 0x3AA, "<h")
            if hx and hy and self.q_phase != "hint":
                self.q_phase = "hint"
                self.mem.call_fn(RVA_TELEPORT, hx, hy)
                self.log("Nhiệm vụ: dịch chuyển tới điểm nhấp nháy")
            if now - self.q_t > 30000:
                self.pause_quest(f'đã tới map {q["map"]} nhưng bước "{q["title"]}" chưa hoàn thành')
            return

        if self.q_action == "TALK":
            if not self.quest_travel(q["map"], cur_map, now):
                return
            if now - self.q_t < 1500:
                return
            if self.q_phase == "menu" and now - self.q_talk_at < 8000:
                if self.handle_npc_menu():
                    self.q_talk_at = now - 6000
                return
            if self.q_tries >= 3:
                self.pause_quest(f'nói chuyện với NPC {q["npc"]} 3 lần nhưng chưa xong "{q["title"]}"')
                return
            npc = self.find_npc(q["npc"])
            if not npc:
                if now - self.q_t > 15000:
                    self.pause_quest(f'không tìm thấy NPC {q["npc"]} ở map {cur_map}')
                return
            dd_st = self.mem.statics("dd")
            menu = self.mem.ptr(dd_st + 0xD0) if dd_st else 0
            if menu and self.mem.read(menu + 0x10, 1) != b"\x00":
                self.mem.write(menu + 0x85, b"\x00")
                self.mem.write(menu + 0x84, b"\x00")
                self.mem.call_fn(RVA_MENU_CLOSE, menu, 0)
            nx = self.mem.num(npc + 0x6C, "<i")
            ny = self.mem.num(npc + 0x70, "<i")
            if abs(self.mem.num(me + 0x6C, "<i") - nx) > 40:
                self.mem.call_fn(RVA_TELEPORT, nx, (ny - 1) & 0xFFFFFFFF)
            self.mem.call_fn(RVA_FOCUS_TO, me, npc)
            hx_st = self.mem.statics("hx")
            svc = self.mem.ptr(hx_st) if hx_st else 0
            if not svc:
                return
            self.mem.call_fn(RVA_OPEN_NPC_MENU, svc, q["npc"] & 0xFFFFFFFF)
            self.q_tries += 1
            self.q_phase = "menu"
            self.q_talk_at = now
            tpl = self.mem.ptr(npc + 0x760)
            npc_name = self.mem.string(tpl + 0x18) if tpl else f'NPC {q["npc"]}'
            self.log(f"Nhiệm vụ: nói chuyện với {npc_name} (lần {self.q_tries})")
            return

        if self.q_action == "KILL":
            if not self.quest_travel(q["map"], cur_map, now):
                return
            if now - self.q_t < 1500:
                return
            if self.q_kill_tpl < 0:
                tpl_id, mob = self.quest_mob_template(q["title"])
                if not mob:
                    if now - self.q_t > 15000:
                        self.pause_quest(f'không thấy quái cần đánh trong "{q["title"]}" ở map {cur_map}')
                    return
                fz = self.mem.mod_instance()
                if fz:
                    self.mem.perform_action(fz, 18, 0)
                    self.mem.perform_action(fz, 19, mob)
                rs_st = self.mem.statics("rs")
                if rs_st:
                    self.mem.write(rs_st + 0x10, b"\x01")
                    self.mem.write(rs_st + 0x40, b"\x01")
                self.q_kill_tpl = tpl_id
                mname = self.mob_template_name(tpl_id) or "quái nhiệm vụ"
                prog = max(0, q["progress"])
                self.log(f'Nhiệm vụ: tàn sát {mname} ({prog}/{q["need"]})')
            return

    # ---------- Săn Cụm BOSS ----------
    def boss_notices(self):
        fq_st = self.mem.statics("fq")
        if not fq_st:
            return []
        vec = self.mem.ptr(fq_st + 0x8)
        out = []
        for e in self.mem.vec_items(vec):
            out.append({
                "ptr": e,
                "name": self.mem.string(e + 0x10),
                "map": self.mem.string(e + 0x18),
                "mapId": self.mem.num(e + 0x20, "<i"),
            })
        return out

    def go_waypoint(self, side):
        """Đi qua cửa map bên "trái" / "phải" / "giữa" của map hiện tại: dịch vào cửa như XMAP (sa.hrw) rồi xin đổi map (-23).
        Dùng được cả cửa giữa map (cửa giữa không tự đổi map khi chạm vào)."""
        jb, hx_st = self.mem.statics("jb"), self.mem.statics("hx")
        svc = self.mem.ptr(hx_st) if hx_st else 0
        wps = self.mem.vec_items(self.mem.ptr(jb + 0xA0)) if jb else []
        if not (svc and wps):
            return False
        min_x = lambda w: self.mem.num(w + 0x10, "<h")  # noqa: E731
        width = self.mem.num(jb + 0x8, "<i")
        if side == "giữa":  # cửa không nằm sát mép map
            mids = [w for w in wps if self.mem.num(w + 0x14, "<h") >= 60 and min_x(w) <= width - 60]
            if not mids:
                return False
            w = mids[0]
        else:
            w = max(wps, key=min_x) if side == "phải" else min(wps, key=min_x)
        wx, max_x, max_y = min_x(w), self.mem.num(w + 0x14, "<h"), self.mem.num(w + 0x16, "<h")
        x = 15 if max_x < 60 else (wx + 30 if wx <= width - 60 else width - 15)
        self.mem.call_fn(RVA_TELEPORT, x, max_y)
        time.sleep(0.25)  # server nhận vị trí mới (charMove) trước khi xin đổi map
        pop = self.mem.ptr(w + 0x20)
        cmd = self.mem.ptr(pop + 0x40) if pop else 0
        if cmd:
            self.mem.call_fn(RVA_CMD_PERFORM, cmd, 0)
        else:
            self.mem.call_fn(RVA_REQUEST_CHANGE_MAP, svc, 0)
        return True

    def map_id_by_name(self, name):
        """id map theo tên (TileMap.mapNames, jb+0xB8; vị trí trong mảng = id map), -1 nếu không thấy"""
        if not self.map_names:
            jb = self.mem.statics("jb")
            arr = self.mem.ptr(jb + 0xB8) if jb else 0
            n = self.mem.num(arr + 0x18, "<i") if arr else 0
            self.map_names = {norm_str(self.mem.string(arr + 0x20 + 8 * i)): i for i in range(min(max(n, 0), 1000))}
        return self.map_names.get(norm_str(name), -1)

    def all_boss_notices(self):
        """Thông báo boss mới nhất trước: danh sách của MOD (fq, chỉ giữ 6 cái) + dòng "BOSS X vừa xuất hiện tại Y"
        trên kênh thông báo mà MOD bỏ sót (vd Ác Ma Picolo)"""
        out = list(reversed(self.boss_notices()))
        for b in out:
            if b["mapId"] <= 0:  # bảng map của MOD thiếu map mới (vd Đồng Bằng Aru = 170) -> tra bảng tên map của game
                b["mapId"] = self.map_id_by_name(b["map"])
        have = {(norm_str(b["name"]), b["mapId"]) for b in out}
        for ptr, text in self.world_notices():
            hit = BOSS_APPEAR_RE.search(norm_str(text))
            if not hit:
                continue
            name, map_name = hit.group(1).strip(), hit.group(2).strip()
            map_id = self.map_id_by_name(map_name)
            if map_id > 0 and (name, map_id) not in have:
                have.add((name, map_id))
                out.append({"ptr": ptr, "name": name, "map": map_name, "mapId": map_id})
        return out

    def cluster_of(self, name, map_id, cfg):
        n = norm_str(name)
        for c in cfg["clusters"]:
            if not c.get("enabled") or not cluster_allows_map(c, map_id):
                continue
            if any(member_matches(m, n) for m in c["members"]):
                return c
        return None

    def is_member(self, cluster, name):
        n = norm_str(name)
        return any(member_matches(m, n) for m in cluster["members"])

    def report_new_boss_names(self, cfg):
        for b in self.boss_notices():
            n = norm_str(b["name"])
            if not n or n in self.seen_names:
                continue
            self.seen_names.add(n)
            if not any(any(member_matches(m, n) for m in c["members"]) for c in cfg["clusters"]):
                line = f'{b["name"]} - {b["map"]} (map {b["mapId"]})'
                self.log("Boss chưa thuộc cụm nào: " + line)
                try:
                    with open(SEEN_BOSS_PATH, "a", encoding="utf-8") as fh:
                        fh.write(line + "\n")
                except OSError:
                    pass

    def pick_target(self, now, cfg):
        for b in self.all_boss_notices():
            if b["ptr"] in self.done or b["mapId"] <= 0:
                continue
            if now < self.bad_maps.get(b["mapId"], 0):
                continue
            c = self.cluster_of(b["name"], b["mapId"], cfg)
            if not c:
                continue
            self.cluster = c
            self.target_map = b["mapId"]
            self.target_name = b["name"]
            self.notice_ptr = b["ptr"]
            self.zone = -1
            self.xmap_tries = 0
            self.zone_req = -1
            self.last_zone_at = 0.0
            self.next_zone_at = 0.0
            self.retry_zone = -1
            self.same_fails = 0
            self.total_fails = 0
            self.visited = set()
            self.list_zone = -1
            self.zone_info = ""
            self.boss_zone = -1
            self.revives_this_target = 0
            return b
        return None

    def info1_items(self):
        """Đọc danh sách (ptr, text) các thông báo hệ thống trên GameScr.info1 và hộp thoại OK"""
        out = []
        dg_st = self.mem.statics("dg")
        info1 = self.mem.ptr(dg_st + 0x2B0) if dg_st else 0
        info = self.mem.ptr(info1 + 0x18) if info1 else 0
        if info:
            cur_it = self.mem.ptr(info + 0x18)
            if cur_it:
                out.append((cur_it, self.mem.string(cur_it + 0x10)))
            for it in self.mem.vec_items(self.mem.ptr(info + 0x10)):
                if it and it != cur_it:
                    out.append((it, self.mem.string(it + 0x10)))
        dd_st = self.mem.statics("dd")
        if dd_st:
            cur_dlg = self.mem.ptr(dd_st + 0x100)
            msgdlg = self.mem.ptr(dd_st + 0x108)
            if cur_dlg and cur_dlg == msgdlg and self.mem.read(msgdlg + 0x38, 1) == b"\x00":
                arr = self.mem.ptr(msgdlg + 0x30)
                if arr:
                    out.append((arr, " ".join(self.mem.str_array(arr))))
        return out

    def poll_zone_message(self):
        """Kiểm tra thông báo mới từ server sau khi gửi yêu cầu đổi khu: trả về ('cooldown'|'full'|None, sec, text)"""
        for ptr, text in self.info1_items():
            if ptr in self.info1_before:
                continue
            self.info1_before.add(ptr)
            sec = parse_zone_cooldown(text)
            if sec is not None:
                return "cooldown", sec, text
            t = norm_str(text)
            if "đầy" in t and "rương" not in t and "hành trang" not in t:
                return "full", 0.0, text
        return None, 0.0, ""

    def world_notices(self):
        """Đọc các dòng thông báo từ kênh thế giới (info2, vChatVip) và hệ thống (info1)"""
        out = list(self.info1_items())
        dg_st = self.mem.statics("dg")
        if not dg_st:
            return out
        info2 = self.mem.ptr(dg_st + 0x2B8)
        info = self.mem.ptr(info2 + 0x18) if info2 else 0
        if info:
            cur_it = self.mem.ptr(info + 0x18)
            if cur_it:
                out.append((cur_it, self.mem.string(cur_it + 0x10)))
            for it in self.mem.vec_items(self.mem.ptr(info + 0x10)):
                if it and it != cur_it:
                    out.append((it, self.mem.string(it + 0x10)))
        for s_ptr in self.mem.vec_items(self.mem.ptr(dg_st + 0x500)):
            n = self.mem.num(s_ptr + 0x10, "<i")
            if 0 < n < 300:
                txt = self.mem.read(s_ptr + 0x14, n * 2).decode("utf-16-le", "replace")
                out.append((s_ptr, txt))
        return out

    def poll_boss_deaths(self):
        """Theo dõi thông báo boss bị tiêu diệt trên kênh thế giới để tự động bỏ qua ngay"""
        for ptr, text in self.world_notices():
            if ptr in self.seen_chat_ptrs:
                continue
            self.seen_chat_ptrs.add(ptr)
            t = norm_str(text)
            if not t or t.startswith("|") or "xuất hiện" in t:
                continue
            if not any(w in t for w in ("tiêu diệt", "hạ gục", "đã hạ")):
                continue
            for b in self.boss_notices():
                bname = norm_str(b["name"])
                if bname and re.search(r"(?<!\w)" + re.escape(bname) + r"(?!\w)", t):
                    self.done.add(b["ptr"])
            if self.state in ("TRAVEL", "ARRIVE", "SCAN") and self.target_name:
                tname = norm_str(self.target_name)
                if tname and re.search(r"(?<!\w)" + re.escape(tname) + r"(?!\w)", t):
                    self.finish_target(f'boss "{self.target_name}" đã bị tiêu diệt ({text.strip()}) -> bỏ qua')
                    return True
        return False

    def chars_in_map(self):
        dg_st = self.mem.statics("dg")
        return self.mem.vec_items(self.mem.ptr(dg_st + 0xF0)) if dg_st else []

    def char_info(self, c):
        return {
            "name": self.mem.string(c + 0x190),
            "id": self.mem.num(c + 0x90, "<i"),
            "hp": self.mem.num(c + 0xD0, "<q"),
            "hpFull": self.mem.num(c + 0x108, "<q"),
            "x": self.mem.num(c + 0x6C, "<i"),
            "y": self.mem.num(c + 0x70, "<i"),
            "pk": self.mem.num(c + 0x295, "<b"),
        }

    def alive_bosses_here(self):
        if not self.cluster:
            return []
        out = []
        for c in self.chars_in_map():
            info = self.char_info(c)
            if info["id"] >= 0 or info["hp"] <= 0:
                continue
            n = norm_str(info["name"])
            info["minion"] = any(member_matches(mm, n) for mm in cluster_minions(self.cluster))
            if info["minion"] or self.is_member(self.cluster, info["name"]):
                out.append((c, info))
        return out

    @staticmethod
    def fight_order(bosses):
        """Thứ tự đánh: boss con (minions) trước, rồi boss đang đánh mình (pk 5)"""
        return sorted(bosses, key=lambda x: (not x[1].get("minion"), not x[1]["pk"] == 5))

    def zone_list(self):
        dg_st = self.mem.statics("dg")
        g = self.mem.ptr(dg_st + 0x18) if dg_st else 0
        if not g:
            return []
        ids = self.mem.int_array(self.mem.ptr(g + 0x70))
        num = self.mem.int_array(self.mem.ptr(g + 0x80))
        mx = self.mem.int_array(self.mem.ptr(g + 0x88))
        return [{"id": z_id, "num": num[i] if i < len(num) else 0, "max": mx[i] if i < len(mx) else 0}
                for i, z_id in enumerate(ids)]

    def next_zone(self, cfg):
        zones = self.zone_list()
        if not zones:
            zones = [{"id": i, "num": 0, "max": 0} for i in range(cfg["maxZone"])]
        # khu đông người trước; khu đầy (boss hay ở khu đông nhất nên dễ đầy) để cuối cùng thay vì bỏ hẳn -
        # server báo "đầy" thì poll_zone_message đánh dấu đã dò
        cand = [z for z in zones if z["id"] not in self.visited]
        cand.sort(key=lambda z: (z["max"] > 0 and z["num"] >= z["max"], -z["num"], z["id"]))
        self.zone_info = f'{cand[0]["num"]} người, còn {len(cand)} khu' if cand else ""
        return cand[0]["id"] if cand else -1

    def escape_zone(self, avoid, cfg):
        zones = self.zone_list()
        if not zones:
            zones = [{"id": i, "num": 0, "max": 0} for i in range(cfg["maxZone"])]
        cand = [z for z in zones if z["id"] != avoid and not (z["max"] > 0 and z["num"] >= z["max"])]
        cand.sort(key=lambda z: (z["num"], z["id"]))
        return cand[0]["id"] if cand else (avoid + 1) % cfg["maxZone"]

    def request_zone(self, z, now):
        hx_st = self.mem.statics("hx")
        svc = self.mem.ptr(hx_st) if hx_st else 0
        if not svc:
            return False
        dg_st = self.mem.statics("dg")
        info1 = self.mem.ptr(dg_st + 0x2B0) if dg_st else 0
        info = self.mem.ptr(info1 + 0x18) if info1 else 0
        if info:
            cur_it = self.mem.ptr(info + 0x18)
            if cur_it and parse_zone_cooldown(self.mem.string(cur_it + 0x10)) is not None:
                self.mem.write(info + 0x18, struct.pack("<Q", 0))
        self.info1_before = {ptr for ptr, _ in self.info1_items()}
        self.show_game_scr()
        self.mem.call_fn(RVA_CHANGE_ZONE, svc, z)
        self.last_zone_at = now
        return True

    def other_players_here(self):
        """Số người chơi khác trong khu (boss / đệ tử có id âm nên không tính)"""
        return sum(1 for c in self.chars_in_map() if self.mem.num(c + 0x90, "<i") >= 0)

    def empty_zone_tick(self, cur_zone, now):
        """Khu trống: có người khác ở khu >= 5s thì mở danh sách khu, sang khu ít người nhất (ưu tiên 0 người).
        Trả về True khi đang bận đổi khu (bỏ qua phần còn lại của tick)."""
        if self.ez_phase == "WATCH":
            if now < self.ez_check_at:
                return False
            self.ez_check_at = now + 2000.0
            others = self.other_players_here()
            if not others:
                self.ez_seen_at = 0.0
                return False
            if not self.ez_seen_at:
                self.ez_seen_at = now
            if now - self.ez_seen_at < 5000 or now < self.ez_next_at:  # người đi ngang qua / đang chờ hồi đổi khu
                return False
            dg_st = self.mem.statics("dg")
            gs = self.mem.ptr(dg_st + 0x18) if dg_st else 0
            hx_st = self.mem.statics("hx")
            svc = self.mem.ptr(hx_st) if hx_st else 0
            if not (gs and svc):
                return False
            self.ez_arr = self.mem.ptr(gs + 0x80)
            self.mem.call_fn(RVA_OPEN_ZONE_UI, svc, 0)
            self.ez_phase, self.ez_t = "LIST", now
            self.log(f"Khu {cur_zone} có {others} người khác -> tìm khu trống")
            return True
        if self.ez_phase == "LIST":
            dg_st = self.mem.statics("dg")
            gs = self.mem.ptr(dg_st + 0x18) if dg_st else 0
            if gs and self.mem.ptr(gs + 0x80) == self.ez_arr and now - self.ez_t < 3000:
                return True  # chờ server gửi danh sách khu
            zones = [z for z in self.zone_list() if z["id"] != cur_zone and not (z["max"] > 0 and z["num"] >= z["max"])]
            self.show_game_scr()  # đóng bảng chọn khu
            others = self.other_players_here()
            best = min(zones, key=lambda z: (z["num"], z["id"])) if zones else None
            if not best or best["num"] >= max(others, 1):  # không có khu vắng hơn khu hiện tại
                self.log("Không có khu nào vắng hơn, ở lại khu này 60s rồi xem lại")
                self.ez_phase, self.ez_next_at, self.ez_seen_at = "WATCH", now + 60000.0, 0.0
                return False
            self.request_zone(best["id"], now)
            self.ez_phase, self.ez_req, self.ez_t = "MOVE", best["id"], now
            self.log(f'Sang khu {best["id"]} ({best["num"]} người)')
            return True
        # MOVE: chờ vào khu mới / đọc thông báo hồi đổi khu
        if cur_zone == self.ez_req:
            self.ez_phase, self.ez_seen_at, self.ez_check_at = "WATCH", 0.0, now + 3000.0  # chờ tải người trong khu
            return False
        kind, sec, _text = self.poll_zone_message()
        if kind == "cooldown":
            self.ez_next_at = now + sec * 1000.0 + 400.0
            self.log(f"Còn {sec:g}s hồi đổi khu, chờ rồi tìm lại")
        elif kind != "full" and now - self.ez_t < 6000:
            return True
        self.ez_phase, self.ez_seen_at = "WATCH", 0.0
        return False

    def finish_target(self, reason):
        self.release_target()
        if self.notice_ptr:
            self.done.add(self.notice_ptr)
        if self.cluster:
            for b in self.boss_notices():
                if b["mapId"] == self.target_map and self.is_member(self.cluster, b["name"]):
                    self.done.add(b["ptr"])
        self.log(f'Xong {self.cluster["name"] if self.cluster else ""}: {reason}')
        self.cluster = None
        self.target_map = -1
        self.target_name = ""
        self.notice_ptr = 0
        self.set_state("IDLE")

    def attack(self, me, c, info, now, cfg):
        self.mem.write(me + 0x2A8, struct.pack("<Q", 0))
        self.mem.write(me + 0x2C8, struct.pack("<Q", c))
        fg_st = self.mem.statics("fg")
        if fg_st:
            self.mem.write(fg_st + 0x0, b"\x01")
        if cfg.get("teleport", True) and now - self.last_move > 400:
            mx = self.mem.num(me + 0x6C, "<i")
            my = self.mem.num(me + 0x70, "<i")
            if abs(mx - info["x"]) > 40 or abs(my - info["y"]) > 40:
                self.mem.write(me + 0x6C, struct.pack("<i", info["x"]))
                self.mem.write(me + 0x70, struct.pack("<i", info["y"]))
                hx_st = self.mem.statics("hx")
                svc = self.mem.ptr(hx_st) if hx_st else 0
                if svc:
                    self.mem.call_fn(RVA_CHAR_MOVE, svc, 0)
                self.last_move = now

    def my_skills(self, me):
        if_kl = self.mem.klass("if")
        for off in (0x218, 0x220, 0x228):
            items = self.mem.vec_items(self.mem.ptr(me + off))
            if items and self.mem.ptr(items[0]) == if_kl:
                return items
        return []

    def is_attack_skill(self, sk):
        if not sk:
            return False
        t = self.mem.ptr(sk + 0x10)
        if not t:
            return False
        tid = self.mem.num(t + 0x10, "<b")
        return self.mem.num(t + 0x28, "<i") == 1 and tid not in (10, 11)

    def use_buff_skill(self, me, now, cfg):
        if not cfg.get("useBuffSkills", True) or now - self.last_buff_try < 1000:
            return
        self.last_buff_try = now
        dg_st = self.mem.statics("dg")
        gs = self.mem.ptr(dg_st + 0x18) if dg_st else 0
        if not gs or self.mem.ptr(me + 0x4D8) or self.mem.read(me + 0x4E0, 1) != b"\x00":
            return
        if any(self.mem.read(me + off, 1) != b"\x00" for off in (0x5F9, 0x5FB, 0x5FC)):
            return
        sks = self.mem.ptr(dg_st + 0xA0)
        if not sks:
            return
        sks_len = self.mem.num(sks + 0x18, "<i")
        ki = self.mem.num(me + 0xC8, "<q")
        buff_list = cfg.get("buffSkills", DEFAULT_BOSS_CFG["buffSkills"])

        cur = self.mem.ptr(me + 0x230)
        if self.is_attack_skill(cur):
            self.attack_skill = cur
        atk = self.attack_skill if self.is_attack_skill(self.attack_skill) else next((s for s in self.my_skills(me) if self.is_attack_skill(s)), 0)

        for sk in self.my_skills(me):
            tpl = self.mem.ptr(sk + 0x10)
            if not tpl or self.mem.num(tpl + 0x28, "<i") != 3:
                continue
            tid = self.mem.num(tpl + 0x10, "<b")
            name = self.mem.string(tpl + 0x18)
            # danh sách ghi được id (13) hoặc tên ("khiên năng lượng")
            if not any(b == tid if isinstance(b, int) else norm_str(b) in norm_str(name) for b in buff_list):
                continue
            last_use = self.mem.num(sk + 0x30, "<q")
            cooldown = self.mem.num(sk + 0x28, "<i")
            # lần dùng cuối là giờ thật của game (ms từ 1970), không so với now (monotonic) được
            if time.time() * 1000.0 - last_use < cooldown + 300:
                continue
            mana = self.mem.num(sk + 0x44, "<i")
            need = self.mem.num(me + 0x110, "<q") * mana / 100 if self.mem.num(tpl + 0x24, "<i") == 1 else mana
            if ki < need:
                continue
            if tid == 13 and self.mem.num(me + 0x5DA, "<b") != 0:
                continue
            if self.mem.num(sk + 0x18, "<h") >= sks_len:
                continue
            self.mem.write(me + 0x230, struct.pack("<Q", sk))
            self.mem.call_fn(RVA_USE_SKILL_NOT_FOCUS, gs, sk)
            if atk:
                self.mem.write(me + 0x230, struct.pack("<Q", atk))
                self.mem.write(gs + 0x1A0, struct.pack("<Q", atk))
                hx_st = self.mem.statics("hx")
                svc = self.mem.ptr(hx_st) if hx_st else 0
                if svc:
                    atk_tid = self.mem.num(self.mem.ptr(atk + 0x10) + 0x10, "<b")
                    self.mem.call_fn(RVA_SELECT_SKILL_SRV, svc, atk_tid)
            self.log(f"Dùng skill hỗ trợ: {name}")
            return

    def handle_death(self, now, cfg):
        if not self.dead:
            self.dead = True
            self.dead_since = now
            self.revive_attempts = 0
            self.last_revive_at = 0.0
            self.went_home = False
            self.release_target()
            self.log("Nhân vật đã chết" if cfg.get("autoRevive", True) else "Nhân vật đã chết, chờ hồi sinh")
        if not cfg.get("autoRevive", True) or self.went_home:
            return
        if now - self.dead_since < cfg.get("reviveDelayMs", 3000) or now - self.last_revive_at < cfg.get("reviveRetryMs", 6000):
            return
        hx_st = self.mem.statics("hx")
        svc = self.mem.ptr(hx_st) if hx_st else 0
        if not svc:
            return
        max_rev = cfg.get("reviveMaxPerTarget", 0)
        too_many = self.cluster and max_rev > 0 and self.revives_this_target >= max_rev
        if not self.cluster or too_many or self.revive_attempts >= cfg.get("reviveAttemptsPerDeath", 3):
            self.went_home = True
            self.last_revive_at = now
            self.mem.call_fn(RVA_RETURN_HOME, svc, 0)
            self.log("Về nhà sau khi chết")
            if too_many:
                self.finish_target("chết quá số lần tối đa")
            return
        self.revive_attempts += 1
        self.last_revive_at = now
        self.mem.call_fn(RVA_REVIVE_HERE, svc, 0)
        self.log(f"Hồi sinh tại chỗ (lần thử {self.revive_attempts})")

    def handle_revived(self, cur_map):
        self.dead = False
        in_place = self.revive_attempts > 0 and not self.went_home
        if in_place:
            self.revives_this_target += 1
        self.log(f"Đã hồi sinh tại chỗ (lần {self.revives_this_target})" if in_place else "Đã sống lại, tiếp tục")
        if self.state == "IDLE":
            return
        if cur_map == self.target_map:
            self.set_state("RETURN" if self.boss_zone >= 0 else "SCAN")
        else:
            self.set_state("TRAVEL")
            self.xmap_at = 0.0
            self.xmap_tries = 0

    def tick(self):
        if not self.enabled and not self.quest_mode and not self.sword_active and not self.egg_active and not self.egg_single_action and not self.empty_zone:
            return
        cfg = self.get_cfg()
        now = time.monotonic() * 1000.0
        bh, jb = self.mem.statics("bh"), self.mem.statics("jb")
        me = self.mem.ptr(bh + 0xA8) if bh else 0
        if not me or not jb:
            return

        cur_map = self.mem.num(jb + 0x7C, "<i")
        cur_map_name = self.mem.string(jb + 0x70)
        cur_zone = self.mem.num(jb + 0x84, "<i")

        if self.egg_active or self.egg_single_action:
            if self.egg_tick(me, cur_map, cur_zone, now):
                return

        if self.sword_active:
            if self.sword_tick(me, cur_map, cur_zone, now):
                return
        # Khu trống: chỉ khi không bận săn boss / làm nhiệm vụ (đang săn thì bộ săn tự lo đổi khu) và còn sống
        if self.empty_zone and self.state == "IDLE" and not self.quest_mode and self.mem.num(me + 0xD0, "<q") > 0:
            if self.empty_zone_tick(cur_zone, now):
                return
        if not self.enabled and not self.quest_mode:
            return

        fq_st = self.mem.statics("fq")
        if fq_st:
            self.mem.write(fq_st + 0x5, b"\x01")
        quest_boss = self.quest_mode and self.q_action == "BOSS"
        if self.enabled or quest_boss:
            self.quiet_mod()

        hp = self.mem.num(me + 0xD0, "<q")
        hp_full = self.mem.num(me + 0x108, "<q")
        my_pct = (hp * 100.0 / hp_full) if hp_full > 0 else 100.0
        is_dead = hp <= 0 or self.mem.read(me + 0x5DE, 1) != b"\x00" or self.mem.num(me + 0x88, "<i") == 14
        if is_dead:
            self.handle_death(now, cfg)
            return
        if self.dead:
            self.handle_revived(cur_map)

        if self.poll_boss_deaths():
            return

        if self.quest_mode and self.state == "IDLE":
            self.quest_tick(me, cur_map, cur_zone, now)

        if self.state == "IDLE":
            if self.quest_mode:
                return
            self.report_new_boss_names(cfg)
            b = self.pick_target(now, cfg)
            if b:
                self.show_game_scr()
                self.set_state("TRAVEL", f'Săn cụm {self.cluster["name"]}: {b["name"]} tại {b["map"]} (map {b["mapId"]})')
                self.xmap_at = 0.0

        elif self.state == "TRAVEL":
            if cur_map == self.target_map:
                self.set_state("ARRIVE", f"Đã tới {cur_map_name}")
                return
            # map XMAP không biết (map mới): XMAP tới map kề rồi tự đi qua cửa map, xem EXTRA_ROUTES
            route = EXTRA_ROUTES.get(self.target_map)
            if route and cur_map == route[0]:
                if now - self.hop_at > 5000:
                    self.hop_at = now
                    self.show_game_scr()
                    if self.go_waypoint(route[1]):
                        self.log(f"Đi qua cửa {route[1]} của {cur_map_name} sang map {self.target_map}")
                return
            xmap_to = route[0] if route else self.target_map
            rv_st = self.mem.statics("rv", init=True)
            xmap_running = bool(self.mem.read(rv_st, 1)[0]) if rv_st else False
            stalled = self.xmap_at != 0.0 and not xmap_running and now - self.xmap_at > 8000
            if self.xmap_at == 0.0 or stalled or now - self.xmap_at > cfg.get("xmapRetryMs", 90000):
                if self.xmap_tries >= 2:
                    self.bad_maps[self.target_map] = now + cfg.get("badMapMs", 600000)
                    self.show_game_scr()
                    self.finish_target(f"XMAP không tới được map {xmap_to}, bỏ qua 10 phút")
                    return
                self.xmap_tries += 1
                self.xmap_at = now
                self.show_game_scr()
                self.mem.call_fn(RVA_XMAP_START, xmap_to, 0)
                self.log(f"XMAP tới map {xmap_to} (lần {self.xmap_tries})")

        elif self.state == "ARRIVE":
            if now - self.t > cfg.get("arriveDelayMs", 2500):
                self.set_state("RETURN" if self.boss_zone >= 0 else "SCAN")

        elif self.state == "SCAN":
            if cur_map != self.target_map:
                self.set_state("TRAVEL")
                self.xmap_at = 0.0
                return
            if self.zone_req >= 0:
                if cur_zone == self.zone_req:
                    self.zone_req = -1
                    self.next_zone_at = 0.0
                    self.same_fails = 0
                    self.total_fails = 0
                    self.t = now
                    return
                kind, sec, text = self.poll_zone_message()
                if kind == "cooldown":
                    self.next_zone_at = now + sec * 1000.0 + 400.0
                    self.retry_zone = self.zone_req
                    self.zone_req = -1
                    self.same_fails = 0
                    self.total_fails = 0
                    self.log(f"Còn {sec:g}s hồi đổi khu ({text}) -> chờ {sec:g}s vào khu {self.retry_zone}")
                    return
                if kind == "full":
                    self.log(f"Khu {self.zone_req} đã đầy ({text}), chuyển khu tiếp")
                    self.visited.add(self.zone_req)
                    self.retry_zone = -1
                    self.zone_req = -1
                    self.same_fails = 0
                    return
                if now - self.last_zone_at < 2500:
                    return
                self.same_fails += 1
                self.total_fails += 1
                self.t = now
                if self.same_fails >= 6:
                    self.log(f"Không vào được khu {self.zone_req}, bỏ qua khu này")
                    self.visited.add(self.zone_req)
                    self.same_fails = 0
                    self.retry_zone = -1
                else:
                    self.retry_zone = self.zone_req
                    self.next_zone_at = now + 2000.0
                self.zone_req = -1
                if self.total_fails >= 15:
                    self.finish_target("không đổi được khu")
                return

            if now - self.t < cfg.get("zoneLoadMs", 2500):
                return
            if cur_zone not in self.visited:
                self.visited.add(cur_zone)
            bosses = self.alive_bosses_here()
            if bosses:
                self.boss_zone = cur_zone
                self.target_name = bosses[0][1]["name"]
                self.set_state("FIGHT", f"Thấy boss {self.target_name} ở khu {cur_zone}")
                self.last_seen = now
                return

            dg_st = self.mem.statics("dg")
            gs = self.mem.ptr(dg_st + 0x18) if dg_st else 0
            cur_zone_arr = self.mem.ptr(gs + 0x80) if gs else 0
            if self.list_zone != cur_zone:
                self.list_zone = cur_zone
                self.list_at = now
                self.list_arr = cur_zone_arr
                hx_st = self.mem.statics("hx")
                svc = self.mem.ptr(hx_st) if hx_st else 0
                if svc:
                    self.mem.call_fn(RVA_OPEN_ZONE_UI, svc, 0)
                return
            if cur_zone_arr == self.list_arr and now - self.list_at < 3000:
                return
            if now < self.next_zone_at:
                return
            nxt = self.retry_zone if self.retry_zone >= 0 else self.next_zone(cfg)
            self.retry_zone = -1
            if nxt < 0:
                self.finish_target("đã dò hết khu, không thấy boss")
                return
            if self.request_zone(nxt, now):
                self.zone_req = nxt
                self.zone = nxt
                self.log(f"Dò khu {nxt}" + (f" ({self.zone_info})" if self.zone_info else ""))

        elif self.state == "FIGHT":
            if cur_map != self.target_map:
                self.set_state("TRAVEL")
                self.xmap_at = 0.0
                return
            bosses = self.alive_bosses_here()
            if not bosses:
                if now - self.last_seen > cfg.get("waitNextMs", 10000):
                    self.release_target()
                    self.loot_empty = 0
                    self.last_loot_poll = 0.0
                    self.set_state("LOOT", "Hết boss trong khu, đang nhặt đồ")
                return
            self.last_seen = now
            flee_pct = cfg.get("fleeHpPct", 0)
            if flee_pct > 0 and my_pct < flee_pct:
                self.boss_zone = cur_zone
                self.release_target()
                self.set_state("FLEE", f"HP còn {my_pct:.0f}%, đổi khu chạy trốn")
                return
            c, info = self.fight_order(bosses)[0]
            self.target_name = info["name"]
            if now - self.last_fight_log > 4000:
                self.last_fight_log = now
                b_pct = (info["hp"] * 100.0 / info["hpFull"]) if info["hpFull"] > 0 else 100.0
                self.log(f'Đánh {info["name"]}: HP {info["hp"]/1e6:.2f}M ({b_pct:.1f}%) | mình {my_pct:.0f}%')
            self.attack(me, c, info, now, cfg)
            self.use_buff_skill(me, now, cfg)

        elif self.state == "LOOT":
            if now - self.t < 1500 or now - self.last_loot_poll < 250:
                return
            self.last_loot_poll = now
            ru_st = self.mem.statics("ru", init=True)
            pick_list = self.mem.ptr(ru_st + 0x30) if ru_st else 0
            pick_count = self.mem.num(pick_list + 0x18, "<i") if pick_list else 0
            self.loot_empty = (self.loot_empty + 1) if pick_count == 0 else 0
            if self.loot_empty >= 3 or now - self.t > cfg.get("lootMaxMs", 12000):
                self.finish_target("đã hạ hết boss và nhặt đồ")

        elif self.state == "FLEE":
            if cur_map != self.target_map:
                self.set_state("TRAVEL")
                self.xmap_at = 0.0
                return
            if cur_zone == self.boss_zone:
                kind, sec, text = self.poll_zone_message()
                if kind == "cooldown":
                    self.next_zone_at = now + sec * 1000.0 + 400.0
                    return
                if now >= self.next_zone_at and now - self.last_zone_at >= 2000:
                    if self.request_zone(self.escape_zone(self.boss_zone, cfg), now):
                        self.log("Đổi khu để chạy trốn")
                return
            self.next_zone_at = 0.0
            if my_pct >= cfg.get("resumeHpPct", 90):
                self.set_state("RETURN", f"HP hồi {my_pct:.0f}%, quay lại khu {self.boss_zone}")

        elif self.state == "RETURN":
            if cur_map != self.target_map:
                self.set_state("TRAVEL")
                self.xmap_at = 0.0
                return
            if cur_zone != self.boss_zone:
                kind, sec, text = self.poll_zone_message()
                if kind == "cooldown":
                    self.next_zone_at = now + sec * 1000.0 + 400.0
                    self.log(f"Chờ {sec:g}s hồi đổi khu để quay lại khu {self.boss_zone}")
                    return
                if now >= self.next_zone_at and now - self.last_zone_at >= 2000:
                    self.request_zone(self.boss_zone, now)
                self.t = now
                return
            self.next_zone_at = 0.0
            if now - self.t < cfg.get("zoneLoadMs", 2500):
                return
            if self.alive_bosses_here():
                self.set_state("FIGHT", "Quay lại đánh tiếp")
                self.last_seen = now
            elif now - self.t > cfg.get("zoneLoadMs", 2500) + cfg.get("waitNextMs", 10000):
                self.finish_target("boss đã bị hạ")


class Game:
    """Một tiến trình game đang theo dõi"""

    def __init__(self, pid, mem, exe, filter_junk, boss_hunter, auto_item=False, pending_login=None):
        self.pid, self.mem, self.exe = pid, mem, exe
        self.hwnd = None
        self.hidden = False
        self.saved_win = None
        self.hidden_fps = 0
        self.filter_junk = filter_junk
        self.auto_item = auto_item
        self.auto_item_init = False
        self.pending_login = pending_login
        self.account = (pending_login["user"], pending_login.get("pass", "")) if pending_login and pending_login.get("user") else None
        self.account_trusted = bool(self.account)  # tài khoản do bảng đăng nhập / nhận theo tên nhân vật, không đoán từ Rms chung
        self.last_char_name = ""
        self.reconnect = True  # Tự kết nối lại khi mất kết nối (bảng tự đăng nhập đúng tài khoản của tab này)
        self.reconnect_wait = 5.0
        self.last_reconnect_try = 0.0
        self.cooldown_seen = 0  # thông báo "đăng nhập lại sau N giây" đã xử lý (mỗi thông báo chỉ tính 1 lần)
        self.boss = boss_hunter
        self.status = {}
        self.cpu_prev = None
        self.cpu_pct = 0.0
        self.ram_mb = 0.0
        self.closing = False


class PanelApp:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.boss_cfg = load_boss_config()
        self.games = {}  # pid -> Game
        self.pending_launches = {}  # pid -> dict cấu hình đăng nhập ngầm cho game vừa mở
        self.lock = threading.Lock()
        self.events = queue.Queue()
        self.sys_prev = system_times()
        self.last_relaunch = 0.0
        self.stop = False
        self.patched_dlls = set()
        self.ensure_dll_patched(self.cfg.get("exePath"))

        root.title("Bảng điều khiển treo game, Đăng Nhập Ngầm, Auto Item, Kiếm Z, Nhiệm Vụ & Săn BOSS - NgocRongViet")
        root.geometry("1360x890")
        top = ttk.Frame(root, padding=(6, 4))
        top.pack(fill="x")
        self.lbl_machine = ttk.Label(top, text="Máy: ...", font=("Segoe UI", 10, "bold"))
        self.lbl_machine.pack(side="left")
        ttk.Button(top, text="Mở thêm game (trống)", command=self.launch_game).pack(side="right")
        ttk.Button(top, text="Chọn file game...", command=self.pick_exe).pack(side="right", padx=4)

        # ---------- Khu vực Đăng nhập tự động & Mở game chạy ngầm ----------
        login_bar = ttk.LabelFrame(
            root,
            text="Đăng nhập tự động & Mở game chạy ngầm trên VPS (không cần bật cửa sổ game)",
            padding=(6, 4),
        )
        login_bar.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(login_bar, text="Tài khoản:").pack(side="left")
        self.var_user = tk.StringVar(value=self.cfg.get("lastUser", ""))
        acc_list = list((self.cfg.get("accounts") or {}).keys())
        self.cmb_user = ttk.Combobox(login_bar, textvariable=self.var_user, values=acc_list, width=16)
        self.cmb_user.pack(side="left", padx=(2, 8))
        self.cmb_user.bind("<<ComboboxSelected>>", self.on_select_account)

        ttk.Label(login_bar, text="Mật khẩu:").pack(side="left")
        self.var_pass = tk.StringVar(value=self.cfg.get("lastPass", ""))
        self.ent_pass = ttk.Entry(login_bar, textvariable=self.var_pass, width=15, show="*")
        self.ent_pass.pack(side="left", padx=(2, 4))
        self.var_show_pass = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            login_bar,
            text="Hiện MK",
            variable=self.var_show_pass,
            command=lambda: self.ent_pass.config(show="" if self.var_show_pass.get() else "*"),
        ).pack(side="left", padx=(0, 8))

        self.var_login_hide = tk.BooleanVar(value=self.cfg.get("loginHideBg", True))
        ttk.Checkbutton(
            login_bar,
            text="Chạy ngầm (tự ẩn cửa sổ + bật Tự ĐN)",
            variable=self.var_login_hide,
            command=self.save_opts,
        ).pack(side="left", padx=(0, 8))

        self.var_login_auto_item = tk.BooleanVar(value=self.cfg.get("loginAutoItem", False))
        ttk.Checkbutton(
            login_bar,
            text="Bật kèm Tự dùng Item",
            variable=self.var_login_auto_item,
            command=self.save_opts,
        ).pack(side="left", padx=(0, 8))

        ttk.Button(login_bar, text="Vào game (Chạy ngầm)", command=self.launch_and_login_bg).pack(side="left", padx=2)
        ttk.Button(login_bar, text="Đăng nhập dòng chọn", command=self.login_selected).pack(side="left", padx=2)

        cols = ("pid", "name", "map", "hp", "mp", "cpu", "ram", "picked", "bag", "dropped", "quest", "boss", "flags", "view")
        heads = ("PID", "Nhân vật", "Map - khu", "HP", "MP", "CPU", "RAM", "Đã nhặt", "Túi (SKH)", "Đã lọc", "Nhiệm vụ chính tuyến", "Săn Boss / NV", "Đang bật", "Hiển thị")
        widths = (48, 95, 130, 102, 102, 44, 54, 52, 76, 46, 170, 108, 195, 52)
        self.tree = ttk.Treeview(root, columns=cols, show="headings", selectmode="extended", height=6)
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w" if c in ("name", "map", "quest", "boss", "flags") else "center")
        self.tree.pack(fill="x", padx=6)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        bar = ttk.Frame(root, padding=(6, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="Dòng đang chọn:").pack(side="left")
        ttk.Button(bar, text="Ẩn", command=lambda: self.set_hidden(self.selected(), True)).pack(side="left", padx=2)
        ttk.Button(bar, text="Hiện", command=lambda: self.set_hidden(self.selected(), False)).pack(side="left", padx=2)
        for key, label in FLAG_NAMES:
            ttk.Button(bar, text=label, command=lambda k=key: self.toggle_flag(k)).pack(side="left", padx=2)
        ttk.Button(bar, text="Tự dùng Item (Bật/Tắt)", command=self.toggle_auto_item_selected).pack(side="left", padx=2)
        ttk.Button(bar, text="Auto Ấp Trứng (Bật/Tắt)", command=self.toggle_egg_auto_selected).pack(side="left", padx=2)
        ttk.Button(bar, text="Lọc đồ rác", command=self.toggle_filter_junk).pack(side="left", padx=2)
        ttk.Button(bar, text="Khu trống (Bật/Tắt)", command=self.toggle_empty_zone_selected).pack(side="left", padx=2)
        ttk.Button(bar, text="Kết nối lại (Bật/Tắt)", command=self.toggle_reconnect_selected).pack(side="left", padx=2)
        ttk.Button(bar, text="Tự làm NV (Bật/Tắt)", command=self.toggle_quest_selected).pack(side="left", padx=(6, 2))
        ttk.Button(bar, text="Săn Boss (Bật/Tắt)", command=self.toggle_boss_selected).pack(side="left", padx=2)
        ttk.Button(bar, text="Bỏ qua boss này", command=self.skip_boss_selected).pack(side="left", padx=2)
        ttk.Button(bar, text="Tắt game", command=self.kill_selected).pack(side="left", padx=(8, 2))

        bar2 = ttk.Frame(root, padding=(6, 0, 6, 4))
        bar2.pack(fill="x")
        ttk.Button(bar2, text="Ẩn tất cả", command=lambda: self.set_hidden(list(self.games), True)).pack(side="left", padx=2)
        ttk.Button(bar2, text="Hiện tất cả", command=lambda: self.set_hidden(list(self.games), False)).pack(side="left", padx=2)
        ttk.Label(bar2, text="   FPS khi ẩn:").pack(side="left")
        self.var_fps = tk.IntVar(value=self.cfg["hiddenFps"])
        ttk.Spinbox(bar2, from_=3, to=60, width=4, textvariable=self.var_fps, command=self.save_opts).pack(side="left")
        ttk.Label(bar2, text="(5 = nhẹ nhất mà vẫn đánh đủ nhanh)").pack(side="left", padx=4)
        self.var_watch = tk.BooleanVar(value=self.cfg["watchdog"])
        ttk.Checkbutton(bar2, text="Tự mở lại game bị thoát", variable=self.var_watch, command=self.save_opts).pack(side="right")
        self.var_filter = tk.BooleanVar(value=self.cfg.get("filterJunk", True))
        ttk.Checkbutton(bar2, text="Tự lọc đồ rác (giữ SKH)", variable=self.var_filter, command=self.on_toggle_all_filter).pack(side="right", padx=10)

        # ---------- Khu vực cấu hình Tự động dùng Item bổ trợ ----------
        item_frame = ttk.LabelFrame(
            root,
            text="Vật phẩm Tự động dùng khi hết hiệu ứng (tích chọn item rồi bấm 'Tự dùng Item (Bật/Tắt)' cho nhân vật)",
            padding=(6, 3),
        )
        item_frame.pack(fill="x", padx=6, pady=(0, 4))
        item_grid = ttk.Frame(item_frame)
        item_grid.pack(fill="x")
        self.auto_item_vars = {}
        saved_items = self.cfg.get("autoItems") or {}
        for idx, (k, label, _ids, _names, def_val) in enumerate(AUTO_ITEM_DEFS):
            var = tk.BooleanVar(value=saved_items.get(k, def_val))
            ttk.Checkbutton(item_grid, text=label, variable=var, command=self.save_opts).grid(
                row=idx // 8, column=idx % 8, sticky="w", padx=(0, 10), pady=1
            )
            self.auto_item_vars[k] = var
        custom_box = ttk.Frame(item_frame)
        custom_box.pack(fill="x", pady=(2, 0))
        ttk.Label(custom_box, text="Item khác (nhập tên hoặc ID, cách nhau dấu phẩy):").pack(side="left")
        self.var_custom_items = tk.StringVar(value=self.cfg.get("customAutoItems", ""))
        ent_custom = ttk.Entry(custom_box, textvariable=self.var_custom_items, width=36)
        ent_custom.pack(side="left", padx=4)
        ent_custom.bind("<FocusOut>", lambda _e: self.save_opts())
        ent_custom.bind("<Return>", lambda _e: self.save_opts())
        ttk.Button(custom_box, text="Áp dụng", command=self.save_opts).pack(side="left", padx=2)

        # ---------- Khu vực tự đổi + nâng cấp Kiếm Z ----------
        sword_frame = ttk.LabelFrame(
            root,
            text="Kiếm Z (đổi Vĩnh viễn ở Tổ Sư Kaio tới khi đầy hành trang -> nâng cấp ở NPC Mai, Hành tinh ngục tù 2)",
            padding=(6, 4),
        )
        sword_frame.pack(fill="x", padx=6, pady=(0, 4))
        self.sword_vars = {}
        for key, label, default, hi in (("swordMinNew", "Kiếm mới: giữ khi sức đánh >= (%)", 5, 50),
                                        ("swordMaxLevel", "Nâng tới cấp +", 6, 16),
                                        ("swordMinFinal", "Đủ cấp: giữ khi sức đánh > (%)", 30, 200)):
            ttk.Label(sword_frame, text=label).pack(side="left")
            self.sword_vars[key] = tk.IntVar(value=self.cfg.get(key, default))
            ttk.Spinbox(sword_frame, from_=1, to=hi, width=4, textvariable=self.sword_vars[key], command=self.save_opts).pack(
                side="left", padx=(2, 8)
            )
        ttk.Button(sword_frame, text="Tự đổi Kiếm Z (Bật/Tắt)", command=self.toggle_sword_selected).pack(side="left", padx=3)
        self.lbl_sword_status = ttk.Label(sword_frame, text="Đang dừng", foreground="#1a73e8", font=("Segoe UI", 9, "bold"))
        self.lbl_sword_status.pack(side="left", padx=(10, 0))

        # ---------- Khu vực Auto Ấp Trứng Nhanh & Mua Đá Linh Lực (Mốc 1 Ngày) ----------
        egg_frame = ttk.LabelFrame(
            root,
            text="Auto Ấp Trứng Nhanh & Mua Đá Linh Lực (Mốc 1 Ngày - Karin & Trứng Linh Thú)",
            padding=(6, 4),
        )
        egg_frame.pack(fill="x", padx=6, pady=(0, 4))

        f_row1 = ttk.Frame(egg_frame)
        f_row1.pack(fill="x")

        self.btn_egg_toggle = ttk.Button(f_row1, text="BẮT ĐẦU AUTO ẤP TRỨNG", command=self.toggle_egg_auto_selected)
        self.btn_egg_toggle.pack(side="left", padx=(0, 8))

        ttk.Button(f_row1, text="Dừng Auto", command=self.stop_egg_selected).pack(side="left", padx=2)
        ttk.Button(f_row1, text="Mua 99 Đá LL ngay", command=self.buy_stone_now_selected).pack(side="left", padx=4)
        ttk.Button(f_row1, text="Giảm 1 ngày ngay", command=self.speedup_egg_now_selected).pack(side="left", padx=2)
        ttk.Button(f_row1, text="Nở trứng ngay", command=self.hatch_egg_now_selected).pack(side="left", padx=2)

        ttk.Label(f_row1, text="Delay (ms):").pack(side="left", padx=(8, 2))
        self.var_egg_delay = tk.IntVar(value=self.cfg.get("eggDelayMs", 120))
        ttk.Spinbox(f_row1, from_=40, to=1000, increment=20, width=5, textvariable=self.var_egg_delay, command=self.save_opts).pack(side="left")

        ttk.Label(f_row1, text="Mục tiêu giảm (ngày):").pack(side="left", padx=(8, 2))
        self.var_egg_target = tk.IntVar(value=self.cfg.get("eggTargetDays", 0))
        ttk.Spinbox(f_row1, from_=0, to=999, width=4, textvariable=self.var_egg_target, command=self.save_opts).pack(side="left")
        ttk.Label(f_row1, text="(0 = đến khi nở)").pack(side="left", padx=2)

        f_row2 = ttk.Frame(egg_frame, padding=(0, 3, 0, 0))
        f_row2.pack(fill="x")

        self.var_egg_buy_stone = tk.BooleanVar(value=self.cfg.get("eggAutoBuyStone", True))
        ttk.Checkbutton(f_row2, text="Tự mua 99 Đá LL khi < 30", variable=self.var_egg_buy_stone, command=self.save_opts).pack(side="left", padx=(0, 10))

        self.var_egg_buy_egg = tk.BooleanVar(value=self.cfg.get("eggAutoBuyEgg", True))
        ttk.Checkbutton(f_row2, text="Tự mua trứng mới khi nở", variable=self.var_egg_buy_egg, command=self.save_opts).pack(side="left", padx=(0, 10))

        self.var_egg_use_egg = tk.BooleanVar(value=self.cfg.get("eggAutoUseEgg", True))
        ttk.Checkbutton(f_row2, text="Tự dùng trứng khi có trong túi", variable=self.var_egg_use_egg, command=self.save_opts).pack(side="left", padx=(0, 10))

        self.lbl_egg_status = ttk.Label(f_row2, text="Trạng thái: Đang dừng | Đã giảm: 0 ngày | Đã mua: 0 Đá LL | Nở: 0 quả", foreground="#1a73e8", font=("Segoe UI", 9, "bold"))
        self.lbl_egg_status.pack(side="left", padx=(10, 0))

        # ---------- Khu vực cấu hình Săn Cụm BOSS & Nhật ký Nhiệm Vụ ----------
        boss_frame = ttk.LabelFrame(
            root,
            text="Cấu hình Săn Cụm BOSS & Nhật ký Tự làm Nhiệm Vụ Chính Tuyến (chọn dòng nhân vật rồi bấm 'Tự làm NV' hoặc 'Săn Boss')",
            padding=6,
        )
        boss_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        clusters_box = ttk.Frame(boss_frame)
        clusters_box.pack(fill="x")
        self.cluster_vars = []
        for i, c in enumerate(self.boss_cfg["clusters"]):
            var = tk.BooleanVar(value=c.get("enabled", False))
            text = f'{c["name"]} ({", ".join(c["members"][:4])}{"..." if len(c["members"]) > 4 else ""})'
            ttk.Checkbutton(clusters_box, text=text, variable=var, command=self.save_boss_opts).grid(
                row=i // 3, column=i % 3, sticky="w", padx=(0, 10), pady=1
            )
            self.cluster_vars.append(var)

        b_opts = ttk.Frame(boss_frame, padding=(0, 6, 0, 2))
        b_opts.pack(fill="x")
        self.var_teleport = tk.BooleanVar(value=self.boss_cfg.get("teleport", True))
        ttk.Checkbutton(b_opts, text="Dịch chuyển áp sát boss", variable=self.var_teleport, command=self.save_boss_opts).pack(side="left")
        self.var_revive = tk.BooleanVar(value=self.boss_cfg.get("autoRevive", True))
        ttk.Checkbutton(b_opts, text="Tự hồi sinh khi chết", variable=self.var_revive, command=self.save_boss_opts).pack(side="left", padx=12)
        ttk.Label(b_opts, text="Tối đa mỗi boss (0=vô hạn):").pack(side="left")
        self.var_revive_max = tk.IntVar(value=self.boss_cfg.get("reviveMaxPerTarget", 0))
        ttk.Spinbox(b_opts, from_=0, to=99, width=3, textvariable=self.var_revive_max, command=self.save_boss_opts).pack(side="left", padx=2)
        self.var_buff = tk.BooleanVar(value=self.boss_cfg.get("useBuffSkills", True))
        ttk.Checkbutton(b_opts, text="Tự dùng skill hỗ trợ (TDHS/Đẻ trứng/Biến khỉ)", variable=self.var_buff, command=self.save_boss_opts).pack(side="left", padx=12)
        ttk.Label(b_opts, text="Chạy trốn HP < (%):").pack(side="left")
        self.var_flee = tk.IntVar(value=self.boss_cfg.get("fleeHpPct", 0))
        ttk.Spinbox(b_opts, from_=0, to=90, width=3, textvariable=self.var_flee, command=self.save_boss_opts).pack(side="left", padx=2)
        ttk.Label(b_opts, text="Quay lại HP >= (%):").pack(side="left", padx=(6, 0))
        self.var_resume = tk.IntVar(value=self.boss_cfg.get("resumeHpPct", 90))
        ttk.Spinbox(b_opts, from_=10, to=100, width=3, textvariable=self.var_resume, command=self.save_boss_opts).pack(side="left", padx=2)

        self.boss_log = tk.Listbox(boss_frame, height=6)
        self.boss_log.pack(fill="both", expand=True, pady=(4, 0))

        threading.Thread(target=self.poll_loop, daemon=True).start()
        threading.Thread(target=self.boss_loop, daemon=True).start()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(500, self.refresh_ui)

    # ---------- luồng nền: nhận game mới, đọc trạng thái, làm NV & săn boss ----------
    def poll_loop(self):
        while not self.stop:
            try:
                self.poll_once()
            except Exception as e:
                self.events.put(("error", str(e)))
            time.sleep(1)

    def boss_loop(self):
        while not self.stop:
            with self.lock:
                games = list(self.games.values())
            for g in games:
                if g.boss.enabled or g.boss.quest_mode or g.boss.sword_active or g.boss.egg_active or g.boss.egg_single_action or g.boss.empty_zone:
                    try:
                        g.boss.tick()
                    except Exception:
                        pass
            time.sleep(0.15)

    def get_target_auto_items(self):
        target_ids = set()
        target_names = set()
        saved_items = self.cfg.get("autoItems") or {}
        for k, _label, ids, names, def_val in AUTO_ITEM_DEFS:
            if saved_items.get(k, def_val):
                target_ids.update(ids)
                for nm in names:
                    target_names.add(norm_str(nm))
        custom = self.cfg.get("customAutoItems", "")
        for part in custom.split(","):
            s = norm_str(part)
            if not s:
                continue
            if s.isdigit():
                target_ids.add(int(s))
            else:
                target_names.add(s)
        return target_ids, target_names

    def poll_once(self):
        pids = list_game_pids()
        wins = game_windows()
        # Ẩn ngay cửa sổ Unity của game vừa bấm "Vào game (Chạy ngầm)" ngay cả khi chưa nạp xong GameCanvas
        for pid in list(self.pending_launches):
            if pid not in pids:
                self.pending_launches.pop(pid, None)
                continue
            pend = self.pending_launches[pid]
            if pend.get("hide") and pid in wins and not pend.get("saved_win"):
                try:
                    pend["saved_win"] = hide_window(wins[pid])
                except Exception:
                    pass
        for pid in list(self.games):
            if pid not in pids:
                self.events.put(("exited", pid))
        for pid in pids:
            if pid not in self.games:
                try:
                    mem = GameMemory(pid)
                    bh = BossHunter(mem, lambda: self.boss_cfg, lambda msg: self.events.put(("boss_log", msg)))
                    pend = self.pending_launches.pop(pid, None)
                    auto_it = bool(pend.get("auto_item", False)) if pend else False
                    game = Game(
                        pid,
                        mem,
                        self.exe_of(pid),
                        filter_junk=self.cfg.get("filterJunk", True),
                        boss_hunter=bh,
                        auto_item=auto_it,
                        pending_login=pend,
                    )
                    if pend and pend.get("hide") and game.mem.can_hide():
                        game.hidden = True
                        game.hidden_fps = max(3, self.cfg["hiddenFps"])
                        game.saved_win = pend.get("saved_win")
                        if pid in wins and not game.saved_win:
                            game.saved_win = hide_window(wins[pid])
                        game.mem.set_hidden(True, max(15, game.hidden_fps))
                    elif game.mem.can_hide() and game.mem.read(game.mem.base + D_FORCE, 1) != bytes(1):
                        game.hidden, game.hidden_fps = True, max(3, self.cfg["hiddenFps"])
                except OSError:
                    continue
                with self.lock:
                    self.games[pid] = game
        idle, total = system_times()
        d_total = total - self.sys_prev[1]
        machine_cpu = 100 * (1 - (idle - self.sys_prev[0]) / d_total) if d_total > 0 else 0
        self.sys_prev = (idle, total)
        ncpu = os.cpu_count() or 1
        target_ids, target_names = self.get_target_auto_items()
        with self.lock:
            games = list(self.games.values())
        for g in games:
            if g.pid in wins:
                g.hwnd = wins[g.pid]
                if g.hidden and not g.saved_win:
                    try:
                        g.saved_win = hide_window(g.hwnd)
                    except Exception:
                        pass
            usage = process_usage(g.pid)
            if usage:
                cpu, g.ram_mb = usage
                now = time.monotonic()
                if g.cpu_prev:
                    g.cpu_pct = (cpu - g.cpu_prev[0]) / 1e7 / (now - g.cpu_prev[1]) / ncpu * 100
                g.cpu_prev = (cpu, now)
            try:
                g.status = g.mem.status()
                if g.status.get("ready") and not g.status.get("offline"):
                    self.learn_account(g)
                if g.status.get("ready") and not g.status.get("offline"):
                    if not g.auto_item_init:
                        g.auto_item_init = True
                        if g.status.get("autoItemCount", 0) > 0:
                            g.auto_item = True
                    if g.pending_login:
                        if g.pending_login.get("auto_login", True) and not g.reconnect:
                            g.mem.set_flag("al", True)
                            g.status["flags"]["al"] = True
                        g.pending_login = None
                    if g.reconnect and g.account_trusted and (g.status.get("flags") or {}).get("al"):
                        # Tự ĐN của MOD đọc acc/pass từ Rms chung -> dễ vào nhầm tài khoản tab khác; để bảng tự kết nối lại
                        g.mem.set_flag("al", False)
                        g.status["flags"]["al"] = False
                    if (g.status.get("flags") or {}).get("al"):
                        u, p = g.account if (g.account_trusted and g.account) else (None, None)
                        g.mem.ensure_auto_login_bound(u, p)
                    sword_busy = g.boss.sword_active  # đang tự đổi/nâng Kiếm Z: không đụng vào hành trang, mua nhanh cần đủ FPS
                    if g.hidden:
                        g.mem.set_fps(60 if sword_busy else g.hidden_fps)
                    if not sword_busy and (g.auto_item or g.mem.panel_auto_ids):  # chưa bật trên bảng thì không đụng vào Auto Item của MOD
                        g.status["autoItemCount"] = g.mem.sync_auto_items(g.auto_item, target_ids, target_names)
                    # Không vứt đồ rác đúng lúc đang giao chiến với boss hoặc đang tự đổi/nâng Kiếm Z
                    if not sword_busy and g.filter_junk and g.status.get("junkSlots") and g.boss.state != "FIGHT":
                        threw = False
                        for slot in reversed(g.status["junkSlots"][-5:]):
                            if g.mem.throw_bag_item(slot):
                                threw = True
                        if threw:
                            g.status = g.mem.status()
                else:
                    if g.hidden:
                        g.mem.set_fps(max(15, g.hidden_fps))
                    now = time.monotonic()
                    if g.pending_login:
                        if now - g.pending_login.get("last_try", 0.0) >= 3.8:
                            g.pending_login["last_try"] = now
                            g.pending_login["tries"] = g.pending_login.get("tries", 0) + 1
                            u = g.pending_login.get("user", "")
                            pw = g.pending_login.get("pass", "")
                            if g.pending_login.get("auto_login", True):
                                g.mem.set_flag("al", True)
                            g.mem.login_now(u, pw)
                            if g.pending_login["tries"] >= 10:
                                g.pending_login = None
                    elif g.status.get("onLoginScr"):
                        # Người chơi đang mở màn hình Đổi tài khoản (LoginScr): không tự đăng nhập đè tài khoản cũ,
                        # đồng thời xoá trạng thái tài khoản cũ của cửa sổ này để nhận tài khoản mới khi vào game
                        g.account, g.account_trusted = None, False
                        g.last_reconnect_try = now
                    elif g.reconnect and g.account_trusted and g.account and g.account[0]:
                        dup_ready = any(
                            o.pid != g.pid and (o.status or {}).get("ready") and not (o.status or {}).get("offline")
                            and o.account and o.account[0] == g.account[0]
                            for o in games
                        )
                        cd = g.mem.login_cooldown()  # "Bạn chỉ có thể đăng nhập lại sau N giây nữa" -> chờ đúng N giây
                        if cd and cd[0] != g.cooldown_seen:
                            g.cooldown_seen = cd[0]
                            g.last_reconnect_try, g.reconnect_wait = now, cd[1] + 1.0
                        # server bị DDoS thì thử thưa dần (5s, 10s, 20s... tối đa 60s), vào được thì về lại 5s
                        if not dup_ready and now - g.last_reconnect_try >= g.reconnect_wait:
                            g.last_reconnect_try = now
                            g.reconnect_wait = min(60.0, max(5.0, g.reconnect_wait) * 2)
                            self.events.put(("boss_log", f"[{g.account[0]}] Mất kết nối -> đăng nhập lại (lần sau chờ {g.reconnect_wait:g}s)"))
                            g.mem.login_now(g.account[0], g.account[1])
            except OSError:
                pass
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
            elif ev[0] == "boss_log":
                self.boss_log.insert("end", ev[1])
                if self.boss_log.size() > 200:
                    self.boss_log.delete(0)
                self.boss_log.see("end")
            elif ev[0] == "error":
                print("[LỖI]", ev[1])
        with self.lock:
            games = dict(self.games)
        for pid in self.tree.get_children():
            if int(pid) not in games:
                self.tree.delete(pid)
        for pid, g in games.items():
            self.tree_row(g)
        pids = self.selected() or list(games.keys())
        first_game = games.get(pids[0]) if pids else None
        if first_game:
            bh = first_game.boss
            bh_st = first_game.mem.statics("bh") if first_game.mem else 0
            me_ptr = first_game.mem.ptr(bh_st + 0xA8) if bh_st else 0
            da_ll, _ = first_game.mem.count_bag_item(me_ptr, ITEM_ID_DA_LINH_LUC) if me_ptr else (0, 0)
            tv, _ = first_game.mem.count_bag_item(me_ptr, ITEM_ID_THOI_VANG) if me_ptr else (0, 0)
            txt = f"Trạng thái: {bh.egg_status_text} | Đã giảm: {bh.egg_days_reduced} ngày | Đã mua: {bh.egg_stones_bought} Đá LL | Nở: {bh.egg_hatched_count} quả | Còn: {da_ll} Đá LL, {tv} TV"
            self.lbl_egg_status.config(text=txt)
            self.lbl_sword_status.config(text=bh.sword_status_text)
            self.btn_egg_toggle.config(text="DỪNG AUTO ẤP TRỨNG" if bh.egg_active else "BẮT ĐẦU AUTO ẤP TRỨNG")
        self.root.after(1000, self.refresh_ui)

    def tree_row(self, g):
        s = g.status or {}
        if s.get("ready"):
            name = s["name"] + (" (chết)" if s.get("dead") else "")
            where = f'{s["map"]} - khu {s["zone"]}'
            hp = f'{s["hp"]:,}/{s["hpFull"]:,}'
            mp = f'{s["mp"]:,}/{s["mpFull"]:,}'
            bag_info = f'{s.get("bagUsed", 0)} ({s.get("skhCount", 0)} SKH)'
            q = s.get("quest")
            if q and not q.get("done"):
                cnt_txt = f' ({max(0, q["progress"])}/{q["need"]})' if q.get("need", -1) > 1 else ""
                quest_txt = f'NV{q["id"]} [{q["step"]+1}/{q["total"]}]: {q["title"]}{cnt_txt}'
            elif q and q.get("done"):
                quest_txt = f'NV{q["id"]}: Hoàn thành'
            else:
                quest_txt = ""
        else:
            u = (g.pending_login or {}).get("user") or (g.account[0] if g.account else "")
            name = f"Đang ĐN ({u})..." if u else "Đang đăng nhập..."
            where, hp, mp, bag_info, quest_txt = "", "", "", "", ""
        flag_list = [label for key, label in FLAG_NAMES if (s.get("flags") or {}).get(key)]
        if g.auto_item:
            cnt = s.get("autoItemCount", 0)
            flag_list.append(f"Auto Item({cnt})" if cnt else "Auto Item")
        if g.filter_junk:
            flag_list.append("Lọc rác")
        if g.boss.empty_zone:
            flag_list.append("Khu trống")
        if g.reconnect:
            flag_list.append("Kết nối lại" if g.account_trusted else "Kết nối lại (chưa rõ TK)")
        if g.boss.quest_mode:
            flag_list.append("Làm NV")
        if g.boss.egg_active:
            flag_list.append("Ấp trứng")
        if g.boss.sword_active:
            flag_list.append("Kiếm Z")
        flags = ", ".join(flag_list)
        picked = "" if s.get("picked") is None else s["picked"]
        dropped = s.get("dropped", 0)
        boss_txt = g.boss.summary_text()
        view = "Ẩn" if g.hidden else "Hiện"
        vals = (g.pid, name, where, hp, mp, f"{g.cpu_pct:.0f}%", f"{g.ram_mb:.0f} MB", picked, bag_info, dropped, quest_txt, boss_txt, flags, view)
        if self.tree.exists(str(g.pid)):
            self.tree.item(str(g.pid), values=vals)
        else:
            self.tree.insert("", "end", iid=str(g.pid), values=vals)

    def selected(self):
        return [int(i) for i in self.tree.selection()]

    def on_tree_select(self, _ev=None):
        pids = self.selected()
        if not pids:
            return
        g = self.games.get(pids[0])
        if g and g.account and g.account[0]:
            u, pw = g.account
            if not pw:
                pw = (self.cfg.get("accounts") or {}).get(u, "")
            self.var_user.set(u)
            self.var_pass.set(pw)

    def on_select_account(self, _ev=None):
        u = self.var_user.get().strip()
        pw = (self.cfg.get("accounts") or {}).get(u)
        if pw is not None:
            self.var_pass.set(pw)

    def remember_account(self, user, pw):
        user = (user or "").strip()
        pw = (pw or "").strip()
        if not user:
            return
        save_rms_login(user, pw)
        accs = dict(self.cfg.get("accounts") or {})
        accs[user] = pw
        self.cfg["accounts"] = accs
        self.cfg["lastUser"] = user
        self.cfg["lastPass"] = pw
        self.cmb_user["values"] = list(accs.keys())
        save_config(self.cfg)

    def launch_and_login_bg(self):
        user = self.var_user.get().strip()
        pw = self.var_pass.get().strip()
        if not user:
            messagebox.showinfo("Đăng nhập ngầm", "Hãy nhập Tài khoản và Mật khẩu trước khi bấm 'Vào game (Chạy ngầm)'.")
            return
        self.remember_account(user, pw)
        hide_bg = bool(self.var_login_hide.get())
        auto_it = bool(self.var_login_auto_item.get())
        pend = {"user": user, "pass": pw, "hide": hide_bg, "auto_login": True, "auto_item": auto_it, "last_try": 0.0, "tries": 0}
        # Nếu đang chọn 1 dòng game đang ở màn hình chờ đăng nhập (!ready) thì đăng nhập luôn vào dòng đó
        for pid in self.selected():
            g = self.games.get(pid)
            if g and not (g.status or {}).get("ready"):
                g.account, g.account_trusted = (user, pw), True
                g.auto_item = auto_it or g.auto_item
                g.pending_login = dict(pend)
                if hide_bg:
                    self.set_hidden([pid], True)
                try:
                    g.mem.set_flag("al", True)
                    g.mem.login_now(user, pw)
                    g.pending_login["last_try"] = time.monotonic()
                    g.pending_login["tries"] = 1
                except OSError:
                    pass
                return
        self.launch_game(pending_login=pend)

    def login_selected(self):
        pids = self.selected()
        if not pids:
            messagebox.showinfo("Đăng nhập dòng chọn", "Hãy chọn ít nhất 1 dòng game đang ở màn hình chờ để đăng nhập.")
            return
        user = self.var_user.get().strip()
        pw = self.var_pass.get().strip()
        if user and len(pids) == 1:
            self.remember_account(user, pw)
        for pid in pids:
            g = self.games.get(pid)
            if not g:
                continue
            if len(pids) > 1 and g.account and g.account[0]:
                u, p = g.account
            else:
                u, p = (user, pw) if user else (g.account or ("", ""))
            if u:
                g.account, g.account_trusted = (u, p), True
            g.pending_login = {"user": u, "pass": p, "hide": g.hidden, "auto_login": True, "auto_item": g.auto_item, "last_try": time.monotonic(), "tries": 1}
            try:
                g.mem.set_flag("al", True)
                g.mem.login_now(u, p)
            except OSError:
                pass

    def toggle_auto_item_selected(self):
        pids = self.selected()
        if not pids:
            messagebox.showinfo("Tự dùng Item", "Hãy chọn ít nhất 1 dòng nhân vật trên bảng để bật/tắt Tự dùng Item.")
            return
        first_game = self.games.get(pids[0])
        target = not (first_game.auto_item if first_game else False)
        t_ids, t_names = self.get_target_auto_items()
        for pid in pids:
            g = self.games.get(pid)
            if g:
                g.auto_item = target
                g.auto_item_init = True
                try:
                    g.status["autoItemCount"] = g.mem.sync_auto_items(target, t_ids, t_names)
                except OSError:
                    pass

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
                show_window(g.hwnd, g.saved_win)
                g.saved_win = None
            g.hidden = hide
            g.hidden_fps = fps
            try:
                g.mem.set_hidden(hide, fps)
            except OSError:
                pass

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

    def toggle_filter_junk(self):
        pids = self.selected()
        if not pids:
            return
        first_game = self.games.get(pids[0])
        target = not (first_game.filter_junk if first_game else True)
        for pid in pids:
            g = self.games.get(pid)
            if g:
                g.filter_junk = target

    def toggle_quest_selected(self):
        pids = self.selected()
        if not pids:
            messagebox.showinfo("Tự làm Nhiệm Vụ", "Hãy chọn ít nhất 1 dòng nhân vật trên bảng để bật/tắt Tự làm Nhiệm Vụ Chính Tuyến.")
            return
        first_game = self.games.get(pids[0])
        target = not (first_game.boss.quest_mode if first_game else False)
        for pid in pids:
            g = self.games.get(pid)
            if g:
                try:
                    g.boss.set_quest_mode(target)
                except OSError:
                    pass

    def toggle_boss_selected(self):
        pids = self.selected()
        if not pids:
            messagebox.showinfo("Săn Boss", "Hãy chọn ít nhất 1 dòng nhân vật trên bảng để bật/tắt Săn Cụm BOSS.")
            return
        first_game = self.games.get(pids[0])
        target = not (first_game.boss.enabled if first_game else False)
        for pid in pids:
            g = self.games.get(pid)
            if g:
                try:
                    g.boss.set_enabled(target)
                except OSError:
                    pass

    def toggle_empty_zone_selected(self):
        pids = self.selected()
        if not pids:
            messagebox.showinfo("Khu trống", "Hãy chọn ít nhất 1 dòng nhân vật để bật/tắt tự tìm khu trống.")
            return
        first_game = self.games.get(pids[0])
        target = not (first_game.boss.empty_zone if first_game else False)
        for pid in pids:
            g = self.games.get(pid)
            if g:
                g.boss.empty_zone = target
                g.boss.ez_phase, g.boss.ez_seen_at, g.boss.ez_next_at = "WATCH", 0.0, 0.0

    def toggle_reconnect_selected(self):
        pids = self.selected()
        if not pids:
            messagebox.showinfo("Tự kết nối lại", "Hãy chọn ít nhất 1 dòng nhân vật để bật/tắt tự kết nối lại.")
            return
        first_game = self.games.get(pids[0])
        target = not (first_game.reconnect if first_game else True)
        for pid in pids:
            g = self.games.get(pid)
            if g:
                g.reconnect, g.reconnect_wait = target, 5.0

    def learn_account(self, g):
        """Tab đang trong game: nhớ / nhận lại tài khoản theo tên nhân vật, rồi tới tài khoản MOD gắn đúng nhân vật,
        cuối cùng là ô đăng nhập của chính tab (không đoán từ Rms dùng chung)"""
        name = (g.status or {}).get("name") or ""
        if not name:
            return
        prev_name = getattr(g, "last_char_name", "")
        if prev_name and prev_name != name:
            # Đổi sang nhân vật khác trên cùng cửa sổ game -> học lại tài khoản theo nhân vật mới
            g.account, g.account_trusted = None, False
        g.last_char_name = name
        g.reconnect_wait = 5.0
        char_accs = self.cfg.setdefault("charAccounts", {})
        accs = self.cfg.setdefault("accounts", {})
        taken_by_other = {u for ch, u in char_accs.items() if ch != name and u}
        if g.account_trusted and g.account and g.account[0]:
            mapped = char_accs.get(name)
            if not mapped:
                if g.account[0] not in taken_by_other:
                    char_accs[name] = g.account[0]
                    save_config(self.cfg)
                    if getattr(g, "mem", None) and g.status.get("loginUser") and g.status.get("loginUser") != g.account[0]:
                        try:
                            g.mem.sync_login_box(g.account[0], g.account[1])
                        except OSError:
                            pass
                    return
                # Tài khoản đang giữ thuộc về nhân vật khác -> cửa sổ này đã đổi tài khoản trong game
                g.account, g.account_trusted = None, False
            else:
                if mapped != g.account[0]:
                    # nhân vật này đã biết là của tài khoản khác -> tab đã vào nhầm tài khoản (vd Tự ĐN của MOD đọc Rms chung):
                    # không ghi đè, theo đúng tài khoản thật để kết nối lại không giành nhau với tab kia
                    g.account = (mapped, accs.get(mapped, ""))
                if getattr(g, "mem", None) and g.status.get("loginUser") and g.status.get("loginUser") != g.account[0]:
                    try:
                        g.mem.sync_login_box(g.account[0], g.account[1])
                    except OSError:
                        pass
                return
        login_user = g.status.get("loginUser") or ""
        login_pass = g.status.get("loginPass") or ""
        bound_user = g.status.get("boundUser") or ""
        if login_user in taken_by_other:
            # Ô loginScr.tfUser đang kẹt tài khoản cũ của nhân vật khác (do vào từ màn hình chọn server / QLTK trước khi vá):
            # kiểm tra Rms hiện tại nếu là tài khoản mới chưa gán cho ai thì nạp lại vào loginScr
            rms_u, rms_p = read_rms_login()
            if rms_u and rms_u not in taken_by_other and getattr(g, "mem", None):
                try:
                    g.mem.sync_login_box(rms_u, rms_p)
                except OSError:
                    pass
                login_user, login_pass = rms_u, rms_p
                g.status["loginUser"], g.status["loginPass"] = rms_u, rms_p
            else:
                login_user, login_pass = "", ""
        if bound_user in taken_by_other:
            bound_user = ""
        user = char_accs.get(name) or bound_user or login_user
        if not user:
            return
        pw = accs.get(user) or (login_pass if user == login_user else "") or ""
        if pw and not accs.get(user):
            accs[user] = pw  # chỉ lưu vào cấu hình bảng, không ghi Rms chung (ghi Rms là tab khác đọc nhầm)
            save_config(self.cfg)
        g.account, g.account_trusted = (user, pw), True
        if getattr(g, "mem", None) and g.status.get("loginUser") and g.status.get("loginUser") != user:
            try:
                g.mem.sync_login_box(user, pw)
            except OSError:
                pass

    def skip_boss_selected(self):
        for pid in self.selected():
            g = self.games.get(pid)
            if g:
                try:
                    g.boss.skip_current()
                except OSError:
                    pass

    def on_toggle_all_filter(self):
        on = self.var_filter.get()
        for g in list(self.games.values()):
            g.filter_junk = on
        self.save_opts()

    def save_boss_opts(self):
        for c, var in zip(self.boss_cfg["clusters"], self.cluster_vars):
            c["enabled"] = bool(var.get())
        self.boss_cfg["teleport"] = bool(self.var_teleport.get())
        self.boss_cfg["autoRevive"] = bool(self.var_revive.get())
        self.boss_cfg["useBuffSkills"] = bool(self.var_buff.get())
        try:
            self.boss_cfg["reviveMaxPerTarget"] = int(self.var_revive_max.get())
            self.boss_cfg["fleeHpPct"] = int(self.var_flee.get())
            self.boss_cfg["resumeHpPct"] = int(self.var_resume.get())
        except (tk.TclError, ValueError):
            pass
        save_boss_config(self.boss_cfg)

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
            others = list(self.games.values())
        if g:
            g.mem.close()
        if g and not g.closing and self.var_watch.get() and g.exe and time.monotonic() - self.last_relaunch > 5:
            u = (g.account[0] if g.account and g.account[0] else "") or self.cfg.get("lastUser", "") or read_rms_string("acc").strip()
            if u and any(o.account and o.account[0] == u for o in others):
                return
            self.last_relaunch = time.monotonic()
            print(f"[MỞ LẠI] Game PID {pid} đã thoát, đang mở lại")
            pw = (g.account[1] if g.account and len(g.account) > 1 and g.account[1] else "") or (self.cfg.get("accounts") or {}).get(u, "") or read_rms_string("pass").strip()
            pend = None
            if u:
                pend = {
                    "user": u,
                    "pass": pw,
                    "hide": g.hidden,
                    "auto_login": True,
                    "auto_item": g.auto_item,
                    "last_try": 0.0,
                    "tries": 0,
                }
            self.launch_game(g.exe, pending_login=pend)

    def ensure_dll_patched(self, exe=None):
        if not exe or not os.path.exists(exe):
            return
        dll = os.path.abspath(os.path.join(os.path.dirname(exe), "GameAssembly.dll"))
        if dll in self.patched_dlls or not os.path.exists(dll):
            return
        try:
            patch_dll(dll)
            self.patched_dlls.add(dll)
        except Exception:
            pass

    def launch_game(self, exe=None, pending_login=None):
        exe = exe or self.cfg["exePath"]
        if not os.path.exists(exe):
            messagebox.showerror("Mở game", f"Không thấy file game:\n{exe}\nBấm 'Chọn file game...'")
            return
        self.ensure_dll_patched(exe)
        proc = subprocess.Popen([exe, *GAME_ARGS], cwd=os.path.dirname(exe), creationflags=BELOW_NORMAL_PRIORITY_CLASS)
        if pending_login and proc and proc.pid:
            self.pending_launches[proc.pid] = dict(pending_login)

    def pick_exe(self):
        path = filedialog.askopenfilename(title="Chọn NgocRongViet.exe", filetypes=[("NgocRongViet", "*.exe")])
        if path:
            self.cfg["exePath"] = os.path.abspath(path)
            self.ensure_dll_patched(self.cfg["exePath"])
            save_config(self.cfg)

    def get_sword_opts(self):
        out = []
        for key, default in (("swordMinNew", 5), ("swordMaxLevel", 6), ("swordMinFinal", 30)):
            try:
                out.append(max(1, int(self.sword_vars[key].get())))
            except (tk.TclError, ValueError):
                out.append(default)
        return out

    def toggle_sword_selected(self):
        pids = self.selected()
        if not pids:
            messagebox.showinfo("Kiếm Z", "Chọn dòng nhân vật cần tự đổi Kiếm Z trước.")
            return
        self.save_opts()
        first_game = self.games.get(pids[0])
        target = not (first_game.boss.sword_active if first_game else False)
        if target and not messagebox.askyesno(
            "Kiếm Z", "Bảng sẽ VỨT HẲN mọi Kiếm Z không đạt ngưỡng (kể cả kiếm đang có sẵn trong hành trang).\nTiếp tục?"
        ):
            return
        for pid in pids:
            g = self.games.get(pid)
            if g:
                try:
                    g.boss.set_sword_auto(target, *self.get_sword_opts())
                except OSError:
                    pass

    def get_egg_opts(self):
        try:
            delay_ms = max(40, min(2000, int(self.var_egg_delay.get())))
        except (tk.TclError, ValueError):
            delay_ms = 120
        try:
            target_days = max(0, min(1000, int(self.var_egg_target.get())))
        except (tk.TclError, ValueError):
            target_days = 0
        auto_buy_stone = bool(self.var_egg_buy_stone.get())
        auto_buy_egg = bool(self.var_egg_buy_egg.get())
        auto_use_egg = bool(self.var_egg_use_egg.get())
        return delay_ms, target_days, auto_buy_stone, auto_buy_egg, auto_use_egg

    def toggle_egg_auto_selected(self):
        pids = self.selected() or list(self.games.keys())
        if not pids:
            messagebox.showinfo("Auto Ấp Trứng", "Chưa có tiến trình game nào đang mở.")
            return
        self.save_opts()
        delay_ms, target_days, buy_stone, buy_egg, use_egg = self.get_egg_opts()
        first_game = self.games.get(pids[0])
        target = not (first_game.boss.egg_active if first_game else False)
        for pid in pids:
            g = self.games.get(pid)
            if g:
                try:
                    g.boss.set_egg_auto(target, delay_ms, target_days, buy_stone, buy_egg, use_egg)
                except OSError:
                    pass
        self.btn_egg_toggle.config(text="DỪNG AUTO ẤP TRỨNG" if target else "BẮT ĐẦU AUTO ẤP TRỨNG")

    def stop_egg_selected(self):
        pids = self.selected() or list(self.games.keys())
        for pid in pids:
            g = self.games.get(pid)
            if g:
                try:
                    g.boss.stop_egg_auto("Đã dừng Auto Ấp Trứng")
                except OSError:
                    pass
        self.btn_egg_toggle.config(text="BẮT ĐẦU AUTO ẤP TRỨNG")

    def buy_stone_now_selected(self):
        pids = self.selected() or list(self.games.keys())
        if not pids:
            messagebox.showinfo("Mua Đá Linh Lực", "Chưa có tiến trình game nào đang mở.")
            return
        for pid in pids:
            g = self.games.get(pid)
            if g:
                try:
                    g.boss.trigger_buy_stone_once()
                except OSError:
                    pass

    def speedup_egg_now_selected(self):
        pids = self.selected() or list(self.games.keys())
        if not pids:
            messagebox.showinfo("Giảm 1 Ngày", "Chưa có tiến trình game nào đang mở.")
            return
        for pid in pids:
            g = self.games.get(pid)
            if g:
                try:
                    g.boss.trigger_speedup_once()
                except OSError:
                    pass

    def hatch_egg_now_selected(self):
        pids = self.selected() or list(self.games.keys())
        if not pids:
            messagebox.showinfo("Nở Trứng", "Chưa có tiến trình game nào đang mở.")
            return
        for pid in pids:
            g = self.games.get(pid)
            if g:
                try:
                    g.boss.trigger_hatch_once()
                except OSError:
                    pass

    def save_opts(self):
        try:
            self.cfg["hiddenFps"] = max(3, min(60, self.var_fps.get()))
        except tk.TclError:
            return
        self.cfg["watchdog"] = self.var_watch.get()
        self.cfg["filterJunk"] = self.var_filter.get()
        self.cfg["loginHideBg"] = bool(self.var_login_hide.get())
        self.cfg["loginAutoItem"] = bool(self.var_login_auto_item.get())
        self.cfg["autoItems"] = {k: bool(v.get()) for k, v in self.auto_item_vars.items()}
        self.cfg["customAutoItems"] = self.var_custom_items.get().strip()
        self.cfg["swordMinNew"], self.cfg["swordMaxLevel"], self.cfg["swordMinFinal"] = self.get_sword_opts()
        egg_delay, egg_target, egg_buy_stone, egg_buy_egg, egg_use_egg = self.get_egg_opts()
        self.cfg["eggDelayMs"] = egg_delay
        self.cfg["eggTargetDays"] = egg_target
        self.cfg["eggAutoBuyStone"] = egg_buy_stone
        self.cfg["eggAutoBuyEgg"] = egg_buy_egg
        self.cfg["eggAutoUseEgg"] = egg_use_egg
        save_config(self.cfg)
        t_ids, t_names = self.get_target_auto_items()
        for g in list(self.games.values()):
            if g.auto_item:
                try:
                    g.status["autoItemCount"] = g.mem.sync_auto_items(True, t_ids, t_names)
                except OSError:
                    pass

    def on_close(self):
        self.stop = True
        for g in list(self.games.values()):
            if g.boss.enabled:
                try:
                    g.boss.set_enabled(False)
                except OSError:
                    pass
            if g.boss.quest_mode:
                try:
                    g.boss.set_quest_mode(False)
                except OSError:
                    pass
            if g.boss.sword_active:
                try:
                    g.boss.stop_sword_auto("")
                except OSError:
                    pass
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
