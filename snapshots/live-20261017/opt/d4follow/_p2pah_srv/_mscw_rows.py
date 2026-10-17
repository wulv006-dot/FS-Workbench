# -*- coding: utf-8 -*-
"""只读探针：dump 金币价格管理列表的表头 + 指定行原始 HTML（看单位列）。"""
import io
import json
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
want = set(("21754", "21746", "22434"))
args = sys.argv
for i, v in enumerate(args):
    if v == "--gid":
        gid = args[i + 1]
    elif v == "--rows":
        want = set(args[i + 1].split(","))

s = L.Session("/srv/_srv_profile", False)
try:
    print("logged_in:", s.logged_in())
    url = L.BASE_URL + L.gold_list_url(gid)
    s.pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    s.pg.wait_for_timeout(2500)
    html = re.sub(r"<!--[\s\S]*?-->", "", s.pg.content())
    print("=== TH 表头 ===")
    print([re.sub(r"\s+", " ", t).strip() for t in re.findall(r"<th[^>]*>(.*?)</th>", html, re.S)])
    for rid in sorted(want):
        m = re.search(r'<tr\s+data-id="%s"[^>]*>(.*?)</tr>' % rid, html, re.S)
        print("\n=== TR %s ===" % rid)
        if not m:
            print("  (未找到)")
            continue
        body = re.sub(r"\s+", " ", m.group(1))
        print(body[:2500])
        print("\n  -- td data-type 汇总 --")
        for i, (attrs, inner) in enumerate(re.findall(r"<td([^>]*)>(.*?)</td>", m.group(1), re.S)):
            t = re.search(r'data-type="([^"]*)"', attrs)
            v = re.search(r'<input[^>]*value="([^"]*)"', inner)
            print("   td%-2d type=%-16s value=%r  raw=%s" % (
                i, t.group(1) if t else "-", v.group(1) if v else None,
                re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()[:80]))
finally:
    try:
        s.close()
    except Exception:
        pass
