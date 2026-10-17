"""Prepare an inspect-only four-file scope with controller and collector deltas."""
import argparse,hashlib,json,shutil
from pathlib import Path
import controller_patch as bridge

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def prepare(repo,successful_stage,output,commit):
    repo=Path(repo);successful_stage=Path(successful_stage);output=Path(output)
    if output.exists():raise ValueError('new_stage_required')
    baseline=json.loads((successful_stage/'approved-manifest.json').read_text('utf-8'))
    rows={r['target']:r for r in baseline['files']}
    base=bridge.load_base();output.mkdir(parents=True,mode=0o700)
    release=repo/'releases/fs-dashboard/traffic-hermes-20261017';files=[]
    for candidate,target in base.HERMES_HISTORY_TARGETS.items():
        row=rows[target];source=successful_stage/'candidate'/row['candidate']
        if sha(source)!=row['sha256']:raise ValueError('successful_stage_source_drift')
        if target==bridge.CONTROLLER:source=release/'source/controller.py'
        if target==bridge.COLLECTOR:source=repo/'mmoexp_google_data/details/collect_details.py'
        dest=output/'candidate'/candidate;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
        files.append({'candidate':candidate,'target':target,'sha256':sha(dest),'beforeSha256':row['sha256']})
    protected={r['path']:r['sha256'] for r in baseline['unchangedRequired']}
    protected.update({target:row['sha256'] for target,row in rows.items() if target not in base.HERMES_HISTORY_TARGETS.values()})
    publisher=output/'publisher';publisher.mkdir()
    for name in ('controller_patch.py','release_navigation_base.py'):shutil.copyfile(release/'publisher'/name,publisher/name)
    manifest={k:v for k,v in baseline.items() if k in ('schemaVersion','imageId','runtimeRequired','absenceRequired')}
    manifest.update(scope=base.HERMES_HISTORY_SCOPE,releaseReady=False,businessWrites=False,timersChanged=False,nightlyChanges=False,sourceCommit=commit,basePublisherSha256=bridge.BASE_SHA,controllerBridgeSha256=sha(publisher/'controller_patch.py'),files=files,unchangedRequired=[{'path':p,'sha256':v} for p,v in sorted(protected.items())],controllerProtectedBaseline=protected,baselinePending=[])
    base.validate(manifest,output)
    (output/'approved-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--successful-stage',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--source-commit',required=True);a=p.parse_args();m=prepare(a.repo,a.successful_stage,a.output,a.source_commit);print(json.dumps({'releaseReady':m['releaseReady'],'files':len(m['files']),'protected':len(m['unchangedRequired'])}))
