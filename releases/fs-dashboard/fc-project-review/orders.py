"""Project-review order facts from pinned Admin/ES and reconciled Order caches."""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median
import sys
import time
from urllib.parse import urlencode


GAMES = {"833": "FC26", "1327": "FC27"}
MAIN_SITE = "266"
TZ = "Asia/Shanghai"
PLATFORMS = ("PS", "XBOX", "PC")
CATEGORIES = ("Coins", "Players", "SBC", "Packs", "Boosting", "Other")
AMOUNT_EDGES = (20, 40, 60, 80, 100, 150, 200, 300, 500)
AMOUNT_BANDS = ("<20", *(f"{lo}–<{hi}" for lo, hi in zip(AMOUNT_EDGES, AMOUNT_EDGES[1:])), "≥500", "unknown")
DIMENSIONS = {"categories": "category", "platforms": "platform", "countries": "country",
              "payments": "payment", "customerLifecycle": "lifecycle"}
CACHE = Path("/var/lib/fs-business-ranges/fc-detail")
RUNTIME = ("/opt/fs-exact-range-20261001", "/opt/fs-hermes-fc")
COUNTRY = re.compile(r"[A-Z]{2}\Z")
PAYMENT = re.compile(r"[a-z][a-z0-9_-]{0,39}\Z")


def number(value):
    try:
        parsed = Decimal(re.sub(r"[$￥¥,\s]", "", str(value)))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def identity(row, order_field):
    return (str(row["site_id"]), str(row[order_field]))


def comparable_stamp(value):
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def amounts(rows, field):
    values = [row[field] for row in rows]
    return float(sum(values, Decimal(0))) if all(value is not None for value in values) else None


def first_lifecycle(rows):
    earliest = min(row["paid_at"] for row in rows)
    flags = {row["lifecycle"] for row in rows if row["paid_at"] == earliest}
    return next(iter(flags)) if len(flags) == 1 else "unknown"


def group_orders(rows, *keys, customers=True):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in keys)].append(row)
    customer_counts = Counter()
    if customers and "lifecycle" in keys:
        # Customer counts classify the first purchase in each displayed window.
        # Order count and USD retain the original ES flag on each individual order.
        first = defaultdict(list)
        for row in rows:
            if row["buyer"]:
                first[tuple(row[key] for key in keys if key != "lifecycle") + (row["buyer"],)].append(row)
        for orders in first.values():
            flag = first_lifecycle(orders)
            if flag != "unknown":
                customer_counts[tuple(flag if key == "lifecycle" else orders[0][key] for key in keys)] += 1
    output = []
    for group, sample in sorted(groups.items()):
        result = dict(zip(keys, group), orders=len(sample), salesUsd=amounts(sample, "sales"))
        if customers and "lifecycle" in keys:
            result["customers"] = (customer_counts[group]
                                   if result["lifecycle"] != "unknown" and all(row["buyer"] for row in sample)
                                   else None)
        output.append(result)
    return output


def amount_band(value):
    if value is None or value < 0:
        return "unknown"
    return AMOUNT_BANDS[next((index for index, edge in enumerate(AMOUNT_EDGES) if value < edge), len(AMOUNT_EDGES))]


def consumption(rows):
    buyers, buckets = defaultdict(list), defaultdict(list)
    for row in rows:
        if row["buyer"]:
            buyers[row["game"], row["buyer"]].append(row)
    for (game, _), orders in buyers.items():
        buckets[game,amount_band(amounts(orders,"sales")),first_lifecycle(orders)].append(orders)
    cumulative = [dict(game=game,band=band,lifecycle=label,customers=len(people),
                       orders=sum(map(len,people)),salesUsd=amounts([row for orders in people for row in orders],"sales"))
                  for (game,band,label),people in buckets.items()]
    individual = group_orders([dict(row,band=amount_band(row["sales"])) for row in rows],
                              "game","band","lifecycle",customers=False)
    for series in (cumulative, individual):
        series.sort(key=lambda row:(row["game"],AMOUNT_BANDS.index(row["band"]),row["lifecycle"]))
    return cumulative, individual


def status(covered, total, present, reason):
    return dict(status=("complete" if present and covered == total else
                        "partial" if present else "unavailable"),
                coveredOrders=covered, totalOrders=total, reason=reason)


