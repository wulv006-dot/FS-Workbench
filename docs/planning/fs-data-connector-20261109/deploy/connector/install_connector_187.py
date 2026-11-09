"""One reviewed first-install transaction. Default is read-only; root owns execution."""
import argparse
from contextlib import ExitStack
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import ssl
import subprocess
import tempfile
import time

HERE=Path(__file__).resolve().parent
UNIT=Path('/etc/systemd/system/fs-data-connector.service')
LOCATIONS=Path('/etc/nginx/fs-data-connector.locations.conf')
VHOST=Path('/etc/nginx/conf.d/iggm-web.conf')
DATA=Path('/var/lib/fs-data-connector')
BACKUP=Path('/var/backups/fs-data-connector/connector-20261109-787b5c0')
GATEWAY=Path('/opt/fs-dashboard-release/release_gateway.py')
GATEWAY_SHA='90cf84524aabcaa13c54aef7f7256fa9ef46a1d9f53eb0fe6165270c5dcbf5e2'
VHOST_SHA='23baaca2bb61bf0c3fd86a7482ef4395b3bf83749c579fbcde917f3f91cfcb71'
ANCHOR=b'include /etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf;'
ADDITION=b'\n    include /etc/nginx/fs-data-connector.locations.conf;'
ORIGINAL_UNITS=('nginx.service','fs-business-range.service','fs-hermes-fc.service')


def sha(raw):return hashlib.sha256(raw).hexdigest()


def run(command):
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
    if result.returncode:
        if BACKUP.is_dir():
            atomic(BACKUP/'last-command-stderr.txt',result.stderr.encode(),0o600)
        raise RuntimeError('command_failed: '+command[0]+' exit='+str(result.returncode))
    return result.stdout


