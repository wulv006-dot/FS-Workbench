import http.client
import importlib.util
_fs_policy_spec=importlib.util.spec_from_file_location("fs_access_policy", "/opt/fs-access-policy/access_policy.py")
_fs_policy=importlib.util.module_from_spec(_fs_policy_spec)
_fs_policy_spec.loader.exec_module(_fs_policy)
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MMOEXP 运营管理中心 · 统一登录门户 (auth-portal)
================================================
替代 nginx Basic Auth 的浏览器原生弹窗，改为自建 HTML 登录页 + 签名 Cookie 会话。

设计要点
--------
* 零第三方依赖：只用 Python 标准库（与 /opt/fc27-gate 同款做法，避免装包）。
* 复用现有 htpasswd（$apr1$ / {SHA} / crypt / 明文），**用户密码完全不变**。
* Cookie 为 HMAC-SHA256 签名的无状态会话 —— 服务重启不掉线、可多进程。
* 对 nginx 暴露 /verify 供 auth_request 子请求使用，返回 X-Auth-User /
  X-Auth-Groups 供 nginx 注入上游（替代原来的 $remote_user）。

端点（后端视角；对外经 nginx 加 /__auth 前缀）
--------------------------------------------
  GET  /login?next=&err=      登录页
  POST /login                 校验并下发 Cookie，302 回 next
  GET  /logout                清 Cookie 并回登录页
  GET  /verify?group=<g>      内部校验：200 通过 / 401 未登录 / 403 组无权限
  GET  /health                健康检查

配置（/opt/auth-portal/config.env，由 systemd EnvironmentFile 注入）
------------------------------------------------------------------
  AUTH_SECRET         必填。HMAC 密钥；缺失则拒绝启动（避免默认密钥被伪造）
  AUTH_PORT           默认 8895
  AUTH_BIND           默认 127.0.0.1
  AUTH_PREFIX         对外路径前缀，默认 /__auth
  AUTH_COOKIE_NAME    默认 MMOEXP_AUTH
  AUTH_COOKIE_SECURE  1/0，默认 1（HTTPS 才回传）
  AUTH_TTL_DAYS       勾选"记住我"的会话时长，默认 30 天
  AUTH_SESSION_HOURS  未勾选时的会话时长，默认 12 小时
  AUTH_GROUPS         组定义 name=htpasswd路径，分号分隔
                      默认 dashboard=/etc/nginx/.htpasswd-dashboard;deploy=/etc/nginx/.htpasswd-deploy
  AUTH_TEMPLATE       登录页模板路径，默认同目录 login.html
  AUTH_DATA_DIR       审计日志目录，默认同目录 data
  AUTH_MAX_FAILS      同 IP+账号 连续失败上限，默认 6
  AUTH_LOCK_SECONDS   触发上限后的锁定时长（秒），默认 300
