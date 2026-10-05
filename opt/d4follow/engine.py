# -*- coding: utf-8 -*-
"""跟价引擎

职责：把「IGGM 竞品价变化」翻译成「我方前端价应该改成多少」的决策，
并叠加所有安全闸。**引擎本身不改任何数据**，只产出决策清单；
真正落库/改前端由 apply_price.py 在 --confirm 下执行。

开关（config.跟价.模式）：
  OFF  —— 只监控、只出建议。所有决策 action 记成 hold，绝不产生写操作。
  AUTO —— 按策略算目标价，通过全部安全闸的决策 action 记成 follow_up / follow_down。

口径（2026-09-23 用户确认）：
  · 竞品参考价 = IGGM **折后**价（core_iggm 取的就是页面折后展示价 true_price）。
  · 跟价对齐的是**我方前端价（客户实付）**；后台「$每个价格」（标价）= 前端价 ÷ 后台「折扣」。
  · 策略固定一条（2026-09-27 用户要求）：
    **我方前端价 = IGGM 真价 × (1 − 让价百分比)** ——
    即「不管竞品涨还是降，都紧跟它当前价，但我方始终再低 X%」（X 默认 5）。
  · 折扣只用来把前端价换算回标价、以及算毛利，本身不参与让价计算。

为什么还要留闸：IGGM 一降价就无条件跟随，很容易把价格压到成本线以下，
所以「跟随」必须同时满足：不低于成本 × (1 + 最低毛利率)。
（2026-09-24 用户要求：删除「测试期保护 / 只允许调高」与「默认 DRY-RUN」；
  竞品涨跌一律同向跟，不再只许调高。）
"""
import math

# ── 三道闸门 2026-10-05 ──
# 闸一 绑定漂移 / 闸二 数量冲突 / 闸三 单轮幅度上限（详见 gates.py 模块 docstring）
try:
    from gates import (detect_binding_drift, audit_qty_collisions,
                        clamp_round_step)
except ImportError:      # gates.py 不在时全部降级为「不拦」，绝不因此崩掉跟价
    detect_binding_drift = None
    audit_qty_collisions = None
    clamp_round_step = None


# ---------------------------------------------------------------------------
# 偏差纠偏「只降不升」开关（2026-09-29）
#
# 生产必须保持 True。置 False 只用于「修复前后对比」的验证脚本
# （见 verify_dev_gate.py —— 同一份真实数据跑两遍，量化修复影响）。
# ⚠ 不要暴露到 config：它是行为开关，不是运营参数。
# ---------------------------------------------------------------------------
DEV_DOWN_ONLY = True


def _round_to(v, step):
    if not step or step <= 0:
        return round(v, 6)
    return round(round(v / step) * step, 6)


def fit_under_tick(v, step, disc, limit, dec=None):
    """把标价 `v` 取整到 tick，同时**保证** 前端价（v×disc）不超过 `limit`。

    ★ 为什么需要（2026-09-27 验收发现的真问题）
    ------------------------------------------------
    原来只有「四舍五入到最近 tick」。而四舍五入会**朝上**多走最多半个 tick；
    当目标价小到与 tick 同量级时，这点误差会被放大：
        例：POE2 崇高石目标前端价 $0.0000947、tick = $0.0001
            ⇒ 四舍五入到 $0.0001 ⇒ 前端价 $0.0001 = IGGM 真价
            ⇒ 「比 IGGM 低 5%」被抬成「持平」。
    用户验收口径是「最终前端价必须 ≤ IGGM 真价 × (1−让价)」，所以取整**只许朝安全侧收**：
      · 先按原口径四舍五入 → 若已满足 ≤ limit，照旧（价格几乎不变）；
      · 超了 limit ⇒ 改为**向下取整**到 tick；
      · 向下取整会变成 0（连一个 tick 都放不下）⇒ 返回 None，
        调用方必须按「不动手」处理 —— 绝不能为了凑 tick 把价**抬上去**。

    ★ 2026-09-27 补：「前端价」本身还要再舍到 `dec` 位才算客户看到的数
    -------------------------------------------------------------
    标价 4 位（dec=4）、折扣 0.9 ⇒ 前端价有 5 位小数，平台展示时要再舍一次，
    而这次舍入是**朝上**的：实测 GREATER_LAIR_KEY_X10 标价 $0.1103 × 0.9 = $0.09927
    本已 ≤ 限 $0.099275，但前端价舍到 4 位变成 $0.0993 ⇒ 又超线了。
    所以「是否超线」必须用**舍到 dec 位之后的前端价**判，并用
    「前端价能取到的最大值 ÷ 折扣」反推标价上限，再对 tick 向下取整。

    返回取整后的标价；无法满足时返回 None。
    """
    if v is None:
        return None
    r = _round_to(v, step) if step and step > 0 else round(v, 6)
    if dec is not None and (not step or step < 0.01):
        r = round(r, dec)
    if limit is None or not disc or disc <= 0:
        return r
    _eps = 1e-12
    _p = 10 ** (dec if dec is not None else 6)

    def _front(x):
        """客户实际看到的前端价（= 标价 × 折扣，再舍到 dec 位）。"""
        f = x * disc
        return round(f, dec) if dec is not None else f

    if _front(r) <= limit * (1 + _eps):
        return r
    # 向下收：先求「前端价可达的最大 dec 位值」，再换算回标价并对 tick 向下取整
    _fmax = math.floor(limit * _p + _eps) / _p
    _bid = _fmax / disc
    if step and step > 0:
        _k = int(math.floor(round(_bid / step, 9) + 1e-9))
        _fl = round(_k * step, 6)
    else:
        _fl = round(_bid, dec) if dec is not None else round(_bid, 6)
    if _fl > 0 and _front(_fl) <= limit * (1 + _eps):
        return _fl
    return None


def front_disc_of(row):
    """从一行「我方商品」记录里取**前端实测折扣**（百分数，100 = 不打折）。取不到返回 None。

    ⚠ 必须同时认两种字段名（2026-09-27 修）：
      · `front_disc`  —— 库里 `our_price` 的列名，`store.our_latest()` 读出来是这个名字
      · `_前台折扣`   —— `core_front` 刚抓回来、**还没入库**的行用的是这个名字
    采集流程里 `ours_now` 是「本轮刚抓的行」（`_前台折扣`）+「库里兜底的行」（`front_disc`）
    混在一起的，只认一个名字会让**新抓的那批折扣全部读不到**，退回 config 里的旧值 ——
    而 config 里的值恰恰是用户改折扣后最容易滞后的东西，等于白改。
    """
    if not row:
        return None
    for k in ("front_disc", "_前台折扣"):
        try:
            v = row.get(k)
            if v is not None and float(v) > 0:
                return float(v)
        except (TypeError, ValueError):
            continue
    return None


def disc_of(cfg, item_cfg):
    """后台「折扣」：前端展示价 = 我方标价 × 折扣。

    取值优先级（2026-09-25 加，为多游戏）：
      ① 对照项自己写的 `后台折扣`（最精细）
      ② `商品映射.游戏字典.<游戏>.后台折扣`（按游戏统一）
      ③ `前端.后台折扣`（全局，暗黑4 走这条）
    暗黑4 = 90（9 折），POE2 实测 = 100（前端价就是标价）。
    """
    for v in ((item_cfg or {}).get("后台折扣"),
              (((cfg.get("商品映射") or {}).get("游戏字典") or {})
               .get((item_cfg or {}).get("游戏")) or {}).get("后台折扣"),
              (cfg.get("前端") or {}).get("后台折扣")):
        try:
            d = float(v)
            if d > 0:
                return d / 100.0
        except (TypeError, ValueError):
            continue
    return 1.0

def allowance(cfg):
    """让价系数 = 1 − 让价百分比/100（我方前端价 = IGGM 真价 × 该系数）。

    **统一从这里取** —— 首次对齐工具（poe2_align / 首次对齐脚本）与引擎共用同一个字段，
    避免两边各算一套、口径悄悄漂移。
    """
    try:
        g = float(((cfg.get("跟价") or {}).get("跟随策略") or {})
                  .get("让价百分比", 0.0) or 0.0)
    except (TypeError, ValueError):
        g = 0.0
    g = max(0.0, min(g, 90.0))
    return 1.0 - g / 100.0


def units_of(item_cfg):
    """IGGM 参考价 → 我方该规格价格的「计数」倍数。

    用户口径（2026-09-25 POE2）：`Divine Orb(1000+50 Free)` 按 **1000d** 折算单价，
    赠送的 50 个算促销、不计价。所以 IGGM 的「单个价」要 ×1000 才是这行的目标价。
    IGGM 有同款套餐时直接对同款，计数=1。
    """
    try:
        n = float(((item_cfg or {}).get("iggm") or {}).get("计数", 1) or 1)
    except (TypeError, ValueError):
        n = 1.0
    return n if n > 0 else 1.0


def zone_of(item_cfg):
    """本行的**区服 / 服务器**标签（同名的东西在不同区服价格天然不同，必须分开比）。

    取法：`iggm.服务区`（最贴竞品口径）→ `p2pah.服务区` → `千岛.区服`。
    实测样例：流放之路2 = Standard / Hardcore / Forbidden Rites SC / Runes of Aldur SC；
              WoW Forever = Normal / Roleplay / PVP；暗黑破坏神4 目前为空。
    """
    it = item_cfg or {}
    for path in (("iggm", "服务区"), ("p2pah", "服务区"), ("千岛", "区服")):
        v = (it.get(path[0]) or {}).get(path[1])
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def sanity_check(cfg, items, log=None):
    """字段一致性自检（用户规则，2026-10-01）。

    ⚠ 核心前提：**`装量` 是唯一真值**。
      `key` 名（_X10 / _X100）只是**标识符**，会落后于真实装量 ——
      商品改数量时 key 通常不改名，所以**永远不能拿 key 当依据**。
      踩过的坑：
        · LAIR_KEY_X10 名字像 10 个，实际装量 1000（改过好几轮）
        · CORRUPTED_ROOTS 原来 10 个、后来改 100 个，key 没变

    校验三条（都以 `装量` 为基准）：
      ① `千岛.刻度` == 装量   —— 否则成本按错的量摊薄（倒挂 / 成本地板失效）
      ② `p2pah.装量` == 装量  —— 否则写入口径错
      ③ key 尾部数字 == 装量  —— 仅提醒，key 允许与装量不符（改名会丢历史）

    返回：问题描述列表（空 = 全部一致）。只告警，不阻断定价。
    """
    import re as _re
    bad = []
    for it in (items or []):
        k = str(it.get("key") or "")
        try:
            pk = float(it.get("装量"))
        except (TypeError, ValueError):
            continue                      # 没写装量的（ARC/DND）跳过
        if pk <= 0:
            continue
        # ① 千岛.刻度
        _sc = (it.get("千岛") or {}).get("刻度")
        if _sc is not None:
            try:
                if float(_sc) != pk:
                    bad.append("千岛.刻度=%s != 装量=%g  [%s]" % (_sc, pk, k))
            except (TypeError, ValueError):
                pass
        # ② p2pah.装量
        _pv = (it.get("p2pah") or {}).get("装量")
        if _pv is not None:
            try:
                if float(_pv) != pk:
                    bad.append("p2pah.装量=%s != 装量=%g  [%s]" % (_pv, pk, k))
            except (TypeError, ValueError):
                pass
        # ③ key 名尾部数字（仅提醒）
        _m = _re.search(r"[_xX](\d+)\s*$", k)
        if _m:
            try:
                if float(_m.group(1)) != pk:
                    bad.append("key名 %s != 装量=%g（仅提醒，key 可落后）  [%s]"
                               % (_m.group(1), pk, k))
            except (TypeError, ValueError):
                pass
    if log and bad:
        log("  ⚠ 字段一致性自检：发现 %d 处不一致（装量为真值）" % len(bad))
        for _b in bad[:20]:
            log("      · %s" % _b)
        if len(bad) > 20:
            log("      · …（其余 %d 处省略）" % (len(bad) - 20))
    return bad

