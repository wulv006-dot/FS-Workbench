# -*- coding: utf-8 -*-
"""容器内只读 dump：复用 p2pah_local 内部函数，仅把浏览器通道从 msedge 换成自带 chromium。

用法（宿主机）：
  docker run --rm --network host --shm-size=1g --memory=3g -e P2PAH_CHANNEL= \
    -v /opt/d4follow:/srv -w /srv p2pah-srv:1 \
    python /srv/_p2pah_srv/_dump_readonly.py --gid 456 --aid 15711 --dump /srv/_p2pah_srv/_x.json

只读，不改任何线上数据。
"""
import sys
import os

sys.path.insert(0, "/srv/_p2pah_srv")
os.environ["P2PAH_CHANNEL"] = ""

import p2pah_local as L  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def _init(self, profile, keep_open=False):
    self._p = sync_playwright().start()
    self.ctx = self._p.chromium.launch_persistent_context(
        profile, channel=None, headless=not keep_open,
        viewport={"width": 1400, "height": 950})
    self.pg = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
    self._inject_saved_cookies()
    self.auto_login = bool(L.AUTO_LOGIN[0]) and (L.autologin is not None)
    try:
        self._prep_login_helpers()
    except Exception:
        pass


L.Session.__init__ = _init


class A(object):
    pass


a = A()
a.cmd = "readgame"
a.profile = "/srv/_p2pah_srv/_srv_profile"
a.config = "/srv/config.json"
a.show = False
a.wait = 2500
a.no_auto_login = False
a.username = None
a.password = None
a.aid = ""
a.keyword = ""
a.dump = ""
a.gid = "456"
a.all_pages = True

argv = sys.argv
for i, v in enumerate(argv):
    if v == "--gid":
        a.gid = argv[i + 1]
    elif v == "--keyword":
        a.keyword = argv[i + 1]
    elif v == "--dump":
        a.dump = argv[i + 1]
    elif v == "--config":
        a.config = argv[i + 1]
    elif v == "--aid":
        a.aid = argv[i + 1]
    elif v == "--page1":
        a.all_pages = False

L.AUTO_LOGIN[0] = True
sys.exit(L.cmd_readgame(a))
