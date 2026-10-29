"""Kiểm tra Tự kết nối lại: mỗi tab giữ đúng tài khoản của nó, đăng nhập 2 tab không chen nhau vào Rms dùng chung."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import control_panel as cp  # noqa: E402

cp.save_config = lambda _cfg: None  # không ghi panel_config.json thật


class App:
    learn_account = cp.PanelApp.learn_account

    def __init__(self):
        self.cfg = {"accounts": {"accA": "passA", "accB": "passB"}, "charAccounts": {}}


def game(name, account=None, bound=""):
    g = cp.Game.__new__(cp.Game)
    g.account, g.account_trusted = account, bool(account)
    g.reconnect_wait = 40.0
    g.status = {"name": name, "boundUser": bound} if bound else {"name": name}
    return g


app = App()
# Tab A do bảng đăng nhập accA -> nhớ nhân vật "NvA" là của accA
a = game("NvA", ("accA", "passA"))
app.learn_account(a)
assert app.cfg["charAccounts"] == {"NvA": "accA"} and a.reconnect_wait == 5.0

# Bảng mở lại: tab A chưa rõ tài khoản -> nhận lại theo tên nhân vật, kể cả khi ô đăng nhập (Rms chung) đang ghi accB
a2 = game("NvA")
a2.status["username"] = "accB"
app.learn_account(a2)
assert a2.account == ("accA", "passA") and a2.account_trusted

# Nhân vật lạ: chỉ tin tài khoản MOD đã gắn đúng id nhân vật (boundUser), không đoán bừa
b = game("NvB", bound="accB")
app.learn_account(b)
assert b.account == ("accB", "passB") and b.account_trusted
c = game("NvC")
app.learn_account(c)
assert c.account is None and not c.account_trusted

# Đăng nhập ngay trong game (bảng chưa biết gì): nhận từ ô Tài khoản/Mật khẩu của chính tab đó, nhớ mật khẩu vào cấu hình
d = game("NvD")
d.status.update(loginUser="accD", loginPass="passD")
app.learn_account(d)
assert d.account == ("accD", "passD") and d.account_trusted and app.cfg["accounts"]["accD"] == "passD"
app.learn_account(d)  # lần sau: ghi nhớ nhân vật -> tài khoản
assert app.cfg["charAccounts"]["NvD"] == "accD"

# Nhân vật đã biết của accA nhưng ô đăng nhập ghi accB (mật khẩu B): vẫn lấy accA và mật khẩu của A
e = game("NvA")
e.status.update(loginUser="accB", loginPass="passB")
app.learn_account(e)
assert e.account == ("accA", "passA"), e.account

# Tab định đăng nhập accB nhưng lỡ vào nhân vật NvA (của accA): không ghi đè NvA -> accB, theo tài khoản thật accA
f = game("NvA", ("accB", "passB"))
app.learn_account(f)
assert app.cfg["charAccounts"]["NvA"] == "accA" and f.account == ("accA", "passA"), (app.cfg["charAccounts"], f.account)

# 2 tab mất kết nối cùng lúc: ghi Rms + nạp + đăng nhập của tab này phải xong hẳn rồi tab kia mới được ghi
order = []


class Mem(cp.GameMemory):
    def __init__(self, user):
        self.user = user

    def _login_now(self, username, password):
        order.append(("start", username))
        time.sleep(0.05)
        order.append(("end", username))
        return True


ts = [threading.Thread(target=Mem(u).login_now, args=(u, "x")) for u in ("accA", "accB")]
for t in ts:
    t.start()
for t in ts:
    t.join()
assert [k for k, _ in order] == ["start", "end", "start", "end"], order
assert order[0][1] == order[1][1] and order[2][1] == order[3][1]
print("OK: kết nối lại giữ đúng tài khoản từng tab, đăng nhập lần lượt từng tab")
