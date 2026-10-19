import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / 'releases/fs-dashboard/hermes-report-repair-20261019/source'
sys.path[:0] = [str(SOURCE), str(ROOT/'releases/fs-dashboard/hermes-fc-pilot-20261013'),
                str(ROOT/'releases/fs-dashboard/admin-data-tools-20261018/candidate/hermes'), str(ROOT)]
if sys.platform == 'win32':
    sys.modules.setdefault('fcntl', types.SimpleNamespace())
from evidence_access import read_evidence, model_view
from management_context import ManagementBook, task_prompt
from es_order_structure import ESReader


EV = 'ev_' + 'a'*24


def facts():
    return {'snapshotId':'management-'+'b'*24, 'businessDate':'2026-10-19',
            'generatedAt':'2026-10-19T00:20:00+08:00',
            'period':{'start':'2026-10-01','end':'2026-10-18','observed':18,'month_days':31},
            'projects':[{'profile':p,'name':p,'group':g,'owner':'operator',
                         'month':{'values':{'rev':100,'ord':4,'prof':20,'new':2}},
                         'targets':{'rev':200,'ord':8,'prof':40,'new':4},
                         'daily':[{'d':d,'rev':5} for d in ('2026-10-16','2026-10-17','2026-10-18')]}
                        for p,g in [('FC27','sports'),('D4','rpg'),('AION2','other')]]}


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.book=types.SimpleNamespace(evidence={EV:{'data':{'rows':[{'n':n,'text':'字'*2000} for n in range(40)],'total':40},'query':{'profile':'FC27'}}})

    def test_report_revision_keeps_new_read_and_html_tools(self):
        from continuation import FrozenEvidenceBook
        book=object.__new__(FrozenEvidenceBook);book.evidence=self.book.evidence
        value=book.call('fc.read_evidence',{'evidence_id':EV,'path':'/data/total'})
        self.assertEqual(value['value'],40)
        value=book.call('fc.check_report_html',{'html':'<!doctype html><html><body>report</body></html>'})
        self.assertEqual(value['issue_count'],0)

    def test_large_data_is_indexed_and_all_rows_are_readable(self):
        record={'evidence_id':EV,'data':self.book.evidence[EV]['data']}
        view=model_view(record)
        self.assertLess(len(json.dumps(view,ensure_ascii=False).encode()),16000)
        self.assertEqual(view['read_more']['evidence_id'],EV)
        rows=[];offset=0
        while offset is not None:
            page=read_evidence(self.book,{'evidence_id':EV,'path':'/data/rows','offset':offset})
            self.assertLess(len(json.dumps(page,ensure_ascii=False).encode()),16000)
            rows.extend(x['n'] for x in page['items']);offset=page['next_offset']
        self.assertEqual(rows,list(range(40)))
        self.assertEqual(len(self.book.evidence[EV]['data']['rows']),40)

    def test_cross_task_and_arbitrary_paths_rejected(self):
        for args, error in [({'evidence_id':'ev_'+'c'*24},PermissionError),
                            ({'evidence_id':EV,'path':'/etc/passwd'},ValueError),
                            ({'evidence_id':EV,'path':'/data/rows/-1'},ValueError),
                            ({'evidence_id':EV,'url':'https://example.invalid'},ValueError)]:
            with self.assertRaises(error):read_evidence(self.book,args)

    def test_large_dictionary_has_bounded_index_pages(self):
        self.book.evidence[EV]['data']={str(n):'x'*1500 for n in range(150)}
        seen=[];offset=0
        while offset is not None:
            view=read_evidence(self.book,{'evidence_id':EV,'offset':offset})
            self.assertLess(len(json.dumps(view).encode()),16000)
            seen.extend(x['path'] for x in view['content_index']);offset=view['next_offset']
        self.assertEqual(len(set(seen)),150)


class ManagementTests(unittest.TestCase):
    def test_all_groups_are_in_the_compact_initial_prompt(self):
        f=facts();prompt=task_prompt(f,EV)
        self.assertIn('sports',prompt);self.assertIn('rpg',prompt);self.assertIn('other',prompt)
        self.assertIn('300.0',prompt);self.assertLess(len(prompt.encode()),16000)

    def test_registered_profile_native_read_and_wrong_profile_denied(self):
        calls=[]
        book=ManagementBook(facts(),{'start':'2026-10-01','end':'2026-10-18'},
            native=lambda q:(calls.append(q) or {'status':'available','captured_at':'2026-10-19T01:00:00Z','authoritative_fields':{}}))
        q={'profile':'D4','start':'2026-10-01','end':'2026-10-18'}
        value=book.call('fc.query_native_statistics',q)
        self.assertEqual(value['data']['status'],'available');self.assertEqual(calls,[q])
        with self.assertRaises(ValueError):book.call('fc.query_native_statistics',dict(q,profile='UNREGISTERED'))
        with self.assertRaises(ValueError):book.call('fc.query_native_statistics',dict(q,end='2026-10-20'))

    def test_management_full_evidence_remains_readable(self):
        book=ManagementBook(facts(),{'start':'2026-10-01','end':'2026-10-18'})
        r=book.register('management.frozen_context',{}, {'projects':facts()['projects']})
        view=book.call('fc.read_evidence',{'evidence_id':r['evidence_id'],'path':'/data/projects/1'})
        self.assertEqual(view['value']['profile'],'D4')


