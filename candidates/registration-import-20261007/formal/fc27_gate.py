import http.client
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FC27 只读看板 · 自注册门禁服务

职责：
  1. 提供注册页 / 登录页（自带 HTML，不依赖外部 CDN，内网也能开）
  2. 校验账号 -> 下发会话 Cookie
  3. 向 nginx 暴露 /verify，供 auth_request 子请求判定放行与否
  4. 提供管理页（仅管理员可见）：注册名单、封号/解封、重置密码、删除

设计要点：
  - 只用标准库（http.server / sqlite3 / hashlib / secrets），服务器上无需 pip install
  - 密码 PBKDF2-HMAC-SHA256 + 每用户独立 salt，绝不存明文
  - 只监听 127.0.0.1，由 nginx 反代；不直接暴露公网
  - 会话 Cookie 用 secrets.token_urlsafe(32)，服务端存库可随时吊销
  - 权限模型：注册用户一律 readonly；管理员由 users.is_admin 标记

环境变量：
  FC27_DB      SQLite 路径（默认 /opt/fc27-gate/data/gate.db）
  FC27_PORT    监听端口（默认 8896）
  FC27_ADMIN_USER / FC27_ADMIN_PASS  首次启动时自建的管理员账号
  FC27_COOKIE_SECURE  设为 1 时给 Cookie 加 Secure（上 HTTPS 后再开）
