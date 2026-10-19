from pathlib import Path
import hashlib,json
from release_ui_finish import TARGETS,CONFIG,INDEX,PACKAGE,STATIC,SCOPE
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
 p=Path(__file__).parent;c=p/'candidate'
 baselines={CONFIG:'dc2c3bfbb8c11d2490d1168d29b7363df07fdbe452719a85cf31d6859ceb0e47',INDEX:'acebb058decd48beb5d14c8b2fc1a965373deabda2b3cd814a5fd7b0cec2ed2f'}
 for target,value in baselines.items():
  if sha(target)!=value:raise ValueError('current UI baseline drift')
 previous=json.loads((p/'manifest.json').read_text())
 protected={r['target']:r['sha256'] for r in previous['files'] if r['candidate'].startswith(('data/','range/'))}
 protected['/var/www/dashboard/index.html']='5c6c217a4353ae9cd8aa9ec0a10f97c1cddac89041a028418a17d2fdb8b603ba'
 for target,value in protected.items():
  if sha(target)!=value:raise ValueError('protected runtime drift')
 config=Path(CONFIG).read_text()
 for n,mime in [('google.js','application/javascript'),('google.css','text/css'),('shell.js','application/javascript')]:
  url='/dashboard/workspace-assets/'+PACKAGE+'/'+n
  if url in config:raise ValueError('existing candidate route')
  config+='\nlocation = '+url+' {\n    if ($request_method !~ ^(GET|HEAD)$) { return 405; }\n    auth_request /__nav_formal_native_session;\n    error_page 401 = @auth_login;\n    types { }\n    default_type '+mime+';\n    alias '+STATIC+PACKAGE+'/'+n+';\n    disable_symlinks on;\n    expires -1;\n    sub_filter "</body>" "</body>";\n    add_header X-Content-Type-Options "nosniff" always;\n}\n'
 (c/'zz-routes.conf').write_text(config)
 old='/dashboard/workspace-assets/workspace-native-20261019-traffic-v2/shell.js';s=Path(INDEX).read_text()
 if s.count(old)!=1:raise ValueError('current shell drift')
 (c/'z-index.html').write_text(s.replace(old,'/dashboard/workspace-assets/'+PACKAGE+'/shell.js'))
 files=[]
 for rel,target in TARGETS.items():
  if target not in baselines and Path(target).exists():raise ValueError('new target collision')
  files.append(dict(candidate=rel,target=target,sha256=sha(c/rel),beforeSha256=baselines.get(target)))
 value=dict(schemaVersion=1,scope=SCOPE,releaseReady=True,businessWrites=False,timersChanged=False,files=files,runtimeRequired={'nginx.service':{'ActiveState':'active'},'fs-marketing-range.service':{'ActiveState':'active'}},unchangedRequired=[dict(path=k,sha256=v) for k,v in protected.items()])
 raw=json.dumps(value,indent=2).encode();(p/'ui-manifest.json').write_bytes(raw);print(hashlib.sha256(raw).hexdigest())
if __name__=='__main__':main()
