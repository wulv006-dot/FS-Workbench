# -*- coding: utf-8 -*-
"""货架纳管补丁生成（P2：只生成 diff，绝不落盘）

消费 shelf_check.detect() 的产出，转成**人可读的补丁草稿**给用户审阅：
  · new_items  建议新增的对照项（照抄同族已有档位的范式）
  · fix_dup    建议清理的「_重复上架」错误关系
  · diff_text  统一 diff 风格文本（供页面展示 / 复制）

⚠ 本模块纯函数式：不写 config、不写 db、不写价格。
  真正的落盘由 P3 的按钮（走 app.save_cfg）完成。
"""
import json
import copy
import re

_KEY_PACK_RE = re.compile(r"_X(\d+)$")


def key_pack(key):
    m = _KEY_PACK_RE.search(str(key or ""))
    return int(m.group(1)) if m else 1


def _base_key(key):
    """去掉 _X<n> 后缀：CRUX_X100 → CRUX"""
    return _KEY_PACK_RE.sub("", str(key or ""))


def _all_items(cfg):
    return list(((cfg.get("商品映射") or {}).get("对照项") or []))


def _find_item(cfg, key):
    for it in _all_items(cfg):
        if it.get("key") == key:
            return it
    return None


def _stem_of_name(name):
    """从中文名去尾巴：'伪先知的奥义 ×100' → '伪先知的奥义'"""
    return re.sub(r"\s*[×xX*]\s*\d+\s*$", "", str(name or "")).strip()


def _sibling_template(cfg, base_key):
    """找同族已有档位作为范式模板。优先 X1（最完整），其次任意同 base。"""
    cands = [it for it in _all_items(cfg)
             if _base_key(it.get("key")) == base_key]
    if not cands:
        return None
    # 优先装量最小的那个（一般是基准档，字段最全）
    cands.sort(key=lambda x: int(x.get("装量") or 1))
    return cands[0]


def _build_item(cfg, base_key, pack, front_name, game=""):
    """按同族范式生成一个新对照项草稿。"""
    tpl = _sibling_template(cfg, base_key)
    if not tpl:
        return None
    it = copy.deepcopy(tpl)
    old_pack = int(tpl.get("装量") or 1)
    new_key = "%s_X%d" % (base_key, pack) if pack != 1 else base_key

    it["key"] = new_key
    it["装量"] = pack
    if game:
        it["游戏"] = game

    # 中文名：把原有装量尾巴换成新装量
    stem = _stem_of_name(tpl.get("中文名") or base_key)
    it["中文名"] = "%s ×%d" % (stem, pack)

    # 千岛刻度
    qd = it.get("千岛") or {}
    qd["刻度"] = pack
    it["千岛"] = qd

    # iggm 计数（IGGM 没有该装量档时用 1 装 × N，与 CRUX_X10 同范式）
    ig = it.get("iggm") or {}
    ig["计数"] = pack
    it["iggm"] = ig

    # p2pah 装量
    p = it.get("p2pah") or {}
    p["装量"] = pack
    p["后台商品ID"] = ""   # 留空 = 等 P3 落盘时用后台行 id 回填
    it["p2pah"] = p

    it["跟价"] = True
    it.pop("_映射", None)
    it["_映射"] = {
        "判定": "由 P2 货架自检生成（同族 %s 范式）" % tpl.get("key"),
        "后台行名": front_name or "",
    }
    return it


def _compress(obj, indent=2):
    """给 diff 用：把对照项压成紧凑多行 JSON"""
    return json.dumps(obj, ensure_ascii=False, indent=indent)


