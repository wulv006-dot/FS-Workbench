# -*- coding: utf-8 -*-
"""订单/发货历史库（SQLite 单文件）。

为什么要它
----------
采集器原来每轮都从 page=1 翻到 total，把已经抓过的行重新读一遍
（2026-10-29 实测近 7 天 36,098 页请求）。明细数据是**只增不改**的，
本该落库一次、之后只取增量。

设计约束
--------
* 服务器 sqlite 只有 3.7.17 —— 全篇只用 `INSERT OR REPLACE`，
  不写 UPSERT / RETURNING / partial index / 生成列。
* 幂等：订单主键 = 后台 order.id，发货主键 = delivery_id，
  同一批数据重复写不会膨胀。
* 保留 raw JSON：后台加字段时不用改表，回放也不用重抓。

表
--
orders       订单主表
deliveries   发货/成本
sync_state   水位线（每类一行）
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path

DEFAULT_PATH = os.environ.get("FS_ORDER_DB") or "/opt/sales-dashboard/data/history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
  id            INTEGER PRIMARY KEY,
  order_no      TEXT,
  gid           INTEGER,
  site_id       INTEGER,
  uid           INTEGER,
  paytime       TEXT,
  pay_status    INTEGER,
  status        INTEGER,
  amount        REAL,
  discount_code TEXT,
  raw           TEXT NOT NULL,
  first_seen    TEXT,
  last_seen     TEXT
);
CREATE INDEX IF NOT EXISTS ix_orders_paytime ON orders(paytime);
CREATE INDEX IF NOT EXISTS ix_orders_gid     ON orders(gid, site_id);

CREATE TABLE IF NOT EXISTS deliveries (
  delivery_id TEXT PRIMARY KEY,
  order_no    TEXT,
  source      TEXT,
  sn          TEXT,
  trade_at    TEXT,
  gid         INTEGER,
  genre       TEXT,
  qty         REAL,
  cost_unit   REAL,
  cost_total  REAL,
  sale_total  REAL,
  supplier    TEXT,
  operator    TEXT,
  status      TEXT,
  raw         TEXT,
  first_seen  TEXT,
  last_seen   TEXT
);
CREATE INDEX IF NOT EXISTS ix_dlv_trade ON deliveries(trade_at);
CREATE INDEX IF NOT EXISTS ix_dlv_order ON deliveries(order_no);

CREATE TABLE IF NOT EXISTS sync_state (
  kind       TEXT PRIMARY KEY,
  high_id    INTEGER,
  high_time  TEXT,
  last_run   TEXT,
  last_full  TEXT,
  last_deep  TEXT,
  last_error TEXT,
  rows       INTEGER
);
"""

_AMOUNT_KEYS = ("amount", "total", "pay_amount", "price", "money")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _num(v, cast=float):
    try:
        if v in (None, ""):
            return None
        return cast(str(v).replace(",", "").replace("$", "").strip())
    except Exception:
        return None


_LEAD_DT = re.compile(r"^\s*(\d{2,4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2}:\d{2})")


def _dt(v):
    """统一成 'YYYY-MM-DD HH:MM:SS'（解析不了返回 None）。

    后台三种形态都出现过：
      * 订单 paytime           '2026-10-29 16:26:45'
      * 发货 trade_at          '26-09-29 22:32:39'（2 位年）
      * 改过的发货 trade_at    '26-10-29 14:08:41        改 26-10-29 14:09:49'
    最后一种如果原样入库，字符串比较会把它排到所有正常时间之上，
    水位线直接被污染（实测把 2 小时窗口放大成 7 天、翻了 125 页）。
    所以这里只取**开头那个**时间，取不到就返回 None。
    """
    s = str(v or "").strip().replace("/", "-")
    m = _LEAD_DT.match(s)
    if not m:
        return None
    y, mo, d, t = m.groups()
    if len(y) == 2:
        y = "20" + y
    return "%s-%s-%s %s" % (y, mo, d, t)


def open_db(path: str | None = None) -> sqlite3.Connection:
    p = Path(path or DEFAULT_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ------------------------------------------------------------------ 写
def upsert_orders(conn, rows) -> int:
    if not rows:
        return 0
    now = _now()
    payload = []
    for r in rows:
        oid = _num(r.get("id"), int)
        if not oid:
            continue
        amount = None
        for k in _AMOUNT_KEYS:
            if r.get(k) not in (None, ""):
                amount = _num(r.get(k))
                break
        payload.append((
            oid,
            str(r.get("order_no") or r.get("sn") or ""),
            _num(r.get("gid"), int),
            _num(r.get("site_id"), int),
            _num(r.get("uid"), int),
            _dt(r.get("paytime")),
            _num(r.get("pay_status"), int),
            _num(r.get("status"), int),
            amount,
            str(r.get("discount_code") or ""),
            json.dumps(r, ensure_ascii=False, sort_keys=True),
            now, now,
        ))
    if not payload:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO orders"
        " (id,order_no,gid,site_id,uid,paytime,pay_status,status,amount,discount_code,raw,first_seen,last_seen)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", payload)
    conn.commit()
    return len(payload)


