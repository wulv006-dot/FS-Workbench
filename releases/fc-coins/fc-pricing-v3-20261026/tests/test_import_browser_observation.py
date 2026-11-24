from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest

from fc_pricing_v3.competitor_offers import POLICY
from fc_pricing_v3.financial import fingerprint

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
from import_browser_observation import import_quotes


class BrowserObservationImport(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Path(folder.name) / 'control.sqlite3'
        self.run_id = '00000000-0000-4000-8000-000000000001'
        self.now = datetime(2026, 11, 24, 9, 17, tzinfo=timezone.utc)
        self.batch = dict(run_id=self.run_id, captured_at=self.now.isoformat(), offers=[
            dict(source='U4GM', platform='PS', purchase_k='100', regular_price='6.50', bonus_k='5'),
            dict(source='U4GM', platform='PC', purchase_k='1000', regular_price='73.00', bonus_k='50')])
        self.snapshot = dict(origin='live_collector', created_at=self.now.isoformat(),
                             evidence=dict(competitor_policy=POLICY, competitor_offers=[], checked_at=self.now.isoformat()))
        self.observation = dict(run_id=self.run_id, status='observed', package_offers=[],
                                source_snapshot_sha256=fingerprint(self.snapshot['evidence']),
                                package_status={source: dict(status='missing', errors=['source_blocked'], attempts=[
                                    dict(node='187', errors=['source_blocked'], response_received=False)])
                                                for source in ('U4GM',)})
        with sqlite3.connect(self.db) as conn:
            conn.execute('CREATE TABLE pricing_snapshots(id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            conn.execute('CREATE TABLE market_observations(id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            conn.execute('INSERT INTO pricing_snapshots VALUES (?,?)', (self.run_id, json.dumps(self.snapshot)))
            conn.execute('INSERT INTO market_observations VALUES (?,?)', (self.run_id, json.dumps(self.observation)))

    def test_preview_then_update_only_missing_monitoring_slots(self):
        self.assertEqual(import_quotes(self.db, self.batch, self.now, False)['added'], 2)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(json.loads(conn.execute('SELECT body FROM market_observations').fetchone()[0]),
                             self.observation)
        self.assertEqual(import_quotes(self.db, self.batch, self.now, True)['added'], 2)
        self.batch['offers'][0]['regular_price'] = '4.00'
        duplicate = import_quotes(self.db, self.batch, self.now, True)
        self.assertEqual(duplicate['skipped_existing'], 2)
        self.assertFalse(duplicate['written'])
        with sqlite3.connect(self.db) as conn:
            data = json.loads(conn.execute('SELECT body FROM market_observations').fetchone()[0])
            self.assertEqual(data['package_offers'][0]['regular_price'], '6.5')
            self.assertEqual(data['package_offers'][0]['collection_node'], 'local')
            status = data['package_status']['U4GM']
            self.assertEqual(status['attempts'], self.observation['package_status']['U4GM']['attempts'])
            self.assertEqual(status['browser_readbacks'][0]['accepted'], [['PS', '100'], ['PC', '1000']])
            self.assertEqual(json.loads(conn.execute('SELECT body FROM pricing_snapshots').fetchone()[0]),
                             self.snapshot)

    def test_reject_old_round_and_non_observation_sources(self):
        with self.assertRaisesRegex(ValueError, 'browser_observation_stale'):
            import_quotes(self.db, dict(self.batch, captured_at='2026-11-24T08:00:00+00:00'), self.now, True)
        with self.assertRaisesRegex(ValueError, 'browser_observation_original_round_required'):
            import_quotes(self.db, dict(self.batch, captured_at='2026-11-24T09:16:59+00:00'), self.now, True)
        for source in ('Lootbar', 'IGGM'):
            self.batch['offers'][0]['source'] = source
            with self.assertRaisesRegex(ValueError, 'browser_observation_offer_scope'):
                import_quotes(self.db, self.batch, self.now, True)
