#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy_server.py —— 自助部署通道（服务器端）

零第三方依赖：http.server + sqlite3 + zipfile

职责
----
接收使用者上传的工具包（zip 或单个 HTML），原子发布到
    /var/www/sites/<owner>/<site>/
对外 URL
    http://<host>/s/<owner>/<site>/

安全边界（这是「不开 SSH」的替代方案，边界必须清楚）
--------------------------------------------------
- owner 只认 nginx 注入的 X-Remote-User，客户端伪造无效（nginx 会覆盖请求头）
- 只能写 /var/www/sites/<owner>/<site>/，目录名过严格白名单正则
- 解压时拒绝：绝对路径 / .. 穿越 / 符号链接 / 加密项 / zip bomb（体积、数量双限）
- 只能删除自己名下的站点
- 服务以 root 跑，但落地文件 chmod 755/644 —— nginx 可读不可写
"""

import io
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

# ----------------------------------------------------------------- 配置

HERE = os.path.dirname(os.path.abspath(__file__))
ARGS = None

DEFAULT_CFG = {
    # 站点根目录（对外 /s/ 映射到这里）
    "sites_dir": "/var/www/sites",
    # 服务自己的工作目录
    "work_dir": "/opt/deploy-hub",
    # 上传上限（字节）。nginx 的 client_max_body_size 要 >= 这个值
    "max_upload": 100 * 1024 * 1024,
    # 解压后总大小上限（防 zip bomb）
    "max_unzip": 300 * 1024 * 1024,
    # 压缩包内文件数上限
    "max_files": 5000,
    # 每个站点保留几份历史备份
    "keep_backups": 3,
    # 对外访问前缀（仅用于拼给用户看的 URL）
    "url_prefix": "/s/",
    # 站点名白名单：小写字母开头，可含数字、下划线、短横线
    "site_re": r"^[a-z0-9][a-z0-9_-]{0,30}$",
    # 公开只读列表页（不带认证访问 /deploy/ 时）—— None 表示必须认证
    "public_list": False,
    # 免认证下载客户端脚本
    "public_client": True,
}

CFG = dict(DEFAULT_CFG)
DB_LOCK = threading.Lock()

# 站点名 / 用户名只允许这些字符，其余一律拒绝（防注入路径）
RE_BAD_NAME = re.compile(r"[^a-z0-9_-]")
# zip 内部条目的文件名里，Windows 非法字符换成下划线
RE_BAD_FN = re.compile(r'[\x00-\x1f<>:"|?*\\]')


class HubError(Exception):
    """业务错误 —— 会把 message 原样回给使用者"""
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


# ----------------------------------------------------------------- 工具

def init_console():
    """把标准输出/错误切到 UTF-8，并对打印做异常兜底。

    服务器上 systemd 的 journal 一般能收 UTF-8，但 stdout 若被重定向到
    文件、或 LANG 没设置时，默认编码可能是 ASCII —— 一条中文日志就能
    让整个请求 500。所以所有输出都必须走 safe() 包装。
    """
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def safe(*a):
    try:
        print(*a)
    except Exception:
        try:
            print(" ".join(str(x) for x in a).encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass
    try:
        sys.stdout.flush()
    except Exception:
        pass


def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def human(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return ("%.0f %s" if u == "B" else "%.1f %s") % (n, u)
        n /= 1024.0


def load_cfg():
    global CFG
    CFG = dict(DEFAULT_CFG)
    p = os.path.join(HERE, "hub_config.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                CFG.update(json.load(f))
        except Exception as e:
            safe("[!] hub_config.json 读取失败：%s" % e)
    return CFG


# ----------------------------------------------------------------- 数据库

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
  owner      TEXT NOT NULL,
  name       TEXT NOT NULL,
  note       TEXT,
  files      INTEGER DEFAULT 0,
  bytes      INTEGER DEFAULT 0,
  version    INTEGER DEFAULT 1,
  created_at REAL,
  updated_at REAL,
  updated_by TEXT,
  PRIMARY KEY (owner, name)
);
CREATE TABLE IF NOT EXISTS logs (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  ts     REAL,
  owner  TEXT,
  action TEXT,
  site   TEXT,
  detail TEXT,
  ip     TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts DESC);
"""


