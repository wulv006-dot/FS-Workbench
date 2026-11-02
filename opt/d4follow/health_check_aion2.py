#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AION2（永恒之塔2）改价系统健康巡检 —— 供自动化任务每 4 小时调用。

设计原则
--------
* **只读为主**：默认不改任何东西。带 `--fix` 才执行小修复。
* **分级**：
    - 小问题（可自修）：服务挂掉、采集轮次停滞、DB 被锁、队列堆积、
                        某个服务区整轮无落库、DD373 成本全空。
    - 大问题（必须人工确认）：定价链级别异常、口径/单位异常、DD373 撞风控、
                             疑似代码 bug（如列数/占位符不匹配）、价格离谱。
* **退出码**：0=全绿；10=只报告；20=已自修；30=发现大问题（需人工）。
* 所有判定都打印**证据**，方便人工复核，不做黑箱结论。

用法：
    python3 health_check_aion2.py            # 只体检
    python3 health_check_aion2.py --fix      # 体检 + 修小问题
    python3 health_check_aion2.py --json     # 机器可读输出
"""

from __future__ import print_function

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

ROOT = "/opt/d4follow"
DB = os.path.join(ROOT, "data", "iggm_follow.db")
SVC = "d4follow"
API = "http://127.0.0.1:8900"
LOGDIR = os.path.join(ROOT, "logs")

# AION2 期望的服务区数（34 个区 × 2 阵营…按实际落库口径，设阈值而非硬等）
MIN_ROWS = 20
# 采集轮次超过这个分钟数没更新就认为停滞
STALL_MIN = 75          # 周期 30min，留 45 分钟冗余
# 队列堆积阈值
QUEUE_WARN = 12
# 售价合理区间（$/M）
PRICE_LO, PRICE_HI = 0.05, 60.0

PROBLEMS = []      # 小问题（可自修）
BIG = []           # 大问题（需人工）
INFO = []


def sh(cmd):
    try:
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        out, _ = p.communicate()
        return p.returncode, (out or b"").decode("utf-8", "ignore")
    except Exception as e:
        return -1, "exec fail: %s" % e


def add_problem(msg):
    PROBLEMS.append(msg)
    print("  [小问题] %s" % msg)


def add_big(msg):
    BIG.append(msg)
    print("  [大问题] %s" % msg)


def add_info(msg):
    INFO.append(msg)
    print("  [信息]   %s" % msg)


# ---------------------------------------------------------------- 1. 服务状态
def check_service(fix=False):
    print("\n[1] 服务状态")
    rc, out = sh("systemctl is-active %s" % SVC)
    state = out.strip()
    if state == "active":
        rc2, out2 = sh("curl -s -o /dev/null -w '%%{http_code}' %s/" % API)
        code = out2.strip()[-3:]
        print("  active · HTTP %s" % code)
        if code != "200":
            add_problem("服务 active 但首页返回 HTTP %s" % code)
            if fix:
                if do_restart("首页 HTTP %s" % code):
                    pass
                else:
                    add_big("重启后仍拿不到 HTTP 200")
        return True
    add_problem("服务状态 = %s（不是 active）" % (state or "空"))
    if fix:
        do_restart("服务 %s" % state)
    return False


def check_health_api():
    """官方健康接口 —— 比 systemctl 更能反映「应用层能不能干活」。"""
    print("\n[1b] 应用健康接口 /api/health")
    rc, out = sh("curl -s %s/api/health" % API)
    if rc != 0 or not out.strip().startswith("{"):
        add_problem("/api/health 不可读（返回：%s）" % (out.strip()[:80] or "空"))
        return
    try:
        d = json.loads(out)
    except Exception:
        add_problem("/api/health 返回非 JSON")
        return
    print("  ok=%s  version=%s  time=%s"
          % (d.get("ok"), d.get("version"), d.get("time")))
    if not d.get("ok"):
        add_problem("/api/health 报 ok=false")


def do_restart(why):
    print("       ↻ 自修：systemctl restart %s（原因：%s）" % (SVC, why))
    rc, out = sh("systemctl restart %s && sleep 4 && systemctl is-active %s"
                 % (SVC, SVC))
    if out.strip().endswith("active"):
        print("       ✔ 已恢复 active")
        return True
    print("       ✘ 重启失败：%s" % out.strip()[:200])
    return False


# ---------------------------------------------------------------- 2. 数据库
def check_db():
    print("\n[2] 数据库")
    if not os.path.exists(DB):
        add_big("数据库不存在：%s" % DB)
        return None
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=15)
        con.row_factory = sqlite3.Row
    except Exception as e:
        add_problem("数据库打不开：%s" % e)
        return None
    try:
        # 完整性 + 是否被锁
        rc, _ = sh("ls -la %s*.wal 2>/dev/null | wc -l" % DB)
        print("  %s（%.1f MB）"
              % (DB, os.path.getsize(DB) / 1048576.0))
        con.execute("SELECT count(*) FROM gold_cost").fetchone()
    except sqlite3.OperationalError as e:
        if "locked" in str(e):
            add_problem("数据库被锁：%s" % e)
        else:
            add_big("数据库查询失败：%s" % e)
        con.close()
        return None
    return con


# ---------------------------------------------------------------- 3. 采集轮次
# ⚠ gold_price 表**没有 game 列**（游戏靠 key 前缀区分，如 AION2_EU_...）。
#    写 WHERE game='AION2' 会直接报 no such column —— 巡检自己先踩过这个坑。
GAME_WHERE = "key LIKE 'AION2_%'"


def check_rounds(con, fix=False):
    print("\n[3] AION2 采集轮次与落库")
    try:
        r = con.execute(
            "SELECT max(ts) t, count(*) n FROM gold_price WHERE %s" % GAME_WHERE
        ).fetchone()
        if not r or not r["t"]:
            add_big("gold_price 里一条 AION2 记录都没有")
            return None
        ts, n = r["t"], r["n"]
        age_min = (time.time() - time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))) / 60.0
        print("  最新轮次 %s（%.1f 分钟前）· 累计 %d 行" % (ts, age_min, n))
        if age_min > STALL_MIN:
            add_problem("采集停滞：最新轮次已 %.0f 分钟没更新（阈值 %d）"
                        % (age_min, STALL_MIN))
        # 最新一轮的级别分布
        rows = con.execute(
            "SELECT price_tier t, count(*) n FROM gold_price "
            "WHERE %s AND ts=? GROUP BY price_tier" % GAME_WHERE, (ts,)
        ).fetchall()
        dist = {str(x["t"]): x["n"] for x in rows}
        print("  最新一轮定价级别分布：%s" % dist)
        t1 = dist.get("1", 0)
        t2 = dist.get("2", 0)
        t3 = dist.get("3", 0)
        tot = t1 + t2 + t3
        if tot < MIN_ROWS:
            add_problem("最新一轮只有 %d 个区落库（阈值 %d）—— 可能整轮采集失败"
                        % (tot, MIN_ROWS))
        if tot and t3 == tot:
            add_big("全部 %d 个区都掉到第 3 级（兜底价）—— "
                    "说明 DD373 与 G2G 双双无数据，需要人工看" % tot)
        elif t3 > 0:
            # ⚠ 第 3 级的实际售价随定价模式而变：dd373_markup=9.9 固定价，
            #    g2g_cheapold=12.99（条数不足）/19.9（无货兜底）。这里直接读真实值，
            #    避免文案与实际价不符（2026-10-21 修复）。
            add_info("第 3 级（兜底价）命中 %d 个区，实际售价分布：%s ｜ 样例：%s"
                     % (t3, tier3_prices(con, ts), tier3_keys(con, ts)))
        if t2 / max(1, tot) > 0.5:
            add_info("超过一半的区在用第 2 级（G2G 兜底）—— DD373 报价覆盖率偏低")
        return ts
    except Exception as e:
        add_big("检查采集轮次失败：%s" % e)
        return None


def tier3_keys(con, ts):
    try:
        return ",".join([r["key"] for r in con.execute(
            "SELECT key FROM gold_price WHERE %s AND ts=? "
            "AND price_tier=3 LIMIT 6" % GAME_WHERE, (ts,))])
    except Exception:
        return "(读不到)"


def tier3_prices(con, ts):
    """第 3 级各区**实际售价**的分布（$/M）—— 不同模式兜底价不同，别写死。"""
    try:
        d = {}
        for r in con.execute(
                "SELECT our_per_m v, count(*) n FROM gold_price "
                "WHERE %s AND ts=? AND price_tier=3 GROUP BY our_per_m" % GAME_WHERE,
                (ts,)):
            if r["v"] is None:
                continue
            d["$%.2f" % r["v"]] = r["n"]
        return ", ".join("%s×%d" % (k, d[k]) for k in sorted(d)) or "(无)"
    except Exception:
        return "(读不到)"


# ---------------------------------------------------------------- 4. 定价链
def check_pricing(con, ts):
    print("\n[4] 定价链与价格合理性")
    if not ts:
        return
    try:
        rows = con.execute(
            "SELECT key, our_per_m, price_tier, comp_min, gap_comp_pct, src_fallb "
            "FROM gold_price WHERE %s AND ts=?" % GAME_WHERE, (ts,)).fetchall()
    except Exception as e:
        add_big("读定价失败：%s" % e)
        return
    bad_price = []
    no_comp = 0
    no_comp_with_fallb = 0
    for r in rows:
        p = r["our_per_m"]
        if p is None:
            continue
        if not (PRICE_LO <= p <= PRICE_HI):
            bad_price.append("%s=$%s" % (r["key"], p))
        if r["comp_min"] is None:
            no_comp += 1
            if r["src_fallb"]:
                no_comp_with_fallb += 1
    print("  有目标价 %d 个区 · 无目标价 %d 个区"
          % (len([r for r in rows if r["our_per_m"] is not None]),
             len([r for r in rows if r["our_per_m"] is None])))
    if bad_price:
        add_big("售价超出合理区间 [%.2f, %.2f] $/M：%s"
                % (PRICE_LO, PRICE_HI, ", ".join(bad_price[:5])))
    # comp_min 为空 ≠ 采集故障：它只让看板的「竞品对比」列空。
    # 判据（经验 #128）：空值区与 src_fallb（同大区均价兜底）区**一一对应** ⇒ 三源本就无数据，
    # 属正常态，不影响定价（core_gold.py 对 comp_min 0 处引用）⇒ 只作信息提示。
    if no_comp > len(rows) * 0.5:
        if no_comp_with_fallb == no_comp:
            add_info("超过一半的区没有竞品最低价（comp_min 为空）—— "
                     "但 %d/%d 个都与同大区均价兜底(src_fallb)一一对应 ⇒ "
                     "三源本就无数据，属正常态，**不影响定价**，仅看板对比列空"
                     % (no_comp_with_fallb, no_comp))
        else:
            add_problem("超过一半的区没有竞品最低价（comp_min 为空）—— "
                        "其中 %d/%d 个有 src_fallb 兜底、%d 个无兜底，"
                        "需查采集侧是否真断供"
                        % (no_comp_with_fallb, no_comp, no_comp - no_comp_with_fallb))

    # ── 利润率下限 15% 是否真的生效（2026-10-21 新增）────────────────────
    #   判据：**用本轮 reason 里的「目标 $X/M」算利润率**，而不是用 gold_price.our_per_m。
    #   our_per_m 是「本轮计划价 / 上轮已落地价」，改价工单还没落地前它仍偏低于目标价，
    #   直接拿它比会误报成「20 个区跌破 15% 下限」（经验 #143 的老疑问）。
    #   正确口径：(目标价 − 真实成本 usd_per_m) ÷ 目标价 ≥ 15%。
    #   ⚠ 目标价在 reason 里**只保留 2~4 位小数**，回算利润率会带 ±0.005%~±0.4% 的
    #   截断误差（正好卡在 15% 线上时会误报）。故按显示位数推算容差：
    #   |Δmargin| ≈ (成本/目标²) × 0.5×10^-decimals。
    #   🔴 2026-10-27 修复永久误报：**货源闸固定价行不吃利润闸**，判据与
    #     core_gold.py 的排除条件保持一致（基准来源 src_base ∈ {无货兜底, 薄区挂单价}）：
    #       · 薄区 $4.99 —— 2026-10-22 老板定案「$4.99/M 是挂单价、不是成本」，
    #         可买量 < 薄区阈值 ⇒ 统一挂 $4.99，本行**不吃**成本兜底、
    #         也**不吃**利润率上下限闸 ⇒ 成本高于 $4.99 时利润率本就是负的，
    #         属**设计内**（例：SA_ARIEL_E 成本 $7.52 挂 $4.99）；
    #       · 无货兜底 $19.9 —— 老板口径「没挂单的统一调 19.9」= 严格统一，
    #         同样不吃成本兜底 / 利润率下限。
    #     这两类按通用 15% 判据核查会**每轮永久误报**（本次即 SA_ARIEL_E）
    #     ⇒ 排除出「跌破下限」计数，另作信息项列出（不隐藏，豁免量透明化）。
    try:
        rr = con.execute(
            "SELECT p.key k, p.our_per_m o, p.reason rs, p.src_base sb, c.usd_per_m cost "
            "FROM gold_price p JOIN gold_cost c ON c.key=p.key AND c.ts=p.ts "
            "WHERE p.key LIKE 'AION2_%%' AND p.ts=? AND c.usd_per_m>0 AND c.ok=1",
            (ts,)).fetchall()
        tgt = re.compile(r"目标\s*\$([0-9.]+)/M")
        # 货源闸固定价：不吃利润闸（与 core_gold.py 排除条件一致）
        GATE_EXEMPT = ("无货兜底", "薄区挂单价")
        n_cmp = 0
        n_exempt = 0
        below_tgt = []
        below_now = 0
        exempt_rows = []
        for x in rr:
            m = tgt.search(x["rs"] or "")
            if not m:
                continue
            n_cmp += 1
            txt = m.group(1)
            t = float(txt)
            if t <= 0:
                continue
            dec = len(txt.split(".")[1]) if "." in txt else 0
            tol = (x["cost"] / (t * t)) * (0.5 * (10 ** -dec))   # 显示截断容差
            mg = (t - x["cost"]) / t
            sb = (x["sb"] or "")
            if sb in GATE_EXEMPT:
                # 固定价行：低利润率是设计内 ⇒ 不计入跌破计数，转信息项
                n_exempt += 1
                exempt_rows.append("%s(%s 目标$%s 成本$%.4f 利润率%.2f%%)"
                                   % (x["k"], sb, txt, x["cost"], mg * 100))
                continue
            if mg < 0.15 - tol:
                below_tgt.append("%s(目标$%s 成本$%.4f 利润率%.2f%%)"
                                 % (x["k"], txt, x["cost"], mg * 100))
            if x["o"] and (x["o"] - x["cost"]) / x["o"] < 0.15:
                below_now += 1
        if n_cmp:
            print("  利润下限核对：可比 %d 区 · 目标价口径跌破 15%% 的 %d 区"
                  " · 现价口径跌破 15%% 的 %d 区（改价工单未落地，属正常）"
                  % (n_cmp, len(below_tgt), below_now))
        if n_exempt:
            # ⚠ 2026-10-29：这两个价会随老板定案变（2026-10-29 已把无货兜底 19.9 → 12.99），
            #   硬编码在文案里必然过时 ⇒ 改成从 config 实时读，读不到就不显示金额。
            _g_thin = _g_park = "?"
            try:
                _cfg0 = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
                _pol0 = ((_cfg0.get("金币") or {}).get("定价策略") or {})
                _g_thin = _pol0.get("薄区挂单价_USD每M") or "?"
                _g_park = _pol0.get("无货兜底售价_USD每M") or "?"
            except Exception:
                pass
            print("  [信息] 货源闸固定价 %d 区（不吃利润闸，不参与 15%% 下限核对）：%s"
                  % (n_exempt, ", ".join(exempt_rows[:5])))
            add_info("货源闸固定价 %d 区不吃利润闸（薄区 $%s / 无货兜底 $%s），"
                     "已排除出 15%% 下限核对" % (n_exempt, _g_thin, _g_park))
        if below_tgt:
            add_problem("有 %d 个区按**目标价**算利润率仍低于 15%% 下限：%s"
                        % (len(below_tgt), ", ".join(below_tgt[:5])))
    except Exception as e:
        add_info("利润下限核对跳过：%s" % e)

    # 第 2 级的口径问题（此前遗留待确认：G2G 加价 2% vs 老板字面「直接用 G2G 价」）
    try:
        cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
        p = (cfg.get("金币") or {}).get("定价策略") or {}
        print("  定价策略：模式=%s 加价=%s 次源=%s 次源利润率=%s 默认=%s"
              % (p.get("模式"), p.get("加价比例"), p.get("次源"),
                 p.get("次源利润率"), p.get("默认售价_USD每M")))
        # ⚠ 2026-10-29 修复永久误报：本行原判据是 `!= "dd373_markup"`，
        #   但**当前实际使用的模式名是 `dd373_only`**（2026-10-06 起）⇒ 每轮都误报
        #   「当前不是 DD373 定价模式」，而实际恰恰就是 DD373 定价（已连续 3 轮误报）。
        #   两个模式名都是「以 DD373 进货成本为基准」，故按白名单判定。
        _DD373_MODES = ("dd373_only", "dd373_markup")
        if p.get("模式") not in _DD373_MODES:
            add_info("当前不是 DD373 定价模式（模式=%s）" % p.get("模式"))
        # ⚠ 次源加价 2% 已于 2026-10-02 由老板拍板保留
        #   （老板原话「直接用 G2G 的价格」，但实现时加了 2% 避免贴竞品打，
        #    询问后确认「就按你说的这样可以」= 保留 2%）。
        #   → 这里只做**一致性核对**，不再每次都提示待确认。
        # ⚠ config 里的键名是「次源利润率」（core_gold.py 同名读取），
        #    不是「次源加价」—— 读错键会永远拿到 None→0.0 → 恒判 ≠0.02（已误报 43 次）。
        #    「次源加价」只存在于 dd373_markup 模式的归档段里。
        sec = float(p.get("次源利润率") or p.get("次源加价") or 0.0)
        if abs(sec - 0.02) < 1e-9:
            print("  第 2 级：G2G × %.2f（已确认保留 +2%%，非待确认项）" % (1 + sec))
        else:
            add_info("第 2 级 G2G 加价 = %.4f（≠0.02）—— "
                     "若要改回 0.02 改 config 的 次源利润率 再 restart" % sec)
    except Exception as e:
        add_problem("读 config.json 的定价策略失败：%s" % e)


# ---------------------------------------------------------------- 5. DD373 成本
def check_dd373(con, fix=False):
    print("\n[5] DD373 进货成本")
    try:
        r = con.execute(
            "SELECT max(ts) t, count(*) n FROM gold_cost WHERE ok=1").fetchone()
        if not r or not r["t"]:
            add_big("gold_cost 里没有任何 ok=1 的成功记录")
            return
        print("  最新成本轮次 %s · 有效 %d 条" % (r["t"], r["n"]))
        # 风控检测
        blk = con.execute(
            "SELECT count(*) n FROM gold_cost WHERE basis LIKE '%风控%' "
            "AND ts=?", (r["t"],)).fetchone()
        if blk and blk["n"] > 0:
            add_big("DD373 最新一轮有 %d 个区撞上风控（滑块页）—— 需要人工处理"
                    % blk["n"])
        # 单位口径 —— 换算错会全盘错价
        # ⚠ 必须按 game='AION2' 过滤：gold_cost 是**多游戏共表**（AION2 + MSCW 等），
        #    MSCW 的单位是「万金」不是「万基纳」。不过滤就会把 MSCW 的正常行
        #    算成 AION2 的口径错 —— 已连续 31 次误报（2026-10-21 修复）。
        #    注：gold_price 无 game 列（靠 key 前缀），但 gold_cost **有** game 列。
        badunit = con.execute(
            "SELECT count(*) n FROM gold_cost WHERE ts=? AND game='AION2' "
            "AND unit IS NOT NULL AND unit NOT LIKE '%%万基纳%%'", (r["t"],)).fetchone()
        if badunit and badunit["n"] > 0:
            add_big("DD373 最新一轮有 %d 条单位不是「万基纳」—— 换算会错，"
                    "本轮成本不可用" % badunit["n"])
        else:
            # 非 AION2 游戏的单位口径不同（MSCW=万金），属正常，只作信息提示
            other = con.execute(
                "SELECT count(*) n FROM gold_cost WHERE ts=? AND game<>'AION2' "
                "AND unit IS NOT NULL AND unit NOT LIKE '%%万基纳%%'",
                (r["t"],)).fetchone()
            if other and other["n"] > 0:
                add_info("另有 %d 条非 AION2 记录用了别的单位口径（如 MSCW=万金）"
                         " —— 不影响 AION2 定价" % other["n"])
        # 最新一轮里 AION2 有效成本条数
        ok = con.execute(
            "SELECT count(*) n FROM gold_cost WHERE ts=? AND ok=1",
            (r["t"],)).fetchone()
        print("  该轮有效报价 %d 条" % (ok["n"] if ok else 0))
        if ok and ok["n"] == 0:
            add_problem("DD373 最新一轮 0 条有效报价")
    except Exception as e:
        add_big("检查 DD373 成本失败：%s" % e)


# ---------------------------------------------------------------- 6. 改价台账
def check_action(con):
    print("\n[6] 改价台账")
    try:
        n = con.execute("SELECT count(*) c FROM gold_action").fetchone()["c"]
        r = con.execute("SELECT max(ts) t FROM gold_action").fetchone()["t"]
        print("  gold_action 累计 %d 条 · 最近 %s" % (n, r))
        last = con.execute(
            "SELECT key, old_usd_m, new_usd_m, delta_pct FROM gold_action "
            "ORDER BY id DESC LIMIT 3").fetchall()
        for x in last:
            print("    %s  $%s ➡️ $%s  %+.2f%%"
                  % (x["key"], x["old_usd_m"], x["new_usd_m"], x["delta_pct"] or 0))
    except Exception as e:
        add_problem("读 gold_action 失败：%s" % e)


# ---------------------------------------------------------------- 7. 队列
def check_queue():
    """⚠ 接口是 `/api/local/jobs`（不是 /api/queue，那个 404），
       字段是 `jobs`，在跑/排队的单 `finished_at` 为 null。"""
    print("\n[7] 工单队列")
    rc, out = sh("curl -s %s/api/local/jobs" % API)
    if rc != 0 or not out.strip().startswith("{"):
        print("  （接口不可读，跳过）")
        return
    try:
        d = json.loads(out)
    except Exception:
        print("  （返回非 JSON，跳过）")
        return
    jobs = d.get("jobs") or []
    pend = [x for x in jobs if not x.get("finished_at")]
    done = len(jobs) - len(pend)
    print("  未完成 %d 张 / 共 %d 张（已完成 %d）" % (len(pend), len(jobs), done))
    for x in pend[:3]:
        print("    %s  kind=%s  创建 %s" % (x.get("id"), x.get("kind"),
                                             x.get("created_at")))
    if len(pend) > QUEUE_WARN:
        add_problem("队列堆积 %d 张未完成单（阈值 %d）—— "
                    "服务器执行器可能掉线或变慢" % (len(pend), QUEUE_WARN))


# ---------------------------------------------------------------- 8. 任务日志
def check_logs():
    print("\n[8] 最近任务日志")
    try:
        fs = sorted([os.path.join(LOGDIR, f) for f in os.listdir(LOGDIR)
                     if f.startswith("task_") and f.endswith(".log")],
                    key=lambda p: os.path.getmtime(p), reverse=True)
        if not fs:
            print("  没有任务日志")
            return
        p = fs[0]
        age = (time.time() - os.path.getmtime(p)) / 60.0
        txt = open(p, "r", encoding="utf-8", errors="ignore").read()
        errs = re.findall(r"^.*(?:Traceback|❌|异常|失败).*$", txt, re.M)
        print("  最新 %s（%.0f 分钟前，%d 行）"
              % (os.path.basename(p), age, txt.count("\n")))
        if errs:
            add_info("最新任务日志有 %d 行报错样例，末条：%s"
                     % (len(errs), errs[-1].strip()[:140]))
        for key in ("Traceback (most recent call last)", "sqlite3.OperationalError",
                    "values for", "no such column", "no such table"):
            if key in txt:
                add_big("任务日志出现严重错误 `%s`（可能是代码 bug）：%s"
                        % (key, [l for l in txt.split("\n") if key in l][0][:140]))
                break
    except Exception as e:
        add_problem("读任务日志失败：%s" % e)


# ---------------------------------------------------------------- 9. 落库完整性
def check_schema(con):
    print("\n[9] 表结构自检（防「加列忘了改 INSERT」）")
    try:
        cols = [r["name"] for r in con.execute("PRAGMA table_info(gold_price)")]
        print("  gold_price %d 列" % len(cols))
        need = ["comp_min", "gap_comp", "price_mode", "price_tier", "src2_g2g"]
        miss = [c for c in need if c not in cols]
        if miss:
            add_big("gold_price 缺列：%s —— 看板会报错，需要改代码" % miss)
        n_act = con.execute(
            "SELECT count(*) c FROM sqlite_master WHERE type='table' "
            "AND name='gold_action'").fetchone()["c"]
        if not n_act:
            add_problem("gold_action 表不存在 —— 改价台账没有数据")
        else:
            print("  gold_action 表存在")
    except Exception as e:
        add_big("表结构自检失败：%s" % e)


# ---------------------------------------------------------------- 汇总
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="自动修小问题")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    a = ap.parse_args()

    print("=" * 70)
    print("AION2 改价系统健康巡检  %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print("目标：%s  DB：%s" % (ROOT, DB))
    print("=" * 70)

    check_service(fix=a.fix)
    check_health_api()
    con = check_db()
    if con is not None:
        ts = check_rounds(con, fix=a.fix)
        check_pricing(con, ts)
        check_dd373(con, fix=a.fix)
        check_action(con)
        check_schema(con)
        con.close()
    check_queue()
    check_logs()

    print("\n" + "=" * 70)
    print("巡检结论：小问题 %d 项，大问题 %d 项" % (len(PROBLEMS), len(BIG)))
    if PROBLEMS and not a.fix:
        print("  → 小问题未修（本次是只读体检）。要自动修请加 --fix")
    if BIG:
        print("  → 有 %d 项**大问题**，需要人工确认后再处理：" % len(BIG))
        for b in BIG:
            print("      · %s" % b)
    else:
        print("  → 无大问题，系统健康。")

    if a.json:
        print(json.dumps({"小问题": PROBLEMS, "大问题": BIG, "信息": INFO},
                         ensure_ascii=False, indent=2))

    if BIG:
        return 30
    if PROBLEMS:
        return 20 if a.fix else 10
    return 0


if __name__ == "__main__":
    sys.exit(main())