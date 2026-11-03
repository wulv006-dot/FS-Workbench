# -*- coding: utf-8 -*-
"""config.json 幂等补丁 —— 2026-11-03 MSCW 定价口径改为「DD373 成本 + 固定 30% 利润」。

用法
----
    python patch_mscw_cost_markup.py --in <config.json> [--out ...] [--apply]

    · 默认只打印 diff 报告（dry-run），`--apply` 才写（写前自动备份）。

改动（**只动一处**）
-------------------
金币.定价策略.按游戏["MapleStory Classic World"] =
    {模式: dd373_only, 利润率: 0.30, 利润率下限: 0.30,
     无货最小可买万基纳: 500（万金 = 5M）, 条数下限: 10, 无货处理: "hold"}

老板原话（2026-11-03）：
    「监督 IGGM 的价格的但不跟随，然后固定 30% 利润定价，
      成本抓取还是从 DD373 抓，抓取总额要满 5M，条数最低 10 条」

回滚
----
把该块换回 2026-10-12 的 iggm_undercut（让价比例 0.0 / 利润率下限 0.15）
或直接 `cp config.json.bak-<时间戳> config.json`；代码侧无需回滚
（iggm_undercut 分支仍在，未删除）。
"""
import argparse
import datetime as dt
import io
import json
import os
import sys

GAME = "MapleStory Classic World"

POLICY_NEW = {
    "模式": "dd373_only",
    "利润率": 0.30,
    "利润率下限": 0.30,
    "无货最小可买万基纳": 500,     # 万金 = 5M（本专区单位是「万金」，非「万基纳」）
    "条数下限": 10,
    "无货处理": "hold",            # 数据不达标 ⇒ 不出价，保持线上现价
    "成本源": "DD373",
    "_说明": (
        "🔴 2026-11-03 老板定案（原话）：「监督 IGGM 的价格的但不跟随，然后固定 30% 利润定价，"
        "成本抓取还是从 DD373 抓，抓取总额要满5M，条数最低10条」。"
        "⇒ 定价模式由 iggm_undercut（跟 IGGM）改为 **dd373_only（成本加成）**："
        "① 目标前端 $/K = DD373 进货成本 $/K ÷ (1 − 30%)（= 成本 ÷ 0.70，真利润率正好 30%）；"
        "② 利润率下限同为 30% ⇒ 常规定价时恒不触发，只在被跌停限幅等机制压低时把价抬回 30%；"
        "③ **IGGM 只采集展示、不参与定价**（看板仍显示 IGGM 列与差距，仅监督）；"
        "④ DD373 数据达标门槛 = 可买量 ≥ 500 万金（5M）且挂单 ≥ 10 条；"
        "⑤ 不达标的轮次（无报价 / 量不足 / 条数不足）**本轮不出价（hold，保持线上现价）**，"
        "不再套 12.99/19.9 这类固定保护价（MSCW 单价是 $/K 量级，套 M 口径会翻几倍）。"
        "｜沿革：2026-10-08 起 iggm_undercut（IGGM×0.9 + 15% 兜底）→ 10-12 让价 0.1→0.0（持平 IGGM）"
        "→ 10-17 让价 0.05 → **2026-11-03 本次改为成本加成 30%**。"
        "｜⚠ 2026-11-03 实测：IGGM 常被 CF 拦而 MSCW 原先「完全依赖 IGGM」⇒ 一熔断就整轮 hold，"
        "价格长期不动；改成本加成后 DD373 单源即可出价。"),
    "成本源明细": (
        "DD373「新枫之谷经典版冒险岛怀旧服」北美NA(k5faqj) + 欧洲EU(sphpwv) 合并订单簿，"
        "买满 **500 万金（5M）**且挂单 **≥ 10 条**（跳过最低 1 条）的数量加权均价（元/万金）"
        "→ $/K = 元/万金 ÷ 汇率 ÷ 10"),
    "_回滚": ("把本块整体换回 {模式: iggm_undercut, 让价比例: 0.0, 利润率下限: 0.15, "
              "成本源: DD373} 即可（代码两条分支都在）；或直接还原 config 备份。"),
}

