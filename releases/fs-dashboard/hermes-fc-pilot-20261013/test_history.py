from contextlib import contextmanager
import json,sqlite3,tempfile,unittest
from pathlib import Path
from fs_evidence import ReportHistory,SourcePins,attach_owner_history
from research import ResearchBook,tool_schemas
from test_research import dataset

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        path=Path(self.temp.name)/'history.db'
        class Daily:
            @contextmanager
            def db(self):
                conn=sqlite3.connect(path)
                try:
                    with conn:yield conn
                finally:conn.close()
        self.daily=Daily()
        with self.daily.db() as db:
            db.execute('CREATE TABLE reports(job_id INTEGER PRIMARY KEY,day TEXT,content TEXT)')
            for i in range(1,11):
                report={'date':'2026-10-12','revision':i,'report_id':'stored_'+str(i),'main':{'revenue':'10.00'},'deep':{'evidence':[{'ref':'old-period','kind':'period_facts','value':{'revenue_usd':'10.00'},'period':{'start':'2026-10-05','end':'2026-10-11'}}],'decision':{'findings':[{'title':'旧判断','observation':'whole reviewed statement '+('x'*9000),'hypothesis':'competing explanation','refs':['old-period']}]}}}
                db.execute('INSERT INTO reports VALUES(?,?,?)',(i,'2026-10-12',json.dumps(report)))

    def test_versions_are_complete_paged_and_later_appends_do_not_shift_the_boundary(self):
        history=ReportHistory(self.daily);q={'start':'2026-09-28','end':'2026-10-12'}
        first=history.read(q);self.assertEqual(first['pagination']['total_reports'],10);self.assertTrue(first['pagination']['has_more'])
        self.assertEqual(first['reports'][0]['revision'],10);self.assertIn('x'*9000,first['reports'][0]['previous_judgments'][0]['observation'])
        with self.daily.db() as db:db.execute('INSERT INTO reports VALUES(11,?,?)',('2026-10-12','{}'))
        second=history.read(dict(q,page=2));self.assertEqual(second['reports'][0]['revision'],9);self.assertEqual(second['pagination']['total_reports'],10)
        self.assertFalse(history.read(dict(q,page=10))['pagination']['has_more']);self.assertEqual(history.read(dict(q,page=11))['status'],'empty')
        self.assertLess(len(json.dumps(first).encode()),16000)

    def test_report_business_day_is_discoverable_and_not_confused_with_analysis_period(self):
        history=ReportHistory(self.daily);self.assertEqual(history.index['available_days'],[{'day':'2026-10-12','versions':10}])
        book=ResearchBook(dataset(),{}, {'start':'2026-10-05','end':'2026-10-11'},history=SourcePins().wrap(history.read,'history'),history_index=history.index)
        self.assertEqual(book.call('fc.get_data_catalog',{})['data']['history_index']['available_days'][0]['day'],'2026-10-12')
        result=book.call('fc.read_history',{'start':'2026-10-12','end':'2026-10-12'})
        self.assertEqual(result['data']['reports'][0]['readings'][0]['period']['end'],'2026-10-11')
        self.assertNotEqual(result['snapshot_id'],book.capture_id)
        for value in (True,0,-1,'2'):
            with self.assertRaises(ValueError):book.call('fc.read_history',{'start':'2026-10-12','end':'2026-10-12','page':value})
        schema=next(s['function']['parameters'] for s in tool_schemas() if s['function']['name']=='mcp__fcro__fc_read_history')
        self.assertIn('page',schema['properties']);self.assertNotIn('page',schema['required'])

    def test_completed_hermes_versions_are_owner_scoped_paged_and_not_appended_to_daily(self):
        with self.daily.db() as db:
            db.execute('CREATE TABLE requests(id TEXT,owner TEXT,state TEXT,body TEXT,result TEXT)')
            body=json.dumps({'start':'2026-10-05','end':'2026-10-11'})
            for i,owner in enumerate(['owner']*5+['other']):
                result=json.dumps({'summary':'full summary '+str(i),'findings':['x'*18000],'actions':['action'],'reviews':['review'],'limitations':['gap']})
                db.execute('INSERT INTO requests VALUES(?,?,?,?,?)',(str(i),owner,'COMPLETED',body,result))
        daily=ReportHistory(self.daily);book=ResearchBook(dataset(),{}, {'start':'2026-10-05','end':'2026-10-11'},history=daily.read,history_index=daily.index)
        attach_owner_history(book,self.daily,'owner')
        daily_page=book.call('fc.read_history',{'start':'2026-10-12','end':'2026-10-12'})['data']
        self.assertNotIn('hermes_reports',daily_page)
        q={'start':'2026-10-05','end':'2026-10-11','source':'hermes'}
        first=book.call('fc.read_history',q)['data'];self.assertEqual(first['pagination']['total_reports'],5)
        self.assertEqual(first['hermes_reports'][0]['report_id'],'4');self.assertEqual(len(first['hermes_reports']),1)
        with self.daily.db() as db:db.execute('INSERT INTO requests VALUES(?,?,?,?,?)',('later','owner','COMPLETED',body,result))
        second=book.call('fc.read_history',dict(q,page=2))['data'];self.assertEqual(second['hermes_reports'][0]['report_id'],'3');self.assertEqual(second['pagination']['total_reports'],5)
        self.assertEqual(len(second['hermes_reports'][0]['findings'][0]),18000);self.assertLess(len(json.dumps(first)),20000)
        self.assertEqual(book.history_index['hermes']['total_versions'],5)
        self.assertNotIn('other',json.dumps(first));self.assertNotIn('later',json.dumps(second))

if __name__=='__main__':unittest.main()