"""
import os
import sys
import json
import html
import time
import base64
import sqlite3
import hashlib
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB_PATH = os.environ.get("FC27_DB", "/opt/fc27-gate/data/gate.db")
PORT = int(os.environ.get("FC27_PORT", "8896"))
ADMIN_USER = os.environ.get("FC27_ADMIN_USER", "fc27admin")
ADMIN_PASS = os.environ.get("FC27_ADMIN_PASS", "")
COOKIE_NAME = "fc27sess"
SESSION_DAYS = 14
COOKIE_SECURE = os.environ.get("FC27_COOKIE_SECURE", "0") == "1"

# AI 运营分析内容（**仅内部账号可见**）。
# 为什么不直接写进看板 HTML：页面是静态文件，源码对每个登录用户都可见，
# 把分析嵌进去等于把经营判断（含定价策略）公开给外部自注册用户。
# 所以内容存服务端，由本服务按角色下发；前端取不到就整块不渲染。
ANALYSIS_PATH = os.environ.get("FC27_ANALYSIS", "/opt/fc27-gate/data/analysis.json")

# 服务对外挂载前缀。nginx 把 /fc27/ 反代到本服务根路径，所以页面里生成的链接
# 必须带上这个前缀，否则会跳到主站的同名路径（那是另一个应用的地盘）。
# 用环境变量而非写死，将来换路径不用改代码。
BASE = os.environ.get("FC27_BASE", "/fc27").rstrip("/")
DASH = "/s/wulv/fc27-ops/"

# ---------------------------------------------------------------- 内部老账号
# 服务器上那个 /etc/nginx/.htpasswd-dashboard 是 5 个应用共用的，内部同事
# 一直拿它登录。本服务另起了独立凭据体系后，这些人在 FC27 看板上会登不进来，
# 为了不打断他们的使用习惯，这里声明"哪些用户名属于内部账号、各自什么角色"，
# 而**密码仍从原 htpasswd 实时校验**（APR1），所以他们在页面上填原密码即可，
# 不需要重新通知密码，也不会因为 htpasswd 改了密码而失效。
#
# 格式: "chenchao:admin,wulv:admin,DY:admin,mmoexp:readonly"
LEGACY_HTPASSWD = os.environ.get(
    "FC27_LEGACY_HTPASSWD", "/etc/nginx/.htpasswd-dashboard")


def _parse_legacy_roles(raw):
    """'u1:admin,u2:readonly' -> {'u1': True, 'u2': False}"""
    out = {}
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        u, r = chunk.split(":", 1)
        u = u.strip()
        if u:
            out[u] = (r.strip().lower() == "admin")
    return out


LEGACY_ROLES = _parse_legacy_roles(os.environ.get("FC27_LEGACY_ROLES", ""))


def U(path):
    """把服务内路径拼成对外 URL。U('/login') -> '/fc27/login'"""
    path = "/" + (path or "").lstrip("/")
    return BASE + path if path != "/" else BASE + "/"

_HTML_HEAD = """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
*{box-sizing:border-box}
body{margin:0;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
background:#f6f7f9;color:#1c1e21;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.card{background:#fff;border:1px solid #e3e5e8;border-radius:14px;padding:34px 32px 28px;
width:100%;max-width:400px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.card.wide{max-width:1040px;align-self:flex-start}
h1{font-size:20px;font-weight:600;margin:0 0 4px}
.sub{color:#83868c;font-size:13px;margin:0 0 22px}
label{display:block;font-size:13px;font-weight:500;margin:14px 0 6px;color:#3c4043}
input[type=text],input[type=password]{width:100%;padding:11px 13px;border:1px solid #d5d8dc;
border-radius:9px;font-size:15px;font-family:inherit;background:#fff}
input:focus{outline:none;border-color:#2f6fd0;box-shadow:0 0 0 3px rgba(47,111,208,.12)}
button{width:100%;margin-top:20px;padding:12px;border:0;border-radius:9px;background:#2f6fd0;
color:#fff;font-size:15px;font-weight:500;font-family:inherit;cursor:pointer}
button:hover{background:#2860b5}
button.ghost{background:#fff;color:#3c4043;border:1px solid #d5d8dc}
button.ghost:hover{background:#f2f3f5}
button.danger{background:#d93a3a}
.msg{padding:10px 13px;border-radius:9px;font-size:13.5px;margin-bottom:16px}
.err{background:#fdecec;color:#a52222;border:1px solid #f5c2c2}
.ok{background:#e9f7ee;color:#1c6b38;border:1px solid #b7e2c6}
.warn{background:#fef8e7;color:#8a6108;border:1px solid #f6dfa8}
.foot{margin-top:20px;padding-top:16px;border-top:1px solid #eceef0;font-size:12.5px;color:#83868c;text-align:center}
a{color:#2f6fd0;text-decoration:none}
a:hover{text-decoration:underline}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #eceef0;vertical-align:top}
th{font-weight:500;color:#83868c;font-size:12.5px;background:#fafbfc}
.tag{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11.5px;font-weight:500}
.on{background:#e9f7ee;color:#1c6b38}
.off{background:#f2f3f5;color:#83868c}
.banned{background:#fdecec;color:#a52222}
.admin{background:#eaf1fd;color:#25569c}
.src{background:#f0ecfb;color:#5a3fa8}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.inline{display:inline}
.btn-sm{width:auto;margin:0;padding:5px 11px;font-size:12.5px;border-radius:7px}
h2{font-size:16px;font-weight:600;margin:26px 0 10px}
.stat{display:flex;gap:26px;margin-bottom:8px;flex-wrap:wrap}
.stat div span{display:block;font-size:24px;font-weight:600}
.stat div small{color:#83868c;font-size:12.5px}
</style>
</head><body><div class="card__EXTRA__">
"""

_HTML_TAIL = """</div></body></html>"""


def _page(title, body, extra_cls=""):
    """渲染整页。

    页面模板里刻意用 __U_XXX__ 占位，而不是直接写 '/login'：
    服务挂在 /fc27/ 前缀下，写死的绝对路径会把用户甩到主站同名路径去。
    在这里统一替换，保证链接始终指回本服务。
    """
    body = (body
            .replace("__U_LOGIN__", U("/login"))
            .replace("__U_REGISTER__", U("/register"))
            .replace("__U_LOGOUT__", U("/logout"))
            .replace("__U_ADMIN_ACTION__", U("/admin/action"))
            .replace("__DASH__", DASH))
    head = (_HTML_HEAD
            .replace("__TITLE__", html.escape(title))
            .replace("__EXTRA__", extra_cls))
    return head + body + _HTML_TAIL


# PBKDF2 迭代次数。生产固定 200000；自测时可用环境变量调低以免跑太久
# （只影响本机自测，服务部署后仍是 200000）。
PBKDF2_ROUNDS = int(os.environ.get("FC27_PBKDF2_ROUNDS", "200000"))


def _q(sql, args=(), one=False):
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        cur = c.execute(sql, args)
        if sql.strip().lower().startswith("select"):
            rows = cur.fetchall()
            return (rows[0] if rows else None) if one else rows
        c.commit()
        return cur.rowcount
    finally:
        c.close()


def _hash_pw(password, salt=None):
    """PBKDF2-HMAC-SHA256。返回 (salt_hex, hash_hex)。"""
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return salt.hex(), dk.hex()


def _verify_pw(password, salt_hex, hash_hex):
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    _, got = _hash_pw(password, salt)
    return secrets.compare_digest(got, hash_hex)


# ---------------------------------------------------------------- APR1 校验
# Apache 的 .htpasswd 用 $apr1$（MD5-crypt 变体）。新版 Python 已移除 crypt 模块，
# 所以这里自己实现一份纯标准库版本，用来校验内部同事的**原密码**。
# 实现已与服务器上 openssl/htpasswd 现场生成的向量对拍通过。
_ITOA64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _to64(v, n):
    s = ""
    while n > 0:
        s += _ITOA64[v & 0x3F]
        v >>= 6
        n -= 1
    return s


def apr1_crypt(password, salt):
    """算出 APR1 的 hash 部分（不含 $apr1$salt$ 前缀）。"""
    if isinstance(password, str):
        password = password.encode("utf-8")
    if isinstance(salt, str):
        salt = salt.encode("utf-8")
    salt = salt[:8]

    m = hashlib.md5()
    m.update(password + b"$apr1$" + salt)

    alt = hashlib.md5(password + salt + password).digest()

    n = len(password)
    while n > 0:
        m.update(alt[:min(16, n)])
        n -= 16

    i = len(password)
    while i:
        m.update(b"\x00" if (i & 1) else password[:1])
        i >>= 1

    final = m.digest()

    for i in range(1000):
        m2 = hashlib.md5()
        m2.update(password if (i & 1) else final)
        if i % 3:
            m2.update(salt)
        if i % 7:
            m2.update(password)
        m2.update(final if (i & 1) else password)
        final = m2.digest()

    out = _to64((final[0] << 16) | (final[6] << 8) | final[12], 4)
    out += _to64((final[1] << 16) | (final[7] << 8) | final[13], 4)
    out += _to64((final[2] << 16) | (final[8] << 8) | final[14], 4)
    out += _to64((final[3] << 16) | (final[9] << 8) | final[15], 4)
    out += _to64((final[4] << 16) | (final[10] << 8) | final[5], 4)
    out += _to64(final[11], 2)
    return out


def apr1_verify(password, stored):
    """stored 形如 $apr1$salt$hash"""
    if not stored or not stored.startswith("$apr1$"):
        return False
    try:
        _, _, salt, want = stored.split("$", 3)
    except ValueError:
        return False
    return secrets.compare_digest(apr1_crypt(password, salt), want)


def read_htpasswd():
    """读老 htpasswd，返回 {username: hash}。

    每次现读（不做缓存）：这文件只有几行、登录频率也低，
    换来的是"管理员改了原文件里的密码，下一轮登录立刻生效"，
    不需要重启服务。缓存会因文件系统 mtime 精度问题产生偶发不一致。
    """
    data = {}
    try:
        with open(LEGACY_HTPASSWD, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                u, h = line.split(":", 1)
                data[u.strip()] = h.strip()
    except OSError:
        return {}
    return data


def verify_legacy(username, password, mirror=""):
    """内部账号校验。

    优先用**实时** htpasswd 的值（这样改了原文件密码立刻生效），
    文件暂时读不到时退回库里的镜像哈希，避免整个登录挂掉。
    """
    stored = read_htpasswd().get(username) or mirror or ""
    if stored.startswith("$apr1$"):
        return apr1_verify(password, stored)
    # 万一以后换成 bcrypt/其它格式，宁可登录失败也不要静默放行
    return False


def sync_legacy(verbose=False):
    """Existing accounts are authoritative; never rename/recreate credentials at startup/login."""
    missing = []
    for user in LEGACY_ROLES:
        if not _q("SELECT username FROM users WHERE username=?", (user,), one=True):
            missing.append(user)
    if verbose and missing:
        print("[legacy] Existing-only policy: configured names absent from account database: %s" % ", ".join(missing))
    return [], [], missing



def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT UNIQUE NOT NULL,
        salt        TEXT NOT NULL,
        pwhash      TEXT NOT NULL,
        pw_scheme   TEXT NOT NULL DEFAULT 'pbkdf2',
        is_admin    INTEGER NOT NULL DEFAULT 0,
        is_banned   INTEGER NOT NULL DEFAULT 0,
        note        TEXT DEFAULT '',
        created_at  INTEGER NOT NULL,
        created_ip  TEXT DEFAULT '',
        last_login  INTEGER,
        login_count INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS sessions (
        token       TEXT PRIMARY KEY,
        username    TEXT NOT NULL,
        created_at  INTEGER NOT NULL,
        expires_at  INTEGER NOT NULL,
        ip          TEXT DEFAULT '',
        ua          TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS audit (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          INTEGER NOT NULL,
        actor       TEXT DEFAULT '',
        action      TEXT NOT NULL,
        target      TEXT DEFAULT '',
        ip          TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_sess_exp  ON sessions(expires_at);
    CREATE INDEX IF NOT EXISTS idx_audit_ts  ON audit(ts DESC);
    """)
    c.commit()

    # 增量迁移：老库补 pw_scheme 列（既有账号默认 pbkdf2，行为不变）
    cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
    if "pw_scheme" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN pw_scheme TEXT NOT NULL DEFAULT 'pbkdf2'")
        c.commit()
        print("[init] users 表已补 pw_scheme 列（老账号默认 pbkdf2）")

    # 首次启动自建管理员
    if ADMIN_PASS:
        row = c.execute("SELECT id FROM users WHERE username=?", (ADMIN_USER,)).fetchone()
        if not row:
            salt, h = _hash_pw(ADMIN_PASS)
            c.execute("""INSERT INTO users(username,salt,pwhash,pw_scheme,is_admin,note,created_at,created_ip)
                         VALUES(?,?,?,'pbkdf2',1,?,?,?)""",
                      (ADMIN_USER, salt, h, "系统管理员", int(time.time()), "localhost"))
            c.commit()
            print("[init] 已创建管理员账号：%s" % ADMIN_USER)
    c.close()

    # 预置内部账号（沿用原密码那批）
    if LEGACY_ROLES:
        sync_legacy(verbose=True)


def audit(actor, action, target="", ip=""):
    _q("INSERT INTO audit(ts,actor,action,target,ip) VALUES(?,?,?,?,?)",
       (int(time.time()), actor, action, target, ip))


def purge_expired():
    _q("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))


USERNAME_MIN, USERNAME_MAX = 3, 24
PASSWORD_MIN = 8


def valid_username(u):
    if not (USERNAME_MIN <= len(u) <= USERNAME_MAX):
        return False, "用户名长度需在 %d-%d 个字符之间" % (USERNAME_MIN, USERNAME_MAX)
    for ch in u:
        if not (ch.isalnum() or ch in "_-."):
            return False, "用户名只能包含字母、数字、下划线、短横线、点"
    if u[0] in "_-." or u[-1] in "_-.":
        return False, "用户名不能以符号开头或结尾"
    return True, ""


def register(username, password, confirm, ip):
    ok, err = valid_username(username)
    if not ok:
        return False, err
    if len(password) < PASSWORD_MIN:
        return False, "密码至少 %d 位" % PASSWORD_MIN
    if password != confirm:
        return False, "两次输入的密码不一致"
    if len(password) > 200:
        return False, "密码过长"
    if _q("SELECT id FROM users WHERE username=?", (username,), one=True):
        return False, "该用户名已被占用，换一个吧"
    salt, h = _hash_pw(password)
    try:
        _q("""INSERT INTO users(username,salt,pwhash,is_admin,note,created_at,created_ip)
              VALUES(?,?,?,0,?,?,?)""",
           (username, salt, h, "自助注册", int(time.time()), ip))
    except sqlite3.IntegrityError:
        return False, "该用户名已被占用，换一个吧"
    audit(username, "register", username, ip)
    return True, "注册成功"


def login(username, password, ip, ua):
    row = _q("SELECT * FROM users WHERE username=?", (username,), one=True)

    ok = False
    if row:
        if row["pw_scheme"] == "apr1":
            # 内部账号：密码跟老 htpasswd 走（APR1）
            ok = verify_legacy(username, password, row["pwhash"])
        else:
            ok = _verify_pw(password, row["salt"], row["pwhash"])
    elif username in LEGACY_ROLES:
        # 兜底：配置里声明了、但库里还没有（安装脚本没跑，或刚往 htpasswd
        # 里加了新人）。校验通过就地补建，省得要重启服务。
        if verify_legacy(username, password):
            sync_legacy()
            row = _q("SELECT * FROM users WHERE username=?", (username,), one=True)
            ok = row is not None

    if not row or not ok:
        audit(username, "login_fail", username, ip)
        return None, "用户名或密码不正确"
    if row["is_banned"]:
        audit(username, "login_banned", username, ip)
        return None, "该账号已被停用，请联系管理员"
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    _q("""INSERT INTO sessions(token,username,created_at,expires_at,ip,ua)
          VALUES(?,?,?,?,?,?)""",
       (token, username, now, now + SESSION_DAYS * 86400, ip, ua[:200]))
    _q("UPDATE users SET last_login=?, login_count=login_count+1 WHERE id=?",
       (now, row["id"]))
    audit(username, "login", username, ip)
    return token, ""


def check_session(token):
    """返回 (username, is_admin) 或 (None, False)。"""
    if not token:
        return None, False
    row = _q("""SELECT s.username AS u, s.expires_at AS exp, u.is_admin AS adm, u.is_banned AS ban
                FROM sessions s JOIN users u ON u.username = s.username
                WHERE s.token=?""", (token,), one=True)
    if not row:
        return None, False
    if row["exp"] < int(time.time()):
        _q("DELETE FROM sessions WHERE token=?", (token,))
        return None, False
    if row["ban"]:
        _q("DELETE FROM sessions WHERE token=?", (token,))
        return None, False
    return row["u"], row["u"] in ("wulv", "chenchao", "DY") and bool(row["adm"])


def is_internal(username):
    """是否内部账号 —— 决定能不能看 AI 运营分析。

    命中任一即为内部：
      1. 配置登记的内部账号 LEGACY_ROLES（chenchao / wulv / DY / mmoexp）
      2. 管理员（is_admin=1，含 fc27admin）
      3. 库里 pw_scheme='apr1' —— 仍在跟随 htpasswd 的那批内部账号
         （管理页「重置密码」会把 pw_scheme 改成 pbkdf2，那种情况靠第 1 条兜住）

    外部自助注册用户一律不是内部账号。
    """
    if not username:
        return False
    if username in LEGACY_ROLES:
        return True
    row = _q("SELECT is_admin, pw_scheme FROM users WHERE username=?",
             (username,), one=True)
    if not row:
        return False
    return bool(row["is_admin"]) or row["pw_scheme"] == "apr1"


def logout(token):
    if token:
        _q("DELETE FROM sessions WHERE token=?", (token,))


# ---------------------------------------------------------------- 页面

def page_login(err="", ok="", next_url="/s/wulv/fc27-ops/"):
    e = ""
    if err:
        e += '<div class="msg err">%s</div>' % html.escape(err)
    if ok:
        e += '<div class="msg ok">%s</div>' % html.escape(ok)
    nxt = html.escape(next_url, quote=True)
    body = """
<h1>FC27 运营看板</h1>
<p class="sub">只读访问 · 请登录</p>
%s
<form method="post" action="__U_LOGIN__">
  <input type="hidden" name="next" value="%s">
  <label for="u">用户名</label>
  <input id="u" name="username" type="text" autocomplete="username" required autofocus>
  <label for="p">密码</label>
  <input id="p" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">登录</button>
</form>
<div class="foot">还没有账号？<a href="__U_REGISTER__">立即注册（只读权限）</a></div>
""" % (e, nxt)
    return _page("FC27 看板 · 登录", body)


def page_register(err="", ok=""):
    e = ""
    if err:
        e += '<div class="msg err">%s</div>' % html.escape(err)
    if ok:
        e += '<div class="msg ok">%s</div>' % html.escape(ok)
    body = """
<h1>注册只读账号</h1>
<p class="sub">注册后即可查看 FC27 运营数据看板</p>
%s
<div class="msg warn">本账号为<b>只读</b>权限，只能查看，不能修改任何数据。</div>
<form method="post" action="__U_REGISTER__">
  <label for="u">用户名</label>
  <input id="u" name="username" type="text" autocomplete="username" required autofocus
         placeholder="字母/数字/_-. ，3-24 位">
  <label for="p">密码</label>
  <input id="p" name="password" type="password" autocomplete="new-password" required
         placeholder="至少 8 位">
  <label for="p2">确认密码</label>
  <input id="p2" name="confirm" type="password" autocomplete="new-password" required>
  <button type="submit">注册并登录</button>
</form>
<div class="foot">已有账号？<a href="__U_LOGIN__">去登录</a></div>
""" % e
    return _page("FC27 看板 · 注册", body)


def page_admin(username, users, err="", ok=""):
    e = ""
    if err:
        e += '<div class="msg err">%s</div>' % html.escape(err)
    if ok:
        e += '<div class="msg ok">%s</div>' % html.escape(ok)

    total = len(users)
    banned = sum(1 for u in users if u["is_banned"])
    week = sum(1 for u in users if u["created_at"] > time.time() - 7 * 86400)

    rows = []
    for u in users:
        tags = '<span class="tag admin">管理员</span>' if u["is_admin"] else \
               '<span class="tag on">只读</span>'
        if u["pw_scheme"] == "apr1":
            tags += ' <span class="tag src">内部账号</span>'
        if u["is_banned"]:
            tags += ' <span class="tag banned">已停用</span>'
        act = ""
        if u["is_admin"]:
            act = '<span class="tag off">—</span>'
        else:
            if u["is_banned"]:
                act += ('<form class="inline" method="post" action="__U_ADMIN_ACTION__">'
                        '<input type="hidden" name="op" value="unban">'
                        '<input type="hidden" name="target" value="%s">'
                        '<button class="btn-sm ghost" type="submit">解封</button></form> ') % \
                       html.escape(u["username"], quote=True)
            else:
                act += ('<form class="inline" method="post" action="__U_ADMIN_ACTION__" '
                        'onsubmit="return confirm(\'确定停用 %s ？\')">'
                        '<input type="hidden" name="op" value="ban">'
                        '<input type="hidden" name="target" value="%s">'
                        '<button class="btn-sm danger" type="submit">停用</button></form> ') % \
                       (html.escape(u["username"], quote=True), html.escape(u["username"], quote=True))
            act += ('<form class="inline" method="post" action="__U_ADMIN_ACTION__">'
                    '<input type="hidden" name="op" value="reset">'
                    '<input type="hidden" name="target" value="%s">'
                    '<button class="btn-sm ghost" type="submit">重置密码</button></form> ') % \
                   html.escape(u["username"], quote=True)
            act += ('<form class="inline" method="post" action="__U_ADMIN_ACTION__" '
                    'onsubmit="return confirm(\'彻底删除 %s ？不可恢复\')">'
                    '<input type="hidden" name="op" value="delete">'
                    '<input type="hidden" name="target" value="%s">'
                    '<button class="btn-sm ghost" type="submit">删除</button></form>') % \
                   (html.escape(u["username"], quote=True), html.escape(u["username"], quote=True))

        rows.append("""<tr>
<td><b>%s</b><br><span style="color:#83868c;font-size:12px">%s</span></td>
<td>%s</td>
<td>%s</td>
<td>%s</td>
</tr>""" % (html.escape(u["username"]),
            html.escape(u["note"] or ""),
            tags,
            time.strftime("%Y-%m-%d %H:%M", time.localtime(u["created_at"])),
            act))

    body = """
<div class="row" style="justify-content:space-between">
  <div><h1>账号管理</h1>
  <p class="sub">当前登录：%s ｜ 「内部账号」= 沿用原 htpasswd 密码的同事</p></div>
  <form method="post" action="__U_LOGOUT__"><button class="btn-sm ghost" type="submit">退出登录</button></form>
</div>
%s
<div class="stat">
  <div><span>%d</span><small>账号总数</small></div>
  <div><span>%d</span><small>近 7 天新增</small></div>
  <div><span>%d</span><small>已停用</small></div>
</div>
<h2>注册名单</h2>
<table>
<thead><tr><th>用户名</th><th>状态</th><th>注册时间</th><th>操作</th></tr></thead>
<tbody>%s</tbody>
</table>
<div class="foot"><a href="__DASH__">← 返回看板</a></div>
""" % (html.escape(username), e, total, week, banned, "".join(rows))
    return _page("FC27 看板 · 账号管理", body, extra_cls=" wide")


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "fc27-gate/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s - %s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), self.address_string(), fmt % args))

    # ---- 工具
    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None,
              close=False):
        """close=True 时显式关连接。

        必要性：HTTP/1.1 默认 keep-alive。若某个分支在**没读完请求体**的情况下
        直接回错（例如权限不足提前返回 403），socket 里会残留未读字节，
        下一条请求的报文就错位了 —— 客户端表现为"卡住/超时"。
        凡是提前拒绝的分支，一律 close=True。
        """
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        for k, v in (extra or {}).items():
            for header_value in (v if isinstance(v, list) else [v]):
                self.send_header(k, header_value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _redirect(self, url, extra=None):
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            for header_value in (v if isinstance(v, list) else [v]):
                self.send_header(k, header_value)
        self.end_headers()
        # 302 响应带 body（表单纯属浪费），且此时请求体可能没读完。
        # 沿用 keep-alive 会让残留字节污染下一条请求，客户端表现为"提交后卡住"。
        self.close_connection = True

    def _current_identity(self):
        conn = http.client.HTTPConnection("127.0.0.1", 8895, timeout=3)
        try:
            conn.request("GET", "/verify", headers={"Cookie": self.headers.get("Cookie", ""),
                "X-Original-Method": self.command, "X-Original-URI": self.path})
            response = conn.getresponse()
            user = response.getheader("X-Auth-User") if response.status == 200 else None
            response.read()
            return user, user in ("wulv", "chenchao", "DY") if user else False
        except (OSError, http.client.HTTPException):
            return None, False
        finally:
            conn.close()

    def _cookie_token(self):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith(COOKIE_NAME + "="):
                return urllib.parse.unquote(part[len(COOKIE_NAME) + 1:])
        return ""

    def _set_cookie(self, token):
        c = "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d" % (
            COOKIE_NAME, urllib.parse.quote(token), SESSION_DAYS * 86400)
        if COOKIE_SECURE:
            c += "; Secure"
        return {"Set-Cookie": c}

    def _clear_cookie(self):
        return {"Set-Cookie": ["%s=; Path=/; HttpOnly; Max-Age=0" % COOKIE_NAME, "MMOEXP_AUTH=; Path=/; HttpOnly; Secure; Max-Age=0"]}

    def _form(self):
        """读并**完整消费**请求体。

        必须读完：否则 keep-alive 复用同一连接时，残留字节会被当成下一条请求的
        起始行，服务端解析错乱、客户端一直等响应（表现为"提交后卡住"）。
        """
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        if n > 64 * 1024:
            # 过大就丢弃并断开，避免占着连接
            try:
                self.rfile.read(n)
            except Exception:
                pass
            self.close_connection = True
            return {}
        raw = self.rfile.read(n).decode("utf-8", "replace")
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

    def _client_ip(self):
        # nginx 会注入真实来源；没走 nginx 时退回 socket
        xff = self.headers.get("X-Real-IP") or ""
        if not xff:
            xff = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        return xff or self.client_address[0]

    def _safe_next(self, nxt):
        """只允许跳回本站路径，防开放重定向。"""
        nxt = (nxt or "").strip()
        if not nxt.startswith("/") or nxt.startswith("//"):
            return DASH
        # 登录/注册/校验这类功能性路径不作为回跳目标（否则会绕圈）
        for pre in (U("/login"), U("/register"), U("/verify"), U("/logout"), U("/")):
            if pre != U("/") and nxt.startswith(pre):
                return DASH
        return nxt

    def _norm(self, raw_path):
        """剥掉对外前缀，得到服务内部路径。

        nginx 有两种接法，都得兼容：
          A) location /fc27/ { proxy_pass http://...:8896/; }  -> 后端收到 /login
          B) location /fc27/ { proxy_pass http://...:8896; }   -> 后端收到 /fc27/login
        所以这里统一：若以 BASE 开头就剥掉。
        """
        path = raw_path or "/"
        if BASE and (path == BASE or path.startswith(BASE + "/")):
            path = path[len(BASE):] or "/"
        return path.rstrip("/") or "/"

    # ---- 路由
    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        path = self._norm(p.path)
        qs = urllib.parse.parse_qs(p.query)

        if path == "/verify":
            # nginx auth_request 子请求：200 放行，401 拦截
            user, adm = check_session(self._cookie_token())
            if user:
                return self._send(200, "OK", "text/plain; charset=utf-8",
                                  {"X-Fc27-User": user.encode("ascii", "replace").decode(),
                                   "X-Fc27-Role": "admin" if adm else "readonly"})
            return self._send(401, "unauthorized", "text/plain; charset=utf-8")

        if path == "/healthz":
            return self._send(200, json.dumps({"ok": True, "t": int(time.time())}),
                              "application/json; charset=utf-8")

        if path == "/analysis":
            # AI 运营分析：仅内部账号可取。
            # 判据见 is_internal()；外部账号拿到的只有 403，内容不落任何一次响应体。
            user, _adm = self._current_identity()
            if not user:
                return self._send(401, json.dumps({"ok": False, "reason": "unauthenticated"}),
                                  "application/json; charset=utf-8", close=True)
            try:
                with open(ANALYSIS_PATH, "r", encoding="utf-8") as f:
                    payload = f.read()
                json.loads(payload)      # 先校验合法，坏文件不至于把前端渲染搞白
            except FileNotFoundError:
                return self._send(404, json.dumps({"ok": False, "reason": "not_generated"}),
                                  "application/json; charset=utf-8", close=True)
            except Exception:
                return self._send(500, json.dumps({"ok": False, "reason": "bad_content"}),
                                  "application/json; charset=utf-8", close=True)
            return self._send(200, payload, "application/json; charset=utf-8")

        if path in ("/", "/login"):
            if self._current_identity()[0]:
                return self._redirect(self._safe_next(qs.get("next", [""])[0]))
            return self._send(200, page_login(err=qs.get("err", [""])[0],
                                              next_url=self._safe_next(qs.get("next", [""])[0])))
        if path == "/register":
            return self._send(403, "self registration disabled", "text/plain; charset=utf-8", close=True)

        if path == "/logout":
            logout(self._cookie_token())
            return self._redirect(U("/login"), self._clear_cookie())

        if path == "/admin":
            user, adm = self._current_identity()
            if not user:
                return self._redirect(U("/login") + "?next=" + urllib.parse.quote("/admin"))
            if not adm:
                return self._send(403, page_login(err="该账号没有管理权限"),
                                  extra={}, close=True)
            users = _q("SELECT * FROM users ORDER BY created_at DESC")
            return self._send(200, page_admin(user, users,
                                              ok=qs.get("ok", [""])[0],
                                              err=qs.get("err", [""])[0]))

        if path == "/admin/audit":
            user, adm = self._current_identity()
            if not (user and adm):
                return self._send(403, "forbidden", "text/plain; charset=utf-8",
                                  close=True)
            rows = _q("SELECT * FROM audit ORDER BY ts DESC LIMIT 200")
            return self._send(200, json.dumps([dict(r) for r in rows], ensure_ascii=False),
                              "application/json; charset=utf-8")

        return self._send(404, page_login(err="页面不存在"))


    def do_HEAD(self):
        return self.do_GET()

    def do_POST(self):
        path = self._norm(urllib.parse.urlparse(self.path).path)
        ip = self._client_ip()
        ua = self.headers.get("User-Agent") or ""

        if path == "/login":
            f = self._form()
            token, err = login((f.get("username") or "").strip(), f.get("password") or "", ip, ua)
            if err:
                return self._send(401, page_login(err=err,
                                                  next_url=self._safe_next(f.get("next"))))
            nxt = self._safe_next(f.get("next"))
            return self._redirect(nxt, self._set_cookie(token))

        if path == "/register":
            return self._send(403, "self registration disabled", "text/plain; charset=utf-8", close=True)

        if path == "/logout":
            logout(self._cookie_token())
            return self._redirect(U("/login"), self._clear_cookie())

        if path == "/admin/action":
            user, adm = self._current_identity()
            if not (user and adm):
                return self._send(403, "forbidden", "text/plain; charset=utf-8",
                                  close=True)
            f = self._form()
            op = f.get("op") or ""
            target = (f.get("target") or "").strip()
            tgt = _q("SELECT * FROM users WHERE username=?", (target,), one=True)
            if not tgt:
                return self._redirect(U("/admin") + "?err=" + urllib.parse.quote("找不到该账号"))
            if tgt["is_admin"] and op in ("ban", "delete"):
                return self._redirect(U("/admin") + "?err=" + urllib.parse.quote("不能对管理员执行该操作"))

            if op == "ban":
                _q("UPDATE users SET is_banned=1 WHERE username=?", (target,))
                _q("DELETE FROM sessions WHERE username=?", (target,))
                audit(user, "ban", target, ip)
                return self._redirect(U("/admin") + "?ok=" + urllib.parse.quote("已停用 " + target))
            if op == "unban":
                _q("UPDATE users SET is_banned=0 WHERE username=?", (target,))
                audit(user, "unban", target, ip)
                return self._redirect(U("/admin") + "?ok=" + urllib.parse.quote("已解封 " + target))
            if op == "reset":
                newpw = secrets.token_urlsafe(9)
                salt, h = _hash_pw(newpw)
                # 一并把 pw_scheme 改成 pbkdf2：管理员既然手动指定了新密码，
                # 就以新密码为准（内部账号由此"转正"为普通账号，脱离 htpasswd）
                _q("UPDATE users SET salt=?, pwhash=?, pw_scheme='pbkdf2' WHERE username=?",
                   (salt, h, target))
                _q("DELETE FROM sessions WHERE username=?", (target,))
                audit(user, "reset", target, ip)
                tip = ""
                if tgt["pw_scheme"] == "apr1":
                    tip = "（该账号原为内部账号，重置后已改用独立密码，不再跟随 htpasswd）"
                return self._redirect(U("/admin") + "?ok=" + urllib.parse.quote(
                    "已重置 %s 的密码为：%s （请立即转告，刷新后不再显示）%s" % (target, newpw, tip)))
            if op == "delete":
                _q("DELETE FROM users WHERE username=?", (target,))
                _q("DELETE FROM sessions WHERE username=?", (target,))
                audit(user, "delete", target, ip)
                tip = ""
                if target in LEGACY_ROLES:
                    tip = "（注意：该账号在内部账号配置里仍有登记，服务重启或他下次登录时会被重新预置；要长期停用请改用『停用』）"
                return self._redirect(U("/admin") + "?ok=" + urllib.parse.quote(
                    "已删除 " + target + tip))
            return self._redirect(U("/admin") + "?err=" + urllib.parse.quote("未知操作"))

        return self._send(404, "not found", "text/plain; charset=utf-8")



def janitor():
    """每小时清一次过期会话，顺便清 90 天前的审计日志。"""
    while True:
        try:
            purge_expired()
            _q("DELETE FROM audit WHERE ts < ?", (int(time.time()) - 90 * 86400,))
        except Exception as e:
            sys.stderr.write("[janitor] %s\n" % e)
        time.sleep(3600)


def main():
    # Independent FC identity is retired; do not initialize/sync/purge its DB.
    sys.path.insert(0, '/opt/auth-portal/registration-runtime/20261007-ca6258ad')
    from consumer_seams import install_fc as _registration_install_fc
    import native_access_policy as _registration_policy
    _registration_install_fc(sys.modules[__name__], _registration_policy)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    print("[+] FC27 门禁服务已启动 http://127.0.0.1:%d  DB=%s" % (PORT, DB_PATH))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] 收到中断，退出")


if __name__ == "__main__":
    main()