def load_cache(days, root=CACHE):
    wanted = {day + " 00:00": (date.fromisoformat(day) + timedelta(days=1)).isoformat() + " 00:00"
              for day in days}
    daily = {}
    if root.is_dir():
        for path in root.glob("*.json"):
            if path.is_symlink() or path.stat().st_size > 32 * 1024 * 1024:
                continue
            with path.open(encoding="utf-8") as stream:
                value = json.load(stream)
            period = value.get("coverage", {}).get("period", {})
            start, end = period.get("start"), period.get("end")
            if start not in wanted or wanted[start] != end:
                continue
            def preference(entry):
                return (entry.get("coverage", {}).get("native_classification", {}).get("status") == "available",
                        entry.get("shipping_coverage", {}).get("native_summary_reconciled") is True,
                        entry.get("as_of") or "")
            if start not in daily or preference(value) > preference(daily[start]):
                daily[start] = value
    return {day[:10]: item for day, item in daily.items()}


def checked_text(value, pattern):
    value = str(value or "")
    return value if pattern.fullmatch(value) else "unknown"


def normalized_paid(game, native, lines, projections, details):
    hashes = Counter(hashlib.sha256(str(row["order_no"]).encode()).hexdigest() for row in native)
    by_hash = defaultdict(list)
    for row in lines:
        by_hash[row.get("订单号")].append(row)
    rows = []
    for row in native:
        key = identity(row, "order_no")
        day = row["paytime"][:10]
        sales = number(row.get("amount_usd_format"))
        proof = details.get(key, {})
        if proof and comparable_stamp(proof.get("paid_at")) != comparable_stamp(row["paytime"]):
            proof = {}
        if proof.get("_legacy_main_cache") and (sales is None or number(proof.get("amount_cents")) != sales * 100):
            proof = {}
        projection = projections.get(key, {})
        joined_hash = hashlib.sha256(key[1].encode()).hexdigest()
        # Published ES lines use a hash without the site ID. Never bridge a collision across sites.
        linked = [item for item in by_hash.get(joined_hash, [])
                  if str(item.get("付款时间", "")).replace("/", "-")[:10] == day
                  and re.sub(r"\s+", "", str(item.get("游戏") or "")).upper() == game] if hashes[joined_hash] == 1 else []
        flags = {item.get("是否新客户") for item in linked}
        buyers = {str(item.get("buyer_id") or "") for item in linked}
        flag = {"是": "new", "否": "returning"}.get(next(iter(flags))) if len(flags) == 1 else None
        if not linked:
            # The historical channel archive preserves the ES order flag but not customer identity.
            flag = {"新客": "new", "老客": "returning"}.get((row.get("tracking") or {}).get("customerType"))
        category = proof.get("category") if proof.get("category_status") == "verified" else None
        if category == "Other":
            source_types = {item.get("产品类型") for item in linked}
            if proof.get("review_category") in ("Packs", "Boosting", "Other"):
                category = proof["review_category"]
            elif proof.get("item_count") == 1 and source_types == {"代练包(Package)"}:
                category = "Boosting"
            elif proof.get("item_count") != 1 or not source_types or not source_types <= {"账号(Account)", "充值(Top Up)"}:
                category = None
        # The published Coins projection requires strict native ordered-K proof for every content item.
        if category is None and number(projection.get("purchase_k")) and linked and {item.get("产品类型") for item in linked} == {"货币(Gold)"}:
            category = "Coins"
        platform = proof.get("platform")
        projected_platform = projection.get("platform")
        if projected_platform in PLATFORMS:
            platform = projected_platform if platform not in PLATFORMS or platform == projected_platform else None
        regular = number(proof.get("regular_usd", projection.get("regular_usd")))
        discount_values = {number(item.get("折扣金额")) for item in linked}
        discount = next(iter(discount_values)) if len(discount_values) == 1 else None
        if regular is None or regular <= 0 or discount is None or not 0 <= discount <= regular:
            regular = discount = None
        payment = (row.get("paytype_display") or "")
        rows.append(dict(game=game, date=day, key=key, site=(row.get("site") or {}).get("full_title"),
                         platform=platform if platform in PLATFORMS else "unknown",
                         category=category if category in CATEGORIES else "unknown",
                         country=checked_text(row.get("country_code"), COUNTRY), payment=checked_text(payment, PAYMENT),
                         sales=sales, lifecycle=flag or "unknown",
                         buyer=(key[0], next(iter(buyers))) if len(buyers) == 1 and all(buyers) else None,
                         regular=regular, discount=discount, purchase_k=number(projection.get("purchase_k")),
                         paid_at=row.get("paytime"), state=str(row.get("status_format") or ""),
                         order_issue=proof.get("issue") is True, product=proof.get("productProof")))
    return rows


