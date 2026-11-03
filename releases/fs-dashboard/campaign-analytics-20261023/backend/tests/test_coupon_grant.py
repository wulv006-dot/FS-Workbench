"""One private recipient, original durable ledger, synthetic final Admin boundary."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from campaign_backend.benefits import row_hash
from campaign_backend.core import ContractError
from campaign_backend.services import BackendServices
from campaign_backend.adapters import AdminRead
from test_benefit_operations import native_row


class CouponGrantTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.backend=BackendServices(Path(self.temp.name)/'private',{})
        self.row=dict(native_row(),status=1)
        self.request=dict(action='coupon_grant',site_id='266',kind='coupon',native_id='123',
            operation_id='synthetic-grant-operation',before_hash=row_hash(self.row),
            grant_batch_no='synthetic-approved-batch',email='one@example.test')
        self.posts=[];self.gets=[];self.timeout=False;self.retries=0;self.code=1
        # status is deliberately opaque: public JS defines no success enum.
        self.data=dict(mode='sync',batch_no=self.request['grant_batch_no'],total=1,success=1,
            not_found=0,pending_register=0,skipped_limit=0,failed=0,
            rows=[dict(email=self.request['email'],status='opaque-server-value',member_id=321,member_coupon_id=456,msg='private')])
        self.job=None
        test=self
        class Session:
            token='synthetic-token'
            @property
            def admin(self):return self
            def get_adapter(self,url):return SimpleNamespace(max_retries=SimpleNamespace(total=test.retries))
            def post(self,url,**kwargs):
                test.posts.append((url,kwargs))
                if test.timeout:raise TimeoutError('synthetic only')
                return SimpleNamespace(status_code=200,content=json.dumps(dict(code=test.code,data=test.data)).encode())
            def get_admin(self,route,**params):
                test.gets.append((route,params))
                return 200,dict(code=1,data=deepcopy(test.job))
        class Reader(AdminRead):
            def detail(self,kind,ident):return deepcopy(test.row)
            def close(self):pass
        self.reader=Reader(Session())

    def call(self,request=None):
        return self.backend.handle(request or self.request,lambda:self.reader,grant_authorize=lambda payload:payload==self.request)

    def test_no_private_host_approval_cannot_dispatch(self):
        with self.assertRaisesRegex(ContractError,'BUSINESS_AUTHORIZATION_REQUIRED'):
            self.backend.handle(self.request,lambda:self.reader)
        self.assertEqual(self.posts,[])

    def lookup(self,reconcile=False):
        return self.call(dict(action='operation_reconcile' if reconcile else 'operation_lookup',site_id='266',
            operation_id=self.request['operation_id']))

    def test_sync_confirms_unique_actual_result_without_job_or_undefined_echoes(self):
        result=self.call()
        self.assertEqual(result['state'],'confirmed')
        self.assertEqual(result['result']['upstream_ref'],'member-coupon:456')
        self.assertEqual(self.call(),result);self.assertEqual(len(self.posts),1)
        url,wire=self.posts[0]
        self.assertEqual(url,'https://admin-api.p2pah.cn/admin/market.CouponGrant/import')
        self.assertEqual(wire['json'],dict(site_id='266',coupon_id='123',grant_batch_no='synthetic-approved-batch',emails='one@example.test'))
        self.assertFalse(wire['allow_redirects']);self.assertNotIn('operation_id',wire['json'])
        from campaign_backend.ledger import OperationLedger
        original=OperationLedger(self.backend.state_dir/'operations.sqlite3').request_payload(self.request['operation_id'])
        self.assertEqual(original,self.request)

    def test_optional_counts_absent_are_not_fabricated_or_required(self):
        for key in ('total','not_found','pending_register','skipped_limit','failed','batch_no'):
            self.data.pop(key)
        self.data['not_found']=None  # Unknown optional statistic is not fabricated zero.
        self.assertEqual(self.call()['state'],'confirmed')
        self.assertEqual(len(self.posts),1)

    def test_sync_distinguishes_real_non_success_and_never_reposts(self):
        for outcome in ('not_found','pending_register','skipped_limit','failed'):
            with self.subTest(outcome=outcome):
                self.backend=BackendServices(Path(self.temp.name)/outcome,{})
                self.request['operation_id']='synthetic-'+outcome
                self.data.update(success=0,not_found=0,pending_register=0,skipped_limit=0,failed=0)
                self.data[outcome]=1;self.data['rows'][0]['member_coupon_id']=None
                result=self.call()
                self.assertEqual(result['state'],'unknown' if outcome=='pending_register' else 'rejected')
                self.assertEqual(result['result']['reason_code'],'GRANT_'+outcome.upper())
                self.assertEqual(self.call(),result)
        self.assertEqual(len(self.posts),4)

    def test_unconfirmed_conflicting_target_batch_counts_or_missing_result_stay_unknown(self):
        original=deepcopy(self.data)
        bad=[dict(original,success=None),dict(original,success=0),dict(original,total=2),
             dict(original,failed=1),dict(original,batch_no='another-batch'),dict(original,rows=[]),
             dict(original,rows=original['rows']*2),dict(original,rows=[dict(original['rows'][0],email='other@example.test')]),
             dict(original,rows=[dict(original['rows'][0],member_coupon_id=None)]),
             dict(original,rows=[{k:v for k,v in original['rows'][0].items() if k!='status'}])]
        for index,value in enumerate(bad):
            with self.subTest(index=index):
                # Each unknown keeps the object lock: use an independent real ledger.
                self.backend=BackendServices(Path(self.temp.name)/str(index),{})
                self.data=value;result=self.call()
                self.assertEqual(result['state'],'unknown');self.assertEqual(self.call(),result)
        self.assertEqual(len(self.posts),len(bad))

    def test_async_persists_real_job_and_queries_only_original_id(self):
        completed=deepcopy(self.data)
        self.data=dict(mode='async',job_id='job-123',batch_no=self.request['grant_batch_no'])
        result=self.call();self.assertEqual(result['state'],'unknown')
        self.assertEqual(result['result']['upstream_ref'],'job-123')
        self.job=dict(mode='async',job_id='job-123',status='pending')
        self.assertEqual(self.lookup(True)['result']['reason_code'],'GRANT_TASK_PENDING')
        self.job=dict(completed,mode='async',job_id='wrong-job',status='done')
        self.assertEqual(self.lookup(True)['state'],'unknown')
        self.job=dict(completed,mode='async',job_id='job-123',status='done')
        self.assertEqual(self.lookup(True)['state'],'confirmed')
        self.assertEqual(self.lookup(True)['state'],'confirmed')
        self.assertEqual(self.gets,[('/admin/market.CouponGrant/jobStatus',{'job_id':'job-123'})]*3)
        self.assertEqual(len(self.posts),1)

    def test_async_missing_or_wrong_id_and_transport_unknown_never_guess_batch_lookup(self):
        self.data=dict(mode='async',batch_no=self.request['grant_batch_no'])
        self.assertEqual(self.call()['state'],'unknown')
        self.assertEqual(self.lookup(True)['state'],'unknown');self.assertEqual(self.gets,[])
        self.assertEqual(len(self.posts),1)
        self.backend=BackendServices(Path(self.temp.name)/'timeout',{});self.timeout=True
        self.assertEqual(self.call()['state'],'unknown')
        self.assertEqual(self.call()['state'],'unknown');self.assertEqual(self.lookup(True)['state'],'unknown')
        self.assertEqual(len(self.posts),2);self.assertEqual(self.gets,[])

    def test_template_scope_before_and_one_recipient_reject_before_post(self):
        for changes in ({'email':'one@example.test two@example.test'},{'site_id':'0'},{'before_hash':'0'*64}):
            with self.subTest(changes=tuple(changes)),self.assertRaises(ContractError):self.call(dict(self.request,**changes))
        self.row['fetch_scene']=3
        with self.assertRaises(ContractError):self.call()
        self.assertEqual(self.posts,[])


if __name__=='__main__':unittest.main()
