"""Bảng điều khiển Săn Cụm BOSS cho NgocRongViet (gắn vào game đang chạy bằng Frida).

Chạy: mở game, đăng nhập vào nhân vật, rồi chạy run_boss_hunter.bat (hoặc python boss_hunter.py).
Danh sách cụm boss nằm trong boss_clusters.json, có thể sửa tên thành viên cho đúng tên boss trên server.
"""

import json
import os
import queue
import sys
import tkinter as tk
from tkinter import messagebox, ttk

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".deps"))  # frida cài bởi run_boss_hunter.bat
try:
    import frida
except ImportError:
    print("[LỖI] Chưa cài frida. Chạy run_boss_hunter.bat để tự cài.")
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_PATH = os.path.join(BASE_DIR, "boss_hunter_agent.js")
CONFIG_PATH = os.path.join(BASE_DIR, "boss_clusters.json")
SEEN_PATH = os.path.join(BASE_DIR, "boss_seen.txt")  # tên boss chưa có trong cụm nào
PROCESS_NAME = "NgocRongViet.exe"

STATE_TEXT = {
    "IDLE": "Đang chờ boss thuộc cụm đã chọn",
    "TRAVEL": "Đang XMAP tới map boss",
    "ARRIVE": "Đã tới map, chờ tải xong",
    "SCAN": "Đang dò khu (đông người trước)",
    "FIGHT": "Đang đánh boss",
    "LOOT": "Đang nhặt đồ boss rơi",
    "FLEE": "Máu thấp, đang đổi khu chạy trốn",
    "RETURN": "Đã hồi máu, quay lại khu boss",
}


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)


