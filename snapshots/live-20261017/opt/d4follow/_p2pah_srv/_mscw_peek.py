# -*- coding: utf-8 -*-
"""只读探针：读 gid=<--gid> 金币价格管理列表，打印每行的采购成本/利润率/b2c。

容器内运行（把 Session 的浏览器通道从 msedge 换成自带 chromium，其余逻辑不动）：
  cd /opt/d4follow/_p2pah_srv && docker run --rm \
    -v /opt/d4follow/_p2pah_srv:/srv -w /srv --shm-size=1g --memory=3g \
    p2pah-srv:1 python /srv/_mscw_peek.py --gid 1300

只读，不发任何写请求。
"""
import io
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
    # 会话过期兜底所需的账号密码
    self.auto_login = bool(L.AUTO_LOGIN[0]) and (L.autologin is not None)
    try:
        _a = L.autologin.accounts()["order"]
        self.user = _a.get("username") or ""
        self.pw = _a.get("password") or ""
    except Exception:
        self.user = self.pw = ""
    try:
        self._prep_login_helpers()
    except Exception:
        pass


L.Session.__init__ = _init
L.AUTO_LOGIN[0] = True

gid = "1300"
argv = sys.argv
for i, v in enumerate(argv):
    if v == "--gid":
        gid = argv[i + 1]

cfg = {}
try:
    cfg = json.load(io.open("/srv/_cfg/config.json", encoding="utf-8"))
except Exception as e:
    print("cfg load fail:", e)

s = L.Session("/srv/_srv_profile", False)
try:
    print("logged_in:", s.logged_in())
    print("url:", L.BASE_URL + L.gold_list_url(gid))
    print("title:", s.pg.title())
    rows = s.gold_rows(gid=gid)
    print("rows:", len(rows))
    for rid in sorted(rows, key=lambda x: int(x)):
        print(rid, json.dumps(rows[rid], ensure_ascii=False))
finally:
    try:
        s.close()
    except Exception:
        pass
