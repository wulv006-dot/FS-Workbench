from pathlib import Path
import hashlib,json,shutil,zipfile
R=Path(__file__).resolve().parent;D=R.parent/'docs/planning/business-shipping-profit-20261024'
live=json.loads((R/'baseline/label-live-baseline.json').read_text('utf-8-sig'))
prior=json.loads((R/'stage/ui-fix/approved-manifest.json').read_text('utf-8'))
names=('business.js','home-business.js','legacy-business.js','shell.js')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
version='shipping-profit-labels-20261024-'+hashlib.sha256(b''.join((R/'source'/n).read_bytes() for n in names)).hexdigest()[:12]
files=[];conf=live['files']['generated/navigation.conf']['content'].encode()
for name in names:
 key='source/'+name;target='/var/lib/fs-navigation-formal-static/'+version+'/'+name
 needle=('alias '+live['files'][key]['target']+';').encode()
 assert conf.count(needle)==1,('exact_alias',name)
 conf=conf.replace(needle,('alias '+target+';').encode(),1)
 files.append(dict(candidate=key,target=target,sha256=sha(R/key),beforeSha256=None,owner='0:0',mode='0o644'))
files.append(dict(candidate='generated/navigation.conf',target=live['files']['generated/navigation.conf']['target'],sha256=hashlib.sha256(conf).hexdigest(),beforeSha256=live['files']['generated/navigation.conf']['sha256'],owner='0:0',mode='0o644'))
changed={f['target'] for f in files}
m={**prior,'scope':'business-shipping-profit-labels-20261024','version':version,'files':files,'unchangedRequired':[dict(path=p,sha256=s) for p,s in sorted(live['protected'].items()) if p not in changed]}
stage=R/'stage/label-fix';stage.mkdir(exist_ok=True)
for name in ('release.py','release_navigation_base.py','ui_fix.py'):shutil.copyfile(R/'stage/ui-fix'/name,stage/name)
adapter='''"""Profit label/description follow-up through the existing static-only publisher."""
SCOPE='business-shipping-profit-labels-20261024'
TARGETS='''+repr({f['candidate']:f['target'] for f in files})+'''
NEW=frozenset('''+repr([f['candidate'] for f in files if f['beforeSha256'] is None])+''')
def load_base():
    import ui_fix
    ui_fix.SCOPE,ui_fix.TARGETS,ui_fix.NEW=SCOPE,TARGETS,NEW
    return ui_fix.load_base()
if __name__=='__main__':load_base().main()
'''
(R/'deploy/label_fix.py').write_text(adapter,encoding='utf-8',newline='\n');(stage/'label_fix.py').write_text(adapter,encoding='utf-8',newline='\n')
for f in files:
 p=stage/'candidate'/f['candidate'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(conf if f['candidate'].startswith('generated/') else (R/f['candidate']).read_bytes())
(stage/'approved-manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
(D/'LABELS-SOURCE-MAP.json').write_text(json.dumps({k:m[k] for k in ('scope','version','files')},ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
with zipfile.ZipFile(R/'stage/label-fix.zip','w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(stage.rglob('*')):
  if p.is_file():z.write(p,p.relative_to(stage).as_posix())
print(json.dumps(dict(version=version,manifestSha256=sha(stage/'approved-manifest.json'),zipSha256=sha(R/'stage/label-fix.zip'),targets=len(files),protected=len(m['unchangedRequired']))))
