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
    return dict(id=123, create_time=10, update_time=20, type=1, title='Project coupon',
        fetch_scene=4, status=0, mode_type=2, attain='1.25', reduce='85.00', max_reduce='23.40',
        limit_qty=0, fetch_qty=0, used_qty=0, repeat_qty=1, time_effect=1, start_time='', end_time=0,
        days=0, site_id=266, game_id=1327, product_type=0, goods_id=170014917,
        remark='Synthetic fixture', brief='Description', is_open=0, jump_url='', param_code='SECRET_PARAM')


def policy():
    return dict(coupon_objects={'123': dict(site_id='266', game_id='1327', goods_id='170014917',
        ownership_verified=True, exact_id_readback_verified=True, compensation_verified=True,
        status_zero_verified=True, disable_verified=True, partial_edit_verified=True,
        full_preserve_edit_verified=True, full_preserve_toggle_verified=True, fs_bridge_acceptance_verified=True)})


class Reader:
    def __init__(self, row=None, timeout=False):
        self.row = row or native_row()
        self.calls = []
        self.timeout = timeout
        self.session = SimpleNamespace(token='fixture-only', admin=SimpleNamespace(post=self.post, get_adapter=lambda url: SimpleNamespace(max_retries=SimpleNamespace(total=0))))

    def detail(self, kind, native_id):
        return copy.deepcopy(self.row)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        self.row.update(kwargs['json'])
        if self.timeout:
            raise TimeoutError('SECRET_TRANSPORT_ERROR')
        return SimpleNamespace(status_code=200, content=b'{"code":1,"msg":"ok"}')

    def close(self):
        pass


class BenefitTests(unittest.TestCase):
    def test_discount_detail_projects_real_code_and_uid_without_enabling_discount_writer(self):
        row=dict(id=6049,site_id=266,code='FCSCOUT10',uid=0,status=1,type=1,attain='0.00',discount='90.00',gid=['1327'],cid=['2'],exclude_gids=[],aid=0,repeat_qty=0,timestart='2026-10-26 00:00:00',timeend='2027-10-25 23:59:59',secret='NEVER_PROJECT')
        reader=Reader(row);view=benefits.detail(reader,{},'discount','6049','266')
        self.assertEqual(view['fields']['code'],'FCSCOUT10');self.assertEqual(view['fields']['uid'],0)
        self.assertEqual(view['fields']['cid'],['2']);self.assertNotIn('NEVER_PROJECT',str(view));self.assertEqual(reader.calls,[])
        self.assertNotIn('code',benefits.DISCOUNT_FIELDS);self.assertNotIn('uid',benefits.DISCOUNT_FIELDS)
    def test_coupon_candidates_calls_one_real_upstream_page_without_codes(self):
        from campaign_backend.adapters import AdminRead
        calls=[]
        class Session:
            def get_admin(self,route,**params):
                calls.append((route,params))
                return 200,{'code':1,'data':{'list':[dict(native_row(),code='PRIVATE_CODE')],'total':2}}
            def close(self):pass
        reader=AdminRead(Session())
        result=BackendServices(self.temp.name,policy()).handle(
            dict(action='coupon_candidates',site_id='266',page=1,limit=1),lambda:reader)
        self.assertEqual(len(calls),1)
        route,params=calls[0]
        self.assertEqual(route,'/admin/market.Coupon/index')
        self.assertEqual((params['page'],params['limit'],params['order']),(1,1,'id,desc'))
        self.assertEqual((params['search[0][field]'],params['search[0][operator]'],params['search[0][val]']),('site_id','=','266'))
        self.assertEqual((result['coverage'],result['complete'],result['has_more'],result['next_page']),('single_page',False,True,2))
        self.assertEqual(result['items'],[dict(native_id='123',site_id='266',game_id='1327',goods_id='170014917',status=0,fetch_qty=0,used_qty=0)])
        self.assertNotIn('PRIVATE',str(result));self.assertNotIn('brief',str(result))

    def test_coupon_page_failure_scope_and_unknown_counters_do_not_become_empty(self):
        from campaign_backend.adapters import AdminRead
        for code,row,total in ((0,native_row(),1),(1,dict(native_row(),site_id=0),1),(1,dict(native_row(),fetch_qty=None),1),(1,native_row(),None)):
            class Session:
                def get_admin(self,route,**params):return 200,dict(code=code,data=dict(list=[row],total=total))
                def close(self):pass
            with self.subTest(code=code,site=row['site_id'],total=total),self.assertRaises(ContractError):
                AdminRead(Session()).coupons_page('266',page=1,limit=1)
        with self.assertRaises(ContractError):AdminRead(None).coupons_page('0')
        with self.assertRaises(ContractError):AdminRead(None).coupons_page('266',page=True)
        with self.assertRaises(ContractError):AdminRead(None).coupons_page('266',limit=201)

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
        self.assertEqual(self.reader.calls[0][1]['json'], dict(native_row(), title='Updated project title'))
        self.assertFalse(self.reader.calls[0][1]['allow_redirects'])

    def test_timeout_never_retries_and_original_reconcile_stays_unknown(self):
        self.reader.timeout = True
        result = benefits.mutate(self.reader, self.ledger, policy(), self.request)
        self.assertEqual(result['state'], 'unknown')
        self.assertNotIn('SECRET_TRANSPORT', str(result))
        self.assertEqual(benefits.operation(self.ledger, self.reader, '266', self.request['operation_id'], True)['state'], 'unknown')
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
        self.assertEqual(self.reader.calls[0][1]['json'], dict(native_row(), status=0))

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
