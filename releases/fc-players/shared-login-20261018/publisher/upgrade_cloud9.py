"""Deploy model images after exact cloud.8 baseline and active-job checks."""
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path

ROOT = Path('/opt/fc27-player-tool')
STAGE = ROOT / 'staging/model-images-20261003'
CURRENT = ROOT / 'current'
ENV = Path('/etc/fc27-player-tool/app.env')
UNIT = Path('/etc/systemd/system/fc27-player-tool.service')
DB = Path('/var/lib/fc27-player-tool/db/control.sqlite3')
VERSION = '2026.10.03-cloud.9'
RELEASE = ROOT / 'releases' / VERSION
BASE_IMAGE = 'fc27-player-tool:2026.10.03-cloud.8'
BASE_IMAGE_ID = 'sha256:e515a924a08f2d136d109f2e41bdaf9eb51b09437f8fa667a8a36d41e13a7759'
IMAGE = 'fc27-player-tool:' + VERSION
MANUAL_FLAG = 'MANUAL_MODEL_IMAGES_ENABLED'

def run(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=180)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def active(unit):
    return run('systemctl','show',unit,'--property=ActiveState').stdout.strip() == 'ActiveState=active'

def healthy():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8901/healthz',timeout=2) as response:
            return response.status == 200
    except Exception:
        return False

def db_state():
    with sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        return {'active':db.execute("SELECT COUNT(*) FROM executions WHERE status IN ('queued','running')").fetchone()[0],
                'executions':db.execute('SELECT COUNT(*) FROM executions').fetchone()[0],
                'legacy':db.execute('SELECT COUNT(*) FROM legacy_unresolved').fetchone()[0]}

def baseline(manifest):
    if CURRENT.resolve().name != manifest['base_version']:
        raise RuntimeError('Concurrent release changed')
    for name,value in manifest['baseline'].items():
        if sha(CURRENT/name) != value:
            raise RuntimeError('Baseline drift: '+name)

