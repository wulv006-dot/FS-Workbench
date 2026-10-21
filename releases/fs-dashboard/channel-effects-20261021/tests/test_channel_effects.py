import json
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from channel_effects import Attribution, ChannelService, TZ, metrics, money, normalize, parse_query, view
from channel_source import pages, windows
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
        return dict(period=self.period, generatedAt=datetime.now(TZ).isoformat(), orders=self.rows(), sources={}, mapping={})

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


class Paging(unittest.TestCase):
    def test_real_delivery_two_digit_year_is_normalized_not_ignored(self):
        self.assertEqual(delivery_timestamp('26-10-20 23:57:49'), '2026-10-20 23:57:49')
        self.assertEqual(delivery_timestamp('2026-10-20 23:57:49'), '2026-10-20 23:57:49')
        with self.assertRaises(ValueError): delivery_timestamp('20/10/26')

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