def payment_products(rows):
    batches = defaultdict(list)
    for row in rows:
        product = row["product"]
        if product and row["category"] in ("Players", "SBC"):
            batches[(row["game"], row["category"], product["pid"], product["name"])].append(row)
    return [dict(game=game, category=category, productId=pid, name=name, orders=len(sample),
                 salesUsd=amounts(sample, "sales"))
            for (game, category, pid, name), sample in sorted(batches.items())]


def fulfillment(days, daily, paid):
    matched = {day: value for day, value in daily.items()
               if value.get("shipping_coverage", {}).get("native_summary_reconciled") is True}
    matches = defaultdict(list)
    for row in paid:
        matches[row["site"], row["key"][1]].append(row)
    memberships = {key: rows[0] for key, rows in matches.items() if len(rows) == 1}
    categories = {key: row["category"] for key, row in memberships.items() if row["category"] != "unknown"}
    for value in daily.values():
        for row in value.get("shipping_orders", []):
            if row.get("category_status") == "verified":
                key = (row["site"], row["id"])
                if len(matches.get(key, [])) > 1:
                    continue
                previous = categories.get(key)
                if row["category"] == "Other":
                    continue
                categories[key] = row["category"] if previous in (None, row["category"]) else "unknown"
    shipped, conflicts = {}, set()
    for day, value in matched.items():
        for row in value.get("shipping", []):
            key = (row.get("source"), str(row.get("delivery_id") or ""))
            if not key[0] or not key[1] or str(row.get("trade_at"))[:10] != day:
                raise ValueError("review_shipping_scope")
            if key in shipped and row != shipped[key]:
                conflicts.add(key)
            shipped[key] = row
    groups, times = defaultdict(list), defaultdict(list)
    for identifier, row in shipped.items():
        if identifier in conflicts:
            continue
        key = (row["source"], row["sn"])
        shipment = {**row, "sales": number(row.get("sale_total")), "cost": number(row.get("cost_total"))}
        groups[("all", str(row["trade_at"])[:10])].append(shipment)
        groups[(categories.get(key, "unknown"), str(row["trade_at"])[:10])].append(shipment)
        membership = memberships.get(key)
        if membership:
            paid_at, trade_at = comparable_stamp(membership["paid_at"]), comparable_stamp(row.get("trade_at"))
            if paid_at and trade_at and trade_at >= paid_at:
                times[key].append((trade_at - paid_at).total_seconds() / 60)
    def result(category, sample, **extra):
        sale, cost = amounts(sample, "sales"), amounts(sample, "cost")
        return dict(game="FC27", category=category, shippingRecords=len(sample),
                    shippingOrders=len({(row["source"], row["sn"]) for row in sample}),
                    salesCny=sale, costCny=cost, grossProfitCny=round(sale - cost, 2) if sale is not None and cost is not None else None,
                    medianMinutes=None, p90Minutes=None, **extra)
    rollup = defaultdict(list)
    for (category, _), sample in groups.items():
        rollup[category].extend(sample)
    nonclassified = len(rollup.get("unknown", []))
    coverage_reason = "按 Order 发货交易日。分组为可归属小计，未关联金额单列。"
    if set(matched) != set(days):
        coverage_reason += "部分交易日缺已核对的原生明细。"
    coverage = dict(status=("unavailable" if not matched else "partial" if set(matched) != set(days) or nonclassified or conflicts else "complete"),
                    source="Order /order/admin_delivery/index.html 与 /stats/admin_index/delivery.html",
                    reason=coverage_reason, missingDays=sorted(set(days) - set(matched)),
                    unmatchedCategoryRecords=nonclassified, conflictingRecords=len(conflicts))
    delivery_groups = defaultdict(list)
    for row in paid:
        if row["category"] != "Coins" or row["purchase_k"] is None:
            continue
        key = (row["site"], row["key"][1])
        group = (row["game"], row["platform"], "Coins", "atLeast1000" if row["purchase_k"] >= 1000 else "under1000")
        state = ("problem" if row["order_issue"] or any(word in row["state"] for word in ("问题", "退款", "欺诈", "争议", "投诉"))
                 else "smooth" if row["state"].startswith("已完成") else "unknown")
        delivery_groups[group + (state,)].append(min(times[key]) if times[key] else None)
    delivery_rows = []
    for group, observed in sorted(delivery_groups.items()):
        known = sorted(minutes for minutes in observed if minutes is not None)
        delivery_rows.append(dict(zip(("game","platform","category","quantityBand","deliveryStatus"), group),
                                  orders=len(observed), timedOrders=len(known),
                                  medianMinutes=round(median(known), 2) if known else None,
                                  p90Minutes=round(known[math.ceil(0.9*len(known))-1], 2) if known else None))
    diagnostic = dict(status="partial" if delivery_rows else "unavailable",
                      reason="付款后到窗口内首次已观察发货的耗时。状态为归档时末态诊断，缺完整问题事件和最终交付时间。",
                      rows=[{**{k:v for k,v in row.items() if k != "deliveryStatus"},
                             "observedState": {"smooth":"completed_at_snapshot","problem":"adverse_at_snapshot","unknown":"unknown"}[row["deliveryStatus"]]}
                            for row in delivery_rows])
    return {**coverage, "rows": [result(category, sample) for category, sample in sorted(rollup.items())],
            "daily": [result(category, sample, date=day) for (category, day), sample in sorted(groups.items())]}, diagnostic


