#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上线后读回：核对 AION2 金币口径（**DD373 改名匹配修复** + **2 亿 → 1 亿** +
**取消翻页/只读第 1 页**）是否如期生效。

用法（在服务器上跑）：
    /opt/d4follow/venv/bin/python verify_aion2_after_1yi.py [BASE]
BASE 默认 http://127.0.0.1:8900

⚠ 字段名按 /api/gold_cost 的实际返回（2026-10-06 实测）：
   item: key / ok / ts / 依据 / DD区 / DD游戏区 / 成本_USD每M / 成本_元每万基纳 /
         售价_USD每M / 库存 / 定价{mode,action,base,base_v,tier,reason,...}
   top : game / ok / rate / ts / 口径 / 定价策略（**单游戏** dict）/ items / 汇总

验收项
  1. 定价策略：模式 dd373_only ｜ 加价 0.07 ｜ 无货兜底 19.9 ｜ **无货最小可买 10000**（= 1 亿）
  2. 「依据」里**不应再出现**「DD373 无对应区（游戏区×大区）」← 改名匹配修复的直接验收点
  3. 有成本的行：「DD游戏区」有值，且「依据」是「买满1亿订单簿加权」（不是 2 亿）
  4. **跨大区错配 = 0**：该行 DD区 必须等于它自己所在大区（旧代码的「同名兜底」曾把
     欧服 Azphel 的进货价套给日服/北美东/南美 Azphel，南美 Zikel 套给其它 Zikel，共 7 行）
  5. tier1：售价 = **计划自己的成本 dd** × 1.07（容差 0.011）；tier3：售价全部 = 19.9
     ⚠ 不要用行顶层 `成本_USD每M` 去乘 —— 那是**本轮**新快照，而 `定价` 是**上一轮**
       算好并派单的计划（`定价.采集ts` 写明用哪一轮成本），两者差一轮，互算会假阳性。
  6. 挂单数/可买量口径（2026-10-06 **第五轮：只读第 1 页**）：
     依据含「站点N单」+「仅第1页」、库存为「可买X万基纳」（可买量 = **第 1 页**合计）、
     备注含「第 1 页」口径说明；**全库不得再出现「首屏」字样**；
     「挂单数」= 站点权威总数，只判「是否取到」，不跟第 1 页解析条数比大小
     （只读首页后站点总数天然远大于解析条数，属**预期**）
  7. 翻页策略：**已取消翻页** ⇒ 每一行的「翻页数」必须恒为 **1**（哪怕站点有 8 页）；
     依据带「仅第1页」。此行若有 ≠1 即判失败（说明仍在翻页 = 会撞风控）