def upsert_deliveries(conn, rows, gid: int | None = None) -> int:
    if not rows:
        return 0
    now = _now()
    payload = []
    for r in rows:
        did = str(r.get("delivery_id") or "").strip()
        if not did:
            continue
        payload.append((
            did,
            str(r.get("order_no") or r.get("sn") or ""),
            str(r.get("source") or ""),
            str(r.get("sn") or ""),
            _dt(r.get("trade_at")),
            _num(r.get("gid"), int) or gid,
            str(r.get("genre") or ""),
            _num(r.get("qty")),
            _num(r.get("cost_unit")),
            _num(r.get("cost_total")),
            _num(r.get("sale_total")),
            str(r.get("supplier") or ""),
            str(r.get("operator") or ""),
            str(r.get("settle_status") or ""),
            json.dumps(r, ensure_ascii=False, sort_keys=True),
            now, now,
        ))
    if not payload:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO deliveries"
        " (delivery_id,order_no,source,sn,trade_at,gid,genre,qty,cost_unit,cost_total,"
        "  sale_total,supplier,operator,status,raw,first_seen,last_seen)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", payload)
    conn.commit()
    return len(payload)


def existing_delivery_ids(conn, ids) -> set:
    ids = [str(i) for i in ids if i]
    out = set()
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        q = "SELECT delivery_id FROM deliveries WHERE delivery_id IN (%s)" % ",".join("?" * len(chunk))
        out.update(r[0] for r in conn.execute(q, chunk))
    return out


def ids_in_range(conn, kind: str, lo: str, hi: str) -> set:
    """区间内已经入库的主键集合 —— 增量翻页靠它「追上已知就收手」。

    有了这个集合，重叠窗口就可以开得很大（订单 24h、发货 12h）而几乎不花成本：
    第一页通常全是已知数据，直接停。
    """
    if kind == "orders":
        q = "SELECT id FROM orders WHERE paytime >= ? AND paytime <= ?"
    else:
        q = "SELECT delivery_id FROM deliveries WHERE trade_at >= ? AND trade_at <= ?"
    return {str(r[0]) for r in conn.execute(q, (lo, hi))}


def should_stop(batch, id_key: str, known) -> bool:
    """这一页能否当最后一页：空页，或整页主键都已在库里。

    比"按第一页的 total 算页数"可靠 —— total 是翻页开始那一刻的快照，
    下单高峰时窗口内最旧的那几条会被新单挤到算出来的页数之外，静默丢掉。
    列表按 id 倒序（订单显式 order=id,desc，发货页默认也是最新在前），
    所以"整页都认识"就等于"后面全是更旧的、已经抓过的"。
    """
    if not batch:
        return True
    if not known:
        return False
    for r in batch:
        if str(r.get(id_key) or "") not in known:
            return False
    return True


# ------------------------------------------------------------------ 读
def count(conn, table: str) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0])


def load_orders(conn, start: str, end: str) -> list:
    rows = conn.execute(
        "SELECT raw FROM orders WHERE paytime >= ? AND paytime <= ? ORDER BY id DESC",
        (start + " 00:00:00", end + " 23:59:59")).fetchall()
    return [json.loads(r[0]) for r in rows]


def load_deliveries(conn, start: str, end: str) -> list:
    rows = conn.execute(
        "SELECT raw FROM deliveries WHERE trade_at >= ? AND trade_at <= ? ORDER BY trade_at DESC",
        (start + " 00:00:00", end + " 23:59:59")).fetchall()
    return [json.loads(r[0]) for r in rows]


def get_state(conn, kind: str) -> dict:
    r = conn.execute("SELECT * FROM sync_state WHERE kind=?", (kind,)).fetchone()
    return dict(r) if r else {}


def set_state(conn, kind: str, **kw) -> None:
    cur = get_state(conn, kind)
    cur.setdefault("kind", kind)
    cur.update({k: v for k, v in kw.items() if v is not None})
    conn.execute(
        "INSERT OR REPLACE INTO sync_state"
        " (kind,high_id,high_time,last_run,last_full,last_deep,last_error,rows)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (kind, cur.get("high_id"), cur.get("high_time"), cur.get("last_run"),
         cur.get("last_full"), cur.get("last_deep"), cur.get("last_error"), cur.get("rows")))
    conn.commit()


def bump_watermark(conn, kind: str, rows) -> None:
    """把水位推到本批数据里最大的 id / 最晚的时间。"""
    st = get_state(conn, kind)
    high_id = st.get("high_id") or 0
    high_time = st.get("high_time") or ""
    for r in rows:
        v = _num(r.get("id"), int)
        if v and v > high_id:
            high_id = v
        t = _dt(r.get("paytime") if kind == "orders" else r.get("trade_at")) or ""
        if t > high_time:
            high_time = t
    set_state(conn, kind, high_id=high_id, high_time=high_time)


# ------------------------------------------------------------------ 回填
def import_json(conn, path: Path, kind: str, gid: int | None = None) -> int:
    """把采集器以前落盘的 orders.json / deliveries.json 直接倒进库。

    有这批文件就不用为了建库再翻一遍 43 天的页（约 650 页）。
    """
    p = Path(path)
    if not p.exists():
        return 0
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(rows, list) or not rows:
        return 0
    n = upsert_orders(conn, rows) if kind == "orders" else upsert_deliveries(conn, rows, gid)
    bump_watermark(conn, kind, rows)
    # 这批 JSON 本身就是全量快照 —— 直接算作「刚做过全量/重扫」，
    # 不然建库后第一轮会立刻再跑一次 7 天重扫（订单 15 页 + 发货 105 页）。
    set_state(conn, kind, rows=count(conn, kind), last_run=_now(),
              last_full=_now(), last_deep=_now())
    return n