CHANGELOG_KEY = "2026-11-03_MSCW成本加成30%"
CHANGELOG = {
    "时间": "2026-11-03 17:00",
    "内容": ("冒险岛怀旧服（MSCW）定价口径切换：IGGM 跟价 → DD373 成本 + 固定 30% 利润；"
             "IGGM 降级为纯监控。DD373 抓取目标量 800 万金 → 500 万金（5M），新增挂单 ≥ 10 条门槛；"
             "数据不达标时本轮 hold（保持线上现价），不再挂固定保护价。"),
    "老板原话": ("「监督 IGGM 的价格的但不跟随，然后固定 30% 利润定价，"
                 "成本抓取还是从 DD373 抓，抓取总额要满5M，条数最低10条」"),
    "代码侧": ("core_gold.py：dd373_only 新增「无货处理=hold」（仅该游戏开启，AION2 行为不变）；"
               "利润率下限闸适用游戏由 AION2 扩到 AION2+MSCW；"
               "core_dd373_cost.py：FLAT_ZONES.MSCW target_wan 800→500、新增 min_quotes=10，"
               "翻页终止改为「量 + 条数」双条件；app.py：金币日志按游戏取单位（万金/$/K）。"),
    "回滚": "config 备份 config.json.bak-<ts>；代码回滚点见同批次发布目录。",
}


def patch(cfg, log=print):
    changed = []
    pol = (cfg.get("金币") or {}).setdefault("定价策略", {})
    per = pol.setdefault("按游戏", {})
    old = per.get(GAME)
    if old == POLICY_NEW:
        log("  = 金币.定价策略.按游戏.%s 已是目标值（跳过）" % GAME)
    else:
        log("  ~ 金币.定价策略.按游戏.%s" % GAME)
        if isinstance(old, dict):
            for k in ("模式", "让价比例", "利润率", "利润率下限", "无货最小可买万基纳", "条数下限"):
                log("      %-12s %r → %r" % (k, old.get(k), POLICY_NEW.get(k)))
        else:
            log("      原值 %r" % (old,))
        per[GAME] = dict(POLICY_NEW)
        changed.append("金币.定价策略.按游戏.%s → dd373_only/30%%" % GAME)

    ch = cfg.setdefault("_变更记录", {})
    if ch.get(CHANGELOG_KEY) != CHANGELOG:
        ch[CHANGELOG_KEY] = dict(CHANGELOG)
        changed.append("_变更记录 += %s" % CHANGELOG_KEY)
        log("  + _变更记录 += %s" % CHANGELOG_KEY)
    else:
        log("  = _变更记录 已含 %s（跳过）" % CHANGELOG_KEY)
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    dst = a.dst or a.src
    with io.open(a.src, encoding="utf-8") as f:
        cfg = json.load(f)
    print("=== config 补丁报告 ===  %s" % a.src)
    changed = patch(cfg)
    print("\n改动 %d 项：%s" % (len(changed), "；".join(changed) or "（无）"))
    if not a.apply:
        print("\n[dry-run] 未写文件。加 --apply 才写。")
        return 0
    _bak = "%s.bak-%s" % (dst, dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    if os.path.exists(dst):
        with io.open(dst, encoding="utf-8") as f:
            _old = f.read()
        with io.open(_bak, "w", encoding="utf-8", newline="") as f:
            f.write(_old)
        print("\n已备份 → %s" % _bak)
    txt = json.dumps(cfg, ensure_ascii=False, indent=2)
    with io.open(dst, "w", encoding="utf-8", newline="") as f:
        f.write(txt)
    print("已写出 → %s（%d 字节）" % (dst, len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
