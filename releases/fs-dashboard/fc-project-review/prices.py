"""Read actual site 266 tier confirmations. Run with the existing authorized ledger reader."""
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import sqlite3
from statistics import median

TZ = timezone(timedelta(hours=8))


def confirmed(db, start, end):
    if start > end:
        raise ValueError("invalid date interval")
    windows = defaultdict(list)
    for (raw,) in db.execute("SELECT body FROM actual_price_windows"):
        window = json.loads(raw)
        stamp = datetime.fromisoformat(window["opened_at"].replace("Z", "+00:00")).astimezone(TZ)
        if not start <= stamp.date() <= end:
            continue
        for platform, proof in window.get("curve_confirmations", {}).items():
            if proof.get("basis") != "full_prices_and_tier_specs_readback":
                continue
            windows[(proof.get("operation_id"),platform)].append(stamp)
    prices = defaultdict(list)
    for (operation_id, platform), stamps in windows.items():
        row = db.execute("SELECT body FROM operations WHERE id=?", (operation_id,)).fetchone()
        if not row:
            continue
        proof = json.loads(row[0]).get("readback", {}).get("curve_results", {}).get(platform, {})
        curve = proof.get("actual_site266_curve", {})
        if str(curve.get("identity", {}).get("site_id")) != "266":
            continue
        for tier in curve.get("tiers", []):
            quantity = Decimal(tier["purchase_k"])
            if quantity in (100, 1000):
                prices[(platform,int(quantity))].append(float(tier["native_price_usd"]))
    return [dict(platform=p, purchaseK=q, observations=len(values), minUsd=min(values),
                 medianUsd=round(median(values),4), maxUsd=max(values)) for (p,q),values in sorted(prices.items())]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("start", type=date.fromisoformat)
    parser.add_argument("end", type=date.fromisoformat)
    args = parser.parse_args()
    db = sqlite3.connect("file:/var/lib/fc27-cloud/v3/control.sqlite3?mode=ro", uri=True)
    try:
        print(json.dumps(dict(start=str(args.start), end=str(args.end), scope="site266",
                              basis="confirmed native price per distinct operation and platform; observed inside interval",
                              tiers=confirmed(db,args.start,args.end))))
    finally:
        db.close()
