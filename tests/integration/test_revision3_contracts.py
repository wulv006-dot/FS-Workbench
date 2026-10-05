"""Targeted revision3 offline contracts. Synthetic identities, prices and archive bytes only."""
import ast,contextlib,hashlib,http.client,importlib.util,io,json,os,re,socket,subprocess,sys,tempfile,threading,types,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2]
def load(name,rel):
 spec=importlib.util.spec_from_file_location(name,ROOT/rel);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
bundle=load('bundle_r3','opt/deploy-hub/bundle_policy.py')
scope=load('scope_r3','opt/auth-portal/fc_read_scope.py')
writer=load('writer_r3','opt/nba-reprice/backend/write_contract.py')
def extracted(rel,names,ns):
 tree=ast.parse((ROOT/rel).read_text(encoding='utf-8'));nodes=[]
 for item in tree.body:
  if isinstance(item,ast.FunctionDef) and item.name in names:nodes.append(item)
  if isinstance(item,ast.ClassDef):nodes.extend(n for n in item.body if isinstance(n,ast.FunctionDef) and n.name in names)
 assert {n.name for n in nodes}==set(names)
 exec(compile(ast.Module(body=nodes,type_ignores=[]),rel,'exec'),ns)
 return ns
def envelope(value,identity='a'*32):
 raw=json.dumps({'confirm':'NBA_PRICE_APPLY','operator':'wulv','prices':{'PlayStation 5':value}},separators=(',',':'))
 return {'requestId':identity,'planSha256':hashlib.sha256(raw.encode()).hexdigest(),'planJson':raw}

class BundleContracts(unittest.TestCase):
 def test_recursive_json_credentials_case_escape_and_values(self):
  bad=[{'a':[{'Cookie':'session=SYNTHETIC'}]},{'BATOKEN':'SYNTHETIC'},{'Authorization':'Basic SYNTHETIC'},
       {'authorization':'Bearer SYNTHETIC'},{'X':{'set-cookie':['session=SYNTHETIC']}},
       {'value':'Cookie: session=SYNTHETIC'},{'array':['Bearer SYNTHETIC']}]
  for value in bad:
   with self.subTest(value=list(value)),self.assertRaisesRegex(ValueError,'SENSITIVE'):
    bundle.validate_publish_content('assets/settings.json',json.dumps(value).encode())
  with self.assertRaisesRegex(ValueError,'SENSITIVE'):
   bundle.validate_publish_content('a.json',b'{"\\u0043ookie":"session=SYNTHETIC"}')
  with self.assertRaises(ValueError):bundle.validate_publish_content('a.json',b'{"Cookie":"SYNTHETIC","Cookie":""}')
 def test_normal_static_json_code_placeholders(self):
  for data in [b'{"title":"Demo","theme":"dark","authorization":"Bearer ${token}"}',
               b'{"Cookie":"YOUR_COOKIE","batoken":"REPLACE_BATOKEN","password":""}']:
   bundle.validate_publish_content('assets/settings.json',data)
  for data in [b'const cookie = document.cookie;',b'const headers = {Authorization: "Bearer " + token};',
               b'const batoken = "YOUR_BATOKEN";',b'// Cookie/Authorization field names without values']:
   bundle.validate_publish_content('app.js',data)
 def test_rejected_zip_never_writes_partial(self):
  class HubError(Exception):pass
  ns=extracted('opt/deploy-hub/deploy_server.py',['safe_extract'],{'validated_zip_members':bundle.validated_zip_members,'CFG':{'max_files':20,'max_unzip':4000},'HubError':HubError,'os':os})
  for key in ['Cookie','batoken','Authorization']:
   out=io.BytesIO()
   with zipfile.ZipFile(out,'w') as z:
    z.writestr('index.html','safe');z.writestr('assets/settings.json',json.dumps({key:'SYNTHETIC'}))
   with tempfile.TemporaryDirectory() as tmp:
    with self.assertRaises(HubError):ns['safe_extract'](out.getvalue(),tmp)
    self.assertEqual(list(Path(tmp).iterdir()),[])
 def test_generated_standalone_policy_exact(self):
  src=(ROOT/'opt/deploy-hub/bundle_policy.py').read_text(encoding='utf-8')
  client=(ROOT/'opt/deploy-hub/deploy_client.py').read_text(encoding='utf-8')
  header='# Generated from bundle_policy.py SHA256 '+hashlib.sha256(src.encode()).hexdigest()+'; keep standalone download compatibility.\n'
  self.assertIn(header+src+'\n# End generated publishing policy.',client)