def db_path():
    return os.path.join(CFG["work_dir"], "data", "hub.db")


def db():
    os.makedirs(os.path.dirname(db_path()), exist_ok=True)
    c = sqlite3.connect(db_path(), timeout=20)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return c


def init_db():
    os.makedirs(CFG["work_dir"], exist_ok=True)
    # 注意：必须用 os.path.dirname 取父目录。写死 "/" 在 Windows 上不成立
    # （本地跑测试时踩过：目录没建出来 -> unable to open database file）
    os.makedirs(os.path.dirname(db_path()), exist_ok=True)
    os.makedirs(CFG["sites_dir"], exist_ok=True)
    for sub in ("staging", "backup"):
        os.makedirs(os.path.join(CFG["work_dir"], sub), exist_ok=True)
    with db() as c:
        c.executescript(SCHEMA)


def log_action(owner, action, site="", detail="", ip=""):
    try:
        with DB_LOCK, db() as c:
            c.execute("INSERT INTO logs(ts,owner,action,site,detail,ip) VALUES(?,?,?,?,?,?)",
                      (time.time(), owner, action, site, str(detail)[:2000], ip))
            # 只留最近 5000 条
            c.execute("DELETE FROM logs WHERE id < (SELECT MAX(id)-5000 FROM logs)")
    except Exception as e:
        safe("[!] 写日志失败：%s" % e)


# ----------------------------------------------------------------- 校验

def check_name(v, what):
    v = (v or "").strip().lower()
    if not v:
        raise HubError("缺少%s" % what)
    if not re.match(CFG["site_re"], v):
        raise HubError("%s「%s」不合法：只能用英文小写字母、数字、下划线、短横线，"
                       "且以字母或数字开头，最长 31 字符（例如 fc-odds、fc_tools）"
                       % (what, v))
    return v


def decode_zip_name(raw):
    """zipfile 默认按 cp437 解文件名，中文名会变乱码。

    先按 cp437→utf-8 试（现代压缩工具 + UTF-8 标志位），失败再试 gbk
    （Windows 自带「发送到压缩文件夹」、WinRAR 老版本）。
    """
    if not raw:
        return raw
    # 有 UTF-8 标志位（bit 11）时 zipfile 已经正确解码
    try:
        return raw.encode("cp437").decode("utf-8")
    except Exception:
        pass
    try:
        return raw.encode("cp437").decode("gbk")
    except Exception:
        return raw


def normalize_rel(name):
    """把 zip 内的条目路径规整成安全相对路径。不安全就抛 HubError。"""
    if name is None:
        raise HubError("压缩包里有空文件名")
    s = name.replace("\\", "/")
    if s.startswith("/") or re.match(r"^[A-Za-z]:", s):
        raise HubError("压缩包里有绝对路径，拒绝：%s" % name)
    parts = []
    for seg in s.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise HubError("压缩包里有「..」路径穿越，拒绝：%s" % name)
        parts.append(RE_BAD_FN.sub("_", seg))
    return "/".join(parts)


# ----------------------------------------------------------------- 解包

