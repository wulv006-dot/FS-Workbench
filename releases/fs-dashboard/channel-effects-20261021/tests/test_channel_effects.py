import json
import io
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from channel_effects import Attribution, ChannelService, TZ, metrics, money, normalize, parse_query, view, accounting_row
from channel_source import pages, windows, apply_customer_types, customer_types, apply_cost_overrides
from channel_cost_source import delivery_timestamp


def order(sn='A', **changes):
    return dict(dict(id=sn, site_id=266, order_no=sn, gid=1, game_format='Game A', amount_usd_format='$ 10.00',
                paytime='2026-10-20 12:00:00', status_format='已完成', pay_status=1, discount_code='Alpha',
                recommend_uid=0, country_code='US', paytype_display='PayPal', isNew=1), **changes)


class Effects(unittest.TestCase):
    def setUp(self):
        self.mapping = {'entries':[{'code':'Alpha','channel':'KOL'}, {'code':'beta','channel':'SEO'}]}
        self.config = [dict(code='ALPHA', site_id='266', gid='1', uid=42, admins={'nickname':'运营甲'}),
                       dict(code='beta', site_id='266', gid='1', uid=43, admins={})]
        self.directory = {'by_code':{'ALPHA':{'uid':42,'name':'推广甲'}}, 'by_uid':{'42':{'name':'推广甲'}}}
        self.period = {'start':'2026-10-20','end':'2026-10-20'}

    def rows(self):
        orders = [order(), order('B', **{'discount_code':'', 'recommend_uid':42, 'amount_usd_format':'$ 20'}),
                  order('C', **{'discount_code':'', 'amount_usd_format':'$ 30'}),
                  order('D', **{'discount_code':'beta', 'amount_usd_format':'$ 40'})]
        deliveries = [dict(delivery_id='1', source='www.mmoexp.com', genre='订单发货', sn='A', sale_total='¥ 70', cost_total='¥ 35'),
                      dict(delivery_id='2', source='www.mmoexp.com', genre=1, sn='D', sale_total='280', cost_total='252'),
                      dict(delivery_id='3', source='eldorado.gg', genre=1, sn='B', sale_total='100', cost_total='0')]
        logs = [dict(id=1, site_id=266, order_no='A', coupon_id=7, title='券', use_time='2026-10-20 11:59:59', memberCoupon={'grant_batch_no':'one'}),
                dict(id=2, site_id=266, order_no='A', coupon_id=8, title='另一券', use_time='2026-10-20 11:59:59', memberCoupon={'grant_batch_no':'two'})]
        return normalize(orders, self.config, logs, [], deliveries, self.directory, self.mapping)

    def data(self):
        return dict(period=self.period, generatedAt=datetime.now(TZ).isoformat(), orders=self.rows(),
                    sources={'orders':{'status':'complete'},'coupons':{'status':'complete'}}, mapping={})

    def test_uncompleted_and_fraud_orders_do_not_have_cost_or_profit(self):
        data=self.data();data['orders'][0]['status']='问题订单';data['orders'][1]['status']='验证·未通过'
        result=view(data,{});rows={r['orderNo']:r for r in result['orders']}
        self.assertEqual(result['summary']['completedOrders'],1)
        self.assertEqual(result['summary']['pendingOrders'],2)
        self.assertEqual(result['summary']['fraudOrders'],1)
        self.assertEqual(result['summary']['missingCostOrders'],0)
        self.assertIsNone(rows['A']['costCny']);self.assertIsNone(rows['A']['profitCny'])
        self.assertEqual(rows['B']['costStatus'],'欺诈单：待退款/申诉')
        self.assertEqual(data['orders'][0]['costCny'],35)  # Original source evidence stays intact.

    def test_confirmed_historical_zero_cost_order_has_full_profit(self):
        row=self.rows()[0];row.update(saleCny=None,costCny=None,profitCny=None,deliveryRows=0)
        rule={'A':dict(gid='1',salesUsd='10',saleCny='67.25',costCny='0',productTitle='fictional historical coupon')}
        result=accounting_row(row,rule)
        self.assertEqual((result['saleCny'],result['costCny'],result['profitCny']),(67.25,0,67.25))
        self.assertEqual(metrics([result])['margin'],1)
        self.assertEqual(metrics([result])['zeroCostOrders'],1)
        other=dict(row,orderNo='other');self.assertIsNone(accounting_row(other,rule)['costCny'])
        changed=dict(row,salesUsd=11);self.assertIsNone(accounting_row(changed,rule)['costCny'])
        refunded=dict(row,refunded=True);self.assertIsNone(accounting_row(refunded,rule)['profitCny'])

    def test_scm_completed_cost_remains_unknown(self):
        for game in ('NBA2K27','ARC Raiders'):
            row=dict(self.rows()[0],game=game,costCny=None,saleCny=None,profitCny=None)
            result=accounting_row(row,{})
            self.assertIn('SCM',result['costStatus'])
            self.assertIsNone(metrics([result])['profitCny'])

    def test_invalid_nonzero_override_is_not_applied(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'accounting-overrides.json';path.write_text(json.dumps(dict(contract='channel-zero-cost-v1',orders={'A':dict(gid='1',salesUsd='10',saleCny='67',costCny='5',productTitle='fictional')})));path.chmod(0o600)
            with patch('channel_source.ROOT',Path(folder)):data=apply_cost_overrides(self.data())
        self.assertEqual(data['costOverrides'],{})
        self.assertEqual(data['sources']['accounting']['status'],'unavailable')

    def test_customer_uses_order_time_es_flag_and_corrects_old_cache(self):
        import hashlib
        data = self.data()
        for row in data['orders']: row['customerType'] = '老客'
        records = [dict(订单号=hashlib.sha256(sn.encode()).hexdigest(), 付款时间='2026/10/20 12:00:00', 是否新客户=flag) for sn, flag in [('A','是'),('B','否')]]
        dataset = dict(rows=records, parse_failures=0, failed_files=0, declared_files=1, hashes=['a'*64], captured_at='2026-10-21T00:00:00Z')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'manifest.json').write_text(json.dumps(dict(query=self.period,captured_at=dataset['captured_at'])))
            customer_types.cache_clear()
            with patch('channel_source.ES_ARCHIVE',root), patch.dict(sys.modules,{'es_order_structure':SimpleNamespace(archived_dataset=lambda *a,**kw:dataset)}):
                apply_customer_types(data)
        self.assertEqual([r['customerType'] for r in data['orders']],['新客','老客','新老客未提供','新老客未提供'])
        self.assertEqual(data['sources']['customer']['matchedOrders'],2)
        # Admin flags and UID=0 never override the ES order flag.
        self.assertTrue(all(r['customerType']=='新老客未提供' for r in self.rows()))

    def test_customer_conflicting_es_flags_are_not_assigned(self):
        import hashlib
        digest=hashlib.sha256(b'A').hexdigest()
        records=[{'订单号':digest,'付款时间':'2026/10/20 12:00:00','是否新客户':v} for v in ('是','否')]
        dataset=dict(rows=records,parse_failures=0,failed_files=0,declared_files=1,hashes=['b'*64],captured_at='2026-10-21T00:00:00Z')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'manifest.json').write_text(json.dumps(dict(query=self.period)))
            customer_types.cache_clear()
            with patch('channel_source.ES_ARCHIVE',root), patch.dict(sys.modules,{'es_order_structure':SimpleNamespace(archived_dataset=lambda *a,**kw:dataset)}):
                data=apply_customer_types(self.data())
        self.assertEqual(data['orders'][0]['customerType'],'待核：新老客冲突')

    def test_missing_es_source_keeps_unknown_and_uses_existing_export_entry(self):
        from unittest.mock import Mock
        export=Mock(return_value={'status':'unavailable','reason':'existing_attempt_unknown'})
        with tempfile.TemporaryDirectory() as folder:
            customer_types.cache_clear()
            with patch('channel_source.ES_ARCHIVE',Path(folder)), patch.dict(sys.modules,{'es_order_structure':SimpleNamespace(server_bundle=export)}):
                data=apply_customer_types(self.data(),request=True)
        self.assertTrue(all(r['customerType']=='新老客未提供' for r in data['orders']))
        self.assertEqual(export.call_count,1)

    def test_casefold_preserves_spelling_and_directory_precedence(self):
        a = Attribution(self.mapping, self.config, self.directory)
        row = a.resolve(order(**{'discount_code':'aLpHa'}))
        self.assertEqual((row['code'],row['codeKey'],row['project'],row['promoter']), ('aLpHa','alpha','KOL','推广甲'))

    def test_mapping_collision_stays_pending_and_not_natural(self):
        self.mapping['entries'].append(dict(code='ALPHA', channel='SEO'))
        row = Attribution(self.mapping, self.config, self.directory).resolve(order())
        self.assertTrue(row['conflict']); self.assertEqual(row['project'], '待核：映射冲突')

    def test_config_game_scope_and_conflict(self):
        self.config += [dict(code='Alpha', site_id='266', gid='2', uid=99, admins={})]
        a = Attribution(self.mapping, self.config, {})
        self.assertEqual(a.resolve(order())['promoterUid'], '42')
        self.config += [dict(code='Alpha', site_id='266', gid='1', uid=99, admins={})]
        self.assertTrue(Attribution(self.mapping, self.config, {}).resolve(order())['conflict'])

    def test_member_uid_is_not_labeled_as_the_code_admin(self):
        self.config.append(dict(code='Alpha', site_id='266', gid='1', uid=42, admins={'nickname':'另一操作员'}))
        row = Attribution(self.mapping, self.config, {}).resolve(order())
        self.assertEqual(row['promoterUid'], '42')
        self.assertEqual(row['promoter'], '推广人 42')
        self.assertFalse(row['conflict'])

    def test_referrer_without_code_not_counted_as_coded(self):
        rows = self.rows()
        self.assertEqual(rows[1]['project'], 'KOL')
        self.assertEqual(rows[1]['attribution'], '推荐人无码')
        self.assertEqual(metrics(rows[:2])['codedOrders'], 1)
        self.assertEqual(rows[2]['project'], '无推广归属')

    def test_ambiguous_referrer_channel_not_guessed(self):
        self.mapping['entries'].append(dict(code='other', channel='SEO'))
        self.config.append(dict(code='other', site_id='266', gid='', uid=42, admins={}))
        result = Attribution(self.mapping, self.config, self.directory).resolve(order(**{'discount_code':'','recommend_uid':42}))
        self.assertEqual(result['project'], '推荐人渠道待核')

    def test_missing_cost_null_same_currency_weighted_margin(self):
        result = metrics(self.rows())
        self.assertEqual(result['costCny'], 287)
        self.assertEqual(result['profitCny'], 63)
        self.assertAlmostEqual(result['margin'], .18)
        self.assertEqual(result['coveredOrders'], 2)
        self.assertIsNone(self.rows()[1]['costCny'])
        self.assertIsNone(metrics(self.rows()[1:3])['profitCny'])
        self.assertIsNone(metrics([])['margin'])
        self.assertIsNone(money('bad')); self.assertIsNone(money('NaN'))

    def test_default_excludes_unattributed_but_left_keeps_control(self):
        result = view(self.data(), {})
        self.assertEqual(result['summary']['orders'], 3)
        self.assertEqual(result['summary']['salesUsd'], 70)
        self.assertEqual(result['denominator']['orders'], 4)
        self.assertIn('无推广归属', [r['key'] for r in result['projects']])
        self.assertEqual(result['summary']['shareSite'], .5)

    def test_project_and_code_do_not_shrink_denominators_or_left(self):
        result = view(self.data(), {'project':'KOL','code':'alpha'})
        self.assertEqual(result['summary']['orders'], 1)
        self.assertEqual(result['summary']['shareAllCodes'], .5)
        self.assertEqual(result['summary']['shareSite'], .25)
        self.assertEqual(len(result['projects']), 3)
        self.assertEqual(len(result['codes']), 2)

    def test_coupon_overlap_is_deduplicated_and_batches_independent(self):
        result = view(self.data(), {'mode':'coupon'})
        self.assertEqual(result['summary']['orders'], 1)
        self.assertEqual(result['summary']['overlapOrders'], 1)
        self.assertEqual(len(result['projects']), 2)
        self.assertEqual(len(result['codes']), 2)
        self.assertEqual(view(self.data(), {'mode':'coupon','project':'7'})['codes'][0]['key'], 'one')

    def test_refund_and_game_scope(self):
        d = self.data(); d['orders'][0]['refunded'] = True
        self.assertEqual(view(d, {})['summary']['orders'], 2)
        self.assertEqual(view(d, {'status':'refund'})['summary']['orders'], 1)
        self.assertEqual(view(d, {'gid':'999'})['summary']['orders'], 0)

    def test_unused_mapped_codes_remain_zero_with_game_scope(self):
        self.mapping['entries'].append(dict(code='unused', channel='KOL'))
        self.config.append(dict(code='unused', site_id='266', gid='2', uid=42, admins={}))
        d = self.data(); d['codeCatalog'] = Attribution(self.mapping, self.config, self.directory).catalog()
        zero = next(r for r in view(d, {})['codes'] if r['key'] == 'unused')
        self.assertEqual((zero['orders'],zero['salesUsd']), (0,0))
        self.assertNotIn('unused', {r['key'] for r in view(d, {'gid':'1'})['codes']})

    def test_no_pii_projection_and_invalid_identity_fails(self):
        raw = order(**{'email':'private@example.test','ip':'private','note':'secret'})
        row = normalize([raw], [], [], [], [], {}, self.mapping)[0]
        self.assertFalse({'email','ip','note','member','txn_id'} & row.keys())
        with self.assertRaises(ValueError): normalize([raw,raw], [], [], [], [], {}, self.mapping)
        with self.assertRaises(ValueError): normalize([order(**{'site_id':999})], [], [], [], [], {}, self.mapping)

    def test_period_and_pagination_validation(self):
        q = {k:[v] for k,v in self.period.items()}
        self.assertEqual(parse_query(q)['start'], self.period['start'])
        for changes in ({'start':['2026-10-21'],'end':['2026-10-20']},{'sort':['email']},{'page':['0']},{'gid':['all']},{'start':['2026-01-01','2026-02-01']},{'extra':['x']}):
            with self.assertRaises(ValueError): parse_query(dict(q, **changes))
        self.assertEqual(len(list(windows({'start':'2026-09-01','end':'2026-10-20'}))), 2)

    def test_service_auth_before_data_or_source(self):
        with tempfile.TemporaryDirectory() as root:
            service = ChannelService(root, lambda user: user == 'admin', lambda period: self.fail('unauthorized read'))
            self.assertEqual(service.get({}, 'reader')[0], 403)
            service.pool.shutdown()

    def test_failed_capture_preserves_last_complete_file(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root)/'fixed.json'; target.write_text('last-complete')
            called = []
            def fail(period): called.append(period); raise ValueError('source failure')
            service = ChannelService(root, lambda user: True, fail)
            with patch.dict(sys.modules, {'fcntl':SimpleNamespace(flock=lambda *args: None, LOCK_EX=1, LOCK_NB=2)}):
                service.capture(self.period,'fixed',target)
            self.assertEqual(called, [self.period])
            self.assertEqual(target.read_text(), 'last-complete')
            self.assertEqual(service.jobs['fixed'], 'source_failed'); service.pool.shutdown()

    def test_orders_publish_before_costs_and_cost_failure_keeps_orders(self):
        for fail_cost in (False, True):
            with tempfile.TemporaryDirectory() as root:
                target = Path(root)/'fixed.json'
                initial = self.data()
                def enrich(data, force=False):
                    self.assertEqual(json.loads(target.read_text())['orders'], initial['orders'])
                    if fail_cost: raise ValueError('shared_order_unavailable')
                    data['sources']['cost_enriched'] = True; return data
                fake = SimpleNamespace(collect=lambda period:deepcopy(initial),enrich=enrich)
                service = ChannelService(root, lambda user: True)
                with patch.dict(sys.modules, {'fcntl':SimpleNamespace(flock=lambda *args: None, LOCK_EX=1, LOCK_NB=2),'channel_source':fake}):
                    service.capture(self.period,'fixed',target)
                self.assertEqual(service.jobs['fixed'], 'cost_failed' if fail_cost else 'available')
                self.assertEqual(json.loads(target.read_text())['orders'], initial['orders'])
                service.pool.shutdown()

    def test_recent_complete_cost_range_is_reused_without_another_order_read(self):
        import channel_source
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'order-deliveries.json'
            path.write_text(json.dumps(dict(contract='channel-order-deliveries-v1',complete=True,generatedAt=datetime.now(TZ).isoformat(),period=dict(start='2026-10-01',end=datetime.now(TZ).date().isoformat(),until='2026-10-21 19:00'),rows=[])))
            with patch.object(channel_source,'ROOT',Path(root)), patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"ready":true}')):
                data = self.data();data['sources']={'cost':{}}
                result = channel_source.enrich(data)
            self.assertIn('复用固定发货截止', result['sources']['cost']['limitation'])
            fake_session = SimpleNamespace(close=lambda:None)
            with patch.object(channel_source,'ROOT',Path(root)), patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"ready":true}')), patch.dict(sys.modules,{'fcntl':SimpleNamespace(flock=lambda *args:None,LOCK_EX=1,LOCK_NB=2),'p2pah_auth':SimpleNamespace(Session=lambda:fake_session)}), patch('channel_cost_source.collect',side_effect=ValueError('forced_order_read')):
                with self.assertRaisesRegex(ValueError,'forced_order_read'):channel_source.enrich(data,force=True)

    def test_order_unavailable_preserves_orders_and_marks_the_source(self):
        import channel_source
        data = self.data();data['sources'] = {'cost':{}}
        before = deepcopy(data['orders'])
        with patch('urllib.request.urlopen',side_effect=OSError('unavailable')):
            result = channel_source.enrich(data)
        self.assertEqual(result['orders'],before)
        self.assertEqual(result['sources']['cost']['status'],'unavailable')

    def test_long_admin_period_is_split_and_complete_before_merge(self):
        import channel_source
        requested = {'start':'2026-08-01','end':'2026-10-20'}
        segments = []
        closed = []
        session = SimpleNamespace(bind_admin_token=lambda token:None,close=lambda:closed.append(True))
        def page_rows(session,path,filters=(),limit=200):
            if path != '/admin/order.Order/index': return []
            start,end = next(value for field,operator,value in filters if field=='paytime').split(',')
            self.assertLessEqual((datetime.fromisoformat(end).date()-datetime.fromisoformat(start).date()).days,27)
            segments.append((start,end))
            return [order('SEG'+str(len(segments)), **{'paytime':start})]
        auth = SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture',''))
        with patch.dict(sys.modules,{'p2pah_auth':auth}),patch.object(channel_source,'pages',side_effect=page_rows),patch.object(channel_source,'load_costs',return_value=([],{'status':'unavailable'})):
            result = channel_source.collect(requested)
        self.assertEqual(len(segments),3)
        self.assertEqual(segments[0][0],'2026-08-01 00:00:00')
        self.assertEqual(segments[-1][1],'2026-10-20 23:59:59')
        self.assertEqual([r['orderNo'] for r in result['orders']],['SEG1','SEG2','SEG3'])
        self.assertEqual(result['sources']['orders']['rows'],3)
        self.assertEqual(closed,[True])

    def test_later_month_failure_keeps_previous_complete_capture(self):
        import channel_source
        requested={'start':'2026-08-01','end':'2026-10-20'};segments=[];closed=[]
        session=SimpleNamespace(bind_admin_token=lambda token:None,close=lambda:closed.append(True))
        def page_rows(session,path,filters=(),limit=200):
            self.assertEqual(path,'/admin/order.Order/index')
            segments.append(filters)
            if len(segments)==2:raise ValueError('admin_page_failed')
            return [order('SEG1',**{'paytime':'2026-08-01 00:00:00'})]
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture',''))
        with tempfile.TemporaryDirectory() as root:
            target=Path(root)/'previous.json';target.write_text('previous-complete')
            service=ChannelService(root,lambda user:True,channel_source.collect)
            with patch.dict(sys.modules,{'p2pah_auth':auth,'fcntl':SimpleNamespace(flock=lambda *args:None,LOCK_EX=1,LOCK_NB=2)}),patch.object(channel_source,'pages',side_effect=page_rows):
                service.capture(requested,'previous',target)
            self.assertEqual(target.read_text(),'previous-complete')
            self.assertEqual(service.jobs['previous'],'source_failed')
            service.pool.shutdown()
        self.assertEqual(len(segments),2)
        self.assertEqual(closed,[True])