class FCSessionContracts(unittest.TestCase):
 def verify(self,path,method='GET',user='fcguest',status=200,group='',portal=None,registered=()):
  calls=[]
  class Connection:
   def __init__(self,*a,**kw):calls.append((a,kw))
   def request(self,*a,**kw):calls.append((a,kw))
   def getresponse(self):return types.SimpleNamespace(status=status,getheader=lambda *a:user,read=lambda size:b'OK')
   def close(self):pass
  ns={'parse_cookies':lambda c:{'fc27sess':'SYNTHETIC_VALID_TOKEN'},'CFG':{'cookie':'portal'},'read_token':lambda t:portal,
      'groups_of':lambda u:list(registered),'allowed_fc_read':scope.allowed_fc_read,'re':re,
      'http':types.SimpleNamespace(client=types.SimpleNamespace(HTTPConnection=Connection,HTTPException=http.client.HTTPException)),
      '_fs_policy':types.SimpleNamespace(ADMINS=('wulv','chenchao','DY'),authorize=lambda u,m,p,g:200 if m in ('GET','HEAD') or u=='wulv' else 403)}
  extracted('opt/auth-portal/auth_portal.py',['_do_verify','_verify_fc_read'],ns)
  obj=types.SimpleNamespace(headers={'Cookie':'SYNTHETIC','X-Original-URI':path,'X-Original-Method':method},_send=lambda code,body,headers=None:(code,dict(headers or [])))
  obj._verify_fc_read=lambda g:ns['_verify_fc_read'](obj,g)
  return ns['_do_verify'](obj,group),calls
 def test_valid_fc_only_reads_no_portal_promotion(self):
  for path in ['/s/wulv/fc27-ops/','/s/wulv/fc27-ops/index.html','/s/wulv/fc27-ops/api/jobs/'+'a'*32,
               '/tools/fc27-players/','/tools/fc27-players/api/bootstrap','/tools/fc27-players/api/status',
               '/tools/fc27-players/api/candidates?label=synthetic%20filter']:
   for name in ['fcguest','wulv','DY']:
    (code,headers),calls=self.verify(path,user=name)
    self.assertEqual(code,200);self.assertEqual(headers,{'X-Fc27-User':name,'X-Fc27-Role':'readonly'})
    self.assertEqual(calls[1][0],('GET','/verify'))
 def test_fc_expired_banned_unregistered_gate_rejected(self):
  for status in [401,403,500]:self.assertEqual(self.verify('/tools/fc27-players/',status=status)[0][0],401)
  for name in ['', 'bad\r\nX-Auth-Role: admin']:
   self.assertEqual(self.verify('/tools/fc27-players/',user=name)[0][0],401)
 def test_fc_writes_internal_unknown_and_traversal_never_bridge(self):
  for path in ['/dashboard/','/dashboard/tasks/','/docs/','/tools/fc27-gallery/',
               '/dashboard/fc27-quote-api/','/tools/fc27-players/api/auth/login','/s/wulv/fc27-ops/api/collect',
               '/s/wulv/fc27-ops/../private.json','/tools/fc27-players/%2e%2e/admin','/tools/fc27-players/api/unknown']:
   result,calls=self.verify(path);self.assertEqual(result[0],401);self.assertEqual(calls,[])
  for method in ['POST','PUT','DELETE','OPTIONS']:
   result,calls=self.verify('/tools/fc27-players/',method);self.assertEqual(result[0],401);self.assertEqual(calls,[])
  self.assertEqual(self.verify('/tools/fc27-players/',group='dashboard')[0][0],401)
 def test_internal_signed_live_admin_and_reader_keep_policy(self):
  self.assertEqual(self.verify('/dashboard/',portal={'u':'reader'},registered=['dashboard'],group='dashboard')[0][0],200)
  self.assertEqual(self.verify('/dashboard/',method='POST',portal={'u':'reader'},registered=['dashboard'],group='dashboard')[0][0],403)
  result,_=self.verify('/dashboard/',method='POST',portal={'u':'wulv'},registered=['dashboard'],group='dashboard')
  self.assertEqual(result[1]['X-Auth-Role'],'admin')

