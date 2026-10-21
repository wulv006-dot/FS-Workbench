"""Root-owned bridge: export sanitized facts; publish only an exact reviewed recipe."""
import json
import os
import re
import shutil
import subprocess
import stat
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from common import age, assess, repair_html, repair_content, sha, MONITOR_BEFORE, feishu_connection
from github_api import GitHub

HERE = Path(__file__).resolve().parent
STATE = Path('/var/lib/fs-hermes-ops')
PROFILE = Path('/var/lib/fs-hermes-fc/profile/ops-watchdog')
BRAIN = Path('/var/www/dashboard/fs-home/brain/index.html')
ASSETS = Path('/var/lib/fs-navigation-formal-static/workspace-native-20261006-561eda9b98e2/ui')
PREFIX = 'releases/fs-dashboard/hermes-ops-20261020/repairs/'

def safe(path):
    for item in (path, *path.parents):
        if item.is_symlink(): raise ValueError('symlink_refused')
    return path

@contextmanager
def parent_fd(path):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = child
        yield fd
    finally: os.close(fd)

def read(path, default=None):
    safe(path)
    if os.name == 'posix' and PROFILE in path.parents:
        try:
            with parent_fd(path) as directory:
                fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                with os.fdopen(fd, 'r', encoding='utf-8') as stream:
                    meta = os.fstat(stream.fileno())
                    if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_size > 1024*1024: raise ValueError('invalid_profile_message')
                    return json.load(stream)
        except FileNotFoundError: return default
    try: return json.loads(path.read_text('utf-8'))
    except FileNotFoundError: return default

def publisher():
    import importlib.util
    source = HERE/'release_navigation_base.py'
    if sha(source.read_bytes()) != '5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357': raise ValueError('publisher_drift')
    spec = importlib.util.spec_from_file_location('_ops_frozen_ui', source)
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    return base

def write(path, value):
    safe(path)
    if os.name == 'posix' and PROFILE in path.parents:
        with parent_fd(path) as directory:
            name = '.ops-' + uuid.uuid4().hex
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(value, stream, ensure_ascii=False, indent=2); stream.flush(); os.fsync(stream.fileno())
                os.replace(name, path.name, src_dir_fd=directory, dst_dir_fd=directory); os.fsync(directory)
            finally:
                try: os.unlink(name, dir_fd=directory)
                except FileNotFoundError: pass
        return
    publisher().atomic(path, json.dumps(value, ensure_ascii=False, indent=2).encode(), 0o600)

def collect(now):
    try: raw = read(Path('/var/lib/fc-ops-readonly-monitor/latest.json'), {})
    except (OSError, ValueError): raw = {}
    issues = assess(raw, now)
    services = {}
    for unit in ('nginx', 'fs-hermes-fc', 'fs-hermes-desktop', 'hermes-dingtalk', 'fc27-cloud-api', 'fc27-cloud-worker'):
        child = subprocess.run(['systemctl', 'is-active', unit], capture_output=True, text=True, timeout=4)
        services[unit] = child.stdout.strip()
        if services[unit] != 'active': issues.append('service_unavailable:' + unit)
    brain = {'repairable': False}
    try:
        before = safe(BRAIN).read_bytes()
        after = repair_html(before)
        if before != after:
            issues.append('brain_ui_dependencies_missing')
            brain = {'repairable': True, 'before_sha256': sha(before), 'after_sha256': sha(after)}
    except (OSError, ValueError): issues.append('brain_ui_unverified')
    monitor_repairable = sha(safe(Path('/opt/fc-ops-readonly-monitor/hooks.py')).read_bytes()) == MONITOR_BEFORE
    if monitor_repairable: issues.append('monitor_known_health_schema_regression')
    # The research API also writes gateway_state.json; use the live gateway's own connection events.
    try:
        owner = subprocess.run(['systemctl','show','hermes-dingtalk','-p','MainPID'], capture_output=True, text=True, timeout=4)
        pid = int(owner.stdout.strip().split('=',1)[1])
        ticks = int(Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()[19])
        boot = int(next(l.split()[1] for l in Path('/proc/stat').read_text().splitlines() if l.startswith('btime ')))
        started_at = boot + ticks / os.sysconf('SC_CLK_TCK')
        previous = read(STATE/'feishu-connection.json', {})
        if previous.get('pid') != pid: previous = {}
        log = (PROFILE.parent/'logs/gateway.log').read_text('utf-8',errors='replace')
        feishu = feishu_connection(log, started_at, previous)
        write(STATE/'feishu-connection.json', {'pid':pid,'started_at':started_at,'state':feishu})
    except (OSError, ValueError, IndexError, StopIteration, subprocess.TimeoutExpired):
        feishu = 'unknown'
    if feishu != 'connected': issues.append('hermes_feishu_disconnected')
    coin = raw.get('coin', {})
    job = coin.get('job', {})
    return {'exported_at': now.isoformat(), 'business_captured_at': raw.get('captured_at'),
            'issues': sorted(set(issues)), 'services': services, 'brain': brain, 'monitor_repairable': monitor_repairable,
            'coin': {'enabled': coin.get('config', {}).get('system_enabled'), 'mode': coin.get('config', {}).get('mode'), 'interval_minutes': coin.get('config', {}).get('interval_minutes'),
                     'job_id': job.get('job_id'), 'status': job.get('status'), 'result': job.get('result'), 'completed_at': job.get('completed_at'), 'next_at': coin.get('schedule', {}).get('next_at')},
            'feishu_state': feishu, 'repair': read(STATE/'repair.json', {})}