def atomic(path,raw,mode):
    fd,name=tempfile.mkstemp(prefix='.connector-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),mode);stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
        parent=os.open(str(path.parent),os.O_RDONLY)
        try:os.fsync(parent)
        finally:os.close(parent)
    finally:
        if os.path.exists(name):os.unlink(name)


def original_state():
    return {'services':{name:run(['systemctl','show',name,'--no-pager','-p','ActiveState','-p','SubState']).splitlines()
                        for name in ORIGINAL_UNITS},
            'timers':run(['systemctl','list-units','--type=timer','--all','--plain','--no-legend','--no-pager']).splitlines()}


def make_vhost(raw):
    if raw.count(ANCHOR)!=1 or b'fs-data-connector.locations.conf' in raw:
        raise ValueError('vhost_anchor_or_existing_connector_changed')
    return raw.replace(ANCHOR,ANCHOR+ADDITION,1)


def unit_bytes(image_id):
    if not isinstance(image_id,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',image_id):raise ValueError('fixed_image_id_required')
    raw=(HERE/'fs-data-connector.service.in').read_bytes()
    if raw.count(b'@IMAGE_ID@')!=1:raise ValueError('unit_template_changed')
    return raw.replace(b'@IMAGE_ID@',image_id.encode())


def locks():
    if sha(GATEWAY.read_bytes())!=GATEWAY_SHA:raise ValueError('existing_publisher_source_changed')
    spec=importlib.util.spec_from_file_location('connector_existing_publisher',GATEWAY)
    gateway=importlib.util.module_from_spec(spec);spec.loader.exec_module(gateway)
    stack=ExitStack()
    try:
        for name in ('fs-navigation-release.lock','fs-dashboard-release.lock'):
            path=Path('/var/lock')/name
            info=path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1:
                raise ValueError('unsafe_existing_release_lock')
            stack.enter_context(gateway.Lock(path))
        return stack
    except BaseException:
        stack.close();raise


def check(image_id):
    unit=unit_bytes(image_id)
    if os.geteuid()!=0:raise ValueError('root_execution_required')
    for path in (UNIT,LOCATIONS):
        if path.exists() or path.is_symlink():raise ValueError('first_install_target_already_exists')
    raw=VHOST.read_bytes()
    if VHOST.is_symlink() or sha(raw)!=VHOST_SHA:raise ValueError('fresh_vhost_baseline_required')
    image=json.loads(run(['docker','image','inspect',image_id]))[0]
    labels=image['Config'].get('Labels') or {}
    if image['Id']!=image_id or labels.get('org.opencontainers.image.revision')!='9c1fac9c4e6c49ef40b4c58cabe75a71e01159b5' or labels.get('fs.purpose')!='readonly-mcp-connector':
        raise ValueError('tested_connector_image_required')
    if DATA.exists():
        info=DATA.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o700:
            raise ValueError('private_oauth_directory_required')
    listeners=run(['ss','-H','-lnt'])
    if re.search(r':8937\s',listeners):raise ValueError('connector_port_occupied')
    snippet=(HERE/'fs-data-connector.locations.conf').read_bytes()
    after=make_vhost(raw)
    return raw,unit,snippet,after


def receipt_write(value):atomic(BACKUP/'receipt.json',json.dumps(value,indent=2).encode(),0o600)


def wait_for_public_routes(read,timeout=10,clock=time.monotonic,sleep=time.sleep):
    # nginx reload returns before every new worker has taken over its public routes.
    deadline=clock()+timeout
    while clock()<deadline:
        statuses=[]
        try:
            for path in ('/.well-known/oauth-authorization-server/connector',
                         '/.well-known/oauth-protected-resource/connector/mcp'):
                remaining=deadline-clock()
                if remaining<=0:break
                statuses.append(read(path,timeout=min(2,remaining))[0])
        except ssl.SSLCertVerificationError:
            raise
        except (OSError,http.client.HTTPException):
            pass
        if statuses==[200,200]:return
        remaining=deadline-clock()
        if remaining>0:sleep(min(.2,remaining))
    raise RuntimeError('public_routes_not_ready_after_reload')


def apply(image_id):
    with locks():
        before,unit,snippet,after=check(image_id)
        if BACKUP.exists():raise ValueError('release_already_recorded_reconcile_same_release')
        BACKUP.mkdir(parents=True,mode=0o700)
        atomic(BACKUP/'vhost.before',before,0o600)
        spec=importlib.util.spec_from_file_location('connector_public_before',HERE/'client_public_probe.py')
        public=importlib.util.module_from_spec(spec);spec.loader.exec_module(public)
        dashboard_before=public.request('/dashboard/')[0]
        if dashboard_before!=302:raise ValueError('original_dashboard_baseline_not_302')
        state=original_state()
        receipt={'status':'prepared','image_id':image_id,'source_commit':'9c1fac9c4e6c49ef40b4c58cabe75a71e01159b5',
            'vhost_before_sha256':sha(before),'vhost_after_sha256':sha(after),'unit_sha256':sha(unit),
            'locations_sha256':sha(snippet),'original_state':state,'dashboard_status_before':dashboard_before,
            'oauth_directory_preserved':True}
        receipt_write(receipt)
        try:
            if not DATA.exists():DATA.mkdir(mode=0o700)
            atomic(UNIT,unit,0o644);atomic(LOCATIONS,snippet,0o644);atomic(VHOST,after,0o644)
            run(['nginx','-t'])
            run(['systemctl','daemon-reload'])
            run(['systemctl','enable','--now','fs-data-connector.service'])
            for attempt in range(50):
                try:
                    c=http.client.HTTPConnection('127.0.0.1',8937,timeout=1)
                    c.request('GET','/.well-known/oauth-authorization-server/connector',headers={'Host':'47.85.224.112'})
                    r=c.getresponse();r.read();c.close()
                    if r.status==200:break
                except OSError:pass
                time.sleep(.2)
            else:raise RuntimeError('new_connector_startup_failed')
            run(['systemctl','reload','nginx.service'])
            wait_for_public_routes(public.request)
            spec=importlib.util.spec_from_file_location('connector_anonymous_smoke',HERE/'connector_smoke.py')
            smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)
            receipt['anonymous_smoke']=smoke.probe()
            receipt['state_after']=original_state()
            receipt['original_services_unchanged']=state['services']==receipt['state_after']['services']
            receipt['original_timers_unchanged']=state['timers']==receipt['state_after']['timers']
            if not receipt['original_services_unchanged']:raise RuntimeError('original_service_state_changed')
            receipt['status']='anonymous_entry_verified';receipt_write(receipt)
            print(json.dumps(receipt,ensure_ascii=False))
        except BaseException as exc:
            receipt.update(status='failed_reconcile_original_release',error_type=type(exc).__name__)
            receipt_write(receipt);raise


def rollback():
    with locks():
        receipt=json.loads((BACKUP/'receipt.json').read_text())
        before=(BACKUP/'vhost.before').read_bytes()
        if sha(before)!=receipt['vhost_before_sha256']:raise ValueError('backup_changed')
        expected={UNIT:(None,receipt['unit_sha256']),LOCATIONS:(None,receipt['locations_sha256']),
                  VHOST:(receipt['vhost_before_sha256'],receipt['vhost_after_sha256'])}
        for path,allowed in expected.items():
            current=sha(path.read_bytes()) if path.exists() else None
            if path.is_symlink() or current not in allowed:raise ValueError('rollback_target_drift')
        if UNIT.exists():run(['systemctl','disable','--now','fs-data-connector.service'])
        atomic(VHOST,before,0o644)
        for path in (UNIT,LOCATIONS):
            if path.exists():path.unlink()
        run(['systemctl','daemon-reload']);run(['nginx','-t']);run(['systemctl','reload','nginx.service'])
        receipt['status']='rolled_back_oauth_preserved';receipt_write(receipt)
        print(json.dumps({'status':receipt['status'],'oauth_directory_preserved':str(DATA)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--image-id');parser.add_argument('--apply',action='store_true')
    parser.add_argument('--rollback',action='store_true');parser.add_argument('--self-check',action='store_true');args=parser.parse_args()
    if args.self_check:
        assert make_vhost(b'server {\n '+ANCHOR+b'\n}').count(ADDITION)==1
        try:unit_bytes('floating-tag')
        except ValueError:pass
        else:raise AssertionError('floating image must fail')
        assert b'@IMAGE_ID@' not in unit_bytes('sha256:'+'a'*64)
        print(json.dumps({'self_check':True,'production_writes':0}))
    elif args.rollback:rollback()
    else:
        check(args.image_id)
        if args.apply:apply(args.image_id)
        else:print(json.dumps({'read_only_plan':True,'production_writes':0,'image_id':args.image_id,
              'vhost':str(VHOST),'new_unit':str(UNIT),'new_locations':str(LOCATIONS),'backup':str(BACKUP)}))
