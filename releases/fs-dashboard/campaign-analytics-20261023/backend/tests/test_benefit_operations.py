import copy
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from bridge import handle
from campaign_backend import benefits
from campaign_backend.core import ContractError
from campaign_backend.ledger import OperationLedger
from campaign_backend.services import BackendServices


def native_row():
    return dict(id=123, site_id=266, game_id=1327, goods_id=170014917, title='Project coupon',
                brief='Description', status=0, code='SECRET_CODE', param_code='SECRET_PARAM')


def policy():
    return dict(coupon_objects={'123': dict(site_id='266', game_id='1327', goods_id='170014917',
        ownership_verified=True, exact_id_readback_verified=True, compensation_verified=True,
        status_zero_verified=True, disable_verified=True, partial_edit_verified=True)})


class Reader:
    def __init__(self, row=None, timeout=False):
        self.row = row or native_row()
        self.calls = []
        self.timeout = timeout
        self.session = SimpleNamespace(token='fixture-only', admin=SimpleNamespace(post=self.post))

    def detail(self, kind, native_id):
        return copy.deepcopy(self.row)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        self.row.update(kwargs['json'])
        if self.timeout:
            raise TimeoutError('SECRET_TRANSPORT_ERROR')
        return SimpleNamespace(status_code=200)

    def close(self):
        pass


class BenefitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = OperationLedger(Path(self.temp.name) / 'operations.sqlite3')
        self.reader = Reader()
        self.request = dict(action='benefit_edit', kind='coupon', site_id='266', native_id='123',
            operation_id='fixture-operation-1', before_hash=benefits.row_hash(self.reader.row),
            changes={'title': 'Updated project title'})

    def tearDown(self):
        self.temp.cleanup()

    def test_detail_whitelist_and_default_server_gate(self):
        view = benefits.detail(self.reader, {}, 'coupon', '123', '266')
        self.assertEqual(view['editability']['allowed_changes'], [])
        self.assertFalse(view['editability']['can_disable'])
        self.assertFalse(view['editability']['can_enable'])
        self.assertNotIn('SECRET', str(view))
        result = benefits.mutate(self.reader, self.ledger, {}, self.request)
        self.assertEqual((result['state'], result['dispatch_state']), ('rejected', 'not_started'))
        self.assertEqual(self.reader.calls, [])
        self.assertEqual(self.ledger.lookup(self.request['operation_id']), result)

    def test_exact_edit_once_and_duplicate_result_survives_restart(self):
        first = benefits.mutate(self.reader, self.ledger, policy(), self.request)
        second = benefits.mutate(self.reader, OperationLedger(self.ledger.path), policy(), self.request)
        self.assertEqual(first, second)
        self.assertEqual(first['state'], 'confirmed')
        self.assertEqual(len(self.reader.calls), 1)
        self.assertEqual(self.reader.calls[0][1]['json'], {'id': 123, 'title': 'Updated project title'})
        self.assertFalse(self.reader.calls[0][1]['allow_redirects'])

    def test_timeout_never_retries_and_original_reconcile_confirms(self):
        self.reader.timeout = True
        result = benefits.mutate(self.reader, self.ledger, policy(), self.request)
        self.assertEqual(result['state'], 'unknown')
        self.assertNotIn('SECRET_TRANSPORT', str(result))
        self.assertEqual(benefits.operation(self.ledger, self.reader, '266', self.request['operation_id'], True)['state'], 'confirmed')
        self.assertEqual(len(self.reader.calls), 1)

    def test_bad_before_hash_and_bad_fields_are_durable_unstarted_rejections(self):
        for number, changes in enumerate(({'before_hash': 'wrong'}, {'changes': {'status': 1}})):
            request = dict(self.request, operation_id='fixture-operation-' + str(number + 10), **changes)
            result = benefits.mutate(self.reader, self.ledger, policy(), request)
            self.assertEqual((result['operation_id'], result['state'], result['dispatch_state']),
                             (request['operation_id'], 'rejected', 'not_started'))
        self.assertEqual(self.reader.calls, [])

    def test_conflicting_request_cannot_certify_original_unknown_was_not_sent(self):
        self.reader.timeout = True
        benefits.mutate(self.reader, self.ledger, policy(), self.request)
        result = benefits.mutate(self.reader, self.ledger, policy(), dict(self.request, changes={'title': 'different'}))
        self.assertEqual(result['state'], 'unknown')
        self.assertNotEqual(result['dispatch_state'], 'not_started')
        self.assertEqual(len(self.reader.calls), 1)

    def test_enable_requires_separate_verified_activation_authorization(self):
        request = dict(self.request, action='benefit_toggle', enabled=True)
        request.pop('changes')
        result = benefits.mutate(self.reader, self.ledger, policy(), request)
        self.assertEqual(result['state'], 'rejected')
        self.assertEqual(self.reader.calls, [])

    def test_explicit_disable_of_verified_exact_native_id(self):
        self.reader.row['status'] = 1
        request = dict(self.request, action='benefit_toggle', enabled=False,
                       before_hash=benefits.row_hash(self.reader.row))
        request.pop('changes')
        self.assertEqual(benefits.mutate(self.reader, self.ledger, policy(), request)['state'], 'confirmed')
        self.assertEqual(self.reader.calls[0][1]['json'], {'id': 123, 'status': 0})

    def test_pending_reconcile_fences_original_preflight_worker_before_it_can_send(self):
        entered, resume = threading.Event(), threading.Event()
        original = self.reader.detail
        def slow_detail(*args):
            entered.set()
            if not resume.wait(5):
                raise AssertionError('preflight fixture did not resume')
            return original(*args)
        self.reader.detail = slow_detail
        results = []
        thread = threading.Thread(target=lambda: results.append(benefits.mutate(self.reader, self.ledger, policy(), self.request)))
        thread.start()
        self.assertTrue(entered.wait(5))
        result = benefits.operation(self.ledger, None, '266', self.request['operation_id'], True)
        self.assertEqual((result['state'], result['dispatch_state']), ('rejected', 'not_started'))
        resume.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]['state'], 'rejected')
        self.assertEqual(self.reader.calls, [])

    def test_browser_cannot_supply_policy_or_data_path_and_foreign_scope_is_rejected(self):
        service = BackendServices(Path(self.temp.name), policy())
        with self.assertRaisesRegex(ContractError, 'REQUEST_FIELDS_NOT_ALLOWED'):
            handle(dict(self.request, path='/tmp/elsewhere'), services=service)
        with self.assertRaisesRegex(ContractError, 'PROJECT_SITE_REQUIRED'):
            handle(dict(action='analysis_summary', site_id='999'), services=service)


if __name__ == '__main__':
    unittest.main()
