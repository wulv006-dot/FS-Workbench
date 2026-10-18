from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import time
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'hermes-generic-data-20261018'/'source'))
from cohort_reader import CohortReader, SHANGHAI, checked_query, refresh_registered, tool_schema


def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data),'utf-8')


class ReaderTests(unittest.TestCase):
    def test_tool_schema_exposes_all_observation_windows_read_only(self):
        schema=tool_schema()['function']['parameters']
        self.assertEqual(schema['properties']['window_days'],{
            'type':'integer','enum':[7,14,30],
            'description':'Requested maximum observation days; default 30; monitor stops at this mature cutoff'})
        self.assertEqual(schema['properties']['action']['enum'],['read'])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.pool=ThreadPoolExecutor(max_workers=1)
        self.today=datetime.now(SHANGHAI).date()
        self.start=(self.today-timedelta(days=40)).isoformat()
        self.q={'profile':'FC27','start':self.start,'end':self.start}
        def source(q,config):
            return {'orders':[{'id':'ORDER-PRIVATE','customer_key':'ANON-A','paid_at':self.start+'T10:00:00+08:00','customer':'new','site_group':'main','platform':'PS'},
                              {'id':'ORDER-OTHER-SITE','customer_key':'ANON-B','paid_at':self.start+'T10:00:00+08:00','customer':'new','site_group':'satellite','platform':'PS'}],
                    'coverage':{'period':q['period'],'paid_complete':True,'missing_payment_time':0,'missing_days':[]},'snapshot_id':'fc-detail-synthetic','as_of':datetime.now(SHANGHAI).isoformat()}
        self.detail=SimpleNamespace(cache=Path(self.tmp.name),pool=self.pool,config={'enabled':True,'trust_customer_flag':True},reader=source)
        self.reader=CohortReader(self.detail)
        self.stub=patch.dict(sys.modules,{'fc_detail':SimpleNamespace(atomic=atomic)})
        self.stub.start()
        self.es=patch('cohort_es_source.archive_for',return_value={'status':'available','rows':[{'order_hash':hashlib.sha256(ident.encode()).hexdigest(),'flag':'new','payment_day':self.start} for ident in ('ORDER-PRIVATE','ORDER-OTHER-SITE')],'source_version':'test-es','coverage':{}})
        self.es.start()

    def tearDown(self):
        self.pool.shutdown();self.es.stop();self.stub.stop();self.tmp.cleanup()

    def test_create_freeze_archive_and_scope(self):
        first=self.reader.get(self.q,action='create')
        self.assertEqual(first['status'],'pending')
        next(iter(self.reader.jobs.values()))[0].result()
        value=self.reader.get(self.q,create=False)
        self.assertEqual(value['members'],1)
        self.assertEqual(value['monitor']['state'],'completed')
        self.assertTrue(value['evidence_id'].startswith('cohort_'))
        self.assertNotIn('ANON-A',json.dumps(value))
        self.assertEqual(self.reader.get(self.q,action='pause')['monitor']['state'],'paused')
        self.assertEqual(refresh_registered(self.detail),[])
        self.reader.tick()
        self.assertEqual(len(self.reader.jobs),1)
        pinned=self.reader.get(dict(self.q,evidence_id=value['evidence_id']))
        self.assertEqual(pinned['evidence_id'],value['evidence_id'])

    def test_off_and_unverified_flags(self):
        self.detail.config['enabled']=False
        self.assertEqual(self.reader.get(self.q)['reason'],'fc_detail_disabled')
        self.detail.config.update(enabled=True,trust_customer_flag=False)
        self.assertEqual(self.reader.get(self.q)['status'],'pending')
        self.assertFalse(list(self.reader.root.glob('*.monitor.json')))

    def test_incomplete_paid_source_fails(self):
        self.detail.reader=lambda q,c:{'orders':[],'coverage':{'paid_complete':False}}
        self.reader.get(self.q,action='create')
        with self.assertRaises(ValueError):next(iter(self.reader.jobs.values()))[0].result()
        value=self.reader.get(self.q,create=False)
        self.assertEqual(value['reason'],'cohort_source_failed')
        self.assertFalse(list(self.reader.root.glob('*.aggregate.json')))

    def test_strict_query(self):
        for extra in ({'url':'https://example.com'},{'site_group':'distribution_group'},{'profile':'ALL'},{'end':self.today.isoformat()}):
            with self.assertRaises(ValueError):checked_query(dict(self.q,**extra))

    def test_plain_tool_read_is_one_shot_and_persistent_cache(self):
        first=self.reader.get(self.q)
        self.assertEqual(first['status'],'pending')
        self.assertRegex(first['archive_id'],r'^[a-f0-9]{64}$')
        self.assertFalse(list(self.reader.root.glob('*.monitor.json')))
        next(iter(self.reader.jobs.values()))[0].result()
        value=self.reader.get_id(first['archive_id'])
        self.assertEqual(value['status'],'available')
        self.assertEqual(value['members'],1)
        self.assertEqual(value['archive_id'],first['archive_id'])
        self.assertIn('captured_at',value)
        self.assertFalse(list(self.reader.root.glob('*.monitor.json')))
        fresh=CohortReader(self.detail)
        self.assertEqual(fresh.get(self.q)['evidence_id'],value['evidence_id'])
        self.assertEqual(fresh.jobs,{})
        self.assertEqual(fresh.get_id(first['archive_id'])['evidence_id'],value['evidence_id'])

    def test_historical_fc_acquisition_window_reads_through_observation_cutoff(self):
        start=self.today-timedelta(days=17)
        q={'profile':'FC27','start':start.isoformat(),'end':(start+timedelta(days=3)).isoformat(),'window_days':14}
        periods=[];original=self.detail.reader
        def source(query,config):
            periods.append(query['period'])
            value=original(query,config)
            value['orders']=[]
            return value
        self.detail.reader=source
        with patch('cohort_es_source.archive_for',return_value={'status':'available','rows':[],'source_version':'test-es','coverage':{}}):
            first=self.reader.get(q)
            next(iter(self.reader.jobs.values()))[0].result()
        self.assertEqual(self.reader.get_id(first['archive_id'])['status'],'available')
        self.assertEqual(periods,[{'start':q['start']+' 00:00','end':self.today.isoformat()+' 00:00'}])
        self.assertFalse(list(self.reader.root.glob('*.monitor.json')))

    def test_manual_refresh_does_not_register_monitor(self):
        first=self.reader.get(self.q,action='refresh',refresh=True)
        self.assertEqual(first['status'],'pending')
        next(iter(self.reader.jobs.values()))[0].result()
        self.assertEqual(self.reader.get_id(first['archive_id'])['status'],'available')
        self.assertFalse(list(self.reader.root.glob('*.monitor.json')))

    def test_poll_during_explicit_refresh_does_not_return_old_aggregate(self):
        first=self.reader.get(self.q)
        next(iter(self.reader.jobs.values()))[0].result()
        old=self.reader.get_id(first['archive_id'])
        self.reader.finished[first['archive_id']]-=31
        started=threading.Event();release=threading.Event();original=self.detail.reader
        def slow(q,c):
            started.set();release.wait(5)
            value=original(q,c);value['snapshot_id']='new-synthetic-version'
            return value
        self.detail.reader=slow
        try:
            refresh=self.reader.get(self.q,action='refresh',refresh=True)
            self.assertEqual(refresh['status'],'pending')
            self.assertTrue(started.wait(2))
            polling=self.reader.get_id(first['archive_id'])
            self.assertEqual(polling['status'],'pending')
            self.assertEqual(polling['previous']['evidence_id'],old['evidence_id'])
        finally:
            release.set()
        next(iter(self.reader.jobs.values()))[0].result()
        self.assertEqual(self.reader.get_id(first['archive_id'])['status'],'available')

    def test_capacity_pending_id_is_resumable(self):
        self.reader.jobs={'busy-one':(Future(),time.monotonic()),'busy-two':(Future(),time.monotonic())}
        queued=self.reader.get(self.q)
        self.assertEqual(queued['reason'],'cohort_queue_capacity')
        self.assertTrue((self.reader.root/(queued['archive_id']+'.query.json')).exists())
        self.assertEqual(self.reader.get_id(queued['archive_id'])['reason'],'cohort_queue_capacity')

    def test_failed_one_shot_has_cooldown_and_can_retry(self):
        self.detail.reader=lambda q,c:(_ for _ in ()).throw(ValueError('source_failed'))
        first=self.reader.get(self.q)
        with self.assertRaises(ValueError):next(iter(self.reader.jobs.values()))[0].result()
        failed=self.reader.get_id(first['archive_id'])
        self.assertEqual(failed['reason'],'cohort_source_failed')
        self.assertGreater(failed['retryAfter'],0)
        self.assertEqual(len(self.reader.jobs),1)
        self.assertFalse(list(self.reader.root.glob('*.monitor.json')))
        self.reader.finished[first['archive_id']]-=61
        self.detail.reader=lambda q,c:{'orders':[],'coverage':{'period':q['period'],'paid_complete':True,'missing_payment_time':0,'missing_days':[]},'snapshot_id':'retry','as_of':datetime.now(SHANGHAI).isoformat()}
        retry=self.reader.get_id(first['archive_id'])
        self.assertEqual(retry['status'],'pending')
        next(iter(self.reader.jobs.values()))[0].result()

    def test_archive_id_rejects_tampered_query(self):
        first=self.reader.get(self.q)
        next(iter(self.reader.jobs.values()))[0].result()
        path=self.reader.root/(first['archive_id']+'.query.json')
        data=json.loads(path.read_text('utf-8'));data['start']=(self.today-timedelta(days=39)).isoformat()
        atomic(path,data)
        with self.assertRaises(ValueError):self.reader.get_id(first['archive_id'])

    def test_missing_identity_not_completed(self):
        original=self.detail.reader
        def missing(q,c):
            data=original(q,c);data['orders'][0]['customer_key']=None;return data
        self.detail.reader=missing
        self.reader.get(self.q,action='create')
        next(iter(self.reader.jobs.values()))[0].result()
        result=self.reader.get(self.q)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['monitor']['state'],'needs_review')

    def test_unmatched_and_identity_missing_orders_form_partial_stable_subset(self):
        def source(q,c):
            rows=[{'id':'MATCHED-NEW','customer_key':'ANON-1','paid_at':self.start+'T10:00:00+08:00','site_group':'main','platform':'PS'},
                  {'id':'UNMATCHED','customer_key':'ANON-2','paid_at':self.start+'T11:00:00+08:00','site_group':'main','platform':'PS'},
                  {'id':'NEW-NO-KEY','customer_key':None,'paid_at':self.start+'T12:00:00+08:00','site_group':'main','platform':'PS'}]
            return {'orders':rows,'coverage':{'period':q['period'],'paid_complete':True,
                'missing_payment_time':0,'missing_days':[]},'snapshot_id':'synthetic-complete',
                'as_of':datetime.now(SHANGHAI).isoformat()}
        flags=[{'order_hash':hashlib.sha256(ident.encode()).hexdigest(),'flag':'new','payment_day':self.start}
            for ident in ('MATCHED-NEW','NEW-NO-KEY')]
        self.detail.reader=source
        with patch('cohort_es_source.archive_for',return_value={'status':'available','rows':flags,
                'source_version':'synthetic-es','coverage':{'file_set_complete':True}}):
            first=self.reader.get(self.q)
            next(iter(self.reader.jobs.values()))[0].result()
        value=self.reader.get_id(first['archive_id'])
        self.assertEqual(value['status'],'partial')
        self.assertEqual(value['members'],1)
        self.assertEqual(value['coverage']['unmatched_es_orders'],1)
        self.assertEqual(value['coverage']['excluded_es_new_identity_orders'],1)
        self.assertIn('未匹配订单',value['coverage']['member_basis'])
        self.assertTrue((self.reader.root/(first['archive_id']+'.aggregate.json')).exists())
        self.assertNotIn('ANON-',json.dumps(value))

    def test_partial_recheck_preserves_previously_frozen_members(self):
        first=self.reader.get(self.q,action='create')
        next(iter(self.reader.jobs.values()))[0].result()
        self.assertEqual(self.reader.get_id(first['archive_id'])['members'],1)
        original=self.detail.reader
        def expanded(q,c):
            value=original(q,c)
            value['orders'].append({'id':'NEW-LATE','customer_key':'ANON-LATE',
                'paid_at':self.start+'T13:00:00+08:00','site_group':'main','platform':'PS'})
            value['orders'].append({'id':'UNMATCHED-LATE','customer_key':'ANON-OTHER',
                'paid_at':self.start+'T14:00:00+08:00','site_group':'main','platform':'PS'})
            value['snapshot_id']='synthetic-second-capture'
            return value
        self.detail.reader=expanded
        flags=[{'order_hash':hashlib.sha256(ident.encode()).hexdigest(),'flag':'new','payment_day':self.start}
            for ident in ('ORDER-PRIVATE','ORDER-OTHER-SITE','NEW-LATE')]
        with patch('cohort_es_source.archive_for',return_value={'status':'available','rows':flags,
                'source_version':'synthetic-es-second','coverage':{'file_set_complete':True}}):
            value=self.reader.capture(checked_query(self.q),first['archive_id'])
        self.assertEqual(value['members'],1)
        self.assertEqual(value['status'],'partial')
        self.assertTrue(value['coverage']['source_complete'])

    def test_failure_persists_next_due(self):
        self.detail.reader=lambda q,c:(_ for _ in ()).throw(ValueError('source_failed'))
        self.reader.get(self.q,action='create')
        with self.assertRaises(ValueError):next(iter(self.reader.jobs.values()))[0].result()
        monitor=next(self.reader.root.glob('*.monitor.json'))
        state=json.loads(monitor.read_text('utf-8'))
        self.assertEqual(state['last_status'],'failed')
        self.assertGreater(datetime.fromisoformat(state['next_due']),datetime.now(SHANGHAI))

    def test_selected_window_and_read_id(self):
        first=self.reader.get(dict(self.q,window_days=7),action='create')
        next(iter(self.reader.jobs.values()))[0].result()
        result=self.reader.get_id(first['archive_id'])
        self.assertEqual([w['days'] for w in result['windows']],[7])
        self.assertEqual(result['monitor']['window_days'],7)

    def test_d4_generic_main_site_uses_pseudonymous_paid_source(self):
        q=dict(self.q,profile='D4')
        hashed=hashlib.sha256(b'ORDER-PRIVATE').hexdigest()
        def source(args):
            period={'start':args['start']+' 00:00','end':
                (datetime.fromisoformat(args['end'])+timedelta(days=1)).date().isoformat()+' 00:00'}
            return {'kind':'cohort_paid_orders','status':'available','query':args,
                'orders':[{'id':hashed,'id_is_hashed':True,'customer_key':'ANON-D4',
                    'paid_at':self.start+'T10:00:00+08:00','site_group':'main','platform':'all'}],
                'coverage':{'period':period,'paid_complete':True,'missing_payment_time':0,'missing_days':[]},
                'snapshot_id':'synthetic-d4','as_of':datetime.now(SHANGHAI).isoformat()}
        with patch('cohort_paid_source.read_service',side_effect=source):
            self.reader.get(q,action='create')
            next(iter(self.reader.jobs.values()))[0].result()
        value=self.reader.get(q)
        self.assertEqual(value['members'],1)
        self.assertEqual(value['scope']['profile'],'D4')
        self.assertNotIn('ANON-D4',json.dumps(value))
        with self.assertRaises(ValueError):checked_query(dict(q,site_group='all'))


if __name__=='__main__':unittest.main()
