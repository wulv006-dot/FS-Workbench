"""Import verified aggregate packets through the deployed archive writer."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys


def main():
    p=argparse.ArgumentParser()
    p.add_argument("source",type=Path)
    p.add_argument("--sha256",required=True)
    args=p.parse_args()
    raw=args.source.read_bytes()
    if sha256(raw).hexdigest()!=args.sha256:
        raise ValueError("aggregate package checksum changed")
    sys.path.insert(0,"/opt/fs-exact-range-20261001")
    from fc_project_review.api import publish
    packets=json.loads(raw)["packets"]
    keys={(r["game"],r["start"],r["end"],r["scope"]) for r in packets}
    if not packets or len(keys)!=len(packets):raise ValueError("invalid duplicate windows")
    for r in packets:
        if not isinstance(r.get("kpi"),dict) or not isinstance(r.get("daily"),list):
            raise ValueError("invalid review packet")
    for r in packets:
        doc=publish(r)
        print(json.dumps({"game":r["game"],"start":r["start"],"end":r["end"],"revision":doc["revision"]}))


if __name__=="__main__":
    main()
