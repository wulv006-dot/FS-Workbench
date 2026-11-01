"""Synthetic preview only: never inspects production or accepts an apply switch."""
import argparse,hashlib,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from eviction_policy import CHECKS,dry_run


def run():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);raw=b'{"synthetic":true}';ident=hashlib.sha256(raw).hexdigest();path=root/(ident+'.data.json');path.write_bytes(raw)
        item=dict(path=str(path),object_id=ident,dataset_id='fixture.orders',scope_hash='fixture-scope',source_contract='fixture-source',classification='L1',active_job=False,mode='fresh',expires_at=1,start='2026-10-01',end_exclusive='2026-10-02',fields=['order_id'],proof_id='synthetic-only')
        proof=dict(proof_id='synthetic-only',evidence_kind='synthetic',evidence_sha256='0'*64,verified=True,mode='current_state',dataset_id='fixture.orders',scope_hash='fixture-scope',source_contract='fixture-source',start='2026-10-01',end_exclusive='2026-10-02',fields=['order_id'],stable_key='order_id',checks={key:True for key in CHECKS})
        policy=dict(contract='fs-cache-eviction-dryrun-v1',policy_id='fixture-not-production',roots=[str(root)],datasets=['fixture.orders'],quarantine_days=7,max_object_bytes=1000,max_batch_bytes=1000)
        refs=dict(complete=True,epoch='fixture-epoch',pins={ident:0},references=[])
        result=dry_run([item],policy,{'synthetic-only':proof},lambda dataset:refs,now=2,fixture=True)
        result.update(synthetic=True,production_proof=False,protected_file_preserved=path.read_bytes()==raw)
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',required=True,choices=['synthetic']);parser.add_argument('--dry-run',action='store_true',required=True)
    parser.add_argument('--report',help='Optional JSON basename in current local working directory')
    args=parser.parse_args();result=run();text=json.dumps(result,indent=2)
    if args.report:
        name=Path(args.report)
        if name.name!=args.report or name.suffix!='.json':parser.error('report must be a local JSON basename')
        name.write_bytes((text+'\n').encode())
    print(text)
