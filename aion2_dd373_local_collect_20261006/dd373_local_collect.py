# -*- coding: utf-8 -*-
"""DD373 本机代抓 —— 用「本机 IP + 浏览器 cookie」采集 AION2 基纳进货成本。

背景
----
服务器出口 IP 已被 DD373 的阿里云 WAF 打进风控（无痕验证滑块页），
`core_dd373_cost.fetch_costs()` 在服务器上恒返回风控 ⇒ 成本冻结、不出单。
实测本机 IP **没过风控**，只是**自动化请求**会被拦：
    · 无 cookie         → 11955B 拦页
    · 只带 acw_tc       → 拦页
    · 带浏览器整套 cookie → 200，20 条商品 ✅
所以本脚本：先用真实 Edge（可见窗口，几秒）过一次站点，拿到 cookie，
再用轻量 urllib（带 cookie）批量抓 —— 解析逻辑**完全复用服务器的
`core_dd373_cost.py`**（同一份文件，只替换底层 `_get`）。

用法
----
    python dd373_local_collect.py                    # AION2 全量 + MSCW（各推一次）
    python dd373_local_collect.py --limit 5          # 每个游戏只抓前 5 个区（联调）
    python dd373_local_collect.py --only-game AION2  # 只抓某一个游戏
    python dd373_local_collect.py --gap 1.6          # 请求间隔秒
输出：`<归档根>/验证/local_costs_<游戏>_<时间戳>.json`

⚠ 2026-10-15（方案 A）：本机代抓必须覆盖**服务器采集目标里的每一个游戏**。
    服务器侧「优先本机推送」是**整轮跳过自抓**（不按游戏区分），而
    `金币.进货成本.游戏列表 = [AION2, MapleStory Classic World]`；以前只推 AION2
    的 86 区 ⇒ **MSCW（冒险岛）被顺带跳过**，成本自 2026-10-14 13:06 起冻结 5.5 小时。
    现在两个游戏各抓一轮、各推一次（MSCW 走扁平专区，仅 1 个服务区、约 2 次请求）。
"""
import os
import sys
import json
import time
import gzip
import argparse
import datetime
import urllib.request

