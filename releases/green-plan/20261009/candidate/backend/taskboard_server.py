#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MMOEXP 站内项目工作任务台 · 后端服务
=====================================

零第三方依赖（只用 Python 3 标准库），与 /opt/fc27-gate、/opt/auth-portal 同款做法。

架构位置
--------
    nginx(443)
      |-- auth_request /__auth_verify  --> auth-portal 127.0.0.1:8895/verify
      |-- location /dashboard/tasks/       -> alias /var/www/dashboard/tasks/     (静态前端)
      |-- location /dashboard/tasks/api/   -> proxy_pass http://127.0.0.1:8932/   (本服务)
                                                proxy_set_header X-Auth-User $auth_user

本服务只监听 127.0.0.1，公网不可达。身份唯一来源是 nginx 注入的 X-Auth-User —— 该头由 nginx
用 auth_request_set 覆盖写入，客户端自带同名字头会被 nginx 覆盖，因此无法伪造。

三层权限
--------
L1 网络门：nginx auth_request（dashboard 组）。未登录 401、不在组 403，根本到不了本服务。
L2 应用角色：admin / editor / viewer，由本服务判定。
L3 字段级：editor 只能修改「自己名下任务」的进展、状态与自检项；其余字段一律 admin。

安全承诺
--------
* 不落任何凭据；不写死密码；不读 htpasswd。
* 未登记账号默认 viewer（最小权限），新注册账号不会自动获得写权限。
* GUARD_ADMINS 三人永远 admin，且任何接口都无法把他们降级 —— 防止 members 表被写坏后无人能修。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
import time
import traceback
import urllib.parse
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.0.0"
HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- 配置

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


CFG = {
    "bind": _env("TASKBOARD_BIND") or "127.0.0.1",
    "port": int(_env("TASKBOARD_PORT") or 8932),
    "data_dir": Path(_env("TASKBOARD_DATA") or (HERE / "data")),
    "seed": Path(_env("TASKBOARD_SEED") or (HERE / "seed.json")),
    "max_body": 1 << 20,          # 请求体上限 1 MiB
    "max_events": 400,            # 每个任务最多保留的审计事件条数
    # 未在任务台登记过的账号如何处置：
    #   deny（默认）—— 拒绝访问。因为统一门户的 /verify 在门户会话失效时会回退到 FC27
    #                  只读门禁，把 FC27 的外部自注册用户也算作 dashboard 组成员返回，
    #                  若这里放行，外部用户将能读到内部任务、接手人与人员安排。
    #   readonly     —— 降级为只读放行（仅当确认不存在外部自注册用户时才可改）。
    "unregistered": (_env("TASKBOARD_UNREGISTERED") or "deny").lower(),
}
CFG["db"] = CFG["data_dir"] / "taskboard.db"

# 守护管理员：与 fs_permissions_unification_20260930/access_policy.py 的 ADMINS 完全一致。
GUARD_ADMINS = frozenset(("wulv", "chenchao", "DY"))

ROLES = ("admin", "editor", "viewer")
STATUSES = ("todo", "doing", "blocked", "review", "done")
HORIZONS = ("short", "long")

# 各角色可经由 PATCH /api/tasks/<id> 写入的任务字段
ADMIN_FIELDS = frozenset(("project", "dept", "horizon", "title", "assignee", "due",
                          "status", "progress", "checks"))
EDITOR_FIELDS = frozenset(("status", "progress"))

MAX_TITLE = 200
MAX_CHECK = 200
MAX_CHECKS = 40
MAX_ASSIGNEE = 40
MAX_NOTE = 400

WRITE_LOCK = threading.Lock()
LOG_LOCK = threading.Lock()


def log(msg: str, kind: str = "info") -> None:
    line = "%s [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), kind, msg)
    with LOG_LOCK:
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except Exception:
            pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- 异常

