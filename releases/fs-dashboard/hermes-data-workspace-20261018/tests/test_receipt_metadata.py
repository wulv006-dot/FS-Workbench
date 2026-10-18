import ast
from pathlib import Path
import unittest
SOURCE=Path(__file__).resolve().parents[1]/'source'

class MethodReceiptTests(unittest.TestCase):
 def test_four_current_documents_do_not_claim_legacy_examples(self):
  tree=ast.parse((SOURCE/'controller.py').read_text('utf-8'))
  execute=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='execute')
  statement=next(n for n in ast.walk(execute) if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and any(k.arg=='teaching_examples' for k in n.value.keywords))
  receipt={'files':[{'path':name} for name in ('SKILL.md','METHOD.md','ACCEPTANCE.md','APPLICATIONS.md')]}
  env=dict(design_receipt=receipt,body={},request_report_kind=lambda body:'weekly')
  exec(compile(ast.Module(body=[statement],type_ignores=[]),'actual receipt statement','exec'),env)
  self.assertEqual(env['design_receipt']['teaching_examples'],[])
  self.assertEqual(env['design_receipt']['files'],receipt['files'])
  self.assertEqual(env['design_receipt']['report_kind'],'weekly')

if __name__=='__main__':unittest.main()
