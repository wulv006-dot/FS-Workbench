from datetime import datetime, timezone
from pathlib import Path
import json, tempfile, unittest
from unittest.mock import patch
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3 import ledger as module

NOW=datetime(2026,11,7,15,tzinfo=timezone.utc)
class SmartMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Ledger(Path(self.tmp.name)/'control.db')
        self.plan=dict(plan_id='p',revision=1,mode='smart',state='ACTIVE',generation='g',resources=['base:console','base:pc'],starts_at='2026-11-05T00:00:00+00:00',ends_at=None,parameters={},baseline_plan=dict(plan_id='old',revision=1,mode='revenue_sprint',parameters={},price_anchor={}),price_anchor={})
        self.db.put('pricing_plans','p',self.plan)
        self.db.put('metadata','generation',dict(id='g'))
        with self.db.transaction() as c:
            for r in self.plan['resources']:c.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)',(r,'p',1,'g'))
    def test_migration_preserves_original_plan_and_updates_owned_revision(self):
        self.db.put('operations','old-op',dict(operation_id='old-op',plan_id='p',status='NO_CHANGE',resources=['base:pc']))
        old=self.db.get('operations','old-op')
        with patch.object(module,'clock',return_value=NOW):result=self.db.migrate_smart_strategy('p',1,'wulv')
        self.assertEqual(result['plan_id'],'p');self.assertEqual(result['revision'],2)
        self.assertEqual(result['starts_at'],self.plan['starts_at'])
        self.assertEqual(result['smart_started_at'],NOW.isoformat())
        self.assertEqual(result['smart_strategy_version'],'smart-bidirectional-v2')
        self.assertEqual(result['parameters']['region_pricing'],'global')
        self.assertEqual(result['baseline_plan']['parameters']['competitor_policy'],'lootbar_primary_arabut_secondary_v1')
        self.assertEqual(self.db.get('operations','old-op'),old)
        self.assertEqual(self.db.migrate_smart_strategy('p',1,'wulv'),result)
        with self.db.connect() as c:self.assertEqual({r[0] for r in c.execute('SELECT revision FROM plan_ownership')},{2})
        with self.db.connect() as c:jobs=[json.loads(r[0]) for r in c.execute("SELECT body FROM durable_jobs WHERE kind='cycle'")]
        self.assertEqual(jobs,[dict(plan_id='p',revision=2,scheduled_at=NOW.isoformat())])
        self.assertEqual(self.db.migrate_smart_strategy('p',2,'wulv'),result)
    def test_unknown_or_running_cycle_cannot_be_migrated(self):
        self.db.put('operations','unknown',dict(status='UNKNOWN',resources=['base:pc']))
        with self.assertRaisesRegex(ValueError,'unresolved'):self.db.migrate_smart_strategy('p',1,'wulv')
        self.db.put('operations','unknown',dict(status='COMPLETED',resources=['base:pc']))
        self.db.enqueue('cycle','running',NOW,dict(plan_id='p',revision=1))
        with self.db.transaction() as c:c.execute("UPDATE durable_jobs SET state='running' WHERE id='running'")
        with self.assertRaisesRegex(ValueError,'running'):self.db.migrate_smart_strategy('p',1,'wulv')
        self.assertEqual(self.db.get('pricing_plans','p'),self.plan)
    def test_wrong_revision_and_owner_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'revision'):self.db.migrate_smart_strategy('p',2,'wulv')
        with self.db.transaction() as c:c.execute("UPDATE plan_ownership SET plan_id='other'")
        with self.assertRaises(ValueError):self.db.migrate_smart_strategy('p',1,'wulv')

    def test_api_migration_validates_fields(self):
        from fc_pricing_v3 import api
        with patch.object(api,'ledger',return_value=self.db):
            with self.assertRaisesRegex(ValueError,'fields_invalid'):
                api.post('plans/p/migrate-smart-strategy',dict(expected_revision=1,extra=True),'wulv')
            result=api.post('plans/p/migrate-smart-strategy',dict(expected_revision=1),'wulv')
        self.assertEqual(result['smart_strategy_version'],'smart-bidirectional-v2')
