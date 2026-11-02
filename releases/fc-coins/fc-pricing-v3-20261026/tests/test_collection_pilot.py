from datetime import timedelta
from contextlib import closing, contextmanager
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
    @contextmanager
    def recheck_fixture(self):
        from fc_collection import pilot
        from fc_collection.public_sources import VERSIONS, arab_adapter
        from fc_collection.worker import Worker
        from fc_collection.adapters import SourceUnavailable
        with tempfile.TemporaryDirectory() as folder:
            root, current, calls = Path(folder), [NOW], []
            value = dict(platform='playstation', delivery='normal', quantity=100000, market='console',
                total=dict(currency='SAR', amountHalalah=3200), displayTotal=dict(currency='USD', amountMinor=853),
                priceVersion=False, pricedAt=NOW.isoformat())
            def fetch(*args):
                calls.append(args)
                return json.dumps(value).encode()
            def historical_adapter(task, transport):
                try:
                    return arab_adapter(task, transport)
                except SourceUnavailable as exc:
                    if task['assignment_generation'] <= 2 and str(exc).startswith('arab_quote_'):
                        raise ValueError('historical_parser_failure') from None
                    raise
            class Session:
                def __init__(self, *_): pass
                def __enter__(self): return self
                def __exit__(self, *_): pass
                def health(self, *args, **kwargs):
                    return dict(node_id='183', node_boot_id='a' * 32, adapters=VERSIONS)
                def resend(self, *args, **kwargs): return dict(status='idle')
                def run(self, task, principal, coordinator):
                    class Endpoint:
                        def __getattr__(self, name): return getattr(coordinator, name)
                        def claim_job(self, *args): return task
                    return Worker(Endpoint(), principal, {'ArabUT': historical_adapter}, root / 'spool',
                        fetch, clock=lambda: current[0]).run_once()
            config = root / 'config.json'
            config.write_text(json.dumps(dict(worker_digest='b' * 64)))
            def sleep(seconds): current[0] += timedelta(seconds=seconds)
            with patch.object(pilot, 'Session', Session), patch.object(pilot, 'ssh_command', return_value=['fixture']), \
                    patch.object(pilot, 'utc', side_effect=lambda: current[0]), patch.object(pilot.time, 'sleep', side_effect=sleep):
                yield lambda ident='original', **kwargs: pilot.run(config, root / 'state', ident, **kwargs), root, current, value, calls

    def test_final_diagnostic_group_preserves_two_failures_and_stops_at_six_requests(self):
        with self.recheck_fixture() as (run, root, current, value, calls):
            first = run()
            second = run('original-recheck', recheck_of='original')
            self.assertEqual(first['status'], 'source_unavailable')
            self.assertEqual(second['status'], 'source_unavailable')
            with closing(sqlite3.connect(root / 'state/collection.sqlite3')) as db:
                original = db.execute('SELECT * FROM collection_observations ORDER BY rowid').fetchall()
            value['priceVersion'] = 2841
            third = run('original-recheck-recheck', recheck_of='original-recheck')
            self.assertEqual(third['status'], 'valid_shadow_observation')
            current[0] += timedelta(days=2)
            run('original-recheck-recheck', recheck_of='original-recheck')
            self.assertEqual(len(calls), 6)
            with self.assertRaises(ValueError):
                run('original-recheck-recheck-recheck', recheck_of='original-recheck-recheck')
            with closing(sqlite3.connect(root / 'state/collection.sqlite3')) as db:
                self.assertEqual(db.execute('SELECT * FROM collection_observations ORDER BY rowid LIMIT 2').fetchall(), original)
                self.assertEqual(db.execute('SELECT SUM(count) FROM collection_permits').fetchone()[0], 6)

    def test_one_recheck_keeps_original_failure_and_lifetime_budget_even_after_window(self):
        with self.recheck_fixture() as (run, root, current, value, calls):
            first = run()
            self.assertEqual(first['source_reasons'], ['adapter_contract_invalid'])
            with closing(sqlite3.connect(root / 'state/collection.sqlite3')) as db:
                original = db.execute('SELECT * FROM collection_observations').fetchone()
            value['priceVersion'] = 2841
            current[0] += timedelta(days=2)
            second = run('original-recheck', recheck_of='original')
            self.assertEqual(second['status'], 'valid_shadow_observation')
            self.assertEqual(second['offers'], 2)
            self.assertFalse(second['pricing_consumption'])
            again = run('original-recheck', recheck_of='original')
            self.assertEqual(second['observed_at'], again['observed_at'])
            current[0] += timedelta(days=2)
            run('original-recheck', recheck_of='original')
            self.assertEqual(len(calls), 4)
            with closing(sqlite3.connect(root / 'state/collection.sqlite3')) as db:
                self.assertEqual(db.execute('SELECT * FROM collection_observations WHERE job=?', (first['job_id'],)).fetchone(), original)
                self.assertEqual(db.execute('SELECT SUM(count) FROM collection_permits').fetchone()[0], 4)
                policy = json.loads(db.execute('SELECT body FROM collection_sources').fetchone()[0])
                self.assertEqual((policy['generation'], policy['max_requests']), (2, 4))
            for ident, kwargs in [('third-run', {}), ('original-another', dict(recheck_of='original')),
                                  ('original-recheck-recheck', dict(recheck_of='original-recheck'))]:
                with self.subTest(ident=ident), self.assertRaises(ValueError): run(ident, **kwargs)
            self.assertEqual(len(calls), 4)

    def test_recheck_requires_original_terminal_parser_failure(self):
        with self.recheck_fixture() as (run, root, current, value, calls):
            with self.assertRaises(ValueError): run('original-recheck', recheck_of='original')
            value['priceVersion'] = 2841
            run()
            with self.assertRaises(ValueError): run('original-recheck', recheck_of='original')
            self.assertEqual(len(calls), 2)

    def test_recheck_fences_parallel_original_before_returning_from_validation(self):
        from fc_collection import pilot
        with self.recheck_fixture() as (run, root, current, value, calls):
            run()
            current[0] += timedelta(days=2)
            value['priceVersion'] = 2841
            verify = pilot.configure_recheck
            def competing_original(*args):
                result = verify(*args)
                with self.assertRaisesRegex(ValueError, 'generation_regression'):
                    run('parallel-original')
                return result
            with patch.object(pilot, 'configure_recheck', side_effect=competing_original):
                self.assertEqual(run('original-recheck', recheck_of='original')['status'], 'valid_shadow_observation')
            self.assertEqual(len(calls), 4)

    def test_recheck_preserves_source_block_and_does_not_send(self):
        with self.recheck_fixture() as (run, root, current, value, calls):
            run()
            with closing(sqlite3.connect(root / 'state/collection.sqlite3')) as db:
                policy = json.loads(db.execute('SELECT body FROM collection_sources').fetchone()[0])
                policy.update(blocked=True, cooldown_until=(current[0]+timedelta(hours=2)).timestamp())
                db.execute('UPDATE collection_sources SET body=?', (json.dumps(policy),))
                db.commit()
            result = run('original-recheck', recheck_of='original')
            self.assertEqual(result['status'], 'not_verified')
            self.assertEqual(len(calls), 2)
            with closing(sqlite3.connect(root / 'state/collection.sqlite3')) as db:
                actual = json.loads(db.execute('SELECT body FROM collection_sources').fetchone()[0])
                self.assertTrue(actual['blocked'])
                self.assertEqual(actual['cooldown_until'], policy['cooldown_until'])

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
