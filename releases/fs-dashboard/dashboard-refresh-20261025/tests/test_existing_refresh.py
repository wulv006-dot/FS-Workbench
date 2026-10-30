import copy, sys, unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'source'))
from live_summary import SummaryCache, query, key_of, SHANGHAI

PROFILES={'FC27':(None,'FC27')}
PARAMS={'mode':['summary'],'profile':['FC27'],'start':['2026-10-15'],'end':['2026-10-15']}
NOW=datetime(2026,10,15,16,30,tzinfo=SHANGHAI)

class Pool:
    def __init__(self): self.jobs=[]
    def submit(self, fn, *args): self.jobs.append((fn,args))
    def drain(self):
        jobs,self.jobs=self.jobs,[]
        for fn,args in jobs: fn(*args)

class RefreshTest(unittest.TestCase):
    def cache(self):
        self.now=0;self.reads=[];self.failure=None
        def read(q):
            self.reads.append(copy.deepcopy(q))
            if self.failure: raise self.failure
            return {'status':'available','period':q['period'],'capturedAt':datetime.now(timezone.utc).isoformat(), 'currency':'USD','metrics':{}}
        c=SummaryCache(read,read,PROFILES,clock=lambda:self.now)
        c.close();c.pools={n:Pool() for n in c.readers}
        return c
    def drain(self,c):
        for p in c.pools.values():p.drain()
    def test_force_same_key_new_cutoff_once_and_no_pending_duplicate(self):
        c=self.cache();q=query(PARAMS,PROFILES,NOW)
        self.assertEqual(c.get(q)[0],202);self.drain(c)
        self.assertFalse(c.get(q)[1]['stale']);self.assertEqual(len(self.reads),2)
        forced=query({**PARAMS,'refresh':['true']},PROFILES,NOW.replace(minute=31))
        self.assertEqual(key_of(forced),key_of(q));c.get(forced);c.get(forced)
        self.assertEqual(sum(len(p.jobs) for p in c.pools.values()),2)
        self.drain(c);status,result=c.get(query(PARAMS,PROFILES,NOW.replace(minute=31)))
        self.assertEqual(status,200);self.assertFalse(result['stale'])
        self.assertEqual(result['profile']['period']['end'],'2026-10-15 16:31')
        self.assertEqual(len(self.reads),4);self.assertTrue(all('refresh' not in q for q in self.reads))
    def test_force_preserves_failure_cooldown_and_denial(self):
        for error,expected in [(OSError('source'),503),(PermissionError('denied'),403)]:
            c=self.cache();self.failure=error;q=query({**PARAMS,'refresh':['true']},PROFILES,NOW)
            c.get(q);self.drain(c)
            self.assertEqual(c.get(q)[0],expected)
            self.assertEqual(sum(len(p.jobs) for p in c.pools.values()),0)
    def test_force_preserves_rate_limit(self):
        c=self.cache();q=query(PARAMS,PROFILES,NOW);c.get(q);self.drain(c)
        for starts in c.starts.values():starts[:]=[0]*6
        self.assertEqual(c.get({**q,'refresh':True})[0],429)
        self.assertEqual(sum(len(p.jobs) for p in c.pools.values()),0)
    def test_today_refreshes_at_ten_minutes_and_history_keeps_its_policy(self):
        c=self.cache();q=query(PARAMS,PROFILES,NOW);c.get(q);self.drain(c)
        self.now=599;self.assertFalse(c.get(q)[1]['stale'])
        self.assertEqual(sum(len(p.jobs) for p in c.pools.values()),0)
        self.now=600;self.assertTrue(c.get(q)[1]['stale'])
        self.assertEqual(sum(len(p.jobs) for p in c.pools.values()),2)
        self.assertEqual(query(PARAMS,PROFILES,NOW.replace(day=16))['cacheSeconds'],604800)
    def test_history_reuses_live_sources_for_seven_days_then_revalidates(self):
        c=self.cache();q=query(PARAMS,PROFILES,NOW.replace(day=16))
        with patch('daily_archive.save'):
            self.assertEqual(c.get_live(q)[0],202);self.drain(c)
        for age in (7201,604799):
            self.now=age;self.assertFalse(c.get_live(q)[1]['stale'])
            self.assertEqual(sum(len(p.jobs) for p in c.pools.values()),0)
        self.now=604800;self.assertTrue(c.get_live(q)[1]['stale'])
        self.assertEqual(sum(len(p.jobs) for p in c.pools.values()),2)
    def test_saved_summary_keeps_original_version_across_new_ttl_and_expires_at_seven_days(self):
        c=self.cache();q=query(PARAMS,PROFILES,NOW.replace(day=16));now=datetime.now(timezone.utc)
        for age in (7201,604799,604800):
            stamp=(now-timedelta(seconds=age)).isoformat()
            old=dict(generatedAt=stamp,query=dict(q,cacheSeconds=7200),sources={'Admin':{'status':'available'}},profile={'value':17})
            with patch('daily_archive.read',return_value=old),patch('daily_archive.derive_summary',return_value=None),patch('daily_archive.save') as save,patch.object(c,'get_live',return_value=(202,{'status':'pending'})) as native,patch('live_summary.datetime',wraps=datetime) as clock:
                clock.now.return_value=now
                code,value=c.get(q)
                self.assertEqual(code,200);self.assertEqual(value['generatedAt'],stamp)
                self.assertEqual(value['query']['cacheSeconds'],604800);save.assert_not_called()
                if age<604800:
                    self.assertFalse(value['stale']);self.assertEqual(value['refreshSeconds'],604800);native.assert_not_called()
                else:self.assertTrue(value['refreshing']);native.assert_called_once()
    def test_invalid_refresh_and_unchanged_other_scope(self):
        for refresh in (['false'],['1'],['true','true']):
            with self.assertRaises(ValueError):query({**PARAMS,'refresh':refresh},PROFILES,NOW)
        with self.assertRaises(ValueError):query({**PARAMS,'profile':['D4']},PROFILES,NOW)
        q=query(PARAMS,PROFILES,NOW)
        self.assertNotIn('refresh',q);self.assertEqual(q['cacheSeconds'],600)

if __name__=='__main__':unittest.main()
