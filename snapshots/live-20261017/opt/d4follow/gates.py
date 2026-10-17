# -*- coding: utf-8 -*-
"""三道闸门补丁（2026-10-05）· 引擎侧

针对两起已实证的事故：
  ① 装量抢行   —— 人工把 `(10) Lair Key` 改成 `(1000)`，配置里 `X10` 的装量被带着改成 1000，
                 与 `_X1000` 构成「同物品同数量重复」，`_X10` 永久抢占前台行，
                 `_X1000` 变成幽灵、每轮吃 4 天前的冻结快照（8.3815 vs 真实 2.3371）。
  ② 跟价暴冲   —— `CORRUPTED_ROOTS_X10` 前台真实从 $3.51 跌到 $0.3264，
                 引擎拿 $0.0326（×10 整包价）当基准算出 target $0.2984（≈9 倍），
                 写进 ×10 行 ⇒ 前端显示 $25.87。

三道闸都做成**配置化旋钮**（不在代码里写死魔数），都**只加检查不改判定**：
判不满就降级成 blocked/hold 并写明原因，绝不静默改数据。

────────────────────────────────────────────────────────────────────────
闸一 · 绑定漂移检测 detect_binding_drift()
    对「已登记后台商品ID」的档位，核对三件事：
      ID 在不在 / 商品名变没变 / 数量变没变
    任一不符 ⇒ 返回漂移记录，交由调用方**停手报警**。

    ⭐ 关键设计：**绝不自动改配置**。
      2026-10-01 那次事故正是「系统悄悄把装量改成 1000」造成的 ——
      自动接受人工改动 = 把错误固化成"正确"，还会顺手带走别人的行。
      正确做法是停下来告诉人：「这行原来是 10 装、现在叫 1000 装，你怎么定？」

闸二 · 数量冲突检测（装量唯一性）
    同一物品名 + 同一数量出现多条档位 ⇒ 它们会互相抢前台行。
    改价时对撞上就停手，并指名道姓告诉哪几条撞了。

闸三 · 单轮跟价幅度上限 clamp_round_step()
    单轮目标价相对现价的变动不超过该方向的限幅（默认 ±50%）。
    2026-10-10 起**分向**：`单轮幅度上限_涨` / `单轮幅度上限_跌` 各自独立，
    缺键回落旧的 `单轮幅度上限`。老板要求「解锁跟涨、跟跌不变」⇒ 涨设 0（关闭）、跌保持 0.5。
    超了不跟随，判 blocked —— 宁可慢一拍，不让 $0.43 一步跳成 $25.87。
"""


# ────────────────────────────────────────────────────────────── 闸一：绑定漂移

def strip_qty_prefix(title):
    """🔴 剥掉商品名里的数量前缀/后缀，只留物品名本体。

    这是「数量从名称里剥离」在闸门侧的落地 —— 不剥的话：
      配置关键词 'Lair Key'          vs 后台 '(1000) Lair Key'
      归一化后 'lairkey' vs '1000lairkey' ⇒ 每次都误报「改名」。

    支持前缀 `(1000) Xxx` 与后缀 `Xxx * 100` / `Xxx ✕100` 两种写法。
    """
    import re
    s = str(title or "").strip()
    if not s:
        return "", None
    m = re.match(r"^\s*\(\s*(\d+)\s*\)\s*(.+)$", s)
    if m:
        return m.group(2).strip(), int(m.group(1))
    m = re.match(r"^\s*(\d+)\s*(.+)$", s)          # 无括号：1000Lair Key
    if m:
        return m.group(2).strip(), int(m.group(1))
    m = re.search(r"^(.+?)\s*[*✕✖x]\s*(\d+)\s*$", s, re.I)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return s, None


def _norm_txt(s):
    """物品名归一化：先剥数量前缀，再只保留字母/数字/**中日韩文字**。

    ⚠ 中文必须保留。早前用 `[^a-z0-9]+` 把中文全滤掉了，于是
    `Lair Key(改了名)` 归一化成 `lairkey` == 配置的 `lairkey`
    ⇒ **改了中文名反而检测不到**（漏报），恰是最该拦的场景。
    """
    import re
    base, _q = strip_qty_prefix(s)
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", base.lower())



