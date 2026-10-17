# -*- coding: utf-8 -*-
"""只读实测：写价路径 fetch_all_needed 对 D4 全量 359 键的取数效果（容器内跑）。

验证三件事：
  ① 359 个 key > KEYWORD_SEARCH_MAX(40) ⇒ 确实走「跳过关键词搜索」这条路
  ② 新增的「按类目定位」分支被触发，且每个类目只花 1~2 页
  ③ 359 个登记ID 全部拿到、且不是靠翻 335 页换来的

⚠ 全程只 GET 列表页，不发任何写请求。
用法（宿主机）：
  docker run --rm --network host --shm-size=1g --memory=3g -e P2PAH_CHANNEL= \
    -v /opt/d4follow:/srv -w /srv p2pah-srv:1 \
    python /srv/_p2pah_srv/_test_fetch_needed.py --gid 456 --limit 0
"""
import argparse
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="/srv/config.json")
    ap.add_argument("--profile", default="/srv/_p2pah_srv/_srv_profile")
    ap.add_argument("--gid", default="456")
    ap.add_argument("--limit", type=int, default=0, help="只取前 N 个 key（0=全部）")
    a = ap.parse_args()

    cfg = json.load(io.open(a.config, encoding="utf-8"))
    idmap = ((cfg.get("p2pah") or {}).get("商品ID映射") or {})
    keys = []
    for k in idmap:
        if str(k).startswith("_"):
            continue
        try:
            if L.game_gid_of(cfg, k) == str(a.gid):
                keys.append(k)
        except Exception:
            continue
    if a.limit:
        keys = keys[:a.limit]
    L.log("gid=%s 参与取数的 key = %d 个（KEYWORD_SEARCH_MAX=%d）"
          % (a.gid, len(keys), L.KEYWORD_SEARCH_MAX))

    # 预期要拿到的后台ID
    want = set()
    for k in keys:
        for i in (L.ids_of(cfg, k) or []):
            want.add(str(i))
    L.log("对应后台ID = %d 个" % len(want))

    L.AUTO_LOGIN[0] = True
    s = L.Session(a.profile, False)
    try:
        if not s.logged_in():
            raise SystemExit("会话已失效，请先跑 login")
        t0 = time.time()
        byid = L.fetch_all_needed(s, cfg, keys)
        dt = time.time() - t0
        hit = want & set(byid.keys())
        L.log("")
        L.log("=== 结果 ===")
        L.log("耗时 %.1f 秒 ｜ byid %d 行 ｜ 登记ID 命中 %d/%d（%.1f%%）"
              % (dt, len(byid), len(hit), len(want),
                 100.0 * len(hit) / max(1, len(want))))
        miss = sorted(want - set(byid.keys()))
        if miss:
            L.log("未命中 %d 个：%s" % (len(miss), ", ".join(miss[:40])))
        return 0
    finally:
        try:
            s.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
