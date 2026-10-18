from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from cohort_reader import CohortReader, SHANGHAI, checked_query, refresh_registered


def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data),'utf-8')


class ReaderTests(unittest.TestCase):
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

    def tearDown(self):
        self.pool.shutdown();self.stub.stop();self.tmp.cleanup()

    def test_create_freeze_archive_and_scope(self):
        self.assertEqual(self.reader.get(self.q,create=False)['reason'],'observation_not_started')
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
        self.assertEqual(self.reader.get(self.q)['reason'],'customer_flag_not_verified')

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

    def test_plain_tool_read_does_not_create(self):
        self.assertEqual(self.reader.get(self.q)['reason'],'observation_not_started')
        self.assertEqual(self.reader.jobs,{})

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


if __name__=='__main__':unittest.main()
