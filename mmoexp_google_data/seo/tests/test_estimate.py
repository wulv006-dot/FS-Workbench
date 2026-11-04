import unittest
import tempfile
from pathlib import Path
from mmoexp_google_data.seo import estimates, admin_summary


class Estimate(unittest.TestCase):
    def test_directly_uses_admin_existing_price_without_recomputing(self):
        result=estimates.calculate(dict(purchase_events='4'),dict(admin_customer_price_usd='7.25',paid_orders=1,paid_revenue_usd='1000'))
        self.assertEqual(result['revenue_usd'],'29.00')
        self.assertEqual(result['status'],'estimated')
        self.assertEqual(result['price_field'],'customer_price')

    def test_missing_stays_missing_and_native_zero_stays_zero(self):
        self.assertIsNone(estimates.calculate(dict(purchase_events=None),dict(admin_customer_price_usd='7'))['revenue_usd'])
        self.assertIsNone(estimates.calculate(dict(purchase_events='4'),dict(admin_customer_price_usd=None))['revenue_usd'])
        self.assertEqual(estimates.calculate(dict(purchase_events='0'),dict(admin_customer_price_usd='7'))['revenue_usd'],'0.00')

    def test_money_is_rounded_only_at_final_result(self):
        self.assertEqual(estimates.calculate(dict(purchase_events='3'),dict(admin_customer_price_usd='1.235'))['revenue_usd'],'3.71')

    def test_summary_uses_existing_admin_metric_and_scope(self):
        calls=[]
        def read(scope,day):
            calls.append((scope,day))
            return dict(status='available',normalisedScope='main-website',currency='USD',period=dict(start=day+' 00:00',end=day+' 23:59'),filters=dict(site=266,game='1327',pay_status=1),metrics={
                'orders':dict(value=291,status='available'), 'revenueUsd':dict(value=16620.53,status='available'),
                'averageCustomerUsd':dict(value=58.73,status='available',field='customer_price')})
        result=next(admin_summary.AdminSummarySource(read).pages('FC27','2026-11-04'))
        self.assertEqual(result['rows'][0]['metrics']['admin_customer_price_usd'],'58.73')
        self.assertEqual(calls,[('FC27','2026-11-04')])

    def test_four_games_estimates_are_computed_at_publication_and_frozen(self):
        from mmoexp_google_data.seo import store,snapshot,contracts
        import datetime as dt
        with tempfile.TemporaryDirectory() as tmp:
            work=store.Store(Path(tmp))
            context=contracts.make_daily_context(dt.datetime(2026,11,4,19,20,tzinfo=dt.timezone.utc))
            for scope in contracts.GAMES:
                for source,metrics in [('ga4',dict(sessions='10',engagedSessions='4',ecommercePurchases='3')),('admin',dict(paid_orders='7',paid_revenue_usd='800',admin_customer_price_usd='1.235'))]:
                    work.ingest_page(source,scope,context.report_date,dict(rows=[dict(key=context.report_date,metrics=metrics)],next_cursor=None,source_timezone='Asia/Shanghai',status='available',quality={}),context.now.isoformat())
            candidate,meta=snapshot.build(work,context,source_names=['ga4','admin'])
            snapshot.publish_once(work.root,candidate,meta)
            for scope in contracts.GAMES:
                row=snapshot.read(work.root,meta['snapshot_id'],'summary',scope)['rows'][0]
                self.assertEqual(row['estimate']['revenue_usd'],'3.71')
                self.assertEqual(row['metrics']['admin']['admin_customer_price_usd'],'1.235')

    def test_summary_rejects_all_site_or_wrong_game(self):
        def read(scope,day):
            return dict(status='available',normalisedScope='all-sites',currency='USD',filters=dict(site='',game='1327',pay_status=1))
        with self.assertRaises(ValueError):next(admin_summary.AdminSummarySource(read).pages('D4','2026-11-04'))


if __name__=='__main__':unittest.main()