def family_of(item_cfg, cfg=None):
    """「商品族」名 —— 同一件东西的**同一区服**下的不同规格（10 个装 / 100 个装）归一族。

    组成：`游戏 · 区服 · 商品基名`（空的部分自动省略），例：
      「暗黑破坏神4 · 精良巢穴钥匙」、「流放之路2 · Standard · Divine Orb」。

    ⚠ 区服**必须**参与分组：实测 POE2「神圣石」在 Standard $0.0024 / Hardcore $0.6000
      （差 250 倍），WoW gold 在 Normal / Roleplay / PVP 之间差 8 倍 —— 那是**正常**的
      区服价差，不是竞品挂错价。不分区服就会把这些正常价差误判成「同族倒挂」全拦下来。

    商品基名取法（按可靠度降序，第一个非空即用）：
      ① `千岛.商品`（例：精良巢穴钥匙）—— 最干净，人工维护的基名；
      ② `p2pah.商品名关键词`（例：Superior Lair Key）；
      ③ `中文名` 去掉 `×N / *N / (N) / N 个` 等规格后缀后的基名。

    用途：`异常闸·同族倒挂检查` 靠它把「Superior Lair Key ×10」与「×100」配成一对，
    发现 IGGM 自家两个规格的**单位价**互相矛盾时不跟着错价走（见 evaluate 里的说明）。
    """
    import re as _re
    it = item_cfg or {}
    base = ""
    for path in (("千岛", "商品"), ("p2pah", "商品名关键词")):
        v = (it.get(path[0]) or {}).get(path[1])
        if isinstance(v, str) and v.strip():
            base = v.strip()
            break
    if not base:
        nm = str(it.get("中文名") or "").strip()
        if nm:
            nm = _re.sub(r"[\s（(【\[]*[×xX*]\s*\d+\s*[)）】\]]?\s*$", "", nm)
            nm = _re.sub(r"[\s（(【\[]*\d+\s*(个|件|枚|套)?\s*[)）】\]]?\s*$", "", nm)
            base = nm.replace("单件", "").replace("单个", "").strip()
    if not base:
        return ""
    parts = [str(it.get("游戏") or "").strip(), zone_of(it), base]
    return " · ".join([p for p in parts if p])


def tier_factor_map(cfg, items):
    """批量阶梯优惠系数（用户规则，2026-10-01）。

    规则：同一「商品族」(family_of) 内，按 **装量升序** 排列；
      最低档系数 = 1.0（保持 IGGM 让价后的基准）
      第 2 档 = 0.95
      第 3 档 = 0.95 ** 2 = 0.9025
      第 N 档 = 0.95 ** (N-1)
    即「档位越高、单件越便宜」，每升一档让 5%。

    为什么按装量而不是按价格排：装量才是「一次买多少」的真实口径。
      （key 名里的 _X10/_X100 是设计命名，不等于真实装量 —— 踩过坑。）

    ⚠ 只有「同族 >=2 个不同装量」时才生效；
      装量相同的多条（如 LAIR_KEY_X10 与 _X1000 都是 1000 装）= 同档，
      系数相同，不会凭空造出阶梯。

    返回：{key: 系数}；无阶梯的 key 不出现在结果里（调用方按 1.0 处理）。
    """
    on = True
    step = 5.0
    try:
        _bj = (cfg.get("跟价") or {}).get("批量优惠") or {}
        on = bool(_bj.get("启用", True))
        step = float(_bj.get("每档让价百分比", 5.0) or 5.0)
    except (TypeError, ValueError, AttributeError):
        pass
    if not on:
        return {}
    step = max(0.0, min(step, 50.0))
    k_each = 1.0 - step / 100.0

    fam = {}
    for it in (items or []):
        f = family_of(it, cfg)
        if not f:
            continue
        try:
            pk = float(it.get("装量", 1) or 1)
        except (TypeError, ValueError):
            pk = 1.0
        if pk <= 0:
            pk = 1.0
        k = it.get("key")
        if k:
            fam.setdefault(f, []).append((pk, k))

    out = {}
    for f, rows in fam.items():
        sizes = sorted(set(r[0] for r in rows))
        if len(sizes) < 2:
            continue                      # 单档（或同装量重复）→ 无阶梯
        tier_of = {}
        for _i, _sz in enumerate(sizes):
            tier_of[_sz] = _i
        for pk, k in rows:
            t = tier_of.get(pk, 0)
            if t > 0:
                out[k] = k_each ** t
    return out


def game_dict(cfg):
    """`商品映射.游戏字典` 的干净副本（剥掉 `_说明` 这类注释键）。"""
    gd = ((cfg.get("商品映射") or {}).get("游戏字典") or {})
    if not isinstance(gd, dict):
        return {}
    return {k: v for k, v in gd.items()
            if not str(k).startswith("_") and isinstance(v, dict)}


def game_order(cfg):
    """游戏展示顺序：`游戏顺序` 优先，字典里登记过但没进顺序的接在后面。

    ⚠ 新增游戏时**不要在这里加分支** —— 只要在 config 的 `游戏字典` 登记一条，
    看板 / 控制台 / 金币明细会自动多出一段（「分区」是数据驱动的，不是写死的）。
    """
    mp = cfg.get("商品映射") or {}
    order = [x for x in (mp.get("游戏顺序") or []) if isinstance(x, str) and x]
    for g in game_dict(cfg):
        if g not in order:
            order.append(g)
    return order


def _game_by_prefix(cfg, key):
    """按 `游戏字典.<游戏>.对照项前缀` 反推游戏（兜底用）。

    为什么需要它：金币行（`GOLD_S15_SC`）**不在对照项里**，只存在于
    `config.金币.服务区`；旧 config 也没有 `游戏` 字段。前面几轮靠"硬编码默认游戏"
    兜底，一旦新增游戏就会把别人的 key 认成暗黑4。改用显式前缀表。
    """
    k = str(key or "").upper()
    if not k:
        return None
    gd = game_dict(cfg)
    for g in game_order(cfg):
        for p in ((gd.get(g) or {}).get("对照项前缀") or []):
            p = str(p).upper()
            if p and k.startswith(p):
                return g
    return None


def default_game(cfg):
    seq = game_order(cfg)
    return seq[0] if seq else "暗黑破坏神4"


def game_of(cfg, key):
    """key → 我方游戏中文名。**这是唯一入口**，别各处再自己猜。

    三级：① 对照项里的「游戏」字段（最权威）→ ② `金币.服务区[].游戏`
    → ③ `游戏字典.<游戏>.对照项前缀` 前缀匹配 → ④ `游戏顺序` 第一项。
    """
    for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
        if it.get("key") == key:
            return it.get("游戏") or default_game(cfg)
    for sv in ((cfg.get("金币") or {}).get("服务区") or []):
        if sv.get("key") == key:
            return (sv.get("游戏") or _game_by_prefix(cfg, key)
                    or str((cfg.get("金币") or {}).get("挂载游戏")
                           or default_game(cfg)))
    return _game_by_prefix(cfg, key) or default_game(cfg)


def is_gold_key(cfg, key):
    """是不是「金币」行 —— 决定它归看板的金币明细区还是跟价主表。

    两条来源都要认：
      ① `config.金币.服务区[].key`（暗黑4，走后台「金币价格管理」采购成本机制）
      ② key 以 `_GOLD` 结尾（POE2 这类，金币在后台是 Quick Gold 普通商品，走物品机制）
    """
    for sv in ((cfg.get("金币") or {}).get("服务区") or []):
        if sv.get("key") == key:
            return True
    return str(key or "").upper().endswith("_GOLD")


def gold_mount_game(cfg):
    """金币（暗黑4 采购成本机制那批）挂在哪个游戏分区下。"""
    return str((cfg.get("金币") or {}).get("挂载游戏") or default_game(cfg))


def game_meta(cfg, name):
    """游戏展示元数据（图标 / 颜色 / 英文名 / 是否预留）。"""
    v = game_dict(cfg).get(name) or {}
    return {"name": name, "en": v.get("英文") or "",
            "icon": v.get("图标") or "", "color": v.get("色") or "",
            "reserved": bool(v.get("预留"))}


def game_entry(cfg, name):
    """按「我方游戏中文名」取 `p2pah.游戏.<短码>` 那条配置。

    ⚠ 2026-09-25 踩坑：`对照项.游戏` 写的是中文名（暗黑破坏神4 / 流放之路2），
    而 `p2pah.游戏` 的键是短码（D4 / POE2）。直接 `g.get("流放之路2")` 会拿到 None
    并静默回退到 D4 → POE2 的 key 也解析成 gid=456，写价会写错游戏。
    这里做三级兼容：
      ① 键名直接相等（短码写法）
      ② `p2pah.游戏别名 = {"流放之路2": "POE2", ...}`（推荐，显式）
      ③ 条目内 `我方名` / `中文名` 字段反向匹配
    """
    g = (cfg.get("p2pah") or {}).get("游戏") or {}
    if isinstance(g.get(name), dict):
        return g[name]
    alias = (((cfg.get("p2pah") or {}).get("游戏别名")) or {})
    code = alias.get(name)
    if code and isinstance(g.get(code), dict):
        return g[code]
    for _k, v in g.items():
        if isinstance(v, dict) and name in (v.get("我方名"), v.get("中文名")):
            return v
    return {}


def game_gid(cfg, key, default="456"):
    """该 key 属于哪个游戏的后台 gid（暗黑4=456、POE2=552）。

    统一走 `game_of` + `game_entry`，别各处再自己 `p2pah.游戏.get(中文名)`
    （那是 gid 串错游戏的根因）。
    """
    gm = game_entry(cfg, game_of(cfg, key))
    if gm.get("game_id"):
        return str(gm["game_id"])
    return str(((cfg.get("p2pah") or {}).get("游戏") or {})
               .get("D4", {}).get("game_id") or default)


def cost_usd_of(item_cfg, qd_row, rate):
    """千岛进货成本 → 美元口径

    刻度: 1 个千岛报价单位 = 多少个本商品的计量单位。
    例：千岛「巢穴钥匙」0.0693 元/个；IGGM「Lair Key * 10」是 10 个装，
        刻度=10 → 成本 = 0.0693 × 10 = 0.693 元 → /6.65 = 0.1042 美元。
    """
    if not qd_row:
        return None, None
    try:
        cny = float(qd_row.get("price_cny") or 0)
    except (TypeError, ValueError):
        return None, None
    if cny <= 0:
        return None, None
    scale = float((item_cfg.get("千岛") or {}).get("刻度", 1) or 1)
    total_cny = cny * scale
    return total_cny, (total_cny / float(rate) if rate else None)


