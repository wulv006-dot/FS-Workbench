"""Use synthetic teaching files; exercise actual digest/ownership/default-report boundaries."""
import ast,hashlib,json,os,stat,tempfile,types,unittest,sys
from pathlib import Path
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parents[1]/'source'

class Method(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)/'method';root.mkdir();self.root=root
  self.ns=dict(Path=Path,os=os,stat=stat,json=json,re=__import__('re'),hashlib=hashlib)
  exec(compile((SOURCE/'report_method.py').read_text('utf-8'),str(SOURCE/'report_method.py'),'exec'),self.ns)
  self.ns['HTML_DESIGN_ROOT']=root;rows=[]
  for name,role in self.ns['HTML_DESIGN_FILES'].items():
   raw=('SENTINEL '+name+' '+role).encode();p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
   rows.append(dict(path=name,role=role,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
  self.m=dict(contract='hermes-full-html-design-v1',version='fixture-new',status='test',root=str(root),files=rows,total_bytes=sum(r['bytes'] for r in rows),profile_skill={},context_policy={},permissions={'directory':'0700','file':'0600','owner':'0:0'})
  self.save();original_fstat=os.fstat;original_stat=Path.stat;self.bad_owner=False
  def fstat(fd):
   s=original_fstat(fd);return types.SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=42 if self.bad_owner else 0,st_gid=0,st_nlink=1,st_size=s.st_size)
  def pstat(p,*args,**kwargs):
   s=original_stat(p,*args,**kwargs)
   if stat.S_ISDIR(s.st_mode) and (p==root or root in p.parents):return types.SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=0,st_gid=0)
   return s
  for obj,name,fn in [(os,'fstat',fstat),(Path,'stat',pstat)]:
   m=patch.object(obj,name,side_effect=fn) if obj is os else patch.object(obj,name,fn);m.start();self.addCleanup(m.stop)
 def save(self):
  raw=json.dumps(self.m).encode();(self.root/'manifest.json').write_bytes(raw);self.ns['HTML_DESIGN_MANIFEST_SHA256']=hashlib.sha256(raw).hexdigest()
 def test_default_manual_automatic_and_pricing_load_same_method(self):
  hashes=[]
  for q in ['日报','周报','月报','定价策略','自动采集后报告','自定义区间']:
   text,receipt=self.ns['html_design_context'](q);hashes.append(receipt['manifest_sha256'])
   self.assertEqual(hashlib.sha256(text.encode()).hexdigest(),receipt['context_sha256'])
   for row in self.m['files']:self.assertIn('SENTINEL '+row['path'],text)
  self.assertEqual(len(set(hashes)),1)
 def test_new_bundle_contains_current_method_and_no_old_report_contract(self):
  for track in ('pricing','operations'):
   b=self.ns['method_bundle'](track);self.assertEqual(b['report_track'],track);self.assertEqual(b['active_skill'],'report-html-authoring')
   self.assertIn('SENTINEL SKILL.md',b['text']);self.assertIn('SENTINEL METHOD.md',b['methods_text']);self.assertEqual(b['weekly_method_text'],'');self.assertEqual(b['permissions'],[])
 def test_drift_missing_owner_symlink_and_unknown_path_fail_closed(self):
  f=self.root/'METHOD.md';raw=f.read_bytes();f.write_bytes(raw+b'changed')
  with self.assertRaisesRegex(ValueError,'material_drift'):self.ns['html_design_context']('日报')
  f.write_bytes(raw);self.bad_owner=True
  with self.assertRaisesRegex(ValueError,'leaf_boundary'):self.ns['html_design_context']('日报')
  self.bad_owner=False
  with patch.object(Path,'is_symlink',return_value=True):
   with self.assertRaisesRegex(ValueError,'link_rejected'):self.ns['html_design_context']('日报')
  self.m['files'][0]['path']='../outside';self.save()
  with self.assertRaisesRegex(ValueError,'fixed_files'):self.ns['html_design_context']('日报')
 def test_windows_and_no_new_business_permissions(self):
  module=types.ModuleType('report_tracks');module.request_report_kind=lambda b:b['test_kind']
  with patch.dict(sys.modules,{'report_tracks':module}):
   daily=self.ns['data_request_context'](dict(start='2026-10-16',end='2026-10-16',test_kind='daily'))
   weekly=self.ns['data_request_context'](dict(start='2026-10-05',end='2026-10-11',test_kind='weekly'))
   monthly=self.ns['data_request_context'](dict(start='2026-09-01',end='2026-09-30',test_kind='monthly'))
  self.assertIn('2026-10-09',daily);self.assertIn('2026-10-15',daily);self.assertIn('2026-09-28',weekly);self.assertIn('2026-10-04',weekly);self.assertIn('2026-08-01',monthly);self.assertIn('2026-08-31',monthly)
  self.assertIn('Order补缺',monthly);self.assertIn('用户亲自验收',monthly)
 def test_real_controller_fingerprints_materials_and_saves_unchanged_raw(self):
  s=(SOURCE/'controller.py').read_text('utf-8');ast.parse(s)
  self.assertIn("design_text,design_receipt=html_design_context(body['question'])",s)
  self.assertIn("admission['prompt']+=data_request_context(body)",s)
  self.assertIn("admission['prompt']+=design_text",s)
  self.assertLess(s.index("admission['prompt']+=design_text"),s.index("request['payload_sha256']=digest(request['body'])"))
  self.assertIn("save_raw(self.root,task['id'],output,book.evidence",s)
  for retired in ['html_design_presentation_policy','五个独立标题','四块齐全','Markdown开头必须']:self.assertNotIn(retired,s)
  business=(SOURCE/'business_context.py').read_text('utf-8');self.assertIn("'report-html-authoring/APPLICATIONS.md'",business);self.assertNotIn("'ops-report-brief/SKILL.md'",business)

if __name__=='__main__':unittest.main()