# ── 闸一标题剥尾括号注释 2026-10-05 ──
_OPEN = "（([【"
_CLOSE = "）)]】"


def _strip_tail_parens(s):
    """剥掉**尾部**成对的括号注释（最多 4 层），字符串中间的一律不动。

    用配对扫描而不是正则 —— 真实数据里括号是**混用嵌套**的：
        "ARC Alloy （[材料] ARC合金）"                      中文括号套方括号
        "Loadout No.1 （[BD配装] No.1——[战斗MK.3 (侧翼突击） …]"  四层混排
    正则 `[^（()\[\]【】]*` 会因「内层含另一种括号」而失配（实测只消掉 7/596）。

    做法：从尾部找第一个右括号，向左扫描配对到左括号，整段剥掉。
    类型不敏感（`（`↔`)`、`[`↔`]` 互认），因为真实数据就是这样混着写的。
    """
    t = str(s or "").strip()
    for _ in range(4):
        # 找尾部最后一个右括号
        end = -1
        for i in range(len(t) - 1, -1, -1):
            if t[i] in _CLOSE:
                end = i
                break
        if end < 0:
            break
        # 向左找配对的左括号（深度计数）
        depth = 0
        start = -1
        for i in range(end, -1, -1):
            c = t[i]
            if c in _CLOSE:
                depth += 1
            elif c in _OPEN:
                depth -= 1
                if depth == 0:
                    start = i
                    break
        if start < 0:
            break                       # 配不上（如 `Lair Key (1000` 缺右括号）→ 放弃
        t2 = t[:start].strip()
        if not t2 or t2 == t:
            break
        t = t2
    return t


def _norm_title(s):
    """闸一专用：先剥尾部括号注释，再走 _norm_txt。

    2026-10-05：后台商品名普遍带中文注释（`ARC Alloy （[材料] ARC合金）`），
    直接归一化会把注释里的中文也参与比较 ⇒ 596 条全是误报。
    先剥掉整段注释再比，商品身份才对得上。
    """
    return _norm_txt(_strip_tail_parens(s))

def _qty_of_front_title(title):
    """从前台商品名解析数量：`Lair Key * 100` / `(1000) Lair Key` → 100；
    **没有数量标记时返回 None**（表示「未标注」，不是「1 装」）。

    ⚠ 关键：早前版本在无标记时返回 1，于是 `Lair Key`（实际是 ×100 档，
    前台就这么写）被判成 1 装、与配置 100 不符 ⇒ 正常场景全量误报。
    「未标注」与「标注为 1」必须区分开。"""
    _base, q = strip_qty_prefix(title)
    return q


# ── 闸一改读权威源 2026-10-05 ──
def _idmap_of(cfg):
    """后台商品ID 的**权威源**：p2pah.商品ID映射。

    core_p2pah.ids_of() 的取值顺序是「商品ID映射 → _重复上架 → 对照项字段」，
    映射表优先。闸一必须跟它同口径，否则会静默漏覆盖
    （实测两处值零冲突，闸一却因为只读次要字段而少覆盖 331 条）。
    """
    return (((cfg or {}).get("p2pah") or {}).get("商品ID映射") or {})


def _pid_of(it, idmap):
    """取该档位登记的后台商品ID：权威源优先，对照项字段兜底。"""
    k = it.get("key")
    v = str((idmap or {}).get(k) or "").strip()
    if v and v != "None":
        return v
    v = str(((it.get("p2pah") or {}).get("后台商品ID")) or "").strip()
    return "" if v == "None" else v


# ── 金币数量豁免 2026-10-05 ──
_AMOUNT_KW = ("gold", "coin", "silver", "money", "cash",
              "金币", "金币数", "现金")