class PendingTests(unittest.TestCase):
    def test_not_ready_does_not_claim_export_failed(self):
        from concurrent.futures import Future
        class Pool:
            def submit(self,*args):return Future()
        reader=ESReader({'enabled':True},Pool())
        r=reader.get({'profile':'FC27','start':'2026-10-12','end':'2026-10-18','group_by':'discount_new_customer'})
        self.assertEqual(r['status'],'pending');self.assertEqual(r['reason'],'es_source_running')
        self.assertEqual(r['quality']['reason'],'es_source_running')

    def test_fresh_current_pool_is_required_when_reusing_paid_snapshot(self):
        import fs_evidence
        now=datetime.now(timezone.utc); config={'enabled':True,'today_cache_seconds':900}
        old={'as_of':(now-timedelta(hours=2)).isoformat(),'coverage':{'paid_complete':True,'missing_days':[]}}
        fresh={'as_of':now.isoformat(),'coverage':{'paid_complete':True,'missing_days':[]}}
        checked=[]
        class Store:
            def get(self,family,args,reader,valid,enabled):
                checked.extend([valid(old),valid(fresh)]);return fresh
        import source_snapshots
        previous=source_snapshots.SnapshotStore;source_snapshots.SnapshotStore=Store
        try:
            detail=types.SimpleNamespace(config=config)
            from unittest.mock import patch
            with patch.dict(sys.modules, {'fc_deep_sources':types.SimpleNamespace(EvidenceReader=None)}):
                value,_=fs_evidence.source_capture(detail,'2026-10-12','2026-10-18')
        finally:source_snapshots.SnapshotStore=previous
        self.assertEqual(checked,[False,True]);self.assertEqual(value,fresh)


class HtmlCheckTests(unittest.TestCase):
    def test_inline_bar_problem_is_detected_without_executing_script(self):
        from html_check import check_html
        raw='<!doctype html><html><style>.track{height:13px}.bar{height:100%;background:red}</style><body><div class="track"><span class="bar" style="width:75%"></span></div><script>throw Error("MUST NOT EXECUTE")</script></body></html>'
        result=check_html({'html':raw})
        self.assertEqual(result['issue_count'],1)
        self.assertEqual(result['issues'][0]['code'],'inline_span_bar_has_no_box')
        fixed=raw.replace('.bar{height:100%;','.bar{display:block;height:100%;')
        self.assertEqual(check_html({'html':fixed})['issue_count'],0)
        flex=raw.replace('.track{height:13px}', '.track{display:flex;height:13px}')
        self.assertEqual(check_html({'html':flex})['issue_count'],0)

    def test_checker_rejects_files_and_oversized_input(self):
        from html_check import check_html
        for args in ({'path':'/etc/passwd'},{'html':'x'*1000001}):
            with self.assertRaises(ValueError):check_html(args)


class MarketingTests(unittest.TestCase):
    def test_fc_landing_content_retains_pre_top_totals_and_scope(self):
        sys.path.extend([str(ROOT/'releases/fs-dashboard/traffic-hermes-20261017/source'),str(ROOT/'mmoexp_google_data/details')])
        import marketing_snapshot as m
        q={'profile':'FC27','start':'2026-10-12','end':'2026-10-18'}
        ga={'resource':'541418940','timezone':'Asia/Shanghai','breakdowns':{'landing_page':{
            'rows':[{'dimensions':{'landingPage':'/fc-27-coins.html?utm=x'},'metrics':{'sessions':10}},
                    {'dimensions':{'landingPage':'https://other.invalid/fc-27.html'},'metrics':{'sessions':90}}],
            'fc27_content':{'metrics':{'sessions':321},'source_limited':True,'returned_matching_rows':42}}}}
        model={'schemaVersion':1,'isMock':False,'details':{'schemaVersion':1,'isMock':False,
            'periods':[dict(q,sources={'ga4':ga})]}}
        out=m.projection(model,q,'a'*64)['sources']['ga4']['fc27_landing_content']
        self.assertEqual(len(out['rows']),1)
        self.assertNotIn('utm',out['rows'][0]['label'])
        self.assertEqual(out['full_calculation']['metrics']['sessions'],'321')
        self.assertTrue(out['full_calculation']['source_limited'])


if __name__=='__main__':unittest.main()

