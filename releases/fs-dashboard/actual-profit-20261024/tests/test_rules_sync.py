import hashlib,json,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1]
class Rules(unittest.TestCase):
 def test_live_baseline_only_adds_the_approved_dashboard_section(self):
  current=(R/'source/business-baseline.md').read_bytes();section=(R/'tests/fixtures/dashboard-profit-rule.md').read_bytes()
  self.assertEqual(current.count(section),1)
  self.assertEqual(hashlib.sha256(current.replace(b'\n\n'+section,b'',1)).hexdigest(),'d97bc447297f3cb898f0ba211d2b51893d555e3a5f8459e093f05bd3b7346687')
  self.assertIn('v15双红线',current.decode());self.assertIn('逐单实际成本毛利',current.decode())
 def test_only_existing_wulv_fs_baseline_digest_changes(self):
  raw=(R/'source/knowledge-load-policy.json').read_bytes();digest=hashlib.sha256((R/'source/business-baseline.md').read_bytes()).hexdigest()
  self.assertEqual(raw.count(digest.encode()),1)
  old=raw.replace(digest.encode(),b'd97bc447297f3cb898f0ba211d2b51893d555e3a5f8459e093f05bd3b7346687',1)
  self.assertEqual(hashlib.sha256(old).hexdigest(),'1a446e554f4ae1677fbfbc8460fd64ece314fc97ca05eb393a4211d02f9da02b')
  routes=json.loads(raw)['task_routes']['routes'];selected=[r for r in routes if r.get('baseline_compatibility',{}).get('sha256')==digest]
  self.assertEqual(len(selected),1);self.assertEqual([selected[0][k] for k in ('owner','project','channel')],['wulv','FS','fs'])
if __name__=='__main__':unittest.main()
