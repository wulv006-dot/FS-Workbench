"""FC27 Coins: competitor delivered USD/K prices our base K; gifts remain in cost."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from fractions import Fraction
import hashlib
import json
import re

PLATFORMS = ("PS", "XBOX", "PC")
SITES = ("Lootbar", "U4GM", "IGGM", "U7Buy")
STEP = Decimal("0.0001")
BASE_LOOTBAR_REDUCTION_PCT = Decimal("0.5")
SHARED_GAP_WEIGHT = Decimal("0.15")
UNCONFIRMED_GAP_WEIGHT = Decimal("0.05")
MAX_LOOTBAR_REDUCTION_PCT = Decimal("8")
PAGE_BASE_K = Decimal("100")
PAGE_CENTS = Decimal("100")


DISCOUNT_RULES_SCHEMA = 1
DISCOUNT_BANDS = ("at_least_40", "30_to_40", "20_to_30", "below_20")


def default_discount_rules():
    return {"schema_version": DISCOUNT_RULES_SCHEMA, "bands": {
        name: {"min_discount_pct": low, "max_discount_pct": high}
        for name, low, high in (("at_least_40", "0.00", "10.00"),
                                ("30_to_40", "7.50", "7.50"),
                                ("20_to_30", "5.00", "5.00"),
                                ("below_20", "0.00", "0.00"))}}


def normalize_discount_rules(value=None):
    if value is None:
        return default_discount_rules()
    if (not isinstance(value, dict) or set(value) != {"schema_version", "bands"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != DISCOUNT_RULES_SCHEMA
            or not isinstance(value["bands"], dict)
            or set(value["bands"]) != set(DISCOUNT_BANDS)):
        raise ValueError("automation_discount_rules_invalid")
    bands = {}
    for name in DISCOUNT_BANDS:
        row = value["bands"][name]
        if not isinstance(row, dict) or set(row) != {"min_discount_pct", "max_discount_pct"}:
            raise ValueError("automation_discount_rules_invalid")
        numbers = {}
        for key in ("min_discount_pct", "max_discount_pct"):
            text = row[key]
            if type(text) is not str or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", text):
                raise ValueError("automation_discount_pct_invalid")
            number = Decimal(text)
            if not 0 <= number <= 10:
                raise ValueError("automation_discount_pct_invalid")
            numbers[key] = number
        if numbers["min_discount_pct"] > numbers["max_discount_pct"]:
            raise ValueError("automation_discount_range_invalid")
        bands[name] = {key: f"{number:.2f}" for key, number in numbers.items()}
    return {"schema_version": DISCOUNT_RULES_SCHEMA, "bands": bands}


def discount_rules_sha256(value=None):
    return hashlib.sha256(json.dumps(normalize_discount_rules(value), sort_keys=True,
                                    separators=(",", ":")).encode("ascii")).hexdigest()


def clamp_discount(reduction, tier, rules=None):
    bounds = normalize_discount_rules(rules)["bands"][tier]
    return min(max(reduction, Fraction(Decimal(bounds["min_discount_pct"])) / 100),
               Fraction(Decimal(bounds["max_discount_pct"])) / 100)


def ceil_integer(value):
    return int(value.to_integral_value(rounding=ROUND_UP))


def floor_integer(value):
    return int(value.to_integral_value(rounding=ROUND_DOWN))


def tiered_page_price(lootbar_page, u4gm_page, iggm_page, cost_usd_per_k,
                      delivered_k, minimum_margin, before_margin, *,
                      lootbar_delivered_k, u4gm_delivered_k, iggm_delivered_k, pricing_rules=None):
    """Price base K from competitor delivered USD/K; cost includes our gifts."""
    pages = (lootbar_page, u4gm_page, iggm_page)
    if any(page != page.quantize(Decimal("0.01")) for page in pages):
        raise ValueError("竞品页面总价须精确到美分")
    quantities = (lootbar_delivered_k, u4gm_delivered_k, iggm_delivered_k, delivered_k)
    if any(quantity <= 0 or quantity > 200 for quantity in quantities):
        raise ValueError("商品含赠送金币数超出范围")
    lootbar_unit = Fraction(lootbar_page) / Fraction(lootbar_delivered_k)
    u4gm_unit = Fraction(u4gm_page) / Fraction(u4gm_delivered_k)
    iggm_unit = Fraction(iggm_page) / Fraction(iggm_delivered_k)
    cost_cents = cost_usd_per_k * delivered_k * PAGE_CENTS
    minimum_cents = ceil_integer(cost_cents / (1 - minimum_margin / 100))
    if before_margin >= 40:
        name = "at_least_40"
        gaps = [max(Fraction(0), (lootbar_unit - unit) / lootbar_unit)
                for unit in (u4gm_unit, iggm_unit)]
        reduction = min(Fraction(1, 10), sum(gaps) / 2)
    elif before_margin >= 30:
        name = "30_to_40"
        reduction = Fraction(3, 40)
    elif before_margin >= 20:
        name = "20_to_30"
        reduction = Fraction(1, 20)
    else:
        name = "below_20"
        reduction = Fraction(0)
    reduction = clamp_discount(reduction, name, pricing_rules)
    preferred = lootbar_unit * (1 - reduction) * Fraction(PAGE_BASE_K) * 100
    preferred_cents = -(-preferred.numerator // preferred.denominator)
    target_cents = max(preferred_cents, minimum_cents)
    page = Decimal(target_cents) / PAGE_CENTS
    margin = (1 - cost_usd_per_k * delivered_k / page) * 100
    exact_discount = (1 - Fraction(page) / Fraction(PAGE_BASE_K) / lootbar_unit) * 100
    discount = Decimal(exact_discount.numerator) / Decimal(exact_discount.denominator)
    maximum_discount = Decimal(normalize_discount_rules(pricing_rules)["bands"][name]["max_discount_pct"])
    if margin < minimum_margin or exact_discount > Fraction(maximum_discount):
        raise ValueError("分档价格边界校验失败")
    return {"cents": target_cents, "tier": name, "discount": discount,
            "requested_discount": Decimal(reduction.numerator) / Decimal(reduction.denominator) * 100,
            "profit_floor_applied": minimum_cents > preferred_cents}


def positive(value, label):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{label} 不是有效数字") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{label} 必须大于 0")
    return number


def nonnegative(value, label):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{label} 不是有效数字") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{label} 不得小于 0")
    return number


def align_console_prices(rows, evidence, fx):
    """FC27 Xbox automation follows the PS auto quote; retain Xbox's own cost floor."""
    if evidence.get("game") != "FC27" or not evidence.get("storefront"):
        return
    by_platform = {row["platform"]: row for row in rows}
    ps, xbox = by_platform["PS"], by_platform["XBOX"]
    if xbox.get("pricing_basis") != "page_total_100k":
        return
    xbox["independent_auto_proposal"] = xbox.get("auto_proposal")
    xbox["auto_price_source"] = "PS"
    anchor = ps.get("auto_proposal")
    if ps.get("missing") or not anchor or ps.get("auto_blocked_reason"):
        xbox["auto_proposal"] = None
        if not xbox.get("quote_manual"):
            xbox.update(auto_blocked_reason="ps_auto_price_unavailable", target_page_usd=None,
                        status="PS 自动建议价不可用 · Xbox 暂不自动改价",
                        warning="PS 没有有效自动建议价，Xbox 本轮不执行自动改价。")
        return
    xbox["auto_proposal"] = anchor
    if xbox.get("quote_manual"):
        return
    price = positive(anchor, "PS 自动建议价")
    delivered = PAGE_BASE_K + Decimal(xbox["own_bonus_k"])
    page = price * PAGE_BASE_K
    margin = (1 - Decimal(xbox["cost_cny"]) / fx * delivered / page) * 100
    lootbar_offer = next(offer for offer in xbox["offers"] if offer["site"] == "Lootbar")
    lootbar_unit = Decimal(lootbar_offer["usd_price"]) / (
        Decimal(lootbar_offer["base_k"]) + Decimal(lootbar_offer["bonus_k"]))
    below = price < Decimal(xbox["floor_usd_per_1k"])
    xbox.update(proposal=f"{price:.4f}", target_page_usd=f"{page:.2f}",
                gross_margin_pct=f"{margin:.2f}", margin_below_minimum=below,
                lootbar_reduction_pct=f"{(1 - page / PAGE_BASE_K / lootbar_unit) * 100:.2f}",
                auto_blocked_reason=None, pricing_mode="ps_shared_market",
                pricing_tier=ps.get("pricing_tier"), benchmark_site="PS",
                requested_discount_pct=ps.get("requested_discount_pct"),
                profit_floor_applied=ps.get("profit_floor_applied", False),
                warning="PS 建议价低于 Xbox 最低毛利要求，Xbox 本轮不执行自动改价。" if below else ps.get("warning", ""),
                status="跟随 PS 建议价 · Xbox 毛利不足，自动改价拦截" if below else
                       "与 PS 统一自动售价 · 待审核")


