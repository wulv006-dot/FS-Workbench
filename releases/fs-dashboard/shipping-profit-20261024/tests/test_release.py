import importlib.util,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('profit_release',R/'deploy/profit_release.py');release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
class Release(unittest.TestCase):
 def test_label_followup_only_delegates_five_static_targets(self):
  spec=importlib.util.spec_from_file_location('label_fix',R/'deploy/label_fix.py');labels=importlib.util.module_from_spec(spec);spec.loader.exec_module(labels)
  self.assertEqual((len(labels.TARGETS),len(labels.NEW)),(5,4));self.assertEqual(set(labels.TARGETS),{'source/business.js','source/home-business.js','source/legacy-business.js','source/shell.js','generated/navigation.conf'})
  sentinel=object();ui=types.SimpleNamespace(load_base=lambda:sentinel)
  with patch.dict(sys.modules,{'ui_fix':ui}):self.assertIs(labels.load_base(),sentinel)
  self.assertEqual((ui.SCOPE,ui.TARGETS,ui.NEW),(labels.SCOPE,labels.TARGETS,labels.NEW))
 def test_static_followup_never_restarts_business_service(self):
  spec=importlib.util.spec_from_file_location('ui_fix',R/'deploy/ui_fix.py');ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
  self.assertEqual((len(ui.TARGETS),len(ui.NEW)),(4,3));calls=[];base=types.SimpleNamespace(restart_for=lambda m,f:calls.append((m,f)))
  with patch.dict(sys.modules,{'release':types.SimpleNamespace(load_base=lambda:base)}),patch('subprocess.run') as run:
   ui.load_base()
   with self.assertRaises(ValueError):base.restart_for({'scope':ui.SCOPE})
   base.restart_for({'scope':ui.SCOPE},object());self.assertEqual([c.args[0] for c in run.call_args_list],[['nginx','-t'],['systemctl','reload','nginx']]);self.assertEqual(calls,[])
 def test_exact_targets_and_no_business_write(self):
  self.assertEqual(len(release.TARGETS),12);self.assertEqual(len(release.NEW),5)
  self.assertEqual(release.TARGETS['source/profit_daily.py'],'/opt/fs-transaction-snapshot/profit_daily.py')
  self.assertTrue(all('/fs-exact-range-' in p or '/fs-navigation-formal-static/' in p or p in ('/opt/fs-transaction-snapshot/profit_daily.py','/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf') for p in release.TARGETS.values()))
 def test_original_guards_and_readiness_extension_remain(self):
  base=types.SimpleNamespace();original=types.SimpleNamespace(load_base=lambda:base);seen=[]
  with patch.dict(sys.modules,{'release':original,'shipping_readiness':types.SimpleNamespace(extend=lambda b,s:seen.append((b,s)))}):self.assertIs(release.load_base(),base)
  self.assertEqual(base.TARGETS_CHANGED_NAV,set(release.TARGETS.values()));self.assertEqual(seen,[(base,release.SCOPE)])
if __name__=='__main__':unittest.main()