class BossHunterApp:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.events = queue.Queue()
        self.session = None
        self.script = None
        self.enabled = False

        root.title("Săn Cụm BOSS & Nhiệm Vụ - NgocRongViet")
        root.geometry("1000x720")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        self.btn_toggle = ttk.Button(top, text="BẬT AUTO SĂN CỤM", command=self.toggle)
        self.btn_toggle.pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Bỏ qua boss này", command=self.skip).pack(side="left", padx=(6, 0))
        self.quest_on = False
        self.btn_quest = ttk.Button(top, text="BẬT TỰ LÀM NHIỆM VỤ", command=self.toggle_quest)
        self.btn_quest.pack(side="left", padx=(6, 0))

        box = ttk.LabelFrame(root, text="Cụm boss", padding=8)
        box.pack(fill="x", padx=8)
        self.cluster_vars = []
        for i, c in enumerate(self.cfg["clusters"]):
            var = tk.BooleanVar(value=c["enabled"])
            text = f'{c["name"]}  ({", ".join(c["members"][:5])}{"..." if len(c["members"]) > 5 else ""})'
            if c.get("maps"):
                text += f'  [map {", ".join(map(str, c["maps"]))}]'
            elif c.get("excludeMaps"):
                text += f'  [trừ map {", ".join(map(str, c["excludeMaps"]))}]'
            ttk.Checkbutton(box, text=text, variable=var, command=self.push_config).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 12))
            self.cluster_vars.append(var)

        opts = ttk.Frame(root, padding=(8, 4))
        opts.pack(fill="x")
        self.teleport_var = tk.BooleanVar(value=self.cfg.get("teleport", True))
        ttk.Checkbutton(opts, text="Dịch chuyển áp sát boss", variable=self.teleport_var,
                        command=self.push_config).pack(side="left")
        hp = ttk.Frame(root, padding=(8, 0))
        hp.pack(fill="x")
        ttk.Label(hp, text="Chạy trốn khi HP dưới (%, 0 = đánh tới cùng):").pack(side="left")
        self.flee_var = tk.IntVar(value=self.cfg.get("fleeHpPct", 0))
        ttk.Spinbox(hp, from_=0, to=90, width=4, textvariable=self.flee_var,
                    command=self.push_config).pack(side="left")
        ttk.Label(hp, text="  Quay lại khi HP đạt (%):").pack(side="left")
        self.resume_var = tk.IntVar(value=self.cfg.get("resumeHpPct", 90))
        ttk.Spinbox(hp, from_=10, to=100, width=4, textvariable=self.resume_var,
                    command=self.push_config).pack(side="left")
        rv = ttk.Frame(root, padding=(8, 2))
        rv.pack(fill="x")
        self.revive_var = tk.BooleanVar(value=self.cfg.get("autoRevive", True))
        ttk.Checkbutton(rv, text="Tự động hồi sinh khi chết (tốn ngọc/vàng)", variable=self.revive_var,
                        command=self.push_config).pack(side="left")
        ttk.Label(rv, text="  Tối đa mỗi boss (0 = tới khi hạ hết):").pack(side="left")
        self.revive_max_var = tk.IntVar(value=self.cfg.get("reviveMaxPerTarget", 0))
        ttk.Spinbox(rv, from_=0, to=99, width=4, textvariable=self.revive_max_var,
                    command=self.push_config).pack(side="left")
        self.buff_var = tk.BooleanVar(value=self.cfg.get("useBuffSkills", True))
        ttk.Checkbutton(root, text="Tự dùng skill hỗ trợ khi đánh (TĐ: Thái Dương Hạ San, Namếc: Đẻ trứng, Xayda: Biến khỉ)",
                        variable=self.buff_var, command=self.push_config, padding=(8, 0)).pack(fill="x")
        ttk.Label(root, text="Mẹo: bật 'Tự động ăn đậu' trong menu MOD để hồi máu khi chạy trốn.",
                  padding=(8, 2), foreground="#666").pack(fill="x")

        self.status = tk.StringVar(value="Chưa kết nối game")
        ttk.Label(root, textvariable=self.status, padding=8, justify="left").pack(fill="x")

        self.log = tk.Listbox(root, height=12)
        self.log.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.attach()
        root.after(100, self.pump)

    # ---- Frida ----
    def attach(self):
        try:
            self.session = frida.attach(PROCESS_NAME)
        except frida.ProcessNotFoundError:
            messagebox.showerror("Lỗi", "Chưa mở game NgocRongViet.exe")
            self.root.destroy()
            return
        with open(AGENT_PATH, encoding="utf-8") as fh:
            self.script = self.session.create_script(fh.read())
        self.script.on("message", lambda msg, data: self.events.put(msg))
        self.session.on("detached", lambda reason, crash: self.events.put({"type": "send", "payload": {"type": "detached", "msg": reason}}))
        self.script.load()
        self.push_config()
        self.add_log("Đã kết nối game")

    def push_config(self):
        for c, var in zip(self.cfg["clusters"], self.cluster_vars):
            c["enabled"] = bool(var.get())
        self.cfg["teleport"] = bool(self.teleport_var.get())
        self.cfg["autoRevive"] = bool(self.revive_var.get())
        self.cfg["useBuffSkills"] = bool(self.buff_var.get())
        try:
            self.cfg["fleeHpPct"] = int(self.flee_var.get())
            self.cfg["resumeHpPct"] = int(self.resume_var.get())
            self.cfg["reviveMaxPerTarget"] = int(self.revive_max_var.get())
        except (tk.TclError, ValueError):
            pass
        save_config(self.cfg)
        if self.script:
            agent_cfg = {k: v for k, v in self.cfg.items()}
            agent_cfg["enabled"] = self.enabled
            self.script.exports_sync.set_config(agent_cfg)

    def toggle(self):
        self.enabled = not self.enabled
        self.btn_toggle.config(text="TẮT AUTO SĂN CỤM" if self.enabled else "BẬT AUTO SĂN CỤM")
        self.push_config()

    def toggle_quest(self):
        self.quest_on = not self.quest_on
        self.btn_quest.config(text="TẮT TỰ LÀM NHIỆM VỤ" if self.quest_on else "BẬT TỰ LÀM NHIỆM VỤ")
        if self.script:
            self.script.exports_sync.set_quest_mode(self.quest_on)

    def skip(self):
        if self.script:
            self.script.exports_sync.skip()

    # ---- UI ----
    def add_log(self, text):
        self.log.insert("end", text)
        self.log.see("end")

    def pump(self):
        while not self.events.empty():
            msg = self.events.get()
            if msg.get("type") == "error":
                self.add_log("[LỖI agent] " + msg.get("description", ""))
                continue
            p = msg.get("payload", {})
            kind = p.get("type")
            if kind == "status":
                target = f'{p["cluster"]} - {p["target"]} (map {p["targetMap"]})' if p["cluster"] else "-"
                self.status.set(
                    f'Trạng thái: {STATE_TEXT.get(p["state"], p["state"])}\n'
                    f'Mục tiêu: {target}\n'
                    f'Vị trí: {p["map"]} (map {p["mapId"]}, khu {p["zone"]})   Đang dò khu: {p["scanZone"]}'
                    + (f'\nNhiệm vụ {p["quest"]["id"]} bước {p["quest"]["step"] + 1}/{p["quest"]["total"]}: '
                       f'{p["quest"]["title"]} [{p["quest"]["action"]}]' if p.get("quest") else "")
                )
            elif kind == "questPaused":
                self.quest_on = False
                self.btn_quest.config(text="BẬT TỰ LÀM NHIỆM VỤ")
                messagebox.showinfo("Tự làm nhiệm vụ", "Đã tạm dừng: " + p["msg"])
            elif kind == "log":
                self.add_log(p["msg"])
            elif kind == "unknownBoss":
                line = f'{p["name"]} - {p["map"]} (map {p["mapId"]})'
                self.add_log("Boss chưa thuộc cụm nào: " + line)
                with open(SEEN_PATH, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            elif kind == "error":
                # agent tự bỏ mục tiêu lỗi và chạy tiếp vòng lặp, không tắt săn
                self.add_log("[LỖI, vẫn săn tiếp] " + p["msg"].splitlines()[0])
            elif kind == "detached":
                self.add_log("Mất kết nối game: " + str(p["msg"]))
        self.root.after(100, self.pump)

    def on_close(self):
        try:
            if self.script:
                self.script.exports_sync.set_config({"enabled": False})
                self.script.unload()
            if self.session:
                self.session.detach()
        except frida.InvalidOperationError:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    BossHunterApp(root)
    root.mainloop()
