# -*- coding: utf-8 -*-
"""多源基准价计算（AION2 专用口径）—— G2G / ELD / IGGM 三方比价 + 同大区均价兜底。

为什么单独一个模块
------------------
2026-10-01 用户定案的口径（AION2 金币专线）：

    基准价 = min(G2G 最低价, ELD 最低价)
    若 IGGM 价 < 基准价 → 基准价 = IGGM 价      （IGGM 只做参考，低了才跟）
    我方目标前端每 M 价 = 基准价 × (1 − 让价百分比)   （默认低 5%）
    某区三方都没数据 → 用**同大区已有数据的均价**兜底

把这段逻辑独立出来（而不是塞进 core_gold.build_plan），原因：
  ① core_gold 是**暗黑4 也在用**的共用模块，AION2 的三源口径只对 AION2 生效；
  ② 三源抓取要各自落盘留证（G2G/ELD/IGGM 快照），独立模块好挂日志与缓存；
  ③ 出问题时能单独禁用（config.金币.多源基准.启用=false）退回纯 IGGM，不影响 D4。

## 单位口径（三方必须统一到「买 1 Mil Kinah 的美元价」= $/M）

| 源 | 原始 | 换算 |
|---|---|---|
| G2G | `converted_unit_price`（`unit_name="Mil Kinah"`） | 已是 $/M，直接用 |
| ELD | `pricePerUnit.amount`（页面写 `$X / K`） | × 1000 = $/M |
| IGGM | `data.one_goods.price`（每单位价） | 已是 $/M |

## 与 core_gold 的关系

`core_gold.build_plan` 抓到 IGGM 价后，调本模块的 `resolve_base()` 拿「基准价」；
若本模块启用且拿到值，就用它当目标价基准；否则退回原来的「IGGM × 让价系数」。
⇒ **D4 不受影响**（D4 的 config 没有「多源基准」段，走旧路径）。
"""
import os
import time

# 大区名（本项目的口径）→ 各站的大区名
# 本项目大区：NA West / NA East / EU / South America / Asia
_REGION_ALIAS = {
    "NA West": ["NA West"],
    "NA East": ["NA East"],
    "EU": ["EU", "Europe"],
    "South America": ["South America", "Latin America", "Latin", "SAM"],
    "Asia": ["Asia"],
}

# 大区 → G2G region_id / ELD 大区名（兜底用；正常从 config 读）
G2G_REGIONS = {
    "US": "dfced32f-2f0a-4df5-a218-1e068cfadffa",
    "EU": "ac3f85c1-7562-437e-b125-e89576b9a38e",
    "Asia": "7d971a93-e541-4055-8fcd-eb942b65701a",
    "SAM": "5b2d2761-128d-4185-9f42-6c502df03516",
}


