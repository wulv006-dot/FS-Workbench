# -*- coding: utf-8 -*-
"""只读：把金币价格管理页 HTML（含内联 JS）落地成文件，供离线分析前台换算公式。"""
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

gid = "1300"
out = "/srv/_mscw_gold.html"
a = sys.argv
for i, v in enumerate(a):
    if v == "--gid":
        gid = a[i + 1]
    elif v == "--out":
        out = a[i + 1]

s = L.Session("/srv/_srv_profile", False)
try:
    print("logged_in:", s.logged_in())
    s.pg.goto(L.BASE_URL + L.gold_list_url(gid), wait_until="domcontentloaded", timeout=60000)
    s.pg.wait_for_timeout(3000)
    html = s.pg.content()
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("saved:", out, len(html))
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
    print("scripts:", srcs)
finally:
    try:
        s.close()
    except Exception:
        pass
