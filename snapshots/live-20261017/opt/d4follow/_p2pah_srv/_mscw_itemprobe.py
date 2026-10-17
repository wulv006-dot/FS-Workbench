# -*- coding: utf-8 -*-
"""只读探针：读「产品价格管理」页（index_item），看 $每个价格 是否 == 某行 b2c。

按分册 08·17.2：产品价格管理 $每个价格 = round(b2c, 5) ← 该产品所属行的采购成本派生。
⇒ 若 21627 的 $每个价格 == 8.59291（行21754 的 b2c），则证明 ROW→产品→前端 链路存在、
   且前台系数 = 1（前端只是缓存未清）；若它 == 0.499，说明价格另有所源。

同时读 AION2 的 aid=22043 作对照（期望 == 0.682798 = 行22288 的 b2c）。
"""
import os
import re
import sys

sys.path.insert(0, "/srv")
os.environ["P2PAH_CHANNEL"] = ""

import p2pah_local as L  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


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

CASES = [
    ("MSCW/21627", "1300", "21627", "9661"),
    ("AION2/22043", "826", "22043", "6527"),
    ("裸页 MSCW", "1300", "", ""),
]

s = L.Session("/srv/_srv_profile", False)
try:
    print("logged_in:", s.logged_in())
    for label, gid, aid, cid in CASES:
        url = (L.BASE_URL + "/game/admin_game_price/index_item.html?gid=%s&aid=%s&cid=%s"
               % (gid, aid, cid))
        print("\n" + "=" * 24, label, url)
        try:
            s.pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            s.pg.wait_for_timeout(2500)
            html = re.sub(r"<!--[\s\S]*?-->", "", s.pg.content())
            print("  len:", len(html), "| title:", s.pg.title())
            print("  th:", [re.sub(r"\s+", " ", t).strip()
                           for t in re.findall(r"<th[^>]*>(.*?)</th>", html, re.S)][:14])
            rows = re.findall(r'<tr\s+data-id="(\d+)"[^>]*>(.*?)</tr>', html, re.S)
            print("  tr 数:", len(rows))
            for rid, body in rows[:6]:
                tds = re.findall(r"<td([^>]*)>(.*?)</td>", body, re.S)
                cells = []
                for attrs, inner in tds:
                    t = re.search(r'data-type="([^"]*)"', attrs)
                    v = re.search(r'<input[^>]*value="([^"]*)"', inner)
                    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
                    cells.append("%s=%s" % (t.group(1) if t else "-",
                                            (v.group(1) if v else txt)[:22]))
                print("   ", rid, "|", " | ".join(cells[:9]))
            for kw in ("unit_price", "cprice", "每个价格", "采购成本"):
                n = html.count(kw)
                if n:
                    print("   kw %-12s x%d" % (kw, n))
        except Exception as e:
            print("  ERR:", repr(e))
finally:
    try:
        s.close()
    except Exception:
        pass
