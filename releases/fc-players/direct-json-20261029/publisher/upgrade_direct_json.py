"""Narrow cloud.15 adaptation of deploy/upgrade_cloud9.py; no backend writes."""
import fcntl
import ast
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
from contextlib import closing
from pathlib import Path

ROOT = Path('/opt/fc27-player-tool')
STAGE = ROOT / 'staging/direct-json-20261029'
CURRENT = ROOT / 'current'
ENV = Path('/etc/fc27-player-tool/app.env')
UNIT = Path('/etc/systemd/system/fc27-player-tool.service')
ON_DEMAND = Path('/etc/systemd/system/fc27-player-tool.service.d/on-demand.conf')
DB = Path('/var/lib/fc27-player-tool/db/control.sqlite3')
VERSION = '2026.10.29-cloud.15'
RELEASE = ROOT / 'releases' / VERSION
BASE_IMAGE = 'fc27-player-tool:2026.10.24-cloud.14'
BASE_IMAGE_ID = 'sha256:93fb354e872b337026093ba2b3c5d073c2d14ed34e36b004aad2dde01a638543'
IMAGE = 'fc27-player-tool:' + VERSION
MANUAL_FLAG = 'FS_SHARED_BACKEND_SESSION'
BASE_VERSION = '2026.10.24-cloud.14'
PATCHES = {
    'player_web/shared_session.py': (ROOT / 'patches/20261028/shared_session.py',
        '5d90a37fd5aa7288c8b560dbb8eaf10595addc456e23bbbfeee698670b06ba96'),
    '球员维护工具/admin_client.py': (ROOT / 'patches/20261028/admin_client.py',
        '6ec742637289429935a681352225d9f20b9dce238112b3ae60801d4a5bd76e6f'),
}
ADMIN_TASKS = Path('/var/lib/fc27-player-tool/admin_state/shared/admin_tasks.json')
PRICE_LOCK = Path('/var/lib/fc27-cloud/state/price-writer.lock')
HMAC_TRANSPORT = '''from 球员维护工具.admin_client import AdminAuthError, AdminClient
DC_PROXY_BASE = 'http://127.0.0.1:8912'
DC_PROXY_TOKEN = 'dc-hmac-proxy'
def session_token():
    raise AdminAuthError('FS_SHARED_SESSION_RETIRED')
def shared_client(settings):
    client = AdminClient(DC_PROXY_BASE, get_retries=0)
    client._token = DC_PROXY_TOKEN
    client.verify_identity()
    return client
'''

def validate_transport(text):
    def shape(source):
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
                    node.body.pop(0)
        return ast.dump(tree, include_attributes=False)
    if shape(text) != shape(HMAC_TRANSPORT):
        raise RuntimeError('Candidate must preserve retired-session HMAC transport on primary 8912')

def atomic_text(path, text):
    temporary = path.with_name(path.name + '.direct-json.pending')
    if temporary.exists() or temporary.is_symlink():
        raise RuntimeError('Pending configuration already exists: ' + str(temporary))
    mode = path.stat().st_mode & 0o777
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush(); os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists(): temporary.unlink()

def updated_unit(text):
    if text.count(BASE_IMAGE) != 1:
        raise RuntimeError('Image reference changed')
    if '--user 992:987' not in text or '--memory 2g' not in text or 'price-writer.lock,readonly' not in text:
        raise RuntimeError('Runtime constraints changed')
    result = text.replace(BASE_IMAGE, IMAGE)
    for name, (source, _) in PATCHES.items():
        original = 'src=' + str(source) + ',dst=/app/' + name + ',readonly'
        if text.count(original) != 1:
            raise RuntimeError('Effective patch mount changed: ' + name)
        result = result.replace(original, 'src=' + str(RELEASE/name) + ',dst=/app/' + name + ',readonly')
    return result