"""
import json
import sys
import urllib.request
from collections import Counter

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8900").rstrip("/")

_AREA_OF = {"ASIA": "日服", "NAW": "北美西", "NAE": "北美东",
            "SA": "南美", "EU": "欧服"}


def _area(key):
    p = str(key or "").split("_")
    return _AREA_OF.get(p[1] if len(p) > 1 else "", "?")


d = json.loads(urllib.request.urlopen(
    BASE + "/api/gold_cost?game=AION2", timeout=120).read().decode("utf-8"))
rows = d.get("items") or []
print("game=%s ｜ ok=%s ｜ rate=%s ｜ 行数=%d" % (d.get("game"), d.get("ok"),
                                                d.get("rate"), len(rows)))
print("本轮 ts:", sorted({str(r.get("ts")) for r in rows}))
_kj = str(d.get("口径") or "")
print("口径:", _kj[:230])
pol = d.get("定价策略") or {}
print("定价策略:", json.dumps(pol, ensure_ascii=False))

fails = []

# ── 1. 定价策略 ────────────────────────────────────────────────────────────
if pol.get("模式") != "dd373_only":
    fails.append("模式 = %r（应为 dd373_only）" % pol.get("模式"))
if abs(float(pol.get("无货最小可买万基纳") or 0) - 10000) > 1e-9:
    fails.append("无货最小可买万基纳 = %r（应为 10000）" % pol.get("无货最小可买万基纳"))
if abs(float(pol.get("加价比例") or 0) - 0.07) > 1e-9:
    fails.append("加价比例 = %r（应为 0.07）" % pol.get("加价比例"))
if "2 亿" in _kj:
    fails.append("口径文案里仍有「2 亿」")

# ── 2. 改名匹配修复 ────────────────────────────────────────────────────────
_nm = [r for r in rows if "无对应区" in str(r.get("依据") or "")]
print("\n『DD373 无对应区』行数 = %d（修复目标：0）" % len(_nm))
if _nm:
    fails.append("仍有 %d 行『DD373 无对应区』：%s"
                 % (len(_nm), [r.get("key") for r in _nm[:5]]))

# ── 3. 有成本行的游戏区 / 口径文案 ─────────────────────────────────────────
okrows = [r for r in rows if r.get("ok")]
print("DD373 有成本(ok=1) 的行 = %d ／ 无报价 %d" % (len(okrows), len(rows) - len(okrows)))
_o1 = [r for r in okrows if "买满1亿订单簿加权" in str(r.get("依据") or "")]
_o2 = [r for r in okrows if "买满2亿" in str(r.get("依据") or "")]
_nozone = [r for r in okrows if not r.get("DD游戏区")]
print("其中 依据含『买满1亿订单簿加权』= %d ／ 仍是『买满2亿』= %d" % (len(_o1), len(_o2)))
if _o2:
    fails.append("%d 行的依据仍是『买满2亿』（代码未生效）" % len(_o2))
if _o1 and len(_o1) != len(okrows):
    fails.append("有成本但依据不是 1 亿口径的行 %d 个" % (len(okrows) - len(_o1)))
if _nozone:
    fails.append("%d 行有成本但缺 DD游戏区" % len(_nozone))

# ── 4. 跨大区错配 ─────────────────────────────────────────────────────────
_mis = []
for r in rows:
    if not r.get("ok"):
        continue
    if str(r.get("DD区") or "") != _area(r.get("key")):
        _mis.append((r.get("key"), _area(r.get("key")), r.get("DD区"), r.get("DD游戏区")))
print("\n跨大区错配（DD区 ≠ 本行所在大区），目标 0：%d" % len(_mis))
for m in _mis[:8]:
    print("   ❌ %-26s 我方=%-6s DD区=%-6s DD游戏区=%s" % m)
if _mis:
    fails.append("%d 行跨大区错配（进货价取错大区）" % len(_mis))

# ── 5. 定价级别与公式 ─────────────────────────────────────────────────────
_tier = Counter((r.get("定价") or {}).get("tier") for r in rows)
print("\n定价.tier:", dict(_tier))
print("定价.action:", dict(Counter(str((r.get("定价") or {}).get("action")) for r in rows)))
print("定价.base:", dict(Counter(str((r.get("定价") or {}).get("base")) for r in rows)))

lv1 = [r for r in rows if (r.get("定价") or {}).get("tier") == 1]
lv3 = [r for r in rows if (r.get("定价") or {}).get("tier") == 3]
# ⚠ 用**计划自身的成本 `定价.dd`** 校验，**不要**用行顶层的 `成本_USD每M`：
#   行顶层成本是**本轮**新落的快照，而 `定价` 是**上一轮**算好并派单的计划
#   （`定价.采集ts` 会明确写它用的是哪一轮成本）—— 两者天然差一轮，
#   拿它们互算会得到 20+ 行「公式异常」的**假阳性**。公式本身用 dd 校验即可。
print("本轮黄金快照 ts =", sorted({str(r.get('ts')) for r in rows}))
print("各行 定价.采集ts =", dict(Counter(str((r.get("定价") or {}).get("采集ts")) for r in rows)),
      "（差一轮属正常：计划用的是上一轮已落库的成本）")
bad1 = [r for r in lv1
        if (r.get("定价") or {}).get("dd") is None or r.get("售价_USD每M") is None
        or abs(float(r["售价_USD每M"]) - float((r["定价"] or {}).get("dd")) * 1.07) > 0.011]
print("tier1 = %d ｜ 售价 = 计划内成本 dd × 1.07 异常的 = %d" % (len(lv1), len(bad1)))
for r in bad1[:3]:
    print("   ⚠ %-26s dd=%s 售价=%s" % (r.get("key"), (r.get("定价") or {}).get("dd"),
                                     r.get("售价_USD每M")))
if bad1:
    fails.append("tier1 公式异常 %d 行" % len(bad1))

set3 = sorted({round(float(r["售价_USD每M"]), 4) for r in lv3 if r.get("售价_USD每M") is not None})
print("tier3 = %d ｜ 售价去重 = %s 共 %d" % (len(lv3), set3[:6], len(set3)))
if set3 and set3 != [19.9]:
    fails.append("tier3 售价不是全部 19.9：%s" % set3[:6])

# ── 6. 挂单数 / 可买量口径（2026-10-06 **第五轮：只读第 1 页**）──────────────
#   依据 = "…(吃x/y条·仅第1页·站点N单)"；库存 = "可买X万基纳"（= 第 1 页可买量）
import re as _re
_st = [r for r in okrows if _re.search(r"站点\s*\d+\s*单", str(r.get("依据") or ""))]
_sh = [r for r in okrows if "可买" in str(r.get("库存") or "")]
_mk = [r for r in okrows if "第 1 页" in str(r.get("备注") or "")]
print("\n依据含『站点N单』= %d ／ 库存含『可买』= %d ／ 备注含『第 1 页』= %d（均应 = %d）"
      % (len(_st), len(_sh), len(_mk), len(okrows)))
if len(_st) != len(okrows):
    fails.append("%d 行有成本但依据缺『站点N单』（站点统计未生效）"
                 % (len(okrows) - len(_st)))
if len(_sh) != len(okrows):
    fails.append("%d 行有成本但库存缺『可买』" % (len(okrows) - len(_sh)))
if len(_mk) != len(okrows):
    fails.append("%d 行有成本但备注缺『第 1 页』口径说明" % (len(okrows) - len(_mk)))

_old = [r for r in rows if "首屏" in (str(r.get("库存") or "")
                                    + str(r.get("备注") or "")
                                    + str(r.get("依据") or ""))]
print("仍出现『首屏』字样的行 = %d（应为 0：第五轮已改为只读第 1 页）" % len(_old))
if _old:
    fails.append("%d 行仍是旧的『首屏』口径文案" % len(_old))

# 挂单数（站点总数）与解析条数**无固定大小关系**：够 1 亿即停后主力服只翻 1 页，
#   站点总数（如 87）天然远大于解析条数（如 21）—— 这是**预期**，不是异常。
#   这里只判「挂单数是否取到」。
_bad_n = [r.get("key") for r in okrows if r.get("挂单数") is None]
print("『挂单数』缺失的行 = %d（应为 0）" % len(_bad_n))
for b in _bad_n[:5]:
    print("   ❌ %-26s 挂单数缺失" % b)
if _bad_n:
    fails.append("%d 行『挂单数』缺失（站点总数没取到）" % len(_bad_n))

# ── 7. 翻页策略：**已取消翻页，只读第 1 页**（2026-10-06 第五轮）────────────
#   预期：**每一行**的「翻页数」恒为 1；依据带「仅第1页」。
#   ≠1 即判失败 —— 那说明还在翻页（= 会撞 DD373 风控）。
_fs = [r.get("翻页数") for r in okrows if isinstance(r.get("翻页数"), int)]
_bad_f = [(r.get("key"), r.get("翻页数"), r.get("站点页数")) for r in okrows
          if r.get("翻页数") != 1]
print("\n翻页数 = 1 的行 = %d / %d（取消翻页后应全部为 1）"
      % (sum(1 for x in _fs if x == 1), len(okrows)))
for k, f, p in _bad_f[:8]:
    print("   ❌ %-26s 翻页数=%s（站点 %s 页）—— 仍在翻页" % (k, f, p))
if _bad_f:
    fails.append("%d 行翻页数 ≠ 1（取消翻页未生效）" % len(_bad_f))

_pgs = [r.get("站点页数") for r in okrows if isinstance(r.get("站点页数"), int)]
if _pgs:
    print("站点页数：最多 %d 页 ／ 多页区(>1 页) = %d 个（这些区本来会翻，现在都不翻）"
          % (max(_pgs), sum(1 for p in _pgs if p > 1)))
_ok_pg = [r for r in okrows if "仅第1页" in str(r.get("依据") or "")]
print("依据含『仅第1页』= %d 行（应 = %d）" % (len(_ok_pg), len(okrows)))
if len(_ok_pg) != len(okrows):
    fails.append("%d 行依据缺『仅第1页』" % (len(okrows) - len(_ok_pg)))

# 抽样展示：站点总数 > 解析条数 的区（= 第一页口径下会少报的那些）
_samp = []
for r in okrows:
    m = _re.search(r"吃(\d+)/(\d+)条", str(r.get("依据") or ""))
    if m and r.get("挂单数") and int(r["挂单数"]) > int(m.group(2)):
        _samp.append((r.get("key"), r.get("挂单数"), m.group(2),
                      str(r.get("库存") or "")))
print("\n站点总数 > 解析条数 的区（共 %d 个，前 8）：" % len(_samp))
for k, tot, loc, stk in sorted(_samp, key=lambda x: -int(x[1]))[:8]:
    print("   %-26s 站点 %-4s 单 ｜ 解析 %-4s 条 ｜ %s" % (k, tot, loc, stk))

# ── 汇总 ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 62)
if fails:
    print("❌ %d 项未通过：" % len(fails))
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("✅ 全部验收项通过（%d 行 ｜ 有成本 %d ｜ tier1 %d ｜ tier3 %d）"
      % (len(rows), len(okrows), len(lv1), len(lv3)))
