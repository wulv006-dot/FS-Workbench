# -*- coding: utf-8 -*-
"""只读 dump：后台「金币价格管理」的**全部行**（行ID / 标题 / 采购成本 / 利润率 / b2c）。

用途：核对「游戏内有、后台价=0」的服务区到底是哪个字段为空。
**不写任何数据**，只 goto + 读页面。

容器内运行：
  docker run --rm -v /opt/d4follow/_p2pah_srv:/srv -w /srv --shm-size=1g --memory=3g \
    p2pah-srv:1 python /srv/_gold_dump_ro.py 826
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

gid = sys.argv[1] if len(sys.argv) > 1 else "826"
out = sys.argv[2] if len(sys.argv) > 2 else "/srv/_gold_dump_%s.json" % gid

s = L.Session("/srv/_srv_profile", False)
try:
    print("logged_in:", s.logged_in())
    print("list_url:", L.gold_list_url(gid) if hasattr(L, "gold_list_url") else "?")
    rows = s.gold_rows(gid=gid)
    print("gid=%s 行数=%d" % (gid, len(rows)))
    json.dump(rows, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("saved:", out)
    zero = []
    for k, v in rows.items():
        cp = v.get("costprice")
        try:
            z = (cp is None) or (str(cp).strip() == "") or (float(cp) == 0)
        except Exception:
            z = True
        if z:
            zero.append((k, v.get("title")))
    print("采购成本为空/0 的行数 =", len(zero))
    for k, t in zero[:60]:
        print("   ZERO 行%-7s %s" % (k, t))
finally:
    try:
        s.close()
    except Exception:
        pass