def _f(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm(s):
    """服务区名归一：去空格、转小写、把全角/半角破折号统一。

    G2G 写 "Siel - Elyos"、ELD 写 "Siel - Elyos"、config 写 "Siel - Elyos（天族）"
    （中文名带括号后缀）。归一后才能跨源匹配。
    """
    if not s:
        return ""
    t = str(s).strip().lower()
    # 去掉中文括号后缀（（天族）/（魔族））
    for ch in ("（", "("):
        i = t.find(ch)
        if i > 0:
            t = t[:i]
    t = t.replace("—", "-").replace("–", "-").replace("－", "-")
    t = " ".join(t.split())
    return t.strip(" -")


def _region_of(region_raw):
    """把各种大区写法归一到本项目口径。"""
    r = (region_raw or "").strip()
    for std, alias in _REGION_ALIAS.items():
        if r in alias:
            return std
    return r


class MultiSource(object):
    """三源抓取 + 基准价计算。

    用法（在 core_gold.build_plan 里）：

        ms = MultiSource(cfg, log=log)
        ms.refresh()                       # 抓 34 区需要的全部 G2G/ELD 数据
        base, why = ms.resolve_base(sv, iggm_price=iggm_cny_or_usd, apo=apo)
    """

    def __init__(self, cfg, log=None, cache_ttl=None):
        self.cfg = cfg or {}
        self.log = log or (lambda *a: None)
        mcfg = self._cfg()
        self.enabled_flag = bool(mcfg.get("启用", False))
        self.ttl = int(cache_ttl if cache_ttl is not None else
                       (mcfg.get("缓存秒") or 1800))
        self._g2g = None          # {"大区|服务区"(归一): {"最低价":..}}
        self._eld = None
        self._ts = 0.0
        self._dump_dir = mcfg.get("快照目录") or ""
        self.stats = {}

    # ---------------------------------------------------------------- config
    def _cfg(self):
        return ((self.cfg.get("金币") or {}).get("多源基准") or {})

    def servers(self):
        """本项目要覆盖的服务区表（config.金币.服务区 里游戏=AION2 的那批）。"""
        out = []
        for sv in ((self.cfg.get("金币") or {}).get("服务区") or []):
            if (sv.get("游戏") or "") != "AION2":
                continue
            if not (sv.get("g2g_服务区") or sv.get("eld_服务区")):
                continue
            out.append(sv)
        return out

    # ------------------------------------------------------------------ 抓取
    def refresh(self, force=False):
        """抓 G2G + ELD（带 TTL 缓存）。返回 True 表示可用。"""
        if not self.enabled_flag:
            return False
        if not force and self._g2g is not None and (time.time() - self._ts) < self.ttl:
            return True
        ok = False
        try:
            import core_g2g
            by, flat = core_g2g.scrape_all(log=self.log)
            self._g2g = {}
            for rec in flat.values():
                k = "%s|%s" % (_region_of(rec.get("大区")), _norm(rec.get("服务区")))
                # 同一 (大区,服务区) 只可能有一条；保险起见取更低的
                old = self._g2g.get(k)
                v = rec.get("最低价")
                if v is None:
                    continue
                if old is None or v < old:
                    self._g2g[k] = v
            ok = ok or bool(self._g2g)
            self._dump("g2g", flat)
        except Exception as e:                    # noqa: BLE001
            self.log("  [多源] G2G 抓取失败：%r" % e)
            self._g2g = self._g2g or {}
        try:
            import core_eld
            flat = core_eld.scrape_all(log=self.log)
            self._eld = {}
            for rec in flat.values():
                k = "%s|%s" % (_region_of(rec.get("大区")), _norm(rec.get("服务区")))
                v = rec.get("最低价")
                if v is None:
                    continue
                old = self._eld.get(k)
                if old is None or v < old:
                    self._eld[k] = v
            ok = ok or bool(self._eld)
            self._dump("eld", flat)
        except Exception as e:                    # noqa: BLE001
            self.log("  [多源] ELD 抓取失败：%r" % e)
            self._eld = self._eld or {}
        self._ts = time.time()
        self.stats = {"g2g": len(self._g2g or {}), "eld": len(self._eld or {})}
        self.log("  [多源] 抓取完成：G2G %d 区、ELD %d 区" %
                 (self.stats["g2g"], self.stats["eld"]))
        return ok

    def _dump(self, src, data):
        """把原始快照落盘留证（可选）。"""
        d = self._dump_dir
        if not d:
            return
        try:
            import json
            if not os.path.isdir(d):
                os.makedirs(d)
            p = os.path.join(d, "%s_%s.json" % (src, time.strftime("%Y%m%d_%H%M%S")))
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception as e:                    # noqa: BLE001
            self.log("  [多源] 快照落盘失败（不影响算价）：%r" % e)

    # -------------------------------------------------------------- 单区取价
    def _lookup(self, table, sv, key_field):
        """按 config 里显式指定的「G2G服务区名 / ELD服务区名」找价。

        config 的服务区项建议带：
          · 大区            = NA West / NA East / EU / South America / Asia
          · g2g_服务区      = "Siel - Elyos"（G2G 页面的服务区名）
          · eld_服务区      = "Siel - Elyos"（ELD 页面的服务区名）
        没配 g2g_服务区 时退回用「中文名」猜（去掉大区前缀与中文括号后缀）。
        """
        if not table:
            return None
        region = _region_of(sv.get("大区") or sv.get("G2G大区") or "")
        name = sv.get(key_field) or ""
        if not name:
            # 退路：中文名「EU · Siel - Elyos（天族）」→ "Siel - Elyos"
            cn = sv.get("中文名") or ""
            if "·" in cn:
                cn = cn.split("·", 1)[1]
            name = cn
        k = "%s|%s" % (region, _norm(name))
        v = table.get(k)
        if v is not None:
            return v
        # 大区没匹配上时，按服务区名在全球找唯一一条（G2G 同名服务区在多个大区都有，
        # 所以只有**唯一命中**才敢用，避免 NA West 的 Siel 被 NA East 的 Siel 顶掉）
        hits = [vv for kk, vv in table.items() if kk.split("|", 1)[-1] == _norm(name)]
        if len(hits) == 1:
            return hits[0]
        return None

    def g2g_of(self, sv):
        return self._lookup(self._g2g, sv, "g2g_服务区")

    def eld_of(self, sv):
        return self._lookup(self._eld, sv, "eld_服务区")

    # ------------------------------------------------------------ 同大区兜底
    def region_avg(self, region, exclude_key=None):  # PATCHED-20261006
        """同大区兜底价 —— **抗污染版：中位数 + 剔离群**（不再是算术均值）。

        用户 2026-10-01 定案：「有些区服其他平台没有就先空着」→「用同大区其他区的
        均价兜底」。

        ⛔ 2026-10-06 事故：原版用 **算术均值**，被 ELD 的离群报价整区污染。
        ELD 对 EU 新区（Tsenka-Quai / Bakarma-Kromede…）返回
        `unitSystem=Unit1000` + `pricePerUnitInUSD.amount=19.99/384/1.0`，
        按 ×1000 换算成 **19990 / 384000 / 1000**（正常量级是 1.2~3.99）。
        这些区 G2G 无货 ⇒ 三源皆空 ⇒ 走本函数 ⇒
            (19990×9 + 1000 + 3.99 + …) / 27 ≈ **6701.5995**
        ⇒ EU 22 个区基准全是 6701.6 ⇒ 毛利率显示成 **-385870%**。

        为什么 aion2_watch.sanity_check 没拦住：它只校验**单行内**三源值偏离中位数，
        而 6701.6 是**整区兜底价**、每行长得「一样离谱」⇒ 中位数判定失效。

        ⇒ 这里改用**中位数**（天然抗单点污染：27 条里 9 条极端值，中位数仍 2.85），
        并先剔除偏离中位数 3 倍以上的离群值再取中位数。
        同时把统计留在 self._last_region_stats，供 resolve_base 做合理性校验。
        """
        vals = []
        for table in (self._g2g, self._eld):
            if not table:
                continue
            for k, v in table.items():
                if k.split("|", 1)[0] != region:
                    continue
                if exclude_key and k == exclude_key:
                    continue
                if v is not None:
                    try:
                        fv = float(v)
                    except (TypeError, ValueError):
                        continue
                    if fv > 0:
                        vals.append(fv)
        if not vals:
            self._last_region_stats = {"region": region, "n_all": 0}
            return None

        svals = sorted(vals)
        n = len(svals)
        med = svals[n // 2] if n % 2 else (svals[n // 2 - 1] + svals[n // 2]) / 2.0
        if med <= 0:
            self._last_region_stats = {"region": region, "n_all": n}
            return None
        keep = [v for v in vals if med / 3.0 <= v <= med * 3.0]
        if not keep:
            keep = [med]
        sk = sorted(keep)
        m2 = len(sk)
        out = sk[m2 // 2] if m2 % 2 else (sk[m2 // 2 - 1] + sk[m2 // 2]) / 2.0
        self._last_region_stats = {
            "region": region, "n_all": n, "n_kept": m2,
            "median_all": med, "used": out,
            "dropped": [v for v in vals if not (med / 3.0 <= v <= med * 3.0)],
        }
        return out

    def region_real_median(self, region_valued):
        """同大区「有真实三源价」的区的**基准中位数**（给兜底合理性校验用）。

        region_valued: {key: 基准}，只应放**非兜底**的真实基准。
        """
        vals = []
        for v in (region_valued or {}).values():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0:
                vals.append(fv)
        if not vals:
            return None
        s = sorted(vals)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0

    # ------------------------------------------------------------- 基准价
    def resolve_base(self, sv, iggm_price=None, apo=1.0, cache=None):
        """算一个服务区的基准价。

        返回 (基准价 $/M, 说明字符串, 明细 dict)；算不出返回 (None, 原因, {...})。

        明细 dict 含 G2G/ELD/IGGM 三方原价与「取谁」，供日志/看板展示。
        """
        region = _region_of(sv.get("大区") or "")
        g = self.g2g_of(sv)
        e = self.eld_of(sv)
        i = _f(iggm_price)
        cand = {}
        if g is not None:
            cand["G2G"] = g
        if e is not None:
            cand["ELD"] = e
        det = {"大区": region, "G2G": g, "ELD": e, "IGGM": i}
        if not cand:
            # 两站都没数据 → 同大区均价兜底
            avg = self.region_avg(region)
            if avg is not None:
                det["兜底"] = "同大区均价"
                det["兜底值"] = round(avg, 4)
                if i is not None and i < avg:
                    det["取谁"] = "IGGM<兜底"
                    return i, ("G2G/ELD 无 %s 数据 → 同大区均价 $%.4f；"
                               "IGGM $%.4f 更低 → 取 IGGM" % (region, avg, i)), det
                return avg, ("G2G/ELD 无 %s 数据 → 同大区均价 $%.4f 兜底"
                             % (region, avg)), det
            # 连同大区都没有 → 只剩 IGGM
            if i is not None:
                det["兜底"] = "仅 IGGM"
                det["取谁"] = "IGGM"
                return i, ("G2G/ELD 无数据且同大区无均价 → 退回 IGGM $%.4f" % i), det
            return None, "三方均无数据", det
        src = min(cand, key=cand.get)
        base = cand[src]
        det["取谁"] = src
        # IGGM 比两站最低价还低 → 跟 IGGM（用户原话：「IGGM 一般不会比上面两家还低，
        # 如果比他们还低，那就跟 IGGM 的价」）
        if i is not None and i < base:
            det["取谁"] = "IGGM(更低)"
            detail = "G2G %s / ELD %s / IGGM %s → IGGM 最低" % (
                _fmt(g), _fmt(e), _fmt(i))
            return i, detail, det
        detail = "G2G %s / ELD %s / IGGM %s → %s 最低" % (_fmt(g), _fmt(e), _fmt(i), src)
        return base, detail, det


def _fmt(v):
    return "-" if v is None else "%.4f" % v
