import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from campaign_backend import ContractError, OperationLedger, MutationAdapter


class Adapter:
    enabled = True

    def __init__(self, reply=None, failure=None):
        self.calls = 0
        self.reply = reply or {'state': 'confirmed', 'upstream_ref': 'batch-1'}
        self.failure = failure

    def dispatch_once(self, operation_id, payload):
        self.calls += 1
        if self.failure:
            raise self.failure
        return self.reply

    def readback(self, operation_id, payload):
        return self.reply


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'operations.sqlite3'
        self.ledger = OperationLedger(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_same_id_payload_one_dispatch_and_canonical_keys(self):
        adapter = Adapter()
        first = self.ledger.execute('op-1', {'b': 2, 'a': 1}, adapter)
        second = self.ledger.execute('op-1', {'a': 1, 'b': 2}, adapter)
        self.assertEqual(first, second)
        self.assertEqual(adapter.calls, 1)
        with self.assertRaisesRegex(ContractError, 'REQUEST_CONFLICT'):
            self.ledger.execute('op-1', {'a': 9}, adapter)
        self.assertEqual(adapter.calls, 1)

    def test_timeout_survives_restart_and_never_blind_retries(self):
        adapter = Adapter(failure=TimeoutError('private upstream detail'))
        self.assertEqual(self.ledger.execute('original', {'count': 1}, adapter)['state'], 'unknown')
        restarted = OperationLedger(self.path)
        self.assertEqual(restarted.execute('original', {'count': 1}, adapter)['state'], 'unknown')
        self.assertEqual(adapter.calls, 1)
        self.assertNotIn('private', str(restarted.lookup('original')))
        adapter.failure = None
        self.assertEqual(restarted.reconcile('original', adapter)['state'], 'confirmed')
        self.assertEqual(adapter.calls, 1)

    def test_crash_after_dispatch_claim_is_not_pending(self):
        adapter = Adapter(failure=SystemExit())
        with self.assertRaises(SystemExit):
            self.ledger.execute('crash', {}, adapter)
        self.assertEqual(OperationLedger(self.path).lookup('crash')['state'], 'unknown')

    def test_concurrent_workers_claim_once(self):
        adapter = Adapter()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: OperationLedger(self.path).execute('same', {}, adapter), range(16)))
        self.assertEqual(adapter.calls, 1)
        self.assertTrue(all(r['state'] in ('unknown', 'confirmed') for r in results))

    def test_disabled_adapter_does_not_prepare_or_dispatch(self):
        with self.assertRaisesRegex(ContractError, 'MAIN_INTEGRATION_REQUIRED'):
            self.ledger.execute('disabled', {}, MutationAdapter())
        self.assertIsNone(self.ledger.lookup('disabled'))

    def test_rejected_and_malformed_results(self):
        rejected = Adapter({'state': 'rejected', 'reason_code': 'SCOPE_REJECTED'})
        self.assertEqual(self.ledger.execute('reject', {}, rejected)['state'], 'rejected')
        self.ledger.execute('reject', {}, rejected)
        self.assertEqual(rejected.calls, 1)
        malformed = Adapter({'state': 'confirmed', 'token': 'must-not-store'})
        result = self.ledger.execute('malformed', {}, malformed)
        self.assertEqual(result['state'], 'unknown')
        self.assertIsNone(result['result'])

    def test_unknown_readback_does_not_authorize_redispatch(self):
        adapter = Adapter({'state': 'unknown', 'reason_code': 'NOT_FOUND_IS_NOT_PROOF'})
        self.ledger.execute('lookup', {}, adapter)
        self.ledger.reconcile('lookup', adapter)
        self.ledger.execute('lookup', {}, adapter)
        self.assertEqual(adapter.calls, 1)

    def test_prepared_operation_can_dispatch_after_restart(self):
        self.assertEqual(self.ledger.prepare('prepared', {})['state'], 'pending')
        self.assertEqual(OperationLedger(self.path).execute('prepared', {}, Adapter())['state'], 'confirmed')

    def test_more_than_100_operations_are_retained(self):
        for number in range(110):
            self.ledger.prepare(str(number), {'n': number})
        self.assertEqual(self.ledger.lookup('0')['state'], 'pending')


if __name__ == '__main__':
    unittest.main()
