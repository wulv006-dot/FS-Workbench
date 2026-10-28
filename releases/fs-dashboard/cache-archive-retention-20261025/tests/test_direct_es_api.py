"""Direct API export keeps the original durable unknown-attempt boundary."""
import ast,hashlib,json,re,sys,tempfile,time,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

SOURCE=Path(__file__).resolve().parents[1]/'source/es_order_structure.py'
tree=ast.parse(SOURCE.read_text('utf-8'))
scope=dict(Path=Path,hashlib=hashlib,json=json,re=re,time=time,datetime=datetime,timezone=timezone,RULE_VERSION='existing-rule',
    checked_query=lambda q:dict(q),SHANGHAI=timezone(timedelta(hours=8)))
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'api_dataset','_server_bundle','retained_bundle','export_bundle','_archived_dataset','cache_seconds','reclaim_projection_slot'}]
from copy import deepcopy
scope['deepcopy']=deepcopy
import threading
scope['threading']=threading
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),scope)
Q={'profile':'FC27','start':'2026-10-27','end':'2026-10-27','group_by':'new_customer','status':'all'}

class DirectES(unittest.TestCase):
    def bundle(self):return {'kind':'es_order_structure_bundle','status':'available','snapshots':[{'query':Q,'value':{'kind':'es_order_structure'}}]}
    def test_success_reuses_cache_and_unknown_attempt_never_regenerates(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);read=Mock(return_value=self.bundle())
            self.assertEqual(scope['_server_bundle'](Q,root,read)['status'],'available')
            scope['_server_bundle'](Q,root,read);read.assert_called_once();self.assertFalse(list(root.glob('*.attempt')))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);read=Mock(side_effect=TimeoutError())
            self.assertIn('unknown',scope['_server_bundle'](Q,root,read)['reason'])
            self.assertIn('unknown',scope['_server_bundle'](Q,root,read)['reason'])
            read.assert_called_once();self.assertEqual(len(list(root.glob('*.attempt'))),1)
    def test_definite_pre_generation_refusal_can_retry_same_period(self):
        with tempfile.TemporaryDirectory() as folder:
            read=Mock(side_effect=[{'kind':'es_order_structure_bundle','status':'unavailable','reason':'api_unavailable','retryable':True,'stage':'not_generated'},self.bundle()])
            with patch.object(time,'time',return_value=1000):scope['_server_bundle'](Q,Path(folder),read)
            self.assertFalse(list(Path(folder).glob('*.attempt')))
            with patch.object(time,'time',return_value=1031):self.assertEqual(scope['_server_bundle'](Q,Path(folder),read)['status'],'available')
            self.assertEqual(read.call_count,2)
    def test_direct_client_generation_is_single_send_and_closes_on_unknown(self):
        client=Mock();client.admin.get.side_effect=[SimpleNamespace(status_code=200,content=b'{"code":1}'),TimeoutError()]
        auth=SimpleNamespace(Session=lambda:client,ADMIN_API='http://127.0.0.1:8912',UA='existing-client')
        def export(manager,args,headers,deadline):
            self.assertIsNone(manager.token);self.assertNotIn('batoken',headers);self.assertTrue(manager.identity_ok(None))
            return manager.request('/admin/order.OrderExcelByEs/downloadsMake',timeout=8)
        with patch.dict(sys.modules,p2pah_auth=auth),patch.dict(scope,export_dataset=export):
            with self.assertRaises(TimeoutError):scope['api_dataset'](Q,time.monotonic()+150)
        self.assertEqual(client.admin.get.call_count,2);client.get_admin.assert_not_called();client.close.assert_called_once()
    def test_direct_identity_refusal_keeps_definite_not_generated_contract(self):
        client=Mock();client.admin.get.return_value=SimpleNamespace(status_code=200,content=b'{"code":401}')
        auth=SimpleNamespace(Session=lambda:client,ADMIN_API='http://127.0.0.1:8912',UA='existing-client')
        def export(manager,args,headers,deadline):return scope['export_bundle'](manager,args,headers,None,deadline=deadline)
        with patch.dict(sys.modules,p2pah_auth=auth),patch.dict(scope,export_dataset=export):
            value=scope['api_dataset'](Q,time.monotonic()+150)
        self.assertEqual((value['kind'],value['stage'],value['retryable']),('es_order_structure_bundle','not_generated',True))
        self.assertEqual(client.admin.get.call_count,1);client.close.assert_called_once()
    def test_export_menu_permission_denial_is_definitely_not_generated(self):
        for status,code in ((401,0),(403,0),(200,401),(200,403)):
            manager=SimpleNamespace(lock=threading.RLock(),token=None,identity_ok=lambda token:True,request=lambda *args,**kwargs:(status,json.dumps({'code':code}).encode()))
            value=scope['export_bundle'](manager,Q,{},None,deadline=time.monotonic()+150)
            self.assertEqual((value['reason'],value['stage'],value['retryable']),('es_export_permission_denied','not_generated',True))
    def test_today_archive_expires_at_600_seconds_but_closed_day_stays_reusable(self):
        today=datetime.now(timezone(timedelta(hours=8))).date().isoformat();q=dict(Q,start=today,end=today)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);raw=b'PKfixture';digest=hashlib.sha256(raw).hexdigest();file=root/(digest+'.xlsx');file.write_bytes(raw);file.chmod(0o600)
            path=root/'manifest.json';value=dict(query=q,captured_at=(datetime.now(timezone.utc)-timedelta(seconds=599)).isoformat(),file_sha256=[digest],file_set={'declared_files':1,'failed_files':0})
            def save():path.write_text(json.dumps(value),encoding='utf-8');path.chmod(0o600)
            with patch.dict(scope,SHANGHAI=timezone(timedelta(hours=8)),MAX_FILE=32*1024*1024,excel_path=lambda root,digest:root/(digest+'.xlsx'),parse_files=lambda files:([],[digest],0),make_dataset=lambda *args:{'_private_dataset':True}):
                save();self.assertIsNotNone(scope['_archived_dataset'](q,root));self.assertEqual(scope['cache_seconds'](today),600)
                value['captured_at']=(datetime.now(timezone.utc)-timedelta(seconds=601)).isoformat();save()
                self.assertIsNone(scope['_archived_dataset'](q,root))
                previous=(datetime.fromisoformat(today)-timedelta(days=1)).date().isoformat();q=dict(q,start=previous,end=previous);value['query']=q;save()
                self.assertIsNotNone(scope['_archived_dataset'](q,root))
    def test_reclaim_never_removes_unknown_attempts_or_incomplete_raw_backing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);read=lambda p:json.loads(p.read_text('utf-8'))
            complete=root/'complete.json';complete.write_text(json.dumps({'saved_at':1,'value':self.bundle()}),encoding='utf-8')
            attempt=root/'original.attempt';attempt.write_text(json.dumps({'query':Q}),encoding='utf-8')
            raw={'status':'available','hashes':['a'*64],'declared_files':1,'failed_files':0,'parse_failures':0}
            with patch.dict(scope,archived_dataset=lambda q:raw):
                self.assertFalse(scope['reclaim_projection_slot'](root,read));self.assertTrue(complete.exists());self.assertTrue(attempt.exists())
            attempt.unlink()
            with patch.dict(scope,archived_dataset=lambda q:dict(raw,failed_files=1)):
                self.assertFalse(scope['reclaim_projection_slot'](root,read));self.assertTrue(complete.exists())
            with patch.dict(scope,archived_dataset=lambda q:raw):self.assertTrue(scope['reclaim_projection_slot'](root,read))
            self.assertFalse(complete.exists())

if __name__=='__main__':unittest.main()
