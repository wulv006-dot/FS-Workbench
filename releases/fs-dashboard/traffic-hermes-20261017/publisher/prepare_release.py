"""Prepare code-only stage and non-releasable manifest from actual read-only baselines."""
import argparse,hashlib,json,shutil
from pathlib import Path
import release_navigation as bridge


def required_paths(base):
    required={'/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')}
    required|={'/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py'}
    required|=set(base.HERMES_TARGETS.values())-set(bridge.TARGETS.values())
    return required|set(bridge.PRESERVED)


def prepare(repo,output,source_map,dependencies,commit,admission=None):
    repo=Path(repo);output=Path(output)
    if output.exists():raise ValueError('new_stage_required')
    output.mkdir(mode=0o700,parents=True)
    release=repo/'releases/fs-dashboard/traffic-hermes-20261017'
    known={}
    for row in source_map['rows']:
        if 'observed_before_sha256' in row and row.get('existed') in (True,False):known[row['runtime']]=row['observed_before_sha256']
    admission=admission or {}
    for row in dependencies['files']+admission.get('files',[]):
        if row.get('exists') is True:known[row['path']]=row['sha256']
        elif row.get('exists') is False:known[row['path']]=None
    files=[];pending=[]
    for candidate,target in bridge.TARGETS.items():
        if candidate.startswith('contract/details/') or candidate.endswith('/traffic_contract.py'):source=repo/'mmoexp_google_data/details'/Path(candidate).name
        else:source=release/'source'/Path(candidate).name
        destination=output/'candidate'/candidate;destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True);shutil.copyfile(source,destination)
        if target not in known:pending.append(target)
        files.append({'candidate':candidate,'target':target,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'beforeSha256':known.get(target)})
    base=bridge.load_base()
    required=required_paths(base)
    unit_facts={name:dict(line.split('=',1) for line in text.splitlines() if '=' in line) for name,text in admission.get('units',{}).items()}
    properties=unit_facts.get('fs-marketing-range.service',{})
    contract={'properties':{k:v for k,v in properties.items() if k!='PROBE_EXIT'},'cgroupPath':'/sys/fs/cgroup/systemd'+properties.get('ControlGroup','')+'/cgroup.procs'} if properties else None
    if not contract:pending.append('runtime:marketingStopContract')
    runtime=dict(bridge.RUNTIME)
    for unit in bridge.TIMERS:
        facts=unit_facts.get(unit,{})
        if not facts or facts.get('PROBE_EXIT','0').strip()!='0':pending.append('runtime:valid-probe:'+unit)
        if facts.get('FragmentPath'):required.add(facts['FragmentPath'])
        for path in facts.get('DropInPaths','').split():required.add(path)
        runtime[unit]={key:facts.get(key) for key in ('ActiveState','SubState','UnitFileState')}
    if properties.get('FragmentPath'):required.add(properties['FragmentPath'])
    for path in properties.get('DropInPaths','').split():required.add(path)
    if bridge.ABSENT not in known or known[bridge.ABSENT] is not None:pending.append('absence:'+bridge.ABSENT)
    protected=[]
    for target in sorted(required):
        if not known.get(target):pending.append(target)
        else:protected.append({'path':target,'sha256':known[target]})
    publisher=output/'publisher';publisher.mkdir(mode=0o700)
    for name in ('release_navigation.py','release_navigation_base.py','es_image_lifecycle.py','marketing_maintenance.py'):shutil.copyfile(release/'publisher'/name,publisher/name)
    manifest={'schemaVersion':1,'scope':bridge.SCOPE,'releaseReady':False,'businessWrites':False,'timersChanged':False,'nightlyChanges':False,'sourceCommit':commit,'basePublisherSha256':bridge.BASE_SHA,'publisherBridgeSha256':hashlib.sha256((publisher/'release_navigation.py').read_bytes()).hexdigest(),'imageLifecycleSha256':hashlib.sha256((publisher/'es_image_lifecycle.py').read_bytes()).hexdigest(),'sessionBaseImage':dependencies['session_image_id'],'sessionCurrentImage':dependencies['session_image_id'],'sessionNewTag':'fc27-cloud-session:traffic-hermes-20261017-es','imageId':'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544','runtimeRequired':runtime,'marketingStopContract':contract,'marketingMaintenanceSha256':hashlib.sha256((publisher/'marketing_maintenance.py').read_bytes()).hexdigest(),'absenceRequired':[bridge.ABSENT],'files':files,'unchangedRequired':protected,'baselinePending':sorted(set(pending)),'installOrder':'contract files first, Hermes consumers second, session image before reader/worker restart; inherited admission and collector locks','archivePolicy':{'path':'/var/lib/fc27-es-exports','max_bytes':536870912,'max_files':512,'reserve_bytes':67108864,'delete_existing':False}}
    (output/'approved-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'stage':str(output),'releaseReady':False,'files':len(files),'baselinePending':manifest['baselinePending']}


def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--source-map',type=Path,required=True);p.add_argument('--dependencies',type=Path,required=True);p.add_argument('--source-commit',required=True);p.add_argument('--admission',type=Path,required=True);a=p.parse_args()
    print(json.dumps(prepare(a.repo,a.output,json.loads(a.source_map.read_text('utf-8')),json.loads(a.dependencies.read_text('utf-8')),a.source_commit,json.loads(a.admission.read_text('utf-8'))),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