def claim_active(request, now):
    claim = read(PROFILE/'claim-codex.json', {})
    try: return claim.get('active') is True and claim.get('owner') == 'codex' and claim.get('incident') == request['incident'] and -60 <= age(claim['claimed_at'], now) <= 3600
    except (KeyError, TypeError, ValueError): return False

def publish_repair(record, github, now):
    commit = record['merge_commit']
    prefix = PREFIX + record['incident'] + '/'
    proof = json.loads(github.file(prefix+'proof.json', commit))
    recipe = record.get('action', 'brain-theme')
    name = 'brain-index.html' if recipe == 'brain-theme' else 'hooks.py'
    target = BRAIN if recipe == 'brain-theme' else Path('/opt/fc-ops-readonly-monitor/hooks.py')
    before = github.file(prefix+'before/'+name, commit)
    after = github.file(prefix+'source/'+name, commit)
    if proof != {'recipe': recipe, 'before': sha(before), 'after': sha(after)} or repair_content(recipe, before) != after:
        raise ValueError('merged_recipe_proof_invalid')
    current = safe(target).read_bytes()
    if current == after:
        return dict(record, status='already_applied_readback_verified', runtime_sha256=sha(current))
    if current != before: raise ValueError('live_baseline_drift')
    stage = safe(STATE/'stages'/record['incident'])
    if stage.exists(): raise ValueError('existing_stage_reconcile_required')
    if recipe == 'monitor-health':
        (stage/'source').mkdir(parents=True, mode=0o700)
        (stage/'source/hooks.py').write_bytes(after)
        shutil.copyfile(HERE/'publish_monitor.py', stage/'publish_monitor.py')
        write(STATE/'repair.json', dict(record, status='publishing', stage=str(stage)))
        result = subprocess.run(['/opt/python39/bin/python3', '-B', str(stage/'publish_monitor.py'), '--apply'], capture_output=True, text=True, timeout=40)
        write(stage/'publisher-result.json', {'exit': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr[-2000:]})
        if result.returncode or target.read_bytes() != after: raise ValueError('monitor_publisher_failed_preserve_receipt')
        return dict(record, status='published_file_readback_verified', runtime_sha256=sha(after), natural_acceptance='next_existing_monitor_tick_pending')
    (stage/'candidate/ui').mkdir(parents=True, mode=0o700)
    (stage/'candidate/ui/brain-index.html').write_bytes(after)
    for name in ('release_ui.py', 'release_navigation_base.py'): shutil.copyfile(HERE/name, stage/name)
    protected = [Path('/var/www/dashboard/index.html'), BRAIN.with_name('brain.css'), BRAIN.with_name('brain.js')] + [ASSETS/n for n in ('fs-tokens.css', 'fs-ui.css', 'fs-theme.js')]
    manifest = {'schemaVersion': 1, 'scope': 'hermes-brain-theme-recovery-20261020', 'releaseReady': True, 'businessWrites': False, 'timersChanged': False, 'runtimeRequired': {},
                'files': [{'candidate': 'ui/brain-index.html', 'target': str(BRAIN), 'beforeSha256': sha(before), 'sha256': sha(after)}],
                'unchangedRequired': [{'path': str(p), 'sha256': sha(safe(p).read_bytes())} for p in protected]}
    write(stage/'approved-manifest.json', manifest)
    raw = (stage/'approved-manifest.json').read_bytes()
    record = dict(record, status='publishing', stage=str(stage))
    write(STATE/'repair.json', record)
    result = subprocess.run(['/opt/python39/bin/python3', '-B', str(stage/'release_ui.py'), 'apply', '--approved-manifest-sha', sha(raw), '--release-id', now.strftime('nav-%Y%m%dT%H%M%SZ')], capture_output=True, text=True, timeout=40)
    write(stage/'publisher-result.json', {'exit': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr[-2000:]})
    if result.returncode or BRAIN.read_bytes() != after: raise ValueError('publisher_failed_or_unknown_preserve_receipt')
    return dict(record, status='published_file_readback_verified', runtime_sha256=sha(after), ui_acceptance='browser_confirmation_pending')

