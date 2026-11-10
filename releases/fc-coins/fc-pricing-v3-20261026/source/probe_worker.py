"""Bounded read-only probe; Player evidence covers request acceptance only."""
import json, subprocess, re
from datetime import datetime, timezone
from pathlib import Path
import urllib.error, urllib.request
import read_only_status as source
from report import report, unverified
from delivery import NoRedirect

RPG_CUTOVER = Path('/opt/rpg-migration-20261102/cutover.active')

def state(unit):
    try:
        p = subprocess.run(['systemctl','is-active',unit],capture_output=True,text=True,timeout=3)
        return p.stdout.strip() if p.stdout.strip() in {'active','inactive','failed'} else 'unknown'
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'

def http_gate(port):
    # Anonymous loopback GET; never fabricate trusted identity headers.
    try:
        with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/health', timeout=3) as response:
            return 'unexpected_anonymous_success'
    except urllib.error.HTTPError as exc:
        return 'active' if exc.code == 401 else 'unexpected_http_status'
    except (OSError, ValueError):
        return 'unknown'

def read(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}

def select(data, fields):
    return {k:data.get(k) for k in fields}

def rpg_probe():
    remote = RPG_CUTOVER.is_file()
    units = ('rpg183-link.service',) if remote else ('d4follow.service','p2pah-srv-exec.service')
    observed = {'checked_at':datetime.now(timezone.utc).isoformat(),
                'scope':'shared_services_and_current_runtime_tasks', 'issues':[],
                'runtime_owner':'183' if remote else '187',
                'role_basis':str(RPG_CUTOVER) if remote else 'local_services_without_cutover',
                'service_states':{u:state(u) for u in units}}
    if remote:
        # The existing tunnel/API proves remote reachability, not systemd state.
        observed['remote_service_states']={u:'unverified' for u in ('d4follow.service','p2pah-srv-exec.service')}
        observed['issues'].append({'level':'warning','code':'rpg_remote_service_state_unverified'})
    for unit, status in observed['service_states'].items():
        if status != 'active':
            observed['issues'].append({'level':'critical','code':'rpg_dependency_unavailable:'+unit})
    try:
        with urllib.request.build_opener(NoRedirect).open('http://127.0.0.1:8900/api/state',timeout=8) as response:
            raw = response.read(4*1024*1024+1)
        if len(raw) > 4*1024*1024:raise ValueError('bounded_rpg_state_required')
        value = json.loads(raw)
        if value.get('ok') is not True or not isinstance(value.get('data',{}).get('tasks'),list):
            raise ValueError('rpg_task_state_required')
        health=value['data'].get('health') or {}
        observed['source_freshness']={k:health.get(k) for k in ('ourTs','ourStaleHours','qdTs','qdStaleHours','iggmTs')}
        observed['remote_server_time']=value['data'].get('serverTime')
        tasks = value['data']['tasks']
        if len(tasks) > 12:raise ValueError('rpg_task_count_changed')
        observed['recent_task_count'] = len(tasks)
        seen = set()
        # Existing endpoint returns newest first; a later success supersedes its task kind/scope.
        for task in tasks:
            identity = task['id']; kind = task['kind']; params = task.get('params') or {}
            if (not re.fullmatch(r'[0-9a-f]{12}',identity) or
                    not re.fullmatch(r'[a-z_]{1,40}',kind) or task['status'] not in {'running','done','error'}):
                raise ValueError('rpg_task_shape_changed')
            game = params.get('game')
            scope = {'暗黑破坏神4':'d4','流放之路2':'poe2','AION2':'aion2'}.get(game,'shared')
            group = (kind,game if isinstance(game,str) else None)
            if group in seen:continue
            seen.add(group)
            if task['status'] == 'error':
                observed['issues'].append({'level':'critical','code':'rpg_task_failed:'+scope+':'+kind+':'+identity})
        # shortcut: in-memory task summaries omit old-process and per-row outcomes; add a read-only receipt feed when RPG exposes one.
    except Exception:
        observed['issues'].append({'level':'critical','code':'rpg_state_unavailable'})
    observed['status'] = 'critical' if any(x['level']=='critical' for x in observed['issues']) else 'warning' if observed['issues'] else 'healthy'
    return observed


