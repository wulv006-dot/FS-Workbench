"""Read historical delivery timings and paid-queue outcomes using existing 187 sources."""
import argparse
from datetime import date
import json
from pathlib import Path
import subprocess
import sys

LOCK = Path("/var/www/dashboard/fs-home/transactions/collector.lock")


def purchase_projection(scope):
    sys.path.insert(0, "/opt/fs-hermes-fc")
    from shared_es_facts import latest_publication, read

    publication = (latest_publication() or {}).get("publication_id")
    if not publication:
        return {}, None
    result = read(scope, publication_id=publication)
    known = {}
    for row in result.get("rows", []):
        coin = row.get("fc27_coins") or {}
        if not coin.get("purchase_k") or str(row["site_id"]) != "266" or not coin.get("platform"):
            continue
        identity = str(row["order_no"])
        if identity in known:
            raise ValueError("duplicate_es_order_identity")
        known[identity] = {"purchase_k": str(coin["purchase_k"]), "platform": coin["platform"]}
    return known, publication


def browser_program(source, start, end, known, publication):
    return f"""
from datetime import date
import json
from time import monotonic

namespace = {{'__name__': 'fulfillment'}}
exec({source!r}, namespace)
start, end = date.fromisoformat({start!r}), date.fromisoformat({end!r})
deadline = monotonic() + 110
result = namespace['collect'](start, end, deadline=monotonic() + 50)
result['completion'] = namespace['collect_queue'](start, end, {known!r}, {publication!r}, deadline=deadline)
print(json.dumps(result, ensure_ascii=False, allow_nan=False))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("start", "end"):
        parser.add_argument("--" + field, required=True, type=date.fromisoformat)
    args = parser.parse_args()
    if not args.start <= args.end:
        parser.error("expected a closed date window")
    start, end = args.start.isoformat(), args.end.isoformat()
    scope = {"start": start, "end": end, "site_id": "266", "gid": "1327"}
    known, publication = purchase_projection(scope)
    if not LOCK.is_file():
        raise ValueError("existing_order_lock_missing")
    source = globals().get("BROWSER_SOURCE")
    if source is None:
        source = Path(__file__).with_name("fulfillment.py").read_text(encoding="utf-8")
    code = browser_program(source, start, end, known, publication)
    proc = subprocess.run(["flock", "-n", str(LOCK), "timeout", "125", "docker", "exec", "-i",
                           "fc27-cloud-browser", "python3", "-B", "-"], input=code.encode("utf-8"), capture_output=True)
    if proc.returncode:
        raise SystemExit("order fulfillment read failed: " + str(proc.returncode))
    data = json.loads(proc.stdout)
    if (data["start"], data["end"]) != (start, end):
        raise ValueError("invalid_order_fulfillment_period")
    print(json.dumps(data, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
