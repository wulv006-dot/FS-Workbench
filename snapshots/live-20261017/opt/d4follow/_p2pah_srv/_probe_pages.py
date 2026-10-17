# -*- coding: utf-8 -*-
"""只读：探测各游戏（gid）后台列表页的真实最大页数，判断有没有分页截断隐患。

背景：D4（gid=456）列表 335 页，而抓取端有 30/40 页硬上限 ⇒ 清单被截断成最新 10%，
闸一把 359 个登记档位全判成 id_gone（2026-10-05~08 连续 3 天全量停手）。
其它游戏是否有同样隐患，用「真实页数 vs 40」直接判。

⚠ 只 GET 列表第 1 页（建类目下拉 + 分页控件），不翻页、不落盘、不发写请求。
"""
import io
import json
import os
import sys
import time

sys.path.insert(0, "/srv/_p2pah_srv")
os.environ["P2PAH_CHANNEL"] = ""

import p2pah_local as L  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def _init(self, profile, keep_open=False):
    self._p = sync_playwright().start()
    self.ctx = self._p.chromium.launch_persistent_context(
        profile, channel=None, headless=True,
        viewport={"width": 1400, "height": 950})
    self.pg = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
    self._inject_saved_cookies()
    self.auto_login = bool(L.AUTO_LOGIN[0]) and (L.autologin is not None)
    try:
        self._prep_login_helpers()
    except Exception:
        pass


L.Session.__init__ = _init


def main():
    cfg = json.load(io.open("/srv/config.json", encoding="utf-8"))
    games = (cfg.get("p2pah") or {}).get("游戏") or {}
    plans = []
    for gname, gm in games.items():
        if gname.startswith("_") or not isinstance(gm, dict):
            continue
        gid = gm.get("game_id")
        if not gid:
            continue
        for sv in (gm.get("服务区") or []):
            if sv.get("启用", True):
                plans.append((gname, str(gid), str(sv.get("id") or ""), sv.get("名称") or ""))

    L.AUTO_LOGIN[0] = True
    s = L.Session("/srv/_p2pah_srv/_srv_profile", False)
    try:
        if not s.logged_in():
            raise SystemExit("会话已失效")
        L.log("%-14s %-8s %-9s %8s  %s" % ("游戏", "gid", "aid", "真实页数", "≈件数"))
        L.log("-" * 62)
        for gname, gid, aid, svname in plans:
            try:
                s.read_rows(url=L.list_url_of(gid, aid=aid), wait=1500)
                nums = [int(x) for x in L.PAGE_NUM_RE.findall(s.pg.content() or "")]
                real = max(nums) if nums else 1
                flag = "  ⚠ 超过 40 页上限！" if real > 40 else ""
                L.log("%-14s %-8s %-9s %8d  %s%s"
                      % (gname, gid, aid, real, real * 200, flag))
            except Exception as e:                    # noqa: BLE001
                L.log("%-14s %-8s %-9s  ✘ %r" % (gname, gid, aid, e))
            time.sleep(0.3)
        return 0
    finally:
        try:
            s.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
