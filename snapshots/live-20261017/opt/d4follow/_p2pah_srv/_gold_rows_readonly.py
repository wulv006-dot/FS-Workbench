# -*- coding: utf-8 -*-
"""只读：读指定 gid 的金币行（采购成本/利润率/b2c），用来与前台售价对照，
   反推「前台系数」的确切定义。不写任何东西。

容器内运行：
  docker run --rm -v /opt/d4follow/_p2pah_srv:/srv -w /srv --shm-size=1g --memory=3g \
    p2pah-srv:1 python /srv/_gold_rows_readonly.py 456 826 1300
"""
import json
import os
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

gids = [a for a in sys.argv[1:] if a.isdigit()] or ["1300"]
s = L.Session("/srv/_srv_profile", False)
try:
    print("logged_in:", s.logged_in())
    for gid in gids:
        rows = s.gold_rows(gid=gid)
        print("\n=== gid=%s 共 %d 行 ===" % (gid, len(rows)))
        for rid, r in sorted(rows.items(), key=lambda kv: int(kv[0]))[:12]:
            print("  行%-7s %-26s 采购成本=%-14s 利润率=%-10s b2c=%s" % (
                rid, str(r.get("title") or "")[:26], r.get("costprice"),
                r.get("lirunlv"), r.get("b2c")))
finally:
    try:
        s.close()
    except Exception:
        pass
