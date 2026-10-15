"""Add UI scope to the reviewed account/AI extension of the existing publisher."""
import ast,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
source=HERE.parent/'accounts/integration/release_navigation.py'
assert hashlib.sha256(source.read_bytes()).hexdigest()=='fe8f5fa6583991c2eca8a2611f95c809d7c45f7a3c487e05ea5bd424f7d5d03e'
base=source.read_text('utf-8');text=base
constants="""REVISION_UI_SCOPE='fs-revision-ui-20261015'
REVISION_UI_TARGETS={
 'revision/navigation.json':'/var/www/dashboard/fs-home/navigation.json',
 'revision/navigation.css':'/var/www/dashboard/fs-home/navigation.css',
 'revision/hubnav.css':'/var/www/dashboard/fs-home/hubnav.css',
 'revision/hubnav.js':'/var/www/hub/hubnav.js',
 **{'revision/modules/'+key+'/index.html':'/var/www/dashboard/modules/'+key+'/index.html' for key in ('analytics','sports')},
 **{'revision/brain/'+name:'/var/www/dashboard/fs-home/brain/'+name for name in ('index.html','brain.js','brain.css')},
}
"""
guard=""" if manifest.get('scope')==REVISION_UI_SCOPE:
  for target in REVISION_UI_TARGETS.values():
   path=rooted(root,target);no_target_link(path)
   for item in (path,*path.parents):
    if item.exists():
     info=item.stat()
     if info.st_uid!=0 or info.st_gid!=0 or info.st_mode&0o022:raise ValueError('unsafe navigation ownership/mode')
    if item==root:break
"""
edits=[('RELATIVE={',constants+'RELATIVE={'),('def expected_files(manifest):','def expected_files(manifest):\n if manifest.get(\'scope\')==REVISION_UI_SCOPE:return set(REVISION_UI_TARGETS)'),('def target_for(rel):','def target_for(rel):\n if rel in REVISION_UI_TARGETS:return REVISION_UI_TARGETS[rel]'),("  if manifest.get('scope')==ACCOUNT_SCOPE and rel!=", "  if manifest.get('scope')==REVISION_UI_SCOPE and not rel.startswith('revision/brain/') and row.get('beforeSha256') is None:raise ValueError('existing navigation baseline required')\n  if manifest.get('scope')==ACCOUNT_SCOPE and rel!="),('def guards(manifest,root):\n','def guards(manifest,root):\n'+guard)]
for old,new in edits:
 assert text.count(old)==1,old
 text=text.replace(old,new)
text=text.replace("'OnCalendar=*-*-* 06:30:00 Asia/Shanghai'", "'OnCalendar=*-*-* 06:30:00'")
text=text.replace(" if manifest.get('scope')==HERMES_NIGHT_SCOPE:\n  if rooted(root,'/etc/localtime')", " if manifest.get('scope') in (HERMES_NIGHT_SCOPE,AI_REVISION_SCOPE):\n  if rooted(root,'/etc/localtime')")
functions=lambda s:{n.name:ast.dump(n,include_attributes=False) for n in ast.parse(s).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
a,b=functions(base),functions(text)
assert {k for k in a if a[k]!=b[k]}=={'expected_files','target_for','validate','guards'}
(HERE/'release_navigation.py').write_text(text,encoding='utf-8',newline='\n')
print(hashlib.sha256((HERE/'release_navigation.py').read_bytes()).hexdigest())
