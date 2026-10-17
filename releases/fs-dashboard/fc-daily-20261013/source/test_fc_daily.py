import concurrent.futures
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fc_daily import DailyReports, SHANGHAI, checked_day, build_report, digest
from fc_daily_model import projection, validate, MODEL

DAY = '2026-10-12'
AT = datetime(2026, 10, 13, 10, tzinfo=SHANGHAI)
FACT = dict(orders=3, revenue_usd=40.25, issues=1, unpriced_orders=0, unfinished=1, completed=2, funding=0)


def source(day=DAY):
    end = (datetime.fromisoformat(day)+timedelta(days=1)).date().isoformat()
    return {'contractId': 'fc27-detail-analytics-v1', 'snapshot_id': 'synthetic-test', 'as_of': AT.isoformat(),
            'query': {'start': day, 'end': day}, 'coverage': {'period': {'start': day+' 00:00', 'end': end+' 00:00'},
            'paid_complete': True, 'missing_days': [], 'site_rule': 'main+satellite', 'backlog_status': 'available'},
            'distribution_identification': 'not_verified', 'data_status': 'available',
            'site_groups': [dict(key='main', **FACT), dict(key='satellite', **{**FACT, 'orders': 0, 'revenue_usd': 0, 'issues': 0})],
            'totals': FACT, 'backlog_summary': FACT,
            'dimensions': {'platform': [dict(key='PS', **FACT)], 'product': [dict(key='Coins', **FACT)]},
            'orders': [{'id': 'PRIVATE-ID', 'password': 'PRIVATE-SECRET', 'email': 'PERSON@example.invalid'}]}


class Detail:
    def __init__(self): self.calls = []; self.data = source(); self.status = 200
    def get(self, params):
        self.calls.append(params)
        return self.status, deepcopy(self.data)


