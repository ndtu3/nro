"""Kiểm tra đánh boss con trước: Siêu Bọ Hung sinh Xên con thì phải đánh Xên con, hết Xên con mới quay lại boss chính."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import control_panel as cp  # noqa: E402


def hunter(cluster, chars):
    h = cp.BossHunter(None, lambda: {}, lambda _m: None)
    h.cluster = cluster
    h.chars_in_map = lambda: list(range(len(chars)))
    h.char_info = lambda i: dict(chars[i])
    return h


def boss(name, pk=0, hp=100, cid=-5):
    return {"name": name, "id": cid, "hp": hp, "hpFull": 100, "x": 0, "y": 0, "pk": pk}


# Cụm trong boss_clusters.json cũ (không có "minions") -> dùng mặc định cho Siêu Bọ Hung
sbh = {"name": "Siêu Bọ Hung", "enabled": True, "members": ["Siêu bọ hung"]}
chars = [boss("Siêu Bọ Hung", pk=5), boss("Xên con 3"), boss("Xên con 1"), boss("Người chơi", cid=123), boss("Xên con 2", hp=0)]
h = hunter(sbh, chars)
alive = h.alive_bosses_here()
names = [i["name"] for _c, i in alive]
assert names == ["Siêu Bọ Hung", "Xên con 3", "Xên con 1"], names  # người chơi và Xên con đã chết bị bỏ
assert h.fight_order(alive)[0][1]["name"].startswith("Xên con")  # đánh Xên con trước dù boss chính đang đánh mình

# Hết Xên con -> quay lại Siêu Bọ Hung
h = hunter(sbh, [boss("Siêu Bọ Hung")])
assert h.fight_order(h.alive_bosses_here())[0][1]["name"] == "Siêu Bọ Hung"

# Cụm "Xên Bọ Hung" (có Xên hoàn thiện), boss_clusters.json cũ không ghi "minions": vẫn đánh Xên con trước
xbh = {"name": "Xên Bọ Hung", "enabled": True, "members": ["Xên Bọ Hung *", "Xên hoàn thiện"]}
h = hunter(xbh, [boss("Xên hoàn thiện", pk=5), boss("Xên con 4")])
assert [i["name"] for _c, i in h.fight_order(h.alive_bosses_here())] == ["Xên con 4", "Xên hoàn thiện"]

# Cụm khác không có boss con: vẫn ưu tiên boss đang đánh mình (pk 5) như cũ, không nhận boss lạ
other = {"name": "Bojack", "members": ["Bojack", "Bido"]}
h = hunter(other, [boss("Bido"), boss("Bojack", pk=5), boss("Xên con 1")])
alive = h.alive_bosses_here()
assert [i["name"] for _c, i in h.fight_order(alive)] == ["Bojack", "Bido"]
print("OK: Siêu Bọ Hung -> đánh Xên con trước, hết Xên con mới đánh boss chính")
