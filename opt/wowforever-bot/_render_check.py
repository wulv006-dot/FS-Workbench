# -*- coding: utf-8 -*-
"""离线渲染校验：直接把卡片 payload 打出来，确认①没有竞品价 ②有跳转。"""
import json
import sys

sys.path.insert(0, "/opt/wowforever-bot")

from lib.store import Store                      # noqa: E402
from modules.priceboard import PriceBoardModule   # noqa: E402

cfg = json.load(open("/opt/wowforever-bot/config.json", encoding="utf-8"))
store = Store("/opt/wowforever-bot/state/_render_check.json")


class Stub(object):
    pass


bot = Stub()
bot.user = Stub()
bot.user.id = "1"
bot.guild = None

m = PriceBoardModule(bot, cfg, store)
m._load_cache()
print("缓存行数 =", len(m.rows), "| fetched_at =", m.fetched_at)
print("大区 =", m.regions())

embed, regions = None, None
embed, regions = m.board_payload()
print("\n=== BOARD ===")
print("title :", embed.title)
print("url   :", getattr(embed, "url", None))
print("desc  :\n" + "\n".join("  " + l for l in (embed.description or "").split("\n")))
for f in embed.fields:
    print("field :", f.name, "=>", (f.value or "").replace("\n", " / ")[:100])

region = m.regions()[0]
tkey = m.types_in(region)[0]
pe = m.panel_embed(region, tkey)
blob = json.dumps({
    "title": pe.title, "url": getattr(pe, "url", None), "description": pe.description,
    "fields": [{"name": f.name, "value": f.value} for f in pe.fields],
    "footer": pe.footer.text,
}, ensure_ascii=False, indent=1)
print("\n=== PANEL CARD (%s · %s) ===" % (region, tkey))
print(blob)

pv = m.panel_view(region, tkey)
print("\n=== PANEL COMPONENTS ===")
for item in pv.children:
    if isinstance(item, __import__("discord").ui.Select):
        print("  select %-14s options=%s" % (item.custom_id, [o.label for o in item.options]))
    else:
        print("  button label=%r url=%r style=%s" % (item.label, item.url, item.style))

bv = m.board_view(regions)
print("\n=== BOARD COMPONENTS ===")
for item in bv.children:
    if isinstance(item, __import__("discord").ui.Select):
        print("  select %-14s options=%s" % (item.custom_id, [o.label for o in item.options]))
    else:
        print("  button label=%r url=%r style=%s" % (item.label, item.url, item.style))

# 断言
bad = []
flat = blob + json.dumps([f.name for f in embed.fields] + [embed.description or ""],
                         ensure_ascii=False)
for kw in ("G2G", "g2g", "Eldorado", "eldorado", "cheaper"):
    if kw in flat:
        bad.append(kw)
if "wow-gold.html" not in blob:
    bad.append("缺跳转链接")
print("\n断言失败项:", bad if bad else "无")
print("CARD CHECK " + ("OK" if not bad else "FAILED"))
