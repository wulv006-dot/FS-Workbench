from pathlib import Path
import json,re,hashlib,shutil,tarfile
R=Path(__file__).resolve().parents[1];W=R.parent;U=R/'ui-system';OLD=R/'releases/fs-dashboard/menu-cache-20261015/native';D=None
sha=lambda b:hashlib.sha256(b).hexdigest()
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--release-id');parser.add_argument('--output',required=True,help='New empty staging directory, never a historical release directory');args=parser.parse_args()
D=Path(args.output).resolve()
if D.exists():raise SystemExit('Output already exists; historical releases are immutable')
if D==R or R in D.parents:raise SystemExit('Build outside the repository; review before importing a new release')
D.mkdir(parents=True)
oldid='workspace-native-20261006-fd4cfd0a70aa';rid=args.release_id or 'workspace-native-20261006-'+sha(Path(__file__).read_bytes()+b''.join(p.read_bytes() for p in sorted(U.rglob('*')) if p.is_file() and '__pycache__' not in str(p)))[:12]
assert re.fullmatch(r'workspace-native-20261006-[a-f0-9]{12}',rid)
rooturl='/dashboard/workspace-assets/'+rid+'/';oldurl='/dashboard/workspace-assets/'+oldid+'/'
N=D/'native';A=N/'assets';
if A.exists():shutil.rmtree(A)
A.mkdir(parents=True,exist_ok=True)
for p in (U/'modules/native').rglob('*'):
 if not p.is_file():continue
 if p.relative_to(U/'modules/native').as_posix() not in {'home.html','index.html','shell.js','workspace.css','business.css','google.css','google.js','business.js','navigation.json'}:continue
 name=p.relative_to(U/'modules/native').as_posix();data=p.read_bytes()
 if p.suffix in ['.html','.js','.css']:
  s=data.decode('utf-8')
  for sourceurl in [oldurl,'/dashboard/workspace-assets/workspace-native-20261006-ba0a83afd594/']:
   for resource in ['home.html','index.html','shell.js','workspace.css','business.css','google.css','google.js','business.js','navigation.json']:s=s.replace(sourceurl+resource,rooturl+resource)
  if name=='shell.js':
   s=s.replace("from './runtime.js'","from '"+oldurl+"runtime.js'").replace("base=new URL('./',import.meta.url);","base=new URL('./',import.meta.url),logicBase=new URL('"+oldurl+"',location.origin);").replace("new URL(state.mode+'.html',base)","new URL(state.mode+'.html',logicBase)")
  if name=='game-monitor/index.html':s=s.replace('"assets/','"'+oldurl+'game-monitor/assets/').replace("'assets/","'"+oldurl+'game-monitor/assets/')
  if p.suffix=='.html':
   tags='<link rel="stylesheet" href="'+rooturl+'ui/fs-tokens.css"><link rel="stylesheet" href="'+rooturl+'ui/fs-ui.css"><script src="'+rooturl+'ui/fs-theme.js"></script>'
   s=s.replace('</head>',tags+'</head>').replace('<body','<body class="fs-ui-page"',1) if '<body class=' not in s else s.replace('</head>',tags+'</head>')
  data=s.encode()
 dest=A/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
for name,source in [('fs-tokens.css','tokens/fs-tokens.css'),('fs-ui.css','components/fs-ui.css'),('fs-theme.js','adapters/fs-theme.js'),('native-alias.css','adapters/native-alias.css'),('legacy.css','adapters/legacy.css'),('hubnav.css','adapters/hubnav.css')]:
 p=A/'ui'/name;p.parent.mkdir(exist_ok=True);p.write_bytes((U/source).read_bytes())
names={p.relative_to(A).as_posix() for p in A.rglob('*') if p.is_file()}
conf=(OLD/'candidate/formal.conf').read_text()
# Existing exact locations and immutable old versions remain. Only friendly page aliases move.
blocks=re.findall(r'location = ([^\s{]+) \{.*?\n\}',conf,re.S)
text=conf
for match in list(re.finditer(r'location = ([^\s{]+) \{.*?\n\}',conf,re.S)):
 route=match.group(1);block=match.group(0)
 if not route.startswith('/dashboard/workspace-assets/'):
  for name in names:block=block.replace('/'+oldid+'/'+name+';', '/'+rid+'/'+name+';')
  text=text.replace(match.group(0),block,1)
# Reuse the existing per-file access policy, content types and headers.
def oldblock(name):
 pattern=r'location = '+re.escape(oldurl+name)+r' \{.*?\n\}'
 match=re.search(pattern,conf,re.S)
 if not match:raise ValueError('missing old asset route '+name)
 return match.group(0)
for name in sorted(names):
 template=oldblock(name) if name not in {x for x in names if x.startswith('ui/')} else oldblock('shell.js' if name.endswith('.js') else 'workspace.css')
 if name.startswith('ui/'):
  orig='shell.js' if name.endswith('.js') else 'workspace.css';template=template.replace(oldurl+orig,rooturl+name).replace('/'+oldid+'/'+orig,'/'+rid+'/'+name)
 else:template=template.replace('/'+oldid+'/', '/'+rid+'/')
 text+='\n'+template+'\n'
