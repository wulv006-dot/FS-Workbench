"""Same-snapshot paid-order hours; the selected day and financial export stay daily."""
import copy
import unittest
from test_fc_dashboard import CFG, Q, aggregate, dataset, order, ship, export_csv


class HourlyProjectionTest(unittest.TestCase):
    def view(self, value, **selection):
        return aggregate(value, {**Q, 'grain':'day', **selection}, CFG)

    def test_single_day_hours_preserve_order_membership_daily_profit_and_export(self):
        value=dataset([order(1,('Coins','Players'),paytime='2026-10-11 09:15:23'),
                       order(2,('SBC',),paytime='2026-10-11 17:45:05')],
                      [ship(1,at='2026-10-11 05:00:00')])
        before=copy.deepcopy(value)
        result=self.view(value);dashboard=result['fc_dashboard'];hours=dashboard['hourly_trend']
        self.assertEqual((result['query']['grain'],dashboard['grain']),('day','day'))
        self.assertEqual(result['snapshot_id'],value['snapshot_id'])
        self.assertEqual(len(dashboard['trend']),1)
        self.assertEqual(len(hours),24)
        self.assertEqual(sum(row['orders'] for row in hours),2)
        self.assertEqual(sum(row['revenue_usd'] for row in hours),40)
        self.assertEqual(hours[9]['orders'],1)
        self.assertEqual(next(row for row in hours[9]['categories'] if row['key']=='Players')['orders'],1)
        self.assertEqual(next(row for row in hours[17]['categories'] if row['key']=='SBC')['orders'],1)
        self.assertNotIn('gross_profit_cny',hours[9])
        self.assertEqual(dashboard['trend'][0]['gross_profit_cny'],20)
        self.assertEqual(dashboard['totals']['gross_margin_pct'],20)
        without_hours={key:row for key,row in dashboard.items() if key!='hourly_trend'}
        self.assertEqual(export_csv(dashboard),export_csv(without_hours))
        self.assertEqual(len(export_csv(dashboard).splitlines()),8)
        self.assertEqual(value,before)

    def test_hourly_projection_uses_same_category_platform_and_site_filters(self):
        rows=[order(1,('Players',),paytime='2026-10-11 09:10:00'),
              order(2,('Coins',),paytime='2026-10-11 10:10:00'),
              order(3,('Players',),site=141,paytime='2026-10-11 11:10:00'),
              order(4,('Players',),paytime='2026-10-11 12:10:00')]
        rows[-1]['platform']='PS'
        hours=self.view(dataset(rows,[]),product='Players',platform='PC',site_group='main')['fc_dashboard']['hourly_trend']
        self.assertEqual(sum(row['orders'] for row in hours),1)
        self.assertEqual(hours[9]['revenue_usd'],20)

    def test_source_cutoff_stops_hours_without_filling_future_time(self):
        value=dataset([order(1,paytime='2026-10-11 14:20:00'),
                       order(2,paytime='2026-10-11 14:50:00')],[])
        period={'start':'2026-10-11 00:00','end':'2026-10-11 14:37'}
        value['coverage']['period']=period
        hours=self.view(value,period=period)['fc_dashboard']['hourly_trend']
        self.assertEqual(len(hours),15)
        self.assertEqual(hours[-1]['date'],'2026-10-11 14:00')
        self.assertEqual(sum(row['orders'] for row in hours),1)

    def test_partial_coverage_preserves_known_events_without_inventing_empty_hours(self):
        value=dataset([order(1,paytime='2026-10-11 10:15:00')],[])
        value['coverage']['paid_complete']=False
        hours=self.view(value)['fc_dashboard']['hourly_trend']
        self.assertIsNone(hours[10]['orders']);self.assertEqual(hours[10]['known_orders'],1)
        self.assertIsNone(hours[10]['revenue_usd']);self.assertEqual(hours[10]['known_revenue_usd'],20)
        for key in ('orders','revenue_usd','known_orders','known_revenue_usd'):
            self.assertIsNone(hours[9][key])

    def test_missing_payment_time_and_missing_day_cannot_produce_complete_hour_counts(self):
        for extra in ({'missing_payment_time':1}, {'missing_days':['2026-10-11'],'paid_complete':False}):
            with self.subTest(coverage=extra):
                value=dataset([],[]);value['coverage'].update(extra)
                hours=self.view(value)['fc_dashboard']['hourly_trend']
                self.assertTrue(all(row['orders'] is None and row['revenue_usd'] is None for row in hours))
                self.assertTrue(all(row['known_orders'] is None and row['known_revenue_usd'] is None for row in hours))

    def test_missing_amount_keeps_order_count_but_not_unknown_revenue_as_zero(self):
        row=order(1,paytime='2026-10-11 10:15:00');row['amount_cents']=None
        hours=self.view(dataset([row],[]))['fc_dashboard']['hourly_trend']
        self.assertEqual(hours[10]['orders'],1)
        self.assertEqual(hours[10]['unpriced_orders'],1)
        self.assertIsNone(hours[10]['revenue_usd']);self.assertIsNone(hours[10]['known_revenue_usd'])
        self.assertEqual(hours[9]['orders'],0);self.assertEqual(hours[9]['revenue_usd'],0)

    def test_multi_day_and_explicit_hour_keep_existing_trend_contract(self):
        value=dataset([],[])
        self.assertNotIn('hourly_trend',self.view(value,end='2026-10-12')['fc_dashboard'])
        explicit=self.view(value,grain='hour')['fc_dashboard']
        self.assertNotIn('hourly_trend',explicit)
        self.assertEqual(len(explicit['trend']),24)


if __name__=='__main__':unittest.main()
