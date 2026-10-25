import importlib.util,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('actual_release',R/'deploy/actual_release.py');release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
class Release(unittest.TestCase):
 def test_filter_release_covers_shared_summary_and_exact_new_assets(self):
  spec=importlib.util.spec_from_file_location('filter_release',R/'deploy/filter_release.py');wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)
  actual=types.SimpleNamespace(load_base=lambda:'original-publisher')
  with patch.dict(sys.modules,{'actual_release':actual}):self.assertEqual(wrapper.load_base(),'original-publisher')
  self.assertEqual(actual.SCOPE,'business-filter-layout-20261025');self.assertEqual(len(actual.TARGETS),11)
  self.assertEqual(actual.NEW,frozenset('source/'+n for n in ('business.js','home-business.js','legacy-business.js','shell.js','site_summary.py')))
  for n in ('live_summary.py','daily_archive.py','summary_bridge.py','site_summary.py'):self.assertEqual(actual.TARGETS['source/'+n],'/opt/fs-exact-range-20261001/'+n)
  self.assertFalse(any('units/' in n or 'auth' in n for n in actual.TARGETS))
 def test_rs_followup_is_exact_existing_backend_and_versioned_ui(self):
  spec=importlib.util.spec_from_file_location('backlog_release',R/'deploy/backlog_release.py');wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)
  actual=types.SimpleNamespace(load_base=lambda:'original-publisher')
  with patch.dict(sys.modules,{'actual_release':actual}):self.assertEqual(wrapper.load_base(),'original-publisher')
  self.assertEqual(actual.TARGETS['source/rs_backlog.py'],'/opt/fs-exact-range-20261001/rs_backlog.py');self.assertEqual(len(actual.TARGETS),6);self.assertEqual(actual.NEW,frozenset('source/'+n for n in ('business.js','home-business.js','legacy-business.js','shell.js')));self.assertEqual(actual.SCOPE,'business-dashboard-backlog-20261025')
 def test_exact_scope_and_targets(self):
  self.assertEqual(release.SCOPE,'business-dashboard-refresh-20261025');self.assertEqual(len(release.TARGETS),11)
  self.assertEqual(release.NEW,frozenset('source/'+n for n in ('business.js','home-business.js','legacy-business.js','shell.js','rs_backlog.py')))
  self.assertEqual(release.TARGETS['source/channel_effects.py'],'/opt/fs-hermes-fc/channel_effects.py')
  self.assertFalse(any('units/' in n or 'auth' in n for n in release.TARGETS))
 def test_original_publisher_and_health_wait_preserved(self):
  base=types.SimpleNamespace(approved_daily_group=lambda *args:False);original=types.SimpleNamespace(load_base=lambda:base);seen=[]
  with patch.dict(sys.modules,{'release':original,'shipping_readiness':types.SimpleNamespace(extend=lambda b,s:seen.append((b,s)))}):self.assertIs(release.load_base(),base)
  self.assertEqual(original.TARGETS,release.TARGETS);self.assertEqual(base.TARGETS_CHANGED_NAV,set(release.TARGETS.values()));self.assertEqual(seen,[(base,release.SCOPE)])
 def test_existing_knowledge_parent_reuses_exact_original_group_boundary(self):
  def group(m,root,item,info):return info.st_gid==0 or (m['scope']=='original-night' and item==root/'var/lib/fs-hermes-fc' and info.st_uid==0 and info.st_gid==9876 and info.st_mode==0o750)
  base=types.SimpleNamespace(approved_daily_group=group,HERMES_NIGHT_SCOPE='original-night',rooted=lambda r,p:r/p.lstrip('/'))
  with patch.dict(sys.modules,{'release':types.SimpleNamespace(load_base=lambda:base),'shipping_readiness':types.SimpleNamespace(extend=lambda *a:None)}):release.load_base()
  for gid,mode,uid,expected in [(9876,0o750,0,True),(9876,0o770,0,False),(9877,0o750,0,False),(9876,0o750,1,False)]:
   self.assertEqual(base.approved_daily_group({'scope':release.SCOPE},Path('/'),Path('/var/lib/fs-hermes-fc'),types.SimpleNamespace(st_uid=uid,st_gid=gid,st_mode=mode)),expected)
  self.assertFalse(base.approved_daily_group({'scope':'other'},Path('/'),Path('/var/lib/fs-hermes-fc'),types.SimpleNamespace(st_uid=0,st_gid=9876,st_mode=0o750)))
if __name__=='__main__':unittest.main()
