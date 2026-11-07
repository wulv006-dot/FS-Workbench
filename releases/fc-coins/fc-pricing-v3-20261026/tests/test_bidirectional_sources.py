from datetime import datetime, timezone
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.selective_sources import source_plan, planned_source_coverage

class BidirectionalSourcesTest(unittest.TestCase):
    def test_core_sources_include_pc_and_item_is_auxiliary(self):
        plan=source_plan('smart',dict(competitor_policy='lootbar_primary_arabut_secondary_v1',region_pricing='global'))
        self.assertEqual(plan['required_markets'],['Lootbar','ArabUT'])
        self.assertEqual(plan['auxiliary_markets'],['ItemD2R'])
        self.assertEqual(plan['market_platforms']['ArabUT'],['PS','XBOX','PC'])
        now=datetime(2026,11,7,15,tzinfo=timezone.utc)
        row=dict(source='ArabUT',platform='PC',currency='USD',base_k='100',total_usd='9.47',delivery='standard',selection_verified=True,checked_at=now.isoformat())
        coverage=planned_source_coverage(dict(run_id='r',arab_ut_status=dict(offers=[row])),plan,now)
        self.assertIn('ArabUT',coverage['reference_sources']['PC'])
        self.assertNotIn('ItemD2R',coverage['optional_sources'])

    def test_legacy_sources_unchanged(self):
        self.assertEqual(source_plan('smart')['required_markets'],['Lootbar','ItemD2R'])

    def test_auxiliary_observation_keeps_sealed_snapshot_and_is_idempotent(self):
        from fc_pricing_v3 import observations, runtime
        with tempfile.TemporaryDirectory() as tmp:
            db=Ledger(Path(tmp)/'db')
            snapshot=dict(evidence=dict(source_plan=dict(auxiliary_markets=['ItemD2R']),reference_market=dict(status='not_required')))
            db.put('pricing_snapshots','r',snapshot)
            with patch.object(runtime,'ledger',return_value=db), patch.object(observations,'collect_reference_market',return_value=dict(status='captured',offers=[])) as collect:
                result=observations.observe('r')
                self.assertEqual(observations.observe('r'),result)
            collect.assert_called_once_with('r')
            self.assertEqual(db.get('pricing_snapshots','r'),snapshot)
            self.assertEqual(result['reference_market']['status'],'captured')