class Paging(unittest.TestCase):
    def test_real_delivery_two_digit_year_is_normalized_not_ignored(self):
        self.assertEqual(delivery_timestamp('26-10-20 23:57:49'), '2026-10-20 23:57:49')
        self.assertEqual(delivery_timestamp('2026-10-20 23:57:49'), '2026-10-20 23:57:49')
        self.assertEqual(delivery_timestamp('26-10-20 22:29:23        改26-10-20 22:31:20'), '2026-10-20 22:29:23')
        with self.assertRaises(ValueError): delivery_timestamp('20/10/26')
        with self.assertRaises(ValueError): delivery_timestamp('26-10-20 22:29:23 改bad')

    def test_page_total_change_and_duplicate_are_rejected(self):
        class Session:
            def __init__(self, duplicate): self.duplicate = duplicate
            def get_admin(self, path, **query):
                n = query['page']
                return 200, {'code':1,'data':{'total':2 if self.duplicate or n == 1 else 3,'list':[{'id':1 if n == 1 or self.duplicate else 2}]}}
        for duplicate in (True, False):
            with self.assertRaises(ValueError): pages(Session(duplicate),'/test',limit=1)

    def test_empty_success_and_explicit_failure(self):
        class Session:
            def __init__(self, status): self.status = status
            def get_admin(self, path, **query): return self.status, {'code':1,'data':{'total':0,'list':[]}}
        self.assertEqual(pages(Session(200), '/test'), [])
        with self.assertRaises(ValueError): pages(Session(503), '/test')


if __name__ == '__main__': unittest.main()
