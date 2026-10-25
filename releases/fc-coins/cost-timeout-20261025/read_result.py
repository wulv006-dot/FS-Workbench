"""Read the fixed recovery operation, current schedule and existing receipts only."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

sys.dont_write_bytecode = True
sys.path.insert(0, '/opt/fc27-cloud-browser')
import automation_tick as tick
import fc27_cloud_api as api

ROOT = Path('/var/lib/fc27-cloud')
STAGE = Path('/opt/fs-release-stage/fc-cost-timeout-20261025')
intent = json.loads((STAGE / 'recovery-intent.json').read_text())
jid = intent['job_id']
job = json.loads((ROOT / 'jobs' / (jid + '.json')).read_text())
latest = tick.latest_cycle()
manifest = json.loads((STAGE / 'manifest.json').read_text())
original = json.loads((ROOT / 'jobs' / (intent['original_job_id'] + '.json')).read_text())
out = dict(observed_at=datetime.now(timezone.utc).isoformat(), job=job, latest_job=latest,
           player_sync_gate=tick.player_sync_gate(),
           original={k: original.get(k) for k in ('job_id', 'status', 'error', 'completed_at')},
           deployment=json.loads((STAGE / 'deployment.json').read_text()),
           runtime_sha256={name: hashlib.sha256((Path('/opt/fc27-cloud-browser') / name).read_bytes()).hexdigest()
                           for name in manifest['files']},
           protected_unchanged=all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
                                   for path, digest in manifest['protected'].items()),
           automation=api.automation_view(tick.load_policy()), health=api.health(),
           services=subprocess.check_output(['systemctl', 'is-active', 'fc27-cloud-api',
                       'fc27-cloud-worker', 'fc27-automation-tick.timer'], text=True).splitlines())
for name, file in [('monitor', '/var/lib/fc-ops-readonly-monitor/latest.json'),
                   ('pricing', '/var/lib/fs-pricing-alerts/latest.json')]:
    value = json.loads(Path(file).read_text())
    out[name] = {k: value.get(k) for k in ('captured_at', 'exported_at', 'issues', 'coin',
                                         'hook_control', 'unknown_operations', 'fc_job') if k in value}
out['receipts'] = {}
receipt_id = latest['job_id']
for folder in ('runs', 'quotes', 'requests', 'executions', 'all-coin-sync', 'player-sync'):
    path = ROOT / folder / (receipt_id + '.json')
    if path.exists():
        out['receipts'][folder] = json.loads(path.read_text())
print(json.dumps(out, ensure_ascii=True))