def order_public_without_all(job, execution, ledger_exists):
    """Only a proven zero-dispatch ALL login failure may be a side warning."""
    import uuid
    from decimal import Decimal
    try:
        jid = job['job_id']
        if str(uuid.UUID(jid)) != jid:
            return False
        baseline = execution.get('all_baseline') or {}
        public = job.get('public_page_readback') or {}
        rows = execution.get('after', {}).get('rows', [])
        targets = {r['platform']:r for r in execution['targets']}
        before = {r['platform']:r for r in execution['before']['rows']}
        selected = execution['selected']
        return (not ledger_exists and job.get('status') == 'ready'
            and (job.get('result') or {}).get('status') == 'confirmed'
            and (job.get('result') or {}).get('execution_id') == jid
            and execution.get('execution_id') == jid and execution.get('status') == 'CONFIRMED'
            and execution.get('sync_confirmed') is True
            and baseline.get('status') == 'deferred_before_dispatch'
            and baseline.get('reason') == 'coin_auth_unavailable'
            and baseline.get('execution_id') == jid
            and baseline.get('price_post_attempted') is False
            and baseline.get('success_scope') == 'order_b2c_and_public_price'
            and public.get('status') == 'verified' and bool(public.get('checked_at'))
            and bool(selected) and set(selected) <= {'PS','XBOX','PC'}
            and set(public.get('platforms') or []) >= set(selected)
            and len(rows) == 3 and {r['platform'] for r in rows} == {'PS','XBOX','PC'}
            and set(targets) == set(before) == {'PS','XBOX','PC'}
            and all(Decimal(str(r['b2c'])) > 0
                and Decimal(str(r['b2c'])) == Decimal(str(targets[r['platform']]['quote'] if r['platform'] in selected else before[r['platform']]['b2c'])) for r in rows))
    except (KeyError,TypeError,ValueError,ArithmeticError):
        return False


def fc_report():
    snapshot = source.collect()
    if snapshot.get('v3',{}).get('enabled'):
        v3=snapshot['v3'];issues=source.assess(snapshot)['issues']
        units=['fc27-cloud-api.service','fc27-cloud-worker.service','fc-pricing-v3.service','fc27-gallery.service','fc27-gate.service']
        checks={u:state(u) for u in units}
        issues += [dict(level='critical',code='service_unavailable:'+u) for u,status in checks.items() if status!='active']
        return dict(status='critical' if any(i['level']=='critical' for i in issues) else 'warning' if issues else 'healthy',
                    captured_at=snapshot['captured_at'],issues=issues,checks=checks,v3=v3,
                    coin=dict(config=snapshot['automation'],schedule=v3['schedule'],job=next(iter(snapshot.get('recent_auto_jobs',[])),{}),collection=snapshot['monitor']['latest_collection']),
                    health=dict(snapshot['health'],incomplete_executions=max(snapshot['health'].get('incomplete_executions',0),v3['pending_count'])),
                    publication=snapshot['publication'],unknown_operations=v3['pending_operations'])
    recent = snapshot.get('recent_auto_jobs', [])
    evidence = {}
    if recent:
        job_id = recent[0]['job_id']
        # UUID identifiers only, no user-controlled filesystem paths.
        import uuid
        uuid.UUID(job_id)
        job = read(source.ROOT / 'jobs' / (job_id+'.json'))
        result = job.get('result') or {}
        linked = job.get('player_sync') or {}
        intent = job.get('player_sync_intent') or {}
        evidence['coin'] = select(job, ('job_id','status','created_at','started_at','completed_at')) | {
            'result':result.get('status'), 'changed_platforms':result.get('platforms'),
            'player_expected': result.get('status') == 'confirmed' and intent.get('enabled') is True,
            'player_job_id':linked.get('job_id'), 'player_dispatch_status':linked.get('status')}
        execution_id = result.get('execution_id')
        if execution_id:
            uuid.UUID(execution_id)
            ledger = read(source.ROOT / 'all-coin-sync' / (execution_id+'.json'))
            execution = read(source.ROOT / 'executions' / (execution_id+'.json'))
            evidence['coin']['execution_id'] = execution_id
            evidence['coin']['order_public_confirmed_without_all'] = order_public_without_all(
                job, execution, (source.ROOT / 'all-coin-sync' / (execution_id+'.json')).exists())
            evidence['all'] = select(ledger, ('execution_id','status','completed_at')) | {
                'steps':[select(s, ('platform','status','product_id','source_product_id'))
                         for s in ledger.get('steps', [])]}
        if linked.get('job_id'):
            uuid.UUID(linked['job_id'])
            ledger = read(source.ROOT / 'player-sync' / (linked['job_id']+'.json'))
            request_job = read(source.ROOT / 'jobs' / (linked['job_id']+'.json'))
            import fc27_cloud_api as api
            evidence['player'] = select(ledger, ('job_id','coin_execution_id','status','stage',
                                                 'created_at','completed_at','category_response','price_verification')) | {
                'request_price_check_waived': api.player_price_readback_waived(request_job)}
    units = ['fc27-cloud-api.service','fc27-cloud-worker.service','fc27-gallery.service','fc27-gate.service']
    checks = {u:state(u) for u in units}
    checks.update({'coin_api_http_gate':http_gate(8879), 'gallery_api_http_gate':http_gate(8902)})
    from hooks import extend_report
    return extend_report(report(snapshot, source.assess(snapshot), checks, evidence))


def main():
    try:
        value = fc_report()
    except Exception as exc:
        value = unverified(type(exc).__name__)
    value['rpg'] = rpg_probe()
    value['issues'].extend(value['rpg']['issues'])
    value['status'] = 'critical' if any(i['level']=='critical' for i in value['issues']) else 'warning' if value['issues'] else 'healthy'
    return value

if __name__ == '__main__':
    print(json.dumps(main(), ensure_ascii=False))
