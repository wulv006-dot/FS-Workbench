from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
BOSS=REPO/'releases/fs-dashboard/boss-workspaces-20261013'
MARKETING=REPO/'mmoexp_google_data/deployment/server_run_integrated.py'
if not BOSS.exists():
    BOSS=HERE.parent/'boss'
    MARKETING=HERE.parent/'marketing/deployment/server_run_integrated.py'
sys.path.insert(0,str(BOSS/'backend'))
sys.path.insert(0,str(BOSS/'tests'))


class PreparationDeadlineTests(unittest.TestCase):
    def test_management_pending_polling_does_not_sleep_across_deadline(self):
        import management_daily as module
        clock=[0]
        calls=[]
        def read(path):
            calls.append(clock[0]);clock[0]+=10
            return {'http_status':202,'body':{'retryAfter':10}}
        def wait(seconds):clock[0]+=seconds
        module._query(read,'FC27',{'start':'2026-10-01','end':'2026-10-18'},budget=100,deadline=45,
                      monotonic=lambda:clock[0],sleep=wait)
        self.assertEqual(calls,[0,20])
        self.assertLessEqual(clock[0],45)

    def test_game_threads_finish_at_owned_deadline(self):
        import game_intelligence as module
        from nightly_http import Deadline
        end=datetime.now(timezone.utc)+timedelta(seconds=.12)
        def slow(url,hosts,deadline_at=None):
            with Deadline(deadline_at) as control:
                return control.run(lambda:time.sleep(.6))
        started=time.monotonic()
        with patch.object(module,'fetch',side_effect=slow):
            result=module.collect(datetime.now(timezone.utc),deadline_at=end)
        self.assertLess(time.monotonic()-started,.3)
        self.assertEqual(result['documents'],[])

    def test_preparation_timeout_never_starts_model(self):
        from test_boss_daily import DailyTests
        import boss_daily
        fixture=DailyTests('test_inspect_is_read_only_and_schedules_are_shanghai')
        fixture.setUp()
        try:
            fixture.at=fixture.at.replace(hour=6,minute=58,second=55)
            def collect(at,**kwargs):
                self.assertIsNotNone(kwargs.get('deadline_at'))
                fixture.at=fixture.at.replace(hour=6,minute=59,second=0)
                return fixture.batch
            fixture.modules['management'].collect=collect
            result=fixture.runner.run('management','scheduled')
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['error_code'],'nightly_deadline_exceeded')
            self.assertEqual(fixture.calls['provider'],0)
            self.assertEqual(fixture.calls['ledger'],0)
        finally:fixture.doCleanups()

    def test_daytime_scheduled_rejected_but_manual_works(self):
        from test_boss_daily import DailyTests
        fixture=DailyTests('test_inspect_is_read_only_and_schedules_are_shanghai')
        fixture.setUp()
        try:
            fixture.at=fixture.at.replace(hour=12)
            self.assertEqual(fixture.runner.run('game-monitor','scheduled')['status'],'not_due')
            self.assertEqual(fixture.calls['source'],0)
            self.assertEqual(fixture.runner.run('game-monitor','manual')['status'],'succeeded')
            self.assertEqual(fixture.calls['provider'],1)
        finally:fixture.doCleanups()


@unittest.skipUnless(os.name=='posix','requires real POSIX flock and fsync')
class MarketingIdempotencyTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('nightly_marketing_fixture',MARKETING)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'data/verified-readonly').mkdir(parents=True)
        (self.root/'verification-20260930').mkdir()
        self.at=datetime(2026,10,19,2,tzinfo=timezone(timedelta(hours=8)))
        self.calls=[]
        def run(*args,**kwargs):
            self.calls.append(args[0]);return types.SimpleNamespace(returncode=0)
        fixed=self.at
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return fixed.astimezone(tz or timezone.utc)
        self.contexts=[patch.object(self.module,'ROOT',self.root),patch.object(self.module.dt,'datetime',Clock),
                       patch.object(self.module.subprocess,'run',side_effect=run),patch('sys.argv',['fixture','--trigger','scheduled']),
                       patch.dict(os.environ,{'MMOEXP_MARKETING_LIVE':'approved','MMOEXP_MARKETING_PUBLISH':'approved','GOOGLE_APPLICATION_CREDENTIALS':'/etc/mmoexp-marketing/service-account.json'}),
                       patch('sys.stdout',new=io.StringIO())]
        for context in self.contexts:context.start();self.addCleanup(context.stop)

    def test_same_night_terminal_attempt_is_not_recollected_or_republished(self):
        self.module.main();self.module.main()
        self.assertEqual(len(self.calls),6)
        record=json.loads((self.root/'data/verified-readonly/nightly-runs/2026-10-19.json').read_text())
        self.assertEqual(record['phase'],'completed')
        self.assertEqual(record['status'],'succeeded')

    def test_started_attempt_survives_restart_without_replay(self):
        path=self.root/'data/verified-readonly/nightly-runs/2026-10-19.json'
        self.module.atomic_record(path,{'phase':'step_pending','status':'incomplete','steps':{'synthetic':0}})
        self.module.main()
        self.assertEqual(self.calls,[])
        self.assertEqual(json.loads(path.read_text())['status'],'incomplete')


if __name__=='__main__':unittest.main()
