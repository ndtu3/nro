"""Kiểm tra tự đổi + nâng cấp Kiếm Z: ngưỡng giữ/vứt và 1 vòng mua nguyên liệu -> đổi -> vứt kiếm xấu -> nâng -> vứt +6 yếu."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import control_panel as cp  # noqa: E402

# ngưỡng: kiếm mới < 5% vứt; +6 phải TRÊN 30% mới giữ; kiếm đang nâng dở thì nâng tiếp dù % thấp
assert cp.sword_action(4, 0) == "vứt" and cp.sword_action(5, 0) == "nâng"
assert cp.sword_action(30, 6) == "vứt" and cp.sword_action(31, 6) == "giữ"
assert cp.sword_action(3, 2) == "nâng"

NEW_SWORDS = [3, 7, 2, 9]  # % sức đánh của các kiếm sẽ đổi được, theo thứ tự
FINAL = {7: 25, 9: 40}     # % sức đánh khi lên +6


class FakeMem:
    def __init__(self):
        self.bag = {cp.ITEM_ID_TINH_THE: 0, cp.ITEM_ID_DA_NGUC_TU: 0, cp.ITEM_ID_THOI_VANG: 50000}
        self.swords = {}  # ô -> [% sức đánh, cấp, % gốc]
        self.cap = 2      # số ô trống dành cho kiếm
        self.menu, self.shop, self.buying = [], False, None
        self.map, self.new, self.thrown = 0, list(NEW_SWORDS), []

    def num(self, addr, fmt):
        return 1  # còn sống

    def statics(self, cls, init=False):
        return 0

    def ptr(self, addr):
        return 0

    def read(self, addr, n):
        return b"\x00" * n

    def call_fn(self, rva, a=0, b=0):
        if rva == cp.RVA_XMAP_START:
            self.map = a
        return True

    def list_swords(self, me):
        return [(slot, d, lvl) for slot, (d, lvl, _b) in sorted(self.swords.items())]

    def count_bag_item(self, me, tid):
        return self.bag[tid], self.cap - len(self.swords)

    def read_current_menu(self):
        return list(self.menu)

    def close_menu(self):
        self.menu = []

    def hide_panels(self):
        self.shop = False

    def is_panel_open(self):
        return self.shop

    is_shop_open = is_panel_open

    def select_menu_option(self, idx):
        cap, self.menu = self.menu[idx], []
        if cap == "trao đổi":
            self.menu = ["15 ngày (15 thỏi)", "vĩnh viễn (100 thỏi)", "từ chối"]
        elif cap.startswith("vĩnh viễn") and self.new:
            self.bag[cp.ITEM_ID_TINH_THE] -= 99
            self.bag[cp.ITEM_ID_THOI_VANG] -= 100
            d = self.new.pop(0)
            self.swords[min(set(range(self.cap)) - set(self.swords))] = [d, 0, d]
        elif cap == "đồng ý":
            sw = self.swords[self.up_slot]
            self.bag[cp.ITEM_ID_DA_NGUC_TU] -= 1
            sw[1] += 1
            if sw[1] == 6:
                sw[0] = FINAL[sw[2]]
        elif cap == "cửa hàng":
            self.shop = True
        elif cap == "đến hành tinh bill":
            self.map = cp.MAP_ID_BILL
        elif cap == "đến hành tinh ngục tù":
            self.map = cp.MAP_ID_NGUC_TU_1
        return True

    def throw_bag_item(self, slot):
        self.thrown.append(tuple(self.swords.pop(slot)[:2]))
        return True

    def start_autobuy(self, tid, threads, qty, delay):
        assert self.shop and self.map == cp.MAP_ID_NGUC_TU_2
        self.buying = tid
        return [1]

    def remaining_autobuy_count(self, items):
        if self.buying:  # mua xong ngay trong 1 nhịp
            self.bag[self.buying] += threads_total
            self.bag[cp.ITEM_ID_THOI_VANG] -= threads_total
            self.buying = None
        return 0

    def stop_all_autobuy(self, items=None):
        self.buying = None

    def use_bag_slot(self, slot):
        assert self.shop and self.map == cp.MAP_ID_NGUC_TU_2
        self.up_slot = slot
        self.menu = ["đồng ý x100", "đồng ý x10", "đồng ý", "từ chối"]
        return True


threads_total = cp.SWORD_BUY_QTY
mem = FakeMem()
logs = []
h = cp.BossHunter(mem, lambda: {}, logs.append)
NPC_MENUS = {
    (cp.MAP_ID_THANH_DIA_KAIO, cp.NPC_ID_TO_SU_KAIO): ["nâng giới hạn sức mạnh", "trao đổi"],
    (cp.MAP_ID_THANH_DIA_KAIO, cp.NPC_ID_OSIN): ["đến kaio", "đến hành tinh bill", "từ chối"],
    (cp.MAP_ID_BILL, cp.NPC_ID_OSIN): ["đến hành tinh ngục tù", "từ chối"],
    (cp.MAP_ID_NGUC_TU_1, cp.NPC_ID_OSIN): ["đến hành tinh bill", "từ chối"],
    (cp.MAP_ID_NGUC_TU_2, cp.NPC_ID_MAI): ["cửa hàng", "nâng cấp"],
}
h.interact_npc = lambda npc: setattr(mem, "menu", list(NPC_MENUS[(mem.map, npc)])) or True
h.sword_door = lambda right, cur: setattr(mem, "map", {(True, cp.MAP_ID_NGUC_TU_1): cp.MAP_ID_NGUC_TU_2,
                                                        (False, cp.MAP_ID_NGUC_TU_2): cp.MAP_ID_NGUC_TU_1}[(right, cur)])
h.chars_in_map = lambda: []
h.show_game_scr = lambda: None

h.set_sword_auto(True)
now = 0.0
for _ in range(600):
    if not h.sword_active:
        break
    h.sword_tick(1, mem.map, 0, now)
    now += 10000
# 4 kiếm đổi được: 3% và 2% vứt ngay; 7% lên +6 chỉ 25% -> vứt; 9% lên +6 được 40% -> giữ. Hết kiếm để đổi thì fake hết hàng.
# trục trặc tạm thời (ở đây: NPC không đổi được nữa) thì không tự dừng mà thử lại, chỉ người dùng bấm mới dừng
assert not mem.new and h.sword_active and "thử lại" in logs[-1], (mem.new, logs)
assert sorted(mem.thrown) == [(2, 0), (3, 0), (25, 6)], mem.thrown
assert [(d, lvl) for d, lvl, _b in mem.swords.values()] == [(40, 6)], mem.swords
assert mem.bag[cp.ITEM_ID_TINH_THE] == cp.SWORD_BUY_QTY - 4 * 99 and mem.bag[cp.ITEM_ID_DA_NGUC_TU] == cp.SWORD_BUY_QTY - 12

# hành trang đầy + hết sạch Đá ngục tù: không có ô để mua -> vứt kiếm kém nhất (chưa đủ cấp) rồi mới mua được
mem = FakeMem()
mem.bag.update({cp.ITEM_ID_TINH_THE: 5000, cp.ITEM_ID_DA_NGUC_TU: 0})
mem.swords = {0: [5, 0, 5], 1: [9, 0, 9]}
mem.new, mem.map = [], cp.MAP_ID_NGUC_TU_2
real_start = mem.start_autobuy
mem.start_autobuy = lambda *a: real_start(*a) if len(mem.swords) < mem.cap else []
h = cp.BossHunter(mem, lambda: {}, logs.append)
h.interact_npc = lambda npc: setattr(mem, "menu", list(NPC_MENUS[(mem.map, npc)])) or True
h.chars_in_map = lambda: []
h.set_sword_auto(True)
for i in range(20):
    h.sword_tick(1, mem.map, 0, i * 10000.0)
assert mem.thrown == [(5, 0)] and mem.bag[cp.ITEM_ID_DA_NGUC_TU] > 0, (mem.thrown, mem.bag, logs[-4:])
print("OK: Kiếm Z - mua nguyên liệu, đổi, vứt kiếm xấu, nâng +6, chỉ giữ kiếm +6 trên 30%")
