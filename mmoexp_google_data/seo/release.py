"""SEO-only extension of FS's frozen CAS/locks/backups/rollback publisher."""
import hashlib
import json
import re
import subprocess
import sys
import types
from pathlib import Path

SCOPE = 'fs-seo-daily-four-games-v1'
PIN = '5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357'
FORMAL = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
NAV = '/var/www/dashboard/fs-home/navigation.json'
UNITS = ('fs-seo-web.service','fs-seo-daily.service','fs-seo-daily.timer')


def targets(manifest):
    package = manifest.get('package','')
    if not re.fullmatch(r'seo-daily-[a-f0-9]{16}',package):
        raise ValueError('SEO_PACKAGE_REQUIRED')
    result = {'config.json':'/etc/fs-seo/config.json','routes.conf':FORMAL,'navigation.json':NAV,
              **{'units/'+n:'/etc/systemd/system/'+n for n in UNITS},
              **{'ui/'+n:'/var/lib/fs-navigation-formal-static/'+package+'/'+n for n in ('index.html','seo.css','app.mjs','model.mjs','ai.mjs','fs-tokens.css','fs-theme.js')}}
    for row in manifest.get('files',[]):
        rel=row.get('candidate','')
        if re.fullmatch(r'runtime/mmoexp_google_data/(?:seo/(?:[a-z_]+\.py|calendar\.fc27\.user-provided\.json)|details/(?:collect_details\.py|game_dimensions\.py|game_mapping_20261019\.json))',rel):
            result[rel]='/opt/fs-seo/releases/'+package+'/'+rel[len('runtime/'):]
    return result


def publisher(stage, manifest):
    frozen=Path(stage)/'release_navigation_base.py';raw=frozen.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PIN:
        raise ValueError('FROZEN_FS_PUBLISHER_DRIFT')
    source=raw.decode('utf-8');needle='(QUERY_SCOPE,TRAFFIC_SCOPE,'
    if source.count(needle)!=2:
        raise ValueError('FS_ACTIVATION_SEAM_CHANGED')
    b=types.ModuleType('seo_frozen_fs_publisher');b.__file__=str(frozen);b.SEO_SCOPE=SCOPE
    exec(compile(source.replace(needle,'(SEO_SCOPE,QUERY_SCOPE,TRAFFIC_SCOPE,'),str(frozen),'exec'),b.__dict__)
    allowed=targets(manifest)
    original_validate,original_guards,original_atomic=b.validate,b.guards,b.atomic
    b.expected_files=lambda m:set(allowed) if m.get('scope')==SCOPE else set()
    b.target_for=lambda rel:allowed[rel]
    def validate(m, stage):
        if m.get('scope')!=SCOPE or m.get('businessWrites') is not False or m.get('aiProviderConfigured') is not False or m.get('seoTimerOnly') is not True:
            raise ValueError('SEO_RELEASE_SCOPE_INVALID')
        config=json.loads((Path(stage)/'candidate/config.json').read_text())
        if any(config.get(k)!=v for k,v in dict(data_root='/var/lib/fs-seo',control_root='/var/lib/fs-seo-control',ai_root='/var/lib/fs-seo-ai').items()):
            raise ValueError('SEO_OWNED_DATA_ROOT_REQUIRED')
        if config.get('sources',{}).get('admin') is not True or config.get('sources',{}).get('orders'):
            raise ValueError('NATIVE_ADMIN_ESTIMATE_REQUIRED')
        return original_validate(m, stage)
    def guards(m, root):
        original_guards(m,root)
        for target in allowed.values():
            path=b.rooted(root,target);b.no_target_link(path)
            for item in (path,*path.parents):
                if item.exists() and (item.stat().st_uid!=0 or item.stat().st_gid!=0 or item.stat().st_mode&0o022):
                    raise ValueError('UNSAFE_SEO_RELEASE_BOUNDARY')
                if item==root:break
        state=subprocess.run(['systemctl','is-active','fs-seo-daily.service'],stdout=subprocess.PIPE,universal_newlines=True).stdout.strip()
        if state in ('active','activating','deactivating','reloading'):
            raise ValueError('SEO_BATCH_BUSY_DEFER_RELEASE')
        if Path('/etc/localtime').read_bytes()!=Path('/usr/share/zoneinfo/Asia/Shanghai').read_bytes():
            raise ValueError('FS_TIMER_TIMEZONE_MUST_BE_SHANGHAI')
    def atomic(path,data,mode=0o644):
        return original_atomic(path,data,0o600 if str(path).endswith('/etc/fs-seo/config.json') else mode)
    def restart(m,fence=None):
        if m.get('scope')!=SCOPE:
            raise ValueError('UNEXPECTED_SEO_ACTIVATION')
        subprocess.run(['nginx','-t'],check=True)
        if Path('/etc/systemd/system/fs-seo-web.service').exists():
            for name in ('fs-seo','fs-seo-control','fs-seo-ai'):
                Path('/var/lib',name).mkdir(mode=0o700,exist_ok=True)
            subprocess.run(['systemctl','daemon-reload'],check=True)
            subprocess.run(['systemctl','enable','fs-seo-web.service'],check=True)
            subprocess.run(['systemctl','restart','fs-seo-web.service'],check=True)
            subprocess.run(['systemctl','enable','--now','fs-seo-daily.timer'],check=True)
            subprocess.run(['systemctl','is-active','--quiet','fs-seo-web.service','fs-seo-daily.timer'],check=True)
        else:
            for unit in ('fs-seo-daily.timer','fs-seo-web.service'):
                state=subprocess.run(['systemctl','is-active',unit],stdout=subprocess.PIPE,universal_newlines=True).stdout.strip()
                if state not in ('active','activating','deactivating','reloading','inactive','failed','unknown'):
                    raise ValueError('SEO_ROLLBACK_UNIT_STATE_UNKNOWN')
                if state not in ('inactive','unknown'):
                    subprocess.run(['systemctl','stop',unit],check=True)
                group='timers' if unit.endswith('.timer') else 'multi-user'
                link=Path('/etc/systemd/system/'+group+'.target.wants/'+unit)
                if link.is_symlink():
                    if str(link.readlink())!='/etc/systemd/system/'+unit:
                        raise ValueError('SEO_ENABLE_LINK_DRIFT')
                    link.unlink()
            subprocess.run(['systemctl','daemon-reload'],check=True)
        subprocess.run(['systemctl','reload','nginx.service'],check=True)
        subprocess.run(['systemctl','is-active','--quiet','nginx.service'],check=True)
    b.validate,b.guards,b.atomic,b.restart_for=validate,guards,atomic,restart
    return b


def main():
    stage=Path(__file__).resolve().parent;raw=(stage/'manifest.json').read_bytes();manifest=json.loads(raw)
    sha=hashlib.sha256(raw).hexdigest();b=publisher(stage,manifest)
    if sys.argv[1]=='inspect':result=b.inspect(manifest,stage)
    elif sys.argv[1]=='apply':
        if len(sys.argv)!=4 or sys.argv[2]!=sha:
            raise ValueError('REVIEWED_MANIFEST_SHA_REQUIRED')
        result=b.apply(manifest,stage,sha,raw,sys.argv[3])
    elif sys.argv[1]=='rollback':result=b.rollback(Path(sys.argv[2]),sys.argv[3])
    else:raise ValueError('INVALID_SEO_RELEASE_ACTION')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