def safe_extract(data, dest):
    """把 zip 字节流传到 dest。返回 (文件数, 字节数)。

    拒绝：路径穿越 / 绝对路径 / 符号链接 / 加密项 / 超量（体积、数量）。
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise HubError("这不是一个有效的 zip 压缩包（%s）。"
                       "如果是单个 HTML 文件，直接上传 .html 即可。" % e)

    infos = zf.infolist()
    if len(infos) > CFG["max_files"]:
        raise HubError("压缩包内条目过多（%d > %d），请检查是否误打包了依赖目录"
                       % (len(infos), CFG["max_files"]))

    total = 0
    for i in infos:
        total += i.file_size
        if total > CFG["max_unzip"]:
            raise HubError("解压后体积过大（超过 %s），请精简后再传"
                           % human(CFG["max_unzip"]))

    n_file = 0
    n_bytes = 0
    written = []          # 已落地文件的真实路径，用于最后统一 chmod
    for info in infos:
        name = normalize_rel(decode_zip_name(info.filename))
        if not name:
            continue
        if info.is_dir():
            continue
        # 加密项：读出来是乱码，直接拒
        if info.flag_bits & 0x1:
            raise HubError("压缩包里有加密文件，不支持：%s" % info.filename)
        # 符号链接：external_attr 高位是 unix mode
        if (info.external_attr >> 16) & 0xF000 == 0xA000:
            raise HubError("压缩包里有符号链接，拒绝：%s" % info.filename)

        out = os.path.join(dest, *name.split("/"))
        # 双保险：解析后的真实路径必须在 dest 里
        real = os.path.realpath(out)
        if not (real == os.path.realpath(dest)
                or real.startswith(os.path.realpath(dest) + os.sep)):
            raise HubError("压缩包内有文件会解压到目标目录之外，拒绝：%s" % info.filename)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with zf.open(info) as src, open(out, "wb") as dst:
            while True:
                chunk = src.read(1 << 18)
                if not chunk:
                    break
                dst.write(chunk)
        n_file += 1
        n_bytes += os.path.getsize(out)
        written.append(out)

    zf.close()
    if n_file == 0:
        raise HubError("压缩包里没有文件（只有空目录？）")
    return n_file, n_bytes


def strip_single_root(dest):
    """如果解压出来只有一层目录（打包时多包了一层），把内容提到根。

    实测很常见：Windows 右键「压缩到 zip」会生成 my-tool/xxx，
    直接发布就会变成 /s/wulv/fc/my-tool/index.html，首页 404。
    """
    entries = [e for e in os.listdir(dest) if not e.startswith(".")]
    if len(entries) != 1:
        return False
    inner = os.path.join(dest, entries[0])
    if not os.path.isdir(inner):
        return False
    # 只有一层、且里面确实像个站点（有 index.html 或任何 html），才剥
    kids = os.listdir(inner)
    if not kids:
        return False
    for e in kids:
        shutil.move(os.path.join(inner, e), os.path.join(dest, e))
    try:
        os.rmdir(inner)
    except OSError:
        pass
    return True


def require_index(dest):
    """发布前必须能确定一个首页。返回首页文件名。"""
    idx = os.path.join(dest, "index.html")
    if os.path.isfile(idx):
        return "index.html"
    # 唯一一个 html 时，帮它改名（省得同事来回折腾）
    htmls = []
    for root, dirs, files in os.walk(dest):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.lower().endswith((".html", ".htm")):
                htmls.append(os.path.relpath(os.path.join(root, f), dest))
    if len(htmls) == 1:
        src = os.path.join(dest, htmls[0])
        shutil.move(src, idx)
        return "index.html（由 %s 自动改名）" % htmls[0]
    if not htmls:
        raise HubError("包里没有找到任何 .html 文件 —— 网页工具至少要有一个首页，"
                       "请把首页命名为 index.html")
    raise HubError("包里没有 index.html，但找到了 %d 个 HTML 文件：%s。"
                   "请把作为首页的那个改名为 index.html"
                   % (len(htmls), "、".join(htmls[:8])))


def chmod_tree(dest):
    """目录 755 / 文件 644 —— nginx(www-data) 可读，但不可写。"""
    try:
        os.chmod(dest, 0o755)
    except OSError:
        pass
    for root, dirs, files in os.walk(dest):
        for d in dirs:
            try:
                os.chmod(os.path.join(root, d), 0o755)
            except OSError:
                pass
        for f in files:
            try:
                os.chmod(os.path.join(root, f), 0o644)
            except OSError:
                pass


# ----------------------------------------------------------------- 发布

def site_dir(owner, name):
    return os.path.join(CFG["sites_dir"], owner, name)


def prune_backups(owner, name, keep):
    d = os.path.join(CFG["work_dir"], "backup", owner)
    if not os.path.isdir(d):
        return
    mine = [f for f in os.listdir(d) if f.startswith(name + ".")]
    mine.sort(reverse=True)          # 时间戳降序
    for old in mine[keep:]:
        shutil.rmtree(os.path.join(d, old), ignore_errors=True)


def publish(owner, name, zip_bytes, note, ip):
    """核心：暂存 -> 校验 -> 原子替换。返回结果 dict。"""
    staging = os.path.join(CFG["work_dir"], "staging", uuid.uuid4().hex)
    os.makedirs(staging, exist_ok=True)
    try:
        n_file, n_bytes = safe_extract(zip_bytes, staging)
        stripped = strip_single_root(staging)
        idx_note = require_index(staging)

        final = site_dir(owner, name)
        os.makedirs(os.path.dirname(final), exist_ok=True)

        backup = None
        if os.path.exists(final):
            ts = time.strftime("%Y%m%d_%H%M%S")
            bdir = os.path.join(CFG["work_dir"], "backup", owner)
            os.makedirs(bdir, exist_ok=True)
            backup = os.path.join(bdir, "%s.%s" % (name, ts))
            # 同一秒内重复发布，避免重名
            k = 1
            while os.path.exists(backup):
                backup = os.path.join(bdir, "%s.%s_%d" % (name, ts, k))
                k += 1
            shutil.move(final, backup)

        shutil.move(staging, final)
        chmod_tree(final)

        with DB_LOCK, db() as c:
            row = c.execute("SELECT version, created_at FROM sites WHERE owner=? AND name=?",
                            (owner, name)).fetchone()
            ver = (int(row["version"]) + 1) if row else 1
            created = row["created_at"] if row else time.time()
            # 注：本机 sqlite 为 3.7.17（CentOS 7 自带），不支持 UPSERT
            #     （ON CONFLICT ... DO UPDATE 需 sqlite >= 3.24，2018-06 起）。
            #     这里用「先 UPDATE，未命中再 INSERT」的等价写法，兼容老 sqlite。
            now = time.time()
            cur = c.execute(
                "UPDATE sites SET note=?, files=?, bytes=?, version=?,"
                " updated_at=?, updated_by=? WHERE owner=? AND name=?",
                (note, n_file, n_bytes, ver, now, owner, owner, name))
            if cur.rowcount == 0:
                c.execute(
                    "INSERT INTO sites(owner,name,note,files,bytes,version,created_at,updated_at,updated_by)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (owner, name, note, n_file, n_bytes, ver, created, now, owner))

        prune_backups(owner, name, int(CFG["keep_backups"]))
        log_action(owner, "publish", name,
                   "v%d  %d 个文件 %s%s%s" % (ver, n_file, human(n_bytes),
                                              "  剥掉了一层目录" if stripped else "",
                                              "  [%s]" % idx_note if "自动改名" in idx_note else ""),
                   ip)
        return {
            "ok": True, "site": name, "owner": owner, "version": ver,
            "files": n_file, "bytes": n_bytes,
            "url": CFG["url_prefix"] + quote(owner) + "/" + quote(name) + "/",
            "backup": os.path.basename(backup) if backup else None,
            "stripped_root": stripped,
            "note": note or "",
        }
    finally:
        # 无论成功失败都清干净暂存目录；成功时它已经被 move 走，这里只是兜底
        shutil.rmtree(staging, ignore_errors=True)


def delete_site(owner, name, ip):
    final = site_dir(owner, name)
    with DB_LOCK, db() as c:
        row = c.execute("SELECT * FROM sites WHERE owner=? AND name=?", (owner, name)).fetchone()
    if not row:
        raise HubError("你名下没有叫「%s」的站点" % name, 404)
    if os.path.exists(final):
        ts = time.strftime("%Y%m%d_%H%M%S")
        bdir = os.path.join(CFG["work_dir"], "backup", owner)
        os.makedirs(bdir, exist_ok=True)
        shutil.move(final, os.path.join(bdir, "%s.deleted.%s" % (name, ts)))
    with DB_LOCK, db() as c:
        c.execute("DELETE FROM sites WHERE owner=? AND name=?", (owner, name))
    log_action(owner, "delete", name, "v%s" % row["version"], ip)
    return {"ok": True, "site": name, "note": "已下线（文件仍保留在服务器备份目录，可找我恢复）"}


# ----------------------------------------------------------------- 列表页

PAGE = u"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<link rel="icon" href="data:,">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>在线工具 · 自助部署</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#f5f6f8;color:#1f2328;
  font:14px/1.55 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:28px 20px 60px}
h1{margin:0 0 4px;font-size:21px;letter-spacing:-.2px}
.sub{color:#6b7280;font-size:13px;margin-bottom:22px}
.me{display:inline-block;background:#eef2ff;color:#4338ca;border-radius:6px;
  padding:2px 9px;font-weight:600;font-size:12.5px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;
  padding:16px 18px;margin-bottom:12px}
.card h2{margin:0 0 12px;font-size:14px;color:#374151;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;color:#6b7280;font-weight:500;font-size:12px;
  padding:0 10px 8px 0;border-bottom:1px solid #eef0f3}
td{padding:9px 10px 9px 0;border-bottom:1px solid #f3f4f6;vertical-align:top}
tr:last-child td{border-bottom:0}
a{color:#2563eb;text-decoration:none;font-weight:600}
a:hover{text-decoration:underline}
code{background:#f3f4f6;padding:1.5px 6px;border-radius:4px;
  font:12.5px ui-monospace,Consolas,monospace}
.u{color:#9ca3af;font-size:12px;font-weight:400}
.own{background:#f0fdf4;color:#15803d;border-radius:5px;padding:1px 7px;
  font-size:11.5px;font-weight:600}
.muted{color:#9ca3af;font-size:12.5px}
.cmds{background:#1f2937;color:#e5e7eb;border-radius:9px;padding:14px 16px;
  font:12.5px/1.7 ui-monospace,Consolas,monospace;overflow-x:auto;white-space:pre}
.cmds .c{color:#9ca3af}
.cmds .k{color:#93c5fd}
.log td{font-size:12.5px;color:#6b7280;padding:5px 10px 5px 0;border:0}
.empty{color:#9ca3af;padding:14px 0;text-align:center;font-size:13px}
.pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11.5px;
  background:#f3f4f6;color:#6b7280}
</style></head><body><div class="wrap">
<h1>在线工具 · 自助部署</h1>
<div class="sub">把你的网页工具传到这台服务器上，拿到一个可分享的链接。
  当前身份 <span class="me">__ME__</span></div>
__BODY__
</div></body></html>
"""


