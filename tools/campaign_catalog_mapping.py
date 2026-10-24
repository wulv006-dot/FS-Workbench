"""Build a management-safe persisted catalog mapping artifact from projected GET evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'releases/fs-dashboard/campaign-analytics-20261023/backend'))
from campaign_backend.catalog import build_reference_mappings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed',type=Path,default=ROOT/'docs/planning/activity-center-v3/handoffs/C-CATALOG-SEED-04.json')
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--supplement',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    read=lambda p:json.loads(p.read_text(encoding='utf8'))
    artifact=build_reference_mappings(read(args.seed),read(args.evidence),read(args.supplement) if args.supplement else None)
    artifact['evidence_file_hashes']={name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in
        (('seed',args.seed),('catalog_get',args.evidence),('currency_schema_get',args.supplement)) if p is not None}
    args.out.write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
    print(json.dumps({'summary':artifact['summary'],'mapping_sha256':artifact['mappings_sha256']},sort_keys=True))


if __name__=='__main__':main()
