# -*- coding: utf-8 -*-
"""RPG 游戏改价系统 · 在线看板与操作台（Flask 单进程）

设计要点
--------
* 所有会动状态的动作（改配置 / 采集 / 模拟 / 改价计划）都走「任务 + 实时日志」，
  前端用 SSE 订阅，过程可见。
* 改配置走白名单 + 类型/范围校验，未知路径一律拒绝，防止把 config.json 写坏。
* 改价是双闸：config 里「系统总开关=开启」且请求带确认短语，两把钥匙都插上才可能真下发；
  没有配置后台账号时，改价任务会明确拒绝而不是瞎猜接口。
* 千岛进货成本由本机（有 Playwright，能过接口签名）抓取后 POST /api/cost 推上来，
  服务器不承担千岛抓取（海外 IP + 无浏览器内核）。
"""
import datetime as dt
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
import uuid

from flask import Flask, Response, jsonify, render_template, request

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import core_front
import core_gold
import core_iggm
import core_qd
import engine
import store
import shelf_check
import shelf_notify
import shelf_patch

# 2026-10-02：DD373 进货成本采集（只读监控，不参与定价）。
# ⛔ 这个模块只写 gold_cost 表，**不碰 gold_price / 不进工单** —— 用户口径：
#   「成本价仅作为监控及参考价值，不干预任何比价及改价写入」。
#   放在 try 里导入：DD373 被墙/改版时不该让整个改价系统起不来。
try:
    import core_dd373_cost
except Exception:                                        # pragma: no cover
    core_dd373_cost = None

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.config["TEMPLATES_AUTO_RELOAD"] = True

CFG_PATH = os.path.join(ROOT, "config.json")
DATA_DIR = os.path.join(ROOT, "data")
LOG_DIR = os.path.join(ROOT, "logs")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

VERSION = "1.1"

DISC_STATE_PATH = os.path.join(DATA_DIR, "disc_state.json")


def _usd(v):
    """None 不要显示成 $0.0000（会被误读成「竞品零元」），统一显示 --"""
    return "--" if v is None else "$%.4f" % float(v)


# ==================================================== 后台折扣（动态跟随）
# 2026-09-27 用户要求：「我取消了 10% 折扣……我经常会修改物品的折扣，
# 你需要根据是否有折扣来修改对应的价格」。
#
# 折扣一改，标价必须跟着重算（后端标价 = 目标前端价 ÷ 当前折扣）。但引擎的评估闸是
# 「只在 IGGM 本轮真变价时才评估」，折扣改了而 IGGM 没动 ⇒ 一条目标价都不出 ⇒
# 库里那份「按旧折扣算出来」的标价原样留着，前端价凭空贵 1/旧折扣 − 1（9 折→原价 = +11.1%）。
# 所以这里落一个「上一轮各游戏生效的折扣」状态文件，供引擎判断「折扣是否刚变过」。


def _disc_load_state():
    try:
        with open(DISC_STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _disc_save_state(cur):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = DISC_STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=1)
        os.replace(tmp, DISC_STATE_PATH)
    except Exception:
        pass


def disc_now_map(cfg, our_map=None, log=None):
    """{游戏: **实际生效**的后台折扣(百分数, 100 = 不打折)} —— 前端实测优先，config 兜底。

    🔴 必须以前端实测为准：config 里那个数是「我们以为的折扣」，用户随时会改后台折扣，
       改完 config 不会跟着变 ⇒ 按 config 比价格会**系统性算错**。
       实测（2026-09-27，`probe_front_disc.py` 直读前端 data-discount）：
         ARC Raiders = 90、Dark and Darker = 100、WoW Forever = 100、
         POE2 = 100、WarDogs = 100（与 config 一致）；
         D4 走 `to_our_rows`，原先该路径没带折扣字段 ⇒ 补上后才有值。
       ⚠ 注意：ARC「前端价比目标高 11.1%」**不是**折扣问题（前端实测就是 90，与 config 同），
         而是**读错了接口字段**：`/ajax/goods` 的 `unit_price` 是**折前标价**、`price` 才是
         折后前端价（实测 587 条 `price = unit_price × discount/100` 全部吻合）。
         旧代码取 `unit_price` 当前端价、引擎再 `÷0.9` ⇒ 0.81 双重折扣 ⇒ 前端价虚高 11.1%。
         已于 2026-09-27 修在 `core_front.fetch_multi_game` / `to_multi_rows`（改用
         `front_price`），与折扣动态化无关。详见本轮执行报告。
    取法：同一游戏下所有读到实测折扣的商品，取**出现次数最多的那个值**（众数）。
    """
    per = {}
    conf = {}
    for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
        g = it.get("游戏") or engine.default_game(cfg)
        conf.setdefault(g, round(engine.disc_of(cfg, it) * 100.0, 6))
        fd = (our_map or {}).get(it["key"]) or {}
        try:
            v = engine.front_disc_of(fd)
            if v is not None and float(v) > 0:
                per.setdefault(g, {})
                per[g][round(float(v), 6)] = per[g].get(round(float(v), 6), 0) + 1
        except (TypeError, ValueError):
            pass
    out = {}
    for g, c in conf.items():
        d = per.get(g) or {}
        if d:
            v = max(d.items(), key=lambda x: x[1])[0]
            out[g] = v
            if log and abs(v - c) > 1e-9:
                log("  ⚠ %s 的前端实测折扣 = %.1f%%，config 里写的是 %.1f%% —— **以前端为准**"
                    % (g, v, c))
        else:
            out[g] = c
    return out


def disc_changed_games(cfg, our_map=None, log=None):
    """返回「本轮要按折扣重算标价」的游戏集合，并把状态写回。

    状态结构（data/disc_state.json）：{"暗黑破坏神4": {"disc": 100.0, "pending": true}}

    · 折扣与上一轮不同          → 触发（用户刚改了折扣）
    · 状态里没有这个游戏        → 触发（首次建立基线；也兜住「折扣早就改过、
                                  但这个状态文件是本轮才加的」这种情况）
    · 上一轮触发过、还没改完    → **pending 继续触发**（关键！）

    ★ 为什么要 pending 这个闩
      引擎的决策是按「快照 ts」整批写进 decisions，派单只认**最新那份快照**。
      如果只在「折扣刚变」的那一轮出目标价，而那一轮没派单（自动跟价关着 / 出单失败），
      下一轮采集就会用「IGGM 没变价 → hold」把同一批商品覆盖成 hold —— 修正凭空消失。
      所以只要还有商品没改到位，就保持 pending，一直重出目标价，直到全部对齐为止。
    """
    prev = _disc_load_state()
    now = disc_now_map(cfg, our_map=our_map, log=log)
    changed = set()
    for g, v in now.items():
        st = prev.get(g)
        if not isinstance(st, dict):
            # 兼容极老格式（直接存数字）
            old_d = st if isinstance(st, (int, float)) else None
            changed.add(g)
            if log:
                log("  ★ 后台折扣%s：%s %s → %.1f%% ⇒ 本轮该游戏的标价按**当前折扣**重算"
                    % ("首次登记基线" if old_d is None else "有变化", g,
                       "—" if old_d is None else "%.1f%%" % float(old_d), float(v)))
            continue
        if abs(float(st.get("disc") or 0) - float(v)) > 1e-9:
            changed.add(g)
            if log:
                log("  ★ 后台折扣有变化：%s %.1f%% → %.1f%% ⇒ 本轮该游戏的标价按**当前折扣**重算"
                    % (g, float(st.get("disc") or 0), float(v)))
        elif st.get("pending"):
            changed.add(g)
            if log:
                log("  ↻ 折扣重算尚未收尾：%s 仍在按 %.1f%% 重出目标价（直至全部对齐）"
                    % (g, float(v)))
    _st = {}
    for g, v in now.items():
        _p = prev.get(g) if isinstance(prev.get(g), dict) else {}
        _st[g] = {"disc": float(v), "pending": bool(_p.get("pending")),
                  "left": int(_p.get("left") or 0), "stall": int(_p.get("stall") or 0)}
    _disc_save_state(_st)
    return changed


def detect_manual_override(cfg, con, ts, log=None):
    """轮间归因：把「我方价变了、但**说不清是系统改的**」的行登记为**人工调价保护**。

    用户策略是「IGGM 改价了我们再改」，但千岛进货价便宜时他会先于 IGGM 手动改价。
    引擎的偏差纠偏闸只看差值、不看是谁改的 ⇒ 会把自主定价当偏差拉回（且每轮重复出单）。
    这里每轮采集后做一次归因，把「人工改的」那些行标出来，交给引擎（条件B）挡住：

      · 我方价**对得上系统最后一次要求的价格**（工单 items[].front_new）⇒ 系统改的，跳过；
      · 对不上 ⇒ 人工改的 ⇒ 登记进 manual_override。

    ⚠ 判据必须按**值**比对，不能按时间窗（实测 ARC_2772640663 的改价 04:58 成功、
      前台 10:56 才刷出来，差了 6 小时）。容差取 max(1e-4, 1%)：前台展示价可能被
      后台四舍五入，而 1% 以内的偏差本来就在纠偏阈值（5%）之内、不影响任何决策。

    返回 {"新增", "已保护", "解除"}
    """
    def _lg(m):
        if log:
            log(m)

    _ts_now = con.execute("SELECT MAX(ts) t FROM our_price").fetchone()["t"]
    _ts_prev = store.prev_ts(con, "our_price", _ts_now) if _ts_now else None
    if not _ts_prev:
        _lg("  [人工保护] 我方价还没有上一份快照，本轮先建基线（不归因）")
        return {"新增": 0, "已保护": 0, "解除": 0}
    now_rows = {r["key"]: dict(r) for r in con.execute(
        "SELECT * FROM our_price WHERE ts=?", (_ts_now,))}
    prv_rows = {r["key"]: dict(r) for r in con.execute(
        "SELECT * FROM our_price WHERE ts=?", (_ts_prev,))}

    # 系统工单账本：近 24h 内**执行成功**的 write 单，收集「系统要求前台显示什么价」。
    #
    # ⚠ 判据是**按值比对**，不是按时间窗 —— 这是实测踩出来的：
    #   ARC_2772640663（Familiar Duck）04:58:53 改价成功（单里 front_new = 0.21474），
    #   但前台直到 10:56 的快照才刷出这个值（**差了 6 小时**，中间 5 轮采集一直读到旧价
    #   0.45，引擎因此每轮重复出同一张单）。纯时间窗要么漏判、要么得开到 24h 那么大。
    #   改成「我方现价 ≈ 系统最后一次要求的价格 ⇒ 系统改的；对不上 ⇒ 人工改的」后，
    #   完全不受生效延迟影响。
    #   （代价不对称，所以偏向「归因给系统」：把人工当系统 → 引擎又把自主定价拉回去，
    #     正是要修的 bug；把系统当人工 → 该行暂停跟随，IGGM 一动就自愈，属良性。
    #     何况真正被人工**降价**的情形由条件A「只降不升」无条件兜住，不依赖这里。）
    _cut = (dt.datetime.now() - dt.timedelta(hours=24)).isoformat(timespec="seconds")
    sys_front = {}          # key -> 系统最后一次要求的前台价（越晚的单覆盖越早）
    done = set()            # 时间窗内被系统单覆盖过的 key（老单没有价格字段时的兜底）
    try:
        for r in con.execute(
                "SELECT plan_json FROM local_job WHERE kind='write' AND status='done'"
                " AND COALESCE(finished_at,created_at)>=?"
                " ORDER BY COALESCE(finished_at,created_at)", (_cut,)):
            try:
                _d = json.loads(r["plan_json"] or "{}")
            except Exception:
                continue
            for x in (_d.get("items") or []):
                _k = x.get("key")
                if not _k:
                    continue
                done.add(str(_k))
                _v = x.get("front_new")
                if _v is None:
                    _v = x.get("new")
                if _v is None:
                    continue
                try:
                    sys_front[str(_k)] = float(_v)
                except (TypeError, ValueError):
                    pass
    except Exception as e:
        _lg("  ⚠ [人工保护] 读工单账本失败（本轮跳过归因）：%r" % e)
        return {"新增": 0, "已保护": 0, "解除": 0}

    def _is_sys_price(price, key):
        """我方这个价是否「跟系统最后一次要求的一致」"""
        _sp = sys_front.get(key)
        if _sp is not None:
            try:
                _pv = float(price)
            except (TypeError, ValueError):
                return False
            return abs(_pv - _sp) <= max(1e-4, 0.01 * abs(_sp))
        return key in done          # 老单没有价格字段 → 退回时间窗兜底

    it_map = {it.get("key"): it for it in (cfg.get("商品映射", {}).get("对照项") or [])}
    ig_ts = latest_ts(con, "iggm_price")
    ig_map = {r["goods_no"]: r for r in (store.iggm_rows(con, ig_ts) if ig_ts else [])}

    def _ign_of(k):
        """该 key 当前 IGGM 本规格真价（含计数）；抓不到 → None"""
        it = it_map.get(k) or {}
        gn = str((it.get("iggm") or {}).get("goods_no") or "")
        row = ig_map.get(gn) or {}
        try:
            if row.get("price_usd") is None:
                return None
            return float(row["price_usd"]) * float(engine.units_of(it) or 1)
        except (TypeError, ValueError):
            return None

    mo = store.manual_override_map(con)
    add, added, rel = [], [], []
    for k, cur in now_rows.items():
        prv = prv_rows.get(k)
        if not prv:
            continue
        _p0, _p1 = prv.get("price_usd"), cur.get("price_usd")
        if _p0 is None or _p1 is None:
            continue
        try:
            if abs(float(_p1) - float(_p0)) <= 1e-9:
                continue                      # 我方价没变 → 与归因无关
        except (TypeError, ValueError):
            continue
        if _is_sys_price(_p1, k):
            continue                          # 现价 = 系统要求的价格 → 系统改的，不算人工

        # ★ 老保护已经在场时：IGGM 若已变价，必须**解除**、不能重新锚定。
        #   否则每轮归因都会把锚点刷成最新的 IGGM 价 ⇒ 保护永远解不开，
        #   而「IGGM 改价了我们再改」恰恰要求 IGGM 一动就跟。
        #   （单测 test_detect.py 用例 D 就是抓的这个 bug。）
        _old_mo = mo.get(k)
        if _old_mo is not None:
            try:
                _a = float(_old_mo.get("iggm_new")) \
                    if _old_mo.get("iggm_new") is not None else None
            except (TypeError, ValueError):
                _a = None
            _cur_ig = _ign_of(k)
            if _a is not None and _cur_ig is not None \
                    and abs(_cur_ig - _a) > max(1e-9, abs(_a) * 1e-6):
                rel.append(k)
                continue                      # IGGM 变过 → 作废保护，按正常跟价走

        it = it_map.get(k) or {}
        _disc = None
        try:
            _fd = engine.front_disc_of(cur)
            if _fd is not None and float(_fd) > 0:
                _disc = float(_fd) / 100.0
        except (TypeError, ValueError):
            _disc = None
        if _disc is None:
            try:
                _disc = float(engine.disc_of(cfg, it) or 1.0)
            except (TypeError, ValueError):
                _disc = 1.0
        add.append({"key": k, "ts": _ts_now, "front": float(_p1),
                    "bid": (float(_p1) / _disc) if _disc else None,
                    "iggm_new": _ign_of(k), "disc": _disc, "src": "diff",
                    "note": "轮间比对：我方前端价 $%s → $%s（上轮快照 %s 无对应系统工单）"
                            % (_p0, _p1, _ts_prev)})
        added.append(k)

    # 已不满足保护条件的行（IGGM 已变价 / 登记时没基线而现在有了）→ 顺手清掉留痕；
    # 引擎（条件B）本来也会放行，这里清理是为了让保护表不积压、页面口径干净。
    for k, v in (mo or {}).items():
        if k in added or k in rel:
            continue
        try:
            _ref = float(v.get("iggm_new")) if v.get("iggm_new") is not None else None
        except (TypeError, ValueError):
            _ref = None
        _cur = _ign_of(k)
        if _ref is None:
            # 登记时没基线：现在能抓到 IGGM 了 ⇒ 基线可用，释放
            if _cur is not None:
                rel.append(k)
        elif _cur is not None and abs(_cur - _ref) > max(1e-9, abs(_ref) * 1e-6):
            rel.append(k)
    if rel:
        store.manual_override_clear(con, rel)
    if add:
        store.manual_override_upsert(con, add)

    def _short(ks):
        return "、".join(ks[:8]) + ("…等 %d 行" % len(ks) if len(ks) > 8 else "")

    if added:
        _lg("  ⏸ [人工保护] 识别到 %d 行人工改价 → 进入保护（IGGM 未变价前不跟）：%s"
            % (len(added), _short(added)))
    if rel:
        _lg("  ▶ [人工保护] 解除 %d 行（IGGM 已变价 → 恢复正常跟随）：%s"
            % (len(rel), _short(rel)))
    return {"新增": len(added), "已保护": len(store.manual_override_map(con) or {}),
            "解除": len(rel)}


def line_pending_map(cfg, con, log=None):
    """「按行 pending 闩」数据源：{key: {bid_new, front_new, ts, job, status, age_h}}

    事实来源 = **工单账本本身**（local_job），不另建表、不写状态文件
    （和上面的 `detect_manual_override` 一样直接从账本推导，天然幂等、不会与账本脱节）。

    ★ 要解决的问题（2026-09-29 用户提出）
    ------------------------------------
    前台生效有延迟，实测 ARC_2772640663（Familiar Duck）的单 04:58:53 就执行成功，
    前台直到 10:56 才刷出来（**差 5 小时 57 分**）。这段时间里每轮采集读到的都是旧价
    ⇒ 引擎发现「我方价 ≠ 目标价」⇒ 又出一张内容**完全相同**的单
    （实测 10:37:44、10:56:05 各一张）。
    `_auto_dispatch` 里那道「同类任务已有 pending/dispatched 的单时本轮跳过」只挡得住
    **还没跑完**的单，挡不住这种「单已 done、前台没跟上」的情形。

    ★ 交给引擎怎么用（见 engine.evaluate 里「按行 pending 闩」段）
      · 单要求的目标标价（items[].new）== 本轮算出的目标标价 ⇒ 不是新变化；
      · 我方现价还没到那个标价 ⇒ 前台还没生效；
      两条同时成立 ⇒ 该行不出单，等前台自己刷出来。
      一旦 IGGM 再变价 / 折扣再变，目标价随之改变 ⇒ 闩自动让路（不挡正常跟价）。

    ★ 取数口径
      · 只认 `保留小时`（config 跟价.按行pending.保留小时，默认 8）内**创建**的单；
        实测最长延迟 5h57m，取 8 小时留余量。过期单不进表 ⇒ 不再拦（兜底）。
      · 只认 `kind='write'`（物品单）。金币单（writegold）的 items 是「采购成本」口径
        （没有 new/front_new），不参与本闩。
      · 状态取 pending / dispatched / done：**failed / canceled 不算**
        （单都没改成功，我方价没动，不拦是合理的）。
      · 同一个 key 出现在多张单里 → 以**最新**那张为准（rows 按 created_at 升序，后者覆盖）。
    """
    try:
        _lp_cfg = (cfg.get("跟价") or {}).get("按行pending") or {}
        # ⚠ 不能写 `float(x or 8)`：值是 0（= 关闭本闩）时会被默认值吃掉。
        _v = _lp_cfg.get("保留小时", 8)
        keep_h = 8.0 if _v is None else float(_v)
    except (TypeError, ValueError, AttributeError):
        keep_h = 8.0
    if keep_h <= 0:
        return {}
    _cut = (dt.datetime.now() - dt.timedelta(hours=keep_h)).isoformat(timespec="seconds")
    out = {}
    try:
        rows = con.execute(
            "SELECT id,status,created_at,plan_json FROM local_job"
            " WHERE kind='write' AND status IN ('pending','dispatched','done')"
            " AND created_at>=? ORDER BY created_at", (_cut,)).fetchall()
    except Exception as e:
        if log:
            log("  ⚠ [按行闩] 读工单账本失败（本轮不做按行拦截，不影响跟价）：%r" % e)
        return {}
    for r in rows:
        try:
            _d = json.loads(r["plan_json"] or "{}")
        except Exception:
            continue
        for x in (_d.get("items") or []):
            _k = x.get("key")
            _b = x.get("new")
            if not _k or _b is None:
                continue
            try:
                _bid = float(_b)
            except (TypeError, ValueError):
                continue
            _f = x.get("front_new")
            try:
                _fr = float(_f) if _f is not None else None
            except (TypeError, ValueError):
                _fr = None
            try:
                _age = (dt.datetime.now()
                        - dt.datetime.fromisoformat(str(r["created_at"]))
                        ).total_seconds() / 3600.0
            except Exception:
                _age = None
            out[str(_k)] = {"bid_new": _bid, "front_new": _fr,
                            "ts": r["created_at"], "job": r["id"],
                            "status": r["status"],
                            "age_h": (round(_age, 2) if _age is not None else -1.0)}
    return out


