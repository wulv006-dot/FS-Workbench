import copy
import unittest
from datetime import datetime, timezone, timedelta
from campaign_backend.discount_revenue import BINDINGS, query_window, summarize, read_revenue
from campaign_backend.core import ContractError
from bridge import handle


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
        for changes in [dict(discount_code='LOH8'),dict(site_id=0),dict(gid=456),dict(pay_status=True),dict(pay_status=3),dict(amount_usd_format='?'),dict(pay_money_format2=['EUR','156.91']),dict(paytime='2026-10-31 08:00:00')]:
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


if __name__=='__main__':unittest.main()
