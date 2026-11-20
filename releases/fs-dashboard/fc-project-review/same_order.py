"""Read the existing Admin publication and Order delivery archives for a paid cohort."""
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from .review import GAMES, TZ, interval
from .orders import PLATFORMS


MAIN = "www.mmoexp.com"
COST_ROOT = Path("/var/lib/fs-channel-effects")
CONTRACT = "fc-same-order-procurement-v1"
ACCOUNTING_RULE = "exclude-confirmed-test-failed-validation-v1"
UNAVAILABLE_NOTE = "同单采购成本本次未取得"


def preserves_delivery_evidence(previous, reviewed, start, end):
    """Every known trade second in the cohort still has evidence of equal authority or newer."""
    previous_order = previous.get("revisions", {}).get("order", [])
    if not previous_order:
        return True
    new_order = sorted(
        (window for window in reviewed["revisions"].get("order", [])
         if window["start"] <= end and start <= window["end"]),
        key=lambda window: window["start"],
    )
    for old in previous_order:
        cursor, stop = max(old["start"], start), min(old["end"], end)
        if cursor > stop:
            continue
        old_stamp = datetime.fromisoformat(old["capturedAt"])
        for fresh in new_order:
            if fresh["start"] > cursor:
                return False
            if fresh["end"] < cursor:
                continue
            stamp = datetime.fromisoformat(fresh["capturedAt"])
            same_authority = (fresh.get("indexRevision") or
                              not old.get("indexRevision") and fresh["revision"] == old["revision"])
            if stamp < old_stamp or stamp == old_stamp and not same_authority:
                continue
            if fresh["end"] >= stop:
                break
            cursor = (datetime.fromisoformat(fresh["end"]) + timedelta(seconds=1)).isoformat(sep=" ")
        else:
            return False
    return True


def same_order_archive_update(packet, reviewed):
    """Return a revised packet when local evidence changes its same-order section."""
    if reviewed["status"] == "unavailable" or reviewed["coverage"]["invalidCostFiles"]:
        return None

    def comparable(section):
        coverage = section.get("coverage", {})
        # Index windows and provenance can advance outside this cohort.
        return (
            section.get("contract"), section.get("status"), section.get("totals"),
            section.get("daily"), section.get("breakdown"), section.get("definition"),
            section.get("revisions", {}).get("accountingRule"),
            {key: value for key, value in coverage.items() if key != "costWindows"},
        )

    previous = packet.get("sameOrder", {})
    if comparable(previous) == comparable(reviewed):
        return None

    before, after = previous.get("coverage", {}), reviewed["coverage"]
    if set(after["missingDays"]) - set(before.get("missingDays", after["missingDays"])):
        return None
    old_revisions, new_revisions = previous.get("revisions", {}), reviewed["revisions"]
    old_admin = old_revisions.get("admin", {}).get("captured_at")
    new_admin = new_revisions.get("admin", {}).get("captured_at")
    if old_admin and new_admin and (
            datetime.fromisoformat(new_admin.replace("Z", "+00:00"))
            < datetime.fromisoformat(old_admin.replace("Z", "+00:00"))):
        return None

    previous_receipts = old_revisions.get("completedStatus", {})
    new_receipts = new_revisions["completedStatus"]
    observations = {day: datetime.fromisoformat(receipt["observedAt"]) for day, receipt in previous_receipts.items()}
    if any(day not in new_receipts or datetime.fromisoformat(new_receipts[day]["observedAt"]) < observed
           for day, observed in observations.items()):
        return None
    new_daily = {item["date"]: item for item in reviewed.get("daily", [])}
    for old in previous.get("daily", []):
        day = old["date"]
        fresh = new_daily[day]
        if (fresh["coveredOrders"] >= old["coveredOrders"]
                or fresh["missingCostOrders"] <= old["missingCostOrders"] or day not in observations):
            continue
        if (new_receipts[day] == previous_receipts[day]
                and new_revisions.get("completedStatusRevision") != old_revisions.get("completedStatusRevision")):
            # Reconstructing the same receipt can lose witnesses when its undo history expires.
            return None
        old_bound = observations[day].astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")
        new_bound = datetime.fromisoformat(new_receipts[day]["observedAt"]).astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")
        if old_bound < new_bound and not any(lo <= old_bound <= new_bound <= hi for lo, hi in after["costWindows"]):
            # The new completed-order observation needs matching delivery coverage.
            return None

    # A verified replacement can correct or remove costs. Rotation cannot prove an older shipment vanished.
    start = packet["start"] + " 00:00:00"
    end = (max(observations.values()).astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")
           if observations else packet["end"] + " 23:59:59")
    if not preserves_delivery_evidence(previous, reviewed, start, end):
        return None
    coverage = [message for message in packet["coverage"] if message != UNAVAILABLE_NOTE]
    return dict(packet, sameOrder=reviewed, coverage=coverage)


