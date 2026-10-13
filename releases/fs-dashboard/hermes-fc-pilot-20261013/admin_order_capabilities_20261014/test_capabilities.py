"""Synthetic trust-boundary/coverage tests, not live source acceptance."""
from concurrent.futures import Future
from copy import deepcopy
from datetime import datetime, timezone
import json
import threading
import hashlib
import unittest
import io
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError

from .capabilities import (checked_query, collect_admin, fulfillment_projection,
                          native_projection, number)
from .admin_session_entry import collect_with_manager
from .provider import CapabilityProvider, tool_schema, response_budget
from .order_detail_projection import read_open_detail
from .fs_reader import admin_read

CONFIG = {'enabled':True,'game_id':1327,'main_site_id':266}
NOW = datetime(2026,10,14,0,30,tzinfo=timezone.utc)
TASK_A, TASK_B = b'a'*32, b'b'*32  # Synthetic keys, never production keys.
NATIVE = {'kind':'native_loss','profile':'FC27','start':'2026-10-13','end':'2026-10-13'}
PRODUCT = dict(NATIVE,kind='product_sales',pages=2)


def native():
    return {'code':1,'time':1791913008,'data':{'data':{
        'total':439,'amount':'29011.54','site_rank':{'main':{'site_name':'www.mmoexp.com'}},
        'game_rank':{'FC 27':{'gid':1327,'cat':{'gold':{'num':200,'amount':'15000.00'}},
            'cb':{'n':2,'amount':'11.50','order_id':['not-for-model']},
            'peak_order_count':1000,'peak_order_date':'2026-10-01','order_no_all':['not-for-model'],
            'contact':'not-for-model'}}}}}


def product(pid=100, **extra):
    return dict(gid=1327,site_id=266,pid=pid,aid=21587,cid=1,title='100 K coins',
        sale_total=245,order_count=236,total_amount='15025.48',paytime=1791854280,
        member={'passwd':'not-for-model'},**extra)


def reply(rows, total=20):
    return 200,json.dumps({'code':1,'time':1791914123,'data':{'list':rows,'total':total}})


def events():
    return {'contract':'fc-order-events-raw-v1','status':'available','captured_at':'2026-10-13T18:00:00+00:00','listed':20,'pages':1,'has_more':True,
        'samples':[{'id':'123','gid':1322,'source':'www.mmoexp.com','status':'问题单','platform':'PS',
            'actor':'not-for-model','content':'not-for-model',
            'items':[{'gid':'1322','aid':'21942','cid':'1','pid':'6394226','qty':'525','used':'0','unit':'K','currency':'USD','rmb':'not-for-model'}],
            'events':[{'id':'1','time':'26-10-14 01:54:52','status':'问题单','actor':'not-for-model'},
                      {'id':'2','time':'26-10-14 01:54:52','status':'问题单','content':'not-for-model'}]}]}


