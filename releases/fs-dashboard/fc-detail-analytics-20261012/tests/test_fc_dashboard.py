import copy
import json
import sys
import unittest
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'source'))
from fc_dashboard import classify, collect_shipping, project, shipping_membership, native_membership, export_csv, reconcile_shipping, filter_echo_matches
from fc_detail_model import normalize, aggregate, deduplicate, selected
from fc_detail import query, FCDetails, atomic
from fc_detail_reader import collect
from test_fc_detail import CFG, raw, Q, data
CFG = {**CFG, '_category_paths': {'1':['1'], '9627':['2','9627'], '9625':['2','9625'], '9629':['2','9629'], '4':['4']}}
NATIVE = {'Coins':('1','1'), 'Players':('9627','0'), 'SBC':('9625','0'), 'Packs':('9629','0'), 'Boosting':('4','2')}
def native(kinds):
    return [dict(pid=str(i+1),goods={'id':str(i+1),'cid':NATIVE[k][0]},native_type=NATIVE[k][1]) for i,k in enumerate(kinds)]

def markup(*kinds):
    return '<em class="area">[PC Platform]</em>' + ''.join('<span class="item">%s - Synthetic x 1 = $20</span>' % kind for kind in kinds)

def order(n, kinds=('Coins',), site=266, **changes):
    return normalize(raw(n, content=markup(*kinds), site_id=site,
                         site={'full_title':'www.mmoexp.com' if site==266 else 'www.test.com'},
                         _fc_native_items=native(kinds), _fc_items_complete=True, **changes), CFG, {266,141})

def ship(n, sale='100', cost='80', sn='TEST1', source='www.mmoexp.com', at='2026-10-11 14:00:00'):
    return dict(delivery_id=str(n),source=source,sn=sn,trade_at=at,sale_total=sale,cost_total=cost)

def dataset(rows, deliveries):
    value=data(rows,[])
    value.update(shipping=deliveries,shipping_orders=rows,shipping_coverage={'status':'available'})
    return value

class TaxonomyTest(unittest.TestCase):
    def test_each_complete_order_has_one_priority_category(self):
        cases=[(('Coins','Players','SBC','Packs','Boosting'),'Players'),
               (('Coins','SBC','Packs'),'SBC'),(('Coins','Packs'),'Packs'),
               (('Coins','Boosting'),'Other'),(('Coins',),'Coins')]
        for kinds,expected in cases:
            with self.subTest(kinds=kinds):self.assertEqual(classify(markup(*kinds), native(kinds), CFG['_category_paths'], True)['category'],expected)

    def test_unknown_item_or_truncated_markup_cannot_be_coins(self):
        for content in (markup('Coins','Mystery'), 'Coins', '<span class="item">Coins'):
            self.assertEqual(classify(content)['category'],'unknown')

    def test_same_number_different_sites_stays_two_orders(self):
        self.assertEqual(len(deduplicate([order(1),order(1,site=141)])),2)