"""

import base64
import hashlib
import hmac
import html
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"

# ---------------------------------------------------------------- 配置

def _env(key, default=""):
    return os.environ.get(key, default).strip()


def _env_int(key, default):
    try:
        return int(_env(key) or default)
    except ValueError:
        return default


HERE = os.path.dirname(os.path.abspath(__file__))

CFG = {
    "secret":     _env("AUTH_SECRET"),
    "port":       _env_int("AUTH_PORT", 8895),
    "bind":       _env("AUTH_BIND") or "127.0.0.1",
    "prefix":     _env("AUTH_PREFIX") or "/__auth",
    "cookie":     _env("AUTH_COOKIE_NAME") or "MMOEXP_AUTH",
    "secure":     (_env("AUTH_COOKIE_SECURE") or "1") not in ("0", "false", "no"),
    "ttl_days":   _env_int("AUTH_TTL_DAYS", 30),
    "sess_hours": _env_int("AUTH_SESSION_HOURS", 12),
    "groups_raw": _env("AUTH_GROUPS") or
                  "dashboard=/etc/nginx/.htpasswd-dashboard;deploy=/etc/nginx/.htpasswd-deploy",
    "template":   _env("AUTH_TEMPLATE") or os.path.join(HERE, "login.html"),
    "status_tpl": _env("AUTH_STATUS_TEMPLATE") or os.path.join(HERE, "status.html"),
    "tz_offset":  _env_int("AUTH_TZ_OFFSET", 8),      # 展示用固定时区偏移（小时）
    "data_dir":   _env("AUTH_DATA_DIR") or os.path.join(HERE, "data"),
    "max_fails":  _env_int("AUTH_MAX_FAILS", 6),
    "lock_secs":  _env_int("AUTH_LOCK_SECONDS", 300),
}

# 组 -> htpasswd 文件
GROUPS = {}
for _item in CFG["groups_raw"].split(";"):
    _item = _item.strip()
    if not _item or "=" not in _item:
        continue
    _n, _p = _item.split("=", 1)
    GROUPS[_n.strip()] = _p.strip()

# 默认组：登录页未指定时使用（dashboard 覆盖面最广）
DEFAULT_GROUP = "dashboard" if "dashboard" in GROUPS else (list(GROUPS)[0] if GROUPS else "")

# ---------------------------------------------------------------- 日志

_log_lock = threading.Lock()


def log(msg, kind="info"):
    line = "%s [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), kind, msg)
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except Exception:
        pass
    try:
        os.makedirs(CFG["data_dir"], exist_ok=True)
        with _log_lock:
            with open(os.path.join(CFG["data_dir"], "audit.log"), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- 密码校验
# 目标：直接吃 nginx 现有的 htpasswd，用户密码一字不改。

_B64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _to64(v, n):
    out = []
    while n > 0:
        out.append(_B64[v & 0x3F])
        v >>= 6
        n -= 1
    return "".join(out)


def apr1_md5(password, salt):
    """Apache $apr1$ (md5-crypt) 摘要，纯标准库实现。

    注意：alt[i % 16] 在 Python3 里是 int，必须切片成 bytes 再 update，
    否则 hashlib 会抛 TypeError —— 这是移植该算法最常见的坑。
    """
    magic = b"$apr1$"
    pw = password.encode("utf-8")
    sb = salt.encode("ascii")

    ctx = hashlib.md5(pw + magic + sb)
    alt = hashlib.md5(pw + sb + pw).digest()
    for i in range(len(pw)):
        ctx.update(alt[i % 16:i % 16 + 1])
    i = len(pw)
    while i:
        ctx.update(b"\x00" if (i & 1) else pw[0:1])
        i >>= 1
    digest = ctx.digest()

    for i in range(1000):
        c = hashlib.md5()
        c.update(pw if (i & 1) else digest)
        if i % 3:
            c.update(sb)
        if i % 7:
            c.update(pw)
        c.update(digest if (i & 1) else pw)
        digest = c.digest()

    seq = [
        (digest[0] << 16) | (digest[6] << 8) | digest[12],
        (digest[1] << 16) | (digest[7] << 8) | digest[13],
        (digest[2] << 16) | (digest[8] << 8) | digest[14],
        (digest[3] << 16) | (digest[9] << 8) | digest[15],
        (digest[4] << 16) | (digest[10] << 8) | digest[5],
        digest[11],
    ]
    return "$apr1$" + salt + "$" + "".join(_to64(v, 4) for v in seq[:5]) + _to64(seq[5], 2)


def check_hash(password, stored):
    """校验明文密码与 htpasswd 中的摘要是否匹配。"""
    if not stored:
        return False
    stored = stored.strip()
    try:
        if stored.startswith("$apr1$"):
            parts = stored.split("$")
            # ['', 'apr1', '<salt>', '<hash>']
            if len(parts) < 4:
                return False
            salt = parts[2][:8]
            return hmac.compare_digest(apr1_md5(password, salt), stored)
        if stored.startswith("{SHA}"):
            d = base64.b64encode(hashlib.sha1(password.encode("utf-8")).digest()).decode()
            return hmac.compare_digest("{SHA}" + d, stored)
        if stored.startswith("$5$") or stored.startswith("$6$"):
            import crypt
            return hmac.compare_digest(crypt.crypt(password, stored), stored)
        if stored.startswith("$2"):          # bcrypt：标准库无实现，明确不支持
            return False
        # 退化为明文比对（老文件可能出现）
        return hmac.compare_digest(password, stored)
    except Exception:
        return False


# htpasswd 读取 + mtime 缓存（每请求都读盘没必要）
_ht_cache = {}
_ht_lock = threading.Lock()


def load_htpasswd(path):
    try:
        st = os.stat(path)
        key = (st.st_mtime, st.st_size)
    except OSError:
        return {}
    with _ht_lock:
        hit = _ht_cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
    users = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                u, h = line.split(":", 1)
                users[u.strip()] = h.strip()
    except OSError:
        return {}
    with _ht_lock:
        _ht_cache[path] = (key, users)
    return users


def authenticate(username, password):
    """在所有组里找这个账号；返回命中的组列表。"""
    hits = []
    for gname, gpath in GROUPS.items():
        users = load_htpasswd(gpath)
        if username in users and check_hash(password, users[username]):
            hits.append(gname)
    return hits


def groups_of(username):
    """已登录用户当前仍有效的组（用户名从凭据里来，视为可信）。"""
    return [g for g, p in GROUPS.items() if username in load_htpasswd(p)]


# ---------------------------------------------------------------- 会话 Cookie

def _b64e(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(txt):
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode(txt + pad)


def _sign(payload_b64):
    mac = hmac.new(CFG["secret"].encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    return _b64e(mac.digest())


def make_token(username, groups, ttl_seconds):
    payload = {
        "u": username,
        "g": ",".join(groups),
        "e": int(time.time()) + int(ttl_seconds),
        "n": _b64e(os.urandom(9)),
    }
    body = _b64e(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    return body + "." + _sign(body)


def read_token(token):
    """校验签名与有效期；通过返回 payload，否则 None。"""
    if not token or "." not in token:
        return None
    body, _, sig = token.rpartition(".")
    if not body or not sig:
        return None
    if not hmac.compare_digest(_sign(body), sig):
        return None
    try:
        payload = json.loads(_b64d(body).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("e") or 0) < int(time.time()):
        return None
    if not payload.get("u"):
        return None
    return payload


def parse_cookies(header):
    jar = {}
    for part in (header or "").split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        jar[k.strip()] = v.strip()
    return jar


# ---------------------------------------------------------------- 防爆破

_fails = {}
_fail_lock = threading.Lock()


def _fail_key(ip, user):
    return "%s|%s" % (ip, user.lower())


def locked_for(ip, user):
    """注意：未达阈值时 until 记 0 表示"仅计数、未锁定"，
    此时绝不能 pop —— 否则每次请求都会把计数清掉，永远锁不住。"""
    k = _fail_key(ip, user)
    with _fail_lock:
        rec = _fails.get(k)
        if not rec:
            return 0
        until, _n = rec
        if until <= 0:
            return 0
        left = int(until - time.time())
        if left <= 0:
            _fails.pop(k, None)
            return 0
        return left


def note_fail(ip, user):
    with _fail_lock:
        k = _fail_key(ip, user)
        _until, n = _fails.get(k, (0, 0))
        n += 1
        until = (time.time() + CFG["lock_secs"]) if n >= CFG["max_fails"] else 0
        _fails[k] = (until, n)
        # 防内存无限增长：条目过多时清掉所有已过期/未锁定的
        if len(_fails) > 20000:
            now = time.time()
            for kk in [x for x, (u, _c) in _fails.items() if u <= now]:
                _fails.pop(kk, None)
        return n


def clear_fail(ip, user):
    with _fail_lock:
        _fails.pop(_fail_key(ip, user), None)


# ---------------------------------------------------------------- 工具

_SAFE_NEXT_RE = re.compile(r"^/(?!/)[^\r\n\\]*$")


def safe_next(raw, fallback="/dashboard/"):
    """只接受站内绝对路径，杜绝开放重定向（//evil.com、http://…、\… 全部拒绝）。"""
    if not raw:
        return fallback
    raw = raw.strip()
    if len(raw) > 512:
        return fallback
    if not _SAFE_NEXT_RE.match(raw):
        return fallback
    return raw


