# -*- coding: utf-8 -*-
"""自测：pricing 口径分支 + store 读写 + core_self 标题解析。

不联网、不碰真价，纯逻辑断言，可随时跑：
    python tools/selftest.py
    python tools/selftest.py --recon   # 额外用侦察快照跑一遍真实建议单（需那个目录在位）
"""
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import core_self                                    # noqa: E402
import pricing                                      # noqa: E402

CFG = json.load(io.open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
FAIL = []


def check(name, got, want):
    ok = got == want
    print("  %s %-46s got=%r want=%r" % ("✓" if ok else "✗", name, got, want))
    if not ok:
        FAIL.append(name)


def test_parse_title():
    print("[1] 标题解析")
    check("标准形态 NA West", core_self.parse_title("Siel - Elyos [NA West]"),
          {"服务区": "Siel", "阵营": "Elyos", "区服组": "NA West"})
    check("标准形态 Asia 魔族", core_self.parse_title("Zikel - Asmodian [Asia]"),
          {"服务区": "Zikel", "阵营": "Asmodian", "区服组": "Asia"})
    check("中文形态(带 region_id 映射)",
          core_self.parse_title("白傑爾 - 天族 (Vaizel - Elyos)",
                                "9820a142-1bc7-4ebe-9997-4e2dc7385879"),
          {"服务区": "Vaizel", "阵营": "Elyos", "区服组": "TW"})
    check("乱标题 → None", core_self.parse_title("Hello World"), None)


def test_parse_offer():
    print("[2] offer 过滤（非 Aion2 金币要滤掉）")
    ok_one = {"offer_id": "G1", "unit_name": "Mil Kinah", "brand_name": "Aion 2",
              "title": "Siel - Elyos [NA West]", "converted_unit_price": 1.05,
              "status": "live"}
    r = core_self.parse_offer(ok_one)
    check("Aion2 金币通过·现价", r and r["现价"], 1.05)
    check("Aion2 金币通过·键", (r["区服组"], r["服务区"], r["阵营"]), ("NA West", "Siel", "Elyos"))
    diamond = dict(ok_one, unit_name="K Diamonds", brand_name="RF Online Next")
    check("别的游戏商品滤掉", core_self.parse_offer(diamond), None)


def _indexes(cfg):
    """手搓成本索引 + 竞品索引（覆盖所有分支，不联网）。"""
    cost_idx = {
        ("NA West", "Siel - Elyos"): {"key": "k1", "大区": "NA West",
                                      "g2g_服务区": "Siel - Elyos", "够量": True,
                                      "成本": 1.00, "可买量万": 500000.0, "条数": 50,
                                      "ok": True, "依据": "买满5亿"},
        ("NA West", "Vaizel - Elyos"): {"key": "k2", "大区": "NA West",
                                        "g2g_服务区": "Vaizel - Elyos", "够量": False,
                                        "成本": 9.99, "可买量万": 800.0,
                                        "条数": 800, "ok": True, "依据": "只够800万·但条数够"},
        ("NA West", "H1 - Elyos"): {"key": "k6", "大区": "NA West",
                                    "g2g_服务区": "H1 - Elyos", "够量": True,
                                    "成本": 1.00, "可买量万": 500000.0, "条数": 50,
                                    "ok": True, "依据": "买满5亿"},
        ("NA West", "H2 - Elyos"): {"key": "k7", "大区": "NA West",
                                    "g2g_服务区": "H2 - Elyos", "够量": True,
                                    "成本": 1.00, "可买量万": 500000.0, "条数": 50,
                                    "ok": True, "依据": "买满5亿"},
        ("NA West", "H3 - Elyos"): {"key": "k8", "大区": "NA West",
                                    "g2g_服务区": "H3 - Elyos", "够量": True,
                                    "成本": 1.00, "可买量万": 500000.0, "条数": 50,
                                    "ok": True, "依据": "买满5亿"},
        # 条数降级：挂单 5 条 ⇒ 固定 $12.99
        ("Asia", "Zikel - Asmodian"): {"key": "k4", "大区": "Asia",
                                       "g2g_服务区": "Zikel - Asmodian", "够量": False,
                                       "成本": 1.00, "可买量万": 3000.0, "条数": 5,
                                       "ok": True, "依据": "仅5条"},
        # 条数降级：0 条（无有效报价）⇒ 仍闸门价 $19.9
        ("Asia", "Nezekan - Asmodian"): {"key": "k5", "大区": "Asia",
                                         "g2g_服务区": "Nezekan - Asmodian", "够量": False,
                                         "成本": None, "可买量万": None, "条数": 0,
                                         "ok": False, "依据": "0 条挂单"},
        # 占位保护用
        ("EU", "Baba - Asmodian"): {"key": "k3", "大区": "EU",
                                    "g2g_服务区": "Baba - Asmodian", "够量": True,
                                    "成本": 2.13, "可买量万": 24120.0, "条数": 60,
                                    "ok": True, "依据": "买满5亿"},
    }
    cb_idx = {
        # A：正常跟 cheapold（落在利润率带内 ⇒ 不吃地板/天花板）
        #    2026-10-13：带子抬到 30%~45% 后，1.40 会掉到地板下，改用 1.60
        #    （1.60×0.99=1.584 ⇒ 毛率 36.9%，仍在带内）
        ("NA West", "Siel - Elyos"): {"cheapold": 1.60, "base": 1.60, "src": "cheapold",
                                      "who": "cheapold", "n": 12},
        # I：cheapold 太低 ⇒ 触发 30% 地板
        ("NA West", "H1 - Elyos"): {"cheapold": 1.05, "base": 1.05, "src": "cheapold",
                                    "who": "cheapold", "n": 9},
        # J：cheapold 太高 ⇒ 触发 45% 天花板
        ("NA West", "H2 - Elyos"): {"cheapold": 5.00, "base": 5.00, "src": "cheapold",
                                    "who": "cheapold", "n": 9},
        # K：cheapold 低于我方成本 ⇒ 成本兜底（随后被地板抬到 30%）
        ("NA West", "H3 - Elyos"): {"cheapold": 0.80, "base": 0.80, "src": "cheapold",
                                    "who": "cheapold", "n": 4},
        # D/E：占位保护区也有 cheapold，只是不吃改价
        ("EU", "Baba - Asmodian"): {"cheapold": 3.00, "base": 3.00, "src": "cheapold",
                                    "who": "cheapold", "n": 7},
    }
    return cost_idx, cb_idx


def test_pricing():
    print("[3] 定价口径（跟 cheapold：地板 30% / 天花板 45%）")
    cfg = json.loads(json.dumps(CFG))          # 深拷贝：不改动全局 CFG
    cfg["定价"]["保护占位价"] = [9.99]
    cfg["定价"]["跟cheapold"] = True
    cfg["定价"]["下浮比例"] = 0.01
    cfg["定价"]["利润率下限"] = 0.3
    cfg["定价"]["利润率上限"] = 0.45
    cfg["定价"]["无cheapold利润率"] = 0.3
    cost_idx, cb_idx = _indexes(cfg)
    offers = [
        {"offer_id": "A", "区服组": "NA West", "服务区": "Siel", "阵营": "Elyos",
         "现价": 1.50, "状态": "live"},
        {"offer_id": "B", "区服组": "NA West", "服务区": "Vaizel", "阵营": "Elyos",
         "现价": 1.20, "状态": "live"},            # 无 cheapold ⇒ 成本÷0.70
        {"offer_id": "C", "区服组": "NA West", "服务区": "Lumie", "阵营": "Asmodian",
         "现价": 0.9, "状态": "live"},             # 成本表里没有
        {"offer_id": "D", "区服组": "EU", "服务区": "Baba", "阵营": "Asmodian",
         "现价": 9.99, "状态": "live"},
        {"offer_id": "E", "区服组": "EU", "服务区": "Baba", "阵营": "Asmodian",
         "现价": 9.9999, "状态": "live"},          # 录入误差，应同样被占位保护
        {"offer_id": "F", "区服组": "Asia", "服务区": "Zikel", "阵营": "Asmodian",
         "现价": 1.00, "状态": "live"},            # 挂单 5 条 ⇒ 12.99
        {"offer_id": "G", "区服组": "Asia", "服务区": "Nezekan", "阵营": "Asmodian",
         "现价": 1.00, "状态": "live"},            # 0 条 ⇒ 19.9
        {"offer_id": "I", "区服组": "NA West", "服务区": "H1", "阵营": "Elyos",
         "现价": 1.10, "状态": "live"},            # 地板
        {"offer_id": "J", "区服组": "NA West", "服务区": "H2", "阵营": "Elyos",
         "现价": 1.10, "状态": "live"},            # 天花板
        {"offer_id": "K", "区服组": "NA West", "服务区": "H3", "阵营": "Elyos",
         "现价": 0.90, "状态": "live"},            # 成本兜底 ⇒ 再被地板抬
    ]
    rows = {r["offer_id"]: r for r in pricing.build_plan(offers, cost_idx, cfg,
                                                         cheapold_idx=cb_idx)}
    # A：跟 cheapold，目标 = 1.60 × 0.99 = 1.584 ⇒ 1.58（毛率 36.9%，在 30%~45% 带内）
    check("A 目标价 = cheapold × (1−1%)", rows["A"]["目标价"], round(1.60 * 0.99, 2))
    check("A 定价方式", rows["A"]["定价方式"], "G2G·cheapold×(1−1.0%)")
    check("A 基准价 = cheapold 价", rows["A"]["基准价"], 1.60)
    check("A 动作", rows["A"]["动作"], "上调")
    # I：cheapold 太低 ⇒ 抬到 成本 ÷ 0.70
    check("I 目标价 = 成本 ÷ 0.70（地板 30%）", rows["I"]["目标价"], round(1 / 0.7, 2))
    check("I 定价方式带「利润下限30%」", "利润下限30%" in rows["I"]["定价方式"], True)
    # J：cheapold 太高 ⇒ 压到 成本 ÷ 0.55
    check("J 目标价 = 成本 ÷ 0.55（天花板 45%）", rows["J"]["目标价"], round(1 / 0.55, 2))
    check("J 定价方式带「利润率上限45%」", "利润率上限45%" in rows["J"]["定价方式"], True)
    # K：cheapold < 成本 ⇒ 按成本价，再被地板抬到 30%
    check("K 目标价 = 成本 ÷ 0.70（兜底后再抬）", rows["K"]["目标价"], round(1 / 0.7, 2))
    check("K 定价方式含「→成本价」", "→成本价" in rows["K"]["定价方式"], True)
    # B：无 cheapold ⇒ 成本 ÷ (1−0.30)
    check("B 无 cheapold ⇒ 成本÷0.70", rows["B"]["目标价"], round(9.99 / 0.70, 2))
    check("B 定价方式", rows["B"]["定价方式"], "成本÷0.70")
    # F / G：条数降级
    check("F 挂单仅 5 条 ⇒ $12.99", (rows["F"]["目标价"], rows["F"]["动作"]), (12.99, "上调"))
    check("G 0 条报价 ⇒ 闸门价 $19.9", (rows["G"]["目标价"], rows["G"]["动作"]), (19.9, "上调"))
    check("C 成本表里没有 ⇒ 无成本数据", rows["C"]["动作"], "无成本数据")
    check("D 现价 9.99 ⇒ 占位保护·不动", rows["D"]["动作"], "占位保护·不动")
    check("E 现价 9.9999 ⇒ 容差保护也算占位", rows["E"]["动作"], "占位保护·不动")

    print("[4] 汇总")
    s = pricing.summarize(list(rows.values()))
    check("上调数", s["上调"], 7)
    check("下调数", s["下调"], 0)
    check("无成本数据数", s["无成本数据"], 1)
    check("占位保护数", s["占位保护"], 2)
    check("来源分布·跟 cheapold", s["来源分布"].get("跟 cheapold"), 4)
    check("来源分布·利润下限抬价", s["来源分布"].get("利润下限抬价"), 2)
    check("来源分布·利润率上限压价", s["来源分布"].get("利润率上限压价"), 1)
    check("来源分布·无cheapold成本定价", s["来源分布"].get("无cheapold·成本定价"), 1)


def test_pricing_without_hold():
    """保护价清空（= 线上当前配置）⇒ 9.99 也照口径改，不再被挡。"""
    print("[3b] 保护价清空 ⇒ 9.99 照口径改")
    cfg = json.loads(json.dumps(CFG))
    cfg["定价"]["保护占位价"] = []
    cfg["定价"]["跟cheapold"] = True
    cost_idx, cb_idx = _indexes(cfg)
    offers = [{"offer_id": "D", "区服组": "EU", "服务区": "Baba", "阵营": "Asmodian",
               "现价": 9.99, "状态": "live"}]
    r = pricing.build_plan(offers, cost_idx, cfg, cheapold_idx=cb_idx)[0]
    # cheapold 3.00 ⇒ 跟价 2.97；成本 2.13 ⇒ 毛率 28.3% < 30% ⇒ 被地板抬到 2.13÷0.70 = 3.04
    _t = round(2.13 / 0.7, 2)
    check("D 现价 9.99 不再保护 ⇒ 跟价后吃地板", (r["目标价"], r["动作"]),
          (_t, "上调" if _t > 9.99 else "下调"))


def test_pricing_legacy():
    """回滚开关 跟cheapold=false ⇒ 回到旧口径 成本 ÷ (1−利润率)。"""
    print("[3c] 跟cheapold=false ⇒ 旧口径")
    cfg = json.loads(json.dumps(CFG))
    cfg["定价"]["保护占位价"] = []
    cfg["定价"]["跟cheapold"] = False
    cfg["定价"]["利润率"] = 0.5
    cost_idx, cb_idx = _indexes(cfg)
    offers = [{"offer_id": "A", "区服组": "NA West", "服务区": "Siel", "阵营": "Elyos",
               "现价": 1.50, "状态": "live"}]
    r = pricing.build_plan(offers, cost_idx, cfg, cheapold_idx=cb_idx)[0]
    check("A 旧口径 = 成本 ÷ 0.50", (r["目标价"], r["定价方式"]), (2.0, "成本÷0.50"))


def test_store():
    print("[5] store 读写（临时库）")
    import store
    tmp = tempfile.mkdtemp()
    store.DB = os.path.join(tmp, "t.db")
    store.init()
    store.save_snapshot("cost", {"rate": 6.65, "costs": {"k": {"ok": True}}})
    ts, pl = store.latest_snapshot("cost")
    check("快照回读", pl["rate"], 6.65)
    store.save_plan([
        {"offer_id": "A", "区服组": "NA West", "服务区": "Siel", "阵营": "Elyos",
         "标题": "t", "当前价": 1.5, "成本": 1.0, "可买量万": 1, "够量": "Y",
         "目标价": 1.3, "差额": -0.2, "动作": "下调", "定价方式": "成本÷(1−利润率)", "说明": "",
         "cheapold价": 1.4, "基准价": 1.31, "基准来源": "G2G·cheapold×(1−1.0%)"},
    ])
    ts2, rows = store.latest_plan()
    check("建议单行数", len(rows), 1)
    check("默认未放行", bool(rows[0]["released"]), False)
    check("cheapold 原价落库", rows[0]["cb"], 1.4)
    check("基准价落库", rows[0]["base"], 1.31)
    check("基准来源落库", rows[0]["base_src"], "G2G·cheapold×(1−1.0%)")
    store.set_released("A", True)
    check("放行后", len(store.released_rows()), 1)
    store.log_write({"offer_id": "A", "new_price": 1.3, "api_ok": True, "verified": True})
    check("写入流水", len(store.list_writes()), 1)


def test_recon():
    """用侦察快照跑真实建议单（只读本地 CSV/JSON，不联网、不写价）。"""
    BASE = r"D:/共享资源/服务器/G2G改价系统_20261010"
    p = os.path.join(BASE, "侦察", "my_offers_full.json")
    c = os.path.join(BASE, "输出", "g2g_target_prices.csv")
    if not (os.path.exists(p) and os.path.exists(c)):
        print("[6] 跳过：侦察目录不在位")
        return
    print("[6] 侦察快照端到端")
    import csv
    raw = json.load(io.open(p, encoding="utf-8"))
    offers = [r for r in (core_self.parse_offer(o) for o in raw) if r]
    costs = {}
    with io.open(c, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            costs[r["key"]] = {
                "ok": bool(r["DD373成本$/M"]),
                "够量": r.get("够量") == "Y",
                "成本_USD每M": float(r["DD373成本$/M"]) if r["DD373成本$/M"] else None,
                "可供量_万基纳": float(r["可买量(万基纳)"]) if r["可买量(万基纳)"] else None,
                "依据": r["说明"],
            }
    idx = pricing.build_cost_index(costs, CFG["服务区"])
    rows = pricing.build_plan(offers, idx, CFG)
    s = pricing.summarize(rows)
    check("Aion2 货架条数", len(offers), 75)
    print("    汇总：", json.dumps(s, ensure_ascii=False))
    check("行数=货架数", len(rows), len(offers))


if __name__ == "__main__":
    test_parse_title()
    test_parse_offer()
    test_pricing()
    test_pricing_without_hold()
    test_pricing_legacy()
    test_store()
    if "--recon" in sys.argv:
        test_recon()
    print()
    if FAIL:
        print("✗ 失败 %d 项：%s" % (len(FAIL), FAIL))
        sys.exit(1)
    print("✓ 全部通过")