class FinancialTest(unittest.TestCase):
    def view(self,value,**q):return aggregate(value,{**Q,**q},CFG)['fc_dashboard']

    def test_current_order_form_reconciles_only_unrestricted_shipping(self):
        period = {'start':'2026-11-16 00:00', 'end':'2026-11-17 00:00'}
        fields = dict(genre='1', gid='1322', aid='0', cid='-1', status='-1', op_id='0',
                      show_ccy='-1', keyword='', sn='', wid='', start='2026-11-16 00:00',
                      end='2026-11-16 23:59', **{'source[]':''})
        inputs = ''.join(f'<input name="{name}" value="{value}">' for name, value in fields.items())
        row = ship(1, '108169.60', '70774.41', at='2026-11-16 15:00:00')
        native = ('<table><thead><tr><th>游戏</th><th>￥销售总额</th><th>￥采购总额</th><th>利润率</th>'
                  '<th>订单总数</th><th>交易总数</th></tr></thead><tbody><tr>'
                  '<td>1322 | FC 27</td><td>108,169.60</td><td>70,774.41</td><td>34.57%</td>'
                  '<td>1</td><td>1</td></tr></tbody></table>')
        for selected, reconciled in (('', True), ('selected', False)):
            with self.subTest(selected=bool(selected)):
                form = (f'<form action="/stats/admin_index/delivery.html">{inputs}'
                        f'<select name="ship_source[]" multiple><option value="0" {selected}>未标/普通</option>'
                        '</select></form>')
                session = SimpleNamespace(get_order=Mock(return_value=(200, form + native)))
                with patch.dict(sys.modules, channel_cost_source=SimpleNamespace(collect=lambda *a, **k:[row])), \
                     patch.object(sys, 'path', list(sys.path)):
                    coverage = collect_shipping(session, period)['coverage']
                sent = session.get_order.call_args.kwargs
                self.assertNotIn('is_stock', sent)
                self.assertEqual((sent['ship_source[]'], sent['wid']), ('', ''))
                self.assertEqual(coverage['native_summary_reconciled'], reconciled)
                if not reconciled:
                    self.assertEqual(coverage['reconciliation_reason'], 'native_summary_filter_mismatch:ship_source[]')

    def test_native_minute_time_echo_does_not_relax_other_filters_or_money(self):
        self.assertTrue(filter_echo_matches('start','2026-11-05 00:00','2026-11-05 00:00:00'))
        self.assertTrue(filter_echo_matches('end','2026-11-05 23:59','2026-11-05 23:59:59'))
        self.assertFalse(filter_echo_matches('end','2026-11-05 23:58','2026-11-05 23:59:59'))
        self.assertFalse(filter_echo_matches('gid','132','1322'))
        self.assertFalse(filter_echo_matches('end','2026-11-05','2026-11-05 23:59:59'))
        self.assertFalse(filter_echo_matches('end','2026-11-05 23:59','2026-11-05 23:59:99'))
        # A server that actually loses boundary-second rows still cannot reconcile.
        self.assertFalse(reconcile_shipping([ship(1,'100.01','80')],'100','80')['native_summary_reconciled'])

    def test_split_delivery_dedup_and_weighted_margin(self):
        rows=[order(1,('Coins','SBC')),order(2,('Coins',))]
        shipments=[ship(1),ship(2,'900','450'),ship(3,'1000','900','TEST2')]
        value=self.view(dataset(rows,shipments+[copy.deepcopy(shipments[0])]))
        self.assertEqual(value['totals']['shipping_sales_cny'],2000)
        self.assertEqual(value['totals']['gross_profit_cny'],570)
        self.assertEqual(value['totals']['gross_margin_pct'],28.5)
        self.assertEqual(value['coverage']['duplicate_shipping_rows'],1)
        self.assertEqual(sum(r['orders'] for r in value['categories']),2)
        self.assertEqual(next(r for r in value['categories'] if r['key']=='SBC')['shipping_sales_cny'],1000)

    def test_missing_cost_unjoined_or_source_failure_is_unknown(self):
        for delivery in (ship(1,cost='-'),ship(1,sn='NO-MEMBERSHIP')):
            self.assertIsNone(self.view(dataset([order(1)],[delivery]))['totals']['gross_profit_cny'])
        value=dataset([order(1)],[]);value['shipping_coverage']['status']='unavailable'
        self.assertIsNone(self.view(value)['totals']['shipping_sales_cny'])

    def test_unfiltered_native_matched_cohort_keeps_unjoined_money_without_allocating_categories(self):
        value=dataset([order(1)],[ship(1),ship(2,'200','150',sn='UNJOINED')])
        value['shipping_coverage'].update(status='partial',membership_failures=1,
            native_summary_reconciled=True,reconciliation_status='matched')
        result=self.view(value)
        self.assertEqual(result['coverage']['unmatched_shipping_rows'],1)
        self.assertEqual(result['coverage']['financial_basis'],'native_matched_raw_delivery_cohort')
        self.assertEqual(result['totals']['shipping_sales_cny'],300)
        self.assertEqual(result['totals']['gross_profit_cny'],70)
        self.assertAlmostEqual(result['totals']['gross_margin_pct'],70/300*100)
        self.assertEqual(sum(r['shipping_sales_cny'] for r in result['trend']),300)
        self.assertTrue(all(r['shipping_sales_cny'] is None for r in result['categories']))
        for filters in ({'product':'Players'},{'platform':'PC'},{'customer':'new'},{'site_group':'satellite'}):
            with self.subTest(filters=filters):
                self.assertIsNone(self.view(value,**filters)['totals']['gross_profit_cny'])

    def test_unfiltered_main_site_uses_exact_raw_source_subset(self):
        value=dataset([],[ship(1),ship(2,'200','150',source='www.test.com',sn='UNJOINED')])
        value['shipping_coverage'].update(native_summary_reconciled=True,reconciliation_status='matched')
        result=self.view(value,site_group='main')
        self.assertEqual(result['totals']['shipping_sales_cny'],100)
        self.assertEqual(result['totals']['gross_profit_cny'],20)

    def test_shipping_membership_does_not_require_payment_in_period(self):
        old=order(1,paytime='2026-10-01 12:00:00')
        value=dataset([], [ship(1)]);value['shipping_orders']=[old]
        result=self.view(value)
        self.assertEqual(result['totals']['orders'],0)
        self.assertEqual(result['totals']['gross_profit_cny'],20)

    def test_filters_consistent_for_financial_trend_consumption_and_export(self):
        value=dataset([order(1,('Coins','Players')),order(2)], [ship(1),ship(2,sn='TEST2')])
        result=aggregate(value,{**Q,'product':'Players','platform':'PC','grain':'hour','format':'csv'},CFG)
        self.assertEqual(result['totals']['orders'],1)
        self.assertEqual(result['fc_dashboard']['totals']['shipping_sales_cny'],100)
        self.assertEqual([r['id'] for r in result['orders']],['TEST1'])
        self.assertEqual(sum(r['orders'] for r in result['fc_dashboard']['trend']),1)
        self.assertEqual(sum(r['shipping_sales_cny'] for r in result['fc_dashboard']['trend']),100)
        self.assertEqual(len(result['fc_dashboard']['trend']),24)

    def test_unverified_customer_flag_does_not_invent_customer_ratios(self):
        value=aggregate(dataset([order(1)],[]),Q,{**CFG,'trust_customer_flag':False})['fc_dashboard']
        self.assertEqual(value['totals']['paying_customers'],1)
        self.assertIsNone(value['totals']['new_customers'])
        self.assertIsNone(value['totals']['repeat_rate_pct'])

    def test_zero_source_deliveries_has_no_margin_denominator(self):
        value=self.view(dataset([order(1)],[]))
        self.assertEqual(value['totals']['gross_profit_cny'],0)
        self.assertIsNone(value['totals']['gross_margin_pct'])

    def test_native_summary_reconciliation_and_mismatch_withhold_confirmed_money(self):
        rows=[ship(1,'100.01','70'),ship(2,'200.02','140')]
        matched=reconcile_shipping(rows,'300.03','210','2')
        self.assertTrue(matched['native_summary_reconciled'])
        json.dumps(matched)
        proof=reconcile_shipping(rows,'300.04','210','2')
        self.assertEqual(proof['reconciliation_status'],'mismatch')
        value=dataset([order(1)],rows);value['shipping_coverage'].update(proof)
        result=self.view(value)
        self.assertIsNone(result['totals']['gross_profit_cny'])
        self.assertEqual(result['totals']['known_shipping_sales_cny'],300.03)

    def test_conflicting_delivery_removed_and_cross_site_id_kept(self):
        deliveries=[ship(1),ship(1,'999'),ship(1,sn='TEST2',source='www.test.com')]
        result=self.view(dataset([order(1),order(2,site=141)],deliveries))
        self.assertEqual(result['coverage']['conflicting_shipping_rows'],1)
        self.assertEqual(result['totals']['known_shipping_sales_cny'],100)
        self.assertIsNone(result['totals']['gross_profit_cny'])

    def test_incomplete_payment_coverage_does_not_become_zero(self):
        value=dataset([],[]);value['coverage'].update(paid_complete=False,missing_days=['2026-10-11'])
        result=self.view(value)
        self.assertIsNone(result['totals']['orders'])
        self.assertIsNone(result['totals']['revenue_usd'])
        self.assertEqual(result['totals']['known_orders'],0)

    def test_category_filter_cannot_hide_unknown_orders_or_shipments_as_zero(self):
        row=order(1);row.update(category='unknown',category_status='unknown')
        result=aggregate(dataset([row,order(2,('Players',))],[ship(1)]),{**Q,'product':'Players'},CFG)
        dashboard=result['fc_dashboard']
        self.assertEqual(dashboard['coverage']['unknown_category_orders'],1)
        self.assertEqual(dashboard['coverage']['classification_status'],'partial')
        for key in ('orders','revenue_usd','shipping_sales_cny','gross_profit_cny'):
            self.assertIsNone(dashboard['totals'][key])
        self.assertIsNone(result['totals']['orders'])
        self.assertEqual(result['totals']['known_orders'],1)
        self.assertEqual(result['dimensions']['platform'][0]['known_orders'],1)
        self.assertIsNone(dashboard['trend'][0]['orders'])

    def test_unknown_platform_cannot_be_filtered_away_as_complete_zero(self):
        row=order(1);row.update(platform='unknown',platform_status='multiple')
        result=aggregate(dataset([row],[ship(1)]),{**Q,'platform':'PS'},CFG)
        self.assertIsNone(result['totals']['orders'])
        self.assertIsNone(result['fc_dashboard']['totals']['gross_profit_cny'])
        self.assertEqual(result['fc_dashboard']['coverage']['unknown_platform_orders'],1)

    def test_unpriced_order_keeps_known_subtotal_without_claiming_full_revenue(self):
        one,two=order(1),order(2);two['amount_cents']=None
        result=aggregate(dataset([one,two],[]),Q,CFG)
        self.assertIsNone(result['totals']['revenue_usd'])
        self.assertEqual(result['totals']['known_revenue_usd'],20)
        self.assertIsNone(result['dimensions']['platform'][0]['revenue_usd'])

    def test_same_number_two_sites_keeps_independent_waiting_hours(self):
        one=order(1,paytime='2026-10-11 00:00:00')
        two=order(1,site=141,paytime='2026-10-12 23:00:00')
        value=dataset([],[]);value['backlog']=[one,two];value['coverage']['backlog_status']='available'
        result=aggregate(value,{**Q,'pool':'current'},CFG,datetime.fromisoformat('2026-10-13T00:00:00+08:00'))
        self.assertEqual(result['slow_orders'],1)

    def test_cross_day_exact_hour_window_applies_to_every_view(self):
        params={k:[v] for k,v in dict(mode='fc-detail',profile='FC27',start='2026-10-11 13:00',end='2026-10-12 12:00',grain='hour').items()}
        q=query(params,datetime(2026,10,13,tzinfo=timezone.utc))
        value=dataset([order(1),order(2,paytime='2026-10-12 12:30:00')],
                      [ship(1,at='2026-10-11 12:59:59'),ship(2,sn='TEST2',at='2026-10-12 12:30:00')])
        result=aggregate(value,q,CFG)
        self.assertEqual(result['totals']['orders'],1)
        self.assertEqual(result['fc_dashboard']['totals']['shipping_rows'],1)
        self.assertEqual(len(result['fc_dashboard']['trend']),24)
        self.assertIn('2026-10-12 12:00',export_csv(result['fc_dashboard']))

