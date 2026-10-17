"""No server/model calls. Execute the exact candidate helpers and fingerprint expressions."""
import ast,hashlib,json,os,re,shutil,stat,tempfile,types,unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[4];SOURCE=Path(__file__).resolve().parents[1]/'source/controller.py'
TREE=ast.parse(SOURCE.read_text('utf-8'))
CONSTANTS=[n for n in TREE.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id.startswith('HTML_DESIGN_') for t in n.targets)]
HELPERS=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in ('html_design_context','html_design_presentation_policy')]
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
class HTMLDesign(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'context';self.root.mkdir()
  self.ns=dict(Path=Path,os=os,stat=stat,json=json,re=re);exec(compile(ast.Module(body=CONSTANTS+HELPERS,type_ignores=[]),str(SOURCE),'exec'),self.ns)
  # Synthetic material exercises the same nine-file shape without copying private examples into Git.
  files=[]
  for name,role in self.ns['HTML_DESIGN_FILES'].items():
   raw=(name+' 教学内容 '+('x'*17000)+' FINAL_SENTINEL_'+role).encode();f=self.root/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(raw);files.append(dict(path=name,role=role,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
  self.m=dict(contract='hermes-full-html-design-v1',version='fixture',status='fixture',root=str(self.root),files=files,total_bytes=sum(r['bytes'] for r in files),profile_skill={},context_policy={},permissions={'directory':'0700','file':'0600','owner':'0:0'})
  self.ns['HTML_DESIGN_ROOT']=self.root;self.save();self.bad_uid=False
  original_fstat=os.fstat;original_stat=Path.stat
  def fstat(fd):
   v=original_fstat(fd);return types.SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=1 if self.bad_uid else 0,st_gid=0,st_nlink=1,st_size=v.st_size)
  def path_stat(path,*args,**kwargs):
   v=original_stat(path,*args,**kwargs)
   if stat.S_ISDIR(v.st_mode) and (path==self.root or self.root in path.parents):return types.SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=0,st_gid=0)
   return v
  # Windows cannot emulate Linux uid/mode: boundary values are controlled explicitly.
  for obj,name,func in [(os,'fstat',fstat),(Path,'stat',path_stat)]:
   mock=patch.object(obj,name,side_effect=func) if obj is os else patch.object(obj,name,func);mock.start();self.addCleanup(mock.stop)
 def save(self):
  raw=json.dumps(self.m).encode();(self.root/'manifest.json').write_bytes(raw);self.ns['HTML_DESIGN_MANIFEST_SHA256']=hashlib.sha256(raw).hexdigest()
 def context(self,q='【完整HTML创作】生成经营报告'):return self.ns['html_design_context'](q)
 def test_only_explicit_prefix_activates_and_old_questions_do_not_read_files(self):
  for q in ('普通日报','引用：【完整HTML创作】','请勿使用【完整HTML创作】',' 【完整HTML创作】'):
   self.assertEqual(self.context(q),('',None))
 def test_all_nine_full_utf8_materials_and_actual_context_hash(self):
  text,receipt=self.context();self.assertEqual(len(receipt['files']),9);self.assertGreater(len(text),150000)
  for row in self.m['files']:self.assertIn('FINAL_SENTINEL_'+row['role'],text)
  self.assertEqual(receipt['output_status'],'raw_html_requires_isolated_browser_qa')
  self.assertEqual(receipt['context_sha256'],hashlib.sha256(text.encode()).hexdigest());self.assertEqual(receipt['context_bytes'],len(text.encode()))
  self.assertIn('完整DOCTYPE HTML',text)
 def test_missing_digest_owner_and_unknown_paths_fail_closed(self):
  f=self.root/self.m['files'][0]['path'];old=f.read_bytes();f.unlink()
  with self.assertRaisesRegex(ValueError,'context_unavailable'):self.context()
  f.write_bytes(old+b'drift')
  with self.assertRaisesRegex(ValueError,'material_drift'):self.context()
  f.write_bytes(old);self.bad_uid=True
  with self.assertRaisesRegex(ValueError,'leaf_boundary'):self.context()
  self.bad_uid=False;self.m['files'][0]['path']='../unapproved';self.save()
  with self.assertRaisesRegex(ValueError,'fixed_files'):self.context()
 def test_symlink_and_manifest_digest_drift_rejected(self):
  with patch.object(Path,'is_symlink',return_value=True):
   with self.assertRaisesRegex(ValueError,'link_rejected'):self.context()
  self.ns['HTML_DESIGN_MANIFEST_SHA256']='f'*64
  with self.assertRaisesRegex(ValueError,'manifest_drift'):self.context()
 def test_optional_history_digest_and_absence_compatibility(self):
  self.context();self.m['previousManifestSha256']='6'*64;self.save();self.context()
  for value in ('bad','A'*64,None,42):
   self.m['previousManifestSha256']=value;self.save()
   with self.assertRaisesRegex(ValueError,'manifest_history'):self.context()
  del self.m['previousManifestSha256'];self.m['unknownField']='not allowed';self.save()
  with self.assertRaisesRegex(ValueError,'manifest_contract'):self.context()
 def test_prompt_does_not_keep_superseded_display_instructions(self):
  policy=''.join(n.value for n in ast.walk(TREE) if isinstance(n,ast.Constant) and isinstance(n.value,str) and any(x in n.value for x in ('Markdown开头','五个独立标题','四块齐全','五段结论','五结论')))
  text=self.ns['html_design_presentation_policy'](policy)
  for forbidden in ('Markdown开头','五个独立标题','逐篇整理几条','每个标题下一段仅一句','四块齐全','五段结论','五结论'):self.assertNotIn(forbidden,text)
  for retained in ('支付同时保留订单量与金额','增长/下降百分比','Admin优先','国家TOP10','本次利润'):self.assertIn(retained,text)
  cls=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and any(isinstance(f,ast.FunctionDef) and f.name=='execute' for f in n.body));execute=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='execute')
  admission=next(n.value for n in ast.walk(execute) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='admission' for t in n.targets))
  prompt=next(v for k,v in zip(admission.keys,admission.values) if isinstance(k,ast.Constant) and k.value=='prompt');expr=compile(ast.Expression(prompt),'<actual-prompt>','eval');env=dict(body={'question':'普通日报','start':'2026-10-16','end':'2026-10-16'},book=types.SimpleNamespace(capture_id='capture'),FORMAT='OLD_FORMAT',design_receipt=None)
  self.assertTrue(eval(expr,env).endswith('OLD_FORMAT'));env['design_receipt']={'contract':'test'};self.assertNotIn('OLD_FORMAT',eval(expr,env))
 def test_actual_spec_fingerprint_and_payload_include_design_version(self):
  cls=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and any(isinstance(f,ast.FunctionDef) and f.name=='execute' for f in n.body));execute=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='execute');spec=next(n.value for n in ast.walk(execute) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='spec' for t in n.targets));expr=compile(ast.Expression(spec),'<actual-spec>','eval')
  text,receipt=self.context();env=dict(body={'question':'【完整HTML创作】日报','start':'2026-10-16','end':'2026-10-16'},book=types.SimpleNamespace(capture_id='c',skills={'version':'s'}),desktop_sha='a',design_receipt=receipt,date=date,timedelta=timedelta,digest=digest,POLICY_ID='policy');first=eval(expr,env)['template_version'];old_env=dict(env,design_receipt=None);self.assertEqual(eval(expr,old_env)['template_version'],'v6-shared-report-'+digest({**env['body'],'desktop_business_sha256':'a'})[:20]);env['design_receipt']=dict(receipt,context_sha256='f'*64);self.assertNotEqual(first,eval(expr,env)['template_version'])
  source=ast.get_source_segment(SOURCE.read_text('utf-8'),execute);self.assertLess(source.index("admission['prompt']=html_design_presentation_policy"),source.index("request['payload_sha256']=digest"));self.assertIn("**({'html_design':design_receipt} if design_receipt else {})",source)
 def test_actual_execute_submits_full_context_and_saves_raw_metadata_without_model(self):
  from datetime import datetime,timezone
  from unittest.mock import MagicMock
  import secrets,threading,re,sys
  cls=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and any(isinstance(f,ast.FunctionDef) and f.name=='execute' for f in n.body));execute=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='execute')
  captured={};raw_html='<!doctype html><html><body>原样<script>window.reportReady=true;</script></body></html>'
  book=types.SimpleNamespace(capture_id='capture',data={},evidence={})
  skills={'version':'skills','sha256':'skillsha'};knowledge={'skills':skills,'text':'stable learning','version':'knowledge','identity':{'knowledge_sha256':'learning'},'files':[],'memory_path':'profile','native_skip_reason':'fixture'}
  def atomic(path,value,mode=0o600):
   path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');captured.setdefault('atomic',[]).append((str(path),json.loads(json.dumps(value))))
  def submission(task):
   request={'body':{'input':'BASE TASK INPUT','session_id':'session'},'headers':{'Idempotency-Key':'one-task'},'payload_sha256':'before'};captured['submission']=request;return request
  env=dict(self.ns,date=date,timedelta=timedelta,datetime=datetime,timezone=timezone,secrets=secrets,re=re,digest=digest,encoded=lambda v:json.dumps(v,ensure_ascii=False),POLICY_ID='policy',FORMAT='OLD_FORMAT_MUST_NOT_REACH_MODEL',build_book=lambda *a,**k:book,loaded_learning=lambda *a:knowledge,attach_owner_history=lambda *a:None,gateway=lambda *a,**k:types.SimpleNamespace(budget=types.SimpleNamespace(policy={'model':'model'})),submission=submission,request_report_kind=lambda body:'daily',validate_admission=lambda code,value:value['run_id'],run_path=lambda rid,*a:{'path':'/v1/runs/'+rid},atomic=atomic,private_report=lambda output:False,save_raw=lambda *a:captured.update(raw=a),SAFE_MODEL_ERRORS=(),management_context=types.SimpleNamespace(request_snapshot=lambda body:None,attach=lambda *a:None))
  exec(compile(ast.Module(body=[execute],type_ignores=[]),str(SOURCE),'exec'),env)
  state={'state':'QUEUED'};task={'id':'a'*32,'state':'QUEUED'};db=MagicMock();db.__enter__.return_value=db;db.execute.return_value.fetchone.return_value={'version':'knowledge'}
  tasks=types.SimpleNamespace(db=lambda:db,create=lambda owner,spec:(captured.update(spec=spec) or dict(task,spec=spec)),get=lambda *a:dict(task,state='RUNNING'),reserve_dispatch=lambda *a:None,bind_run=lambda *a:None)
  def remote(method,path,body=None,*a,**kw):
   if method=='POST':captured['request']=json.loads(json.dumps(body));return 202,{'run_id':'run_'+'a'*32}
   return 200,{'status':'completed','output':raw_html,'runtime':{'fs_context_sha256':'background','fs_effective_input':{'status':'fixture'}}}
  service=types.SimpleNamespace(nightly=types.SimpleNamespace(deadline=lambda key:None),detail=None,daily=None,read_range=None,diagnostics=None,source_root=Path('source'),root=Path(self.tmp.name)/'fs',run_root=Path(self.tmp.name)/'runs',proxy=types.SimpleNamespace(background={},active=lambda task:False),tasks=tasks,action_history=lambda owner:[],lock=threading.RLock(),tokens={},books={},gateways={},clock=lambda:datetime(2026,10,17,tzinfo=timezone.utc),get_job=lambda *a:state,update=lambda key,**kw:state.update(kw),grants=types.SimpleNamespace(mint=lambda *a,**kw:'token',renew=lambda *a:None,revoke=lambda *a:None),remote=remote,mark_progress=lambda *a,**kw:None,usage=lambda *a:{},publish_report=lambda *a:captured.update(published=True))
  service.root.mkdir();service.run_root.mkdir()
  source_snapshots=types.ModuleType('source_snapshots');source_snapshots.prepared_brief=lambda *a:None
  background=types.ModuleType('background');background.task_context=lambda *a:('',{'context_sha256':'background'})
  with patch.dict(sys.modules,{'source_snapshots':source_snapshots,'background':background}):env['execute'](service,'request','owner',{'question':'【完整HTML创作】经营日报','start':'2026-10-16','end':'2026-10-16','mode':'daily','request_id':'request'})
  self.assertTrue(captured.get('published'),state);self.assertEqual(captured['raw'][2],raw_html);meta=captured['raw'][4];self.assertEqual(meta['html_design']['report_kind'],'daily');self.assertEqual(len(meta['html_design']['files']),9)
  self.assertEqual(captured['submission']['payload_sha256'],digest(captured['request']))
  actual=captured['request']['input'];self.assertNotIn('OLD_FORMAT_MUST_NOT_REACH_MODEL',actual)
  for row in self.m['files']:self.assertIn('FINAL_SENTINEL_'+row['role'],actual)
  for forbidden in ('Markdown开头必须','五个独立标题','每个标题下一段仅一句','逐篇整理几条','四块齐全'):self.assertNotIn(forbidden,actual)
  self.assertIn('只返回单一完整HTML文档',actual);self.assertIn(meta['html_design']['manifest_sha256'],actual)
  self.assertTrue(any(value.get('html_design')==meta['html_design'] for _,value in captured['atomic']));self.assertIn('html_design',meta['context_loading'])
 def test_raw_html_is_not_marked_design_accepted(self):
  source=SOURCE.read_text('utf-8');self.assertIn("delivery_status='raw_html_saved_not_design_accepted'",source);self.assertIn("if meta.get('html_design'):",source)
if __name__=='__main__':unittest.main()
