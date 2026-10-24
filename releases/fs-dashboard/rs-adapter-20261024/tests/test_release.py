import importlib.util,unittest,types,sys
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('rs_release',ROOT/'deploy/rs_release.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
class Release(unittest.TestCase):
    def test_shipping_followup_exact_scope(self):
        spec=importlib.util.spec_from_file_location('shipping_release',ROOT/'deploy/shipping_release.py')
        shipping=importlib.util.module_from_spec(spec);spec.loader.exec_module(shipping)
        self.assertEqual(len(shipping.TARGETS),11);self.assertEqual(len(shipping.NEW),4)
        self.assertEqual(shipping.TARGETS['source/rs_shipping.py'],'/opt/fs-exact-range-20261001/rs_shipping.py')
        self.assertFalse(any('auth' in p or 'timer' in p or 'hermes' in p for p in shipping.TARGETS.values()))
    def test_exact_scope(self):
        self.assertEqual(len(release.TARGETS),13);self.assertEqual(len(release.NEW),5)
        self.assertEqual(len(release.ALIASES),4)
        self.assertEqual(release.TARGETS['source/profit_daily.py'],'/opt/fs-transaction-snapshot/profit_daily.py')
        self.assertTrue(all('/fs-exact-range-' in t or '/fs-navigation-formal-static/' in t or t in ('/opt/fs-transaction-snapshot/profit_daily.py','/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf') for t in release.TARGETS.values()))
    def test_only_four_aliases_change(self):
        before=b'# keep all authentication and routes\n'+b'\n'.join(('location /x {auth_request /same; alias '+p+';}').encode() for p in release.ALIASES)
        after=release.candidate(before)
        for old,new in release.ALIASES.items():after=after.replace(new.encode(),old.encode())
        self.assertEqual(after,before)
    def test_drift_not_replaced(self):
        with self.assertRaises(ValueError):release.candidate(b'')
        before=b'\n'.join(('alias '+p+';').encode() for p in release.ALIASES)
        with self.assertRaises(ValueError):release.candidate(before+before)
    def test_changed_dependencies_keep_exact_target_cas(self):
        original=types.SimpleNamespace(load_base=lambda:types.SimpleNamespace())
        with patch.dict(sys.modules,{'release':original}):base=release.load_base()
        self.assertEqual(base.TARGETS_CHANGED_NAV,set(release.TARGETS.values()))
        self.assertEqual(original.TARGETS,release.TARGETS)
if __name__=='__main__':unittest.main()
