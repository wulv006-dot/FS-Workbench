from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'source'))
from customer_tracking import Store,AdminService
from tracking_controller import TrackingController
from tracking_readonly import _database


class ReadOnlyTrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name)
        self.allowed=True
        self.admin=AdminService(self.store,lambda user:self.allowed and user in ('admin-a','admin-b'))
        self.controller=SimpleNamespace(store=self.store,admin=self.admin,
            _poll_scan=Mock(side_effect=AssertionError('scan must not run')),
            _poll_history=Mock(side_effect=AssertionError('history must not run')),
            _queue_reports=Mock(side_effect=AssertionError('reports must not run')),
            client=Mock(read=Mock(side_effect=AssertionError('upstream must not run'))))
        self.day='2026-10-13'
        self.row={'order_no':'FIXTURE-1','email':'fixture@example.test','site_id':266,'gid':1327,
            'pay_status':1,'paid_at':'2026-10-13 23:00:00','order_usd':'600','identity_status':'verified','uid':0}
        self.store.save_candidates(self.day,[self.row],coverage={'complete':True})
        candidate=self.store.candidates(self.day)['items'][0]['candidate_id']
        self.track=self.store.track(candidate,'1'*32,owner='admin-a')['tracking_id']
        self.store.observe(self.track,[self.row],coverage={'complete':False})
        self.base={'mode':['hermes'],'structure':['customer_tracking'],'stored_only':['1']}

    def call(self,view,**arguments):
        params={**self.base,'view':[view],**{key:[value] for key,value in arguments.items()}}
        return TrackingController.get(self.controller,'admin-a',params)

    def fingerprint(self):
        return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(self.temp.name).iterdir() if p.is_file()}

    def test_candidates_and_detail_reuse_stored_values_without_refresh_or_writes(self):
        before=self.fingerprint()
        expected=deepcopy(self.store.candidates(self.day));expected['day']=expected.pop('date')
        code,candidates=self.call('candidates',day=self.day)
        self.assertEqual(code,200)
        self.assertEqual(candidates,{**expected,'stored_only':True,'refreshed':False})
        _,detail=self.call('detail',id=self.track)
        self.assertEqual(detail,{**self.store.detail(self.track),'stored_only':True,'refreshed':False})
        self.assertFalse(detail['history_coverage']['complete'])
        self.assertEqual(before,self.fingerprint())
        self.controller._poll_scan.assert_not_called()
        self.controller._poll_history.assert_not_called()
        self.controller._queue_reports.assert_not_called()
        self.controller.client.read.assert_not_called()

    def test_original_http_admin_scope_is_preserved_without_new_owner_filter(self):
        params={**self.base,'view':['detail'],'id':[self.track]}
        code,value=TrackingController.get(self.controller,'admin-b',params)
        self.assertEqual(code,200)
        self.assertEqual(value['owner'],'admin-a')
        with self.assertRaises(PermissionError):
            TrackingController.get(self.controller,'member',params)
        self.allowed=False
        with self.assertRaises(PermissionError):self.call('detail',id=self.track)

    def test_unknown_fields_and_invalid_original_ids_dates_are_rejected(self):
        cases=[{**self.base,'view':['detail'],'id':['../tracking.db']},
               {**self.base,'view':['candidates'],'day':['2026-02-30']},
               {**self.base,'view':['candidates'],'day':[self.day],'owner':['admin-a']},
               {**self.base,'view':['detail'],'id':[self.track],'refresh':['1']},
               {**self.base,'view':['detail'],'id':[self.track,self.track]},
               {**self.base,'view':['detail'],'id':[self.track],'stored_only':['0']}]
        for params in cases:
            with self.subTest(params=params),self.assertRaises(ValueError):
                TrackingController.get(self.controller,'admin-a',params)

    def test_pending_missing_and_failed_sources_remain_distinct(self):
        _,missing=self.call('candidates',day='2026-10-14')
        self.assertEqual(missing['status'],'unavailable')
        self.store.begin_scan('2026-10-14','2'*32)
        _,pending=self.call('candidates',day='2026-10-14')
        self.assertEqual(pending['status'],'pending')
        with self.store.db() as db:
            db.execute("UPDATE scan_jobs SET state='failed',reason='source_unavailable' WHERE day=?",('2026-10-14',))
        _,failed=self.call('candidates',day='2026-10-14')
        self.assertEqual(failed['status'],'failed')
        self.assertEqual(failed['reason'],'source_unavailable')
        with self.assertRaises(LookupError):self.call('detail',id='f'*32)

    def test_sqlite_is_readonly_and_existing_store_is_not_replaced(self):
        original=self.controller.store
        with _database(self.store.path) as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM tracks')
        self.call('detail',id=self.track)
        self.assertIs(self.controller.store,original)
        self.assertIs(self.controller.admin,self.admin)
        # The original writer remains available after the separate read connection closes.
        self.store.stop(self.track,'3'*32,'admin-a')
        self.assertEqual(self.store.detail(self.track)['status'],'paused')

    def test_existing_publisher_includes_readonly_helper_and_composed_import(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('tracking_readonly_release_scope',HERE/'deploy/release_scope.py')
        scope=importlib.util.module_from_spec(spec);spec.loader.exec_module(scope)
        self.assertEqual(scope.TARGETS['source/tracking_readonly.py'],'/opt/fs-hermes-fc/tracking_readonly.py')
        self.assertIn('/opt/fs-hermes-fc/tracking_readonly.py',scope.NEW_ALLOWED)
        self.assertTrue((HERE/'source/tracking_readonly.py').is_file())
        bridge=ast.parse((HERE/'deploy/release_bridge.py').read_text('utf-8'))
        program=next(n.value for n in ast.walk(bridge) if isinstance(n,ast.Assign)
            and any(isinstance(target,ast.Name) and target.id=='program' for target in n.targets))
        text=ast.literal_eval(program)
        self.assertIn('import customer_tracking,tracking_controller,tracking_tool,pool_reports,tracking_readonly',text)
        self.assertIn("Path(tracking_readonly.__file__).resolve()==candidate/'tracking_readonly.py'",text)
        self.assertIn('assert callable(tracking_readonly.stored_get)',text)
        prepare=(HERE/'deploy/prepare_release.py').read_text('utf-8')
        self.assertIn("EXPECTED['source/tracking_readonly.py']=None",prepare)


if __name__=='__main__':unittest.main()