def _is_amount_style(it):
    """该档位的「装量」是金额语义而非个数语义（金币/现金类）。

    典型：`10,000 Gold` —— 名字里的数字是**这笔钱有多少**，不是**几件**。
    拿它当件数比对必然全错（闸一改读权威源后 4 条 POE2 GOLD 全被误停手）。

    判据：关键词或中文名里含金额单位词，且配置装量为 1 或未设。
    只豁免**数量比对**，ID 与标题照旧核对。
    """
    e = (it.get("p2pah") or {}).get("商品名关键词") or it.get("中文名") or ""
    low = str(e).lower()
    if not any(u in low for u in _AMOUNT_KW):
        return False
    try:
        q = float(it.get("装量"))
    except (TypeError, ValueError):
        q = 1.0
    return q <= 1.0



def detect_binding_drift(cfg, backend_rows, log=print, key_filter=None):
    """🔴 闸一：核对「后台商品ID ↔ 商品名 ↔ 数量」三重绑定是否被改动。

    backend_rows: [{'id': str, 'title': str, ...}, ...]  —— 从后台读到的当前真实清单
    返回 (drift_list, checked_count)：
      drift_list 每项 = {'key','level','id','expect_title','actual_title','expect_qty','actual_qty','msg'}
      level: 'id_gone'（后台找不到该 ID）| 'title_changed'（改名）| 'qty_changed'（改了数量）

    ⚠ 只读。发现漂移**不改配置、不改价**，交由调用方报警给用户拍板。
    """
    idmap = _idmap_of(cfg)
    by_id = {}
    for r in (backend_rows or []):
        rid = str((r or {}).get("id") or "").strip()
        if rid:
            by_id[rid] = r

    drifts = []
    checked = 0
    for it in ((cfg or {}).get("商品映射") or {}).get("对照项") or []:
        key = it.get("key")
        if key_filter and key not in key_filter:
            continue
        pid = _pid_of(it, idmap)
        if not pid:
            continue                      # 未登记 ID 的档位不参与本闸（等 ID 补齐后自然覆盖）
        checked += 1

        row = by_id.get(pid)
        if not row:
            drifts.append({"key": key, "level": "id_gone", "id": pid,
                           "expect_title": it.get("中文名"), "actual_title": None,
                           "expect_qty": it.get("装量"), "actual_qty": None,
                           "msg": "后台已找不到 ID %s（可能被你删了），本档位停手" % pid})
            continue

        a_title = row.get("title")
        e_title = it.get("p2pah", {}).get("商品名关键词") or it.get("中文名")
        # ── 闸一标题剥尾括号注释 2026-10-05 ──
        if e_title and a_title and _norm_title(a_title) != _norm_title(e_title):
            drifts.append({"key": key, "level": "title_changed", "id": pid,
                           "expect_title": e_title, "actual_title": a_title,
                           "expect_qty": it.get("装量"), "actual_qty": None,
                           "msg": "ID %s 改名：配置「%s」→ 后台「%s」"
                                  % (pid, e_title, a_title)})

        if _is_amount_style(it):
            continue          # 金币类：装量是金额不是件数，只比 ID 与标题
        e_q = it.get("装量")
        a_q = _qty_of_front_title(a_title)
        try:
            e_q = int(e_q) if e_q not in (None, "") else None
        except (TypeError, ValueError):
            e_q = None
        if e_q and a_q and e_q != a_q:
            drifts.append({"key": key, "level": "qty_changed", "id": pid,
                           "expect_title": e_title, "actual_title": a_title,
                           "expect_qty": e_q, "actual_qty": a_q,
                           "msg": "ID %s 数量被改：配置 %s 装 → 后台现在是 %s 装（%s）"
                                  % (pid, e_q, a_q, a_title)})

    if drifts:
        log("  🛑 绑定漂移 %d 处（这些档位本轮**停手改价**，请确认后再处理）：" % len(drifts))
        for d in drifts:
            log("     · [%s] %s" % (d["key"], d["msg"]))
    return drifts, checked


