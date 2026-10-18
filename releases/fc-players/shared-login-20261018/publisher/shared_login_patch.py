"""Scoped companion to the existing Players publisher and shared release locks."""
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = Path('/opt/fc27-player-tool')
SESSION = Path('/opt/fc27-cloud/marketing-session-20261009')
UNIT = Path('/etc/systemd/system/fc27-p2pah-session.service')
SOCKET_DIR = Path('/run/fs-player-session')
OLD_TAG = 'fc27-cloud-session:admin-analysis-20261018-v1'
NEW_TAG = 'fc27-cloud-session:players-shared-20261018-v1'


def load(name, path, expected):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError('publisher_source_drift')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def run(*args, timeout=180):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=timeout).strip()


def image(tag):
    return run('docker', 'image', 'inspect', '-f', '{{.Id}}', tag)


def restart(expected):
    run('systemctl', 'daemon-reload')
    run('systemctl', 'restart', 'fc27-p2pah-session.service')
    for _ in range(90):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8767/health', timeout=2) as response:
                if json.load(response).get('ready') is True:
                    if run('docker', 'inspect', '-f', '{{.Image}}', 'fc27-p2pah-session') != expected:
                        raise RuntimeError('session_image_readback')
                    return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError('session_restart_not_ready')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('inspect', 'apply'))
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--approved-sha')
    args = parser.parse_args()
    raw = args.manifest.read_bytes(); manifest = json.loads(raw)
    stage = args.manifest.parent.resolve()
    if stage.parent != ROOT / 'staging' or manifest['version'] != '2026.10.18-cloud.11':
        raise RuntimeError('unexpected_scope')
    base = load('release_base', HERE/'release_navigation_base.py', '1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de')
    players = load('players_publisher', HERE/'upgrade_cloud9.py', manifest['players_publisher_sha256'])
    session = manifest['session']
    targets = {SESSION/'p2pah_session_service.py': stage/'source/session/p2pah_session_service.py',
               SESSION/'player_session_socket.py': stage/'source/session/player_session_socket.py',
               UNIT: stage/'source/session/fc27-p2pah-session.service'}
    if set(session['before']) != {str(p) for p in targets}:
        raise RuntimeError('unexpected_session_targets')
    for target, source in targets.items():
        base.no_target_link(target); base.no_target_link(source)
        if base.digest(target) != session['before'][str(target)] or base.digest(source) != session['after'][str(target)]:
            raise RuntimeError('session_source_drift')
    if image(OLD_TAG) != session['image_before'] or run('docker','inspect','-f','{{.Image}}','fc27-p2pah-session') != session['image_before']:
        raise RuntimeError('session_image_drift')
    players.baseline(manifest)
    if base.digest(players.ENV) != manifest['base_env_sha256'] or base.digest(players.UNIT) != manifest['base_unit_sha256'] or players.db_state()['active']:
        raise RuntimeError('players_policy_or_job_changed')
    if args.action == 'inspect':
        print(json.dumps({'inspect':'passed','manifest_sha256':hashlib.sha256(raw).hexdigest(),'players_active':0})); return
    if args.approved_sha != hashlib.sha256(raw).hexdigest():
        raise RuntimeError('manifest_sha_required')
    backup = ROOT/'backups'/'shared-login-20261018'
    if backup.exists():
        raise RuntimeError('previous_intent_requires_readback')
    # Build before taking the short shared restart window; no network or packages.
    context = stage/'source/session'
    dockerfile = ('FROM '+OLD_TAG+'\nUSER root\nCOPY p2pah_session_service.py player_session_socket.py /usr/local/bin/\n')
    base.atomic(context/'Dockerfile', dockerfile.encode(), 0o600)
    run('docker','build','--network=none','--pull=false','-t',NEW_TAG,str(context))
    if image(OLD_TAG) != session['image_before']: raise RuntimeError('session_base_changed_during_build')
    built = image(NEW_TAG)
    with ExitStack() as stack:
        stack.enter_context(base.locks(Path('/')))
        fence = base.HermesAdmissionFence(Path('/')); stack.callback(fence.close)
        stack.enter_context(base.model_release_lock({'scope':base.HERMES_UPDATE_SCOPE}, Path('/')))
        stack.enter_context(base.live_lock({'scope':base.HERMES_UPDATE_SCOPE}, Path('/')))
        handle = stack.enter_context(open(ROOT/'deployment.lock','a'))
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB)
        for target in targets:
            if base.digest(target) != session['before'][str(target)]: raise RuntimeError('session_cas_drift')
        players.baseline(manifest)
        if players.db_state()['active']: raise RuntimeError('active_players_write')
        backup.mkdir(mode=0o700)
        before = {str(path):path.read_bytes() if path.exists() else None for path in targets}
        for index, (path, data) in enumerate(before.items()):
            if data is not None: base.atomic(backup/(str(index)+'.before'),data,0o600)
        journal = {'state':'intent','manifest_sha256':args.approved_sha,'image_before':session['image_before'],'image_after':built,'targets':list(before)}
        def record(): base.atomic(backup/'journal.json',json.dumps(journal,indent=2).encode(),0o600)
        record()
        if SOCKET_DIR.is_symlink(): raise RuntimeError('unsafe_socket_directory')
        SOCKET_DIR.mkdir(mode=0o2710,exist_ok=True)
        info=SOCKET_DIR.stat()
        if info.st_uid != 0 or info.st_gid not in (0,987) or any(SOCKET_DIR.iterdir()):
            raise RuntimeError('unexpected_socket_directory')
        os.chown(SOCKET_DIR,0,987); os.chmod(SOCKET_DIR,0o2710)
        changed = False
        try:
            for target, source in targets.items():
                if base.digest(target) != session['before'][str(target)]: raise RuntimeError('session_cas_before_replace')
                base.atomic(target,source.read_bytes(),0o644)
                changed=True
            restart(built)
            journal['state']='session_ready';record()
            # Keep the original Players backup, DB preservation and rollback path.
            sys.argv=[str(HERE/'upgrade_cloud9.py'),str(stage)]
            players.main()
            journal['state']='deployed';record()
            print(json.dumps({'shared_session':'deployed','image':built,'backup':str(backup),'product_writes':0}))
        except Exception:
            journal['state']='failed';record()
            if changed:
                for target in targets:
                    if base.digest(target) not in {session['after'][str(target)],session['before'][str(target)]}:
                        raise RuntimeError('rollback_external_drift')
                for target, data in before.items():
                    if data is None: Path(target).unlink(missing_ok=True)
                    else: base.atomic(Path(target),data,0o644)
                restart(session['image_before'])
                journal['state']='rolled_back';record()
            raise


if __name__ == '__main__':
    main()
