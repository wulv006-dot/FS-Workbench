"""FC project review: exact-window source reads and reusable aggregate packets."""
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import http.client
import json
import os
from pathlib import Path
import tempfile
import time

GAMES = {"FC26": ("833", "824"), "FC27": ("1327", "1322")}
TZ = timezone(timedelta(hours=8))


def interval(game, start, end):
    lo, hi = map(date.fromisoformat, (start, end))
    first = date(2025 if game == "FC26" else 2026, 9, 1)
    last = min(datetime.now(TZ).date(), date(2026, 9, 30)) if game == "FC26" else datetime.now(TZ).date()
    if not first <= lo <= hi <= last:
        raise ValueError("日期超出所选项目的期间")
    return [(lo + timedelta(days=i)).isoformat() for i in range((hi-lo).days+1)]


def request_plan(game, start, end):
    interval(game, start, end)
    args = dict(profile=game, start=start, end=end, profit_site="all", profit_basis="shipping")
    return {name: dict(operation=operation, arguments=args, data_path=path) for name, operation, path in (
        ("filters", "business.summary", "/profile/supplement/filters"),
        ("scope", "business.summary", "/profile/supplement/effective_scope"),
        ("capturedAt", "business.summary", "/profile/supplement/capturedAt"),
        ("metrics", "business.summary", "/profile/supplement/metrics"),
        ("rows", "business.summary", "/profile/supplement/rows"),
        ("countries", "business.summary", "/profile/supplement/dimensions/countries"),
        ("payments", "business.summary", "/profile/supplement/dimensions/payments"),
        ("shipping", "business.profit_history", "/history/daily"))}


def rpc(name, arguments):
    token = os.environ.get("FS_REVIEW_ACCESS_TOKEN")
    if not token:
        raise ValueError("当前命令行没有已授权的 FS 访问令牌。已连接的 AI 请使用 requests 导出的参数调用 FS 工具。")
    conn = http.client.HTTPSConnection("47.85.224.112", timeout=40)
    try:
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        conn.request("POST", "/connector/mcp", json.dumps(msg).encode(), {
            "Authorization": "Bearer " + token, "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"})
        res = conn.getresponse()
        if res.status != 200:
            raise ValueError(f"FS HTTP {res.status}")
        payload = json.load(res)
        if "error" in payload:
            raise ValueError("FS 拒绝此调用")
        return json.loads(payload["result"]["content"][0]["text"])
    finally:
        conn.close()


def read_node(request):
    offset, parts, total = 0, [], None
    while True:
        result = rpc("fs_query_data", dict(request, offset=offset, limit=20))
        if result.get("status_code") != 200 or "data" not in result:
            raise ValueError(f'{request["operation"]} {request["data_path"]}: {result.get("status_code")} {result.get("error","未就绪")}')
        data, view = result["data"], result.get("response_view", {})
        if view.get("kind") == "index":
            raise ValueError("需要展开源字段")
        if view.get("kind") != "page":
            return data
        if total is None:
            total = view["total"]
        if total != view["total"] or view["offset"] != offset:
            raise ValueError("分页期间源数据改变")
        parts.extend(data)
        if view.get("next_offset") is None:
            if len(parts) != total:
                raise ValueError("源分页不完整")
            return parts
        if view["next_offset"] <= offset:
            raise ValueError("游标未前进")
        offset = view["next_offset"]


def fetch(game, start, end):
    plan = request_plan(game, start, end)
    rpc("fs_list_data_sources", {"module": "unified-business"})
    # The upstream can first return a derived partial archive or HTTP 202.
    for operation in ("business.summary", "business.profit_history"):
        for _ in range(15):
            result = rpc("fs_query_data", {"operation": operation, "arguments": plan["metrics"]["arguments"]})
            code = result.get("status_code")
            if code == 200 and result.get("data", {}).get("archive", {}).get("nativeStatus") != "pending":
                break
            if code not in (200, 202):
                raise ValueError(f"{operation}: {code}")
            time.sleep(2)
        else:
            raise ValueError(f"{operation} 仍在排队，可按原参数续查")
    nodes = {key: read_node(value) for key, value in plan.items()}
    shipping = nodes.pop("shipping")
    nodes["dimensions"] = {k: nodes.pop(k) for k in ("countries","payments")}
    return {"schema": 1, "game": game, "start": start, "end": end, "scope": "all",
            "admin": nodes, "shipping": shipping, "source": "FS business.summary + business.profit_history"}


