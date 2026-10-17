import importlib.util,json,tempfile,unittest,ast,types,threading
from pathlib import Path
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parents[1]/'source'
spec=importlib.util.spec_from_file_location('html_archive_candidate',SOURCE/'report_artifacts.py');artifacts=importlib.util.module_from_spec(spec);spec.loader.exec_module(artifacts)

class HTMLArchive(unittest.TestCase):
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
   env=dict(json=json,encoded=json.dumps,directory=lambda *a:root,management_context=types.SimpleNamespace(load=lambda *a:None,deliver=forbidden,render_html=forbidden),deliver_output=forbidden,render_report=forbidden,validate_output=None,request_report_kind=lambda *a:'daily',decode_output=lambda s:(_ for _ in ()).throw(ValueError()),save_result=save_result)
   exec(compile(ast.Module(body=[method],type_ignores=[]),'publish_candidate','exec'),env)
   tasks=types.SimpleNamespace(get=lambda *a:task,observe=lambda *a,**k:dict(task,state='VALIDATING'),change=lambda *a:None)
   service=types.SimpleNamespace(root=root,tasks=tasks,usage=lambda *a:{},lock=threading.RLock(),get_job=lambda *a:{'state':'RUNNING'},update=lambda *a,**k:saved.update(receipt=k),clock=lambda:None)
   env['publish_report'](service,'request','owner',{'start':'2026-10-16','end':'2026-10-16'},task,types.SimpleNamespace(capture_id='snapshot',evidence={}),raw,'high')
   self.assertEqual(saved['html'],raw);self.assertEqual(saved['result']['research_text'],raw);self.assertEqual(saved['receipt']['state'],'COMPLETED')

if __name__=='__main__':unittest.main()