def disc_settle(cfg, decisions, changed, our_map=None, log=None):
    """一轮评估跑完后更新 pending 闩。

    还在出目标价（follow_up / follow_down）的游戏 → pending 保持 True，下一轮继续重算；
    已经全部对齐（只剩 hold）→ 清除 pending，不再触发。

    ★ 2026-09-27 加「防自激」兜底
    ----------------------------
    实测踩过这个坑：只要**任何一行**在「折扣变更」通道下持续出 follow_*，pending 就
    永远收不了尾 ⇒ 下一个整点又把整局商品当「折扣变了」重算一遍 ⇒ 每小时重写 677 条
    （其中 634 条 |Δ标价| ≤ $0.0001，纯属取整噪声，每轮却要跑约 8 小时的写价作业）。
    治本靠引擎侧的「最小变动闸」（噪声行变 hold，pending 自然归零）；
    这里再加一道兜底：**连续 3 轮待改行数一点没减少**就强行解除 pending，
    并记 `stall` 计数留痕 —— 宁可少触发一轮，也不能让闩自激烧一晚上。
    """
    if not changed:
        return
    prev = _disc_load_state()
    now = disc_now_map(cfg, our_map=our_map)
    left = {}          # 游戏 -> 本轮仍要改价的行数
    for d in decisions or []:
        # 「⏸ 已出单待前台生效」（被按行 pending 闩拦下的行）也算**尚未收尾**。
        # 这个闩的存在意义就是「一直重出目标价、直到全部对齐」；现在「重出」被按行闩
        # 接管了，那就得让 pending 保持到闩解除 —— 否则一旦那张单失败 / 迟迟不生效，
        # 折扣重算通道下一轮就不再触发，这笔重算就悄悄丢了。
        _wait = bool(d.get("_待前台生效"))
        if d.get("trigger") != "折扣变更" and not _wait:
            continue
        if d.get("action") in ("follow_up", "follow_down") or _wait:
            g = d.get("游戏") or engine.default_game(cfg)
            if g in changed:
                left[g] = left.get(g, 0) + 1
    st = {}
    for g, v in now.items():
        _p = prev.get(g) if isinstance(prev.get(g), dict) else {}
        n = left.get(g, 0)
        keep = n > 0
        stall = int(_p.get("stall") or 0)
        if keep:
            stall = stall + 1 if n == int(_p.get("left") or -1) else 0
            if stall >= 3:
                keep, stall = False, 0
                if log:
                    log("  ⚠ %s 的「折扣变更」重算连续 3 轮待改行数不降（仍 %d 行）"
                        "⇒ 解除 pending 闩（防自激）。这些行下轮起只看 IGGM 变价 / 偏差纠偏通道。"
                        % (g, n))
        else:
            stall = 0
        st[g] = {"disc": float(v), "pending": keep, "left": n, "stall": stall}
    _disc_save_state(st)


def disc_of_key(cfg, our_map, key, key2it=None):
    """某一行的**实际生效折扣**：前端实测值优先，其次 config（engine.disc_of）。

    前端接口每条商品都带 discount（core_front 存进 our_price.front_disc），那才是
    真正乘在标价上的折扣；config 里那个值是人写进去的，可能滞后。
    """
    row = (our_map or {}).get(key) or {}
    try:
        fd = engine.front_disc_of(row)
        if fd is not None and float(fd) > 0:
            return float(fd) / 100.0
    except (TypeError, ValueError):
        pass
    it = (key2it or {}).get(key) or {}
    return engine.disc_of(cfg, it)


# ============================================================ 配置读写

CFG_LOCK = threading.RLock()


# ============================================================ 采集周期（每游戏）
# 用户要求（2026-09-28）：每个游戏一个「查价 + 改价」周期，可选 1 / 3 / 6 / 12 / 24 小时，
# 页面上手动选、点保存写回服务器 config.json。
# 默认：暗黑破坏神4 / 流放之路2 = 1 小时（用户指定），其余游戏 = 6 小时。
# 定时器（d4follow-collect.timer）仍**每小时**触发一次 —— 它只是心跳，
# 真正跑不跑由 due_games() 按每个游戏的周期决定：没到期的游戏不抓价、不算价、不改价。
SCHED_PATH = os.path.join(ROOT, "data", "collect_schedule.json")
SCHED_CHOICES = [0.25, 0.5, 1, 3, 6, 12, 24]    # 允许的周期档位（小时）
# 2026-10-02 用户要求：AION2 金币采集+监控改 30 分钟一轮 → 加 0.5h 档。
# ⚠ 心跳 d4follow-collect.timer 已是 15min（OnUnitActiveSec=15min），
#   所以 0.5h 能被真正等到；心跳比它细，不会漏触发。
SCHED_FAST = ("暗黑破坏神4", "流放之路2")   # 默认 1 小时的那几个
SCHED_DEFAULT_SLOW = 6                   # 其余游戏默认 6 小时
SCHED_TOLERANCE_S = 300                  # 定时器抖动容差：距到期 5 分钟内也算到期


def _sched_load():
    try:
        with open(SCHED_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _sched_save(d):
    try:
        os.makedirs(os.path.dirname(SCHED_PATH), exist_ok=True)
        tmp = SCHED_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, SCHED_PATH)
        return True
    except Exception:
        return False


def track_games(cfg):
    """需要跟踪周期的游戏 = 「游戏顺序」里**真的配了对照项**的那些。

    游戏字典里还有 VALORANT 这类「预留」项（只有占位、没有对照项），不参与调度。
    """
    have = []
    for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
        g = it.get("游戏")
        if g and g not in have:
            have.append(g)
    # 2026-10-01：金币专线的游戏也要跟周期。
    #   金币服务区（config.金币.服务区[].游戏）不一定有对照项 —— AION2 就是
    #   纯金币游戏（0 条对照项），不并入的话它永远不在 due 里，
    #   config 里给它配的 0.25h（15 分钟）就白配了（会跟着暗黑4 的 1h 跑）。
    try:
        import core_gold as _cg
        for _g in _cg.game_names(cfg):
            if _g and _g not in have:
                have.append(_g)
    except Exception:
        pass
    order = ((cfg.get("商品映射") or {}).get("游戏顺序") or [])
    out = [g for g in order if g in have]
    for g in have:
        if g not in out:
            out.append(g)
    return out


def interval_of(cfg, game):
    """某游戏的采集周期（小时）。配置里缺失/非法一律回落到默认值。"""
    d = (cfg_get(cfg, "运行.采集周期小时", {}) or {})
    try:
        v = float(d.get(game))
    except (TypeError, ValueError):
        v = 0
    # 0.25h（15 分钟）~ 24h：小数档（0.25/0.5）与整数档（1/3/6/12/24）都认
    if 0.25 <= v <= 24:
        return v
    return 1 if game in SCHED_FAST else SCHED_DEFAULT_SLOW


def due_games(cfg, force=False, now=None):
    """返回到期、本轮该跑的游戏。

    force=True（页面上手动点「立即采集」）⇒ 所有游戏都跑，不受周期限制。
    首次出现（还没有记录）的游戏一律算到期 ⇒ 新加的游戏立刻生效，不会干等一轮。
    """
    games = track_games(cfg)
    if force:
        return games
    st = _sched_load()
    now = now or dt.datetime.now()
    out = []
    for g in games:
        last = st.get(g)
        if not last:
            out.append(g)
            continue
        try:
            t = dt.datetime.fromisoformat(str(last))
        except Exception:
            out.append(g)
            continue
        if (now - t).total_seconds() >= interval_of(cfg, g) * 3600 - SCHED_TOLERANCE_S:
            out.append(g)
    return out


def sched_mark(cfg, games, ts=None):
    """记下这些游戏本轮真的跑完了（决定下一次什么时候到期）。"""
    games = [g for g in (games or []) if g]
    if not games:
        return
    if not ts:
        ts = dt.datetime.now().isoformat(timespec="seconds")
    st = _sched_load()
    for g in games:
        st[g] = ts
    st["_更新时间"] = ts
    _sched_save(st)


def schedule_snapshot(cfg):
    """给页面渲染：每个游戏的周期 / 上次跑完时间 / 下次预计跑的时间。"""
    st = _sched_load()
    now = dt.datetime.now()
    rows = []
    for g in track_games(cfg):
        h = interval_of(cfg, g)
        last = st.get(g) or ""
        nxt, overdue = "", False
        if not last:
            overdue = True          # 从没跑过 ⇒ 本轮一定跑（口径必须与 due_games 一致）
        else:
            try:
                t = dt.datetime.fromisoformat(str(last))
                nt = t + dt.timedelta(hours=h)
                nxt = nt.isoformat(timespec="minutes")
                overdue = now >= (nt - dt.timedelta(seconds=SCHED_TOLERANCE_S))
            except Exception:
                nxt = ""
                overdue = True      # 记录损坏 ⇒ 也当到期，别让它永远不跑
        rows.append({"游戏": g, "周期小时": h, "上次": last, "下次": nxt, "到期": overdue})
    return {"选项": list(SCHED_CHOICES), "列表": rows,
            "定时器粒度分钟": int(cfg_get(cfg, "运行.采集间隔分钟", 60) or 60),
            "说明": "定时器每小时触发一次；只有到期的游戏才会真正抓价 + 算价 + 改价。"}


def load_cfg():
    with CFG_LOCK:
        with open(CFG_PATH, encoding="utf-8") as f:
            return json.load(f)


def save_cfg(cfg):
    with CFG_LOCK:
        tmp = CFG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CFG_PATH)


def cfg_get(cfg, path, default=None):
    cur = cfg
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def cfg_set(cfg, path, value):
    parts = path.split(".")
    cur = cfg
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


# 白名单：(类型, 最小, 最大) / ("enum", [可选值])
WHITELIST = {
    "汇率.USDCNY":                              ("float", 0.1, 100),
    "跟价.模式":                                ("enum", ["OFF", "AUTO"]),
    # 2026-09-23 第七轮：把语义模糊的「跟价开关 OFF / AUTO」拆成两个独立开关
    "跟价.系统开关":                             ("bool",),
    "跟价.自动跟价":                             ("bool",),
    "跟价.方向.对方降价":                        ("bool",),
    "跟价.方向.对方涨价":                        ("bool",),
    # 策略只剩一条（2026-09-27）：我方前端价 = IGGM 真价 × (1 − 让价百分比)，
    # 标价 = 前端价 ÷ 后台折扣。旧的「策略切换 / 固定差额」开关保持下线；
    # 「最小触发变化」「抖动死区」两个输入侧阈值也按要求删除（任何变化都评估）。
    # 「最高毛利率」引擎从未读取（死开关），一并删除。
    # 2026-09-24 第十五轮：「偏离纠正」阈值（跟价.触发.偏离纠正百分比）已按要求下线
    # —— 参数、白名单放行与引擎触发一并移除，引擎只在 IGGM 真变价时评估。
    # 2026-09-27：让价重新上线（这次是**百分数**，5 = 我方前端价比 IGGM 低 5%）。
    # 与 2026-09-23 归档的同名参数不同量纲（那个是 0~1 小数、只服务已废弃的
    # benchmark_delta 策略），别混。
    "跟价.跟随策略.让价百分比":                   ("float", 0, 90),
    "跟价.跟随策略.最低毛利率":                   ("float", 0, 5),
    # 「最小变动 ($)」「最小变动 (%)」已按要求删除：变了就评估，不留永不生效的开关
    # 「单商品单次最大涨跌幅百分比」也已删除：部分商品涨价幅度很夸张，引擎不再设上限拦截
    "跟价.跟随策略.价格小数位":                   ("int", 0, 6),
    "跟价.跟随策略.取整到":                      ("float", 0, 10),
    # 2026-09-24 按要求下线：「测试期保护 / 只允许调高」「默认 DRY-RUN」两个开关删除。
    # 「单轮最多改几件」更早已删除：单轮不再截断（安全靠「系统总开关 + 确认短语」双闸）。
    "跟价.缓存刷新.自动刷新":                     ("bool",),
    "千岛.对标区服":                             ("str",),
    "前端.服务器直连":                           ("bool",),
    "千岛.服务器抓取":                           ("bool",),
    "前端.后台折扣":                             ("float", 10, 100),
    # 金币跟价同口径（改的是后台「采购成本」那条链，与物品不是一套机制，故单独一个字段）
    "金币.让价百分比":                           ("float", 0, 90),
    "运行.采集间隔分钟":                         ("int", 5, 1440),
}

# 在线可编辑的 KPI 级参数（前端只读展示，不由白名单暴露）
READONLY_PATHS = [
    "跟价.执行限制.需要人工确认",
    "跟价.缓存刷新.入口",
]

# 映射口径（Greater → 强力 / Superior → 精良）已固化在配置里，不给接口、不再上页面。
# 2026-09-23 用户要求：映射口径这种信息不用摆在页面上，一排文字没有作用。


def coerce(path, raw):
    """按白名单把前端传来的原始值转成正确类型；不合法抛 ValueError"""
    spec = WHITELIST.get(path)
    if not spec:
        raise ValueError("字段不允许在线修改：%s" % path)
    kind = spec[0]
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("true", "1", "on", "yes"):
            return True
        if s in ("false", "0", "off", "no"):
            return False
        raise ValueError("%s 需要 true/false" % path)
    if kind == "enum":
        v = str(raw).strip()
        if v not in spec[1]:
            raise ValueError("%s 只能是 %s" % (path, "/".join(spec[1])))
        return v
    if kind == "str":
        v = str(raw).strip()
        if not v:
            raise ValueError("%s 不能为空" % path)
        return v[:60]
    if kind in ("int", "float"):
        try:
            num = float(raw)
        except (TypeError, ValueError):
            raise ValueError("%s 需要数字" % path)
        lo, hi = spec[1], spec[2]
        if not (lo <= num <= hi):
            raise ValueError("%s 需在 %s ~ %s 之间（当前 %s）" % (path, lo, hi, num))
        return int(round(num)) if kind == "int" else round(num, 6)
    raise ValueError("未知类型 %s" % kind)


def editable_snapshot(cfg):
    """把白名单字段抽成扁平 map，供前端渲染表单"""
    out = {}
    for p in WHITELIST:
        out[p] = cfg_get(cfg, p)
    return out


# ============================================================ 任务系统

TASK_LOCK = threading.Lock()
TASKS = {}
TASK_ORDER = []
MAX_TASKS = 40