def cache_details(daily):
    details = {}
    for snap in daily.values():
        for row in snap.get("orders", []):
            if not row.get("id"):
                continue
            if row.get("site_id"):
                details[identity(row, "id")] = row
            elif row.get("site_group") == "main":
                # The legacy reader wrote "main" only for Admin site 266.
                # Keep historical platform evidence, without using its title-based product bucket.
                details[MAIN_SITE, str(row["id"])] = dict(id=row["id"], paid_at=row.get("paid_at"),
                    amount_cents=row.get("amount_cents"), platform=row.get("platform"), _legacy_main_cache=True)
    return details


def with_main_site_history(data, main):
    cover, main_cover = data["coverage"], main["coverage"]
    publication = cover.get("publication_id")
    if not publication or publication != main_cover.get("publication_id"):
        return data
    missing = set(cover.get("missing_days") or [])
    revisions = {day: revision for day, revision in (main_cover.get("day_revisions") or {}).items()
                 if day in missing}
    if not revisions:
        return data
    # Preserve all-site facts on their original days; use the historically archived site only where all-site facts are absent.
    rows = [row for row in main["rows"] if row["paytime"][:10] in revisions and str(row["site_id"]) == MAIN_SITE]
    lines = [row for row in (main.get("dataset") or {}).get("rows", [])
             if str(row.get("付款时间", "")).replace("/", "-")[:10] in revisions]
    dataset = dict(data.get("dataset") or {})
    dataset["rows"] = [*dataset.get("rows", []), *lines]
    evidence = {key: cover.get(key) or main_cover.get(key) for key in ("publication_id","data_revision","captured_at")}
    return dict(data, rows=[*data["rows"], *rows], dataset=dataset,
                coverage={**cover, **evidence, "main_site_day_revisions": revisions})


def coverage_period(days):
    return f"{len(days)} 天（{days[0]} 至 {days[-1]}）" if days else "0 天"


