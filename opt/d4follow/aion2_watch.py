# -*- coding: utf-8 -*-
"""AION2 金币价· 15 分钟采集 + 每 N 轮钉钉推送。

设计要点（踩过的坑都在这）：
  1. **只读采集**：不碰任何写价路径，不调 task_gold_apply，纯采集 + 展示。
     跟价决策仍由主采集器（d4follow-collect.timer，每小时）负责。
  2. **多源缓存要绕过**：`金币.多源基准.缓存秒` = 1800（30 分钟），
     而本脚本 15 分钟一轮 —— 若沿用默认缓存，第二轮会拿到 30 分钟前的G2G/ELD，
     推送里就会出现「价格没动」的假象。故这里显式`cache_ttl=0` 强制真抓。
     （G2G 4 个大区 + ELD，每轮仅十几次请求，15 分钟一轮无压力。）
  3. **失败沿用上一轮**：任一数据源抓失败时沿用上一轮快照，并在消息里标注，
     绝不把「抓不到」当成「价格没变」推出去。
  4. **轮次计数落盘**：state 文件记 round 计数，进程重启不丢。

用法：
    venv/bin/python aion2_watch.py           # 采一轮（不推送，除非刚好满 N 轮）
    venv/bin/python aion2_watch.py --dry     # 只采 + 打印 Markdown，不推送
    venv/bin/python aion2_watch.py --force-push  # 忽略计数，强制推一次
    venv/bin/python aion2_watch.py --excel   # 改走「Excel + 下载链接」（默认是 Markdown 明细表）

推送形态：2026-10-03 用户定案用 **Markdown 明细表**（4 列：服务区/我方/毛利率/三源）。
钉钉自定义机器人不支持发附件，所以 Excel 只能走下载链接；用户试过后决定不用。
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

STATE_FILE = os.path.join(HERE, "logs", "aion2_watch_state.json")
CFG_FILE = os.path.join(HERE, "config.json")
DB_FILE = os.path.join(HERE, "data", "iggm_follow.db")

GAME = "AION2"
TOTAL_ROUNDS = 4          # 4 轮 × 15 分钟 ≈ 1 小时
SNAP_DIR = os.path.join(HERE, "logs", "aion2_watch")
# Excel 下载链接的站点前缀。⚠ 生产机 = 47.85.224.112（旧机 47.253.252.55 已停用）。
# ⚠ 不要用 /dashboard/aion2-gold/latest.xlsx：那个路径在 auth_request 保护下，
#   钉钉里点链接没有登录态，会被 302 弹到登录页。下面这个是 nginx 里专门开的
#   免登录精确匹配入口（token 防遍历），改 token 需同时改 iggm-web.conf 的 location。
DL_PATH = "/a2g/611ba7ac2a4cd01f079d76d1b244203a/latest.xlsx"
PUBLIC_BASE = "https://47.85.224.112"


def _log(*a):
    print("[AION2-WATCH %s]" % time.strftime("%H:%M:%S"), *a)
    sys.stdout.flush()


def load_cfg():
    with open(CFG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:                # noqa: BLE001
            _log("state 读失败，按新状态处理")
    return {"round": 0, "last_push_ts": None, "last_push_round": 0}


def save_state(st):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


# --------------------------------------------------------------------- 采集
def collect(cfg, log=_log):
    """采一轮 AION2 金币三源 + 我方前台价。返回 (rows, warns)。

    rows: [{key, 大区, 名称, 基准, 我方价, G2G, ELD, IGGM, 兜底}]
    warns: 采集过程中的告警（会带到消息里，避免"静默当成没变"）
    """
    import core_gold
    import core_multi

    warns = []
    svs = [s for s in ((cfg.get("金币") or {}).get("服务区") or [])
           if (s.get("游戏") or "") == GAME]
    if not svs:
        raise RuntimeError("config 里没有 %s 的服务区，先核对金币.服务区" % GAME)
    _log("服务区 %d 个" % len(svs))

    # --- 三源（G2G + ELD），cache_ttl=0 强制真抓，绕开 30 分钟缓存 ---
    ms = None
    try:
        ms = core_multi.MultiSource(cfg, log=log, cache_ttl=0)
        if not ms.enabled_flag:
            warns.append("⚠️ 金币.多源基准.启用=false，三源基准不可用")
        else:
            ms.refresh(force=True)
            _log("三源抓取：G2G %d 区、ELD %d 区"
                 % (len(ms._g2g or {}), len(ms._eld or {})))
            if not ms._g2g:
                warns.append("⚠️ G2G 本轮无数据")
            if not ms._eld:
                warns.append("⚠️ ELD 本轮无数据")
    except Exception as e:                       # noqa: BLE001
        warns.append("⚠️ 三源初始化失败：%s" % e)
        _log("三源失败：%r" % e)

    rows = []
    # IGGM 会话要跨全部服务区复用（每次 warm 都是一次页面请求）
    ig_obj = None
    try:
        ig_obj = core_gold.IggmGold(log=log)
    except Exception as e:                       # noqa: BLE001
        warns.append("⚠️ IGGM 客户端初始化失败：%s" % e)
    ig_page = core_gold.game_param(cfg, GAME).get("IGGM金币页")

    for sv in svs:
        aid = sv.get("前端aid")
        iggm = None
        base = None
        why = ""
        fallb = None
        det = {}

        # 基准（纯展示口径，不参与定价——定价模式是 dd373_markup）
        if ms is not None and ms.enabled_flag:
            try:
                base, why, det = ms.resolve_base(sv, iggm_price=None, apo=1.0)
                base = core_gold._f(base)
            except Exception as e:               # noqa: BLE001
                warns.append("基准计算失败 %s：%s" % (sv.get("中文名"), e))
        if det.get("兜底"):
            fallb = det["兜底"]

        # IGGM 竞品价（只读）。金币接口不带 cookie 一律 403，必须走 IggmGold 会话。
        if ig_obj is not None and sv.get("iggm_sid"):
            try:
                d = ig_obj.fetch(int(sv["iggm_sid"]), page=ig_page, retry=2) or {}
                iggm = core_gold._f(d.get("unit_price"))
            except Exception as e:               # noqa: BLE001
                _log("IGGM %s 取价失败：%r" % (sv.get("中文名"), e))
            if iggm and base is None:
                base = iggm
                why = "IGGM（无三源）"

        # 我方前台价
        # ⚠ 用 biggest_tier（最大档）而不是 per_m(tiers, target)：
        #   per_m 要求 target 是档位数，传 None 会 TypeError；
        #   且最大档总价误差最小（用户 2026-09-27 定的口径）。
        our = None
        if aid:
            try:
                tiers = core_gold.fetch_front_gold(cfg, aid, game=GAME, log=log, retry=2)
                _n, _tot, per = core_gold.biggest_tier(tiers, field="price_discount")
                our = core_gold._f(per)
            except Exception as e:               # noqa: BLE001
                _log("前台 %s 取价失败：%r" % (sv.get("中文名"), e))
                warns.append("⚠️ 前台价缺 %s" % (sv.get("中文名")))

        rows.append({
            "key": sv.get("key"),
            "大区": sv.get("大区") or "-",
            "名称": sv.get("中文名") or sv.get("key"),
            "基准": base,
            "我方价": our,
            "G2G": det.get("G2G"),
            "ELD": det.get("ELD"),
            "IGGM": iggm,
            "兜底": fallb,
            "基准来源": why,
        })
        time.sleep(float(((cfg.get("金币") or {}).get("请求延迟秒") or 0.3)))

    return rows, warns


# --------------------------------------------------------------------- 合理性校验
def sanity_check(rows, warns):
    """抓到的三源价是否离谱。返回 (过滤后rows, 新增告警)。

    实测踩到的问题（2026-10-03 14:06 起）：ELD 的 Latin America 大区
    抓到 **58.88** 这种明显错误的价（真实约 3.9，差了 15 倍）——
    ELD 页面的离群剔除把正常价全剔了、只留最离谱的那个。
    当初没污染结果纯属侥幸：基准规则是 `min(G2G, ELD)`，异常值**偏高**所以被 min 忽略。
    ⛔ 但若哪天某个源异常**偏低**（更危险的那种），min 会直接把它当基准用。
    ⇒ 这里加一道独立校验：任何单源价格偏离「本大区其他源中位数」超过 3 倍就标记并剔除。
    """
    import statistics
    out = []
    for r in rows:
        vals = [r.get("G2G"), r.get("ELD"), r.get("IGGM"), r.get("我方价")]
        vals = [float(v) for v in vals if v not in (None, 0)]
        if len(vals) >= 2:
            med = statistics.median(vals)
            if med > 0:
                for src in ("G2G", "ELD", "IGGM", "我方价"):
                    v = r.get(src)
                    if v in (None, 0):
                        continue
                    if float(v) > med * 3 or float(v) < med / 3:
                        warns.append(
                            "⚠️ %s 的 %s=%.4f 偏离同区中位价 %.4f 超过 3 倍，已忽略该源"
                            % (r.get("名称") or r["key"], src, float(v), med))
                        r[src] = None
        # 基准兜底：三源都被剔除时回落到我方价/中位，避免报告里出现空基准
        if r.get("基准") is None and r.get("我方价") is not None:
            r["基准"] = r["我方价"]
        out.append(r)
    return out, warns


# --------------------------------------------------------------------- 快照
def snap_path(round_no):
    os.makedirs(SNAP_DIR, exist_ok=True)
    return os.path.join(SNAP_DIR, "round_%04d.json" % round_no)


def save_snapshot(round_no, rows, warns):
    p = snap_path(round_no)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "round": round_no,
                   "warns": warns, "rows": rows}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def load_prev(round_no):
    """读上一轮快照。取不到返回 None（首轮属正常）。"""
    p = snap_path(round_no)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:                            # noqa: BLE001
        return None


# --------------------------------------------------------------------- 主流程
def main():
    dry = "--dry" in sys.argv
    force_push = "--force-push" in sys.argv
    no_push = "--no-push" in sys.argv

    st = load_state()
    rnd = st.get("round", 0) + 1
    _log("=== 第 %d 轮 ===" % rnd)

    try:
        cfg = load_cfg()
        rows, warns = collect(cfg)
        rows, warns = sanity_check(rows, warns)
    except Exception as e:                       # noqa: BLE001
        _log("采集整体失败：%r" % e)
        _log(traceback.format_exc())
        return 1

    if not rows:
        _log("本轮 0 行，判定采集失败，不推送（沿用上一轮）")
        return 1

    good = [r for r in rows if r.get("基准") is not None or r.get("我方价") is not None]
    _log("有效行 %d/%d，告警 %d 条" % (len(good), len(rows), len(warns)))

    # 沿用上一轮缺失的字段（避免"抓不到"被当成"价格归零/无变化"）
    prev = load_prev(rnd - 1)
    if prev:
        pm = {r["key"]: r for r in prev.get("rows") or []}
        for r in rows:
            p = pm.get(r["key"]) or {}
            for f in ("基准", "我方价", "G2G", "ELD", "IGGM"):
                if r.get(f) is None and p.get(f) is not None:
                    r[f] = p[f]
                    r.setdefault("补", []).append(f)

    save_snapshot(rnd, rows, warns)

    import dingtalk_push as dp
    if dry:
        md = dp.render_aion2_markdown(
            rows, (prev or {}).get("rows") or [], rnd, TOTAL_ROUNDS)
        if warns:
            md = "### 采集告警\n" + "\n".join("- " + w for w in warns) + "\n\n" + md
        print("\n" + "=" * 60)
        print(md)
        print("=" * 60)
        st["round"] = rnd
        save_state(st)
        return 0

    st["round"] = rnd
    save_state(st)

    due = force_push or (not no_push and rnd % TOTAL_ROUNDS == 0)
    if not due:
        _log("未到推送轮次（%d/%d），仅落快照" % (rnd % TOTAL_ROUNDS, TOTAL_ROUNDS))
        return 0

    bot = dp.DingTalkBot.from_env()
    if not bot.configured:
        _log("未配置钉钉 webhook，跳过推送（快照已存round %d）" % rnd)
        return 0

    prev_rows = (prev or {}).get("rows") or []

    # 2026-10-03 用户最终定案：**默认就推 Markdown 明细表**（去掉「基准价」「较上轮」两列）。
    # 中途试过「Excel + 下载链接」，用户反馈不好用，已改回。
    # `--excel` 保留为可选：仍需要 Excel 时手动加，Excel 链路没删。
    use_excel = "--excel" in sys.argv
    if not use_excel:
        md = dp.render_aion2_markdown(rows, prev_rows, rnd, TOTAL_ROUNDS)
        if warns:
            md = "### ⚠️ 本轮采集告警\n" + "\n".join("- " + w for w in warns) + "\n\n" + md
    else:
        try:
            import aion2_xlsx
            path, summary = aion2_xlsx.build_xlsx(rows, prev_rows, rnd, warns=warns)
            # 固定名 latest.xlsx 便于收藏/分享（历史文件按时间戳保留在同目录）
            latest = os.path.join(os.path.dirname(path), "latest.xlsx")
            try:
                import shutil
                shutil.copyfile(path, latest)
            except Exception:                       # noqa: BLE001
                latest = path
            url = PUBLIC_BASE + DL_PATH
            md = aion2_xlsx.render_brief(summary, url, TOTAL_ROUNDS, rnd)
            if warns:
                md = ("### ⚠️ %d 条告警（已在 Excel 的「采集告警」页列出）\n"
                      % len(warns)) + md
            _log("Excel 已生成：%s" % path)
        except Exception as e:                   # noqa: BLE001
            _log("Excel 生成失败，退回 markdown 表格：%r" % e)
            md = dp.render_aion2_markdown(rows, prev_rows, rnd, TOTAL_ROUNDS)
            if warns:
                md = ("### ⚠️ 本轮采集告警\n"
                      + "\n".join("- " + w for w in warns) + "\n\n" + md)

    try:
        bot.send_markdown("AION2 金币价", md)
        _log("✅ 已推送（第 %d 轮）" % rnd)
        st["last_push_ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        st["last_push_round"] = rnd
        save_state(st)
        return 0
    except Exception as e:                       # noqa: BLE001
        _log("❌ 推送失败：%r" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