class Task(object):
    def __init__(self, kind, title, params=None):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.title = title
        self.params = params or {}
        self.status = "running"          # running / done / error
        self.ok = None
        self.started = dt.datetime.now().isoformat(timespec="seconds")
        self.ended = None
        self.lines = []
        self.subs = []
        self.result = None
        self.err = None
        self.lock = threading.Lock()

    def log(self, msg=""):
        line = "[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg)
        with self.lock:
            self.lines.append(line)
            for q in list(self.subs):
                try:
                    q.put_nowait(line)
                except Exception:
                    pass
        try:
            with open(os.path.join(LOG_DIR, "task_%s.log" % self.id), "a",
                      encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        return line

    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            hist = list(self.lines)
            self.subs.append(q)
        return q, hist

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

    def finish(self, status, result=None, err=None):
        with self.lock:
            self.status = status
            self.result = result
            self.err = err
            self.ok = (status == "done")
            self.ended = dt.datetime.now().isoformat(timespec="seconds")
            for q in list(self.subs):
                try:
                    q.put_nowait(None)      # 结束哨兵
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # 2026-10-02：DD373 进货成本采集（**只读监控**）
    # ------------------------------------------------------------------
    def collect_gold_cost(self, cfg, con, ts, log=None, force=False):
        """采 DD373 的 Kinah 进货成本，落 gold_cost 表。

        ⛔⛔ 三条不可越界的边界（用户口径「成本价仅作为监控及参考价值，
           不干预任何比价及改价写入」）：
           ① 只写 gold_cost，**绝不写 gold_price**；
           ② **绝不**改 plan / 目标价 / 动作，不进任何工单；
           ③ 抓不到就写 ok=0，**不用旧值冒充新值**（面板会显示"无报价"）。
        另：被 DD373 风控时**整轮中止**并沿用上一轮快照 —— 宁可显示旧数据，
        也不能把「被拦」显示成「34 个区全部无报价」。
        """
        log = log or self.log
        if core_dd373_cost is None:
            log("  [成本] core_dd373_cost 未导入，跳过")
            return 0
        cc = (cfg.get("金币") or {}).get("进货成本") or {}
        game = str(cc.get("游戏") or "AION2")
        rate = core_gold.rate_of(cfg)
        gap = float(cc.get("请求间隔秒") or 1.3)
        svs = [s for s in ((cfg.get("金币") or {}).get("服务区") or [])
               if s.get("游戏") == game]
        if not svs:
            log("  [成本] config 里没有 %s 的金币服务区，跳过" % game)
            return 0
        log("  [成本] DD373 进货成本 · %s %d 个服务区 · 汇率 %.4f · 间隔 %.1fs"
            % (game, len(svs), rate, gap))
        costs = core_dd373_cost.fetch_costs(
            svs, rate, log=log, gap=gap, refresh_tree=bool(force))
        if not costs:
            log("  [成本] 本轮无数据（多为被风控），沿用上一轮快照")
            return 0
        ok = sum(1 for v in costs.values() if v.get("ok"))
        blocked = [v for v in costs.values()
                   if not v.get("ok") and "风控" in str(v.get("依据") or "")]
        if blocked:
            log("  [成本] ⚠ 撞上 DD373 风控，本轮中止（已抓 %d 条不落库，"
                "面板继续显示上一轮快照）" % ok)
            return 0
        # 最终售价：优先用**本轮目标价**（改价后），没有就退回我方现价
        _price = {}
        try:
            for r in (store.gold_latest(con)[0] or []):
                if engine.game_of(cfg, r.get("key")) != game:
                    continue
                tgt = None
                if r.get("tgt_big") is not None and r.get("big_tier"):
                    tgt = float(r["tgt_big"]) / float(r["big_tier"])
                elif r.get("cost_target") is not None and r.get("divisor"):
                    tgt = float(r["cost_target"]) / float(r["divisor"])
                _price[r.get("key")] = tgt if tgt is not None else r.get("our_per_m")
        except Exception:
            pass
        n = store.save_gold_cost(con, ts, costs, _price, game=game)
        log("  [成本] 已落库 %d 条（有效 %d / 无报价 %d）→ 表 gold_cost"
            % (n, ok, n - ok))
        return n

    def brief(self):
        return {"id": self.id, "kind": self.kind, "title": self.title,
                "status": self.status, "ok": self.ok, "started": self.started,
                "ended": self.ended, "lines": len(self.lines),
                "params": self.params, "err": self.err}


def register(t):
    global TASK_ORDER
    with TASK_LOCK:
        TASKS[t.id] = t
        TASK_ORDER.append(t.id)
        while len(TASK_ORDER) > MAX_TASKS:
            old = TASK_ORDER.pop(0)
            TASKS.pop(old, None)
    return t


def spawn(kind, title, fn, params=None):
    """开一个后台任务线程；同一时刻只允许一个任务在跑（保护 SQLite 与配置）"""
    with TASK_LOCK:
        busy = [TASKS[i] for i in TASK_ORDER if TASKS.get(i) and TASKS[i].status == "running"]
    if busy:
        raise RuntimeError("已有任务在执行中（%s），请等它跑完" % busy[0].title)

    t = register(Task(kind, title, params))

    def wrapper():
        t0 = time.time()
        try:
            fn(t, t.params)
            t.log("")
            t.log("✔ 任务完成，用时 %.1fs" % (time.time() - t0))
            t.finish("done")
        except Exception as e:
            tb = traceback.format_exc()
            t.log("✘ 任务失败：%r" % e)
            t.log(tb[-1200:])
            t.finish("error", err=str(e)[:300])

    threading.Thread(target=wrapper, daemon=True).start()
    return t


# ============================================================ 数据组装

def open_db():
    return store.connect(DATA_DIR)


def build_qd_map(cfg, con, qd_ts):
    """千岛成本 → {对照项key: row}（与 tracker 同逻辑：对标区服优先，缺失时降到参考区服）"""
    rows = [dict(r) for r in con.execute("SELECT * FROM qd_cost WHERE ts=?", (qd_ts,))]
    spec = cfg_get(cfg, "千岛.对标区服", "")
    refs = cfg_get(cfg, "千岛.参考区服") or []
    out = {}
    for it in cfg["商品映射"]["对照项"]:
        kw = (it.get("千岛") or {}).get("商品")
        if not kw:
            continue
        got = core_qd.pick_from_db(rows, spec, [kw])
        if got:
            got["_区服"] = spec
            out[it["key"]] = got
            continue
        for alt in refs:
            got = core_qd.pick_from_db(rows, alt, [kw])
            if got:
                got["_区服"] = alt
                got["_降级区服"] = True
                out[it["key"]] = got
                break
    return out


def latest_ts(con, table):
    r = con.execute("SELECT MAX(ts) t FROM %s" % table).fetchone()
    return r["t"] if r else None


def eval_rows(cfg, con, with_history=True):
    """把库里最新一轮数据算成前端要的表格结构"""
    ts = latest_ts(con, "decisions")
    if not ts:
        return {"ts": None, "rows": [], "kpi": {}, "history": [], "health": {}}

    ig_ts = latest_ts(con, "iggm_price")
    qd_ts = latest_ts(con, "qd_cost")
    our_map, our_ts = store.our_latest(con)

    iggm_now = {r["goods_no"]: r for r in (store.iggm_rows(con, ig_ts) if ig_ts else [])}
    prev_t = store.prev_ts(con, "iggm_price", ig_ts) if ig_ts else None
    iggm_prev = {r["goods_no"]: r for r in (store.iggm_rows(con, prev_t) if prev_t else [])}
    qd_map = build_qd_map(cfg, con, qd_ts) if qd_ts else {}

    decs = [dict(r) for r in con.execute(
        "SELECT * FROM decisions WHERE ts=? ORDER BY key", (ts,))]

    # 后台折扣：前端价 = 我方标价 × 折扣。页面同时展示两个口径，这里统一换算一次。
    # 2026-09-25：改为**按商品/按游戏**取（暗黑4=90、POE2=100），见 engine.disc_of。
    # 2026-09-27：再优先采信**前端实测折扣**（our_price.front_disc），config 只当兜底。
    _key2it = {it["key"]: it for it in cfg["商品映射"]["对照项"]}

    def _disc_of_key(k):
        return disc_of_key(cfg, our_map, k, _key2it)

    key2it = _key2it
    rows, margins, changed = [], [], 0
    for d in decs:
        it = key2it.get(d["key"], {})
        _disc = _disc_of_key(d["key"])
        gn = d.get("iggm_no") or (it.get("iggm") or {}).get("goods_no") or ""
        cur = iggm_now.get(gn) or {}
        # 勾选表是「即时生效」的展示层开关：取消勾选后不必等下一轮重算，
        # 页面上立刻按「只展示」呈现。只改展示值、不写库，
        # 否则每点一次勾选都会多出一条决策快照，把历史搅乱。
        follow = it.get("跟价", True) is not False
        _act, _sug, _rsn, _tgt, _mnew = (d.get("action"), d.get("suggest"),
                                         d.get("reason"), d.get("target_usd"),
                                         d.get("margin_new"))
        if not follow:
            _act, _sug, _tgt, _mnew = "hold", None, None, None
            _rsn = "未勾选跟价：只展示价格与毛利，不出目标价"
        rows.append({
            "key": d["key"],
            "title": d.get("title") or it.get("中文名") or d["key"],
            "cn": it.get("中文名"),
            "iggmTitle": cur.get("title") or (it.get("iggm") or {}).get("title") or "",
            "iggmNo": gn,
            "pack": it.get("装量") or 1,
            "iggmOld": d.get("iggm_old"),
            "iggmNew": d.get("iggm_new"),
            "oursOld": d.get("ours_old"),        # 前端展示价（客户实付）
            # 标价口径由前端价 ÷ 折扣推导。不做成 decisions 表新列，
            # 是因为决策要在数据库里往返一圈，derive 比改表结构稳（表结构不动）。
            "oursBid": (d.get("ours_old") / _disc) if d.get("ours_old") else None,
            "target": _tgt,                      # 目标标价（= IGGM 折后价）
            "targetFront": (round(_tgt * _disc, 4) if _tgt is not None else None),
            "costCny": d.get("cost_cny"),
            "costUsd": d.get("cost_usd"),
            "margin": d.get("margin_old"),
            "marginNew": _mnew,
            "action": _act,
            "suggest": _sug,
            "reason": _rsn,
            "noIggm": bool(it.get("无IGGM对应")),
            "follow": follow,                    # 勾选表开关；False = 只展示不跟价
            # 下面两个标志完全由已有字段推导，不入库（decisions 表结构保持不变）
            "iggmMissing": bool(gn) and not bool(it.get("无IGGM对应"))
                           and d.get("iggm_new") is None,
            "iggmNewSpec": d.get("iggm_old") is None and d.get("iggm_new") is not None,
        })
        if d.get("iggm_old") and d.get("iggm_new") and abs(d["iggm_new"] - d["iggm_old"]) > 1e-12:
            changed += 1
        if d.get("margin_old") is not None:
            margins.append(d["margin_old"])

    # 统计口径跟页面显示对齐：未勾选的行即使库里存着 follow_up，也只算「仅观察」
    s = {"follow_up": 0, "follow_down": 0, "hold": 0, "blocked": 0}
    for r in rows:
        a = r.get("action")
        if a in s:
            s[a] += 1

    neg = [r for r in rows if r["margin"] is not None and r["margin"] < 0]
    kpi = {
        "items": len(rows),
        "followOn": sum(1 for r in rows if r.get("follow", True)),
        "changed": changed,
        "actionable": s["follow_up"] + s["follow_down"],
        "up": s["follow_up"], "down": s["follow_down"],
        "hold": s["hold"], "blocked": s["blocked"],
        # OFF 模式下 action 会降级成 hold，这里的 suggested 才是「如果开 AUTO 该跟几件」
        "suggested": sum(1 for r in rows if r.get("suggest")),
        "holdIdle": sum(1 for r in rows if r["action"] == "hold" and not r.get("suggest")),
        "marginAvg": round(sum(margins) / len(margins), 4) if margins else None,
        "marginMin": round(min(margins), 4) if margins else None,
        "negMargin": len(neg),
        "iggmMissing": sum(1 for r in rows if r.get("iggmMissing")),
        "noOurPrice": sum(1 for r in rows if r.get("oursOld") is None),
    }

    history = []
    if with_history:
        for r in con.execute(
                "SELECT ts, SUM(CASE WHEN action IN ('follow_up','follow_down') THEN 1 ELSE 0 END) act,"
                " COUNT(*) n, AVG(margin_old) m FROM decisions"
                " GROUP BY ts ORDER BY ts DESC LIMIT 40"):
            history.insert(0, {"ts": r["ts"], "actionable": r["act"] or 0,
                               "items": r["n"], "margin": r["m"]})
        history = history[-30:]

    health = {
        "iggmTs": ig_ts, "iggmCount": len(iggm_now),
        "qdTs": qd_ts, "qdKeys": len(qd_map),
        "ourTs": our_ts, "ourCount": len(our_map),
        "qdStaleHours": _age_hours(qd_ts),
        "ourStaleHours": _age_hours(our_ts),
        # 竞品价折算系数（抓取值 → 客户实付折后价），页面据此显示口径说明
        "iggmFactor": _factor(cfg),
        # 让价口径（我方前端价 = IGGM 价 × (1 − 让价%)）—— 页面据此显示口径说明
        "allowPct": _allow_pct(cfg),
        "goldAllowPct": _allow_pct(cfg, gold=True),
    }
    runs = [dict(r) for r in con.execute(
        "SELECT * FROM runs ORDER BY ts DESC LIMIT 12")]
    health["runs"] = runs
    return {"ts": ts, "rows": rows, "kpi": kpi, "history": history, "health": health,
            "decisions": decs}


def _master_raw(cfg):
    """系统总开关的原始值。

    老配置里没有这个键 —— 从「跟价.模式」迁移（模式 AUTO 说明当时是允许改价的），
    避免升级后开关凭空变成「关闭」而与引擎行为对不上。
    """
    cur = cfg_get(cfg, "跟价.系统开关", None)
    if cur is None:
        return str(cfg_get(cfg, "跟价.模式", "OFF")).upper() == "AUTO"
    return bool(cur)


def switch_state(cfg):
    """两个开关的只读快照（不改配置）。"""
    master = _master_raw(cfg)
    auto = bool(cfg_get(cfg, "跟价.自动跟价", False))
    return {
        "master": master,               # 系统总开关：能不能改价
        "auto": auto and master,        # 自动跟价：要不要自动改（总开关关着就不生效）
        "autoRaw": auto,
        "mode": "AUTO" if master else "OFF",
        "canApply": master,
    }


def sync_mode(cfg):
    """把两个业务开关折算成引擎唯一认识的「跟价.模式」，并写回配置。

    引擎只认 OFF / AUTO：
      · 系统总开关 关 → OFF（引擎把动作降级成「只看不动」，只给建议）
      · 系统总开关 开 → AUTO（引擎正常算出目标价；「是否真下发」由
        「自动跟价」开关 + 页面确认短语两道关决定，不由引擎管）
    """
    st = switch_state(cfg)
    cfg_set(cfg, "跟价.模式", st["mode"])
    cfg_set(cfg, "跟价.开关状态", st["mode"])
    return st


# 商品图标：按名字关键字给一个，纯本地 emoji，零网络依赖
ITEM_ICONS = [
    ("巢穴", "🔑"), ("Lair Key", "🔑"),
    ("奥义", "🔮"), ("Crux", "🔮"),
    ("根", "🌿"), ("Root", "🌿"),
    ("符文", "🔯"), ("Rune", "🔯"),
    ("金币", "🪙"), ("Gold", "🪙"),
    ("护符", "📿"), ("Amulet", "📿"),
    ("装备", "🛡"), ("Gear", "🛡"),
]


def item_icon(it):
    n = "%s %s" % (it.get("中文名") or "", ((it.get("iggm") or {}).get("title") or ""))
    low = n.lower()
    for k, v in ITEM_ICONS:
        if k.lower() in low:
            return v
    return "📦"


def gold_follow_items(cfg):
    """把金币服务区变成「跟价范围」里的独立商品条目（一个服务区 = 一个商品）。

    金币不参与 对照项 —— 那条链路按 IGGM 商品映射 + 千岛成本算「标价」；
    金币走 core_gold，改的是后台「采购成本」，是两套东西。所以这里**只在渲染层**
    把它挂进「跟价范围」，开关落 `config.金币.服务区[].跟价`，
    与 core_gold.build_plan 里那句「未勾选跟价，跳过」严格对齐。
    """
    gcfg = cfg.get("金币") or {}
    out = []
    if gcfg.get("启用", True) is False:
        return out
    for sv in (gcfg.get("服务区") or []):
        k = sv.get("key")
        if not k:
            continue
        zh = str(sv.get("中文名") or k)
        # 「赛季普通 (S15 Softcore)」→ 商品名「赛季普通-金币」，副行英文「S15 Softcore」
        short, _, tail = zh.partition("(")
        short = short.strip() or zh
        en = tail.rstrip(") ").strip() if tail else ""
        out.append({
            "key": str(k),
            "name": short + str(gcfg.get("跟价名后缀") or "-金币"),
            "en": en,
            "iggm": en,
            "icon": "",
            "pack": 1,
            "on": sv.get("跟价", True) is not False,
            "gold": True,
            # 2026-10-01：金币服务区不再一律挂到「挂载游戏」那一栏。
            #   多游戏（暗黑4 + AION2）时按**各自**的「游戏」字段归栏，
            #   否则 AION2 的 20 个格子会挤在暗黑4 栏里、AION2 栏空空如也。
            #   取法用 engine.game_of（① 对照项 ② 金币.服务区[].游戏 ③ 前缀 ④ 挂载游戏），
            #   老 config 没有「游戏」字段时自动回落「挂载游戏」，行为与改造前一致。
            "游戏": engine.game_of(cfg, k),
        })
    return out


def follow_tree(cfg):
    """按游戏分组的跟价开关表（竖排：一个游戏一条竖向区间）。

    分组完全由对照项的「游戏」字段决定。以后新增游戏（VALORANT / CS2 / POE2 …）
    只要两步：① 在 商品映射.游戏字典 里登记「中文名 → {英文, 图标, 色}」；
    ② 给它的商品打上「游戏」标签。页面会自动多出一条竖排区间，不需要改前端。
    「游戏顺序」只影响先后；字典里标了 预留:true 而暂时没有商品的游戏会显示成空区间占位。
    """
    items = cfg["商品映射"]["对照项"]
    raw_gd = (cfg["商品映射"].get("游戏字典") or {})
    gd = {}
    if isinstance(raw_gd, dict):
        for k, v in raw_gd.items():
            # 字典里允许放 _说明 这类注释键；只认「游戏名 → {英文, 图标, 色}」的条目
            if not str(k).startswith("_") and isinstance(v, dict):
                gd[k] = v
    hid = cfg["商品映射"].get("隐藏游戏")
    hid = {str(x) for x in hid} if isinstance(hid, (list, tuple, set)) else set()
    order = list(cfg["商品映射"].get("游戏顺序") or [])
    groups = {}
    for it in items:
        groups.setdefault(it.get("游戏") or "未分组", []).append(it)
    names = order + [g for g in groups if g not in order]
    names += [g for g in gd if g not in names]
    # 金币（Gold）：不在 对照项 里，只在渲染层挂进「跟价范围」。
    #   2026-10-01 多游戏：**按每个服务区自己的游戏归栏**（暗黑4 一栏、AION2 一栏），
    #   不能像以前那样一律挂到「挂载游戏」那一栏 —— 否则 AION2 的格子会挤进暗黑4。
    gold_items = gold_follow_items(cfg)
    gold_mount = str((cfg.get("金币") or {}).get("挂载游戏") or "暗黑破坏神4")
    gold_by_game = {}
    for _gi in gold_items:
        gold_by_game.setdefault(_gi.get("游戏") or gold_mount, []).append(_gi)
    for _gm in gold_by_game:
        if _gm not in names:
            names.append(_gm)
    games, total, on = [], 0, 0
    for g in names:
        meta = gd.get(g) or {}
        gi, gon = [], 0
        for it in groups.get(g) or []:
            v = it.get("跟价", True) is not False
            gon += 1 if v else 0
            en = ((it.get("iggm") or {}).get("title") or "")
            gi.append({
                "key": it["key"],
                "name": it.get("中文名") or it["key"],
                "en": en,                      # 英文名（IGGM 商品名），页面第二行
                "iggm": en,                    # 兼容旧字段
                "icon": item_icon(it),
                "pack": it.get("装量", 1),
                "on": v,
            })
        # 金币服务区接在「其他产品」之后；顺序 = config.金币.服务区 的顺序
        for _git in (gold_by_game.get(g) or []):
            gi.append(_git)
            gon += 1 if _git["on"] else 0
        total += len(gi)
        on += gon
        games.append({
            "name": g,
            "en": meta.get("英文") or "",
            "icon": meta.get("图标") or "🎮",
            "color": meta.get("色") or "",
            "reserved": bool(meta.get("预留")),
            "show": g not in hid,          # 顶部「游戏筛选」下拉的勾选状态（存服务器）
            "items": gi,
            "on": gon,
            "note": "" if gi else ("预留位" if meta.get("预留") else "该游戏还没有对照项"),
        })
    return {"games": games, "total": total, "onCount": on}


def _allow_pct(cfg, gold=False):
    """让价百分比（百分数，5 = 我方前端价比 IGGM 低 5%）。物品与金币各一个字段。"""
    node = ((cfg or {}).get("金币") if gold else (cfg or {}).get("跟价")) or {}
    v = (node.get("跟随策略") or {}).get("让价百分比") if not gold else node.get("让价百分比")
    try:
        return max(0.0, min(float(v or 0.0), 90.0))
    except (TypeError, ValueError):
        return 0.0


def _factor(cfg):
    """竞品价折算系数：机房抓取价 → 客户实付折后价（默认 1.0）"""
    try:
        k = float(((cfg or {}).get("iggm") or {}).get("竞品价折算系数", 1.0))
    except (TypeError, ValueError):
        k = 1.0
    return k if k > 0 else 1.0


def _age_hours(ts):
    if not ts:
        return None
    try:
        return round((dt.datetime.now() - dt.datetime.fromisoformat(ts)).total_seconds() / 3600.0, 2)
    except Exception:
        return None


# ============================================================ 改动记录

CHANGELOG = os.path.join(ROOT, "output", "改动记录.md")


def _chg_pct(old, new):
    """变化百分比（相对旧值）"""
    try:
        if not old:
            return None
        return (new - old) / old * 100.0
    except Exception:
        return None


def _changed_rows(decisions):
    """挑出「目标标价 ≠ 现标价」的决策，按变动额从大到小排。
    口径 = 后台「$每个价格」（标价），不是前端展示价。
    目标价认 target_usd（权威列，且是 decisions 表真实字段）；
    ours_new 只在「真的要改」时才被引擎赋值，作兜底。"""
    out = []
    for d in decisions:
        # 被「按行 pending 闩」拦下的行（已出单、前台还没生效）不该算进「本轮有变化」——
        # 它的目标价只是**上一次已经派出去的那个**，不是这一轮新算出来的改动。
        if d.get("_待前台生效"):
            continue
        old = d.get("ours_bid")
        new = d.get("target_usd")
        if new is None:
            new = d.get("ours_new")
        if old is None or new is None or abs(new - old) < 1e-9:
            continue
        out.append((d, old, new, new - old, _chg_pct(old, new)))
    out.sort(key=lambda x: -abs(x[3]))
    return out


_ACT_HINT = {"follow_up": "可执行·涨", "follow_down": "可执行·降",
             "blocked": "被安全闸拦", "hold": "仅记录"}


def _changelog_write(title, ts_start, lines, summary, extra=""):
    """把一段改动记录追加到 output/改动记录.md（跨轮留档，方便事后复盘）"""
    os.makedirs(os.path.dirname(CHANGELOG), exist_ok=True)
    ended = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(CHANGELOG, "a", encoding="utf-8") as f:
        f.write("\n### %s\n\n" % title)
        f.write("- 时段：%s → %s\n" % (ts_start, ended))
        if extra:
            f.write("- 数据：%s\n" % extra)
        if lines:
            for s in lines:
                f.write("- 改动｜%s\n" % s.strip())
        else:
            f.write("- 改动｜无\n")
        f.write("- 小结：%s\n" % summary)
    return CHANGELOG


def emit_record(t, title, ts_start, decisions, extra="", write=True):
    """统一输出「改动记录」：哪个时段 / 改了哪些 / 改了多少。
    日志里只留这一段（外加必要的警告与错误），过程性输出全部收敛掉。
    注意：引擎只在「IGGM 真的变价」时才给出目标价，所以 IGGM 持平时这里就是「无改动」。"""
    rows = _changed_rows(decisions)
    sm = engine.summarize(decisions)
    n_up = sum(1 for _, o, n, _, _ in rows if n > o)
    n_dn = sum(1 for _, o, n, _, _ in rows if n < o)
    lines = ["%s：%s → %s（%+.4f%s）［%s］"
             % (d.get("title") or d.get("key"), _usd(o), _usd(n), dl,
                "" if pc is None else ", %+.2f%%" % pc,
                _ACT_HINT.get(d.get("action"), d.get("action") or ""))
             for d, o, n, dl, pc in rows]
    unchanged = max(0, sm["total"] - len(rows))
    actionable = sm["follow_up"] + sm["follow_down"]
    summary = ("目标标价有变化 %d 件（涨 %d / 降 %d）｜ 未变化 %d 件"
               % (len(rows), n_up, n_dn, unchanged))
    summary2 = ("可执行 %d ｜ 被安全闸拦 %d ｜ 仅记录(开关未开) %d"
                % (actionable, sm["blocked"], max(0, len(rows) - actionable - sm["blocked"])))
    if rows and not actionable:
        try:
            _m = str(cfg_get(load_cfg(), "跟价.模式", "OFF")).upper()
        except Exception:
            _m = "?"
        summary2 += "  ← 当前开关 %s，只记录不执行" % _m

    t.log("── 改动记录 ──")
    if lines:
        for s in lines:
            t.log("  " + s)
    else:
        t.log("  无改动（IGGM 与上轮一致；引擎只在竞品变价时才给目标价）")
    t.log("── 小结 ──")
    t.log("  " + summary)
    if rows:
        t.log("  " + summary2)
    if write:
        try:
            _sum = summary + ((" ｜ " + summary2) if rows else "")
            fp = _changelog_write(title, ts_start, lines, _sum, extra)
            t.log("  已追加记录：%s" % fp)
        except Exception as e:
            t.log("  ⚠ 改动记录写文件失败：%r" % e)
    return sm


# ============================================================ 任务实现

# ---------------------------------------------------------------------------
# 自动跟价：把「跟价.自动跟价」开关真正接上（2026-09-25 第十四轮）
#
# 🔴 修的是什么：这个开关以前**是装饰性的** —— 本文件里它只在 task_apply /
#    task_plan 的日志文案里被读出来打印一行，**没有任何地方读它去触发改价**。
#    所以「打开自动跟价」什么都不会发生，改价仍须人工点「生成改价工单」+ 输确认短语。
#
# 接上之后的行为（采集由 d4follow-collect.timer 每 1 小时触发一轮）：
#     采集一轮 → 引擎算价 → 有可执行改价 且 自动跟价开 → 自动出工单 + 派单
#         → 本机执行器（p2pah_local_worker.py）接单 → p2pah_local.py write --confirm
#         → 写后台 + 复核 + 推前端 + 清缓存 → 结果回传
#
# 仍然保留的安全约束（不是「全自动无人管」，是「自动执行已授权的事」）：
#   · 系统总开关关 → 直接不动（只看不改）
#   · 自动跟价关   → 不动，回到「人工点按钮」的老流程
#   · 逐件「跟价」勾选（config 商品映射.对照项[].跟价 = false 的永不改）
#   · 方向策略（跟价.方向：对方涨价/降价）
#   · 引擎只在 IGGM 价格有变化时才给目标价（偏离纠正已于第十五轮移除）
#   · 该服务器只「算价 + 派单」；写请求由执行方发。
#     2026-09-27 起默认执行方是**服务器自己**（容器 p2pah-srv:1，IP 已进白名单）；
#     可用 config「跟价.执行方式」切成本机执行器（特殊情况）。
#
# 防叠单：同类任务已有 pending/dispatched 的单时，本轮跳过。
#   （否则采集每轮都派一次，本机执行慢时会堆出一串重复单）
# ---------------------------------------------------------------------------
def _auto_dispatch(t, cfg, con):
    """采集完成后：自动跟价开着就自动出单，并按「跟价.执行方式」派给执行方。"""
    st = switch_state(cfg)
    if not st["master"]:
        t.log("  [自动跟价] 系统总开关「关闭」—— 只看不改，本轮不出单")
        return
    if not st["autoRaw"]:
        t.log("  [自动跟价] 开关「关闭」—— 本轮只算价；改价请在控制台点"
              "「生成改价工单」")
        return

    t.log("  [自动跟价] 已开启 —— 检查本轮是否有可执行的改价…")
    # ══════════════════════════════════════════════════════════════════
    # 全局防叠单 · 全部出单、按序入队（2026-10-01 用户要求 · 二次修正）
    #
    #   要点：本轮**所有**可执行的改价（物品 + 金币，各自内部再按游戏拆单）
    #   全部算出工单并**按序入队**，由执行器 FIFO 一张一张跑。
    #   ⇒ 不再「截断」后续单子，任何一个游戏都不会被饿死。
    #
    #   ⚠ 为什么不按老写法「出一张就 break」（踩过的坑，2026-10-01 20:50 实测）：
    #     老写法有两重静默截断 ——
    #       ① 出单前 `if _q: break`：队列里有任何单在跑（如 21:00 物品单跑 5 分钟），
    #          本轮到期的金币单**连算都不算、直接丢弃**，既不入队也不留痕；
    #       ② 出单成功后 `break`：物品单出成功即收工，金币分支永远轮不到。
    #     结果：只要物品单每轮都能凑出可执行件数（19:50 起连续 5 轮 6~23 件），
    #     金币单就从 19:35 起彻底不再出单 —— 用户看到「AION2 金币改价一直没动静」。
    #
    #   排队语义交给执行器：srv_exec.py 是单实例文件锁 + 队列按 ts FIFO 认领，
    #   同一时刻只有一张单在跑，后续单排队等待 ⇒ 天然串行、不并发写后台。
    # ══════════════════════════════════════════════════════════════════
    _dispatched = []
    for kind, fn, label in (("write", task_apply, "物品"),
                            ("writegold", task_gold_apply, "金币")):
        try:
            # confirm 短语由程序提供：用户在控制台打开「自动跟价」＝ 已授权自动执行。
            # task_apply / task_gold_apply 内部仍会自己复查总开关与账号配置。
            r = fn(t, {"confirm": "确认改价", "actor": "auto:定时采集"})
            if r and r.get("count"):
                _exec_who = ("服务器执行器" if str(cfg_get(cfg, "跟价.执行方式", "server")).lower()
                             != "local" else "本机执行器")
                _nk = len(r.get("tickets") or []) or 1
                t.log("    [%s] ✔ 已自动出单并派发%s：%d 件%s"
                      % (label, _exec_who, r["count"],
                         ("（跨 %d 个游戏 → 拆成 %d 张单，执行器不接受混游戏单）"
                          % (len(r.get("games") or []), _nk)) if _nk > 1 else ""))
                _dispatched.append((label, r["count"], _nk))
            else:
                t.log("    [%s] 无可执行的改价（竞品本轮持平 / 全被闸门拦下）" % label)
        except Exception as e:
            t.log("    ⚠ [%s] 自动出单失败（不影响本轮采集与看板）：%s" % (label, e))
    # 汇总一行，方便一眼看清本轮一共排了几张单、几张在排队
    if _dispatched:
        _tot = sum(n for _l, _c, n in _dispatched)
        _items = sum(c for _l, c, _n in _dispatched)
        _pending = con.execute(
            "SELECT COUNT(*) FROM local_job WHERE status IN ('pending','dispatched')"
        ).fetchone()[0]
        t.log("    [队列] 本轮共入队 %d 张单（%d 件改价）；当前排队/执行中 %d 张 —— "
              "执行器按 FIFO 一张一张跑，未跑到的自动等待，不会丢单"
              % (_tot, _items, _pending))
def task_collect(t, opts):
    """采集一轮：IGGM（服务器直连）+ 我方前端（MMOEXP 公开页）+ 千岛（用本机推送的最近快照）

    2026-09-28 起**按游戏周期**跑：
      · 定时器 d4follow-collect.timer 每小时打一次这个接口（心跳，频率没变），
        但只有**到期**的游戏才会真跑；
      · 所有游戏都没到期 ⇒ 立刻返回，不抓价、不算价、不出单（省时间，也少打扰竞品）；
      · 页面上点「立即采集」会带 opts.force=true ⇒ 忽略周期，全部游戏跑一遍。
    """
    cfg = load_cfg()
    mode = str(cfg_get(cfg, "跟价.模式", "OFF")).upper()
    t_start = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    force = bool((opts or {}).get("force"))
    _all = track_games(cfg)
    due = due_games(cfg, force=force)
    t.log("══ 采集一轮 ══ 开关 %s ｜ 起 %s" % (mode, t_start))
    t.log("  周期：%s" % "、".join(
        ("%s %s" % (g, ("%g 分钟" % (interval_of(cfg, g) * 60))
                     if interval_of(cfg, g) < 1 else ("%g 小时" % interval_of(cfg, g))))
        for g in _all))
    if not due:
        t.log("  本轮没有到期的游戏（都没到各自周期）→ 跳过：不抓价、不算价、不出单。")
        return {"ts": dt.datetime.now().isoformat(timespec="seconds"),
                "skipped": True, "due": [],
                "periods": {g: interval_of(cfg, g) for g in _all}}
    t.log("  本轮到期 %d/%d 个游戏：%s" % (len(due), len(_all), "、".join(due)))

    con = open_db()
    ts = dt.datetime.now().isoformat(timespec="seconds")

    # ---- 1) IGGM ----
    ig_rows = []
    try:
        ig_rows = core_iggm.scrape_all(cfg, log=lambda *a: None, games=due)  # 只抓到期的
    except Exception:
        t.log("  [IGGM] 整轮失败：%s" % traceback.format_exc()[-500:])
    # 未到期的游戏不重复抓，但把它们的最近一份行情「沿用」到本轮快照 ——
    # 否则本轮快照只剩到期游戏，看板会缺行、下一轮的比价基线也会断。
    # 🔴 顺序：先搬上一份全量（旧值），再用下面 save_iggm 覆盖本轮真抓到的（新值）。
    if ig_rows and len(due) < len(_all):
        try:
            _n = store.iggm_carryover(con, ts)
            if _n:
                t.log("  ↺ 沿用上一份全量快照 %d 行（未到期的游戏不重复抓）" % _n)
        except Exception:
            t.log("  ⚠ 沿用上一份快照失败（本轮快照可能只含到期游戏）：%s"
                  % traceback.format_exc()[-200:])
    if ig_rows:
        store.save_iggm(con, ts, ig_rows)
        ig_ts = ts
    else:
        ig_ts = store.prev_ts(con, "iggm_price", ts)
        t.log("  ⚠ IGGM 本轮 0 条 → 复用上一份快照 %s" % ig_ts)
    iggm_now = {r["goods_no"]: r for r in (store.iggm_rows(con, ig_ts) if ig_ts else [])}
    prev_t = store.prev_ts(con, "iggm_price", ig_ts) if ig_ts else None
    iggm_prev = {r["goods_no"]: r for r in (store.iggm_rows(con, prev_t) if prev_t else [])}

    # ---- 2) 千岛 ----
    # 2026-09-27 起两级取价：
    #   a) 平台聚合价 currency-spu-price-list —— 只在快照过旧时抓，用来拿
    #      spuId / 名称映射 + 全量列表（这是滞后参考价，不再直接当进货成本）。
    #   b) 订单簿 DWC（currency/spu-list-v2）—— **每轮都做**（缓存默认 1h），
    #      只 upsert 最新快照里那十几行目标商品：不加新行、不涨库。
    #   任何一步失败都沿用上一轮成本，绝不写 0、绝不中断采集。
    qd_ts = latest_ts(con, "qd_cost")
    if bool(cfg_get(cfg, "千岛.服务器抓取", False)):
        _qd_stale = float(cfg_get(cfg, "千岛.服务器抓取阈值小时", 12) or 12)
        if (not qd_ts) or ((_age_hours(qd_ts) or 0) > _qd_stale):
            try:
                t.log("  [千岛] 快照已过 %.0fh，服务器直连抓聚合价…" % _qd_stale)
                _qd_rows, _qd_new, _qd_cached = core_qd.fetch(cfg, log=t.log)
                if _qd_rows:
                    _qd_rows, _m0 = core_qd.apply_books(cfg, _qd_rows, log=t.log)
                    store.save_qd(con, _qd_new, _qd_rows)
                    qd_ts = _qd_new
                    t.log("  [千岛] ✔ %d 条，快照 %s" % (len(_qd_rows), _qd_new))
            except Exception:
                t.log("  ✘ 千岛直连失败（回退库里快照）：%s"
                      % traceback.format_exc()[-300:])

    # 2b) 订单簿：每轮刷新（价格每小时都可能变），只覆盖最新快照里的目标行
    if qd_ts:
        try:
            _rows = [dict(r) for r in con.execute(
                "SELECT * FROM qd_cost WHERE ts=?", (qd_ts,))]
            _spec0 = core_qd.canon_spec(cfg_get(cfg, "千岛.对标区服", ""))
            _before = {(r.get("spec"), r.get("spu_id")): r.get("price_cny")
                       for r in _rows}
            _rows, _m = core_qd.apply_books(cfg, _rows, log=t.log)
            if _m.get("hit"):
                store.save_qd(con, qd_ts, _rows)
            _bt, _bn = core_qd.book_cache_info(cfg)
            t.log("  [千岛·订单簿] 口径=%s｜命中 %s 行｜订单簿快照 %s（%s 组）"
                  % (_m.get("src"), _m.get("hit", 0), _bt, _bn))
            for r in _rows:
                if not r.get("src"):
                    continue
                if core_qd.canon_spec(r.get("spec")) != _spec0:
                    continue
                _old = _before.get((r.get("spec"), r.get("spu_id")))
                _chg = ""
                if _old and r.get("price_cny") and abs(_old - r["price_cny"]) > 1e-9:
                    _chg = "（%.1f%%）" % (100.0 * (r["price_cny"] / _old - 1))
                t.log("      %s %s→%s 元/%s ｜Q=%s 深%s %s %s"
                      % (r.get("name"), _old, r.get("price_cny"), r.get("unit"),
                         r.get("min_buy"), r.get("depth"), r.get("note") or "", _chg))
        except Exception:
            t.log("  ✘ 订单簿刷新失败（沿用现有成本）：%s"
                  % traceback.format_exc()[-300:])

    if qd_ts:
        if (_age_hours(qd_ts) or 0) > 24:
            t.log("  ⚠ 成本快照已超过 24h，可在本机跑 6_推送数据到在线看板.bat 更新")
    else:
        t.log("  ⚠ 库里还没有千岛成本，请先在本机推送")

    # ---- 3) 我方前端价 ----
    our_rows = []
    direct = bool(cfg_get(cfg, "前端.服务器直连", False))
    _fg = str(cfg_get(cfg, "前端.游戏", "暗黑破坏神4") or "暗黑破坏神4")
    if direct and (_fg in due):
        try:
            items = core_front.fetch_all(cfg, log=t.log)
            frows, unmatched = core_front.to_our_rows(cfg, items)
            for r in frows:
                if not r.get("_装量匹配"):
                    t.log("  ⚠ 前端装量降级匹配：%s → %s" % (r["title"], r["key"]))
            if unmatched:
                t.log("  ⚠ 前端未匹配：%s" % "、".join(unmatched[:8]))
            our_rows = frows
        except Exception:
            t.log("  ✘ 前端直连失败：%s" % traceback.format_exc()[-400:])
    elif direct:
        t.log("  [前端] %s 本轮未到期，跳过主页面抓取（多游戏按各自周期走）" % _fg)
    if direct:
        # ---- 3b) 多游戏前端价（POE2 等，走 /ajax/goods 接口）----
        if (cfg.get("iggm") or {}).get("多游戏"):
            try:
                mitems = core_front.fetch_multi_game(cfg, log=t.log, games=due)
                mrows, mun = core_front.to_multi_rows(cfg, mitems)
                if mun:
                    t.log("  ⚠ 多游戏前端未匹配 %d 条：%s"
                          % (len(mun), "、".join(mun[:8])))
                have = {r["key"] for r in our_rows}
                for r in mrows:
                    if r["key"] in have:
                        continue
                    our_rows.append(r)
                t.log("  [前端] 多游戏匹配上 %d 条" % len(mrows))
            except Exception:
                t.log("  ✘ 多游戏前端抓取失败：%s" % traceback.format_exc()[-400:])
    if our_rows:
        # 本轮没读到的 key（抓取部分失败）→ 用库里上一份快照兜底，别让它的毛利变空
        try:
            _old_map, _old_ts = store.our_latest(con)
            _have = {r["key"] for r in our_rows}
            _fill = [r for k, r in (_old_map or {}).items() if k not in _have]
            if _fill:
                our_rows += _fill
                t.log("  ↺ 本轮未读到的 %d 个 key 用库内快照兜底" % len(_fill))
        except Exception:
            pass
        store.save_our(con, ts, our_rows)
    else:
        our_map, our_ts = store.our_latest(con)
        our_rows = list(our_map.values())
        if our_ts:
            if (_age_hours(our_ts) or 0) > 12:
                t.log("  ⚠ 我方价已超过 12h 未更新，建议在本机跑 推送数据.bat")
        else:
            t.log("  ⚠ 库里没有我方价格，请先在本机跑 推送数据.bat")
    ours_now = {r["key"]: r for r in our_rows}

    # ---- 3.4) 人工调价归因（2026-09-29）----
    # 用户策略「IGGM 改价了我们再改」，但千岛进货便宜时他会先手动改我方的价。
    # 这里把「我方价变了但账本里没有系统工单」的行标为人工调价 → 引擎（条件B）挡住，
    # 不让偏差纠偏闸把自主定价拉回去。只读我方价快照 + 工单账本，不写任何价格。
    try:
        _mo_stat = detect_manual_override(cfg, con, ts, log=t.log)
        if _mo_stat.get("已保护"):
            t.log("  人工调价保护当前共 %d 行（IGGM 变价后自动解除）"
                  % _mo_stat["已保护"])
    except Exception:
        t.log("  ⚠ 人工调价归因失败（不影响本轮跟价）：%s" % traceback.format_exc()[-300:])

    # ---- 3.45) 货架自检（2026-10-01，P1：只告警，绝不改配置）----
    # 用户上架新档位 / 手工定价后，若 config 未纳管或映射错位，会被每轮覆盖。
    # 这里每轮纯读自检一次，发现差异就落库 + 日志 + 微信推送（仅新增/变化时）。
    try:
        _dr = shelf_check.detect(cfg, con, opt_dir=ROOT, log=t.log)
        _items = []
        for _k, _kind in (("S1", "unmapped_shelf"), ("S2", "mismatched_pack"),
                          ("S3", "orphan_row")):
            for _x in (_dr.get(_k) or []):
                _x = dict(_x)
                _x["kind"] = _kind
                _items.append(_x)
        store.shelf_drift_save(con, ts, _items)
        for _s in (_dr.get("skipped") or []):
            t.log("  [货架自检] %s" % _s)
        if _items:
            t.log("  ⚠ [货架自检] 发现 %d 项差异（未纳管 %d / 映射错位 %d / 人工价暴露 %d）"
                  % (len(_items), len(_dr.get("S1") or []), len(_dr.get("S2") or []),
                     len(_dr.get("S3") or [])))
            for _x in _items[:20]:
                t.log("      · %s" % _x.get("detail"))
            _prev = store.alert_state_map(con)
            _res = shelf_notify.notify_new(cfg, _items, set(_prev.keys()), log=t.log)
            if _res.get("推送"):
                t.log("  [货架自检] 已推送微信 %d 项" % _res["推送"])
            store.alert_state_prune(con, _res.get("签名") or [])
            store.alert_state_upsert(con, [
                {"sig": _s, "last_ts": ts, "last_detail": ""}
                for _s in (_res.get("签名") or [])])
        else:
            store.alert_state_prune(con, [])
    except Exception:
        t.log("  ⚠ 货架自检失败（不影响本轮跟价）：%s" % traceback.format_exc()[-300:])

    # ---- 3.5) 金币（Gold）----
    # 金币与物品**不是一套机制**：一行 = 一个服务区，可改量是「采购成本」（￥/M），
    # 改完必须点后台「同步价格」前端才刷新（且 🔴 绝不勾「所有区」）。
    # 这里只采数与算目标采购成本，写价由本机执行器 writegold 做（服务器 IP 进不了后台）。
    # 2026-10-01 多游戏：金币专线可能同时挂多个游戏（暗黑4 + AION2），
    #   所以「要不要跑金币」= 有没有**任一**金币游戏到期；跑起来会一次抓全部服务区。
    #   AION2 目前没有对照项、不在 track_games 里，跟着暗黑4 的 1h 周期一起采。
    _goldgames = core_gold.game_names(cfg)
    _goldgame = ("、".join(_goldgames) if _goldgames
                 else str(cfg_get(cfg, "金币.挂载游戏", "暗黑破坏神4") or "暗黑破坏神4"))
    _gold_due = bool(core_gold.enabled(cfg) and any(g in due for g in _goldgames))
    # ---- 3.5) DD373 进货成本（**先采**）──────────────────────────────────
    # ⚠ 2026-10-02 顺序反转：改用「DD373 推荐价 + 加价%」定价后，**目标价依赖成本**，
    #   所以成本必须先落库、再算价。原先成本在 3.6 采、算价在 3.5，
    #   新策略下那样会永远读到**上一轮**的成本（首轮更是全空 → 34 区全 hold）。
    #   仍保持独立表 gold_cost —— 只是现在它从「只读监控」升级为「定价输入」。
    _costcfg = (cfg.get("金币") or {}).get("进货成本") or {}
    _cost_game = str(_costcfg.get("游戏") or "AION2")
    _pol_aion2 = core_gold.pricing_policy(cfg, _cost_game) or {}
    if _costcfg.get("启用") and _gold_due:
        try:
            t.collect_gold_cost(cfg, con, ts, log=t.log, force=force)
        except Exception:
            t.log("  ✘ DD373 成本采集失败（不影响跟价）：%s" % traceback.format_exc()[-400:])
    elif core_gold.enabled(cfg):
        t.log("  [金币] %s 本轮未到期，跳过金币算价" % _goldgame)
        t.log("  [成本] DD373 进货成本未启用或本轮未到期，跳过")

    # 把本轮成本注入算价（DD373 成本 2026-10-06 起是**定价输入**，不只是监控）：
    #   · dd373_markup → 直接拿它当定价基准（三级顺延的第 1 级）；
    #   · g2g_cheapold → 拿它做「成本兜底（竞品低于成本就按成本价）+ 利润率下限 −10%」。
    _dd_costs = {}
    if _pol_aion2.get("模式") in ("dd373_markup", "g2g_cheapold", "dd373_only") \
            and _costcfg.get("启用"):
        try:
            def _avail_wan(_s):
                """从 gold_cost.stock 文本（「可买79390万基纳」）解析可买量（万基纳）。

                ⚠ gold_cost 表**没有**数字型的可买量列，只有这句文本（由
                  core_dd373_cost 生成）。dd373_only 的「不足 1 亿 → 无货兜底」判定
                  要用数字，所以在注入时解析一次。
                  解析失败返回 None ⇒ core_gold 按「有货」处理（宁可正常定价，
                  也不要把真有货的区误挂成 $19.9）。
                """
                _m = re.search(r"可买\s*([0-9]+(?:\.[0-9]+)?)\s*万基纳", str(_s or ""))
                if not _m:
                    return None
                try:
                    return float(_m.group(1))
                except (TypeError, ValueError):
                    return None

            for _r in store.gold_cost_latest(con, game=_cost_game):
                _dd_costs[_r.get("key")] = {
                    "ok": _r.get("ok"), "cny_per_wan": _r.get("cny_per_wan"),
                    "usd_per_m": _r.get("usd_per_m"), "n_items": _r.get("n_items"),
                    "dd_zone": _r.get("dd_zone"), "basis": _r.get("basis"),
                    "note": _r.get("note"), "stock": _r.get("stock"),
                    # 2026-10-06 dd373_only 用：可买量（万基纳，数字）
                    "avail_wan": _avail_wan(_r.get("stock"))}
        except Exception:
            t.log("  ⚠ 读 gold_cost 失败（%s 本轮无成本 → 全部 hold）"
                  % _pol_aion2.get("口径"))
        t.log("  [定价] 注入 DD373 成本 %d 条到 build_plan（有效 %d）"
              % (len(_dd_costs), sum(1 for v in _dd_costs.values() if v.get("ok"))))

    # ---- 3.6) 金币（Gold）· 算目标采购成本 ----
    # 金币与物品**不是一套机制**：一行 = 一个服务区，可改量是「采购成本」（￥/M），
    # 改完必须点后台「同步价格」前端才刷新（且 🔴 绝不勾「所有区」）。
    # 2026-10-01 多游戏：金币专线可能同时挂多个游戏（暗黑4 + AION2），
    #   所以「要不要跑金币」= 有没有**任一**金币游戏到期；跑起来会一次抓全部服务区。
    if _gold_due:
        try:
            gp = core_gold.build_plan(cfg, log=t.log,
                                      known=store.gold_state_map(con),
                                      dd373_costs=_dd_costs)
            store.save_gold(con, ts, gp)
            # 2026-10-02：记「真实发生的调价」（对比上轮我方前端价）→ 看板「改价操作」列
            try:
                _na, _acts = store.gold_action_detect(con, ts, gp)
                if _na:
                    t.log("  [改价台账] 检测到 %d 个服务区售价发生变化 → 表 gold_action" % _na)
                    for _o in _acts[:8]:
                        t.log("      %-22s $%.4f → $%.4f（%+.2f%%）"
                              % (_o["key"], _o["old"], _o["new"], _o["delta_pct"]))
            except Exception:
                t.log("  ⚠ 改价台账写入失败（不影响跟价）：%s"
                      % traceback.format_exc()[-200:])
            t.log("  [金币] 本轮到期的金币游戏：%s ｜ 本轮一并采 %d 个服务区"
                  % ("、".join(g for g in _goldgames if g in due) or _goldgame,
                     len(gp.get("items") or [])))
            _pp = (gp.get("定价策略") or {}).get("AION2")
            if _pp:
                t.log("  [金币] AION2 定价模式：%s ｜ %s" % (_pp.get("模式"), _pp.get("口径")))
            for it in gp["items"]:
                if it.get("定价模式") == "dd373_only":
                    if (it.get("定价来源级别") or 0) == 1:
                        t.log("  [金币] %-22s DD373进货 $%s/M（%s 元/万基纳·可买 %s 万基纳）"
                              "+%.1f%% → 目标采购成本 %s ｜ %s"
                              % (it.get("中文名"), it.get("DD373成本_USD每M"),
                                 it.get("DD373成本_元每万基纳"),
                                 ("%.0f" % it["DD373可买_万基纳"])
                                 if it.get("DD373可买_万基纳") is not None else "-",
                                 (it.get("加价比例") or 0) * 100,
                                 it.get("采购成本_新"), it.get("动作") or "-"))
                    else:
                        t.log("  [金币] %-22s ⛔无货兜底 $%s/M ｜ %s ｜ %s"
                              % (it.get("中文名"), it.get("无货兜底售价_USD每M"),
                                 it.get("无货兜底说明") or "",
                                 it.get("动作") or "-"))
                elif it.get("定价模式") == "dd373_markup":
                    t.log("  [金币] %-22s DD373 $%s（%s 条挂单）+%.1f%% → 目标采购成本 %s ｜ %s"
                          % (it.get("中文名"), it.get("DD373成本_USD每M"),
                             it.get("DD373挂单数"),
                             (it.get("加价比例") or 0) * 100,
                             it.get("采购成本_新"), it.get("动作") or "-"))
                elif it.get("定价模式") == "g2g_cheapold":
                    _tflag = ""
                    if it.get("目标来自成本兜底"):
                        _tflag = " ⛔成本兜底(竞品$%s<成本$%s)" % (
                            it.get("基准价_原竞品"), it.get("DD373成本_USD每M"))
                    if it.get("利润率下限触发"):
                        _tflag += " ⛔利润下限"
                    t.log("  [金币] %-22s G2G %s $%s −%.0f%% → 目标采购成本 %s ｜ %s%s"
                          % (it.get("中文名"), it.get("基准来源") or "-",
                             it.get("基准价"), (it.get("下浮比例") or 0.03) * 100,
                             it.get("采购成本_新"), it.get("动作") or "-", _tflag))
                else:
                    t.log("  [金币] %-22s 利润率 %s ｜ 我方每M %s ｜ IGGM每M %s ｜ 目标采购成本 %s ｜ %s"
                          % (it.get("中文名"), it.get("利润率"),
                             it.get("我方前端每M"), it.get("IGGM每M_跟价用"),
                             it.get("采购成本_新"), it.get("动作") or "-"))
                if it.get("错误"):
                    t.log("      ⚠ %s" % it["错误"])
        except Exception:
            t.log("  ✘ 金币抓取失败（不影响物品跟价）：%s" % traceback.format_exc()[-400:])

    # ---- 4) 引擎 ----
    qd_map = build_qd_map(cfg, con, qd_ts) if qd_ts else {}
    # 后台折扣变了？→ 让这些游戏**跳过「IGGM 未变价就不评估」这道闸**（用户要求：
    # 改了折扣，标价必须跟着重算，否则前端价凭空贵 1/旧折扣 − 1）。
    _dcg = disc_changed_games(cfg, our_map=ours_now, log=t.log)
    # 🔴 只评估**到期**游戏的对照项：没到期的游戏这一轮一律不动它。
    _all_items = cfg["商品映射"].get("对照项") or []
    _items_due = [it for it in _all_items if it.get("游戏") in due]
    t.log("  评估范围 %d/%d 条对照项（只含本轮到期的游戏）"
          % (len(_items_due), len(_all_items)))
    # 按行 pending 闩（2026-09-29）：近 N 小时内已出过单的行，若我方价还没变成
    # 单要求的价格（前台生效慢，实测最长 5h57m），本轮**不重复出单**。
    _lp_map = line_pending_map(cfg, con, log=t.log)
    if _lp_map:
        t.log("  按行 pending 闩：%d 行在窗口（%s 小时）内有已派发的工单 ——"
              "其中前台还没生效的行，本轮不再重复出单"
              % (len(_lp_map), cfg_get(cfg, "跟价.按行pending.保留小时", 8)))
    _brows = engine.load_backend_rows(cfg, log=t.log)
    decisions = engine.evaluate(cfg, _items_due, iggm_now, iggm_prev,
                                ours_now, qd_map, ts, log=t.log,
                                disc_changed_games=_dcg,
                                manual_override=store.manual_override_map(con),
                                line_pending=_lp_map, backend_rows=_brows)  # ── 闸一装载 2026-10-05 ──
    disc_settle(cfg, decisions, _dcg, our_map=ours_now, log=t.log)
    for d in decisions:
        store.add_decision(con, ts, d, applied=0)
    t.log("数据：IGGM %d 项 ｜ 我方 %d 项 ｜ 成本 %d 项 ｜ 上轮基线 %d 项 ｜ 汇率 %s"
          % (len(iggm_now), len(our_rows), len(qd_map), len(iggm_prev),
             cfg_get(cfg, "汇率.USDCNY", 6.65)))
    sm = emit_record(t, "采集一轮", t_start, decisions,
                     extra="IGGM %d 项 / 我方 %d 项 / 成本 %d 项"
                           % (len(iggm_now), len(our_rows), len(qd_map)))

    store.record_run(con, ts, iggm_count=len(iggm_now), qd_count=len(qd_map),
                     our_count=len(our_rows), follows=sm["actionable"], blocked=sm["blocked"],
                     elapsed_s=0, mode=mode, note="web-collect")
    store.purge(con, int(cfg_get(cfg, "运行.保留天数", 365) or 365))

    # ---- 5) 自动跟价：有可执行改价就自动出单 + 派单（执行方见 跟价.执行方式）
    #      开关没开时这里只是一行日志，行为与以前完全一致。
    _auto_dispatch(t, cfg, con)

    # 同步刷一份离线看板 HTML
    try:
        import build_dashboard
        outdir = os.path.join(ROOT, cfg_get(cfg, "运行.输出目录", "output"))
        os.makedirs(outdir, exist_ok=True)
        _gnow, _gts = store.gold_latest(con)
        build_dashboard.build(cfg, con, ts, decisions, iggm_now, iggm_prev, ours_now, qd_map,
                              log=lambda *a: None, gold=_gnow, gold_ts=_gts,
                              out_path=os.path.join(outdir, "自动改价看板.html"))
    except Exception:
        t.log("  ⚠ 离线看板 HTML 生成失败（不影响在线看板）：%s"
              % traceback.format_exc()[-300:])

    # ---- 6) 记下这几个游戏本轮真的跑完了（决定下一次什么时候到期）----
    sched_mark(cfg, due, ts)
    t.log("  已记周期：%s" % "、".join("%s→%s" % (g, ts) for g in due))
    return {"ts": ts, "due": due}


def task_rebuild(t, opts):
    """不联网，按库里已有数据重算评估 + 重出看板"""
    cfg = load_cfg()
    t_start = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t.log("══ 重算看板（不联网）══ 起 %s" % t_start)
    con = open_db()
    ig_ts = latest_ts(con, "iggm_price")
    qd_ts = latest_ts(con, "qd_cost")
    if not ig_ts:
        raise RuntimeError("库里还没有 IGGM 快照，请先跑一次「采集」")

    iggm_now = {r["goods_no"]: r for r in store.iggm_rows(con, ig_ts)}
    prev_t = store.prev_ts(con, "iggm_price", ig_ts)
    iggm_prev = {r["goods_no"]: r for r in (store.iggm_rows(con, prev_t) if prev_t else [])}
    our_map, our_ts = store.our_latest(con)
    qd_map = build_qd_map(cfg, con, qd_ts) if qd_ts else {}
    if not our_map:
        t.log("  ⚠ 库里没有我方价格，目标价与毛利率会算不出来")

    ts = dt.datetime.now().isoformat(timespec="seconds")
    _dcg = disc_changed_games(cfg, our_map=our_map, log=t.log)
    _brows = engine.load_backend_rows(cfg, log=t.log)
    decisions = engine.evaluate(cfg, cfg["商品映射"]["对照项"], iggm_now, iggm_prev,
                                our_map, qd_map, ts, log=t.log,
                                disc_changed_games=_dcg,
                                manual_override=store.manual_override_map(con),
                                line_pending=line_pending_map(cfg, con, log=t.log), backend_rows=_brows)
    disc_settle(cfg, decisions, _dcg, our_map=our_map, log=t.log)
    for d in decisions:
        store.add_decision(con, ts, d, applied=0)
    t.log("数据：IGGM %d 项 ｜ 我方 %d 项 ｜ 成本 %d 项 ｜ 上轮基线 %d 项"
          % (len(iggm_now), len(our_map), len(qd_map), len(iggm_prev)))
    sm = emit_record(t, "重算看板", t_start, decisions,
                     extra="IGGM %d 项 / 我方 %d 项 / 成本 %d 项"
                           % (len(iggm_now), len(our_map), len(qd_map)))
    store.record_run(con, ts, iggm_count=len(iggm_now), qd_count=len(qd_map),
                     our_count=len(our_map), follows=sm["actionable"], blocked=sm["blocked"],
                     elapsed_s=0, mode=str(cfg_get(cfg, "跟价.模式", "OFF")), note="web-rebuild")

    # 同步刷一份离线看板 HTML
    # （2026-09-24 修：原来这里只重算决策、**不重出 HTML**，按钮叫「重算看板」却看不到变化）
    try:
        import build_dashboard
        outdir = os.path.join(ROOT, cfg_get(cfg, "运行.输出目录", "output"))
        os.makedirs(outdir, exist_ok=True)
        _gnow, _gts = store.gold_latest(con)
        out_path = os.path.join(outdir, "自动改价看板.html")
        build_dashboard.build(cfg, con, ts, decisions, iggm_now, iggm_prev, our_map, qd_map,
                              log=t.log, gold=_gnow, gold_ts=_gts, out_path=out_path)
        t.log("  看板已重出：%s" % out_path)
    except Exception:
        t.log("  ⚠ 离线看板 HTML 生成失败（不影响在线看板）：%s"
              % traceback.format_exc()[-300:])
    return {"ts": ts}


def task_simulate(t, opts):
    """模拟：把 IGGM 价按指定变化喂给引擎，看我们会怎么跟（不写任何数据）"""
    import copy
    cfg = load_cfg()
    pct = opts.get("pct")
    goods = opts.get("goods") or {}
    real_mode = str(cfg_get(cfg, "跟价.模式", "OFF")).upper()
    mode = str(opts.get("mode") or "AUTO").upper()

    t_start = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t.log("══ 跟价模拟 ══ 起 %s ｜ 真开关 %s → 按 %s 推演（不改 config、不写库、不发请求）"
          % (t_start, real_mode, mode))
    con = open_db()
    ig_ts = latest_ts(con, "iggm_price")
    if not ig_ts:
        raise RuntimeError("库里还没有 IGGM 快照，请先跑一次「采集」")
    base = {r["goods_no"]: r for r in store.iggm_rows(con, ig_ts)}

    changes = {}
    if goods:
        for k, v in goods.items():
            if k in base:
                changes[k] = float(v)
        label = "指定价 %s" % ", ".join("%s→$%s" % (k[:10], v) for k, v in list(changes.items())[:5])
    else:
        if pct is None:
            pct = 10.0
        changes = {k: round(r["price_usd"] * (1 + pct / 100.0), 6) for k, r in base.items()
                   if r.get("price_usd")}
        label = "IGGM 全部 %+.1f%%" % pct
    if not changes:
        raise RuntimeError("没有可模拟的商品（changes 为空）")

    c2 = copy.deepcopy(cfg)
    c2["跟价"]["模式"] = mode
    qd_map = build_qd_map(cfg, con, latest_ts(con, "qd_cost")) if latest_ts(con, "qd_cost") else {}
    our_map, _ = store.our_latest(con)

    ig_new = {k: dict(v) for k, v in base.items()}
    for k, v in changes.items():
        ig_new[k]["price_usd"] = v

    decisions = engine.evaluate(c2, c2["商品映射"]["对照项"], ig_new, base, our_map, qd_map,
                                dt.datetime.now().isoformat(timespec="seconds"),
                                log=lambda *a: None,
                                manual_override=store.manual_override_map(con),
                                line_pending=line_pending_map(cfg, con))
    t.log("场景：%s ｜ 基线快照 %s（%d 个商品）" % (label, ig_ts, len(base)))
    sm = emit_record(t, "模拟跟价 · %s" % label, t_start, decisions,
                     extra="场景 %s / 基线 %s" % (label, ig_ts))
    if real_mode == "OFF":
        t.log("注意：真实开关仍是 OFF —— 以上仅为 AUTO 推演，本轮不会执行任何改价。")

    outdir = os.path.join(ROOT, "output")
    os.makedirs(outdir, exist_ok=True)
    fp = os.path.join(outdir, "模拟跟价_%s.md" % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    try:
        with open(fp, "w", encoding="utf-8") as f:
            f.write("\n".join(t.lines))
        t.log("报告已存：%s" % fp)
    except Exception:
        pass
    return {"scenario": label, "actionable": sm["actionable"]}


def task_plan(t, opts):
    """生成改价计划（DRY-RUN）：只算不改，产出可审阅的清单"""
    cfg = load_cfg()
    mode = str(cfg_get(cfg, "跟价.模式", "OFF")).upper()
    t_start = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _st = switch_state(cfg)
    t.log("══ 改价计划 DRY-RUN ══ 起 %s ｜ 系统总开关 %s ｜ 自动跟价 %s ｜ 无单轮上限"
          % (t_start, "开启" if _st["master"] else "关闭",
             "开启" if _st["auto"] else "关闭"))

    con = open_db()
    ts = latest_ts(con, "decisions")
    if not ts:
        raise RuntimeError("还没有决策数据，请先「采集」或「重算看板」")
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM decisions WHERE ts=? ORDER BY key", (ts,))]

    # 标价换算：决策里的 ours_new 是标价口径，现价也必须用标价。
    # ours_bid 不是 decisions 表的列，从库里读出来是空的 → 用 前端价 ÷ 折扣 反推。
    # 2026-09-25：折扣改为按商品/按游戏取（暗黑4=90、POE2=100）。
    # 2026-09-27：折扣优先取**前端实测值**（与引擎 evaluate 完全同一口径，
    #   否则「页面上算出来的标价」与「工单里要写的标价」会差一个折扣）。
    _k2it = {it["key"]: it for it in cfg["商品映射"]["对照项"]}
    _our_now, _ = store.our_latest(con)
    for _d in rows:
        if _d.get("ours_old") and not _d.get("ours_bid"):
            _disc = disc_of_key(cfg, _our_now, _d["key"], _k2it)
            _d["ours_bid"] = _d["ours_old"] / _disc

    # 勾选表：没勾的商品即使历史决策里带了目标价，也不进本轮计划
    _on = {it["key"]: (it.get("跟价", True) is not False)
           for it in cfg["商品映射"]["对照项"]}
    plan, skipped = [], []
    for d in rows:
        if not _on.get(d["key"], True):
            continue
        if d["action"] not in ("follow_up", "follow_down"):
            continue
        if d.get("ours_new") is None or d.get("ours_bid") is None:
            skipped.append((d, "缺目标价或现价"))
            continue
        delta = d["ours_new"] - d["ours_bid"]
        if abs(delta) < 1e-9:
            skipped.append((d, "目标价与现价相同"))
            continue
        plan.append(d)
    lines = ["%s：标价 %s → %s（%+.4f, %+.2f%%）｜毛利 %.1f%% → %.1f%% ［%s］"
             % (d["title"], _usd(d["ours_bid"]), _usd(d["ours_new"]),
                d["ours_new"] - d["ours_bid"], _chg_pct(d["ours_bid"], d["ours_new"]) or 0.0,
                (d.get("margin_old") or 0) * 100, (d.get("margin_new") or 0) * 100,
                "涨" if d["ours_new"] > d["ours_bid"] else "降")
             for d in plan]
    why_cnt = {}
    for _d, _why in skipped:
        k = _why.split("（")[0].split("(")[0].strip()
        why_cnt[k] = why_cnt.get(k, 0) + 1
    summary = ("可执行 %d 件（涨 %d / 降 %d）｜ 未纳入 %d 件"
               % (len(plan),
                  sum(1 for d in plan if d["ours_new"] > d["ours_bid"]),
                  sum(1 for d in plan if d["ours_new"] < d["ours_bid"]),
                  len(skipped)))
    t.log("── 改动记录 ──")
    if lines:
        for s in lines:
            t.log("  " + s)
    else:
        t.log("  无（没有可执行的改价）")
    t.log("── 小结 ──")
    t.log("  " + summary)
    if why_cnt:
        t.log("  未纳入原因：" + " / ".join("%s %d" % (k, v) for k, v in why_cnt.items()))
    try:
        t.log("  已追加记录：%s"
              % _changelog_write("改价计划 DRY-RUN", t_start, lines, summary,
                                 extra="依据决策快照 %s（共 %d 条）" % (ts, len(rows))))
    except Exception as e:
        t.log("  ⚠ 改动记录写文件失败：%r" % e)

    outdir = os.path.join(ROOT, "output")
    os.makedirs(outdir, exist_ok=True)
    fp = os.path.join(outdir, "改价计划_%s.json" % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    payload = {"ts": ts, "mode": mode, "dry_run": True,
               "count": len(plan),
               "价格口径": "old / new 都是后台「$每个价格」的标价；front_old 是客户看到的前端价",
               "items": [{"key": d["key"], "title": d["title"],
                          "old": d["ours_bid"], "new": d["ours_new"],
                          "front_old": d.get("ours_old"),
                          "item_id": cfg_get(cfg, "p2pah.商品ID映射." + d["key"])}
                         for d in plan],
               "skipped": [{"key": d.get("key"), "why": w} for d, w in skipped]}
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    t.log("计划文件：%s" % fp)
    t.log("提示：真正下发需要 ①系统总开关=开启 ②页面输入确认短语 ③后台账号已配置")
    return {"plan": fp, "count": len(plan)}


def game_gid_of(cfg, key):
    """该 key 属于哪个游戏的后台 gid（暗黑4=456、POE2=552）。

    ⚠ 2026-09-25 修：以前直接 `p2pah.游戏.get(对照项.游戏)`，但对照项写的是中文名
    （流放之路2），而 p2pah.游戏 的键是短码（POE2）→ 静默回退 456，POE2 的价会被
    当作 D4 去写。现在统一委托 engine.game_gid（带 `p2pah.游戏别名` 兼容）。
    """
    return engine.game_gid(cfg, key)


def _p2pah_ids(cfg, key):
    """后台商品ID列表。重复上架的（如 CRUX_X10 两条）一并返回 —— 少改一条前端可能仍是旧价。"""
    m = cfg_get(cfg, "p2pah.商品ID映射") or {}
    ids = []
    if isinstance(m.get(key), str):
        ids.append(m[key])
    dup = (m.get("_重复上架") or {}).get(key)
    if isinstance(dup, list):
        ids += [str(x) for x in dup]
    seen, out = set(), []
    for i in ids:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def task_apply(t, opts):
    """生成「改价工单」。

    ⚠ 为什么不是直接改价：**本服务的 IP 打不通改价后台**。
    2026-09-23 实测对照（同一个会话 cookie，同一个商品列表地址）：
        本机（家用 IP）        → HTTP 200 / 450KB / 201 行
        本机服务器（阿里云美区） → HTTP 404 / 0 字节
    即 order.p2pah.cn 按来源 IP 拦了机房 IP。所以这里只负责「算准 + 出工单」，
    真正的写请求由能打开后台的机器上的 `p2pah_local.py write --plan <工单> --confirm` 发。
    """
    cfg = load_cfg()
    st = switch_state(cfg)
    confirm = str(opts.get("confirm") or "").strip()

    t.log("=== 生成改价工单 === 系统总开关 %s ｜ 自动跟价 %s"
          % ("开启" if st["master"] else "关闭", "开启" if st["auto"] else "关闭"))
    if not st["master"]:
        raise RuntimeError("系统总开关是「关闭」，已拦截。请先在控制台打开「系统总开关」。")
    if confirm != "确认改价":
        raise RuntimeError("缺少确认短语（需输入：确认改价）")
    if not (cfg_get(cfg, "p2pah.账号.username")):
        raise RuntimeError("未配置 order.p2pah.cn 后台账号（config.json → p2pah.账号）。")

    # 2026-09-25：折扣按商品/按游戏取（暗黑4=90、POE2=100）。工单里逐件带「折扣」，
    # 执行器/复核一律按 items[].折扣 算前端价，不再假设全局 90。
    # 2026-09-27：优先采信**前端实测折扣**（与 engine.evaluate、看板三处口径一致）。
    _k2it = {it["key"]: it for it in cfg["商品映射"]["对照项"]}
    _our_now = {}                            # 下面 open_db() 之后再取（这里还没有连接）

    def _disc_of_key(k):
        return disc_of_key(cfg, _our_now, k, _k2it)

    _disc = engine.disc_of(cfg, {})          # 全局兜底值（仅作工单元信息）

    con = open_db()
    ts = latest_ts(con, "decisions")
    if not ts:
        raise RuntimeError("还没有决策数据，请先「采集」或「重算看板」")
    _our_now, _ = store.our_latest(con)      # 供 _disc_of_key 取前端实测折扣
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM decisions WHERE ts=? ORDER BY key", (ts,))]
    for _d in rows:                     # ours_new 是标价口径，现价也必须用标价
        if _d.get("ours_old") and not _d.get("ours_bid"):
            _d["ours_bid"] = _d["ours_old"] / _disc_of_key(_d["key"])

    _on = {it["key"]: (it.get("跟价", True) is not False)
           for it in cfg["商品映射"]["对照项"]}
    plan, skipped = [], []
    for d in rows:
        if not _on.get(d["key"], True):
            continue
        if d["action"] not in ("follow_up", "follow_down"):
            continue
        if d.get("ours_new") is None or d.get("ours_bid") is None:
            skipped.append((d, "缺目标价或现价"))
            continue
        delta = d["ours_new"] - d["ours_bid"]
        if abs(delta) < 1e-9:
            skipped.append((d, "目标价与现价相同"))
            continue
        ids = _p2pah_ids(cfg, d["key"])
        if not ids:
            skipped.append((d, "后台没有登记商品ID"))
            continue
        plan.append(d)

    t.log("依据决策快照 %s（共 %d 条）" % (ts, len(rows)))
    if not plan:
        t.log("── 小结 ──")
        t.log("  没有可执行的改价（竞品本轮无变化，或全被现有闸门拦下）")
        if skipped:
            why = {}
            for _d, _w in skipped:
                why[_w] = why.get(_w, 0) + 1
            t.log("  未纳入：" + " / ".join("%s %d件" % (k, v) for k, v in why.items()))
        return {"count": 0, "ticket": None}

    items = []
    t.log("── 工单明细（%d 件）──" % len(plan))
    for d in plan:
        ids = _p2pah_ids(cfg, d["key"])
        _dsc = _disc_of_key(d["key"])
        tgt_front = d["ours_new"] * _dsc
        items.append({
            "key": d["key"], "title": d["title"], "ids": ids,
            "gid": game_gid_of(cfg, d["key"]),
            "后台折扣": _dsc * 100.0,
            "old": d["ours_bid"], "new": d["ours_new"],
            "front_old": d.get("ours_old"), "front_new": tgt_front,
            "iggm_new": d.get("iggm_new"), "margin_new": d.get("margin_new"),
            "direction": "涨" if d["ours_new"] > d["ours_bid"] else "降",
            "reason": d.get("reason"),
        })
        t.log("  %-24s 后台ID %-24s 标价 %s → %s（%s）｜目标前端 %s ｜毛利 %s"
              % (d["key"], ",".join(ids), _usd(d["ours_bid"]), _usd(d["ours_new"]),
                 items[-1]["direction"], _usd(tgt_front),
                 ("%.1f%%" % ((d.get("margin_new") or 0) * 100))))

    # 清缓存是「改价完整生效」的最后一步。要不要做由 config 决定，只把「意图」写进工单，
    # 由执行方（服务器容器 / 本机执行器）读取后执行。
    # 2026-09-27：新机 IP 已进 order.p2pah.cn 白名单，服务器自己就能改价 + 清缓存。
    _cf = (cfg.get("跟价") or {}).get("缓存刷新") or {}
    _want_cache = bool(_cf.get("自动刷新", True))
    _exec_mode = str(cfg_get(cfg, "跟价.执行方式", "server")).lower()
    _exec_mode = "local" if _exec_mode == "local" else "server"

    outdir = os.path.join(ROOT, "output")
    os.makedirs(outdir, exist_ok=True)
    fp = os.path.join(outdir, "改价工单_%s.json" % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    payload = {
        "kind": "p2pah-apply-ticket",
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "决策快照": ts, "系统总开关": st["master"],
        "后台折扣": "逐件见 items[].后台折扣（暗黑4=90 / POE2=100）；全局默认 %s"
                    % (_disc * 100.0), "count": len(items), "items": items,
        # 清缓存「意图」：由本工单的执行方读取后执行
        "clearcache": _want_cache,
        "clearcache_来源": "config 跟价.缓存刷新.自动刷新 = %s" % _want_cache,
        "clearcache_执行方": "由本工单的执行方执行（服务器容器 srv_exec.py / 本机执行器）",
        "skipped": [{"key": d.get("key"), "why": w} for d, w in skipped],
        "执行方": ("服务器（容器 p2pah-srv:1，服务器侧直连 order.p2pah.cn）"
                 if _exec_mode == "server" else
                 "本机执行器（人工改派，服务器侧不执行）"),
        "手动复现": "python p2pah_local.py write --plan <本文件> --confirm"
                "（改价成功且复核通过后会自动执行后台「清除全部」；加 --no-clearcache 跳过）",
        "白名单": "2026-09-27 起新机 IP 47.85.224.112 已在 order.p2pah.cn 白名单内"
                "（同一 cookie 同一受保护页：新机与本机 200/107017 字节、md5 一致），"
                "服务器可自行登录改价；换机需重新申请。",
        "价格口径": "old / new 都是后台「$每个价格」(unit_price)；front = unit_price × 后台折扣",
    }
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    t.log("── 小结 ──")
    t.log("  工单已生成：%s" % fp)
    t.log("  清缓存意图：%s" % ("清" if _want_cache else "不清（config 里已关）"))
    t.log("  执行方：%s"
          % ("服务器容器 p2pah-srv:1" if _exec_mode == "server" else "本机执行器"))
    try:
        _jid = store.local_job_add(
            con, kind="write", title="物品改价 %d 件" % len(items),
            plan_path=fp, plan=payload,
            summary="、".join("%s %s→%s" % (i["key"], _usd(i["old"]), _usd(i["new"]))
                              for i in items),
            actor=str(opts.get("actor") or ""), exec_mode=_exec_mode)
        if _exec_mode == "server":
            t.log("  ▶ 已派给服务器执行器：任务 %s（服务器在跑就自动执行）" % _jid)
            t.log("    服务器执行器不在线时会排队等待，不会丢单；"
                  "也可在看板把这一单改成「由本机执行」")
        else:
            t.log("  ▶ 已派发本机执行器：任务 %s（本机在线即自动执行）" % _jid)
            t.log("    本机离线时会排队等待，不会丢单；"
                  "也可在看板把这一单改回「由服务器执行」")
    except Exception as e:
        t.log("  ⚠ 派单失败（工单已落盘，可手工执行）：%r" % e)
    try:
        t.log("  已追加记录：%s" % _changelog_write(
            "改价工单", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ["%s：标价 %s → %s" % (i["title"], _usd(i["old"]), _usd(i["new"]))
             for i in items],
            "工单 %d 件" % len(items), extra="依据决策快照 %s" % ts))
    except Exception as e:
        t.log("  ⚠ 改动记录写文件失败：%r" % e)
    return {"count": len(items), "ticket": fp}




def task_gold_apply(t, opts):
    """生成「金币改价工单」。**只算不改** —— 真正的写请求由执行方发（默认服务器）。

    金币与物品**不是一套机制**（2026-09-24 探明并实测通过）：
      · 金币一行 = 一个服务区，唯一可改的量是「采购成本」（￥/M）；
        换算：前端每M价($) = 采购成本 ÷ 汇率 ÷ (1−利润率)；
        反用：目标采购成本 = 目标每M价 × 汇率 × (1−利润率)。
      · 改价是**两步**：① 改采购成本 → ② 点后台右上角的**刷新图标「更新b2c网站」**
        （`.jq-getweb` → `saveprice.html?getweb=1`）。
        ⚠️ 只点文案为「同步价格」的那个按钮（`getweb=0`）**推不动前端**（2026-09-24 实测）。
        **只做①前端不会刷新**；②的表单里 🔴 绝不能勾「所有区」(allserver)。
    2026-09-27：新机 IP 已在 order.p2pah.cn 白名单内（同一会话 cookie 同一受保护页，
    新机与本机 200/107017 字节、md5 一致），所以**服务器自己就能执行**这张单。
    执行方由 config「跟价.执行方式」决定（server = 服务器容器 srv_exec.py；
    local = 本机执行器）。手工复现：

        python p2pah_local.py writegold --plan "<金币工单>" --confirm
    """
    cfg = load_cfg()
    st = switch_state(cfg)
    confirm = str(opts.get("confirm") or "").strip()
    t.log("=== 生成金币改价工单 === 系统总开关 %s"
          % ("开启" if st["master"] else "关闭"))
    if not st["master"]:
        raise RuntimeError("系统总开关是「关闭」，已拦截。请先在控制台打开「系统总开关」。")
    if confirm != "确认改价":
        raise RuntimeError("缺少确认短语（需输入：确认改价）")

    con = open_db()
    rows, gts = store.gold_latest(con)
    if not rows:
        raise RuntimeError("库里还没有金币数据，请先跑一轮「采集」。")

    # 2026-10-01 金币工单闸门：config.金币.服务区[].仅检测 = true 的服务区
    #   照常参与采集与评估（看板/控制台都能看到 IGGM 变价与差距），
    #   但**不进本单**——不派单、不写后台。AION2 刚上线，用户口径「只做检测不自动改价」。
    #   注意：不能用 跟价=false 表达「只检测」，那会让该行在 task_collect 阶段就跳过，连数据都没有。
    _svs = core_gold.servers_of(cfg)
    on = {sv.get("key"): (sv.get("跟价", True) is not False) for sv in _svs}
    detect_only = {sv.get("key") for sv in _svs if sv.get("仅检测")}
    keep, skipped = [], []
    for r in rows:
        act = str(r.get("action") or "hold")
        if not on.get(r.get("key"), True):
            skipped.append((r, "config 里未勾选跟价"))
            continue
        if r.get("key") in detect_only:
            skipped.append((r, "仅检测（不自动改价）"))
            continue
        if act not in ("follow_up", "follow_down"):
            # patch7：区分「真持平」与「算出来能改、但前端显示价无差别」（无效果闸）
            _why = "本轮已持平 / 数据缺失"
            if "无效果" in str(r.get("reason") or ""):
                _why = "前端显示价无差别（改了看不出，已省单）"
            skipped.append((r, _why))
            continue
        if r.get("cost_target") is None:
            skipped.append((r, "缺目标采购成本"))
            continue
        keep.append(r)

    t.log("依据金币快照 %s（共 %d 个服务区）" % (gts, len(rows)))
    if detect_only:
        t.log("  ℹ 其中 %d 个服务区标记为「仅检测」——只观测与出报告，本单不会改动它们。"
              % len(detect_only))
    if not keep:
        t.log("── 小结 ──")
        t.log("  没有需要改采购成本的服务区（金币价已持平）")
        if skipped:
            why = {}
            for _r, _w in skipped:
                why[_w] = why.get(_w, 0) + 1
            t.log("  未纳入：" + " / ".join("%s %d个" % (k, v) for k, v in why.items()))
        return {"count": 0, "ticket": None}

    def _pm(v):
        if v is None:
            return "-"
        try:
            f = float(v)
        except (TypeError, ValueError):
            return "-"
        return ("%.6g" % f)

    # ══════════════════════════════════════════════════════════════════
    # 按游戏分组出单（2026-10-01）
    #   执行器 p2pah_local.py 的金币列表页**按 gid 分表**，且 cmd_writegold 有硬闸：
    #   一张单里出现多个 gid ⇒ SystemExit「本单混了多个游戏的金币，拒绝执行」。
    #   所以这里必须**每个游戏一张单**：AION2(826) 一单、暗黑4(456) 一单，
    #   否则混游戏单会被执行器整单拒掉（AION2 一条都改不了）。
    #   单游戏的情况下行为与改前完全一致（只出一张单）。
    # ══════════════════════════════════════════════════════════════════
    _gm_by_key = {sv.get("key"): core_gold.server_game(cfg, sv)
                  for sv in core_gold.servers_of(cfg)}
    _by_game = {}
    _order = []
    for r in keep:
        _g_of = _gm_by_key.get(r.get("key")) or core_gold.DEFAULT_GAME
        if _g_of not in _by_game:
            _by_game[_g_of] = []
            _order.append(_g_of)
        _by_game[_g_of].append(r)

    _cf = (cfg.get("跟价") or {}).get("缓存刷新") or {}
    _want_cache = bool(_cf.get("自动刷新", True))
    _exec_mode = str(cfg_get(cfg, "跟价.执行方式", "server")).lower()
    _exec_mode = "local" if _exec_mode == "local" else "server"
    gcfg = cfg.get("金币") or {}
    outdir = os.path.join(ROOT, "output")
    os.makedirs(outdir, exist_ok=True)
    _ts_tag = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    if len(_order) > 1:
        t.log("  ℹ 本单跨 %d 个游戏（%s）—— 按游戏拆成 %d 张单（执行器不接受混游戏单）"
              % (len(_order), "、".join(_order), len(_order)))

    _tickets = []
    for _gname in _order:
        _rows_g = _by_game[_gname]
        jobs = []
        t.log("── 工单明细 · %s（%d 个服务区）──" % (_gname, len(_rows_g)))
        for r in _rows_g:
            j = {"key": r.get("key"), "中文名": r.get("title"), "游戏": _gname,
                 "后台行ID": str(r.get("row_id") or ""),
                 "采购成本_旧": r.get("cost_old"),      # 服务器读不到后台，通常是 null
                 "采购成本_新": r.get("cost_target"),
                 "利润率": r.get("margin_rate"),
                 "我方前端每M": r.get("our_per_m"), "IGGM每M": r.get("iggm_per_m"),
                 "动作": r.get("action")}
            jobs.append(j)
            t.log("  %-22s 后台行 %-7s 采购成本 → %s（%s）｜ 我方每M %s / IGGM 每M %s"
                  % (j["中文名"], j["后台行ID"], _pm(j["采购成本_新"]),
                     "涨" if j["动作"] == "follow_up" else "降",
                     _pm(j["我方前端每M"]), _pm(j["IGGM每M"])))
        t.log("  注：金币「采购成本_旧」由本机执行器现场读后台后回传（表 gold_state），"
              "服务器不登录后台；没回传过的服务区显示 - 。")

        # 自检：一张单**只许有一个游戏**（执行器硬闸会拒混游戏单）
        _gs = sorted({j.get("游戏") for j in jobs if j.get("游戏")})
        if len(_gs) != 1:
            raise RuntimeError(
                "✘ 分单自检失败：本张单的游戏集合是 %r（应恰好 1 个）。"
                "执行器会拒绝混游戏单，已中止出单。" % (_gs,))

        fp = os.path.join(outdir, "金币工单_%s_%s.json" % (_gname, _ts_tag))
        payload = {
            "kind": "p2pah-gold-apply-ticket",
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "金币快照": gts, "系统总开关": st["master"],
            "对标档位": gcfg.get("对标档位", 10000),
            "汇率": core_gold.rate_of(cfg),
            # 🔴 单游戏单：这里一定是长度 1 的列表（执行器按它选 gid）
            "游戏": sorted({j.get("游戏") for j in jobs if j.get("游戏")}),
            "count": len(jobs), "items": jobs,
            "clearcache": _want_cache,
            "clearcache_来源": "config 跟价.缓存刷新.自动刷新 = %s" % _want_cache,
            "口径": "我方前端每M价 = IGGM 每M价 × (1 − 让价百分比)；"
                    "目标采购成本 = 目标每M价 × 汇率 × (1−利润率)",
            "改价两步": "① 改采购成本（POST /game/admin_game_price/itemEdit?ids=<后台行ID>，"
                    "data_type=costprice）→ ② 点后台右上角**刷新图标「更新b2c网站」**"
                    "（saveprice.html?getweb=1&selected_web=b2c&server_id=456，返回「更新网站成功」）。"
                    "⚠️ 只点文案为「同步价格」的按钮 getweb=0 推不动前端（返回「修改价格已推送」）。"
                    "🔴 第②步表单里的「所有区」(allserver) **永不勾选**。",
            "同步说明": "只做第①步前端不会刷新 —— 必须做第②步（getweb=1）再清一次缓存，"
                    "前端约 5~15 分钟后生效（实测 13 分钟）。判断有没有推成功看**返回文案**"
                    "（「更新网站成功」= 成功），别拿前端当即时探针。",
            "执行方": ("服务器（容器 p2pah-srv:1，服务器侧直连 order.p2pah.cn）"
                     if _exec_mode == "server" else
                     "本机执行器（人工改派，服务器侧不执行）"),
            "游戏必填说明": "每个 item 的「游戏」字段决定执行器用哪个金币 gid 读后台列表"
                    "（暗黑4=456 / AION2=826）。2026-10-01 前的老工单没有这个字段，"
                    "执行器会直接拒绝执行（防止把 AION2 写到暗黑4）。"
                    "本单只含一个游戏，多个游戏会被服务端拆成多张单。",
            "手动复现": "python p2pah_local.py writegold --plan <本文件> --confirm"
                    "（会自动：写采购成本 → 点「更新b2c网站」不勾所有区 → 清缓存）",
            "白名单": "2026-09-27 起新机 IP 47.85.224.112 已在 order.p2pah.cn 白名单内"
                    "（同一 cookie 同一受保护页：新机与本机 200/107017 字节、md5 一致），"
                    "服务器可自行登录改价；换机需重新申请。",
            "skipped": [{"key": r.get("key"), "why": w} for r, w in skipped],
        }
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        t.log("── 小结 · %s ──" % _gname)
        t.log("  金币工单已生成：%s" % fp)
        t.log("  清缓存意图：%s" % ("清" if _want_cache else "不清（config 里已关）"))
        t.log("  执行方：%s"
              % ("服务器容器 p2pah-srv:1" if _exec_mode == "server" else "本机执行器"))
        _jid = None
        try:
            _jid = store.local_job_add(
                con, kind="writegold",
                title="金币改价 %s · %d 个服务区" % (_gname, len(jobs)),
                plan_path=fp, plan=payload,
                summary="、".join("%s %s" % (j["中文名"], _pm(j["采购成本_新"]))
                                  for j in jobs),
                actor=str(opts.get("actor") or ""), exec_mode=_exec_mode)
            if _exec_mode == "server":
                t.log("  ▶ 已派给服务器执行器：任务 %s（服务器在跑就自动执行）" % _jid)
                t.log("    服务器执行器不在线时会排队等待，不会丢单；"
                      "也可在看板把这一单改成「由本机执行」")
            else:
                t.log("  ▶ 已派发本机执行器：任务 %s（本机在线即自动执行）" % _jid)
                t.log("    本机离线时会排队等待，不会丢单；"
                      "也可在看板把这一单改回「由服务器执行」")
        except Exception as e:
            t.log("  ⚠ 派单失败（工单已落盘，可手工执行）：%r" % e)
        _tickets.append({"游戏": _gname, "工单": fp, "件数": len(jobs), "任务": _jid})
        try:
            t.log("  已追加记录：%s" % _changelog_write(
                "金币改价工单", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ["%s：采购成本 → %s" % (j["中文名"], _pm(j["采购成本_新"])) for j in jobs],
                "金币工单 %s %d 个服务区" % (_gname, len(jobs)),
                extra="依据金币快照 %s" % gts))
        except Exception as e:
            t.log("  ⚠ 改动记录写文件失败：%r" % e)

    return {"count": len(keep), "tickets": _tickets,
            "games": _order, "ticket": (_tickets[0]["工单"] if _tickets else None)}

    return {"count": len(jobs), "ticket": fp}


@app.route("/api/gold")
def api_gold():
    """金币最新一轮快照（给控制台/页面用，只读）"""
    cfg = load_cfg()
    con = open_db()
    rows, ts = store.gold_latest(con)
    # 2026-10-01 多游戏：金币单价的展示倍率**按游戏取**——
    #   暗黑4 单价 5e-4 量级 → ×100000 显示成「每 10 万 M」；
    #   AION2 单价本身就是 $/M（5.99 / 10.99）→ ×1 显示成「每 M」。
    #   这里给每条行补 游戏 / unit / unitLabel，前端按行取单位，
    #   避免 AION2 被全局常量 100000 放大成 $1,099,000 这种离谱数字。
    _u_cache = {}
    for r in rows:
        try:
            gm = engine.game_of(cfg, r.get("key"))
        except Exception:
            gm = None
        if gm not in _u_cache:
            _u_cache[gm] = core_gold.display_mult_of(cfg, gm)
        r["游戏"] = gm
        r["unit"] = _u_cache[gm]
        r["unitLabel"] = core_gold.unit_label(_u_cache[gm])
    # 2026-10-02 用户要求（改价时间必须是最新一次该区改价、售价不滞后）：
    #   「改价操作」列改用 gold_ticket_map —— 数据源是**执行器回填的 gold_state**
    #   （后台采购成本真值）+ 工单 finished_at（真实完成时刻）。
    #   原先用的 gold_action 是采集时对比上一轮前端价写的，慢一轮，
    #   且叠加 MMOEXP 前端 5~15 分钟推送延迟 → 页面显示「已改价但售价没变」。
    #   gold_action 仍保留在 /api/gold_action 供对账/审计。
    #
    #   🔴 divisor 必须**按游戏**取（AION2=5.32，暗黑4=5.054）：
    #      成本除数 = 汇率 ×(1−利润率)÷ 前台系数，而前台系数按游戏覆盖
    #      （config.金币.游戏参数.AION2.前台系数 = 1.0，暗黑4走全局 1.0526）。
    #      传错游戏 → 除数差 5%，页面价格对不上 MMOEXP 前台。
    _tk = {}
    _games = sorted(set(g for g in _u_cache.keys() if g))
    for _gm in _games:
        try:
            _div = core_gold.cost_divisor_of(cfg, 0.20, _gm)
        except Exception:
            _div = None
        try:
            _tk.update(store.gold_ticket_map(con, _gm, _div))
        except Exception:
            pass
    # 旧价从 gold_action 取（同一区上一次真实变动的价），幅度按新旧重算
    try:
        _acts_prev = store.gold_action_map(con, "AION2")
    except Exception:
        _acts_prev = {}
    for r in rows:
        _k = r.get("key")
        _t = _tk.get(_k)
        if not _t:
            r["上次改价"] = None
            continue
        _new = _t.get("新价")
        _old = None
        _pa = _acts_prev.get(_k)
        if _pa:
            _old = _pa.get("new_usd_m")
        _pct = None
        if _old and _new:
            try:
                _o, _n = float(_old), float(_new)
                if _o:
                    _pct = round((_n / _o - 1.0) * 100.0, 3)
            except (TypeError, ValueError):
                _pct = None
        r["上次改价"] = {
            "时间": _t.get("时间"),
            "旧价": _old,
            "新价": _new,
            "幅度": _pct,
            "模式": (_pa or {}).get("mode"),
            "依据": (_pa or {}).get("basis"),
            "单号": _t.get("单号"),
            "后台成本": _t.get("成本"),
        }
    # 定价策略留证：看板表头要写清「当前按什么定价」，别让人猜
    try:
        _pol_a = core_gold.pricing_policy(cfg, "AION2") or {}
    except Exception:
        _pol_a = {}
    return jsonify({
        "ok": True, "ts": ts,
        "tier": (cfg.get("金币") or {}).get("对标档位", 10000),
        "rate": core_gold.rate_of(cfg),
        # 展示单位：全局默认仍是「每 10 万 M」（D4 口径，保持旧前端兼容）；
        # 每条行自己的 unit 才是权威值，新前端按行取。
        "unit": int(core_gold.PER_100K),
        "unitByGame": {k: v for k, v in _u_cache.items() if k is not None},
        "frontFactor": core_gold.front_factor_of(cfg),
        # 🔴 成本除数**按游戏给**（AION2=5.32 / 暗黑4=5.054，差异来自前台系数）。
        #   api_gold 是多游戏接口，不能用单一除数，也不能漏传 game（会拿到全局值 5.054）。
        "divisorByGame": {_gm: core_gold.cost_divisor_of(cfg, 0.20, _gm)
                          for _gm in _games},
        "divisor": core_gold.cost_divisor_of(
            cfg, 0.20, ((cfg.get("金币") or {}).get("进货成本") or {}).get("游戏")
                        or "AION2"),
        "定价策略": {
            "AION2": _pol_a,
            "说明": ("AION2 售价 = DD373 该区进货成本 × (1+%.1f%%)；DD373 无报价或"
                     "可买量不足 1 亿的区统一挂 $%.2f/M；"
                     "G2G最低价/ELD最低价/IGGM 继续采集监控并展示，但不参与定价。"
                     % ((_pol_a.get("加价比例") or 0.07) * 100,
                        (_pol_a.get("无货兜底售价_USD每M") or 19.9))
                     if _pol_a.get("模式") == "dd373_only" else
                     ("AION2 售价 = DD373 各区推荐价 × %.1f%%；G2G/ELD/IGGM 继续采集监控并展示，"
                      "但不参与定价。旧三源比价策略已归档，改 config 可切回。"
                      % ((_pol_a.get("加价比例") or 0) * 100)
                      if _pol_a.get("模式") == "dd373_markup" else
                      ("AION2 售价 = G2G 该子服务器 cheapold 价（无则推荐前二较低者）"
                       "× (1−%.1f%%)；⛔ 成本兜底：竞品价 < 我方 DD373 成本价时**按成本价定价**"
                       "（成本 = 买满 1 亿基纳的订单簿加权均价），最后按利润率下限 %.0f%% 兜底；"
                       "ELD/IGGM 继续采集监控但不参与定价。"
                       % ((_pol_a.get("下浮比例") or 0.03) * 100,
                          (_pol_a.get("利润率下限")
                           if _pol_a.get("利润率下限") is not None else -0.10) * 100)
                       if _pol_a.get("模式") == "g2g_cheapold" else
                       ("AION2 走旧三源比价策略（multisrc）" if _pol_a else "默认口径")))),
        },
        "items": rows,
    })


@app.route("/api/gold_cost")
def api_gold_cost():
    """金币进货成本 + 利润率汇总（2026-10-02 · DD373 货源）

    返回每个服务区一行：
      最终售价 $/M  ← **改价后的最终售价**（有目标价用目标价，否则我方现价）
      成本价      ← DD373 **买满 1 亿基纳的订单簿加权均价**（元/万基纳 + 折算 $/M）
                     （2026-10-06 前是「综合排序第 1 条单价」——量级太小，已换）
      利润率      ← (售价 − 成本) / 售价，**可以为负**（负数就是亏，别截断）

    ⛔ 本接口只读，不写任何价格；但成本自 2026-10-06 起**参与定价**
       （g2g_cheapold 模式下做「成本兜底 + 利润率下限」，见 core_gold.build_plan）。
    """
    cfg = load_cfg()
    con = open_db()
    cc = (cfg.get("金币") or {}).get("进货成本") or {}
    game = str(cc.get("游戏") or "AION2")
    rate = core_gold.rate_of(cfg)
    # 最终售价：与 collect_gold_cost 同一口径 —— 改价后目标价优先，退我方现价。
    # ⚠ gold_price 表**没有**「目标每M」这一列，别去找它。两个等价算法（实测
    #   AION2_ASIA_ISRAPHEL_A 两条都得 2.303000，互为校验）：
    #     ① tgt_big / big_tier      （最大档总价 ÷ 档位 M 数）
    #     ② cost_target / divisor   （反推目标采购成本 ÷ 成本除数）
    _price, _tier, _src = {}, {}, {}
    try:
        rows, _ts = store.gold_latest(con)
    except Exception:
        rows = []
    for r in rows:
        k = r.get("key")
        if not k or engine.game_of(cfg, k) != game:
            continue
        tgt = None
        if r.get("tgt_big") is not None and r.get("big_tier"):
            tgt = float(r["tgt_big"]) / float(r["big_tier"])
        elif r.get("cost_target") is not None and r.get("divisor"):
            tgt = float(r["cost_target"]) / float(r["divisor"])
        # ⭐ 2026-10-02：DD373 无报价的区 tgt 会是 None —— 这时**不能**退回我方现价，
        #   否则「用现价算利润率」会显示成一个看似正常的正数，掩盖「这个区没定价」的事实。
        #   改为：动作是 hold 且无基准 ⇒ 售价列留空，看板显示「无报价」。
        _has_target = (tgt is not None)
        _price[k] = tgt if _has_target else None
        _tier[k] = r.get("big_tier")
        _src[k] = {"mode": r.get("price_mode"), "base": r.get("src_base"),
                   "base_v": r.get("src_base_v"), "dd": r.get("dd_ref_usd"),
                   "dd_cny": r.get("dd_ref_cny"), "dd_items": r.get("dd_items"),
                   "action": r.get("action"), "reason": r.get("reason"),
                   "our": r.get("our_per_m"),
                   # 2026-10-02：DD373 采集到的我方前台价（**滞后一拍**，仅作参考）
                   "our_采集": r.get("our_per_m"),
                   "采集ts": r.get("ts"),
                   # 2026-10-02：定价级别（第1/2/3 级）+ 竞品三源（仅监控展示）
                   "tier": r.get("price_tier"),
                   # 2026-10-06 用户口径「只关注 G2G最低价」：G2G 列改用**三源基准里的
                   #   G2G 最低价**（src_g2g），不再用子服务器 cheapold（src2_g2g）。
                   #   cheapold 只有旧 g2g_cheapold 模式才有值，新模式下为 NULL ——
                   #   若继续取它，看板 G2G 列会整列空白。
                   "g2g": (r.get("src_g2g") if r.get("src_g2g") is not None
                           else r.get("src2_g2g")),
                   "eld": r.get("src_eld"),
                   "iggm": r.get("iggm_per_m"),
                   # 2026-10-02：竞品最低价与差距 —— 金币监控主表已按用户要求隐藏，
                   #   这三项并进「售价·进货成本·利润率」汇总区，信息不丢。
                   #   口径与主表 gapCell() 完全一致，避免两处算出不同值。
                   "comp_min": r.get("comp_min"),
                   "comp_min_src": r.get("comp_min_src"),
                   "gap_comp": r.get("gap_comp"),
                   "gap_comp_pct": r.get("gap_comp_pct")}
    try:
        costs = store.gold_cost_latest(con, game=game)
    except Exception:
        costs = []
    # 2026-10-06 展示名统一（用户要求）：
    #   汇总表「服务区」列原先只取 DD373 的游戏区名，而本轮新增的 52 个子服务器在
    #   DD373 没有挂单 → 回落成内部主键 AION2_XXX_E，与老 34 区的「Siel / Zikel」
    #   两种格式并存。这里给每条补 服务器名 / 大区中文 / 种族：
    #     · DD373 有数据的区 → 沿用原值（老区外观零变化）
    #     · 新区 → 取 config 金币.服务区（86 区全都有 g2g_服务区/中文名）
    #   前端第一列改用这三个字段，86 行格式统一。
    _REGION_CN = {"EU": "欧服", "NA West": "北美西", "NA East": "北美东",
                  "Asia": "日服", "South America": "南美", "SAM": "南美", "Latin": "南美"}
    _names = {}
    for _s in ((cfg.get("金币") or {}).get("服务区") or []):
        _k = _s.get("key")
        if not _k:
            continue
        _g2g = str(_s.get("g2g_服务区") or "")
        # 只处理「带 G2G 子服务器名」的区（= AION2 这 86 个）。暗黑4 的 4 个金币区没有
        # 该字段，直接跳过 → 仍走 DD373 原名，外观零影响。
        if " - " not in _g2g:
            continue
        _cn = str(_s.get("中文名") or "")
        _serv = _g2g.split(" - ")[0].strip()
        _race = ("天族" if ("（天族）" in _cn or _g2g.endswith("Elyos"))
                 else ("魔族" if ("（魔族）" in _cn or _g2g.endswith("Asmodian")) else ""))
        _names[_k] = {"服务器名": _serv,
                      "大区中文": _REGION_CN.get(_s.get("大区")) or (_s.get("大区") or ""),
                      "种族": _race}
    out = []
    for c in costs:
        k = c.get("key")
        price = _price.get(k, c.get("final_usd_m"))
        if _price.get(k) is None and c.get("final_usd_m") is not None:
            # 本轮 gold_price 里没有该区目标价，但历史快照有 → 明确标出来，别混用
            price = None
        cost_usd = c.get("usd_per_m")
        margin = c.get("margin")
        if price and cost_usd:
            margin = (float(price) - float(cost_usd)) / float(price)
        elif not price:
            margin = None
        out.append({
            "key": k,
            "售价_USD每M": price,
            "售价口径": ("改价后最终售价" if price is not None else None),
            "成本_元每万基纳": c.get("cny_per_wan"),
            "成本_USD每M": cost_usd,
            "利润率": margin,                       # 可为负
            "ok": c.get("ok"),
            "库存": c.get("stock"), "起售": c.get("min_buy"),
            "挂单数": c.get("n_items"),
            "DD区": c.get("dd_area"), "DD种族": c.get("dd_race"),
            "DD游戏区": c.get("dd_zone"),
            # 2026-10-06：展示名（DD373 优先，缺失回落 config）——见上方 _names。
            #   前端汇总表第一列用这三个字段，替代原来的 DD游戏区||key 兜底。
            # ⚠ config 优先、DD373 兜底（2026-10-06）：DD373 的区名有个别笔误
            #   （如 Asia 的 Nezekan 被拼成 Nezekan/Nezakan 两种），两个源混用会让
            #   同一台服务器在表里出现两种拼写。统一以 config（站内权威名）为准。
            "服务器名": (_names.get(k) or {}).get("服务器名") or c.get("dd_zone") or "",
            "大区中文": (_names.get(k) or {}).get("大区中文") or c.get("dd_area") or "",
            "种族": (_names.get(k) or {}).get("种族") or c.get("dd_race") or "",
            "依据": c.get("basis"), "备注": c.get("note"),
            "url": c.get("url"), "ts": c.get("ts"),
            "对照档位M": _tier.get(k),
            "定价": _src.get(k),
        })
    # 2026-10-02 用户要求：售价要和 MMOEXP 前台一致、不滞后。
    #   gold_state 是执行器回填的**后台采购成本真值**（工单写完立刻更新），
    #   除以**成本除数**（AION2=5.32，来自 core_gold.cost_divisor_of）即为前台每 M 价。
    #   ⚠ 绝不能用「汇率 6.65」换算 —— 那是后台美元成本口径，
    #     会把 5.04 算成 0.76，而前台真实价是 0.95（差 25%）。
    #   注：用户已要求页面不显示「前台已生效」列，这里只保留接口字段供对账/排障。
    try:
        _div_g = core_gold.cost_divisor_of(cfg, 0.20, game)
        _tk_all = store.gold_ticket_map(con, game, _div_g)
    except Exception:
        _tk_all = {}
    for _it in out:
        _t = _tk_all.get(_it.get("key"))
        _it["已生效售价_USD每M"] = (_t or {}).get("新价")
        _it["已生效时间"] = (_t or {}).get("时间")
        _it["已生效单号"] = (_t or {}).get("单号")
        _it["后台采购成本"] = (_t or {}).get("成本")
    out.sort(key=lambda r: (r["利润率"] is None,
                            r["利润率"] if r["利润率"] is not None else 0))
    valid = [r for r in out if r["ok"] and r["利润率"] is not None]
    _pol = {}
    try:
        _pol = core_gold.pricing_policy(cfg, game) or {}
    except Exception:
        _pol = {}
    return jsonify({
        "ok": True, "game": game, "rate": rate,
        "ts": (out[0]["ts"] if out else None),
        "口径": (
            ("售价 $/M = DD373 该区进货成本 $/M × (1+%.1f%%)（加价）；"
             "DD373 无有效报价 或 可买量 < %.0f 万基纳（不足 1 亿）⇒ 统一挂 $%.2f/M"
             "（等该区有货下一轮自动跟回）。"
             "G2G最低价/ELD最低价/IGGM 仅采集监控展示，不参与定价；"
             "利润率 = (售价 − 成本) / 售价，可为负。"
             % ((_pol.get("加价比例") or 0.07) * 100,
                (_pol.get("无货最小可买万基纳") or 10000),
                (_pol.get("无货兜底售价_USD每M") or 19.9)))
            if _pol.get("模式") == "dd373_only" else
            ("售价 = G2G 该子服务器 cheapold 价（无则推荐前二较低者）× (1−%.1f%%)；"
             "⛔ 成本兜底（2026-10-06）：竞品价 < 我方 DD373 成本价时**不再跟降，"
             "按成本价定价**；最后按利润率下限 %.0f%% 兜底。"
             "成本 = DD373 **买满 1 亿基纳的订单簿加权均价**（元/万基纳）；"
             "利润率 = (售价 − 成本) / 售价，可为负。"
             % ((_pol.get("下浮比例") or 0.03) * 100,
                (_pol.get("利润率下限") if _pol.get("利润率下限") is not None else -0.10) * 100)
             if _pol.get("模式") == "g2g_cheapold" else
             ("售价 = DD373 该区成本（买满 1 亿基纳的订单簿加权均价）折 $/M × %.1f%%；"
              "成本 = 同一条口径；利润率 = (售价 − 成本) / 售价，可为负。"
              "G2G/ELD/IGGM 仅监控展示，不参与定价。"
              % ((_pol.get("加价比例") or 0) * 100)
              if _pol.get("模式") == "dd373_markup" else
              "成本 = DD373 永恒之塔2国际服·基纳·各区·买满 1 亿基纳的订单簿加权均价；"
              "利润率 = (售价 − 成本) / 售价，可为负。"))),
        "定价策略": _pol,
        "汇总": {
            "服务区数": len(out),
            "有成本": sum(1 for r in out if r["ok"]),
            "无报价": sum(1 for r in out if not r["ok"]),
            "可算利润率": len(valid),
            "亏损区数": sum(1 for r in valid if r["利润率"] < 0),
            "平均利润率": (sum(r["利润率"] for r in valid) / len(valid)) if valid else None,
            "最低利润率": min((r["利润率"] for r in valid), default=None),
            "最高利润率": max((r["利润率"] for r in valid), default=None),
        },
        "items": out,
    })


@app.route("/api/gold_action")
def api_gold_action():
    """某个服务区的**真实调价历史**（2026-10-02 · 看板「改价操作」列的悬浮明细）。

    ⛔ 只读。数据来自 gold_action 台账 —— 采集时对比上一轮我方前端价，
       **真的变了才记一行**（不是「出单时」记，避免工单没执行却显示已改价）。
    不传 key 则返回全部服务区最近一次调价（页面初次渲染用）。
    """
    con = open_db()
    key = request.args.get("key") or ""
    game = request.args.get("game") or ""
    if key:
        return jsonify({"ok": True, "key": key,
                        "items": store.gold_action_history(con, key, limit=30)})
    return jsonify({"ok": True,
                    "items": [{"key": k, **v} for k, v in
                              store.gold_action_map(con, game or None).items()]})


TASK_DISPATCH = {
    "collect": ("采集一轮（IGGM+我方前端+千岛快照+金币）", task_collect),
    "rebuild": ("重算看板（不联网）", task_rebuild),
    "simulate": ("模拟跟价", task_simulate),
    "plan": ("生成改价计划 DRY-RUN", task_plan),
    "apply": ("生成改价工单（按 跟价.执行方式 派单）", task_apply),
    "gold_apply": ("生成金币改价工单（按 跟价.执行方式 派单）", task_gold_apply),
}


# ============================================================ 路由

@app.route("/")
def index():
    return render_template("index.html", version=VERSION)


@app.route("/api/state")
def api_state():
    cfg = load_cfg()
    con = open_db()
    try:
        data = eval_rows(cfg, con)
        data["config"] = editable_snapshot(cfg)
        data["follow"] = follow_tree(cfg)
        data["mode"] = str(cfg_get(cfg, "跟价.模式", "OFF")).upper()
        data["switches"] = switch_state(cfg)
        data["rate"] = cfg_get(cfg, "汇率.USDCNY", 6.65)
        data["version"] = VERSION
        data["schedule"] = schedule_snapshot(cfg)
        data["serverTime"] = dt.datetime.now().isoformat(timespec="seconds")
        data["p2pah"] = {
            "账号已配": bool(cfg_get(cfg, "p2pah.账号.username")),
            "写接口已配": bool(cfg_get(cfg, "p2pah.写接口.产品价格管理.路径")),
            "账号": cfg_get(cfg, "p2pah.账号.username") or "",
        }
        data["qd"] = {
            "对标区服": cfg_get(cfg, "千岛.对标区服"),
            "参考区服": cfg_get(cfg, "千岛.参考区服") or [],
        }
        # 人工调价保护（2026-09-29）：这些行的现价是人工改的，IGGM 未变价前系统不跟。
        # 页面上按行看 reason 也能看到（「⏸ 人工调价保护…」），这里是汇总口径。
        try:
            _mo = store.manual_override_map(con)
        except Exception:
            _mo = {}
        data["manualOverride"] = {"count": len(_mo), "keys": sorted(_mo.keys())}
        # 按行 pending 闩（2026-09-29）：窗口内有已派发工单的行 —— 前台还没生效的
        # 那些行本轮不会重复出单（各行 reason 里会写明「⏸ 已出单待前台生效…」）。
        try:
            _lp = line_pending_map(cfg, con)
        except Exception:
            _lp = {}
        data["linePending"] = {"count": len(_lp), "keys": sorted(_lp.keys()),
                               "hours": cfg_get(cfg, "跟价.按行pending.保留小时", 8)}
        # 映射口径不再下发到页面（用户要求：页面不留这类复述文字）
        with TASK_LOCK:
            data["tasks"] = [TASKS[i].brief() for i in TASK_ORDER[::-1] if i in TASKS][:12]
        return jsonify({"ok": True, "data": data})
    finally:
        con.close()


@app.route("/api/config", methods=["POST"])
def api_config():
    body = request.get_json(force=True, silent=True) or {}
    patch = body.get("patch") or {}
    if not isinstance(patch, dict) or not patch:
        return jsonify({"ok": False, "error": "没有要修改的字段"}), 400
    try:
        cfg = load_cfg()
        applied = {}
        for path, raw in patch.items():
            v = coerce(path, raw)
            cfg_set(cfg, path, v)
            applied[path] = v
        save_cfg(cfg)
        return jsonify({"ok": True, "applied": applied})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": "写入失败：%r" % e}), 500


@app.route("/api/schedule", methods=["POST"])
def api_schedule():
    """保存每个游戏的「采集 + 改价」周期（小时）。

    body: {"周期": {"暗黑破坏神4": 1, "ARC Raiders": 6, ...}}
    可选值只有 SCHED_CHOICES（1/3/6/12/24）；写进服务器 config.json 的
    `运行.采集周期小时`，重启也不丢。定时器 d4follow-collect.timer 每 15 分钟
    触发一次（心跳，比最细的 0.25h 档更密，不会漏触发）。
    """
    body = request.get_json(force=True, silent=True) or {}
    patch = body.get("周期")
    if not isinstance(patch, dict) or not patch:
        return jsonify({"ok": False, "error": "没有要保存的周期"}), 400
    try:
        cfg = load_cfg()
        games = track_games(cfg)
        cur = dict(cfg_get(cfg, "运行.采集周期小时", {}) or {})
        applied = {}
        for g, v in patch.items():
            g = str(g)
            if g.startswith("_"):
                continue
            if g not in games:
                return jsonify({"ok": False, "error": "未知游戏：%s" % g}), 400
            try:
                iv = float(v)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "%s 的周期需要数字小时" % g}), 400
            # ⚠ 必须按 float 比较：SCHED_CHOICES 含 0.25/0.5 两个小数档。
            #   旧代码用 `int(v)` 会把 0.5→0、0.25→0 ⇒ 页面上选「30 分钟」必被拒
            #   （报「只能是 0.25/0.5/1/3/6/12/24 小时」，自相矛盾）。
            if iv not in SCHED_CHOICES:
                return jsonify({"ok": False,
                                "error": "%s 的周期只能是 %s 小时"
                                         % (g, "/".join(str(x) for x in SCHED_CHOICES))}), 400
            if float(iv).is_integer():      # 整数档存 int，config 更干净；0.25/0.5 保留 float
                iv = int(iv)
            cur[g] = iv
            applied[g] = iv
        for g in games:                      # 没提到的游戏补齐默认值（新游戏也能用）
            if g not in cur:
                cur[g] = interval_of(cfg, g)
        cfg_set(cfg, "运行.采集周期小时", cur)
        cfg.setdefault("_变更记录", {})["2.11.0_每游戏采集周期"] = {
            "时间": dt.datetime.now().isoformat(timespec="seconds"),
            "改动": applied,
            "当前": cur,
            "说明": "定时器仍每小时触发；只有到期的游戏才真正抓价+算价+改价。"
                    "可选 %s 小时。" % "/".join(str(x) for x in SCHED_CHOICES),
        }
        save_cfg(cfg)
        return jsonify({"ok": True, "applied": applied, "schedule": schedule_snapshot(cfg)})
    except Exception as e:
        return jsonify({"ok": False, "error": "写入失败：%r" % e}), 500


@app.route("/api/follow", methods=["POST"])
def api_follow():
    """跟价范围勾选。单件传 {key,on}；整表传 {all:true|false}。"""
    body = request.get_json(force=True, silent=True) or {}
    try:
        cfg = load_cfg()
    except Exception as e:
        return jsonify({"ok": False, "error": "读配置失败：%r" % e}), 500
    items = cfg.get("商品映射", {}).get("对照项") or []
    # ---- 展示筛选（顶部「游戏筛选」下拉）：{display: 游戏名, show: bool} ----
    if "display" in body:
        g = str(body.get("display") or "").strip()
        if not g:
            return jsonify({"ok": False, "error": "缺少 display"}), 400
        hid = cfg.get("商品映射", {}).get("隐藏游戏")
        hid = [str(x) for x in hid] if isinstance(hid, (list, tuple)) else []
        if bool(body.get("show")):
            hid = [x for x in hid if x != g]
        elif g not in hid:
            hid.append(g)
        cfg.setdefault("商品映射", {})["隐藏游戏"] = hid
        save_cfg(cfg)
        return jsonify({"ok": True, "display": g, "show": bool(body.get("show"))})
    if "display_all" in body:
        v = bool(body.get("display_all"))
        games = [gg["name"] for gg in follow_tree(cfg)["games"]]
        cfg.setdefault("商品映射", {})["隐藏游戏"] = [] if v else games
        save_cfg(cfg)
        return jsonify({"ok": True, "display_all": v, "count": len(games)})
    if "game" in body:
        g = str(body.get("game") or "").strip()
        v = bool(body.get("on"))
        if not g:
            return jsonify({"ok": False, "error": "缺少 game"}), 400
        n = 0
        for it in items:
            if (it.get("游戏") or "未分组") == g:
                it["跟价"] = v
                n += 1
        # 金币服务区与它所属的游戏同栏，「这一栏全开 / 全关」连带它。
        #   2026-10-01 多游戏：只动**这一栏那个游戏**的服务区。
        #   （原来写死「挂载游戏」，任何游戏点全开会把全部服务区一起改。）
        for sv in ((cfg.get("金币") or {}).get("服务区") or []):
            if str(engine.game_of(cfg, sv.get("key"))) == g:
                sv["跟价"] = v
                n += 1
        if not n:
            return jsonify({"ok": False, "error": "该游戏没有商品：%s" % g}), 404
        save_cfg(cfg)
        return jsonify({"ok": True, "game": g, "on": v, "count": n})
    if "all" in body:
        v = bool(body.get("all"))
        for it in items:
            it["跟价"] = v
        n = len(items)
        for sv in ((cfg.get("金币") or {}).get("服务区") or []):
            sv["跟价"] = v          # 「全部跟价 / 全部停跟」把金币服务区一起管
            n += 1
        save_cfg(cfg)
        return jsonify({"ok": True, "all": v, "count": n})
    key = str(body.get("key") or "").strip()
    if not key:
        return jsonify({"ok": False, "error": "缺少 key"}), 400
    hit = next((it for it in items if it.get("key") == key), None)
    if hit is None:
        # 金币服务区（key = GOLD_*）：开关落 config.金币.服务区[].跟价，
        # core_gold.build_plan 认这个字段（关掉就不算它、也不进金币工单）
        gsv = next((s for s in ((cfg.get("金币") or {}).get("服务区") or [])
                    if str(s.get("key")) == key), None)
        if gsv is None:
            return jsonify({"ok": False, "error": "没有这个商品：%s" % key}), 404
        gsv["跟价"] = bool(body.get("on"))
        save_cfg(cfg)
        return jsonify({"ok": True, "key": key, "on": gsv["跟价"]})
    hit["跟价"] = bool(body.get("on"))
    save_cfg(cfg)
    return jsonify({"ok": True, "key": key, "on": hit["跟价"]})


@app.route("/api/mode", methods=["POST"])
def api_mode():
    """单独的开关接口，方便大按钮用"""
    body = request.get_json(force=True, silent=True) or {}
    mode = str(body.get("mode") or "").upper()
    if mode not in ("OFF", "AUTO"):
        return jsonify({"ok": False, "error": "模式只能 OFF / AUTO"}), 400
    cfg = load_cfg()
    cfg_set(cfg, "跟价.系统开关", mode == "AUTO")   # 与两个新开关保持一致，避免两套状态打架
    sync_mode(cfg)
    save_cfg(cfg)
    return jsonify({"ok": True, "mode": mode, "switches": switch_state(cfg)})


@app.route("/api/switch", methods=["POST"])
def api_switch():
    # 两个大开关：name=master（系统总开关，能不能改）/ auto（自动跟价，要不要自动改）
    body = request.get_json(force=True, silent=True) or {}
    name = str(body.get("name") or "").strip().lower()
    if name not in ("master", "auto"):
        return jsonify({"ok": False, "error": "name 只能 master / auto"}), 400
    cfg = load_cfg()
    if name == "master":
        cfg_set(cfg, "跟价.系统开关", bool(body.get("on")))
    else:
        cfg_set(cfg, "跟价.自动跟价", bool(body.get("on")))
    st = sync_mode(cfg)
    save_cfg(cfg)
    return jsonify({"ok": True, "name": name, "switches": st})


@app.route("/api/task", methods=["POST"])
def api_task():
    body = request.get_json(force=True, silent=True) or {}
    kind = str(body.get("kind") or "")
    opts = body.get("opts") or {}
    if kind not in TASK_DISPATCH:
        return jsonify({"ok": False, "error": "未知任务类型"}), 400
    title, fn = TASK_DISPATCH[kind]
    try:
        t = spawn(kind, title, fn, opts)
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True, "taskId": t.id, "title": title})


