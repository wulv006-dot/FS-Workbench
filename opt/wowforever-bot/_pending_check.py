# -*- coding: utf-8 -*-
"""离线验证「待登记队列」逻辑 —— 走真实方法，只在内存里假 store，不发网络请求。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import modules.giveaway as G  # noqa: E402

fails = []


def ok(cond, label, detail=""):
    print("  [%s] %-46s %s" % ("OK  " if cond else "FAIL", label, detail))
    if not cond:
        fails.append(label)


class FakeStore(object):
    def __init__(self):
        self.d = {}

    def get(self, k):
        v = self.d.get(k)
        return json.loads(json.dumps(v)) if v is not None else None

    def set(self, k, v):
        self.d[k] = json.loads(json.dumps(v))


def make_module():
    m = object.__new__(G.GiveawayModule)          # 跳过 __init__，不连 Discord
    m.store = FakeStore()
    m._feature = {
        "channel": "1567716869429796865",
        "claim_channel": "order_logs",
        "staff_contact": "1477093313265008720",
        "prizes": [
            {"key": "bag10", "type": "bag", "label": "10-Slot Bag", "chance": 2},
            {"key": "bag8", "type": "bag", "label": "8-Slot Bag", "chance": 30},
            {"key": "coupon5", "type": "coupon", "label": "5% Off", "chance": 50},
        ],
    }
    return m


def prizefn(self):
    return self._feature.get("prizes") or []


G.GiveawayModule.prizes = property(prizefn)

print("== 1. 中包 → 落待登记 ==")
m = make_module()
uid = "1037677694487384104"
p1 = m.add_pending(uid, {"key": "bag8"})
ok(bool(p1), "add_pending 返回 ref", p1)
q = m.store.get("giveaway_pending")
ok(len(q) == 1 and q[0]["status"] == "awaiting_details", "队列 1 条且待登记", str(q))
ok(q[0]["user"] == uid, "归属用户正确")

print("\n== 2. 按钮反查（不依赖消息上下文）==")
f = m.find_pending(uid)
ok(f is not None and f["id"] == p1, "find_pending 命中同一条", str(f and f["id"]))
ok(m.find_pending("999") is None, "没中过包的用户返回 None")
ok(m.prize_by_key("bag8")["label"] == "8-Slot Bag", "prize_by_key 能取回奖品")

print("\n== 3. 提交后关闭，再点不会重复登记 ==")
m.close_pending(p1)
ok(m.find_pending(uid) is None, "关闭后 find_pending 为空")
q = m.store.get("giveaway_pending")
ok(q[0]["status"] == "submitted", "状态已置 submitted", q[0]["status"])

print("\n== 4. 同一人中两次包 → 先中的先登记 ==")
a = m.add_pending(uid, {"key": "bag8"})
b = m.add_pending(uid, {"key": "bag10"})
f1 = m.find_pending(uid)
m.close_pending(f1["id"])
f2 = m.find_pending(uid)
ok(f1["id"] == a and f2["id"] == b, "按先后顺序消费", "%s -> %s" % (f1["id"], f2["id"]))
m.close_pending(f2["id"])
ok(m.find_pending(uid) is None, "两条都登记完，队列清空")

print("\n== 5. 持久化注册 & 固定 custom_id ==")
ok(G.DELIVER_CID == "wf:giveaway:deliver", "DELIVER_CID 固定", G.DELIVER_CID)
ok(G.GiveawayModule.views is not None, "views() 存在")
v_names = [type(x).__name__ for x in m.views()]
ok("DeliveryView" in v_names and "GiveawayView" in v_names,
   "两个视图都会持久化注册", str(v_names))
vd = [x for x in m.views() if type(x).__name__ == "DeliveryView"][0]
ok(vd.timeout is None, "DeliveryView.timeout=None（不会过期）")
btn = vd.children[0]
ok(btn.custom_id == G.DELIVER_CID, "按钮 custom_id 与常量一致", btn.custom_id)

print("\n== 6. 通知要 @ 到运营 ==")
src = open(os.path.join(HERE, "modules", "giveaway.py"), encoding="utf-8").read()
ok('content = "<@%s> new bag delivery request" % staff' in src,
   "订单通知带 staff mention")
ok("users.append(discord.Object(id=int(staff)))" in src,
   "allowed_mentions 放行 staff")

print("\n" + ("PENDING CHECK OK" if not fails else "PENDING CHECK FAIL: %s" % fails))
sys.exit(0 if not fails else 1)
