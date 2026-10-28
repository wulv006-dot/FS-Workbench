"""Real marketing cache/query functions; no live collection or service writes."""
import ast
from concurrent.futures import Future
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SOURCE=Path(__file__).resolve().parents[1]/'source/marketing_range_api.py'
TZ=timezone(timedelta(hours=8))
class Clock(datetime):
    @classmethod
    def now(cls,tz=None):return cls(2026,10,28,12,tzinfo=TZ)

def functions(names,ns):
    tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
    tree.body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    exec(compile(tree,str(SOURCE),'exec'),ns)
    return ns

class MarketingTTL(unittest.TestCase):
    def test_today_and_future_600_history_keeps_86400(self):
        ns=functions({'ttl'},dict(datetime=Clock,SHANGHAI=TZ))
        self.assertEqual(ns['ttl']('2026-10-28'),600)
        self.assertEqual(ns['ttl']('2026-10-29'),600)
        self.assertEqual(ns['ttl']('2026-10-27'),86400)

    def test_real_cache_expires_exactly_at_today_600_and_history_86400(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'range.json'
            ns=functions({'ttl','cached'},dict(datetime=Clock,SHANGHAI=TZ,
                time=SimpleNamespace(time=lambda:1000000),json=json,
                RULE_VERSION='rule',GAME_VERSION='game',cache_path=lambda *a:path,
                project_cached_content=lambda value,*args:value))
            with patch.dict(sys.modules,daily_archive=SimpleNamespace(read=lambda *args:None)):
                for end,bound in [('2026-10-28',600),('2026-10-27',86400)]:
                    value=dict(start=end,end=end,status='available',validated_day='2026-10-28',
                        period=dict(rule_version='rule',game_projection_version='game'))
                    path.write_text(json.dumps(value),encoding='utf-8')
                    os.utime(path,(1000000-bound+1,1000000-bound+1))
                    self.assertEqual(ns['cached'](end,end),value)
                    os.utime(path,(1000000-bound,1000000-bound))
                    self.assertIsNone(ns['cached'](end,end))

    def test_refresh_bypasses_existing_cache_and_keeps_original_job_path(self):
        previous=dict(status='available',marker='old')
        fresh=dict(status='available',marker='fresh')
        future=Future();future.set_result(fresh)
        submit=Mock(return_value=future);run=Mock()
        ns=functions({'query','ttl'},dict(datetime=Clock,SHANGHAI=TZ,
            POOL=SimpleNamespace(submit=submit),LOCK=RLock(),JOBS={},BUSY=None,
            validate=Mock(),cached=Mock(return_value=previous),run=run,run_links=Mock(),
            time=SimpleNamespace(monotonic=lambda:1000)))
        self.assertEqual(ns['query']('2026-10-28','2026-10-28'),(200,previous))
        submit.assert_not_called()
        self.assertEqual(ns['query']('2026-10-28','2026-10-28',refresh=True),(200,fresh))
        submit.assert_called_once_with(run,'2026-10-28','2026-10-28')
        self.assertEqual(previous,dict(status='available',marker='old'))

    def test_preserved_live_links_hotfix_uses_direct_admin(self):
        request=Mock();collect=Mock(return_value={'status':'available'})
        ns=functions({'run_links'},dict())
        with patch.dict(sys.modules,dc_admin=SimpleNamespace(request=request),admin_links=SimpleNamespace(collect=collect)):
            self.assertEqual(ns['run_links']('2026-10-01','2026-10-27'),{'status':'available'})
        collect.assert_called_once_with(request,'2026-10-01','2026-10-27')

if __name__=='__main__':unittest.main()
