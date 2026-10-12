"""Check metadata-only dashboard availability without rebuilding business data."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'source/hooks.py'
if not SOURCE.exists():
    SOURCE = HERE.parents[3] / 'fs_hooks_rpg_alerts_20261009/source/hooks.py'
spec = importlib.util.spec_from_file_location('query_hooks', SOURCE)
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)
CATALOG = {'schemaVersion':2,'catalogId':'catalog-06cb55a0f928e4b1',
           'snapshotId':'catalog-06cb55a0f928e4b1',
           'scopeContractId':'all-websites-order-primary-admin-supplement-v1',
           'timezone':'Asia/Shanghai','currency':'USD',
           'dataPolicy':'metadata-only; native values are queried by date',
           'profiles':{'FC':{'primary':{'status':'not_provided'},'metrics':{},'dimensions':{}}}}


class DashboardMonitorTests(unittest.TestCase):
    def probe(self, catalog=CATALOG, historical=None):
        with patch.object(hooks,'read_catalog',return_value=catalog), \
             patch.object(hooks,'snapshot_probe',return_value=historical or {
                 'status':'stale','codes':['business_snapshot_stale'], 'legal_snapshot_retained':True}):
            return hooks.dashboard_probe()

    def test_legacy_mode_keeps_original_snapshot_rules(self):
        result=self.probe(None)
        self.assertEqual(result['codes'],['business_snapshot_stale'])

    def test_active_catalog_ignores_retired_snapshot_age_without_claiming_data_freshness(self):
        for stamp in ('1999-01-01','2099-01-01',None):
            catalog=copy.deepcopy(CATALOG);catalog['generatedAt']=stamp
            result=self.probe(catalog)
            self.assertEqual(result['status'],'queryable')
            self.assertEqual(result['codes'],[])
            self.assertEqual(result['data_freshness'],'not_observed_no_business_query')
            self.assertNotIn('generated_at',result)
            self.assertFalse(result['semantic_queries_verified'])
            self.assertTrue(result['historical_snapshot']['historical_only'])

    def test_wrong_contract_or_financial_values_are_rejected(self):
        for field,value in [('schemaVersion',3),('currency','CNY'),('scopeContractId','wrong'),
                            ('dataPolicy','snapshot'),('snapshotId','different'),('profiles',{})]:
            self.assertEqual(self.probe({**CATALOG,field:value})['status'],'unavailable')
        catalog=copy.deepcopy(CATALOG);catalog['profiles']['FC']['metrics']={'orders':1}
        self.assertEqual(self.probe(catalog)['status'],'unavailable')

    def test_unavailable_new_catalog_does_not_fallback_to_healthy_old_snapshot(self):
        with patch.object(hooks,'read_catalog',side_effect=ValueError('new_query_failed')), \
             patch.object(hooks,'snapshot_probe') as old:
            self.assertEqual(hooks.dashboard_probe()['codes'],['business_snapshot_unverified'])
        old.assert_not_called()

    def test_new_profiles_are_dynamic_and_missing_historical_snapshot_is_explicit(self):
        catalog=copy.deepcopy(CATALOG)
        catalog['profiles']['NEW_GAME']=copy.deepcopy(catalog['profiles']['FC'])
        result=self.probe(catalog,{'status':'unavailable','legal_snapshot_retained':False})
        self.assertEqual(result['profile_count'],2)
        self.assertEqual(result['status'],'queryable')
        self.assertFalse(result['legal_snapshot_retained'])

    def test_reuses_only_existing_provider_metadata_call(self):
        with tempfile.TemporaryDirectory() as name:
            source=Path(name)/'query_api.py'
            source.write_text("VERSION='fs-query-v1-20261012'\ndef snapshot():\n return "+repr(CATALOG)+"\n")
            with patch.object(hooks,'QUERY_SOURCE',source):
                self.assertEqual(hooks.read_catalog(),CATALOG)
            source.write_text("VERSION='fs-query-v1-20261009'\ndef snapshot():\n raise AssertionError('legacy call forbidden')\n")
            with patch.object(hooks,'QUERY_SOURCE',source):
                self.assertIsNone(hooks.read_catalog())

    def test_dashboard_failure_and_range_failure_cannot_pause_fc(self):
        value={'coin':{'config':{'system_enabled':True,'mode':'auto','revision':30},'job':{}},
               'issues':[{'level':'critical','code':c} for c in (
                   'business_snapshot_unverified','exact_range_health_unavailable')],
               'publication':{'platforms':[{'platform':p,'status':'matched'} for p in hooks.PLATFORMS]},
               'unknown_operations':[]}
        with patch.object(hooks,'bot_ready',return_value=False):
            self.assertTrue(all(not p['reasons'] for p in hooks.controls(value)['platforms'].values()))


if __name__ == '__main__':
    unittest.main()
