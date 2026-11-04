import datetime as dt
import unittest

from mmoexp_google_data.seo import contracts, metrics


class Contracts(unittest.TestCase):
    def test_four_game_scope_and_unknown_rejected(self):
        self.assertEqual(contracts.GAMES, ('FC27', 'D4', 'AION2', 'WOW_FOREVER'))
        with self.assertRaises(ValueError):
            contracts.game('WOW')

    def test_context_uses_beijing_and_thirty_calendar_days(self):
        c = contracts.make_daily_context(dt.datetime(2026, 11, 4, 19, 20, tzinfo=dt.timezone.utc))
        self.assertEqual((c.publication_date, c.report_date, c.history_start),
                         ('2026-11-05', '2026-11-04', '2026-10-06'))
        self.assertTrue(c.collection_allowed)
        self.assertFalse(contracts.make_daily_context(dt.datetime(2026, 11, 5, 2, tzinfo=dt.timezone.utc)).collection_allowed)
        self.assertFalse(contracts.source_day_ended('2026-11-04', 'America/Los_Angeles', c.now))

    def test_observations_never_backdated_from_today(self):
        rows = [{'observed_at': '2026-11-03T19:20:00+00:00'},
                {'observed_at': '2026-11-04T19:20:00+00:00'}]
        self.assertEqual(contracts.eligible_observations(rows, '2026-11-04'), rows[:1])

    def test_weighted_metrics_and_zero_denominator(self):
        result = metrics.compute_metrics([
            {'clicks': '2', 'impressions': '10', 'position': '4'},
            {'clicks': '3', 'impressions': '90', 'position': '14'}], 'gsc')
        self.assertEqual(result['ctr'], '0.05')
        self.assertEqual(result['position'], '13')
        self.assertIsNone(metrics.compute_metrics([], 'gsc')['ctr'])

    def test_rank_coverage_keeps_planned_denominator(self):
        result = metrics.compute_metrics([
            {'status': 'found', 'rank': 5, 'effective_depth': 10},
            {'status': 'not_found', 'rank': None, 'effective_depth': 10},
            {'status': 'failed', 'rank': None, 'effective_depth': 0}], 'rankings')
        self.assertEqual(result['top10'], '0.5')
        self.assertAlmostEqual(float(result['coverage']), 2 / 3)
        self.assertIsNone(metrics.compute_metrics([{'status': 'not_found', 'effective_depth': 8}], 'rankings')['top10'])

    def test_paid_attribution_deduplicates_lines_and_unknown_is_not_seo(self):
        rows = [dict(order_ref='one', line_ref='a', game='D4', paid=True, attribution='A', revenue_usd='12.34'),
                dict(order_ref='two', line_ref='b', game='D4', paid=True, attribution='U', revenue_usd='5')]
        result = metrics.compute_metrics(rows + rows[:1], 'orders')
        self.assertEqual(result['paid_orders'], 2)
        self.assertEqual(result['seo_orders'], 1)
        self.assertEqual(result['seo_revenue_usd'], '12.34')
        self.assertEqual(result['attribution_coverage'], '0.5')
        with self.assertRaises(ValueError):
            metrics.compute_metrics(rows[:1] + [dict(rows[0], revenue_usd='9')], 'orders')


if __name__ == '__main__':
    unittest.main()
