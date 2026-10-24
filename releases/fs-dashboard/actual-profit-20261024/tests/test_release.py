import importlib.util,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('actual_release',R/'deploy/actual_release.py');release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
class Release(unittest.TestCase):
 def test_exact_scope_and_targets(self):
  self.assertEqual(release.SCOPE,'business-actual-profit-20261024');self.assertEqual(len(release.TARGETS),13)
  self.assertEqual(release.NEW,frozenset('source/'+n for n in ('business.js','home-business.js','legacy-business.js','shell.js','actual_profit.py')))
  self.assertEqual(release.TARGETS['source/channel_effects.py'],'/opt/fs-hermes-fc/channel_effects.py')
  self.assertFalse(any('units/' in n or 'auth' in n for n in release.TARGETS))
 def test_original_publisher_and_health_wait_preserved(self):
  base=types.SimpleNamespace();original=types.SimpleNamespace(load_base=lambda:base);seen=[]
  with patch.dict(sys.modules,{'release':original,'shipping_readiness':types.SimpleNamespace(extend=lambda b,s:seen.append((b,s)))}):self.assertIs(release.load_base(),base)
  self.assertEqual(original.TARGETS,release.TARGETS);self.assertEqual(base.TARGETS_CHANGED_NAV,set(release.TARGETS.values()));self.assertEqual(seen,[(base,release.SCOPE)])
if __name__=='__main__':unittest.main()