class ApiError(Exception):
    def __init__(self, status: int, message: str, detail=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


# --------------------------------------------------------------------------- 数据库

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT UNIQUE NOT NULL,
    grp     TEXT NOT NULL,
    sort    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS depts (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT UNIQUE NOT NULL,
    sort    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS members (
    username     TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    role         TEXT NOT NULL DEFAULT 'viewer',
    dept         TEXT NOT NULL DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1,
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT NOT NULL,
    dept        TEXT NOT NULL,
    horizon     TEXT NOT NULL,
    title       TEXT NOT NULL,
    assignee    TEXT NOT NULL DEFAULT '',
    ack         INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'todo',
    progress    INTEGER NOT NULL DEFAULT 0,
    due         TEXT NOT NULL DEFAULT '',
    sort        INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_by  TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checks (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id  INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    idx      INTEGER NOT NULL,
    text     TEXT NOT NULL,
    done     INTEGER NOT NULL DEFAULT 0,
    done_by  TEXT NOT NULL DEFAULT '',
    done_at  TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS task_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    task_id   INTEGER,
    actor     TEXT NOT NULL DEFAULT '',
    action    TEXT NOT NULL,
    field     TEXT NOT NULL DEFAULT '',
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    note      TEXT NOT NULL DEFAULT '',
    ip        TEXT NOT NULL DEFAULT '',
    ua        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tasks_project  ON tasks(project);
CREATE INDEX IF NOT EXISTS idx_tasks_dept     ON tasks(dept);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee);
CREATE INDEX IF NOT EXISTS idx_checks_task    ON checks(task_id, idx);
CREATE INDEX IF NOT EXISTS idx_events_task    ON task_events(task_id, id DESC);
"""


def db_connect() -> sqlite3.Connection:
    CFG["data_dir"].mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CFG["db"]), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def q(conn: sqlite3.Connection, sql: str, args=(), one: bool = False):
    cur = conn.execute(sql, args)
    if one:
        return cur.fetchone()
    return cur.fetchall()


def init_db(verbose: bool = True) -> dict:
    with WRITE_LOCK:
        conn = db_connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.commit()
            info = {"created_projects": 0, "created_depts": 0, "created_members": 0,
                    "created_tasks": 0, "skipped": False}

            seed = json.loads(CFG["seed"].read_text(encoding="utf-8")) if CFG["seed"].is_file() else None
            ts = now_iso()

            if seed:
                for i, g in enumerate(seed["groups"]):
                    for j, p in enumerate(g["projects"]):
                        cur = conn.execute(
                            "INSERT OR IGNORE INTO projects(name,grp,sort) VALUES(?,?,?)",
                            (p, g["name"], i * 100 + j))
                        info["created_projects"] += cur.rowcount
                for i, d in enumerate(seed["depts"]):
                    cur = conn.execute("INSERT OR IGNORE INTO depts(name,sort) VALUES(?,?)", (d, i * 10))
                    info["created_depts"] += cur.rowcount
                # 成员：只补建缺失记录，绝不覆盖管理员后来调整过的角色 / 停用状态
                for m in seed.get("members", []):
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO members(username,display_name,role,dept,active,note,
                                                        created_at,updated_at)
                           VALUES(?,?,?,?,1,?,?,?)""",
                        (m["username"], m.get("displayName", ""), m.get("role", "viewer"),
                         m.get("dept", ""), m.get("note", ""), ts, ts))
                    info["created_members"] += cur.rowcount

            existing = q(conn, "SELECT COUNT(*) AS n FROM tasks", one=True)["n"]
            if existing:
                info["skipped"] = True
            elif seed:
                for i, t in enumerate(seed["tasks"]):
                    cur = conn.execute(
                        """INSERT INTO tasks(project,dept,horizon,title,assignee,ack,status,progress,due,sort,
                                             created_by,created_at,updated_by,updated_at)
                           VALUES(?,?,?,?,'',0,'todo',0,?,?,'seed',?,'',?)""",
                        (t["project"], t["dept"], t["horizon"], t["title"], t["due"], i * 10, ts, ts))
                    tid = cur.lastrowid
                    for k, text in enumerate(t["checks"]):
                        conn.execute("INSERT INTO checks(task_id,idx,text) VALUES(?,?,?)", (tid, k, text))
                    conn.execute(
                        """INSERT INTO task_events(ts,task_id,actor,action,field,new_value,note)
                           VALUES(?,?,'seed','create','','','初始任务骨架导入')""", (ts, tid))
                    info["created_tasks"] += 1
                conn.commit()
            conn.commit()
            import green_plan
            green_plan.init(conn)
            return info
        finally:
            conn.close()


# --------------------------------------------------------------------------- 校验

DUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{2,40}$")


def v_text(value, name: str, maxlen: int, allow_empty: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(400, f"{name} 必须是文本")
    value = value.strip()
    if not value and not allow_empty:
        raise ApiError(400, f"{name} 不能为空")
    if len(value) > maxlen:
        raise ApiError(400, f"{name} 超过 {maxlen} 字符")
    return value


def v_enum(value, name: str, allowed) -> str:
    if value not in allowed:
        raise ApiError(400, f"{name} 取值非法，允许：{'/'.join(allowed)}")
    return value


def v_due(value) -> str:
    value = v_text(value, "截止日期", 10)
    if not DUE_RE.match(value):
        raise ApiError(400, "截止日期必须是 YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ApiError(400, "截止日期不是有效日期")
    return value


def v_progress(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(400, "进度必须是 0-100 的整数")
    n = int(value)
    if n < 0 or n > 100:
        raise ApiError(400, "进度必须在 0-100 之间")
    return n


def v_checks(value, conn) -> list:
    if not isinstance(value, list):
        raise ApiError(400, "自检清单必须是数组")
    if len(value) > MAX_CHECKS:
        raise ApiError(400, f"自检清单最多 {MAX_CHECKS} 条")
    out = []
    for item in value:
        if isinstance(item, str):
            out.append({"text": v_text(item, "自检项", MAX_CHECK), "done": False})
        elif isinstance(item, dict):
            out.append({"text": v_text(item.get("text"), "自检项", MAX_CHECK),
                        "done": bool(item.get("done"))})
        else:
            raise ApiError(400, "自检项必须是文本或对象")
    return out


def v_project_dept(conn, project: str, dept: str) -> None:
    if not q(conn, "SELECT 1 FROM projects WHERE name=?", (project,), one=True):
        raise ApiError(400, f"未知项目：{project}")
    if not q(conn, "SELECT 1 FROM depts WHERE name=?", (dept,), one=True):
        raise ApiError(400, f"未知部门：{dept}")


def v_assignee(conn, name: str) -> str:
    name = v_text(name, "接手人", MAX_ASSIGNEE, allow_empty=True)
    if name and q(conn, "SELECT 1 FROM members WHERE username=? AND active=1", (name,), one=True) is None:
        # 允许指派给尚未登记的内部账号，但要在事件里留痕（下面 record 会写 actor）
        log("指派给未在成员表登记的账号: %s" % name, "warn")
    return name


# --------------------------------------------------------------------------- 权限

class Ctx:
    __slots__ = ("user", "role", "ip", "ua", "registered")

    def __init__(self, user: str, role: str, ip: str = "", ua: str = "", registered: bool = True):
        self.user = user
        self.role = role
        self.ip = ip
        self.ua = ua
        self.registered = registered

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def to_json(self) -> dict:
        return {"user": self.user, "role": self.role, "isAdmin": self.is_admin,
                "registered": self.registered,
                "canEditAll": self.is_admin, "canEditOwn": self.is_admin or self.role == "editor"}


def member_state(conn, username: str):
    """返回 (role, registered)。

    守护管理员恒定 admin 且视为已登记；未在 members 表出现的账号一律 (viewer, False)，
    由路由层按 CFG['unregistered'] 决定拒绝还是只读放行。
    """
    if not username:
        return "anonymous", False
    if username in GUARD_ADMINS:
        return "admin", True
    row = q(conn, "SELECT role,active FROM members WHERE username=?", (username,), one=True)
    if not row:
        return "viewer", False
    if not row["active"]:
        return "viewer", True          # 已登记但被停用：降级只读，不再具备写权限
    return (row["role"] if row["role"] in ROLES else "viewer"), True


def role_of(conn, username: str) -> str:
    return member_state(conn, username)[0]


def require_admin(ctx: Ctx) -> None:
    if not ctx.is_admin:
        raise ApiError(403, "需要管理员权限")


def can_edit_task(ctx: Ctx, task) -> bool:
    if ctx.is_admin:
        return True
    if ctx.role == "editor" and task["assignee"] and task["assignee"] == ctx.user:
        return True
    return False


def require_task_edit(ctx: Ctx, task) -> None:
    if not can_edit_task(ctx, task):
        raise ApiError(403, "只能修改自己名下的任务")


# --------------------------------------------------------------------------- 审计

def record(conn, ctx: Ctx, task_id, action: str, field: str = "", old="", new="", note: str = ""):
    conn.execute(
        """INSERT INTO task_events(ts,task_id,actor,action,field,old_value,new_value,note,ip,ua)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (now_iso(), task_id, ctx.user, action, field,
         str(old)[:500], str(new)[:500], note[:MAX_NOTE], ctx.ip, ctx.ua[:200]))
    if task_id:
        conn.execute(
            """DELETE FROM task_events WHERE task_id=? AND id NOT IN
               (SELECT id FROM task_events WHERE task_id=? ORDER BY id DESC LIMIT ?)""",
            (task_id, task_id, CFG["max_events"]))


# --------------------------------------------------------------------------- 读取

def load_task(conn, task_id: int):
    row = q(conn, "SELECT * FROM tasks WHERE id=?", (task_id,), one=True)
    if not row:
        raise ApiError(404, "任务不存在")
    return row


def task_json(conn, row, ctx: Ctx, events: int = 0) -> dict:
    checks = [{"idx": c["idx"], "text": c["text"], "done": bool(c["done"]),
               "doneBy": c["done_by"] or None, "doneAt": c["done_at"] or None}
              for c in q(conn, "SELECT * FROM checks WHERE task_id=? ORDER BY idx", (row["id"],))]
    out = {
        "id": row["id"], "project": row["project"], "dept": row["dept"], "horizon": row["horizon"],
        "title": row["title"], "assignee": row["assignee"], "ack": bool(row["ack"]),
        "status": row["status"], "progress": row["progress"], "due": row["due"],
        "checks": checks,
        "createdBy": row["created_by"], "createdAt": row["created_at"],
        "updatedBy": row["updated_by"] or None, "updatedAt": row["updated_at"] or None,
        "canEdit": can_edit_task(ctx, row),
        "canEditScope": "all" if ctx.is_admin else ("own" if can_edit_task(ctx, row) else "none"),
    }
    if events:
        out["events"] = [{"ts": e["ts"], "actor": e["actor"], "action": e["action"],
                          "field": e["field"], "oldValue": e["old_value"], "newValue": e["new_value"],
                          "note": e["note"]}
                         for e in q(conn,
                                    "SELECT * FROM task_events WHERE task_id=? ORDER BY id DESC LIMIT ?",
                                    (row["id"], events))]
    return out


def structure_json(conn) -> dict:
    groups = []
    for r in q(conn, "SELECT name,grp FROM projects ORDER BY sort"):
        g = next((x for x in groups if x["name"] == r["grp"]), None)
        if g is None:
            g = {"name": r["grp"], "projects": []}
            groups.append(g)
        g["projects"].append(r["name"])
    return {"groups": groups, "depts": [r["name"] for r in q(conn, "SELECT name FROM depts ORDER BY sort")]}


def members_json(conn) -> list:
    rows = q(conn, "SELECT * FROM members ORDER BY role, username")
    known = {r["username"]: r for r in rows}
    out = []
    for u in sorted(GUARD_ADMINS):
        r = known.get(u)
        out.append({"username": u, "displayName": (r["display_name"] if r else "") or u,
                    "role": "admin", "dept": (r["dept"] if r else ""), "active": True,
                    "guard": True, "note": (r["note"] if r else "")})
    for r in rows:
        if r["username"] in GUARD_ADMINS:
            continue
        out.append({"username": r["username"], "displayName": r["display_name"] or r["username"],
                    "role": r["role"] if r["role"] in ROLES else "viewer", "dept": r["dept"],
                    "active": bool(r["active"]), "guard": False, "note": r["note"]})
    return out


def board_json(conn, ctx: Ctx) -> dict:
    rows = q(conn, "SELECT * FROM tasks ORDER BY sort, id")
    return {
        "schemaVersion": 1,
        "serverTime": now_iso(),
        "viewer": ctx.to_json(),
        "structure": structure_json(conn),
        "members": members_json(conn),
        "tasks": [task_json(conn, r, ctx) for r in rows],
    }


# --------------------------------------------------------------------------- 写入操作

def op_create_task(ctx: Ctx, payload: dict) -> dict:
    require_admin(ctx)
    with WRITE_LOCK:
        conn = db_connect()
        try:
            project = v_text(payload.get("project"), "项目", 60)
            dept = v_text(payload.get("dept"), "部门", 60)
            v_project_dept(conn, project, dept)
            horizon = v_enum(payload.get("horizon"), "类型", HORIZONS)
            title = v_text(payload.get("title"), "任务名称", MAX_TITLE)
            assignee = v_assignee(conn, payload.get("assignee") or "")
            due = v_due(payload.get("due") or date.today().isoformat())
            status = v_enum(payload.get("status") or "todo", "状态", STATUSES)
            progress = v_progress(payload.get("progress") or 0)
            checks = v_checks(payload.get("checks") or [], conn)
            if status == "done":
                progress = 100
            with conn:
                nxt = q(conn, "SELECT COALESCE(MAX(sort),0)+10 AS s FROM tasks", one=True)["s"]
                ts = now_iso()
                cur = conn.execute(
                    """INSERT INTO tasks(project,dept,horizon,title,assignee,ack,status,progress,due,sort,
                                         created_by,created_at,updated_by,updated_at)
                       VALUES(?,?,?,?,?,0,?,?,?,?,?,?,?,?)""",
                    (project, dept, horizon, title, assignee, status, progress, due, nxt,
                     ctx.user, ts, ctx.user, ts))
                tid = cur.lastrowid
                for k, c in enumerate(checks):
                    conn.execute("INSERT INTO checks(task_id,idx,text,done) VALUES(?,?,?,?)",
                                 (tid, k, c["text"], 1 if c["done"] else 0))
                record(conn, ctx, tid, "create", note=payload.get("note") or "")
            return task_json(conn, load_task(conn, tid), ctx, events=10)
        finally:
            conn.close()


def op_patch_task(ctx: Ctx, task_id: int, payload: dict) -> dict:
    with WRITE_LOCK:
        conn = db_connect()
        try:
            task = load_task(conn, task_id)
            require_task_edit(ctx, task)
            allowed = ADMIN_FIELDS if ctx.is_admin else EDITOR_FIELDS
            keys = [k for k in payload.keys() if k not in ("note",)]
            forbidden = [k for k in keys if k not in allowed]
            if forbidden:
                raise ApiError(403, "无权修改字段：" + "、".join(sorted(forbidden)))

            new = {}
            if "project" in payload:
                new["project"] = v_text(payload["project"], "项目", 60)
            if "dept" in payload:
                new["dept"] = v_text(payload["dept"], "部门", 60)
            if "project" in new or "dept" in new:
                v_project_dept(conn, new.get("project", task["project"]), new.get("dept", task["dept"]))
            if "horizon" in payload:
                new["horizon"] = v_enum(payload["horizon"], "类型", HORIZONS)
            if "title" in payload:
                new["title"] = v_text(payload["title"], "任务名称", MAX_TITLE)
            if "assignee" in payload:
                new["assignee"] = v_assignee(conn, payload["assignee"])
            if "due" in payload:
                new["due"] = v_due(payload["due"])
            if "status" in payload:
                new["status"] = v_enum(payload["status"], "状态", STATUSES)
            if "progress" in payload:
                new["progress"] = v_progress(payload["progress"])
            checks = None
            if "checks" in payload:
                checks = v_checks(payload["checks"], conn)

            final_status = new.get("status", task["status"])
            if final_status == "done":
                new["progress"] = 100
            if new.get("assignee", task["assignee"]) != task["assignee"]:
                new["ack"] = 0

            with conn:
                sets, args = [], []
                for k, v in new.items():
                    sets.append(f"{k}=?")
                    args.append(v)
                if sets:
                    sets.append("updated_by=?")
                    args.append(ctx.user)
                    sets.append("updated_at=?")
                    args.append(now_iso())
                    args.append(task_id)
                    conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", args)
                for k, v in new.items():
                    old = task[k]
                    old_cmp = bool(old) if k == "ack" else old
                    if old_cmp != v:
                        record(conn, ctx, task_id, "update", field=k, old=old_cmp, new=v)
                if checks is not None:
                    conn.execute("DELETE FROM checks WHERE task_id=?", (task_id,))
                    for k, c in enumerate(checks):
                        conn.execute("INSERT INTO checks(task_id,idx,text,done) VALUES(?,?,?,?)",
                                     (task_id, k, c["text"], 1 if c["done"] else 0))
                    record(conn, ctx, task_id, "update", field="checks",
                           old=len(task_json(conn, task, ctx)["checks"]), new=len(checks))
                note = (payload.get("note") or "").strip()
                if note:
                    record(conn, ctx, task_id, "note", note=note)
            return task_json(conn, load_task(conn, task_id), ctx, events=10)
        finally:
            conn.close()


def op_delete_task(ctx: Ctx, task_id: int) -> dict:
    require_admin(ctx)
    with WRITE_LOCK:
        conn = db_connect()
        try:
            task = load_task(conn, task_id)
            with conn:
                conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
                record(conn, ctx, None, "delete", field="title", old=task["title"],
                       note=f"删除任务 #{task_id}")
            return {"deleted": task_id, "title": task["title"]}
        finally:
            conn.close()


def op_ack(ctx: Ctx, task_id: int, on: bool) -> dict:
    with WRITE_LOCK:
        conn = db_connect()
        try:
            task = load_task(conn, task_id)
            if not (ctx.is_admin or (task["assignee"] and task["assignee"] == ctx.user)):
                raise ApiError(403, "只有该任务的接手人或管理员可以确认接手")
            with conn:
                conn.execute("UPDATE tasks SET ack=?,updated_by=?,updated_at=? WHERE id=?",
                             (1 if on else 0, ctx.user, now_iso(), task_id))
                record(conn, ctx, task_id, "ack" if on else "unack")
            return task_json(conn, load_task(conn, task_id), ctx, events=10)
        finally:
            conn.close()


def op_check(ctx: Ctx, task_id: int, idx: int, done: bool) -> dict:
    with WRITE_LOCK:
        conn = db_connect()
        try:
            task = load_task(conn, task_id)
            require_task_edit(ctx, task)
            row = q(conn, "SELECT * FROM checks WHERE task_id=? AND idx=?", (task_id, idx), one=True)
            if not row:
                raise ApiError(404, "自检项不存在")
            with conn:
                conn.execute("UPDATE checks SET done=?,done_by=?,done_at=? WHERE task_id=? AND idx=?",
                             (1 if done else 0, ctx.user if done else "", now_iso() if done else "",
                              task_id, idx))
                record(conn, ctx, task_id, "check", field=f"check[{idx}]",
                       old="done" if row["done"] else "open",
                       new="done" if done else "open", note=row["text"])
            return task_json(conn, load_task(conn, task_id), ctx, events=10)
        finally:
            conn.close()


def op_submit(ctx: Ctx, task_id: int) -> dict:
    with WRITE_LOCK:
        conn = db_connect()
        try:
            task = load_task(conn, task_id)
            require_task_edit(ctx, task)
            checks = q(conn, "SELECT * FROM checks WHERE task_id=? ORDER BY idx", (task_id,))
            if not checks:
                raise ApiError(400, "该任务没有自检项，无法提交确认")
            open_ones = [c["text"] for c in checks if not c["done"]]
            if open_ones:
                raise ApiError(409, "自检未全部通过，无法提交确认", detail=open_ones)
            with conn:
                conn.execute("UPDATE tasks SET status='done',progress=100,updated_by=?,updated_at=? WHERE id=?",
                             (ctx.user, now_iso(), task_id))
                record(conn, ctx, task_id, "submit",
                       note=f"自检 {len(checks)}/{len(checks)} 全部通过，提交确认")
            return task_json(conn, load_task(conn, task_id), ctx, events=10)
        finally:
            conn.close()


def op_upsert_member(ctx: Ctx, payload: dict) -> dict:
    require_admin(ctx)
    username = v_text(payload.get("username"), "账号", 40)
    if not USERNAME_RE.match(username):
        raise ApiError(400, "账号只能包含字母、数字、下划线、点或连字符，长度 2-40")
    role = v_enum(payload.get("role") or "viewer", "角色", ROLES)
    if username in GUARD_ADMINS:
        raise ApiError(409, "守护管理员账号不允许在任务台内修改")
    with WRITE_LOCK:
        conn = db_connect()
        try:
            with conn:
                ts = now_iso()
                existing = q(conn, "SELECT * FROM members WHERE username=?", (username,), one=True)
                if existing:
                    conn.execute(
                        """UPDATE members SET role=?,display_name=?,dept=?,active=?,note=?,updated_at=?
                           WHERE username=?""",
                        (role, v_text(payload.get("displayName", ""), "显示名", 40, allow_empty=True),
                         v_text(payload.get("dept", ""), "部门", 40, allow_empty=True),
                         1 if payload.get("active", True) else 0,
                         v_text(payload.get("note", ""), "备注", 200, allow_empty=True),
                         ts, username))
                    record(conn, ctx, None, "member_update", field=username,
                           old=existing["role"], new=role)
                else:
                    conn.execute(
                        """INSERT INTO members(username,display_name,role,dept,active,note,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (username,
                         v_text(payload.get("displayName", ""), "显示名", 40, allow_empty=True),
                         role,
                         v_text(payload.get("dept", ""), "部门", 40, allow_empty=True),
                         1 if payload.get("active", True) else 0,
                         v_text(payload.get("note", ""), "备注", 200, allow_empty=True),
                         ts, ts))
                    record(conn, ctx, None, "member_create", field=username, new=role)
            return {"member": next((m for m in members_json(conn) if m["username"] == username), None)}
        finally:
            conn.close()


# --------------------------------------------------------------------------- HTTP

def _registration_verified_identity(handler):
    """Verify independently so direct clients cannot create identity with headers."""
    import http.client
    connection = http.client.HTTPConnection('127.0.0.1', 8895, timeout=3)
    # Derive public URI from actual backend path; never trust client originals.
    public = '/dashboard/tasks' + handler.path
    try:
        connection.request('GET', '/verify', headers={
            'Cookie': handler.headers.get('Cookie', ''),
            'X-Original-Method': handler.command,
            'X-Original-URI': public})
        response = connection.getresponse()
        subject = response.getheader('X-Auth-User')
        verified_role = response.getheader('X-Auth-Role')
        response.read()
        if response.status != 200:
            raise ApiError(503 if response.status >= 500 else response.status,
                           'global verification unavailable' if response.status >= 500 else 'access denied')
        if not subject or verified_role not in ('admin', 'readonly'):
            raise ApiError(503, 'invalid verification response')
        if any(handler.headers.get(name) not in (None, value) for name, value in
               (('X-Auth-User', subject), ('X-Auth-Role', verified_role))):
            raise ApiError(403, 'identity header conflict')
        return subject, verified_role
    except (OSError, http.client.HTTPException):
        raise ApiError(503, 'global verification unavailable') from None
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "MMOEXPTaskboard/" + VERSION
    protocol_version = "HTTP/1.1"

    # ---- 基础工具
    def _send(self, code: int, body=b"", ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
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

    def _json(self, code: int, payload):
        self._send(code, json.dumps(payload, ensure_ascii=False))

    def _error(self, code: int, message: str, detail=None):
        self._json(code, {"error": message, "detail": detail})

    def _ctx(self) -> Ctx:
        user, verified_role = _registration_verified_identity(self)
        ip = (self.headers.get("X-Real-IP") or self.client_address[0] or "")
        ua = self.headers.get("User-Agent") or ""
        conn = db_connect()
        try:
            role, registered = _registration_member(conn, user, verified_role)
            return Ctx(user, role, ip, ua, registered)
        finally:
            conn.close()

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Content-Length 非法")
        if n <= 0:
            return {}
        if n > CFG["max_body"]:
            raise ApiError(413, "请求体过大")
        raw = self.rfile.read(n)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ApiError(400, "请求体不是合法 JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "请求体必须是 JSON 对象")
        return data

    # ---- 路由
    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):
        self._route("HEAD")

    def do_POST(self):
        self._route("POST")

    def do_PATCH(self):
        self._route("PATCH")

    def do_DELETE(self):
        self._route("DELETE")

    def _route(self, method: str):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if path == "/health":
                conn = db_connect()
                try:
                    n = q(conn, "SELECT COUNT(*) AS n FROM tasks", one=True)["n"]
                finally:
                    conn.close()
                return self._json(200, {"ok": True, "version": VERSION, "tasks": n,
                                        "dbWritable": os.access(str(CFG["data_dir"]), os.W_OK),
                                        "time": now_iso()})

            ctx = self._ctx()
            if not ctx.user:
                return self._error(401, "未取得登录身份，请通过统一门户登录后再访问")
            if not ctx.registered and CFG["unregistered"] == "deny":
                # 统一门户 /verify 在门户会话失效时会回退到 FC27 只读门禁，并把 FC27 认可的
                # 账号也标记成 dashboard 组成员。若不在这里显式拦截，FC27 的外部自注册用户
                # 就能读到内部任务、接手人与人员安排。默认严格拒绝，要放行请把
                # config.env 的 TASKBOARD_UNREGISTERED 改为 readonly。
                log("拦截未登记账号：%s（来源 %s）" % (ctx.user, ctx.ip), "warn")
                return self._error(403, "该账号尚未在任务台登记，请联系管理员开通后再访问")

            import green_plan
            if green_plan.route(self, sys.modules[__name__], ctx, method, path):
                return

            if path == "/api/session" and method in ("GET", "HEAD"):
                conn = db_connect()
                try:
                    return self._json(200, {"viewer": ctx.to_json(), "serverTime": now_iso(),
                                            "structure": structure_json(conn)})
                finally:
                    conn.close()

            if path == "/api/board" and method in ("GET", "HEAD"):
                conn = db_connect()
                try:
                    return self._json(200, board_json(conn, ctx))
                finally:
                    conn.close()

            if path == "/api/members" and method in ("GET", "HEAD"):
                conn = db_connect()
                try:
                    return self._json(200, {"members": members_json(conn), "viewer": ctx.to_json()})
                finally:
                    conn.close()

            if path == "/api/members" and method == "POST":
                if not ctx.is_admin:
                    raise ApiError(403, "需要管理员权限")
                return self._json(200, op_upsert_member(ctx, self._body()))

            if path == "/api/tasks" and method == "POST":
                return self._json(200, op_create_task(ctx, self._body()))

            m = re.match(r"^/api/tasks/(\d+)$", path)
            if m:
                tid = int(m.group(1))
                if method == "GET" or method == "HEAD":
                    conn = db_connect()
                    try:
                        return self._json(200, task_json(conn, load_task(conn, tid), ctx, events=40))
                    finally:
                        conn.close()
                if method == "PATCH":
                    return self._json(200, op_patch_task(ctx, tid, self._body()))
                if method == "DELETE":
                    return self._json(200, op_delete_task(ctx, tid))

            m = re.match(r"^/api/tasks/(\d+)/(ack|submit)$", path)
            if m and method == "POST":
                tid = int(m.group(1))
                body = self._body()
                if m.group(2) == "ack":
                    return self._json(200, op_ack(ctx, tid, bool(body.get("on", True))))
                return self._json(200, op_submit(ctx, tid))

            m = re.match(r"^/api/tasks/(\d+)/checks$", path)
            if m and method == "POST":
                body = self._body()
                idx = body.get("idx")
                if not isinstance(idx, int) or idx < 0:
                    raise ApiError(400, "idx 必须是非负整数")
                return self._json(200, op_check(ctx, int(m.group(1)), idx, bool(body.get("done", True))))

            m = re.match(r"^/api/tasks/(\d+)/events$", path)
            if m and method in ("GET", "HEAD"):
                conn = db_connect()
                try:
                    load_task(conn, int(m.group(1)))
                    rows = q(conn, "SELECT * FROM task_events WHERE task_id=? ORDER BY id DESC LIMIT 200",
                             (int(m.group(1)),))
                    return self._json(200, {"events": [
                        {"ts": e["ts"], "actor": e["actor"], "action": e["action"], "field": e["field"],
                         "oldValue": e["old_value"], "newValue": e["new_value"], "note": e["note"]}
                        for e in rows]})
                finally:
                    conn.close()

            return self._error(404, "接口不存在：" + path)

        except ApiError as e:
            return self._error(e.status, e.message, e.detail)
        except Exception:
            log("未处理异常：" + traceback.format_exc(), "error")
            return self._error(500, "服务内部错误")

    def log_message(self, fmt, *args):
        if os.environ.get("TASKBOARD_QUIET"):
            return
        log("%s %s" % (self.address_string(), fmt % args), "access")


# --------------------------------------------------------------------------- 入口

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--init-only" in argv:
        info = init_db()
        print(json.dumps({"init": info, "db": str(CFG["db"])}, ensure_ascii=False))
        return 0
    if "--selftest" in argv:
        return selftest()

    sys.path.insert(0, '/opt/auth-portal/registration-runtime/20261007-ca6258ad')
    from consumer_seams import install_taskboard as _registration_install_taskboard
    import native_access_policy as _registration_policy
    _registration_install_taskboard(sys.modules[__name__], _registration_policy)
    info = init_db()
    log("任务台服务启动 version=%s db=%s" % (VERSION, CFG["db"]))
    log("初始化：%s" % json.dumps(info, ensure_ascii=False))
    srv = ThreadingHTTPServer((CFG["bind"], CFG["port"]), Handler)
    srv.daemon_threads = True
    log("监听 http://%s:%d （仅本机；身份由 nginx 注入 X-Auth-User）" % (CFG["bind"], CFG["port"]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("收到中断，正在退出")
    finally:
        srv.server_close()
    return 0


def selftest() -> int:
    """最小自检：建库、权限函数、纯校验逻辑。不联网、不起服务。"""
    fails = []
    init_db(verbose=False)
    conn = db_connect()
    try:
        for u, want in (("wulv", "admin"), ("chenchao", "admin"), ("DY", "admin"),
                        ("someone", "viewer"), ("", "anonymous")):
            got = role_of(conn, u)
            if got != want:
                fails.append(f"role_of({u!r}) = {got}, 期望 {want}")
        n = q(conn, "SELECT COUNT(*) AS n FROM tasks", one=True)["n"]
        if n < 1:
            fails.append("任务表为空")
        checks = q(conn, "SELECT COUNT(*) AS n FROM checks", one=True)["n"]
        if checks < 1:
            fails.append("自检项为空")
    finally:
        conn.close()

    for bad, name in ((None, "空"), ("x", "过短"), ("2026-13-40", "非法日期")):
        try:
            v_due(bad)
            fails.append(f"v_due({name}) 未拒绝")
        except ApiError:
            pass
    try:
        v_progress(101)
        fails.append("v_progress(101) 未拒绝")
    except ApiError:
        pass

    if fails:
        print("自检失败：")
        for f in fails:
            print("  -", f)
        return 1
    print("自检通过：角色判定、种子数据、字段校验均正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
