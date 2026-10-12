# -*- coding: utf-8 -*-
"""只读：按**产品类目(cid)**抓后台商品清单，每个类目翻完它自己的所有页。

为什么要这个脚本（2026-10-08）
------------------------------
D4 赛季普通（gid=456 / aid=15711）后台全量 **307 页 ≈ 6.1 万件**，而配置登记的
359 个档位（169xxxxxx / 170xxxxxx / 180374xxx）散在**第 31~307 页**。旧的两处硬上限：

  · 本机脚本 fetch_backend_items_pw3.py 默认 `--pages 30`
  · 容器侧 p2pah_local.read_all_pages(max_pages=40) → `min(页面最大页, 40)`

⇒ 清单只拿到最新约 10%（全是 1843/1844 段的新货）⇒ 闸一每轮判「后台已找不到 ID
（可能被你删了）」⇒ 359 档全部停手（2026-10-05 18:56 起连续 3 天）。

按类目抓：D4 后台共 **163 个类目**（其中 8 个是父类目：cid 1 Gold / 2 Items / 3
Account / 4 Powerleveling / 5 Package / 7 Gift Cards / 8 Top Up / 9 Coach），
父类目是子类目的超集 —— 单抓 cid=2 Items 就等于 333 页全量。所以**只抓约 155 个叶子类目**，
每个类目几页就够，既拿全又不用翻 333 页。

顺带产出 **后台ID → cid** 映射（写价路径按类目定位要用）。

用法（宿主机）
--------------
  # ① 先探测：只读每个类目第 1 页，打印页数，不落盘
  docker run --rm --network host --shm-size=1g --memory=3g -e P2PAH_CHANNEL= \
    -v /opt/d4follow:/srv -w /srv p2pah-srv:1 \
    python /srv/_p2pah_srv/_dump_by_cat.py --gid 456 --aid 15711 --probe

  # ② 正式抓：逐类目翻完，落盘
  docker run --rm --network host --shm-size=1g --memory=3g -e P2PAH_CHANNEL= \
    -v /opt/d4follow:/srv -w /srv p2pah-srv:1 \
    python /srv/_p2pah_srv/_dump_by_cat.py --gid 456 --aid 15711 \
           --dump /srv/_p2pah_srv/_d4_by_cat.json

⚠ 只读：只 GET 列表页 + 读页面里现成的下拉与分页控件，不调任何写入接口。
"""
import argparse
import io
import json
import os
import re
import sys
import time

sys.path.insert(0, "/srv/_p2pah_srv")
os.environ["P2PAH_CHANNEL"] = ""

import p2pah_local as L  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

# 把 Session 的浏览器通道从 msedge 换成容器自带 chromium（headless）
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