def ratio(numerator, denominator, factor=1):
    return round(numerator * factor / denominator, 4) if numerator is not None and denominator else None


def money(value):
    return Decimal(str(value))


def packet(core):
    game, start, end = (core[k] for k in ("game", "start", "end"))
    dates = interval(game, start, end)
    admin = core["admin"]
    filters, scope = admin["filters"], admin["scope"]
    bounds = [start + " 00:00", (date.fromisoformat(end) + timedelta(days=1)).isoformat() + " 00:00"]
    now = datetime.now(TZ)
    actual = filters.get("date", [])
    if end == now.date().isoformat() and len(actual)==2:
        cutoff = datetime.strptime(actual[1], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        if cutoff.date()==now.date() and cutoff<=now and scope.get("period",{}).get("end")==actual[1]:
            bounds[1]=actual[1]
    if (core["scope"] != "all" or scope.get("site") != "all" or scope.get("country_code") != "all"
            or filters.get("site") != "" or str(filters.get("game")) != GAMES[game][0]
            or filters.get("date") != bounds or filters.get("pay_status") != 1
            or any(filters.get(k) for k in ("product_type","cid","client","discount_code","country_code","pay_type","order_status"))):
        raise ValueError("Admin 日期、已付款条件、游戏或全站范围不符")
    metrics = {k: v.get("value") if v.get("status") == "available" else None for k, v in admin["metrics"].items()}
    revenue, orders = metrics["revenueUsd"], metrics["orders"]
    buyers, new = metrics.get("payingCustomers"), metrics.get("newCustomers")
    coverage = []
    if end == now.date().isoformat():
        coverage.append("当日付款截至 "+bounds[1]+"，发货日结数据待闭日")
    sales, counts, seen = defaultdict(Decimal), defaultdict(int), set()
    for row in admin["rows"]:
        label = row["date"]
        day = label[:10]
        if day not in dates or label in seen:
            raise ValueError("Admin 逐时/日数据重复或超出窗口")
        seen.add(label)
        sales[day] += money(row["amount"])
        counts[day] += row["orders"]
    if revenue is None or orders is None or sum(sales.values()) != money(revenue) or sum(counts.values()) != orders:
        coverage.append("Admin 明细时段与整段合计未核平，逐日销售暂缺")
        sales.clear()
        counts.clear()
    shipping = {}
    for r in core["shipping"]:
        d = r["date"]
        if d not in dates or d in shipping or r.get("scope", {}).get("sites") != "all-websites" or str(r["scope"].get("orderGameId")) != GAMES[game][1]:
            raise ValueError("Order 发货日期重复或范围错误")
        if r.get("sourceContract") != "order-shipping-v1" or str(r["scope"].get("orderProductType")) != "-1":
            raise ValueError("Order 发货来源或类目不符")
        if r.get("status") == "available" and not r.get("stale") and all(r.get(k) is not None for k in ("salesCny","costCny","profitCny")):
            if abs(money(r["salesCny"])-money(r["costCny"])-money(r["profitCny"])) > Decimal(".01"):
                raise ValueError("Order 发货金额无法核平")
            shipping[d] = r
    daily = []
    for d in dates:
        r = shipping.get(d, {})
        daily.append(dict(date=d, salesUsd=float(sales[d]) if d in sales else None, orders=counts.get(d),
                          profitCny=r.get("profitCny"), shippingSalesCny=r.get("salesCny"), costCny=r.get("costCny"),
                          marginPct=ratio(r.get("profitCny"), r.get("salesCny"), 100),
                          costPct=ratio(r.get("costCny"), r.get("salesCny"), 100)))
    profit = ship_sales = None
    if len(shipping) == len(dates):
        profit = float(sum(money(r["profitCny"]) for r in shipping.values()))
        ship_sales = float(sum(money(r["salesCny"]) for r in shipping.values()))
    else:
        coverage.append("Order 发货统计缺少完整日，整段毛利暂缺")
    share = ratio(new, buyers, 100) if None not in (new, buyers) and 0 <= new <= buyers else None
    kpi = dict(salesUsd=revenue, orders=orders, profitCny=profit, marginPct=ratio(profit,ship_sales,100),
               newCustomers=new, payingCustomers=buyers, newPct=share, returningPct=round(100-share,4) if share is not None else None,
               discountPct=None, aov=ratio(revenue,orders))
    return dict(game=game, start=start, end=end, scope="all", kpi=kpi, daily=daily, coverage=coverage,
                adminDimensions=admin.get("dimensions",{}), capturedAt=admin.get("capturedAt"),
                sources={"sales":"Admin 全站已付款·付款日","profit":"Order 全站发货统计·发货交易日"})


def save(path, data):
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=dest.parent, delete=False, encoding="utf-8") as f:
        try:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        except BaseException:
            f.close()
            os.unlink(f.name)
            raise
    os.replace(f.name, dest)


