# -*- coding: utf-8 -*-
"""SQLite 存储层：IGGM 竞品价 / 我方前端价 / 千岛成本 / 跟价决策台账"""
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS iggm_price (
    ts          TEXT NOT NULL,
    goods_no    TEXT NOT NULL,
    target_key  TEXT,
    cate_id     TEXT,
    cate_name   TEXT,
    title       TEXT,
    price_usd   REAL,
    list_usd    REAL,
    discount    TEXT,
    min_num     INTEGER,
    stock       INTEGER,
    status      INTEGER,
    sales       INTEGER,
    ig_update   TEXT,
    url         TEXT,
    PRIMARY KEY (ts, goods_no)
);
CREATE INDEX IF NOT EXISTS idx_ig_goods ON iggm_price(goods_no, ts);

CREATE TABLE IF NOT EXISTS qd_cost (
    ts          TEXT NOT NULL,
    spec        TEXT NOT NULL,
    spu_id      TEXT NOT NULL,
    name        TEXT,
    category    TEXT,
    unit        TEXT,
    price_cny   REAL,
    -- 2026-09-27 起 price_cny 改为「订单簿深度加权进价(DWC)」；下面几列是留证用的口径
    min_buy     INTEGER,   -- Q：本商品的补货批量
    depth       INTEGER,   -- 全簿可售库存（SELL 且>0）
    book_n      INTEGER,   -- 订单簿在售条数
    lo_price    REAL,      -- 订单簿最低可买单价
    bulk_share  REAL,      -- 起售量>=阈值 的库存占比
    src         TEXT,      -- book = 订单簿价 / agg = 平台聚合价（回退）
    note        TEXT,      -- 深度不足 / 跳过N档 / 批量档 / 单件档 …
    PRIMARY KEY (ts, spec, spu_id)
);

CREATE TABLE IF NOT EXISTS our_price (
    ts          TEXT NOT NULL,
    key         TEXT NOT NULL,
    title       TEXT,
    price_usd   REAL,
    cost_cny    REAL,
    game        TEXT,
    server_zone TEXT,
    cate        TEXT,
    source      TEXT,
    front_disc  REAL,      -- 前端**实测**折扣（data-discount，100 = 不打折）
    PRIMARY KEY (ts, key)
);

CREATE TABLE IF NOT EXISTS decisions (
    ts          TEXT NOT NULL,
    key         TEXT,
    title       TEXT,
    action      TEXT,      -- follow_up / follow_down / hold / blocked
    iggm_old    REAL,
    iggm_new    REAL,
    ours_old    REAL,
    ours_new    REAL,
    target_usd  REAL,
    cost_usd    REAL,
    margin_old  REAL,
    margin_new  REAL,
    mode        TEXT,
    applied     INTEGER DEFAULT 0,
    reason      TEXT,
    PRIMARY KEY (ts, key)
);

CREATE TABLE IF NOT EXISTS runs (
    ts          TEXT PRIMARY KEY,
    iggm_count  INTEGER,
    qd_count    INTEGER,
    our_count   INTEGER,
    follows     INTEGER,
    blocked     INTEGER,
    elapsed_s   REAL,
    mode        TEXT,
    note        TEXT
);

-- 金币（Gold / Currency）：与物品分表 —— 金币一行 = 一个服务区，
-- 价格口径是「每 M 单价」，可改量是「采购成本」，都不是物品那套。
CREATE TABLE IF NOT EXISTS gold_price (
    ts          TEXT NOT NULL,
    key         TEXT NOT NULL,
    title       TEXT,
    row_id      TEXT,        -- 后台「金币价格管理」行ID（== 服务区ID）
    aid         TEXT,        -- 我方前端服务区 ID
    iggm_sid    TEXT,
    iggm_raw    REAL,        -- IGGM 机房抓取价（未折算）
    iggm_per_m  REAL,        -- IGGM 每 M 价（跟价用，已折算成客户真价）
    our_per_m   REAL,        -- 我方前端每 M 价（折后）
    our_tier    INTEGER,     -- 我方取样档位（最接近对标档位的那档）
    our_tiers   TEXT,        -- 我方档位集合（JSON 数组）
    margin_rate REAL,        -- 利润率
    cost_old    REAL,
    cost_target REAL,        -- 目标采购成本（要写进后台的值）
    ratio       REAL,        -- 我方每M / IGGM每M
    action      TEXT,        -- follow_up / follow_down / hold
    reason      TEXT,
    divisor     REAL,        -- 成本除数 = 汇率×(1−利润率)÷前台系数（≈5.054，别用 5.32）
    big_tier    INTEGER,     -- 对照用的「最大金币档位」M 数（用户口径：用最大档对照）
    iggm_big    REAL,        -- IGGM 真价 在该档的总价
    our_big     REAL,        -- 我方前端 在该档的总价（现状）
    tgt_big     REAL,        -- 改正后 在该档的总价
    below_pct   REAL,        -- 改后比 IGGM 真价低几个百分点（目标 ≈ 让价百分比）
    ok          INTEGER,     -- 达标（tgt_big ≤ iggm_big × 让价系数）1/0
    -- 2026-10-01：AION2 三源基准（G2G/ELD/IGGM）可见化。此前 core_gold 已算出
    -- rec["多源明细"]，但 save_gold 没写这几列 ⇒ 数据落库即丢 ⇒ 页面看不到 G2G/ELD。
    src_g2g     REAL,        -- G2G 该区最低 $/M（无数据 = NULL）
    src_eld     REAL,        -- ELDorado 该区最低 $/M（无数据 = NULL）
    src_igmm    REAL,        -- IGGM 该区 $/M（多源口径下的第三方参考）
    src_base    TEXT,        -- 基准取谁：G2G / ELD / IGGM(更低) / IGGM / -
    src_base_v  REAL,        -- 基准价 $/M（三源 min，或同大区均价兜底）
    src_fallb   TEXT,        -- 兜底方式：同大区均价 / 仅 IGGM（空 = 未兜底）
    -- 2026-10-02：改用 DD373 推荐价加价。旧三源仍采集但退出定价，
    --   所以「竞品最低价 / 差距」变成**纯展示**列（看板「差距对比」那一列）。
    comp_min     REAL,       -- G2G/ELD/IGGM 三者里**有数的那几个**的最低 $/M
    comp_min_src TEXT,       -- 竞品最低价取自哪一家（G2G / ELD / IGGM）
    gap_comp     REAL,       -- 我方现价 − 竞品最低价（$/M，正 = 我方更贵）
    gap_comp_pct REAL,       -- 同上百分比
    price_mode   TEXT,       -- 本行用的定价模式（dd373_markup / multisrc / 空=旧口径）
    price_tier   INTEGER,    -- 定价来源级别：1=DD373推荐价+加价 2=G2G兜底 3=默认售价
    src2_g2g     REAL,       -- G2G 兜底用的那一档 $/M（级别 2 才有值）
    dd_ref_usd   REAL,       -- DD373 推荐价折 $/M（定价基准，留证）
    dd_ref_cny   REAL,       -- DD373 单价 元/万基纳（留证）
    dd_items     INTEGER,    -- DD373 该游戏区综合排序下的挂单条数
    -- 2026-10-09：G2G **跟价基准**（cheapold 优先口径）—— 回答「看板 G2G 那一列到底在跟谁」。
    --   此前看板 G2G 列取的是 src_g2g = **三源·大区级** G2G 最低价（core_multi），
    --   与真正被跟着的价（**子服务器** cheapold / 推荐前二，见 core_g2g.cheapold_base）
    --   不是一个东西，老板看混了。这两列落库后看板直接显示「跟的那个价」。
    g2g_base     REAL,       -- 看板「跟价基准」列的价 $/M —— **我方真正在跟的那个价**：
                             --   有 cheapold → cheapold 价（成本兜底前，不受保本抬价影响）；
                             --   无 cheapold → 2026-10-09 起 = 本区 DD373 成本 × 系数（1.30）。
    g2g_base_src TEXT,       -- 上面那个价的来源："G2G·cheapold" / "成本×1.30"（2026-10-09 起）
                             --   （NULL = 该轮没抓到 G2G / 命中 DD373 货源闸没抓）；
                             --   旧快照残留 "G2G·推荐前二"（该口径已于 2026-10-09 废止）
    PRIMARY KEY (ts, key)
);
CREATE INDEX IF NOT EXISTS idx_gold_key ON gold_price(key, ts);

