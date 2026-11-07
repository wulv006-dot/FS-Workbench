# -*- coding: utf-8 -*-
"""welcome 四级面板离线自检：逐级解锁、占位文字、汇总文案。"""
import json
import sys

sys.path.insert(0, "/opt/wowforever-bot")

import discord                                      # noqa: E402
from lib.store import Store                          # noqa: E402
from modules.welcome import WelcomeModule            # noqa: E402

cfg = json.load(open("/opt/wowforever-bot/config.json", encoding="utf-8"))
store = Store("/opt/wowforever-bot/state/_welcome_check.json")


class Stub(object):
    pass


bot = Stub()
bot.user = Stub()
bot.user.id = "1"
bot.guild = None
bot.add_exempt = lambda mid: None

m = WelcomeModule(bot, cfg, store)


def show(state, label):
    view = m.hub_view(state)
    embed = m.hub_embed(state, done=all(state.get(g) for g in
                                        ("regions", "factions", "rulesets", "classes")))
    sels = [c for c in view.children if isinstance(c, discord.ui.Select)]
    print("\n--- %s ---" % label)
    for line in (embed.description or "").split("\n"):
        print("   |", line)
    print("   下拉数量 =", len(sels))
    for s in sels:
        print("     %-14s placeholder=%r options=%d"
              % (s.custom_id, s.placeholder, len(s.options)))


show({}, "空状态（只该出现第 1 级）")
show({"regions": "en"}, "选了地区")
show({"regions": "en", "factions": "horde"}, "选了地区+阵容")
show({"regions": "en", "factions": "horde", "rulesets": "pvp"}, "三级都选了")
show({"regions": "zh", "factions": "alliance", "rulesets": "rpg", "classes": "mage"},
     "四级齐全")

# 断言
bad = []
v0 = m.hub_view({})
if len([c for c in v0.children if isinstance(c, discord.ui.Select)]) != 1:
    bad.append("空状态应只有 1 个下拉")
v1 = m.hub_view({"regions": "en"})
if len([c for c in v1.children if isinstance(c, discord.ui.Select)]) != 2:
    bad.append("选完地区应有 2 个下拉")
v4 = m.hub_view({"regions": "en", "factions": "horde", "rulesets": "pvp", "classes": "mage"})
if len([c for c in v4.children if isinstance(c, discord.ui.Select)]) != 4:
    bad.append("四级齐全应有 4 个下拉")
panel = m._panel_payload()
print("\n公共面板: title=%r 按钮/下拉=%d" % (panel.title, 0))
print("断言失败:", bad if bad else "无")
print("WELCOME CHECK " + ("OK" if not bad else "FAILED"))
