"""Bounded read-only probe; Player evidence covers request acceptance only."""
import json, subprocess
import urllib.error, urllib.request
import read_only_status as source
from report import report

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

def main():
    snapshot = source.collect()
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

if __name__ == '__main__':
    print(json.dumps(main(), ensure_ascii=False))