class NativeMembershipTest(unittest.TestCase):
    def fixtures(self):
        rows=[raw(1,content=markup('Coins','Players'))]
        products=[dict(pid='1',gid=1327,cid='1',goods={'id':1,'cid':1}),
                  dict(pid='2',gid=1327,cid='0',goods={'id':2,'cid':9627})]
        def read(path):
            if 'categorySelect' in path:return 200,json.dumps({'code':1,'data':{'list':[{'id':1},{'id':2,'children':[{'id':9627}]}]}})
            return 200,json.dumps({'code':1,'data':{'list':products,'total':2}})
        return rows, products, read

    def test_native_pid_join_enumerates_all_goods_before_priority(self):
        rows,products,read=self.fixtures();calls=[]
        def pages(filters,name):calls.append(filters);return rows
        paths,proof=native_membership(read,pages,rows,{'start':'2026-10-11 00:00','end':'2026-10-12 00:00'},CFG)
        self.assertEqual(len(calls),2)
        self.assertEqual(normalize(rows[0],{**CFG,'_category_paths':paths},{266})['category'],'Players')
        self.assertEqual(proof['unmatched_orders'],0)

    def test_missing_native_member_is_unknown_even_with_recognizable_names(self):
        rows,products,read=self.fixtures()
        def pages(filters,name):return rows if name.endswith('-1') else []
        paths,proof=native_membership(read,pages,rows,{'start':'2026-10-11 00:00','end':'2026-10-12 00:00'},CFG)
        self.assertEqual(proof['unmatched_orders'],1)
        self.assertEqual(normalize(rows[0],{**CFG,'_category_paths':paths},{266})['category'],'unknown')

    def test_pid_catalogue_relation_conflict_is_local_to_matched_orders(self):
        rows,products,read=self.fixtures();products[0]['goods']['id']=99
        rows.append(raw(2,content=markup('Players')))
        paths,proof=native_membership(read,lambda _,name:rows[:1] if name.endswith('-1') else rows,
                                     rows,{'start':'2026-10-11 00:00','end':'2026-10-12 00:00'},CFG)
        categories=[normalize(row,{**CFG,'_category_paths':paths},{266})['category'] for row in rows]
        self.assertEqual(categories,['unknown','Players'])
        self.assertEqual((proof['status'],proof['invalid_native_products'],proof['unmatched_orders']),('partial',1,1))

    def test_incomplete_pid_scan_preserves_only_whole_order_matches(self):
        rows,_,read=self.fixtures()
        rows.append(raw(2,content=markup('Coins')))
        for timeout in (False,True):
            def pages(_,name):
                if name.endswith('-2'): raise TimeoutError()
                return rows
            budget=2 if timeout else 1
            paths,proof=native_membership(read,pages,rows,{'start':'2026-10-11 00:00','end':'2026-10-12 00:00'},
                                         {**CFG,'native_product_budget':budget})
            self.assertEqual([normalize(row,{**CFG,'_category_paths':paths},{266})['category']
                              for row in rows],['unknown','Coins'])
            self.assertEqual((proof['status'],proof['scanned_native_products']),('partial',1))

