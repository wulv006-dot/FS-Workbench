"""Prepare only private release candidates from fixed observed production hashes."""
from pathlib import Path
import hashlib,json
from release_source_tabs import TARGETS,CONFIG,OLD,PACKAGE,STATIC,SCOPE
BASE={CONFIG:'f44b5819fb51e898fa73e758209135d1a9b90df28e58b4746f86f9e5ceae3cf5',OLD+'index.html':'412bc7fe25cee367ffb9a89678f5adefbc64a56673d390b257a0159c272d17be',
 '/opt/mmoexp-marketing/details/collect_details.py':'a180a6567ea8beb954ea5a1d85812103f0bf2361346fbbcf4cea3774c2a00598',
 '/opt/mmoexp-marketing/details/detail_model.py':'006342349ef7618d91d9c06a38b85a3467a4715bc897f494b547703b60b8bd83',
 '/opt/mmoexp-marketing/custom-range/custom_range.py':'75752cca128c541c60cb09c8be48866446df3cc1b08c48437bf842921883c5dc',
 '/opt/mmoexp-marketing/custom-range/range_api.py':'d99ac3cdacc6212a92f5d0899451cf7a4668af7e3d0a2674cff6c832c60b245a'}
PROTECT={'/var/www/dashboard/index.html':'5c6c217a4353ae9cd8aa9ec0a10f97c1cddac89041a028418a17d2fdb8b603ba',OLD+'shell.js':'20a637060fe1fd9ecece21947aaa713e1e594aafbff9d0a4f74e9c2609592fae',STATIC+'workspace-native-20261006-72d7ba0dbca8/google.js':'2c66c95818935ac11690f01c006c5f67dec8dd326c40a17aed37f4a497672e12'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 stage=Path(__file__).parent;c=stage/'candidate'
 for path,value in {**BASE,**PROTECT}.items():
  if Path(path).is_symlink() or sha(path)!=value:raise ValueError('live baseline drift: '+path)
 config=Path(CONFIG).read_text()
 for name,mime in [('google.js','application/javascript'),('google.css','text/css'),('shell.js','application/javascript')]:
  url='/dashboard/workspace-assets/'+PACKAGE+'/'+name
  if url in config:raise ValueError('new route already exists')
  config+='\nlocation = '+url+' {\n    if ($request_method !~ ^(GET|HEAD)$) { return 405; }\n    auth_request /__nav_formal_native_session;\n    error_page 401 = @auth_login;\n    types { }\n    default_type '+mime+';\n    alias '+STATIC+PACKAGE+'/'+name+';\n    disable_symlinks on;\n    expires -1;\n    sub_filter "</body>" "</body>";\n    add_header X-Content-Type-Options "nosniff" always;\n}\n'
 (c/'zz-routes.conf').write_text(config)
 old='/dashboard/workspace-assets/workspace-native-20261006-37fe775358df/shell.js'
 text=Path(OLD+'index.html').read_text()
 if text.count(old)!=1:raise ValueError('unexpected shell reference')
 (c/'z-index.html').write_text(text.replace(old,'/dashboard/workspace-assets/'+PACKAGE+'/shell.js'))
 rows=[]
 for rel,target in TARGETS.items():
  before=BASE.get(target)
  if before is None and Path(target).exists():raise ValueError('unexpected existing new target: '+target)
  rows.append(dict(candidate=rel,target=target,sha256=sha(c/rel),beforeSha256=before))
 m=dict(schemaVersion=1,scope=SCOPE,releaseReady=True,businessWrites=False,timersChanged=False,files=rows,unchangedRequired=[dict(path=p,sha256=s) for p,s in PROTECT.items()],runtimeRequired={'nginx.service':{'ActiveState':'active'},'fs-marketing-range.service':{'ActiveState':'active'}})
 raw=json.dumps(m,ensure_ascii=False,indent=2).encode();(stage/'manifest.json').write_bytes(raw)
 print(json.dumps({'manifestSha256':hashlib.sha256(raw).hexdigest(),'files':len(rows),'productionMutations':False}))
if __name__=='__main__':main()
