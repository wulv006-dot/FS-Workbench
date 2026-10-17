# -*- coding: utf-8 -*-
"""只读：读 gid=1300 金币价格管理全部行的 采购成本 / b2c，以及前台现行每K价。
   不写任何东西。

容器内运行：
  docker run --rm -v /opt/d4follow/_p2pah_srv:/srv -w /srv --shm-size=1g --memory=3g \
    p2pah-srv:1 python /srv/_mscw_readonly.py
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
    rows = s.gold_rows(gid=GID)
    print("=== gid=%s 金币价格管理 全部行 ===" % GID)
    for rid, r in sorted(rows.items(), key=lambda kv: int(kv[0])):
        print("  行%-7s 服务区=%-28s 采购成本=%-14s 利润率=%-6s b2c=%s" % (
            rid, str(r.get("name") or r.get("server") or "")[:28],
            r.get("costprice"), r.get("profit") or r.get("profitrate"),
            r.get("b2c")))
    print()
    t = rows.get("21754") or {}
    print("重点行 21754：", json.dumps(t, ensure_ascii=False))
finally:
    try:
        s.close()
    except Exception:
        pass