def build(cfg, drift, log=None):
    """drift = shelf_check.detect(...) 的返回。
       返回 {"new_items":[...], "fix_dup":[...], "diff_text":str, "counts":{...}}
    """
    def _lg(m):
        if log:
            log(m)

    base = (cfg.get("p2pah") or {}).get("商品ID映射") or {}
    dup = base.get("_重复上架") or {}

    new_items, fix_dup, seen = [], [], set()

    # ---------- 1) S1 未纳管档位 → 生成新对照项 ----------
    for x in (drift.get("S1") or []):
        fname = x.get("front_name") or ""
        pack = int(x.get("pack_size") or 1)
        k2 = x.get("key") or ""
        # 有降级匹配的 key（如 CRUX_X10）→ 用它推 base；否则用后台行名推
        if k2:
            base_key = _base_key(k2)
        else:
            base_key = None
        if not base_key:
            fix_dup.append({
                "type": "manual",
                "front_name": fname, "pack_size": pack,
                "note": "无同族 key 可参考，需人工指定 base（前台名「%s」）" % fname,
            })
            continue
        if (base_key, pack) in seen:
            continue
        if _find_item(cfg, "%s_X%d" % (base_key, pack) if pack != 1 else base_key):
            # 已存在（S1 可能是关键词没对上）→ 不重复生成
            continue
        it = _build_item(cfg, base_key, pack, fname, x.get("game") or "")
        if it:
            seen.add((base_key, pack))
            new_items.append({
                "item": it,
                "key": it["key"],
                "reason": "前台在售「%s」装量 %d，config 缺该装量的对照项"
                          % (fname, pack),
            })
        else:
            fix_dup.append({
                "type": "manual",
                "front_name": fname, "pack_size": pack,
                "note": "同族 %s 找不到范式模板，需人工补" % base_key,
            })

    # ---------- 2) S2 映射错位 → 建议从 _重复上架 移除 ----------
    for x in (drift.get("S2") or []):
        k = x.get("key") or ""
        rid = str(x.get("row_id") or "")
        if not k or not rid:
            continue
        ids = dup.get(k) or []
        if str(rid) in [str(i) for i in ids]:
            fix_dup.append({
                "type": "dup_remove",
                "key": k, "row_id": rid,
                "front_name": x.get("front_name") or "",
                "pack_size": x.get("pack_size"),
                "note": "%s 的 _重复上架 含后台行 %s，但该行装量是 %s（与 key 装量 %d 不符）⇒ "
                        "应从 _重复上架 移除，避免每轮误写" % (k, rid, x.get("pack_size"), key_pack(k)),
            })

    # ---------- 3) 组织 diff 文本 ----------
    lines = []
    lines.append("【货架纳管补丁草稿】（只生成，未落盘）")
    lines.append("")
    lines.append("── 一、建议新增对照项 (%d 个) ──" % len(new_items))
    for b in new_items:
        lines.append("")
        lines.append("+ 商品映射.对照项 += %s" % b["key"])
        lines.append("  理由：%s" % b["reason"])
        for ln in _compress(b["item"]).splitlines():
            lines.append("  + " + ln)
    if not new_items:
        lines.append("  （无）")

    lines.append("")
    lines.append("── 二、建议清理 _重复上架 (%d 处) ──" % len([f for f in fix_dup if f.get("type") == "dup_remove"]))
    for f in fix_dup:
        if f.get("type") != "dup_remove":
            continue
        lines.append("")
        lines.append("- 商品映射.p2pah.商品ID映射._重复上架[%s] -= \"%s\"" % (f["key"], f["row_id"]))
        lines.append("  理由：%s" % f["note"])

    manual = [f for f in fix_dup if f.get("type") == "manual"]
    if manual:
        lines.append("")
        lines.append("── 三、需人工处理 (%d 处) ──" % len(manual))
        for f in manual:
            lines.append("  ! 前台「%s」(装量 %s)：%s" % (f.get("front_name"), f.get("pack_size"), f.get("note")))

    diff_text = "\n".join(lines)
    counts = {
        "new_items": len(new_items),
        "dup_remove": len([f for f in fix_dup if f.get("type") == "dup_remove"]),
        "manual": len(manual),
    }
    _lg("[P2] 生成补丁草稿：新增 %d / 清理 %d / 人工 %d"
        % (counts["new_items"], counts["dup_remove"], counts["manual"]))
    return {"new_items": new_items, "fix_dup": fix_dup,
            "diff_text": diff_text, "counts": counts}
