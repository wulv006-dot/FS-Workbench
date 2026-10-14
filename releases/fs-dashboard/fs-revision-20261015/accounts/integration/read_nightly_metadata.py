"""Read-only schedule metadata. Never import workers or read provider credentials."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import stat


def properties(command):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True)
    return dict(row.split('=', 1) for row in result.stdout.splitlines() if '=' in row)


out = {'read_only': True, 'observed_at_utc': datetime.now(timezone.utc).isoformat(),
       'provider_calls': 0, 'credential_reads': 0}
out['timezone'] = properties(['timedatectl', 'show', '-p', 'Timezone']).get('Timezone')
out['localtime_target'] = str(Path('/etc/localtime').resolve())
out['server_clock_zone'] = subprocess.run(['date', '+%Z%z'], stdout=subprocess.PIPE,
    stderr=subprocess.PIPE, universal_newlines=True).stdout.strip()
path = Path('/opt/fs-hermes-fc/nightly.py')
data = path.read_bytes()
tree = ast.parse(data)
out['nightly_source'] = {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(),
    'schedule_assignments': [ast.unparse(node) for node in tree.body if isinstance(node, ast.Assign)
         and any(isinstance(target, ast.Name) and target.id in ('STARTS', 'CUTOFF') for target in node.targets)]}
path = Path('/var/lib/fs-hermes-fc/fs/nightly-schedule.json')
value = json.loads(path.read_text()) if path.is_file() else None
out['nightly_configuration'] = ({key: value.get(key) for key in ('contract', 'enabled', 'owner', 'timezone')}
                               if isinstance(value, dict) else {'exists': False})
out['dependency_source_sha256'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in map(Path,
    ('/opt/mmoexp-marketing/deployment/server_run_integrated.py', '/opt/fs-boss-workspaces/backend/nightly_http.py',
     '/opt/fs-hermes-fc/direct_provider.py', '/opt/fs-hermes-fc/proxy_gateway.py'))}
targets = [Path(root) / name for root, names in (
    ('/opt/fs-exact-range-20261001', ('fc_daily.py', 'fc_daily_model.py', 'ai_advisor_model.py', 'ai_advisor.py',
                                   'fc_detail.py', 'range_api.py', 'profit_queries.py', 'fs_cleanup.py')),
    ('/opt/fs-boss-workspaces/backend', ('boss_daily.py', 'game_intelligence.py', 'management_daily.py', 'workspace_official_model.py')),
    ('/opt/fs-hermes-fc', ('report_artifacts.py', 'boss_projection.py', 'boss_renderer.py', 'report.template.html')),
    ('/opt/fs-hermes-fc/assets', ('knowledge-derived.md', 'knowledge-derived.json')),
    ('/etc/systemd/system', ('fs-maintenance-cleanup.service', 'fs-maintenance-cleanup.timer')),
) for name in names]
paths = set(targets)
for path in targets:
    paths.update(path.parents)
paths.update(map(Path, ('/var/lib/fs-hermes-fc', '/var/lib/fs-hermes-fc/fs',
    '/var/lib/fs-business-ranges/fc-daily', '/var/lib/fs-hermes-fc/fs/admission.lock',
    '/var/lib/fs-business-ranges/fc-daily/provider.lock', '/var/www/dashboard/fs-home/transactions/collector.lock')))
out['target_and_lock_boundaries'] = []
for path in sorted(paths):
    row = {'path': str(path), 'target': path in targets, 'exists': path.exists(), 'symlink': path.is_symlink()}
    if path.exists():
        info = path.lstat()
        row.update(uid=info.st_uid, gid=info.st_gid, mode=oct(stat.S_IMODE(info.st_mode)), links=info.st_nlink,
                   kind='regular' if stat.S_ISREG(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else 'other')
    out['target_and_lock_boundaries'].append(row)
out['units'] = {}
for unit in ('fs-boss-game-monitor.service', 'fs-boss-management.service', 'mmoexp-marketing-daily.service',
             'fs-boss-game-monitor.timer', 'fs-boss-management.timer', 'mmoexp-marketing-daily.timer',
             'mmoexp-weekly-report.timer'):
    props = properties(['systemctl', 'show', unit, '--no-pager', '-p', 'ActiveState', '-p', 'SubState',
                        '-p', 'MainPID', '-p', 'UnitFileState', '-p', 'FragmentPath', '-p', 'DropInPaths'])
    fragment = props.get('FragmentPath')
    sources = []
    for source in [fragment] + props.get('DropInPaths', '').split():
        if not source:
            continue
        file = Path(source)
        if file.is_file():
            sources.append({'path': source, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                'schedule': [line for line in file.read_text().splitlines()
                    if line.startswith(('OnCalendar=', 'Persistent=', 'ExecStart=', 'WorkingDirectory='))]})
    out['units'][unit] = dict(props, selected_sources=sources)
print(json.dumps(out, indent=2))