SEL_CID_RE = re.compile(r'<select[^>]*name="cid"[^>]*>(.*?)</select>', re.S)
OPT_RE = re.compile(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', re.S)
# 后台类目下拉用「﹂」（U+FE42 竖排右角括号）表示层级，不是 U+2514
PREFIX = "\ufe42"


def cats_of(html):
    """从页面「产品类目」下拉取 [(cid, 名称, 层级深度)]。

    option 文本形如 `&nbsp;&nbsp;&nbsp;&nbsp;﹂3845 - Runes`，
    层级深度 = 前缀 `﹂`（U+FE42）的个数：0 = 父类目（Gold / Items / Coach …）。

    ⚠ 2026-10-08 实测：D4 共 **163 个类目**，父类目（cid 1/2/3/4/5/7/8/9）是子类目的
      超集 —— 单抓 cid=2 Items 就等于 333 页全量。所以默认**跳过父类目**，只抓叶子，
      并按层级**深的先抓**，让同一个后台ID 归属到最具体的那个类目。
    """
    out = []
    for m in SEL_CID_RE.finditer(html or ""):
        for v, t in OPT_RE.findall(m.group(1)):
            v = (v or "").strip()
            if not v or v == "0":
                continue
            name = L.text(t)
            depth = name.count(PREFIX)
            name = name.replace(PREFIX, "").strip()
            out.append((v, name, depth))
    seen, uniq = set(), []
    for v, n, d in out:
        if v not in seen:
            seen.add(v)
            uniq.append((v, n, d))
    uniq.sort(key=lambda x: -x[2])                # 叶子在前
    return uniq


def page_max(html):
    nums = [int(x) for x in L.PAGE_NUM_RE.findall(html or "")]
    return max(nums) if nums else 1


def read_page(s, url, wait, tries=2):
    """读一页；返回 0 行时用更长等待重试（防渲染慢被当成空页，静默漏 200 行）。"""
    rows = []
    for i in range(tries + 1):
        rows = s.read_rows(url=url, wait=wait if i == 0 else wait * 3)
        if rows:
            return rows
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gid", default="456")
    ap.add_argument("--aid", default="15711")
    ap.add_argument("--profile", default="/srv/_p2pah_srv/_srv_profile")
    ap.add_argument("--config", default="/srv/config.json")
    ap.add_argument("--dump", default="/srv/_p2pah_srv/_by_cat.json")
    ap.add_argument("--wait", type=int, default=1200, help="每页渲染等待 ms")
    ap.add_argument("--sleep", type=float, default=0.25, help="翻页节流秒")
    ap.add_argument("--probe", action="store_true", help="只探页数，不翻不落盘")
    ap.add_argument("--only", default="", help="只抓这些 cid（逗号分隔）")
    ap.add_argument("--keep-parents", action="store_true",
                    help="连父类目一起抓（父类目是子类目超集，等于 333 页全量，一般不要）")
    ap.add_argument("--stop-hit", action="store_true",
                    help="登记键 100% 命中就提前收工（配合 --only 只抓登记类目用）")
    a = ap.parse_args()

    L.AUTO_LOGIN[0] = True
    only = set(x.strip() for x in (a.only or "").split(",") if x.strip())

    s = L.Session(a.profile, False)
    try:
        if not s.logged_in():
            raise SystemExit("会话已失效，请先跑 login")
        L.log("gid=%s aid=%s 起始（无类目过滤）…" % (a.gid, a.aid))
        t0 = time.time()
        read_page(s, L.list_url_of(a.gid, aid=a.aid), a.wait)
        home = s.pg.content() or ""
        total_pages = page_max(home)
        cats_all = cats_of(home)
        parents = [c for c in cats_all if c[2] == 0]
        cats = cats_all if a.keep_parents else [c for c in cats_all if c[2] > 0]
        L.log("全量列表分页控件最大页 = %d（≈ %d 件）｜ 类目 %d 个 = 叶子 %d + 父 %d"
              % (total_pages, total_pages * 200, len(cats_all), len(cats), len(parents)))
        if not a.keep_parents:
            L.log("已跳过父类目（它们是子类目超集，单抓一个就等于全量）：%s"
                  % ", ".join("%s-%s" % (v, n) for v, n, _d in parents))
        for v, n, d in cats:
            L.log("   cid=%-6s %s%s" % (v, "  " * d, n or "(无名)"))

        if a.probe:
            L.log("")
            L.log("=== 探测每个类目的页数（只读第 1 页）===")
            tot = 0
            for v, n, d in cats:
                if only and v not in only:
                    continue
                try:
                    rows = read_page(s, L.list_url_of(a.gid, aid=a.aid, cid=v), a.wait)
                    pg = page_max(s.pg.content() or "")
                except SystemExit:
                    raise
                except Exception as e:
                    L.log("   cid=%-6s %-34s ✘ %r" % (v, n[:34], e))
                    continue
                tot += pg
                L.log("   cid=%-6s %-34s 首页 %3d 行 ／ %3d 页" % (v, n[:34], len(rows), pg))
                time.sleep(a.sleep)
            L.log("合计需翻 %d 页（≈ %.1f 分钟 @ %.2fs/页）"
                  % (tot, tot * (a.wait / 1000.0 + a.sleep) / 60.0, a.wait / 1000.0 + a.sleep))
            return 0

        # ── 正式抓 ─────────────────────────────────────────
        # 登记键白名单：只关心「自动改价系统里登记过的」那些后台ID，
        # 命中到 100% 就没必要再翻别的类目（用户 2026-10-08 的要求）。
        want = {}
        try:
            cfg = json.load(io.open(a.config, encoding="utf-8"))
            _idmap = ((cfg.get("p2pah") or {}).get("商品ID映射") or {})
            for k, v in _idmap.items():
                if str(k).startswith("_"):
                    continue
                try:
                    if L.game_gid_of(cfg, k) != str(a.gid):
                        continue
                except Exception:
                    continue
                want[k] = str(v or "").strip()
            L.log("gid=%s 名下登记键 %d 个（白名单）" % (a.gid, len(want)))
        except Exception as e:
            L.log("⚠ 读配置算白名单失败（%r）→ 不做命中统计" % (e,))

        byid, order, stat = {}, [], []

        def _save():
            out = {
                "gid": a.gid, "aid": a.aid,
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source": "_dump_by_cat.py（按类目翻页，只读）",
                "total_pages_unfiltered": total_pages,
                "cats": [{"cid": v, "name": n, "depth": d} for v, n, d in cats],
                "only": sorted(only),
                "stat": stat,
                "n": len(order),
                "rows": [byid[i] for i in order],
            }
            tmp = a.dump + ".tmp"
            with io.open(tmp, "w", encoding="utf-8") as f:
                f.write(json.dumps(out, ensure_ascii=False))
            os.replace(tmp, a.dump)          # 原子替换，被杀也不会留半截文件

        def _report(tag=""):
            """登记键命中率 —— 抓到达标就可以停"""
            if not want:
                return 0, 0, []
            miss = [k for k, i in want.items() if i not in byid]
            hit = len(want) - len(miss)
            L.log("   ▸ 登记键命中 %d/%d（%s）%s"
                  % (hit, len(want), "%.1f%%" % (100.0 * hit / len(want)), tag))
            return hit, len(want), miss

        for v, n, d in cats:
            if only and v not in only:
                continue
            try:
                rows = read_page(s, L.list_url_of(a.gid, aid=a.aid, cid=v), a.wait)
                html = s.pg.content() or ""
                last = page_max(html)
            except SystemExit:
                raise
            except Exception as e:
                L.log("cid=%-6s %-30s ✘ 首页失败 %r" % (v, n[:30], e))
                continue
            got = 0
            for r in rows:
                if r["id"] not in byid:
                    r["cid"], r["cat"] = v, n
                    byid[r["id"]] = r
                    order.append(r["id"])
                    got += 1
            for p in range(2, last + 1):
                try:
                    rows = read_page(s, L.list_url_of(a.gid, aid=a.aid, cid=v,
                                                      page=str(p)), a.wait)
                except SystemExit:
                    raise
                except Exception as e:
                    L.log("   cid=%s 第%d页 ✘ %r" % (v, p, e))
                    continue
                new = 0
                for r in rows:
                    if r["id"] not in byid:
                        r["cid"], r["cat"] = v, n
                        byid[r["id"]] = r
                        order.append(r["id"])
                        new += 1
                got += new
                if p % 10 == 0 or p == last:
                    L.log("   cid=%s「%s」翻到第 %d/%d 页（累计 %d 行）"
                          % (v, n[:20], p, last, len(byid)))
                time.sleep(a.sleep)
            stat.append({"cid": v, "cat": n, "pages": last, "new": got})
            L.log("cid=%-6s %-30s %3d 页 → 新增 %5d（累计 %d）"
                  % (v, n[:30], last, got, len(byid)))
            _save()                          # 每完成一个类目就落盘
            hit, tot, miss = _report()
            if a.stop_hit and tot and hit == tot:
                L.log("🎯 登记键已 100% 命中 → 提前收工")
                break

        miss = [k for k, i in want.items() if i not in byid] if want else []
        if miss:
            L.log("")
            L.log("⚠ 仍有 %d 个登记键未命中（这些档位会继续被判 id_gone）：" % len(miss))
            for k in miss[:60]:
                L.log("     · %-14s id=%s" % (k, want[k]))

        _save()
        L.log("")
        L.log("✅ 落盘 %s：%d 行 / %d 类目 / 用时 %.1f 分钟"
              % (a.dump, len(order), len(stat), (time.time() - t0) / 60.0))
        return 0
    finally:
        try:
            s.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