def process(now):
    request = read(PROFILE/'request.json', {})
    if not request: return
    if set(request) != {'incident', 'action', 'created_at'} or not re.fullmatch('[a-f0-9]{16}', str(request['incident'])) or request['action'] not in {'brain-theme', 'monitor-health'}: raise ValueError('unsupported_repair_request')
    record = read(STATE/'repair.json', {})
    if record and record.get('incident') != request['incident'] and record.get('status') not in {'published_file_readback_verified', 'already_applied_readback_verified'}:
        raise ValueError('another_incident_requires_reconciliation')
    if not record or record.get('incident') != request['incident']:
        record = {'incident': request['incident'], 'action': request['action'], 'status': 'waiting_codex', 'observed_at': now.isoformat()}
        write(STATE/'repair.json', record)
    if claim_active(request, now):
        if record['status'] == 'waiting_codex': write(STATE/'repair.json', dict(record, owner='codex'))
        return
    if record['status'] == 'waiting_codex':
        if age(record['observed_at'], now) < 600: return
        target = BRAIN if record['action'] == 'brain-theme' else Path('/opt/fc-ops-readonly-monitor/hooks.py')
        before = safe(target).read_bytes(); after = repair_content(record['action'], before)
        if before == after:
            write(STATE/'repair.json', dict(record, status='already_applied_readback_verified', runtime_sha256=sha(after)))
            return
        github = GitHub('/var/lib/hermes-dingtalk/profile/.config/gh/hosts.yml')
        prefix = PREFIX+request['incident']+'/'
        record.update(status='creating_pr', branch='codex/hermes-auto-'+request['incident'])
        write(STATE/'repair.json', record)
        name = 'brain-index.html' if record['action'] == 'brain-theme' else 'hooks.py'
        files = {prefix+'before/'+name: before, prefix+'source/'+name: after, prefix+'proof.json': json.dumps({'recipe':record['action'],'before':sha(before),'after':sha(after)}, indent=2).encode()}
        pr = github.create_pr(record['branch'], 'fix(hermes-ops): apply reviewed '+record['action']+' recovery', 'Automatic approved exact recovery recipe. No business, permissions, scheduling or pricing changes. Required pr-fast validates exact before/after transformation. Publication remains guarded by current-source CAS and the existing module publisher.', files)
        record.update(pr=pr, url=pr['url'], status='pr_open'); write(STATE/'repair.json', record)
    if record['status'] in {'creating_pr', 'merging', 'publishing'}:
        # A crash at a write boundary is not permission to repeat that write.
        return
    if record['status'] == 'pr_open':
        github = GitHub('/var/lib/hermes-dingtalk/profile/.config/gh/hosts.yml')
        if not github.ready(record['pr']): return
        record['status'] = 'merging'; write(STATE/'repair.json', record)
        response = github.request('PUT', '/pulls/'+str(record['pr']['number'])+'/merge', {'sha': record['pr']['head'], 'merge_method': 'squash'})
        if response.get('merged') is not True: raise ValueError('merge_not_confirmed')
        record.update(status='merged', merge_commit=response['sha']); write(STATE/'repair.json', record)
    if record['status'] == 'merged':
        github = GitHub('/var/lib/hermes-dingtalk/profile/.config/gh/hosts.yml')
        write(STATE/'repair.json', publish_repair(record, github, now))

def main():
    import fcntl
    safe(STATE); STATE.mkdir(mode=0o700, exist_ok=True)
    with safe(STATE/'lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        now = datetime.now(timezone.utc)
        try: process(now)
        except Exception as error:
            record = read(STATE/'repair.json', {})
            write(STATE/'repair.json', dict(record, status='blocked_no_retry', error=type(error).__name__ + ':' + str(error)[:120] if isinstance(error, ValueError) else type(error).__name__, checked_at=now.isoformat()))
        write(PROFILE/'snapshot.json', collect(now))

if __name__ == '__main__': main()
