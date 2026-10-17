# -*- coding: utf-8 -*-
"""config.json 幂等补丁 —— 2026-10-08 接入 MSCW（冒险岛怀旧服国际服）+ 摘掉 VALORANT。

用法
----
    python patch_config_mscw.py --in  <config.json> [--out <config.json.new>] [--apply]

    · 默认**只打印 diff 报告**，不写文件（dry-run）。
    · `--apply` 才真正写出（写前自行备份由调用方负责）。

幂等：跑第二遍报告里应全是「已是目标值」，且输出文件的 md5 与第一遍一致。

改动清单（6 处）
---------------
① 金币.服务区        += GOLD_MSCW_GLOBAL（后台行 21754 / 前台 aid 21627 / IGGM sid 29041）
② 金币.游戏参数      += "MapleStory Classic World"（前台 GameId 1333 / cid 9661 / site_id 266）
③ 金币.定价策略.按游戏 += MSCW = iggm_undercut（跟 IGGM ×(1−10%) + 15% 利润兜底）
④ 金币.进货成本.游戏列表 = ["AION2", "MapleStory Classic World"]
⑤ 商品映射.游戏顺序   去掉 VALORANT；商品映射.游戏字典 删掉 VALORANT
⑥ p2pah.游戏别名 / p2pah.游戏 += MSCW（gid 1300，兼容执行器取 gid 的第二条路）
⑦ _变更记录 += "2.12.0_MSCW"（留档）；版本 → 2.12.0
"""
import argparse
import datetime as dt
import io
import json
import os
import sys

GAME = "MapleStory Classic World"

SRV = {
    "key": "GOLD_MSCW_GLOBAL",
    "中文名": "Global World (Windia)",
    # 后台「金币价格管理」gid=1300 的行ID（**只改这一行**）
    "后台行ID": "21754",
    # 后台「产品价格管理」中对应的「货币」产品ID（留档用；本链路不改它，改的是采购成本）
    "后台商品ID": "165167181",
    "前端aid": 21627,
    "iggm_sid": 29041,
    # 后台行 21754 的「利润率」列实测 = 0.30 ⇒ 成本除数 = 6.65×(1−0.30)÷1.0 = 4.655
    "利润率": 0.30,
    "跟价": True,
    "游戏": GAME,
    "大区": "Global",
    "仅检测": False,
    "_新增": ("2026-10-08 接入。前台 https://www.mmoexp.com/Maplestory-classic-world/Mesos.html"
              "（Game_id=1333 / top_cid=1 / cid=9661 / site_id=266 / aid=21627）；"
              "后台 gid=1300；IGGM 金币页 /maplestory-classic-world/mesos、sid=29041（单位 K）。"
              "DD373 走扁平专区（北美NA k5faqj + 欧洲EU sphpwv 合并，买满 100 万金）。"),
}

GPARAM = {
    # 🔴 2026-10-08 22:0x 修正：0.95（原写 1.0 —— 那个结论是错的）
    #    前台售价 = 后台 b2c × 该档位折扣 `discount`/100（逐档位）。
    #    MSCW 对标档位 = 500K，该档 discount = 95 ⇒ 实际乘数 0.95。
    #    ⇒ 成本除数 = 汇率 6.65 ×(1−利润率 0.30) ÷ 0.95 = 4.90（不是 4.655）。
    "前台系数": 0.95,
    "展示倍率": 1,
    "展示单位名": "K",
    "IGGM折算系数": 1.0,
    "对标档位": 500,
    "IGGM金币页": "/maplestory-classic-world/mesos",
    "前台GameId": "1333",
    "前台top_cid": "1",
    "前台cid": "9661",
    "前台site_id": "266",
    "前台Referer": "https://www.mmoexp.com/Maplestory-classic-world/Mesos.html",
    "_说明": (
        "2026-10-08 实测定案："
        "① 🔴 **前台售价 = 后台 b2c × 该档位 `discount`/100**（前台 API 的 `price_discount` "
        "即客户实付价；`discount` 是**逐档位**折扣率，MSCW 档位表 10~500K 对应 100→95）。"
        "Windia 实证：15 个档位一律满足 单价 ÷ (disc/100) × 4.655 = 采购成本，波动 0.00%；"
        "且前台数值 ÷ (0.4491×0.95×…) = 40 ÷ 2.090561 = 19.134（前台彼时仍被采购成本 40 驱动）。"
        "⇒ 对标档位 500K 的 discount = 95 ⇒ **前台系数 = 0.95**、**成本除数 = 6.65×0.70÷0.95 = 4.90**。"
        "（早先「产品价格管理 $每个价格 = b2c 8.592911 逐位相同 ⇒ 系数 1.0」的结论是**误判** —— "
        "那读的是后台**标价列**，客户实付价还要再乘 discount/100。）"
        "② IGGM 折算系数 = 1.0（本机抓 0.499 = 机房抓 0.499，**无机房加价**，"
        "照抄全局 0.909090909 会把目标价凭空压低 9.1%）。"
        "③ 展示倍率 1 + 展示单位名 K ⇒ 看板显示 $/K。"
        "⚠ 若日后后台把 500K 档的 discount 改成别的值（如 97），成本除数要同步改成 4.655÷0.97；"
        "看板 `我方前端折扣` 字段会显示该档当前折扣，可直接对照。"),
}

