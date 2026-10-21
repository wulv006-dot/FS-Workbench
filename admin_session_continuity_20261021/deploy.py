"""Server-only, two-phase cutover of the existing global Admin owner."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
from patch_service import transform, continuity, legacy_entry
from session_state import write, safe_token, checked_file

OP = 'fs-admin-continuity-20261021-v1'
BACKUP = Path('/var/backups') / OP
UNIT = Path('/etc/systemd/system/fc27-p2pah-session.service')
BASE = 'fc27-cloud-session:manual-wulv-20261021-v1'
IMAGE = 'fc27-cloud-session:continuity-read90-20261021-v1'
ROLLBACK = 'fc27-cloud-session:continuity-baseline-20261021-v1'
SOURCE_SHA = '27ab5e9b6f263ec711dd61a7cc6348dab755289241c3cc75a4ba8a60143e7100'
HOST_STATE = Path('/run/fs-admin-session-state')


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def local(path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:8767' + path, timeout=20) as response:
        raw = response.read(32769)
        if len(raw) > 32768:
            raise RuntimeError('local_response_excessive')
        return json.loads(raw)


def read_source(path):
    return run('docker', 'exec', 'fc27-p2pah-session', 'cat', path)


def checkpoint():
    health = local('/health')
    value = local('/session/admin-token')
    if not health['ready'] or not value.get('ready') or not safe_token(value.get('token')):
        raise RuntimeError('existing_session_not_ready')
    path = HOST_STATE / 'session.json'
    if path.exists() or path.is_symlink():
        checked_file(path)
        saved = json.loads(path.read_text())
        if (saved.get('token') == value['token'] and
                saved.get('api_base') == 'https://admin-api.p2pah.cn' and
                saved.get('login_attempts') == health['login_attempts'] and
                0 <= time.time() - saved.get('created', 0) <= 1800 and
                safe_token(saved.get('refresh_token'), optional=True)):
            return health
    # No refresh-token export exists in the old service. Never scrape process memory.
    pack = {'version': 1, 'created': time.time(), 'api_base': 'https://admin-api.p2pah.cn',
            'token': value['token'], 'refresh_token': None, 'refresh_age': 0,
            'login_attempts': health['login_attempts']}
    write(pack, HOST_STATE / 'session.json')
    return health


def record(value):
    path = BACKUP / 'receipt.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2))
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def prepare(resume=False):
    original = read_source('/usr/local/bin/p2pah_session_service.py')
    if digest(original.encode()) != SOURCE_SHA:
        raise RuntimeError('active_source_changed')
    unit = UNIT.read_text()
    if unit.count(BASE) != 1 or 'fs-session-state' in unit:
        raise RuntimeError('unit_changed')
    if resume:
        if (BACKUP / 'unit').read_text() != unit or (BACKUP / 'receipt.json').exists():
            raise RuntimeError('prepare_resume_state_changed')
    else:
        BACKUP.mkdir(mode=0o700, exist_ok=False)
        (BACKUP / 'unit').write_text(unit); os.chmod(BACKUP / 'unit', 0o600)
    HOST_STATE.mkdir(mode=0o700, exist_ok=True)
    os.chmod(HOST_STATE, 0o700)
    old_entry = read_source('/usr/local/bin/admin_order_capabilities_20261014/admin_session_entry.py')
    inspect = json.loads(run('docker', 'inspect', 'fc27-p2pah-session'))[0]
    if run('docker', 'image', 'inspect', BASE, '--format', '{{.Id}}').strip() != inspect['Image']:
        raise RuntimeError('base_image_tag_drift')
    for label, source, entry in (('candidate', transform(original), legacy_entry(old_entry)),
                                 ('baseline', continuity(original), old_entry)):
        context = BACKUP / label; context.mkdir(mode=0o700, exist_ok=resume)
        (context / 'p2pah_session_service.py').write_text(source)
        (context / 'admin_session_entry.py').write_text(entry)
        shutil.copy2(Path(__file__).with_name('session_state.py'), context / 'session_state.py')
        (context / 'Dockerfile').write_text(
            'FROM ' + BASE + '\n'
            'COPY p2pah_session_service.py session_state.py /usr/local/bin/\n'
            'COPY admin_session_entry.py /usr/local/bin/admin_order_capabilities_20261014/\n'
            'RUN python3 -m py_compile /usr/local/bin/p2pah_session_service.py /usr/local/bin/session_state.py /usr/local/bin/admin_order_capabilities_20261014/admin_session_entry.py\n')
        subprocess.run(['docker', 'build', '--network=none', '-q', '-t', IMAGE if label == 'candidate' else ROLLBACK, str(context)], check=True)
    health = checkpoint()
    args = ['docker', 'run', '--rm', '--network', 'fc27-cloud-net', '--read-only',
            '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--entrypoint', 'python3']
    for mount in inspect['Mounts']:
        args += ['--mount', 'type=bind,src=' + mount['Source'] + ',dst=' + mount['Destination'] + ('' if mount['RW'] else ',readonly')]
    args += ['--mount', 'type=bind,src=' + str(HOST_STATE) + ',dst=/run/secrets/fs-session-state', IMAGE, '-c',
             "import sys;sys.path.insert(0,'/usr/local/bin');from p2pah_session_service import SessionManager,read_private_config;from session_state import restore;"
             "m=SessionManager(read_private_config());m.login=lambda:(_ for _ in ()).throw(RuntimeError('login_forbidden'));"
             "assert restore(m) and m.status=='ready';assert m.identity_ok(m.token);"
             "print('existing_session_restore_verified_no_login')"]
    subprocess.run(args, check=True, timeout=60)
    record({'operation': OP, 'state': 'PREPARED', 'unit_before': digest(unit.encode()),
            'source_before': SOURCE_SHA, 'source_after': digest(transform(original).encode()),
            'legacy_before': digest(old_entry.encode()), 'legacy_after': digest(legacy_entry(old_entry).encode()),
            'image': IMAGE, 'image_id': run('docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}}').strip(),
            'rollback_image': ROLLBACK, 'login_attempts_before': health['login_attempts'],
            'refresh_token_transferred': False, 'access_token_restored_preflight': True})


def switch():
    receipt = json.loads((BACKUP / 'receipt.json').read_text())
    if receipt['state'] != 'PREPARED' or digest(UNIT.read_bytes()) != receipt['unit_before']:
        raise RuntimeError('cutover_state_changed')
    if digest(read_source('/usr/local/bin/p2pah_session_service.py').encode()) != SOURCE_SHA:
        raise RuntimeError('source_changed_before_cutover')
    health = checkpoint()
    if health.get('active_model_reads') or health.get('active_customer_reads'):
        raise RuntimeError('active_long_query_wait_before_cutover')
    if subprocess.run(['systemctl', 'is-active', 'sales-dashboard-sync'], capture_output=True, text=True).stdout.strip() in ('active', 'activating'):
        raise RuntimeError('sales_sync_busy')
    original = UNIT.read_text()
    updated = original.replace(BASE, IMAGE).replace('--group-add 11028 ',
        '--group-add 11028 --mount type=bind,src=/run/fs-admin-session-state,dst=/run/secrets/fs-session-state ')
    updated = updated.replace('ExecStartPre=/usr/bin/install -d -o root -g 987',
        'ExecStartPre=/usr/bin/install -d -o root -g root -m 700 /run/fs-admin-session-state\nExecStartPre=/usr/bin/install -d -o root -g 987')
    if updated == original or updated.count('dst=/run/secrets/fs-session-state') != 1:
        raise RuntimeError('unit_patch_invalid')
    receipt['state'] = 'CUTOVER_STARTED'; record(receipt)
    temporary = UNIT.with_suffix('.continuity-new')
    temporary.write_text(updated); temporary.chmod(0o644)
    if UNIT.read_text() != original:
        raise RuntimeError('unit_concurrent_change')
    os.replace(temporary, UNIT)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'restart', 'fc27-p2pah-session'], check=True)
    final = None
    for _ in range(45):
        try:
            final = local('/health')
            if final.get('ready'):break
        except (OSError, ValueError):pass
        time.sleep(1)
    if not final or not final.get('ready') or final.get('login_attempts') != health['login_attempts']:
        receipt.update(state='CUTOVER_VERIFICATION_FAILED', health=final); record(receipt)
        raise RuntimeError('cutover_unverified_inspect_original_receipt_before_recovery')
    receipt.update(state='DEPLOYED_READY', health=final, unit_after=digest(UNIT.read_bytes()),
                   checkpoint_mode=oct((HOST_STATE/'session.json').stat().st_mode & 0o777))
    record(receipt)
    print(json.dumps(receipt))


def rollback():
    receipt = json.loads((BACKUP / 'receipt.json').read_text())
    if receipt['state'] != 'DEPLOYED_READY' or digest(UNIT.read_bytes()) != receipt['unit_after']:
        raise RuntimeError('rollback_state_changed')
    checkpoint()
    original = UNIT.read_text()
    if original.count(IMAGE) != 1:
        raise RuntimeError('rollback_image_changed')
    temporary = UNIT.with_suffix('.continuity-rollback')
    temporary.write_text(original.replace(IMAGE, ROLLBACK)); temporary.chmod(0o644)
    receipt['state'] = 'ROLLBACK_STARTED'; record(receipt)
    if UNIT.read_text() != original:
        raise RuntimeError('rollback_concurrent_change')
    os.replace(temporary, UNIT)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'restart', 'fc27-p2pah-session'], check=True)
    receipt['state'] = 'ROLLBACK_RESTARTED_REQUIRES_READBACK'; record(receipt)


if __name__ == '__main__':
    with open('/run/lock/fs-admin-session-unify.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if sys.argv[1:] == ['prepare']:prepare()
        elif sys.argv[1:] == ['resume-prepare']:prepare(resume=True)
        elif sys.argv[1:] == ['switch']:switch()
        elif sys.argv[1:] == ['rollback']:rollback()
        else:raise RuntimeError('expected_prepare_or_switch')
