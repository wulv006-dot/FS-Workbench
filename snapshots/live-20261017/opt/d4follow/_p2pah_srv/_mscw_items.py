# -*- coding: utf-8 -*-
"""只读：拉 gid=1300 的「产品价格管理」全部页，逐条打印（服务区/产品名/每份数量/$每个价格/￥采购成本）。

目的：找出 **货币** 产品（= 前端金币商品）的 $每个价格，与金币价格管理各行 b2c 对位，
     从而定出「后台行 → 前端」的换算系数（前台系数）。
"""
import os
import re
import sys

sys.path.insert(0, "/srv")
os.environ["P2PAH_CHANNEL"] = ""

import p2pah_local as L  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

TD = re.compile(r"<td([^>]*)>(.*?)</td>", re.S)


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


def cells(body):
    out = []
    for attrs, inner in TD.findall(body):
        t = re.search(r'data-type="([^"]*)"', attrs)
        v = re.search(r"<input[^>]*value=\"([^\"]*)\"", inner)
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
        out.append((t.group(1) if t else "", (v.group(1) if v else txt)))
    return out


gid = "1300"
a = sys.argv
for i, v in enumerate(a):
    if v == "--gid":
        gid = a[i + 1]

s = L.Session("/srv/_srv_profile", False)
try:
    print("logged_in:", s.logged_in())
    seen = set()
    for page in range(1, 9):
        url = (L.BASE_URL + "/game/admin_game_price/index_item.html?gid=%s&aid=&cid=&page=%d"
               % (gid, page))
        s.pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        s.pg.wait_for_timeout(2200)
        html = re.sub(r"<!--[\s\S]*?-->", "", s.pg.content())
        rows = re.findall(r'<tr\s+data-id="(\d+)"[^>]*>(.*?)</tr>', html, re.S)
        new = 0
        for rid, body in rows:
            if rid in seen:
                continue
            seen.add(rid)
            new += 1
            c = cells(body)
            txt = " | ".join("%s=%s" % (k, v[:26]) for k, v in c)
            print("p%d %s" % (page, txt))
        tot = re.search(r"共\s*<[^>]*>(\d+)<", html)
        pg = re.findall(r"[\?&]page=(\d+)", html)
        print("  -- page %d 新增 %d 行，共见 %d 行；站点共%s 页链接%s"
              % (page, new, len(seen), (tot.group(1) if tot else "?"),
                 sorted({int(x) for x in pg})[-3:]))
        if new == 0:
            break
    print("\n总行数:", len(seen))
finally:
    try:
        s.close()
    except Exception:
        pass