class Reports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.at = AT; self.detail = Detail(); self.calls = []
        self.service = DailyReports(self.detail, self.tmp.name, clock=lambda: self.at, is_configured=lambda: False,
                                    authorizer=lambda u: u == 'existing-admin')
    def generate(self, rid='request-0001'):
        self.service.enqueue(DAY, rid); self.service.run_one(); return self.service.latest(DAY)
    def query(self, **kwargs): return {'mode': ['fc-daily'], 'date': [DAY], **{k: [v] for k, v in kwargs.items()}}
    def test_real_aggregate_contract_no_raw_rows_persisted(self):
        report = self.generate()
        self.assertEqual(report['main']['revenue_usd'], 40.25)
        self.assertEqual(report['analysis']['issue_share_pct'], 33.33)
        self.assertNotIn('PRIVATE', json.dumps(report)); self.assertNotIn('PERSON', json.dumps(report))
        self.assertEqual([x['site_group'] for x in self.detail.calls], [['all'], ['main']])
    def test_missing_model_degrades_and_persists(self):
        report = self.generate(); self.assertEqual(report['status'], 'degraded')
        other = DailyReports(self.detail, self.tmp.name)
        self.assertEqual(other.latest(DAY), report)
        self.assertEqual(report['ai']['status'], 'configuration_missing')
    def test_parallel_generation_and_request_id_dedup(self):
        with concurrent.futures.ThreadPoolExecutor(10) as pool:
            rows = list(pool.map(lambda n: self.service.enqueue(DAY, 'parallel-'+str(n)), range(20)))
        self.assertEqual(len({r['id'] for r in rows}), 1)
        self.service.run_one()
        repeated = self.service.enqueue(DAY, rows[0]['request_id'])
        self.assertEqual(repeated['state'], 'degraded')
    def test_unknown_model_receipt_not_replayed(self):
        def model(p): self.calls.append(p); raise TimeoutError('secret-containing exception')
        self.service.model = model; self.service.is_configured = lambda: True
        self.generate(); self.at += timedelta(minutes=2); report = self.generate('request-0002')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(report['ai']['status'], 'unknown_model_error')
        self.assertNotIn('secret-containing', self.service.db_path.read_bytes().decode('latin1'))
    def test_pending_model_receipt_after_crash_not_replayed(self):
        report = build_report(DAY, source(), source()); fingerprint = digest(projection(report))
        with self.service.db() as db: db.execute("INSERT INTO model_calls VALUES(?,?,'started',NULL)", (fingerprint, DAY))
        self.service.is_configured = lambda: True
        self.service.model = lambda _: self.fail('must not retry unknown')
        self.assertEqual(self.generate()['ai']['status'], 'unknown_previous_attempt')
    def test_failed_refresh_preserves_previous_version(self):
        old = self.generate(); self.at += timedelta(minutes=2); self.detail.status = 503
        self.generate('request-0002')
        status, result = self.service.get(self.query(), 'viewer', {})
        self.assertEqual(status, 200); self.assertEqual(result['report'], old)
        self.assertEqual(result['last_attempt']['error'], 'source_unavailable')
    def test_incomplete_paid_day_never_published(self):
        self.detail.data['coverage']['paid_complete'] = False
        self.assertIsNone(self.generate())
        self.assertEqual(self.service.get(self.query(), 'viewer', {})[1]['last_attempt']['error'], 'paid_data_incomplete')
    def test_missing_money_not_zero(self):
        self.detail.data['site_groups'][0]['unpriced_orders'] = 1
        report = self.generate(); self.assertIsNone(report['main']['revenue_usd'])
        self.assertEqual(report['ai']['status'], 'skipped_incomplete_data')
    def test_backlog_missing_separate_from_payment_day(self):
        self.detail.data['data_status'] = 'partial'; self.detail.data['coverage']['backlog_status'] = 'partial'
        report = self.generate(); self.assertIsNone(report['backlog']); self.assertEqual(report['main']['orders'], 3)
    def test_source_period_and_snapshot_mismatch(self):
        main = source(); main['snapshot_id'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'snapshot'): build_report(DAY, source(), main)
        main = source(); main['coverage']['period']['end'] = '2026-10-14 00:00'
        with self.assertRaisesRegex(ValueError, 'period'): build_report(DAY, source(), main)
    def test_authentication_role_and_csrf(self):
        action = self.query(action='run', request_id='manual-0001')
        self.assertEqual(self.service.get(action, '', {})[0], 401)
        self.assertEqual(self.service.get(action, 'viewer', {'X-FS-Report-Action': 'generate'})[0], 403)
        self.assertEqual(self.service.get(action, 'existing-admin', {})[0], 403)
        self.assertEqual(self.service.get(action, 'existing-admin', {'X-FS-Report-Action': 'generate', 'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.service.get(action, 'existing-admin', {'X-FS-Report-Action': 'generate', 'Sec-Fetch-Site': 'same-origin'})[0], 200)
        self.assertFalse(self.service.get(self.query(), 'viewer', {})[1]['can_generate'])
    def test_date_boundaries_beijing_leap_and_year(self):
        for day, at in [('2026-12-31', datetime(2027,1,1,0,1,tzinfo=SHANGHAI)), ('2024-02-29', datetime(2024,3,1,tzinfo=SHANGHAI))]:
            self.assertEqual(checked_day(day, at).isoformat(), day)
        for day in ['2026-10-13', '2026-10-14', '../2026-10-12', '2025-01-01', '2026-02-30']:
            self.assertEqual(self.service.get({'mode': ['fc-daily'], 'date': [day]}, 'viewer', {})[0], 422)
    def test_schedule_due_catchup_and_idempotence(self):
        self.at = AT.replace(hour=9, minute=14); self.service.tick(); self.assertIsNone(self.service.latest(DAY))
        self.at += timedelta(minutes=1); self.service.tick(); self.service.tick()
        report = self.service.latest(DAY); self.assertEqual(report['trigger'], 'scheduled'); self.assertEqual(report['revision'], 1)
        result = self.service.get(self.query(), 'viewer', {})[1]
        self.assertEqual(result['schedule']['next_run'], '2026-10-14T09:15:00+08:00')
    def test_scheduler_failure_backoff_bounded_three(self):
        self.detail.status = 503; self.service.tick(); self.at += timedelta(minutes=9); self.service.tick()
        with self.service.db() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 1)
        self.at += timedelta(minutes=1); self.service.tick(); self.at += timedelta(minutes=30); self.service.tick()
        self.at += timedelta(hours=1); self.service.tick()
        with self.service.db() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 3)
    def test_versions_and_old_version_read(self):
        old = self.generate(); self.at += timedelta(minutes=2); self.detail.data['site_groups'][0]['orders'] = 4; new = self.generate('request-0002')
        result = self.service.get(self.query(revision=str(old['revision'])), 'viewer', {})[1]
        self.assertEqual(result['report'], old); self.assertEqual(len(result['versions']), 2); self.assertNotEqual(new['revision'], old['revision'])
    def test_projection_exact_whitelist_and_output_validation(self):
        report = self.generate(); report['dimensions']['product'].insert(0, dict(key='PRIVATE-UNTRUSTED', **FACT))
        projected = projection(report); self.assertNotIn('PRIVATE', json.dumps(projected))
        good = {'model': MODEL, 'id': 'chatcmpl-test', 'usage': {'prompt_tokens': 50, 'completion_tokens': 20, 'total_tokens': 70},
                'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'focus': 'review_issues', 'evidence_ref': 'facts.issues', 'explanation': '建议核对原记录中的问题状态并安排复核。'})}}]}
        self.assertEqual(validate(good, projected)['status'], 'succeeded')
        bad = deepcopy(good); bad['choices'][0]['message']['content'] = json.dumps({'focus': 'review_issues', 'evidence_ref': 'facts.issues', 'explanation': '立即降价百分之二十。'})
        with self.assertRaises(ValueError): validate(bad, projected)
    def test_same_scope_comparison_only(self):
        previous = build_report('2026-10-11', source('2026-10-11'), source('2026-10-11'))
        current = build_report(DAY, source(), source(), previous)
        self.assertEqual(current['comparison']['revenue_delta'], 0)
        previous['scope_fingerprint'] = 'old-scope'
        self.assertIsNone(build_report(DAY, source(), source(), previous)['comparison'])


if __name__ == '__main__': unittest.main(verbosity=2)
