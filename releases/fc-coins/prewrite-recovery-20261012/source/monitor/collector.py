"""Bounded read-only collection; optional external delivery is separately approved."""
import argparse, hashlib, json, os, subprocess, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from report import unverified

def now():
    return datetime.now(timezone.utc).isoformat()

def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        if os.name == 'posix':
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def probe():
    try:
        child = subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('probe_worker.py'))],
                               capture_output=True, text=True, timeout=40)
        if child.returncode:
            return unverified('ProbeProcessFailed')
        value = json.loads(child.stdout)
        if value.get('status') not in {'healthy','warning','critical','unverified'}:
            raise ValueError('invalid_report')
        return value
    except Exception as exc:
        return unverified(type(exc).__name__)

def signature(value):
    canonical = {'status':value['status'], 'codes':sorted(i['code'] for i in value.get('issues', [])),
                 'unknown_operations': sorted(x['operation_id'] for x in value.get('unknown_operations') or [])}
    return hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()

def apply_prewrite_recovery(value):
    coin = value.get('coin', {})
    collection = coin.get('collection') or {}
    proof = collection.get('prewrite_failure_recovery') or {}
    job = coin.get('job') or {}
    attempt = coin.get('latest_attempt') or {}
    if (proof.get('verified_prewrite') is not True or job.get('status') != 'failed' or
            proof.get('failed_job_id') != job.get('job_id') or
            proof.get('failed_completed_at') != job.get('completed_at') or
            type(proof.get('policy_revision')) is not int or
            proof.get('policy_revision') != coin.get('config',{}).get('revision') or
            not collection.get('run_id') or
            proof.get('new_collection_run_id') != collection.get('run_id') or
            proof.get('new_collection_created_at') != collection.get('created_at') or
            attempt.get('run_id') != collection.get('run_id') or attempt.get('status') != 'ready_for_quote' or
            collection.get('storefront_run_id') != collection.get('run_id') or
            value.get('unknown_operations') != [] or
            not any(i['code'] == 'latest_coin_job_failed' and i['level'] == 'critical' for i in value.get('issues',[]))):
        return value
    try:
        newer = datetime.fromisoformat(proof['new_collection_created_at'].replace('Z','+00:00'))
        failed = datetime.fromisoformat(proof['failed_completed_at'].replace('Z','+00:00'))
        captured = datetime.fromisoformat(value['captured_at'].replace('Z','+00:00'))
        interval = coin.get('config',{}).get('interval_minutes')
        same_job = (proof.get('same_failed_job_collection') is True and collection['run_id'] == job['job_id'] and
                    datetime.fromisoformat(job['created_at'].replace('Z','+00:00')) <= newer <=
                    datetime.fromisoformat(collection['quote_created_at'].replace('Z','+00:00')) <= failed)
        if (type(interval) is not int or interval <= 0 or newer.utcoffset() is None or failed.utcoffset() is None or
                not (failed < newer or same_job) or not -60 <= (captured-newer).total_seconds() <= interval*60+900):
            return value
    except (KeyError,TypeError,ValueError):
        return value
    remaining = [i for i in value['issues'] if i['code'] != 'latest_coin_job_failed']
    from hooks import controls
    control = controls(dict(value, issues=remaining))
    if any(state['reasons'] for state in control['platforms'].values()):
        return value
    value['issues'] = remaining + [
        {'level':'warning','code':'historical_prewrite_failure'}]
    value['status'] = 'critical' if any(i['level'] == 'critical' for i in value['issues']) else 'warning'
    return value

def collect_bounded(run_probe=probe, sleep=time.sleep):
    observations = []
    value = None
    for attempt in range(3):
        value = apply_prewrite_recovery(run_probe())
        observations.append({'captured_at':value['captured_at'], 'status':value['status'],
                             'issues':value.get('issues', [])})
        if value['status'] in {'healthy','warning'} or attempt == 2:
            break
        sleep(10)
    value['observations'] = observations
    value['finished_at'] = now()
    value['bounded_confirmation'] = {'maximum_attempts':3, 'probe_timeout_seconds':40,
                                     'interval_seconds':10, 'maximum_total_seconds':140}
    return value

