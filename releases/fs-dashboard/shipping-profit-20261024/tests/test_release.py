import importlib.util,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('profit_release',R/'deploy/profit_release.py');release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
class Release(unittest.TestCase):
 def test_exact_targets_and_no_business_write(self):
  self.assertEqual(len(release.TARGETS),12);self.assertEqual(len(release.NEW),5)
  self.assertEqual(release.TARGETS['source/profit_daily.py'],'/opt/fs-transaction-snapshot/profit_daily.py')
  self.assertTrue(all('/fs-exact-range-' in p or '/fs-navigation-formal-static/' in p or p in ('/opt/fs-transaction-snapshot/profit_daily.py','/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf') for p in release.TARGETS.values()))
 def test_original_guards_and_readiness_extension_remain(self):
  base=types.SimpleNamespace();original=types.SimpleNamespace(load_base=lambda:base);seen=[]
  with patch.dict(sys.modules,{'release':original,'shipping_readiness':types.SimpleNamespace(extend=lambda b,s:seen.append((b,s)))}):self.assertIs(release.load_base(),base)
  self.assertEqual(base.TARGETS_CHANGED_NAV,set(release.TARGETS.values()));self.assertEqual(seen,[(base,release.SCOPE)])
if __name__=='__main__':unittest.main()