@app.route("/api/logs/<tid>")
def api_logs(tid):
    with TASK_LOCK:
        t = TASKS.get(tid)
    if not t:
        return jsonify({"ok": False, "error": "任务不存在或已过期"}), 404

    def gen():
        q, hist = t.subscribe()
        try:
            for line in hist:
                yield "data: %s\n\n" % json.dumps({"line": line}, ensure_ascii=False)
            yield "data: %s\n\n" % json.dumps({"status": t.status}, ensure_ascii=False)
            while True:
                try:
                    line = q.get(timeout=15)
                except queue.Empty:
                    yield ": ping\n\n"
                    if t.status != "running":
                        break
                    continue
                if line is None:
                    break
                yield "data: %s\n\n" % json.dumps({"line": line}, ensure_ascii=False)
            yield "data: %s\n\n" % json.dumps(
                {"status": t.status, "done": True, "ok": t.ok, "err": t.err},
                ensure_ascii=False)
        finally:
            t.unsubscribe(q)

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@app.route("/api/cost", methods=["POST"])
def api_cost():
    """本机推送千岛成本表。body: {"ts": "...", "rows": [{spec, spu_id, name, category, unit, price_cny}]}"""
    body = request.get_json(force=True, silent=True) or {}
    rows = body.get("rows") or []
    if not rows:
        return jsonify({"ok": False, "error": "rows 为空"}), 400
    ts = str(body.get("ts") or dt.datetime.now().isoformat(timespec="seconds"))
    con = open_db()
    try:
        n = store.save_qd(con, ts, rows)
        specs = sorted({str(r.get("_spec_label") or r.get("spec") or "") for r in rows})
        return jsonify({"ok": True, "saved": n, "ts": ts, "specs": specs})
    finally:
        con.close()


