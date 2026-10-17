"""Prepare an exact, inspect-only V3 stage from the successful 4b release and fresh readback."""
import argparse,hashlib,json,re,shutil
from pathlib import Path
import es_v3_patch as bridge

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def prepare(repo,prior_stage,receipt,baseline,maintenance,output,commit=None):
    repo=Path(repo);prior_stage=Path(prior_stage);output=Path(output)
    if output.exists():raise ValueError('new_stage_required')
    prior=read(prior_stage/'approved-manifest.json')
    if receipt.get('sourceCommit')!=prior['sourceCommit'] or receipt.get('session_ready') is not True or receipt.get('nginx')!='passed':raise ValueError('successful_prior_receipt_required')
    for row in prior['files']:
        if sha(prior_stage/'candidate'/row['candidate'])!=row['sha256']:raise ValueError('prior_stage_drift')
    expected={r['path']:r['sha256'] for r in prior['unchangedRequired']}
    expected.update({r['target']:r['sha256'] for r in prior['files']})
    observed={r['path']:r['sha256'] for r in baseline['files'] if r.get('exists') is True}
    if any(observed.get(p)!=h for p,h in expected.items()):raise ValueError('current_runtime_drift_from_successful_release')
    for contract in maintenance.values():
        for row in contract['files']:
            if row['path'] in observed and observed[row['path']]!=row['sha256']:raise ValueError('unit_readback_drift')
            observed[row['path']]=row['sha256']
    leaf_path=Path(__file__).with_name('es_v3_image_lifecycle.py')
    import es_v3_image_lifecycle as leaf
    if baseline.get('session_image_id')!=leaf.BASE_IMAGE or baseline.get('session_tag')!=leaf.OLD_TAG or receipt.get('container_image')!=leaf.BASE_IMAGE:raise ValueError('current_session_baseline_required')
    if baseline.get('archive_mounts')!=[{'source':leaf.ARCHIVE,'destination':leaf.ARCHIVE,'rw':True}]:raise ValueError('existing_persistent_archive_mount_required')
    if commit is not None and not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('source_commit_required')
    release=repo/'releases/fs-dashboard/traffic-hermes-20261017';payload=[]
    for candidate,target in bridge.TARGETS.items():
        if candidate.endswith('/traffic_contract.py') or candidate=='contract/details/detail_model.py':source=repo/'mmoexp_google_data/details'/Path(candidate).name
        else:
            name='shared_range_es_v3.py' if candidate=='shared/range_api.py' else 'Dockerfile.session.es-v3' if candidate=='session/Dockerfile.session' else 'fc27-p2pah-session-es-v3.service' if candidate.endswith('.service') else Path(candidate).name
            source=release/'source'/name
        if target not in observed or sha(source)!=bridge.EXPECTED_AFTER[target]:raise ValueError('exact_v3_source_or_baseline_missing: '+target)
        payload.append((candidate,target,source,observed[target]))
    output.mkdir(parents=True,mode=0o700);files=[]
    for candidate,target,source,before in payload:
        dest=output/'candidate'/candidate;dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700);shutil.copyfile(source,dest)
        files.append({'candidate':candidate,'target':target,'sha256':sha(dest),'beforeSha256':before})
    publisher=output/'publisher';publisher.mkdir(mode=0o700)
    for name in ('es_v3_patch.py','release_navigation_base.py','es_v3_image_lifecycle.py','marketing_maintenance.py'):shutil.copyfile(release/'publisher'/name,publisher/name)
    protected={p:h for p,h in observed.items() if p not in bridge.TARGETS.values()}
    manifest={k:v for k,v in prior.items() if k in ('schemaVersion','imageId','runtimeRequired','absenceRequired')}
    manifest.update(scope=bridge.SCOPE,releaseReady=False,businessWrites=False,timersChanged=False,nightlyChanges=False,sourceCommit=commit,baselineSourceCommit=prior['sourceCommit'],baselineObservedAt=baseline['observed_at'],basePublisherSha256=bridge.BASE_SHA,publisherBridgeSha256=sha(publisher/'es_v3_patch.py'),imageLifecycleSha256=sha(publisher/'es_v3_image_lifecycle.py'),marketingMaintenanceSha256=sha(publisher/'marketing_maintenance.py'),sessionBaseImage=leaf.BASE_IMAGE,sessionCurrentImage=leaf.BASE_IMAGE,sessionNewTag=leaf.NEW_TAG,marketingStopContract={k:v for k,v in maintenance['fs-marketing-range.service'].items() if k!='files'},businessStopContract={k:v for k,v in maintenance['fs-business-range.service'].items() if k!='files'},files=files,unchangedRequired=[{'path':p,'sha256':h} for p,h in sorted(protected.items())],baselinePending=[] if commit else ['candidate_source_commit_not_frozen'],archivePolicy={'path':leaf.ARCHIVE,'delete_existing':False,'max_bytes':536870912,'max_files':512},esAttemptPolicy='existing attempts require read-only reconciliation before session restart')
    if commit:bridge.load_base().validate(manifest,output)
    (output/'approved-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output/'target-deltas.json').write_text(json.dumps(files,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('repo','prior-stage','receipt','baseline','maintenance','output'):p.add_argument('--'+key,required=True)
    p.add_argument('--source-commit');a=p.parse_args()
    m=prepare(a.repo,a.prior_stage,read(a.receipt),read(a.baseline),read(a.maintenance),a.output,a.source_commit)
    print(json.dumps({'scope':m['scope'],'releaseReady':m['releaseReady'],'files':len(m['files']),'protected':len(m['unchangedRequired']),'baselinePending':m['baselinePending']}))