def health_line():
    """真实运行状态：任一 htpasswd 读不到就示警，而不是永远显示"一切正常"。"""
    bad = [g for g, p in GROUPS.items() if not load_htpasswd(p)]
    if bad:
        return "认证数据源异常（%s）· 请联系管理员" % "、".join(bad), "warn"
    return "服务运行正常 · 安全连接已建立", ""


def _local(ts):
    """按配置时区偏移格式化（服务器本身可能是 UTC，直接显示会让人困惑）。"""
    return time.gmtime(int(ts) + CFG["tz_offset"] * 3600)


def fmt_ts(ts, pattern="%Y-%m-%d %H:%M"):
    return time.strftime(pattern, _local(ts))


def humanize(secs):
    secs = int(secs)
    if secs <= 0:
        return "已过期"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return "%d 天 %d 小时" % (d, h)
    if h:
        return "%d 小时 %d 分" % (h, m)
    return "%d 分钟" % max(m, 1)


def _load_tpl(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        log("模板读取失败 %s: %s" % (path, exc), "error")
        return ("<!doctype html><meta charset=utf-8><title>登录</title>"
                "<body style=\"font-family:sans-serif;padding:40px;line-height:1.7\">"
                "<h2>页面模板缺失</h2><p>请检查 %s</p></body>" % html.escape(path))


def _fill(path, vals):
    tpl = _load_tpl(path)
    for k, v in vals.items():
        tpl = tpl.replace("{{%s}}" % k, v)
    return tpl


def _render_page(**kw):
    status_text, status_cls = health_line()
    return _fill(CFG["template"], {
        "U_LOGIN":  CFG["prefix"] + "/login",
        "U_LOGOUT": CFG["prefix"] + "/logout",
        "STATUS":       html.escape(status_text),
        "STATUS_CLASS": status_cls,
        "NEXT":     html.escape(kw.get("next") or "/dashboard/", quote=True),
        "MSG":      html.escape(kw.get("msg") or ""),
        "MSG_KIND": kw.get("msg_kind") or "",
        "THEME":    kw.get("theme") or "light",
        "HINT":     html.escape(kw.get("hint") or ""),
        "FOOT_L":   html.escape(kw.get("foot_l") or ("v" + VERSION)),
    })


def _render_status(pl, ip, theme="light"):
    user = pl.get("u") or ""
    live = groups_of(user)
    tags = "".join(
        '<span class="tag g%d">%s</span>' % (1 if i == 0 else 2, html.escape(g))
        for i, g in enumerate(live)
    ) or '<span class="tag">—</span>'
    exp = int(pl.get("e") or 0)
    now = time.time()
    return _fill(CFG["status_tpl"], {
        "THEME":      theme,
        "USER":       html.escape(user),
        "GROUP_TAGS": tags,
        "EXP":        html.escape(fmt_ts(exp)),
        "LEFT":       html.escape(humanize(exp - now)),
        "IP":         html.escape(ip),
        "U_HOME":     "/dashboard/",
        "U_LOGOUT":   CFG["prefix"] + "/logout",
        "VER":        "v" + VERSION,
        "NOW":        html.escape(fmt_ts(now)),
    })


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "MMOEXPAuthPortal/" + VERSION
    protocol_version = "HTTP/1.1"

    # ---- 基础工具 ----
    def log_message(self, fmt, *args):
        pass  # 交给 log()，避免默认访问日志刷屏

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in (headers or []):
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD" and body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _redirect(self, location, extra_headers=None):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or []):
            self.send_header(k, v)
        self.end_headers()

    def _cookie_header(self, token, max_age):
        bits = ["%s=%s" % (CFG["cookie"], token), "Path=/", "HttpOnly", "SameSite=Lax"]
        if CFG["secure"]:
            bits.append("Secure")
        bits.append("Max-Age=%d" % int(max_age))
        return "Set-Cookie", "; ".join(bits)

    def _clear_cookie_header(self):
        bits = ["%s=" % CFG["cookie"], "Path=/", "HttpOnly", "SameSite=Lax",
                "Max-Age=0", "Expires=Thu, 01 Jan 1970 00:00:00 GMT"]
        if CFG["secure"]:
            bits.append("Secure")
        return "Set-Cookie", "; ".join(bits)

    @property
    def ip(self):
        """真实客户端 IP。

        本服务只监听 127.0.0.1、由 nginx 反代，所以 client_address 恒为 127.0.0.1，
        直接用它会让审计日志与状态页的"来源 IP"全部失效。
        nginx 侧已配 proxy_set_header X-Real-IP $remote_addr，这里优先取它。
        """
        for h in ("X-Real-IP", "X-Forwarded-For"):
            v = (self.headers.get(h) or "").strip()
            if v:
                return v.split(",")[0].strip()[:64]
        return self.client_address[0] if self.client_address else "?"

    def _uaprefix(self):
        return (self.headers.get("User-Agent") or "")[:120]

    # ---- 路由 ----
    def do_GET(self):
        self._route()

    def do_HEAD(self):
        self._route()

    def do_POST(self):
        self._route()

    def _route(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        def q(name, default=""):
            v = qs.get(name)
            return v[0] if v else default

        try:
            if path in ("/", "/login"):
                if self.command == "POST":
                    return self._do_login(q("next"))
                return self._page_login(next_url=q("next"), err=q("err"),
                                        msg=q("msg"), theme=q("theme"))
            if path == "/status":
                return self._page_status(q("theme"))
            if path == "/logout":
                return self._do_logout(q("next"))
            if path == "/verify":
                return self._do_verify(q("group"))
            if path == "/iam" or path.startswith("/iam/"):
                return self._do_iam(path, qs)
            if path == "/health":
                return self._send(200, json.dumps({
                    "ok": True, "version": VERSION, "groups": list(GROUPS.keys()),
                    "time": int(time.time()),
                }), "application/json; charset=utf-8")
            return self._send(404, "not found")
        except Exception as exc:            # 任何异常都不能把服务打挂
            log("未捕获异常 %s: %r" % (path, exc), "error")
            return self._send(500, "internal error")

    # ---- 登录页 ----
    def _page_login(self, next_url=None, err="", msg="", theme="light"):
        nxt = safe_next(next_url)
        kind, text, foot = "", "", ""

        if err == "noperm":
            bad = ""
            tok = parse_cookies(self.headers.get("Cookie")).get(CFG["cookie"])
            pl = read_token(tok)
            if pl:
                bad = pl.get("u") or ""
            kind, text = "err", ("账号 %s 没有访问该模块的权限，请换一个有权限的账号登录。" % bad) if bad \
                else "当前账号没有访问该模块的权限。"
            foot = "权限不足"
        elif err == "expired":
            kind, text = "err", "登录状态已过期，请重新登录。"
        elif err == "bad":
            kind, text = "err", "账号或密码不正确，请重试。"
        elif err == "locked":
            kind, text = "err", "尝试次数过多，该账号已被临时锁定，请稍后再试。"
        elif err == "csrf" or err == "badreq":
            kind, text = "err", "请求格式不正确，请重新提交。"
        elif msg:
            kind, text = "ok", msg

        page = _render_page(next=nxt, msg=text, msg_kind=kind, theme=theme,
                            hint=("" if not foot else foot), foot_l=("v" + VERSION))
        return self._send(200, page, "text/html; charset=utf-8",
                          headers=[("X-Frame-Options", "DENY")])

    # ---- 登录状态页 ----
    def _page_status(self, theme="light"):
        tok = parse_cookies(self.headers.get("Cookie")).get(CFG["cookie"])
        pl = read_token(tok)
        if not pl or not groups_of(pl.get("u") or ""):
            return self._redirect(
                CFG["prefix"] + "/login?err=expired&next=" +
                urllib.parse.quote(CFG["prefix"] + "/status"))
        page = _render_status(pl, self.ip, theme or "light")
        return self._send(200, page, "text/html; charset=utf-8",
                          headers=[("X-Frame-Options", "DENY")])

    # ---- 提交登录 ----
    def _do_login(self, next_q):
        # 表单体
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 8192:
            return self._redirect(CFG["prefix"] + "/login?err=badreq")
        raw = self.rfile.read(length).decode("utf-8", "replace")
        form = urllib.parse.parse_qs(raw, keep_blank_values=True)

        def f(name, default=""):
            v = form.get(name)
            return (v[0] if v else default)

        username = f("username").strip()
        password = f("password")
        nxt = safe_next(f("next") or next_q)
        remember = f("remember") in ("1", "on", "true", "yes")

        if not username or not password:
            return self._login_fail("bad", nxt)

        left = locked_for(self.ip, username)
        if left:
            log("登录被拒(锁定中 %ds) user=%s ip=%s" % (left, username, self.ip), "warn")
            return self._login_fail("locked", nxt)

        hits = authenticate(username, password)
        if not hits:
            # 注册账号的会话不在门户 token（CFG["cookie"]）体系内：改用注册会话登录
            # 并下发 FS_ACCESS_CANDIDATE cookie，Bridge.verify 才能识别。
            _bridge = getattr(sys.modules[__name__], '_registration_bridge', None)
            if _bridge is not None:
                _resp = _bridge.try_reg_login(self, username, password, nxt)
                if _resp is not None:
                    log("登录成功(注册账号) user=%s ip=%s" % (username, self.ip), "info")
                    return _resp
            n = note_fail(self.ip, username)
            log("登录失败 user=%s ip=%s 累计失败=%d ua=%s" % (username, self.ip, n, self._uaprefix()), "warn")
            bad = "locked" if n >= CFG["max_fails"] else "bad"
            return self._login_fail(bad, nxt)

        clear_fail(self.ip, username)
        ttl = (CFG["ttl_days"] * 86400) if remember else (CFG["sess_hours"] * 3600)
        token = make_token(username, hits, ttl)
        log("登录成功 user=%s 组=%s ip=%s ttl=%ds remember=%s" %
            (username, ",".join(hits), self.ip, ttl, remember), "info")
        return self._redirect(nxt, [self._cookie_header(token, ttl)])

    def _login_fail(self, err, nxt):
        """登录失败后回哪。

        从新控制台（/__auth/access/）提交的表单，就回它自己 —— 那个页面的登录框
        会就地显示 err 文案，用户不用在两个不同风格的登录页之间跳。其他来源
        仍旧回老的统一登录页，行为不变。
        """
        base = CFG["prefix"] + "/login"
        if nxt == CFG["prefix"] + "/access" or nxt.startswith(CFG["prefix"] + "/access/"):
            base = CFG["prefix"] + "/access/"
        sep = "&" if "?" in base else "?"
        return self._redirect(base + sep + "err=" + err + "&next=" + urllib.parse.quote(nxt))

    # ---- 登出 ----
    def _do_logout(self, next_q):
        tok = parse_cookies(self.headers.get("Cookie")).get(CFG["cookie"])
        pl = read_token(tok)
        if pl:
            log("登出 user=%s ip=%s" % (pl.get("u"), self.ip), "info")
        dest = safe_next(next_q) if next_q else (CFG["prefix"] + "/login")
        if not dest.startswith(CFG["prefix"]):
            dest = CFG["prefix"] + "/login"
        conn = http.client.HTTPConnection("127.0.0.1", 8896, timeout=3)
        try:
            conn.request("POST", "/logout", body=b"", headers={"Cookie": self.headers.get("Cookie", ""), "Content-Length": "0"})
            response = conn.getresponse()
            response.read()
        except (OSError, http.client.HTTPException):
            pass
        finally:
            conn.close()
        return self._redirect(dest, [self._clear_cookie_header(),
            ("Set-Cookie", "fc27sess=; Path=/; HttpOnly; Secure; Max-Age=0")])

    # ---- 供 nginx auth_request 调用 ----
    def _do_verify(self, group):
        tok = parse_cookies(self.headers.get("Cookie")).get(CFG["cookie"])
        pl = read_token(tok)
        user = pl.get("u") if pl else None
        live = groups_of(user) if user else []
        if not live:
            user = None
            conn = http.client.HTTPConnection("127.0.0.1", 8896, timeout=3)
            try:
                conn.request("GET", "/verify", headers={"Cookie": self.headers.get("Cookie", "")})
                response = conn.getresponse()
                if response.status == 200:
                    user = response.getheader("X-Fc27-User")
                    live = ["dashboard"] if user else []
                response.read()
            except (OSError, http.client.HTTPException):
                user = None
            finally:
                conn.close()
        if not user or not live:
            return self._send(401, "unauthorized")
        if group and group not in live and group != "deploy":
            return self._send(403, "forbidden")
        code = _fs_policy.authorize(user, self.headers.get("X-Original-Method", "GET"),
                                    self.headers.get("X-Original-URI", "/"), group)
        if code != 200:
            return self._send(code, "forbidden")
        admin = user in _fs_policy.ADMINS
        role = "admin" if admin else "readonly"
        groups = sorted(set(live + (["deploy"] if admin else [])))
        return self._send(200, "OK", headers=[("X-Auth-User", user),
            ("X-Auth-Groups", ",".join(groups)), ("X-Auth-Role", role),
            ("X-Fc27-User", user), ("X-Fc27-Role", role)])

    # ---- 成员与权限控制台（fs-iam） ----
    def _do_iam(self, path, qs):
        """把 /__auth/iam/* 交给 /opt/fs-access-policy/iam_console.py。

        拆出去的原因：auth_portal 只管「认证 + auth_request 网关」，
        「谁能干什么」的策略与界面全部收敛在 fs-access-policy 一个目录里，
        两边职责不混。这里只做接线，任何异常都退化成 503，不带崩主服务。
        """
        try:
            if "iam_console" not in sys.modules:
                policy_dir = "/opt/fs-access-policy"
                if policy_dir not in sys.path:
                    sys.path.insert(0, policy_dir)
                import iam_console  # noqa: F401
            module = sys.modules["iam_console"]
            portal = sys.modules.get(__name__) or sys.modules.get("__main__")
            return module.handle(portal, self, path, qs)
        except Exception as exc:
            log("IAM 控制台异常 %s: %r" % (path, exc), "error")
            return self._send(503, "IAM 暂时不可用", "text/plain; charset=utf-8")


    # ---------------------------------------------------------------- 自检

def selftest():
    """用 openssl 生成的已知向量自证 APR1 实现正确（不联网）。"""
    import subprocess
    ok = True
    for pw in ("password", "chenchao", "P@ssw0rd!2026", "中文密码测试"):
        try:
            out = subprocess.run(["openssl", "passwd", "-apr1", "-salt", "abcdefgh", pw],
                                 capture_output=True, text=True, timeout=10)
            want = out.stdout.strip()
        except Exception as exc:
            print("跳过（openssl 不可用）: %r" % exc)
            return 1
        got = apr1_md5(pw, "abcdefgh")
        flag = "OK " if got == want else "FAIL"
        if got != want:
            ok = False
        print("%s  pw=%-18r %s" % (flag, pw, got))
    print("自检结果:", "全部通过" if ok else "存在失败")
    return 0 if ok else 2


# ---------------------------------------------------------------- 入口

def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())

    if not CFG["secret"] or len(CFG["secret"]) < 16:
        sys.stderr.write("致命错误：AUTH_SECRET 缺失或过短（<16 字符），拒绝启动。\n"
                         "请在 config.env 中设置，例如：\n"
                         "  AUTH_SECRET=$(openssl rand -hex 32)\n")
        sys.exit(1)
    if not GROUPS:
        sys.stderr.write("致命错误：AUTH_GROUPS 未解析出任何组。\n")
        sys.exit(1)
    if not os.path.exists(CFG["template"]):
        sys.stderr.write("致命错误：登录页模板不存在 %s\n" % CFG["template"])
        sys.exit(1)

    os.makedirs(CFG["data_dir"], exist_ok=True)

    # Frozen registration runtime: explicit existing-store boot, never first-init.
    _registration_root = '/opt/auth-portal/registration-runtime/20261007-ca6258ad'
    if not os.path.isdir(_registration_root):
        raise RuntimeError('registration runtime missing; refusing listener')
    sys.path.insert(0, _registration_root)
    from portal_bridge import install as _registration_install
    _registration_install(sys.modules[__name__], 'https://47.85.224.112')

    srv = ThreadingHTTPServer((CFG["bind"], CFG["port"]), Handler)
    srv.daemon_threads = True
    log("auth-portal v%s 启动 bind=%s:%d prefix=%s 组=%s secure_cookie=%s"
        % (VERSION, CFG["bind"], CFG["port"], CFG["prefix"],
           ",".join("%s(%d人)" % (g, len(load_htpasswd(p))) for g, p in GROUPS.items()),
           CFG["secure"]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
