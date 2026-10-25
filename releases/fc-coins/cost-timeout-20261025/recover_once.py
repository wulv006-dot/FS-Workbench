"""One authorized fresh cycle through the original queue; never replay the failed job."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, '/opt/fc27-cloud-browser')
import automation_tick as tick
from snapshot_layer import atomic_json

ROOT = Path('/var/lib/fc27-cloud')
STAGE = Path('/opt/fs-release-stage/fc-cost-timeout-20261025')
ORIGINAL = '715ec3af-8ade-45c5-b821-186face4572b'
intent = STAGE / 'recovery-intent.json'
with tick.queue_mutation():
    if intent.exists():
        print(json.dumps({'status': 'already_dispatched_do_not_replay', 'intent': json.loads(intent.read_text())}))
        raise SystemExit(0)
    manifest = json.loads((STAGE / 'manifest.json').read_text())
    assert json.loads((STAGE / 'deployment.json').read_text())['status'] == 'deployed'
    assert all(hashlib.sha256((Path('/opt/fc27-cloud-browser') / name).read_bytes()).hexdigest() == row['after']
               for name, row in manifest['files'].items()), 'runtime_drift'
    policy = tick.load_policy()
    last = tick.latest_cycle()
    assert policy['system_enabled'] and policy['mode'] == 'auto' and policy['revision'] == 40
    assert last['job_id'] == ORIGINAL and tick.proven_readonly_cycle_failure(last, policy['revision'])
    assert tick.retry_guard() == 'ready', 'unresolved_or_active_operation'
    job_id = str(uuid.uuid4())
    record = dict(job_id=job_id, kind='auto_cycle', actor='codex-authorized-recovery',
                  created_at=datetime.now(timezone.utc).isoformat(), status='queued',
                  request={'policy_revision': policy['revision']})
    atomic_json(intent, {'job_id': job_id, 'original_job_id': ORIGINAL,
                         'kind': 'manual_authorized_fresh_cycle', 'record': record})
    tick.exclusive_json(ROOT / 'queue' / (job_id + '.json'), record)
    print(json.dumps({'status': 'queued', 'job_id': job_id, 'original_job_id': ORIGINAL,
                      'natural_cycle': False, 'original_replayed': False}))
