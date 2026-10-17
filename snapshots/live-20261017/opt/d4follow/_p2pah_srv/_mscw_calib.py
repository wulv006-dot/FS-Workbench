# -*- coding: utf-8 -*-
"""前台系数实测（一次性、可回滚）：写已知采购成本 → 推送前端 → 读前台账位 → 还原。

- 只动 gid=1300 的行 21754（Global World）的「采购成本」一个字段；
- 测试值 4655.0 ⇒ b2c = 4655/6.65/0.7 = 1000.0（无论前台系数多大，前端价都只会**变高**，
  不会出现「低于成本被薅」的风险）；
- 测完立刻还原成 40.000000 并再次推送。

容器内运行：
  docker run --rm -v /opt/d4follow/_p2pah_srv:/srv -w /srv --shm-size=1g --memory=3g \
    p2pah-srv:1 python /srv/_mscw_calib.py
"""
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, "/srv")
os.environ["P2PAH_CHANNEL"] = ""

import p2pah_local as L  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

GID = "1300"
ROW = "21754"
ORIG = 40.000000
TEST = 4655.0
AID = "21627"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


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


def front_price():
    body = urllib.parse.urlencode({"Game_id": "1333", "top_cid": "1", "aid": AID,
                                   "cid": "9661", "site_id": "266"}).encode()
    req = urllib.request.Request(
        "https://www.mmoexp.com/ajax/goods", data=body,
        headers={"User-Agent": UA,
                 "Referer": "https://www.mmoexp.com/Maplestory-classic-world/Mesos.html",
                 "X-Requested-With": "XMLHttpRequest",
                 "Content-Type": "application/x-www-form-urlencoded"})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace"))
    it = (((d.get("goods") or {}).get("index") or {}).get("list") or [{}])[0]
    gl = it.get("goods_list") or {}
    tiers = sorted((int(v.get("num") or k), v.get("price_discount")) for k, v in gl.items())
    return it.get("unit_price"), it.get("unit"), tiers[:3]


s = L.Session("/srv/_srv_profile", False)
try:
    print("logged_in:", s.logged_in())
    r0 = s.gold_rows(gid=GID)
    print("[before] 21754 =", json.dumps(r0.get(ROW), ensure_ascii=False))
    print("[front before]", front_price())

    print("\n>>> 写 采购成本 = %.6f" % TEST)
    res = s.set_gold_cost(ROW, "%.6f" % TEST)
    print("  写回执:", res)
    time.sleep(1.5)
    r1 = s.gold_rows(gid=GID)
    print("  读回 21754 =", json.dumps(r1.get(ROW), ensure_ascii=False))

    sy = s.sync_gold_price(wait_ms=10000, gid=GID)
    print("  推送前端:", {k: sy.get(k) for k in ("ok", "getweb", "allserver", "msg")})

    print("\n>>> 轮询前端（最多 6 次 × 6s）")
    seen = None
    for i in range(6):
        time.sleep(6)
        try:
            up, un, t = front_price()
            print("  [%d] unit_price=%s unit=%s tiers=%s" % (i + 1, up, un, t))
            seen = (up, un, t)
            break
        except Exception as e:
            print("  [%d] ERR %r" % (i + 1, e))

    print("\n>>> 还原 采购成本 = %.6f" % ORIG)
    res2 = s.set_gold_cost(ROW, "%.6f" % ORIG)
    print("  写回执:", res2)
    time.sleep(1.5)
    r2 = s.gold_rows(gid=GID)
    print("  读回 21754 =", json.dumps(r2.get(ROW), ensure_ascii=False))
    sy2 = s.sync_gold_price(wait_ms=10000, gid=GID)
    print("  推送前端:", {k: sy2.get(k) for k in ("ok", "getweb", "allserver", "msg")})
    time.sleep(8)
    print("[front after-restore]", front_price())
    r3 = s.gold_rows(gid=GID)
    print("[after] 21754 =", json.dumps(r3.get(ROW), ensure_ascii=False))
finally:
    try:
        s.close()
    except Exception:
        pass
