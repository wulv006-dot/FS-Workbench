# -*- coding: utf-8 -*-
"""SQLite 存储层（独立库 data/g2gfollow.db，与 d4follow 的库无关）。

三张表，各管一段：
  snapshot    每轮采集的原始落盘（成本 / 货架），只留最近若干轮
  plan_row    最近一次生成的建议单（dry-run 工单），带逐行「放行」开关
  write_log   真实写入的审计流水（改前价 / 改后价 / 读回校验结果）

并发：gunicorn 是 gthread 多线程，这里每次操作现开现关连接 + WAL，
不做连接池，简单且不会踩「SQLite objects created in a thread…」。
"""
import json
import os
import sqlite3
import time
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "g2gfollow.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    ts      REAL NOT NULL,
    kind    TEXT NOT NULL,          -- cost | offers
    payload TEXT NOT NULL,
    PRIMARY KEY (ts, kind)
);
CREATE INDEX IF NOT EXISTS idx_snap_kind ON snapshot(kind, ts DESC);

CREATE TABLE IF NOT EXISTS plan_row (
    ts          REAL NOT NULL,
    offer_id    TEXT NOT NULL,
    zone_group  TEXT,
    server      TEXT,
    side        TEXT,
    title       TEXT,
    cur_price   REAL,
    cost        REAL,
    qty_wan     REAL,               -- 可买量（万基纳）
    enough      TEXT,               -- Y / N
    target      REAL,
    diff        REAL,
    action      TEXT,
    mode        TEXT,
    note        TEXT,
    -- 2026-10-13 新增：跟 cheapold 口径要落库，看板重启后仍能显示「跟谁、基准多少」
    base        REAL,               -- 本轮真正在跟的基准价（原始值，未下浮）
    base_src    TEXT,               -- 基准来源：G2G·cheapold×(1−1%)｜利润率上限40% 等
    cb          REAL,               -- 该区卖家 cheapold 的原始挂牌价（无此卖家则 NULL）
    released    INTEGER DEFAULT 0,  -- 人工放行开关
    PRIMARY KEY (ts, offer_id)
);
CREATE INDEX IF NOT EXISTS idx_plan_ts ON plan_row(ts DESC);

CREATE TABLE IF NOT EXISTS write_log (
    ts          REAL NOT NULL,
    offer_id    TEXT NOT NULL,
    zone_group  TEXT,
    server      TEXT,
    side        TEXT,
    old_price   REAL,
    new_price   REAL,
    api_ok      INTEGER,
    readback    REAL,
    verified    INTEGER,
    operator    TEXT,
    detail      TEXT,
    PRIMARY KEY (ts, offer_id)
);
CREATE INDEX IF NOT EXISTS idx_write_ts ON write_log(ts DESC);
"""


def _conn():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


@contextmanager
def _db():
    """取连接 → 用完提交并关闭。

    注意别写成 `with sqlite3.connect(...) as c`：那个上下文只提交事务、
    **不关连接**，长期跑会把连接数堆起来。
    """
    c = _conn()
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with _db() as c:
        c.executescript(SCHEMA)
        # 2026-10-13 迁移：老库的 plan_row 没有 base / base_src / cb 三列，补上（幂等）。
        cols = {r[1] for r in c.execute("PRAGMA table_info(plan_row)")}
        if "base" not in cols:
            c.execute("ALTER TABLE plan_row ADD COLUMN base REAL")
        if "base_src" not in cols:
            c.execute("ALTER TABLE plan_row ADD COLUMN base_src TEXT")
        if "cb" not in cols:
            c.execute("ALTER TABLE plan_row ADD COLUMN cb REAL")


# ───────────────────────── 快照 ─────────────────────────

def save_snapshot(kind, payload, keep=8):
    ts = time.time()
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO snapshot(ts, kind, payload) VALUES(?,?,?)",
                  (ts, kind, json.dumps(payload, ensure_ascii=False)))
        # 只留最近 keep 轮，避免库无限长
        c.execute("""DELETE FROM snapshot WHERE kind=? AND ts NOT IN
                     (SELECT ts FROM snapshot WHERE kind=? ORDER BY ts DESC LIMIT ?)""",
                  (kind, kind, keep))
    return ts


def latest_snapshot(kind):
    with _db() as c:
        r = c.execute("SELECT ts, payload FROM snapshot WHERE kind=? ORDER BY ts DESC LIMIT 1",
                      (kind,)).fetchone()
    if not r:
        return None, None
    return r["ts"], json.loads(r["payload"])


# ───────────────────────── 建议单 ─────────────────────────

def save_plan(rows):
    ts = time.time()
    with _db() as c:
        for r in rows:
            c.execute("""INSERT OR REPLACE INTO plan_row
                (ts, offer_id, zone_group, server, side, title, cur_price, cost, qty_wan,
                 enough, target, diff, action, mode, note, base, base_src, cb, released)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                      (ts, r["offer_id"], r["区服组"], r["服务区"], r["阵营"], r.get("标题"),
                       r.get("当前价"), r.get("成本"), r.get("可买量万"), r.get("够量"),
                       r.get("目标价"), r.get("差额"), r.get("动作"), r.get("定价方式"),
                       r.get("说明"), r.get("基准价"), r.get("基准来源"),
                       r.get("cheapold价")))
    return ts


def latest_plan():
    with _db() as c:
        ts = c.execute("SELECT MAX(ts) AS t FROM plan_row").fetchone()["t"]
        if not ts:
            return None, []
        rows = [dict(x) for x in c.execute(
            "SELECT * FROM plan_row WHERE ts=? ORDER BY zone_group, server, side", (ts,))]
    return ts, rows


def set_released(offer_id, on):
    with _db() as c:
        ts = c.execute("SELECT MAX(ts) AS t FROM plan_row").fetchone()["t"]
        cur = c.execute("UPDATE plan_row SET released=? WHERE ts=? AND offer_id=?",
                        (1 if on else 0, ts, offer_id))
        return cur.rowcount


def released_rows():
    ts, rows = latest_plan()
    return [r for r in rows if r.get("released")]


# ───────────────────────── 写入流水 ─────────────────────────

def log_write(rec):
    with _db() as c:
        c.execute("""INSERT OR REPLACE INTO write_log
            (ts, offer_id, zone_group, server, side, old_price, new_price,
             api_ok, readback, verified, operator, detail)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (rec.get("ts") or time.time(), rec["offer_id"], rec.get("区服组"),
                   rec.get("服务区"), rec.get("阵营"), rec.get("old_price"),
                   rec.get("new_price"), 1 if rec.get("api_ok") else 0,
                   rec.get("readback"),
                   1 if rec.get("verified") else (0 if rec.get("verified") is False else None),
                   rec.get("operator") or "dashboard", rec.get("detail")))


def list_writes(limit=100):
    with _db() as c:
        return [dict(x) for x in c.execute(
            "SELECT * FROM write_log ORDER BY ts DESC LIMIT ?", (limit,))]


if __name__ == "__main__":
    init()
    print("init ok ->", DB)
    print("job 表就绪；库大小存在否:", os.path.exists(DB))