def render_page(owner, is_admin):
    with db() as c:
        rows = c.execute("SELECT * FROM sites ORDER BY updated_at DESC").fetchall()
        logs = c.execute("SELECT * FROM logs ORDER BY ts DESC LIMIT 12").fetchall()

    mine = [r for r in rows if r["owner"] == owner]
    other = [r for r in rows if r["owner"] != owner]

    def tbl(rs, show_owner):
        if not rs:
            return u'<div class="empty">还没有任何工具</div>'
        h = [u"<table><tr><th>工具</th><th>链接</th><th>大小</th><th>版本</th><th>更新时间</th></tr>"]
        for r in rs:
            url = "%s%s/%s/" % (CFG["url_prefix"], quote(r["owner"]), quote(r["name"]))
            owner_tag = u' <span class="u">%s</span>' % r["owner"] if show_owner else u""
            note = u'<div class="u">%s</div>' % (r["note"] or "") if r["note"] else u""
            h.append(
                u'<tr><td><b>%s</b>%s%s</td>'
                u'<td><a href="%s" target="_blank">%s</a></td>'
                u'<td class="u">%s · %d 个文件</td>'
                u'<td><span class="pill">v%d</span></td>'
                u'<td class="u">%s</td></tr>'
                % (r["name"], owner_tag, note, url, url,
                   human(r["bytes"]), r["files"], r["version"],
                   time.strftime("%m-%d %H:%M", time.localtime(r["updated_at"]))))
        h.append("</table>")
        return "".join(h)

    body = []
    body.append(u'<div class="card"><h2>我的工具（%d）</h2>%s</div>'
                % (len(mine), tbl(mine, False)))
    if other:
        body.append(u'<div class="card"><h2>同事的工具（%d）</h2>%s</div>'
                    % (len(other), tbl(other, True)))

    cmds = (
        u'<div class="card"><h2>怎么上传</h2>'
        u'<div class="muted" style="margin-bottom:10px">'
        u'准备好工具目录（根目录下必须有 <code>index.html</code>），然后在电脑上执行：</div>'
        u'<div class="cmds"><span class="c"># 1) 下载上传工具（只需一次；这个地址免登录，直接下）</span>\n'
        u'curl -o deploy_client.py __HOST__/deploy/api/client.py\n\n'
        u'<span class="c"># 2) 上传整个目录</span>\n'
        u'python deploy_client.py --dir ./我的工具 --site fc-odds \\\n'
        u'    --user %ME% --password 你的密码 --note "FC 赔率看板"\n\n'
        u'<span class="c"># 3) 查看我的站点 / 删掉某个</span>\n'
        u'python deploy_client.py --list --user %ME% --password 你的密码\n'
        u'python deploy_client.py --delete --site fc-odds --user %ME% --password 你的密码</div>'
        u'<div class="muted" style="margin-top:10px">'
        u'站点名只能用英文小写字母、数字、下划线、短横线。'
        u'链接需要登录：2026-09-30 起全站改用统一登录页（Cookie 会话，不再弹系统密码框），'
        u'账号和以前一样；客户端会自己登录，你只要按上面写账号密码。</div></div>')
    body.append(cmds.replace("%ME%", owner))

    if logs:
        h = [u'<div class="card"><h2>最近操作</h2><table class="log">']
        for r in logs:
            act = {"publish": u"发布", "delete": u"下线"}.get(r["action"], r["action"])
            h.append(u'<tr><td>%s</td><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>'
                     % (time.strftime("%m-%d %H:%M", time.localtime(r["ts"])),
                        r["owner"], act, r["site"] or "-", r["detail"] or ""))
        h.append("</table></div>")
        body.append("".join(h))

    html = PAGE.replace("__ME__", owner).replace("__BODY__", "".join(body))
    # 用请求里的 Host 拼出可直接复制的下载地址
    return html


