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
    python dd373_local_collect.py            # 全量 86 区
    python dd373_local_collect.py --limit 5  # 只抓前 5 个区（联调）
    python dd373_local_collect.py --gap 1.6  # 请求间隔秒
输出：`<归档根>/验证/local_costs_<时间戳>.json`
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
SRC = os.path.join(ROOT, "改前源")
sys.path.insert(0, SRC)

import core_dd373_cost as dd          # noqa: E402

PROFILE = r"C:\Users\yi\AppData\Local\Temp\dd_edge_profile"
HOME = "https://www.dd373.com/"


def grab_cookie(verbose=True):
    """用真实 Edge（可见）访问首页，取回 dd373 域的整串 cookie。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE,
            channel="msedge",
            headless=False,
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
    """把采集结果推给服务器 /api/dd373_cost（经 SSH：scp 上传 + 本机回环 POST）。

    为什么不用 HTTP 直连：服务器的 8900 只监听回环，公网不可达（实测
    `curl http://47.85.224.112:8900/api/health` = 000）。SSH 已经是通的，最省事。
    """
    import subprocess
    remote = "/tmp/dd373_push.json"
    _b = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=25"]
    r1 = subprocess.run(["scp", "-i", key] + _b + [js_path, "%s:%s" % (host, remote)],
                        capture_output=True)
    if r1.returncode != 0:
        print("[push] scp 失败：%s" % r1.stderr.decode("utf-8", "ignore")[-300:])
        return False
    cmd = ("curl -s -m 60 -X POST http://127.0.0.1:8900/api/dd373_cost"
           " -H 'Content-Type: application/json; charset=utf-8'"
           " --data-binary @%s" % remote)
    r2 = subprocess.run(["ssh", "-i", key] + _b + [host, cmd], capture_output=True)
    out = r2.stdout.decode("utf-8", "ignore").strip()
    if out:
        print("[push] 服务器响应：%s" % out[:300])
    else:
        print("[push] ssh 无输出：%s" % r2.stderr.decode("utf-8", "ignore")[-300:])
    return '"ok":true' in out.replace(" ", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
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
                    or r"D:\共享资源\服务器\No1.pem")
    ap.add_argument("--ssh-host", default=os.environ.get("DD373_SSH_HOST")
                    or "root@47.85.224.112")
    a = ap.parse_args()

    cfg = json.load(open(os.path.join(SRC, "config.json"), encoding="utf-8"))
    g = cfg.get("金币") or {}
    svs = [s for s in (g.get("服务区") or []) if s.get("游戏") == "AION2"]
    if a.limit:
        svs = svs[:a.limit]
    rate = float((cfg.get("汇率") or {}).get("USDCNY") or 6.65)
    print("[配置] AION2 服务区 %d 个 · 汇率 %.4f · 间隔 %.1fs"
          % (len(svs), rate, a.gap))

    # cookie：优先复用本地缓存（免弹窗），探针失效才开浏览器
    ck = "" if a.refresh_cookie else load_cookie(a.max_cookie_age)
    if ck:
        dd._get = make_get(ck)
        if not cookie_alive():
            print("[cookie] 缓存失效 —— 改用真实浏览器重新取")
            ck = ""
    if not ck:
        ck = grab_cookie()
        if not ck:
            print("FATAL 拿不到 cookie")
            return 2
        save_cookie(ck)
        dd._get = make_get(ck)
    if a.cookie_only:
        return 0

    t0 = time.time()
    costs = dd.fetch_costs(svs, rate, log=print, gap=a.gap,
                           refresh_tree=not a.no_refresh_tree)
    dt = time.time() - t0

    ok = [k for k, v in costs.items() if v.get("ok")]
    blk = [k for k, v in costs.items()
           if not v.get("ok") and "风控" in str(v.get("依据") or "")]
    print()
    print("=== 结果 === 用时 %.1fs · 共 %d 区 · 有报价 %d · 风控 %d"
          % (dt, len(costs), len(ok), len(blk)))
    print("--- 样例 3 区 ---")
    for k in list(costs.keys())[:3]:
        v = costs[k]
        print("  %-24s ok=%s 成本=%s $/M=%s | %s"
              % (k, v.get("ok"), v.get("成本_元每万基纳"),
                 v.get("成本_USD每M"), str(v.get("依据"))[:70]))

    out_dir = os.path.join(ROOT, "验证")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "local_costs_%s.json"
                       % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                   "game": "AION2", "rate": rate,
                   "costs": costs}, f, ensure_ascii=False, indent=1)
    print("[输出] %s" % out)
    if a.push:
        _pushed = push_to_server(out, a.ssh_key, a.ssh_host)
        print("[push] %s" % ("成功 ✅" if _pushed else "失败 ❌"))
        return 0 if (ok and _pushed) else 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