class NBAPlanContracts(unittest.TestCase):
 def test_receipt_idempotency_binding_no_reexecution(self):
  with tempfile.TemporaryDirectory() as tmp:
   writes=[];plan=envelope(1.1)
   def execute(p):writes.append(p['prices']);return {'ok':True,'verified':True}
   first=writer.execute_bound_plan(tmp,plan,execute)
   again=writer.execute_bound_plan(tmp,plan,execute)
   self.assertTrue(first['ok']);self.assertTrue(again['replayedReceipt']);self.assertEqual(len(writes),1)
   with self.assertRaisesRegex(ValueError,'CONFLICT'):writer.execute_bound_plan(tmp,envelope(2.2),execute)
   self.assertEqual(len(writes),1)
 def test_pending_unknown_and_bad_hash_never_replayed(self):
  with tempfile.TemporaryDirectory() as tmp:
   plan=envelope(1.1);calls=[]
   def unknown(p):calls.append(p);raise RuntimeError('SYNTHETIC_UPSTREAM_FAILURE')
   result=writer.execute_bound_plan(tmp,plan,unknown);self.assertEqual(result['state'],'unknown')
   self.assertEqual(writer.execute_bound_plan(tmp,plan,unknown)['error'],'WRITE_OUTCOME_UNKNOWN');self.assertEqual(len(calls),1)
   bad=envelope(2.2,'b'*32);bad['planSha256']='0'*64
   with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):writer.execute_bound_plan(tmp,bad,unknown)
   self.assertEqual(len(calls),1)
 def test_delayed_two_plans_serialize_and_keep_own_bindings(self):
  with tempfile.TemporaryDirectory() as tmp:
   entered=threading.Event();release=threading.Event();out=[];writes=[]
   def execute(plan):
    value=plan['prices']['PlayStation 5'];writes.append(value)
    if value==1.1:entered.set();self.assertTrue(release.wait(3))
    return {'ok':True,'observedPrice':value}
   a=threading.Thread(target=lambda:out.append(writer.execute_bound_plan(tmp,envelope(1.1,'a'*32),execute)))
   b=threading.Thread(target=lambda:out.append(writer.execute_bound_plan(tmp,envelope(2.2,'b'*32),execute)))
   a.start();self.assertTrue(entered.wait(3));b.start();self.assertEqual(writes,[1.1]);release.set();a.join(4);b.join(4)
   self.assertFalse(a.is_alive() or b.is_alive());self.assertEqual(writes,[1.1,2.2])
   self.assertEqual({r['requestId']:r['observedPrice'] for r in out},{'a'*32:1.1,'b'*32:2.2})
 def test_actual_curl_uses_unique_response_files_and_cleans(self):
  with tempfile.TemporaryDirectory() as tmp:
   paths=[]
   def fake_run(cmd,**kwargs):
    dst=cmd[cmd.index('-o')+1];paths.append(dst);Path(dst).write_bytes(b'SYNTHETIC_RESPONSE');return types.SimpleNamespace(stdout=b'200')
   ns={'_runtime_serialized':lambda fn:fn,'prepare_runtime':lambda:None,'DATA_DIR':tmp,'tempfile':tempfile,'os':os,
       'private_write':lambda p,v:Path(p).write_text(v),'CK_FILE':str(Path(tmp)/'cookie-placeholder'),
       'UA':'SYNTHETIC','json':json,'subprocess':types.SimpleNamespace(run=fake_run)}
   fn=extracted('opt/nba-reprice/backend/p2pah_api.py',['_curl'],ns)['_curl']
   self.assertEqual(fn('GET','https://synthetic.invalid',cookie_jar=False),('200',b'SYNTHETIC_RESPONSE'))
   fn('GET','https://synthetic.invalid',cookie_jar=False)
   self.assertNotEqual(*paths);self.assertTrue(all(not Path(p).exists() for p in paths))

if __name__=='__main__':
 with patch('socket.socket.connect',side_effect=AssertionError('network forbidden')),patch('socket.getaddrinfo',side_effect=AssertionError('DNS forbidden')),\
      patch('subprocess.run',side_effect=AssertionError('real subprocess forbidden')),patch('subprocess.Popen',side_effect=AssertionError('real subprocess forbidden')):
  result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
 print(json.dumps({'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'passed':result.wasSuccessful(),'scope':'synthetic contracts; local temp files only; no production identities/writes/network'}))
 sys.exit(not result.wasSuccessful())