def audit_qty_collisions(cfg, log=print):
    """🔴 闸二：同一物品 + 同一数量出现多条档位 ⇒ 会互相抢前台行。

    2026-10-01 实证：LAIR / GREATER_LAIR / SUPERIOR_LAIR 三族的 `X10`（装量被改成 1000）
    与 `_X1000` 装量重复，`X10` 在配置列表靠前、严格大于比较下永久抢占，后者变幽灵。
    """
    import re as _re
    buckets = {}
    for it in ((cfg or {}).get("商品映射") or {}).get("对照项") or []:
        if it.get("前台商品名"):
            continue                      # 多游戏条目走 to_multi_rows，不参与 D4 匹配
        try:
            q = int(it.get("装量", 1) or 1)
        except (TypeError, ValueError):
            continue
        base = _re.sub(r"_x?\d+$", "", str(it.get("key") or ""), flags=_re.I)
        buckets.setdefault((base, q), []).append(it.get("key"))

    collisions = {k: v for k, v in buckets.items() if len(v) > 1}
    if collisions:
        log("  🛑 同物品同数量冲突 %d 组（这些档位会互相抢前台行，本轮**停手改价**）："
            % len(collisions))
        for (base, q), ks in sorted(collisions.items()):
            log("     · %s ×%s → %s" % (base, q, "、".join(ks)))
    return collisions


# ─────────────────────────────────────────────────── 闸三：单轮跟价幅度上限

def clamp_round_step(cfg, ours_bid, tgt):
    """🔴 闸三：单轮目标价相对现价的变动不超过配置上限（默认 ±50%）。

    2026-10-02 实证（腐化根藤）：前台真实暴跌 90%（$3.51 → $0.3264），
    引擎拿跌后的现价当基准算出 9 倍目标价，直接把 ×10 行写成 $25.87。
    根因不是装量，是**没有任何单轮幅度约束** —— 竞品真正常见的 ±5~30% 波动必须照跟，
    但 ±900% 这种一眼就不对的东西必须拦住。

    返回 (new_tgt, clamped_bool, limit_pct)。
    ⚠ 拦下时**不静默改价**，由调用方判 blocked 并写明原因。

    旋钮语义（2026-10-10 拆成**分向**两个旋钮，方向独立）：
      · `引擎.单轮幅度上限_涨` —— **涨**方向的限幅（ratio > 0 时用）
      · `引擎.单轮幅度上限_跌` —— **跌**方向的限幅（ratio < 0 时用）
      · `引擎.单轮幅度上限`   —— 兼容旧配置的兜底值（分了向的键缺哪个就用它）
    **某一向的值设 0 或负数 = 该方向显式关闭限幅**（不是"回退到默认"，
    否则用户想关都关不掉 —— 分册铁律 15：不确定的旋钮别留两头语义）。

    2026-10-10 老板要求：**解锁跟涨**（涨方向设 0 = 不再挡超过 +50% 的涨），
    **跟跌不变**（跌方向仍 0.5 = ±50%）。缺键时行为与拆分前**一字不差**。
    """
    eng = ((cfg or {}).get("引擎") or {})
    try:
        lim_both = float(eng.get("单轮幅度上限", 0.5))
    except (TypeError, ValueError):
        lim_both = 0.5
    if not ours_bid or not tgt:
        return tgt, False, lim_both

    try:
        ours_bid = float(ours_bid)
        tgt = float(tgt)
    except (TypeError, ValueError):
        return tgt, False, lim_both
    if ours_bid <= 0:
        return tgt, False, lim_both

    ratio = (tgt - ours_bid) / ours_bid
    # 方向旋钮：本向显式给了键就用它，缺键回落 单轮幅度上限
    _key = "单轮幅度上限_涨" if ratio > 0 else "单轮幅度上限_跌"
    if _key in eng:
        try:
            lim = float(eng.get(_key))
        except (TypeError, ValueError):
            lim = lim_both
    else:
        lim = lim_both
    if lim <= 0:                       # 该方向显式关闭
        return tgt, False, lim
    if abs(ratio) <= lim:
        return tgt, False, lim
    cap = ours_bid * (1.0 + lim) if ratio > 0 else ours_bid * (1.0 - lim)
    # 限幅后必须仍为正，避免把价格压成 0/负数
    if cap <= 0:
        cap = ours_bid
    return cap, True, lim
