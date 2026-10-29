"""Kiểm tra BossHunter.use_buff_skill: hồi chiêu tính theo giờ thật của game, nhận skill theo id hoặc tên (Khiên)."""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import control_panel as cp  # noqa: E402

DG, GS, SKS, ME = 0x1000, 0x2000, 0x3000, 0x4000


class FakeMem:
    def __init__(self):
        self.m = bytearray(0x20000)
        self.names, self.used = {}, []
        self.w(DG + 0x18, "<Q", GS)
        self.w(DG + 0xA0, "<Q", SKS)
        self.w(SKS + 0x18, "<i", 10)  # bảng hiệu ứng skill có 10 phần tử
        self.w(ME + 0xC8, "<q", 10_000)    # KI
        self.w(ME + 0x110, "<q", 10_000)   # KI tối đa

    def w(self, addr, fmt, v):
        self.m[addr:addr + struct.calcsize(fmt)] = struct.pack(fmt, v)

    def read(self, addr, size):
        return bytes(self.m[addr:addr + size])

    def num(self, addr, fmt):
        return struct.unpack(fmt, self.read(addr, struct.calcsize(fmt)))[0]

    def ptr(self, addr):
        return self.num(addr, "<Q")

    def write(self, addr, data):
        self.m[addr:addr + len(data)] = data

    def string(self, addr):
        return self.names.get(addr, "")

    def statics(self, cls):
        return DG if cls == "dg" else 0

    def call_fn(self, rva, _rcx, sk):
        assert rva == cp.RVA_USE_SKILL_NOT_FOCUS
        self.used.append(sk)
        return True

    def skill(self, k, tid, name, last_use_ms, cd_ms):
        sk, tpl = 0x6000 + k * 0x100, 0x9000 + k * 0x100
        self.w(sk + 0x10, "<Q", tpl)
        self.w(sk + 0x30, "<q", last_use_ms)
        self.w(sk + 0x28, "<i", cd_ms)
        self.w(sk + 0x44, "<i", 10)
        self.w(tpl + 0x28, "<i", 3)   # skill tự dùng
        self.w(tpl + 0x10, "<b", tid)
        self.names[tpl + 0x18] = name
        return sk


def hunter(mem, skills):
    h = cp.BossHunter(mem, lambda: {}, lambda _m: None)
    h.my_skills = lambda _me: skills
    h.is_attack_skill = lambda _sk: False
    return h


cfg = {"useBuffSkills": True, "buffSkills": [13, "khiên năng lượng"]}
now_ms = time.time() * 1000.0

# Biến khỉ dùng cách đây 70s, hồi 60s -> phải dùng lại (lỗi cũ: so với monotonic nên coi như đang hồi mãi)
m = FakeMem()
khi = m.skill(0, 13, "Biến khỉ", int(now_ms - 70_000), 60_000)
hunter(m, [khi]).use_buff_skill(ME, time.monotonic() * 1000.0, cfg)
assert m.used == [khi], m.used

# Vừa biến khỉ 10s trước -> đang hồi, không dùng
m = FakeMem()
khi = m.skill(0, 13, "Biến khỉ", int(now_ms - 10_000), 60_000)
hunter(m, [khi]).use_buff_skill(ME, time.monotonic() * 1000.0, cfg)
assert m.used == []

# Khiên nhận theo tên (không cần biết id)
m = FakeMem()
khien = m.skill(1, 19, "Khiên năng lượng", 0, 30_000)
hunter(m, [khien]).use_buff_skill(ME, time.monotonic() * 1000.0, cfg)
assert m.used == [khien], m.used

# Skill không có trong danh sách: không đụng tới
m = FakeMem()
tt = m.skill(2, 8, "Tái tạo năng lượng", 0, 1000)
hunter(m, [tt]).use_buff_skill(ME, time.monotonic() * 1000.0, cfg)
assert m.used == []
print("OK: skill hỗ trợ dùng lại khi hết hồi (giờ thật), nhận Khiên theo tên")