class ProjectionTests(unittest.TestCase):
    def test_query_timezone_range_and_ttl(self):
        q=checked_query(NATIVE,CONFIG,NOW)
        self.assertEqual(q['date_utc'],['2026-10-12T16:00:00.000Z','2026-10-13T15:59:59.000Z'])
        self.assertEqual(q['ttl_seconds'],7200)
        q=checked_query(dict(NATIVE,start='2026-10-14',end='2026-10-14'),CONFIG,NOW)
        self.assertEqual(q['period']['end'],'2026-10-14 08:30:00')
        self.assertEqual(q['ttl_seconds'],900)

    def test_closed_fields_and_mapping(self):
        for extra in ({'url':'https://example.com'},{'role':'admin'},{'token':'x'},{'page':True}):
            with self.assertRaises(ValueError):checked_query(dict(NATIVE,**extra),CONFIG,NOW)
        with self.assertRaises(ValueError):checked_query(dict(NATIVE,profile='FC26'),CONFIG,NOW)
        with self.assertRaises(ValueError):checked_query(NATIVE,dict(CONFIG,main_site_id=1),NOW)

    def test_period_rejects_future_reversed_and_large(self):
        for start,end in [('2026-10-15','2026-10-15'),('2026-10-14','2026-10-13'),('2026-08-01','2026-10-13')]:
            with self.assertRaises(ValueError):checked_query(dict(NATIVE,start=start,end=end),CONFIG,NOW)

    def test_native_semantics_missing_null_and_secret_projection(self):
        value=native_projection(native(),checked_query(NATIVE,CONFIG,NOW))
        self.assertEqual(value['loss_groups']['cb'],{'count':2,'amount_usd':'11.50'})
        self.assertIsNone(value['loss_groups']['pianzi']['count'])
        self.assertIsNone(value['categories']['coach']['amount_usd'])
        self.assertFalse(value['coverage']['definitions_verified'])
        self.assertNotIn('not-for-model',json.dumps(value))

    def test_native_rejects_filter_leak(self):
        for scope in ('game','site'):
            payload=native();data=payload['data']['data']
            if scope=='game':data['game_rank']['FC 27']['gid']=1
            else:data['site_rank']['main']['site_name']='other-site'
            with self.assertRaises(ValueError):native_projection(payload,checked_query(NATIVE,CONFIG,NOW))
        payload=native();payload['data']['data']['site_rank']={}
        with self.assertRaises(ValueError):native_projection(payload,checked_query(NATIVE,CONFIG,NOW))
        payload=native();payload['data']['data']['game_rank']['FC 27']['cat']=[]
        with self.assertRaises(ValueError):native_projection(payload,checked_query(NATIVE,CONFIG,NOW))

    def test_business_code_denial_is_not_empty(self):
        for status,payload in [(200,{'code':401,'msg':'not-for-model'}),(403,{'code':1})]:
            out=collect_admin(lambda path,body:(status,json.dumps(payload)),NATIVE,CONFIG,NOW)
            self.assertEqual(out['status'],'denied')
            self.assertNotIn('not-for-model',json.dumps(out))

    def test_failed_native_shape_has_only_fixed_safe_diagnostic(self):
        raw=native();raw['data']['data']['game_rank']=[]
        out=collect_admin(lambda *_:(200,json.dumps(raw)),NATIVE,CONFIG,NOW)
        self.assertEqual(out['reason'],'native_shape')
        self.assertNotIn('not-for-model',json.dumps(out))
        out=collect_admin(lambda *_:(200,'not-for-model'),NATIVE,CONFIG,NOW)
        self.assertEqual(out['reason'],'source_contract_or_read_failed')
        self.assertNotIn('not-for-model',json.dumps(out))

    def test_loopback_failure_preserves_projected_reason_for_provider(self):
        for status,kind,reason in ((503,'not_available','native_shape'),):
            projected=collect_admin(lambda *_:(200,json.dumps({'code':403})),NATIVE,CONFIG,NOW)
            projected.update(status=kind,reason=reason)
            error=HTTPError('http://127.0.0.1:8767/business/fc-capability',status,'fixed-local',{},io.BytesIO(json.dumps(projected).encode()))
            with patch('admin_order_capabilities_20261014.fs_reader.build_opener') as opener:
                opener.return_value.open.side_effect=error
                out=admin_read(NATIVE)
            self.assertEqual(out,projected)
            provider=CapabilityProvider(dict(CONFIG),ImmediatePool(),lambda _:out,None,TASK_A,date_clock=lambda:NOW)
            provider.get(NATIVE);self.assertEqual(provider.get(NATIVE)['reason'],reason)

    def test_loopback403_never_revives_good_cache_for_any_body(self):
        good=collect_admin(lambda *_:(200,json.dumps(native())),NATIVE,CONFIG,NOW)
        for body in (b'{"status":"denied"}',b'{',b'x'*1000001,json.dumps(good).encode()):
            clock=[0];calls=[0]
            def read(args):
                calls[0]+=1
                if calls[0]==1:return good
                error=HTTPError('http://127.0.0.1:8767/business/fc-capability',403,'fixed-local',{},io.BytesIO(body))
                with patch('admin_order_capabilities_20261014.fs_reader.build_opener') as opener:
                    opener.return_value.open.side_effect=error
                    return admin_read(args)
            provider=CapabilityProvider(dict(CONFIG),ImmediatePool(),read,None,TASK_A,lambda:clock[0],lambda:NOW)
            provider.get(NATIVE);self.assertEqual(provider.get(NATIVE)['status'],'available')
            clock[0]=7201;provider.get(NATIVE);out=provider.get(NATIVE)
            self.assertEqual(out['status'],'denied');self.assertNotIn('source_amount_usd',out)
            self.assertNotIn('stale',out)

    def test_loopback503_cannot_become_a_fresh_success(self):
        good=collect_admin(lambda *_:(200,json.dumps(native())),NATIVE,CONFIG,NOW)
        for body in (json.dumps(good).encode(),b'{"status":"partial"}',b'{',b'x'*1000001):
            clock=[0];calls=[0]
            def read(args):
                calls[0]+=1
                if calls[0]==1:return good
                error=HTTPError('http://127.0.0.1:8767/business/fc-capability',503,'fixed-local',{},io.BytesIO(body))
                with patch('admin_order_capabilities_20261014.fs_reader.build_opener') as opener:
                    opener.return_value.open.side_effect=error
                    return admin_read(args)
            provider=CapabilityProvider(dict(CONFIG),ImmediatePool(),read,None,TASK_A,lambda:clock[0],lambda:NOW)
            provider.get(NATIVE);self.assertEqual(provider.get(NATIVE)['status'],'available')
            clock[0]=7201;provider.get(NATIVE);out=provider.get(NATIVE)
            self.assertTrue(out['stale']);self.assertEqual(out['refresh_status'],'not_available')

    def test_disabled_makes_no_query(self):
        out=collect_admin(lambda *a:self.fail('disabled called source'),NATIVE,dict(CONFIG,enabled=False),NOW)
        self.assertEqual(out['reason'],'fc_detail_disabled')

    def test_only_observed_read_endpoints_and_exact_post(self):
        calls=[]
        def read(path,body):calls.append((path,body));return 200,json.dumps(native())
        out=collect_admin(read,NATIVE,CONFIG,NOW)
        self.assertEqual(out['status'],'available')
        self.assertEqual(calls[0][0],'/admin/order.Order/orderStaticsDetailByEs')
        self.assertEqual(calls[0][1]['site'],266)
        self.assertEqual(calls[0][1]['game'],1327)
        self.assertEqual(calls[0][1]['pay_status'],1)

    def test_product_duplicate_and_total_are_explicit(self):
        calls=[]
        def read(path,body):
            calls.append((path,body));return reply([product(i) for i in range(10)],20)
        out=collect_admin(read,PRODUCT,CONFIG,NOW)
        self.assertEqual(out['status'],'partial')
        self.assertEqual(out['coverage']['distinct_projected_rows'],10)
        self.assertEqual(out['coverage']['received_rows'],20)
        self.assertIn('exact_duplicate_rows',out['errors'])
        self.assertFalse(out['coverage']['complete'])
        self.assertNotIn('not-for-model',json.dumps(out))
        params=parse_qs(urlsplit(calls[0][0]).query)
        self.assertEqual(params['order'],['order_count,descending'])
        self.assertIn('2026-10-13 00:00:00,2026-10-13 23:59:59',params['search[2][val]'])
        self.assertTrue(all(body is None for _,body in calls))

    def test_product_changed_total_is_partial(self):
        count=[0]
        def read(path,body):
            count[0]+=1;return reply([product(i+10*count[0]) for i in range(10)],20+count[0])
        out=collect_admin(read,PRODUCT,CONFIG,NOW)
        self.assertFalse(out['coverage']['total_stable'])
        self.assertIsNone(out['coverage']['source_total'])
        self.assertIn('source_total_changed',out['errors'])

    def test_product_wrong_site_or_dimension_not_exposed(self):
        for field,value in [('site_id',1),('gid',1),('aid',1)]:
            row=product();row[field]=value
            out=collect_admin(lambda *a:reply([row]),dict(PRODUCT,area_id=21587),CONFIG,NOW)
            self.assertEqual(out['status'],'not_available')
            self.assertNotIn('rows',out)

    def test_product_nested_objects_and_unsafe_title_dropped(self):
        row=product();row['title']='person@example.com';row['total_amount']='not-for-model'
        out=collect_admin(lambda *a:reply([row],1),PRODUCT,CONFIG,NOW)
        self.assertIsNone(out['rows'][0]['title'])
        self.assertIsNone(out['rows'][0]['total_amount_usd'])
        self.assertNotIn('passwd',json.dumps(out))

    def test_non_numeric_is_not_zero(self):
        for value in (None,True,[],{},'1e3','NaN','1,234'):
            self.assertIsNone(number(value))

    def test_events_keep_same_second_distinct_and_task_scope(self):
        q=checked_query({'kind':'fulfillment_samples','profile':'FC27'},CONFIG,NOW)
        a=fulfillment_projection(events(),q,TASK_A);b=fulfillment_projection(events(),q,TASK_B)
        self.assertEqual(len(a['samples'][0]['events']),2)
        self.assertNotEqual(a['samples'][0]['events'][0]['event_ref'],a['samples'][0]['events'][1]['event_ref'])
        self.assertNotEqual(a['samples'][0]['case_ref'],b['samples'][0]['case_ref'])
        self.assertEqual(a['samples'][0]['items'][0]['used'],'0')
        self.assertNotIn('pid',a['samples'][0]['items'][0])
        self.assertNotEqual(a['samples'][0]['items'][0]['item_ref'],b['samples'][0]['items'][0]['item_ref'])
        self.assertEqual(a['source_captured_at'],'2026-10-13T18:00:00+00:00')
        self.assertNotIn('not-for-model',json.dumps(a))
        self.assertFalse(a['coverage']['history_complete'])
        public_case=a['samples'][0]['case_ref'];public_event=a['samples'][0]['events'][0]['event_ref']
        candidates={'event_'+hashlib.sha256((public_case+'\0'+str(i)).encode()).hexdigest()[:24] for i in range(1000)}
        self.assertNotIn(public_event,candidates)

    def test_events_reject_duplicate_id_and_wrong_scope(self):
        q=checked_query({'kind':'fulfillment_samples','profile':'FC27'},CONFIG,NOW)
        for change in ('id','scope'):
            raw=events()
            if change=='id':raw['samples'][0]['events'][1]['id']='1'
            else:raw['samples'][0]['source']='other-site'
            with self.assertRaises(ValueError):fulfillment_projection(raw,q,TASK_A)

    def test_events_report_reader_truncation(self):
        q=checked_query({'kind':'fulfillment_samples','profile':'FC27'},CONFIG,NOW)
        raw=events();raw['samples'][0]['event_count']=200
        out=fulfillment_projection(raw,q,TASK_A)
        self.assertTrue(out['samples'][0]['truncated'])
        self.assertEqual(out['samples'][0]['source_event_count'],200)

    def test_order_open_detail_scope_and_path(self):
        class Page:
            def __init__(self,origin='https://order.p2pah.cn'):self.origin=origin
            def evaluate(self,script):
                self.script=script
                return {'origin':self.origin,'path':'/order/admin_order/look/id/123.html','login':False,
                        'found':True,'items':[],'events':[],'item_count':0,'event_count':0}
        page=Page();out=read_open_detail(page,'/order/admin_order/look/id/123.html')
        self.assertEqual(out['event_count'],0)
        # Selection deliberately excludes actor/content and rmb attributes.
        self.assertNotIn('c[2].textContent',page.script)
        self.assertNotIn('c[4].textContent',page.script)
        self.assertNotIn("'rmb'",page.script)
        with self.assertRaises(ValueError):read_open_detail(Page('https://example.com'),'/order/admin_order/look/id/123.html')
        with self.assertRaises(ValueError):read_open_detail(page,'/order/admin_order/edit/id/123.html')

    def test_session_binding_disabled_or_missing_identity_no_request(self):
        class Manager:
            lock=threading.RLock();token=None
            def identity_ok(self,token):return False
            def request(self,*a,**k):raise AssertionError('no source request')
        out=collect_with_manager(Manager(),NATIVE,CONFIG,NOW)
        self.assertEqual(out['reason'],'existing_auth_unavailable')
        out=collect_with_manager(None,NATIVE,dict(CONFIG,enabled=False),NOW)
        self.assertEqual(out['reason'],'fc_detail_disabled')

    def test_tool_schema_closed(self):
        params=tool_schema()['function']['parameters']
        self.assertFalse(params['additionalProperties'])
        self.assertNotIn('url',params['properties'])
        self.assertNotIn('token',params['properties'])

    def test_kind_schema_rejects_missing_dates_and_irrelevant_fields(self):
        params=tool_schema()['function']['parameters']
        branches={b['properties']['kind']['enum'][0]:b for b in params['oneOf']}
        for kind in ('native_loss','product_sales'):
            self.assertEqual(branches[kind]['required'],['start','end'])
        for kind,args in [('native_loss',NATIVE),('product_sales',PRODUCT),
                          ('fulfillment_samples',{'kind':'fulfillment_samples','profile':'FC27','platform':'PS'})]:
            checked_query(args,CONFIG,NOW)
            branch=branches[kind]
            self.assertTrue(set(branch.get('required',[]))<=set(args))
            self.assertFalse(any(branch['properties'].get(k) is False for k in args))
        self.assertIs(branches['product_sales']['properties']['samples'],False)
        self.assertIs(branches['native_loss']['properties']['pages'],False)
        self.assertIs(branches['fulfillment_samples']['properties']['start'],False)
        self.assertEqual(params['properties']['sort']['enum'],['order_count,descending'])
        for sort in ('order_count,desc','total_amount,desc','total_amount,descending'):
            with self.assertRaises(ValueError):checked_query(dict(PRODUCT,sort=sort),CONFIG,NOW)

    def test_order_reader_errors_are_bounded_safe_coverage(self):
        raw=events();raw['samples']=[]
        raw['errors']=['read_budget','sample_budget','sample_unavailable','read_budget','private-note',{'token':'private-note'}]*100
        out=fulfillment_projection(raw,checked_query({'kind':'fulfillment_samples','profile':'FC27'},CONFIG,NOW),TASK_A)
        self.assertEqual(out['coverage']['errors'],['read_budget','sample_budget','sample_unavailable'])
        self.assertEqual(out['coverage']['sampled'],0)
        self.assertNotIn('private-note',json.dumps(out))

    def test_transport_budget_reports_truncation(self):
        value={'status':'partial','rows':[{'title':'字'*160,'area':'字'*160} for _ in range(300)],
               'coverage':{'complete':False,'received_rows':300}}
        out=response_budget(value)
        self.assertLessEqual(len(json.dumps(out,ensure_ascii=True,separators=(',',':')).encode()),12000)
        self.assertTrue(out['coverage']['output_truncated'])
        self.assertEqual(out['coverage']['received_rows'],300)
        self.assertLess(len(out['rows']),300)

    def test_transport_budget_includes_truncation_metadata_at_boundary(self):
        value={'status':'available','http_status':200,'rows':[{'title':'x'*28} for _ in range(300)],'coverage':{'complete':True}}
        before=deepcopy(value);out=response_budget(value)
        self.assertLessEqual(len(json.dumps(out,ensure_ascii=True,separators=(',',':')).encode()),12000)
        self.assertTrue(out['coverage']['output_truncated'])
        self.assertEqual(value,before)


