"""Execute over the approved SSH entrypoint. Reads only; emits no secrets/prices.

No application main(), jobs, login, writer, POST, or authentication header is used.
"""
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
import subprocess

sys.dont_write_bytecode = True
APP = Path('/opt/fc27-cloud-browser')
ROOT = Path('/var/lib/fc27-cloud')

def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default

def selected(value, keys):
    return {k: value.get(k) for k in keys}

def summary_jobs(directory, kind=None):
    rows = [read(p) for p in directory.glob('*.json')]
    rows = [r for r in rows if r and (kind is None or r.get('kind') == kind)]
    rows.sort(key=lambda r: r.get('created_at', ''), reverse=True)
    return [selected(r, ('job_id','id','kind','created_at','completed_at','finished_at','status','error','error_detail')) |
            {'result_status': (r.get('result') or r.get('sync_result') or {}).get('status'),
             'cache_status': (r.get('cache_refresh') or {}).get('status'),
             'public_readback_status': (r.get('public_page_readback') or {}).get('status')}
            for r in rows[:5]]

def assess(value):
    """Proposed read-only thresholds, not automatic remediation or price policy."""
    issues = []
    stamp = datetime.fromisoformat(value['captured_at'])
    health = value.get('health', {})
    gateway = value.get('gateway', {})
    if not gateway.get('certificate_valid') or gateway.get('http_status') not in ('401','302','303'):
        issues.append({'level':'critical','code':'https_or_anonymous_gate_unverified'})
    for key in ('api','worker','browser','p2pah_session'):
        if health.get(key) != 'ok':
            issues.append({'level':'critical','code':key+'_unhealthy_or_unknown'})
    if health.get('automation_timer') != 'active':
        issues.append({'level':'critical','code':'automation_timer_inactive_or_unknown'})
    if health.get('https_certificate',{}).get('status') != 'ok':
        issues.append({'level':'critical','code':'certificate_expiry_or_renewal_unhealthy'})
    if health.get('incomplete_executions', 1) > 0:
        issues.append({'level':'critical','code':'coin_execution_needs_reconcile'})
    monitor = value.get('monitor', {})
    collection = monitor.get('latest_collection', {})
    from fc27_quote_engine import reference_sites
    platforms = ('PS','XBOX','PC')
    sites = ('Lootbar','IGGM','U4GM','U7Buy')
    expected_keys = {(s,p) for s in sites for p in platforms}
    rows = collection.get('competitor_keys', [])
    keys = {tuple(x) for x in rows if isinstance(x, list) and len(x) == 2 and all(isinstance(v,str) for v in x)}
    sources = health.get('sources', {})
    coverage_ok = (len(keys) == len(rows) == collection.get('competitor_count') and
                   keys <= expected_keys and not collection.get('competitor_records_invalid') and
                   all(('Lootbar',p) in keys and reference_sites({s for s,p2 in keys if p2 == p}) for p in platforms) and
                   collection.get('cost_count') == 3 and
                   set(collection.get('cost_platforms',[])) == set(platforms) and
                   all(sources.get(k) == 'ok' for k in ('lootbar','p2pah_cost','fx')) and
                   all(sources.get(s.lower()) == ('ok' if all((s,p) in keys for p in platforms) else 'missing')
                       for s in sites[1:]))
    if not coverage_ok:
        issues.append({'level':'critical','code':'source_coverage_unverified'})
    else:
        for site in sites[1:]:
            if any((site,p) not in keys for p in platforms):
                issues.append({'level':'warning','code':'noncore_source_unavailable:'+site})
    interval = value.get('automation',{}).get('interval_minutes')
    allowance = interval*60+900 if type(interval) is int and interval>0 else None
    try:
        age = (stamp-datetime.fromisoformat(collection['created_at'].replace('Z','+00:00'))).total_seconds()
        if allowance is None or age < -60 or age > allowance:
            issues.append({'level':'critical','code':'collection_stale_or_clock_invalid'})
    except (KeyError,ValueError,TypeError):
        issues.append({'level':'critical','code':'collection_time_unverified'})
    if ((monitor.get('latest_attempt') or {}).get('status') != 'ready_for_quote' or
        (monitor.get('latest_attempt') or {}).get('run_id') != collection.get('run_id') or
        collection.get('storefront_run_id') != collection.get('run_id')):
        issues.append({'level':'warning','code':'latest_attempt_or_monitor_run_unverified'})
    publication = value.get('publication',{})
    if (publication.get('status') != 'matched' or len(publication.get('platforms',[])) != 3 or
        {r.get('platform') for r in publication.get('platforms',[])} != {'PS','XBOX','PC'} or
        any(r.get('status') != 'matched' for r in publication.get('platforms',[]))):
        issues.append({'level':'critical','code':'three_platform_publication_unverified'})
    player = value.get('player_sync', {})
    last = player.get('last_job') or {}
    if player.get('enabled') is None:
        issues.append({'level':'critical','code':'player_switch_unknown'})
    elif (last.get('result') == 'needs_reconcile' or last.get('status') == 'failed') and player.get('price_verification_waived') is not True:
        issues.append({'level':'critical' if player['enabled'] else 'warning',
                       'code':'player_pending_enabled' if player['enabled'] else 'player_disabled_pending_retained'})
    gallery = value.get('gallery',{})
    if gallery.get('blocked'):
        issues.append({'level':'critical','code':'gallery_task_unconfirmed'})
    if gallery.get('settings',{}).get('enabled') is False:
        issues.append({'level':'warning','code':'gallery_automation_disabled'})
    elif gallery.get('settings',{}).get('enabled') is not True:
        issues.append({'level':'critical','code':'gallery_switch_unknown'})
    if gallery.get('settings',{}).get('enabled') is True:
        if gallery.get('config',{}).get('pause_reason'):
            issues.append({'level':'critical','code':'gallery_automation_paused'})
        try:
            interval = gallery['settings']['interval_minutes']
            captured = gallery['latest']['checked_at']
            age = (stamp-datetime.fromisoformat(captured.replace('Z','+00:00'))).total_seconds()
            if type(interval) is not int or interval <= 0 or age < -60 or age > interval*60+900:
                issues.append({'level':'critical','code':'gallery_readback_stale_or_clock_invalid'})
        except (KeyError,ValueError,TypeError,AttributeError):
            issues.append({'level':'critical','code':'gallery_readback_time_unverified'})
    if health.get('queue_depth',0) >= 5:
        issues.append({'level':'warning','code':'queue_depth_at_least_five'})
    if isinstance(health.get('disk_free_gb'), (int,float)) and health['disk_free_gb'] < 10:
        issues.append({'level':'warning','code':'disk_below_ten_gb'})
    return {'status':'critical' if any(i['level']=='critical' for i in issues) else 'warning' if issues else 'healthy',
            'issues':issues,'thresholds':{'collection_grace_minutes':15,'worker_heartbeat_seconds':15,
                                         'certificate_days':2,'queue_warning':5,'disk_warning_gb':10,
                                         'gallery_grace_minutes':15}}

