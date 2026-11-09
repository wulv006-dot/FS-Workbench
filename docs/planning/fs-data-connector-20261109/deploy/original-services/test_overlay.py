"""Exercise the exact observed-source overlays in isolated local stores."""
import ast
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
PACKAGE=HERE/'package-cb87b490-final'
FS=REPO/'releases/fs-dashboard'
sys.path[:0]=[str(PACKAGE/'candidate/runtime'),str(PACKAGE/'candidate/http'),str(PACKAGE),
    str(FS/'hermes-conversation-20261018/source'),str(FS/'hermes-fc-pilot-20261013'),
    str(FS/'hermes-generic-data-20261018/source'),str(FS/'fs-business-baseline-20261021/source/hermes')]
import customer_tracking
import tracking_controller
import tracking_readonly
import tracking_tool
import pool_reports
import customer_reports
import conversation_http
import conversation_readonly


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=customer_tracking.Store(self.temp.name)
        self.row={'order_no':'ORDER-20261109-000000001','email':'fixture@example.test','uid':0,
            'site_id':266,'gid':1327,'pay_status':1,'paid_at':'2026-11-08T01:00:00+00:00',
            'order_usd':'600.10','discount_usd':None,'identity_status':'verified'}
        candidate=self.store.save_candidates('2026-11-08',[self.row])['items'][0]['candidate_id']
        self.track=self.store.track(candidate,'a'*32,owner='fixture-admin')['tracking_id']
        self.store.observe(self.track,[self.row],coverage={'complete':False,'source_total':10,'received':1})

    def test_actual_imports_are_the_reviewed_overlay_modules(self):
        for module in (customer_tracking,tracking_controller,tracking_readonly,tracking_tool,pool_reports,customer_reports):
            self.assertEqual(Path(module.__file__).resolve(),(PACKAGE/'candidate/runtime'/(module.__name__+'.py')).resolve())
        for module in (conversation_http,conversation_readonly):
            self.assertEqual(Path(module.__file__).resolve(),(PACKAGE/'candidate/http'/(module.__name__+'.py')).resolve())

    def test_actual_live_domain_detail_and_anonymous_calculation_are_preserved(self):
        import build
        before=(PACKAGE/'before/runtime/customer_tracking.py').read_text('utf-8')
        after=(PACKAGE/'candidate/runtime/customer_tracking.py').read_text('utf-8')
        for name in ('Store.detail','Store.observe','Store.candidates','AdminService.get','AdminService._admin'):
            self.assertEqual(build.symbol(before,name)[1],build.symbol(after,name)[1])
        before=(PACKAGE/'before/runtime/tracking_tool.py').read_text('utf-8')
        after=(PACKAGE/'candidate/runtime/tracking_tool.py').read_text('utf-8')
        self.assertEqual(build.symbol(before,'anonymous_snapshot')[1],build.symbol(after,'anonymous_snapshot')[1])
        detail=self.store.detail(self.track);snapshot=tracking_tool.customer_snapshot(detail)
        self.assertEqual(snapshot['status'],'partial');self.assertFalse(snapshot['history_coverage']['complete'])
        self.assertEqual(snapshot['email'],self.row['email']);self.assertEqual(snapshot['uid'],0)
        self.assertEqual(snapshot['orders'][0]['order_no'],self.row['order_no'])
        self.assertEqual(snapshot['orders'][0]['order_usd'],'600.10')

    def test_stored_read_does_not_poll_or_observe_and_preserves_admin_scope(self):
        controller=SimpleNamespace(store=self.store,admin=customer_tracking.AdminService(self.store,lambda u:u in ('fixture-admin','other-admin')))
        for method in ('_poll_scan','_poll_history','_queue_reports'):
            setattr(controller,method,Mock(side_effect=AssertionError('must not run')))
        params={'mode':['hermes'],'structure':['customer_tracking'],'stored_only':['1'],
                'view':['detail'],'id':[self.track]}
        before={p.name:p.read_bytes() for p in Path(self.temp.name).iterdir() if p.is_file()}
        code,value=tracking_controller.TrackingController.get(controller,'other-admin',params)
        self.assertEqual(code,200);self.assertTrue(value['stored_only']);self.assertFalse(value['refreshed'])
        self.assertEqual(value['email'],self.row['email'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in Path(self.temp.name).iterdir() if p.is_file()})
        with self.assertRaises(PermissionError):tracking_controller.TrackingController.get(controller,'member',params)

    def test_1000_normal_length_order_ids_preserve_original_report_capacity_and_totals(self):
        detail=self.store.detail(self.track)
        detail['orders']=[dict(self.row,order_no='ORDER-20261109-'+str(i).zfill(9)) for i in range(1000)]
        detail['history_coverage']={'complete':True,'source_total':1000,'received':1000}
        class Conversation:
            prompt=''
            def create(self,user):return {'conversation_id':'b'*32}
            def submit(self,user,cid,text,rid):self.prompt=text;return {'turn_id':'c'*32,'state':'queued'}
        conversation=Conversation()
        with patch.object(self.store,'detail',return_value=deepcopy(detail)):
            evidence=pool_reports.pool_evidence(self.store)
            result=pool_reports.PoolReports(conversation,self.store).generate('fixture-admin','d'*32)
        row=evidence['customers'][0]
        self.assertEqual(sum(g['paid_orders'] for g in row['groups']),1000)
        self.assertEqual(row['email'],self.row['email']);self.assertEqual(row['uid'],0)
        self.assertEqual(row['customer_ref'],self.track)
        self.assertLess(len(conversation.prompt),12000);self.assertEqual(result['customer_count'],1)
        old_prompt=customer_reports.report_prompt(detail,0)
        self.assertIn(self.row['email'],old_prompt);self.assertIn(self.track,old_prompt)
        self.assertLess(len(old_prompt),12000)
        self.assertEqual(len(tracking_tool.customer_snapshot(detail)['orders']),1000)

    def test_original_fenced_restart_refreshes_cached_worker_schema_then_range(self):
        tree=ast.parse((PACKAGE/'release.py').read_text('utf-8'))
        outer=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='load_base')
        node=next(n for n in outer.body if isinstance(n,ast.FunctionDef) and n.name=='restart')
        module=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]));calls=[]
        base=SimpleNamespace(DEEP_SCOPE='original-range-scope',HERMES_WORKER_SCOPE='original-worker-scope',guards=Mock())
        release=SimpleNamespace(software_restart=lambda b,old,m,f:calls.append(m['scope']),running_worker=Mock())
        namespace={'base':base,'release':release,'original_restart':object()}
        exec(compile(module,'reviewed-release-restart','exec'),namespace)
        fence=SimpleNamespace(stop_then_unlock_database=Mock(),root=Path('/'))
        namespace['restart']({'scope':'delta'},fence)
        self.assertEqual(calls,['original-worker-scope','original-range-scope']);fence.stop_then_unlock_database.assert_called_once()
        release.running_worker.assert_called_once();base.guards.assert_called_once()
        with self.assertRaises(ValueError):namespace['restart']({'scope':'delta'},None)


def load_tests(loader,tests,pattern):
    for name,path in (
        ('overlay_tracking_readonly',FS/'hermes-customer-lifecycle-20261019/tests/test_readonly.py'),
        ('overlay_conversation_readonly',FS/'hermes-conversation-20261018/tests/test_conversation_readonly.py')):
        spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        tests.addTests(loader.loadTestsFromModule(module))
    return tests


if __name__=='__main__':unittest.main()
