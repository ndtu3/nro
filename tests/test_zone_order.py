"""Kiểm tra thứ tự dò khu tìm boss: khu đông người trước, khu đầy để cuối (không bỏ hẳn)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import control_panel as cp  # noqa: E402

h = cp.BossHunter(None, lambda: {}, lambda _m: None)
h.zone_list = lambda: [
    {"id": 0, "num": 3, "max": 12},
    {"id": 1, "num": 12, "max": 12},  # đầy
    {"id": 2, "num": 8, "max": 12},
    {"id": 3, "num": 0, "max": 12},
    {"id": 4, "num": 1, "max": 12},
]
h.visited = {4}  # khu đang đứng đã dò
order = []
while (z := h.next_zone({"maxZone": 15})) >= 0:
    order.append(z)
    h.visited.add(z)
assert order == [2, 0, 3, 1], order
print("OK: dò khu đông người trước, khu đầy để cuối")
