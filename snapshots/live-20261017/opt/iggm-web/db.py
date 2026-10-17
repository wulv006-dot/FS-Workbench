# -*- coding: utf-8 -*-
"""
SQLite 存储层：任务表
=====================
无账号体系，所有人共享同一条全局队列。
提交人只是一个可留空的备注名（存浏览器本地，不注册、不校验）。
"""
import os
import sqlite3
import threading
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("IGGM_DATA", os.path.join(BASE_DIR, "data"))
EXPORT_DIR = os.environ.get("IGGM_EXPORTS", os.path.join(DATA_DIR, "exports"))
DB_PATH = os.path.join(DATA_DIR, "iggm.db")

_lock = threading.Lock()

# 允许 UPDATE 的字段白名单（防列名注入）
_UPDATABLE = {"status", "progress", "detail", "rows", "file_name", "error",
              "finished_at"}

_CREATE_TASKS = """
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    site        TEXT NOT NULL DEFAULT '',
    game        TEXT NOT NULL DEFAULT '',
    game_url    TEXT NOT NULL,
    submitter   TEXT NOT NULL DEFAULT '',
    categories  TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'queued',
    progress    REAL NOT NULL DEFAULT 0,
    detail      TEXT NOT NULL DEFAULT '',
    rows        INTEGER NOT NULL DEFAULT 0,
    file_name   TEXT NOT NULL DEFAULT '',
    error       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT ''
);
"""


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn):
    """把旧版（带 users / username 列）的库平滑升级到无账号结构；
    已是无账号结构的，缺列则补列（如后加的 site）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
    if not cols:
        return
    if "game" not in cols or "username" in cols:
        conn.executescript("ALTER TABLE tasks RENAME TO tasks_old;")
        conn.execute(_CREATE_TASKS)
        conn.execute(
            "INSERT INTO tasks(id, site, game, game_url, submitter, categories,"
            " status, progress, detail, rows, file_name, error, created_at,"
            " finished_at) "
            "SELECT id, '', '', game_url, COALESCE(username,''), categories,"
            " status, progress, detail, rows, file_name, error, created_at,"
            " finished_at FROM tasks_old")
        conn.execute("DROP TABLE tasks_old")
        return
    if "site" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN site TEXT NOT NULL DEFAULT ''")


def init_db():
    with _lock:
        conn = connect()
        try:
            conn.execute(_CREATE_TASKS)
            _ensure_schema(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created "
                         "ON tasks(created_at DESC)")
            conn.commit()
        finally:
            conn.close()
    os.makedirs(EXPORT_DIR, exist_ok=True)


# ---------------- 任务 ----------------
def insert_task(task):
    with _lock:
        conn = connect()
        try:
            conn.execute(
                "INSERT INTO tasks(id, site, game, game_url, submitter,"
                " categories, status, progress, detail, rows, file_name, error,"
                " created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task["id"], task.get("site", ""), task.get("game", ""),
                 task["url"], task.get("submitter", ""),
                 ",".join(task["categories"]),
                 task["status"], task["progress"], task["detail"],
                 task["rows"], task.get("file", ""), task["error"],
                 task["created"]))
            conn.commit()
        finally:
            conn.close()


def update_task(task_id, **kv):
    cols = [k for k in kv if k in _UPDATABLE]
    if not cols:
        return
    sql = "UPDATE tasks SET " + ",".join(c + "=?" for c in cols) + " WHERE id=?"
    args = [kv[c] for c in cols] + [task_id]
    with _lock:
        conn = connect()
        try:
            conn.execute(sql, args)
            conn.commit()
        finally:
            conn.close()


def list_tasks(limit=40):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,))]
    finally:
        conn.close()
