# -*- coding: utf-8 -*-
"""只读探针：对比 gid=1300 / gid=826 的「更新b2c网站」推送请求，定位站点选择差异。

不修改任何价格（值本来就不变，只是重复提交一次 = 引擎每轮都在做的动作）。
"""
import os
import re
import sys
import time
import urllib.parse

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

gids = ["1300", "826"]
a = sys.argv
for i, v in enumerate(a):
    if v == "--gids":
        gids = a[i + 1].split(",")

s = L.Session("/srv/_srv_profile", False)
try:
    print("logged_in:", s.logged_in())
    for gid in gids:
        print("\n" + "=" * 26, "gid =", gid)
        s.pg.goto(L.BASE_URL + L.gold_list_url(gid), wait_until="domcontentloaded", timeout=60000)
        s.pg.wait_for_timeout(2500)

        info = s.pg.evaluate("""() => {
            const out = {};
            document.querySelectorAll('input[type=hidden]').forEach(el => {
                out[(el.name||'(noname)')] = el.value;
            });
            const sel = document.querySelector('#b2c-website');
            out['__website_selected'] = sel ? Array.from(sel.selectedOptions||[]).map(o=>o.value) : null;
            const lab = document.querySelector('.fs-label');
            out['__fs_label'] = lab ? lab.innerText.trim() : null;
            out['__web_checks'] = Array.from(document.querySelectorAll('input[name="web[]"]')).map(
                e => [e.value, e.checked]);
            out['__allserver'] = Array.from(document.querySelectorAll('input[name=allserver]')).map(e => e.checked);
            out['__getweb_btn'] = !!document.querySelector('.jq-getweb');
            out['__update_btn'] = !!document.querySelector('.jq-update-button');
            return out;
        }""")
        for k in sorted(info):
            print("   %-22s = %r" % (k, info[k]))

        box = {"url": None, "body": None, "post": None}

        def _on_req(r):
            if "saveprice" in r.url:
                box["url"] = r.url
                try:
                    box["post"] = r.post_data
                except Exception:
                    pass
                try:
                    box["body"] = r.text()[:300]
                except Exception:
                    pass

        s.pg.on("request", _on_req)
        try:
            if s.pg.query_selector(".jq-getweb"):
                s.pg.click(".jq-getweb")
            s.pg.wait_for_timeout(9000)
        finally:
            try:
                s.pg.remove_listener("request", _on_req)
            except Exception:
                pass
        print("   saveprice url :", box["url"])
        print("   saveprice POST:", box["post"])
        print("   saveprice resp:", box["body"])
        if box["url"]:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(box["url"]).query)
            print("   query keys    :", {k: v[:3] for k, v in q.items()})
finally:
    try:
        s.close()
    except Exception:
        pass
