"""Build a new immutable version from an explicit previously verified package.
No environment guessing or server reads; a fresh manifest CAS protects publication.
"""
from pathlib import Path
import argparse,hashlib,json,shutil,re
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--previous',required=True,type=Path);p.add_argument('--activate',action='store_true');p.add_argument('--controller-sha');p.add_argument('--home-sha');a=p.parse_args()
home_sha=a.home_sha or hashlib.sha256((ROOT/'baseline/ui/home.html').read_bytes()).hexdigest()
if not re.fullmatch(r'[a-f0-9]{64}',home_sha):raise SystemExit('verified home sha required')
controller_sha=a.controller_sha or hashlib.sha256((ROOT/'source/backend/controller.py').read_bytes()).hexdigest()
if not re.fullmatch(r'[a-f0-9]{64}',controller_sha):raise SystemExit('verified controller sha required')
previous=a.previous.resolve();oldformal=(previous/'candidate/formal.conf').read_bytes();oldhub=(previous/'candidate/hubnav.js').read_bytes()
files={p.name:p.read_bytes() for p in (ROOT/'source/frontend').iterdir() if p.is_file() and p.name!='targets.json'}
DATA_SHA='77b32a25489148646ca7e7c5a2e2e17428212dd821dbef8deb743182d65aa57e'
phase='production-entry' if a.activate else 'protected-preview-only'
rid='workspace-native-20261006-'+hashlib.sha256((phase+DATA_SHA+controller_sha+home_sha).encode()+b''.join(k.encode()+files[k] for k in sorted(files))).hexdigest()[:12]
stage=ROOT/'release'/('static-'+rid)
if stage.exists():raise SystemExit('immutable stage exists')
(stage/'assets').mkdir(parents=True);(stage/'candidate').mkdir()
for name,data in files.items():(stage/'assets'/name).write_bytes(data)
(stage/'candidate/hubnav.js').write_bytes(oldhub)
new=oldformal.decode();preview='/dashboard/__preview/management-v2-20261015/'
def location(path,target,html=False):
 inject='<script defer src="/__hub/hubnav.js?v=management-v2-20261015"></script></body>' if html else '</body>'
 inject=inject.replace('"','\\"')
 return ('location = '+path+' {\n    if ($request_method !~ ^(GET|HEAD)$) { return 405; }\n    auth_request /__nav_formal_native_session;\n    error_page 401 = @auth_login;\n    alias '+target+';\n    disable_symlinks on;\n    expires -1;\n    sub_filter "</body>" "'+inject+'";\n    add_header Cache-Control "no-store" always;\n    add_header X-Content-Type-Options "nosniff" always;\n    add_header X-Robots-Tag "noindex, nofollow" always;\n    add_header Referrer-Policy "same-origin" always;\n}\n')
def update(path,target,html=False):
 global new
 block=location(path,target,html);pattern=r'(?ms)^location = '+re.escape(path)+r' \{\n.*?^\}\n'
 if re.search(pattern,new):new,n=re.subn(pattern,lambda _:block,new);assert n==1
 else:new+='\n'+block
rows=[]
for name,data in sorted(files.items()):
 target='/var/lib/fs-navigation-formal-static/'+rid+'/management/'+name
 update(preview+name,target,name.endswith('.html'))
 update('/dashboard/workspace-assets/'+rid+'/management/'+name,target,name.endswith('.html'))
 if a.activate:update('/dashboard/management/'+name,target,name.endswith('.html'))
 rows.append({'candidate':'assets/'+name,'target':target,'beforeSha256':None,'sha256':hashlib.sha256(data).hexdigest()})
target='/var/lib/fs-navigation-formal-static/'+rid+'/management/targets.json'
update(preview+'targets.json',target)
update('/dashboard/workspace-assets/'+rid+'/management/targets.json',target)
if a.activate:update('/dashboard/management/targets.json',target)
rows.append({'candidate':'assets/targets.json','target':target,'beforeSha256':None,'sha256':DATA_SHA})
public='/var/lib/fs-boss-workspaces/public/management-v2.json'
update(preview+'daily-v2.json',public)
update('/dashboard/workspace-assets/'+rid+'/management/daily-v2.json',public)
if a.activate:update('/dashboard/management/daily-v2.json',public)
(stage/'candidate/formal.conf').write_text(new)
for name,target,old in [('formal.conf','/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf',oldformal),('hubnav.js','/var/www/hub/hubnav.js',oldhub)]:
 rows.append({'candidate':'candidate/'+name,'target':target,'beforeSha256':hashlib.sha256(old).hexdigest(),'sha256':hashlib.sha256((stage/'candidate'/name).read_bytes()).hexdigest()})
m={'scope':'fs-management-v2-static','releaseId':rid,'businessWrites':False,'phase':phase,'runtimeDataPolicy':'Targets remain on the existing protected server; verify pinned bytes at publication. No production business dataset is stored in this repository.','files':rows,'unchangedRequired':[{'path':'/opt/fs-hermes-fc/controller.py','sha256':controller_sha},{'path':'/var/www/dashboard/fs-home/index.html','sha256':home_sha}]}
(stage/'contract.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
shutil.copy(ROOT/'release/publish_static.py',stage/'publish_static.py');shutil.copy(ROOT/'baseline/release_navigation_base.py',stage/'release_navigation_base.py')
print(stage);print(hashlib.sha256((stage/'contract.json').read_bytes()).hexdigest())
