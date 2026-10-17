# -*- coding: utf-8 -*-
"""订单后台（order.p2pah.cn）金币售价**只读**发现探针。

为什么要有这个脚本
------------------
老大 2026-10-12 要求：工作台「当期金币售价」应默认从后台自动带出。
后台位置 = 订单后台 → 游戏&产品 → **金币价格管理** → 所属游戏 922（MLB The Show 26）
→ 里面的 **B2C 价格** 即该游戏金币的 USD 售价。

⚠️ 但这个字段的**真实接口、字段名、单位（每 K / 每 100K）都不知道**。
单位差 100 倍会直接把整批卡价打偏，所以先跑**只读**探针把事实钉下来，
再决定怎么接进 `rate`。

安全边界（红线）
----------------
- **只发 GET**，绝不 POST 任何写接口（唯一例外是与本探针无关的登录 POST）。
- 不在脚本里硬编码任何凭据 —— 用户名/密码走命令行或环境变量。
- 不修改后台任何数据；只读菜单与列表页。

用法
----
    # 1) 登录（ddddocr 自动过码，最多 3 次）
    python _p2pah_price_probe.py login --user wulv --session /tmp/p2pah.pkl

    # 2) 拉后台左侧菜单，找出「金币价格管理」的真实 URL
    python _p2pah_price_probe.py menu --session /tmp/p2pah.pkl --dump /tmp/menu.html

    # 3) 命中候选接口列表（哪些 200 / 哪些 404）
    python _p2pah_price_probe.py probe --session /tmp/p2pah.pkl

    # 4) 读指定游戏的金币价格表
    python _p2pah_price_probe.py price --session /tmp/p2pah.pkl --gid 922
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import re
import sys
import time

import requests

BASE = "https://order.p2pah.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
HDR = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}

#: 菜单组「游戏&产品」下「金币价格管理」的候选 URL。
#: ThinkCMF + simpleboot3 的路径形如 `<模块>/<控制器小写下划线>/<动作>.html`，
#: 控制器名从中文菜单名反推，覆盖各种命名习惯 —— 只要能命中一个就够。
#: ⚠️ 已实测命中：`game/admin_game_price/index.html`（2026-10-12）。其余留作备份，
#:    万一后台改版可以再扫一遍。
CANDIDATES = (
    "game/admin_game_price/index.html",     # ← 实测命中：金币价格管理
    "admin/game/admin_game_price/index.html",
    "goods/admin_gold_price/index.html",
    "goods/admin_goods_price/index.html",
    "goods/admin_price/index.html",
    "goods/admin_gold/index.html",
    "goods/admin_goods/index.html",
    "product/admin_gold_price/index.html",
    "product/admin_price/index.html",
    "price/admin_gold/index.html",
    "gold/admin_price/index.html",
)


# --------------------------------------------------------------------- 会话
def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HDR)
    r = s.get(BASE + "/login.html", timeout=30, allow_redirects=True)
    print("[login.html] HTTP=%s %d bytes | cookies=%s"
          % (r.status_code, len(r.text), s.cookies.get_dict()))
    return s


def save_session(s, path):
    with open(path, "wb") as f:
        pickle.dump(s, f)
    print("[session] 已保存 →", path)


def load_session(path):
    with open(path, "rb") as f:
        s = pickle.load(f)
    print("[session] 已载入 ←", path)
    return s


def logged_in(s) -> bool:
    """未登录时 /admin/* 会 302 到登录页 —— 这是最可靠的判据。"""
    r = s.get(BASE + "/admin/index/index.html", timeout=30, allow_redirects=False)
    return r.status_code == 200


# --------------------------------------------------------------------- 登录
def grab_captcha(s):
    r = s.get(BASE + "/new_captcha.html?height=32&width=150&font_size=18",
              timeout=30, headers={"Referer": BASE + "/login.html"})
    return r.content


def do_login(s, user, password, captcha):
    r = s.post(BASE + "/admin/public/dologin.html", timeout=30, data={
        "username": user, "password": password, "captcha": captcha,
        "_captcha_id": "", "redirect": "",
    }, headers={"Referer": BASE + "/login.html",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": BASE,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    try:
        return json.loads(r.text)
    except Exception:
        return {"code": None, "msg": r.text[:200]}


def solve(png):
    """ddddocr 过码。识别不出 4~6 位数字/字母就返回空串交给重试。"""
    import ddddocr
    ocr = ddddocr.DdddOcr(show_ad=False)
    code = (ocr.classification(png) or "").strip()
    return code


def cmd_login(a):
    user = a.user or os.environ.get("P2PAH_ORDER_USER")
    password = a.password or os.environ.get("P2PAH_ORDER_PASS")
    if not user or not password:
        raise SystemExit("缺少凭据：用 --user/--password 或环境变量 "
                         "P2PAH_ORDER_USER / P2PAH_ORDER_PASS")
    s = new_session()
    last = None
    for n in range(1, 4):
        png = grab_captcha(s)
        code = solve(png)
        if not re.fullmatch(r"[0-9A-Za-z]{3,6}", code or ""):
            last = "识别结果异常 %r" % code
            print("  第 %d 次：识别异常 %r，换一张" % (n, code))
            continue
        print("  第 %d 次：识别为 %s" % (n, code))
        j = do_login(s, user, password, code)
        print("  dologin ->", j)
        if j.get("code") == 1:
            save_session(s, a.session)
            return 0
        last = j.get("msg")
        if "验证码" not in str(j.get("msg")):
            raise SystemExit("登录失败（非验证码原因，不重试）：%r" % j)
        time.sleep(0.5)
    raise SystemExit("验证码连续失败：%s" % last)


def abs_url(path: str) -> str:
    """菜单里的路径是**站点根相对**（页面里 `WEB_ROOT = "/"`）。

    ⚠️ 曾误加 `/admin/` 前缀 → 一律 404。实测 `/game/admin_game_price/index.html`
    才是对的（同一后台里 `/admin/index/index.html` 也能通，因为 `admin` 只是
    其中一个模块名，不是统一前缀）。
    """
    return BASE + "/" + path.lstrip("/")


# --------------------------------------------------------------------- 发现
def cmd_menu(a):
    s = load_session(a.session)
    if not logged_in(s):
        raise SystemExit("会话已失效，请先 login")
    r = s.get(BASE + "/admin/index/index.html", timeout=30)
    html = r.text
    if a.dump:
        with open(a.dump, "w", encoding="utf-8") as f:
            f.write(html)
        print("[dump] 菜单原始 HTML → %s（%d 字节）" % (a.dump, len(html)))

    print("\n=== 含「金币 / 价格 / 游戏 / 产品」的菜单链接 ===")
    hits = 0
    for m in re.finditer(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                         html, re.S | re.I):
        href, text = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if any(k in text for k in ("金币", "价格", "游戏", "产品", "商品")):
            hits += 1
            print("  %-60s  %s" % (href, text))
    if not hits:
        print("  （当前页 HTML 里没有菜单 —— simpleboot3 的菜单可能是异步加载的，" 
              "接着跑 probe 试候选接口）")
    return 0


def cmd_probe(a):
    s = load_session(a.session)
    if not logged_in(s):
        raise SystemExit("会话已失效，请先 login")
    print("%-52s %-6s %-8s %s" % ("路径", "HTTP", "长度", "判定"))
    found = []
    for c in CANDIDATES:
        url = abs_url(c)
        try:
            r = s.get(url, timeout=25, allow_redirects=False)
        except Exception as e:
            print("%-52s %-6s %-8s %r" % (c, "-", "-", e))
            continue
        body = r.text or ""
        # 后台未登录/无权限会给 302；控制器不存在通常 404 或返回一段 HTML 错误页
        verdict = "✅ 命中" if r.status_code == 200 and "<table" in body.lower() else \
                  ("200 但无表格" if r.status_code == 200 else
                   ("重定向(可能无权限)" if r.status_code in (301, 302) else "不存在"))
        print("%-52s %-6s %-8s %s" % (c, r.status_code, len(body), verdict))
        if r.status_code == 200:
            found.append(c)
    if a.dump_dir:
        os.makedirs(a.dump_dir, exist_ok=True)
        for c in found:
            name = c.replace("/", "_")
            with open(os.path.join(a.dump_dir, name), "w", encoding="utf-8") as f:
                f.write(s.get(abs_url(c), timeout=25).text)
        print("[dump] 已保存 %d 个命中页 → %s" % (len(found), a.dump_dir))
    return 0


def cmd_price(a):
    s = load_session(a.session)
    if not logged_in(s):
        raise SystemExit("会话已失效，请先 login")
    path = a.path
    r = s.get(abs_url(path), timeout=30,
              params={"gid[]": str(a.gid)} if a.gid else None)
    print("[price] %s?gid[]=%s -> HTTP=%s %d 字节"
          % (path, a.gid, r.status_code, len(r.text)))
    html = r.text
    if a.dump:
        with open(a.dump, "w", encoding="utf-8") as f:
            f.write(html)
        print("[dump] →", a.dump)

    # 表头 + 头几行，够看清字段名与单位
    for m in re.finditer(r"<table\b.*?</table>", html, re.S | re.I):
        tbl = m.group(0)
        ths = [re.sub(r"<[^>]+>", "", x).strip()
               for x in re.findall(r"<th\b[^>]*>(.*?)</th>", tbl, re.S | re.I)]
        if ths:
            print("\n表头：", ths)
        rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", tbl, re.S | re.I)[:6]
        for row in rows:
            tds = [re.sub(r"<[^>]+>", " ", x).strip()
                   for x in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S | re.I)]
            if any(tds):
                print("  ", [re.sub(r"\s+", " ", t) for t in tds])
    return 0


def main():
    ap = argparse.ArgumentParser(description="P2PAH 订单后台金币价格只读探针")
    ap.add_argument("mode", choices=("login", "menu", "probe", "price"))
    ap.add_argument("--session", default=os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "p2p_order_session.pkl"))
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--gid", type=int, default=922)
    ap.add_argument("--path", default="game/admin_game_price/index.html",
                    help="price 模式的控制器路径（站点根相对，不带 /admin 前缀）")
    ap.add_argument("--dump", default="")
    ap.add_argument("--dump-dir", default="")
    a = ap.parse_args()
    return {"login": cmd_login, "menu": cmd_menu, "probe": cmd_probe,
            "price": cmd_price}[a.mode](a) or 0


if __name__ == "__main__":
    sys.exit(main())
