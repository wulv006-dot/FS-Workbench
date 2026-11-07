# -*- coding: utf-8 -*-
"""离线验证抽奖新规则：次数上限 / 库存 / 固定折扣码 / 库存耗尽降级。
走真实方法，只在内存里假 store，不发网络请求。"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import modules.giveaway as G  # noqa: E402

fails = []
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3000-\u303f\uff01-\uff60]")


def ok(cond, label, detail=""):
    print("  [%s] %-44s %s" % ("OK  " if cond else "FAIL", label, detail))
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


PRIZES = [
    {"key": "bag10", "type": "bag", "label": "10-Slot Bag", "emoji": "🎒",
     "chance": 2, "stock": 10, "color": "#7F77DD"},
    {"key": "bag8", "type": "bag", "label": "8-Slot Bag", "emoji": "🎒",
     "chance": 30, "stock": 50, "color": "#378ADD"},
    {"key": "coupon5", "type": "coupon", "label": "5% Off Coupon", "emoji": "🎟️",
     "chance": 50, "code": "wowexp", "color": "#97C459"},
    {"key": "coupon8", "type": "coupon", "label": "8% Off Coupon", "emoji": "🎟️",
     "chance": 18, "code": "wowexp8", "color": "#EF9F27"},
]


def make(prizes=None, cap=2):
    m = object.__new__(G.GiveawayModule)
    m.store = FakeStore()
    m._feature = {
        "channel": "1567716869429796865", "claim_channel": "order_logs",
        "staff_contact": "1477093313265008720",
        "spins_per_user": cap, "fallback_prize": "coupon5",
        "panel_title": "WOW FOREVER · Lucky Loot",
        "bypass_users": ["1037677694487384104"],
        "prizes": prizes if prizes is not None else PRIZES,
    }
    return m


G.GiveawayModule.prizes = property(lambda self: self._feature.get("prizes") or [])
G.GiveawayModule.feature = property(lambda self: self._feature)

print("== 1. 每次抽奖次数上限 ==")
m = make()
U = "555"
ok(m.spins_allowed() == 2, "spins_allowed = 2")
ok(m.spins_left(U) == 2, "初始剩 2 次")
m.mark_spin(U)
ok(m.spins_left(U) == 1, "抽 1 次后剩 1 次")
m.mark_spin(U)
ok(m.spins_left(U) == 0, "抽 2 次后剩 0 次")
ok(m.spins_used(U) == 2, "spins_used 记账正确")
ok(m.spins_left("1037677694487384104") == -1, "白名单用户不受限（-1）")
m2 = make(cap=0)
ok(m2.spins_left(U) == -1, "cap=0 时全员不限次")

print("\n== 2. 库存（10格10个 / 8格50个）==")
m = make()
ok(m.stock_left("bag10") == 10, "10 格包初始 10")
ok(m.stock_left("bag8") == 50, "8 格包初始 50")
ok(m.stock_left("coupon5") is None, "券没有库存概念（None）")
paid = 0
for _ in range(60):
    if m.take_stock("bag8"):
        paid += 1
ok(paid == 50, "8 格包正好发出 50 个", "发出 %d" % paid)
ok(m.stock_left("bag8") == 0, "发完剩 0")
ok(m.take_stock("bag8") is False, "再扣返回 False")
ok(m.store.get("giveaway_stock") == {"bag8": 0}, "库存已落盘",
   str(m.store.get("giveaway_stock")))

print("\n== 3. 库存耗尽 → 降级成 5% 券 ==")
em = make(prizes=[
    {"key": "bag8", "type": "bag", "label": "8-Slot Bag", "chance": 100,
     "stock": 1, "color": "#378ADD"},
    {"key": "coupon5", "type": "coupon", "label": "5% Off Coupon", "chance": 0,
     "code": "wowexp", "color": "#97C459"},
])
first = em.draw()
ok(first and first["key"] == "bag8", "第 1 抽拿到 bag8", first and first["key"])
second = em.draw()
ok(second and second["key"] == "coupon5", "第 2 抽自动降级成 coupon5",
   second and second["key"])

print("\n== 4. 固定折扣码 ==")
m = make()
c5 = m.prize_by_key("coupon5")
c10 = m.prize_by_key("coupon8")
ok(c5.get("code") == "wowexp", "5% 券码 = wowexp")
ok(c10.get("code") == "wowexp8", "8% 券码 = wowexp8")
ok(c10["key"] == "coupon8" and "8%" in c10["label"], "券档位为 8%")
m.record_win("777", c5, "wowexp")
m.record_win("888", c5, "wowexp")
logs = m.store.get("giveaway_coupon_log") or []
ok(len(logs) == 2, "固定码按流水累积，不互相覆盖", "%d 条" % len(logs))
ok(m.store.get("giveaway_codes") in (None, {}), "固定码不写进唯一码表")
gen = m.prize_by_key("coupon8")
m.record_win("999", {"key": "couponX", "label": "tmp"}, G.gen_code("coupon8"))
codes = m.store.get("giveaway_codes") or {}
ok(len(codes) == 1 and list(codes)[0].startswith("WOWF-8P-"),
   "无 code 配置时仍生成唯一码", str(list(codes))[:40])

print("\n== 5. 面板文案（英文魔兽风 + 库存 + 次数）==")
m = make()
embeds = m.panel_payload()
main = embeds[0]
blob = json.dumps([e.to_dict() for e in embeds], ensure_ascii=False)
ok("Lucky Loot" in (main.title or ""), "标题 = Lucky Loot", main.title)
ok("Blingtron" in main.description, "保留工程机器人风格")
ok("2 free spins" in main.description, "文案写明 2 次机会")
ok(len(embeds) == 1, "1 张卡片按奖品类型分组", "%d 张" % len(embeds))
ok(not any((e.title or "") == "How it works" for e in embeds), "已删掉 How it works 说明块")
ok("10 / 10 left" in blob and "50 / 50 left" in blob,
   "库存按「剩余/总数 left」显示")
ok("🟢" in blob, "库存带颜色标记（满库存=绿）")
ok("### 🎒 Bags" in blob and "### 🎟️ Coupons" in blob, "背包/券各有分组标题")

print("\n== 5b. 库存颜色随余量变化 ==")
mm = make()
p10 = mm.prize_by_key("bag10")
ok("🟢" in mm.stock_line(p10, 10), "10/10 → 绿")
ok("🟡" in mm.stock_line(p10, 4), "4/10 → 黄")
ok("🔴" in mm.stock_line(p10, 1), "1/10 → 红")
ok("sold out" in mm.stock_line(p10, 0), "0 → sold out")
ok("unlimited" in mm.stock_line(mm.prize_by_key("coupon5"), None), "券 → unlimited")
ok(not CJK.search(blob), "面板无中文字符",
   "命中: %s" % "".join(sorted(set(CJK.findall(blob))))[:20])

print("\n== 6. 概率合计 ==")
tot = sum(float(p["chance"]) for p in PRIZES)
ok(abs(tot - 100) < 0.01, "概率合计 100%", "%.0f%%" % tot)

print("\n" + ("RULES CHECK OK" if not fails else "RULES CHECK FAIL: %s" % fails))
sys.exit(0 if not fails else 1)
