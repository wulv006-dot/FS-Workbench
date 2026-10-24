import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from campaign_backend import benefits
from campaign_backend.core import ContractError, canonical
from campaign_backend.ledger import OperationLedger, ObjectOperationBusy, now
from test_benefit_operations import Reader, policy


class DelayedNativeReader(Reader):
    def post(self, url, **kwargs):
        # The request may still apply upstream after this timeout; readback is temporarily unchanged.
        self.calls.append((url, kwargs))
        raise TimeoutError('native result not yet available')


class ObjectLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'operations.sqlite3'
        self.reader = DelayedNativeReader()
        self.request = dict(action='benefit_edit', site_id='266', kind='coupon', native_id='123',
            before_hash=benefits.row_hash(self.reader.row), changes={'title': 'Delayed native title'})

    def tearDown(self):
        self.temp.cleanup()

    def mutate(self, operation_id):
        return benefits.mutate(self.reader, OperationLedger(self.path), policy(),
                               dict(self.request, operation_id=operation_id))

    def test_unknown_different_id_same_object_blocked_across_connections_and_restart(self):
        first = self.mutate('object-operation-A')
        self.assertEqual(first['state'], 'unknown')
        self.assertEqual(self.reader.row['title'], 'Project coupon')
        for requested in ('object-operation-B', 'object-operation-C'):
            response = self.mutate(requested)
            self.assertTrue(response['object_busy'])
            self.assertEqual(response['requested_operation_id'], requested)
            self.assertEqual(response['operation_id'], 'object-operation-A')
            self.assertEqual(response['recovery_operation_id'], 'object-operation-A')
            self.assertIsNone(OperationLedger(self.path).lookup(requested))
        self.assertEqual(len(self.reader.calls), 1)

    def test_original_unknown_readback_does_not_release_until_trusted_terminal(self):
        self.mutate('object-operation-A')
        ledger = OperationLedger(self.path)
        self.assertEqual(benefits.operation(ledger, self.reader, '266', 'object-operation-A', True)['state'], 'unknown')
        self.assertTrue(self.mutate('object-operation-B')['object_busy'])
        self.assertEqual(len(self.reader.calls), 1)
        self.reader.row['title'] = self.request['changes']['title']
        self.assertEqual(benefits.operation(ledger, self.reader, '266', 'object-operation-A', True)['state'], 'confirmed')
        request = dict(self.request, operation_id='object-operation-B', before_hash=benefits.row_hash(self.reader.row),
                       changes={'brief': 'A new authorized change after original terminal'})
        self.assertEqual(benefits.mutate(self.reader, OperationLedger(self.path), policy(), request)['state'], 'unknown')
        self.assertEqual(len(self.reader.calls), 2)

    def test_pending_preflight_owns_object_before_native_dispatch(self):
        entered, resume = threading.Event(), threading.Event()
        original = self.reader.detail
        def delayed(*args):
            entered.set()
            if not resume.wait(5):
                raise AssertionError('fixture did not resume')
            return original(*args)
        self.reader.detail = delayed
        results = []
        thread = threading.Thread(target=lambda: results.append(self.mutate('object-operation-A')))
        thread.start()
        self.assertTrue(entered.wait(5))
        blocked = self.mutate('object-operation-B')
        self.assertEqual(blocked['state'], 'pending')
        self.assertEqual(blocked['recovery_operation_id'], 'object-operation-A')
        self.assertEqual(self.reader.calls, [])
        resume.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]['state'], 'unknown')
        self.assertEqual(len(self.reader.calls), 1)

    def test_simultaneous_different_ids_same_object_get_one_native_post(self):
        ledgers = [OperationLedger(self.path), OperationLedger(self.path)]
        start = threading.Barrier(2)
        def worker(index):
            start.wait(5)
            return benefits.mutate(self.reader, ledgers[index], policy(),
                dict(self.request, operation_id='parallel-operation-' + str(index)))
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(worker, range(2)))
        self.assertEqual(len(self.reader.calls), 1)
        blocked = [row for row in responses if row.get('object_busy')]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(len({row['operation_id'] for row in responses}), 1)

    def test_object_namespace_and_canonical_numeric_ids(self):
        ledger = OperationLedger(self.path)
        payload = dict(site_id='266', kind='coupon', native_id='123')
        ledger.prepare('first-object-operation', payload)
        with self.assertRaises(ObjectOperationBusy):
            OperationLedger(self.path).prepare('same-object-operation', dict(payload, site_id=266, native_id='00123'))
        ledger.prepare('other-object-operation', dict(payload, native_id='124'))
        ledger.prepare('other-site-operation', dict(payload, site_id='267'))
        ledger.prepare('other-kind-operation', dict(payload, kind='discount'))

    def test_unstarted_rejection_releases_and_original_fence_still_prevents_dispatch(self):
        ledger = OperationLedger(self.path)
        payload = dict(site_id='266', kind='coupon', native_id='123')
        ledger.prepare('fenced-operation-A', payload)
        ledger.reject_unstarted('fenced-operation-A', payload, 'PREFLIGHT_FENCED_BEFORE_DISPATCH')
        ledger.prepare('new-operation-B', payload)
        class NeverDispatch:
            enabled = True
            def dispatch_once(self, *args):
                raise AssertionError('fenced worker sent a request')
        self.assertEqual(ledger.execute('fenced-operation-A', payload, NeverDispatch())['state'], 'rejected')
        with self.assertRaises(ObjectOperationBusy):
            ledger.prepare('new-operation-C', payload)

    def test_upgrade_existing_unknown_rows_fail_closed_without_discarding_old_ids(self):
        ledger = OperationLedger(self.path)
        payload = dict(site_id='266', kind='coupon', native_id='123')
        # Simulate rows written before object association existed; both original IDs must survive.
        with ledger._connection() as db:
            for operation_id in ('legacy-operation-A', 'legacy-operation-B'):
                db.execute("INSERT INTO operations VALUES (?,?,?,'unknown',1,NULL,?,?)",
                    (operation_id, canonical(payload), 'a' * 64, now(), now()))
        with self.assertRaises(ObjectOperationBusy) as caught:
            OperationLedger(self.path).prepare('new-operation-C', payload)
        self.assertEqual(caught.exception.operation_ids, ['legacy-operation-A', 'legacy-operation-B'])
        self.assertEqual(ledger.lookup('legacy-operation-A')['state'], 'unknown')
        self.assertEqual(ledger.lookup('legacy-operation-B')['state'], 'unknown')


if __name__ == '__main__':
    unittest.main()
