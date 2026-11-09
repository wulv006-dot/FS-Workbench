# -*- coding: utf-8 -*-
"""IGGM 金币「本机代抓」——住宅 IP 抓 IGGM 真价，推给服务器定价引擎。

背景（2026-10-20）：Cloudflare 把机房出口整站拦掉（连 /maplestory-classic-world/mesos
都 403），而 core_gold.IggmGold.fetch() 是服务器直连 ⇒ IGGM 每M 恒为 None。
对 MSCW(iggm_undercut) 是致命的：模式要「IGGM 真价 × (1−让价)」，基准没了就
不出目标价、不出工单，还写出「基准 - $None」的漂移值，下一轮把漂移当现价 ⇒ 永远 hold。

本脚本在本机（住宅 IP）按每个服务区的 iggm_sid 抓一次 goods_ajax，
写成 data/iggm_gold_push.json（形状见 core_gold._pushed_iggm_gold），
服务器 fetch() 会优先读它；本机不跑时文件过期，自动回退直连（行为与改造前一致）。

用法：
    python iggm_gold_local.py                 # 抓「参与定价」的游戏（默认）
    python iggm_gold_local.py --all           # 抓全部（含 AION2 的 86 个区）
    python iggm_gold_local.py --games "MapleStory Classic World,暗黑破坏神4"
    python iggm_gold_local.py --no-push       # 只写本地文件，不上传

2026-10-22 老板要求「IGGM 也要能看价」⇒ 新增 AION2 抓取支持：
  · AION2 走**独立会话缸** `core_iggm.AION2_SESSION`（86 个区请求量大，不能和使用
    GOLD_SESSION 的 D4/MSCW 共用熔断器 —— 否则 AION2 撞一次 CF 就把别人的基准价也熔断）；
  · 新增 `--gap`（默认 0）限速，AION2 建议 0.6s，避免 86 连击触发 Cloudflare。
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 2026-10-23：由 iggm_guard（pythonw）调起时，下面的 scp / ssh 子进程会各自新开控制台窗口
# （Win11 交给 Windows Terminal ⇒ 标题显示 C:\WINDOWS\System32\OpenSSH\ssh.exe 的黑窗）。
# 加 CREATE_NO_WINDOW 让它们彻底无窗口。
NO_WIN = 0x08000000 if os.name == "nt" else 0

# 2026-10-21：pythonw + 管道输出时 stdout 默认 GBK，下面的 ✔/✘ 会抛 UnicodeEncodeError，
# 而且它落在 try 块里 ⇒ 抓取明明成功却被记成失败（金币侧 10:14 起全挂的根因）。强制 UTF-8。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import core_gold as cg          # noqa: E402  （会连带导入 core_iggm / net_util）
try:                            # 2026-10-22：AION2 要用独立会话缸，容错导入
    import core_iggm as _ci     # noqa: E402
except Exception:               # noqa: BLE001
    _ci = None

CFG_PATH = os.path.join(HERE, "config.json")
OUT_PATH = os.path.join(HERE, "iggm_gold_push.json")
# 参与定价（IGGM 真价是定价基准 / 兜底参照）的游戏；AION2 走 DD373，IGGM 仅展示
PRICING_GAMES = ("MapleStory Classic World", "暗黑破坏神4", "ARC Raiders")


def load_cfg():
    with open(CFG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def targets(cfg, games=None):
    """[(游戏, key, sid, page)]"""
    g = cfg.get("金币") or {}
    gp = g.get("游戏参数") or {}
    out = []
    for sv in (g.get("服务区") or []):
        gm = sv.get("游戏") or cg.DEFAULT_GAME
        if games is not None and gm not in games:
            continue
        sid = sv.get("iggm_sid")
        if not sid:
            continue
        page = (gp.get(gm) or {}).get("IGGM金币页")
        out.append((gm, sv.get("key"), str(sid), page))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default=None, help="逗号分隔；默认只抓参与定价的游戏")
    ap.add_argument("--all", action="store_true", help="抓全部（含 AION2 86 个区）")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--gap", type=float, default=0.0,
                    help="每个区之间的间隔秒（AION2 86 个区建议 0.6，防 CF 风控）")
    ap.add_argument("--ssh-key", default=os.path.expanduser("~/.ssh/fs_admin"))
    ap.add_argument("--host", default="root@47.85.170.62")
    ap.add_argument("--remote", default="/opt/d4follow/data/iggm_gold_push.json")
    a = ap.parse_args()

    if a.all:
        games = None
    elif a.games:
        games = tuple(x.strip() for x in a.games.split(",") if x.strip())
    else:
        games = PRICING_GAMES

    cfg = load_cfg()
    tg = targets(cfg, games)
    print("待抓 %d 个服务区（游戏：%s）"
          % (len(tg), "、".join(sorted({t[0] for t in tg}))))

    by_sid = {}
    ok_n = fail_n = 0
    pages_warmed = {}
    _aion2_sess = getattr(_ci, "AION2_SESSION", None) if _ci else None
    for gm, key, sid, page in tg:
        line = None
        try:
            sess_page = page or "/diablo-4-items"
            # 2026-10-22：AION2 走独立会话缸 —— 86 个区撞 CF 时不能连带熔断
            #   D4/MSCW 正在用的 GOLD_SESSION（那会直接抽掉它们的定价基准）。
            _sess = _aion2_sess if gm == "AION2" else None
            ig = cg.IggmGold(log=lambda *x: None, sess=_sess)
            if (sess_page, _sess is not None) not in pages_warmed:
                pages_warmed[(sess_page, _sess is not None)] = ig.warm(page=sess_page)
            d = ig.fetch(sid, page=page, retry=2)
            up = d.get("unit_price")
            if not up:
                fail_n += 1
                line = "  ✘ %-28s sid=%-7s 无 unit_price" % (key, sid)
            else:
                by_sid[sid] = {
                    "unit_price": up,
                    "goods_no": d.get("goods_no"),
                    "title": d.get("title"),
                    "rule": d.get("rule"),
                    "update_time": d.get("update_time"),
                    "tiers": d.get("tiers") or [],
                    "game": gm, "zone_key": key, "page": page,
                }
                ok_n += 1
                line = ("  ✔ %-28s sid=%-7s $%.6f/M  %d 档  %s"
                        % (key, sid, up, len(d.get("tiers") or []), (d.get("title") or "")[:34]))
        except Exception as e:  # noqa: BLE001
            fail_n += 1
            line = "  ✘ %-28s sid=%-7s %r" % (key, sid, e)
        # 打印一律放在 try 之外：编码异常不会再被当成「抓取失败」
        print(line)
        if a.gap and a.gap > 0:          # 2026-10-22：限速（AION2 86 区防 CF 风控）
            time.sleep(a.gap)

    doc = {"ts": dt.datetime.now().isoformat(timespec="seconds"),
           "source": "本机住宅IP代抓 core_gold.IggmGold.fetch",
           "games": sorted({t[0] for t in tg}),
           "count": len(by_sid), "by_sid": by_sid}
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print("\n已写出 %s（成功 %d / 失败 %d）" % (OUT_PATH, ok_n, fail_n))

    if a.no_push or not by_sid:
        if not by_sid:
            print("没有任何有效数据，不推送")
        return 0 if ok_n else 1

    print("上传到 %s:%s …" % (a.host, a.remote))
    r = subprocess.run(["scp", "-o", "StrictHostKeyChecking=no", "-i", a.ssh_key,
                        OUT_PATH, "%s:%s.tmp" % (a.host, a.remote)],
                       capture_output=True, text=True, creationflags=NO_WIN)
    if r.returncode != 0:
        print("上传失败：", (r.stderr or "").strip()[:300])
        return 1
    mv = ("mv -f %s.tmp %s && chown root:root %s && "
          "ls -l --time-style=+%%m-%%d_%%H:%%M %s" % (a.remote, a.remote, a.remote, a.remote))
    r2 = subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no", "-i", a.ssh_key,
                         a.host, mv], capture_output=True, text=True, creationflags=NO_WIN)
    print((r2.stdout or r2.stderr or "").strip()[:300])
    return 0 if r2.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
