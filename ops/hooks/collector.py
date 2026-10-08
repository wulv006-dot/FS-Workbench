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

def collect_bounded(run_probe=probe, sleep=time.sleep):
    observations = []
    value = None
    for attempt in range(3):
        value = run_probe()
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
        event = {'event_id':event_id, 'created_at':value['finished_at'],
                 'kind':'recovery' if (value['status']=='healthy' or (previous.get('status')=='critical' and value['status']=='warning')) else 'incident',
                 'fingerprint':fingerprint, 'status':value['status'], 'issues':value.get('issues', []),
                 'operation_ids':sorted(x['operation_id'] for x in value.get('unknown_operations') or []),
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
        from hooks import persist_controls
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
