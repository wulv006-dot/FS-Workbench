import copy, importlib.util, json, sys, tempfile, unittest
import contextlib,io,runpy
from types import SimpleNamespace
from unittest.mock import Mock,patch
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'source'))
from fc_detail_model import normalize, deduplicate, aggregate, amount_bucket
from fc_detail import query, FCDetails,read_source
CFG = json.loads((ROOT / 'source/fc_detail_config.json').read_text())
CFG['trust_customer_flag']=True

def raw(number, amount='20.00', **extra):
    result=dict(id=number, order_no='TEST'+str(number), gid=1327, pay_status=1, site_id=266,
                amount=amount, amount_usd_format='$ '+amount, uid=2, isNew=1,
                content='<em>[PC Platform]</em>100 K coins', paytime='2026-10-11 12:00:00',
                timestamp_format='2026-10-11 11:59:00', lasttime='2026-10-12 08:00:00',
                status=31, status_format='发货·发货中', device=0, country_code='US', paytype_display='paypal')
    result.update(extra);return result

def row(number, amount='20.00', **changes):
    value=raw(number, amount);value.update(changes);return normalize(value, CFG, {266,141,320,575})

def data(rows, backlog=None):
    return {'orders':rows,'backlog':backlog if backlog is not None else rows,'as_of':datetime.now(timezone.utc).isoformat(),
            'snapshot_id':'fc-detail-test','coverage':{'period':{'start':'2026-10-11 00:00','end':'2026-10-12 00:00'}},'data_status':'available'}

Q={'start':'2026-10-11','end':'2026-10-11','pool':'paid','page':'1'}

