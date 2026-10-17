# -*- coding: utf-8 -*-
"""货架漂移自检（P1：只告警，不改配置）

背景（2026-10-01 用户实证）：
  用户上架了 100 装 Crux 并手动定价 $54，结果被 CRUX_X10 当"重复上架"尾随写入，
  从 09-29 到 10-01 被覆盖 20+ 次（每轮写 5.x）。根因：闸④ detect_manual_override
  只保护 config 里**存在**的 key，对被别的 key 尾随写到的行完全无感。

本模块每轮采集后跑一次，**纯读**，只做三件事：
  S1 未纳管档位  前台有 (100) X，但 config 没有对应装量的对照项
  S2 映射错位    key 的映射指向的后台行，装量与 key 后缀不符
  S3 人工价暴露  被尾随写到的行 + 我方价 != 系统最后要求值（会被每轮覆盖）

产出：
  · store.shelf_drift 表（每轮快照）
  · 日志 ⚠ 行
  · 返回值给 app 用于页面告警条 + 微信推送（仅"新增/变化"时推）

⚠ 本模块**绝不调用 save_cfg**，也绝不改任何价格。
"""
import json
import os
import re

# 装量前缀：前台商品名形如
#   "(1000) Lair Key"  "(1000)Greater Lair Key"  "(1000)Superior Lair Key"  "(10)Crux..."
# 三种空格写法都要兼容。
_PACK_RE = re.compile(r"^\s*\(\s*(\d+)\s*\)\s*")

# key 后缀 → 装量，例：CRUX_X1000 → 1000、LAIR_KEY_X10 → 10
_KEY_PACK_RE = re.compile(r"_X(\d+)$")


def front_pack(name):
    """从前台商品名解析装量；无前缀 → 1"""
    m = _PACK_RE.match(str(name or ""))
    return int(m.group(1)) if m else 1


def key_pack(key):
    """从 key 后缀解析装量；无后缀 → 1（例 CRUX → 1）"""
    m = _KEY_PACK_RE.search(str(key or ""))
    return int(m.group(1)) if m else 1


def strip_pack(name):
    """去掉装量前缀：'(100) Crux' → 'Crux'"""
    return _PACK_RE.sub("", str(name or "")).strip()


def _norm(s):
    """归一化：小写 + 去空格/引号变体，用于关键词比对"""
    s = str(s or "").lower()
    for ch in ("\u2019", "\u2018", "\u02bc", "\u2032"):
        s = s.replace(ch, "'")
    return re.sub(r"\s+", " ", s).strip()


def build_index(cfg):
    """构建对照项索引：
       by_pack  : {(归一化关键词, 装量): key}
       keys_of  : {key: 对照项}
       kbyname  : {归一化关键词: [装量...]}
    """
    by_pack, keys_of, kbyname = {}, {}, {}
    for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
        k = it.get("key")
        if not k:
            continue
        pz = int(it.get("装量") or 1)
        kw = _norm((it.get("p2pah") or {}).get("商品名关键词")
                   or it.get("中文名") or k)
        by_pack[(kw, pz)] = k
        kbyname.setdefault(kw, []).append(pz)
        keys_of[k] = it
    return by_pack, keys_of, kbyname


def find_key(cfg, front_name, pack, index=None):
    """前台商品名 + 装量 → 对照项 key（精确 / 降级），返回 (key, exact)"""
    if index is None:
        index = build_index(cfg)
    by_pack, keys_of, kbyname = index

    nm = _norm(strip_pack(front_name))
    # 1) 精确：(关键词, 装量) 直接命中；也允许关键词"包含"关系
    if (nm, pack) in by_pack:
        return by_pack[(nm, pack)], True
    for (kw, pz), k in by_pack.items():
        if pz != pack:
            continue
        if nm and (nm in kw or kw in nm):
            return k, True
    # 2) 降级：同关键词、任意装量
    cand = []
    for (kw, pz), k in by_pack.items():
        if nm and (nm in kw or kw in nm):
            cand.append((abs(pz - pack), pz, k))
    if cand:
        cand.sort()
        return cand[0][2], False
    return None, False


