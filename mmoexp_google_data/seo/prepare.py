"""Build this SEO module's immutable release and exact FS publisher manifest."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from .retention import ResourcePolicy

FORMAL = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
NAV = '/var/www/dashboard/fs-home/navigation.json'
SCOPE = 'fs-seo-daily-four-games-v1'
PIN = '5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357'
UNITS = ('fs-seo-web.service','fs-seo-daily.service','fs-seo-daily.timer')


def units(runtime):
    common = '\nAfter=network.target\n\n[Service]\nUser=root\nWorkingDirectory='+runtime+'\nEnvironment=PYTHONUNBUFFERED=1\nEnvironment=PYTHONDONTWRITEBYTECODE=1\nUMask=0077\nNoNewPrivileges=true\nPrivateTmp=true\nProtectSystem=full\nProtectHome=true\nReadOnlyDirectories=/opt\nMemoryAccounting=true\nCPUAccounting=true\nCPUQuota=100%\nNice=10\n'
    python = '/opt/mmoexp-marketing/venv-ssl/bin/python -B -m mmoexp_google_data.seo.'
    return {
        'fs-seo-web.service':'[Unit]\nDescription=FS SEO frozen snapshot API'+common+'Type=simple\nMemoryLimit=2G\nExecStart='+python+'web --config /etc/fs-seo/config.json\nRestart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=multi-user.target\n',
        'fs-seo-daily.service':'[Unit]\nDescription=FS SEO single nightly base batch'+common+'Type=oneshot\nEnvironmentFile=-/etc/fs-seo/brightdata.env\nMemoryLimit=4G\nTimeoutStartSec=0\nExecStart='+python+'runtime --config /etc/fs-seo/config.json\n',
        'fs-seo-daily.timer':'[Unit]\nDescription=FS SEO four games one daily batch\n\n[Timer]\nOnCalendar=*-*-* 03:20:00\nAccuracySec=1s\nPersistent=false\nUnit=fs-seo-daily.service\n\n[Install]\nWantedBy=timers.target\n'
    }


def routes(package, assets, port):
    url = '/dashboard/analytics/seo/'
    static = '/var/lib/fs-navigation-formal-static/'+package+'/'
    result = ['# >>> FS SEO daily >>>', 'location = '+url.rstrip('/')+' { return 302 '+url+'; }',
              'location = '+url+' { rewrite ^ '+url+'index.html last; }']
    for name in assets:
        mime = '\n    default_type application/javascript;' if name.endswith('.mjs') else ''
        result.append('location = '+url+name+' {\n    if ($request_method !~ ^(GET|HEAD)$) { return 405; }\n    auth_request /__nav_formal_native_session;\n    error_page 401 = @auth_login;\n    alias '+static+name+';\n    disable_symlinks on;\n    expires -1;'+mime+'\n}')
    result.append('location ^~ '+url+'api/v1/ {\n    auth_request /__nav_formal_native_session;\n    proxy_pass http://127.0.0.1:'+str(port)+';\n    proxy_set_header Host $http_host;\n    proxy_set_header Cookie $http_cookie;\n    proxy_set_header Origin $http_origin;\n    proxy_read_timeout 30s;\n    client_max_body_size 16k;\n    proxy_cache off;\n    add_header Cache-Control "no-store" always;\n}')
    result.append('# <<< FS SEO daily <<<\n')
    return '\n'.join(result)


def build(repo, baseline, formal, navigation, config, output):
    repo, output = Path(repo), Path(output)
    if output.exists():
        raise FileExistsError('NEW_RELEASE_DIRECTORY_REQUIRED')
    ResourcePolicy(**config['resource_policy'])
    if not config.get('memory_policy') or config.get('sources',{}).get('admin') is not True:
        raise ValueError('CALIBRATED_NATIVE_ADMIN_CONFIG_REQUIRED')
    if config.get('sources',{}).get('orders'):
        raise ValueError('INITIAL_ESTIMATE_RELEASE_USES_NATIVE_SUMMARY')
    if hashlib.sha256(formal).hexdigest()!=baseline['target_hashes'][FORMAL] or hashlib.sha256(navigation).hexdigest()!=baseline['target_hashes'][NAV]:
        raise ValueError('CAPTURED_BASELINE_HASH_MISMATCH')
    payloads = {}
    for path in sorted((repo/'mmoexp_google_data/seo').glob('*.py')):
        payloads['mmoexp_google_data/seo/'+path.name] = path.read_bytes()
    plan='mmoexp_google_data/seo/calendar.fc27.user-provided.json'
    payloads[plan]=(repo/plan).read_bytes()
    for name in ('collect_details.py','game_dimensions.py','game_mapping_20261019.json'):
        path = 'mmoexp_google_data/details/'+name
        payloads[path] = (repo/path).read_bytes()
    assets = {name:(repo/'ui-system/modules/seo'/name).read_bytes() for name in ('index.html','seo.css','app.mjs','model.mjs','ai.mjs')}
    assets.update({'fs-tokens.css':(repo/'ui-system/tokens/fs-tokens.css').read_bytes(),'fs-theme.js':(repo/'ui-system/adapters/fs-theme.js').read_bytes()})
    version = hashlib.sha256()
    for name,raw in sorted({**payloads,**assets,'config.json':json.dumps(config,sort_keys=True).encode()}.items()):
        version.update(name.encode()+b'\0'+raw)
    package = 'seo-daily-'+version.hexdigest()[:16]
    runtime = '/opt/fs-seo/releases/'+package
    candidates = {**{'runtime/'+k:(runtime+'/'+k,v) for k,v in payloads.items()},
                  **{'ui/'+k:('/var/lib/fs-navigation-formal-static/'+package+'/'+k,v) for k,v in assets.items()},
                  **{'units/'+k:('/etc/systemd/system/'+k,v.encode()) for k,v in units(runtime).items()},
                  'config.json':('/etc/fs-seo/config.json',(json.dumps(config,ensure_ascii=False,indent=2)+'\n').encode())}
    original = formal.decode('utf-8')
    start, end = '# >>> FS SEO daily >>>', '# <<< FS SEO daily <<<'
    replacement = routes(package,assets,config['web_port'])
    if start in original or end in original:
        if original.count(start)!=1 or original.count(end)!=1 or original.index(end)<original.index(start):
            raise ValueError('SEO_ROUTE_MARKERS_INVALID')
        a,b=original.index(start),original.index(end)+len(end)
        amended=original[:a]+replacement.rstrip()+original[b:]
    else:
        amended=original.rstrip()+'\n\n'+replacement
    candidates['routes.conf'] = (FORMAL,amended.encode())
    nav = json.loads(navigation)
    existing=[t for t in nav['tools'] if t['id']=='seo']
    if len(existing)>1 or existing and existing[0].get('path')!='/dashboard/analytics/seo/':
        raise ValueError('SEO_NAVIGATION_ID_CONFLICT')
    section = next(s for s in nav['sections'] if s['id']=='analytics')
    if 'seo' not in section['ids']:
        section['ids'].append('seo')
    if not existing:
        nav['tools'].append(dict(id='seo',label='SEO监控台',path='/dashboard/analytics/seo/',icon='▥',short='四游戏昨日固定数据与成交预估',scope='global-portal',section='analytics',requiredGroup='dashboard',serverGuard='/__nav_formal_native_session'))
    candidates['navigation.json']=(NAV,(json.dumps(nav,ensure_ascii=False,indent=2)+'\n').encode())
    output.mkdir(parents=True)
    files=[]
    for name,(target,raw) in candidates.items():
        path=output/'candidate'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        files.append(dict(candidate=name,target=target,sha256=hashlib.sha256(raw).hexdigest(),beforeSha256=baseline['target_hashes'].get(target)))
    manifest=dict(schemaVersion=1,scope=SCOPE,releaseReady=True,package=package,businessWrites=False,aiProviderConfigured=False,
                  seoTimerOnly=True,files=files,unchangedRequired=baseline['unchangedRequired'],
                  runtimeRequired={unit:dict(ActiveState='active') for unit in ('nginx.service','auth-portal.service','fc-pricing-v3.service','rpg183-link.service')})
    raw=(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    (output/'manifest.json').write_bytes(raw)
    frozen=repo/'releases/fs-dashboard/menu-cache-20261015/native/release_navigation.py'
    if hashlib.sha256(frozen.read_bytes()).hexdigest()!=PIN:
        raise ValueError('FROZEN_PUBLISHER_DRIFT')
    shutil.copyfile(frozen,output/'release_navigation_base.py')
    shutil.copyfile(repo/'mmoexp_google_data/seo/release.py',output/'release.py')
    return dict(package=package,files=len(files),manifest_sha256=hashlib.sha256(raw).hexdigest(),output=str(output))


def main():
    parser=argparse.ArgumentParser()
    for name in ('baseline','formal','navigation','config','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=build(Path(__file__).resolve().parents[2],json.loads(args.baseline.read_text(encoding='utf-8-sig')),
                 args.formal.read_bytes(),args.navigation.read_bytes(),json.loads(args.config.read_text(encoding='utf-8-sig')),args.output)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
