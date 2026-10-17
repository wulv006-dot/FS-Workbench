"""Project a successful ES baseline into an exact learning stage, no publication."""
import argparse,hashlib,json,re,shutil
from pathlib import Path
from prepare_learning import check,TARGETS
from learning_bridge import BASE_SHA

def verify_receipt(es,raw,receipt,commit,operation):
    if es.get('releaseReady') is not True or receipt.get('sourceCommit')!=es.get('sourceCommit') or es.get('sourceCommit')!=commit:raise ValueError('es_receipt_commit_mismatch')
    if not re.fullmatch(r'nav-\d{8}T\d{6}Z',operation or '') or any(receipt.get(k)!=operation for k in ('operation','releaseID','releaseId')) or receipt.get('backup')!='/var/backups/fs-navigation-20261006/'+operation:raise ValueError('es_receipt_operation_mismatch')
    if receipt.get('executionManifestSha256')!=hashlib.sha256(raw).hexdigest() or receipt.get('session_ready') is not True or receipt.get('protected_verified') is not True or receipt.get('business_health') is not True:raise ValueError('es_success_evidence_required')
    for key,expected in [('readback',{r['target']:r['sha256'] for r in es['files']}),('protected_readback',{r['path']:r['sha256'] for r in es['unchangedRequired']})]:
        rows=receipt.get(key,[])
        if len(rows)!=len(expected) or {r['target']:r['sha256'] for r in rows}!=expected:raise ValueError('es_exact_readback_required')
    if receipt.get('targets')!=len(es['files']) or receipt.get('protected')!=len(es['unchangedRequired']):raise ValueError('es_receipt_count_mismatch')

def prepare(private,es_manifest,base_path,out,commit,receipt=None,operation=None):
    private=Path(private);out=Path(out);m=check(private)
    if out.exists():raise ValueError('new_output_required')
    if len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):raise ValueError('frozen_commit_required')
    es_raw=Path(es_manifest).read_bytes();es=json.loads(es_raw)
    known={r['path']:r['sha256'] for r in es['unchangedRequired']};known.update({r['target']:r['sha256'] for r in es['files']})
    for r in m['files']:
        if r['beforeSha256'] is not None and known.get(r['target'],r['beforeSha256'])!=r['beforeSha256']:raise ValueError('post_es_learning_baseline_drift')
    if receipt is not None:
        receipt=json.loads(Path(receipt).read_text(encoding='utf8'))
        verify_receipt(es,es_raw,receipt,commit,operation)
    raw=Path(base_path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BASE_SHA:raise ValueError('frozen_base_required')
    out.mkdir(parents=True);(out/'candidate').mkdir()
    files=[]
    for r in m['files']:
        rel='learning/'+Path(r['candidate']).name;p=out/'candidate'/rel;p.parent.mkdir(exist_ok=True);shutil.copyfile(private/r['candidate'],p)
        files.append(dict(r,candidate=rel))
    approved=dict(imageId=es['imageId'],schemaVersion=1,scope='hermes-private-learning-20261017-v1',releaseReady=receipt is not None,sourceCommit=commit,files=files,unchangedRequired=[dict(path=p,sha256=s) for p,s in sorted(known.items()) if p not in TARGETS],runtimeRequired=es['runtimeRequired'],businessWrites=False,timersChanged=False,modelChanged=False,budgetChanged=False,baselinePending=receipt is None)
    data=(json.dumps(approved,ensure_ascii=False,indent=2)+'\n').encode();(out/'approved-manifest.json').write_bytes(data)
    (out/'release_navigation_base.py').write_bytes(raw)
    bridge=Path(__file__).with_name('learning_bridge.py').read_text(encoding='utf8').replace('PREPARE_REPLACES_THIS',hashlib.sha256(data).hexdigest())
    (out/'learning_bridge.py').write_text(bridge,encoding='utf8',newline='\n')
    return approved

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('private','es-manifest','base','output','commit'):p.add_argument('--'+n,required=True)
    p.add_argument('--receipt');p.add_argument('--operation');a=p.parse_args();m=prepare(a.private,a.es_manifest,a.base,a.output,a.commit,a.receipt,a.operation)
    print(json.dumps(dict(targets=len(m['files']),protected=len(m['unchangedRequired']),releaseReady=m['releaseReady'])))
