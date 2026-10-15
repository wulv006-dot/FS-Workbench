from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parents[2]
source=ROOT/'source/frontend'
files={p.name:p.read_bytes() for p in source.iterdir() if p.is_file()}
rid='workspace-native-20261006-'+hashlib.sha256(b''.join(k.encode()+files[k] for k in sorted(files))).hexdigest()[:12]
stage=ROOT/'release'/('preview-'+rid)
if stage.exists():raise SystemExit('immutable stage exists')
(stage/'assets').mkdir(parents=True);(stage/'candidate').mkdir()
for name,data in files.items():(stage/'assets'/name).write_bytes(data)
oldformal=(ROOT/'baseline/ui/formal.conf').read_bytes()
oldhub=(ROOT/'baseline/ui/hubnav.js').read_bytes()
hub=oldhub.decode().replace("const styledModule=location.pathname.startsWith('/dashboard/')||location.pathname.startsWith('/tools/fc27-gallery/')||location.pathname.startsWith('/tools/fc27-players/');", "const styledModule=!document.body.hasAttribute('data-management-v2')&&(location.pathname.startsWith('/dashboard/')||location.pathname.startsWith('/tools/fc27-gallery/')||location.pathname.startsWith('/tools/fc27-players/'));")
assert hub!=oldhub.decode()
(stage/'candidate/hubnav.js').write_text(hub)
new=oldformal.decode()+'\n# Protected management-v2 preview; existing production aliases unchanged.\n'
url='/dashboard/__preview/management-v2-20261015/'
def location(path,target,html=False):
 inject='<script defer src="/__hub/hubnav.js?v=management-v2-20261015"></script></body>' if html else '</body>'
 inject=inject.replace('"','\\"')
 return ('location = '+path+' {\n    if ($request_method !~ ^(GET|HEAD)$) { return 405; }\n    auth_request /__nav_formal_native_session;\n    error_page 401 = @auth_login;\n    alias '+target+';\n    disable_symlinks on;\n    expires -1;\n    sub_filter "</body>" "'+inject+'";\n    add_header Cache-Control "no-store" always;\n    add_header X-Content-Type-Options "nosniff" always;\n    add_header X-Robots-Tag "noindex, nofollow" always;\n    add_header Referrer-Policy "same-origin" always;\n}\n')
rows=[]
for name,data in sorted(files.items()):
 target='/var/lib/fs-navigation-formal-static/'+rid+'/management/'+name
 new+=location(url+name,target,name.endswith('.html'))
 new+=location('/dashboard/workspace-assets/'+rid+'/management/'+name,target,name.endswith('.html'))
 rows.append({'candidate':'assets/'+name,'target':target,'beforeSha256':None,'sha256':hashlib.sha256(data).hexdigest()})
new+=location(url+'daily-v2.json','/var/lib/fs-boss-workspaces/public/management-v2.json')
(stage/'candidate/formal.conf').write_text(new)
for name,target,old in [('formal.conf','/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf',oldformal),('hubnav.js','/var/www/hub/hubnav.js',oldhub)]:
 rows.append({'candidate':'candidate/'+name,'target':target,'beforeSha256':hashlib.sha256(old).hexdigest(),'sha256':hashlib.sha256((stage/'candidate'/name).read_bytes()).hexdigest()})
manifest={'scope':'fs-management-v2-static','releaseId':rid,'businessWrites':False,'phase':'protected-preview-only','files':rows,'unchangedRequired':[{'path':'/opt/fs-hermes-fc/controller.py','sha256':'67bb8c6d66e5cf05f9fbd31418100cae235cbda54c3c4879a0c16ad14f257efb'},{'path':'/var/www/dashboard/fs-home/index.html','sha256':hashlib.sha256((ROOT/'baseline/ui/home.html').read_bytes()).hexdigest()}]}
(stage/'contract.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
shutil.copy(ROOT/'release/publish_static.py',stage/'publish_static.py')
shutil.copy(ROOT/'baseline/release_navigation_base.py',stage/'release_navigation_base.py')
print(stage);print('manifest',hashlib.sha256((stage/'contract.json').read_bytes()).hexdigest());print('preview',url+'index.html')
