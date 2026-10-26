import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CANONICAL=ROOT/'source'
sys.path.insert(0,str(CANONICAL))
import fc_pricing_v3
from fc_pricing_v3 import api, simulation


def input_body(window, rows, *, snapshots=(), complete=True, as_of='2026-10-26T10:00:00+08:00'):
    paid=window['paid_window']
    return dict(schema_version='fc-pricing-v3-history-input-v1',period_selector=window['period_selector'],
        paid_window=paid,as_of=as_of,source_sha256='a'*64,historical_orders=rows,
        historical_orders_coverage=dict(period_selector=window['period_selector'],
            paid_window_start=paid['start']+'T00:00:00+08:00',
            paid_window_end_exclusive=paid['end_exclusive']+'T00:00:00+08:00',
            population_status='complete' if complete else 'partial',window_complete=complete,
            status='partial',available_at=as_of,gaps={} if complete else {'missing_closed_day':1}),
        snapshot_ids=list(snapshots))


def order(key, paid_at, available_at, paid_usd='10', **extra):
    return dict(order_key=key,paid_at=paid_at,available_at=available_at,paid_usd=paid_usd,**extra)


class HistoricalWindow(unittest.TestCase):
    def test_14_28_and_previous_complete_month_are_distinct_closed_windows(self):
        now=datetime.fromisoformat('2026-10-26T21:00:00+08:00')
        self.assertEqual(simulation.historical_window(14,now)['paid_window'],
            dict(start='2026-10-12',end_exclusive='2026-10-26',timezone='Asia/Shanghai'))
        self.assertEqual(simulation.historical_window(28,now)['paid_window']['start'],'2026-09-28')
        self.assertEqual(simulation.historical_window('month',now),dict(period_selector='last_complete_month',
            paid_window=dict(start='2026-09-01',end_exclusive='2026-10-01',timezone='Asia/Shanghai')))
        self.assertEqual(simulation.historical_window('month',datetime.fromisoformat('2027-01-01T00:01:00+08:00'))['paid_window']['start'],'2026-12-01')
        with self.assertRaisesRegex(ValueError,'pricing_historical_window_invalid'):
            simulation.historical_window('current_month',now)

    def test_today_backfill_uses_paid_window_and_keeps_private_rows_out_of_api(self):
        now='2026-10-26T10:00:00+08:00'
        window=simulation.historical_window(14,now)
        rows=[order('inside-early','2026-10-12T00:00:00+08:00',now,'8'),
              order('inside-last','2026-10-25T23:59:59+08:00',now,'12'),
              order('before','2026-10-11T23:59:59+08:00',now,'99'),
              order('today','2026-10-26T00:00:00+08:00',now,'99')]
        attachment=input_body(window,rows)
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.db'
            with closing(sqlite3.connect(source)) as db, db:
                db.executescript('CREATE TABLE event_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,body TEXT);'
                    'CREATE TABLE historical_inputs(id TEXT PRIMARY KEY,body TEXT);'
                    'CREATE TABLE pricing_snapshots(id TEXT PRIMARY KEY,body TEXT);')
                db.execute('INSERT INTO historical_inputs VALUES (?,?)',('input-one',json.dumps(attachment)))
                event=dict(simulation_id='sim-one',kind='actual_reconstruction',closed_days=14,
                    requested_at=now,historical_input_id='input-one',period_selector=window['period_selector'],paid_window=window['paid_window'])
                db.execute('INSERT INTO event_outbox(kind,body) VALUES (?,?)',('simulation_requested',json.dumps(event)))
            shadow=simulation.Shadow(Path(folder)/'shadow.db')
            self.assertEqual(shadow.consume(source)['cursor'],1)
            with shadow.connect() as db:
                raw=json.loads(db.execute("SELECT body FROM history WHERE id='sim-one'").fetchone()[0])
            self.assertEqual(raw['reconciled_actual']['actual']['order_count'],2)
            self.assertEqual(raw['reconciled_actual']['actual']['net_revenue_usd'],'20')
            self.assertTrue(raw['reconciled_actual']['population_complete'])
            self.assertEqual(raw['paid_window'],window)
            public=api.history_view(raw)
            self.assertEqual(public['paid_window'],window)
            self.assertNotIn('inside-early',json.dumps(public))
            self.assertNotIn('inside-last',json.dumps(public))
            with closing(sqlite3.connect(source)) as db, db:
                db.execute('INSERT INTO event_outbox(kind,body) VALUES (?,?)',('simulation_requested',json.dumps(event)))
            self.assertEqual(simulation.Shadow(shadow.path).consume(source)['cursor'],2)
            with shadow.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM history').fetchone()[0],1)

    def test_late_cost_revision_changes_final_actual_not_original_asof(self):
        now='2026-10-26T10:00:00+08:00'
        window=simulation.historical_window(14,now)
        early='2026-10-21T08:00:00+08:00'
        first=order('same','2026-10-20T08:00:00+08:00',early,'10',cost_usd=None)
        revised=order('same','2026-10-20T08:00:00+08:00',now,'10',cost_usd='4')
        coverage=input_body(window,[],as_of=early)['historical_orders_coverage']
        old=dict(snapshot_id='old',evidence=dict(checked_at=early,historical_orders=[first],
            historical_orders_coverage=coverage))
        late=input_body(window,[revised],snapshots=['old'])
        late_snapshot=dict(snapshot_id='input-two',origin='verified_historical_attachment',available_at=now,
            evidence=dict(checked_at=now),historical_orders=late['historical_orders'],
            historical_orders_coverage=late['historical_orders_coverage'])
        with tempfile.TemporaryDirectory() as folder:
            result=simulation.Shadow(Path(folder)/'shadow.db').historical([old,late_snapshot],
                kind='actual_reconstruction',closed_days=14,paid_window=window,coverage=late['historical_orders_coverage'])
        self.assertIsNone(result['records'][0]['cumulative_actual']['procurement_contribution_usd'])
        self.assertEqual(result['records'][0]['as_of'],early)
        self.assertEqual(result['reconciled_actual']['actual']['procurement_contribution_usd'],'6')
        self.assertEqual(result['reconciled_actual']['revised_order_count'],1)

    def test_late_attachment_does_not_backdate_fixed_order_prices(self):
        now='2026-10-26T10:00:00+08:00'
        window=simulation.historical_window(28,now)
        row=order('late','2026-10-03T08:00:00+08:00',now,'10',platform='PS',region_id=0,
            base_k='100',bonus_k='0',regular_usd='10',promotion_path=dict(kind='none'),
            price_version='original',package_retained_ratio='1')
        late=dict(snapshot_id='input-three',origin='verified_historical_attachment',available_at=now,
            evidence=dict(checked_at=now),historical_orders=[row],
            historical_orders_coverage=input_body(window,[row])['historical_orders_coverage'])
        with tempfile.TemporaryDirectory() as folder:
            result=simulation.Shadow(Path(folder)/'shadow.db').historical([late],
                kind='fixed_orders_reprice',closed_days=28,paid_window=window)
        self.assertEqual(result['records'][0]['status'],'historical_price_window_missing')
        self.assertIsNone(result['records'][0]['fixed_order_count'])

    def test_previous_month_excludes_current_mtd_and_partial_coverage_keeps_known_revenue(self):
        now='2026-10-26T10:00:00+08:00'
        window=simulation.historical_window('month',now)
        rows=[order('august','2026-08-31T23:59:59+08:00',now,'100'),
              order('september-first','2026-09-01T00:00:00+08:00',now,'7'),
              order('september-last','2026-09-30T23:59:59+08:00',now,'11'),
              order('october-mtd','2026-10-01T00:00:00+08:00',now,'100')]
        attachment=input_body(window,rows,complete=False)
        snapshot=dict(snapshot_id='month-input',origin='verified_historical_attachment',available_at=now,
            evidence=dict(checked_at=now),historical_orders=rows,
            historical_orders_coverage=attachment['historical_orders_coverage'])
        with tempfile.TemporaryDirectory() as folder:
            result=simulation.Shadow(Path(folder)/'shadow.db').historical([snapshot],
                kind='actual_reconstruction',closed_days='month',paid_window=window,
                coverage=attachment['historical_orders_coverage'])
        self.assertEqual(result['reconciled_actual']['actual']['order_count'],2)
        self.assertEqual(result['reconciled_actual']['actual']['net_revenue_usd'],'18')
        self.assertFalse(result['reconciled_actual']['population_complete'])
        self.assertEqual(result['records'][0]['status'],'partial')
        self.assertIn(dict(reason='missing_closed_day',count=1),result['coverage']['gaps'])
        self.assertIn('historical_orders_population_partial',[gap['reason'] for gap in result['records'][0]['gaps']])

    def test_zero_orders_requires_explicit_complete_population(self):
        now='2026-10-26T10:00:00+08:00'
        window=simulation.historical_window(7,now)
        with tempfile.TemporaryDirectory() as folder:
            shadow=simulation.Shadow(Path(folder)/'shadow.db')
            for complete,expected in ((True,'0'),(False,None)):
                attachment=input_body(window,[],complete=complete)
                snapshot=dict(snapshot_id='empty-'+str(complete),origin='verified_historical_attachment',
                    available_at=now,evidence=dict(checked_at=now),historical_orders=[],
                    historical_orders_coverage=attachment['historical_orders_coverage'])
                result=shadow.historical([snapshot],kind='actual_reconstruction',closed_days=7,
                    paid_window=window,coverage=attachment['historical_orders_coverage'])
                self.assertEqual(result['records'][0]['actual']['net_revenue_usd'],expected)

    def test_coverage_mismatch_keeps_original_cursor(self):
        now='2026-10-26T10:00:00+08:00'
        window=simulation.historical_window('month',now)
        attachment=input_body(window,[order('september','2026-09-30T23:00:00+08:00',now)])
        attachment['historical_orders_coverage']['paid_window_start']='2026-10-01T00:00:00+08:00'
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.db'
            with closing(sqlite3.connect(source)) as db, db:
                db.executescript('CREATE TABLE event_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,body TEXT);'
                    'CREATE TABLE historical_inputs(id TEXT PRIMARY KEY,body TEXT);'
                    'CREATE TABLE pricing_snapshots(id TEXT PRIMARY KEY,body TEXT);')
                db.execute('INSERT INTO historical_inputs VALUES (?,?)',('input-month',json.dumps(attachment)))
                event=dict(simulation_id='sim-month',kind='actual_reconstruction',closed_days='month',
                    requested_at=now,historical_input_id='input-month',period_selector=window['period_selector'],paid_window=window['paid_window'])
                db.execute('INSERT INTO event_outbox(kind,body) VALUES (?,?)',('simulation_requested',json.dumps(event)))
            shadow=simulation.Shadow(Path(folder)/'shadow.db')
            with self.assertRaisesRegex(ValueError,'pricing_historical_coverage_window_mismatch'):
                shadow.consume(source)
            with shadow.connect() as db:
                self.assertIsNone(db.execute("SELECT value FROM cursor WHERE id='production'").fetchone())


if __name__=='__main__':
    unittest.main()