class ReaderWiringTest(unittest.TestCase):
    def test_native_source_denial_stops_the_collection(self):
        def request(path):
            if 'siteList' in path:return 200,json.dumps({'code':1,'data':{'list':[{'id':266}]}})
            return 403,'{}'
        with self.assertRaises(PermissionError):
            collect(request,{'period':{'start':'2026-10-11 00:00','end':'2026-10-12 00:00'}},CFG)

    def test_denied_cache_is_withheld_but_bounded_retry_can_recover(self):
        class Pool:
            def submit(self,*args):self.args=args
        with tempfile.TemporaryDirectory() as root:
            pool=Pool();service=FCDetails(pool,root,config=CFG)
            params={k:[v] for k,v in dict(mode='fc-detail',profile='FC27',start='2026-10-11',end='2026-10-11').items()}
            status,_=service.get(params);self.assertEqual(status,202)
            key=next(iter(service.jobs))
            atomic(Path(root)/(key+'.json'),dataset([order(1)],[]))
            service.jobs[key]={'state':'failed','error':'fc_source_denied','at':time.monotonic()}
            self.assertEqual(service.get(params)[0],403)
            service.jobs[key]['at']-=61
            self.assertEqual(service.get(params)[0],202)
            self.assertEqual(service.jobs[key]['state'],'pending')
            self.assertEqual(service.get(params)[0],202)
            self.assertIn(key,service.denied)

    def test_native_range_above_28_days_is_requested_once_and_shipping_wired(self):
        periods=[]
        def request(path):
            if 'siteList' in path:return 200,json.dumps({'code':1,'data':{'list':[{'id':266}]}})
            if 'paytime' in path:periods.append(path)
            return 200,json.dumps({'code':1,'data':{'total':0,'list':[]}})
        result=collect(request,{'period':{'start':'2026-09-01 00:00','end':'2026-11-01 00:00'}},CFG,shipping_reader=lambda p:[])
        self.assertEqual(len(periods),1)
        self.assertEqual(result['shipping_coverage']['game_id'],1322)
        self.assertEqual(result['shipping_coverage']['status'],'available')

    def test_hour_query_and_new_categories(self):
        params={k:[v] for k,v in dict(mode='fc-detail',profile='FC27',start='2026-10-11',end='2026-10-11',grain='hour',product='Players').items()}
        self.assertEqual(query(params,datetime(2026,10,12,tzinfo=timezone.utc))['grain'],'hour')

if __name__=='__main__':unittest.main()