def ledger_digest(db, table):
    rows = sorted((list(row) for row in db.execute('SELECT * FROM ' + table)),
                  key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()

def protected_state():
    units = {}
    for name in ('fc-pricing-v3.service', 'fc27-cloud-api.service', 'fc27-p2pah-session.service'):
        result = run('systemctl', 'show', name)
        wanted = {'ActiveState', 'SubState', 'MainPID', 'ExecMainStartTimestamp', 'UnitFileState'}
        units[name] = '\n'.join(sorted(line for line in result.stdout.splitlines()
                                      if '=' in line and line.split('=', 1)[0] in wanted))
    retired = dict(line.split('=', 1) for line in units['fc27-p2pah-session.service'].splitlines() if '=' in line)
    if retired.get('MainPID') != '0' or retired.get('ActiveState') not in {'failed', 'inactive'}:
        raise RuntimeError('Retired session became active')
    info = PRICE_LOCK.stat()
    return {'units': units, 'price_lock': [info.st_dev, info.st_ino, info.st_mode]}

def verify_image_sources(image, expected, *, container=False):
    check = ('import hashlib,json,pathlib; expected=json.loads(' + repr(json.dumps(expected, ensure_ascii=False)) + '); '
             'actual={n:hashlib.sha256((pathlib.Path("/app")/n).read_bytes()).hexdigest() for n in expected}; '
             'assert actual==expected,(actual,expected); print(json.dumps(actual,sort_keys=True))')
    if container:
        return run('docker', 'exec', 'fc27-player-tool', 'python3', '-B', '-c', check).stdout
    return run('docker', 'run', '--rm', '--network=none', '--entrypoint', 'python3', image, '-B', '-c', check).stdout

def verify_bind_sources(*, deployed):
    mounts = json.loads(run('docker','inspect','--format','{{json .Mounts}}','fc27-player-tool').stdout)
    for name, (source, _) in PATCHES.items():
        expected = RELEASE/name if deployed else source
        matches = [item for item in mounts if item['Destination']=='/app/'+name]
        if len(matches)!=1 or matches[0]['Source']!=str(expected) or matches[0]['RW']:
            raise RuntimeError('Effective container bind differs: '+name)

def validate_manifest(manifest):
    if (manifest['version'], manifest['base_version'], manifest['base_image_id'], manifest['manual_flag']) != (VERSION, BASE_VERSION, BASE_IMAGE_ID, MANUAL_FLAG):
        raise RuntimeError('Only exact cloud14 to cloud15 HMAC migration is allowed')
    required = {'VERSION', *PATCHES}
    if not required <= set(manifest['files']):
        raise RuntimeError('Effective HMAC patch missing from delta')
    if not manifest.get('baseline') or not {'VERSION', *PATCHES} <= set(manifest['baseline']):
        raise RuntimeError('Complete release baseline required')
    for name in (*manifest['baseline'], *manifest['files']):
        if not name or name.startswith('/') or '..' in Path(name).parts or '\\' in name:
            raise RuntimeError('Unsafe manifest path')
    for value in (*manifest['baseline'].values(), *manifest['files'].values(), manifest['archive_sha256'], manifest['dockerfile_sha256']):
        if not isinstance(value, str) or len(value)!=64 or any(ch not in '0123456789abcdef' for ch in value):
            raise RuntimeError('Invalid SHA256')
    if manifest.get('base_env_sha256') != '165451691cdb2f0e93590fb1120c488cef85ed3498efaa4df6afdb926ca107ab':
        raise RuntimeError('Approved policy baseline changed')
    if manifest.get('base_unit_sha256') != '12c77da9be6828e97942d6fadd0359e5d828fc805633217a7d0d57db7a5f891c':
        raise RuntimeError('Approved unit baseline changed')
    if manifest.get('base_on_demand_sha256') != 'ce3a5f2195e7f9211663bccd7f75002aefa1bdd1c7efb8269badf8217544a614':
        raise RuntimeError('Approved dropin baseline changed')
    if manifest.get('base_source_manifest_sha256') != '35e82ae4f604cae19d459eb3e4aabd430d3cb9ee341907158e219a177e038e93':
        raise RuntimeError('Approved source manifest changed')

def validate_dockerfile(text):
    if text.splitlines() != [
        'FROM '+BASE_IMAGE, 'USER root', 'WORKDIR /app',
        'COPY player_web /app/player_web',
        'COPY ["球员维护工具", "/app/球员维护工具"]', 'COPY VERSION /app/',
    ]:
        raise RuntimeError('Only exact inherited image source overlay is allowed')

def run(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=180)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def active(unit):
    return run('systemctl','show',unit,'--property=ActiveState').stdout.strip() == 'ActiveState=active'

def healthy():
    try:
        port = 18901 if ON_DEMAND.exists() else 8901
        with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/healthz',timeout=2) as response:
            return response.status == 200
    except Exception:
        return False

def db_state():
    with closing(sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        return {'active':db.execute("SELECT COUNT(*) FROM executions WHERE status IN ('queued','running','waiting_price_lock')").fetchone()[0],
                'executions':db.execute('SELECT COUNT(*) FROM executions').fetchone()[0],
                'legacy':db.execute('SELECT COUNT(*) FROM legacy_unresolved').fetchone()[0],
                'ledger': {table: ledger_digest(db, table) for table in ('executions','execution_items','events','active_scope','legacy_unresolved')},
                'admin_tasks_sha256': sha(ADMIN_TASKS)}

def baseline(manifest):
    if CURRENT.resolve().name != manifest['base_version']:
        raise RuntimeError('Concurrent release changed')
    for name,value in manifest['baseline'].items():
        if sha(CURRENT/name) != value:
            raise RuntimeError('Baseline drift: '+name)
    if sha(CURRENT/'source_manifest.json') != manifest['base_source_manifest_sha256']:
        raise RuntimeError('Source manifest changed')
    source_manifest = json.loads((CURRENT/'source_manifest.json').read_text(encoding='utf-8'))
    if source_manifest.get('files') != manifest['baseline'] or source_manifest.get('version') != BASE_VERSION:
        raise RuntimeError('Release baseline is incomplete')
    for source, value in PATCHES.values():
        if sha(source) != value:
            raise RuntimeError('Effective patch changed: ' + str(source))
    if sha(ENV) != manifest['base_env_sha256'] or sha(UNIT) != manifest['base_unit_sha256']:
        raise RuntimeError('Approved config changed')
    if not ON_DEMAND.is_file() or sha(ON_DEMAND) != manifest['base_on_demand_sha256']:
        raise RuntimeError('Approved on-demand config changed')
    if {p.name for p in ON_DEMAND.parent.glob('*.conf')} != {'on-demand.conf'}:
        raise RuntimeError('Unexpected Players dropin')

def main():
    global STAGE
    if len(sys.argv) not in (1, 2):
        raise RuntimeError('Expected zero or one stage argument')
    if len(sys.argv) == 2:
        STAGE = Path(sys.argv[1]).resolve()
        if STAGE.parent != ROOT / 'staging':
            raise RuntimeError('Stage must be in existing module staging')
    manifest=json.loads((STAGE/'manifest.json').read_text(encoding='utf-8'))
    validate_manifest(manifest)
    protected_before = protected_state()
    demand_socket_active = ON_DEMAND.exists() and active('fc27-player-demand.socket')
    if not active('fc27-player-tool.service'):
        raise RuntimeError('Expected active Players service; no implicit wake during deploy')
    if manifest['version'] != VERSION or not healthy():
        raise RuntimeError('Unexpected release/service state')
    baseline(manifest)
    if sha(STAGE/'delta.tar.gz') != manifest['archive_sha256'] or sha(STAGE/'Dockerfile') != manifest['dockerfile_sha256']:
        raise RuntimeError('Package checksum mismatch')
    validate_dockerfile((STAGE/'Dockerfile').read_text(encoding='utf-8'))
    if run('docker','inspect','--format','{{.Image}}','fc27-player-tool').stdout.strip() != BASE_IMAGE_ID:
        raise RuntimeError('Running image changed')
    if run('docker','image','inspect','--format','{{.Id}}',BASE_IMAGE).stdout.strip() != BASE_IMAGE_ID:
        raise RuntimeError('Base image changed')
    verify_bind_sources(deployed=False)
    verify_image_sources(BASE_IMAGE, {**manifest['baseline'], **{name:value for name,(_,value) in PATCHES.items()}}, container=True)
    env_text=ENV.read_text(encoding='utf-8'); unit_text=UNIT.read_text(encoding='utf-8')
    demand_text=ON_DEMAND.read_text(encoding='utf-8') if ON_DEMAND.exists() else None
    if demand_text is not None and demand_text.count(BASE_IMAGE) != 1:
        raise RuntimeError('On-demand image reference changed')
    config=dict(line.split('=',1) for line in env_text.splitlines() if '=' in line and not line.startswith('#'))
    if config.get('WRITE_ENABLED') != 'false' or config.get('AUTO_WRITE_ENABLED') != 'false' or config.get('MANUAL_NEW_CARDS_ENABLED') != 'true' or config.get('APPROVED_PUBLIC_HTTP_SOURCE') != 'http://139.28.18.234:8001':
        raise RuntimeError('Source/new-card policy changed')
    shared_active = MANUAL_FLAG == 'FS_SHARED_BACKEND_SESSION' and config.get(MANUAL_FLAG) == 'true'
    if (MANUAL_FLAG in config and not shared_active) or (MANUAL_FLAG == 'MANUAL_EXISTING_RECOMMEND_ENABLED' and config.get('MANUAL_MODEL_IMAGES_ENABLED') != 'true') or unit_text.count(BASE_IMAGE) != 1 or '--user 992:987' not in unit_text or 'price-writer.lock,readonly' not in unit_text:
        raise RuntimeError('Unexpected configuration/unit')
    if not shared_active:
        raise RuntimeError('Existing manual HMAC transport flag must remain enabled')
    next_unit = updated_unit(unit_text)
    next_demand = updated_unit(demand_text) if demand_text is not None else None
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
    if (RELEASE/'VERSION').read_text(encoding='utf-8').strip() != VERSION:
        raise RuntimeError('Released VERSION differs')
    validate_transport((RELEASE/'player_web/shared_session.py').read_text(encoding='utf-8'))
    (RELEASE/'source_manifest.json').write_text(json.dumps({'version':VERSION,'files':expected},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    shutil.copy2(STAGE/'Dockerfile',RELEASE/'Dockerfile')
    run('docker','build','--network=none','--tag',IMAGE,str(RELEASE))
    run('docker','run','--rm','--network=none','--entrypoint','python3',IMAGE,'-B','-c','import player_web.main; import PIL; assert PIL.__version__ == "9.0.1"')
    verify_image_sources(IMAGE, expected)
    backup=ROOT/'backups'/(VERSION+'-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
    backup.mkdir(parents=True,mode=0o700)
    for source,name in ((ENV,'app.env'),(UNIT,'fc27-player-tool.service')):
        shutil.copy2(source,backup/name);os.chmod(backup/name,0o600)
    if demand_text is not None:
        (backup/'on-demand.conf').write_text(demand_text,encoding='utf-8')
    candidate=backup/'candidate.env';candidate.write_bytes(ENV.read_bytes());os.chmod(candidate,0o600)
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
        if sha(ENV)!=env_sha or sha(UNIT)!=unit_sha or db_state()!=before or protected_state()!=protected_before or (ON_DEMAND.read_text(encoding='utf-8') if ON_DEMAND.exists() else None)!=demand_text:
            raise RuntimeError('Concurrent configuration/job changed')
        run('systemctl','stop','fc27-player-collect.timer')
        if active('fc27-player-collect.service'):
            raise RuntimeError('Collection in progress; retry later')
        baseline(manifest)
        if sha(ENV)!=env_sha or sha(UNIT)!=unit_sha or db_state()!=before or protected_state()!=protected_before or (ON_DEMAND.read_text(encoding='utf-8') if ON_DEMAND.exists() else None)!=demand_text:
            raise RuntimeError('Concurrent configuration/job changed before switch')
        if demand_socket_active:
            run('systemctl','stop','fc27-player-demand.socket')
        switched=True
        run('systemctl','stop','fc27-player-tool.service')
        if db_state()!=before or protected_state()!=protected_before:
            raise RuntimeError('Ledger/protected runtime changed while stopping Players')
        with closing(sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(str(backup/'control.sqlite3'))) as target:
            source.backup(target)
            if target.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                raise RuntimeError('Backup check failed')
        os.chmod(backup/'control.sqlite3',0o600)
        # Current manual policy is already enabled; ENV remains byte-identical.
        atomic_text(UNIT, next_unit)
        if demand_text is not None:
            atomic_text(ON_DEMAND, next_demand)
        run('systemctl','daemon-reload');run('systemctl','start','fc27-player-tool.service')
        for attempt in range(30):
            if healthy():break
            time.sleep(1)
        else:raise RuntimeError('New health failed')
        verify_image_sources(IMAGE, expected, container=True)
        verify_bind_sources(deployed=True)
        if sha(ENV)!=env_sha or protected_state()!=protected_before:
            raise RuntimeError('Policy/protected runtime changed')
        link=ROOT/'current.direct-json.pending';link.symlink_to(RELEASE);os.replace(link,CURRENT)
        if demand_socket_active:
            run('systemctl','start','fc27-player-demand.socket')
        if timer_active:run('systemctl','start','fc27-player-collect.timer')
        after=db_state()
        if after!=before:raise RuntimeError('Execution or legacy state changed')
        print(json.dumps({'deployed':VERSION,'backup':str(backup),'source_sha':expected,'changed_files':list(manifest['files']),
                          'before':before,'after':after,'product_writes':0,'global_write':False,'manual_model_images':True,'manual_new_cards':True,'manual_flag':MANUAL_FLAG}))
    except Exception:
        if switched:
            run('systemctl','stop','fc27-player-tool.service')
            atomic_text(ENV, (backup/'app.env').read_text(encoding='utf-8'));atomic_text(UNIT,(backup/'fc27-player-tool.service').read_text(encoding='utf-8'))
            if demand_text is not None:
                atomic_text(ON_DEMAND,(backup/'on-demand.conf').read_text(encoding='utf-8'))
            link=ROOT/'current.direct-json.rollback';link.symlink_to(ROOT/'releases'/manifest['base_version']);os.replace(link,CURRENT)
            run('systemctl','daemon-reload');run('systemctl','start','fc27-player-tool.service')
        if demand_socket_active:
            run('systemctl','start','fc27-player-demand.socket')
        if timer_active:run('systemctl','start','fc27-player-collect.timer')
        raise

if __name__=='__main__':
    with open(ROOT/'deployment.lock','a') as handle:
        fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        main()