for _k in ("http_proxy", "https_proxy", "all_proxy",
           "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_k, None)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# 解析模块 core_dd373_cost.py：优先用**本目录的副本**（run_collect.py 每轮会从服务器
# scp 同步最新版，保证口径与线上一致）；没有副本时退回归档目录的「改前源」。
SRC = HERE
if not os.path.exists(os.path.join(SRC, "core_dd373_cost.py")):
    SRC = os.path.join(ROOT, "改前源")
sys.path.insert(0, SRC)

import core_dd373_cost as dd          # noqa: E402

PROFILE = r"C:\Users\yi\AppData\Local\Temp\dd_edge_profile"
HOME = "https://www.dd373.com/"

# 代抓的游戏 → 输出文件名 slug
GAME_SLUG = {"AION2": "aion2", "MapleStory Classic World": "mscw"}
# 代抓顺序：MSCW 先、AION2 后 —— 服务器的 `data/dd373_local_push.json` 只记
# **最后一次**推送的 saved/ok_rows，把 AION2（86 条）放最后，可让采集日志里
# 「本机推来 N 条」与历史一致（否则会显示成 MSCW 的 1 条，看着像推送丢了）。
GAMES_DEFAULT = ("MapleStory Classic World", "AION2")


def grab_cookie(verbose=True, headless=True):
    """用真实 Edge 访问首页，取回 dd373 域的整串 cookie。

    2026-10-14：默认改为**无头**（headless=True）——原先 headless=False 会在
    cookie 每 6 小时过期时弹一个可见浏览器窗口，影响办公。
    仍靠 --disable-blink-features=AutomationControlled 绕自动化检测；
    调用处对取回的 cookie 做探针校验，失败会自动回退 headless=False。
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE,
            channel="msedge",
            headless=headless,
            args=["--no-proxy-server",
                  "--disable-blink-features=AutomationControlled"],
            locale="zh-CN",
            viewport={"width": 1366, "height": 900},
        )
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            pg.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(3500)
            title = pg.title()
            cks = ctx.cookies()
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    d = {}
    for c in cks:
        if "dd373.com" in (c.get("domain") or ""):
            d[c["name"]] = c["value"]
    ck = "; ".join("%s=%s" % (k, v) for k, v in d.items())
    if verbose:
        print("[cookie] 站点标题=%r  取到 %d 项 / %d 字节"
              % (title, len(d), len(ck)))
    return ck


COOKIE_FILE = os.path.join(HERE, ".dd373_cookie.json")
# 探针用固定小区：Asia|Siel（天1），常年有货；只用来判断 cookie 是否还活着
PROBE_SEG = "heft1r-d1be8h-ak5ga1"


def save_cookie(ck):
    try:
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump({"cookie": ck,
                       "saved_at": datetime.datetime.now().isoformat(timespec="seconds")},
                      f, ensure_ascii=False)
        print("[cookie] 已缓存到 %s" % os.path.basename(COOKIE_FILE))
    except Exception as e:              # noqa: BLE001
        print("[cookie] 缓存写入失败 %r" % (e,))


def load_cookie(max_age_h=6.0):
    """读本地缓存 cookie；超过 max_age_h 小时视为过期。"""
    try:
        with open(COOKIE_FILE, encoding="utf-8") as f:
            j = json.load(f)
        t = datetime.datetime.fromisoformat(str(j.get("saved_at") or ""))
        age = (datetime.datetime.now() - t).total_seconds() / 3600.0
        if age > max_age_h:
            print("[cookie] 缓存已 %.1f 小时，视为过期" % age)
            return ""
        ck = str(j.get("cookie") or "")
        print("[cookie] 复用本地缓存（%.2f 小时前保存 / %d 字节）" % (age, len(ck)))
        return ck
    except Exception:
        return ""


def cookie_alive(verbose=True):
    """用当前（已 patch 的）_get 试抓 1 个小区，判断 cookie 是否仍有效。"""
    try:
        h = dd._get(dd._short_url(PROBE_SEG), tries=1)
        n = h.count("goods-list-item")
        if verbose:
            print("[cookie] 探针 goods-list-item=%d %s" % (n, "✅" if n > 0 else "❌"))
        return n > 0
    except Exception as e:              # noqa: BLE001
        if verbose:
            print("[cookie] 探针异常 %r —— 视为失效" % (e,))
        return False


def make_get(cookie):
    """替换 dd._get：同一套重试/解压逻辑，只多一个 Cookie 头。"""
    def _get2(url, referer=dd.BASE + "/", timeout=25, tries=2):
        last = None
        t = max(1, int(tries))
        for i in range(t):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": dd.UA,
                    "Referer": referer,
                    "Accept-Encoding": "identity",
                    "Accept": "text/html,application/json,*/*",
                    "Cookie": cookie,
                })
                ctx = getattr(dd, "_sslctx", None)
                with urllib.request.urlopen(req, timeout=timeout,
                                            context=ctx) as f:
                    raw = f.read()
                    if (f.headers.get("Content-Encoding") == "gzip"
                            or raw[:2] == b"\x1f\x8b"):
                        raw = gzip.decompress(raw)
                return raw.decode("utf-8", "ignore")
            except Exception as e:          # noqa: BLE001
                last = e
                if i < t - 1:
                    time.sleep(2.0 + 2.0 * i)
        raise last
    return _get2


def push_to_server(js_path, key, host, verbose=True):
    """把采集结果推给服务器 /api/dd373_cost（经 SSH：ssh+cat 上传 + 本机回环 POST）。

    为什么不用 HTTP 直连：服务器的 8900 只监听回环，公网不可达（实测
    `curl http://47.85.224.112:8900/api/health` = 000）。SSH 已经是通的，最省事。

    为什么不用 scp：本机**自带的 `C:\\Windows\\System32\\OpenSSH\\scp.exe` 不可用**
    （2026-10-06 实测恒报 `scp: pipe: Unknown error`；同目录的 ssh.exe 正常）。
    所以改成 `ssh host "cat > 远端"`，用标准输入把文件内容喂过去。
    """
    import subprocess
    # ⚠ 2026-10-07：本脚本由 pythonw.exe 启动（无控制台）。
    #   从这里 spawn 控制台程序 ssh.exe 必须带 CREATE_NO_WINDOW，
    #   否则 Windows 新开控制台 ⇒ Win11 交给 Windows Terminal ⇒ 弹黑框。
    _nw = 0x08000000 if os.name == "nt" else 0
    remote = "/tmp/dd373_push.json"
    _b = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=25"]
    with open(js_path, "rb") as _f:
        _data = _f.read()
    r1 = subprocess.run(["ssh", "-i", key] + _b + [host, "cat > %s" % remote],
                        input=_data, capture_output=True, creationflags=_nw)
    if r1.returncode != 0:
        print("[push] 上传失败（ssh cat）：%s"
              % (r1.stderr or b"").decode("utf-8", "ignore")[-300:])
        return False
    cmd = ("curl -s -m 60 -X POST http://127.0.0.1:8900/api/dd373_cost"
           " -H 'Content-Type: application/json; charset=utf-8'"
           " --data-binary @%s" % remote)
    r2 = subprocess.run(["ssh", "-i", key] + _b + [host, cmd], capture_output=True,
                        creationflags=_nw)
    out = r2.stdout.decode("utf-8", "ignore").strip()
    if out:
        print("[push] 服务器响应：%s" % out[:300])
    else:
        print("[push] ssh 无输出：%s" % r2.stderr.decode("utf-8", "ignore")[-300:])
    return '"ok":true' in out.replace(" ", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="每个游戏只抓前 N 个服务区（联调），0 = 全量")
    ap.add_argument("--only-game", default="",
                    help="只抓指定游戏（默认两个都抓：MSCW + AION2）")
    ap.add_argument("--gap", type=float, default=1.5)
    ap.add_argument("--cookie-only", action="store_true")
    ap.add_argument("--no-refresh-tree", action="store_true")
    ap.add_argument("--refresh-cookie", action="store_true",
                    help="强制用浏览器重新取 cookie（默认优先复用本地缓存）")
    ap.add_argument("--max-cookie-age", type=float, default=6.0,
                    help="缓存 cookie 的最长复用小时数（默认 6）")
    ap.add_argument("--push", action="store_true",
                    help="采集完把结果推给服务器 /api/dd373_cost")
    ap.add_argument("--ssh-key", default=os.environ.get("DD373_SSH_KEY")
                    or r"D:\workbuddy文件目录\服务器\fs_admin_20261016_ed25519")
    ap.add_argument("--ssh-host", default=os.environ.get("DD373_SSH_HOST")
                    or "root@47.85.224.112")
    a = ap.parse_args()

    cfg = json.load(open(os.path.join(SRC, "config.json"), encoding="utf-8"))
    g = cfg.get("金币") or {}
    all_sv = g.get("服务区") or []
    rate = float((cfg.get("汇率") or {}).get("USDCNY") or 6.65)
    games = [a.only_game] if a.only_game else list(GAMES_DEFAULT)
    print("[配置] 本轮代抓 %d 个游戏：%s · 汇率 %.4f · 间隔 %.1fs"
          % (len(games), "、".join(games), rate, a.gap))

    # cookie：优先复用本地缓存（免弹窗），探针失效才开浏览器
    ck = "" if a.refresh_cookie else load_cookie(a.max_cookie_age)
    if ck:
        dd._get = make_get(ck)
        if not cookie_alive():
            print("[cookie] 缓存失效 —— 改用真实浏览器重新取")
            ck = ""
    if not ck:
        # 2026-10-14：无头优先（办公时不弹窗）；拿回的 cookie 先过探针，
        # 无效再回退可见模式一次，保证采集链不因无头检测而中断。
        for _hl in (True, False):
            _c = grab_cookie(headless=_hl)
            if not _c:
                continue
            dd._get = make_get(_c)
            if cookie_alive():
                ck = _c
                print("[cookie] %s模式可用" % ("无头" if _hl else "可见"))
                break
            print("[cookie] %s模式取到的 cookie 探针未通过" % ("无头" if _hl else "可见"))
        if not ck:
            print("FATAL 拿不到 cookie")
            return 2
        save_cookie(ck)
        dd._get = make_get(ck)
    if a.cookie_only:
        return 0

    results = {}
    for game in games:
        svs = [s for s in all_sv if s.get("游戏") == game]
        if not svs:
            print("[配置] config 里没有 %s 的金币服务区，跳过" % game)
            continue
        if a.limit:
            svs = svs[:a.limit]
        # 扁平专区（MSCW）没有三层服务区树 ⇒ refresh_tree 只对 AION2 有意义
        _rt = (not a.no_refresh_tree) and (game == "AION2")
        print()
        print("[配置] %-26s 服务区 %d 个" % (game, len(svs)))

        t0 = time.time()
        try:
            costs = dd.fetch_costs(svs, rate, log=print, gap=a.gap,
                                   refresh_tree=_rt, game=game)
        except Exception as e:                       # noqa: BLE001
            print("[采集] %s 异常（不影响其它游戏）：%r" % (game, e))
            results[game] = {"ok": 0, "total": len(svs), "pushed": False}
            continue
        dt = time.time() - t0

        ok = [k for k, v in costs.items() if v.get("ok")]
        blk = [k for k, v in costs.items()
               if not v.get("ok") and "风控" in str(v.get("依据") or "")]
        print()
        print("=== 结果 === %s · 用时 %.1fs · 共 %d 区 · 有报价 %d · 风控 %d"
              % (game, dt, len(costs), len(ok), len(blk)))
        print("--- 样例 3 区 ---")
        for k in list(costs.keys())[:3]:
            v = costs[k]
            print("  %-24s ok=%s 成本=%s $/M=%s | %s"
                  % (k, v.get("ok"), v.get("成本_元每万基纳"),
                     v.get("成本_USD每M"), str(v.get("依据"))[:70]))

        out_dir = os.path.join(ROOT, "验证")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, "local_costs_%s_%s.json"
                           % (GAME_SLUG.get(game, "other"),
                              datetime.datetime.now().strftime("%Y%m%d_%H%M%S")))
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                       "game": game, "rate": rate,
                       "costs": costs}, f, ensure_ascii=False, indent=1)
        print("[输出] %s" % out)

        _pushed = False
        if a.push:
            if blk and len(blk) == len(costs):
                # 全被风控 ≠ 无货：推上去会把「被拦」写成「无报价」
                # ⇒ 跳过推送，让服务器沿用上一轮快照（与服务器自抓口径一致）
                print("[push] ⚠ %s 本轮全部被风控 —— 跳过推送（沿用上一轮快照）" % game)
            else:
                _pushed = push_to_server(out, a.ssh_key, a.ssh_host)
                print("[push] %s %s" % (game, "成功 ✅" if _pushed else "失败 ❌"))
        results[game] = {"ok": len(ok), "total": len(costs), "pushed": _pushed}

    print()
    print("=== 汇总 ===")
    for _g in games:
        if _g not in results:
            continue
        _r = results[_g]
        print("  %-26s 有报价 %d/%d · 推送 %s"
              % (_g, _r["ok"], _r["total"],
                 "✅" if _r["pushed"] else ("-" if not a.push else "❌")))
    if not results:
        return 2
    if a.push:
        return 0 if all(_r["pushed"] for _r in results.values()) else 1
    return 0 if all(_r["ok"] for _r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
