"""Kiểm tra BossHunter.empty_zone_tick (Khu trống) với game giả lập: đếm người, danh sách khu, hồi đổi khu."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import control_panel as cp  # noqa: E402


class FakeMem:
    def __init__(self):
        self.arr = 1
        self.calls = []

    def statics(self, cls):
        return 0x100 if cls in ("dg", "hx") else 0

    def ptr(self, addr):
        return self.arr if addr == 0x200 + 0x80 else 0x200  # gs+0x80 = mảng số người theo khu

    def call_fn(self, rva, *_args):
        self.calls.append(rva)
        return True


def hunter(others, zones, msg=(None, 0.0, "")):
    h = cp.BossHunter(FakeMem(), lambda: {}, lambda _m: None)
    h.other_players_here = lambda: others[0]
    h.zone_list = lambda: zones
    h.show_game_scr = lambda: None
    h.poll_zone_message = lambda: msg
    h.moved = []
    h.request_zone = lambda z, _now: h.moved.append(z) or True
    return h


Z = [{"id": 0, "num": 3, "max": 15}, {"id": 1, "num": 0, "max": 15}, {"id": 2, "num": 2, "max": 15}]

# Một mình trong khu: không làm gì
h = hunter([0], Z)
for t in range(0, 20000, 500):
    assert not h.empty_zone_tick(0, t)
assert h.moved == [] and h.mem.calls == []

# Có người > 5s: mở danh sách khu, chờ danh sách mới, sang khu 1 (0 người)
h = hunter([2], Z)
t = 0
while h.ez_phase == "WATCH":
    h.empty_zone_tick(0, t)
    t += 500
assert h.ez_phase == "LIST" and t > 5000 and h.mem.calls == [cp.RVA_OPEN_ZONE_UI]
assert h.empty_zone_tick(0, t)          # danh sách chưa về
h.mem.arr = 2                            # server gửi danh sách khu
h.empty_zone_tick(0, t + 500)
assert h.moved == [1] and h.ez_phase == "MOVE"
assert not h.empty_zone_tick(1, t + 1500) and h.ez_phase == "WATCH"  # đã vào khu 1

# Người đi ngang qua < 5s: không đổi khu
h = hunter([1], Z)
h.empty_zone_tick(0, 0)
h.other_players_here = lambda: 0
h.empty_zone_tick(0, 2500)
h.other_players_here = lambda: 1
for t in range(5000, 9000, 500):
    h.empty_zone_tick(0, t)
assert h.ez_phase == "WATCH" and h.moved == []

# Khu nào cũng đông bằng hoặc hơn: ở lại, 60s sau mới xem lại
h = hunter([1], [{"id": 0, "num": 2, "max": 15}, {"id": 1, "num": 2, "max": 15}])
t = 0
while h.ez_phase == "WATCH":
    h.empty_zone_tick(0, t)
    t += 500
h.mem.arr = 2
h.empty_zone_tick(0, t)
assert h.moved == [] and h.ez_phase == "WATCH" and h.ez_next_at >= t + 60000

# Server báo còn hồi đổi khu: chờ đúng số giây đó
h = hunter([2], Z, ("cooldown", 9.0, "Chờ 9 giây"))
t = 0
while h.ez_phase != "MOVE":
    h.mem.arr += 1
    h.empty_zone_tick(0, t)
    t += 500
h.empty_zone_tick(0, t)
assert h.ez_phase == "WATCH" and h.ez_next_at >= t + 9000
print("OK: Khu trống chỉ đổi khu khi có người ở lại >= 5s, chọn khu vắng nhất, tôn trọng hồi đổi khu")