C=N/'candidate/fs-home';C.mkdir(parents=True,exist_ok=True);(C/'index.html').write_bytes((A/'home.html').read_bytes());(C/'navigation.js').write_bytes((U/'adapters/navigation.js').read_bytes())
(N/'candidate/formal.conf').write_text(text);shutil.copy2(OLD/'candidate/retired-radar.conf',N/'candidate/retired-radar.conf')
old=json.loads((OLD/'release-contract.json').read_text());m={**old,'scope':'FS UI system native visual migration; business contracts unchanged','releaseReady':False,'releaseId':rid}
m['immutableAssets']=[{'candidate':'assets/'+name,'target':'/var/lib/fs-navigation-formal-static/'+rid+'/'+name,'url':rooturl+name,'beforeSha256':None,'sha256':sha((A/name).read_bytes())} for name in sorted(names)]
for row in m['targets']:
 oldrow=next(x for x in old['targets'] if x['target']==row['target']);row['beforeSha256']=oldrow['sha256'];row['sha256']=sha((N/row['candidate']).read_bytes())
m['unchangedRequired']=[x for x in old['unchangedRequired'] if '/workspace-native-' not in x['path'] and x['path'] not in {r['target'] for r in m['targets']} and x['path']!='/var/www/dashboard/fs-home/navigation.json']
# Keep every selected current input pinned, without editing historical releases.
for row in old['immutableAssets']:
 if (OLD/row['candidate']).exists():m['unchangedRequired'].append({'path':row['target'],'sha256':row['sha256']})
raw=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(N/'release-contract.json').write_bytes(raw)
ready={**m,'releaseReady':True};(N/'release-manifest.json').write_text(json.dumps(ready,ensure_ascii=False,indent=2)+'\n')
s=(OLD/'release_workspace.py').read_text();s=re.sub(r'^NAMES = .*$', 'NAMES = set('+repr(sorted(names))+')',s,flags=re.M);s=re.sub(r"CONTRACT_SHA = '[a-f0-9]+'", "CONTRACT_SHA = '"+sha(raw)+"'",s);(N/'release_workspace.py').write_text(s)
shutil.copy2(U/'publishers/native_bridge.py',N/'release_navigation.py')
# Separate, bounded shared-navigation release; no auth/worker/timer updates.
S=D/'shared';(S/'candidate/ui').mkdir(parents=True,exist_ok=True)
targets={'ui/hubnav.js':'/var/www/hub/hubnav.js','ui/hubnav.css':'/var/www/dashboard/fs-home/hubnav.css','ui/navigation.json':'/var/www/dashboard/fs-home/navigation.json','ui/brain.css':'/var/www/dashboard/fs-home/brain/brain.css'}
baselines={}
# Explicit currently observed hashes.
baselines.update({'/var/www/hub/hubnav.js':'7cb572d2d5f63f4095844a9baf561140cd83b891c4ebaef32aaed5c3c32c268d','/var/www/dashboard/fs-home/hubnav.css':'a4d91836a041bb2d60e344905162929cb7642c560a8f866603b81ff4efc5c9a3','/var/www/dashboard/fs-home/navigation.json':'496fe59571e43c1afeb584caafee6cdcd86f8e09bcc70477e7ca7e0f695db5fd','/var/www/dashboard/fs-home/brain/brain.css':'15ff7f0c59920a42e8ed7ed76d74e3e320c954846ba2c1aba4b34e70685c054b'})
for name,p in [('hubnav.js',U/'adapters/hubnav.js'),('hubnav.css',U/'adapters/hubnav.css'),('navigation.json',U/'modules/native/navigation.json'),('brain.css',U/'modules/brain/brain.css')]:
 (S/'candidate/ui'/name).write_text(p.read_text().replace('__FS_UI_ROOT__',rooturl+'ui/'))
scope='fs-ui-system-20261015'
shutil.copy2(U/'publishers/shared_bridge.py',S/'release_navigation.py')
m={'schemaVersion':1,'scope':scope,'releaseReady':True,'businessWrites':False,'timersChanged':False,'runtimeRequired':{},'files':[{'candidate':n,'target':t,'beforeSha256':baselines[t],'sha256':sha((S/'candidate'/n).read_bytes())} for n,t in targets.items()],'unchangedRequired':[{'path':'/var/www/dashboard/index.html','sha256':old['requiredBusinessLedger']['sha256']}]+[{'path':x['target'],'sha256':x['sha256']} for x in ready['immutableAssets'] if x['candidate'].startswith('assets/ui/')]}
(S/'approved-manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
(D/'release-info.json').write_text(json.dumps({'releaseId':rid,'nativeManifest':sha((N/'release-manifest.json').read_bytes()),'sharedManifest':sha((S/'approved-manifest.json').read_bytes()),'assets':len(names)},indent=2))
print((D/'release-info.json').read_text())
