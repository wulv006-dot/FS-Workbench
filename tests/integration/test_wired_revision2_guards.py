"""Offline tests of reviewed candidate functions with synthetic files and identities."""
import ast,contextlib,hashlib,html,importlib.util,io,json,mimetypes,os,socket,subprocess,sys,tempfile,types,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
W=Path(__file__).resolve().parents[2]
def load(name, rel):
 spec=importlib.util.spec_from_file_location(name,W/rel);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
bundle=load('bundle_policy', 'opt/deploy-hub/bundle_policy.py')
static=load('static_path', 'opt/mlb-online/static_path.py')
def extracted(rel,names,namespace):
 source=(W/rel).read_text(encoding='utf-8');tree=ast.parse(source);nodes=[]
 for item in tree.body:
  if isinstance(item,(ast.FunctionDef,ast.ClassDef)):
   if item.name in names:nodes.append(item)
   elif isinstance(item,ast.ClassDef):
    nodes.extend(n for n in item.body if isinstance(n,ast.FunctionDef) and n.name in names)
 assert {n.name for n in nodes}==set(names)
 exec(compile(ast.Module(body=nodes,type_ignores=[]),str(W/rel),'exec'),namespace)
 return namespace
def archive(entries):
 buf=io.BytesIO()
 with zipfile.ZipFile(buf,'w') as z:
  for name,data in entries:z.writestr(name,data)
 return buf.getvalue()

class DeployTests(unittest.TestCase):
 def setUp(self):
  class HubError(Exception):pass
  self.ns=extracted('opt/deploy-hub/deploy_server.py',['safe_extract'],{'validated_zip_members':bundle.validated_zip_members,'CFG':{'max_files':20,'max_unzip':4000},'HubError':HubError,'os':os})
 def test_valid_static_bundle(self):
  with tempfile.TemporaryDirectory() as tmp:
   self.assertEqual(self.ns['safe_extract'](archive([('index.html',b'<h1>test</h1>'),('assets/a.js',b'const a=1')]),tmp),(2,22))
   self.assertEqual((Path(tmp)/'assets/a.js').read_bytes(),b'const a=1')
 def test_bad_member_after_valid_writes_nothing(self):
  for name,data in [('.env',b'synthetic'),('creds.json',b'{"password":"SYNTHETIC_ONLY"}'),('x.pem',b'private'),('a/../x.js',b'test'),('CON.js',b'test'),('x%2e.js',b'test')]:
   with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
    with self.assertRaises(self.ns['HubError']):self.ns['safe_extract'](archive([('index.html',b'ok'),(name,data)]),tmp)
    self.assertEqual(list(Path(tmp).iterdir()),[])
 def test_duplicate_case_hierarchy_and_limits(self):
  cases=[[('index.html',b'a'),('INDEX.html',b'b')],[('a.js',b'x'),('a.js/child.css',b'x')],[('index.html',b'x'*4001)]]
  for entries in cases:
   with self.subTest(entries=[x[0] for x in entries]),self.assertRaises(ValueError):bundle.validated_zip_members(archive(entries),20,4000)
 def test_symlink_and_corrupt_crc(self):
  buf=io.BytesIO()
  with zipfile.ZipFile(buf,'w') as z:
   member=zipfile.ZipInfo('index.html');member.create_system=3;member.external_attr=0o120777<<16;z.writestr(member,b'target')
  with self.assertRaises(ValueError):bundle.validated_zip_members(buf.getvalue())
  data=archive([('index.html',b'UNIQUE_SYNTHETIC_PAYLOAD')]);data=data.replace(b'UNIQUE_SYNTHETIC_PAYLOAD',b'CORRUPTED_TEST___PAYLOAD')
  with self.assertRaises(ValueError):bundle.validated_zip_members(data)
 def test_client_no_exclude_cannot_bypass(self):
  ns={**vars(bundle),'os':os,'io':io,'zipfile':zipfile,'EXCLUDE_DIRS':{'.git'},'EXCLUDE_FILES':set(),'EXCLUDE_EXT':set()}
  extracted('opt/deploy-hub/deploy_client.py',['make_zip','skip'],ns)
  with tempfile.TemporaryDirectory() as tmp:
   (Path(tmp)/'index.html').write_text('safe');(Path(tmp)/'.env').write_text('SYNTHETIC_ONLY')
   with self.assertRaises(ValueError):ns['make_zip'](tmp,True)
 def test_notes_and_other_database_text_are_escaped(self):
  value='<img src=x onerror=alert(1)>'
  row={'owner':value,'name':value,'note':value,'bytes':1,'files':1,'version':1,'updated_at':1}
  class DB:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def execute(self,q):return self
   def fetchall(self):return [row]
  # Logs have separate shape; keep empty to focus all site fields.
  class DB2(DB):
   def execute(self,q):self.q=q;return self
   def fetchall(self):return [row] if 'FROM sites' in self.q else []
  import time
  from urllib.parse import quote
  ns={'db':DB2,'CFG':{'url_prefix':'/s/'},'PAGE':'__ME__ __BODY__','escaped_text':bundle.escaped_text,'quote':quote,'time':time,'human':str}
  extracted('opt/deploy-hub/deploy_server.py',['render_page'],ns)
  rendered=ns['render_page'](value,True)
  self.assertNotIn(value,rendered);self.assertIn('&lt;img',rendered)