@app.route("/api/our", methods=["POST"])
def api_our():
    """本机推送我方前端价（MMOEXP 公开页的抓取结果）。

    服务器出口访问 www.mmoexp.com 会超时/502（实测 0/6 成功），所以这项也必须由本机抓。
    """
    body = request.get_json(force=True, silent=True) or {}
    rows = body.get("rows") or []
    if not rows:
        return jsonify({"ok": False, "error": "rows 为空"}), 400
    ts = str(body.get("ts") or dt.datetime.now().isoformat(timespec="seconds"))
    con = open_db()
    try:
        n = store.save_our(con, ts, rows)
        return jsonify({"ok": True, "saved": n, "ts": ts})
    finally:
        con.close()


@app.route("/api/cost/status")
def api_cost_status():
    cfg = load_cfg()
    con = open_db()
    try:
        qd_ts = latest_ts(con, "qd_cost")
        rows = []
        if qd_ts:
            spec = cfg_get(cfg, "千岛.对标区服", "")
            for r in con.execute(
                    "SELECT name, MIN(price_cny) c, COUNT(*) n, MAX(src) src,"
                    " MAX(min_buy) q, MAX(depth) d, MAX(lo_price) lo, MAX(note) note"
                    " FROM qd_cost"
                    " WHERE ts=? AND spec=? GROUP BY name ORDER BY c", (qd_ts, spec)):
                rows.append({"name": r["name"], "price_cny": r["c"], "offers": r["n"],
                             "src": r["src"], "q": r["q"], "depth": r["d"],
                             "lo": r["lo"], "note": r["note"]})
        _bt, _bn = core_qd.book_cache_info(cfg)
        return jsonify({"ok": True, "ts": qd_ts, "ageHours": _age_hours(qd_ts),
                        "spec": cfg_get(cfg, "千岛.对标区服"), "rows": rows,
                        "bookTs": _bt, "bookN": _bn, "bookAgeHours": _age_hours(_bt)})
    finally:
        con.close()