class FactsTest(unittest.TestCase):
    def test_reader_cli_uses_direct_api_and_closes_without_session_service(self):
        client=Mock()
        client.get_admin.side_effect=lambda path:(200,{'code':1,'data':{'list':[{'id':266}]}}) if 'siteList' in path else (200,{'code':1,'data':{'total':1,'list':[raw(1)]}})
        output=io.StringIO();args={'query':{'period':{'start':'2026-10-11 00:00','end':'2026-10-12 00:00'}},'config':CFG}
        with patch.dict(sys.modules,p2pah_auth=SimpleNamespace(Session=lambda:client)),patch.object(sys,'argv',['reader',json.dumps(args)]),patch.object(sys,'path',list(sys.path)),contextlib.redirect_stdout(output):
            runpy.run_path(str(ROOT/'source/fc_detail_reader.py'),run_name='__main__')
        value=json.loads(output.getvalue());self.assertTrue(value['coverage']['paid_complete']);client.close.assert_called_once()
        self.assertEqual(client.get_admin.call_count,15)
    def test_source_runner_is_original_host_reader_not_a_container(self):
        result=SimpleNamespace(returncode=0,stdout=json.dumps(data([])).encode())
        with patch('fc_detail.subprocess.run',return_value=result) as run:
            self.assertEqual(read_source({},CFG)['snapshot_id'],'fc-detail-test')
        self.assertEqual(run.call_args.args[0][:2],[sys.executable,str(ROOT/'source/fc_detail_reader.py')])
    def risk_data(self, rows, complete=True):
        value=data([],rows)
        value['as_of']='2026-10-14T12:00:00+08:00'
        if complete:value['coverage']['backlog_status']='available'
        return value

    def test_current_risks_use_full_pool_before_ui_paging(self):
        rows=[row(n,'300.00',status=91,status_format='问题单',paytime='2026-10-12 12:00:00') for n in range(1,25)]
        value=self.risk_data(rows)
        q={**Q,'pool':'current','site_group':'main'}
        result=aggregate(value,q,CFG)
        risks=result['current_risks']
        self.assertEqual(len(result['orders']),10)
        self.assertEqual(risks['issues']['orders'],24)
        self.assertEqual(risks['issues']['amount_usd'],7200)
        self.assertEqual(risks['waiting24']['orders'],24)
        self.assertEqual(risks['high_amount']['orders'],24)
        self.assertEqual(aggregate(value,{**q,'page':'3','start':'2026-09-01','end':'2026-09-02'},CFG)['current_risks'],risks)

    def test_risks_deduplicate_before_terminal_filter_and_respect_scope(self):
        live=row(1,'400.00',status=91,status_format='问题单',lasttime='2026-10-12 00:00:00')
        done=row(1,'400.00',status=101,status_format='已完成',lasttime='2026-10-13 00:00:00')
        main=row(2,'300.00',status=91,status_format='问题单')
        satellite=row(3,'500.00',site_id=141,status=91,status_format='问题单')
        result=aggregate(self.risk_data([live,done,main,copy.deepcopy(main),satellite]),{**Q,'site_group':'main'},CFG)
        self.assertEqual(result['backlog_summary']['orders'],1)
        self.assertEqual(result['current_risks']['issues']['amount_usd'],300)
        self.assertEqual(result['current_risks']['high_amount']['orders'],1)
        self.assertEqual(aggregate(self.risk_data([main]),{**Q,'platform':'PS'},CFG)['current_risks']['issues']['orders'],0)

    def test_exact_24_and_72_hour_boundaries_and_money_threshold(self):
        rows=[row(1,'299.99',paytime='2026-10-13 12:00:01'),row(2,'300.00',paytime='2026-10-13 12:00:00'),
              row(3,'300.01',paytime='2026-10-11 12:00:01'),row(4,'400.00',paytime='2026-10-11 12:00:00')]
        at=datetime.fromisoformat('2026-10-14T12:00:00+08:00')
        result=aggregate(self.risk_data(rows),{**Q,'pool':'current'},CFG,now=at)
        r=result['current_risks']
        self.assertEqual(r['aging'],{'under24':1,'24to72':2,'at_least72':1,'unknown_time':0,'created_time_fallback':0})
        self.assertEqual(r['waiting24']['orders'],3)
        self.assertEqual(r['high_amount']['orders'],3)
        near=next(x for x in result['orders'] if x['id']=='TEST1')
        self.assertEqual(near['age_hours'],24.0)
        self.assertNotIn('等待较久',near['attention'])
        self.assertEqual(result['slow_orders'],3)

    def test_money_and_time_unknowns_do_not_become_zero(self):
        rows=[row(1,'',status=91,status_format='问题单',paytime='',timestamp_format=''),
              row(2,'40.00',status=91,status_format='问题单',paytime='',timestamp_format='2026-10-12 12:00:00'),
              row(3,'400.00',paytime='2026-10-14 13:00:00')]
        r=aggregate(self.risk_data(rows),Q,CFG)['current_risks']
        self.assertEqual(r['status'],'partial')
        self.assertEqual(r['issues']['orders'],2);self.assertIsNone(r['issues']['amount_usd'])
        self.assertEqual(r['issues']['known_amount_usd'],40)
        self.assertEqual(r['issues']['missing_amount_orders'],1)
        self.assertEqual(r['aging']['unknown_time'],2);self.assertEqual(r['aging']['created_time_fallback'],1)
        self.assertIsNone(r['waiting24']['orders']);self.assertEqual(r['waiting24']['known_orders'],1)
        self.assertIsNone(r['high_amount']['orders']);self.assertEqual(r['high_amount']['known_orders'],1)
        self.assertIsNone(r['high_amount']['amount_usd'])

    def test_pool_incomplete_or_unverified_suppresses_all_three_totals(self):
        value=self.risk_data([row(1)],complete=False)
        for coverage in ({},{'backlog_status':'partial'},{'backlog_status':'available','backlog_failed_groups':[2]}):
            value['coverage'].update(coverage)
            r=aggregate(value,Q,CFG)['current_risks']
            self.assertEqual(r['status'],'not_available');self.assertNotIn('issues',r)

    def test_financial_states_overlap_without_becoming_loss(self):
        rows=[row(1,'400.00',status_format='投诉·调查中'),row(2,'20.00',status=91,status_format='问题单')]
        r=aggregate(self.risk_data(rows),Q,CFG)['current_risks']
        self.assertEqual(r['issues']['orders'],2);self.assertEqual(r['high_amount']['orders'],1)
        self.assertEqual(r['waiting24']['orders'],1)
        self.assertNotIn('loss',r);self.assertNotIn('profit',r)

    def test_snapshot_aging_is_reproducible_and_empty_verified_pool_is_zero(self):
        value=self.risk_data([row(1,paytime='2026-10-13 12:00:01')])
        first=aggregate(value,Q,CFG,now=datetime.fromisoformat('2026-10-14T12:00:00+08:00'))['current_risks']
        later=aggregate(value,Q,CFG,now=datetime.fromisoformat('2026-10-15T12:00:00+08:00'))['current_risks']
        self.assertEqual(first,later);self.assertEqual(first['waiting24']['orders'],0)
        empty=aggregate(self.risk_data([]),Q,CFG)['current_risks']
        self.assertEqual(empty['issues']['amount_usd'],0);self.assertEqual(empty['high_amount']['orders'],0)

    def test_money_boundaries_and_missing(self):
        r=aggregate(data([row(1,'19.99'),row(2,'20.00'),row(3,'40.00'),row(4,'500.00'),row(5,'')]),Q,CFG)
        self.assertEqual([b['orders'] for b in r['buckets']], [1,1,1,0,0,0,0,0,0,1,1])
        self.assertEqual(sum(b['orders'] for b in r['buckets']),r['totals']['orders'])
        self.assertEqual(r['totals']['unpriced_orders'],1)
    def test_main_satellite_and_no_referral_exclusion(self):
        self.assertEqual(row(1,site_id=575,http_referer='ELD G2G')['site_group'],'satellite')
        self.assertEqual(row(2,site_id=999)['site_group'],'unknown')
        c=copy.deepcopy(CFG);c['distribution_site_ids']=[575]
        self.assertEqual(normalize(raw(3,site_id=575),c,{575})['site_group'],'distribution_group')
    def test_no_non_fc_or_unpaid(self):
        self.assertIsNone(row(1,gid=1329));self.assertIsNone(row(2,pay_status=0))
    def test_dedup_and_customer_arithmetic(self):
        rows=deduplicate([row(1),row(1),row(2,isNew=0),row(3,isNew=None)])
        r=aggregate(data(rows),Q,CFG)
        self.assertEqual(r['totals']['orders'],3)
        self.assertEqual(r['totals']['new']+r['totals']['returning']+r['totals']['unknown'],3)
    def test_user_cumulative_and_site_identity(self):
        r=aggregate(data([row(1,'15.00'),row(2,'35.00'),row(3,'15.00',site_id=141)]),Q,CFG)
        self.assertEqual(r['user_buckets'][2]['users'],1);self.assertEqual(r['users_identified'],2)
    def test_guest_does_not_become_user(self):
        r=aggregate(data([row(1,uid=0),row(2,uid=0)]),Q,CFG)
        self.assertEqual(r['users_identified'],0);self.assertEqual(r['orders_without_customer_id'],2)
    def test_old_backlog_not_date_limited_or_terminal(self):
        old=row(1,paytime='2026-08-01 12:00:00');done=row(2,status=101,status_format='已完成');refund=row(3,status=83,status_format='已退款·其他原因')
        r=aggregate(data([old,done,refund],[old,done,refund]),{**Q,'pool':'current'},CFG)
        self.assertEqual(r['backlog_summary']['orders'],1);self.assertEqual(r['orders'][0]['id'],'TEST1')
        self.assertEqual(r['orders'][0]['age_basis'],'支付时间')
    def test_drill_all_filters_and_pages(self):
        rows=[row(n,customer_key='unused') for n in range(1,25)]
        rows += [row(99,site_id=141),row(100,isNew=0),row(101,'40.00')]
        r=aggregate(data(rows),{**Q,'site_group':'main','customer':'new','platform':'PC','bucket':'1','page':'2'},CFG)
        self.assertEqual(r['list_total'],24);self.assertEqual(len(r['orders']),10)
    def test_no_pii_in_normalized_record(self):
        r=row(1,email='private@example.test',telephone='SECRET_PHONE',add_info='EA_PASSWORD',remark='BACKUP_CODE',note='DO_NOT_EXPORT')
        text=json.dumps(r)
        for value in ('private@example.test','SECRET_PHONE','EA_PASSWORD','BACKUP_CODE','DO_NOT_EXPORT'):self.assertNotIn(value,text)
    def test_unverified_flag_is_unknown_not_returning(self):
        c={**CFG,'trust_customer_flag':False}
        self.assertEqual(normalize(raw(1,isNew=0),c,{266})['customer'],'unknown')
        result=aggregate(data([row(1)]),Q,c)
        self.assertEqual(result['totals']['unknown'],1);self.assertEqual(result['customer_status'],'not_verified')
    def test_query_cannot_escape_fc_scope(self):
        for changes in ({'profile':['D4']},{'site_id':['266']},{'page':['-1']},{'platform':['other']},{'sql':['x']}):
            with self.assertRaises(ValueError):query({'mode':['fc-detail'],'profile':['FC27'],'start':['2026-10-11'],'end':['2026-10-11'],**changes})
    def test_pagination_cash_format_and_failed_source_not_zero(self):
        with tempfile.TemporaryDirectory() as temp,ThreadPoolExecutor(max_workers=1) as pool:
            captured=data([row(1),row(2)])
            c=FCDetails(pool,temp,lambda q,c:{**captured,'coverage':{'period':q['period']}},CFG)
            params={'mode':['fc-detail'],'profile':['FC27'],'start':['2026-10-11'],'end':['2026-10-11']}
            self.assertEqual(c.get(params)[0],202)
            pool.submit(lambda:None).result()
            status,result=c.get({**params,'format':['csv']})
            self.assertEqual(status,200);self.assertIn('TEST1',result['csv']);self.assertEqual(result['totals']['orders'],2)
            report=c.get({**params,'mode':['fc-report']})[1]['report']
            self.assertTrue(report['report_id']);self.assertEqual(len(list((Path(temp)/'reports').glob('*.json'))),1)
    def test_refresh_uses_same_cache_queue_and_csv_exports_all(self):
        calls=[]
        with tempfile.TemporaryDirectory() as temp,ThreadPoolExecutor(max_workers=1) as pool:
            def read(q,c):
                calls.append(q)
                return {**data([row(n) for n in range(1,25)]),'coverage':{'period':q['period']}}
            cache=FCDetails(pool,temp,read,CFG)
            params={'mode':['fc-detail'],'profile':['FC27'],'start':['2026-10-11'],'end':['2026-10-11']}
            self.assertEqual(cache.get(params)[0],202);pool.submit(lambda:None).result()
            result=cache.get({**params,'format':['csv']})[1]
            self.assertEqual(len(result['csv'].splitlines()),25);self.assertEqual(len(result['orders']),10)
            self.assertEqual(cache.get({**params,'refresh':['true']})[0],202);pool.submit(lambda:None).result()
            self.assertEqual(cache.get(params)[0],200);self.assertEqual(len(calls),2)
            cache.config={**CFG,'trust_customer_flag':False}
            with self.assertRaisesRegex(ValueError,'customer_not_verified'):cache.get({**params,'customer':['new']})

    def test_snapshot_csv_exports_only_the_requested_cached_revision(self):
        calls=[]
        with tempfile.TemporaryDirectory() as temp,ThreadPoolExecutor(max_workers=1) as pool:
            def read(q,c):
                calls.append(q)
                return {**data([row(1)]),'snapshot_id':'fc-detail-'+str(len(calls)),
                        'coverage':{'period':q['period']}}
            cache=FCDetails(pool,temp,read,CFG)
            params={'mode':['fc-detail'],'profile':['FC27'],'start':['2026-10-11'],'end':['2026-10-11']}
            export={**params,'format':['csv'],'snapshot_id':['fc-detail-1']}
            self.assertEqual(cache.get(export),(409,{'error':'fc_export_snapshot_changed'}))
            self.assertEqual(calls,[])
            self.assertEqual(cache.get(params)[0],202);pool.submit(lambda:None).result()
            status,result=cache.get(export)
            self.assertEqual(status,200)
            self.assertIn('TEST1',result['csv'])
            self.assertEqual(result['snapshot_id'],'fc-detail-1')
            self.assertIn('fc-detail-1',result['csv'])
            self.assertIn('fc-detail-1',result['dashboard_csv'])
            self.assertEqual(cache.get({**params,'refresh':['true']})[0],202);pool.submit(lambda:None).result()
            self.assertEqual(cache.get(export),(409,{'error':'fc_export_snapshot_changed'}))
            self.assertEqual(len(calls),2)

    def test_failed_initial_source_is_unavailable_not_zero(self):
        def failed(q,c):raise OSError('unavailable')
        with tempfile.TemporaryDirectory() as temp,ThreadPoolExecutor(max_workers=1) as pool:
            cache=FCDetails(pool,temp,failed,CFG)
            params={'mode':['fc-detail'],'profile':['FC27'],'start':['2026-10-11'],'end':['2026-10-11']}
            self.assertEqual(cache.get(params)[0],202);pool.submit(lambda:None).result()
            status,result=cache.get(params);self.assertEqual(status,503);self.assertNotIn('totals',result)

if __name__=='__main__':unittest.main()