def persist(directory, value):
    try:
        previous = json.loads((directory / 'latest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = {}
    fingerprint = signature(value)
    previous_fingerprint = signature(previous) if previous.get('status') else None
    value['incident_fingerprint'] = fingerprint
    if fingerprint != previous_fingerprint and (value['status'] != 'healthy' or previous.get('status') in {'critical','warning','unverified'}):
        stamp = datetime.fromisoformat(value['finished_at']).strftime('%Y%m%dT%H%M%S%fZ')
        # Same transition survives a crash before latest.json is replaced.
        event_id = hashlib.sha256((str(previous.get('finished_at'))+str(previous_fingerprint)+fingerprint).encode()).hexdigest()
        prefix = 'noncore_source_unavailable:'
        previous_codes = {i['code'] for i in previous.get('issues', [])}
        codes = {i['code'] for i in value.get('issues', [])}
        recovered_sources = sorted(code[len(prefix):] for code in previous_codes - codes
                                   if code.startswith(prefix) and code[len(prefix):] in {'IGGM','U4GM','U7Buy'})
        source_recovery = bool(recovered_sources) and codes <= previous_codes and value['status'] in {'healthy','warning'}
        event = {'event_id':event_id, 'created_at':value['finished_at'],
                 'kind':'recovery' if (value['status']=='healthy' or (previous.get('status')=='critical' and value['status']=='warning') or source_recovery) else 'incident',
                 'fingerprint':fingerprint, 'status':value['status'], 'issues':value.get('issues', []),
                 'operation_ids':sorted(x['operation_id'] for x in value.get('unknown_operations') or []),
                 'recovered_sources':recovered_sources if source_recovery else [],
                 'reference_sources':(value.get('coin',{}).get('collection') or {}).get('reference_sources',{}),
                 'delivery_state':'pending', 'attempt_count':0, 'acknowledged_at':None}
        event_path = directory / 'outbox' / (event_id+'.json')
        if not event_path.exists():
            atomic(event_path, event)
    stamp = datetime.fromisoformat(value['finished_at']).strftime('%Y%m%dT%H%M%S%fZ')
    atomic(directory / 'history' / (stamp+'.json'), value)
    atomic(directory / 'latest.json', value)
    # Bounded own history only. Never delete unacknowledged alert outbox entries.
    files = sorted((directory / 'history').glob('*.json'))
    for file in files[:-8640]:
        file.unlink()

def persist_cycle_recovery(directory, value, previous, control):
    import uuid
    coin = value.get('coin', {})
    job = coin.get('job') or {}
    config = coin.get('config') or {}
    job_id = job.get('job_id')
    try:
        if str(uuid.UUID(job_id)) != job_id:
            return None
    except (ValueError,TypeError,AttributeError):
        return None
    revision = config.get('revision')
    if (job.get('status') != 'ready' or job.get('result') not in {'confirmed','no_price_change'} or
            config.get('system_enabled') is not True or config.get('mode') != 'auto' or
            type(revision) is not int or previous.get('policy_revision') != revision or
            control.get('policy_revision') != revision or value.get('unknown_operations') != []):
        return None
    platforms = sorted(p for p in ('PS','XBOX','PC')
                       if previous.get('platforms',{}).get(p,{}).get('phase') == 'AWAITING_CYCLE' and
                       control.get('platforms',{}).get(p,{}).get('phase') == 'RECOVERED' and
                       not control['platforms'][p].get('reasons') and
                       previous['platforms'][p].get('resume_after_job_id') and
                       previous['platforms'][p].get('resume_after_job_id') != job_id)
    if not platforms:
        return None
    proof = {'job_id':job_id,'policy_revision':revision,'platforms':platforms,'result':job['result']}
    identity = {'event':'fc_natural_cycle_recovery','job_id':job_id,'policy_revision':revision,'platforms':platforms}
    event_id = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    target = directory/'outbox'/(event_id+'.json')
    if not target.exists():
        atomic(target, {'event_id':event_id,'created_at':value['finished_at'],'kind':'recovery',
                        'status':value['status'],'issues':value.get('issues',[]),'cycle_recovery':proof,
                        'reference_sources':(coin.get('collection') or {}).get('reference_sources',{}),
                        'operation_ids':[],'fingerprint':event_id,'delivery_state':'pending',
                        'attempt_count':0,'acknowledged_at':None})
    return event_id

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--delivery-config', type=Path, default=Path('/etc/fc-ops-readonly-monitor/delivery.json'))
    args = parser.parse_args()
    try:
        import fcntl
        args.output_dir.mkdir(parents=True, exist_ok=True)
        lock = (args.output_dir / '.collector.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        value = collect_bounded()
        from hooks import controls, persist_controls
        control_path = args.output_dir/'gates'/'control.json'
        previous = json.loads(control_path.read_text()) if control_path.exists() else {}
        # Outbox first: a crash before control publication retries the same event ID.
        persist_cycle_recovery(args.output_dir, value, previous, controls(value, previous))
        persist_controls(args.output_dir, value)
        persist(args.output_dir, value)
        from delivery import deliver
        delivery = deliver(args.output_dir, args.delivery_config)
        print(json.dumps({'status':value['status'], 'finished_at':value['finished_at'],
                          'delivery_state':delivery['state'], 'delivered':False}))
        return 0 if value['status'] in {'healthy','warning'} else 2
    except Exception as exc:
        print(json.dumps({'status':'unverified','error_type':type(exc).__name__,
                          'code':'monitor_storage_or_runtime_failure','delivery_state':'not_configured'}))
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
