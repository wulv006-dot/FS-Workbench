# -*- coding: utf-8 -*-
"""
mlb_server.py —— MLB 新卡上架「在线工作台」服务端

部署在当前阿里云服务器，端口 8897，nginx 挂在 /mlb/ 下。

职责边界（重要）
---------------------------------------------------------
它【不】访问 showdd.io。旧服务器出口 IP（47.253.252.55，阿里云机房段）曾实测
会被 Cloudflare 判定为风险来源，返回 chl_page JS 挑战；而本机住宅出口 IP
直接 200 拿到真页面。这跟 P2PAH 后台「服务器 IP 不在白名单」是同一类约束。

所以架构照搬已验证过的「采集与托管分离」：

    同事浏览器 --HTTP--> [本服务 + nginx] <--轮询-- 本机执行器(mlb_agent.py)
                                                      |
                                                      +--> showdd.io（本机 IP 过关）

本服务只做六件事：
  1. 托管前端页面
  2. 存任务队列（SQLite）
  3. 给执行器发任务 / 收结果（含三次采样的中间进度）
  4. 存生成好的 Excel，供下载
  5. **采集完成后把卡片冻结下来，等人放行**（`/writeback/approve`），
     放行后起写卡子进程直写 p2pah 后台（`mlb_writeback.py`）
  6. **从订单后台带出当期金币售价**（`/api/coins-rate` → `mlb_coins_rate.py`）

⚠️ 5 和 6 是「做别的事」的旁路，共享同一条铁律：
   **任何旁路失败都不许影响主链路**（建任务 / 领任务 / 回传）。
   5 失败 → 任务照旧 done，只少一个上架状态；6 失败 → 输入框退回人工填写。

零第三方依赖（标准库 http.server + sqlite3）。
  需要第三方库的两件事（写卡、取价）一律走**子进程**，见那两个模块的说明。

启动：
    python3 mlb_server.py --port 8897 --root /var/www/mlb-online
"""
import os
import sys
import io
import json
import time
import uuid
import sqlite3
import argparse
import threading
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import mlb_writeback as WB       # noqa: E402  自动上架桥（同目录本地模块）
import mlb_coins_rate as CR      # noqa: E402  当期金币售价自动取价（同目录本地模块）

DB_LOCK = threading.Lock()
ARGS = None
CFG = {}
SERVER_VERSION = "1.2"

#: 自动上架的中间产物落点（交给直写脚本的结果 JSON / 它回吐的逐卡报告）。
#: 刻意**不**放 files/ —— 那里是「给人下载的交付物」，混在一起会让
#: 下载列表里冒出一堆内部文件。
WB_WORKDIR = os.path.join(HERE, "data", "writeback")

#: 取价的缓存与中间产物（同样不放 files/）。
RATE_DIR = os.path.join(HERE, "data", "pricing")

# 执行器 30 秒一次心跳；120 秒内没动静就算掉线（采样一轮要等 120 秒，留足余量）
AGENT_ONLINE_SEC = 150
MAX_UPLOAD = 40 * 1024 * 1024          # 生成的 xlsx 一般几百 KB，40MB 足够