def compute_target(item_cfg, strategy_cfg, iggm_new, ours_old=None, iggm_old=None,
                   front_disc=1.0):
    """算「我方应对标的价格」——返回的是**标价**口径（= 后台「$每个价格」）

    ⭐ 当前口径（2026-09-27 用户定案）：
        **我方前端价（客户实付）= IGGM 真价 × (1 − 让价百分比/100)**
        标价 = 前端价 ÷ 后台折扣（折扣从配置读，折扣一改自动跟随，不写死）
    让价默认 5 ⇒ 「紧跟竞品当前价，但始终比他们低 5%」。
    沿革：2026-09-24 曾定为「前端 = IGGM 折后价」（持平、不让价）；09-27 改成恒定让价 5%。

    已删除的三个旧分支：`fixed_gap` / `benchmark_delta` / `relative_follow`
    —— 它们不被任何配置使用；且 `benchmark_delta` 的口径与「标价 = 前端价 ÷ 折扣」
    不兼容（会把折扣算漏一次，前端会变成 0.9×0.95×竞品价、比竞品低 14.5%），
    留着只会误导后人。`相对IGGM系数` 一并归档（等价替代 = 让价百分比）。
    `ours_old` / `iggm_old` 两个入参保留只为兼容调用方，本口径下不再使用。
    """
    if iggm_new is None:
        return None
    # 让价百分比：我方前端价比 IGGM 真价低多少（**百分数**，5 = 低 5%）。
    # 夹在 0~90，避免配置写错把价格打成 0 或负数。
    try:
        gap_pct = float(strategy_cfg.get("让价百分比", 0.0) or 0.0)
    except (TypeError, ValueError):
        gap_pct = 0.0
    gap_pct = max(0.0, min(gap_pct, 90.0))
    k = 1.0 - gap_pct / 100.0
    _fd = float(front_disc or 1.0)
    if _fd <= 0:
        _fd = 1.0
    return iggm_new * k / _fd


def margin(price_usd, cost_usd):
    if not price_usd or price_usd <= 0 or cost_usd is None:
        return None
    return (price_usd - cost_usd) / price_usd


# ── backend_rows 装载 2026-10-05 ──
def load_backend_rows(cfg, data_dir=None, log=None):
    """读本机执行器落下的后台商品清单，供闸一核对「ID ↔ 名称 ↔ 数量」。

    为什么需要它：`evaluate(..., backend_rows=)` 这个参数一直没人传，
    闸一在生产从未真正生效（此前误判为「对 D4 不生效」）。

    为什么服务器侧不现取：后台按来源 IP 拦机房 IP，实测服务器上
    `P2PAHClient.request(list_url(...))` 返回的是登录页 HTML 而非商品列表。
    所以由**本机执行器**取一次、落盘到 data/backend_items.json，
    服务器每轮只读文件。

    返回 [] 表示「本轮没有清单」，调用方据此跳过闸一 —— 绝不阻塞定价。
    """
    import json as _json
    import os as _os
    if not data_dir:
        data_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data")
    p = ((cfg or {}).get("闸门") or {}).get("后台清单路径") or "backend_items.json"
    fp = p if _os.path.isabs(p) else _os.path.join(data_dir, p)
    try:
        if not _os.path.exists(fp):
            if log:
                log("  ℹ️闸一：本机未落后台清单（%s），本轮跳过绑定漂移检测"
                    % _os.path.basename(fp))
            return []
        with open(fp, encoding="utf-8") as f:
            j = _json.load(f)
        rows = j.get("rows") if isinstance(j, dict) else j
        rows = rows or []
        if log:
            log("  🔒 闸一：读到后台清单 %d 条（%s），核对 ID ↔ 名称 ↔ 数量"
                % (len(rows), _os.path.basename(fp)))
        return rows
    except Exception as e:
        if log:
            log("  ⚠️ 闸一：读后台清单失败（%r），本轮跳过绑定漂移检测" % (e,))
        return []


