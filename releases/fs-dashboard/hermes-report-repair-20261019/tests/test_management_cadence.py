import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime, date, timezone, timedelta
import types
import unittest

ROOT=Path(__file__).resolve().parents[4]
SOURCE=ROOT/'releases/fs-dashboard/hermes-report-repair-20261019/source'
sys.path[:0]=[str(SOURCE),str(ROOT/'releases/fs-dashboard/hermes-fc-pilot-20261013')]
if sys.platform=='win32':sys.modules.setdefault('fcntl',types.SimpleNamespace())
import management_context as m
import nightly as n


class CadenceTests(unittest.TestCase):
    def test_monday_only_and_closed_week_cross_month(self):
        sh=timezone(timedelta(hours=8))
        before=n.due(datetime(2026,11,2,2,29,tzinfo=sh))
        self.assertNotIn('management_weekly',[x['kind'] for x in before])
        after=n.due(datetime(2026,11,2,2,30,tzinfo=sh))
        week=next(x for x in after if x['kind']=='management_weekly')
        self.assertEqual((week['start'],week['end']),('2026-10-26','2026-11-01'))
        self.assertNotIn('management_weekly',[x['kind'] for x in n.due(datetime(2026,11,3,3,tzinfo=sh))])
        self.assertEqual(n.due(datetime(2026,11,2,7,tzinfo=sh)),[])
        self.assertEqual({k:v.isoformat() for k,v in n.STARTS.items() if k in ('daily','weekly','monthly')},
                         {'daily':'00:45:00','weekly':'01:45:00','monthly':'03:15:00'})

    def test_plain_brief_preserved_and_bound_without_old_json(self):
        facts={'snapshotId':'management-'+'a'*24,'businessDate':'2026-10-19','validUntil':'2026-10-20T00:00:00+08:00'}
        text='经营进度保持领先，但综合组略低于时间进度。今天先核查落后项目的有效订单及承接问题，再决定是否补充资源。'
        result={'output_format':'text','research_text':text,'management_context':{'snapshotId':facts['snapshotId'],'evidenceId':'ev_'+'b'*24}}
        value=m.analysis_from_result(result,facts,'task',datetime.now(m.SH))
        self.assertEqual(value['status'],'succeeded');self.assertEqual(value['summary'],text)
        result['management_context']['snapshotId']='other'
        self.assertEqual(m.analysis_from_result(result,facts,'task',datetime.now(m.SH))['status'],'needs_review')
        result['research_text']='<!doctype html><html>full report</html>'
        self.assertEqual(m.analysis_from_result(result,facts,'task',datetime.now(m.SH))['status'],'needs_review')

    def test_scheduled_questions_and_weekly_never_replace_daily(self):
        now=datetime(2026,11,2,3,tzinfo=m.SH)
        facts={'contract':'fs-management-daily-v2','businessDate':'2026-11-02','snapshotId':'management-'+'a'*24,
               'projects':[{'month':{'values':{'rev':100}}}]}
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'public.json';path.write_text(json.dumps(facts),'utf-8')
            daily=m.scheduled_question(now,path);weekly=m.scheduled_weekly_question(now,path)
            self.assertTrue(daily.startswith(m.MARKER));self.assertIn('不生成HTML',daily)
            self.assertTrue(weekly.startswith(m.WEEKLY_MARKER));self.assertIn('完整离线交互HTML',weekly)
            body={'mode':'investigation','question':weekly,'start':'2026-10-26','end':'2026-11-01'}
            self.assertEqual(m.request_snapshot(body),facts['snapshotId'])
            self.assertFalse(m.publish(body,{},'weekly',root=Path(td),public=path,now=now))
            self.assertEqual(json.loads(path.read_text('utf-8')),facts)


if __name__=='__main__':unittest.main()