@app.route("/api/history/<key>")
def api_history(key):
    con = open_db()
    try:
        seq = []
        for r in con.execute(
                "SELECT ts, iggm_new, ours_old, target_usd, cost_usd, margin_old, action"
                " FROM decisions WHERE key=? ORDER BY ts DESC LIMIT 60", (key,)):
            seq.insert(0, dict(r))
        return jsonify({"ok": True, "key": key, "points": seq})
    finally:
        con.close()


@app.route("/api/board")
def api_board():
    """离线版整页看板（build_dashboard 生成的那份）"""
    cfg = load_cfg()
    outdir = os.path.join(ROOT, cfg_get(cfg, "运行.输出目录", "output"))
    fp = os.path.join(outdir, "自动改价看板.html")
    if not os.path.exists(fp):
        return jsonify({"ok": False, "error": "还没有生成看板，先跑一次采集"}), 404
    with open(fp, encoding="utf-8") as f:
        return Response(f.read(), mimetype="text/html")


# ---------------------------------------------------------------------------
# 本机执行通道的 4 个接口（2026-09-25）
#
# 只在 127.0.0.1:8900 上被本机执行器调用（执行器走 SSH 在本机 localhost 上 curl），
# 所以不额外加 token；经 nginx 的 /d4/ 路径访问时有 Basic Auth 兜着。
# 🔴 这里**没有任何**「服务器登录 order.p2pah.cn」的代码 —— 服务器做不了那件事。
# ---------------------------------------------------------------------------
@app.route("/api/local/pull", methods=["POST"])
def api_local_pull():
    """本机执行器接单。body: {agent}"""
    body = request.get_json(force=True, silent=True) or {}
    agent = str(body.get("agent") or "unknown")[:64]
    con = open_db()
    job = store.local_job_pull(con, agent, ip=request.remote_addr or "")
    if not job:
        return jsonify({"ok": True, "job": None})
    try:
        job["plan"] = json.loads(job.get("plan_json") or "{}")
    except Exception as e:
        job["plan"] = None
        job["plan_error"] = repr(e)
    return jsonify({"ok": True, "job": job})