def main():
    global STAGE, VERSION, RELEASE, BASE_IMAGE, BASE_IMAGE_ID, IMAGE, MANUAL_FLAG
    if len(sys.argv) == 2:
        STAGE = Path(sys.argv[1]).resolve()
        if STAGE.parent != ROOT / 'staging':
            raise RuntimeError('Stage must be in existing module staging')
    manifest=json.loads((STAGE/'manifest.json').read_text())
    if len(sys.argv) == 2:
        VERSION = manifest['version']; RELEASE = ROOT / 'releases' / VERSION
        if '/' in VERSION or VERSION in {'.', '..'}:
            raise RuntimeError('Invalid release version')
        BASE_IMAGE = 'fc27-player-tool:' + manifest['base_version']
        BASE_IMAGE_ID = manifest['base_image_id']; IMAGE = 'fc27-player-tool:' + VERSION
        MANUAL_FLAG = manifest['manual_flag']
        if MANUAL_FLAG not in {'MANUAL_EXISTING_RECOMMEND_ENABLED', 'FS_SHARED_BACKEND_SESSION'}:
            raise RuntimeError('Only scoped manual recommendation hotfix is allowed')
    if manifest['version'] != VERSION or not healthy():
        raise RuntimeError('Unexpected release/service state')
    baseline(manifest)
    if sha(STAGE/'delta.tar.gz') != manifest['archive_sha256'] or sha(STAGE/'Dockerfile') != manifest['dockerfile_sha256']:
        raise RuntimeError('Package checksum mismatch')
    if run('docker','inspect','--format','{{.Image}}','fc27-player-tool').stdout.strip() != BASE_IMAGE_ID:
        raise RuntimeError('Running image changed')
    if run('docker','image','inspect','--format','{{.Id}}',BASE_IMAGE).stdout.strip() != BASE_IMAGE_ID:
        raise RuntimeError('Base image changed')
    env_text=ENV.read_text(); unit_text=UNIT.read_text()
    config=dict(line.split('=',1) for line in env_text.splitlines() if '=' in line and not line.startswith('#'))
    if config.get('WRITE_ENABLED') != 'false' or config.get('AUTO_WRITE_ENABLED') != 'false' or config.get('MANUAL_NEW_CARDS_ENABLED') != 'true' or config.get('APPROVED_PUBLIC_HTTP_SOURCE') != 'http://139.28.18.234:8001':
        raise RuntimeError('Source/new-card policy changed')
    shared_active = MANUAL_FLAG == 'FS_SHARED_BACKEND_SESSION' and config.get(MANUAL_FLAG) == 'true'
    if (MANUAL_FLAG in config and not shared_active) or (MANUAL_FLAG == 'MANUAL_EXISTING_RECOMMEND_ENABLED' and config.get('MANUAL_MODEL_IMAGES_ENABLED') != 'true') or unit_text.count(BASE_IMAGE) != 1 or '--user 992:987' not in unit_text or 'price-writer.lock,readonly' not in unit_text:
        raise RuntimeError('Unexpected configuration/unit')
    if shared_active and 'src=/run/fs-player-session,dst=/run/fs-player-session,readonly' not in unit_text:
        raise RuntimeError('Shared-session mount changed')
    if len(sys.argv) == 2 and (sha(ENV) != manifest['base_env_sha256'] or sha(UNIT) != manifest['base_unit_sha256']):
        raise RuntimeError('Approved configuration baseline changed')
    if MANUAL_FLAG == 'FS_SHARED_BACKEND_SESSION' and config.get('MANUAL_EXISTING_RECOMMEND_ENABLED') != 'true':
        raise RuntimeError('Existing recommendation scope changed')
    before=db_state()
    if before['active']:
        raise RuntimeError('Active job; retry after completion')
    env_sha,unit_sha=sha(ENV),sha(UNIT)
    expected={**manifest['baseline'],**manifest['files']}
    if RELEASE.exists() and (RELEASE.is_symlink() or any(not(RELEASE/name).is_file() or sha(RELEASE/name)!=value for name,value in expected.items())):
        raise RuntimeError('Prepared release differs')
    RELEASE.mkdir(mode=0o755,exist_ok=True)
    for name in manifest['baseline']:
        path=RELEASE/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(CURRENT/name,path)
    with tarfile.open(STAGE/'delta.tar.gz','r:gz') as archive:
        members=archive.getmembers()
        if len(members)!=len(manifest['files']) or {item.name for item in members}!=set(manifest['files']):
            raise RuntimeError('Delta members differ')
        if any(not item.isfile() or item.name.startswith('/') or '..' in Path(item.name).parts for item in members):
            raise RuntimeError('Unsafe delta')
        archive.extractall(RELEASE)
    if any(sha(RELEASE/name)!=value for name,value in expected.items()):
        raise RuntimeError('Release SHA differs')
    (RELEASE/'source_manifest.json').write_text(json.dumps({'version':VERSION,'files':expected},ensure_ascii=False,indent=2)+'\n')
    shutil.copy2(STAGE/'Dockerfile',RELEASE/'Dockerfile')
    run('docker','build','--network=none','--tag',IMAGE,str(RELEASE))
    run('docker','run','--rm','--network=none','--entrypoint','python3',IMAGE,'-B','-c','import player_web.main; import PIL; assert PIL.__version__ == "9.0.1"')
    backup=ROOT/'backups'/(VERSION+'-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
    backup.mkdir(parents=True,mode=0o700)
    for source,name in ((ENV,'app.env'),(UNIT,'fc27-player-tool.service')):
        shutil.copy2(source,backup/name);os.chmod(backup/name,0o600)
    candidate=backup/'candidate.env';candidate.write_text(env_text if shared_active else env_text.rstrip()+'\n'+MANUAL_FLAG+'=true\n');os.chmod(candidate,0o600)
    if shared_active and sha(candidate) != sha(ENV):
        raise RuntimeError('Existing policy must remain byte-identical')
    run('docker','run','--rm','--network=none','--env-file',str(candidate),'--entrypoint','python3',IMAGE,'-B','-c',
        'from player_web.settings import Settings; s=Settings.from_env(); assert s.model_image_write_enabled and s.new_card_write_enabled and s.http_source_approved and not s.write_enabled')
    if MANUAL_FLAG == 'MANUAL_EXISTING_RECOMMEND_ENABLED':
        run('docker','run','--rm','--network=none','--env-file',str(candidate),'--entrypoint','python3',IMAGE,'-B','-c',
            'from player_web.settings import Settings; s=Settings.from_env(); assert s.existing_action_write_enabled("recommend_enable") and not any(s.existing_action_write_enabled(a) for a in ("recommend_disable","add_tags","remove_tags","unlist"))')
    switched=False;timer_active=active('fc27-player-collect.timer')
    try:
        baseline(manifest)
        if sha(ENV)!=env_sha or sha(UNIT)!=unit_sha or db_state()['active']:
            raise RuntimeError('Concurrent configuration/job changed')
        run('systemctl','stop','fc27-player-collect.timer')
        if active('fc27-player-collect.service'):
            raise RuntimeError('Collection in progress; retry later')
        baseline(manifest)
        if sha(ENV)!=env_sha or sha(UNIT)!=unit_sha or db_state()['active']:
            raise RuntimeError('Concurrent configuration/job changed before switch')
        run('systemctl','stop','fc27-player-tool.service');switched=True
        with sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True) as source,sqlite3.connect(str(backup/'control.sqlite3')) as target:
            source.backup(target)
            if target.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                raise RuntimeError('Backup check failed')
        os.chmod(backup/'control.sqlite3',0o600)
        shutil.copy2(candidate,ENV)
        next_unit = unit_text.replace(BASE_IMAGE,IMAGE)
        if MANUAL_FLAG == 'FS_SHARED_BACKEND_SESSION' and not shared_active:
            mount = ' --mount type=bind,src=/run/fs-player-session,dst=/run/fs-player-session,readonly '
            if '/run/fs-player-session' in unit_text:
                raise RuntimeError('Unexpected existing shared-session mount')
            next_unit = next_unit.replace(' ' + IMAGE, mount + IMAGE)
            next_unit = next_unit.replace('After=network-online.target docker.service',
                                          'After=network-online.target docker.service fc27-p2pah-session.service')
            next_unit = next_unit.replace('Wants=network-online.target docker.service',
                                          'Wants=network-online.target docker.service fc27-p2pah-session.service')
        UNIT.write_text(next_unit)
        run('systemctl','daemon-reload');run('systemctl','start','fc27-player-tool.service')
        for attempt in range(30):
            if healthy():break
            time.sleep(1)
        else:raise RuntimeError('New health failed')
        link=ROOT/'current.cloud9.pending';link.symlink_to(RELEASE);os.replace(link,CURRENT)
        if timer_active:run('systemctl','start','fc27-player-collect.timer')
        after=db_state()
        if after!=before:raise RuntimeError('Execution or legacy state changed')
        print(json.dumps({'deployed':VERSION,'backup':str(backup),'source_sha':expected,'changed_files':list(manifest['files']),
                          'before':before,'after':after,'product_writes':0,'global_write':False,'manual_model_images':True,'manual_new_cards':True,'manual_flag':MANUAL_FLAG}))
    except Exception:
        if switched:
            run('systemctl','stop','fc27-player-tool.service')
            shutil.copy2(backup/'app.env',ENV);shutil.copy2(backup/'fc27-player-tool.service',UNIT)
            link=ROOT/'current.cloud9.rollback';link.symlink_to(ROOT/'releases'/manifest['base_version']);os.replace(link,CURRENT)
            run('systemctl','daemon-reload');run('systemctl','start','fc27-player-tool.service')
        if timer_active:run('systemctl','start','fc27-player-collect.timer')
        raise

if __name__=='__main__':
    with open(ROOT/'deployment.lock','a') as handle:
        fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        main()
