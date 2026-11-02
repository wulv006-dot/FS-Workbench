from datetime import timedelta
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from collection_cases import NOW


class ReadOnlyPilot(unittest.TestCase):
    def test_other_pending_run_is_not_dispatched_under_this_pilot_id(self):
        from fc_collection import pilot
        from fc_collection.contracts import build_job
        from fc_collection.coordinator import Coordinator
        from fc_collection.public_sources import VERSIONS
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            current = [NOW]
            state = root / 'state'
            c = Coordinator(state / 'collection.sqlite3')
            c.enqueue(build_job(dict(run_id='older-unstarted', created_at=NOW.isoformat()), 'ArabUT',
                dict(requested_platforms=['PS', 'XBOX'], region_scope=[21], quantity_scope=dict(purchase_quantity='100', quantity_unit='K'),
                     discount_scope='coupon_excluded', currency='USD', policy_version='arab-shadow-two-request-v1',
                     adapter_version=VERSIONS['ArabUT'], assignment_generation=1, total_attempt_limit=1, total_request_budget=2),
                (NOW + timedelta(seconds=60)).isoformat()))
            class Session:
                def __init__(self, *_):
                    pass
                def __enter__(self):
                    return self
                def __exit__(self, *_):
                    pass
                def health(self, *args, **kwargs):
                    return dict(node_id='183', node_boot_id='a' * 32, adapters=VERSIONS)
                def resend(self, *args):
                    return dict(status='idle')
                def run(self, task, *args):
                    raise AssertionError('unrequested run dispatched: ' + task['parent_run_id'])
            config = root / 'config.json'; config.write_text(json.dumps(dict(worker_digest='b' * 64)))
            def sleep(seconds):
                current[0] += timedelta(seconds=seconds)
            with patch.object(pilot, 'Session', Session), patch.object(pilot, 'ssh_command', return_value=['fixture']), \
                    patch.object(pilot, 'utc', side_effect=lambda: current[0]), patch.object(pilot.time, 'sleep', side_effect=sleep):
                result = pilot.run(config, state, 'new-explicit-run')
            self.assertEqual(result['status'], 'original_run_pending')
            with c.transaction() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM collection_permits').fetchone()[0], 0)

    def test_repeating_original_pilot_keeps_observation_time_and_two_request_budget(self):
        from fc_collection import pilot
        from fc_collection.public_sources import VERSIONS, arab_adapter
        from fc_collection.worker import Worker
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            current = [NOW]
            value = dict(platform='playstation', delivery='normal', quantity=100000, market='console',
                total=dict(currency='SAR', amountHalalah=3750), displayTotal=dict(currency='USD', amountMinor=1000),
                priceVersion='fixture', pricedAt=NOW.isoformat())
            class Session:
                def __init__(self, *_):
                    pass
                def __enter__(self):
                    return self
                def __exit__(self, *_):
                    pass
                def health(self, *args, **kwargs):
                    return dict(node_id='183', node_boot_id='a' * 32, adapters=VERSIONS)
                def resend(self, *args, **kwargs):
                    return dict(status='idle')
                def run(self, task, principal, coordinator):
                    class Endpoint:
                        def __getattr__(self, name):
                            return getattr(coordinator, name)
                        def claim_job(self, *args):
                            return task
                    return Worker(Endpoint(), principal, {'ArabUT': arab_adapter}, root / 'spool',
                        lambda *_: json.dumps(value).encode(), clock=lambda: current[0]).run_once()
            config = dict(host='172.18.108.183', user='fs-fc-collector', identity_file='not-used',
                          known_hosts='not-used', worker_digest='b' * 64)
            config_path = root / 'access.json'
            config_path.write_text(json.dumps(config))
            def sleep(seconds):
                current[0] += timedelta(seconds=seconds)
            with patch.object(pilot, 'Session', Session), patch.object(pilot, 'ssh_command', return_value=['fixture']), \
                    patch.object(pilot, 'utc', side_effect=lambda: current[0]), patch.object(pilot.time, 'sleep', side_effect=sleep):
                first = pilot.run(config_path, root / 'state', 'shadow-original')
                second = pilot.run(config_path, root / 'state', 'shadow-original')
            self.assertEqual(first['status'], 'valid_shadow_observation')
            self.assertEqual(first['job_id'], second['job_id'])
            self.assertEqual(first['observed_at'], second['observed_at'])
            self.assertEqual(first['offers'], 2)
            self.assertFalse(first['pricing_consumption'])
            with closing(sqlite3.connect(root / 'state/collection.sqlite3')) as db:
                self.assertEqual(db.execute('SELECT SUM(count) FROM collection_permits').fetchone()[0], 2)