def aggregate(start, end, datasets, projections, daily, live):
    days = [(date.fromisoformat(start) + timedelta(days=i)).isoformat()
            for i in range((date.fromisoformat(end) - date.fromisoformat(start)).days + 1)]
    details = cache_details(daily)
    details.update(live)
    rows, sources, summaries, site_coverage = [], [], [], []
    for gid, dataset in datasets.items():
        game = GAMES[gid]
        cover = dataset["coverage"]
        members = normalized_paid(game, dataset["rows"], (dataset.get("dataset") or {}).get("rows", []),
                                  projections if gid == "1327" else {}, details if gid == "1327" else {})
        if not all(row["date"] in days for row in members) or len({row["key"] for row in members}) != len(members):
            raise ValueError("review_paid_scope")
        full_days = days if cover["complete"] else sorted(cover.get("day_revisions") or {})
        main_days = sorted(cover.get("main_site_day_revisions") or {})
        source_scope = dict(game=game, allSiteDays=full_days, mainSiteOnlyDays=main_days,
                            uncoveredDays=sorted(set(days)-set(full_days)-set(main_days)))
        site_coverage.append(source_scope)
        sources.append(dict(game=game, source="Admin 付款订单共享归档 + ES 销售订单", siteCoverage=source_scope,
                            **{key: cover.get(key) for key in ("publication_id","data_revision","captured_at","complete","missing_days","day_revisions","main_site_day_revisions","admin_payment_membership")}))
        summaries.append(dict(game=game, orders=len(members) if cover["complete"] or members else None,
                              salesUsd=amounts(members, "sales") if cover["complete"] or members else None))
        rows.extend(members)
    complete = all(source["complete"] is True for source in sources)
    any_source = complete or bool(rows)
    coverage = {"totals": status(len(rows), len(rows), any_source, "付款日共享归档已知小计，经营页 Admin 实时汇总另列。")}
    if not complete and any_source:
        coverage["totals"]["status"] = "partial"
        coverage["totals"]["totalOrders"] = None
    for key, field in DIMENSIONS.items():
        covered = sum(row[field] != "unknown" for row in rows)
        coverage[key] = status(covered, len(rows), any_source and (not rows or bool(covered)),
                               "原字段或完整原生归属；未知订单保留在总额内。")
        if not complete and coverage[key]["status"] == "complete":
            coverage[key]["status"] = "partial"
    known_discount = [row for row in rows if row["regular"] is not None]
    regular, discount = amounts(known_discount, "regular"), amounts(known_discount, "discount")
    discount_data = dict(status=status(len(known_discount), len(rows), bool(known_discount), "")["status"],
                         basis="同单 ES 优惠美元 / Admin 优惠前商品金额，按金额加权",
                         coveredOrders=len(known_discount), totalOrders=len(rows), regularUsd=regular if known_discount else None,
                         discountUsd=discount if known_discount else None,
                         discountPct=round(100 * discount / regular, 4) if regular else None)
    if not complete and discount_data["status"] == "complete":
        discount_data["status"] = "partial"
    coverage["discount"] = {key: discount_data[key] for key in ("status","coveredOrders","totalOrders")}
    coverage["customerLifecycle"]["reason"] = "订单按 ES 新老客标记，历史归档可保留原标记。人数按网站及 buyer_id 去重，以窗内首次付款单标记分组；身份缺失时人数留空。"
    coverage["customerLifecycle"]["buyerKnownOrders"] = sum(row["buyer"] is not None for row in rows)
    sales_known = sum(row["sales"] is not None for row in rows)
    if any_source and sales_known < len(rows):
        coverage["totals"]["status"] = "partial"
        coverage["totals"]["missingSalesOrders"] = len(rows) - sales_known
    shipping, first_shipment = fulfillment(days, daily, rows)
    if "1327" not in datasets:
        shipping["reason"] = "现有交易日发货明细仅覆盖 FC27。"
    coverage["fulfillment"] = {key: shipping[key] for key in ("status","reason")}
    products = payment_products(rows)
    spend_bands, order_bands = consumption(rows)
    buyer_order_count = sum(row["buyer"] is not None for row in rows)
    coverage["spendBands"] = status(buyer_order_count, len(rows), any_source and (not rows or bool(buyer_order_count)),
                                     "按窗口内站点及 buyer_id 聚合实付美元，无可核客户身份的订单单列覆盖。")
    if not complete and coverage["spendBands"]["status"] == "complete":
        coverage["spendBands"]["status"] = "partial"
    product_orders = sum(product["orders"] for product in products)
    coverage["products"] = status(product_orders, sum(row["category"] in ("Players","SBC") for row in rows),
                                  bool(products), "可核原生目录、且完整订单仅含单个 PID 的球员卡／SBC实收。")
    if not complete and coverage["products"]["status"] == "complete":
        coverage["products"]["status"] = "partial"
    has_all_sites = any(item["allSiteDays"] for item in site_coverage)
    has_main_only = any(item["mainSiteOnlyDays"] for item in site_coverage)
    effective_site = "mixed" if has_all_sites and has_main_only else "all" if has_all_sites else MAIN_SITE if has_main_only else None
    if not complete:
        scope_note = " ".join(
            f'{item["game"]} 全站{coverage_period(item["allSiteDays"])}，'
            f'MMOEXP 主站（266）{coverage_period(item["mainSiteOnlyDays"])}，'
            f'两种口径均缺{coverage_period(item["uncoveredDays"])}。'
            for item in site_coverage)
        for key in ("totals", *DIMENSIONS, "spendBands", "products", "discount"):
            coverage[key]["reason"] = (coverage[key].get("reason", "") + " " + scope_note).strip()
        if has_main_only:
            coverage["totals"]["reason"] += "主站历史归档与 Admin 实时全站统计的支付状态及快照时间不同，两者不能按包含关系相减。"
    delivery = {"status":"unavailable","reason":"完成发货时点和完整问题事件资料不在已读订单快照。","rows":[]}
    coverage["delivery"] = {key:delivery[key] for key in ("status","reason")}
    if daily:
        sources.append(dict(source="原 FC 明细读取的北京自然日缓存快照", snapshots={day:value.get("snapshot_id") for day,value in daily.items()}))
    if live:
        sources.append(dict(source="Admin Direct 原生 PID 目录和逐 PID 付款单关联", purpose="补足已有快照的分类缺口"))
    return dict(status=("unavailable" if not any_source else "complete" if complete and all(item["status"] == "complete" for item in coverage.values()) else "partial"),
                scope=dict(start=start,end=end,timezone=TZ,site="all",effectiveSite=effective_site,
                           games=[GAMES[gid] for gid in datasets],siteCoverageByGame=site_coverage),
                totals=dict(orders=len(rows) if any_source else None,salesUsd=amounts(rows,"sales") if any_source else None),
                games=summaries, daily=group_orders(rows,"date","game"),
                **{key:group_orders(rows,"game",field) for key,field in DIMENSIONS.items()},
                categoryDaily=group_orders(rows,"date","game","category"), lifecycleDaily=group_orders(rows,"date","game","lifecycle"),
                sites=group_orders([dict(row,siteId=row["key"][0]) for row in rows],"game","siteId"),
                fulfillment=shipping, firstShipmentDiagnostic=first_shipment,
                delivery=delivery,
                products=products, discount=discount_data,
                spendBands=spend_bands, orderAmountBands=order_bands,
                coverage=coverage, sources=sources, gaps=[key for key,value in coverage.items() if value["status"]!="complete"])


