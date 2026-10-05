# -*- coding: utf-8 -*-
"""改价执行器 —— 唯一会真正动到钱的模块，所以闸门最多。

三道闸，任何一道不过就不写：
  ① 总开关闸：config.跟价.系统开关 必须是开启（关闭一律拒绝执行）
     ＋ 兼容闸：config.跟价.模式 必须是 AUTO（由总开关自动折算）
  ② 确认闸：必须显式传 --confirm（不加只打印计划）
  ③ 白名单闸：只允许改 config.商品映射 里登记过、且勾选了「跟价」的商品
             （单轮件数上限已按要求取消；安全靠 总开关 + 确认短语 双闸）

2026-09-24 按要求删除：原「测试期保护 · 只允许调高」闸门（涨跌一律同向跟）。
用法：
  python apply_price.py                 # 只看计划，不动数据
  python apply_price.py --confirm       # 真改（改完自动清缓存）
  python apply_price.py --confirm --only LAIR_KEY          # 只改指定商品
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import store
from core_p2pah import P2PAHClient, CacheRefresher


def log(msg):
    print("[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg))


def disc_of(cfg, item_cfg=None):
    """后台「折扣」：前端展示价 = 我方标价 × 折扣

    2026-09-25：改为按商品/按游戏取（暗黑4 = 90、POE2 = 100），见 engine.disc_of。
    不传 item_cfg 时退回全局值（旧调用点行为不变）。
    """
    try:
        import engine
        return engine.disc_of(cfg, item_cfg or {})
    except Exception:
        r = float((cfg.get("前端") or {}).get("后台折扣", 100) or 100) / 100.0
        return r if r > 0 else 1.0


def item_of(cfg, key):
    for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
        if it.get("key") == key:
            return it
    return {}


def bid_of(d, cfg):
    """我方标价（后台商品列表的「$每个价格」）。

    决策里的 ours_new 是标价口径，所以对比也必须用标价。ours_bid 不是 decisions
    表的列，从库里读出来是空的 —— 这时用 前端价 ÷ 折扣 反推。
    """
    if d.get("ours_bid"):
        return d["ours_bid"]
    return (d["ours_old"] / disc_of(cfg, item_of(cfg, d.get("key")))) \
        if d.get("ours_old") else None


def load(cfg_path=None):
    return json.load(open(cfg_path or os.path.join(ROOT, "config.json"), encoding="utf-8"))


def collect_plan(cfg, con, only=None, plan_file=None):
    """从库里最近一轮决策（或一份外部计划文件）里挑出「可执行」的改价项"""
    g = cfg["跟价"]
    mode = str(g.get("模式", "OFF")).upper()
    # 单轮件数上限、「测试期保护 · 只允许调高」均已按要求删除（参数不再存在）

    if plan_file:
        d = json.load(open(plan_file, encoding="utf-8"))
        rows = d.get("plan") if isinstance(d, dict) else d
        if not isinstance(rows, list):
            raise SystemExit("计划文件格式不对：应为 {\"plan\": [...]} 或 [...]")
    else:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM decisions WHERE ts=(SELECT MAX(ts) FROM decisions) ORDER BY key")]
    plan, skipped = [], []
    for d in rows:
        if only and d.get("key") not in only:
            continue
        if d.get("action") not in ("follow_up", "follow_down"):
            continue
        cur_bid = bid_of(d, cfg)
        if d.get("ours_new") is None or cur_bid is None:
            skipped.append((d, "缺目标价或现价"))
            continue
        delta = d["ours_new"] - cur_bid
        if abs(delta) < 1e-9:
            skipped.append((d, "目标价与现价相同"))
            continue
        plan.append(d)
    return plan, skipped, mode


def refresh_cache(cfg, log=log):
    """改价后清缓存 —— ⚠ 2026-09-24 起**本函数的清缓存动作已停用**。

    原因：本服务器的 IP 不在 order.p2pah.cn 白名单（同一会话 cookie：
    本机 200 / 服务器 404）。服务器既发不出改价写请求，也进不了后台清缓存。
    清缓存的**唯一执行方是本机执行器**：

        python p2pah_local.py write --plan <工单> --confirm   # 写价成功后自动清
        python p2pah_local.py clearcache                       # 只清一次

    config 里的 `跟价.缓存刷新.自动刷新` 只作为「意图」写进工单（字段 clearcache），
    由本机执行器读取。入口（本机打开）：
        order.p2pah.cn → 设置 → 清除缓存 → 「清除全部」
        /admin/setting/clearcachepost.html  → 页面正文出现「缓存已更新！」= 成功
    """
    cf = cfg["跟价"].get("缓存刷新") or {}
    log("  [缓存] 跳过：清缓存必须由本机执行器执行（本服务器 IP 不在 order.p2pah.cn 白名单）。")
    log("  [缓存] 本机执行：python p2pah_local.py write --plan <工单> --confirm"
        "（或 p2pah_local.py clearcache 单独清一次）")
    log("  [缓存] config「自动刷新」= %s（该值只作为意图写进工单）"
        % ("开启" if cf.get("自动刷新") else "关闭"))
    return False


def main():
    ap = argparse.ArgumentParser(description="IGGM 跟价 · 改价执行器")
    ap.add_argument("--confirm", action="store_true", help="真的执行改价（不加则 dry-run）")
    ap.add_argument("--only", nargs="*", help="只处理这些 key")
    ap.add_argument("--plan", help="改用外部计划文件（如 simulate.py --save-plan 产出的）")
    ap.add_argument("--config", help="指定 config.json")
    a = ap.parse_args()

    cfg = load(a.config)
    mode = str(cfg["跟价"].get("模式", "OFF")).upper()
    master = cfg["跟价"].get("系统开关", mode == "AUTO")
    auto = bool(cfg["跟价"].get("自动跟价", False))
    log("=== 改价执行器 ｜ 系统总开关=%s ｜ 自动跟价=%s ｜ %s ==="
        % ("开启" if master else "关闭", "开启" if auto else "关闭",
           "真改" if a.confirm else "DRY-RUN（不动数据）"))

    con = store.connect(os.path.join(ROOT, cfg["运行"]["数据目录"]))
    plan, skipped, mode = collect_plan(cfg, con, a.only, a.plan)
    if a.plan:
        try:
            meta = json.load(open(a.plan, encoding="utf-8"))
            if isinstance(meta, dict) and meta.get("simulated"):
                log("⚠ 本计划来自【模拟】场景「%s」—— 不是真实 IGGM 变化，仅供演练，请勿据此改价"
                    % meta.get("scenario"))
        except Exception:
            pass

    log("待改 %d 件，跳过 %d 件" % (len(plan), len(skipped)))
    for d in plan:
        bid = bid_of(d, cfg)
        arrow = "↑" if d["ours_new"] > bid else "↓"
        log("  %-10s %-22s 标价 $%.4f %s $%.4f   (IGGM $%.4f→$%.4f, 毛利 %.1f%%)"
            % (d["key"], d["title"], bid, arrow, d["ours_new"],
               d.get("iggm_old") or 0, d.get("iggm_new") or 0,
               (d.get("margin_new") or 0) * 100))
    for d, why in skipped[:20]:
        log("  [跳过] %-10s %s —— %s" % (d["key"], d["title"], why))

    if not plan:
        log("没有需要改的价格，结束。")
        return 0

    # ---------- 闸门 ----------
    if not a.confirm:
        log("")
        log("★ 这是 DRY-RUN。以上只是「计划」，没有修改任何数据。")
        log("  确认要执行请加 --confirm：python apply_price.py --confirm")
        return 0
    if not master:
        log("")
        log("✗ 总开关闸未通过：config.跟价.系统开关 = 关闭（模式 %s）。" % mode)
        log("  系统总开关关着 = 拦截一切改价。请先打开「系统总开关」。")
        return 2
    if mode != "AUTO":
        log("")
        log("✗ 开关闸未通过：config.跟价.模式 = %s，不是 AUTO。" % mode)
        log("  （模式由「系统总开关」自动折算，一般不用手改；两边对不上说明配置被手改了）")
        return 2
    if not (cfg["p2pah"].get("账号") or {}).get("username"):
        log("✗ 未配置 order.p2pah.cn 账号密码，无法改价。")
        return 3

    cli = P2PAHClient(cfg, log=log)
    if not cli.login():
        log("✗ 登录失败，终止（未改任何数据）")
        return 4

    # ---------- 执行 ----------
    gap = float((cfg["跟价"].get("执行限制") or {}).get("改价最小间隔秒", 1.5))
    ok_cnt, fail = 0, []
    for d in plan:
        try:
            res = cli.set_price_by_key(d["key"], d["ours_new"])
            if res.get("ok"):
                ok_cnt += 1
                log("  ✓ %s -> $%.4f" % (d["key"], d["ours_new"]))
                store.add_decision(con, dt.datetime.now().isoformat(timespec="seconds"),
                                   {**d, "reason": (d.get("reason") or "") + " | 已执行"},
                                   applied=1)
            else:
                fail.append((d["key"], res.get("msg") or "未知错误"))
                log("  ✗ %s 改价失败: %s" % (d["key"], res.get("msg")))
        except Exception as e:
            fail.append((d["key"], repr(e)))
            log("  ✗ %s 异常: %r" % (d["key"], e))
        time.sleep(gap)

    log("执行完成：成功 %d / 失败 %d" % (ok_cnt, len(fail)))
    if fail:
        for k, m in fail:
            log("   失败明细 %s: %s" % (k, m))

    if ok_cnt:
        log("清缓存…")
        refresh_cache(cfg, log=log)
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
