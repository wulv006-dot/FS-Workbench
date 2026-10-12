# -*- coding: utf-8 -*-
"""修正 D4 5 处登记错误（2026-10-08）

背景
----
清单截断修好后，闸一预演从 359 处 id_gone 降到 9 处；其中 D4 占 5 处。
逐条核对后台真实行后确认，这 5 处**不是后台被人改了**，而是配置登记本身的错：

① CORRUPTED_ROOTS / CORRUPTED_ROOTS_X10 —— **两个后台ID记反了**
     配置装量 100 的档绑到了后台 `(10) Corrupted Roots` 那行，
     配置装量 10 的档绑到了 `(100) Corrupted Roots` 那行。
     交换两个键的 `商品ID映射` 值即恢复「ID ↔ 名称 ↔ 数量」三重绑定。
     （这同时修掉了定价取数错乱：100 装档在拿 10 装行的价）

② ADEPTS_PRISM_X100 / PROTECTORS_PRISM_X100 / JUDICATORS_MASK —— **关键词只写了前缀**
     同族其它键（Kullean / Aggressive / Chromatic / Entropic / Pragmatic / Resourceful）
     都写的是完整英文名 + `(DLC Required)`，这 3 个只写了 `Adept` / `Protector` / `Judicator`。
     闸一用 `_norm_title` 整串相等比较 ⇒ 永远不匹配 ⇒ 每轮误报「改名」。
     补全成完整名即可（`商品名关键词` 在 core_front 里是**子串**匹配，
     改长只会让候选更精确，不影响前台匹配）。

⚠ 幂等：① 先判断「当前 ID 行的数量是否已等于配置装量」，已正确则跳过；
         ② 直接赋值，天然幂等。
⚠ 只改这 5 个键，绝不碰其它登记。
"""
import argparse
import io
import json
import os
import re
import sys
import time

CFG = "/opt/d4follow/config.json"
ITEMS = "/opt/d4follow/data/backend_items.json"

SWAP = ("CORRUPTED_ROOTS", "CORRUPTED_ROOTS_X10")
KW_FIX = {
    "ADEPTS_PRISM_X100":     "Adept's Tuning Prism (DLC Required)",
    "PROTECTORS_PRISM_X100": "Protector's Tuning Prism (DLC Required)",
    "JUDICATORS_MASK":       "Judicator's Mask (DLC Required)",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg", default=CFG)
    ap.add_argument("--items", default=ITEMS)
    ap.add_argument("--apply", action="store_true", help="写回盘（默认只预演）")
    a = ap.parse_args()

    sys.path.insert(0, "/opt/d4follow")
    import gates as G

    raw = io.open(a.cfg, encoding="utf-8").read()
    cfg = json.loads(raw)
    m = re.search(r'\n(\s+)"', raw)
    indent = len(m.group(1)) if m else 2

    p2 = cfg.get("p2pah") or {}
    idmap = p2.get("商品ID映射") or {}
    bykey = {}
    for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
        bykey[str(it.get("key"))] = it

    rows = []
    if os.path.exists(a.items):
        j = json.load(io.open(a.items, encoding="utf-8"))
        rows = (j.get("rows") if isinstance(j, dict) else j) or []
    byid = {str(r.get("id")): r for r in rows}

    L = lambda *x: print(*x, flush=True)
    L("=" * 74)
    L("D4 登记修正 %s   cfg=%s" % ("【APPLY】" if a.apply else "【DRY-RUN】", a.cfg))
    L("=" * 74)

    # ── ① ID 互换 ─────────────────────────────────────────────
    ka, kb = SWAP
    if ka not in idmap or kb not in idmap:
        L("① ✘ 商品ID映射里找不到 %s / %s，中止" % (ka, kb))
        return 2
    ia, ib = str(idmap[ka]), str(idmap[kb])
    qa = int(bykey[ka].get("装量") or 0)
    qb = int(bykey[kb].get("装量") or 0)
    ta = (byid.get(ia) or {}).get("title")
    tb = (byid.get(ib) or {}).get("title")
    na, nb = G._qty_of_front_title(ta), G._qty_of_front_title(tb)

    L("① ID 互换校验")
    L("   %-20s 装量=%-4s id=%-11s 后台数量=%-5s title=%s" % (ka, qa, ia, na, ta))
    L("   %-20s 装量=%-4s id=%-11s 后台数量=%-5s title=%s" % (kb, qb, ib, nb, tb))
    if na == qa and nb == qb:
        L("   → 已是正确状态，跳过（幂等）")
    else:
        idmap[ka], idmap[kb] = ib, ia
        L("   → 交换：%s %s→%s ｜ %s %s→%s" % (ka, ia, ib, kb, ib, ia))
        for k, newpid in ((ka, ib), (kb, ia)):
            it = bykey[k]
            old = str(((it.get("p2pah") or {}).get("后台商品ID")) or "")
            if old:
                it.setdefault("p2pah", {})["后台商品ID"] = newpid
                L("     · %s.p2pah.后台商品ID %s → %s" % (k, old, newpid))

    # ── ② 关键词补全 ─────────────────────────────────────────
    L("② 商品名关键词补全")
    for k, newkw in KW_FIX.items():
        it = bykey.get(k)
        if not it:
            L("   ✘ %s：对照项不存在，跳过" % k)
            continue
        old = (it.get("p2pah") or {}).get("商品名关键词")
        if old == newkw:
            L("   · %-22s 已是 %r，跳过" % (k, newkw))
            continue
        it.setdefault("p2pah", {})["商品名关键词"] = newkw
        L("   ✓ %-22s %r → %r" % (k, old, newkw))

    # ── ③ 用修正后的配置做闸一预演 ───────────────────────────
    L("")
    L("③ 闸一预演（用修正后的配置，对 %d 行后台清单）" % len(rows))
    drifts, checked = G.detect_binding_drift(cfg, rows, log=L)
    L("   核对 %d 档，漂移 %d 处" % (checked, len(drifts)))
    d4k = set(str(it.get("key")) for it in ((cfg.get("商品映射") or {}).get("对照项") or [])
              if str(it.get("游戏")) == "暗黑破坏神4")
    d4d = [d for d in drifts if d.get("key") in d4k]
    oth = [d for d in drifts if d.get("key") not in d4k]
    L("   其中 D4（游戏=暗黑破坏神4）：%d 处" % len(d4d))
    for d in oth:
        L("   非 D4 残留：· [%s] %s" % (d.get("key"), d.get("msg")))

    if a.apply:
        tmp = a.cfg + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(cfg, ensure_ascii=False, indent=indent))
            f.write("\n")
        os.replace(tmp, a.cfg)
        L("")
        L("✅ 已写回 %s" % a.cfg)
    else:
        L("")
        L("（DRY-RUN，未写盘。加 --apply 生效）")
    return 0 if len(d4d) == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
