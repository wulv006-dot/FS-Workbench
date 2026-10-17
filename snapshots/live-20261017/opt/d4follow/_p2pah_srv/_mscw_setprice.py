# -*- coding: utf-8 -*-
"""MSCW 金币：把行 21754 的采购成本从占位值 40 改为**按口径算出的目标值**，并推送前端。

口径（用户 2026-10-08 定案）：
    目标前端每K价 = IGGM真价($/K) × (1 − 让价10%)
    兜底          = DD373 成本($/M) × (1 + 15%) ÷ 1000   （仅当目标低于兜底时抬到兜底）
    采购成本      = 目标前端每K价 × 汇率6.65 × (1 − 利润率0.30)
                  = 目标前端每K价 × 4.655

本次数值：
    IGGM Windia = 0.49900000 $/K   （机房里抓 = 本机抓，无机房加价 ⇒ 折算系数 1.0）
    目标 = 0.499 × 0.90 = 0.44910 $/K  ⇒ 采购成本 = 0.44910 × 4.655 = 2.090561
    （DD373 兜底 = $270.67/M × 1.15 = $311.27/M = $0.31127/K < 0.44910 ⇒ 不触发）

只改 gid=1300 行 21754 的「采购成本」一个字段。
"""
import io
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
OLD = "40.000000"
NEW = 2.090561


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
        print("⚠ 改前值与预期不符（预期 %s），继续但请核对" % OLD)
    print(">>> 写 采购成本 = %.6f" % NEW)
    print("   写回执:", s.set_gold_cost(ROW, "%.6f" % NEW))
    time.sleep(1.5)
    r1 = s.gold_rows(gid=GID)
    print("[读回] 行%s = %s" % (ROW, json.dumps(r1.get(ROW), ensure_ascii=False)))
    sy = s.sync_gold_price(wait_ms=10000, gid=GID)
    print("[推送] ", {k: sy.get(k) for k in ("ok", "getweb", "allserver", "msg")})
    # 立刻用「产品价格管理」的 $每个价格 验证（它是同步后立刻变的，比前端即时）
    time.sleep(2)
    s.pg.goto(L.BASE_URL + "/game/admin_game_price/index_item.html?gid=%s&aid=&cid=" % GID,
              wait_until="domcontentloaded", timeout=60000)
    s.pg.wait_for_timeout(2500)
    html = re.sub(r"<!--[\s\S]*?-->", "", s.pg.content())
    print("[产品价格管理] 货币行：")
    for rid, body in re.findall(r'<tr\s+data-id="(\d+)"[^>]*>(.*?)</tr>', html, re.S):
        cells = []
        for attrs, inner in re.findall(r"<td([^>]*)>(.*?)</td>", body, re.S):
            t = re.search(r'data-type="([^"]*)"', attrs)
            v = re.search(r'<input[^>]*value="([^"]*)"', inner)
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
            cells.append((t.group(1) if t else "", (v.group(1) if v else txt)))
        if len(cells) > 4 and "货币" in cells[3][1]:
            print("   ", rid, "服务区=%s" % cells[2][1],
                  "每份数量=%s" % cells[5][1], "$每个价格=%s" % cells[9][1],
                  "销售价=%s" % cells[10][1])
finally:
    try:
        s.close()
    except Exception:
        pass
