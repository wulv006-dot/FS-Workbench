#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy_client.py —— 把本地网页工具发布到线上（自助部署通道 · 客户端）

纯 Python 标准库，单文件，不需要 pip install 任何东西。
Windows / macOS / Linux 都能跑。

常用命令
--------
    # 看一眼账号对不对
    python deploy_client.py --whoami

    # 发布整个目录（目录里要有 index.html）
    python deploy_client.py --dir ./我的工具 --site fc-odds --note "FC 赔率看板"

    # 只有单个 HTML 文件
    python deploy_client.py --file 看板.html --site fc-odds

    # 看我已经发布了哪些
    python deploy_client.py --list

    # 下线某个工具
    python deploy_client.py --delete --site fc-odds

账号密码可以不写命令行，三种方式任选（优先级从高到低）：
    1. 命令行 --user / --password
    2. 环境变量 P2PAH_DEPLOY_USER / P2PAH_DEPLOY_PASSWORD
    3. P2PAH_DEPLOY_CONFIG 指向仓库外 deploy_client.json:  {"user":"wulv","password":"xxx"}

鉴权说明（2026-09-30 起）
-------------------------
服务器全站已从浏览器弹窗（nginx Basic Auth）换成统一登录页 + Cookie 会话，
所以本客户端不再发基本认证头：它会先用账号密码登录 /__auth/login，
拿到会话 Cookie 后再调 /deploy/api/*。会话中途过期会自动重新登录并重试一次。
账号密码和以前完全一样，不需要重新申请。

先干跑看看会传什么（不上传）：
    python deploy_client.py --dir ./我的工具 --site fc-odds --dry
"""

import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

# Generated from bundle_policy.py SHA256 07a9d053f769d9488bbf9b1c98cc1106c81a042bc619c7fe3370a0ae72dee722; keep standalone download compatibility.
"""Static site publishing policy shared by client/server; no deployment effects."""
import json
import re
from pathlib import PurePosixPath

EXTENSIONS = frozenset(('.html','.htm','.css','.js','.mjs','.json','.webmanifest','.png','.jpg','.jpeg',
    '.gif','.webp','.avif','.svg','.ico','.woff','.woff2','.ttf','.otf','.eot','.wasm','.mp3','.mp4','.ogg','.webm'))
TEXT_EXTENSIONS = frozenset(('.html','.htm','.css','.js','.mjs','.json','.webmanifest','.svg'))
DENIED_DIRS = frozenset(('.git','.svn','.hg','.venv','venv','node_modules','__pycache__','runtime','logs','backups','data','raw'))
DENIED_NAMES = frozenset(('deploy_client.json','hub_config.json','config.json','server_config.json','automation.json',
    '_token.txt','_ck.txt','_api_body.tmp','apply_log.jsonl','.admin_prices.tmp.json','.cookies.txt','.iggm.cookies.txt'))
SECRET = re.compile(r'''(?i)["']?(password|passwd|client_secret|refresh_token|access_token|api_key|session_token|cookie|set-cookie|batoken|authorization)["']?\s*[:=]\s*["']([^"'\n]+)["']''')
TOKEN = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}|\bya29\.[A-Za-z0-9_-]{20,}|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}')
CREDENTIAL_KEYS = frozenset(('password','passwd','clientsecret','refreshtoken','accesstoken',
    'apikey','sessiontoken','cookie','setcookie','batoken','authorization'))
AUTH_VALUE = re.compile(r'(?i)^\s*(?:Basic|Bearer)\s+\S+')
HEADER_VALUE = re.compile(r'(?i)^\s*(?:Cookie|Set-Cookie|batoken|Authorization)\s*:\s*\S+')
PLACEHOLDER = re.compile(r'^(?:(?:REPLACE|EXAMPLE|YOUR)_[A-Z0-9_]+|\$\{[A-Za-z_][A-Za-z0-9_]*\}|<[A-Z0-9_]+>)$')

def is_placeholder(value):
    if not isinstance(value,str):return False
    if not value or PLACEHOLDER.fullmatch(value):return True
    # A literal header scheme or an explicit template has no credential bytes.
    auth=re.fullmatch(r'(?i)(Basic|Bearer)(?:\s+(.*))?',value)
    return bool(auth and (not (auth.group(2) or '').strip() or PLACEHOLDER.fullmatch(auth.group(2))))

def _json_pairs(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('DUPLICATE_STATIC_JSON_KEY')
        value[key]=item
    return value

def validate_json_value(value, credential=False):
    """Parsed keys handle JSON unicode escapes; never expose a rejected value."""
    if isinstance(value,dict):
        for key,item in value.items():
            name=re.sub(r'[^a-z0-9]','',key.casefold())
            validate_json_value(item,credential or name in CREDENTIAL_KEYS)
    elif isinstance(value,list):
        for item in value:validate_json_value(item,credential)
    elif isinstance(value,str):
        if not is_placeholder(value) and (credential or AUTH_VALUE.search(value)
                                         or HEADER_VALUE.search(value) or TOKEN.search(value)):
            raise ValueError('SENSITIVE_STATIC_CONTENT_REFUSED')
    elif credential and value not in (None,False):
        raise ValueError('SENSITIVE_STATIC_CONTENT_REFUSED')

def validate_publish_name(name):
    if not isinstance(name,str) or not name or '\\' in name or ':' in name or name.startswith('/'):
        raise ValueError('UNSAFE_STATIC_MEMBER')
    parts = name.split('/')
    if any(not p or p in ('.','..') or p.endswith((' ','.')) or any(ord(c)<32 for c in p) for p in parts):
        raise ValueError('UNSAFE_STATIC_MEMBER')
    reserved = frozenset(('con','prn','aux','nul','clock$') + tuple('com'+str(i) for i in range(1,10)) + tuple('lpt'+str(i) for i in range(1,10)))
    if any(p.split('.')[0].lower() in reserved or any(c in p for c in '<>"|?*%') for p in parts):
        raise ValueError('UNSAFE_STATIC_MEMBER')
    low = [p.lower() for p in parts]
    if any(p in DENIED_DIRS or p.startswith('.') for p in low):
        raise ValueError('PRIVATE_STATIC_MEMBER_REFUSED')
    fn = low[-1]
    if fn in DENIED_NAMES or any(x in fn for x in ('cookie','token','credential','password','secret')):
        raise ValueError('PRIVATE_STATIC_MEMBER_REFUSED')
    if PurePosixPath(fn).suffix not in EXTENSIONS:
        raise ValueError('STATIC_TYPE_NOT_ALLOWED')
    return name

def validate_publish_content(name, data):
    validate_publish_name(name)
    if PurePosixPath(name).suffix.lower() not in TEXT_EXTENSIONS:
        return
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('STATIC_TEXT_ENCODING_REFUSED') from None
    if TOKEN.search(text):
        raise ValueError('SENSITIVE_STATIC_CONTENT_REFUSED')
    if PurePosixPath(name).suffix.lower() in ('.json','.webmanifest'):
        try:
            value=json.loads(text,object_pairs_hook=_json_pairs,
                parse_constant=lambda value:(_ for _ in ()).throw(ValueError('INVALID_STATIC_JSON')))
            validate_json_value(value)
        except (json.JSONDecodeError,RecursionError):
            raise ValueError('INVALID_STATIC_JSON') from None
    for match in SECRET.finditer(text):
        value = match.group(2)
        if is_placeholder(value):
            continue
        raise ValueError('SENSITIVE_STATIC_CONTENT_REFUSED')

def escaped_text(value):
    import html
    return html.escape(str(value or ''), quote=True)

def validated_zip_members(data, max_files=5000, max_unzip=300*1024*1024):
    """Validate every member and CRC before returning any bytes to the writer."""
    import io
    import zipfile
    import stat
    result, seen, files, total = [], set(), set(), 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > max_files:
                raise ValueError('STATIC_MEMBER_LIMIT')
            for info in infos:
                raw = info.filename
                if info.flag_bits & 1:
                    raise ValueError('ENCRYPTED_STATIC_MEMBER_REFUSED')
                mode = (info.external_attr >> 16) & 0xF000
                if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError('SPECIAL_STATIC_MEMBER_REFUSED')
                directory = info.is_dir()
                name = raw[:-1] if directory else raw
                # Reuse full path validation without granting a file type exception.
                validate_publish_name(name + '/directory-check.css' if directory else name)
                key = name.casefold()
                if key in seen:
                    raise ValueError('DUPLICATE_STATIC_MEMBER_REFUSED')
                seen.add(key)
                parents = ['/'.join(key.split('/')[:i]) for i in range(1,len(key.split('/')))]
                if any(p in files for p in parents) or (not directory and any(s.startswith(key+'/') for s in seen)):
                    raise ValueError('STATIC_HIERARCHY_CONFLICT')
                if directory:
                    continue
                files.add(key)
                total += info.file_size
                if total > max_unzip or info.file_size < 0:
                    raise ValueError('STATIC_BYTE_LIMIT')
                payload = archive.read(info)  # CRC checked by zipfile, bounded by declared size.
                if len(payload) != info.file_size:
                    raise ValueError('STATIC_SIZE_MISMATCH')
                validate_publish_content(name, payload)
                result.append((name, payload))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
        raise ValueError('INVALID_STATIC_ARCHIVE') from None
    if not result:
        raise ValueError('EMPTY_STATIC_ARCHIVE')
    return result

# End generated publishing policy.

# ------------------------------------------------------------------ 默认值

# 默认走 HTTPS：会话 Cookie 带 Secure 标记，且账号密码不该走明文。
# （服务器用的是 Let's Encrypt 签发的 IP 证书，正常 Python 能验通过，无需忽略证书校验。）
DEFAULT_SERVER = "https://47.85.224.112"
DEFAULT_PREFIX = "/deploy"

# 统一登录门户（2026-09-30 起，全站鉴权从 nginx Basic Auth 换成了
# 「HTML 登录页 + Cookie 会话」）。所以客户端不再发基本认证头，
# 而是先用账号密码 POST 到 AUTH_LOGIN 换一张会话 Cookie，再带着它调 /deploy/api/*。
AUTH_LOGIN = "/__auth/login"
AUTH_COOKIE = "MMOEXP_AUTH"

# 打包时跳过的目录名
EXCLUDE_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", ".idea", ".vscode",
    "node_modules", ".venv", "venv", "env", ".pytest_cache",
    ".mypy_cache", ".cache", ".ipynb_checkpoints",
}
# 打包时跳过的文件名
EXCLUDE_FILES = {".DS_Store", "Thumbs.db", "desktop.ini", ".gitignore"}
# 打包时跳过的后缀
EXCLUDE_EXT = {".pyc", ".pyo", ".pdb", ".log", ".tmp", ".bak", ".orig", ".swp"}

# 单个文件超过这个大小就提醒（服务器上传上限 100 MB）
WARN_FILE_MB = 20


def init_console():
    """Windows 控制台可能是 GBK，任何非 GBK 字符都会让脚本崩掉。"""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def say(*a):
    """异常安全的打印 —— 打印失败绝不能让发布流程挂掉。"""
    try:
        print(*a)
    except Exception:
        try:
            print(" ".join(str(x) for x in a).encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass


def human(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return ("%.0f %s" if u == "B" else "%.1f %s") % (n, u)
        n /= 1024.0


# ------------------------------------------------------------------ 账号

def load_creds(A):
    here = os.path.dirname(os.path.abspath(__file__))
    # Never autodiscover credentials in a source tree or publisher working directory.
    config_path = os.environ.get("P2PAH_DEPLOY_CONFIG", "")
    cand = [config_path] if config_path else []
    user = passwd = None
    for p in cand:
        if os.path.isfile(p):
            try:
                cfg = json.load(open(p, encoding="utf-8"))
                user = user or cfg.get("user")
                passwd = passwd or cfg.get("password")
            except Exception:
                pass
    user = A.user or os.environ.get("P2PAH_DEPLOY_USER") or user
    passwd = A.password or os.environ.get("P2PAH_DEPLOY_PASSWORD") or passwd
    return user, passwd


# ------------------------------------------------------------------ HTTP

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """不自动跟随 302。

    统一登录门户的「未登录」响应是 302 -> /__auth/login，登录接口自己在 302
    响应上带 Set-Cookie。必须由我们自己看这两个响应，不能被 urllib 悄悄跟掉。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _pick_cookie(headers, name):
    """从响应头里挑出 `name=值` 这一段（不含 Path/HttpOnly 等属性）。"""
    for k, v in (headers.items() if headers else []):
        if k.lower() != "set-cookie":
            continue
        first = v.split(";", 1)[0].strip()
        if first.startswith(name + "="):
            return first
    return None


class Ctx(object):
    def __init__(self, server, user, passwd, timeout=600, verbose=False,
                 prefix=DEFAULT_PREFIX):
        self.server = server.rstrip("/")
        self.user = user
        self.passwd = passwd
        self.timeout = timeout
        self.verbose = verbose
        self.prefix = (prefix or "").rstrip("/")
        self._cookie = None
        self._opener = urllib.request.build_opener(_NoRedirect)

    def url(self, path):
        return self.server + self.prefix + path

    # -------- 登录：换一张会话 Cookie --------
    def login(self):
        """用账号密码登录统一门户，拿到 MMOEXP_AUTH 会话 Cookie。"""
        if self._cookie:
            return self._cookie
        if not self.user or not self.passwd:
            raise SystemExit(
                "\n[X] 没拿到账号或密码。三种写法任选一种：\n"
                "    1) 命令行：  --user %s --password 你的密码\n"
                "    2) 环境变量：P2PAH_DEPLOY_USER / P2PAH_DEPLOY_PASSWORD\n"
                "    3) 仓库外 deploy_client.json（由 P2PAH_DEPLOY_CONFIG 指定）：{\"user\":\"%s\",\"password\":\"你的密码\"}\n"
                % (self.user or "wulv", self.user or "wulv"))
        form = urllib.parse.urlencode({
            "username": self.user,
            "password": self.passwd,
            "remember": "1",
        }).encode("utf-8")
        req = urllib.request.Request(self.server + AUTH_LOGIN, data=form, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Accept", "text/html,application/json")
        if self.verbose:
            say("    [req] POST %s%s （登录取会话）" % (self.server, AUTH_LOGIN))
        try:
            r = self._opener.open(req, timeout=min(self.timeout, 60))
            code, hdrs = r.status, r.headers
            r.read()
        except urllib.error.HTTPError as e:
            code, hdrs = e.code, e.headers
        except urllib.error.URLError as e:
            raise SystemExit(
                "\n[X] 连不上服务器 %s\n    %s\n"
                "    检查：网络是否正常；地址是否写对（默认 %s）\n"
                % (self.server, e, DEFAULT_SERVER))
        ck = _pick_cookie(hdrs, AUTH_COOKIE)
        if not ck:
            raise SystemExit(
                "\n[X] 登录失败：没拿到会话 Cookie（HTTP %s）。\n"
                "    最可能的原因：账号或密码不对（登录页会原地报错，不发 Cookie）。\n"
                "    当前账号：%s\n"
                "    检查方法：python deploy_client.py --whoami\n"
                "    也可设置 P2PAH_DEPLOY_CONFIG 指向仓库外配置：\n"
                '      {"user":"%s","password":"你的密码"}\n'
                % (code, self.user, self.user or "wulv"))
        self._cookie = ck
        if self.verbose:
            say("    [res] 登录成功，会话已就绪")
        return ck

    def http(self, method, path, body=None, ctype=None, _retry=True):
        self.login()
        url = self.url(path)
        if self.verbose:
            say("    [req] %s %s (%s)" % (method, url, human(len(body)) if body else "无请求体"))
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Cookie", self._cookie)
        req.add_header("Accept", "application/json")
        if ctype:
            req.add_header("Content-Type", ctype)
        t0 = time.time()
        try:
            r = self._opener.open(req, timeout=self.timeout)
            raw, code, hdrs = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e:
            raw, code, hdrs = e.read(), e.code, e.headers
            if code in (301, 302, 303, 307, 308):
                loc = (hdrs.get("Location") or "") if hdrs else ""
                if _retry and AUTH_LOGIN in loc:
                    # 会话过期：重新登录一次再重发（此时请求还没到后端，重发无副作用）
                    if self.verbose:
                        say("    [res] 会话已失效，重新登录后重试…")
                    self._cookie = None
                    self.login()
                    return self.http(method, path, body, ctype, _retry=False)
                raise SystemExit(
                    "\n[X] 被跳转到登录页，说明这次没通过鉴权。\n    账号：%s\n"
                    "    重新跑一次命令即可（客户端会自动重新登录）。\n" % self.user)
            if code == 401:
                raise SystemExit(
                    "\n[X] 登录被拒（401）。账号或密码不对。\n"
                    "    当前用的账号：%s\n"
                    "    检查方法：python deploy_client.py --whoami\n"
                    "    也可设置 P2PAH_DEPLOY_CONFIG 指向仓库外配置：\n"
                    '      {"user":"%s","password":"你的密码"}' % (self.user, self.user))
            try:
                msg = json.loads(raw.decode("utf-8")).get("error") or raw.decode("utf-8")[:300]
            except Exception:
                msg = raw.decode("utf-8", "replace")[:300] or ("HTTP %d" % code)
            raise SystemExit("\n[X] 服务器拒绝了这次请求（HTTP %d）：\n    %s\n" % (code, msg))
        except urllib.error.URLError as e:
            raise SystemExit(
                "\n[X] 连不上服务器 %s\n    %s\n"
                "    检查：网络是否正常；地址是否写对（默认 %s）\n"
                % (self.server, e, DEFAULT_SERVER))
        if self.verbose:
            say("    [res] HTTP %d，%.2f 秒" % (code, time.time() - t0))
        txt = raw.decode("utf-8", "replace")
        try:
            return json.loads(txt)
        except Exception:
            raise SystemExit("\n[X] 服务器返回的不是 JSON：\n    %s\n" % txt[:400])


# ------------------------------------------------------------------ 打包

def skip(name, is_dir, no_exclude):
    if no_exclude:
        return False
    if is_dir:
        return name in EXCLUDE_DIRS
    if name in EXCLUDE_FILES:
        return True
    return os.path.splitext(name)[1].lower() in EXCLUDE_EXT


def make_zip(src_dir, no_exclude=False):
    src_dir = os.path.abspath(src_dir)
    if not os.path.isdir(src_dir):
        raise SystemExit("[X] 不是目录：%s" % src_dir)
    buf = io.BytesIO()
    files = []
    raw_bytes = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, fs in os.walk(src_dir):
            dirs[:] = sorted(d for d in dirs if not skip(d, True, no_exclude))
            if any(os.path.islink(os.path.join(root,d)) for d in dirs):
                raise ValueError("STATIC_SYMLINK_REFUSED")
            for f in sorted(fs):
                if skip(f, False, no_exclude):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, src_dir).replace("\\", "/")
                if os.path.islink(full):
                    raise ValueError("STATIC_SYMLINK_REFUSED")
                with open(full, "rb") as source:
                    content = source.read()
                validate_publish_content(rel, content)
                z.writestr(rel, content)
                sz = len(content)
                files.append((rel, sz))
                raw_bytes += sz
    data = buf.getvalue()
    validated_zip_members(data)
    return data, files, raw_bytes


def precheck(files):
    """上传前先自己检查一遍，把服务器会拒的原因提前说清楚。"""
    names = [n for n, _ in files]
    low = [n.lower() for n in names]
    warn = []
    if "index.html" not in low:
        htmls = [n for n in names if n.lower().endswith((".html", ".htm"))]
        if len(htmls) == 1:
            warn.append("没有 index.html，但只有一个 HTML（%s）—— 服务器会自动改名为 index.html" % htmls[0])
        elif htmls:
            warn.append("没有 index.html，找到 %d 个 HTML：%s。"
                        "服务器会拒绝，请把首页改名为 index.html"
                        % (len(htmls), "、".join(htmls[:6])))
        else:
            warn.append("目录里没有任何 .html 文件 —— 这不像一个网页工具")
    big = [(n, s) for n, s in files if s > WARN_FILE_MB * 1024 * 1024]
    if big:
        warn.append("有 %d 个超过 %d MB 的大文件：%s"
                    % (len(big), WARN_FILE_MB,
                       "、".join("%s(%s)" % (n, human(s)) for n, s in big[:4])))
    return warn


def check_rels(files, base="."):
    """提醒容易踩的坑：绝对路径引用。

    部署到 /s/<用户>/<工具>/ 这种子路径下，页面里写死的 /style.css、
    /api/xxx 会打到站点根目录（别的应用），必然 404。
    """
    hits = []
    for n, _ in files:
        if not n.lower().endswith((".html", ".htm")):
            continue
        try:
            with open(os.path.join(base, n), encoding="utf-8", errors="ignore") as f:
                txt = f.read()
        except Exception:
            continue
        for pat in ('src="/', "src='/", 'href="/', "href='/", 'url(/', '"/api/'):
            if pat in txt:
                hits.append((n, pat))
                break
    return hits


# ------------------------------------------------------------------ 命令

def cmd_whoami(ctx):
    say("[*] 服务器：%s" % ctx.server)
    say("[*] 账号  ：%s" % ctx.user)
    h = ctx.http("GET", "/api/health")
    say("    [OK] 服务正常，版本 %s" % h.get("version"))
    sites = ctx.http("GET", "/api/sites")
    mine = [s for s in sites if s.get("mine")]
    say("    [OK] 登录成功。你名下已有 %d 个站点%s"
        % (len(mine), "" if not mine else "：" + "、".join(s["site"] for s in mine)))
    return 0


def cmd_list(ctx):
    sites = ctx.http("GET", "/api/sites")
    if not sites:
        say("[*] 服务器上还没有任何工具")
        return 0
    mine = [s for s in sites if s.get("mine")]
    other = [s for s in sites if not s.get("mine")]
    for title, group in (("我的工具", mine), ("同事的工具", other)):
        if not group:
            continue
        say("")
        say("[*] %s（%d）" % (title, len(group)))
        for s in group:
            say("    %-20s v%-3s %-10s %s"
                % (s["site"], s["version"], human(s["bytes"]), s["url"]))
            if s.get("note"):
                say("      %s" % s["note"])
    say("")
    say("    提示：链接需要登录（未登录会自动跳到统一登录页，账号同看板）")
    return 0


def cmd_delete(ctx, site):
    r = ctx.http("POST", "/api/delete",
                 json.dumps({"site": site}).encode("utf-8"),
                 ctype="application/json; charset=utf-8")
    say("[+] 已下线：%s" % site)
    say("    %s" % r.get("note", ""))
    return 0


def cmd_deploy(ctx, A):
    # ---- 准备压缩包 ----
    base = (os.path.dirname(os.path.abspath(A.file)) if A.file
            else os.path.abspath(A.dir or "."))
    if A.file:
        p = os.path.abspath(A.file)
        if not os.path.isfile(p):
            raise SystemExit("[X] 文件不存在：%s" % p)
        data = open(p, "rb").read()
        if p.lower().endswith(".zip"):
            validated_zip_members(data)
        else:
            validate_publish_content(os.path.basename(p), data)
        if p.lower().endswith((".html", ".htm")):
            say("[*] 单个 HTML 文件：%s（%s）" % (os.path.basename(p), human(len(data))))
        else:
            say("[*] 上传文件：%s（%s）" % (os.path.basename(p), human(len(data))))
        files = [(os.path.basename(p), len(data))]
        raw_bytes = len(data)
    else:
        src = A.dir or "."
        say("[*] 打包目录：%s" % os.path.abspath(src))
        t0 = time.time()
        data, files, raw_bytes = make_zip(src, A.all)
        if not files:
            raise SystemExit("[X] 目录里没有可上传的文件（是不是全被排除了？加 --all 试试）")
        say("    [OK] %d 个文件，原始 %s -> 压缩后 %s（%.1f 秒）"
            % (len(files), human(raw_bytes), human(len(data)), time.time() - t0))
        for n, s in files[:12]:
            say("         %-52s %s" % (n[:52], human(s)))
        if len(files) > 12:
            say("         ... 还有 %d 个" % (len(files) - 12))

        for w in precheck(files):
            say("    [!] %s" % w)
        hits = check_rels(files, base)
        if hits:
            say("")
            say("    [!] 发现「绝对路径引用」—— 部署到子路径后这些资源会 404：")
            for n, pat in hits[:6]:
                say("         %s  ->  %s" % (n, pat))
            say("        建议改成相对路径（./style.css、./api/x），"
                "或去掉开头的斜杠。")

    if len(data) > 100 * 1024 * 1024:
        raise SystemExit("[X] 压缩包 %s 超过服务器上限 100 MB，请精简后再传" % human(len(data)))

    if A.dry:
        say("")
        say("[*] --dry 干跑模式：没有上传。去掉 --dry 就会真的发布。")
        return 0

    # ---- 上传 ----
    say("")
    say("[*] 上传到 %s" % ctx.server)
    q = "/api/deploy?site=%s" % A.site
    if A.note:
        q += "&note=" + urllib.parse.quote(A.note)
    t0 = time.time()
    r = ctx.http("POST", q, data, ctype="application/octet-stream")
    el = time.time() - t0

    say("")
    say("=" * 60)
    say("  发布成功！")
    say("  工具名   %s" % r["site"])
    say("  版本     v%s" % r["version"])
    say("  文件     %d 个，%s" % (r["files"], human(r["bytes"])))
    if r.get("stripped_root"):
        say("  提示     压缩包多了一层目录，已自动剥掉")
    say("  耗时     %.1f 秒" % el)
    say("")
    say("  访问链接：")
    say("    %s%s" % (ctx.server, r["url"]))
    say("=" * 60)
    say("")
    say("  把这个链接发给要用的人即可。")
    say("  第一次打开会跳到统一登录页（和看板同一套账号，不再是浏览器弹窗）。")
    if r.get("backup"):
        say("  上一个版本已备份为 %s，传错了我可以帮你回滚。" % r["backup"])
    return 0


# ------------------------------------------------------------------ main

def main():
    init_console()
    ap = argparse.ArgumentParser(
        description="把本地网页工具发布到线上",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("常用命令")[-1])

    ap.add_argument("--dir", help="要发布的目录（里面要有 index.html）")
    ap.add_argument("--file", help="只发布一个文件（.html 或 .zip）")
    ap.add_argument("--site", help="站点名：小写字母/数字/下划线/短横线，例如 fc-odds")
    ap.add_argument("--note", default="", help="说明文字，会显示在工具列表里")
    ap.add_argument("--list", action="store_true", help="列出已发布的工具")
    ap.add_argument("--delete", action="store_true", help="下线某个工具（配合 --site）")
    ap.add_argument("--whoami", action="store_true", help="检查账号密码和服务连通性")
    ap.add_argument("--dry", action="store_true", help="只打包检查，不上传")
    ap.add_argument("--all", action="store_true",
                    help="不排除任何文件（默认会跳过 .git / __pycache__ / node_modules 等）")
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--prefix", default=DEFAULT_PREFIX,
                    help="API 路径前缀（默认 %s，本地调试才需要改）" % DEFAULT_PREFIX)
    ap.add_argument("--user")
    ap.add_argument("--password")
    ap.add_argument("-v", "--verbose", action="store_true")
    A = ap.parse_args()

    if not any([A.dir, A.file, A.list, A.delete, A.whoami]):
        ap.print_help()
        say("")
        say("最常用的一条命令：")
        say("  python deploy_client.py --dir ./我的工具 --site fc-odds --note \"FC 赔率看板\"")
        say("")
        say("（把账号密码写在仓库外 deploy_client.json（由 P2PAH_DEPLOY_CONFIG 指定） 里就不用每次输：")
        say('  {"user":"wulv","password":"你的密码"} ）')
        return 1

    user, passwd = load_creds(A)
    if not user or not passwd:
        raise SystemExit(
            "[X] 还没有配置账号密码。三种方式任选：\n"
            "    1) 命令行：  --user wulv --password 你的密码\n"
            "    2) 环境变量：set P2PAH_DEPLOY_USER=wulv & set P2PAH_DEPLOY_PASSWORD=xxx\n"
            "    3) 建文件：  在 deploy_client.py 同目录建 deploy_client.json\n"
            '                 {"user":"wulv","password":"你的密码"}')

    ctx = Ctx(A.server, user, passwd, verbose=A.verbose, prefix=A.prefix)

    try:
        if A.whoami:
            return cmd_whoami(ctx)
        if A.list:
            return cmd_list(ctx)
        if A.delete:
            if not A.site:
                raise SystemExit("[X] --delete 要配上 --site 指定要下线哪个工具")
            return cmd_delete(ctx, A.site)
        if not A.site:
            raise SystemExit("[X] 缺 --site 参数。站点名只能用英文小写字母、数字、"
                             "下划线、短横线，例如 fc-odds")
        return cmd_deploy(ctx, A)
    except KeyboardInterrupt:
        say("")
        say("[!] 已取消")
        return 130


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        say("")
        say("[X] 出错了：%r" % (e,))
        say("    把上面这些信息发给陈超，我来看。")
        sys.exit(1)
