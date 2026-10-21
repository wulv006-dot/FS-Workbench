from datetime import date, timedelta
import unittest
from unittest.mock import patch
from monthly_paid import windows, collect
from patch_paid import transform
import ast
from pathlib import Path

# Synthetic adapter contract; production source remains on the server.
FIXTURE = '''import hashlib,json
def checked_query(q):return q
def collect(request,args):
    q=checked_query(args);gid=1327
    out={'orders':[]}
    expected=None;seen=set();previous_id=float('inf')
    excluded=[]
    batch=request(args);expected=len(batch)
    for row in batch:
            if str(row.get('gid'))!=str(gid) or str(row.get('site_id'))!='266' or str(row.get('pay_status'))!='1':
                raise ValueError('cohort_paid_scope')
            seen.add(row['id'])
            if not q['start']<=row['paytime']<=q['end']:raise ValueError('cohort_paid_time')
            customer_key=hashlib.sha256(str(row['id']).encode()).hexdigest()
            out['orders'].append({'id':str(row['id']),'customer_key':customer_key})
    complete=len(seen)==expected
    out.update(status='available',query=q,coverage={
        'paid_complete':complete,'source_total':expected,'received':len(seen),
        'source_scope':'Admin paid orders; exact gid + main site 266; site-local UID',
        'pages':[{'page':1,'rows':len(batch),'total':expected}]})
    return out
'''


class MonthlyPaidTests(unittest.TestCase):
    def test_calendar_windows_cover_leap_and_year_boundaries_without_overlap(self):
        for start, end in [('2026-09-17', '2026-10-20'), ('2024-02-20', '2024-03-02'), ('2025-12-31', '2026-01-01')]:
            pieces = windows(start, end)
            days = []
            for lo, hi in pieces:
                self.assertEqual(lo[:7], hi[:7])
                current = date.fromisoformat(lo)
                while current <= date.fromisoformat(hi):
                    days.append(current); current += timedelta(days=1)
            self.assertEqual(len(days), len(set(days)))
            self.assertEqual(days, [date.fromisoformat(start) + timedelta(days=i)
                                   for i in range((date.fromisoformat(end) - date.fromisoformat(start)).days + 1)])

    def part(self, query, ident=None, complete=True):
        return {'kind': 'cohort_paid_orders', 'query': query, 'status': 'available' if complete else 'partial',
            'orders': [{'id': ident or query['start'] + '-synthetic'}],
            'coverage': {'paid_complete': complete, 'source_total': 1, 'received': 1,
                'pages': [{'page': 1, 'rows': 1, 'total': 1}],
                'missing_days': [], 'missing_payment_time': 0}}

    def test_complete_merge_preserves_query_and_real_segment_totals(self):
        q = {'profile': 'FC27', 'start': '2026-09-17', 'end': '2026-10-20'}
        calls = []
        def single(request, query):
            calls.append(query.copy()); return self.part(query)
        result = collect(None, q, single)
        self.assertEqual([(x['start'], x['end']) for x in calls], [('2026-10-01', '2026-10-20'), ('2026-09-17', '2026-09-30')])
        self.assertEqual(result['query'], q)
        self.assertEqual(result['coverage']['period'], {'start': '2026-09-17 00:00', 'end': '2026-10-21 00:00'})
        self.assertEqual((result['coverage']['source_total'], result['coverage']['received']), (2, 2))
        self.assertEqual(result['status'], 'available')
        self.assertTrue(result['coverage']['paid_complete'])

    def test_partial_or_duplicate_month_never_becomes_complete(self):
        q = {'profile': 'FC27', 'start': '2026-09-17', 'end': '2026-10-20'}
        result = collect(None, q, lambda request, query: self.part(query, complete=False))
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['coverage']['paid_complete'])
        self.assertIsNone(result['coverage']['source_total'])
        with self.assertRaisesRegex(ValueError, 'cross_month_duplicate'):
            collect(None, q, lambda request, query: self.part(query, ident='same-synthetic'))

    def test_global_request_budget_does_not_multiply_by_month_count(self):
        q = {'profile': 'FC27', 'start': '2026-09-17', 'end': '2026-10-20'}
        calls = []
        def single(request, query):
            for _ in range(151):request('/admin/read', 30)
            return self.part(query)
        with self.assertRaisesRegex(TimeoutError, 'total_read_budget'):
            collect(lambda *args: calls.append(args), q, single)
        self.assertEqual(len(calls), 300)
        with patch('monthly_paid.time.monotonic', side_effect=[0, 851]):
            with self.assertRaisesRegex(TimeoutError, 'total_read_budget'):
                collect(lambda *a: None, q, lambda request, query: request('/admin/read', 30))

    def test_single_month_and_source_drift_keep_original_contract(self):
        q = {'profile': 'FC27', 'start': '2026-10-01', 'end': '2026-10-20'}
        source = self.part(q)
        self.assertIs(collect(None, q, lambda *a: source), source)
        transformed = transform(FIXTURE)
        self.assertIn('def _single_month_collect', transformed)
        with self.assertRaisesRegex(RuntimeError, 'source_changed'):
            transform('def collect(request, args):return None\n')

    def test_refunded_enumerated_but_never_emitted_as_paid(self):
        module={};exec(transform(FIXTURE),module)
        q={'profile':'FC27','start':'2026-10-01','end':'2026-10-20'}
        paid={'id':2,'gid':1327,'site_id':266,'pay_status':1,'paytime':'2026-10-03'}
        refunded=dict(paid,id=1,pay_status=2)
        value=module['collect'](lambda args:[paid,refunded],q)
        self.assertEqual([r['id'] for r in value['orders']],['2'])
        c=value['coverage']
        self.assertEqual((c['source_scanned_total'],c['source_scanned_received'],c['excluded_refunded']), (2,2,1))
        self.assertEqual((c['source_total'],c['received'],c['paid_complete']), (1,1,True))
        self.assertEqual(c['pages'][0]['rows'],2)
        for changed in ({'pay_status':0},{'pay_status':3},{'gid':456},{'site_id':1}):
            with self.assertRaisesRegex(ValueError,'cohort_paid_scope'):
                module['collect'](lambda args:[dict(paid,**changed)],q)
        with self.assertRaisesRegex(ValueError,'cohort_paid_time'):
            module['collect'](lambda args:[dict(refunded,paytime='2026-09-30')],q)

    def test_monthly_enumeration_counts_are_added_without_hiding_refunds(self):
        q={'profile':'FC27','start':'2026-09-17','end':'2026-10-20'}
        def single(request,query):
            part=self.part(query)
            part['coverage'].update(source_scanned_total=3,source_scanned_received=3,excluded_refunded=2)
            return part
        c=collect(None,q,single)['coverage']
        self.assertEqual((c['source_scanned_total'],c['source_scanned_received'],c['excluded_refunded']), (6,6,4))
        self.assertEqual((c['source_total'],c['received']), (2,2))

    def test_deployment_preserves_existing_mounts_and_rejects_drift(self):
        tree=ast.parse(Path(__file__).with_name('deploy_monthly.py').read_text('utf-8'))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='unit_patch')
        context={'BASE':'old-image','IMAGE':'new-image'}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<unit-patch>','exec'),context)
        original='ExecStart=run --mount dst=/run/secrets/fs-session-state --mount current-ocr-config old-image\n'
        updated=context['unit_patch'](original)
        self.assertEqual(updated,original.replace('old-image','new-image'))
        for bad in (original.replace('old-image','other-image'),original+'old-image',original.replace('fs-session-state','different-state')):
            with self.assertRaisesRegex(RuntimeError,'unit_changed'):context['unit_patch'](bad)
