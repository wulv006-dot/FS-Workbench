"""Backend half of the shared URL handoff contract; no child processes."""
import json
from pathlib import Path
import sys
import unittest
SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
sys.path.append(str(SOURCE.parents[1]/'admin-data-tools-20261018/candidate/hermes'))
from data_workspace_request import checked_request
CASES=json.loads((Path(__file__).parent/'handoff-cases.json').read_text('utf-8'))

class BrainHandoffTests(unittest.TestCase):
 def test_three_forms_match_real_backend_request(self):
  for case in CASES:
   if case['valid']:
    with self.subTest(case=case['name']):
     result=checked_request(case['expected'])
     self.assertEqual(result['kind'],case['expected']['kind'])
     for key,value in case['expected']['query'].items():self.assertEqual(result['query'][key],value)
 def test_archive_identity_and_window_remain_rejected_by_backend(self):
  for case in CASES:
   if not case['valid']:
    with self.subTest(case=case['name']):
     with self.assertRaises(ValueError):checked_request(case['expected'])

if __name__=='__main__':unittest.main()
