# -*- coding: utf-8 -*-
"""从订单后台（order.p2pah.cn）读 MLB 金币 B2C 单价 —— 只读。

背景
----
老大 2026-10-12 要求：工作台「当期金币售价（USD / 100K Stub）」不要再人工填，
默认从后台自动带出。

后台位置（**已实测确认，勿凭猜改**）
----------------------------------
    订单后台 order.p2pah.cn → 游戏&产品 → 金币价格管理
      → 所属游戏 922 = MLB The Show 26 → 行内 **b2c** 字段

实测事实（2026-10-12）
--------------------
- 菜单 `金币价格管理` 的链接是
  `javascript:openapp('/game/admin_game_price/index.html','333game','金币价格管理',true)`
  ⚠️ 页面里 `WEB_ROOT = "/"` —— 路径是**站点根相对**，**不能加 `/admin/` 前缀**
     （加了就 404）。`/admin/...` 只是恰好有一个叫 admin 的模块。
- 按游戏过滤的参数是 **`?gid=922`**（普通 query）。
  ⚠️ 写 `?gid[]=922`（axios 数组风格）会被路由打成 **500**。
- 页面表格**生效列只有 7 个**：ID / 所属游戏 / 游戏区名称 / 采购成本 /
  最新采购价 / 利润率 / **b2c**。
  后面 c2c / g2g.com / eldorado.gg 三列在 HTML 里**被 `<!-- -->` 注释掉了** ——
  解析前必须**先剥注释**，否则会把注释里的 td 当成真列，列序整体错位。
- gid 也写在行的 `<td title="922">` 上，可用来校验"取到的是不是这个游戏"。

单位（★ 重要，差 100 倍会整批打偏）
--------------------------------
后台 b2c 的口径是 **USD / 1K Stub**（每千）。工作台的 `rate` 口径是
**USD / 100K Stub**，故：

    rate(USD/100K) = b2c × multiplier        （默认 multiplier = 100）

实测锚点：2026-10-12 取到 b2c = 0.0429 → 4.29 USD/100K；
技能记录里 2026-10-05 的口径是 3.89 —— 同量级、一周 +10%，一致。
（若当作 100K 直接使用，会得到 0.0429 USD/100K，比历史值低 90 倍 → 明显不成立。）

⚠️ multiplier 做成可配参数、且输出里同时回吐 `b2c` 原值与推导式，
   便于人工一眼核验；**绝不把换算藏起来**。

依赖与可测性
------------
只 import 标准库（urllib / http.cookiejar / re / json）。
`ddddocr` 在 `solve()` 内**惰性 import** —— 于是本模块可以被离线用例直接
import 并测解析函数，不会因为缺 ddddocr 而失败。

⚠️ 服务器 `/opt/python39` **没有 requests**（实测 MISS），所以这里必须用
   urllib，不能用 requests。

用法
----
    python p2pah_price.py --gid 922 --area "PS 5" --out /tmp/price.json
    python p2pah_price.py --cred _cred_order.json --json
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://order.p2pah.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

#: 金币价格管理（实测路径，站点根相对）
PRICE_PATH = "/game/admin_game_price/index.html"

#: 默认游戏：922 = MLB The Show 26（与技能 `p2pah-order-issues` 记的一致）
DEFAULT_GID = 922

#: 默认取价平台。后台按「游戏区」分 PS 5 / XBOX / Switch 三行；
#: 工作台的 rate 是单一值，所以取一行 —— 但**三个平台的差异会在结果里回吐**，
#: 不一致时置 `areas_consistent = false` 让上层提示人工确认。
DEFAULT_AREA = "PS 5"

#: b2c（USD/1K） → rate（USD/100K）
DEFAULT_MULTIPLIER = 100.0


def _log(msg):
    """诊断信息一律走 stderr —— stdout 只留给最终的 JSON。"""
    sys.stderr.write("[price] %s\n" % msg)
    sys.stderr.flush()


# ============================================================ HTML 解析（纯函数）
def strip_comments(html: str) -> str:
    """剥掉 HTML 注释。

    ⚠️ 这一步**不能省**：金币价格表里 c2c / g2g.com / eldorado.gg 三列
    是被 `<!-- -->` 注释掉的，不剥就会把它们里面的 `<td>` 一起数进来，
    7 列变 11 列、列序整体错位（本次开发时就踩了这个坑）。
    """
    return re.sub(r"<!--.*?-->", "", html or "", flags=re.S)


def _cell_text(x: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", x or "")).strip()


def parse_price_html(html: str, gid: int = DEFAULT_GID) -> dict:
    """从金币价格管理页面解析出各「游戏区」行。纯函数，离线用例直接喂 HTML。"""
    h = strip_comments(html)
    tables = re.findall(r"<table\b.*?</table>", h, re.S | re.I)
    if not tables:
        return {"ok": False, "step": "parse", "error": "页面里找不到 <table>"}

    for tbl in tables:
        head_html = re.search(r"<thead\b.*?</thead>", tbl, re.S | re.I)
        rows_html = re.findall(r"<tr\b[^>]*>(.*?)</tr>", tbl, re.S | re.I)
        if not rows_html:
            continue
        ths = [_cell_text(x) for x in
               re.findall(r"<th\b[^>]*>(.*?)</th>", head_html.group(0)
                          if head_html else rows_html[0], re.S | re.I)]
        low = [t.lower() for t in ths]
        if not any("b2c" in t for t in low):
            continue                       # 不是价格表，换下一张

        i_b2c = next(i for i, t in enumerate(low) if "b2c" in t)
        i_area = next((i for i, t in enumerate(ths)
                       if "区名称" in t or t.endswith("区")), None)
        i_id = next((i for i, t in enumerate(low) if t == "id"), 0)

        out = []
        for row in rows_html:
            tds_raw = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S | re.I)
            if not tds_raw:
                continue
            # gid 校验：行的「所属游戏」td 上带 title="922"
            m_title = re.search(r'<td\b[^>]*title="(\d+)"[^>]*>', row)
            row_gid = int(m_title.group(1)) if m_title else None
            vals = [_cell_text(x) for x in tds_raw]
            if len(vals) <= i_b2c:
                continue                   # 不是数据行（如空态行）
            out.append({
                "id": vals[i_id] if i_id < len(vals) else None,
                "gid": row_gid,
                "area": vals[i_area] if (i_area is not None and i_area < len(vals)) else None,
                "b2c": vals[i_b2c],
            })
        if not out:
            return {"ok": False, "step": "parse",
                    "error": "找到 b2c 列但没有任何数据行"}
        return {"ok": True, "headers": ths, "rows": out,
                "gid_matched": [r["gid"] for r in out if r["gid"] is not None]}
    return {"ok": False, "step": "parse",
            "error": "没有一张表带 b2c 列（表头：%s）"
                     % ([_cell_text(x) for x in
                         re.findall(r"<th\b[^>]*>(.*?)</th>",
                                    strip_comments(html), re.S | re.I)][:12])}


def pick_row(rows, area: str):
    """按「游戏区」名挑一行；挑不到就退回第一行（并在结果里标明）。"""
    for r in rows:
        if (r.get("area") or "").strip().lower() == (area or "").strip().lower():
            return r, "exact"
    return (rows[0], "fallback") if rows else (None, "none")


def build_result(parsed: dict, gid: int, area: str, multiplier: float) -> dict:
    """把解析结果收敛成上层要的口径。**纯函数**。"""
    rows = parsed.get("rows") or []
    row, how = pick_row(rows, area)
    if not row:
        return {"ok": False, "step": "parse", "error": "没有任何游戏区行"}
    try:
        b2c = float(row["b2c"])
    except (TypeError, ValueError):
        return {"ok": False, "step": "parse",
                "error": "b2c 不是数字：%r" % row.get("b2c")}

    # 三个平台是否一致 —— 不一致时上层要提示人工确认，不能默默取一个
    uniq = sorted({str(r.get("b2c")) for r in rows})
    return {
        "ok": True,
        "source": "order.p2pah.cn" + PRICE_PATH,
        "gid": gid,
        "area": row.get("area"),
        "area_match": how,
        "row_id": row.get("id"),
        "b2c": b2c,
        "b2c_unit": "USD/1K",
        "multiplier": multiplier,
        # ★ 换算过程显式写出来，页面上直接展示，错了能一眼看见
        "formula": "%s(USD/1K) × %s = %s(USD/100K)" % (b2c, multiplier,
                                                       round(b2c * multiplier, 4)),
        "rate_usd_per_100k": round(b2c * multiplier, 4),
        "rows": rows,
        "areas_consistent": len(uniq) <= 1,
        "areas": uniq,
    }


# ============================================================ 网络
def _opener(cookiejar=None, allow_redirect=True):
    ctx = ssl.create_default_context()
    handlers = [urllib.request.HTTPSHandler(context=ctx),
                urllib.request.ProxyHandler({})]      # 强制直连，绕开系统代理
    if cookiejar is not None:
        handlers.append(urllib.request.HTTPCookieProcessor(cookiejar))
    if not allow_redirect:
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None
        handlers.append(_NoRedirect())
    return urllib.request.build_opener(*handlers)


def _get(opener, url, *, referer=None, timeout=30, binary=False):
    h = {"User-Agent": UA,
         "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
         "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    if referer:
        h["Referer"] = referer
    req = urllib.request.Request(url, headers=h, method="GET")
    with opener.open(req, timeout=timeout) as r:
        raw = r.read()
        return raw if binary else raw.decode("utf-8", "replace")


def solve_captcha(png: bytes) -> str:
    """ddddocr 过码（惰性 import，缺库时报明确的错）。"""
    try:
        import ddddocr
    except Exception as e:                             # noqa: BLE001
        raise RuntimeError("缺少 ddddocr，无法自动过验证码：%r" % e)
    code = (ddddocr.DdddOcr(show_ad=False).classification(png) or "").strip()
    return code


def login(opener, user: str, password: str, *, tries: int = 3) -> None:
    """走后台自己的登录流程。失败即抛，**不无限重试**（避免触发账号锁定）。"""
    # 1) 先建立会话：不带 cookie 时 / 与 /login.html 会互相 302，
    #    所以先打一次 / 拿 PHPSESSID，再访问 /login.html。
    _get(opener, BASE + "/", timeout=30)
    html = _get(opener, BASE + "/login.html", timeout=30)
    if "dologin" not in html:
        raise RuntimeError("登录页异常（未含 dologin 表单），可能被 IP 白名单拦")
    last = None
    for n in range(1, tries + 1):
        png = _get(opener, BASE + "/new_captcha.html?height=32&width=150&font_size=18",
                   referer=BASE + "/login.html", binary=True)
        code = solve_captcha(png)
        if not re.fullmatch(r"[0-9A-Za-z]{3,6}", code or ""):
            _log("第 %d 次：识别结果异常 %r，换一张" % (n, code))
            last = "OCR 结果异常 %r" % code
            continue
        _log("第 %d 次：验证码识别为 %s" % (n, code))
        body = urllib.parse.urlencode({
            "username": user, "password": password, "captcha": code,
            "_captcha_id": "", "redirect": "",
        }).encode("utf-8")
        req = urllib.request.Request(
            BASE + "/admin/public/dologin.html", data=body,
            headers={"User-Agent": UA, "Referer": BASE + "/login.html",
                     "Origin": BASE, "X-Requested-With": "XMLHttpRequest",
                     "Content-Type":
                         "application/x-www-form-urlencoded; charset=UTF-8"},
            method="POST")
        with opener.open(req, timeout=30) as r:
            txt = r.read().decode("utf-8", "replace")
        try:
            j = json.loads(txt)
        except Exception:                              # noqa: BLE001
            raise RuntimeError("登录响应不是 JSON：%r" % txt[:160])
        if j.get("code") == 1:
            _log("登录成功")
            return
        last = j.get("msg")
        if "验证码" not in str(j.get("msg")):
            # 密码错 / 被锁等 —— 立刻停，绝不继续试（可能把账号试锁）
            raise RuntimeError("登录失败（非验证码原因，已停止重试）：%r" % j)
        _log("  验证码被判定错误，换一张重试")
        time.sleep(0.5)
    raise RuntimeError("验证码连续失败：%s" % last)


def fetch_rows(*, user, password, gid=DEFAULT_GID, timeout=40) -> dict:
    cj = http.cookiejar.CookieJar()
    op = _opener(cookiejar=cj)
    login(op, user, password)
    url = "%s%s?gid=%d" % (BASE, PRICE_PATH, gid)
    # ⚠️ 参数必须是 `?gid=922`。写成 `?gid[]=922` 会被路由打成 500（实测）。
    html = _get(op, url, referer=BASE + "/admin/index/index.html", timeout=timeout)
    return parse_price_html(html, gid)


def load_cred(path: str) -> dict:
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="读 MLB 金币 B2C 单价（只读）")
    ap.add_argument("--gid", type=int, default=DEFAULT_GID)
    ap.add_argument("--area", default=DEFAULT_AREA)
    ap.add_argument("--multiplier", type=float, default=DEFAULT_MULTIPLIER)
    ap.add_argument("--cred", default="",
                    help="凭据 JSON：{P2PAH_ORDER_USERNAME, P2PAH_ORDER_PASSWORD}")
    ap.add_argument("--timeout", type=float, default=40)
    ap.add_argument("--out", default="", help="把结果 JSON 写到该文件")
    ap.add_argument("--json", action="store_true", help="把结果 JSON 打到 stdout")
    ap.add_argument("--html", default="",
                    help="不联网，直接解析一个本地 HTML（离线自检用）")
    a = ap.parse_args()

    started = time.time()
    try:
        if a.html:
            parsed = parse_price_html(open(a.html, encoding="utf-8").read(), a.gid)
        else:
            cred = load_cred(a.cred)
            user = (cred.get("P2PAH_ORDER_USERNAME")
                    or os.environ.get("P2PAH_ORDER_USER")
                    or os.environ.get("P2PAH_ORDER_USERNAME") or "")
            password = (cred.get("P2PAH_ORDER_PASSWORD")
                        or os.environ.get("P2PAH_ORDER_PASS")
                        or os.environ.get("P2PAH_ORDER_PASSWORD") or "")
            if not user or not password:
                raise RuntimeError("缺少凭据：--cred 或环境变量 "
                                   "P2PAH_ORDER_USERNAME / P2PAH_ORDER_PASSWORD")
            parsed = fetch_rows(user=user, password=password, gid=a.gid,
                                timeout=a.timeout)
        result = build_result(parsed, a.gid, a.area, a.multiplier) \
            if parsed.get("ok") else parsed
    except Exception as e:                             # noqa: BLE001 —— 兜住一切
        result = {"ok": False, "step": "exception",
                  "error": "%s: %s" % (type(e).__name__, e)}

    result["gid"] = result.get("gid", a.gid)
    result["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    result["elapsed_sec"] = round(time.time() - started, 1)

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        _log("结果 → %s" % a.out)
    if a.json or not a.out:
        # stdout 只出 JSON —— 上层直接 json.loads(stdout) 就能用
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
        sys.stdout.write("\n")
    if result.get("ok"):
        _log("OK  b2c=%s %s  %s" % (result.get("b2c"), result.get("b2c_unit"),
                                    result.get("formula")))
    else:
        _log("失败 @%s：%s" % (result.get("step"), result.get("error")))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
