"""Build four exact report-input deltas from successful backend/followup/UI receipts, never old baselines."""
import argparse,hashlib,json,re,shutil
from pathlib import Path
import report_inputs_patch as bridge
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def load_stage(stage,manifest_name,rows_key):
    stage=Path(stage);manifest=json.loads((stage/manifest_name).read_text(encoding='utf8'))
    for row in manifest[rows_key]:
        source=stage/('candidate/'+row['candidate'] if rows_key=='files' else row['candidate'])
        if sha(source)!=row['sha256']:raise ValueError('successful_stage_source_drift: '+row['target'])
    return manifest

def prepare(repo,backend_stage,followup_stage,ui_stage,receipt,output,commit):
    repo=Path(repo);backend_stage=Path(backend_stage);followup_stage=Path(followup_stage);output=Path(output)
    if output.exists():raise ValueError('new_stage_required')
    if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('source_commit_required')
    first=load_stage(backend_stage,'approved-manifest.json','files');last=load_stage(followup_stage,'approved-manifest.json','files');ui=load_stage(ui_stage,'release-manifest.json','immutableAssets')
    for row in ui['targets']:
        if sha(Path(ui_stage)/row['candidate'])!=row['sha256']:raise ValueError('successful_ui_source_drift')
    if ui.get('releaseId')!='workspace-native-20261006-e0654eaced60' or receipt.get('sourceCommit')!=last['sourceCommit'] or receipt.get('ui_backup','').split('/')[-1]!=ui['releaseId'] or receipt.get('nginx')!='passed' or receipt.get('session_ready') is not True:raise ValueError('latest_receipt_required')
    base=bridge.load_base();known={};sources={}
    for stage,manifest in [(backend_stage,first),(followup_stage,last)]:
        known.update({r['path']:r['sha256'] for r in manifest['unchangedRequired']})
        for row in manifest['files']:known[row['target']]=row['sha256'];sources[row['target']]=stage/'candidate'/row['candidate']
    known.update({r['path']:r['sha256'] for r in ui['unchangedRequired']})
    known.update({r['target']:r['sha256'] for r in ui['immutableAssets']+ui['targets']})
    targets=base.HERMES_HISTORY_TARGETS;release=repo/'releases/fs-dashboard/traffic-hermes-20261017';payload=[]
    for candidate,target in targets.items():
        if target not in known:raise ValueError('missing_current_baseline: '+target)
        source=release/'source'/('source_snapshots_daily_window.py' if target==bridge.SNAPSHOTS else Path(target).name) if target in bridge.DELTAS else sources[target]
        if target==bridge.SNAPSHOTS and known[target]!='da8ca17d739bbc2a95bf6a21510eefda06b2e2f44eabab33c26278886634a277':raise ValueError('source_snapshots_activity_drift')
        if target not in bridge.DELTAS and sha(source)!=known[target]:raise ValueError('current_history_source_drift')
        if sha(source)!=bridge.EXPECTED_SHA[target]:raise ValueError('exact_report_input_source_sha_required: '+target)
        payload.append((candidate,target,source,known[target]))
    output.mkdir(mode=0o700,parents=True);files=[]
    for candidate,target,source,before in payload:
        dest=output/'candidate'/candidate;dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True);shutil.copyfile(source,dest);files.append({'candidate':candidate,'target':target,'sha256':sha(dest),'beforeSha256':before})
    protected={p:h for p,h in known.items() if p not in set(targets.values())};publisher=output/'publisher';publisher.mkdir(mode=0o700)
    for name in ('report_inputs_patch.py','release_navigation_base.py'):shutil.copyfile(release/'publisher'/name,publisher/name)
    manifest={k:v for k,v in last.items() if k in ('schemaVersion','imageId','runtimeRequired','absenceRequired')}
    manifest.update(scope=base.HERMES_HISTORY_SCOPE,releaseReady=False,businessWrites=False,timersChanged=False,nightlyChanges=False,sourceCommit=commit,basePublisherSha256=bridge.BASE_SHA,reportInputsBridgeSha256=sha(publisher/'report_inputs_patch.py'),files=files,unchangedRequired=[{'path':p,'sha256':h} for p,h in sorted(protected.items())],reportProtectedBaseline=protected,baselinePending=[])
    base.validate(manifest,output);(output/'approved-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8');return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--backend-stage',required=True);p.add_argument('--followup-stage',required=True);p.add_argument('--ui-stage',required=True);p.add_argument('--receipt',required=True);p.add_argument('--output',required=True);p.add_argument('--source-commit',required=True);a=p.parse_args();m=prepare(a.repo,a.backend_stage,a.followup_stage,a.ui_stage,json.loads(Path(a.receipt).read_text(encoding='utf8')),a.output,a.source_commit);print(json.dumps({'releaseReady':m['releaseReady'],'files':len(m['files']),'protected':len(m['unchangedRequired'])}))
