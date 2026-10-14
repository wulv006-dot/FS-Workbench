from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from test_fc_detail import FCDetails, CFG, data, row

ROOT=Path(__file__).resolve().parent
WIRE="\n".join(s for s in (ROOT/'candidate/range_api.py').read_text().splitlines()
               if s.startswith(('FC_POOL=','FC_DETAIL=')))

class DedicatedFCQueue(unittest.TestCase):
    def test_legacy_queue_cannot_hold_fc_snapshot(self):
        release=threading.Event()
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as legacy:
            blocked=legacy.submit(release.wait)
            calls=[]
            def reader(q,c):
                calls.append(q)
                return {**data([row(1)]),'coverage':{'period':q['period']}}
            context={'ThreadPoolExecutor':ThreadPoolExecutor,'POOL':legacy,'CACHE':Path(folder),
                     'FCDetails':lambda p,c:FCDetails(p,c,reader,CFG)}
            exec(WIRE,context)
            fc=context['FC_DETAIL'];fc_pool=context['FC_POOL']
            try:
                params={'mode':['fc-detail'],'profile':['FC27'],'start':['2026-10-11'],'end':['2026-10-11']}
                self.assertEqual(fc.get(params)[0],202)
                fc_pool.submit(lambda:None).result(timeout=2)
                self.assertFalse(blocked.done())
                self.assertEqual(fc.get(params)[0],200)
                self.assertEqual(len(calls),1)
                self.assertIsNot(fc.pool,legacy)
            finally:
                release.set();fc_pool.shutdown()

    def test_one_running_one_queued_and_original_third_request_guard(self):
        release,started=threading.Event(),threading.Event()
        def reader(q,c):
            started.set();release.wait(3)
            return {**data([row(1)]),'coverage':{'period':q['period']}}
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool:
            fc=FCDetails(pool,folder,reader,CFG)
            try:
                params={'mode':['fc-detail'],'profile':['FC27'],'start':['2026-10-11'],'end':['2026-10-11']}
                self.assertEqual(fc.get(params)[0],202);self.assertTrue(started.wait(1))
                self.assertEqual(fc.get({**params,'start':['2026-10-10']})[0],202)
                self.assertEqual(fc.get({**params,'start':['2026-10-09']})[0],429)
                self.assertEqual(len(fc.jobs),2)
                self.assertEqual(sorted(j['phase'] for j in fc.jobs.values()),['queued','reading'])
            finally:
                release.set()

if __name__=='__main__':
    unittest.main()
