"""Current monitor rules retain genuine failures without retired price-policy alarms."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
from fc_pricing_v3 import monitoring
from fc_pricing_v3.ledger import Ledger
from fixtures import NOW
spec=importlib.util.spec_from_file_location('current_read_only_status',SOURCE/'read_only_status.py')
status=importlib.util.module_from_spec(spec);spec.loader.exec_module(status)


def snapshot():
    return dict(captured_at=NOW.isoformat(),gateway=dict(certificate_valid=True,http_status='401'),
        health=dict(api='ok',worker='ok',browser='ok',p2pah_session='ok',automation_timer='active',
                    https_certificate=dict(status='ok'),incomplete_executions=0,sources={}),
        automation=dict(interval_minutes=60),monitor=dict(latest_collection={}),
        v3=dict(enabled=True,issues=[],source_coverage=dict(status='verified')),
        publication=dict(status='matched',platforms=[dict(platform=p,status='matched') for p in ('PS','XBOX','PC')]),
        player_sync=dict(enabled=True),gallery=dict(settings=dict(enabled=False)))


class CurrentMonitor(unittest.TestCase):
    def test_v6_platform_financial_failure_is_not_shared_source_failure(self):
        from fc_pricing_v3.dispatch import CURVE_WRITE_PROTOCOL
        plan=dict(plan_id='p',revision=1,write_protocol=CURVE_WRITE_PROTOCOL)
        row=dict(plan_id='p',plan_revision=1,write_protocol=CURVE_WRITE_PROTOCOL,
                 snapshot_id='s',created_at=NOW.isoformat(),evidence={'checked_at':NOW.isoformat()},
                 result={'rows':[{'platform':'PC','status':'NO_FEASIBLE_CURVE'}]})
        coverage=monitoring.source_coverage([row],[plan],NOW)
        self.assertEqual(coverage['status'],'verified')
        self.assertEqual(coverage['issues'][0]['platform'],'PC')
        value=snapshot();value['v3'].update(source_coverage=coverage,issues=coverage['issues'])
        self.assertNotIn('source_coverage_unverified',[i['code'] for i in self.assess(value)['issues']])

    def assess(self,value):
        with patch.dict(sys.modules,{'fc27_quote_engine':SimpleNamespace(reference_sites=lambda sites:['U4GM'] if 'U4GM' in sites else [])}):
            return status.assess(value)

    def test_current_policy_does_not_warn_retired_competitors(self):
        result=self.assess(snapshot())
        self.assertFalse(any(x['code'].startswith('noncore_source_unavailable:') for x in result['issues']))
        self.assertNotIn('source_coverage_unverified',[x['code'] for x in result['issues']])

    def test_public_pending_is_observation_only_but_mismatch_stays_critical(self):
        for state in ('unavailable','not_checked_after_write','no_confirmed_write'):
            value=snapshot();value['publication']=dict(status=state,platforms=[])
            result=self.assess(value)
            self.assertNotEqual(result['status'],'critical')
            self.assertIn(dict(level='warning',code='coin_v3_public_observation_pending'),result['issues'])
        value=snapshot();value['publication']['platforms'][1]['status']='mismatch';value['publication']['status']='mismatch'
        self.assertIn(dict(level='critical',code='three_platform_publication_unverified'),self.assess(value)['issues'])

    def test_real_unknown_and_stale_sources_stay_critical(self):
        value=snapshot();value['v3']['issues']=[dict(level='critical',code='coin_v3_original_operation_unknown:original')]
        self.assertEqual(self.assess(value)['status'],'critical')
        value=snapshot();value['v3']['source_coverage']['status']='unverified'
        self.assertIn(dict(level='critical',code='source_coverage_unverified'),self.assess(value)['issues'])

    def test_legacy_public_and_source_requirements_are_retained(self):
        value=snapshot();value['v3']['enabled']=False;value['publication']={}
        result=self.assess(value)
        self.assertIn(dict(level='critical',code='three_platform_publication_unverified'),result['issues'])
        self.assertIn(dict(level='critical',code='source_coverage_unverified'),result['issues'])

    def test_known_no_dispatch_terminal_is_not_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=Ledger(root/'v3/control.sqlite3');(root/'config').mkdir()
            (root/'config/v3-control.json').write_text('{"enabled":true}')
            (root/'v3/heartbeat.json').write_text(json.dumps(dict(checked_at=NOW.isoformat())))
            for state in ('FAILED_BEFORE_WRITE','CANCELLED','UNKNOWN','PARTIALLY_APPLIED'):
                db.put('operations',state,dict(operation_id=state,status=state,created_at=NOW.isoformat(),plan_id='original',resources=['base:XBOX']))
            value=monitoring.projection(root,NOW)
            self.assertEqual({x['status'] for x in value['pending_operations']},{'UNKNOWN','PARTIALLY_APPLIED'})
            self.assertEqual(value['pending_count'],2)
            self.assertTrue(all(x['platforms']==['XBOX'] for x in value['pending_operations']))
            self.assertEqual(value['schedule']['status'],'needs_reconcile')

if __name__=='__main__':unittest.main()
