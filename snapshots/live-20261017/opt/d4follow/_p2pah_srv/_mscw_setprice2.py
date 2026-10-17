# -*- coding: utf-8 -*-
"""MSCW 行 21754：把采购成本改成**按实证定律校正后**的目标值，并推送前端。

口径（2026-10-08 定案 · 实证校正后）：
    目标前台售价 = IGGM 真价 $0.499/K × (1 − 让价 10%) = $0.449100/K
    前台售价 = b2c × (对标档位 500K 的 discount 95 / 100)
    ⇒ 采购成本 = 目标 × 汇率 6.65 × (1 − 利润率 0.30) ÷ 0.95
               = 目标 × 4.90 = 0.449100 × 4.90 = **2.200590**
    15% 利润兜底线 = DD373成本 $0.268369/K ÷ 0.85 = $0.315729/K ＜ 0.4491 ⇒ 不触发

对照：上一版（2026-10-08 20:58）写的是 2.090561（漏算 discount ⇒ 实收价低 5%，
      前台实测 0.42664 = 0.4491×0.95，正好印证）。

只改 gid=1300 行 21754 的「采购成本」一个字段；永不勾 allserver。
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, "/srv")
os.environ["P2PAH_CHANNEL"] = ""

import p2pah_local as L  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

GID = "1300"
ROW = "21754"
OLD = "2.090561"
NEW = 2.200590


def _init(self, profile, keep_open=False):
    self._p = sync_playwright().start()
    self.ctx = self._p.chromium.launch_persistent_context(
        profile, channel=None, headless=not keep_open,
        viewport={"width": 1400, "height": 950},
        args=["--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu", "--no-zygote"])
    self.pg = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
    self._inject_saved_cookies()
    self.auto_login = bool(L.AUTO_LOGIN[0]) and (L.autologin is not None)
    try:
        _a = L.autologin.accounts()["order"]
        self.user = _a.get("username") or ""
        self.pw = _a.get("password") or ""
    except Exception:
        self.user = self.pw = ""


L.Session.__init__ = _init
L.AUTO_LOGIN[0] = True

s = L.Session("/srv/_srv_profile", False)
try:
    print("logged_in:", s.logged_in())
    r0 = s.gold_rows(gid=GID)
    print("[改前] 行%s = %s" % (ROW, json.dumps(r0.get(ROW), ensure_ascii=False)))
    if (r0.get(ROW) or {}).get("costprice") not in (OLD, "%.6f" % NEW):
        print("⚠ 改前值与预期(%s)不符，继续但请核对" % OLD)
    print(">>> 写 采购成本 = %.6f" % NEW)
    print("   写回执:", s.set_gold_cost(ROW, "%.6f" % NEW))
    time.sleep(1.5)
    r1 = s.gold_rows(gid=GID)
    print("[读回] 行%s = %s" % (ROW, json.dumps(r1.get(ROW), ensure_ascii=False)))
    sy = s.sync_gold_price(wait_ms=10000, gid=GID)
    print("[推送] ", {k: sy.get(k) for k in ("ok", "getweb", "allserver", "msg")})
    time.sleep(2)
    s.pg.goto(L.BASE_URL + "/game/admin_game_price/index_item.html?gid=%s&aid=&cid=" % GID,
              wait_until="domcontentloaded", timeout=60000)
    s.pg.wait_for_timeout(2500)
    html = re.sub(r"<!--[\s\S]*?-->", "", s.pg.content())
    print("[产品价格管理] 货币行（标价列；客户实付还要 ×discount/100）：")
    for rid, body in re.findall(r'<tr\s+data-id="(\d+)"[^>]*>(.*?)</tr>', html, re.S):
        cells = []
        for attrs, inner in re.findall(r"<td([^>]*)>(.*?)</td>", body, re.S):
            t = re.search(r'data-type="([^"]*)"', attrs)
            v = re.search(r'<input[^>]*value="([^"]*)"', inner)
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
            cells.append((t.group(1) if t else "", (v.group(1) if v else txt)))
        if len(cells) > 4 and "货币" in cells[3][1]:
            print("   ", rid, "服务区=%s" % cells[2][1], "$每个价格=%s" % cells[9][1])
finally:
    try:
        s.close()
    except Exception:
        pass