def collect():
    sys.path.insert(0, str(APP))
    import fc27_cloud_api as api
    monitor = api.monitor_view()
    gallery = Path('/var/lib/fc27-gallery')
    cfg = read(gallery/'settings.json', {})
    latest = read(gallery/'latest.json', {})
    gallery_jobs = [read(p) for p in (gallery/'jobs').glob('*.json')]
    collection = monitor.get('latest_collection') or {}
    competitors = collection.get('competitors', [])
    valid_competitors = [r for r in competitors if isinstance(r,dict) and r.get('status') in (None,'valid')]
    from fc27_quote_engine import reference_sites
    refs = {p:reference_sites({r.get('source') for r in valid_competitors if r.get('platform') == p})
            for p in ('PS','XBOX','PC')}
    record_keys = [(r.get('source'),r.get('platform')) for r in competitors if isinstance(r,dict)]
    invalid_competitors = (len(record_keys) != len(competitors) or
                          len(set(record_keys)) != len(record_keys) or
                          any(r.get('status') not in (None,'valid','missing') for r in competitors if isinstance(r,dict)) or
                          any(s not in ('Lootbar','IGGM','U4GM','U7Buy') or p not in ('PS','XBOX','PC') for s,p in record_keys) or
                          any(r.get('comparable') is not True and
                              not (r.get('comparable') is None and r.get('conditional') is not True)
                              for r in valid_competitors
                              if r.get('source') == 'Lootbar' or r.get('source') in refs.get(r.get('platform'),[])))
    tls = subprocess.run(['curl','--silent','--show-error','--connect-timeout','5','--max-time','15',
                          '--output','/dev/null','--write-out','%{http_code} %{ssl_verify_result}',
                          'https://47.85.224.112/dashboard/'], capture_output=True, text=True, timeout=20)
    fields = tls.stdout.split()
    value = {
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'gateway': {'transport_ok':tls.returncode == 0,
                    'http_status':fields[0] if len(fields)==2 else None,
                    'certificate_valid':tls.returncode == 0 and len(fields)==2 and fields[1]=='0'},
        'health': monitor['health'], 'automation': monitor['automation'],
        'player_sync': monitor['player_sync'],
        'monitor': {k:monitor[k] for k in ('latest_attempt','page_readback','cache_refresh')} |
                   {'latest_collection': selected(collection,('run_id','created_at','quote_created_at')) |
                     {'competitor_count':len(valid_competitors),
                      'cost_count':len(collection.get('costs',[])),
                      'competitor_keys':[[r.get('source'),r.get('platform')] for r in valid_competitors],
                      'competitor_records_invalid':invalid_competitors,
                      'unavailable_sources':[s for s in ('IGGM','U4GM','U7Buy')
                                             if any(not any(r.get('source') == s and r.get('platform') == p
                                                            for r in valid_competitors) for p in ('PS','XBOX','PC'))],
                      'reference_sources':refs,
                      'cost_platforms':[r.get('platform') for r in collection.get('costs',[])],
                      'storefront_run_id':monitor['storefront'].get('collection_run_id')}},
        'publication': {'status':monitor['publication'].get('status'),
                        'platforms':[{k:r.get(k) for k in ('platform','status','public_checked_at')}
                                     for r in monitor['publication'].get('platforms',[])]},
        'recent_auto_jobs': summary_jobs(ROOT/'jobs','auto_cycle'),
        'gallery': {'config': selected(cfg,('revision','updated_at','pause_reason')),
                    'settings': selected(cfg.get('settings',{}),('enabled','interval_minutes')),
                    'blocked': any(j.get('status') in ('uncertain','running','dispatching') for j in gallery_jobs),
                    'job_count':len(gallery_jobs), 'recent_jobs':summary_jobs(gallery/'jobs'),
                    'latest': selected(latest,('checked_at','applied_at','scope','revision')),
                    'schedule':read(gallery/'schedule.json',{})},
        'hashes': {str(p):hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in [APP/'player_sync_job.py',APP/'fc27_cloud_api.py',APP/'automation_tick.py',
                             Path('/opt/fc27-gallery/api.py'),Path('/opt/fc27-gallery/runner.py')]
                   if p.exists()}}
    # Only a fresh usable collection can clear an independently proven no-write rejection.
    from hooks import controls
    control = controls({'issues':assess(value)['issues'],'coin':{'config':monitor['automation']},
                        'publication':value['publication'],'unknown_operations':[]})
    if (not any(state['reasons'] for state in control['platforms'].values()) and
            (monitor.get('latest_attempt') or {}).get('status') == 'ready_for_quote' and
            (monitor.get('latest_attempt') or {}).get('run_id') == collection.get('run_id') and
            value['monitor']['latest_collection']['storefront_run_id'] == collection.get('run_id')):
        try:
            import uuid
            from automation_tick import proven_prewrite_rejection
            latest = next(iter(value['recent_auto_jobs']), {})
            job_id = latest.get('job_id')
            if str(uuid.UUID(job_id)) != job_id:
                raise ValueError('job_identity_invalid')
            job = read(ROOT/'jobs'/(job_id+'.json'), {})
            revision = monitor['automation'].get('revision')
            if (proven_prewrite_rejection(job, revision) and
                    datetime.fromisoformat(collection['created_at'].replace('Z','+00:00')) >
                    datetime.fromisoformat(job['completed_at'].replace('Z','+00:00'))):
                value['monitor']['latest_collection']['prewrite_failure_recovery'] = {
                    'verified_prewrite':True,'failed_job_id':job_id,'failed_completed_at':job['completed_at'],
                    'policy_revision':revision,'new_collection_run_id':collection['run_id'],
                    'new_collection_created_at':collection['created_at']}
        except (ImportError,AttributeError,KeyError,TypeError,ValueError,OSError):
            pass
    return value

if __name__ == '__main__':
    try:
        value = collect()
        value['assessment'] = assess(value)
        print(json.dumps(value, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'status':'unverified','error_type':type(exc).__name__}))
        raise SystemExit(2)
