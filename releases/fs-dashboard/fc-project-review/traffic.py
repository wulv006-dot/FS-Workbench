"""Build the FC27 project traffic packet from authorized, read-only sources on 187."""
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import gzip
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlsplit

FS_MARKETING = Path("/var/lib/fs-data-archive/marketing/MMOEXP")
READER_PATH = "/opt/mmoexp-marketing/details"
ACCOUNTS = {"1430398974", "8154986819", "3552474396"}
CN = timezone(timedelta(hours=8))
FC_PATH = r"/(?:[a-z]{2}/)?fc-27(?:/.*|[.]html)?"
GA_URL = "https://analyticsdata.googleapis.com/v1beta/properties/541418940:runReport"
GSC_URL = "https://www.googleapis.com/webmasters/v3/sites/" + quote("sc-domain:mmoexp.com", safe="") + "/searchAnalytics/query"
ADS_FIELDS = {"cost": "cost", "impressions": "impressions", "clicks": "clicks",
              "conversions": "conversions", "value": "conversionsValue"}
GA_FIELDS = {"sessions": "sessions", "purchases": "ecommercePurchases", "new_users": "newUsers"}
GSC_FIELDS = ("clicks", "impressions", "ctr", "position")
WINDOWS = ("current", "previous")


def dates(start, end):
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def ratio(numerator, denominator):
    return round(float(Decimal(numerator) / Decimal(denominator)), 8) if denominator else None


def ads_metrics(sums):
    values = {key: float(sums.get(key, 0)) for key in ADS_FIELDS}
    return dict(values, cpc=ratio(sums.get("cost", 0), sums.get("clicks", 0)),
                cpa=ratio(sums.get("cost", 0), sums.get("conversions", 0)),
                roas=ratio(sums.get("value", 0), sums.get("cost", 0)),
                conversion_per_click=ratio(sums.get("conversions", 0), sums.get("clicks", 0)))


def add_ads(target, group, row):
    for label, field in ADS_FIELDS.items():
        target[group][label] += Decimal(row["metrics"][field])