def enrich(packets, orders=(), traffic=(), prices=(), delivery=()):
    """Join period-matched auxiliary sources only. Each source retains its own coverage."""
    for paths, kind in ((orders,"ordersData"), (traffic,"traffic"), (prices,"prices"), (delivery,"delivery")):
        for path in paths:
            source = json.loads(path.read_text(encoding="utf-8-sig"))
            scope = source["scope"] if kind == "ordersData" else source["periods"]["current"] if kind == "traffic" else source
            for p in packets:
                if (p["start"],p["end"]) != (scope["start"],scope["end"]):
                    continue
                if kind == "ordersData":
                    if p["game"] not in scope.get("games",[]):
                        continue
                    games = [g["game"] for g in source["games"] if g.get("orders") != 0]
                    if scope["site"] != "all" or any(game != p["game"] for game in games):
                        raise ValueError("订单补充含其他游戏或站点")
                    p[kind] = source
                    proof = source.get("discount",{})
                    p["kpi"]["discountPct"] = proof.get("discountPct")
                    if proof.get("status") != "complete":
                        p["coverage"].append(f"优惠率为同单已核子集 {proof.get('coveredOrders',0)}/{proof.get('totalOrders','?')} 笔")
                elif p["game"] == "FC27":
                    if kind == "delivery":
                        p.setdefault("ordersData",{})["delivery"] = source
                    else:
                        p[kind] = source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("requests", "fetch"):
        p = sub.add_parser(name)
        p.add_argument("--game", choices=GAMES, required=True)
        p.add_argument("--start", required=True)
        p.add_argument("--end", required=True)
        if name == "fetch":
            p.add_argument("--output", required=True)
    build = sub.add_parser("build")
    build.add_argument("--core", type=Path, nargs="+", required=True)
    for field in ("orders", "traffic", "prices", "delivery"):
        build.add_argument("--" + field, nargs="+", type=Path, default=[])
    build.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.cmd == "requests":
        print(json.dumps(request_plan(args.game,args.start,args.end), indent=2, ensure_ascii=False))
        return
    if args.cmd == "fetch":
        core = fetch(args.game,args.start,args.end)
        packets = [packet(core)]
        revision = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()
        save(Path(args.output).parent/"sources"/f"{args.game}-{args.start}-{args.end}-{revision}.json", core)
    else:
        packets = [packet(json.loads(f.read_text(encoding="utf-8-sig"))) for f in args.core]
        enrich(packets,args.orders,args.traffic,args.prices,args.delivery)
    first = packets[0]
    save(args.output, {"asOf":max(p["end"] for p in packets), "defaultPeriod":{k:first[k] for k in ("game","start","end")},
                       "packets":packets,"requestCommand":"python review.py requests --game {game} --start {start} --end {end}"})


if __name__ == "__main__":
    main()
