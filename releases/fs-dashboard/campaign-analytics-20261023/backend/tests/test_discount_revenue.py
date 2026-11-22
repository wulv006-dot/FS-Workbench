import copy
import unittest
from datetime import datetime, timezone, timedelta
from campaign_backend.discount_revenue import BINDINGS, query_window, summarize, read_revenue
from campaign_backend.core import ContractError
from bridge import handle
from campaign_backend.adapters import AdminRead


def order(**changes):
    return dict(dict(order_no='fixture-1', site_id=266, gid=891, pay_status=1,
                     paytime='2026-10-30 10:07:13', discount_code=' hwaion15 ',
                     amount_usd_format='$ 156.91', currency_code='USD', pay_money_format2=['USD', '156.91']), **changes)


class DiscountRevenueTests(unittest.TestCase):
    def setUp(self):
        self.request = dict(action='discount_revenue', site_id='266', **{'from':'2026-10-30','to':'2026-10-30'}, game='all')
        self.start, self.end, self.game = query_window(self.request)

    def summary(self, rows, game='all'):
        return summarize(rows, self.start, self.end, game)

    def test_paid_and_refunded_remain_payments_unpaid_excluded_and_no_pii(self):
        value=self.summary([order(), order(order_no='fixture-2',pay_status='2'), order(order_no='fixture-3',pay_status=0)])
        self.assertEqual(value['totals'],dict(paid_orders=2,paid_usd_minor=31382,refunded_orders=1))
        self.assertEqual(value['coverage']['excluded_unpaid'],1)
        self.assertIsNone(value['refund_amount']);self.assertIsNone(value['net_amount'])
        self.assertNotIn('fixture-1',str(value));self.assertEqual(len(value['codes']),12)

    def test_deduplicate_order_and_reject_conflicts(self):
        self.assertEqual(self.summary([order(),order()])['totals']['paid_orders'],1)
        with self.assertRaisesRegex(ContractError,'CONFLICTING_DUPLICATE_ORDER'):
            self.summary([order(),order(pay_money_format2=['USD','999'])])

    def test_scope_money_state_and_boundaries_fail_closed(self):
        for changes in [dict(discount_code='LOH8'),dict(site_id=0),dict(gid=456),dict(pay_status=True),dict(pay_status=3),dict(amount_usd_format='?'),dict(pay_money_format2=['?','156.91']),dict(paytime='2026-10-31 08:00:00')]:
            with self.subTest(changes=changes),self.assertRaises(ContractError):self.summary([order(**changes)])
        self.assertEqual(self.start.hour,8)
        self.assertEqual(self.summary([order(paytime='2026-10-30 08:00:00')])['totals']['paid_orders'],1)
        with self.assertRaises(ContractError):self.summary([order(paytime='2026-10-30 07:59:59')])

    def test_no_currency_mix_and_game_filter(self):
        rows=[order(),order(order_no='fixture-eur',currency_code='EUR',pay_money_format2=['EUR','100.01'],amount_usd_format='$ 111.11')]
        value=self.summary(rows)
        self.assertEqual(value['paid_currencies'],[dict(currency='EUR',amount='100.01'),dict(currency='USD',amount='156.91')])
        self.assertEqual(value['totals']['paid_usd_minor'],26802)
        self.assertEqual(self.summary(rows,'456')['totals']['paid_orders'],0)

    def test_original_currency_and_payment_display_currency_are_independent(self):
        rows=[order(),order(order_no='fixture-pln',currency_code='PLN',pay_money_format2=['USD','10.00'],amount_usd_format='$ 10.00')]
        value=self.summary(rows+rows)
        self.assertEqual(value['totals']['paid_orders'],2)
        self.assertEqual(value['totals']['paid_usd_minor'],16691)
        self.assertEqual(value['paid_currencies'],[dict(currency='USD',amount='166.91')])
        self.assertTrue(value['coverage']['complete'])
        converted=self.summary([order(currency_code='BRL',pay_money_format2=['USD','14.22'])])
        self.assertEqual(converted['paid_currencies'],[dict(currency='USD',amount='14.22')])
        self.assertEqual(converted['totals']['paid_usd_minor'],15691)
        with self.assertRaisesRegex(ContractError,'USD_ORDER_AMOUNT_REQUIRED'):
            self.summary([order(currency_code='PLN',amount_usd_format='?')])
        for parts in [['USD','?'],['?','10.00'],['USD'],None]:
            with self.subTest(parts=parts),self.assertRaisesRegex(ContractError,'PAID_CURRENCY_AMOUNT_REQUIRED'):
                self.summary([order(currency_code='PLN',pay_money_format2=parts)])

    def test_31_day_windows_split_and_identity_readback(self):
        class Reader:
            def __init__(self):self.calls=[]
            def pages(self,resource,filters,**kw):
                self.calls.append((resource,filters))
                return [dict(id=n,code=c,site_id=266) for n,c,g,o in BINDINGS] if resource=='discounts' else []
            def close(self):pass
        reader=Reader()
        request=dict(self.request,**{'from':'2026-10-01','to':'2026-10-31'})
        value=handle(request,reader_factory=lambda:reader)
        self.assertEqual(value['totals']['paid_orders'],0)
        calls=[filters for resource,filters in reader.calls if resource=='orders']
        self.assertEqual(len(calls),2)
        self.assertIn(('paytime','RANGE','2026-10-01 08:00:00,2026-10-29 07:59:59'),calls[0])
        self.assertIn(('paytime','RANGE','2026-10-29 08:00:00,2026-11-01 07:59:59'),calls[1])
        bad=copy.deepcopy(request);bad['codes']=['ANY']
        with self.assertRaises(ContractError):handle(bad,reader_factory=lambda:self.fail('No reads for untrusted filters'))
        with self.assertRaises(ContractError):query_window(dict(self.request,**{'to':'2026-11-31'}))

    def test_native_identity_collision_or_missing_code_blocks_report(self):
        class Reader:
            def pages(self,resource,filters,**kw):
                if resource!='discounts':raise AssertionError('Do not query orders after an identity conflict')
                return [dict(id=n,code=c,site_id=266) for n,c,g,o in BINDINGS][:-1]
        with self.assertRaisesRegex(ContractError,'ACTIVITY_CODE_IDENTITY_MISMATCH'):
            read_revenue(Reader(),self.request)
        with self.assertRaisesRegex(ContractError,'REPORT_MONEY_EXCEEDS_SAFE_INTEGER'):
            self.summary([order(amount_usd_format='$ 90071992547409.92')])

    def test_same_bound_native_id_can_be_global_without_expanding_order_site(self):
        class Reader(AdminRead):
            def __init__(self):
                self.calls=[]
                self.natives=[dict(id=n,code=c,site_id=0 if n=='6033' else 266) for n,c,g,o in BINDINGS]
            def _get(self,route,**params):
                self.calls.append((route,params))
                return dict(list=self.natives,total=len(self.natives)) if 'Discount' in route else dict(list=[],total=0)
        reader=Reader()
        self.assertEqual(read_revenue(reader,self.request)['status'],'available')
        orders=[p for route,p in reader.calls if 'Order' in route]
        self.assertEqual(orders[0]['search[0][field]'],'site_id')
        self.assertEqual(orders[0]['search[0][operator]'],'=')
        self.assertEqual(orders[0]['search[0][val]'],'266')
        for change in [dict(id='99999'),dict(site_id=999)]:
            reader=Reader();reader.natives[5].update(change)
            with self.subTest(change=change),self.assertRaisesRegex(ContractError,'UPSTREAM_SCOPE_MISMATCH'):
                read_revenue(reader,self.request)
            self.assertFalse(any('Order' in route for route,p in reader.calls))

    def test_fc_tracks_completed_orders_separately_from_payment(self):
        common = dict(gid=1327, discount_code='FCSCOUT10')
        done = order(**common, status_format='已完成')
        rows = [done, done, order(**common, order_no='refunded', pay_status=2, status_format='已完成'),
                order(**common, order_no='pending', status_format='待发货'), order(**common, order_no='unknown')]
        result = summarize(rows, self.start, self.end, self.game, 'fc27-season2')
        self.assertEqual(result['totals']['paid_orders'], 4)
        self.assertEqual(result['completed'], dict(orders=1, usd_minor=15691, unknown_orders=1))

    def test_fc_shared_code_actual_paid_orders_not_single_page_conversion(self):
        class Reader:
            def __init__(self): self.calls = []
            def pages(self, resource, filters, **kwargs):
                self.calls.append((resource, filters))
                if resource == 'discounts': return [dict(id='6049', code='FCSCOUT10', site_id=266)]
                paid = order(gid=1327, discount_code='FCSCOUT10')
                return [paid, paid, order(order_no='unpaid', gid=1327, discount_code='FCSCOUT10', pay_status=0), order(order_no='refunded', gid=1327, discount_code='FCSCOUT10', pay_status=2)]
            def close(self): pass
        reader = Reader()
        result = handle(dict(self.request, activity='fc27-season2'), reader_factory=lambda:reader)
        self.assertEqual(result['activity_id'], 'fc27-season2')
        self.assertEqual(result['attribution_level'], 'shared_activity_group')
        self.assertEqual(result['page_allocation'], 'not_available')
        self.assertEqual(result['visitor_join'], 'not_available')
        self.assertEqual(result['totals'], dict(paid_orders=2, paid_usd_minor=31382, refunded_orders=1))
        self.assertEqual([x['code'] for x in result['codes']], ['FCSCOUT10'])
        self.assertIn(('discount_code', 'IN', 'FCSCOUT10'), reader.calls[1][1])
        for changes in [dict(activity='fc27-weekly'), dict(activity='fc27-season2',game='891')]:
            with self.assertRaises(ContractError): handle(dict(self.request, **changes), reader_factory=lambda:self.fail('invalid scope must not read'))