@app.route("/api/local/result", methods=["POST"])
def api_local_result():
    """本机执行器回传结果。body: {id, ok, log, result, agent}"""
    body = request.get_json(force=True, silent=True) or {}
    jid = str(body.get("id") or "")
    if not jid:
        return jsonify({"ok": False, "error": "缺 id"}), 400
    con = open_db()
    _ok = bool(body.get("ok"))
    _res = body.get("result")
    store.local_job_finish(con, jid, ok=_ok,
                           log=str(body.get("log") or ""),
                           result=_res,
                           agent=str(body.get("agent") or "")[:64])
    # 2026-09-26（patch11）：金币单把本机现场读到的后台真值落库（表 gold_state）。
    # 服务器 IP 进不了后台，这是采购成本现值的**唯一**来源。
    try:
        _hz = (_res or {}).get("成本回执") if isinstance(_res, dict) else None
        if _hz:
            _row = con.execute("SELECT kind FROM local_job WHERE id=?", (jid,)).fetchone()
            if _row and _row["kind"] == "writegold":
                _n = store.gold_state_upsert(
                    con, _hz, ok=_ok, src="%s/%s" % (jid, str(body.get("agent") or "?")[:32]))
                app.logger.info("[gold_state] %s 落库 %d 个服务区的现行采购成本", jid, _n)
    except Exception as e:
        app.logger.warning("[gold_state] 落库失败（不影响本单）：%r", e)
    return jsonify({"ok": True})