class ImmediatePool:
    def submit(self,fn,*args):
        f=Future()
        try:f.set_result(fn(*args))
        except Exception as error:f.set_exception(error)
        return f


class ProviderTests(unittest.TestCase):
    def test_pending_not_zero_and_retains_good_after_failed_refresh(self):
        clock=[0];calls=[0]
        def read(args):
            calls[0]+=1
            status,body=(200,json.dumps(native())) if calls[0]==1 else (503,'{}')
            return collect_admin(lambda *a:(status,body),args,CONFIG,NOW)
        provider=CapabilityProvider(dict(CONFIG),ImmediatePool(),read,None,TASK_A,lambda:clock[0],lambda:NOW)
        self.assertEqual(provider.get(NATIVE)['status'],'pending')
        good=provider.get(NATIVE)
        self.assertEqual(good['status'],'available')
        clock[0]=7201
        self.assertTrue(provider.get(NATIVE)['stale'])
        refreshed=provider.get(NATIVE)
        self.assertEqual(refreshed['source_amount_usd'],'29011.54')
        self.assertEqual(refreshed['refresh_status'],'not_available')
        self.assertEqual(calls[0],2)
        provider.config['enabled']=False
        self.assertEqual(provider.get(NATIVE)['reason'],'fc_detail_disabled')
        self.assertEqual(calls[0],2)

    def test_permission_denial_never_releases_cached_values(self):
        clock=[0];calls=[0]
        def read(args):
            calls[0]+=1
            status,body=(200,json.dumps(native())) if calls[0]==1 else (200,json.dumps({'code':401})) if calls[0]==2 else (503,'{}')
            return collect_admin(lambda *a:(status,body),args,CONFIG,NOW)
        provider=CapabilityProvider(dict(CONFIG),ImmediatePool(),read,None,TASK_A,lambda:clock[0],lambda:NOW)
        provider.get(NATIVE);self.assertEqual(provider.get(NATIVE)['status'],'available')
        clock[0]=7201;provider.get(NATIVE)
        out=provider.get(NATIVE)
        self.assertEqual(out['status'],'denied');self.assertNotIn('source_amount_usd',out)
        clock[0]+=61;provider.get(NATIVE);out=provider.get(NATIVE)
        self.assertEqual(out['status'],'denied');self.assertNotIn('source_amount_usd',out)

    def test_ttl_begins_at_completion_not_consumption(self):
        clock=[0]
        def read(args):return collect_admin(lambda *a:(200,json.dumps(native())),args,CONFIG,NOW)
        provider=CapabilityProvider(dict(CONFIG),ImmediatePool(),read,None,TASK_A,lambda:clock[0],lambda:NOW)
        provider.get(NATIVE);clock[0]=8000
        out=provider.get(NATIVE)
        self.assertTrue(out['stale']);self.assertEqual(out['refresh_status'],'pending')

    def test_midnight_invalidates_unfinished_day(self):
        dates=[datetime(2026,10,13,15,58,tzinfo=timezone.utc)];clock=[0]
        def read(args):return collect_admin(lambda *a:(200,json.dumps(native())),args,CONFIG,dates[0])
        provider=CapabilityProvider(dict(CONFIG),ImmediatePool(),read,None,TASK_A,lambda:clock[0],lambda:dates[0])
        provider.get(NATIVE);old=provider.get(NATIVE)
        self.assertEqual(old['query']['period']['end'],'2026-10-13 23:58:00')
        dates[0]=datetime(2026,10,13,16,1,tzinfo=timezone.utc);clock[0]=180
        out=provider.get(NATIVE)
        self.assertEqual(out['status'],'pending');self.assertNotIn('source_amount_usd',out)
        new=provider.get(NATIVE)
        self.assertEqual(new['query']['period']['end'],'2026-10-13 23:59:59')

    def test_raw_admin_object_is_not_a_projected_callback(self):
        provider=CapabilityProvider(dict(CONFIG),ImmediatePool(),lambda args:native(),None,TASK_A,date_clock=lambda:NOW)
        provider.get(NATIVE);out=provider.get(NATIVE)
        self.assertEqual(out['status'],'not_available');self.assertNotIn('data',out)

    def test_each_provider_defaults_to_private_distinct_key(self):
        a=CapabilityProvider(dict(CONFIG),ImmediatePool(),None,None)
        b=CapabilityProvider(dict(CONFIG),ImmediatePool(),None,None)
        self.assertEqual(len(a.task_key),32);self.assertNotEqual(a.task_key,b.task_key)
        with self.assertRaises(ValueError):CapabilityProvider(dict(CONFIG),ImmediatePool(),None,None,'public-task-id')

    def test_transport_permission_exceptions_are_denial_not_stale(self):
        for error in (PermissionError('not-for-model'),HTTPError('https://example.com',403,'not-for-model',None,None)):
            clock=[0];calls=[0]
            def read(args):
                calls[0]+=1
                if calls[0]>1:raise error
                return collect_admin(lambda *a:(200,json.dumps(native())),args,CONFIG,NOW)
            provider=CapabilityProvider(dict(CONFIG),ImmediatePool(),read,None,TASK_A,lambda:clock[0],lambda:NOW)
            provider.get(NATIVE);provider.get(NATIVE);clock[0]=7201
            provider.get(NATIVE);out=provider.get(NATIVE)
            self.assertEqual(out['status'],'denied');self.assertNotIn('source_amount_usd',out)
            self.assertNotIn('not-for-model',json.dumps(out))


if __name__ == '__main__':unittest.main()