@lru_cache(maxsize=12)
def delivery_capture(path, signature):
    from channel_cache import delivery_bounds

    raw = path.read_bytes()
    value = json.loads(raw)
    if (value.get("contract") != "channel-order-deliveries-v1" or value.get("complete") is not True
            or value.get("scope") is not None):
        raise ValueError("invalid_delivery_capture")
    period = value["period"]
    if path.parent.name == "delivery-days" and period != dict(start=path.stem, end=path.stem):
        raise ValueError("invalid_delivery_day")
    start, stop = delivery_bounds(period)
    captured = datetime.fromisoformat(value["generatedAt"].replace("Z", "+00:00"))
    if captured.tzinfo is None or captured.astimezone(TZ).replace(tzinfo=None) < datetime.fromisoformat(stop):
        raise ValueError("invalid_delivery_capture_time")
    rows = {}
    seen = set()
    for row in value["rows"]:
        # The rolling archive also retains records outside its current verified bounds.
        if not start <= row["trade_at"] <= stop:
            if path.parent.name == "delivery-days":
                raise ValueError("invalid_delivery_day_row")
            continue
        identity = str(row["delivery_id"])
        if not identity.isdecimal() or identity in seen or row["source"] != MAIN or str(row["genre"]) != "1":
            raise ValueError("invalid_delivery_scope")
        seen.add(identity)
        if row["sn"]:
            rows[identity] = (row["sn"], row["trade_at"], row["cost_total"])
    return start, stop, captured, sha256(raw).hexdigest(), rows


def delivery_evidence(dates, now, root, order_keys=None):
    if order_keys:
        try:
            from order_delivery_index import read_evidence
        except ImportError:
            read_evidence = None
        if read_evidence is not None:
            evidence = read_evidence(order_keys, root=root, as_of=now)
            if evidence is not None:
                windows = evidence['intervals']
                costs, seen = defaultdict(list), set()
                for row in evidence['rows']:
                    identity = str(row["delivery_id"])
                    if (not identity.isdecimal() or identity in seen or row["source"] != MAIN
                            or str(row["genre"]) != "1" or (MAIN,row["sn"]) not in order_keys
                            or not any(lo <= row["trade_at"] <= hi for lo,hi in windows)):
                        raise ValueError("invalid_delivery_index_row")
                    seen.add(identity)
                    costs[row["sn"]].append((row["trade_at"],row["cost_total"]))
                return costs, windows, evidence['provenance'], []
    captures, missing = [], []
    paths = [root / "order-deliveries.json"]
    # shortcut: consult the selected days and the next closed trade day; wider late-cost history needs an indexed order source.
    next_day = (datetime.fromisoformat(dates[-1]).date() + timedelta(days=1)).isoformat()
    paths.extend(root / "delivery-days" / (day + ".json") for day in (*dates, next_day))
    for path in paths:
        try:
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError("delivery_cache_link")
            stat = path.stat()
            if stat.st_size > 128 * 1024 * 1024:
                raise ValueError("delivery_cache_size")
            capture = delivery_capture(path, (stat.st_mtime_ns, stat.st_size, stat.st_ino))
            if capture[2] > now:
                raise ValueError("future_delivery_capture")
            captures.append(capture)
        except FileNotFoundError:
            continue
        except (OSError, ValueError, KeyError, TypeError):
            missing.append(path.name)
    # A newer complete capture replaces the entire overlapping trade window, including removals.
    records, revisions = {}, []
    for lo, hi, stamp, digest, rows in sorted(captures, key=lambda capture: capture[2]):
        records = {key: row for key, row in records.items() if not lo <= row[1] <= hi}
        records.update(rows)
        revisions.append(dict(start=lo, end=hi, capturedAt=stamp.isoformat(), revision=digest))
    by_order = defaultdict(list)
    for order_no, trade, cost in records.values():
        by_order[order_no].append((trade, cost))
    windows = []
    for lo, hi, *_ in sorted(captures, key=lambda capture: capture[:2]):
        adjacent = (datetime.fromisoformat(lo) - timedelta(seconds=1)).isoformat(sep=" ")
        if windows and adjacent <= windows[-1][1]:
            first, last = windows[-1]
            windows[-1] = (first, max(last, hi))
        else:
            windows.append((lo, hi))
    return by_order, windows, revisions, missing


