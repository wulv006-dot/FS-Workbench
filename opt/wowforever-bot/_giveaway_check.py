# -*- coding: utf-8 -*-
"""抽奖模块离线自检：面板结构、中奖卡、发码、登记落库（不发网络请求）。"""
import json
import sys
from collections import Counter

sys.path.insert(0, "/opt/wowforever-bot")

from lib.store import Store                        # noqa: E402
from modules.giveaway import (GiveawayModule, gen_code,  # noqa: E402
                              weighted_pick)

cfg = json.load(open("/opt/wowforever-bot/config.json", encoding="utf-8"))
store = Store("/opt/wowforever-bot/state/_giveaway_check.json")


class Stub(object):
    pass


bot = Stub()
bot.user = Stub()
bot.user.id = "1"
bot.guild = None
bot.add_exempt = lambda mid: None

m = GiveawayModule(bot, cfg, store)
print("模块 enabled =", m.enabled, "| 冷却小时 =", m.cooldown_hours)
print("bypass 名单 =", m.feature.get("bypass_users"))
print("老板号 bypass =", m.bypass("1037677694487384104"),
      "| 路人 bypass =", m.bypass("999999999"))
print("商店链接 =", m.shop("url"), "|", m.shop("label"))

embeds = m.panel_payload()
print("\n=== 面板 %d 个 embed ===" % len(embeds))
for e in embeds:
    print("  title:", e.title)
    for line in (e.description or "").split("\n"):
        print("    |", line if line.strip() else "(空行)")
    print("  footer:", e.footer.text if e.footer else None)
    print()

prizes = m.prizes
cnt = Counter()
for _ in range(100000):
    cnt[weighted_pick(prizes)["key"]] += 1
print("=== 10 万次分布 ===")
for p in prizes:
    print("  %-9s 配置 %4.0f%%  实际 %5.2f%%" % (p["key"], p["chance"],
                                                cnt[p["key"]] * 100.0 / 100000))

print("\n=== 背包中奖卡 ===")
bag = next(p for p in prizes if p["type"] == "bag")
be = m.bag_win_embed(bag)
print("  title:", be.title)
for line in (be.description or "").split("\n"):
    print("    |", line)
print("  fields:", [(f.name, f.value) for f in be.fields])

print("\n=== 券中奖卡 ===")
cp = next(p for p in prizes if p["type"] == "coupon")
code = gen_code(cp["key"])
ce = m.coupon_win_embed(cp, code)
print("  title:", ce.title)
for line in (ce.description or "").split("\n"):
    print("    |", line)
print("  fields:", [(f.name, f.value.replace("\n", "\\n")) for f in ce.fields])
print("  样例码:", code, "| 另一枚:", gen_code(cp["key"]))

print("\n=== 登记落库（不联网）===")
m.add_claim({"user": "123", "name": "tester", "prize": "bag8", "label": "8-Slot Bag",
             "server": "US", "realm": "Normal - Alliance", "char": "Arthas",
             "ts": 0, "status": "pending"})
claims = store.get("giveaway_claims") or []
print("  claims 条数 =", len(claims), "| 最后一条 =", claims[-1]["char"])

print("\n=== 码表落库 ===")
m.record_win("123", cp, code)
codes = store.get("giveaway_codes") or {}
print("  code 记录 =", codes.get(code))
print("\nGIVEAWAY CHECK OK")
