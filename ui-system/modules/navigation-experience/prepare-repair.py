from pathlib import Path
import hashlib,json,re
P=Path('/opt/fs-release-stage/navigation-experience-20261103-repair-v3');C=P/'candidate';B=P/'baseline'
C.mkdir(parents=True,exist_ok=True);B.mkdir(exist_ok=True)
version='navigation-experience-20261103-v3'
sha=lambda b:hashlib.sha256(b).hexdigest()
old=json.loads(Path('/opt/fs-release-stage/navigation-experience-20261103-final-v2/manifest.json').read_text())
targets={f['candidate']:f['target'] for f in old['files']}
targets['fc-coins.html']='/var/www/dashboard/fc27-coins.html'
files=[]
script='<script src="/__hub/hubnav.js?v='+version+'"></script>'
preload='<link rel="preload" as="script" href="/__hub/hubnav.js?v='+version+'">'
for name,target in targets.items():
 raw=Path(target).read_bytes();(B/name).write_bytes(raw)
 if name in ('hubnav.js','nav.js'):
  assert sha(raw)==next(f['sha256'] for f in old['files'] if f['candidate']==name),'concurrent nav edit'
 else:
  text=raw.decode('utf-8')
  text=re.sub(r'((?:hubnav|nav)\.js\?v=)[A-Za-z0-9_-]+',lambda m:m[1]+version,text)
  if name in ('z-main.conf','zz-formal.conf'):
   text=text.replace("sub_filter '</head>' '<link", "sub_filter '</head>' '"+preload+'<link')
  if name=='zz-formal.conf':
   marker='location ^~ /dashboard/analytics/campaigns/ {\n'
   assert text.count(marker)==1
   # This proxy's pages have no static shell. Mount before their blocking business scripts.
   injection=("    sub_filter '<body class=\"fs-ui-page\">' '<body class=\"fs-ui-page\">"+script+"';\n"
    +"    sub_filter '</body>' '"+script+"</body>';\n"
    +"    sub_filter '</head>' '"+preload+'<link rel="stylesheet" href="/__hub/navigation-experience.css?v=navigation-experience-20261103-v1"></head>'+"';\n")
   text=text.replace(marker,marker+injection)
  if name=='fc-coins.html':
   marker='<body class="fs-ui-page">';assert text.count(marker)==1
   text=text.replace(marker,marker+script)
  (C/name).write_text(text,encoding='utf-8')
 files.append(dict(candidate=name,target=target,beforeSha256=sha(raw),sha256=sha((C/name).read_bytes())))
m={k:v for k,v in old.items() if k!='files'};m['files']=files
(P/'manifest.json').write_text(json.dumps(m,indent=2));(P/'targets.json').write_text(json.dumps(targets,indent=2))
(P/'release_ui.py').write_bytes(Path('/opt/fs-release-stage/navigation-experience-20261103-final-v2/release_ui.py').read_bytes())
print(json.dumps(dict(files=len(files),manifestSha256=sha((P/'manifest.json').read_bytes()))))
