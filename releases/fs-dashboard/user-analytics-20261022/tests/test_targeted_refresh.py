"""Small invented inputs for bounded ID refresh; never production orders."""
import json
import ast
from datetime import timedelta
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
import test_users as fixtures
from test_users import order,NOW
from user_jobs import targeted_candidates,targeted_refresh
from user_source import shared_correct,targeted_windows


# Exercise the real shared search/paging functions without importing other modules.
_shared_path=Path(__file__).resolve().parents[4]/'releases/fs-dashboard/channel-effects-20261021/source/channel_source.py'
_shared_tree=ast.parse(_shared_path.read_text(encoding='utf-8-sig'))
_shared={}
exec(compile(ast.Module(body=[n for n in _shared_tree.body if isinstance(n,ast.FunctionDef) and n.name in ('search','pages')],type_ignores=[]),str(_shared_path),'exec'),_shared)
def channel(reader=None):return SimpleNamespace(pages=reader or _shared['pages'],search=_shared['search'])


class TargetedRefresh(unittest.TestCase):
    setUp,load=fixtures.Users.setUp,fixtures.Users.load

    def rows(self,number=3):
        return [order(i,'2026-10-01') for i in range(1,number+1)]

    def test_bounded_groups_wrap_and_exclude_recent_completed_refunded(self):
        rows=self.rows(250)
        rows += [dict(order(i,'2026-10-01'),status='91') for i in range(251,501)]
        rows += [dict(order(501,'2026-10-01'),status='101'),order(502,'2026-10-21'),order(503,'2026-10-22T01:00:00+08:00'),order(504,'2026-10-01',status=2)]
        self.load(rows,end='2026-10-23')
        first,cursors=targeted_candidates(self.store,'266',NOW,{})
        self.assertEqual(len(first),400)
        self.assertEqual(cursors,{'fast':200,'watch':450})
        second,after=targeted_candidates(self.store,'266',NOW,cursors)
        self.assertEqual(len(second),400)
        self.assertTrue(set(map(str,range(201,251)))<=set(second))
        self.assertTrue(set(map(str,range(451,501)))<=set(second))
        self.assertFalse(set(first)&{'501','502','503','504'})
        self.assertEqual(after,{'fast':150,'watch':400})

    def test_partial_advances_cursor_without_deleting_missing_or_claiming_window(self):
        rows=self.rows();self.load(rows)
        coverage=self.store.coverage()
        def reader(store,site,requested):
            return store.correct_orders(site,requested,[dict(rows[0],status='101')],NOW.isoformat())
        result=targeted_refresh(self.store,'266',NOW,reader,self.store.root/'fixture.lock')
        self.assertEqual((result['status'],result['returned_rows'],result['missing_rows']),('partial',1,2))
        self.assertEqual(self.store.coverage(),coverage)
        stored={row['order_key']:row for row in self.store.read()[1]}
        self.assertEqual(len(stored),3)
        self.assertTrue(all(row['valid'] for row in stored.values()))
        state=json.loads((self.store.root/'targeted-refresh.json').read_text())
        self.assertEqual(state['cursors']['266']['fast'],3)

    def test_group_migration_is_picked_up_after_cursor_wrap_without_duplicate(self):
        rows=[order(1,'2026-10-01'),dict(order(2,'2026-10-01'),status='91'),
              order(3,'2026-10-01'),dict(order(4,'2026-10-01'),status='91')]
        self.load(rows)
        with patch('user_jobs.TARGETED_GROUP_LIMIT',1):
            first,cursors=targeted_candidates(self.store,'266',NOW,{})
            self.assertEqual(set(first),{'1','2'})
            self.store.correct_orders('266',first,[dict(rows[0],status='91'),dict(rows[1],status='11')],NOW.isoformat())
            second,cursors=targeted_candidates(self.store,'266',NOW,cursors)
            third,cursors=targeted_candidates(self.store,'266',NOW,cursors)
        self.assertEqual(set(second),{'2','4'})
        self.assertEqual(set(third),{'1','3'})
        self.assertEqual(len(second),2);self.assertEqual(len(third),2)

    def test_failed_receipt_keeps_progress_and_health_exposes_failure(self):
        self.load(self.rows())
        reader=Mock(side_effect=ValueError('unmapped_order_status'))
        result=targeted_refresh(self.store,'266',NOW,reader,self.store.root/'fixture.lock')
        self.assertEqual(result['status'],'failed')
        state=json.loads((self.store.root/'targeted-refresh.json').read_text())
        self.assertNotIn('266',state['cursors'])
        self.assertEqual(self.store.job_health()['targeted_reconciliation']['status'],'failed')

    def test_untrusted_receipt_never_advances(self):
        self.load(self.rows())
        result=targeted_refresh(self.store,'266',NOW,lambda *a:dict(mode='targeted',state='complete',requested_rows=3,returned_rows=1,missing_rows=0,changed_rows=0),self.store.root/'fixture.lock')
        self.assertEqual(result['status'],'failed')
        self.assertNotIn('266',json.loads((self.store.root/'targeted-refresh.json').read_text())['cursors'])

    def test_bad_metadata_is_preserved_without_scanning_or_fetching(self):
        self.load(self.rows());path=self.store.root/'targeted-refresh.json'
        for value in ([],dict(contract='fs-users-targeted-refresh-v1',cursors={'266':{'fast':True}},latest_attempts={}),
                      dict(contract='fs-users-targeted-refresh-v1',cursors={},latest_attempts={'266':[]})):
            raw=json.dumps(value);path.write_text(raw);path.chmod(0o600)
            with self.subTest(value=type(value).__name__),patch('user_jobs.targeted_candidates') as scan:
                source=Mock();result=targeted_refresh(self.store,'266',NOW,source,self.store.root/'fixture.lock')
                self.assertEqual(result['status'],'failed');scan.assert_not_called();source.assert_not_called()
                self.assertEqual(path.read_text(),raw)
                self.assertEqual(self.store.job_health()['targeted_reconciliation']['status'],'failed')

    def test_bad_projection_stops_before_source_and_is_not_rescanned(self):
        self.load(self.rows())
        with self.store.db() as db:db.execute("UPDATE orders SET body='[]' WHERE order_key='admin:266:test-1'")
        source=Mock();path=self.store.root/'fixture.lock'
        self.assertEqual(targeted_refresh(self.store,'266',NOW,source,path)['status'],'failed')
        with patch('user_jobs.targeted_candidates') as scan:
            result=targeted_refresh(self.store,'266',NOW,source,path)
        self.assertTrue(result['automatic_retry_blocked']);scan.assert_not_called();source.assert_not_called()

    def test_contract_failure_stops_automatic_retry_until_explicit_recheck(self):
        self.load(self.rows())
        failed=Mock(side_effect=ValueError('targeted_permission_denied'))
        path=self.store.root/'fixture.lock'
        targeted_refresh(self.store,'266',NOW,failed,path)
        blocked=targeted_refresh(self.store,'266',NOW,failed,path)
        self.assertTrue(blocked['automatic_retry_blocked']);self.assertEqual(failed.call_count,1)
        def repaired(store,site,requested):return store.correct_orders(site,requested,self.rows(),NOW.isoformat())
        self.assertEqual(targeted_refresh(self.store,'266',NOW,repaired,path,force=True)['status'],'complete')

    def test_temporary_source_error_allows_next_natural_retry(self):
        self.load(self.rows());path=self.store.root/'fixture.lock'
        reader=Mock(side_effect=RuntimeError('targeted_source_temporary'))
        targeted_refresh(self.store,'266',NOW,reader,path)
        targeted_refresh(self.store,'266',NOW,reader,path)
        self.assertEqual(reader.call_count,2)

    @unittest.skipUnless(os.name=='posix','real flock required')
    def test_source_busy_does_not_fetch_or_advance(self):
        import fcntl
        self.load(self.rows());reader=Mock();path=self.store.root/'fixture.lock'
        with path.open('a+b') as held:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=targeted_refresh(self.store,'266',NOW,reader,path)
        self.assertEqual(result['status'],'deferred');reader.assert_not_called()
        self.assertNotIn('266',json.loads((self.store.root/'targeted-refresh.json').read_text())['cursors'])

    def test_source_uses_id_filter_without_filtering_out_final_status(self):
        self.load(self.rows(2))
        requested={'1':'admin:266:test-1','2':'admin:266:test-2'}
        rows=[dict(order(2,'2026-10-01',status=2),status='81'),dict(order(1,'2026-10-01'),status='101')]
        session=Mock();pages=Mock(return_value=rows)
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture','ok'))
        expected={'mode':'targeted','state':'complete'}
        self.store.correct_orders=Mock(return_value=expected)
        with patch.dict(sys.modules,{'p2pah_auth':auth,'channel_source':channel(pages)}):
            self.assertEqual(shared_correct(self.store,'266',requested),expected)
        filters=pages.call_args.args[2]
        self.assertEqual(filters,[('site_id','=','266'),('id','IN','1,2'),('paytime','RANGE','2026-10-01 00:00:00,2026-10-28 23:59:59')])
        self.assertEqual(pages.call_args.args[3],1000)
        self.store.correct_orders.assert_called_once()
        session.close.assert_called_once()

    def test_source_wrong_id_and_duplicate_or_sort_never_apply(self):
        self.load(self.rows(2))
        session=Mock();auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture','ok'))
        self.store.correct_orders=Mock()
        requested={'1':'admin:266:test-1','2':'admin:266:test-2'}
        for rows in ([order(3,'2026-10-01')],[order(1,'2026-10-01'),order(1,'2026-10-01')],[order(1,'2026-10-01'),order(2,'2026-10-01')]):
            with self.subTest(rows=len(rows)),patch.dict(sys.modules,{'p2pah_auth':auth,'channel_source':channel(Mock(return_value=rows))}):
                with self.assertRaises(ValueError):shared_correct(self.store,'266',requested)
        self.store.correct_orders.assert_not_called()

    def test_source_permission_and_transient_status_are_distinct(self):
        self.load(self.rows(1))
        requested={'1':'admin:266:test-1'};session=Mock()
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture','ok'))
        def read(adapter,path,filters,limit):return adapter.get_admin(path)[1]
        for response,error in (((403,{'code':403}),ValueError),((200,{'code':401}),ValueError),((502,None),RuntimeError),((429,None),RuntimeError),((True,{}),ValueError),((200,{'code':True}),ValueError)):
            session.get_admin.return_value=response
            with self.subTest(response=response[0]),patch.dict(sys.modules,{'p2pah_auth':auth,'channel_source':channel(read)}):
                with self.assertRaises(error):shared_correct(self.store,'266',requested)

    def test_actual_adapter_contract_reconciles_completed_and_refunded_in_temp_store(self):
        rows=self.rows(2);self.load(rows)
        requested={'1':'admin:266:test-1','2':'admin:266:test-2'}
        response=[dict(rows[1],status='81',pay_status=2),dict(rows[0],status='101')]
        session=Mock();session.get_admin.return_value=(200,dict(code=1,data=dict(total=2,list=response)))
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture','ok'))
        def paging(adapter,path,filters,limit):return adapter.get_admin(path,page=1,limit=limit)[1]['data']['list']
        with patch.dict(sys.modules,{'p2pah_auth':auth,'channel_source':channel(paging)}):
            result=shared_correct(self.store,'266',requested)
        self.assertEqual((result['state'],result['changed_rows']),('complete',2))
        self.assertEqual([r['valid'] for r in self.store.read()[1]],[1,0])
        session.get_admin.assert_called_once()

    def test_ignored_id_filter_or_incomplete_first_page_cannot_expand_budget(self):
        self.load(self.rows(1))
        requested={'1':'admin:266:test-1'};session=Mock()
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture','ok'))
        def paging(adapter,path,filters,limit):
            adapter.get_admin(path,page=1,limit=limit)
            self.fail('invalid first response must be rejected before pagination')
        for data in (dict(total=2,list=[order(1,'2026-10-01')]),dict(total=1,list=[]),dict(total='1',list=[order(1,'2026-10-01')])):
            session.get_admin.return_value=(200,dict(code=1,data=data))
            with self.subTest(data=data['total']),patch.dict(sys.modules,{'p2pah_auth':auth,'channel_source':channel(paging)}):
                with self.assertRaises(ValueError):shared_correct(self.store,'266',requested)

    def test_old_dates_use_real_datetime_search_and_apply_all_groups_once(self):
        rows=[order(1,'2026-01-01'),order(2,'2026-01-28'),order(3,'2026-01-29'),order(4,'2026-06-01')]
        self.load(rows);requested={str(r['id']):'admin:266:'+r['order_no'] for r in rows}
        response={str(r['id']):dict(r,status='101' if r['id']!=2 else '81',pay_status=2 if r['id']==2 else 1) for r in rows}
        session=Mock();seen=[]
        def get(path,**params):
            self.assertEqual(path,'/admin/order.Order/index');self.assertEqual(params['page'],1)
            self.assertEqual(params['limit'],1000);self.assertEqual(params['order'],'id,desc')
            self.assertEqual([params[f'search[{i}][field]'] for i in range(3)],['site_id','id','paytime'])
            self.assertEqual(params['search[2][render]'],'datetime')
            ids=params['search[1][val]'].split(',');seen.append((ids,params['search[2][val]']))
            values=[response[i] for i in sorted(ids,key=int,reverse=True)]
            return 200,dict(code=1,data=dict(total=len(values),list=values))
        session.get_admin.side_effect=get
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture','ok'))
        with patch.dict(sys.modules,{'p2pah_auth':auth,'channel_source':channel()}),patch.object(self.store,'correct_orders',wraps=self.store.correct_orders) as apply:
            result=shared_correct(self.store,'266',requested)
        self.assertEqual((result['state'],result['requested_rows'],result['changed_rows']),('complete',4,4))
        self.assertEqual(seen,[(['1','2'],'2026-01-01 00:00:00,2026-01-28 23:59:59'),(['3'],'2026-01-29 00:00:00,2026-02-25 23:59:59'),(['4'],'2026-06-01 00:00:00,2026-06-28 23:59:59')])
        apply.assert_called_once();self.assertEqual([r['id'] for r in apply.call_args.args[2]],[4,3,2,1])
        self.assertEqual(sum(r['valid'] for r in self.store.read()[1]),3);session.close.assert_called_once()

    def test_later_group_failure_never_partially_updates_or_advances(self):
        rows=[order(1,'2026-01-01'),order(2,'2026-03-01')];self.load(rows)
        before=self.store.read();session=Mock()
        session.get_admin.side_effect=[(200,dict(code=1,data=dict(total=1,list=[dict(rows[0],status='101')]))),(403,dict(code=403))]
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture','ok'))
        with patch.dict(sys.modules,{'p2pah_auth':auth,'channel_source':channel()}),patch.object(self.store,'correct_orders',wraps=self.store.correct_orders) as apply:
            result=targeted_refresh(self.store,'266',NOW,shared_correct,self.store.root/'fixture.lock')
        self.assertEqual(result['status'],'failed');self.assertFalse(result['retryable']);apply.assert_not_called()
        self.assertEqual(self.store.read(),before)
        self.assertNotIn('266',json.loads((self.store.root/'targeted-refresh.json').read_text())['cursors'])

    def test_old_group_missing_preserves_record_and_does_not_claim_whole_day(self):
        rows=[order(1,'2026-01-01'),order(2,'2026-03-01')];self.load(rows)
        requested={str(r['id']):'admin:266:'+r['order_no'] for r in rows};coverage=self.store.coverage()
        session=Mock();session.get_admin.side_effect=[(200,dict(code=1,data=dict(total=0,list=[]))),(200,dict(code=1,data=dict(total=1,list=[dict(rows[1],status='101')]))) ]
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture','ok'))
        with patch.dict(sys.modules,{'p2pah_auth':auth,'channel_source':channel()}):result=shared_correct(self.store,'266',requested)
        self.assertEqual((result['state'],result['returned_rows'],result['missing_rows']),('partial',1,1))
        self.assertEqual(len(self.store.read()[1]),2);self.assertEqual(self.store.coverage(),coverage)

    def test_each_group_has_its_own_budget_and_id_subset(self):
        rows=[order(1,'2026-01-01'),order(2,'2026-03-01')];self.load(rows)
        requested={str(r['id']):'admin:266:'+r['order_no'] for r in rows}
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture','ok'))
        for data in (dict(total=2,list=rows),dict(total=1,list=[rows[1]])):
            session=Mock();session.get_admin.return_value=200,dict(code=1,data=data)
            with self.subTest(total=data['total']),patch.dict(sys.modules,{'p2pah_auth':auth,'channel_source':channel()}),patch.object(self.store,'correct_orders') as apply:
                with self.assertRaises(ValueError):shared_correct(self.store,'266',requested)
                apply.assert_not_called()

    def test_budget_expiry_discards_prior_group_and_keeps_cursor(self):
        rows=[order(1,'2026-01-01'),order(2,'2026-03-01')];self.load(rows);before=self.store.read()
        session=Mock();session.get_admin.return_value=200,dict(code=1,data=dict(total=1,list=[dict(rows[0],status='101')]))
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture','ok'))
        with patch.dict(sys.modules,{'p2pah_auth':auth,'channel_source':channel()}),patch('user_source.monotonic',side_effect=[0,0,1,181]),patch.object(self.store,'correct_orders') as apply:
            result=targeted_refresh(self.store,'266',NOW,shared_correct,self.store.root/'fixture.lock')
        self.assertEqual(result['status'],'failed');self.assertTrue(result['retryable']);apply.assert_not_called()
        self.assertEqual(self.store.read(),before);self.assertEqual(session.get_admin.call_count,1)
        self.assertNotIn('266',json.loads((self.store.root/'targeted-refresh.json').read_text())['cursors'])

    def test_date_group_limit_stops_before_fetch_and_selected_identity_is_bound(self):
        rows=[order(1,'2026-01-01'),order(2,'2026-03-01')];self.load(rows)
        requested={str(r['id']):'admin:266:'+r['order_no'] for r in rows};auth=Mock()
        with patch.dict(sys.modules,{'p2pah_auth':auth,'channel_source':channel()}),patch('user_source.TARGETED_MAX_WINDOWS',1):
            with self.assertRaisesRegex(RuntimeError,'targeted_read_budget_exhausted'):shared_correct(self.store,'266',requested)
        auth.Session.assert_not_called()
        with self.assertRaisesRegex(ValueError,'targeted_projection_identity'):targeted_windows(self.store,'266',{'3':'admin:266:test-1'})

    def test_payment_dates_are_grouped_as_beijing_days(self):
        self.load([order(1,'2026-01-01T18:30:00+00:00')])
        begin,end,group=targeted_windows(self.store,'266',{'1':'admin:266:test-1'})[0]
        self.assertEqual(begin.isoformat(),'2026-01-02T00:00:00+08:00')
        self.assertEqual(end-begin,timedelta(days=28));self.assertEqual(set(group),{'1'})

    def test_full_encoded_request_budget_is_checked_before_any_source_call(self):
        rows=[order(8_000_000_000_000_000_000+i,'2026-10-01') for i in range(272)]
        self.load(rows);requested={str(r['id']):'admin:266:'+r['order_no'] for r in rows}
        self.assertLessEqual(sum(len(i)+3 for i in requested),6000)
        auth=Mock()
        with patch.dict(sys.modules,{'p2pah_auth':auth,'channel_source':channel()}):
            with self.assertRaisesRegex(ValueError,'targeted_request_scope'):shared_correct(self.store,'266',requested)
        auth.Session.assert_not_called()


if __name__=='__main__':unittest.main()
