"""Kiểm tra toàn bộ chu trình Auto Ấp Trứng Nhanh & Mua Đá Linh Lực tại Nhà Bunma (map 101) <-> Siêu Thị (map 84)."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import control_panel as cp  # noqa: E402

BH, DD, HX, BJ, DG, MAIN = 0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x6000
ME, BAG, SHOP, SHOP_TAB, PANEL, MENU, SVC = 0x7000, 0x8000, 0x9000, 0x9500, 0xA000, 0xB000, 0xC000
IT_EGG_SHOP, TPL_EGG_SHOP = 0xD000, 0xD500


class FakeEggMem(cp.GameMemory):
    def __init__(self):
        self.m = bytearray(0x30000)
        self.da_ll = 50
        self.thoi_vang = 100
        self.eggs_in_bag = 0
        self.egg_used_pending_reload = False
        self.egg_in_incubator = False
        self.egg_days_left = 2
        self.cur_map = cp.MAP_ID_NHA_BUNMA
        self.menu_caps = []
        self.selected_picks = []
        self.rva_calls = []
        self.performed_actions = []
        self.use_egg_calls = 0

        self.write(BH + 0xA8, struct.pack("<Q", ME))
        self.write(DD + 0xD0, struct.pack("<Q", MENU))
        self.write(DD + 0xD8, struct.pack("<Q", PANEL))
        self.write(HX, struct.pack("<Q", SVC))

        # Cấu hình item Trứng Linh Thú trong Shop Bunma (tid = 970)
        self.write(IT_EGG_SHOP + 0x18, struct.pack("<Q", TPL_EGG_SHOP))
        self.write(TPL_EGG_SHOP + 0x10, struct.pack("<h", 970))
        self.write(IT_EGG_SHOP + 0x40, struct.pack("<q", 1))

    def read(self, addr, size):
        return bytes(self.m[addr:addr + size])

    def write(self, addr, data):
        self.m[addr:addr + len(data)] = data

    def statics(self, cls, init=False):
        return {"bh": BH, "dd": DD, "hx": HX, "bj": BJ, "dg": DG, "Main": MAIN}.get(cls, 0)

    def count_bag_item(self, me, target_tid):
        if target_tid == cp.ITEM_ID_DA_LINH_LUC:
            return self.da_ll, 10
        if target_tid == cp.ITEM_ID_THOI_VANG:
            return self.thoi_vang, 10
        return 0, 10

    def find_egg_in_bag(self, me):
        if self.eggs_in_bag > 0:
            return 5, 970, "trứng linh thú"
        return -1, 0, ""

    def find_egg_in_shop(self, me):
        if self.read(PANEL + 0x10, 1) != b"\x00":
            return IT_EGG_SHOP, 970, "trứng linh thú"
        return 0, -1, ""

    def read_current_menu(self):
        if self.read(MENU + 0x10, 1) == b"\x00":
            return []
        return list(self.menu_caps)

    def open_fake_menu(self, caps):
        self.menu_caps = list(caps)
        self.write(MENU + 0x10, b"\x01")

    def call_fn(self, rva, arg1=0, arg2=0):
        self.rva_calls.append((rva, arg1, arg2))
        if rva == cp.RVA_PANEL_HIDE:
            self.write(arg1 + 0x10, b"\x00")
            return True
        if rva == cp.RVA_OPEN_NPC_MENU:
            npc_id = arg2
            if npc_id in cp.EGG_SHOP_NPC_IDS:
                self.open_fake_menu(["cửa hàng", "99 đá linh lực 14 thỏi vàng", "99 bùa linh thú 198 thỏi vàng", "ok"])
            elif npc_id in cp.EGG_INCUBATOR_NPC_IDS and self.egg_in_incubator:
                if self.egg_days_left > 0:
                    self.open_fake_menu(["truyền linh lực", "hủy bỏ trứng"])
                else:
                    self.open_fake_menu(["nở", "hủy bỏ trứng"])
            return True
        if rva == cp.RVA_MENU_CLOSE:
            is_select = self.read(MENU + 0x84, 1) == b"\x01" and self.read(MENU + 0x85, 1) == b"\x00"
            pick = self.num(MENU + 0x20, "<i")
            caps_now = list(self.menu_caps)
            self.write(MENU + 0x10, b"\x00")
            self.menu_caps = []
            if is_select and 0 <= pick < len(caps_now):
                self.selected_picks.append((caps_now, pick))
                cap = caps_now[pick]
                if "cửa hàng" in cap:
                    self.write(PANEL + 0x10, b"\x01")
                elif "99 đá linh lực" in cap:
                    self.da_ll += 99
                    self.thoi_vang -= 14
                elif "truyền linh lực" in cap:
                    self.open_fake_menu(["2 đá ll +10tr 1 giờ", "15 đá ll +1 tv 10 giờ", "30 đá ll +3 tv 1 ngày", "từ chối"])
                elif "1 ngày" in cap:
                    self.open_fake_menu(["ok", "từ chối"])
                elif cap == "ok":
                    self.da_ll -= 30
                    self.thoi_vang -= 3
                    self.egg_days_left -= 1
                elif cap == "đồng ý":
                    assert self.eggs_in_bag > 0
                    self.eggs_in_bag -= 1
                    self.use_egg_calls += 1
                    self.egg_used_pending_reload = True
                elif cap == "nở" and any("hủy bỏ" in x for x in caps_now):
                    self.open_fake_menu(["nở", "từ chối"])
                elif cap == "nở":
                    assert self.da_ll >= 200, f"Hatching requires >= 200 Đá LL, had {self.da_ll}"
                    self.da_ll -= 200
                    self.egg_in_incubator = False
            return True
        if rva == cp.RVA_USE_ITEM_BY_TID:
            assert arg1 == 970
            assert self.eggs_in_bag > 0
            # Giống thực tế tại Nhà Bunma (map 101): khi dùng Trứng Linh Thú, server mở menu xác nhận ['đồng ý', 'từ chối']
            self.open_fake_menu(["đồng ý", "từ chối"])
            return True
        return True

    def perform_action(self, listener, id_action, p_obj=0):
        self.performed_actions.append((listener, id_action, p_obj))
        if listener == PANEL and id_action == 3004 and p_obj == IT_EGG_SHOP:
            self.eggs_in_bag += 1
            return True
        return True

    def use_bag_item(self, slot_idx):
        it, tpl = 0xE000, 0xE500
        self.write(ME + 0x250, struct.pack("<Q", BAG))
        self.write(BAG + 0x20 + 8 * slot_idx, struct.pack("<Q", it))
        self.write(it + 0x18, struct.pack("<Q", tpl))
        self.write(tpl + 0x10, struct.pack("<h", 970))
        return super().use_bag_item(slot_idx)


def test_full_egg_auto_cycle():
    mem = FakeEggMem()
    logs = []
    hunter = cp.BossHunter(mem, lambda: {}, logs.append)

    def fake_find_npc(npc_tpl_id):
        if mem.cur_map != cp.MAP_ID_NHA_BUNMA:
            return 0
        if npc_tpl_id == cp.NPC_ID_BUNMA_HOME:
            return 0x11000
        if npc_tpl_id == cp.NPC_ID_MABU_EGG:
            return 0x12000 if mem.egg_in_incubator else 0
        return 0

    waypoints_entered = []

    def fake_go_waypoint(side):
        waypoints_entered.append((mem.cur_map, side))
        if mem.cur_map == cp.MAP_ID_NHA_BUNMA and side == "phải":
            mem.cur_map = cp.MAP_ID_SIEU_THI
            return True
        if mem.cur_map == cp.MAP_ID_SIEU_THI and side == "trái":
            mem.cur_map = cp.MAP_ID_NHA_BUNMA
            if mem.egg_used_pending_reload:
                mem.egg_used_pending_reload = False
                mem.egg_in_incubator = True
                mem.egg_days_left = 2
            return True
        return False

    hunter.find_npc = fake_find_npc
    hunter.go_waypoint = fake_go_waypoint
    hunter.set_egg_auto(True, delay_ms=50, target_days=0, buy_stone=True, buy_egg=True, use_egg=True)

    now = 1000.0
    for _ in range(60):
        now += 1000.0
        hunter.egg_tick(ME, mem.cur_map, 0, now)
        if hunter.egg_hatched_count >= 1 and hunter.egg_phase == "BUY_EGG":
            break

    # 1. Mua đúng 1 quả trứng và chỉ sử dụng đúng 1 quả trứng
    assert any("cửa hàng" in caps[pick] for caps, pick in mem.selected_picks), mem.selected_picks
    assert (PANEL, 3004, IT_EGG_SHOP) in mem.performed_actions, mem.performed_actions
    assert mem.use_egg_calls == 1, mem.use_egg_calls
    # 2. Sau khi dùng 1 trứng, tự sang Siêu Thị (cửa phải map 101) rồi quay lại Nhà Bunma (cửa trái map 84)
    assert waypoints_entered == [(101, "phải"), (84, "trái")], waypoints_entered
    # 3. Ấp giảm 1 ngày 2 lần (tốn 60 Đá LL) + nở trứng (cần >= 200 Đá LL nên tự mua 3 lần 99 Đá LL = 297 Đá LL)
    assert hunter.egg_stones_bought == 297, hunter.egg_stones_bought
    assert hunter.egg_days_reduced == 2, hunter.egg_days_reduced
    assert hunter.egg_hatched_count == 1, hunter.egg_hatched_count
    assert hunter.egg_phase == "BUY_EGG", hunter.egg_phase


def test_only_uses_one_egg_when_bag_has_multiple():
    """Đảm bảo khi trong túi có sẵn 3 quả trứng, tool chỉ dùng ĐÚNG 1 quả rồi sang Siêu Thị load map (không mở liền 3 quả)."""
    mem = FakeEggMem()
    mem.eggs_in_bag = 3
    logs = []
    hunter = cp.BossHunter(mem, lambda: {}, logs.append)

    hunter.find_npc = lambda tpl_id: 0x11000 if (mem.cur_map == 101 and tpl_id == 37) else (0x12000 if (mem.cur_map == 101 and tpl_id == 50 and mem.egg_in_incubator) else 0)

    def fake_go_waypoint(side):
        if mem.cur_map == 101 and side == "phải":
            mem.cur_map = 84
            return True
        if mem.cur_map == 84 and side == "trái":
            mem.cur_map = 101
            mem.egg_in_incubator = True
            mem.egg_days_left = 1
            return True
        return False

    hunter.go_waypoint = fake_go_waypoint
    hunter.set_egg_auto(True, delay_ms=50, target_days=0, buy_stone=True, buy_egg=True, use_egg=True)

    now = 1000.0
    for _ in range(10):
        now += 1000.0
        hunter.egg_tick(ME, mem.cur_map, 0, now)
        if hunter.egg_phase == "SPEEDUP" and mem.egg_in_incubator:
            break

    assert mem.use_egg_calls == 1, f"Expected 1 egg used, got {mem.use_egg_calls}"
    assert mem.eggs_in_bag == 2, f"Expected 2 eggs remaining in bag, got {mem.eggs_in_bag}"
    assert hunter.egg_phase == "SPEEDUP", hunter.egg_phase


if __name__ == "__main__":
    test_full_egg_auto_cycle()
    test_only_uses_one_egg_when_bag_has_multiple()
    print("OK: test_egg_auto")