@app.route("/api/local/heartbeat", methods=["POST"])
def api_local_heartbeat():
    """本机执行器心跳（2026-09-27）：只续 last_seen，**不碰任何工单**。

    为什么要它：worker 主循环是「领单 → 阻塞执行 → 回传」，跑一张单要几分钟到
    几十分钟，期间不会调 pull ⇒ last_seen 冻住 ⇒ 看板按「>90 秒未报到」判离线。
    实测：服务器 14:22:20，last_seen 停在 14:13:11（差 549 秒），而那张单正在跑。
    现在 worker 单起一个线程每 25 秒打这里，长任务期间也一直显示「在线」。
    ⚠ 不做超时单回收（会误伤正在跑的长单）；回收见 store.local_agent_touch。
    """
    body = request.get_json(force=True, silent=True) or {}
    agent = str(body.get("agent") or "unknown")[:64]
    con = open_db()
    now = store.local_agent_ping(con, agent, ip=request.remote_addr or "")
    return jsonify({"ok": True, "now": now})


# ---------------------------------------------------------------------------
# 执行方式（2026-09-27）：服务器直接执行 / 本机执行器执行
#   服务器执行 = 常驻 srv_exec.py 认领工单 → docker run p2pah-srv:1 → 结果回写本表
#   本机执行   = 老通道，本机 p2pah_local_worker.py 通过 /api/local/pull 接单
# 当前用哪种存在 config「跟价.执行方式」（server / local），这样定时采集派单时也读得到。
# ---------------------------------------------------------------------------
SRV_EXEC_STATE = os.path.join(ROOT, "data", "srv_exec.json")


def _srv_exec_state():
    """读服务器执行器心跳（srv_exec.py 每轮写一次；文件不存在 = 没在跑）。"""
    try:
        with open(SRV_EXEC_STATE, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {"alive": False, "state": "missing",
                "why": "服务器执行器没有在跑（读不到状态文件）"}
    d["alive"] = True
    try:
        age = (dt.datetime.now() - dt.datetime.strptime(
            d.get("ts") or "", "%Y-%m-%dT%H:%M:%S")).total_seconds()
        d["age_s"] = int(age)
        # 空转时每 10 秒写一次心跳；但跑一张单可能几十分钟不刷新 —— 那种情况
        # state='running'，一律当作在线，只有空闲态才按 90 秒判活。
        if d.get("state") != "running" and age >= 90:
            d["alive"] = False
            d["why"] = "状态文件超过 90 秒未刷新（进程可能已退出）"
    except Exception:
        d["age_s"] = None
    return d


@app.route("/api/local/jobs")
def api_local_jobs():
    """给看板用：最近几单 + 本机执行器心跳 + 服务器执行器状态"""
    con = open_db()
    try:
        limit = max(1, min(50, int(request.args.get("limit") or 12)))
    except (TypeError, ValueError):
        limit = 12
    cfg = load_cfg()
    mode = str(cfg_get(cfg, "跟价.执行方式", "server")).lower()
    mode = "local" if mode == "local" else "server"
    jobs = store.local_job_list(con, limit)
    return jsonify({
        "ok": True, "jobs": jobs,
        "worker": store.local_agent_get(con),
        "mode": mode,
        "srvExec": _srv_exec_state(),
        "pendingServer": sum(1 for j in jobs if j.get("status") == "pending"
                             and j.get("exec_mode") == "server"),
        # 兼容旧字段（前端已改，留着免得缓存里的老 JS 读到 undefined）
        "serverCould": True, "whyServerCannot": "",
    })


@app.route("/api/exec/mode", methods=["POST"])
def api_exec_mode():
    """切换执行方式：server = 服务器直接执行（默认）；local = 本机执行器。"""
    body = request.get_json(force=True, silent=True) or {}
    mode = "local" if str(body.get("mode") or "").lower() == "local" else "server"
    try:
        cfg = load_cfg()
        cfg.setdefault("跟价", {})["执行方式"] = mode
        save_cfg(cfg)
    except Exception as e:
        return jsonify({"ok": False, "error": "写 config 失败：%r" % e})
    return jsonify({"ok": True, "mode": mode})


@app.route("/api/local/reassign", methods=["POST"])
def api_local_reassign():
    """把一张**还没开跑**的工单改用另一种方式执行（看板上的「改用本机执行」按钮）。

    body: {id, mode: 'server'|'local'}
    """
    body = request.get_json(force=True, silent=True) or {}
    jid = str(body.get("id") or "")
    mode = "local" if str(body.get("mode") or "").lower() == "local" else "server"
    if not jid:
        return jsonify({"ok": False, "error": "缺 id"})
    con = open_db()
    ok = store.local_job_reassign(con, jid, mode)
    return jsonify({"ok": ok,
                    "error": None if ok else "只能改派「排队中」的工单（已在执行的改不了）"})


@app.route("/api/local/cancel", methods=["POST"])
def api_local_cancel():
    body = request.get_json(force=True, silent=True) or {}
    jid = str(body.get("id") or "")
    con = open_db()
    ok = store.local_job_cancel(con, jid) if jid else False
    return jsonify({"ok": ok, "error": None if ok else "单号不存在或已在执行，无法取消"})


@app.route("/api/shelf_drift")
def api_shelf_drift():
    """货架自检结果（供页面告警条用）。纯读。"""
    con = store.connect(DATA_DIR)
    rows, ts = store.shelf_drift_latest(con)
    by = {"unmapped_shelf": [], "mismatched_pack": [], "orphan_row": []}
    for r in rows:
        (by.get(r.get("kind")) or by["unmapped_shelf"]).append(r)
    return jsonify({"ok": True, "ts": ts, "total": len(rows),
                    "unmapped_shelf": by["unmapped_shelf"],
                    "mismatched_pack": by["mismatched_pack"],
                    "orphan_row": by["orphan_row"]})


@app.route("/api/shelf_patch")
def api_shelf_patch():
    """生成货架纳管补丁草稿（P2：只生成，绝不落盘）。纯读。"""
    import shelf_patch as _sp
    cfg = load_cfg()
    con = store.connect(DATA_DIR)
    try:
        drift = shelf_check.detect(cfg, con, opt_dir=ROOT)
        pk = _sp.build(cfg, drift)
        pk["ok"] = True
        pk["drift_count"] = drift.get("count", 0)
        return jsonify(pk)
    except Exception:
        return jsonify({"ok": False, "err": traceback.format_exc()[-500:],
                        "diff_text": "", "counts": {}})


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "version": VERSION,
                    "time": dt.datetime.now().isoformat(timespec="seconds")})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8900, debug=False, threaded=True)