POLICY = {
    "模式": "iggm_undercut",
    "让价比例": 0.10,
    "利润率下限": 0.15,
    "成本源": "DD373",
    "_说明": ("2026-10-08 老板定案（原话）：「以 IGGM 的价格为对标，在保证 15% 利润兜底的"
              "情况下，永远比 IGGM 的售价低 10%；若 IGGM 价格低于成本价格，不跟随，"
              "按照最低 15% 利润率兜底，不再跟进」＋「取消 30% 利润上限，只无脑跟 IGGM 的价"
              "就行，利润兜底保留」。"
              "⇒ 目标前端 $/K = IGGM 真价 × 0.90（无成本加价上限）；"
              "兜底 = 利润率 ≥ 15% ⇔ 目标 ≥ 成本 ÷ 0.85（IGGM 低于成本时自动被这道闸挡住）。"),
    "成本源明细": ("DD373「新枫之谷经典版冒险岛怀旧服」北美NA k5faqj + 欧洲EU sphpwv 合并，"
                   "买满 100 万金的订单簿加权均价（元/万金）→ $/K = 元/万金 ÷ 汇率 ÷ 10"),
}

GAME_ALIAS = {
    "MapleStory Classic World": "MSCW",
    "MSCW": "MSCW",
    "冒险岛怀旧服": "MSCW",
    "冒险岛怀旧服国际服": "MSCW",
    "MapleStory": "MSCW",
    "MapleStory Classic": "MSCW",
}

P2PAH_GAME = {
    "名称": "1300 MapleStory Classic World",
    "game_id": "1300",
    "服务区": [{"id": "21754", "名称": "Global World (Windia)", "启用": True}],
    "类目": [{"id": "0", "名称": "Currency / 游戏币", "启用": True}],
    "其它类目": {"1": "Gold", "2": "Items"},
    "我方名": "MapleStory Classic World",
    "_说明": ("2026-10-08 接入（金币专线）。**本游戏只跑金币，不跑物品跟价** —— "
              "p2pah.游戏 里登记仅为让执行器取 gid 的第二条路（第一条是 p2pah_local.GOLD_GID）"
              "与留档；金币写入由 core_gold + p2pah_local.cmd_writegold 负责。"),
}