def review_category(category, items, paths):
    if category != "Other":
        return category
    product_paths = [paths[item["goods"]["cid"]] for item in items]
    if any("9825" in path for path in product_paths):
        return "Packs"
    if any(path[0] == "4" or path[0] == "5" and set(path) & {"104", "106", "108"} for path in product_paths):
        return "Boosting"
    return "Other"


def native_details(days):
    """Reuse the original complete product membership and its fixed Admin read endpoints."""
    from fc_dashboard import native_membership
    from fc_detail_model import normalize
    from fc_detail_reader import native_page_rows
    from summary_bridge import dc_request
    config = json.loads((Path(RUNTIME[0]) / "fc_detail_config.json").read_text(encoding="utf-8"))
    result = {}
    for day in days:
        period = dict(start=day+" 00:00",end=(date.fromisoformat(day)+timedelta(days=1)).isoformat()+" 00:00")
        budget, deadline, catalog = 300, time.monotonic()+300, {}
        def read(path):
            nonlocal budget
            if budget <= 0 or time.monotonic() >= deadline:
                raise TimeoutError("review_native_budget")
            budget -= 1
            code, raw = dc_request(path, method="GET")
            if code in (301,302,401,403):
                raise PermissionError("review_native_denied")
            if "productSalesByEs" in path and code == 200:
                for product in (json.loads(raw).get("data") or {}).get("list") or []:
                    goods = product.get("goods")
                    if isinstance(goods, dict):
                        name = product.get("title")
                        if isinstance(name,str) and name.strip() and len(name) <= 240 and not re.search(r"[@<>]",name):
                            catalog[str(product["pid"])] = name.strip()
            return code, raw
        def pages(filters, name):
            rows, seen, expected, last = [], set(), None, math.inf
            count = 0
            for page in range(1, 301):
                request = dict(page=page,limit=100,order="id,desc")
                for index, (field,value,operator) in enumerate(filters):
                    request.update({f"search[{index}][field]":field,f"search[{index}][val]":value,
                                    f"search[{index}][operator]":operator})
                    if field == "paytime":
                        request[f"search[{index}][render]"] = "datetime"
                code, raw = read("/admin/order.Order/index?"+urlencode(request))
                value = json.loads(raw); data = value.get("data") or {}
                batch, total = data.get("list"), data.get("total")
                if code != 200 or value.get("code") != 1 or not isinstance(batch,list) or type(total) is not int or total < 0 or (expected is not None and total != expected):
                    raise ValueError("review_native_page")
                expected = total
                if any(str(row.get("gid")) != "1327" or str(row.get("pay_status")) != "1" or str(row.get("paytime") or "")[:10] != day for row in batch):
                    raise ValueError("review_native_scope")
                count += len(batch)
                batch, _ = native_page_rows(batch, seen)
                ids = [int(row["id"]) for row in batch]
                if ids != sorted(ids,reverse=True) or (ids and ids[0] >= last):
                    raise ValueError("review_native_sort")
                if ids:
                    last = ids[-1]
                seen.update(ids)
                rows.extend(batch)
                if count == total:
                    return rows
                if not batch or count > total:
                    raise ValueError("review_native_total")
            raise ValueError("review_native_pages")
        base = [("gid",1327,"="),("pay_status",1,"="),("paytime",day+" 00:00:00,"+day+" 23:59:59","RANGE")]
        paid = pages(base,"paid")
        paths, proof = native_membership(read,pages,paid,period,config)
        print(json.dumps({"day":day,"paid":len(paid),"native":proof},ensure_ascii=False),file=sys.stderr)
        sites = {int(row["site_id"]) for row in paid}
        if not sites:
            continue
        for raw in paid:
            row = normalize(raw,{**config,"_category_paths":paths},sites)
            row["regular_usd"] = raw.get("before_discount")
            items = raw.get("_fc_native_items", [])
            if row["category_status"]=="verified":
                row["review_category"] = review_category(row["category"],items,paths)
            if row["category_status"]=="verified" and len(items)==1:
                pid = items[0]["pid"]
                row["productProof"] = dict(pid=pid,name=catalog.get(pid,"PID "+pid))
            result[identity(row,"id")] = row
    return result