class PortalTests(unittest.TestCase):
 def verify(self,session,registered,method='GET',group='dashboard'):
  class Policy:
   ADMINS=('wulv','chenchao','DY')
   @staticmethod
   def authorize(user,method,path,group):return 200 if method in ('GET','HEAD','OPTIONS') or user in Policy.ADMINS else 403
  ns={'parse_cookies':lambda c:{'portal':'SYNTHETIC'},'CFG':{'cookie':'portal'},'read_token':lambda t:session,'groups_of':lambda u:registered,'_fs_policy':Policy}
  fn=extracted('opt/auth-portal/auth_portal.py',['_do_verify'],ns)['_do_verify']
  obj=types.SimpleNamespace(headers={'Cookie':'SYNTHETIC','X-Original-Method':method,'X-Original-URI':'/dashboard/'},_send=lambda code,body,headers=None:(code,headers),_verify_fc_read=lambda group:(401,None))
  return fn(obj,group)
 def test_external_or_expired_identity_never_fallback(self):
  self.assertEqual(self.verify(None,[])[0],401)
  self.assertEqual(self.verify({'u':'external'},[])[0],401)
  self.assertEqual(self.verify({'u':'wulv'},[])[0],401)
 def test_registered_reader_and_admin_methods(self):
  self.assertEqual(self.verify({'u':'internal'},['dashboard'])[0],200)
  self.assertEqual(self.verify({'u':'internal'},['dashboard'],'POST')[0],403)
  for name in ('wulv','chenchao','DY'):
   self.assertEqual(self.verify({'u':name},['dashboard'],'POST')[0],200)
 def test_group_gate(self):self.assertEqual(self.verify({'u':'internal'},['other'])[0],403)

class MLBTests(unittest.TestCase):
 def test_actual_static_handler_uses_guard(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'site';root.mkdir();(root/'ok.css').write_text('SAFE')
   outside=Path(tmp)/'site-old';outside.mkdir();(outside/'x.css').write_text('PRIVATE_SYNTHETIC')
   ns={'safe_static_path':static.safe_static_path,'ARGS':types.SimpleNamespace(root=str(root)),'mimetypes':mimetypes}
   fn=extracted('opt/mlb-online/mlb_server.py',['_static'],ns)['_static'];obj=types.SimpleNamespace(_send=lambda status,data,headers=None:(status,data))
   self.assertEqual(fn(obj,'ok.css'),(200,b'SAFE'))
   self.assertEqual(fn(obj,'../site-old/x.css')[0],403)
   self.assertEqual(fn(obj,'%252e%252e/site-old/x.css')[0],403)
   self.assertEqual(fn(obj,'absent.css')[0],404)

class IGGMTests(unittest.TestCase):
 def test_all_actual_crawlers_reject_bad_urls_before_open(self):
  sys.path.insert(0,str(W/'opt/iggm-web'))
  try:
   for mod,cls in [('core','IGGMCrawler'),('core_aoeah','AoeahCrawler'),('core_u4gm','U4gmCrawler')]:
    m=load(mod,'opt/iggm-web/'+mod+'.py');crawler=getattr(m,cls)(log=lambda x:None)
    with self.subTest(module=mod),self.assertRaises(ValueError):crawler.get('http://127.0.0.1/?iggm.com')
   import sites
   for name in ['https://evil.example/iggm.com','https://iggm.com.evil.example/']:
    with self.assertRaises(ValueError):sites.detect_site(name)
   self.assertEqual(sites.detect_site('https://shop.aoeah.com/game'),'aoeah')
  finally:sys.path.pop(0)

class NBAOutputTests(unittest.TestCase):
 def test_login_does_not_emit_token_captcha_or_raw_response(self):
  sentinel='SYNTHETIC_SECRET_MARKER'
  ns={'uuid':types.SimpleNamespace(uuid4=lambda:sentinel),'os':os,'DATA_DIR':'SYNTHETIC_NOT_WRITTEN','DIR':'SYNTHETIC_CODE','CRED':{'username':'test','password':sentinel},'subprocess':types.SimpleNamespace(run=lambda *a,**k:types.SimpleNamespace(stdout=sentinel.encode())),'_curl':lambda *a,**k:None,'api':lambda *a,**k:('200',{'code':1,'msg':sentinel,'data':{'token':sentinel}}),'private_write':lambda *a:None,'TOKEN_FILE':'SYNTHETIC_NOT_WRITTEN'}
  ns['BASE']='https://synthetic.invalid';ns['_runtime_serialized']=lambda fn:fn
  fn=extracted('opt/nba-reprice/backend/p2pah_api.py',['login'],ns)['login']
  output=io.StringIO()
  with contextlib.redirect_stdout(output):self.assertEqual(fn(),sentinel)
  self.assertNotIn(sentinel,output.getvalue())

if __name__=='__main__':
 with patch('socket.socket.connect',side_effect=AssertionError('external network forbidden')),patch('socket.getaddrinfo',side_effect=AssertionError('real DNS forbidden')),patch('subprocess.run',side_effect=AssertionError('real subprocess forbidden')),patch('subprocess.Popen',side_effect=AssertionError('real subprocess forbidden')):
  r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
 print(json.dumps({'run':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped),'passed':r.wasSuccessful(),'scope':'mocked candidate functions; synthetic local fixtures; external network/process disabled'}))
 sys.exit(not r.wasSuccessful())