def evaluate(cfg, items, iggm_now, iggm_prev, ours_now, qd_map, ts,
             log=print, disc_changed_games=None, manual_override=None,
             line_pending=None, backend_rows=None):
    """产出决策清单。

    items       : config.商品映射.对照项
    iggm_now    : {goods_no: row}
    iggm_prev   : {goods_no: row} 上一次快照
    ours_now    : {key: row}
    qd_map      : {key: qd_row}
    disc_changed_games : 本轮「后台折扣与上一轮不同」的游戏名集合（可为 None）。
    manual_override    : {key: {iggm_new, ...}} 「人工调价保护」表（2026-09-29 条件B）
                         我方现价是人工改的、且 IGGM 真价自那次改动以来未变
                         ⇒ 偏差纠偏通道不出目标价（详见下方触发判定里的注释）。
    line_pending       : {key: {bid_new, front_new, ts, job, age_h, status}}
                         「按行 pending 闩」表（2026-09-29）：该行近 N 小时内**已经出过单**、
                         单要求的目标标价与本轮算出来的**完全一致**、但我方现价还没变成
                         那个价 ⇒ 说明这是「前台生效慢」而不是「新的变化」⇒ 本轮不重复
                         出单（详见下方触发判定里「按行 pending 闩」段的注释）。

    ★ 为什么需要 disc_changed_games（2026-09-27 用户要求）
    -----------------------------------------------------
    用户原话：「我取消了 10% 折扣……我经常会修改物品的折扣，你需要根据是否有折扣
              来修改对应的价格」。

    而引擎的评估闸是「只在 IGGM 本轮真变价时才评估」。折扣一改、IGGM 没动 ⇒ 本轮
    一条目标价都不出 ⇒ 后台标价**原样留着按旧折扣算出来的数**：
        后端标价 = 目标前端价 ÷ 旧折扣(0.9)   →  折扣改成 100 后
        前端价 = 该标价 × 1.0 = 目标前端价 × 1/0.9 = **凭空贵 11.1%**
    实测就是这么发生的：decisions 最新 687 行可比里，中位/四分位**全部 = 1.1111**。
    所以折扣一变，必须让这些游戏**跳过「IGGM 未变价」这道闸**，按当前折扣重算标价。
    （注意：这不是原来那个「偏离纠正」通道 —— 那个是拿我方价与目标价的偏差当触发，
      任何价格噪声都会点火；这里只认「折扣配置本身变了」这一件事，方向明确、不误触发。）
    """
    g = cfg["跟价"]
    mode = str(g.get("模式", "OFF")).upper()
    rate = float(cfg["汇率"]["USDCNY"])

    def _usd(v):
        """价格展示用（None → '-'），文案里到处都是，避免重复写 try 格式化"""
        try:
            return "%.4f" % float(v)
        except (TypeError, ValueError):
            return "-"

    # 千岛对标区服名（用于「成本不可信」时的告警文案）
    qd_base_spec = str((cfg.get("千岛") or {}).get("对标区服") or "")
    sc = g.get("跟随策略", {})
    trig = g.get("触发", {})
    min_chg = float(trig.get("最小变化百分比", 0.0))
    dead = float(trig.get("抖动死区百分比", 0.0))
    # ★ 按行 pending 闩的保留窗口（2026-09-29）：只认这么多小时内创建的工单。
    #   实测前台生效延迟最长 5h57m（ARC_2772640663 单 04:58:53 成功、前台 10:56 才刷出），
    #   取 8 小时留余量；超过窗口的单不再挡（兜底：哪怕前台一直没生效也不会永远不出单）。
    try:
        # ⚠ 不能写 `float(x or 8)`：值是 0（= 关闭本闩）时会被默认值吃掉。
        _lpv = (g.get("按行pending") or {}).get("保留小时", 8)
        _lp_keep_h = 8.0 if _lpv is None else float(_lpv)
    except (TypeError, ValueError, AttributeError):
        _lp_keep_h = 8.0
    # ★ 偏差纠偏闸（2026-09-27 用户口径重新启用，见下方触发判定）
    #   用户原话：「其实你只要核对最终修改后的前端价格是比IGGM的实际价格还低5%就行了，
    #              这不就解决问题了。每次改完看下」。
    #   只靠「IGGM 变价才评估」是**跟变化**，追不上「口径本身变了」——实测就是这样：
    #     · ARC Raiders 前端折扣早就从 90 改成 100 了，config 还写 90
    #       ⇒ 583 条前端价全部比目标高 11.1%（= 1/0.9），而 IGGM 一直没动，一条单都不出；
    #     · POE2 的让价 5% 是 09-27 才定的，之前按「持平」写的 9 条一直挂着。
    #   所以补一条：**只要我方前端价与目标前端价的偏差超过该阈值，就出目标价**，
    #   让它回到「我方前端价 = IGGM 真价 × (1−让价)」这条不变式上。
    #   置 0 = 关闭（恢复 09-24 那版「只跟 IGGM 变化」的行为）。
    try:
        dev_thr = float(trig.get("偏差纠偏百分比", 5.0) or 0.0)
    except (TypeError, ValueError):
        dev_thr = 5.0
    # ★ 最小变动闸（2026-09-27 新增，修「每轮无意义重写 677 条」）
    #   由来：折扣动态化上线后，「折扣变更」通道 + pending 闩 会把整局商品每轮重算一遍。
    #   而「标价 = 前端价 ÷ 折扣」这一步在 dec=4 的精度下天生带 ±1 个 tick 的余数：
    #   实测 677 条里 634 条 |Δ标价| ≤ $0.0001（p50 = $6.667e-05），全是显示噪声。
    #   这种变动改上去**客户看不到任何差别**，却要为每一条跑约 45 秒的后台写操作
    #   （677 条 ≈ 8 小时），还会让 pending 闩永远收不了尾 → 每小时重复一遍。
    #   判据（任一成立即视为噪声、不重写）：
    #     · |Δ标价| < 绝对闸（默认 $0.001）           —— 连 1 分钱的千分之一都不到
    #     · |Δ标价| ÷ 现标价 < 相对闸（默认 0.05%）   —— 大额商品上的绝对噪声
    #   置 0 = 关闭该闸。注意它**只在标价口径**上比，与「验收不变式」无关：
    #   让价 5% 远大于这两个闸，所以「前端价 ≤ IGGM真价×0.95」照样成立。
    _mv = trig.get("最小变动") or {}
    try:
        mv_abs = float(_mv.get("绝对", 0.001) or 0.0)
    except (TypeError, ValueError):
        mv_abs = 0.001
    try:
        mv_rel = float(_mv.get("相对百分比", 0.05) or 0.0)
    except (TypeError, ValueError):
        mv_rel = 0.05
    # ★ 异常闸（2026-09-27 新增，修 `SUPERIOR_LAIR_KEY_X10` 从 $0.281 抬到 $2.8189）
    #   由来：IGGM 自家「* 10」与「* 100」两个规格的价格互相矛盾 ——
    #     实测 2026-09-27 22:09 快照（均为 IGGM 真价 price_usd）：
    #       Superior Lair Key * 10 = $2.6706  → 单位价 $0.26706/个
    #       Superior Lair Key *100 = $2.5300  → 单位价 $0.02530/个   （差 10.56 倍！）
    #       Lair Key        * 10 = $0.5278 / *100 = $0.5000  → 差 10.56 倍
    #       Greater Lair Key* 10 = $0.1045 / *100 = $0.9900  → 差 1.06 倍（**正常**的量贩折扣）
    #   IGGM 的「* 10」挂的是「10 个装的总价」，却几乎等于它自己「* 100」的总价 ——
    #   照它的 *10 报价去跟，会让我方 10 个装比 100 个装还贵 10 倍。
    #   判据：同一「商品族」（同游戏 + 同区服 + 同商品基名）内，
    #     本行 IGGM 单位价（ig_new ÷ 装量） > 族内最小单位价 × (1 + 容忍百分比)  ⇒ 判为错配
    #   默认容忍 400%（即要溢价 5 倍以上才拦）—— 实测这一档分得很干净：
    #     巢穴钥匙 = 10.56 倍、精良巢穴钥匙 = 10.56 倍  ⇒ 拦下（真错配，见上）
    #     强力巢穴钥匙 = 1.06 倍（正常量贩折扣）、暗黑4「10,000 Gold」各档 = 1.90 倍
    #                                            ⇒ 放行（同区服内正常价差）
    #   被拦的行**不动价**，并把按族内最低单位价推算的参考目标写进 reason，
    #   供人工一眼判断是「IGGM 挂错价」还是「我们映射装量错了」。
    _an = g.get("异常闸") or {}
    an_on = bool(_an.get("启用", True))
    an_inv_on = bool(_an.get("同族倒挂检查", True))
    try:
        an_inv_tol = float(_an.get("倒挂容忍百分比", 400.0) or 0.0) / 100.0
    except (TypeError, ValueError):
        an_inv_tol = 4.0
    try:
        an_max_chg = float(_an.get("单次最大涨跌幅百分比", 0.0) or 0.0)
    except (TypeError, ValueError):
        an_max_chg = 0.0
    _dch_set = set(disc_changed_games or ())
    # 「偏离纠正」触发与阈值已按要求整体移除（2026-09-24 第十五轮）：
    # 只在 IGGM 本轮真变价时才评估，不再要求「我方标价偏离目标超阈值」也触发。
    # 「单商品单次最大涨跌幅百分比」也已在 09-24 删除：部分商品涨价幅度很夸张，不做上限拦截。
    # ⚠ 2026-09-27 部分回补，但**换了性质**（见下方 `异常闸`）：
    #   · 新增「最小变动闸」（绝对 $0.001 / 相对 0.05%）—— 挡「标价÷折扣」的取整噪声，
    #     不是当年那个「最小变动($)(%)」；后者是把正常小波动也拦掉，已删。
    #   · 新增「异常闸」（同族倒挂 + 可选单次涨跌幅兜底）—— 挡数据错配（如巢穴钥匙
    #     小包装挂错价），默认不设涨跌幅上限，与 09-24 的删除决定不冲突。
    floor_m = float(sc.get("最低毛利率", -9.9))
    step = float(sc.get("取整到", 0.0) or 0)
    dec = int(sc.get("价格小数位", 4))
    # 后台「折扣」：前端展示价 = 我方标价 × 折扣。2026-09-23 实测 9/9 对上
    # （后台标注价 $0.627 → 前端 $0.5643；IGGM 折后 $0.6207 ≈ 我方标价）。
    # 安全闸一律在标价口径上比较；前端价只用来算毛利（客户实付）。
    ## 2026-09-25：折扣改为**按商品/按游戏**取（见 disc_of）——暗黑4 = 90、POE2 = 100。
    # 这里保留一个全局值，只给「同族联动」当兜底（暗黑4 用）。
    gdisc = disc_of(cfg, {})

    # ---------- 预扫描：同族最小 IGGM 单位价（供「异常闸·同族倒挂检查」用） ----------
    # 「商品族」= 同游戏 + 同中文基名。取 `千岛.商品`（最干净，例：精良巢穴钥匙），
    # 没有就退 `p2pah.商品名关键词`，再退「中文名去掉 ×N / (N) 之后的基名」。
    # 单位价 = IGGM 该规格报价(ig_new) ÷ 本规格装量 —— 这样 10 个装和 100 个装可比。
    fam_min_unit = {}
    fam_unit = {}
    # ── 批量阶梯优惠（2026-10-01 用户规则）──────────────────────
    #   同族按装量升序分档，第 N 档单价 ×(1−每档让价/100)^(N-1)。
    #   在这里一次性算好，后面每行乘上去；不改 compute_target 签名。
    _tier = tier_factor_map(cfg, items)
    if log and _tier:
        _tshow = ", ".join("%s×%.4f" % (_kk, _vv)
                         for _kk, _vv in sorted(_tier.items()))
        log("  ⇩ 批量阶梯优惠生效：%s" % _tshow)

    # ── 隐藏档位同族单位价推算 2026-10-05 ──
    # ── 我方同族单位价预扫描（供「隐藏档位」推算现价用）──────────────────
    #   前台隐藏的档位（如 ×10）匹配不到自己的前台行，只能借同族的行。
    #   这里按「前台行实测装量 pack_size」算出可信的我方单位价。
    #   ⚠ 只收 pack_size 与本行装量**一致**的行 —— pack_size 缺失或对不上的行
    #     本身就是「借来的行」，不能当基准（那正是本补丁要修的东西）。
    _it_map = {}          # key -> item
    _our_unit = {}        # key -> 我方单位价（前端价 ÷ 实测装量）
    try:
        for _it in items:
            _k = _it.get("key")
            if _k:
                _it_map[_k] = _it
            try:
                _pz = float(_it.get("装量", 1) or 1)
            except (TypeError, ValueError):
                continue
            if _pz <= 0:
                continue
            _row = ours_now.get(_k) or {}
            _ps = _row.get("pack_size")
            if _ps in (None, ""):
                continue                      # 没实测装量 → 不可信，不用
            try:
                _ps = float(_ps)
            except (TypeError, ValueError):
                continue
            if abs(_ps - _pz) > 1e-9:
                continue                      # 装量对不上 → 正是要修的那类行
            _px = _row.get("price_usd")
            if _px in (None, ""):
                continue
            try:
                _px = float(_px)
            except (TypeError, ValueError):
                continue
            if _px <= 0:
                continue
            _our_unit[_k] = _px / _ps
    except Exception as _e:
        _our_unit = {}
        if log:
            log("  ⚠ 我方同族单位价预扫描异常（不影响正常档位）：%r" % (_e,))
    # ── 隐藏档位推算日志降噪 2026-10-05 ──
    # 同族总档位数（key -> 该族在本配置里共有几档）。
    # 判「本行是不是隐藏档」的唯一依据：同族只有它一档 ⇒ pack_size 缺失是正常的，
    # 不是隐藏档，不该推算也不该刷日志。
    _fam_size = {}
    try:
        for _k3, _it3 in _it_map.items():
            _f3 = family_of(_it3, cfg) or _k3
            _fam_size[_f3] = _fam_size.get(_f3, 0) + 1
    except Exception as _e:
        _fam_size = {}
        if log:
            log("  ⚠ 同族档位统计异常（不影响定价）：%r" % (_e,))

    if log and _our_unit:
        _fam_n = {}
        for _k2 in _our_unit:
            _f2 = family_of(_it_map.get(_k2, {}), cfg) or _k2
            _fam_n[_f2] = _fam_n.get(_f2, 0) + 1
        _show = sorted(_fam_n.items(), key=lambda kv: -kv[1])[:6]
        log("  ⓘ 我方同族单位价基准：%d 档可用 / %d 族（明细前 6：%s%s）"
            % (len(_our_unit), len(_fam_n),
               "、".join("%s(%d档)" % (_f, _c) for _f, _c in _show),
               " …" if len(_fam_n) > 6 else ""))

    # ── 字段一致性自检（2026-10-01）：装量是唯一真值 ────────
    #   检查 千岛.刻度 / p2pah.装量 / key名 是否与装量一致。
    #   key 名只是标识符、允许落后；刻度/p2pah 必须跟装量走。
    try:
        sanity_check(cfg, items, log=log)
    except Exception as _e:
        if log:
            log("  ⚠ 一致性自检异常（不影响定价）：%s" % _e)
    if an_on and an_inv_on:
        for it in items:
            _gn = str((it.get("iggm") or {}).get("goods_no") or "")
            _cur = iggm_now.get(_gn) if _gn else None
            if not _cur:
                continue
            _ig = _cur.get("price_usd")
            if _ig is None:
                continue
            _ig = float(_ig) * units_of(it)
            try:
                _pz = float(it.get("装量", 1) or 1)
            except (TypeError, ValueError):
                _pz = 1.0
            if _pz <= 0:
                continue
            _fam = family_of(it, cfg)
            if not _fam:
                continue
            _u = _ig / _pz
            fam_unit[it["key"]] = (_fam, _u, _ig, _pz)
            if _fam not in fam_min_unit or _u < fam_min_unit[_fam]:
                fam_min_unit[_fam] = _u
        if log and fam_min_unit:
            _byfam = {}
            for _k, (_f, _u, _ig, _pz) in fam_unit.items():
                _byfam.setdefault(_f, set()).add(round(_u, 8))
            for _f, _us in _byfam.items():
                if len(_us) > 1:
                    log("  ⌗ 商品族「%s」内 IGGM 单位价跨度 %s（最小 $%s）"
                        % (_f, sorted(_us), fam_min_unit[_f]))

    # ── 三道闸门 2026-10-05 · 审计段 ────────────────────────────────────
    # 闸门只把 key 标成「本轮停手」，**绝不改配置、绝不改价**。
    # 判据不满时降级成 blocked/hold 并在 reason 里写清原因，等人拍板。
    gate_hold = {}          # key -> 停手原因
    if audit_qty_collisions is not None:
        try:
            for (base, q), ks in (audit_qty_collisions(cfg, log=log) or {}).items():
                for k in ks:
                    gate_hold[k] = ("🛑 数量冲突：「%s」同时有两条档位都是 %s 装（%s）"
                                    "⇒ 它们会互相抢同一条前台行，本轮**停手改价**，"
                                    "请先定夺哪条作数" % (base, q, "、".join(ks)))
        except Exception as e:                       # 闸门自身出错绝不能拖垮跟价
            log("  ⚠️ 闸二（数量冲突检测）异常，本轮跳过：%r" % (e,))
    if detect_binding_drift is not None and backend_rows:
        try:
            drifts, _n = detect_binding_drift(cfg, backend_rows, log=log)
            for dr in drifts:
                gate_hold.setdefault(dr["key"], "🛑 " + dr["msg"] + " ⇒ 本轮**停手改价**")
        except Exception as e:
            log("  ⚠️ 闸一（绑定漂移检测）异常，本轮跳过：%r" % (e,))
    if gate_hold and log:
        log("  🛑 本轮因闸门停手 %d 个档位（只停手、不改价、不改配置）" % len(gate_hold))
    # ─────────────────────────────────────────────────────────────────

    out = []
    ctx = {}          # key -> 决策（供同族联动取基准）
    for it in items:
        key = it["key"]
        if key in gate_hold:      # 闸一/闸二 命中 ⇒ 只登记一条 blocked，不出目标价
            out.append({"key": key,
                        "title": it.get("中文名") or key,
                        "iggm_title": (it.get("iggm") or {}).get("title"),
                        "iggm_no": str((it.get("iggm") or {}).get("goods_no") or ""),
                        "mode": mode, "装量": it.get("装量", 1),
                        "iggm_old": None, "iggm_new": None,
                        "ours_old": None, "ours_bid": None,
                        "游戏": it.get("游戏"), "计数": units_of(it),
                        "_disc_pct": None,
                        "ours_new": None, "target_usd": None, "target_front_usd": None,
                        "cost_cny": None, "cost_usd": None,
                        "margin_old": None, "margin_new": None,
                        "action": "blocked", "applied": 0,
                        "reason": gate_hold[key],
                        "跟价": it.get("跟价", True),
                        "仅展示": bool(it.get("无IGGM对应"))})
            continue
        disc = disc_of(cfg, it)
        cnt = units_of(it)
        gn = str((it.get("iggm") or {}).get("goods_no") or "")
        cur = iggm_now.get(gn)
        prv = iggm_prev.get(gn) if gn else None
        # 计数：IGGM 参考价按「单个/最小规格」报价时，乘上本规格的计数才是同口径
        # （Divine Orb(1000+50 Free) 计数=1000 → 目标价 = IGGM单个真价 × 1000）
        ig_new = cur.get("price_usd") * cnt if cur else None
        ig_old = prv.get("price_usd") * cnt if prv else None
        our = ours_now.get(key) or {}
        # ★ 2026-09-27：折扣以**前端实测值**为准（前端接口每条商品都带 discount，
        #   core_front 抓下来存在 our_price.front_disc）。用户会随时改折扣，配置里那个
        #   数是「我们以为的折扣」，前端那个数才是**真正乘在标价上**的折扣 ——
        #   两者不一致时，用前端值才能把「标价 = 前端价 ÷ 折扣」还原对。
        #   前端没读到（老库/抓取失败）才回退 config（见 disc_of 三级回退）。
        #   注意：`ours_now` 里混着「本轮刚抓的行」（字段名 `_前台折扣`）和
        #   「库内兜底的行」（字段名 `front_disc`），统一走 front_disc_of 取。
        _fd = front_disc_of(our)
        try:
            if _fd is not None and float(_fd) > 0:
                _fdv = float(_fd) / 100.0
                if abs(_fdv - disc) > 1e-9:
                    log("  ↺ %s 折扣以**前端实测 %.1f%%** 为准（config 写的是 %.1f%%）"
                        % (key, _fdv * 100.0, disc * 100.0))
                disc = _fdv
        except (TypeError, ValueError):
            pass
        ours_old = our.get("price_usd")                       # 前端展示价（客户实付）
        # ── 隐藏档位同族单位价推算 2026-10-05 ──
        # ── 装量一致性校验 + 隐藏档位推算 ──────────────────────────────
        #   前台隐藏的档位（例：×10 已隐藏）匹配到的是别的档位的行，
        #   直接拿它的价当本档用 → 目标价算出来是 −99%，被闸三拦死，
        #   隐藏档的价格就永久冻结了。这里识别出来并按同族单位价重算。
        _pz_this = 1.0
        try:
            _pz_this = float(it.get("装量", 1) or 1)
        except (TypeError, ValueError):
            _pz_this = 1.0
        _ps_seen = our.get("pack_size")
        _ps_bad = _ps_seen in (None, "")
        if not _ps_bad:
            try:
                _ps_bad = abs(float(_ps_seen) - _pz_this) > 1e-9
            except (TypeError, ValueError):
                _ps_bad = True
        _est_used = 0
        _est_unit = None
        _est_peers = 0
        _fam = family_of(it, cfg) or key
        _fam_total = _fam_size.get(_fam, 1)
        # ── 隐藏档位推算日志降噪 2026-10-05 ──
        # 同族只有本档 ⇒ 前台没有别的行可比，pack_size 缺失是**正常**的
        # （POE2 / DND / ARC 等单规格商品都是这样），不是隐藏档，不推算也不打印。
        if _ps_bad and _pz_this > 0 and _our_unit and _fam_total > 1:
            _sib = sorted(u for k2, u in _our_unit.items()
                          if k2 != key
                          and u > 0
                          and (family_of(_it_map.get(k2, {}), cfg) or k2) == _fam)
            if _sib:
                if len(_sib) % 2:
                    _mid = _sib[len(_sib) // 2]
                else:
                    _mid = (_sib[len(_sib) // 2 - 1] + _sib[len(_sib) // 2]) / 2.0
                ours_old = _mid * _pz_this
                _est_used = 1
                _est_unit = _mid
                _est_peers = len(_sib)
                if log:
                    log("  ⓘ [%s] 前台未上架/装量不符（实测 %s vs 本行 %g）⇒ "
                        "按同族单位价 $%.6f × %g 推算现价 $%.4f（同族基准 %d 档）"
                        % (key,
                           _ps_seen if _ps_seen not in (None, "") else "无",
                           _pz_this, _mid, _pz_this, ours_old, len(_sib)))
            elif log:
                log("  ⚠ [%s] 同族共 %d 档，但**全部**缺装量实测值 ⇒ 本轮无法推算，"
                    "保持不动价；请检查该族前台是否已上架或 pack_size 抓取是否失败"
                    % (key, _fam_total))
        ours_bid = (ours_old / disc) if ours_old else None    # 我方标价（后台「$每个价格」）
        cost_cny, cost_usd = cost_usd_of(it, qd_map.get(key), rate)
        # ★ 成本可信度（2026-09-27 新增）：千岛对标区服本轮缺失时，app.build_qd_map
        #   会降级到「参考区服」，其中第一项是「国际服 / 赛季 / 专家」= 硬核服，
        #   报价是普通服的数倍~十几倍。降级成本**照旧展示**（毛利率仍算出给人看），
        #   但必须**冻结跟价**：既不参与成本地板（地板本身已不可信，会像 2026-09-27
        #   那样把成本算成 10 倍、把所有变价全判 blocked），也不产生写操作。
        _q = qd_map.get(key) or {}
        cost_trust = not bool(_q.get("_降级区服"))

        d = {"key": key, "title": it.get("中文名") or (cur or {}).get("title") or key,
             "iggm_title": (cur or {}).get("title") or (it.get("iggm") or {}).get("title"),
             "iggm_no": gn, "mode": mode, "装量": it.get("装量", 1),
             "iggm_old": ig_old, "iggm_new": ig_new,
             "ours_old": ours_old, "ours_bid": ours_bid,
             # 2026-09-25 多游戏：把本行的游戏与折扣带在决策里，
             # 供同族联动/展示层按行取折扣（不入库，add_decision 只取白名单字段）。
             "游戏": it.get("游戏"), "计数": cnt, "_disc_pct": disc * 100.0,
             # ours_new 只在「真的算出目标标价」时才赋值（见下方 d["ours_new"] = tgt）。
             # 曾经预置成 ours_old（前端价），与 ours_bid（标价）差一个折扣，
             # 会让任何不按 action 过滤的消费方把「没改动」误读成「降了一个折扣」。
             "ours_new": None,
             "target_usd": None, "target_front_usd": None,
             "cost_cny": cost_cny, "cost_usd": cost_usd,
             "margin_old": margin(ours_old, cost_usd), "margin_new": None,
             "_成本可信": cost_trust, "_成本区服": _q.get("_区服"),
             "qd_name": _q.get("name") if _q else None,
             "action": "hold", "applied": 0, "reason": "",
             # # ── 隐藏档位同族单位价推算 2026-10-05 ── 隐藏档位推算标记（正常档位恒为 0/None）
             "_ours_est": _est_used, "_ours_est_unit": _est_unit,
             "_ours_est_peers": _est_peers, "_ours_est_seen_pack": _ps_seen,
             "跟价": it.get("跟价", True),      # 勾选表开关：False = 只展示、不跟价
             "仅展示": bool(it.get("无IGGM对应"))}
        ctx[key] = d

        # 勾选表：没勾的商品只展示价格与毛利，不出目标价、不参与同族联动
        if d["跟价"] is False:
            d["action"] = "hold"
            d["reason"] = "未勾选跟价：只展示价格与毛利，不出目标价"
            out.append(d)
            continue

        if it.get("无IGGM对应") or not gn:
            d["action"] = "hold"
            mb = member_base(cfg, key)
            d["reason"] = ("IGGM 无此规格，仅记录我方价格与毛利"
                           + ("；该规格由「同族联动」跟随基准 %s 等比调整" % mb if mb else ""))
            if ours_old is None:
                # 我方前端也没读到 → 联动同样算不出来。这种行以前只会安静地挂着，
                # 必须显式提出来，让用户决定是「前端补上架」还是「下架该规格」。
                d["reason"] += ("；⚠ 我方前端也没读到该规格，同族联动无法生效，"
                                "请确认是「前端补上架」还是「下架该规格」")
                d["need_input"] = True
            out.append(d)
            continue
        if ig_new is None:
            # 配置里挂了竞品商品号、但本轮抓取里没有 → 多半是竞品已下架该规格。
            # 这种行以前会一直安静地"不动"，看起来和正常没差别，必须显式告警。
            d["action"] = "hold"
            d["iggm_missing"] = True
            d["reason"] = ("⚠ IGGM 本轮无此规格（该规格可能已被竞品下架），映射需更新"
                           + ("；我方前端也未读到该规格" if ours_old is None else ""))
            mb = member_base(cfg, key)
            if mb:
                d["reason"] += "；本规格由「同族联动」跟随基准 %s" % mb
            out.append(d)
            continue
        if ig_old is None or ig_old == 0:
            d["action"] = "hold"
            d["iggm_new_spec"] = True
            d["reason"] = ("IGGM 本轮新增 / 首次抓到该规格（上一轮没有对标价），"
                           "先建立基线，下一轮起才参与跟价")
            out.append(d)
            continue

        chg = (ig_new - ig_old) / ig_old * 100.0
        direction = "up" if ig_new > ig_old else ("down" if ig_new < ig_old else "flat")
        moved = (direction != "flat" and abs(chg) >= max(dead, min_chg))

        # ── 触发判定 ─────────────────────────────────────────────
        # ① 常态：IGGM 本轮真变价 → 评估。
        # ② 后台折扣变了（前端实测折扣 / config 折扣）→ 对这些游戏强制重算，
        #    否则标价会一直停在「按旧折扣算出来」的数上（前端凭空贵 1/旧折扣 − 1）。
        # ③ 偏差纠偏：我方前端价与目标前端价差得太多（> `触发.偏差纠偏百分比`）→ 拉回。
        #    这条是为「口径/参数变了但 IGGM 没动」准备的（折扣、让价、成本口径都属于这类），
        #    否则那些行会**永远**挂在那儿没人管。
        #    （注：这不是 09-24 删掉的那个「偏离纠正」——那条拿标价与目标的偏差当触发，
        #      任何抓取噪声都会点火；这条比的是**前端价**、阈值也放大到 5%，
        #      只有真的差出半个让价才动。）
        # 先算目标价（②③ 都要用它）
        tgt = compute_target(it, sc, ig_new, ours_old=ours_bid, iggm_old=ig_old,
                             front_disc=disc)
        # ── 批量阶梯优惠：高档位单件更便宜（2026-10-01 用户规则）────
        #   先让价（compute_target 内已做）→ 再乘档位系数，逐档累乘。
        _tk = _tier.get(key)
        if _tk and tgt is not None and _tk < 1.0:
            _tgt_pre = tgt
            tgt = tgt * _tk
            if log:
                log("  ⇩ [%s] 批量优惠 ×%.4f：$%.6f → $%.6f"
                    % (key, _tk, _tgt_pre, tgt))
        # 目标**前端价**（验收不变式：我方前端价 ≤ 该值 = IGGM真价 ×(1−让价)）
        _lim = (ig_new * allowance(cfg)) if ig_new is not None else None
        _tick_short = False        # True = 连一个 tick 都放不下（见 fit_under_tick）
        if tgt is not None:
            if step >= 0.01:
                tgt = _round_to(tgt, step)
                tgt = round(tgt, 2)
            else:
                _fitted = fit_under_tick(tgt, step, disc, _lim, dec=dec)
                if _fitted is None:
                    # 目标价小于最小 tick ⇒ 取整只能向上、会破坏 ≤ 不变式
                    # ⇒ 本轮**不动手**（宁可保持原价，也不能把价抬到 IGGM 之上）
                    _tick_short = True
                    tgt = _round_to(tgt, step) if step > 0 else round(tgt, dec)
                    tgt = round(tgt, dec)
                else:
                    tgt = _fitted
        _dev = None
        if tgt and ours_bid:
            _dev = (ours_bid - tgt) / tgt * 100.0
        _dev_raw = bool(_dev is not None and dev_thr > 0 and abs(_dev) > dev_thr)
        # ★ 条件A（2026-09-29）：偏差纠偏**只降不升**。
        #   由来：用户策略是「IGGM 改价了我们再改」，但千岛进货价便宜时他会**先于
        #   IGGM** 手动把价改低抢单。原闸只看「我方价 vs 目标价」的差值、不看这个价
        #   是谁改的 ⇒ 把自主低价当成偏差「拉回」到 IGGM×0.95，并且每轮重复出单
        #   （实测 ARC_2772640663 在 10:37:44 与 10:56:05 各出一张同内容的单）。
        #   限定成「只有我方比目标**贵**才纠偏」后：
        #     · 09-27 要修的「折扣写错 ⇒ 我方偏贵 11.1%」照旧被拉低 ✔
        #     · 我方自主卖便宜 ⇒ 系统**永不**在 IGGM 未动时上调 ✘（误判消除）
        _dev_skip_low = bool(DEV_DOWN_ONLY and _dev_raw and _dev is not None and _dev <= 0)
        # ★ 条件B（2026-09-29）：人工调价保护 —— 我方现价是人工改的、且 IGGM 真价自
        #   那次改动以来没变 ⇒ 按「IGGM 改了我们再改」不跟，不出目标价。
        #   保护**只在偏差纠偏通道生效**：IGGM 真变价（moved）与折扣变更（_dch）照常走，
        #   免得退回 09-27 那个「折扣改了标价不重算 ⇒ 前端凭空贵 1/旧折扣−1」的坑。
        _mo = (manual_override or {}).get(key) or {}
        _mo_on = False
        if _mo:
            try:
                _ref = float(_mo.get("iggm_new")) if _mo.get("iggm_new") is not None else None
            except (TypeError, ValueError):
                _ref = None
            if _ref is None:
                # 登记时就没抓到 IGGM 价：只有**现在仍然抓不到**才继续保护；
                # 一旦竞品规格出现了，说明基线可用了 ⇒ 保护作废、恢复正常跟随。
                _mo_on = (ig_new is None)
            elif ig_new is None:
                # 竞品本轮缺该规格：保守起见继续保护（宁可不动，也别误改）
                _mo_on = True
            else:
                _mo_on = abs(float(ig_new) - _ref) <= max(1e-9, abs(_ref) * 1e-6)
        _mo_hit = bool(_dev_raw and _mo_on)
        _dev_hit = bool(_dev_raw and not _mo_hit and not _dev_skip_low)
        _dch = bool(_dch_set) and ((it.get("游戏") or default_game(cfg)) in _dch_set)
        if not moved and not _dch and not _dev_hit:
            d["action"] = "hold"
            _tgt_front = round(float(tgt) * disc, dec) if tgt is not None else None
            if _mo_hit:
                d["_人工调价保护"] = True
                d["reason"] = (
                    "⏸ 人工调价保护：我方自主定价 $%s（目标 $%s，偏差 %+.1f%%），"
                    "IGGM 真价 $%s 自那次改价以来未变 ⇒ 按「IGGM 改价了我们再改」不跟。"
                    "竞品一变价，本保护自动解除。"
                    % (_usd(ours_old), _usd(_tgt_front), _dev or 0.0, _usd(ig_new)))
            elif _dev_skip_low:
                d["_偏差只降不升"] = True
                d["reason"] = (
                    "我方定价低于目标（前端 $%s vs 目标 $%s，低 %.1f%%）：按 09-29 起"
                    "「偏差纠偏只降不升」，IGGM 未变价时不主动上调（自主低价抢单不受干预）。"
                    % (_usd(ours_old), _usd(_tgt_front), abs(_dev or 0.0)))
            else:
                # 两个阈值已按要求删掉（=0）：持平就是持平，别再报「未达触发线(0.00%)」这种废话
                d["reason"] = ("IGGM 价格与上轮持平，无需调整" if direction == "flat"
                               else "IGGM 变动 %.3f%% 未达触发线(%.2f%%)，视为抖动"
                                    % (chg, max(dead, min_chg)))
            out.append(d)
            continue
        if moved:
            d["trigger"] = "iggm"
        elif _dch:
            d["trigger"] = "折扣变更"
        else:
            d["trigger"] = "偏差纠偏"
            d["_dev_pct"] = round(_dev or 0.0, 3)

        # ── 异常闸·同族倒挂检查 ────────────────────────────────────
        # IGGM 自家「×10」与「×100」两个规格的报价互相矛盾时（例：Superior Lair Key
        # *10 = $2.6706、*100 = $2.5300，单位价差 10.56 倍），照小包装的报价跟价
        # 会让我方 10 个装比 100 个装还贵。这种行**不动价**，并把「按族内最低单位价
        # 推算的参考目标」写出来，人工一眼就能判断是竞品挂错价还是我们映射错了装量。
        if an_on and an_inv_on:
            _fu = fam_unit.get(key)
            if _fu and ig_new is not None:
                _fam, _u_this, _ig_this, _pz_this = _fu
                _u_min = fam_min_unit.get(_fam)
                if _u_min and _u_this > _u_min * (1.0 + an_inv_tol):
                    _lim_f = ig_new * allowance(cfg)              # 现口径的目标前端价
                    _ref_front = _u_min * _pz_this * allowance(cfg)  # 按族内最低单位价推
                    _ref_bid = _ref_front / disc if disc else None
                    d["action"] = "blocked"
                    d["_anom"] = "同族倒挂"
                    d["_anom_ratio"] = round(_u_this / _u_min, 4)
                    if _ref_bid:
                        d["_ref_bid"] = round(_ref_bid, dec)
                    d["reason"] = (
                        "⚠ 异常闸拦下（同族倒挂）：IGGM「%s」报价 $%.4f ÷ 装量 %g "
                        "= 单位价 $%.6f，而同族「%s」里最低单位价只有 $%.6f，"
                        "**高出 %.2f 倍**（容忍 %.0f%%）—— 竞品小包装报价与其大包装自相矛盾。"
                        "照它跟价会让我方 %g 个装比大包装还贵 ⇒ 本轮不动价。"
                        "若按族内最低单位价推算，参考目标前端价 $%.4f（标价 $%s）；"
                        "请人工确认是「IGGM 挂错价」还是「映射装量错了」。"
                        % (d.get("iggm_title") or "", ig_new, _pz_this, _u_this, _fam, _u_min,
                           _u_this / _u_min, an_inv_tol * 100.0, _pz_this, _ref_front,
                           "%.*f" % (dec, _ref_bid) if _ref_bid else "-"))
                    out.append(d)
                    continue

        # 方向开关：只在「IGGM 真变价」时生效。折扣变更 / 偏差纠偏不改竞品价，没有方向可关。
        _up = (direction == "up")
        dir_allow = bool((g.get("方向") or {}).get("对方涨价" if _up else "对方降价", True))
        if moved and not dir_allow:
            d["action"] = "hold"
            d["reason"] = "配置里关闭了「对方%s」跟随" % ("涨价" if _up else "降价")
            out.append(d)
            continue

        if tgt is None:
            d["action"], d["reason"] = "hold", "无法计算目标价（缺少我方现价或基准价）"
            out.append(d)
            continue
        d["target_usd"] = tgt                                  # 标价口径（要写进后台的数）
        d["target_front_usd"] = round(tgt * disc, dec)         # 换算成客户看到的前端价

        # 提前记下方向性建议：后面「成本地板」等分支
        # 都会提前 continue，若等到最后才设 suggest，被拦下的行「建议」列就是空的，
        # 看板上看不出它本该往哪个方向走。
        if ours_bid is not None:
            d["suggest"] = "follow_up" if tgt > ours_bid else "follow_down"

        # ★ 成本不可信 → 冻结跟价（2026-09-27 新增，替代原来的「静默降级照用」）
        if not cost_trust:
            d["action"] = "hold"
            d["reason"] = ("⚠ 千岛「%s」本轮无数据，成本取自参考区服「%s」"
                           "（专家＝硬核服，报价常为普通服的数倍），成本不可信 → 本轮不动价；"
                           "目标标价本应为 $%.4f"
                           % (qd_base_spec or "对标区服", _q.get("_区服") or "?", tgt))
            out.append(d)
            continue

        # 成本地板
        floor = None
        if cost_usd is not None and floor_m > -9:
            floor = _round_to(cost_usd * (1.0 + floor_m), step) if step else cost_usd * (1.0 + floor_m)
            # ── 成本地板竞品封顶 2026-10-05 ──
            # 地板高于竞品对标价 = 竞对在贴钱抢市场。用户 2026-10-05 决定：
            # 按 IGGM 对标价强制对齐（继续跟到竞品价），而不是停手不跟。
            # 保住销量，代价是该档负毛利 —— reason 里写清楚，不静默吞掉。
            # 口径：ig_new 是折后前端价，地板是标价 → 先除 disc 换回标价。
            _cap_on = bool(sc.get("地板按竞品封顶", True))
            _cap_ref = None
            if _cap_on and ig_new is not None:
                try:
                    _cap_ref = (ig_new / disc) if disc else ig_new
                    _cap_ref = _round_to(_cap_ref, step) if step else round(_cap_ref, dec)
                except Exception:
                    _cap_ref = None
            if _cap_ref is not None and _cap_ref > 0 and floor > _cap_ref:
                d["floor_capped"] = True
                d["floor_usd_raw"] = floor
                d["cap_ref_usd"] = _cap_ref
                floor = _cap_ref
                d["floor_cap_note"] = ("地板 $%.4f 高于竞品对标价 $%.4f，已按竞品对齐跟价"
                                       "（该档负毛利）" % (d["floor_usd_raw"], _cap_ref))
            if tgt < floor:
                d["action"] = "blocked"
                d["reason"] = ("目标价 $%.4f 低于成本地板 $%.4f（成本 $%.4f × (1+%.0f%%)），"
                               "不跟价" % (tgt, floor, cost_usd, floor_m * 100))
                if d.get("floor_cap_note"):
                    d["reason"] += "；" + d["floor_cap_note"]
                d["floor_usd"] = floor
                out.append(d)
                continue
        d["floor_usd"] = floor
        if d.get("floor_cap_note"):
            d["reason"] = (d.get("reason") or "") or ""
            d["_cap_warn"] = d["floor_cap_note"]

        if ours_bid is None:
            d["action"], d["reason"] = "hold", "我方标价未知（需先读到该商品的前端价才能换算）"
            out.append(d)
            continue

        if _tick_short:
            # 目标前端价小于最小 tick（例：POE2 崇高石目标 $0.0000947 / tick $0.0001）。
            # 这种行只能「保持现价」—— 现价本来就 ≤ IGGM，抬到 tick 反而会违反验收标准。
            d["action"] = "hold"
            d["reason"] = ("目标前端价 $%.6f 小于最小取整档 $%s，无法再降价（抬到一档就"
                           "会高于 IGGM），保持现价" % ((_lim or 0.0), step))
            out.append(d)
            continue

        delta = tgt - ours_bid
        # ★ 最小变动闸（2026-09-27）：|Δ| 太小 = 显示噪声，不重写标价。
        #   典型来源：「标价 = 前端价 ÷ 折扣」在 dec=4 精度下的 ±1 tick 余数。
        #   实测 677 条报「折扣变更」的行里 634 条 |Δ| ≤ $0.0001，全部属于这一类。
        #   加这道闸后这些行变 hold ⇒ `disc_settle` 的 pending 闩能正常收尾，
        #   不再每小时重写整局、不再每轮派 8 小时的写单。
        _rel_pct = (abs(delta) / ours_bid * 100.0) if ours_bid else 9e9
        _noise_abs = (mv_abs > 0 and abs(delta) < mv_abs)
        _noise_rel = (mv_rel > 0 and _rel_pct < mv_rel)
        if abs(delta) < 1e-9 or _noise_abs or _noise_rel:
            d["action"] = "hold"
            if abs(delta) < 1e-9:
                d["reason"] = "目标标价 $%.4f 与现标价完全相同，无需调整" % tgt
            else:
                d["reason"] = ("目标标价 $%.4f 与现标价 $%.4f 相差 $%.6f（%.4f%%），"
                               "低于最小变动闸（≥$%s 或 ≥%s%%）⇒ 属取整显示噪声，不重写"
                               % (tgt, ours_bid, delta, _rel_pct, mv_abs, mv_rel))
            out.append(d)
            continue

        # 记下「若不受开关限制，本该往哪个方向走」。提前到这里设，是为了让之后被
        # 成本地板等闸门拦下的行也能显示「本可跟涨 / 本可跟降」，信息不丢。
        d["suggest"] = "follow_up" if delta > 0 else "follow_down"

        # ★ 异常闸·单次最大涨跌幅（默认 0 = 关闭，保持 2026-09-24 起「不拦截夸张涨幅」的口径）
        #   这是**数据错误探针**，不是当年那个把正常波动也拦掉的「单次最大涨跌幅上限」
        #   （那个阈值只有 20%~50%，正常调价都会中招，已于 09-24 删除）。
        #   只有当某行一次要动到 config 里设定的倍数（默认关闭，建议 ≥300）才拦，
        #   用作兜底：万一出现新的「口径 / 装量错配」，先停下不动价、留痕等人看。
        #   （同族倒挂检查已覆盖巢穴钥匙那类小包装挂错价；这条是更广的兜底。）
        _chg_pct = (abs(delta) / ours_bid * 100.0) if ours_bid else 0.0
        if an_on and an_max_chg > 0 and _chg_pct > an_max_chg:
            d["action"] = "blocked"
            d["_anom"] = "涨跌幅超异常闸"
            d["_chg_pct"] = round(_chg_pct, 2)
            d["reason"] = ("⚠ 异常闸拦下：单次需变动 %.1f%%（$%.4f → $%.4f），"
                           "超过异常闸 %.0f%% ⇒ 疑似数据 / 装量错配，本轮不动价，请人工确认"
                           % (_chg_pct, ours_bid, tgt, an_max_chg))
            out.append(d)
            continue

        # ── 按行 pending 闩（2026-09-29）────────────────────────────────
        # 走到这里 = 三闸有其一成立、且过了最小变动闸与异常闸 ⇒ 本轮**本来要出单**。
        # 但若**这一行**近 N 小时内已经出过单、单要求的目标标价与现在算出来的完全一致，
        # 而我方现价还没变成那个价 ⇒ 这不是「新的变化」，只是**前台生效慢**。
        # 实测：ARC_2772640663 的单 04:58:53 执行成功，前台 10:56 才刷出来（差 5h57m），
        # 中间 5 轮采集读到的都是旧价 0.45 ⇒ 引擎在 10:37:44、10:56:05 各重出一张
        # **内容完全相同**的单。`_auto_dispatch` 那道「已有 pending/dispatched 单就跳过」
        # 只挡得住还没跑完的单，挡不住这种「单已 done、前台没跟上」的情形。
        #
        # 判据三条同时成立才拦（少一条都不拦，宁可多出一次单也不漏跟一次价）：
        #   ① 闩里那单要求的目标标价 == 本轮目标标价（⇒ IGGM 没再变价 / 折扣没再变，
        #      所以这不是一次新变化；**目标一变这里立刻不成立，闩自动让路**）；
        #   ② 我方现价 ≠ 那个标价（⇒ 前台还没生效）；
        #   ③ 窗口内（由 app 侧按 `保留小时` 过滤，过期单根本不会进 line_pending）。
        _lp = (line_pending or {}).get(key) or {}
        if _lp and ours_bid and tgt:
            try:
                _lp_bid = float(_lp.get("bid_new")) if _lp.get("bid_new") is not None else None
            except (TypeError, ValueError):
                _lp_bid = None
            if _lp_bid is not None:
                _lp_same = abs(_lp_bid - tgt) <= max(1e-6, abs(tgt) * 1e-4)
                _lp_gap = abs(ours_bid - _lp_bid) > max(1e-9, abs(_lp_bid) * 1e-3)
                if _lp_same and _lp_gap:
                    d["action"] = "hold"
                    d["_待前台生效"] = True
                    d["_line_pending"] = {"job": _lp.get("job"), "ts": _lp.get("ts"),
                                          "status": _lp.get("status"),
                                          "bid_new": _lp_bid,
                                          "front_new": _lp.get("front_new"),
                                          "age_h": _lp.get("age_h")}
                    d["reason"] = (
                        "⏸ 已出单待前台生效：单 %s（%s 派发，%.1f 小时前）已要求标价 $%.4f"
                        "（前端 $%s），我方现价 $%.4f 仍是旧值 —— 前台刷新要 5~15 分钟、"
                        "实测最长约 6 小时 ⇒ 本轮**不重复出单**。前台一到位本闩自动解除；"
                        "超过 %g 小时或竞品再变价也会自动放行。"
                        % (_lp.get("job") or "?", _lp.get("ts") or "?",
                           float(_lp.get("age_h") or 0.0), _lp_bid,
                           _usd(_lp.get("front_new")), ours_bid, _lp_keep_h))
                    out.append(d)
                    continue

        # ── 闸三 2026-10-05 · 单轮幅度上限（默认 ±50%，引擎.单轮幅度上限 设 0 = 关闭）
        # 2026-10-02 腐化根藤实证：前台真实暴跌 90%，引擎拿跌后现价当基准算出 9 倍
        # 目标价 ⇒ ×10 行被写成 $25.87。这里把「一眼就不对」的幅度直接判 blocked。
        if clamp_round_step is not None:
            tgt2, _clamped, _lim = clamp_round_step(cfg, ours_bid, tgt)
            if _clamped:
                d["action"] = "blocked"
                d["suggest"] = "follow_up" if delta > 0 else "follow_down"
                d["target_usd"] = tgt
                d["target_front_usd"] = round(tgt * disc, 4)
                d["reason"] = (
                    "🛑 单轮幅度超限：目标标价 $%.4f 相对我方现价 $%.4f 变动 %+.0f%%，"
                    "超过上限 ±%.0f%%（竞品真正常见的波动是 ±5~30%%）⇒ 本轮**停手**，"
                    "不跟随。限幅参考价 $%.4f，请确认后手工处理，或调 `引擎.单轮幅度上限`"
                    % (tgt, ours_bid, ((tgt - ours_bid) / ours_bid * 100.0) if ours_bid else 0.0,
                       _lim * 100.0, tgt2))
                out.append(d)
                continue
        # ──────────────────────────────────────────────────────────────
        d["ours_new"] = tgt
        # 目标价是标价口径，客户实付 = 标价 × 折扣 → 毛利必须按前端价算
        d["margin_new"] = margin(tgt * disc, cost_usd)
        d["action"] = "follow_up" if delta > 0 else "follow_down"
        # 无论开关状态都记下「该不该跟」：OFF 时 action 会降级成 hold（不动手），
        # 但看板要能区分「建议跟涨」和「真的不用动」，所以单独留一个 suggest。
        d["suggest"] = d["action"]
        if not moved:
            # 折扣变更 / 偏差纠偏触发：IGGM 没动，讲清「为什么这轮要改价」
            if _dch:
                _why = ("后台折扣变更 ⇒ 按**当前折扣 %.1f%%** 重算标价："
                        "标价 $%.4f → $%.4f（前端价 = 标价 × %.2f = $%.4f），预期毛利 %.1f%%"
                        % (disc * 100.0, ours_bid, tgt, disc, tgt * disc,
                           (d["margin_new"] or 0) * 100))
            else:
                _why = ("偏差纠偏：我方前端价 $%.4f（标价 $%.4f × 折扣 %.0f%%）"
                        "比目标前端价 $%.4f 高 %.2f%%（阈值 %.1f%%）⇒ 拉回："
                        "标价 $%.4f → $%.4f，预期毛利 %.1f%%"
                        % (ours_bid * disc, ours_bid, disc * 100.0, tgt * disc,
                           (_dev or 0.0), dev_thr, ours_bid, tgt,
                           (d["margin_new"] or 0) * 100))
        else:
            _why = ("IGGM %s %.2f%%($%.4f→$%.4f)，我方标价 $%.4f→$%.4f，"
                    "预期毛利 %.1f%%"
                    % ("涨价" if direction == "up" else "降价", chg, ig_old, ig_new,
                       ours_bid, tgt, (d["margin_new"] or 0) * 100))
        if mode == "OFF":
            d["action"] = "hold"
            d["reason"] = "【开关=关闭】" + _why + "（不执行）"
        else:
            d["reason"] = _why
        out.append(d)

    # ---------- 同族联动：IGGM 没有的规格，按基准规格的变化比例等比调整 ----------
    fam = cfg.get("同族联动") or {}
    if fam.get("启用", True) and fam.get("组"):
        by_key = {d["key"]: d for d in out}
        for grp in fam["组"]:
            base = by_key.get(grp.get("基准"))
            if not base:
                continue
            if base.get("跟价") is False:
                # 基准没勾选跟价 → 整组不联动，成员保持原状并说明原因
                for _mk in grp.get("成员", []):
                    _m = by_key.get(_mk)
                    if _m and _m.get("action") == "hold":
                        _m["reason"] = ("基准规格「%s」未勾选跟价，本规格暂不联动"
                                        % grp.get("基准"))
                continue
            b_old, b_new = base.get("ours_bid"), base.get("target_usd")
            ratio = (b_new / b_old) if (b_old and b_new and b_old > 0) else None

            def _touch(msg, action, sug=None, force=False):
                """给成员行落一个明确状态。

                原来基准一旦被安全闸拦下，这里就整组 continue，成员既不算跟、也不算拦，
                直接落进「其余不动」，而且原因栏是空的 —— 看板上完全看不出为什么。

                force=True：连成员自己算出来的 follow_* 也一起改成 action
                （用于「基准已出单、前台还没生效」—— 这时成员单飞会把同一批货重复改一遍）。
                blocked / 其它状态一律不碰。
                """
                for _mk in grp.get("成员", []):
                    _m = by_key.get(_mk)
                    if not _m:
                        continue
                    _act = _m.get("action")
                    if _act not in ("hold", "follow_up", "follow_down"):
                        continue
                    if not force and _act != "hold":
                        continue
                    # 成员自己已被「按行 pending 闩」拦下（已出单、前台没生效）→
                    # 保留它自己的理由，别用联动的笼统说法盖掉更具体的信息。
                    if _m.get("_待前台生效"):
                        continue
                    # 成员自己已经有更具体的问题（竞品下架 / 新增规格 / 我方未上架）时，
                    # 保留它当主因，只把联动状态追加在后面 —— 不能把更重要的信息盖掉。
                    if _m.get("iggm_missing") or _m.get("iggm_new_spec") or _m.get("need_input"):
                        _m["reason"] = ((_m.get("reason") or "")
                                        + "；同族联动：基准「%s」本轮%s"
                                        % (grp.get("基准"),
                                           "已被安全闸拦下" if action == "blocked"
                                           else "没有可用目标价"))
                        continue
                    _m["action"] = action
                    _m["联动自"] = grp.get("基准")
                    _m["reason"] = msg
                    if sug:
                        _m["suggest"] = sug
                    if ratio and _m.get("ours_bid"):
                        _m["target_usd"] = _round_to(_m["ours_bid"] * ratio, step)
                        _m["target_front_usd"] = round(
                            _m["target_usd"] * (float(_m.get("_disc_pct") or 100.0) / 100.0),
                            dec)

            # ★ 基准被「按行 pending 闩」拦下（已出单、前台还没生效）→ 整组同步不动。
            #   不加这一条会漏：成员自己虽然也被闩拦成 hold，但下面 `base.action == "hold"`
            #   且 target_usd 仍在 ⇒ ratio 有值 ⇒ 成员被**改写回 follow_down** 照旧出单
            #   （实测 CRUX / CRUX_X10 就是这么漏出去的）。
            if base.get("_待前台生效"):
                _touch("基准规格「%s」已出单、前台还没刷新，本规格同步不动（不重复出单）"
                       % grp.get("基准"), "hold", force=True)
                continue
            if base["action"] == "blocked":
                # ⭐ 基准被拦 → 成员同步标记为「已拦截」，并把基准的原因带过去，
                # 方向性建议也照旧给出（否则被拦的行「建议」列就是空的）。
                _touch("基准规格「%s」已被安全闸拦下，本规格同步不动；基准原因：%s"
                       % (grp.get("基准"), (base.get("reason") or "").strip()),
                       "blocked",
                       ("follow_up" if (ratio and ratio > 1) else
                        ("follow_down" if (ratio and ratio < 1) else None)))
                continue
            if base["action"] not in ("follow_up", "follow_down", "hold"):
                continue
            if not ratio or abs(ratio - 1.0) < 1e-9:
                _touch("基准规格「%s」本轮没有可用目标价，本规格暂不联动"
                       % grp.get("基准"), "hold")
                continue
            for mk in grp.get("成员", []):
                m = by_key.get(mk)
                if not m:
                    continue
                if not m.get("仅展示") and m.get("action") != "hold":
                    continue
                if not m.get("ours_bid"):
                    continue
                # 成员按基准的相对变化比例等比缩放，保持各规格之间的价差结构不变
                tgt = _round_to(m["ours_bid"] * ratio, step)
                tgt = round(tgt, 2 if step >= 0.01 else dec)
                m["target_usd"] = tgt
                m["target_front_usd"] = round(
                    tgt * (float(m.get("_disc_pct") or 100.0) / 100.0), dec)
                m["联动自"] = grp.get("基准")
                m["联动比例"] = ratio
                m["suggest"] = "follow_up" if tgt > (m.get("ours_bid") or 0) else "follow_down"
                # 全套闸门照旧（成本不可信的行不过地板 —— 它的成本本来就是降级的）
                if m.get("cost_usd") is not None and floor_m > -9 \
                        and m.get("_成本可信", True):
                    fl = _round_to(m["cost_usd"] * (1.0 + floor_m), step) if step \
                        else m["cost_usd"] * (1.0 + floor_m)
                    m["floor_usd"] = fl
                    if tgt < fl:
                        m["action"] = "blocked"
                        m["reason"] = ("同族联动目标价 $%.4f 低于成本地板 $%.4f，不跟"
                                       % (tgt, fl))
                        continue
                # 口径修正：tgt 是「标价」，现价也必须取标价。
                # 原来取 ours_old（前端价 = 标价 × 折扣），两者天然差一个折扣，
                # delta 会恒为负 → 被误判成「降价」。
                delta = tgt - m["ours_bid"]
                if abs(delta) < 1e-9:
                    m["action"] = "hold"
                    m["reason"] = ("同族联动（基准 %s）目标标价与现标价相同，无需调整"
                                   % grp.get("基准"))
                    continue
                # ── 闸三 2026-10-05 · 同族联动同样受幅度上限约束 ────────
                if clamp_round_step is not None:
                    tgt2, _clamped, _lim = clamp_round_step(cfg, m.get("ours_bid"), tgt)
                    if _clamped:
                        m["action"] = "blocked"
                        m["suggest"] = "follow_up" if delta > 0 else "follow_down"
                        m["reason"] = (
                            "🛑 单轮幅度超限（同族联动）：目标标价 $%.4f 相对现价 $%.4f "
                            "变动 %+.0f%%，超过上限 ±%.0f%% ⇒ 本轮**停手**，不跟随。"
                            "限幅参考价 $%.4f"
                            % (tgt, m.get("ours_bid"),
                               ((tgt - m["ours_bid"]) / m["ours_bid"] * 100.0)
                               if m.get("ours_bid") else 0.0,
                               _lim * 100.0, tgt2))
                        continue
                # ──────────────────────────────────────────────────────
                m["ours_new"] = tgt
                m["margin_new"] = margin(tgt, m.get("cost_usd"))
                m["suggest"] = "follow_up" if delta > 0 else "follow_down"
                if mode == "OFF":
                    m["action"] = "hold"
                    m["reason"] = ("【开关=关闭】同族联动建议标价 $%.4f→$%.4f"
                                   "（基准 %s 变动 %.1f%%），不执行"
                                   % (m["ours_bid"], tgt, grp.get("基准"), (ratio - 1) * 100))
                else:
                    m["action"] = "follow_up" if delta > 0 else "follow_down"
                    m["reason"] = ("同族联动：基准 %s 变动 %.1f%%，本规格标价 $%.4f→$%.4f，"
                                   "预期毛利 %.1f%%"
                                   % (grp.get("基准"), (ratio - 1) * 100, m["ours_bid"], tgt,
                                      (m["margin_new"] or 0) * 100))
    return out


def member_base(cfg, key):
    """该 key 是不是某个「同族联动」组的成员；是则返回基准 key"""
    for grp in ((cfg.get("同族联动") or {}).get("组") or []):
        if key in (grp.get("成员") or []):
            return grp.get("基准")
    return None


def summarize(decisions):
    """统计：可执行/被拦/仅建议"""
    s = {"total": len(decisions), "follow_up": 0, "follow_down": 0,
         "blocked": 0, "hold": 0, "actionable": 0}
    for d in decisions:
        a = d.get("action", "hold")
        s[a] = s.get(a, 0) + 1
    s["actionable"] = s["follow_up"] + s["follow_down"]
    return s


def formula_analysis(pairs, rate):
    """分析「采购成本 ↔ 前端价格」的换算关系。

    pairs: [(name, cost_cny, front_usd), ...]
    用户给的已知条件：汇率固定 6.65。要判断的是前端价到底怎么从采购成本算出来。
    这里做三件事：
      1. 算每条的隐含倍率 front_usd / (cost_cny/rate)
      2. 若倍率高度一致 → 结论「前端价 = 采购成本 / 6.65 × 倍率」
      3. 若不一致 → 输出散点，让用户/人工看是不是分段、加法项或另有参数
    """
    rows = []
    for name, cny, usd in pairs:
        if not cny or not usd or cny <= 0:
            continue
        base = cny / float(rate)
        rows.append({"name": name, "cost_cny": cny, "cost_usd": base,
                     "front_usd": usd, "ratio": usd / base if base else None,
                     "addon": usd - base})
    if not rows:
        return {"rows": [], "conclusion": "无有效样本"}
    ratios = [r["ratio"] for r in rows if r["ratio"]]
    addons = [r["addon"] for r in rows]
    def _cv(xs):
        if len(xs) < 2:
            return 0.0
        m = sum(xs) / len(xs)
        if not m:
            return 9.9
        var = sum((x - m) ** 2 for x in xs) / len(xs)
        return math.sqrt(var) / abs(m)
    cv_r, cv_a = _cv(ratios), _cv(addons)
    if ratios and cv_r < 0.02:
        concl = ("乘法模式：前端价 = 采购成本 ÷ %.2f × %.4f（倍率波动 %.2f%%，高度一致）"
                 % (rate, sum(ratios) / len(ratios), cv_r * 100))
        kind = "multiply"
    elif cv_a < 0.02 * max(1.0, abs(sum(addons) / len(addons))):
        concl = ("加法模式：前端价 = 采购成本 ÷ %.2f + %.4f（加价额波动 %.2f%%，高度一致）"
                 % (rate, sum(addons) / len(addons), cv_a * 100))
        kind = "add"
    else:
        concl = ("既非纯乘法也非纯加法（倍率波动 %.1f%%，加价额波动 %.1f%%）——"
                 "可能分段计价或还有别的参数，需要更多样本或直接看后台代码"
                 % (cv_r * 100, cv_a * 100))
        kind = "unknown"
    return {"rows": rows, "kind": kind, "conclusion": concl,
            "ratio_mean": sum(ratios) / len(ratios) if ratios else None,
            "addon_mean": sum(addons) / len(addons) if addons else None}
