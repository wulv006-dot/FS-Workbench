"""Overlay only the reviewed range handler on the original, verified 187 sources."""
import argparse
from hashlib import sha256
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
RANGE=HERE.parent/"dashboard-refresh-20261025/source/range_api.py"
DASH=HERE.parent/"fc-detail-analytics-20261012/source/fc_dashboard.py"
BASE={"range_api.py":"6f0e4baee0f98775d74b6a5f3174c92ccea18bfbe96cf577dbbdc83570b8903d",
      "fc_dashboard.py":"d397b19b63546bdeed3ddf75218aced4d75ee920b26a30e91c39325ff845eb3f"}


def prepare(baseline, output):
    for name,digest in BASE.items():
        if sha256((baseline/name).read_bytes()).hexdigest()!=digest:
            raise ValueError(f"Release baseline changed: {name}")
    anchor="  if params.get('mode')==['fc-daily']:"
    start="  if params.get('mode')==['fc-project-review']:"
    source=RANGE.read_text(encoding="utf-8")
    original=(baseline/"range_api.py").read_text(encoding="utf-8")
    if original.count(anchor)!=1 or start in original or source.count(start)!=1 or source.count(anchor)!=1:
        raise ValueError("Active handler mapping changed")
    block=source[source.index(start):source.index(anchor)]
    output.mkdir(parents=True,exist_ok=True)
    (output/"range_api.py").write_bytes(original.replace(anchor,block+anchor).encode())
    for path in [DASH,*(HERE/k for k in ("api.py","review.py","orders.py","traffic.py","prices.py","fulfillment.py"))]:
        shutil.copyfile(path,output/path.name)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("baseline",type=Path)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    prepare(args.baseline,args.output)
