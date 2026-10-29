"""Kiểm tra GameMemory.sync_auto_items trên bộ nhớ giả (fg.cnf giả lập đúng kiểu BẬT/TẮT của MOD)."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import control_panel as cp  # noqa: E402

FG, MJR, ARR, BH, ME, BAG = 0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x6000


class FakeMem(cp.GameMemory):
    def __init__(self, user_list, flag, bag_ids):
        self.m = bytearray(0x20000)
        self.panel_auto_ids, self.panel_auto_flag, self.auto_item_tried = set(), False, {}
        self.calls = 0
        self.write(FG + 0x11, bytes([flag]))
        self.write(FG + 0x18, struct.pack("<Q", MJR))
        self.write(MJR + 0x10, struct.pack("<Q", ARR))
        self.set_list(user_list)
        self.write(BH + 0xA8, struct.pack("<Q", ME))
        self.write(ME + 0x250, struct.pack("<Q", BAG))
        self.write(BAG + 0x18, struct.pack("<i", len(bag_ids)))
        for k, tid in enumerate(bag_ids):
            it, tpl = 0x7000 + k * 0x100, 0x9000 + k * 0x100
            self.write(BAG + 0x20 + 8 * k, struct.pack("<Q", it))
            self.write(it + 0x18, struct.pack("<Q", tpl))
            self.write(tpl + 0x10, struct.pack("<h", tid))

    def read(self, addr, size):
        return bytes(self.m[addr:addr + size])

    def write(self, addr, data):
        self.m[addr:addr + len(data)] = data

    def statics(self, cls):
        return {"fg": FG, "bh": BH}.get(cls, 0)

    def set_list(self, ids):
        self.write(ARR + 0x20, b"".join(struct.pack("<ii", i + 1000, i) for i in ids))
        self.write(MJR + 0x18, struct.pack("<i", len(ids)))

    def ids(self):
        return [iid for _ic, iid in self._mod_auto_list(FG)[2]]

    def flag(self):
        return self.m[FG + 0x11]

    def call_fn(self, rva, it, _show):  # fg.cnf: có thì xoá, chưa có thì thêm
        assert rva == cp.RVA_AUTO_ITEM_SET
        self.calls += 1
        tid = self.num(self.ptr(it + 0x18) + 0x10, "<h")
        cur = self.ids()
        self.set_list([i for i in cur if i != tid] if tid in cur else cur + [tid])
        return True


# Người chơi tự bật Auto Item trong game với 381 (Cuồng nộ) + 999; hành trang có 381 và 1635 (Cỏ 4 lá)
m = FakeMem([381, 999], 1, [381, 1635])
assert m.sync_auto_items(True, {1635}, set()) == 3 and sorted(m.ids()) == [381, 999, 1635], m.ids()
assert m.panel_auto_ids == {1635} and m.calls == 1
for _ in range(3):  # gọi lại mỗi giây: không được bật/tắt qua lại
    m.sync_auto_items(True, {1635}, set())
assert sorted(m.ids()) == [381, 999, 1635] and m.calls == 1, (m.ids(), m.calls)
m.sync_auto_items(True, set(), set())  # bỏ tích Cỏ: chỉ xoá Cỏ, giữ đồ của người chơi
assert sorted(m.ids()) == [381, 999] and m.flag() == 1, m.ids()
m.sync_auto_items(False, set(), set())  # tắt trên bảng: không tắt cờ người chơi tự bật
assert sorted(m.ids()) == [381, 999] and m.flag() == 1

# Người chơi chưa bật gì: bảng bật cờ + thêm 381, tắt trên bảng thì trả lại như cũ
m = FakeMem([], 0, [381])
m.sync_auto_items(True, {381}, set())
assert m.ids() == [381] and m.flag() == 1 and m.panel_auto_flag
m.sync_auto_items(False, {381}, set())
assert m.ids() == [] and m.flag() == 0

# Item tích theo TÊN (ô "Item khác") không bị bỏ rồi thêm lại
m = FakeMem([], 1, [1234])
m.write(0x9000 + 0x18, struct.pack("<Q", 0))
orig_string = m.string
m.string = lambda addr: "bình nước" if addr == 0x9000 + 0x18 else orig_string(addr)
for _ in range(3):
    m.sync_auto_items(True, set(), {"bình nước"})
assert m.ids() == [1234] and m.calls == 1, (m.ids(), m.calls)
print("OK: sync_auto_items giữ Auto Item của người chơi, không bật/tắt qua lại")
