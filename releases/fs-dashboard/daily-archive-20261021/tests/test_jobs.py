import ast
from concurrent.futures import Future
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SOURCE=Path(__file__).resolve().parents[1]/'source';sys.path.insert(0,str(SOURCE))
import archive_jobs as jobs
import daily_archive as archive


def functions(path,names,namespace):
    tree=ast.parse((SOURCE/path).read_text(encoding='utf-8'))
    tree.body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    exec(compile(tree,str(path),'exec'),namespace)
    return namespace


class Jobs(unittest.TestCase):
    def test_daily_presets_exclude_today_and_history_stops_at_september(self):
        profiles={'FC27':('FC27','FC27',1322,1327,'sports')}
        daily=list(jobs.candidates(date(2026,10,22),profiles,True))
        self.assertEqual([(r['start'],r['end']) for r in daily if r.get('mode')=='summary'],
            [('2026-10-21','2026-10-21'),('2026-10-15','2026-10-21'),('2026-09-22','2026-10-21')])
        history=list(jobs.candidates(date(2026,10,22),profiles,False))
        self.assertEqual(min(r['start'] for r in history),'2026-09-01')
        self.assertEqual(max(r['end'] for r in history),'2026-10-21')
        self.assertEqual(min(r['start'] for r in jobs.candidates(date(2027,1,22),profiles,False)),'2026-10-22')

    def test_busy_source_defers_and_persists_original_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);store=archive.Archive(root)
            args=dict(mode='summary',profile='FC27',start='2026-10-20',end='2026-10-20')
            def atomic(path,value):path.write_bytes(archive.encoded(value))
            with patch.object(jobs,'ROOT',root),patch.object(jobs,'Archive',return_value=store),patch.object(jobs,'profiles',return_value={}),patch.object(jobs,'candidates',return_value=iter([args])),patch.object(jobs,'atomic',side_effect=atomic),patch.object(jobs,'read_route',return_value=(429,{'status':'busy'})) as read:
                result=jobs.run_once(True,5)
                self.assertEqual(result['reason'],'busy');self.assertEqual(read.call_count,1)
                state=list(__import__('json').loads((root/'scheduler-state.json').read_text()).values())[0]
                self.assertEqual(state['query'],args);self.assertTrue(state['requestedAt'])
                self.assertGreater(state['retryAfter'],0)

    def test_marketing_archive_returns_immediately_while_busy(self):
        from threading import RLock
        value={'status':'available','archive':{'sourceCapturedAt':'2026-10-01T00:00:00Z'}}
        future=Future()
        ns=functions('marketing_range_api.py',{'query'},dict(datetime=datetime,timezone=timezone,SHANGHAI=archive.TZ,
            time=__import__('time'),POOL=Mock(submit=Mock()),LOCK=RLock(),JOBS={},BUSY=future,validate=Mock(),cached=Mock(return_value=value),ttl=lambda _:86400,run=Mock(),run_links=Mock()))
        code,result=ns['query']('2026-10-01','2026-10-01')
        self.assertEqual(code,200);self.assertTrue(result['archive']['refreshDeferred'])
        ns['POOL'].submit.assert_not_called()

    def test_native_archive_preserves_query_validation_and_explicit_refresh(self):
        q={'profile':'FC27','start':'2026-10-20','end':'2026-10-20','grain':'day','baseSnapshotId':'new'}
        live=Mock(return_value=(202,{'status':'pending'}))
        ns=functions('range_api.py',{'get_range'},dict(datetime=datetime,timezone=timezone,PROFILE_MAP={'FC27':[1322]},query=Mock(return_value=q),snapshot=Mock(return_value={}),get_range_live=live))
        with patch.object(archive,'read',return_value={'archive':{'sourceCapturedAt':datetime.now(timezone.utc).isoformat()}}):
            code,result=ns['get_range']({'profile':['FC27']})
            self.assertEqual(code,200);self.assertEqual(result['query'],q);live.assert_not_called()
            self.assertEqual(ns['get_range']({'profile':['FC27'],'refresh':['true']})[0],202)
            self.assertTrue(live.call_args.kwargs['force'])
        with self.assertRaises(ValueError):ns['get_range']({'refresh':['false']})
        ns['query'].side_effect=LookupError('catalog_changed')
        with self.assertRaises(LookupError):ns['get_range']({'profile':['FC27']})


if __name__=='__main__':unittest.main()
