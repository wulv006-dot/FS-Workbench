import importlib.util,json,tempfile,unittest,ast,types,threading
from pathlib import Path
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parents[1]/'source'
spec=importlib.util.spec_from_file_location('html_archive_candidate',SOURCE/'report_artifacts.py');artifacts=importlib.util.module_from_spec(spec);spec.loader.exec_module(artifacts)

class HTMLArchive(unittest.TestCase):
 def test_new_html_archive_never_creates_legacy_derivatives_and_keeps_exact_bytes(self):
  with tempfile.TemporaryDirectory() as d:
   task='c'*32;raw='<!doctype html><html><body>原稿</body></html>'
   artifacts.save_raw(d,task,raw,{},dict(html_design={'contract':'new'}))
   with patch.object(artifacts,'save_boss',side_effect=AssertionError('legacy derivative')):
    artifacts.save_result(d,task,{'html_design':{'contract':'new'}},raw)
   folder=Path(d)/'reports'/task
   self.assertEqual((folder/'model.txt').read_bytes(),(folder/'report.html').read_bytes())
   self.assertFalse(list(folder.glob('boss-*')))
 def test_old_archive_still_builds_legacy_report(self):
  with tempfile.TemporaryDirectory() as d:
   with patch.object(artifacts,'save_boss') as old:
    artifacts.save_result(d,'d'*32,{},'<html>old</html>');old.assert_called_once()
 def test_html_and_boss_routes_preserve_bytes_without_old_renderer(self):
  with tempfile.TemporaryDirectory() as d:
   task='a'*32;raw='<!doctype html><html><body>原稿<script>window.ready=true</script></body></html>'
   artifacts.save_raw(d,task,raw,{},dict(html_design={'contract':'new-method'}))
   with patch.object(artifacts,'save_boss',side_effect=AssertionError('old renderer must not run')):
    for kind in ('boss','html','raw'):
     got=artifacts.read_file(d,task,kind);self.assertEqual(got['content'],raw);self.assertTrue(got['mime'].startswith('text/plain'))
   p=Path(d)/'reports'/task/'model.txt';p.write_text('drift',encoding='utf-8')
   with self.assertRaisesRegex(ValueError,'artifact_changed'):artifacts.read_file(d,task,'boss')
 def test_actual_publish_method_bypasses_old_semantic_analysis_and_layout(self):
  tree=ast.parse((SOURCE/'controller.py').read_text('utf-8'));method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='publish_report')
  with tempfile.TemporaryDirectory() as d:
   task={'id':'b'*32,'state':'RUNNING','lease':'lease','run_id':'run'};raw='<!doctype html><html><body>原始交互</body></html>';meta={'raw_sha256':'1'*64,'skills_version':'new','skill_sha256':'2'*64,'html_design':{'contract':'new'}}
   root=Path(d);(root/'metadata.json').write_text(json.dumps(meta),encoding='utf-8');saved={}
   def forbidden(*a,**k):raise AssertionError('old report transformation called')
   def save_result(root,task_id,result,html):saved.update(result=result,html=html);return {'html_sha256':'3'*64,'result_sha256':'4'*64}
   import re
   env=dict(re=re,json=json,encoded=json.dumps,directory=lambda *a:root,management_context=types.SimpleNamespace(load=lambda *a:None,deliver=forbidden,render_html=forbidden),deliver_output=forbidden,render_report=forbidden,validate_output=None,request_report_kind=lambda *a:'daily',decode_output=lambda s:(_ for _ in ()).throw(ValueError()),save_result=save_result)
   exec(compile(ast.Module(body=[method],type_ignores=[]),'publish_candidate','exec'),env)
   tasks=types.SimpleNamespace(get=lambda *a:task,observe=lambda *a,**k:dict(task,state='VALIDATING'),change=lambda *a:None)
   service=types.SimpleNamespace(root=root,tasks=tasks,usage=lambda *a:{},lock=threading.RLock(),get_job=lambda *a:{'state':'RUNNING'},update=lambda *a,**k:saved.update(receipt=k),clock=lambda:None)
   env['publish_report'](service,'request','owner',{'start':'2026-10-16','end':'2026-10-16'},task,types.SimpleNamespace(capture_id='snapshot',evidence={}),raw,'high')
   self.assertEqual(saved['html'],raw);self.assertEqual(saved['result']['research_text'],raw);self.assertEqual(saved['receipt']['state'],'COMPLETED')
   self.assertEqual(saved['result']['output_format'],'html')
   plain='短结论：原样保留 <script>不执行</script>'
   env['publish_report'](service,'request','owner',{'start':'2026-10-16','end':'2026-10-16'},task,types.SimpleNamespace(capture_id='snapshot',evidence={}),plain,'high')
   self.assertEqual(saved['html'],plain);self.assertEqual(saved['result']['summary'],plain)
   self.assertEqual(saved['result']['output_format'],'text')
 def test_prompt_policy_and_security_unchanged(self):
  method=(SOURCE/'report_method.py').read_text('utf-8')
  self.assertNotIn('最终仅完整离线HTML',method)
  self.assertNotIn('请直接沿用认可范本',method)
  self.assertIn('不强制章节或清单',method)
  js=(SOURCE/'brain.js').read_text('utf-8')
  self.assertIn("const result=text;",js)
  self.assertIn("node('pre',content,host)",js)
  self.assertIn("sandbox=\"allow-scripts allow-modals allow-downloads\"",js)
  self.assertNotIn('allow-same-origin',js)
  self.assertIn("actual!==expected",js)
  self.assertIn("['product_orders','discount','cohort'].includes(dataKind)",js)
  self.assertIn('尚未发起调查',js)
  self.assertIn('不得把URL内容当事实',js)
 def test_plain_archive_is_txt_and_cannot_run_markup(self):
  with tempfile.TemporaryDirectory() as d:
   task='e'*32;raw='<html><script>alert(1)</script></html>'
   artifacts.save_raw(d,task,raw,{},dict(html_design={'contract':'new'}))
   for kind in ('html','boss'):
    value=artifacts.read_file(d,task,kind)
    self.assertEqual(value['content'],raw)
    self.assertTrue(value['filename'].endswith('.txt'))
    self.assertTrue(value['mime'].startswith('text/plain'))

if __name__=='__main__':unittest.main()