def load_cfg(path):
    global CFG
    for p in ([path] if path else []) + [os.path.join(HERE, "server_config.json")]:
        if p and os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    CFG = json.load(f)
                return p
            except Exception as e:
                print("[!] 读配置失败 %s: %s" % (p, e))
    return None


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id          TEXT PRIMARY KEY,
  created_at  REAL,
  submitter   TEXT,
  kind        TEXT,
  title       TEXT,
  payload     TEXT,
  status      TEXT,
  agent       TEXT,
  claimed_at  REAL,
  finished_at REAL,
  progress    TEXT,
  result      TEXT,
  error       TEXT
);
CREATE TABLE IF NOT EXISTS agents (
  name        TEXT PRIMARY KEY,
  ip          TEXT,
  version     TEXT,
  note        TEXT,
  host        TEXT,
  first_seen  REAL,
  last_seen   REAL,
  tasks_done  INTEGER DEFAULT 0,
  tasks_fail  INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS kv (
  k           TEXT PRIMARY KEY,
  v           TEXT,
  updated_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, created_at);
"""


def db():
    conn = sqlite3.connect(os.path.join(HERE, "data", "mlb.db"), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "files"), exist_ok=True)
    os.makedirs(WB_WORKDIR, exist_ok=True)
    os.makedirs(RATE_DIR, exist_ok=True)
    with db() as c:
        c.executescript(SCHEMA)


def writeback_read(tid):
    """读 `tasks.result.write_back`（上架状态的**权威来源**）。

    ★ 放行判断只能基于这里的服务端状态，绝不能信前端传参 ——
      否则"点了没点"就变成一个可以伪造的开关。
    """
    with db() as c:
        r = c.execute("SELECT result FROM tasks WHERE id=?", (tid,)).fetchone()
    if not r or not r["result"]:
        return {}
    try:
        cur = json.loads(r["result"])
    except Exception:
        return {}
    if not isinstance(cur, dict):
        return {}
    wb = cur.get("write_back")
    return wb if isinstance(wb, dict) else {}


def writeback_update(tid, patch):
    """把自动上架的结果合并进 `tasks.result.write_back`。

    刻意**不加新列**：线上 SQLite 是 3.7.17，`ALTER TABLE ADD COLUMN` 虽支持，
    但一旦要回滚就得再删列（3.35+ 才有 DROP COLUMN），迁移风险不值得。
    `result` 本来就是 JSON 文本，塞一个子键是最省事、可回退的做法。
    """
    with db() as c:
        r = c.execute("SELECT result FROM tasks WHERE id=?", (tid,)).fetchone()
        cur = {}
        if r and r["result"]:
            try:
                cur = json.loads(r["result"])
            except Exception:
                cur = {}
        if not isinstance(cur, dict):
            cur = {}
        cur["write_back"] = patch
        c.execute("UPDATE tasks SET result=? WHERE id=?",
                  (json.dumps(cur, ensure_ascii=False), tid))


def mark_interrupted_writebacks():
    """启动时清扫两类"看起来还在动、其实已经停了"的状态。

    1. `running`：线程随进程没了，但库里还写着"上架中" —— 典型的静默假象。
    2. `awaiting_review`：**待审是持久态，重启后必须保留**（人还没点）。
       但如果那份待审快照文件没了，就永远放行不了 —— 标成 `review_lost`
       明说，别让人一直等一个永远不会来的按钮。
    """
    n = 0
    with db() as c:
        rows = c.execute("SELECT id, result FROM tasks WHERE result LIKE '%\"write_back\"%'"
                         ).fetchall()
        for r in rows:
            try:
                cur = json.loads(r["result"])
            except Exception:
                continue
            wb = cur.get("write_back") or {}
            st = wb.get("status")

            if st == "running":
                wb["status"] = "interrupted"
                wb["error"] = (wb.get("error") or "") + \
                    "（hub 重启：上架线程已随进程结束，未留下最终结论）"
            elif st == WB.AWAITING:
                if not os.path.isfile(WB.pending_path(WB_WORKDIR, r["id"])):
                    wb["status"] = "review_lost"
                    wb["error"] = ("待审快照文件缺失，无法放行 —— "
                                   "请重跑一次采集任务再核对")
                else:
                    continue          # 待审态原样保留，不动
            else:
                continue

            cur["write_back"] = wb
            c.execute("UPDATE tasks SET result=? WHERE id=?",
                      (json.dumps(cur, ensure_ascii=False), r["id"]))
            n += 1
    if n:
        print("[!] 有 %d 条上架记录状态已失效（running/review_lost），已标注" % n)
    return n


def task_brief(r, full=False):
    d = {
        "id": r["id"],
        "created_at": r["created_at"],
        "created_at_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["created_at"] or 0)),
        "submitter": r["submitter"],
        "kind": r["kind"],
        "title": r["title"],
        "status": r["status"],
        "agent": r["agent"],
        "claimed_at": r["claimed_at"],
        "finished_at": r["finished_at"],
        "finished_at_str": (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["finished_at"]))
                            if r["finished_at"] else None),
        "error": r["error"],
    }
    for k in ("payload", "progress", "result"):
        if full:
            try:
                d[k] = json.loads(r[k]) if r[k] else None
            except Exception:
                d[k] = None
    # 列表页也要能看出进度，不然同事不知道跑到哪一步了
    try:
        d["progress"] = json.loads(r["progress"]) if r["progress"] else None
    except Exception:
        d["progress"] = None
    return d


class Handler(BaseHTTPRequestHandler):
    server_version = "MLBDeploy/" + SERVER_VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # ---------------- 工具 ----------------
    def _send(self, code, obj, extra_headers=None):
        if isinstance(obj, (dict, list)):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        elif isinstance(obj, bytes):
            body = obj
            ctype = "application/octet-stream"
        else:
            body = str(obj).encode("utf-8")
            ctype = "text/plain; charset=utf-8"
        # extra_headers 允许覆盖默认头（否则会出现重复的 Content-Type，
        # 浏览器取第一个 -> 调用方指定的 MIME 被无声忽略）
        extra = dict(extra_headers or {})
        ctype = extra.pop("Content-Type", ctype)
        if "Content-Length" in extra:
            extra.pop("Content-Length")   # 长度由这里统一算，防止不一致
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        if n > MAX_UPLOAD:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _user(self):
        u = self.headers.get("X-Remote-User") or self.headers.get("X-Auth-User") or ""
        if not u and ARGS.no_auth:
            u = "local"
        return u.strip() or "unknown"

    # ---------------- GET ----------------
    def do_GET(self):
        from urllib.parse import unquote
        p = urlparse(self.path)
        q = parse_qs(p.query)
        # path 里可能带 %XX（任务产物文件名含中文/空格时会被编码），先解码再匹配
        path = unquote(p.path)

        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path in ("/favicon.ico", "/apple-touch-icon.png"):
            return self._send(204, b"")

        if path == "/api/health":
            wb = WB.cfg(CFG)
            return self._send(200, {
                "ok": True, "t": time.strftime("%Y-%m-%d %H:%M:%S"),
                "version": SERVER_VERSION,
                # 只回布尔量，不回路径 —— 页面不需要知道服务器上凭据放在哪
                "writeback": {
                    "enabled": wb["enabled"],
                    "dry_run": wb["dry_run"],
                    # 有这道闸门时，采集跑完会**停下来等人放行**
                    "require_approval": wb["require_approval"],
                    "script_ok": bool(wb["script"] and os.path.isfile(wb["script"])),
                    "cred_ok": bool(wb["cred"] and os.path.isfile(wb["cred"])),
                },
                "coins_rate": CR.status(CR.cfg(CFG)),
            })

        # 当期金币售价：从订单后台自动带出（只读，失败则页面退回人工填写）
        if path == "/api/coins-rate":
            c = CR.cfg(CFG)
            c["cache_dir"] = c.get("cache_dir") or RATE_DIR
            force = (q.get("force") or ["0"])[0] not in ("0", "", "false", "no")
            data = CR.get(c, force=force,
                          out_dir=RATE_DIR,
                          log=lambda m: sys.stderr.write("%s\n" % m))
            return self._send(200, data)

        if path == "/api/tasks":
            limit = min(int((q.get("limit") or ["60"])[0]), 300)
            with db() as c:
                rows = c.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                                 (limit,)).fetchall()
            return self._send(200, [task_brief(r) for r in rows])

        if path == "/api/agents":
            now = time.time()
            with db() as c:
                rows = c.execute("SELECT * FROM agents ORDER BY last_seen DESC").fetchall()
            out = []
            for r in rows:
                d = dict(r)
                age = now - (r["last_seen"] or 0)
                d["idle"] = round(age, 1)
                d["online"] = age < AGENT_ONLINE_SEC
                d["last_seen_str"] = time.strftime("%Y-%m-%d %H:%M:%S",
                                                   time.localtime(r["last_seen"] or 0))
                out.append(d)
            return self._send(200, out)

        if path == "/api/stats":
            with db() as c:
                r = c.execute("SELECT status, COUNT(*) n FROM tasks GROUP BY status").fetchall()
                a = c.execute("SELECT COUNT(*) n, SUM(tasks_done) d FROM agents").fetchone()
            return self._send(200, {"tasks": {x["status"]: x["n"] for x in r},
                                    "agents": (a["n"] if a else 0),
                                    "done_total": (a["d"] if a and a["d"] else 0)})

        # 执行器拉取业务参数（当期金币售价等），由网页提交任务时带上
        if path == "/api/agent-config":
            return self._send(200, {
                "markup": CFG.get("markup", "1.1"),
                "floor": CFG.get("floor", "0.50"),
                "interval": CFG.get("interval", 120),
                "updates_url": CFG.get("updates_url", "https://www.showdd.io/26/updates"),
            })

        if path.startswith("/api/tasks/"):
            tid = path.rsplit("/", 1)[-1]
            with db() as c:
                r = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
            if not r:
                return self._send(404, {"error": "not found"})
            return self._send(200, task_brief(r, full=True))

        # 文件下载：任务产物（Excel）+ 静态分发物（执行器压缩包等）
        if path.startswith("/files/"):
            rel = path[len("/files/"):]
            fn = os.path.basename(rel)
            if ".." in rel or not fn:
                return self._send(404, {"error": "not found"})
            # 查找顺序：静态根下的 files/（随包分发的执行器等）
            #          -> 应用目录的 files/（任务产物）
            #          -> 应用目录的 web/files/（本地开发的兜底）
            cands = [
                os.path.join(ARGS.root, "files", fn),
                os.path.join(HERE, "files", fn),
                os.path.join(HERE, "web", "files", fn),
            ]
            fp = next((c for c in cands if os.path.isfile(c)), None)
            if not fp:
                return self._send(404, {"error": "not found"})
            with open(fp, "rb") as f:
                data = f.read()
            ext = os.path.splitext(fn)[1].lower()
            ctype = {
                ".xlsx": "application/vnd.openxmlformats-officedocument"
                         ".spreadsheetml.sheet",
                ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
                ".xls": "application/vnd.ms-excel",
                ".zip": "application/zip",
                ".md": "text/markdown; charset=utf-8",
                ".txt": "text/plain; charset=utf-8",
                ".csv": "text/csv; charset=utf-8",
            }.get(ext, "application/octet-stream")
            from urllib.parse import quote
            disp = "attachment; filename*=UTF-8''%s" % quote(fn)
            return self._send(200, data, {
                "Content-Type": ctype,
                "Content-Disposition": disp,
                "Content-Length": str(len(data)),
            })

        if path.startswith("/assets/"):
            return self._static(path.lstrip("/"))

        return self._send(404, {"error": "not found"})

    # ---------------- POST ----------------
    def do_POST(self):
        p = urlparse(self.path)
        path = p.path
        body = self._json_body()

        # 网页提交采集任务
        if path == "/api/tasks":
            kind = body.get("kind") or "collect"
            rate = body.get("rate")
            payload = {
                "kind": kind,
                "rate": rate,
                "batch": body.get("batch") or "",
                "show_browser": bool(body.get("show_browser")),
                "interval": int(body.get("interval") or CFG.get("interval", 120)),
                "template": body.get("template") or "",
                # 采集跑完是否自动写 p2pah 后台（第三道闸门在服务配置里）
                "write_back": bool(body.get("write_back")),
            }
            # 模板随任务下发：网页上传的 Excel 以 base64 带给执行器，
            # 否则执行器只能靠本地 --template / 工作目录里找。
            # 不落库到 payload 之外，领取时一并返回，完成任务后随之归档。
            if body.get("template_b64"):
                payload["template_b64"] = body["template_b64"]
                payload["template_name"] = body.get("template_name") or "mould-create.xlsx"
            if kind == "collect" and not rate:
                return self._send(400, {"error": "请填写当期金币售价（USD / 100K Stub）"})
            tid = uuid.uuid4().hex[:12]
            with db() as c:
                c.execute("INSERT INTO tasks(id,created_at,submitter,kind,title,payload,status)"
                          " VALUES(?,?,?,?,?,?,?)",
                          (tid, time.time(), self._user(), kind,
                           body.get("title") or ("采集 %s" % (payload["batch"] or "最新批次")),
                           json.dumps(payload, ensure_ascii=False), "pending"))
            return self._send(200, {"id": tid, "status": "pending"})

        # 执行器心跳
        if path == "/api/heartbeat":
            name = (body.get("agent") or "").strip()
            if not name:
                return self._send(400, {"error": "agent 为空"})
            ip = (self.headers.get("X-Real-IP") or self.headers.get("X-Forwarded-For")
                  or self.client_address[0] or "")
            ip = ip.split(",")[0].strip()
            now = time.time()
            # 注意：不要用 "INSERT ... ON CONFLICT(name) DO UPDATE"（SQLite UPSERT）。
            # 那需要 SQLite >= 3.24.0（2018），而 CentOS 7 自带的是 3.7.17，
            # 会直接抛 sqlite3.OperationalError: near "ON": syntax error，
            # 表现为心跳接口 500 / "Empty reply from server"，执行器永远显示离线。
            # 这里用最兼容的 SELECT + UPDATE/INSERT 两步写法。
            ver = str(body.get("version") or "")
            note = str(body.get("note") or "")[:200]
            host = str(body.get("host") or "")[:80]
            with db() as c:
                exists = c.execute("SELECT 1 FROM agents WHERE name=?", (name,)).fetchone()
                if exists:
                    c.execute("UPDATE agents SET ip=?, version=?, note=?, host=?, last_seen=?"
                              " WHERE name=?", (ip, ver, note, host, now, name))
                else:
                    c.execute("INSERT INTO agents(name,ip,version,note,host,first_seen,last_seen)"
                              " VALUES(?,?,?,?,?,?,?)",
                              (name, ip, ver, note, host, now, now))
                r = c.execute("SELECT * FROM agents WHERE name=?", (name,)).fetchone()
            return self._send(200, {"ok": True, "ip": ip, "agent": dict(r) if r else None})

        # 执行器领任务（原子）
        if path == "/api/claim":
            agent = (body.get("agent") or "").strip() or "unknown"
            with DB_LOCK, db() as c:
                r = c.execute("SELECT * FROM tasks WHERE status='pending'"
                              " ORDER BY created_at LIMIT 1").fetchone()
                if not r:
                    return self._send(200, {"task": None})
                c.execute("UPDATE tasks SET status='running', agent=?, claimed_at=?"
                          " WHERE id=? AND status='pending'", (agent, time.time(), r["id"]))
                if c.total_changes == 0:
                    return self._send(200, {"task": None})
                r = c.execute("SELECT * FROM tasks WHERE id=?", (r["id"],)).fetchone()
            return self._send(200, {"task": task_brief(r, full=True)})

        # 执行器回传进度（三轮采样的每一步）
        if path.startswith("/api/tasks/") and path.endswith("/progress"):
            tid = path.split("/")[3]
            with db() as c:
                c.execute("UPDATE tasks SET progress=? WHERE id=?",
                          (json.dumps(body.get("progress"), ensure_ascii=False), tid))
            return self._send(200, {"ok": True})

        # 执行器回传结果（含 Excel 文件内容，base64）
        if path.startswith("/api/tasks/") and path.endswith("/result"):
            tid = path.split("/")[3]
            st = body.get("status") or "done"
            if st not in ("done", "failed"):
                st = "done"
            agent = (body.get("agent") or "").strip()
            result = body.get("result") or {}
            file_name = None

            # 落盘生成的 Excel
            b64 = result.pop("file_b64", None)
            if b64 and st == "done":
                try:
                    import base64
                    raw = base64.b64decode(b64)
                    file_name = result.get("file_name") or ("mlb_new_cards_%s.xlsx"
                                                            % time.strftime("%Y%m%d_%H%M%S"))
                    file_name = os.path.basename(file_name)
                    with open(os.path.join(HERE, "files", file_name), "wb") as f:
                        f.write(raw)
                    result["file_name"] = file_name
                    result["file_size"] = len(raw)
                    # file_url 会被直接塞进 <a href>，含中文/空格必须先编码，
                    # 否则浏览器和 urllib 都会在请求行上抛 ascii 编码错误。
                    from urllib.parse import quote
                    result["file_url"] = "/files/%s" % quote(file_name)
                except Exception as e:
                    result["file_error"] = "文件落盘失败：%s" % e

            with db() as c:
                c.execute("UPDATE tasks SET status=?, finished_at=?, result=?, error=?"
                          " WHERE id=?",
                          (st, time.time(),
                           json.dumps(result, ensure_ascii=False),
                           body.get("error"), tid))
                if agent:
                    col = "tasks_done" if st == "done" else "tasks_fail"
                    c.execute("UPDATE agents SET %s=%s+1, last_seen=? WHERE name=?"
                              % (col, col), (time.time(), agent))

            # ---- 采集完成后自动上架（Fire & Forget，不拖住执行器的回传）----
            wb_state = None
            if st == "done":
                with db() as c:
                    r = c.execute("SELECT payload FROM tasks WHERE id=?", (tid,)).fetchone()
                try:
                    tpayload = json.loads(r["payload"]) if r and r["payload"] else {}
                except Exception:
                    tpayload = {}
                try:
                    wb_state = WB.start(
                        tid=tid, payload=tpayload,
                        cards=result.get("cards") or [],
                        config=CFG, update=writeback_update,
                        read=writeback_read,
                        workdir=WB_WORKDIR,
                        log=lambda m: sys.stderr.write("%s\n" % m))
                except Exception as e:       # noqa: BLE001 —— 上架起不来也不能影响回传
                    print("[!] 自动上架启动失败：%r" % e)
                    wb_state = {"status": "failed", "reason": "%r" % e}

            return self._send(200, {"ok": True, "file": file_name,
                                    "writeback": wb_state})

        # ---- 人工放行：**只有这一步之后才会真的写后台** ----
        if path.startswith("/api/tasks/") and path.endswith("/writeback/approve"):
            tid = path.split("/")[3]
            names = body.get("names")
            if names is not None and not isinstance(names, list):
                return self._send(400, {"error": "names 必须是数组（product_name 列表）"})
            try:
                out = WB.approve(tid=tid, names=names, config=CFG,
                                 update=writeback_update, read=writeback_read,
                                 workdir=WB_WORKDIR, by=self._user(),
                                 log=lambda m: sys.stderr.write("%s\n" % m))
            except Exception as e:           # noqa: BLE001
                print("[!] 放行失败：%r" % e)
                return self._send(500, {"error": "%r" % e})
            return self._send(200, out)

        # ---- 人工取消本次上架 ----
        if path.startswith("/api/tasks/") and path.endswith("/writeback/cancel"):
            tid = path.split("/")[3]
            try:
                out = WB.cancel(tid=tid, read=writeback_read,
                                update=writeback_update, workdir=WB_WORKDIR,
                                by=self._user(), reason=str(body.get("reason") or ""),
                                log=lambda m: sys.stderr.write("%s\n" % m))
            except Exception as e:           # noqa: BLE001
                print("[!] 取消失败：%r" % e)
                return self._send(500, {"error": "%r" % e})
            return self._send(200, out)

        if path == "/api/tasks/requeue":
            tid = body.get("id")
            with db() as c:
                c.execute("UPDATE tasks SET status='pending', agent=NULL, claimed_at=NULL,"
                          " progress=NULL, error=NULL WHERE id=?", (tid,))
            return self._send(200, {"ok": True})

        if path == "/api/tasks/delete":
            tid = body.get("id")
            with db() as c:
                c.execute("DELETE FROM tasks WHERE id=?", (tid,))
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})

    def do_HEAD(self):
        return self.do_GET()

    # ---------------- 静态 ----------------
    def _static(self, rel):
        fp = os.path.normpath(os.path.join(ARGS.root, rel))
        if not fp.startswith(os.path.abspath(ARGS.root)):
            return self._send(403, {"error": "forbidden"})
        if not os.path.isfile(fp):
            return self._send(404, {"error": "not found"})
        ctype, _ = mimetypes.guess_type(fp)
        if fp.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif fp.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif fp.endswith(".html"):
            ctype = "text/html; charset=utf-8"
        with open(fp, "rb") as f:
            data = f.read()
        return self._send(200, data, {"Content-Type": ctype or "application/octet-stream"})


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8897)
    ap.add_argument("--root", default="/var/www/mlb-online")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--config", default="")
    ap.add_argument("--no-auth", action="store_true",
                    help="本地调试用，不做 X-Remote-User 校验")
    ARGS = ap.parse_args()
    load_cfg(ARGS.config)
    init_db()
    mark_interrupted_writebacks()
    srv = ThreadingHTTPServer((ARGS.host, ARGS.port), Handler)
    print("[+] MLB 在线工作台 已启动：http://%s:%d/  root=%s" % (ARGS.host, ARGS.port, ARGS.root))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] 已停止")


if __name__ == "__main__":
    main()