-- ---------------------------------------------------------------------------
-- 金币进货成本（2026-10-02 新增 · AION2 Kinah / DD373 货源）
--
-- ⛔⛔ **这张表是「只读监控」，与 gold_price 完全解耦** ——
--    用户口径原话：「成本价**仅作为监控及参考价值，不干预任何比价及改价写入**」。
--    所以：① 独立成表，绝不加列进 gold_price（那张表是改价链路的输入）；
--          ② 采集器 core_dd373_cost 只读这张表、绝不回写 gold_price；
--          ③ 写价工单的成本除数仍走「目标每M × 汇率×(1−利润率)÷前台系数」，
--             与本表**无关**。
--    改错表 = 直接改错售价；这条边界要守住。
--
-- 口径：DD373 永恒之塔2国际服 · 基纳 · 各区/种族/游戏区 · **综合排序第 1 条**的单价
CREATE TABLE IF NOT EXISTS gold_cost (
    ts          TEXT NOT NULL,
    key         TEXT NOT NULL,       -- 金币.服务区[].key
    game        TEXT,                -- 游戏（AION2）
    cny_per_wan REAL,                -- 进货单价 元/万基纳（用户口径的主数字）
    unit        TEXT,                -- 单位（必须是「万基纳」，否则采集阶段就丢弃）
    usd_per_m   REAL,                -- 折算后 $/M（= cny_per_wan × 100 ÷ 汇率）
    final_usd_m REAL,                -- 改价后最终售价 $/M（由引擎回填，用于算利润率）
    margin      REAL,                -- 利润率 =(final−cost)/final，**可以为负**
    stock       TEXT,                -- 库存（留证：1 条挂单的高价区要能看出来）
    min_buy     TEXT,
    n_items     INTEGER,             -- 该游戏区综合排序下的挂单条数
    dd_area     TEXT,                -- DD373 侧大区（日服/北美西/…）
    dd_race     TEXT,                -- DD373 侧种族（天族/魔族）
    dd_zone     TEXT,                -- DD373 侧游戏区（Siel/Nezekan/…）
    src         TEXT,                -- 固定 'dd373'
    basis       TEXT,                -- 依据（人话可读，鼠标悬停看）
    note        TEXT,                -- 备注 / 无报价原因 / 自校验告警
    url         TEXT,
    ok          INTEGER,             -- 0 = 无报价/被风控/单位异常（本行不算数）
    PRIMARY KEY (ts, key)
);
CREATE INDEX IF NOT EXISTS idx_gold_cost_key ON gold_cost(key, ts);

-- ---------------------------------------------------------------------------
-- 工单执行通道（2026-09-25 建立；2026-09-27 增加「服务器直接执行」）
--
-- 2026-09-27 起新机 IP 已被加入 order.p2pah.cn 白名单（实测同一个 cookie、同一个
-- 受保护页：新机与本机都是 200 / 107017 字节、md5 一致），所以**服务器自己也能
-- 登录后台改价**。工单由 exec_mode 决定谁来干：
--   exec_mode='server' → 服务器容器 p2pah-srv:1 直接执行（默认，见 srv_exec.py）
--   exec_mode='local'  → 派给本机执行器（特例：服务器有问题时人工改派）
-- 老单没有这一列（NULL），一律按 'local' 处理 —— 免得迁移过来的历史单无人认领。
-- 工单全文随单下发（plan_json），执行方无需 scp。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS local_job (
    id           TEXT PRIMARY KEY,
    ts           TEXT,
    kind         TEXT,          -- write（物品）/ writegold（金币）
    title        TEXT,
    plan_path    TEXT,          -- 服务器上的工单文件（留档/取证）
    plan_json    TEXT,          -- 工单全文（本机直接落盘执行）
    status       TEXT,          -- pending / dispatched / done / failed / canceled
    created_at   TEXT,
    claimed_at   TEXT,
    started_at   TEXT,
    finished_at  TEXT,
    attempts     INTEGER DEFAULT 0,
    agent        TEXT,
    actor        TEXT,          -- 触发人（nginx $remote_user）
    exec_mode    TEXT,          -- server / local：由谁执行（2026-09-27）
    result_json  TEXT,
    log          TEXT
);
CREATE INDEX IF NOT EXISTS idx_local_job_st ON local_job(status, ts);

-- ---------------------------------------------------------------------------
-- 金币改价动作台账（2026-10-02 新增 · 看板「改价操作」列的数据源）
--
-- 用户口径：「这一列要写清我方价格调整的变化（如 180$➡️130$）、变化时间、变化幅度」。
-- ⇒ 需要一张**跨轮次**的表：gold_price 是每轮快照（会被覆盖式追加），
--    拿它对比「上轮 vs 本轮」只能看出最近一次；这张表把每次实际变化单独记一行。
--
-- ⛔ 记录时机：**采集时对比上一轮我方前端价**，发现真变了才写。
--    不在「出工单时」写 —— 工单可能没放行、可能执行失败，那时候记就是假账。
--    口径：our_per_m 是**我方前端实际售价**（客户看到的那个），不是后台采购成本。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold_action (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,      -- 变化被发现的时间（= 采集轮 ts）
    key         TEXT NOT NULL,
    game        TEXT,
    old_usd_m   REAL,               -- 变化前的我方售价 $/M
    new_usd_m   REAL,               -- 变化后的我方售价 $/M
    delta       REAL,               -- new − old（$/M）
    delta_pct   REAL,               -- (new/old − 1) × 100
    mode        TEXT,               -- 当时的定价模式
    basis       TEXT                -- 依据（如「DD373 推荐价 $x +5%」）
    -- ⚠ 不能写 PRIMARY KEY (ts,key)：id 已是 INTEGER PRIMARY KEY，
    --   SQLite 会报「more than one primary key」。用 UNIQUE 索引达到同样的
    --   INSERT OR REPLACE 去重效果。
    , UNIQUE (ts, key)
);
CREATE INDEX IF NOT EXISTS idx_gold_action_key ON gold_action(key, ts);

-- 执行器心跳（判断本机在线/离线）
CREATE TABLE IF NOT EXISTS local_agent (
    agent      TEXT PRIMARY KEY,
    last_seen  TEXT,
    last_ip    TEXT,
    running    TEXT
);