# ----------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "DeployHub/1.0"
    protocol_version = "HTTP/1.1"

    # -------- 基础输出 --------
    def _send(self, code, obj=None, raw=None, ctype="application/json; charset=utf-8",
              headers=None):
        if raw is None:
            body = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
        elif isinstance(raw, str):
            body = raw.encode("utf-8")
        else:
            body = raw
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def log_message(self, fmt, *a):
        if ARGS and ARGS.verbose:
            safe("[%s] %s" % (self.address_string(), fmt % a))

    # -------- 身份 --------
    def _user(self, required=True):
        """owner 来自 nginx 注入的 X-Remote-User。

        客户端自己发同名头是无效的 —— nginx 的 proxy_set_header 会覆盖。
        --no-auth 本地调试时改为自己解析 Basic Auth（等价于 nginx 的行为），
        这样本地测试走的是和线上同一条代码路径。
        """
        u = (self.headers.get("X-Remote-User") or "").strip()
        if not u and ARGS and ARGS.no_auth:
            auth = self.headers.get("Authorization") or ""
            if auth.lower().startswith("basic "):
                try:
                    import base64
                    dec = base64.b64decode(auth.split(None, 1)[1]).decode("utf-8", "replace")
                    u = dec.split(":", 1)[0].strip()
                except Exception:
                    u = ""
            if not u:
                u = (self.headers.get("X-Debug-User") or "debug").strip()
        if not u:
            raise HubError("没有拿到登录身份（nginx 未注入 X-Remote-User）", 401)
        if not re.match(CFG["site_re"], u.lower()):
            raise HubError("账号名 %r 含非法字符，请联系管理员" % u, 403)
        return u.lower()

    def _body(self):
        te = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in te:
            buf = []
            total = 0
            while True:
                line = self.rfile.readline().strip()
                if not line:
                    break
                try:
                    n = int(line.split(b";")[0], 16)
                except ValueError:
                    raise HubError("chunked 编码解析失败")
                if n == 0:
                    self.rfile.readline()
                    break
                total += n
                if total > CFG["max_upload"]:
                    raise HubError("上传内容超过上限 %s" % human(CFG["max_upload"]), 413)
                buf.append(self.rfile.read(n))
                self.rfile.readline()
            return b"".join(buf)

        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return b""
        if n > CFG["max_upload"]:
            raise HubError("上传内容超过上限 %s（当前 %.1f MB）"
                           % (human(CFG["max_upload"]), n / 1048576.0), 413)
        return self.rfile.read(n)

    def _json_body(self):
        raw = self._body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise HubError("请求体不是合法 JSON")

    def _q(self):
        return parse_qs(urlparse(self.path).query)

    # -------- 路由 --------
    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        q = self._q()
        try:
            if path in ("/api/health", "/health"):
                return self._send(200, {
                    "ok": True, "version": "1.0", "time": now_str(),
                    "sites_dir": CFG["sites_dir"],
                    "max_upload": CFG["max_upload"], "max_unzip": CFG["max_unzip"],
                    "max_files": CFG["max_files"],
                })

            if path == "/api/client.py":
                # 部署到服务器时两者同目录；开发时客户端脚本在 ../client/
                cands = [os.path.join(HERE, "deploy_client.py"),
                         os.path.join(os.path.dirname(HERE), "client", "deploy_client.py")]
                p = next((x for x in cands if os.path.isfile(x)), None)
                if not p:
                    return self._send(404, {"error": "服务器上没有 deploy_client.py"})
                with open(p, "rb") as f:
                    return self._send(200, raw=f.read(),
                                      ctype="text/x-python; charset=utf-8")

            owner = self._user()

            if path in ("", "/", "/api", "/api/sites"):
                with db() as c:
                    rows = c.execute("SELECT * FROM sites ORDER BY updated_at DESC").fetchall()
                out = []
                for r in rows:
                    out.append({
                        "owner": r["owner"], "site": r["name"], "note": r["note"],
                        "files": r["files"], "bytes": r["bytes"], "version": r["version"],
                        "updated_at": r["updated_at"],
                        "mine": r["owner"] == owner,
                        "url": CFG["url_prefix"] + quote(r["owner"]) + "/" + quote(r["name"]) + "/",
                    })
                if path in ("", "/", "/api"):
                    # 浏览器直接访问 -> 给列表页；带 ?format=json 走 JSON
                    if (q.get("format") or [""])[0] == "json":
                        return self._send(200, out)
                    host = self.headers.get("Host") or "127.0.0.1"
                    # 按访客实际用的协议拼下载地址（nginx 会注入 X-Forwarded-Proto）
                    scheme = (self.headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip()
                    if scheme not in ("http", "https"):
                        scheme = "http"
                    html = render_page(owner, False).replace(
                        "__HOST__", scheme + "://" + host)
                    return self._send(200, raw=html,
                                      ctype="text/html; charset=utf-8")
                return self._send(200, out)

            if path == "/api/log":
                limit = min(int((q.get("limit") or ["100"])[0]), 500)
                with db() as c:
                    rows = c.execute("SELECT * FROM logs ORDER BY ts DESC LIMIT ?",
                                     (limit,)).fetchall()
                return self._send(200, [{
                    "ts": r["ts"], "time": time.strftime("%Y-%m-%d %H:%M:%S",
                                                         time.localtime(r["ts"])),
                    "owner": r["owner"], "action": r["action"], "site": r["site"],
                    "detail": r["detail"], "ip": r["ip"],
                } for r in rows])

            # 站点包下载（备份回滚用）：暂不做
            return self._send(404, {"error": "未知接口：%s" % path})
        except HubError as e:
            return self._send(e.code, {"error": str(e)})
        except Exception as e:
            safe("[!] GET %s 异常：%r" % (path, e))
            return self._send(500, {"error": "服务器内部错误：%r" % e})

    def do_POST(self):
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        q = parse_qs(u.query)
        try:
            if path == "/api/deploy":
                owner = self._user()
                site = check_name((q.get("site") or [""])[0], "站点名")
                note = (q.get("note") or [""])[0].strip()[:200]
                data = self._body()
                if not data:
                    raise HubError("上传内容为空")
                t0 = time.time()
                if data[:2] != b"PK":
                    # 不是 zip：当单个 HTML 处理
                    head = data[:2048].decode("utf-8", "ignore").lower()
                    if "<html" not in head and "<!doctype" not in head:
                        raise HubError("上传内容既不是 zip 压缩包，也不像 HTML 文件。"
                                       "请传 .zip 或 .html")
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                        z.writestr("index.html", data)
                    data = buf.getvalue()
                    note = note or "（单个 HTML 文件）"
                res = publish(owner, site, data, note, self.client_address[0])
                res["elapsed"] = round(time.time() - t0, 2)
                safe("[+] %s 发布 %s/v%d  %d 文件 %s  %.2fs"
                     % (owner, site, res["version"], res["files"],
                        human(res["bytes"]), res["elapsed"]))
                return self._send(200, res)

            if path == "/api/delete":
                owner = self._user()
                body = self._json_body()
                site = check_name(body.get("site") or (q.get("site") or [""])[0], "站点名")
                return self._send(200, delete_site(owner, site, self.client_address[0]))

            return self._send(404, {"error": "未知接口：%s" % path})
        except HubError as e:
            return self._send(e.code, {"error": str(e)})
        except Exception as e:
            safe("[!] POST %s 异常：%r" % (path, e))
            return self._send(500, {"error": "服务器内部错误：%r" % e})


# ----------------------------------------------------------------- main

def main():
    global ARGS
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8898)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-auth", action="store_true",
                    help="本地调试：允许用 X-Debug-User 指定身份")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--sites-dir", help="覆盖站点根目录（本地测试用）")
    ap.add_argument("--work-dir", help="覆盖工作目录（本地测试用）")
    ARGS = ap.parse_args()

    init_console()
    load_cfg()
    if ARGS.sites_dir:
        CFG["sites_dir"] = ARGS.sites_dir
    if ARGS.work_dir:
        CFG["work_dir"] = ARGS.work_dir
    init_db()

    srv = ThreadingHTTPServer((ARGS.host, ARGS.port), Handler)
    srv.daemon_threads = True
    safe("=" * 62)
    safe(" 自助部署通道 · deploy-hub")
    safe(" 监听   : http://%s:%d" % (ARGS.host, ARGS.port))
    safe(" 站点   : %s" % CFG["sites_dir"])
    safe(" 工作区 : %s" % CFG["work_dir"])
    safe(" 上限   : 上传 %s / 解压 %s / %d 个文件"
         % (human(CFG["max_upload"]), human(CFG["max_unzip"]), CFG["max_files"]))
    safe("=" * 62)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        safe("bye")


if __name__ == "__main__":
    main()
