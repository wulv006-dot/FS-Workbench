# -*- coding: utf-8 -*-
"""
mlb_agent.py —— MLB 新卡上架「本机执行器」

跑在能过 Cloudflare、且能装 Playwright 的机器上（默认就是你的办公电脑）。
它轮询服务器的任务队列，领到任务后：
  1. 用 Playwright 起真实 Chrome 访问 showdd，抓最新批次的新卡
  2. 对每张候选卡连续采样 3 次官方 Buy Now，每次间隔 >= 120 秒
  3. 取中位数，按公式算售价，过滤掉 < $0.50 的
  4. 追加写入 Excel 模板（严格保留原文件名/扩展名/工作表/旧行）
  5. 校验后把结果 + Excel（base64）回传给服务器

为什么抓取要放在本机：
  旧服务器出口 IP 47.253.252.55 是阿里云机房段，访问 showdd.io 曾命中
  Cloudflare 的 chl_page JS 挑战；本机住宅 IP 直接 200 拿到真页面。
  实测请求头完全一致，唯一变量是出口 IP。故采集留在本机。

用法：
  # 先装依赖
  pip install -r requirements.txt
  python -m playwright install chromium     # 或直接用本机已装的 Chrome/Edge

  # 常驻轮询（推荐，挂着就行）
  python mlb_agent.py --server https://47.85.224.112 --user wulv \
      --agent wulv-pc --workdir "D:\\MLB工作目录"

  # 只跑一次（调试）
  python mlb_agent.py ... --once

  # 本地自测：不走服务器，直接抓一批
  python mlb_agent.py ... --self-test --rate 3.89
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import statistics
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

SHOWDD_UPDATES = "https://www.showdd.io/26/updates"
SHOWDD_ROOT = "https://www.showdd.io"
AGENT_VERSION = "mlb-agent/1.1"
DEFAULT_INTERVAL = 120
FLOOR = Decimal("0.50")
MARKUP = Decimal("1.1")

HEADERS = [
    "游戏", "服务区", "产品分类", "产品名称", "图标地址", "单价", "折扣",
    "最小购买量", "收货价格(¥)", "是否推荐", "是否热门", "是否启用",
    "产品摘要", "产品描述", "扩展属性", "分类ID（勿改）",
]


# ==========================================================================
# 网络：跟服务器说话
# ==========================================================================
class Hub:
    """和执行器宿主机打交道。

    认证方式说明（重要）
    ---------------------------------------------------------
    2026-09-30 起，MMOEXP 门户全站把 nginx `auth_basic` 换成了
    `auth_request` + 签名 Cookie 会话（服务 127.0.0.1:8895）。

    这意味着：**HTTP Basic Auth 已经彻底失效**。用 Basic 头去访问
    /mlb/api/* 只会拿到 302 跳登录页，而不是 401 —— 表现为 JSON 解析
    失败（"Expecting value: line 1 column 1"），极难从表象看出是认证问题。

    所以这里改成：先 POST /__auth/login 拿签名 Cookie，之后所有请求
    都带上它。Cookie 名称与 TTL 由门户下发，这里只做解析和透传。
    Basic Auth 保留为兜底分支（万一某天又切回去）。
    """

    #: 门户登录端点（相对站点根）
    AUTH_LOGIN = "/__auth/login"

    def __init__(self, base, user, password, timeout=60, log=None):
        self.site = self._normalize_site(base)
        self.base = self.site + "/mlb"
        self.user = user
        self.password = password
        self.timeout = timeout
        self.log = log or (lambda m: None)
        self.cookie = ""          # 形如 "MMOEXP_AUTH=xxxx"
        self._use_basic = False   # 兜底：Cookie 拿不到时退回 Basic

    @staticmethod
    def _normalize_site(base):
        """把 --server 归一化成【站点根 + HTTPS】（不带 /mlb）。

        服务挂在 nginx 的 /mlb/ 前缀下，API 实际路径是 /mlb/api/xxx。
        用户通常只写 47.85.224.112（不带前缀），这里统一处理，
        避免出现 /api/heartbeat -> 404 这种一眼看不出原因的失败。
        已经带了 /mlb 的地址会被剥掉前缀，因为登录入口在站点根下。

        2026-10-12：nginx 对 location /__auth/ 加了
            if ($scheme = http) { return 308 https://47.85.224.112$request_uri; }
        门户 Cookie 又是 secure_cookie=True，所以走 HTTP 时登录请求
        根本到不了门户（在 nginx 就被 308 拦掉），表现为
        「HTTP 303/308 被重定向到登录页」。因此这里强制升级成 HTTPS。
        """
        b = (base or "").strip().rstrip("/")
        if not b:
            return b
        if not b.startswith(("http://", "https://")):
            b = "https://" + b
        if b.endswith("/mlb"):
            b = b[:-4].rstrip("/")
        if b.startswith("http://"):
            b = "https://" + b[len("http://"):]
        return b

    # 自签名/IP 证书在部分 Python 构建上会校验失败，
    # 这里给一个不校验的 SSL 上下文兜底（服务器用的是 Let's Encrypt
    # 正规证书，IP 已在 SAN 里，正常不会走到这里）。
    @staticmethod
    def _ssl_context():
        import ssl
        try:
            return ssl.create_default_context()
        except Exception:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx

    def _opener(self):
        """统一构造「不自动跟随重定向」的 opener。"""
        hub = self

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        handlers = [_NoRedirect()]
        if self.site.startswith("https://"):
            handlers.append(urllib.request.HTTPSHandler(context=self._ssl_context()))
        # 强制直连，绕开系统/环境里的 HTTP 代理。
        # 站点是固定 IP 的公网服务器，走代理既慢又会拿到 502。
        handlers.append(urllib.request.ProxyHandler({}))
        return urllib.request.build_opener(*handlers)

    # ---------------- 手动登录（浏览器兜底） ----------------
    def login_manual(self, timeout=300):
        """打开真实 Chrome 让人手动登录，然后把 Cookie 接管过来。

        场景：账号密码登录被门户拒绝（改密、锁定、SSO、验证码等），
        但人在浏览器里手动能登进去。门户 Cookie 是 HttpOnly + Secure，
        Playwright 只能从 context 里读出来，拿不到也没关系——
        我们要的只是 "name=value" 这段字符串，转给 urllib 用。

        返回 True 表示成功拿到 Cookie。
        """
        if sync_playwright is None:
            self.log("[X] 没装 Playwright，无法手动登录："
                     "pip install playwright && python -m playwright install chromium")
            return False

        self.log("=" * 60)
        self.log("  手动登录模式")
        self.log("  即将弹出 Chrome 窗口打开 %s%s" % (self.site, self.AUTH_LOGIN))
        self.log("  请在窗口里自己输入账号密码并登录，登录成功后本程序会自动接管。")
        self.log("  超时 %s 秒。浏览器Profile 会复用，Cookie 有效期 30 天（记住登录）。" % timeout)
        self.log("=" * 60)

        # 单独一个 profile，避免污染 showdd 采集用的浏览器登录态
        profile = Path.home() / "MLB新卡上架" / "portal_profile"
        profile.mkdir(parents=True, exist_ok=True)

        pw = None
        ctx = None
        try:
            exe = find_local_browser()
            pw = sync_playwright().start()
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                executable_path=str(exe),
                headless=False,
                viewport={"width": 1100, "height": 800},
                args=["--disable-blink-features=AutomationControlled",
                      "--no-first-run", "--no-default-browser-check",
                      "--start-maximized"],
                ignore_https_errors=True,
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(self.site + self.AUTH_LOGIN, wait_until="domcontentloaded")

            deadline = time.time() + timeout
            done = False
            while time.time() < deadline:
                cookies = ctx.cookies()
                hit = None
                for c in cookies:
                    if c.get("name") == "MMOEXP_AUTH" and c.get("value"):
                        hit = c
                        break
                if hit:
                    self.cookie = "%s=%s" % (hit["name"], hit["value"])
                    self.log("[OK] 已从浏览器接管会话 Cookie：MMOEXP_AUTH=***")
                    done = True
                    break
                # 人已经登进去了（登录后一般会跳到 next 或 dashboard）
                try:
                    url_now = page.url
                except Exception:
                    url_now = ""
                if url_now and "/__auth/login" not in url_now:
                    cookies = ctx.cookies()
                    for c in cookies:
                        if c.get("name") == "MMOEXP_AUTH" and c.get("value"):
                            self.cookie = "%s=%s" % (c["name"], c["value"])
                            self.log("[OK] 页面已进入 %s，接管会话 Cookie 成功" % url_now)
                            done = True
                            break
                    if done:
                        break
                page.wait_for_timeout(1000)

            if not done:
                self.log("[X] 手动登录超时（%s 秒内没检测到 MMOEXP_AUTH Cookie）" % timeout)
                self.log("    常见原因：没点登录 / 登录报错了 / 账号被锁 / 门户要求额外验证")
                return False

            # 立刻验证一次：拿不到能用的会话就没意义
            try:
                self._req("/api/health", _retry=False)
                self.log("[OK] 会话校验通过，服务器认这个 Cookie")
                return True
            except Exception as e:
                self.log("[!] Cookie拿到了但校验没过：%s" % e)
                return False
        except Exception as e:
            self.log("[X] 手动登录出错：%s" % e)
            return False
        finally:
            try:
                if ctx:
                    ctx.close()
            except Exception:
                pass
            try:
                if pw:
                    pw.stop()
            except Exception:
                pass

    # ---------------- 登录 ----------------
    def _url(self, path):
        """把站点根路径补全成绝对 URL。path 以 / 开头。"""
        if self.site.startswith(("http://", "https://")):
            return self.site + path
        return self.site + path

    def login(self):
        """用账号密码换签名 Cookie。

        返回 True 表示拿到 Cookie；False 表示登录失败（会打印原因）。
        """
        if not self.user or not self.password:
            return False

        form = urllib.parse.urlencode({
            "username": self.user,
            "password": self.password,
            "remember": "1",          # 勾 30 天，避免频繁重登
            "next": "/mlb/",
        }).encode("utf-8")

        req = urllib.request.Request(
            self._url(self.AUTH_LOGIN), data=form, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        # 门户把登录失败做成 302 -> /login?err=bad，而不是 4xx。
        # 必须自己看 Location，否则「登录失败」会被当成「登录成功」。
        opener = self._opener()
        try:
            resp = opener.open(req, timeout=self.timeout)
            code, headers = resp.status, resp.headers
        except urllib.error.HTTPError as e:
            code, headers = e.code, e.headers
        except Exception as e:
            self.log("登录请求失败：%s" % e)
            return False

        # 从 Set-Cookie 里挑出会话 Cookie
        raw_cookies = []
        try:
            raw_cookies = headers.get_all("Set-Cookie") or []
        except Exception:
            sc = headers.get("Set-Cookie")
            raw_cookies = [sc] if sc else []

        for sc in raw_cookies:
            head = sc.split(";", 1)[0].strip()
            if "=" in head and not head.endswith("="):
                self.cookie = head
                self.log("已登录，拿到会话 Cookie：%s=***" % head.split("=", 1)[0])
                return True

        # 没拿到 Cookie：看 Location 判断具体原因
        loc = headers.get("Location", "") or ""
        reason = "未知"
        if "err=bad" in loc:
            reason = "账号或密码不对"
        elif "err=locked" in loc:
            reason = "尝试次数过多，账号/IP 被临时锁定（约 5 分钟）"
        elif "err=noperm" in loc:
            reason = "账号没有该模块权限"
        elif code in (301, 302, 303, 307, 308):
            reason = "被重定向到 %s（多半是未登录或密码错误）" % loc
        if code == 308:
            reason = ("被 308 强制跳 HTTPS（%s）。"
                      "请把 --server 写成 https://开头" % loc)
        elif code == 303:
            reason = ("被 303 重定向到 %s —— 门户 Cookie 是 Secure，"
                      "必须全程走 HTTPS；确认 --server 是 https:// 开头" % loc)
        self.log("[X] 登录失败（HTTP %s）：%s" % (code, reason))
        return False

    def _ensure_auth(self):
        """第一次用的时候自动登录一次。"""
        if self.cookie or self._use_basic or not self.user:
            return
        if not self.login():
            self.log("[!] 拿不到会话 Cookie，退回 Basic Auth 重试"
                     "（若仍失败，说明门户已不再支持 Basic）")
            self._use_basic = True

    def _req(self, path, method="GET", body=None, raw=False, _retry=True):
        self._ensure_auth()
        url = self.base + path
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json; charset=utf-8")
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        elif self.user:
            tok = base64.b64encode(("%s:%s" % (self.user, self.password)).encode()).decode()
            req.add_header("Authorization", "Basic " + tok)

        # 不允许自动跟随 302：跟随会把跳登录页当成成功，
        # 然后 JSON 解析报 "Expecting value: line 1 column 1"，
        # 完全看不出真正原因是「没登录」。
        opener = self._opener()
        try:
            resp = opener.open(req, timeout=self.timeout)
            code = resp.status
            payload = resp.read()
            loc = resp.headers.get("Location", "")
        except urllib.error.HTTPError as e:
            code, loc = e.code, e.headers.get("Location", "")
            payload = b""
            try:
                payload = e.read()
            except Exception:
                pass

            # 会话过期 -> 重新登录一次再试（只重试一次，避免死循环）
            if code in (302, 303) and _retry and self.user:
                self.log("会话可能已过期（被重定向），重新登录…")
                self.cookie = ""
                if self.login():
                    return self._req(path, method, body, raw, _retry=False)

            hint = ""
            if code in (301, 302, 303, 307, 308):
                hint = ("（被跳转到 %s —— 认证没通过："
                        "没有凭据 / 账号密码不对 / 不在 dashboard 组）"
                        % (loc or "登录页"))
            elif code == 401:
                hint = "（登录凭据不对或会话失效）"
            elif code == 403:
                hint = "（账号没有该模块权限，或 IP 被限制）"
            elif code == 404:
                hint = "（路径不对：确认 --server 指向的站点已部署 /mlb/）"
            elif code >= 500:
                hint = "（服务器内部错误：去看 journalctl -u mlb-online）"
            raise RuntimeError("请求 %s 失败：HTTP %s %s %s"
                               % (path, code, e.reason, hint)) from e
        except urllib.error.URLError as e:
            raise RuntimeError("连不上 %s：%s（检查网络 / 服务器是否在跑）"
                               % (url, e.reason)) from e

        # 200 但被跳转到登录页 = 认证其实没过
        if code in (301, 302, 303, 307, 308):
            if _retry and self.user:
                self.log("被重定向到 %s，重新登录…" % loc)
                self.cookie = ""
                if self.login():
                    return self._req(path, method, body, raw, _retry=False)
            raise RuntimeError(
                "请求 %s 被重定向到 %s —— 认证没通过。"
                "请核对账号密码（--user/--password 或 .mlb_pass）。"
                % (path, loc or "(未提供 Location)"))

        if raw:
            return payload
        txt = payload.decode("utf-8", "replace")
        if not txt.strip():
            return None
        try:
            return json.loads(txt)
        except ValueError:
            raise RuntimeError(
                "请求 %s 返回的不是 JSON（前 120 字：%r）。"
                "常见原因：被 nginx 拦在登录页 / 服务没起来 / 路径不对。"
                % (path, txt[:120]))

    def heartbeat(self, name, version, note=""):
        import socket
        return self._req("/api/heartbeat", "POST", {
            "agent": name, "version": version,
            "note": note, "host": socket.gethostname(),
        })

    def claim(self, name):
        return self._req("/api/claim", "POST", {"agent": name})

    def progress(self, tid, prog):
        return self._req("/api/tasks/%s/progress" % tid, "POST", {"progress": prog})

    def result(self, tid, status, result, error=None, agent=None):
        return self._req("/api/tasks/%s/result" % tid, "POST", {
            "status": status, "result": result, "error": error, "agent": agent,
        })

    def agent_config(self):
        return self._req("/api/agent-config")


# ==========================================================================
# 数据模型
# ==========================================================================
class Card:
    __slots__ = ("name", "ovr", "team", "position", "series", "card_hash",
                 "player_url", "samples", "median", "sale_price", "status",
                 "include", "rate")

    def __init__(self, name, ovr, team, position, series, card_hash, player_url=""):
        self.name = name
        self.ovr = ovr
        self.team = team
        self.position = position
        self.series = series
        self.card_hash = card_hash
        self.player_url = player_url
        self.samples = []
        self.median = None
        self.sale_price = None
        self.status = "待采样"
        self.include = False
        self.rate = None          # 本次任务使用的金币售价，校验时独立复算用

    @property
    def product_name(self):
        return "%s/%s/%s/%s/%s" % (self.name, self.ovr, self.position, self.team, self.series)

    def to_dict(self):
        return {
            "name": self.name, "ovr": self.ovr, "team": self.team,
            "position": self.position, "series": self.series,
            "hash": self.card_hash,
            "samples": self.samples, "median": self.median,
            "sale_price": str(self.sale_price) if self.sale_price is not None else None,
            "product_name": self.product_name,
            "status": self.status, "include": self.include,
        }


def parse_stub_value(cell):
    """把 '38,000' / '38 000' / '' 解析成整数。取不到返回 None（绝不用 0 顶替）。"""
    if not cell:
        return None
    m = re.search(r"([\d][\d,\s]*)", str(cell))
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group(1))
    return int(digits) if digits else None


def parse_dom_market_rows(rows):
    """把 showdd 更新页的表格行解析成 {hash: Card}。"""
    cards = {}
    for row in rows:
        item_url = row.get("item_url") or ""
        hm = re.search(r"/items/([0-9a-f]{32})", item_url, re.IGNORECASE)
        if not hm:
            continue
        name = (row.get("name") or "").strip()
        if not name:
            continue
        card_text = re.sub(r"\s+", " ", row.get("card_text") or "").strip()
        while card_text.casefold().startswith(name.casefold()):
            card_text = card_text[len(name):].strip()
        m = re.match(
            r"(?P<ovr>\d+)\s+(?P<team>.+?)\s+•\s+(?P<pos>[A-Z0-9]+)\s+(?P<series>.+)$",
            card_text)
        if not m:
            continue
        card_hash = hm.group(1).lower()
        card = Card(name=name, ovr=int(m.group("ovr")),
                    team=m.group("team").strip(), position=m.group("pos").strip(),
                    series=m.group("series").strip(), card_hash=card_hash,
                    player_url=row.get("player_url") or "")
        # showdd 的 Sell 列 = 官方 Buy Now = 进货成本
        buy_now = parse_stub_value(row.get("sell_text"))
        if buy_now is not None:
            card.samples.append(buy_now)
        cards[card_hash] = card
    return cards


# ==========================================================================
# 浏览器采集
# ==========================================================================
def find_local_browser():
    cands = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    import shutil
    for cmd in ("chrome", "msedge"):
        got = shutil.which(cmd)
        if got:
            cands.insert(0, got)
    for c in cands:
        if os.path.isfile(c):
            return Path(c)
    raise FileNotFoundError("未找到 Chrome / Edge，请先安装其一")


class Browser:
    """真实 Chrome 抓 showdd。用持久化 profile 让 Cloudflare 的通行证能留下来。"""

    def __init__(self, cancel_flag=None, show=False, log=print, profile_dir=None):
        if sync_playwright is None:
            raise RuntimeError("Playwright 未安装：pip install playwright && python -m playwright install chromium")
        self.cancel_flag = cancel_flag
        self.show = show
        self.log = log
        self.profile_dir = Path(profile_dir or (Path.home() / "MLB新卡上架" / "browser_profile"))
        self.exe = find_local_browser()
        self.pw = None
        self.ctx = None
        self.page = None

    def __enter__(self):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.pw = sync_playwright().start()
        self.ctx = self.pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            executable_path=str(self.exe),
            headless=not self.show,
            viewport={"width": 1360, "height": 900},
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-default-apps", "--no-first-run",
                  "--no-default-browser-check"],
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        # 统一默认超时：任何没显式指定 timeout 的调用都有上限，
        # 防止页面卡住时整个采集流程被永久挂起。
        self.page.set_default_timeout(20000)
        self.page.set_default_navigation_timeout(120000)
        return self

    def __exit__(self, *exc):
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self.pw:
                self.pw.stop()

    def _body_text(self):
        """读 body 文本，失败返回空串（用于判断文案，不该因读不到就崩）。"""
        try:
            return self.page.locator("body").inner_text(timeout=10000)
        except Exception:
            return ""

    def _navigate(self, url):
        if self.cancel_flag and self.cancel_flag():
            raise InterruptedError("用户取消")
        # 页面级默认超时：让所有未显式传 timeout 的调用（含 page.title()）都有上限，
        # 避免页面无响应时永久挂住。
        try:
            self.page.set_default_timeout(20000)
        except Exception:
            pass
        self.page.goto(url, wait_until="domcontentloaded", timeout=120000)
        reported = False
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                title = self.page.title()
                body = self.page.locator("body").inner_text(timeout=10000)
            except Exception as e:
                # 单次探测失败（超时/页面重建中）不应中断整个流程，继续轮询
                if self.cancel_flag and self.cancel_flag():
                    raise InterruptedError("用户取消")
                self.log("页面探测暂时失败（%s），继续等待…"
                         % str(e).split("\n")[0][:80])
                time.sleep(2)
                continue
            blocked = ("Just a moment" in title
                       or "Enable JavaScript and cookies" in body
                       or "Verify you are human" in body)
            if not blocked:
                self.page.wait_for_timeout(1200)
                return
            if not reported:
                if not self.show:
                    raise RuntimeError(
                        "网站要求人工验证。请用 --show 参数重跑，在弹出的浏览器里点一下验证。\n"
                        "（通过一次后 profile 会记住，后续通常不再要求）")
                self.log("检测到网页验证，请在弹出的浏览器窗口中完成验证")
                reported = True
            time.sleep(1)
        raise TimeoutError("等待网页验证超时（%s）" % url)

    def latest_update_url(self):
        self._navigate(SHOWDD_UPDATES)
        hrefs = self.page.locator('a[href^="/26/updates/"]').evaluate_all(
            "els => els.map(el => el.getAttribute('href'))")
        for h in hrefs:
            if h and re.fullmatch(r"/26/updates/\d{1,2}-\d{1,2}-\d{2}", h):
                return SHOWDD_ROOT + h
        raise ValueError("无法从 showdd 更新列表识别最新批次")

    def collect(self, update_url):
        self._navigate(update_url)
        if "Update not found" in self._body_text():
            raise ValueError("指定的更新批次不存在：%s" % update_url)
        hrefs = self.page.locator('a[href*="page="]').evaluate_all(
            "els => els.map(el => el.getAttribute('href'))")
        pages = [int(m.group(1)) for h in hrefs
                 if h and (m := re.search(r"[?&]page=(\d+)", h))]
        page_count = max(pages, default=1)
        merged = {}
        for pno in range(1, page_count + 1):
            if pno > 1:
                self._navigate("%s?sort=overall-desc-1&page=%d#pagination" % (update_url, pno))
            self.page.locator("table").last.wait_for(state="visible", timeout=60000)
            rows = self.page.locator("table").last.locator("tbody tr").evaluate_all(
                """
                rows => rows.map(row => {
                  const cells = [...row.querySelectorAll('td')];
                  const player = row.querySelector('a[href^="/26/player/"]');
                  const item = row.querySelector('a[href*="mlb26.theshow.com/items/"]');
                  const images = [...(cells[0]?.querySelectorAll('img[alt]') || [])];
                  const nameImage = images.find(img => !/overall|stubs/i.test(img.alt || ''));
                  return {
                    card_text: cells[0]?.innerText || '',
                    sell_text: cells[3]?.innerText || '',
                    name: nameImage?.alt || '',
                    player_url: player?.href || '',
                    item_url: item?.href || ''
                  };
                })""")
            merged.update(parse_dom_market_rows(rows))
        return merged


# ==========================================================================
# Excel 写入
# ==========================================================================
def validate_template(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, keep_vba=str(path).lower().endswith(".xlsm"))
    target = None
    for ws in wb.worksheets:
        row1 = [ws.cell(row=1, column=i + 1).value for i in range(len(HEADERS))]
        norm = [str(v).strip() if v is not None else "" for v in row1]
        if norm == HEADERS:
            target = ws
            break
    if target is None:
        raise ValueError("在 %s 里找不到表头匹配的工作表（需要 16 列表头精确匹配）"
                         % os.path.basename(path))
    existing = 0
    for r in range(2, target.max_row + 1):
        if target.cell(row=r, column=4).value:
            existing += 1
    return {"sheet": target.title, "existing": existing,
            "type": "xlsm" if str(path).lower().endswith(".xlsm") else "xlsx"}


def write_output(template_path, cards, icon_base="https://cards.theshow.com/mlb26/"):
    from openpyxl import load_workbook
    from copy import copy
    is_vba = str(template_path).lower().endswith(".xlsm")
    wb = load_workbook(template_path, keep_vba=is_vba)

    target = None
    for ws in wb.worksheets:
        row1 = [str(ws.cell(row=1, column=i + 1).value or "").strip()
                for i in range(len(HEADERS))]
        if row1 == HEADERS:
            target = ws
            break
    if target is None:
        raise ValueError("找不到表头匹配的工作表")

    # 已有商品名与 hash（去重依据）
    existing_names, existing_hashes = set(), set()
    for r in range(2, target.max_row + 1):
        nm = target.cell(row=r, column=4).value
        if nm:
            existing_names.add(str(nm).strip().casefold())
        for col in (5, 15):
            v = target.cell(row=r, column=col).value
            if v:
                for h in re.findall(r"[0-9a-f]{32}", str(v), re.IGNORECASE):
                    existing_hashes.add(h.lower())

    # 起始行：第 2 行是空占位行就直接用，否则追加到末尾
    start = target.max_row + 1
    r2_name = target.cell(row=2, column=4).value
    if not r2_name and target.max_row >= 2:
        start = 2

    added, dup = 0, 0
    row = start
    for card in cards:
        if not card.include:
            continue
        pname = card.product_name
        if pname.casefold() in existing_names or card.card_hash.lower() in existing_hashes:
            dup += 1
            continue
        values = [
            "MLB 26",                    # 1 游戏
            None,                        # 2 服务区
            "Players",                   # 3 产品分类
            pname,                       # 4 产品名称
            "%s%s-baked-sm.webp" % (icon_base, card.card_hash),  # 5 图标地址
            float(card.sale_price),      # 6 单价
            100,                         # 7 折扣
            1,                           # 8 最小购买量
            None,                        # 9 收货价格(¥)
            0,                           # 10 是否推荐
            0,                           # 11 是否热门
            1,                           # 12 是否启用
            None, None,                  # 13/14 摘要/描述
            "zh_title=%s" % card.card_hash,  # 15 扩展属性
            8233,                        # 16 分类ID（勿改）
        ]
        for i, v in enumerate(values, start=1):
            target.cell(row=row, column=i).value = v
        # 沿用上一行的样式，避免新行没有边框
        if row > 2:
            for i in range(1, len(HEADERS) + 1):
                try:
                    target.cell(row=row, column=i)._style = copy(
                        target.cell(row=row - 1, column=i)._style)
                except Exception:
                    pass
        existing_names.add(pname.casefold())
        existing_hashes.add(card.card_hash.lower())
        added += 1
        row += 1

    out = Path(template_path)
    wb.save(out)          # 原文件名、原扩展名就地保存
    return out, added, dup


def verify_output(path, cards, sheet_name):
    """交付前的强制检查。任何一项不过就报错，不静默放过。"""
    from openpyxl import load_workbook
    is_vba = str(path).lower().endswith(".xlsm")
    wb = load_workbook(path, keep_vba=is_vba)
    problems = []
    if sheet_name not in wb.sheetnames:
        problems.append("工作表 %s 丢失" % sheet_name)
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.worksheets[0]
    row1 = [str(ws.cell(row=1, column=i + 1).value or "").strip()
            for i in range(len(HEADERS))]
    if row1 != HEADERS:
        problems.append("表头被改动")

    seen_names, seen_hashes = set(), set()
    for r in range(2, ws.max_row + 1):
        nm = ws.cell(row=r, column=4).value
        if not nm:
            continue
        key = str(nm).strip().casefold()
        if key in seen_names:
            problems.append("第 %d 行产品名称重复：%s" % (r, nm))
        seen_names.add(key)
        icon = ws.cell(row=r, column=5).value
        ext = ws.cell(row=r, column=15).value
        if icon and ext:
            hi = re.search(r"([0-9a-f]{32})", str(icon), re.IGNORECASE)
            he = re.search(r"([0-9a-f]{32})", str(ext), re.IGNORECASE)
            if hi and he and hi.group(1).lower() != he.group(1).lower():
                problems.append("第 %d 行图标 hash 与扩展属性不一致" % r)
            if hi:
                if hi.group(1).lower() in seen_hashes:
                    problems.append("第 %d 行 hash 重复：%s" % (r, hi.group(1)))
                seen_hashes.add(hi.group(1).lower())
        disc = ws.cell(row=r, column=7).value
        if disc != 100 and nm:
            problems.append("第 %d 行折扣不是 100（实际 %r）" % (r, disc))

    # 独立重算单价
    for card in cards:
        if not card.include or card.median is None:
            continue
        expect = (Decimal(card.median) / Decimal("100000") * Decimal(str(card.rate))
                  * MARKUP).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if card.sale_price != expect:
            problems.append("%s 单价不符：%s != %s" % (card.name, card.sale_price, expect))

    if problems:
        raise ValueError("交付前校验未通过：\n  - " + "\n  - ".join(problems))
    return True


# ==========================================================================
# 主流程
# ==========================================================================
# 模板常见存放处（按优先级）。产品模板由运营在 mmoexp 后台导出，落在
# 「桌面\产品模型\<游戏>\mould-create_*.xlsx/.xlsm」；老大的习惯是放在
# 那里而不是工作目录，所以把它们纳入自动发现范围，省得每次手动复制。
# 2026-10-05 实测：因为只扫工作目录，首次运行直接报「没有可用的 Excel 模板」。
_TEMPLATE_DIRS = (
    "~/MLB新卡上架",
    "~/Desktop/产品模型/MLB",
    "~/Desktop/产品模型",
    "~/Documents/MLB新卡上架工具/generated",
)


def _template_candidates(wd):
    """列出所有可用的模板候选路径，工作目录优先，其后是常用存放目录。"""
    out = []
    seen = set()

    # 1) 工作目录（含网页刚下发落盘的）
    for p in sorted(wd.glob("mould-create*")):
        if p.suffix.lower() in (".xlsx", ".xlsm", ".xls") and str(p) not in seen:
            seen.add(str(p))
            out.append(p)

    # 2) 常用目录下的模板
    for d in _TEMPLATE_DIRS:
        try:
            base = Path(d).expanduser()
            if not base.is_dir():
                continue
            for p in sorted(base.glob("mould-create*")):
                if p.suffix.lower() in (".xlsx", ".xlsm", ".xls") and str(p) not in seen:
                    seen.add(str(p))
                    out.append(p)
        except Exception:
            continue
    return out


def _resolve_template(args, payload, log):
    """定出本次要用的 Excel 模板路径。

    优先级：
      1) 任务 payload 里带 template_b64（网页上传的模板）-> 落到 workdir 后用这个
      2) 命令行 --template 指定的本地路径
      3) 工作目录里最近用过的 mould-create*.xlsx/.xlsm
      4) 常用模板目录（桌面\\产品模型\\MLB 等）里最近的一个
    """
    import base64 as _b64

    wd = Path(getattr(args, "workdir", "") or (Path.home() / "MLB新卡上架"))
    wd.mkdir(parents=True, exist_ok=True)

    b64 = (payload or {}).get("template_b64") or ""
    name = (payload or {}).get("template_name") or "mould-create.xlsx"
    if b64:
        # 防止名字里带路径分隔符跑出去
        safe = os.path.basename(str(name)).replace("..", "_") or "mould-create.xlsx"
        if not safe.lower().endswith((".xlsx", ".xlsm", ".xls")):
            safe += ".xlsx"
        dest = wd / safe
        try:
            raw = _b64.b64decode(b64)
        except Exception as e:
            raise ValueError("任务下发的模板 base64 解不开：%s" % e)
        dest.write_bytes(raw)
        log("已接收网页上传的模板：%s（%d bytes）" % (dest.name, len(raw)))
        return str(dest)

    if args.template and os.path.isfile(args.template):
        return args.template

    cands = sorted(_template_candidates(wd),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if cands:
        chosen = cands[0]
        log("用模板：%s" % chosen)
        return str(chosen)

    raise ValueError(
        "没有可用的 Excel 模板。请在网页上随任务上传模板，"
        "或用 --template 指定 mould-create_gid927_*.xlsx/.xlsm；"
        "也可以把模板放进工作目录 %s 后重试。" % wd)


def _profile_dir_for(args):
    """浏览器持久化 profile 的存放位置。

    给了 --workdir 就放 <workdir>/browser_profile；否则退回
    ~/MLB新卡上架/browser_profile。
    固定下来很重要：Cloudflare 的通行 cookie 存在这里，换目录等于要重新过验证。
    """
    wd = getattr(args, "workdir", "") or ""
    if wd:
        return Path(wd).expanduser() / "browser_profile"
    return None


def run_collect(payload, hub, tid, agent_name, log, args):
    rate = Decimal(str(payload["rate"]))
    interval = int(payload.get("interval") or DEFAULT_INTERVAL)
    batch = (payload.get("batch") or "").strip()
    show = bool(payload.get("show_browser")) or args.show

    def prog(pct, text, extra=None):
        d = {"pct": pct, "text": text}
        if extra:
            d.update(extra)
        try:
            hub.progress(tid, d)
        except Exception:
            pass
        log("[%d%%] %s" % (pct, text))

    prog(3, "启动浏览器")
    cancel = lambda: False

    with Browser(cancel_flag=cancel, show=show, log=log,
                 profile_dir=_profile_dir_for(args)) as br:
        if batch:
            url = batch if batch.startswith("http") else \
                "%s/26/updates/%s" % (SHOWDD_ROOT, batch.strip("/"))
        else:
            prog(6, "查找最新批次")
            url = br.latest_update_url()
        log("目标批次：%s" % url)

        # --- 三轮采样 ---
        all_cards = {}
        for n in range(1, 4):
            prog(8 + (n - 1) * 26, "第 %d/3 轮 Buy Now 采样" % n)
            got = br.collect(url)
            if not got:
                raise ValueError("第 %d 轮没有解析到任何卡片，请检查网页结构" % n)
            if n == 1:
                all_cards = got
                log("页面共解析到 %d 张卡" % len(all_cards))
            else:
                for h, c in got.items():
                    if h in all_cards and c.samples:
                        all_cards[h].samples.extend(c.samples)
            valid = sum(1 for c in got.values() if c.samples)
            log("第 %d 轮取得 %d 个有效 Buy Now" % (n, valid))
            if n < 3:
                left = interval
                while left > 0:
                    time.sleep(min(10, left))
                    left -= min(10, left)
                prog(8 + n * 26, "已完成 %d/3 轮" % n)

        # --- 筛选与定价 ---
        prog(84, "筛选与定价")
        for c in all_cards.values():
            if c.series.casefold() == "live":
                c.status = "排除：Live 系列"
                continue
            if len(c.samples) < 3:
                c.status = "排除：价格不足 3 次采样"
                continue
            c.samples = c.samples[:3]
            c.median = int(statistics.median(c.samples))
            c.sale_price = (Decimal(c.median) / Decimal("100000") * rate * MARKUP
                            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            c.rate = rate
            if c.sale_price < FLOOR:
                c.status = "排除：售价低于 $0.50"
            else:
                c.include = True
                c.status = "准备写入"

        cards = sorted(all_cards.values(),
                       key=lambda c: (not c.include,
                                      -(c.sale_price or Decimal(0)), c.name))
        included = [c for c in cards if c.include]
        log("符合上架规则：%d 张" % len(included))

        # --- 写 Excel ---
        added = dup = 0
        out_path = None
        summary = {}
        if included:
            tpl_path = _resolve_template(args, payload, log)
            prog(88, "写入并校验 Excel")
            info = validate_template(tpl_path)
            log("模板：%s 工作表「%s」已有 %d 条商品"
                % (os.path.basename(tpl_path), info["sheet"], info["existing"]))
            out_path, added, dup = write_output(tpl_path, cards)
            verify_output(out_path, cards, info["sheet"])
            log("写入完成：新增 %d 条，重复跳过 %d 条" % (added, dup))
            summary["sheet"] = info["sheet"]

    # --- 回传 ---
    prog(96, "回传结果")
    result = {
        "batch": url,
        "rate": str(rate),
        "parsed": len(cards),
        "eligible": len(included),
        "added": added,
        "duplicates": dup,
        "cards": [c.to_dict() for c in cards],
        "filtered_not_tradable": sum(1 for c in cards if c.status.startswith("排除：价格不足")),
        "filtered_live": sum(1 for c in cards if c.status.startswith("排除：Live")),
        "filtered_low_price": sum(1 for c in cards if c.status.startswith("排除：售价低于")),
    }
    if out_path and os.path.isfile(out_path):
        raw = Path(out_path).read_bytes()
        result["file_b64"] = base64.b64encode(raw).decode()
        result["file_name"] = "%s_%s" % (datetime.now().strftime("%Y%m%d_%H%M%S"),
                                         os.path.basename(out_path))
        log("结果文件：%s（%.0f KB）" % (result["file_name"], len(raw) / 1024.0))
    return result


def _password_file_candidates(args):
    """密码文件的候选路径，按优先级：工作目录 -> 脚本所在目录 -> 家目录。

    坑（2026-10-05 老大实测踩到）：用 Windows 记事本保存密码时，
    记事本默认会强制加扩展名，最终落盘的文件叫 `.mlb_pass.txt`
    而不是 `.mlb_pass`。程序如果只认无扩展名的名字，就会永远读不到
    密码 —— 而 bat 那边看到"密码文件不存在"就转去交互输入，
    表现成"我明明建了密码文件却还要输密码"，非常费解。

    所以这里对每个目录都展开多个常见变体，把 .txt 一并认掉。
    """
    dirs = []
    wd = getattr(args, "workdir", "") or ""
    if wd:
        dirs.append(Path(wd).expanduser())
    dirs.append(Path.home() / "MLB新卡上架")
    try:
        dirs.append(Path(__file__).resolve().parent)
    except Exception:
        pass

    # 同一目录可能重复（例如 workdir 就是脚本目录），用 seen 去重
    names = (".mlb_pass", ".mlb_pass.txt", "mlb_pass.txt", "mlb_pass")
    out = []
    seen = set()
    for d in dirs:
        for nm in names:
            p = d / nm
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out


def resolve_password(args, log=print):
    """按「环境变量 -> .mlb_pass 文件 -> 交互输入」顺序拿密码。

    为什么不用 getpass 一把梭：
      双击 bat / 由其他进程拉起时常常没有可用的控制台，
      getpass 会直接抛异常或拿到空串，而调用方如果没兜住，
      表现就是「窗口一闪、什么都没发生」——极难排查。
      所以这里每一步都显式判断并给出可执行的提示。
    """
    env = os.environ.get("MLB_AGENT_PASSWORD")
    if env:
        log("从环境变量 MLB_AGENT_PASSWORD 读取密码")
        return env.strip()

    for p in _password_file_candidates(args):
        try:
            if p.is_file():
                txt = p.read_text(encoding="utf-8-sig", errors="replace").strip()
                if txt:
                    log("从密码文件读取密码：%s" % p)
                    return txt
        except Exception as e:
            log("读取密码文件失败（%s）：%s" % (p, e))

    # 交互式输入。
    # 注意：Windows 上 sys.stdin.isatty() 在「无控制台/被重定向」时
    # 并不可靠（常常仍返回 True），所以这里不能只靠它判断。
    # 策略：能走 getpass 就走（不回显、有提示）；失败则退回 input；
    #       再失败就返回空，由调用方给出明确报错。
    # 真正的兜底在 启动执行器.bat —— 它用 set /p 先拿到密码再传进来，
    # 所以正常双击启动的路径根本不会走到这里。
    try:
        return getpass.getpass("MLB 工作台密码（看不到输入是正常的）：").strip()
    except (EOFError, KeyboardInterrupt) as e:
        log("未输入密码（%s）" % type(e).__name__)
        return ""
    except Exception as e:
        log("交互式读取密码失败（%s），改用普通输入" % e)
        try:
            return input("MLB 工作台密码：").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
        except Exception:
            return ""


def _setup_console():
    """把控制台输出固定成 UTF-8，避免中文在 GBK(936) 机器上变成乱码。

    背景：中文 Windows 的 cmd 默认代码页是 936(GBK)。Python 3.6+ 在
    Windows 上若不显式 reconfigure，stdout 会用 GBK 编码输出；一旦 bat 里
    用过 chcp 65001（或用户手动切过代码页），控制台按 UTF-8 解码，
    双方一错位，中文提示就变成 "◆◆" / "锟斤拷" 这类满屏乱码，
    而错误原因被完全掩盖 —— 这比报错本身更难排查。

    这里做三件事，都做了失败兜底，任何一步不支持都不会影响主流程：
      1) stdout / stderr 强制 UTF-8，errors=replace 防止个别字符直接抛异常
      2) 把控制台代码页切到 65001（与上面的输出编码对齐）
      3) 关掉 Windows 上 CPython 对 UTF-8 输出会用 surrogateescape 的行为差异
    """
    # 1) 文本流重配
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            # 极端情况下（例如流已被替换成不支持 reconfigure 的对象）忽略
            pass

    # 2) 控制台代码页切 65001。只对真实控制台生效，重定向时静默跳过。
    try:
        if sys.stdout is not None and sys.stdout.isatty():
            import ctypes
            # 65001 = CP_UTF8，附在 kernel32 上便于后续扩展
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        # 非 Windows / 无控制台 / 权限不足：都不影响功能，跳过即可
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="https://47.85.224.112")
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--agent", default="")
    ap.add_argument("--template", default="", help="Excel 模板路径")
    ap.add_argument("--workdir", default="",
                    help="工作目录（存浏览器登录态 + 下载的模板），默认 ~/MLB新卡上架")
    ap.add_argument("--show", action="store_true", help="显示浏览器窗口（过验证码用）")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    ap.add_argument("--once", action="store_true", help="只领一次任务就退出")
    ap.add_argument("--poll", type=int, default=15, help="轮询间隔秒")
    ap.add_argument("--self-test", action="store_true", help="不走服务器，本地直接采一批")
    ap.add_argument("--rate", default="", help="self-test 用的金币售价")
    ap.add_argument("--batch", default="")
    ap.add_argument("--manual-login", action="store_true",
                    help="不自动登录，弹Chrome 让你手动登录后接管 Cookie")
    args = ap.parse_args()

    _setup_console()

    def log(msg):
        print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)

    if args.self_test:
        if not args.rate:
            raise SystemExit("--self-test 需要同时给 --rate")
        r = run_collect({"rate": args.rate, "batch": args.batch,
                         "interval": args.interval, "show_browser": args.show},
                        _NullHub(), "self-test", "self-test", log, args)
        print(json.dumps({k: v for k, v in r.items() if k != "file_b64"},
                         ensure_ascii=False, indent=2))
        return

    if args.user and not args.password and not args.manual_login:
        args.password = resolve_password(args, log)
        if not args.password:
            # 绝不允许「密码为空还继续跑」：那样心跳会 401，
            # 表现出来只是网页上执行器一直离线，很难定位。
            raise SystemExit(
                "[X] 没有拿到密码，已停止。\n"
                "    三种给法任选：\n"
                "      1) 启动参数：--password 你的密码\n"
                "      2) 环境变量：set MLB_AGENT_PASSWORD=你的密码\n"
                "      3) 密码文件：把密码单独一行写进 <工作目录>/.mlb_pass\n"
                "    （用 启动执行器.bat 启动时会自动读第 2/3 种）")

    if not args.agent:
        args.agent = "%s-%s" % (os.environ.get("USERNAME") or "pc", uuid.uuid4().hex[:4])
    hub = Hub(args.server, args.user, args.password, log=log)
    log("执行器启动：%s -> %s" % (args.agent, args.server))
    log("站点根：%s   API 基地址：%s" % (hub.site, hub.base))
    log("认证方式：门户 Cookie 会话（先 POST %s 换取签名 Cookie）"
        % Hub.AUTH_LOGIN)
    # 主动登录一次，把认证失败的原因讲清楚，而不是等到心跳报错
    if args.manual_login:
        log("使用手动登录模式（弹浏览器自己登）")
        if not hub.login_manual():
            raise SystemExit("[X] 手动登录没成功，已停止。")
    elif args.user and not hub.login():
        raise SystemExit(
            "[X] 登录门户失败，已停止。\n"
            "    1) 确认账号密码正确（--password 或 .mlb_pass）\n"
            "    2) 确认账号在 dashboard 组（MLB 工作台用它做门禁）\n"
            "    3) 浏览器打开 %s/__auth/login 手动登一次，看是否正常\n"
            "    4) 还是不行就加 --manual-login，让程序弹窗口给你手动登录\n"
            "    5) 门户侧日志：journalctl -u auth-portal -n 50 --no-pager"
            % args.server.rstrip("/"))
    try:
        info = hub.heartbeat(args.agent, AGENT_VERSION, "MLB 新卡采集执行器")
        log("已连接服务器，心跳正常：%s" % json.dumps(info, ensure_ascii=False))
    except Exception as e:
        raise SystemExit(
            "[X] 连不上服务器：%s\n"
            "    排查顺序：\n"
            "      1) 浏览器能打开 %s/mlb/ 吗？打不开说明服务/网络有问题\n"
            "      2) 心跳接口本身报错的话，去服务器看：\n"
            "         journalctl -u mlb-online -n 50 --no-pager"
            % (e, args.server.rstrip("/")))

    idle = 0
    while True:
        try:
            if idle % 4 == 0:
                hub.heartbeat(args.agent, AGENT_VERSION, "MLB 新卡采集执行器")
            res = hub.claim(args.agent)
            task = (res or {}).get("task")
            if not task:
                idle += 1
                if args.once:
                    log("没有待处理任务")
                    return
                time.sleep(args.poll)
                continue
            idle = 0
            tid = task["id"]
            payload = task.get("payload") or {}
            log("领到任务 %s：%s" % (tid, task.get("title")))
            try:
                result = run_collect(payload, hub, tid, args.agent, log, args)
                hub.result(tid, "done", result, agent=args.agent)
                log("任务 %s 完成" % tid)
            except Exception as e:
                tb = traceback.format_exc()
                log("任务 %s 失败：%s" % (tid, e))
                hub.result(tid, "failed", {}, error="%s\n%s" % (e, tb), agent=args.agent)
            if args.once:
                return
        except KeyboardInterrupt:
            log("已停止")
            return
        except Exception as e:
            log("轮询异常：%s" % e)
            time.sleep(args.poll)


class _NullHub:
    """--self-test 用的空实现：不连服务器，所有上报动作都是 no-op。"""

    def progress(self, *a, **k):
        pass

    def heartbeat(self, *a, **k):
        pass

    def claim(self, *a, **k):
        return {"task": None}

    def result(self, *a, **k):
        pass

    def login(self, *a, **k):
        return True

    def agent_config(self, *a, **k):
        return {}


if __name__ == "__main__":
    main()