class ProductSalesTests(unittest.TestCase):
    def rows(self):return [order(gid=1327,discount_code='FCSCOUT10'),order(order_no='refunded',gid=1327,discount_code='FCSCOUT10',pay_status=2)]
    def line(self,**changes):return dict(dict(game_id='1322',category_id='2',product_id='6530400',attribute_id='21946',title='Actual Player',quantity='1',unit='item',platform='21946'),**changes)
    def test_actual_paid_order_item_lines_group_and_refunds_without_whole_order_allocation(self):
        from campaign_backend.discount_revenue import product_sales
        calls=[]
        def read(number,**kw):calls.append(number);return [self.line(),self.line(),self.line(category_id='1',quantity='305',unit='K'),self.line(game_id='other')]
        rows=self.rows();r=product_sales(rows+[rows[0],order(pay_status=0)],read)
        self.assertEqual(len(calls),2);self.assertTrue(r['coverage']['complete']);self.assertEqual(len(r['rows']),1)
        x=r['rows'][0];self.assertEqual(x['quantity'],'4');self.assertEqual(x['paid_orders'],2);self.assertEqual(x['refunded_orders'],1);self.assertEqual(x['refunded_quantity'],'2');self.assertEqual(x['line_amounts'],[])
        self.assertNotIn('fixture-1',str(r));self.assertNotIn('paid_usd_minor',x)
    def test_missing_or_partial_lines_are_not_zero_and_expired_budget_stops_reads(self):
        from campaign_backend.discount_revenue import product_sales
        r=product_sales(self.rows());self.assertEqual(r['status'],'unavailable');self.assertIsNone(r['rows'])
        def partial(number,**kw):
            if number=='refunded':raise ContractError('ORDER_LINES_CONTRACT')
            return [self.line()]
        r=product_sales(self.rows(),partial);self.assertEqual(r['status'],'partial');self.assertEqual(r['coverage']['covered_paid_orders'],1)
        r=product_sales(self.rows(),lambda *a,**k:self.fail('expired must not read'),deadline=9,clock=lambda:10);self.assertEqual(r['reason'],'ORDER_LINES_TIME_BUDGET')
        calls=[]
        def timeout(number,**kw):calls.append(number);raise TimeoutError()
        product_sales(self.rows(),timeout);self.assertEqual(len(calls),1)
    def test_read_revenue_completes_paid_totals_even_when_order_line_source_missing(self):
        outer=self
        class Reader:
            def pages(self,resource,filters,**kw):
                return [dict(id='6049',code='FCSCOUT10',site_id=266)] if resource=='discounts' else outer.rows()
            def read_order_lines(self,number,**kw):raise ContractError('ORDER_LINE_ORDER_NOT_FOUND')
        r=read_revenue(Reader(),dict(action='discount_revenue',site_id='266',activity='fc27-season2',game='all',**{'from':'2026-10-30','to':'2026-10-30'}))
        self.assertEqual(r['status'],'available');self.assertEqual(r['totals']['paid_orders'],2);self.assertEqual(r['product_sales']['status'],'unavailable');self.assertIsNone(r['product_sales']['rows'])
    def test_product_row_byte_budget_preserves_completed_orders_and_reports_partial(self):
        from campaign_backend.discount_revenue import product_sales
        rows=[order(order_no='order-'+str(i),pay_status=1) for i in range(5)]
        def read(number,**kw):return [self.line(product_id=number+'-'+str(i),title='球'*500) for i in range(200)]
        r=product_sales(rows,read);self.assertEqual(r['status'],'partial');self.assertEqual(r['reason'],'ORDER_LINES_RESPONSE_LIMIT');self.assertLess(r['coverage']['covered_paid_orders'],5)
    def test_complete_zero_orders_zero_and_invalid_line_invalidates_whole_order(self):
        from campaign_backend.discount_revenue import product_sales
        r=product_sales([]);self.assertEqual(r['status'],'available');self.assertEqual(r['rows'],[]);self.assertTrue(r['coverage']['complete'])
        r=product_sales(self.rows()[:1],lambda *a,**k:[self.line(),self.line(quantity='?')]);self.assertEqual(r['status'],'unavailable');self.assertIsNone(r['rows']);self.assertEqual(r['coverage']['covered_paid_orders'],0)

if __name__=='__main__':unittest.main()