def calculate(evidence, edits=None):
    """Return comparison rows and proposals. Edits never mutate source evidence."""
    edits = edits or {}
    pricing_rules = normalize_discount_rules(edits.get("pricing_rules"))
    cost_edits = edits.get("costs") or {}
    offer_edits = edits.get("offers") or {}
    quote_edits = edits.get("quotes") or {}
    fx = positive(evidence["fx"]["cny_per_usd"], "人民币兑美元汇率")
    minimum_margin = nonnegative(edits.get("minimum_gross_margin_pct", "10"), "最低毛利率")
    if minimum_margin >= 100:
        raise ValueError("最低毛利率必须低于 100%")
    rows = []
    for platform in PLATFORMS:
        raw_cost = evidence.get("costs", {}).get(platform)
        raw_cost = raw_cost or {}
        raw_cost_value = (positive(raw_cost["cny_per_1k"], f"{platform} 采购成本")
                          if raw_cost.get("cny_per_1k") else None)
        effective_cost = (positive(cost_edits.get(platform, raw_cost_value), f"{platform} 人工成本")
                          if raw_cost_value or platform in cost_edits else None)
        offers = []
        missing = []
        benchmark = []
        for site in SITES:
            source = evidence.get("offers", {}).get(platform, {}).get(site)
            manual = offer_edits.get(platform, {}).get(site) or {}
            if not source and not manual:
                missing.append(site)
                offers.append({"site": site, "status": "缺数据", "comparable": False})
                continue
            source = source or {}
            try:
                price = positive(manual.get("usd_price", source.get("usd_price")), f"{platform} {site} 售价")
                base = positive(manual.get("base_k", source.get("base_k")), f"{platform} {site} 购买 K")
                bonus = nonnegative(manual.get("bonus_k", source.get("bonus_k", 0)), f"{platform} {site} 赠送 K")
            except ValueError:
                missing.append(site)
                offers.append({"site": site, "status": "价格或数量缺数据", "comparable": False})
                continue
            conditional = bool(source.get("conditional"))
            comparable = bool(manual.get("comparable", source.get("comparable", not conditional)))
            unit = price / (base + bonus)
            offer = {
                "site": site,
                "usd_price": str(price),
                "base_k": str(base),
                "bonus_k": str(bonus),
                "usd_per_1k": f"{unit:.4f}",
                "comparable": comparable,
                "conditional": conditional,
                "manual": bool(manual),
                "url": manual.get("url") or source.get("url", ""),
                "checked_at": manual.get("checked_at") or source.get("checked_at"),
                "status": source.get("status", "已核对") if not manual else "人工修正",
            }
            offers.append(offer)
            if comparable:
                benchmark.append((unit, site))
        base_row = {
            "platform": platform,
            "raw_cost_cny": str(raw_cost_value) if raw_cost_value else None,
            "cost_cny": str(effective_cost) if effective_cost else None,
            "cost_manual": platform in cost_edits,
            "cost_record_id": raw_cost.get("record_id"),
            "cost_trade_at": raw_cost.get("trade_at"),
            "offers": offers,
            "missing": missing,
        }
        if effective_cost is None:
            base_row.update(status="缺成本", proposal=None)
            rows.append(base_row)
            continue
        if missing or not benchmark:
            base_row.update(status="缺竞品数据" if missing else "无可比竞品", proposal=None)
            rows.append(base_row)
            continue
        lowest, lowest_site = min(benchmark)
        floor = (effective_cost / fx / (Decimal("1") - minimum_margin / 100)).quantize(STEP, rounding=ROUND_UP)
        comparable = {site: unit for unit, site in benchmark}
        if any(site not in comparable for site in ("Lootbar", "U4GM", "IGGM")):
            base_row.update(status="核心竞品不可比", proposal=None)
            rows.append(base_row)
            continue
        lootbar = comparable["Lootbar"]
        u4gm_gap = max(Decimal("0"), (lootbar - comparable["U4GM"]) / lootbar * 100)
        iggm_gap = max(Decimal("0"), (lootbar - comparable["IGGM"]) / lootbar * 100)
        storefront = (evidence.get("storefront") or {}).get("rows", {}).get(platform)
        if storefront:
            if positive(storefront.get("base_k"), "MMOEXP 购买 K") != PAGE_BASE_K:
                raise ValueError("MMOEXP 100K 商品规格不符")
            own_bonus = nonnegative(storefront.get("bonus_k"), "MMOEXP 赠送 K")
            if own_bonus > 100:
                raise ValueError("MMOEXP 赠送 K 超出范围")
            comparable_offers = {offer["site"]: offer for offer in offers if offer.get("comparable")}
            if any(Decimal(comparable_offers[site]["base_k"]) != PAGE_BASE_K
                   for site in ("Lootbar", "U4GM", "IGGM")):
                base_row.update(status="核心竞品规格不一致", proposal=None)
                rows.append(base_row)
                continue
            pages = {site: positive(comparable_offers[site]["usd_price"], site + " 页面总价")
                     for site in ("Lootbar", "U4GM", "IGGM")}
            quantities = {site: PAGE_BASE_K + nonnegative(comparable_offers[site]["bonus_k"],
                                                           site + " 赠送 K")
                          for site in ("Lootbar", "U4GM", "IGGM")}
            if any(quantity > 200 for quantity in quantities.values()):
                base_row.update(status="核心竞品赠送数量异常", proposal=None)
                rows.append(base_row)
                continue
            page_gaps = {site: max(Decimal(0), (lootbar - comparable[site]) / lootbar * 100)
                         for site in ("U4GM", "IGGM")}
            delivered = PAGE_BASE_K + own_bonus
            cost_usd = effective_cost / fx
            before_page = positive(storefront.get("package_usd"), "MMOEXP 当前页面总价")
            before_margin = (Decimal(1) - cost_usd * delivered / before_page) * 100
            picked = tiered_page_price(pages["Lootbar"], pages["U4GM"], pages["IGGM"],
                                      cost_usd, delivered, minimum_margin, before_margin,
                                      lootbar_delivered_k=quantities["Lootbar"],
                                      u4gm_delivered_k=quantities["U4GM"],
                                      iggm_delivered_k=quantities["IGGM"], pricing_rules=pricing_rules)
            floor_cents = ceil_integer(cost_usd * delivered * PAGE_CENTS /
                                       (1 - minimum_margin / 100))
            floor = Decimal(floor_cents) / Decimal("10000")
            auto = Decimal(picked["cents"]) / Decimal("10000") if picked else None
            is_manual = platform in quote_edits
            manual = positive(quote_edits[platform], f"{platform} 人工建议价") if is_manual else None
            if manual is not None and manual != manual.quantize(STEP):
                raise ValueError("人工建议价最多四位小数")
            # A technical fallback keeps a complete preview; write gates reject it until
            # the operator supplies an explicit manual quote.
            final = manual if is_manual else auto if auto is not None else floor
            page_total = final * PAGE_BASE_K
            gross_margin = (Decimal(1) - cost_usd * delivered / page_total) * 100
            below_floor = final < floor
            blocked = not is_manual and picked is None
            blocked_reason = "no_feasible_price_in_band" if blocked else None
            reduction = (Decimal(1) - (page_total / PAGE_BASE_K) / lootbar) * 100
            warning = ("人工建议价低于设定毛利率；已按人工审核价待确认发布。"
                       if is_manual and below_floor else
                       "目标降幅与设置的最低毛利率无共同可行价；已暂停该平台自动改价，请人工审核。"
                       if blocked else
                       f"最低 {minimum_margin}% 毛利保护覆盖目标降幅 {picked['requested_discount']:.2f}%；实际采用降幅 {reduction:.2f}%，标价 ${page_total:.2f}，赠送计入采购成本。"
                       if not is_manual and picked and picked["profit_floor_applied"] else "")
            base_row.update(
                lowest_site=lowest_site, lowest_usd_per_1k=f"{lowest:.4f}",
                lootbar_usd_per_1k=f"{lootbar:.4f}",
                lootbar_page_usd=f"{pages['Lootbar']:.2f}",
                target_page_usd=f"{page_total:.2f}" if not blocked or is_manual else None,
                pricing_basis="page_total_100k", pricing_tier=picked["tier"] if picked else None,
                pricing_quantity_basis="own_base_competitor_delivered",
                requested_discount_pct=f"{picked['requested_discount']:.2f}" if picked else None,
                profit_floor_applied=bool(not is_manual and picked and picked["profit_floor_applied"]),
                own_bonus_k=str(own_bonus), pre_change_margin_pct=f"{before_margin:.2f}",
                u4gm_gap_pct=f"{page_gaps['U4GM']:.2f}",
                iggm_gap_pct=f"{page_gaps['IGGM']:.2f}",
                lootbar_reduction_pct=f"{reduction:.2f}" if not blocked or is_manual else None,
                floor_usd_per_1k=f"{floor:.4f}",
                auto_proposal=f"{auto:.4f}" if auto is not None else None,
                proposal=f"{final:.4f}", quote_manual=is_manual,
                gross_margin_pct=f"{gross_margin:.2f}",
                pricing_mode="manual" if is_manual else "tier_unavailable" if blocked else "lootbar_anchor",
                benchmark_site="Lootbar", minimum_gross_margin_pct=str(minimum_margin),
                margin_below_minimum=below_floor,
                auto_blocked_reason=blocked_reason,
                warning=warning,
                status=("人工审核通过 · 待发布" if is_manual else
                        "分档无可行自动价 · 待人工审核" if blocked else
                        "按 Lootbar 含赠送实际单价对标 · 待审核"),
            )
            rows.append(base_row)
            continue
        reduction = min(MAX_LOOTBAR_REDUCTION_PCT,
                        BASE_LOOTBAR_REDUCTION_PCT
                        + SHARED_GAP_WEIGHT * min(u4gm_gap, iggm_gap)
                        + UNCONFIRMED_GAP_WEIGHT * max(u4gm_gap, iggm_gap))
        target = (lootbar * (Decimal("1") - reduction / 100)).quantize(STEP, rounding=ROUND_DOWN)
        cap_floor = (lootbar * (Decimal("1") - MAX_LOOTBAR_REDUCTION_PCT / 100)).quantize(
            STEP, rounding=ROUND_UP)
        auto = max(target, cap_floor)
        is_manual = platform in quote_edits
        final = positive(quote_edits[platform], f"{platform} 人工建议价") if is_manual else auto
        below_floor = final is not None and final < floor
        gross_margin = (Decimal("1") - effective_cost / fx / final) * 100 if final else None
        warning = ("人工建议价低于设定毛利率；已按人工审核价待确认发布。" if is_manual and below_floor else
                   f"Lootbar 基准下调 {reduction:.2f}% 后仍未达设定毛利率，请逐项审核。"
                   if below_floor else "")
        base_row.update(
            lowest_site=lowest_site,
            lowest_usd_per_1k=f"{lowest:.4f}",
            lootbar_usd_per_1k=f"{lootbar:.4f}",
            u4gm_gap_pct=f"{u4gm_gap:.2f}",
            iggm_gap_pct=f"{iggm_gap:.2f}",
            lootbar_reduction_pct=f"{reduction:.2f}",
            floor_usd_per_1k=f"{floor:.4f}",
            auto_proposal=f"{auto:.4f}" if auto else None,
            proposal=f"{final:.4f}" if final else None,
            quote_manual=is_manual,
            gross_margin_pct=f"{gross_margin:.2f}" if gross_margin is not None else None,
            pricing_mode="manual" if is_manual else "margin_warning" if below_floor else "lootbar_anchor",
            benchmark_site="Lootbar",
            minimum_gross_margin_pct=str(minimum_margin),
            margin_below_minimum=below_floor,
            warning=warning,
            status=("人工审核通过 · 待发布" if is_manual else
                    "低于设定毛利率 · 待审核" if below_floor else
                    "按 Lootbar 对标 · 待审核"),
        )
        rows.append(base_row)
    align_console_prices(rows, evidence, fx)
    return {"checked_at": evidence.get("checked_at"), "fx": evidence["fx"],
            "minimum_gross_margin_pct": str(minimum_margin), "rows": rows}
