import unittest
from datetime import datetime, timezone

from fc_collection.package_routes import collect_missing


class PackageRouting(unittest.TestCase):
    def test_registered_block_fences_all_three_nodes_before_network(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from fc_collection.coordinator import Coordinator
        from fc_collection.package_routes import read_node, record_restriction
        from fc_collection.pilot import source_policy
        with TemporaryDirectory() as tmp, patch('fc_collection.client.DATABASE',Path(tmp)/'db'):
            ledger = Coordinator(Path(tmp)/'db')
            for source in ('U4GM',):
                origin = 'https://www.'+source.lower()+'.com'
                ledger.configure_source(source,dict(source_policy(),mode='consume',origin=origin))
                req = dict(source=source,run_id='prior')
                record_restriction(req,dict(req,errors=['http_403']))
                with patch('fc_collection.package_routes.subprocess.run') as child, patch('fc_collection.client.collect_remote') as remote, patch('fc_collection.package_relay.request_local') as local:
                    now = datetime.now(timezone.utc)
                    rows, attempts = collect_missing(source,'next',[('PC','100')],lambda node,r:read_node(node,r,now),lambda:now)
                    self.assertEqual((attempts[0]['node'], attempts[0]['errors'], attempts[0]['response_received']),
                                     ('187', ['source_blocked'], False))
                    self.assertFalse(rows)
                    for entry in (child, remote):
                        entry.assert_not_called()
                    local.assert_called_once_with(dict(source='U4GM', run_id='next', wanted=[('PC','100')],
                                                      mode='cached_u4gm'))

    def test_primary_process_failure_releases_its_permit_for_the_next_node(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from fc_collection.client import legacy_ready
        from fc_collection.coordinator import Coordinator
        from fc_collection.package_routes import read_node
        from fc_collection.pilot import source_policy
        with TemporaryDirectory() as tmp, patch('fc_collection.client.DATABASE',Path(tmp)/'db'):
            ledger = Coordinator(Path(tmp)/'db')
            ledger.configure_source('U4GM',dict(source_policy(),mode='consume',origin='https://www.u4gm.com'))
            req = dict(source='U4GM',run_id='round',wanted=[('PS','100')])
            with patch('fc_collection.package_routes.subprocess.run',side_effect=FileNotFoundError), self.assertRaises(FileNotFoundError):
                read_node('187',req,datetime.now(timezone.utc))
            self.assertTrue(legacy_ready('U4GM',require_registered=True))

    def test_late_reader_crash_preserves_previous_node_quotes(self):
        now = datetime.now(timezone.utc)
        def read(node,request):
            if node != '187':
                raise RuntimeError('reader failed')
            offer = dict(source='U4GM',platform='PC',purchase_k='100',bonus_k='0',regular_price='6',
                         captured_at=now.isoformat(),run_id='round',status='valid',currency='USD',
                         comparable=True,conditional=False,coupon_excluded=True,delivery_method='comfort_trade',delivery_tier='standard')
            return dict(request,offers=[offer],errors=[])
        rows,attempts = collect_missing('U4GM','round',[('PC','100'),('PS','100')],read,lambda:now)
        self.assertEqual([r['platform'] for r in rows],['PC'])
        self.assertEqual(attempts[-1]['errors'],['RuntimeError'])

    def test_disabled_arab_source_does_not_fall_back_to_local(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import Mock, patch
        from fc_collection.client import arab_normal
        from fc_collection.coordinator import Coordinator
        from fc_collection.pilot import source_policy
        with TemporaryDirectory() as tmp, patch('fc_collection.client.DATABASE',Path(tmp)/'db'):
            ledger = Coordinator(Path(tmp)/'db')
            local = Mock(return_value={'status':'valid'})
            self.assertEqual(arab_normal(local,pinned={'mode':'local'}),{'status':'valid'})
            ledger.configure_source('ArabUT',dict(source_policy(),mode='off'))
            self.assertEqual(arab_normal(local,pinned={'mode':'local'})['status'],'unavailable')
            local.assert_called_once()

    def test_relay_waits_for_three_seven_second_platform_reads_after_accept(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import MagicMock, patch
        from fc_collection.package_relay import request_local
        with TemporaryDirectory() as tmp, patch('fc_collection.package_relay.socket.AF_UNIX',1,create=True), patch('fc_collection.package_relay.socket.socket') as listen:
            server = listen.return_value.__enter__.return_value
            conn = MagicMock()
            server.accept.return_value = (conn,None)
            req = dict(source='U4GM',run_id='00000000-0000-4000-8000-000000000001',wanted=[('PC','100')])
            with patch.object(Path,'chmod'), patch('fc_collection.package_relay.write_message'), patch('fc_collection.package_relay.read_message',return_value=req):
                self.assertEqual(request_local(req,root=Path(tmp)),req)
            self.assertGreater(conn.settimeout.call_args.args[0],3*7)

    def test_explicit_restriction_survives_malformed_partial_offers(self):
        for reason in ('http_403','http_429'):
            with self.subTest(reason=reason):
                calls = []
                def read(node, req):
                    calls.append(node)
                    malformed = dict(source='U4GM', run_id='round', platform=[], purchase_k='100')
                    return dict(req, offers=[malformed], errors=[reason])
                rows, attempts = collect_missing('U4GM','round',[('PC','100')],read,lambda:datetime.now(timezone.utc))
                self.assertEqual(calls,['187','local'])
                self.assertIn(reason,attempts[0]['errors'])
                self.assertFalse(rows)

    def test_local_timeout_before_any_connection_records_no_worker_response(self):
        import socket
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from fc_collection.package_relay import LocalWorkerUnavailable, request_local

        with TemporaryDirectory() as tmp, patch('fc_collection.package_relay.socket.AF_UNIX', 1, create=True), \
                patch('fc_collection.package_relay.socket.socket') as listen:
            server = listen.return_value.__enter__.return_value
            server.accept.side_effect = socket.timeout
            request = dict(source='U4GM', run_id='00000000-0000-4000-8000-000000000001', wanted=[('PC','100')])
            with patch.object(Path, 'chmod'), self.assertRaises(LocalWorkerUnavailable):
                request_local(request, root=Path(tmp))

    def test_u4gm_uses_local_for_missing_slots_and_stops_on_access_restrictions(self):
        now = datetime.now(timezone.utc)
        for error, nodes in [('template_changed',['187','183','local']),('http_403',['187','local'])]:
            with self.subTest(error=error):
                requests = []
                def read(node, request):
                    requests.append(node)
                    return dict(request, offers=[], errors=[error] if node == '187' else [])
                rows, _ = collect_missing('U4GM','round',[('PC','1000')],read,lambda:now)
                self.assertFalse(rows)
                self.assertEqual(requests,nodes)

    def test_direct_readers_share_the_origin_budget_with_each_other(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from fc_collection.coordinator import Coordinator
        from fc_collection.pilot import source_policy
        now = datetime.now(timezone.utc)
        with TemporaryDirectory() as tmp:
            ledger = Coordinator(Path(tmp) / 'collection.db')
            ledger.configure_source('U4GM', dict(source_policy(), mode='consume', origin='https://www.u4gm.com'))
            with ledger.package_requests('U4GM', 'primary', 1, now):
                with self.assertRaisesRegex(ValueError, 'request_budget_unavailable'):
                    with ledger.package_requests('U4GM', 'concurrent', 1, now):
                        self.fail('concurrency limit')
            with ledger.package_requests('U4GM', 'readback', 1, now):
                pass
            with self.assertRaisesRegex(ValueError, 'request_budget_unavailable'):
                with ledger.package_requests('U4GM', 'excess', 1, now):
                    self.fail('origin budget')

    def test_local_worker_uses_its_own_ssh_config_and_returns_on_idle(self):
        from io import BytesIO
        from unittest.mock import patch
        from fc_collection.package_relay import local_once
        with patch('fc_collection.package_relay.subprocess.Popen') as launch:
            process = launch.return_value.__enter__.return_value
            process.stdout = BytesIO(b'{"status":"idle"}\n')
            process.wait.return_value = 0
            local_once('worker-ssh-config')
        command = launch.call_args.args[0]
        self.assertEqual(command[:3], ['ssh', '-F', 'worker-ssh-config'])
        self.assertEqual(command[-1], 'fs-fc-iggm-readback')
        self.assertIn('StrictHostKeyChecking=yes', command)
        process.stdin.write.assert_not_called()

    def test_u4gm_keeps_primary_and_supplement_and_tries_local_for_remaining_slots(self):
        now = datetime.now(timezone.utc)
        calls = []
        def read(node, request):
            calls.append((node, list(request['wanted'])))
            platform, quantity = request['wanted'][-1]
            if node == '183':
                raise ValueError('template_changed')
            offer = dict(source='U4GM', platform=platform, purchase_k=quantity, bonus_k='0',
                         regular_price='7', currency='USD', status='valid', conditional=False,
                         coupon_excluded=True, comparable=True, promotion_eligibility='all_customers',
                         delivery_method='comfort_trade', delivery_tier='standard',
                         captured_at=now.isoformat(), run_id='round')
            return dict(source='U4GM', run_id='round', offers=[offer], errors=[])
        rows, attempts = collect_missing('U4GM', 'round', [('PS','100'),('PC','1000')], read, lambda:now)
        self.assertEqual([node for node, _ in calls], ['187','183','local'])
        self.assertEqual(calls[1][1], [('PC','1000')])
        self.assertEqual(calls[2][1], [('PC','1000')])
        self.assertEqual([row['collection_node'] for row in rows], ['187','local'])
        self.assertEqual(len(attempts), 3)

    def test_rate_limit_is_saved_in_the_shared_ledger_for_the_following_round(self):
        from unittest.mock import patch
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from fc_collection.client import legacy_ready
        from fc_collection.coordinator import Coordinator
        from fc_collection.package_routes import record_restriction
        from fc_collection.pilot import source_policy
        with TemporaryDirectory() as tmp, patch('fc_collection.client.DATABASE', Path(tmp) / 'db.sqlite'):
            ledger = Coordinator(Path(tmp) / 'db.sqlite')
            policy = dict(source_policy(1), origin='https://www.u4gm.com', mode='consume')
            ledger.configure_source('U4GM', policy)
            self.assertTrue(legacy_ready('U4GM', require_registered=True))
            request = dict(source='U4GM', run_id='round')
            record_restriction(request, dict(request, errors=['http_429'], retry_after_seconds=7200))
            self.assertFalse(legacy_ready('U4GM', require_registered=True))
            with ledger.transaction() as db:
                expiry = ledger._get(db, 'collection_sources', 'U4GM')['cooldown_until']
            self.assertGreater(expiry, datetime.now(timezone.utc).timestamp() + 7100)