CHANGELOG_KEY = "2.12.0_MSCW"
CHANGELOG = {
    "时间": "2026-10-08 21:10",
    "内容": ("接入新游戏「MapleStory Classic World（冒险岛怀旧服国际服 / MSCW）」金币专线，"
             "并下线空的 VALORANT 监控区。"),
    "接入点": [
        "金币.服务区 += GOLD_MSCW_GLOBAL（后台行 21754 Global World / Windia；"
        "前台 aid 21627；IGGM sid 29041；利润率 0.30）",
        "金币.游戏参数 += MapleStory Classic World（前台 GameId 1333 / cid 9661 / site_id 266；"
        "展示单位 K；**前台系数 0.95**；**IGGM 折算系数 = 1.0**）",
        "金币.定价策略.按游戏.MSCW = {模式: iggm_undercut, 让价比例: 0.10, 利润率下限: 0.15}",
        "金币.进货成本.游戏列表 = [AION2, MapleStory Classic World]",
        "p2pah.游戏别名 / p2pah.游戏 += MSCW（gid 1300）",
        "商品映射.游戏顺序 / 游戏字典 摘掉 VALORANT",
    ],
    "前台定价定律（2026-10-08 实证 · Windia 15 档 0.00% 拟合）": (
        "**前台客户实付价 = 后台 b2c × (该档位 discount ÷ 100)**，其中 discount 是逐档位折扣"
        "（MSCW 档位表 10→500K 对应 100→95；AION2 全 100；D4 为 90~99）。"
        "b2c = 采购成本 ÷ 汇率 ÷ (1 − 利润率)。"
        "⇒ 成本除数（对标档位）= 汇率 × (1−利润率) ÷ (discount/100)。"
        "⚠ 用途：算「采购成本」时必须用**对标档位那一档的折扣**，否则客户实付价会系统性偏低/偏高。"),
    "定价口径（老板定案）": ("目标前端 $/K = IGGM 真价 × 0.90（**无 30% 成本加价上限**，"
                             "只跟 IGGM）；唯一闸 = 利润率 ≥ 15% ⇔ 目标 ≥ 成本 ÷ 0.85；"
                             "IGGM 低于成本时自动被这道闸抬回，不再跟进。"),
    "成本口径": ("DD373「新枫之谷经典版冒险岛怀旧服」北美NA(k5faqj) + 欧洲EU(sphpwv) 合并，"
                 "买满 100 万金（不足则翻页，最多 6 页）的订单簿加权均价（元/万金）→ "
                 "$/K = 元/万金 ÷ 汇率(6.65) ÷ 10。"),
    "换算": ("采购成本 = 目标前台 $/K × 6.65 × (1 − 0.30) ÷ 前台系数 0.95 = 目标 × **4.90**"
             "（4.90 = 汇率 × (1−利润率) ÷ 前台系数；前台系数 0.95 = 对标档位 500K 的"
             "前台折扣 discount/100）。⚠ 修正记录：2026-10-08 22:0x 由 4.655 改为 4.90 —— "
             "4.655 漏算了前台逐档位折扣 `discount`，会让客户实付价比目标低 5%。"),
    "代码侧": ("core_gold.py 新增定价模式 iggm_undercut（含按游戏策略覆盖 + 利润率下限兜底段）；"
               "core_dd373_cost.py 新增扁平专区采集（fetch_costs 按游戏分发）；"
               "app.py 金币成本按「所有需要成本的游戏」注入；p2pah_local.py GOLD_GID 增补 MSCW 别名。"),
    "下线": "商品映射.游戏顺序 / 游戏字典 移除 VALORANT（一直是空监控区）。",
}


def _diff(log, path, old, new):
    if old == new:
        log("  = %-46s 已是目标值（跳过）" % path)
        return False
    log("  ~ %-46s %r → %r" % (path, old, new))
    return True