-- ---------------------------------------------------------------------------
-- 人工调价保护（2026-09-29）
--
-- 背景：用户策略是「IGGM 改价了我们再改」。但千岛进货价便宜时，他会**先于 IGGM**
-- 手动改我方的价（自主低价抢单）。此时 IGGM 没动，而引擎的「偏差纠偏」闸只看
-- 「我方价 vs 目标价」的差值、**不看这个价是谁改的** ⇒ 把用户的自主定价当成偏差
-- 「拉回」到 IGGM×0.95，而且每轮重复出同一张单（实测 ARC_2772640663 在 10:37:44
-- 与 10:56:05 各出一张一模一样的单）。
--
-- 这张表记「哪一行的现价是人工改的、改的时候 IGGM 是什么价」：
--   · 该行 IGGM 真价 == 记录时那个值（竞品没动）⇒ 保护生效，不出目标价；
--   · IGGM 真价一变（竞品开始动了）⇒ 保护作废，恢复正常跟随。
-- ⚠ 保护**只作用于「偏差纠偏」通道**，不影响「IGGM 变价」与「折扣变更」两个通道
--   —— 否则会退回 09-27 那个「折扣改了标价不重算 ⇒ 前端凭空贵 1/旧折扣−1」的坑。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS manual_override (
    key        TEXT PRIMARY KEY,
    ts         TEXT,     -- 识别到的时刻（我方价快照 ts）
    front      REAL,     -- 人工改后的我方**前端价**（客户实付）
    bid        REAL,     -- 对应标价 = front ÷ 折扣
    iggm_new   REAL,     -- 记录时的 IGGM 本规格真价（含计数）—— 保护的有效期锚点
    disc       REAL,     -- 记录时的折扣
    src        TEXT,     -- 识别来源：diff = 轮间比对自动识别 / manual = 手工登记
    note       TEXT
);
"""


def connect(data_dir):
    os.makedirs(data_dir, exist_ok=True)
    # 2026-10-26：显式等锁时间。库已切 WAL（journal_mode=wal），读者不再被写锁挡住；
    # 但写者之间仍互斥，原来是 python 默认 5s，遇外部长事务就每轮报 database is locked。
    con = sqlite3.connect(os.path.join(data_dir, "iggm_follow.db"), timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=10000")
    except Exception:                            # noqa: BLE001
        pass
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def _migrate(con):
    """轻量迁移：老库补新列（SQLite 没有 IF NOT EXISTS 的 ADD COLUMN）"""
    # 2026-09-26（patch11）：金币「现行采购成本」表。
    # 服务器 IP 进不了 order 后台，采购成本现值只能由本机执行器现场读到后回传
    # （见 app.api_local_result 把「成本回执」落到这张表）。以前没有这张表，
    # gold_price.cost_old 一直没人填（188 行全空）。
    con.execute("CREATE TABLE IF NOT EXISTS gold_state("
                "key TEXT PRIMARY KEY, cost REAL, src TEXT, ts TEXT)")
    want = {"our_price": [("unit_price_usd", "REAL"), ("pack_size", "INTEGER"),
                          # 2026-09-27：前端**实测折扣**（core_front 抓到的 data-discount）。
                          # 用户随时会改折扣，config 里那个值可能滞后；前端那个才是真正
                          # 乘在标价上的折扣，引擎按它反推标价、也按它换算出目标标价。
                          ("front_disc", "REAL")],
            "decisions": [("装量", "INTEGER"), ("suggest", "TEXT")],
            # 竞品折算前的机房原始价，留证用
            # （2026-09-23 起 price_usd 存的是折算后的「客户实付折后价」）
            "iggm_price": [("raw_usd", "REAL")],
            # 2026-09-27：千岛成本改用订单簿深度加权进价（DWC），补口径留证列
            "qd_cost": [("min_buy", "INTEGER"), ("depth", "INTEGER"), ("book_n", "INTEGER"),
                        ("lo_price", "REAL"), ("bulk_share", "REAL"),
                        ("src", "TEXT"), ("note", "TEXT")],
            # 2026-09-27：金币「最大档对照」列（用户口径：金币单位大，用最大的那个
            # 金币选项对照价格变化）+ 成本除数留证（5.054 而不是 5.32 的那个数）。
            "gold_price": [("divisor", "REAL"), ("big_tier", "INTEGER"), ("iggm_big", "REAL"),
                           ("our_big", "REAL"), ("tgt_big", "REAL"), ("below_pct", "REAL"),
                           ("ok", "INTEGER"),
                           # 2026-10-01：AION2 三源（G2G/ELD/IGGM）可见化补列
                           ("src_g2g", "REAL"), ("src_eld", "REAL"), ("src_igmm", "REAL"),
                           ("src_base", "TEXT"), ("src_base_v", "REAL"),
                           ("src_fallb", "TEXT"),
                           # 2026-10-02：改 DD373 加价。竞品最低价/差距转为**纯展示**列，
                           # 另加 DD373 定价基准留证（事后能核对「当时按多少钱算的」）。
                           ("comp_min", "REAL"), ("comp_min_src", "TEXT"),
                           ("gap_comp", "REAL"), ("gap_comp_pct", "REAL"),
                           ("price_mode", "TEXT"),
                           ("price_tier", "INTEGER"), ("src2_g2g", "REAL"),
                           ("dd_ref_usd", "REAL"), ("dd_ref_cny", "REAL"),
                           ("dd_items", "INTEGER"),
                           # 2026-10-09：看板「G2G 跟价基准」列（cheapold 优先口径）补列。
                           ("g2g_base", "REAL"), ("g2g_base_src", "TEXT")]}
    for table, cols in want.items():
        have = {r["name"] for r in con.execute("PRAGMA table_info(%s)" % table)}
        for name, typ in cols:
            if name not in have:
                con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, typ))
    # 2026-09-27：工单加「执行方式」列（server = 服务器直接执行 / local = 本机执行器）。
    # 老库补列后历史行的值是 NULL，取用时一律 COALESCE(exec_mode,'local')。
    _lj_cols = {r["name"] for r in con.execute("PRAGMA table_info(local_job)")}
    if "exec_mode" not in _lj_cols:
        con.execute("ALTER TABLE local_job ADD COLUMN exec_mode TEXT")
    con.commit()


def canon_spec(label):
    parts = [p.strip() for p in str(label or "").split("/")]
    return " / ".join(p for p in parts if p)


# ---------- 写入 ----------
def save_iggm(con, ts, rows):
    data = [(ts, r["goods_no"], r.get("target_key"), r.get("cate_id"), r.get("cate_name"),
             r.get("title"), r.get("unit_price_usd"), r.get("list_price_usd"),
             str(r.get("discount") or ""), r.get("min_num"), r.get("stock"),
             r.get("status"), r.get("sales"), r.get("ig_update_time"), r.get("url"),
             r.get("unit_price_raw_usd"))
            for r in rows if r.get("goods_no")]
    con.executemany(
        "INSERT OR REPLACE INTO iggm_price"
        "(ts,goods_no,target_key,cate_id,cate_name,title,price_usd,list_usd,discount,"
        " min_num,stock,status,sales,ig_update,url,raw_usd)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        data)
    con.commit()
    return len(data)


def save_qd(con, ts, rows):
    data = []
    for r in rows:
        try:
            pr = float(r.get("rmbPrice") or 0) or None
        except (TypeError, ValueError):
            pr = None
        def _n(key, cast):
            try:
                v = cast(r.get(key))
            except (TypeError, ValueError):
                return None
            return v
        data.append((ts, canon_spec(r.get("_spec_label") or r.get("_spec_shown")),
                     str(r.get("spuId")), r.get("spuName"), r.get("typeName"),
                     r.get("rmbPriceUnit"), pr,
                     _n("_book_q", int), _n("_book_depth", int), _n("_book_n", int),
                     _n("_book_lo", float), _n("_book_share", float),
                     r.get("src"), r.get("_book_note")))
    con.executemany(
        "INSERT OR REPLACE INTO qd_cost(ts,spec,spu_id,name,category,unit,price_cny,"
        " min_buy,depth,book_n,lo_price,bulk_share,src,note)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", data)
    con.commit()
    return len(data)


def _fnum(v):
    """安全转 float（拿不到就返回 None）。前端折扣可能是字符串 '90' / 数字 90 / 空。"""
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def save_our(con, ts, rows):
    data = [(ts, r["key"], r.get("title"), r.get("price_usd"), r.get("cost_cny"),
             r.get("game"), r.get("server_zone"), r.get("cate"), r.get("source"),
             r.get("unit_price_usd"), r.get("_pack_size"), _fnum(r.get("_前台折扣")))
            for r in rows]
    con.executemany(
        "INSERT OR REPLACE INTO our_price"
        "(ts,key,title,price_usd,cost_cny,game,server_zone,cate,source,"
        " unit_price_usd,pack_size,front_disc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", data)
    con.commit()
    return len(data)


def save_gold(con, ts, plan):
    """存一轮金币跟价快照。plan = core_gold.build_plan() 的返回（或 {"items":[...]}）"""
    rows = plan.get("items") if isinstance(plan, dict) else plan
    data = []
    for r in (rows or []):
        tiers = r.get("我方档位集合")
        _md = r.get("多源明细") or {}
        data.append((ts, r.get("key"), r.get("中文名"), str(r.get("后台行ID") or ""),
                     str(r.get("前端aid") or ""), str(r.get("iggm_sid") or ""),
                     r.get("IGGM每M"), r.get("IGGM每M_跟价用"), r.get("我方前端每M"),
                     r.get("我方前端档位"),
                     json.dumps(tiers, ensure_ascii=False) if tiers else None,
                     r.get("利润率"), r.get("采购成本_旧"), r.get("采购成本_新"),
                     r.get("差距倍数"), r.get("动作"),
                     (r.get("说明") or r.get("错误")),
                     r.get("成本除数"), r.get("对照档位"), r.get("对照_IGGM真价"),
                     r.get("对照_我方现价"), r.get("对照_我方改后"),
                     r.get("对照_改后低于IGGM"), (1 if r.get("达标") else 0),
                     _md.get("G2G"), _md.get("ELD"), _md.get("IGGM"),
                     (r.get("基准来源") or _md.get("取谁")),
                     r.get("基准价"),
                     _md.get("兜底"),
                     # 2026-10-02：竞品最低价 / 差距（纯展示）+ DD373 定价留证
                     r.get("竞品最低价"), r.get("竞品最低来源"),
                     r.get("差距_对竞品最低"), r.get("差距_对竞品最低_百分比"),
                     r.get("定价模式"), r.get("定价来源级别"), r.get("G2G_USD每M"),
                     r.get("DD373成本_USD每M"), r.get("DD373成本_元每万基纳"),
                     r.get("DD373挂单数"),
                     # 2026-10-09：G2G 跟价基准（cheapold 优先）—— core_gold 在
                     #   g2g_cheapold 分支里已算出「成本兜底前的原竞品价」及来源，
                     #   此前没落库 ⇒ 看板只能拿三源 G2G 顶替 ⇒ 老板看不明白。这里补上。
                     #   其它定价模式（dd373_markup / multisrc / iggm_undercut）没有这两个
                     #   字段 ⇒ 落 NULL，行为与改动前一致。
                     r.get("基准价_原竞品"), r.get("基准来源_原竞品")))
    con.executemany(
        "INSERT OR REPLACE INTO gold_price"
        "(ts,key,title,row_id,aid,iggm_sid,iggm_raw,iggm_per_m,our_per_m,our_tier,"
        " our_tiers,margin_rate,cost_old,cost_target,ratio,action,reason,"
        " divisor,big_tier,iggm_big,our_big,tgt_big,below_pct,ok,"
        " src_g2g,src_eld,src_igmm,src_base,src_base_v,src_fallb,"
        " comp_min,comp_min_src,gap_comp,gap_comp_pct,price_mode,price_tier,src2_g2g,"
        " dd_ref_usd,dd_ref_cny,dd_items,g2g_base,g2g_base_src)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
        "?,?,?,?,?,?,?,?,?,?,?,?,?)", data)
    # ⚠ 上面这串 ? 必须**正好 42 个**（对齐上面 42 个列名）。
    #   2026-10-02 踩过：加了 10 个新列却只补到 39 个 ?，
    #   线上报 "39 values for 40 columns"，而 save_gold 的调用点被 try/except
    #   吞掉，只在日志里留一行「金币抓取失败」—— 整轮白跑、快照不落库。
    #   verify_schema_local.py 的 G 组会静态校验这个数量，别删。
    #   2026-10-09：加 g2g_base / g2g_base_src ⇒ 40 → 42，列名与 ? 各 42，已静态校验。
    con.commit()
    return len(data)


# ---------------------------------------------------------------------------
# 金币改价动作台账（2026-10-02）—— 看板「改价操作」列的数据源
# ---------------------------------------------------------------------------
def gold_action_detect(con, ts, plan, eps=0.0005):
    """对比**上一轮**我方售价，变化超 eps 的记一行 gold_action。

    为什么在采集时记、而不是出工单时记：工单可能没放行 / 执行失败 /
    前端 5~15 分钟才刷新 —— 那时候记下来的「已改价」可能是假的。
    只有**我方前端价真的变了**才算一次真实调价。

    返回 (新增条数, [{key, old, new, delta, delta_pct}...])。
    """
    rows = plan.get("items") if isinstance(plan, dict) else plan
    if not rows:
        return 0, []
    # 上一轮（严格早于本轮 ts）的每 key 售价
    prev = {}
    for r in con.execute(
            "SELECT key, our_per_m FROM gold_price WHERE ts < ?"
            " AND ts=(SELECT MAX(ts) FROM gold_price WHERE ts < ?)", (ts, ts)):
        prev[r["key"]] = r["our_per_m"]
    if not prev:
        return 0, []
    out = []
    for r in rows:
        k = r.get("key")
        new = r.get("我方前端每M")
        old = prev.get(k)
        if k is None or old is None or new is None:
            continue
        try:
            old = float(old)
            new = float(new)
        except (TypeError, ValueError):
            continue
        if not old or abs(new - old) <= eps:
            continue                     # 没变（或变化小于噪声）→ 不记
        _mk = r.get("加价比例") or 0
        out.append({
            "key": k, "old": old, "new": new,
            "delta": round(new - old, 6),
            "delta_pct": round((new / old - 1.0) * 100.0, 3),
            "game": r.get("游戏"),
            "mode": r.get("定价模式"),
            "basis": ("DD373 推荐价 $%s + %.1f%%" % (r.get("DD373成本_USD每M"), _mk * 100)
                      if r.get("定价模式") == "dd373_markup"
                      else "基准 %s $%s" % (r.get("基准来源") or "-", r.get("基准价"))),
        })
    if not out:
        return 0, []
    con.executemany(
        "INSERT OR REPLACE INTO gold_action"
        "(ts,key,game,old_usd_m,new_usd_m,delta,delta_pct,mode,basis)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        [(ts, o["key"], o["game"], o["old"], o["new"], o["delta"],
          o["delta_pct"], o["mode"], o["basis"]) for o in out])
    con.commit()
    return len(out), out


def gold_action_map(con, game=None):
    """每个 key 的**最近一次**调价 → {key: {...}}（看板「改价操作」列）。

    只取最近一条，不要把整段历史灌进页面（那是 showHistory 的活）。
    """
    q = ("SELECT a.* FROM gold_action a JOIN"
         " (SELECT key, MAX(ts) ts FROM gold_action%s GROUP BY key) m"
         " ON a.key=m.key AND a.ts=m.ts" % (" WHERE game=?" if game else ""))
    args = (game,) if game else ()
    out = {}
    for r in con.execute(q, args):
        out[r["key"]] = dict(r)
    return out


# ---------------------------------------------------------------------------
# 2026-10-02 用户要求：改价操作时间必须是「该区最近一次真实执行完成」的时间，
#   售价必须是「已写入后台的真值」，两者都不能滞后。
#
#   为什么不用 gold_action：那张表是**采集时对比上一轮我方售价**写的，
#   记的是「观察到的价格变化」，天生慢一轮，而且采集值本身还叠加了
#   MMOEXP 前端 5~15 分钟的推送延迟 → 页面上「已改价但售价没变」。
#
#   真值来源（都是执行器 srv-exec 写进库的，不是估算）：
#     · gold_state.cost / .ts / .src  ← 执行器回填，src 形如 J2026.../srv-exec
#     · local_job.finished_at          ← 工单实际完成时刻
#   两者结合 = 该区「最后一次改价确实落地」的时间与结果。
# ---------------------------------------------------------------------------
def gold_state_rows(con, game=None):
    """{key: {cost, ts, src}} —— gold_state 全量（执行器回传的真值）。"""
    out = {}
    for r in con.execute("SELECT key,cost,ts,src FROM gold_state"):
        k = r["key"] or ""
        if game and not k.startswith(game + "_"):
            continue
        out[k] = {"cost": r["cost"], "ts": r["ts"], "src": r["src"] or ""}
    return out


def _job_finish_time(con, job_id):
    """工单 id → finished_at（执行完成时刻）。取不到返回 None。"""
    if not job_id:
        return None
    row = con.execute(
        "SELECT finished_at FROM local_job WHERE id=? AND finished_at IS NOT NULL"
        " ORDER BY finished_at DESC LIMIT 1", (job_id,)).fetchone()
    return row["finished_at"] if row else None


def gold_ticket_map(con, game=None, divisor=None):
    """每个 key 的**最近一次已执行改价** → {key: {...}}。

    数据源 = gold_state（执行器回填的后台采购成本真值），时间取工单 finished_at。
    比 gold_action 准：gold_action 慢一轮，gold_ticket_map 是执行完就更新。

    🔴 divisor（成本除数）必须由调用方从 config 经 core_gold.cost_divisor_of 传入。
       **绝不能在这里猜汇率**。事故记录（2026-10-02 23:45）：
         · 旧版写 `SELECT rate FROM gold_price` —— gold_price 表**根本没有 rate 列**，
           sqlite 抛异常被 except 吞掉，静默回退到硬编码 6.65；
         · 6.65 是**后台美元成本口径**的汇率，而「后台采购成本 → 前台每 M 价」
           的真实除数是 divisor（AION2 = 5.32 = 6.65×(1−利润率)÷前台系数，AION2 前台系数=1.0）；
         · 结果页面把 5.04 算成 5.04/6.65 = **0.76**，而 MMOEXP 前台真实价是
           5.04/5.32 = **0.95** —— 假价低 20%，用户看到「前台还是 0.95」。
       两者差异达 25%，绝不能用错。

    返回每项：
        新价    : 前台每 M 价 USD（= 后台采购成本 ÷ divisor，与 MMOEXP 前台一致）
        成本    : 后台采购成本原值
        时间    : 该次执行的 finished_at（不是采集 ts）
        单号    : 工单号，便于对账
    """
    if not divisor:
        raise ValueError("gold_ticket_map 必须显式传入 divisor，"
                         "请用 core_gold.cost_divisor_of(cfg, 利润率, game)")
    divisor = float(divisor)
    out = {}
    for key, st in gold_state_rows(con, game).items():
        # src 形如 J20261002231042/srv-exec → 取工单号
        src = st.get("src") or ""
        job_id = src.split("/")[0] if "/" in src else (src or None)
        fin = _job_finish_time(con, job_id) or st.get("ts")
        try:
            cost = float(st.get("cost"))
        except (TypeError, ValueError):
            continue
        out[key] = {
            "新价": round(cost / divisor, 4) if divisor else None,
            "成本": cost,
            "时间": fin,
            "单号": job_id,
            "src": src,
        }
    return out


def gold_action_history(con, key, limit=20):
    """某个 key 的调价历史（倒序），给「改价操作」列的悬浮提示用。"""
    return [dict(r) for r in con.execute(
        "SELECT * FROM gold_action WHERE key=? ORDER BY ts DESC LIMIT ?",
        (key, int(limit)))]


# ---------------------------------------------------------------------------
# 金币进货成本（DD373）—— 只读监控表，⛔ 与 gold_price / 改价链路无关
# ---------------------------------------------------------------------------
def save_gold_cost(con, ts, costs, final_price_by_key=None, game="AION2"):
    """存一轮金币进货成本。

    costs             : core_dd373_cost.fetch_costs() 的返回 {key: {...}}
    final_price_by_key: {key: 改价后最终售价 $/M}，用来算利润率；没有就传 {}
    ⛔ 本函数**只写 gold_cost**，绝不碰 gold_price —— 成本不参与定价（用户口径）。
    """
    final_price_by_key = final_price_by_key or {}
    data = []
    for key, c in (costs or {}).items():
        cost_usd = c.get("成本_USD每M")
        price = final_price_by_key.get(key)
        margin = None
        # 利润率可以为负 —— 那是真实结论，别截断
        if price and cost_usd:
            margin = (float(price) - float(cost_usd)) / float(price)
        data.append((
            ts, key, game,
            c.get("成本_元每万基纳"), c.get("单位"), cost_usd,
            price, margin,
            c.get("库存"), c.get("起售"), c.get("商品条数"),
            c.get("DD区"), c.get("DD种族"), c.get("DD游戏区"),
            "dd373", c.get("依据"), c.get("备注"), c.get("URL"),
            (1 if c.get("ok") else 0),
        ))
    if not data:
        return 0
    con.executemany(
        "INSERT OR REPLACE INTO gold_cost"
        "(ts,key,game,cny_per_wan,unit,usd_per_m,final_usd_m,margin,"
        " stock,min_buy,n_items,dd_area,dd_race,dd_zone,src,basis,note,url,ok)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", data)
    con.commit()
    return len(data)


def gold_cost_latest(con, game="AION2"):
    """取每个服务区**最新一条**成本记录（面板汇总区用）。"""
    q = ("SELECT c.* FROM gold_cost c JOIN"
         " (SELECT key, MAX(ts) ts FROM gold_cost WHERE game=? GROUP BY key) m"
         " ON c.key=m.key AND c.ts=m.ts")
    return [dict(r) for r in con.execute(q, (game,))]


def gold_cost_prev_ts(con, game="AION2"):
    """上一轮成本快照的时间戳（用于「本轮是否全被风控 ⇒ 沿用旧值」）。"""
    r = con.execute(
        "SELECT MAX(ts) t FROM (SELECT DISTINCT ts FROM gold_cost WHERE game=?"
        " ORDER BY ts DESC LIMIT 2 OFFSET 1)", (game,)).fetchone()
    return (r or {}).get("t")



def gold_state_upsert(con, items, ok=True, src="", ts=None):
    """记「本机执行器现场读到的后台真值」。

    items = {key: {"现行": <现场读到的现值>, "目标": <工单目标>, "行ID": ...}}
    写成功且复核通过时以「目标」为现行值；否则以现场读到的「现行」为准。
    """
    ts = ts or _now()
    n = 0
    for k, v in (items or {}).items():
        if not k or not isinstance(v, dict):
            continue
        try:
            prev = float(v.get("现行"))
        except (TypeError, ValueError):
            prev = None
        try:
            tgt = float(v.get("目标")) if ok else None
        except (TypeError, ValueError):
            tgt = None
        cur = tgt if tgt is not None else prev
        if cur is None:
            continue
        con.execute("INSERT OR REPLACE INTO gold_state(key,cost,src,ts) VALUES(?,?,?,?)",
                    (str(k), cur, src, ts))
        n += 1
    con.commit()
    return n


def gold_state_map(con):
    """{key: 现行采购成本} —— 本机执行器回传过才有；没回传过的 key 不在字典里"""
    try:
        return {r["key"]: r["cost"] for r in con.execute("SELECT key,cost FROM gold_state")}
    except Exception:
        return {}


def add_decision(con, ts, d, applied=0):
    con.execute(
        "INSERT OR REPLACE INTO decisions"
        "(ts,key,title,action,iggm_old,iggm_new,ours_old,ours_new,target_usd,cost_usd,"
        " margin_old,margin_new,mode,applied,reason,装量,suggest) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, d.get("key"), d.get("title"), d.get("action"), d.get("iggm_old"),
         d.get("iggm_new"), d.get("ours_old"), d.get("ours_new"), d.get("target_usd"),
         d.get("cost_usd"), d.get("margin_old"), d.get("margin_new"), d.get("mode"),
         applied, d.get("reason"), d.get("装量"), d.get("suggest")))
    con.commit()


def record_run(con, ts, **kw):
    con.execute(
        "INSERT OR REPLACE INTO runs(ts,iggm_count,qd_count,our_count,follows,blocked,"
        "elapsed_s,mode,note) VALUES (?,?,?,?,?,?,?,?,?)",
        (ts, kw.get("iggm_count"), kw.get("qd_count"), kw.get("our_count"),
         kw.get("follows"), kw.get("blocked"), kw.get("elapsed_s"), kw.get("mode"),
         kw.get("note", "")))
    con.commit()


# ---------- 查询 ----------
def prev_ts(con, table, before_ts):
    r = con.execute("SELECT MAX(ts) t FROM %s WHERE ts < ?" % table, (before_ts,)).fetchone()
    return r["t"] if r and r["t"] else None


def iggm_rows(con, ts):
    return [dict(r) for r in con.execute("SELECT * FROM iggm_price WHERE ts=?", (ts,))]


def iggm_carryover(con, ts):
    """把**所有目标**最近一份行情复制到本轮 ts，保住「每个 ts 都是全量快照」。

    为什么需要它：采集改成「只抓到期的游戏」之后，快照表每轮只剩一部分行 ——
    看板会缺其它游戏、下一轮的「与上轮比价」基线也会断。这里把最近一份行情
    沿用过来补齐。

    🔴 用法（顺序不能反）：
        store.iggm_carryover(con, ts)      # ① 先把上一份全量搬过来（旧值）
        store.save_iggm(con, ts, ig_rows)  # ② 再用本轮真抓到的覆盖（新值）

    先搬、后覆盖，就不需要「排除本轮已抓到的 goods_no」——那要把上千个 goods_no
    塞进 SQL 的 NOT IN，会撞上 SQLite 的变量上限（实测报
    `too many SQL variables`；CentOS 7 自带的老 SQLite 上限是 999）。
    走 idx_ig_goods(goods_no, ts) 索引，按 goods_no 取 MAX(ts) 很快。
    返回搬过来的行数。
    """
    q = ("INSERT OR REPLACE INTO iggm_price "
         "(ts,goods_no,target_key,cate_id,cate_name,title,price_usd,list_usd,discount,"
         " min_num,stock,status,sales,ig_update,url,raw_usd) "
         "SELECT ?, t.goods_no, t.target_key, t.cate_id, t.cate_name, t.title,"
         "       t.price_usd, t.list_usd, t.discount, t.min_num, t.stock, t.status,"
         "       t.sales, t.ig_update, t.url, t.raw_usd "
         "FROM iggm_price t JOIN "
         "  (SELECT goods_no, MAX(ts) mx FROM iggm_price WHERE ts < ? GROUP BY goods_no) m "
         "  ON m.goods_no = t.goods_no AND m.mx = t.ts")
    cur = con.execute(q, (ts, ts))
    con.commit()
    return cur.rowcount


def iggm_history(con, goods_no, limit=500):
    rows = con.execute("SELECT ts,price_usd,list_usd FROM iggm_price WHERE goods_no=? "
                       "ORDER BY ts DESC LIMIT ?", (goods_no, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def gold_rows(con, ts):
    return [dict(r) for r in con.execute("SELECT * FROM gold_price WHERE ts=?", (ts,))]


def gold_latest(con):
    """最近一轮金币快照 → ([rows], ts)；没数据返回 ([], None)"""
    r = con.execute("SELECT MAX(ts) t FROM gold_price").fetchone()
    ts = r["t"] if r else None
    return ([dict(x) for x in con.execute("SELECT * FROM gold_price WHERE ts=?", (ts,))], ts) if ts \
        else ([], None)


def gold_prev_iggm(con, before_ts):
    """上一轮的 IGGM 每M价 → {key: iggm_per_m}（判断竞品是否真变价，与物品口径一致）"""
    ts = prev_ts(con, "gold_price", before_ts)
    if not ts:
        return {}
    return {r["key"]: r["iggm_per_m"]
            for r in con.execute("SELECT key,iggm_per_m FROM gold_price WHERE ts=?", (ts,))}


def our_latest(con):
    ts = con.execute("SELECT MAX(ts) t FROM our_price").fetchone()["t"]
    if not ts:
        return {}, None
    return {r["key"]: dict(r) for r in con.execute("SELECT * FROM our_price WHERE ts=?", (ts,))}, ts


def our_history(con, key, limit=500):
    rows = con.execute("SELECT ts,price_usd FROM our_price WHERE key=? ORDER BY ts DESC LIMIT ?",
                       (key, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# 人工调价保护（2026-09-29，表结构见 SCHEMA 里的 manual_override）
#
# 写入者是 app.detect_manual_override（每轮采集后做一次归因）；
# 读取者是 engine.evaluate（条件B：IGGM 未变价时不出目标价）。
# ---------------------------------------------------------------------------
def manual_override_map(con):
    """{key: {ts, front, bid, iggm_new, disc, src, note}}；表不存在时返回 {}"""
    try:
        return {r["key"]: dict(r)
                for r in con.execute("SELECT * FROM manual_override")}
    except Exception:
        return {}


def manual_override_upsert(con, rows, ts=None):
    """登记 / 更新保护行。rows = [{key, front, bid, iggm_new, disc, src, note}]"""
    ts = ts or _now()
    n = 0
    for r in (rows or []):
        k = r.get("key")
        if not k:
            continue
        con.execute(
            "INSERT OR REPLACE INTO manual_override"
            "(key,ts,front,bid,iggm_new,disc,src,note) VALUES(?,?,?,?,?,?,?,?)",
            (str(k), r.get("ts") or ts, r.get("front"), r.get("bid"),
             r.get("iggm_new"), r.get("disc"), r.get("src") or "diff",
             r.get("note") or ""))
        n += 1
    con.commit()
    return n


def manual_override_clear(con, keys=None):
    """解除保护。keys=None → 全清；否则只清这些 key。返回清除条数。"""
    if keys:
        ks = [str(k) for k in keys]
        cur = con.execute(
            "DELETE FROM manual_override WHERE key IN (%s)" % ",".join("?" * len(ks)), ks)
    else:
        cur = con.execute("DELETE FROM manual_override")
    con.commit()
    return cur.rowcount


def decisions(con, limit=500, days=90):
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    return [dict(r) for r in con.execute(
        "SELECT * FROM decisions WHERE ts>=? ORDER BY ts DESC LIMIT ?", (since, limit))]


def follow_counts(con):
    """近 24h 跟价统计"""
    since = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    r = con.execute(
        "SELECT SUM(action='follow_up') up, SUM(action='follow_down') dn,"
        " SUM(action='blocked') bl, SUM(applied=1) ap, COUNT(*) tot"
        " FROM decisions WHERE ts>=?", (since,)).fetchone()
    return {k: (r[k] or 0) for k in ("up", "dn", "bl", "ap", "tot")}


def purge(con, keep_days):
    cut = (datetime.now() - timedelta(days=keep_days)).isoformat(timespec="seconds")
    for t in ("iggm_price", "qd_cost", "decisions", "runs", "gold_price"):
        con.execute("DELETE FROM %s WHERE ts < ?" % t, (cut,))
    con.commit()


# ---------------------------------------------------------------------------
# 本机执行通道：派单 / 接单 / 回传
#
# ⚠ 并发假设：d4follow 用 `gunicorn -w 1 --threads 16` 起（单进程多线程），
#   所以「先 SELECT 再 UPDATE」之间不会有别的**进程**插进来抢单。
#   若哪天改成 -w >1，必须改成 `UPDATE ... WHERE id=(SELECT ...) AND status='pending'`
#   式原子抢单，否则会重复执行改价。
# ---------------------------------------------------------------------------
LOCAL_KINDS = {"write": "物品改价", "writegold": "金币改价"}


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 工单日志保留（2026-10-22 用户口径：「日志区要能追溯 7 天的改价情况」）
#
# 原来只留最近 **200 单** ⇒ 按每天 50~90 单算只够 2~3 天，10-19 之前的单已被
# 真删掉（不可恢复）。现在改成「按时间留 8 天（JOB_KEEP_DAYS，比 7 天多一天做
# 缓冲）+ 兜底至少留 300 单（防长时间停跑后被清空）」。
# 体积估算：平均 log 6KB、7 天约 500~600 单 ⇒ 3~4MB，对 790MB 的库无感。
# ⚠ 服务器 sqlite 是 3.7.17：只用了 DELETE / 子查询 / LIMIT，没碰窗口函数与 UPSERT。
# ---------------------------------------------------------------------------
JOB_KEEP_DAYS = 8
JOB_KEEP_MIN = 300


def local_job_add(con, kind, title, plan_path, plan, summary="", actor="",
                  exec_mode="server"):
    """把工单派出去。exec_mode='server' → 服务器执行（默认）；'local' → 本机执行器。"""
    base = "J" + datetime.now().strftime("%Y%m%d%H%M%S")
    jid, n = base, 0
    while con.execute("SELECT 1 FROM local_job WHERE id=?", (jid,)).fetchone():
        n += 1
        jid = "%s-%d" % (base, n)
    now = _now()
    _mode = "local" if str(exec_mode).lower() == "local" else "server"
    con.execute(
        "INSERT INTO local_job(id,ts,kind,title,plan_path,plan_json,status,"
        " created_at,attempts,agent,actor,exec_mode,log)"
        " VALUES(?,?,?,?,?,?,'pending',?,0,NULL,?,?,?)",
        (jid, now, kind, title, plan_path,
         json.dumps(plan, ensure_ascii=False), now, actor or "", _mode,
         "%s 派单（%s）：%s" % (now, "服务器执行" if _mode == "server" else "本机执行",
                             summary or title)))
    # 保留期（2026-10-22）：按时间留 8 天，再兜底至少 300 单。
    _cut = (datetime.now() - timedelta(days=JOB_KEEP_DAYS)).isoformat(timespec="seconds")
    con.execute("DELETE FROM local_job WHERE ts < ?", (_cut,))
    con.execute("DELETE FROM local_job WHERE id NOT IN "
                "(SELECT id FROM local_job ORDER BY ts DESC LIMIT %d)" % JOB_KEEP_MIN)
    con.commit()
    return jid


def local_agent_ping(con, agent, ip=""):
    """纯心跳（2026-09-27）：只续 last_seen，**一个字都不碰工单**。

    为什么单独开一个：worker 主循环是「领单 → 阻塞执行 → 回传」，跑一张单要几分钟
    到几十分钟，期间一次都不调 pull ⇒ last_seen 冻住 ⇒ 看板按「>90 秒未报到」判
    「离线」，明明在拼命干活却显示离线。worker 另起一个心跳线程打这里续期即可。
    ⚠ 这里绝不能做超时单回收 —— 否则正在跑的长单会被自己的心跳退回 pending，
      变成重复派单。回收只归 local_agent_touch（真正领单时）管。
    """
    now = _now()
    con.execute("INSERT OR REPLACE INTO local_agent(agent,last_seen,last_ip,running)"
                " VALUES(?,?,?,?)", (agent, now, ip or "", None))
    con.commit()
    return now


def local_agent_touch(con, agent, ip="", running=None, stale_s=600):
    """执行器心跳（领单时调用）。顺手把「派发出去太久还没结果」的单退回 pending。

    ⚠ 2026-09-27 加了一道前提：**只回收「连心跳都断了」的执行器**的单。
      以前只看 claimed_at；一旦 worker 有了独立心跳（跑单期间也续 last_seen），
      一张跑超过 stale_s 的长单就会被自己下一次领单时的 touch 退回 pending
      ⇒ 被重复领取、重复执行。现在改成「该 agent 也没有新鲜心跳了」才回收：
      真死掉的执行器照旧会被回收（行为不变），忙着跑长单的不会被误伤。
    """
    now = _now()
    con.execute("INSERT OR REPLACE INTO local_agent(agent,last_seen,last_ip,running)"
                " VALUES(?,?,?,?)", (agent, now, ip or "", running))
    cut = (datetime.now() - timedelta(seconds=stale_s)).isoformat(timespec="seconds")
    con.execute("UPDATE local_job SET status='pending', agent=NULL, claimed_at=NULL"
                " WHERE status='dispatched' AND claimed_at<?"
                "   AND NOT EXISTS (SELECT 1 FROM local_agent a"
                "                   WHERE a.agent=local_job.agent AND a.last_seen>=?)",
                (cut, cut))
    con.commit()
    return now


def local_job_pull(con, agent, ip=""):
    """本机执行器接单：取最早的、**指定由本机执行**的 pending 单。

    ⚠ 2026-09-27：只取 exec_mode='local' 的单（COALESCE 兜住没有该列值的老单）。
      否则默认交给服务器执行的单会被本机执行器抢走 —— 两边同时改同一件商品。
    """
    local_agent_touch(con, agent, ip)
    r = con.execute("SELECT * FROM local_job WHERE status='pending'"
                    " AND COALESCE(exec_mode,'local')='local'"
                    " ORDER BY ts LIMIT 1").fetchone()
    if not r:
        return None
    now = _now()
    cur = con.execute("UPDATE local_job SET status='dispatched',agent=?,claimed_at=?,"
                      " started_at=?,attempts=attempts+1 WHERE id=? AND status='pending'",
                      (agent, now, now, r["id"]))
    con.commit()
    if not cur.rowcount:
        return None
    d = dict(r)
    d.update({"status": "dispatched", "agent": agent, "claimed_at": now, "started_at": now})
    return d


def local_job_claim_srv(con, agent="srv-exec"):
    """服务器执行器认领一张 **exec_mode='server'** 的 pending 单（原子）。

    认领方式与 local_job_pull 同款：先选候选，再用「带 status 条件的 UPDATE」
    抢；rowcount==0 说明被别人（并发循环 / 本机）先拿走了，返回 None 即可。
    """
    r = con.execute("SELECT * FROM local_job WHERE status='pending'"
                    " AND COALESCE(exec_mode,'local')='server'"
                    " ORDER BY ts LIMIT 1").fetchone()
    if not r:
        return None
    now = _now()
    cur = con.execute("UPDATE local_job SET status='dispatched',agent=?,claimed_at=?,"
                      " started_at=?,attempts=attempts+1 WHERE id=? AND status='pending'",
                      (agent, now, now, r["id"]))
    con.commit()
    if not cur.rowcount:
        return None
    d = dict(r)
    d.update({"status": "dispatched", "agent": agent, "claimed_at": now, "started_at": now})
    return d


def local_job_get(con, jid):
    r = con.execute("SELECT * FROM local_job WHERE id=?", (jid,)).fetchone()
    return dict(r) if r else None


def local_job_reassign(con, jid, mode):
    """把**还没开跑**的单改成用另一种方式执行（server <-> local）。

    只允许 status='pending'：已经在跑的单改 exec_mode 没有意义（人已经接了）。
    返回 True/False 表示是否改动成功。
    """
    mode = "server" if str(mode).lower() == "server" else "local"
    cur = con.execute(
        "UPDATE local_job SET exec_mode=?,"
        " log=coalesce(log,'')||char(10)||?"
        " WHERE id=? AND status='pending'",
        (mode, "%s 人工改派：改由%s执行"
         % (_now(), "服务器" if mode == "server" else "本机"), jid))
    con.commit()
    return bool(cur.rowcount)


def local_job_finish(con, jid, ok, log="", result=None, agent=""):
    now = _now()
    row = con.execute("SELECT log FROM local_job WHERE id=?", (jid,)).fetchone()
    prev = (row["log"] or "") if row else ""
    body = (prev + chr(10) + "--- 执行器输出（" + (agent or "?") + " / " + now + "）---"
            + chr(10) + (log or ""))
    con.execute("UPDATE local_job SET status=?, finished_at=?, log=?, result_json=?"
                " WHERE id=?",
                ("done" if ok else "failed", now, body[-40000:],
                 json.dumps(result, ensure_ascii=False) if result else None, jid))
    con.commit()


def local_job_cancel(con, jid):
    cur = con.execute("UPDATE local_job SET status='canceled', finished_at=?,"
                      " log=coalesce(log,'')||char(10)||'人工取消'"
                      " WHERE id=? AND status IN ('pending','dispatched')", (_now(), jid))
    con.commit()
    return bool(cur.rowcount)


def local_job_list(con, limit=12):
    rows = con.execute(
        "SELECT id,ts,kind,title,plan_path,status,created_at,claimed_at,started_at,"
        " finished_at,attempts,agent,actor,result_json,"
        " coalesce(exec_mode,'local') AS exec_mode,"
        " coalesce(log,'') AS log FROM local_job ORDER BY ts DESC LIMIT ?",
        (limit,)).fetchall()
    return [dict(r) for r in rows]


def local_agent_get(con):
    r = con.execute("SELECT * FROM local_agent ORDER BY last_seen DESC LIMIT 1").fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------------------
# 详细改价日志（2026-10-22）
#
# 背景：看板「④ 执行器」里那张工单表固定只拉 10 条（api/local/jobs?limit=10），
#       用户要看「近 7 天到底改过什么、哪天失败了」必须能翻页 + 按天汇总。
#
# 口径：
#   · 时间一律用 local_job.ts（派单时刻，ISO 'YYYY-MM-DDTHH:MM:SS'，字典序可比）；
#   · date_from / date_to 是页面上的自定义区间（含首含尾），不给就按 days 倒退；
#   · 列表页**不返回全文 log**，只给前 600 字 + 长度 —— 单条详情再取全文，
#     否则一页 50 条 × 6KB 会把页面拖死。
# ---------------------------------------------------------------------------
def _job_error_hint(log):
    """从执行日志里抠一句最有用的失败原因（列表页「失败原因」列）。

    日志尾部才是真死因（Traceback 在最末），所以从后往前找：
    ① 最后一条 Python 异常 `XxxError: msg`；② returncode / 复核不符；
    ③ 都没有就取末行。截到 180 字，避免撑破表格。
    """
    if not log:
        return ""
    lines = [x.strip() for x in str(log).splitlines() if x.strip()]
    if not lines:
        return ""
    tail = lines[-60:]
    for ln in reversed(tail):
        m = re.search(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)):\s*(.+)$", ln)
        if m:
            return ("%s: %s" % (m.group(1), m.group(2)))[:180]
    for ln in reversed(tail):
        if "复核不符" in ln or "returncode" in ln:
            return ln[:180]
    return tail[-1][:180]


def _job_where(days=7, status="", kind="", q="", date_from="", date_to=""):
    """拼 WHERE（参数化）+ 返回参数列表。所有时间比较都是字符串比较。"""
    w, p = [], []
    if date_from:
        w.append("ts >= ?")
        p.append(str(date_from)[:10])
    if date_to:
        # 'YYYY-MM-DD' 直接比会把当天 00:00 之后的判成 > ；用次日零点做开区间上界
        try:
            _d = datetime.strptime(str(date_to)[:10], "%Y-%m-%d") + timedelta(days=1)
            w.append("ts < ?")
            p.append(_d.isoformat(timespec="seconds")[:10])
        except ValueError:
            pass
    if not date_from and not date_to:
        cut = (datetime.now() - timedelta(days=max(1, int(days)))).isoformat(timespec="seconds")
        w.append("ts >= ?")
        p.append(cut)
    sts = [x for x in str(status or "").split(",") if x in
           ("pending", "dispatched", "done", "failed", "canceled")]
    if sts:
        w.append("status IN (%s)" % ",".join("?" * len(sts)))
        p.extend(sts)
    if kind in ("write", "writegold"):
        w.append("kind = ?")
        p.append(kind)
    if q:
        like = "%" + str(q).strip()[:60] + "%"
        w.append("(title LIKE ? OR id LIKE ? OR coalesce(agent,'') LIKE ?)")
        p.extend([like, like, like])
    return (" WHERE " + " AND ".join(w)) if w else "", p


def local_job_history(con, days=7, status="", kind="", q="", page=1, size=50,
                      date_from="", date_to=""):
    """分页 + 筛选 + 按天汇总的改价日志。返回 dict，全部字段 JSON 可序列化。"""
    w, p = _job_where(days, status, kind, q, date_from, date_to)
    try:
        size = max(10, min(200, int(size)))
    except (TypeError, ValueError):
        size = 50
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    total = con.execute("SELECT COUNT(*) FROM local_job" + w, p).fetchone()[0]
    rows = con.execute(
        "SELECT id,ts,kind,title,status,created_at,claimed_at,started_at,finished_at,"
        "       attempts,agent,actor,coalesce(exec_mode,'local') AS exec_mode,"
        "       coalesce(result_json,'') AS result_json,"
        "       substr(coalesce(log,''),1,600) AS log_head,"
        "       substr(coalesce(log,''),-1600) AS log_tail,"
        "       length(coalesce(log,'')) AS log_len"
        "  FROM local_job" + w + " ORDER BY ts DESC LIMIT ? OFFSET ?",
        p + [size, (page - 1) * size]).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        # ⚠ 失败原因必须从**尾部**取：派单日志的开头是 55 个区服的清单，
        #   Traceback 在最后。用 log_head 会把「派单（服务器执行）：Asia · Ariel…」
        #   当成死因（2026-10-22 实测踩过）。
        d["error_hint"] = _job_error_hint(d.pop("log_tail", "")) \
            if d.get("status") == "failed" else ""
        out.append(d)
    # 每日汇总（同口径、不分页）—— 用 GROUP BY 而不是窗口函数（sqlite 3.7.17）
    daily = {}
    for d, st, c in con.execute(
            "SELECT substr(ts,1,10) AS d, status, COUNT(*) FROM local_job" + w +
            " GROUP BY d, status ORDER BY d DESC", p).fetchall():
        row = daily.setdefault(d, {"date": d, "total": 0, "done": 0, "failed": 0,
                                   "canceled": 0, "pending": 0, "dispatched": 0})
        if st in row:
            row[st] = c
        row["total"] += c
    days_list = sorted(daily.values(), key=lambda x: x["date"], reverse=True)
    for r in days_list:
        ok, fin = r["done"], r["done"] + r["failed"]
        r["ok_rate"] = round(100.0 * ok / fin, 1) if fin else None
    sm = {"total": total, "pages": (total + size - 1) // size}
    for st in ("done", "failed", "canceled", "pending", "dispatched"):
        sm[st] = sum(d.get(st, 0) for d in days_list)
    return {"ok": True, "page": page, "size": size, "days": days,
            "date_from": date_from, "date_to": date_to,
            "total": total, "summary": sm, "daily": days_list, "rows": out}



# ─────────────────────────────────────────────────────────────
# 货架漂移自检（2026-10-01，P1：只告警）
# 背景：用户上架 100 装 Crux 并手工定价 $54，被 CRUX_X10 尾随写入覆盖 20+ 次。
#       闸④只保护 config 里存在的 key，对尾随行无感 ⇒ 需独立自检兜住。
# ─────────────────────────────────────────────────────────────
def shelf_drift_save(con, ts, items):
    """存一轮自检结果。items = [{kind,game,key,row_id,front_name,pack_size,detail}]"""
    con.execute("CREATE TABLE IF NOT EXISTS shelf_drift("
                "ts TEXT, kind TEXT, game TEXT, key TEXT, row_id TEXT,"
                "front_name TEXT, pack_size INTEGER, detail TEXT,"
                " PRIMARY KEY(ts, kind, key, row_id, front_name))")
    for r in (items or []):
        con.execute(
            "INSERT OR REPLACE INTO shelf_drift"
            "(ts,kind,game,key,row_id,front_name,pack_size,detail)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (ts, r.get("kind"), r.get("game") or "", r.get("key") or "",
             str(r.get("row_id") or ""), r.get("front_name") or "",
             r.get("pack_size"), r.get("detail") or ""))
    con.execute("DELETE FROM shelf_drift WHERE ts NOT IN "
                "(SELECT ts FROM shelf_drift GROUP BY ts ORDER BY ts DESC LIMIT 30)")
    con.commit()


def shelf_drift_latest(con):
    """最近一轮自检结果 ([dict...], ts)；表不存在 → ([], None)"""
    try:
        r = con.execute("SELECT MAX(ts) t FROM shelf_drift").fetchone()
        ts = r["t"] if r else None
        if not ts:
            return [], None
        return ([dict(x) for x in con.execute(
            "SELECT * FROM shelf_drift WHERE ts=? ORDER BY kind, key, row_id", (ts,))], ts)
    except Exception:
        return [], None


def alert_state_map(con):
    """告警去重状态 {sig: {last_ts, last_detail}}"""
    try:
        return {r["sig"]: dict(r) for r in con.execute("SELECT * FROM alert_state")}
    except Exception:
        return {}


def alert_state_upsert(con, rows):
    """rows = [{sig, last_ts, last_detail}]"""
    con.execute("CREATE TABLE IF NOT EXISTS alert_state("
                "sig TEXT PRIMARY KEY, last_ts TEXT, last_detail TEXT)")
    n = 0
    for r in (rows or []):
        if not r.get("sig"):
            continue
        con.execute("INSERT OR REPLACE INTO alert_state(sig,last_ts,last_detail)"
                    " VALUES(?,?,?)",
                    (str(r["sig"]), r.get("last_ts"), r.get("last_detail") or ""))
        n += 1
    con.commit()
    return n


def alert_state_prune(con, keep_sigs):
    """删掉本轮不再出现的签名（差异消失 ⇒ 下次再出现算「新增」）"""
    try:
        if not keep_sigs:
            con.execute("DELETE FROM alert_state")
        else:
            ks = [str(s) for s in keep_sigs]
            con.execute("DELETE FROM alert_state WHERE sig NOT IN (%s)"
                        % ",".join("?" * len(ks)), ks)
        con.commit()
    except Exception:
        pass