# ─────────────────────────────────────────────────────────
# 后台行名缓存：从 p2pah dump 里取 {row_id: name}
# ─────────────────────────────────────────────────────────
def _load_backend_names(opt_dir):
    """扫描 _p2pah_srv 下的 readgame dump，汇总 {id: name}。
       只读文件，找不到就返回 {}（自检会跳过依赖它的检查器）。"""
    out = {}
    base = os.path.join(opt_dir, "_p2pah_srv")
    if not os.path.isdir(base):
        return out
    for fn in os.listdir(base):
        if not (fn.startswith("_read") and fn.endswith(".json")):
            continue
        try:
            with open(os.path.join(base, fn), encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        rows = d if isinstance(d, list) else (d.get("rows") or d.get("data") or [])
        for r in rows:
            if isinstance(r, dict) and r.get("id"):
                nm = r.get("name") or r.get("产品名") or ""
                if nm:
                    out[str(r["id"])] = str(nm)
    return out


def detect(cfg, con, opt_dir=".", log=None):
    """跑三个检查器。返回 dict：
       {"S1":[...], "S2":[...], "S3":[...], "count":n, "skipped":[...]}
       —— 纯读，不写配置、不写价格。
    """
    def _lg(m):
        if log:
            log(m)

    import store  # 延迟导入，避免循环

    out = {"S1": [], "S2": [], "S3": [], "skipped": []}
    index = build_index(cfg)

    # ---------- S1 未纳管档位 ----------
    try:
        our_map, our_ts = store.our_latest(con)
        rows = list(our_map.values())
    except Exception as e:
        rows = []
        out["skipped"].append("S1 读我方价快照失败：%r" % e)

    for r in rows:
        key = r.get("key")
        title = r.get("title") or ""
        pz = int(r.get("pack_size") or front_pack(title) or 1)
        game = r.get("game") or ""
        # 已纳管的 key 直接跳过（key 存在即为已纳管）
        if key and key in index[1]:
            continue
        k2, exact = find_key(cfg, title, pz, index)
        if k2 is None:
            out["S1"].append({
                "game": game, "key": "", "row_id": "",
                "front_name": title, "pack_size": pz,
                "detail": "前台有「%s」(装量 %d)，但 config 无任何匹配的对照项 ⇒ 未纳管"
                          % (title, pz),
            })
        elif not exact:
            kp = key_pack(k2)
            out["S1"].append({
                "game": game, "key": k2, "row_id": "",
                "front_name": title, "pack_size": pz,
                "detail": "装量降级匹配：前台「%s」装量 %d → 匹配到 %s（装量 %d）"
                          " ⇒ 口径可能错位" % (title, pz, k2, kp),
            })

    # ---------- S2 映射错位 / S3 人工价暴露 ----------
    bnames = _load_backend_names(opt_dir)
    if not bnames:
        out["skipped"].append(
            "S2/S3 跳过：_p2pah_srv 下没有 readgame dump（后台行名缓存为空）")
        out["count"] = len(out["S1"]) + len(out["S2"]) + len(out["S3"])
        return out

    m = (cfg.get("p2pah") or {}).get("商品ID映射") or {}
    dup = m.get("_重复上架") or {}
    our_map2 = {}
    try:
        our_map2, _ = store.our_latest(con)
    except Exception:
        pass

    # 组织：key → 它声明要写的所有行 id（去重！同一 id 可能同时出现在
    # 商品ID映射 和 _重复上架 里，否则 S2 会重复报）
    decl = {}
    for k, v in m.items():
        if k.startswith("_") or not isinstance(v, str):
            continue
        decl.setdefault(k, [])
        if v not in decl[k]:
            decl[k].append(v)
    for k, ids in dup.items():
        if k.startswith("_") or not isinstance(ids, list):
            continue
        decl.setdefault(k, [])
        for i in ids:
            if str(i) not in decl[k]:
                decl[k].append(str(i))

    for k, ids in decl.items():
        want = key_pack(k)
        for rid in ids:
            nm = bnames.get(str(rid))
            if not nm:
                continue
            actual = front_pack(nm)
            if actual != want:
                out["S2"].append({
                    "game": "", "key": k, "row_id": str(rid),
                    "front_name": nm, "pack_size": actual,
                    "detail": "映射错位：%s 宣称写装量 %d，但后台行 %s 实际是「%s」(装量 %d)"
                              % (k, want, rid, nm, actual),
                })
                # S3：错位行若还有我方价，且不属于任何 key → 人工价暴露
                _orphan_check(con, our_map2, cfg, k, rid, nm, actual, out)

    out["count"] = len(out["S1"]) + len(out["S2"]) + len(out["S3"])
    return out


def _orphan_check(con, our_map, cfg, owner_key, rid, name, pack, out):
    """该错位行是否承载着"会被覆盖的人工价"。

    判据：该行被某个 key 尾随写（= S2 命中），且我方价快照里能找到同名的
    装量档 —— 说明它有真实在售/在用价格。这种情况手工定价必被每轮覆盖。
    """
    nm = _norm(strip_pack(name))
    hit = None
    for r in (our_map or {}).values():
        if _norm(strip_pack(r.get("title") or "")) == nm:
            hit = r
            break
    if not hit:
        return
    out["S3"].append({
        "game": hit.get("game") or "",
        "key": owner_key, "row_id": str(rid),
        "front_name": hit.get("title") or name, "pack_size": pack,
        "detail": "人工价暴露：后台行 %s「%s」(装量 %d) 被 %s 尾随写入，"
                  "若你手工定过价会被每轮覆盖（我方现价 $%s）"
                  % (rid, name, pack, owner_key, hit.get("price_usd")),
    })