def patch(cfg, log=print):
    changed = []
    g = cfg.setdefault("金币", {})

    # ① 金币.服务区
    svs = g.setdefault("服务区", [])
    _has = next((s for s in svs if s.get("key") == SRV["key"]), None)
    if _has is None:
        svs.append(dict(SRV))
        changed.append("金币.服务区 += GOLD_MSCW_GLOBAL")
        log("  + 金币.服务区 追加 %s（共 %d 个服务区 → %d）"
            % (SRV["key"], len(svs) - 1, len(svs)))
    elif {k: v for k, v in _has.items() if k != "_新增"} != \
            {k: v for k, v in SRV.items() if k != "_新增"}:
        _has.update(SRV)
        changed.append("金币.服务区[GOLD_MSCW_GLOBAL] 已存在但字段有差异 → 已对齐")
        log("  ~ 金币.服务区[%s] 已存在，字段已对齐到目标值" % SRV["key"])
    else:
        log("  = 金币.服务区[%s] 已是目标值（跳过）" % SRV["key"])

    # ② 金币.游戏参数
    gp = g.setdefault("游戏参数", {})
    if _diff(log, "金币.游戏参数.%s" % GAME, gp.get(GAME), GPARAM):
        gp[GAME] = dict(GPARAM)
        changed.append("金币.游戏参数 += %s" % GAME)

    # ③ 金币.定价策略.按游戏
    pol = g.setdefault("定价策略", {})
    per = pol.setdefault("按游戏", {})
    if _diff(log, "金币.定价策略.按游戏.%s" % GAME, per.get(GAME), POLICY):
        per[GAME] = dict(POLICY)
        changed.append("金币.定价策略.按游戏 += %s = iggm_undercut" % GAME)
    # 顶层 适用游戏 必须仍是 AION2（MSCW 走 按游戏 覆盖；别把 MSCW 塞进名单，
    #   否则顶层模式会和 按游戏 打架）
    _ag = pol.get("适用游戏")
    if isinstance(_ag, list) and GAME in _ag:
        _ag.remove(GAME)
        changed.append("金币.定价策略.适用游戏 移除 %s（MSCW 走 按游戏 覆盖）" % GAME)
        log("  ~ 金币.定价策略.适用游戏 移除 %s" % GAME)

    # ④ 金币.进货成本.游戏列表
    cc = g.setdefault("进货成本", {})
    want = ["AION2", GAME]
    if cc.get("游戏列表") != want:
        _old = cc.get("游戏列表")
        cc["游戏列表"] = want
        changed.append("金币.进货成本.游戏列表 = %r" % want)
        log("  ~ 金币.进货成本.游戏列表 %r → %r" % (_old, want))
    else:
        log("  = 金币.进货成本.游戏列表 已是目标值（跳过）")

    # ⑤ 商品映射：摘掉 VALORANT
    pm = cfg.get("商品映射") or {}
    order = pm.get("游戏顺序")
    if isinstance(order, list) and "VALORANT" in order:
        order.remove("VALORANT")
        changed.append("商品映射.游戏顺序 移除 VALORANT")
        log("  - 商品映射.游戏顺序 移除 VALORANT → %r" % (order,))
    else:
        log("  = 商品映射.游戏顺序 已无 VALORANT（跳过）")
    gd = pm.get("游戏字典")
    if isinstance(gd, dict) and "VALORANT" in gd:
        gd.pop("VALORANT")
        changed.append("商品映射.游戏字典 删除 VALORANT")
        log("  - 商品映射.游戏字典 删除 VALORANT")
    else:
        log("  = 商品映射.游戏字典 已无 VALORANT（跳过）")
    for _k in ("隐藏游戏", "_显示筛选说明"):
        _v = pm.get(_k)
        if isinstance(_v, list) and "VALORANT" in _v:
            _v.remove("VALORANT")
            changed.append("商品映射.%s 移除 VALORANT" % _k)
            log("  - 商品映射.%s 移除 VALORANT" % _k)

    # ⑥ p2pah 别名 / 游戏
    pj = cfg.setdefault("p2pah", {})
    al = pj.setdefault("游戏别名", {})
    _add = {k: v for k, v in GAME_ALIAS.items() if al.get(k) != v}
    if _add:
        al.update(_add)
        changed.append("p2pah.游戏别名 += %s" % list(_add))
        log("  + p2pah.游戏别名 += %r" % (_add,))
    else:
        log("  = p2pah.游戏别名 已是目标值（跳过）")
    pg = pj.setdefault("游戏", {})
    if _diff(log, "p2pah.游戏.MSCW", pg.get("MSCW"), P2PAH_GAME):
        pg["MSCW"] = dict(P2PAH_GAME)
        changed.append("p2pah.游戏 += MSCW")

    # ⑦ 版本 + 变更记录（留档）
    ch = cfg.setdefault("_变更记录", {})
    if _diff(log, "_变更记录.%s" % CHANGELOG_KEY, ch.get(CHANGELOG_KEY), CHANGELOG):
        ch[CHANGELOG_KEY] = dict(CHANGELOG)
        changed.append("_变更记录 += %s" % CHANGELOG_KEY)
    ver = cfg.get("版本")
    _new_ver = "2.12.0"
    if ver != _new_ver:
        cfg["版本"] = _new_ver
        changed.append("版本 %r → %r" % (ver, _new_ver))
        log("  ~ 版本 %r → %r" % (ver, _new_ver))
    else:
        log("  = 版本 已是 %s（跳过）" % _new_ver)
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
    # 备份
    _bak = "%s.bak_%s" % (dst, dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
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