def read_orders(start, end, native_days=(), *, game=None, publication_id=None):
    lo, hi = date.fromisoformat(start), date.fromisoformat(end)
    if lo > hi or (hi-lo).days >= 366 or any(not start <= day <= end for day in native_days):
        raise ValueError("review_order_period")
    games = [gid for gid, label in GAMES.items() if game is None or game == label]
    if not games or (native_days and "1327" not in games):
        raise ValueError("review_order_game")
    for root in reversed(RUNTIME):
        if root not in sys.path:
            sys.path.insert(0, root)
    from shared_es_facts import latest_publication, read
    publication = publication_id or (latest_publication() or {}).get("publication_id")
    scope = dict(start=start,end=end,site_id="all")
    datasets = {gid:read(dict(scope,gid=gid),publication_id=publication) for gid in games}
    projections, daily = {}, {}
    days = [(lo+timedelta(days=i)).isoformat() for i in range((hi-lo).days+1)]
    for gid, dataset in datasets.items():
        if gid == "1327" or dataset["coverage"].get("missing_days"):
            main = read(dict(scope,site_id=MAIN_SITE,gid=gid),publication_id=publication)
            datasets[gid] = with_main_site_history(dataset, main)
            if gid == "1327":
                projections = {identity(row,"order_no"):row["fc27_coins"] for row in main["rows"] if "fc27_coins" in row}
    if "1327" in datasets:
        daily = load_cache(days)
    return aggregate(start,end,datasets,projections,daily,native_details(sorted(set(native_days))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start")
    parser.add_argument("end",help="Inclusive Shanghai business date")
    parser.add_argument("--game",choices=tuple(GAMES.values()))
    parser.add_argument("--publication-id",help="Published shared ES snapshot ID")
    parser.add_argument("--native-day",action="append",default=[],help="Read existing native Admin product facts for this closed date")
    args = parser.parse_args()
    print(json.dumps(read_orders(args.start,args.end,args.native_day,game=args.game,publication_id=args.publication_id),
                     ensure_ascii=False,allow_nan=False))
