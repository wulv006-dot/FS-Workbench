import ast,json,tempfile,types,sys,unittest,hashlib
from pathlib import Path
from unittest.mock import MagicMock,patch
SOURCE=Path(__file__).resolve().parents[1]/'source'

class Followup(unittest.TestCase):
 def run_case(self,html):
  method=next(n for n in ast.parse((SOURCE/'continuation.py').read_text('utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='load_report_followup')
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);evidence={'ev_'+'a'*24:{'evidence_id':'ev_'+'a'*24,'source':'source','captured_at':'2026-10-17T01:00:00+00:00','query':{'profile':'FC27'},'data':{'complete_value':'x'*50000}}};raw=json.dumps(evidence).encode();(root/'evidence.json').write_bytes(raw);meta={'evidence_sha256':hashlib.sha256(raw).hexdigest()}
   if html:meta['html_design']={'contract':'new'}
   (root/'metadata.json').write_text(json.dumps(meta),encoding='utf-8')
   body={'start':'2026-10-16','end':'2026-10-16'};row={'body':json.dumps(body),'task_id':'task','owner':'owner'}
   db=MagicMock();db.__enter__.return_value=db;db.execute.return_value.fetchone.return_value=row
   tasks=types.SimpleNamespace(db=lambda:db,get=lambda *a:{'id':'task','state':'PARTIAL','spec':{'knowledge_version':'new'}})
   def frozen(*a):return types.SimpleNamespace(evidence=json.loads(raw))
   module=types.ModuleType('report_artifacts');module.directory=lambda *a,**kw:root;module.digest_bytes=lambda b:hashlib.sha256(b).hexdigest();module.read_file=lambda *a:{'content':'<!doctype html><html>original HTML</html>' if a[-1]=='raw' else json.dumps({'research_text':'legacy text'})}
   env=dict(json=json,re=__import__('re'),load_bundle=lambda *a:{'version':'new'},compatible_version=lambda a,b:a==b,FrozenEvidenceBook=frozen,encoded=json.dumps)
   exec(compile(ast.Module(body=[method],type_ignores=[]),'actual_followup','exec'),env)
   with patch.dict(sys.modules,{'report_artifacts':module}):book=env['load_report_followup'](tasks,'b'*32,body['start'],body['end'],'source',root)
   return book,json.loads(book.continuation_context)
 def test_html_uses_exact_original_and_complete_index_without_discarding_frozen_data(self):
  book,context=self.run_case(True);self.assertLess(len(book.continuation_context),2000);self.assertTrue(context['original_report'].startswith('<!doctype html>'));self.assertIn('query',next(iter(context['evidence'].values())));self.assertNotIn('data',next(iter(context['evidence'].values())));self.assertEqual(len(next(iter(book.evidence.values()))['data']['complete_value']),50000)
 def test_legacy_still_receives_full_context(self):
  book,context=self.run_case(False);self.assertEqual(context['original_report'],'legacy text');self.assertEqual(len(next(iter(context['evidence'].values()))['data']['complete_value']),50000)

if __name__=='__main__':unittest.main()