def archived_day(root, day):
    matches = []
    close = datetime.combine(date.fromisoformat(day) + timedelta(days=1), datetime.min.time(), tzinfo=CN)
    for path in (root / (day + "_" + day)).glob("*.json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            raw = json.load(stream)
        value = raw["value"]
        period = value["period"]
        captured = datetime.fromisoformat(raw["sourceAt"].replace("Z", "+00:00"))
        if (value["start"] == value["end"] == period["start"] == period["end"] == day
                and close <= captured < close + timedelta(days=1)):
            matches.append((captured, path.name, period))
    return min(matches, default=None, key=lambda item: item[:2])


def ads_window(root, days):
    totals = defaultdict(lambda: defaultdict(Decimal))
    campaigns = defaultdict(lambda: defaultdict(Decimal))
    countries = defaultdict(lambda: defaultdict(Decimal))
    unmapped = defaultdict(lambda: defaultdict(Decimal))
    labels = {}
    coverage = {"days": [], "issues": [], "geo_issues": [], "snapshots": []}
    for day in days:
        try:
            snap = archived_day(root, day)
        except (OSError, ValueError, KeyError, TypeError):
            coverage["issues"].append({"date": day, "reason": "invalid_archive"})
            continue
        if not snap:
            coverage["issues"].append({"date": day, "reason": "missing_first_post_close_day_archive"})
            continue
        captured, filename, period = snap
        coverage["snapshots"].append({"date": day, "source_at": captured.isoformat(), "file": filename,
                                      "mapping_version": period.get("game_projection_version")})
        processed = set()
        for account in period["adsAccounts"]:
            account_id = account["customerId"]
            if account_id not in ACCOUNTS:
                continue
            if (account["currency"], account["timezone"]) != ("USD", "Asia/Hong_Kong"):
                coverage["issues"].append({"date": day, "account": account_id, "reason": "unexpected_currency_or_timezone"})
                continue
            if not account["campaign_calculation_complete"] or account["campaign_status"]["status"] not in ("success", "empty"):
                coverage["issues"].append({"date": day, "account": account_id, "reason": "incomplete_campaign_report"})
                continue
            if account_id in processed:
                raise ValueError("duplicate_ads_account")
            processed.add(account_id)
            selected = set()
            seen = set()
            for row in account["calculation_campaigns"]:
                key = (account_id, str(row["campaignId"]))
                if key in seen:
                    raise ValueError("duplicate_ads_campaign")
                seen.add(key)
                name = row["campaignName"]
                mapping = row.get("game_mapping") or {}
                if mapping.get("metric_scope") == "cross_game" and mapping.get("project_game") == "FC27":
                    add_ads(totals, "cross_game", row)
                    continue
                if mapping.get("game") != "FC27":
                    if name.casefold().startswith("fc27-"):
                        add_ads(unmapped, key, row)
                        labels[key] = name
                    continue
                selected.add(key)
                labels[key] = name
                add_ads(totals, "fc_only", row)
                add_ads(campaigns, key, row)
            geo = account["countries"]
            if geo["status"]["status"] not in ("success", "empty") or not geo["status"]["quality"].get("pagination_complete"):
                coverage["geo_issues"].append({"date": day, "account": account_id, "reason": "incomplete_country_report"})
                continue
            for row in geo["rows"]:
                if (str(row["customerId"]), str(row["campaignId"])) in selected:
                    add_ads(countries, row["country"], row)
        if processed:
            coverage["days"].append(day)
        if processed != ACCOUNTS:
            coverage["issues"].append({"date": day, "missing_accounts": sorted(ACCOUNTS - processed)})
    coverage["requested_days"] = days
    coverage["geography_cost_coverage"] = ratio(sum(v["cost"] for v in countries.values()), totals["fc_only"]["cost"])
    return {"coverage": coverage, "totals": totals, "campaigns": campaigns, "countries": countries,
            "unmapped": unmapped, "labels": labels}


def series(left, right, describe, normalize, weight, complete=(False, False)):
    data = []
    for key in left.keys() | right.keys():
        label, extra = describe(key)
        data.append({"key": "/".join(key) if isinstance(key, tuple) else key, "label": label,
                     "current": normalize(left[key]) if key in left else normalize({}) if complete[0] else None,
                     "previous": normalize(right[key]) if key in right else normalize({}) if complete[1] else None,
                     **extra})
    return sorted(data, key=lambda row: (-max((row[window] or {}).get(weight, 0) or 0 for window in WINDOWS),
                                         row["key"]))


def paid_packet(root, days):
    current, previous = [ads_window(root, days[window]) for window in WINDOWS]
    both = (current, previous)
    cover = {window: data["coverage"] for window, data in zip(WINDOWS, both)}
    complete = tuple(bool(data["coverage"]["days"]) and not data["coverage"]["issues"] for data in both)

    def campaign(key):
        return current["labels"].get(key) or previous["labels"][key], {"account": key[0], "campaign_id": key[1]}

    def metrics(data, key):
        return ads_metrics(data["totals"][key]) if data["coverage"]["days"] else None

    return {
        "status": "complete" if all(complete) else "partial" if any(c["days"] for c in cover.values()) else "unavailable",
        "source": "Google Ads · FS MMOEXP archived daily snapshot",
        "scope": "三个 USD 账户中确认映射为 FC27 的专属系列，跨游戏 PMAX 另列",
        "archive_policy": "earliest_snapshot_in_first_source_day_after_close",
        "currency": "USD", "time_zone": "Asia/Hong_Kong", "coverage": cover,
        "current": metrics(current, "fc_only"), "previous": metrics(previous, "fc_only"),
        "cross_game": {"label": "FC27-PMAX-Coins-US · 跨游戏",
                       "current": metrics(current, "cross_game"), "previous": metrics(previous, "cross_game")},
        "campaigns": series(current["campaigns"], previous["campaigns"], campaign, ads_metrics, "cost", complete),
        "countries": series(current["countries"], previous["countries"], lambda key: (key, {}),
                            ads_metrics, "cost"),
        "unmapped_named_campaigns": series(current["unmapped"], previous["unmapped"], campaign,
                                          ads_metrics, "cost", complete),
    }


def ga_filter(field, expression, match="FULL_REGEXP"):
    return {"filter": {"fieldName": field,
                       "stringFilter": {"matchType": match, "value": expression, "caseSensitive": False}}}


def ga_metrics(values):
    numbers = {k: int(values.get(k, 0)) for k in GA_FIELDS}
    return dict(numbers, purchase_rate=ratio(numbers["purchases"], numbers["sessions"]))


def ga_report(reader, start, end, dims):
    body = {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "dimensions": [{"name": key} for key in dims],
        "metrics": [{"name": source} for source in GA_FIELDS.values()],
        "dimensionFilter": {"andGroup": {"expressions": [
            ga_filter("hostName", r"(?:www[.])?mmoexp[.]com"),
            ga_filter("landingPage", FC_PATH),
            ga_filter("sessionDefaultChannelGroup", "Organic Search", "EXACT"),
        ]}},
        "limit": 10000,
    }
    rows = {}
    for offset in range(0, 50000, body["limit"]):
        raw = reader.request("ga4", GA_URL, dict(body, offset=offset))
        for row in raw.get("rows", []):
            key = tuple(value["value"] for value in row.get("dimensionValues", []))
            if len(key) != len(dims) or key in rows:
                raise ValueError("invalid_ga4_dimensions")
            rows[key] = ga_metrics({name: value["value"] for name, value in zip(GA_FIELDS, row["metricValues"])})
        if len(rows) >= raw.get("rowCount", 0):
            break
        if not raw.get("rows"):
            break
    meta = raw.get("metadata", {})
    quality = {key: meta[key] for key in ("subjectToThresholding", "dataLossFromOtherRow", "samplingMetadatas") if meta.get(key)}
    quality.update({"pagination_complete": len(rows) == raw.get("rowCount", 0), "time_zone": meta.get("timeZone")})
    return rows, quality


def ga_window(reader, days):
    result = {"coverage": {"reports": {}, "requested_days": days}}
    for key, dims in (("total", []), ("daily", ["date"]), ("countries", ["country"]),
                      ("landing_pages", ["landingPage"]), ("country_pages", ["country", "landingPage"])):
        try:
            rows, quality = ga_report(reader, days[0], days[-1], dims)
        except (OSError, ImportError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            result["coverage"]["reports"][key] = {"error": source_error(exc)}
            continue
        result["coverage"]["reports"][key] = quality
        result[key] = rows
    present = {datetime.strptime(d, "%Y%m%d").date().isoformat() for (d,) in result.get("daily", {})}
    result["coverage"]["observed_days"] = sorted(present)
    result["coverage"]["missing_days"] = sorted(set(days) - present)
    return result


def source_error(exc):
    code = str(exc)
    return code if re.fullmatch("[A-Z_0-9]{1,60}", code) else type(exc).__name__


def numeric_series(current, previous, key, weight, labels=None):
    def flatten(data):
        return {"/".join(keys) if len(keys) > 1 else keys[0]: values for keys, values in data.get(key, {}).items()}
    return series(flatten(current), flatten(previous), labels or (lambda key: (key, {})), dict, weight)


def ga_packet(reader, days):
    current, previous = [ga_window(reader, days[window]) for window in WINDOWS]
    cover = {window: data["coverage"] for window, data in zip(WINDOWS, (current, previous))}
    complete = all(not c["missing_days"] and all(r.get("pagination_complete") and r.get("time_zone") == "Asia/Shanghai" and len(r) == 2
                   for r in c["reports"].values()) for c in cover.values())
    return {
        "status": "complete" if complete else "partial" if any("total" in d for d in (current, previous)) else "unavailable",
        "source": "GA4 Data API · 541418940",
        "scope": "MMOEXP 主站 FC27 路径自然搜索落地；包括各已匹配语言目录",
        "time_zone": "Asia/Shanghai", "coverage": cover, "page_filter": FC_PATH,
        "current": current.get("total", {}).get(()), "previous": previous.get("total", {}).get(()),
        "countries": numeric_series(current, previous, "countries", "sessions"),
        "landing_pages": numeric_series(current, previous, "landing_pages", "sessions"),
        "country_pages": numeric_series(current, previous, "country_pages", "sessions",
                                         lambda key: (key, {})),
    }


def gsc_report(reader, start, end, dims, filtered=True):
    body = {"startDate": start, "endDate": end, "dimensions": dims, "type": "web",
            "dataState": "final", "rowLimit": 10000}
    if filtered:
        body.update({"aggregationType": "byPage", "dimensionFilterGroups": [{"filters": [
            {"dimension": "page", "operator": "includingRegex",
             "expression": r"(?i)^https?://(?:www[.])?mmoexp[.]com" + FC_PATH + "$"}
        ]}]})
    rows = {}
    complete = False
    for offset in range(0, 50000, body["rowLimit"]):
        raw = reader.request("gsc", GSC_URL, dict(body, startRow=offset))
        page = raw.get("rows", [])
        for row in page:
            keys = tuple(row.get("keys", []))
            if len(dims) != len(keys) or keys in rows:
                raise ValueError("INVALID_GSC_DIMENSIONS")
            rows[keys] = {key: row[key] for key in GSC_FIELDS}
        if len(page) < body["rowLimit"]:
            complete = True
            break
    return rows, complete


def gsc_window(reader, days):
    data = {"coverage": {"compared_days": days, "reports": {}}}
    if days:
        for key, dims in (("total", []), ("landing_pages", ["page"]), ("countries", ["country"])):
            try:
                rows, complete = gsc_report(reader, days[0], days[-1], dims)
                data[key] = rows
                data["coverage"]["reports"][key] = {
                    "pagination_complete": complete, "top_rows_only": bool(dims)}
            except (OSError, ImportError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                data["coverage"]["reports"][key] = {"error": source_error(exc)}
    return data


def search_packet(reader, days):
    current_days, prev_days = days["current"], days["previous"]
    final_site = {}
    error = None
    try:
        final_site, complete_dates = gsc_report(reader, prev_days[0], current_days[-1], ["date"], filtered=False)
        if not complete_dates:
            error = "DATE_COVERAGE_PAGINATION_INCOMPLETE"
    except (OSError, ImportError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        error = source_error(exc)
    final = {key[0] for key in final_site}
    # Only compare matching offsets from contiguous final days in both periods.
    compared = 0
    for left, right in zip(current_days, prev_days):
        if left not in final or right not in final:
            break
        compared += 1
    current, previous = [gsc_window(reader, days[window][:compared]) for window in WINDOWS]
    coverage = {window: dict(data["coverage"], requested_days=days[window],
                             final_days=[d for d in days[window] if d in final])
                for window, data in zip(WINDOWS, (current, previous))}
    coverage["date_report_error"] = error
    coverage["latest_final_day_in_probe"] = max(final, default=None)
    status = "unavailable"
    if compared:
        status = ("complete" if not error and compared == len(current_days) and all(
            all(r.get("pagination_complete") for r in v["coverage"]["reports"].values())
            for v in (current, previous)) else "partial")
    def page_label(url):
        return urlsplit(url).path, {"url": url}

    return {
        "status": status, "source": "Google Search Console API · sc-domain:mmoexp.com · Web · final",
        "scope": "MMOEXP 主站 FC27 路径，Google 自然搜索",
        "time_zone": "America/Los_Angeles", "coverage": coverage, "page_filter": FC_PATH,
        "current": current.get("total", {}).get(()), "previous": previous.get("total", {}).get(()),
        "landing_pages": numeric_series(current, previous, "landing_pages", "clicks", page_label),
        "countries": numeric_series(current, previous, "countries", "clicks"),
    }


def channel_packet(periods, site_id, responses):
    """Normalize complete /channels pages returned by the authenticated FS connector."""
    cover = {}
    grouped = {}
    labels = {}
    totals = {}
    complete = True
    for window in WINDOWS:
        raw = responses.get(window) or {}
        context = raw.get("data_context", {}).get("", {})
        scope = context.get("effective_scope") or {}
        view = raw.get("response_view", {})
        expected = dict(periods[window], site_id=site_id, gid="1327", status="all", channel="all")
        if (raw.get("status_code") != 200 or not view.get("value_complete") or view.get("next_offset") is not None
                or scope != expected or not isinstance(raw.get("data"), list)):
            cover[window] = {"status": "unavailable", "error": raw.get("error") or "invalid_scope_or_page"}
            complete = False
            continue
        coverage = context["coverage"]
        grouped[window] = {}
        for row in raw["data"]:
            channel = row["channel"]
            if channel in grouped[window]:
                raise ValueError("duplicate_effective_channel")
            labels[channel] = row["label"]
            grouped[window][channel] = {
                "orders": row["orders"], "sales_usd": float(Decimal(row["admin_paid_usd"])),
                "order_share": row["order_share"], "conflict_orders": row["conflict_orders"],
                "missing_sales_orders": row["missing_admin_usd_orders"],
            }
        rows = list(grouped[window].values())
        totals[window] = {"orders": sum(r["orders"] for r in rows),
                          "sales_usd": round(sum(r["sales_usd"] for r in rows), 2),
                          "missing_sales_orders": sum(r["missing_sales_orders"] for r in rows)}
        cover[window] = {**coverage, "effective_scope": scope, "snapshot_id": context.get("snapshot_id"),
                         "captured_at": context.get("captured_at"),
                         "attribution_revision": context.get("revisions", {}).get("attribution"),
                         "effective_attribution": context.get("revisions", {}).get("effective_attribution")}
        if (coverage.get("missing_days") or coverage.get("unlinked_attribution_rows")
                or coverage.get("unlinked_admin_rows") or totals[window]["missing_sales_orders"]):
            complete = False
    return {
        "status": "complete" if complete else "partial" if grouped else "unavailable",
        "source": "FS channels.facts · 有效归因",
        "scope": "FC27 全站" if site_id == "all" else "FC27 MMOEXP 主站",
        "site_id": site_id, "time_zone": "Asia/Shanghai", "currency": "USD", "time_basis": "Admin paytime",
        "coverage": cover, **{window: totals.get(window) for window in WINDOWS},
        "channels": series(grouped.get("current", {}), grouped.get("previous", {}),
                           lambda key: (labels[key], {}), dict, "sales_usd"),
    }


def collect_traffic(reader, periods, archive_root=FS_MARKETING):
    days = {window: dates(*periods[window]) for window in WINDOWS}
    if (not all(days.values()) or len(days["current"]) != len(days["previous"])
            or days["current"][0] <= days["previous"][-1]
            or periods["current"][1] >= datetime.now(CN).date()):
        raise ValueError("Expected equal-length, nonoverlapping, closed periods in Shanghai time")
    return {
        "periods": {window: {"start": values[0], "end": values[-1]} for window, values in days.items()},
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "paid": paid_packet(archive_root, days), "organic": ga_packet(reader, days), "search": search_packet(reader, days),
        "orders": {"status": "unavailable", "source": "FS channels.facts",
                   "scope": "FC27 已付款订单有效归因；由业务事实入口独立读取",
                   "coverage": {}, "channels": []},
        "limitations": [
            "Google Ads 按互动日选各日结束后首个自然日的最早快照，以相近归因年龄对照。晚归因可能回补。广告价值和 ROAS 采用 Google 归因，实付订单另看 FS。",
            "GA4 购买事件 ÷ 会话是事件密度，订单成交率与真实获客成本需要会话和订单的有效关联。",
            "GSC、GA4 和 Ads 各沿来源时区。GSC 仅比较同位置的已完成日期，页面与国家明细遵循 Google 可返回的 Top 行。",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("start", "end", "previous-start", "previous-end"):
        parser.add_argument("--" + field, required=True, type=date.fromisoformat)
    args = parser.parse_args()
    sys.path.insert(0, READER_PATH)
    from collect_details import Reader
    reader = Reader()
    try:
        packet = collect_traffic(reader, {"current": (args.start, args.end),
                                          "previous": (args.previous_start, args.previous_end)})
    finally:
        reader.close()
    print(json.dumps(packet, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