def same_order_review(game, start, end, *, read=None, status_reader=None, cost_root=COST_ROOT, overrides=None):
    from channel_effects import accounting_row, completed, fraud, money, number
    from channel_source import apply_cost_overrides

    if read is None:
        from shared_es_facts import read
    if status_reader is None:
        from shared_es_facts import read_main_paid_status as status_reader
    gid = GAMES[game][0]
    dates = interval(game, start, end)
    scope = dict(start=start, end=end, site_id="all", gid=gid)
    shared = read(scope,native_only=True)
    source = shared["coverage"]
    missing = source.get("missing_days", dates)
    completed_status, receipts = status_reader(scope)
    now = datetime.now(TZ)
    observations = {}
    for day, receipt in receipts.items():
        instant = datetime.fromisoformat(receipt["observedAt"])
        if instant.tzinfo is None or not datetime.fromisoformat(day).replace(tzinfo=TZ) <= instant <= now:
            raise ValueError("invalid_paid_status_observation")
        observations[day] = instant.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")
    keys = {(MAIN,str(row["order_no"])) for row in shared["rows"]
            if str(row.get("site_id")) == "266" and (row.get("site") or {}).get("full_title") == MAIN
            and row.get("order_no")}
    costs, windows, cost_revisions, invalid_files = (
        delivery_evidence(dates, now, cost_root, keys) if observations else ({}, [], [], []))
    config = (overrides or apply_cost_overrides)(dict(sources={}))
    rows, identities, sites = [], set(), defaultdict(set)
    for raw in shared["rows"]:
        site, title = str(raw["site_id"]), (raw.get("site") or {}).get("full_title")
        pay, order_no, paid_at = str(raw["pay_status"]), raw["order_no"], raw["paytime"]
        day = datetime.strptime(paid_at, "%Y-%m-%d %H:%M:%S").date().isoformat()
        key = (site, order_no)
        if (str(raw["gid"]) != gid or day not in dates or key in identities or pay not in ("1", "2")
                or not site.isdecimal() or not order_no):
            raise ValueError("invalid_paid_order_identity")
        identities.add(key)
        if title:
            sites[title].add(site)
        if pay == "1":
            rows.append((raw, site, title, day, paid_at))
    by_day = defaultdict(list)
    groups = defaultdict(list)
    for raw, site, title, day, paid_at in rows:
        order_no = raw["order_no"]
        main = title == MAIN and site == "266" and sites[MAIN] == {"266"}
        observed = observations.get(day)
        records = costs.get(order_no, ()) if main else ()
        status = raw.get("status_format") or "状态未提供"
        paid = money(raw.get("amount_usd_format"))
        cny = money(raw.get("amount_rmb_format"))
        witness = completed_status.get((day,order_no), {}) if main else {}
        witnessed = (status == "已完成" and witness.get("id") == str(raw.get("id"))
                     and witness.get("paidAt") == paid_at and paid is not None
                     and money(witness.get("amountUsd")) == paid)
        total = None
        if (observed and witnessed and any(lo <= paid_at <= observed <= hi for lo, hi in windows)
                and not any(trade < paid_at for trade, _ in records)):
            amounts = [money(value) for trade, value in records if paid_at <= trade <= observed]
            if amounts and all(value is not None and value >= 0 for value in amounts):
                total = sum(amounts, Decimal(0))
        row = accounting_row(dict(orderNo=order_no, gid=gid, game=game, status=status,
            refunded=status.startswith("已退款"), salesUsd=paid if paid is not None and paid >= 0 else None,
            adminSaleCny=cny if cny is not None and cny >= 0 else None, costCny=total),
            config["costOverrides"] if main else {}, config["testOrders"] if main else {})
        by_day[day].append(row)
        projection = raw.get("fc27_coins") or {}
        # The native projection's order-level aid cannot disambiguate a mixed cart.
        platform = projection.get("platform") if main and game=="FC27" and projection.get("single_line_unit_purchase") is True else None
        groups[site,title,platform if platform in PLATFORMS else "unknown"].append(row)

    def summary(selected, complete):
        cohort = [row for row in selected if not row["refunded"] and not row["testOrder"] and not fraud(row)]
        paid = [row["salesUsd"] for row in cohort if row["salesUsd"] is not None]
        finished = [row for row in cohort if completed(row)]
        covered = [row for row in finished if row["costCny"] is not None and row["saleCny"] is not None]
        uncovered = [row for row in finished if row["costCny"] is None or row["saleCny"] is None]
        missing_cost_sales_usd = [row["salesUsd"] for row in uncovered if row["salesUsd"] is not None]
        missing_cost_sales_cny = [row["adminSaleCny"] for row in uncovered if row["adminSaleCny"] is not None]
        cost = sum((Decimal(str(row["costCny"])) for row in covered), Decimal(0))
        revenue = sum((Decimal(str(row["saleCny"])) for row in covered), Decimal(0))
        known_total = bool(covered) or complete and not cohort
        return dict(orders=len(cohort) if complete else None,
            observedOrders=len(cohort) if cohort or complete else None,
            salesUsd=number(sum(paid, Decimal(0))) if complete and len(paid) == len(cohort) else None,
            observedSalesUsd=number(sum(paid, Decimal(0))) if paid or complete and not cohort else None,
            missingSalesOrders=len(cohort)-len(paid), completedOrders=len(finished), coveredOrders=len(covered),
            excludedOrders=len(selected)-len(cohort), pendingOrders=len(cohort)-len(finished),
            missingCostOrders=len(uncovered),
            missingCostObservedSalesUsd=number(sum(missing_cost_sales_usd,Decimal(0))) if missing_cost_sales_usd else None,
            missingCostObservedSalesCny=number(sum(missing_cost_sales_cny,Decimal(0))) if missing_cost_sales_cny else None,
            missingCostRevenueMissingUsdOrders=len(uncovered)-len(missing_cost_sales_usd),
            missingCostRevenueMissingCnyOrders=len(uncovered)-len(missing_cost_sales_cny),
            coveredSalesCny=number(revenue) if known_total else None,
            actualCostCny=number(cost) if known_total else None, grossCny=number(revenue-cost) if known_total else None,
            grossMarginPct=round(float((revenue-cost)/revenue*100),4) if revenue else None)

    selected = [row for day in dates for row in by_day[day]]
    complete = source.get("admin_complete") is True and not missing
    totals = summary(selected, complete)
    revisions = dict(accountingRule=ACCOUNTING_RULE, admin={key:source.get(key) for key in
        ("publication_id","data_revision","source_revision","captured_at","day_revisions","fc27_projection_revision")},
        completedStatus=receipts,
        completedStatusRevision=sha256(json.dumps(sorted(completed_status.items()),sort_keys=True).encode()).hexdigest(),
        order=cost_revisions, accounting=config["sources"].get("accounting",{}).get("sourceVersion"))
    revision = sha256(json.dumps([CONTRACT,scope,revisions,invalid_files],sort_keys=True).encode()).hexdigest()
    return dict(schema=1, contract=CONTRACT, profile=game, scope="all", period=dict(start=start,end=end),
        timezone="Asia/Shanghai", status="complete" if complete and not any(totals[k] for k in
            ("missingSalesOrders","missingCostOrders","pendingOrders")) else "partial" if selected or complete else "unavailable",
        revision=revision, revisions=revisions, totals=totals,
        daily=[dict(date=day,**summary(by_day[day],day in (source.get("day_revisions") or {}) or complete)) for day in dates],
        breakdown=[dict(siteId=site,website=title,platform=platform,**summary(group,complete))
                   for (site,title,platform),group in sorted(groups.items(),key=lambda pair:(pair[0][0],pair[0][1] or "",pair[0][2]))],
        coverage=dict(adminComplete=complete, missingDays=missing,
            missingCompletedStatusDays=sorted(set(dates)-set(observations)), costWindows=windows,
            invalidCostFiles=invalid_files, costScope=MAIN),
        definition=("Admin 已付订单按付款日统计美元销售，排除已确认测试单、验证未通过及已退款订单。采购毛利为已核完成同单的 Admin 人民币收入减可关联的 Order 普通订单发货采购成本。"
                    "按同网站和原订单号关联，不能关联的销售补发及最终结算不纳入。缺成本或未完成订单不参与毛利，覆盖仅针对已公布的订单版本。"))
