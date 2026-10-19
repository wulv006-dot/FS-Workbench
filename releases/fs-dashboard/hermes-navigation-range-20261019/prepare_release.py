"""Prepare exact static-only replacements from frozen live inputs; never apply here."""
from pathlib import Path
import hashlib,json,re
P=Path(__file__).parent; C=P/'candidate';V='hermes-nav-20261019-v1'
BASE='/var/lib/fs-navigation-formal-static/workspace-native-20261006-346f59eea565/'
TARGETS={
 'hermes-nav.css':('/var/www/hub/hermes-nav.css',None),
 'hubnav.js':('/var/www/hub/hubnav.js','168fa467650ebd480ccfa1efb0ad65c6b9d57719abba8fed570157234d5bde36'),
 'nav.js':('/var/www/hub/nav.js','1f84fb870492934b34e47957c4d7af10bd585fcf43b0c260cdd83ec2d1352c99'),
 'navigation.json':('/var/www/dashboard/fs-home/navigation.json','201a49e27cf57f9f44367bc371c89aab4780512edd747aac3544b34d0a052777'),
 'hermes-index.html':('/var/www/dashboard/modules/hermes/index.html',None),
 'conversation-index.html':('/var/www/dashboard/fs-home/hermes/conversation/index.html','203a2c327add38fc6f38e891f5e9d703359b20d152299ef4ac9b62c2f0c76a85'),
 'customer-index.html':(BASE+'index.html','d32c67a8d011f81efea850e8766e686d610dcd063938a6dbf6929722ad3d5b10'),
 'page.js':(BASE+'page.js','346f59eea5655e7e394dd499c9ac4e1d0d886b8af982be10f8250d4ef3ca4bb6')}
STATIC={
 'analytics':'31e4cb4054a0706c2f3208ee00ce1da154e8b1b47026295f240f2a515261797f',
 'collaboration':'75044eadced9d2b47b17ea65ffe0b1dca87b65097fbade6260d5c706da16184e',
 'about':'ddd5553bd586bb93588232686ced4eec2643d020c7bbfa4bef397a774b1b4a58',
 'arpg':'dd2c7e1ca5a767044b3f9139c823f2009f22f0948b22215be356b2699b4c66fe',
 'bots':'87cd7a5e43cb31114bb68a344aa03ecc50a5338eec75538b2216a25824719535',
 'sports':'346f7e4709b22f40b7f3573ba52f7181d0b3700e82712ed0778d6f74e1372ad5',
 'home':'52a897a00532d05d64718d4e341ec31e6b143ae22b4b97b0dafe5d745b64b6a2'}
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
def read(path,sha):
 p=Path(path)
 if digest(p)!=sha:raise ValueError('baseline drift: '+path)
 return p.read_text()
def prepare():
 nav=(C/'nav-fragment.html').read_text()
 group=re.search(r'<section class="hn-group"><a class="hn-heading" href="/dashboard/modules/hermes/".*?</section>',nav,re.S).group(0)
 for name,sha in STATIC.items():
  target='/var/www/dashboard/fs-home/index.html' if name=='home' else '/var/www/dashboard/modules/'+name+'/index.html'
  text=read(target,sha)
  text,n=re.subn(r'<section class="hn-group">\s*<a class="hn-heading" href="/dashboard/fs-home/brain/index.html".*?</section>',lambda m:group,text,flags=re.S)
  if n!=1:raise ValueError('static nav seam '+name)
  if 'nav.js?v=177fa59e' not in text:raise ValueError('nav cache seam '+name)
  text=text.replace('nav.js?v=177fa59e','nav.js?v='+V)
  if name=='home':text=text.replace('href="/dashboard/fs-home/brain/index.html"','href="/dashboard/modules/hermes/"')
  rel='static-'+name+'.html';(C/rel).write_text(text);TARGETS[rel]=(target,sha)
 target='/var/www/dashboard/fs-home/brain/index.html';sha='75505a5b8f821b4ee1c8a558cfe22e209d6c392c396a4c7d95b37df33cc8092f'
 text=read(target,sha)
 if 'id="hubNav"' in text:raise ValueError('unexpected static report nav')
 text=text.replace('</head>','<link rel="stylesheet" href="/__hub/hermes-nav.css?v='+V+'"><script defer src="/__hub/nav.js?v='+V+'"></script></head>')
 def body(m):
  tag=m.group(0)
  if 'class="' in tag:tag=tag.replace('class="','class="fs-unified-navigation ',1)
  else:tag=tag[:-1]+' class="fs-unified-navigation">'
  return tag+'\n'+nav
 text=re.sub(r'<body\b[^>]*>',body,text,count=1)
 (C/'report-index.html').write_text(text);TARGETS['report-index.html']=(target,sha)
 for rel,target,sha in [('z-main.conf','/etc/nginx/conf.d/iggm-web.conf','23f90f7b23273ad42270321baedad9d22eae55ffe8bef768ce95d7ba6d4748e0'),('zz-formal.conf','/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf','897f1645cfe8aab02459525a866eaa81012c4d68048288b80a2ddb6e226dde3c')]:
  text=read(target,sha)
  if 'hubnav.js?v=3dda7cae' not in text:raise ValueError('hub cache seam')
  text=text.replace('hubnav.js?v=3dda7cae','hubnav.js?v='+V)
  (C/rel).write_text(text);TARGETS[rel]=(target,sha)
 for rel,(target,sha) in TARGETS.items():
  if digest(Path(target))!=sha:raise ValueError('baseline drift '+target)
 m={'schemaVersion':1,'scope':'traffic-source-tabs-ui-finish-20261019','releaseReady':True,'businessWrites':False,'timersChanged':False,'runtimeRequired':{'nginx.service':{'ActiveState':'active'},'fs-marketing-range.service':{'ActiveState':'active'}},'unchangedRequired':[],'files':[{'candidate':r,'target':t,'beforeSha256':sha,'sha256':digest(C/r)} for r,(t,sha) in TARGETS.items()]}
 for path in ['/opt/fs-hermes-fc/tracking_controller.py','/opt/fs-hermes-fc/customer_tracking.py','/var/www/dashboard/fs-home/hermes/conversation/conversation.js','/var/lib/fs-navigation-formal-static/workspace-native-20261019-traffic-v3/google.js','/var/lib/fs-navigation-formal-static/workspace-native-20261019-traffic-v3/google.css']:
  m['unchangedRequired'].append({'path':path,'sha256':digest(Path(path))})
 (P/'targets.json').write_text(json.dumps({r:t for r,(t,_) in TARGETS.items()},indent=2))
 raw=json.dumps(m,indent=2).encode();(P/'manifest.json').write_bytes(raw)
 print('MANIFEST',hashlib.sha256(raw).hexdigest(),'FILES',len(m['files']))
if __name__=='__main__':prepare()
