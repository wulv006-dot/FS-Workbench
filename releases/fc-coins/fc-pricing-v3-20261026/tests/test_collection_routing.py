from copy import deepcopy
from datetime import timedelta
import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from collection_cases import NOW, context, identity, observation, policy
from fc_collection.contracts import build_job, validate_observation
from fc_collection.public_sources import arab_offers, VERSIONS


def quote():
    return dict(platform='playstation', delivery='normal', quantity=100000, market='console',
        total=dict(currency='SAR', amountHalalah=3750), displayTotal=dict(currency='USD', amountMinor=1000),
        priceVersion=2841, pricedAt=NOW.isoformat())


def arab_context():
    return dict(context(), requested_platforms=['PS', 'XBOX'], region_scope=[21],
                adapter_version=VERSIONS['ArabUT'], total_attempt_limit=1, total_request_budget=3)


class Provenance(unittest.TestCase):
    def setUp(self):
        self.task = dict(build_job(dict(run_id='run-1', created_at=NOW.isoformat()), 'ArabUT',
            arab_context(), (NOW + timedelta(seconds=200)).isoformat()), attempt_id='attempt-1',
            lease_epoch=1, node_id='183', node_boot_id='boot-1')
        self.body = observation(self.task)
        self.body['offers'] = arab_offers(quote(), NOW)

    def test_full_original_quote_contract_and_native_version_survive_projection(self):
        from fc_collection.contracts import to_arab_status
        result = to_arab_status([self.body], self.task, NOW)
        self.assertEqual(result['coverage']['PC'], 'not_requested')
        self.assertEqual([r['platform'] for r in result['offers']], ['PS', 'XBOX'])
        for row in result['offers']:
            self.assertEqual((row['original_currency'], row['original_amount_minor']), ('SAR', 3750))
            self.assertEqual(row['price_version'], 2841)
            self.assertIs(type(row['price_version']), int)
            self.assertEqual(row['priced_at'], NOW.isoformat())
            self.assertEqual(row['captured_at'], NOW.isoformat())
            self.assertEqual(row['delivered_k'], '100')
            self.assertEqual(row['comparison_currency'], 'USD')
            self.assertEqual(row['quantity_basis'], 'official_quote_quantity_bonus_not_advertised')
            self.assertEqual(row['platform_mapping'], 'official_playstation_market_console_shared_PS_Xbox')
            self.assertEqual(row['url'], 'https://www.arab-ut.com/en/coins/quote?platform=playstation&delivery=normal&quantity=100000')

    def test_old_observation_can_be_ACKed_but_cannot_supply_incomplete_production_quote(self):
        from fc_collection.contracts import to_arab_status
        for row in self.body['offers']:
            row.pop('source_metadata', None)
        validate_observation(self.body, self.task, NOW)
        with self.assertRaises(ValueError):
            to_arab_status([self.body], self.task, NOW)

    def test_untrusted_metadata_and_inconsistent_console_quote_are_rejected(self):
        from fc_collection.contracts import to_arab_status
        for change in ({'original_amount_minor': True}, {'price_version': []}, {'priced_at': 'invalid'},
                       {'original_currency': 'USD'}, {'cookie': 'must-not-export'}):
            body = deepcopy(self.body)
            body['offers'][0]['source_metadata'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_observation(body, self.task, NOW)
        for change in ({'bonus_quantity': '5', 'delivered_quantity': '105'}, {'amount': '11'},
                       {'settlement_currency': 'USD', 'conversion_source': 'not_required'}):
            body = deepcopy(self.body)
            body['offers'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                to_arab_status([body], self.task, NOW)


class Routing(unittest.TestCase):
    def setUp(self):
        from fc_collection import client
        from fc_collection.coordinator import Coordinator
        self.client = client
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        self.config = folder / 'routing.json'
        self.database = folder / 'collection.sqlite3'
        self.parent = dict(run_id='run-1', created_at=NOW.isoformat(), deadline_at=(NOW + timedelta(seconds=200)).isoformat())
        self.local = Mock(return_value=dict(status='available', offers=['original']))
        self.patch = patch.multiple(client, ROUTING=self.config, DATABASE=self.database, ACCESS=folder / 'access.json')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        # Test containers run as65534; production root-owned file checks have a separate test.
        private = patch.object(client, 'private_file', side_effect=lambda path: self.assertTrue(path.is_file() and not path.is_symlink()))
        private.start()
        self.addCleanup(private.stop)
        self.coordinator = Coordinator(self.database)
        self.source_policy = dict(policy(), origin='https://www.arab-ut.com', nodes=['183'],
                                  adapter_version=VERSIONS['ArabUT'])
        self.coordinator.configure_source('ArabUT', self.source_policy)
        self.config.write_text(json.dumps(dict(schema_version=1, remote_result_mode='consume', assignment_generation=1)))
        self.config.chmod(0o600)

    def collect(self, **kw):
        with patch.object(self.client, 'utc', return_value=NOW):
            return self.client.arab_normal(self.local, self.parent, **kw)

    def accepted(self):
        self.coordinator.register_node(identity(), ['ArabUT'], NOW - timedelta(seconds=6))
        job = build_job(self.parent, 'ArabUT', dict(arab_context(), requested_platforms=['PS','XBOX','PC'], total_request_budget=4), self.parent['deadline_at'])
        self.coordinator.enqueue(job)
        task = self.coordinator.claim_job(identity(), ['ArabUT'], NOW)
        body = observation(task)
        body['offers'] = arab_offers(quote(), NOW)
        self.coordinator.reserve_request(identity(), task['job_id'], task['lease_epoch'], dict(count=1), NOW)
        self.assertEqual(self.coordinator.submit_observation(identity(), body, NOW)['status'], 'accepted')
        return task

    def test_absent_off_shadow_and_pinned_local_use_original_without_remote_or_DB_creation(self):
        self.config.unlink()
        with patch.object(self.client, 'Coordinator', side_effect=AssertionError('no ledger')):
            self.assertEqual(self.collect(), self.local.return_value)
            for mode in ('off', 'shadow'):
                self.config.write_text(json.dumps(dict(schema_version=1, remote_result_mode=mode, assignment_generation=1)))
                self.config.chmod(0o600)
                self.assertEqual(self.collect(), self.local.return_value)
            self.config.write_text('invalid config ignored by pinned local')
            self.assertEqual(self.collect(pinned=dict(mode='local')), self.local.return_value)

    def test_same_run_reads_original_receipt_without_SSH_and_ignores_a_later_deadline(self):
        task = self.accepted()
        self.parent['deadline_at'] = (NOW + timedelta(seconds=230)).isoformat()
        with patch.object(self.client, 'Session', side_effect=AssertionError('no extra GET')):
            result = self.collect()
            repeated = self.collect()
        self.assertEqual(result, repeated)
        self.assertEqual(result['offers'][0]['captured_at'], NOW.isoformat())
        self.local.assert_not_called()
        with self.coordinator.transaction() as db:
            self.assertEqual(self.coordinator._get(db, 'collection_jobs', task['job_id'])['deadline_at'], task['deadline_at'])

    def test_expired_job_unknown_connection_and_source_block_do_not_fallback_or_renew(self):
        task = self.accepted()
        with patch.object(self.client, 'utc', return_value=NOW + timedelta(seconds=901)), \
                patch.object(self.client, 'Session', side_effect=AssertionError('stale original')):
            result = self.client.arab_normal(self.local, self.parent)
        self.assertEqual(result['offers'], [])
        self.local.assert_not_called()
        with self.coordinator.transaction() as db:
            source = self.coordinator._get(db, 'collection_sources', 'ArabUT')
            source['blocked'] = True
            self.coordinator._put(db, 'collection_sources', 'ArabUT', source)
        with patch.object(self.client, 'Session', side_effect=AssertionError('blocked')):
            self.assertEqual(len(self.collect()['offers']), 2)
        self.local.assert_not_called()

    def test_inflight_turnoff_does_not_consume_or_restart_direct_collection(self):
        self.accepted()
        original = self.client.read_routing
        reads = []
        def read():
            value = original()
            reads.append(1)
            if len(reads) > 1:
                value['remote_result_mode'] = 'off'
            return value
        with patch.object(self.client, 'read_routing', side_effect=read):
            self.assertEqual(self.collect()['offers'], [])
        self.local.assert_not_called()

    def test_claim_is_targeted_and_does_not_lease_another_run(self):
        self.coordinator.register_node(identity(), ['ArabUT'], NOW - timedelta(seconds=6))
        other = build_job(dict(self.parent, run_id='other'), 'ArabUT', arab_context(), self.parent['deadline_at'])
        target = build_job(self.parent, 'ArabUT', arab_context(), self.parent['deadline_at'])
        self.coordinator.enqueue(other)
        self.coordinator.enqueue(target)
        leased = self.coordinator.claim_job(identity(), ['ArabUT'], NOW, job_id=target['job_id'])
        self.assertEqual(leased['job_id'], target['job_id'])
        with self.coordinator.transaction() as db:
            self.assertEqual(db.execute('SELECT state FROM collection_jobs WHERE id=?', (other['job_id'],)).fetchone()[0], 'PENDING')

    def test_generation_change_does_not_restart_same_parent_with_a_new_budget(self):
        self.accepted()
        self.assertEqual(len(self.collect()['offers']), 2)
        self.coordinator.configure_source('ArabUT', dict(self.source_policy, generation=2))
        self.config.write_text(json.dumps(dict(schema_version=1, remote_result_mode='consume', assignment_generation=2)))
        self.config.chmod(0o600)
        with patch.object(self.client, 'Session', side_effect=AssertionError('pinned run')):
            self.assertEqual(self.collect()['offers'], [])
        self.local.assert_not_called()
        with self.coordinator.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM collection_jobs').fetchone()[0], 1)

    def test_unknown_request_is_not_replayed_and_original_spool_can_be_reconciled(self):
        self.client.ACCESS.write_text(json.dumps(dict(worker_digest='a'*64)))
        self.coordinator.register_node(identity(), ['ArabUT'], NOW - timedelta(seconds=6))
        runs = []
        pending = []
        endpoint = self.coordinator
        class Peer:
            def __init__(self, *a, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def health(self, *a, **kw):
                return dict(identity(), adapters=VERSIONS)
            def resend(self, principal, coordinator):
                if pending:
                    coordinator.submit_observation(principal, pending.pop(), NOW)
                    return dict(status='accepted')
                return dict(status='idle')
            def run(self, task, principal, coordinator, **kwargs):
                runs.append(task['job_id'])
                endpoint.reserve_request(principal, task['job_id'], task['lease_epoch'], dict(count=1), NOW)
                body = observation(task)
                body['offers'] = arab_offers(quote(), NOW)
                pending.append(body)
                raise OSError('connection lost before ACK')
        with patch.object(self.client, 'Session', Peer), patch.object(self.client, 'ssh_command', return_value=[]), \
                patch.object(self.client.time, 'sleep'):
            self.assertEqual(self.collect()['offers'], [])
            recovered = self.collect()
            self.assertEqual(len(recovered['offers']), 2)
            self.assertEqual(recovered, self.collect())
        self.assertEqual(len(runs), 1)
        self.local.assert_not_called()
        with self.coordinator.transaction() as db:
            self.assertEqual(db.execute('SELECT SUM(count) FROM collection_permits').fetchone()[0], 1)

    def test_valid_original_platform_receipt_survives_later_origin_block_without_new_request(self):
        self.accepted()
        with self.coordinator.transaction() as db:
            source=self.coordinator._get(db,'collection_sources','ArabUT')
            source['blocked']=True
            self.coordinator._put(db,'collection_sources','ArabUT',source)
        with patch.object(self.client,'Session',side_effect=AssertionError('blocked source cannot request')):
            result=self.collect()
        self.assertEqual(result['status'],'partial')
        self.assertEqual({row['platform'] for row in result['offers']},{'PS','XBOX'})
        self.assertEqual([row['platform'] for row in result['missing']],['PC'])
        self.local.assert_not_called()

    def test_failed_health_does_not_start_local_or_source_request(self):
        self.client.ACCESS.write_text('{}')
        with patch.object(self.client, 'ssh_command', return_value=[]), \
                patch.object(self.client, 'Session', side_effect=OSError('node unavailable')):
            self.assertEqual(self.collect()['offers'], [])
        self.local.assert_not_called()
        with self.coordinator.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM collection_permits').fetchone()[0], 0)

    def test_off_branch_preserves_legacy_error_instead_of_relabeling_it_remote(self):
        self.config.unlink()
        self.local.side_effect = ValueError('original selection failure')
        with self.assertRaisesRegex(ValueError, 'original selection failure'):
            self.collect()

    def test_pinned_local_keeps_original_input_but_does_not_bypass_origin_denial(self):
        with self.coordinator.transaction() as db:
            source=self.coordinator._get(db,'collection_sources','ArabUT')
            source['blocked']=True
            self.coordinator._put(db,'collection_sources','ArabUT',source)
        with patch.object(self.client,'Coordinator',side_effect=AssertionError('no remote ledger dispatch')):
            self.assertEqual(self.collect(pinned=dict(mode='local'))['offers'],[])
        self.local.assert_not_called()

    def test_original_deadline_is_checked_at_consumption_even_when_quote_is_fresh(self):
        self.accepted()
        with patch.object(self.client, 'utc', return_value=NOW + timedelta(seconds=201)), \
                patch.object(self.client, 'Session', side_effect=AssertionError('original deadline')):
            self.assertEqual(self.client.arab_normal(self.local, self.parent)['offers'], [])


class SourceWiring(unittest.TestCase):
    def test_original_branch_needs_no_controller_install_but_configured_route_receives_parent(self):
        from fc_pricing_v3 import sources
        config = Mock()
        config.exists.return_value = False
        config.is_symlink.return_value = False
        local = Mock(return_value='legacy')
        parent = dict(run_id='original')
        with patch.object(sources, 'Path', return_value=config), \
                patch.object(sources.sys, 'path', list(sources.sys.path)), \
                patch('fc_pricing_v3.market_registry.arab_normal', local), \
                patch('fc_collection.client.arab_normal', return_value='routed') as remote:
            self.assertEqual(sources._read_arab(parent, dict(mode='server')), 'legacy')
            remote.assert_not_called()
            config.exists.return_value = True
            self.assertEqual(sources._read_arab(parent, dict(mode='server')), 'routed')
            remote.assert_called_once_with(local, parent, pinned=dict(mode='server'))
            remote.reset_mock()
            self.assertEqual(sources._read_arab(parent, dict(mode='local')), 'routed')
            remote.assert_called_once_with(local,parent,pinned=dict(mode='local'))

    def test_real_quote_evidence_preserves_snapshot_time_and_local_pin_through_source_subprocess(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        root = Path(__file__).resolve().parents[1] / 'source'
        tree = ast.parse((root / 'server_quote_job.py').read_text(encoding='utf-8'))
        assignment = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'evidence' for t in n.targets)
                          and isinstance(n.value, ast.Dict))
        now = datetime.now(timezone.utc).isoformat()
        deadline = (datetime.fromisoformat(now) + timedelta(seconds=30)).isoformat()
        snapshot = dict(created_at=now, collection_mode=dict(mode='local', revision=7), collection_deadline_at=deadline)
        environment = dict(snapshot=snapshot, run_id='real-run', costs=[], offers=[], fx={}, storefront={}, reference_market={})
        exec(compile(ast.Module(body=[assignment], type_ignores=[]), str(root / 'server_quote_job.py'), 'exec'), environment)
        evidence = environment['evidence']
        from fc_pricing_v3 import sources
        process = Mock(return_value=SimpleNamespace(returncode=0, stdout='{}'))
        with patch.object(sources.subprocess, 'run', process):
            sources.collect_context(evidence)
        data = json.loads(process.call_args.kwargs['input'])
        self.assertEqual(data['collection_mode'], snapshot['collection_mode'])
        self.assertEqual(data['collection_context']['created_at'], snapshot['created_at'])
        self.assertEqual(data['collection_context']['run_id'], 'real-run')
        self.assertEqual(data['collection_context']['deadline_at'], deadline)

    def test_source_subprocess_receives_only_minimal_parent_and_pinned_local_mode(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from fc_pricing_v3 import sources
        process = Mock(return_value=SimpleNamespace(returncode=0, stdout='{}'))
        created = datetime.now(timezone.utc)
        deadline = created + timedelta(seconds=30)
        evidence = dict(run_id='original-run', created_at=created.isoformat(), storefront={},
                        collection_mode=dict(mode='local', revision=7), collection_deadline_at=deadline.isoformat(),
                        credential='must-not-forward', writer='must-not-forward')
        with patch.object(sources.subprocess, 'run', process):
            sources.collect_context(evidence)
        payload = json.loads(process.call_args.kwargs['input'])
        self.assertEqual(payload['collection_mode'], evidence['collection_mode'])
        self.assertEqual(payload['collection_context'], dict(run_id='original-run', created_at=created.isoformat(), deadline_at=deadline.isoformat()))
        self.assertNotIn('credential', payload)
        self.assertNotIn('writer', payload)
        self.assertEqual(process.call_args.kwargs['timeout'], 240)

    def test_curve_arab_100k_uses_existing_source_runtime_and_same_parent(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from fc_pricing_v3 import sources

        created = datetime.now(timezone.utc)
        deadline = created + timedelta(seconds=30)
        quote = dict(status='available', offers=[dict(source='ArabUT', platform='PC', purchase_k='100')])
        snapshot = dict(run_id='original-run', created_at=created.isoformat(), collection_deadline_at=deadline.isoformat(),
                        collection_mode=dict(mode='server', revision=7))
        with patch.object(sources.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(quote))) as process:
            self.assertEqual(sources.collect_arab_100k(snapshot), quote)
        self.assertEqual(process.call_args.args[0], ['/opt/python39/bin/python3','-B','-m','fc_pricing_v3.sources'])
        self.assertEqual(json.loads(process.call_args.kwargs['input']), dict(
            action='arab_100k', collection_mode=snapshot['collection_mode'], collection_context=dict(
                run_id='original-run', created_at=created.isoformat(), deadline_at=deadline.isoformat())))

    def test_private_routing_requires_regular_root_owned_private_file(self):
        from types import SimpleNamespace
        from fc_collection.client import private_file
        path = Mock()
        path.is_symlink.return_value = False
        path.is_file.return_value = True
        import stat
        for change in (dict(st_uid=1000, st_mode=stat.S_IFREG | 0o600, st_nlink=1),
                       dict(st_uid=0, st_mode=stat.S_IFREG | 0o644, st_nlink=1),
                       dict(st_uid=0, st_mode=stat.S_IFREG | 0o600, st_nlink=2)):
            path.stat.return_value = SimpleNamespace(st_size=100, **change)
            with patch('fc_collection.client.os.name', 'posix'), self.assertRaises(ValueError):
                private_file(path)


if __name__ == '__main__':
    unittest.main()
