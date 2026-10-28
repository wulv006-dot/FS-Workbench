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
nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in {'ESReader','api_dataset','_server_bundle','retained_bundle','export_bundle','_archived_dataset','cache_seconds','reclaim_projection_slot','_permission_denial','_receipt_paths','_read_receipt','_permission_recovered','recheck_permission'}]
from copy import deepcopy
scope['deepcopy']=deepcopy
import threading
scope['threading']=threading
scope['SERVER_LOCK']=threading.RLock()
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),scope)
Q={'profile':'FC27','start':'2026-10-27','end':'2026-10-27','group_by':'new_customer','status':'all'}

class DirectES(unittest.TestCase):
    def bundle(self):return {'kind':'es_order_structure_bundle','status':'available','snapshots':[{'query':Q,'value':{'kind':'es_order_structure','quality':{}}}]}
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
            self.assertEqual((value['reason'],value['stage'],value['retryable']),('es_export_permission_denied','not_generated',False))
    def denied(self):return dict(kind='es_order_structure_bundle',status='unavailable',reason='es_export_permission_denied',stage='not_generated',retryable=False)
    def saved(self,root,q=None):
        path=scope['_receipt_paths'](q or Q,root)[0]
        return path,json.loads(path.read_text()),hashlib.sha256(path.read_bytes()).hexdigest()
    def test_permission_denial_persists_without_attempt_and_old_retryable_receipt_upgrades_without_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);read=Mock(return_value=self.denied())
            with patch.object(time,'time',return_value=1000):first=scope['_server_bundle'](Q,root,read)
            self.assertEqual((first['reason'],first['stage'],first['retryable']),('es_export_permission_denied','not_generated',False))
            self.assertFalse(list(root.glob('*.attempt')))
            path,record,_=self.saved(root);record['retryable']=True;record['value']['retryable']=True;record.pop('last_attempt_result')
            path.write_text(json.dumps(record));path.chmod(0o600)
            with patch.object(time,'time',return_value=1000000):again=scope['_server_bundle'](Q,root,read)
            self.assertFalse(again['retryable']);read.assert_called_once()
            _,upgraded,_=self.saved(root);self.assertFalse(upgraded['retryable']);self.assertEqual(upgraded['last_attempt_result']['stage'],'not_generated')
            with patch.object(time,'time',return_value=2000000):scope['_server_bundle'](Q,root,read)
            read.assert_called_once();self.assertFalse(list(root.glob('*.attempt')))
    def test_retained_good_value_is_partial_and_denial_cannot_expire_into_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);read=Mock(side_effect=[self.bundle(),self.denied()])
            with patch.object(time,'time',return_value=1000):scope['_server_bundle'](Q,root,read)
            path,record,_=self.saved(root);record['last_attempt']='temporary_source_failure';record['next_retry_at']=0
            path.write_text(json.dumps(record));path.chmod(0o600)
            with patch.object(time,'time',return_value=100000):value=scope['_server_bundle'](Q,root,read)
            self.assertEqual(value['snapshots'][0]['value']['status'],'partial');self.assertEqual(value['stage'],'not_generated')
            with patch.object(time,'time',return_value=1000000):again=scope['_server_bundle'](Q,root,read)
            self.assertEqual(again['snapshots'][0]['value']['status'],'partial');self.assertFalse(again['retryable'])
            self.assertEqual(read.call_count,2);self.assertFalse(list(root.glob('*.attempt')))
    def test_operator_recheck_same_receipt_cas_preserves_refusal_and_never_clears_unknown_or_missing_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);read=Mock(return_value=self.denied());scope['_server_bundle'](Q,root,read)
            path,record,sha=self.saved(root);success=Mock(return_value=self.bundle())
            with self.assertRaisesRegex(ValueError,'receipt_changed'):scope['recheck_permission'](Q,'0'*64,root,success)
            _,attempt,legacy=scope['_receipt_paths'](Q,root)
            for blocker in (attempt,legacy):
                blocker.write_text(json.dumps({'query':Q}));blocker.chmod(0o600);before=blocker.read_bytes()
                with self.assertRaisesRegex(ValueError,'not_definitely_unsent'):scope['recheck_permission'](Q,sha,root,success)
                self.assertEqual(blocker.read_bytes(),before);blocker.unlink()
            missing=dict(record);missing['value']=dict(record['value']);missing['value'].pop('stage');missing.pop('last_attempt_result')
            path.write_text(json.dumps(missing));path.chmod(0o600);missing_sha=hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError,'not_definitely_unsent'):scope['recheck_permission'](Q,missing_sha,root,success)
            scope['_server_bundle'](Q,root,success);self.assertNotIn('stage',json.loads(path.read_text())['value']);success.assert_not_called()
            path.write_text(json.dumps(record));path.chmod(0o600);sha=hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(scope['recheck_permission'](Q,sha,root,success)['status'],'available');success.assert_called_once()
            _,restored,_=self.saved(root);self.assertEqual(restored['permission_denial']['receipt_sha256'],sha)
            self.assertEqual(restored['permission_denial']['result']['stage'],'not_generated');self.assertFalse(list(root.glob('*.attempt')))
            with self.assertRaisesRegex(ValueError,'receipt_changed'):scope['recheck_permission'](Q,sha,root,success)
            success.assert_called_once()
    def test_legacy_good_permission_label_can_recheck_without_fabricating_old_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path,attempt,legacy=scope['_receipt_paths'](Q,root)
            original=dict(saved_at=1000,value=self.bundle(),last_attempt='es_export_permission_denied',retryable=True,next_retry_at=1030)
            path.write_text(json.dumps(original));path.chmod(0o600);before=path.read_bytes();sha=hashlib.sha256(before).hexdigest();source=Mock(return_value=self.bundle())
            with patch.object(time,'time',return_value=1000000):value=scope['_server_bundle'](Q,root,source)
            self.assertEqual(value['snapshots'][0]['value']['status'],'partial');self.assertNotIn('stage',value)
            self.assertEqual(path.read_bytes(),before);source.assert_not_called()
            for blocker in (attempt,legacy):
                blocker.write_text(json.dumps({'query':Q}));blocker.chmod(0o600)
                with self.assertRaisesRegex(ValueError,'not_definitely_unsent'):scope['recheck_permission'](Q,sha,root,source)
                blocker.unlink()
            self.assertEqual(scope['recheck_permission'](Q,sha,root,source)['status'],'available');source.assert_called_once()
            _,record,_=self.saved(root);self.assertEqual(record['permission_denial']['receipt_sha256'],sha)
            self.assertEqual(record['permission_denial']['result'],{'reason':'es_export_permission_denied'})
    def test_long_lived_reader_observes_another_instances_operator_success_without_generation(self):
        import importlib.util
        from concurrent.futures import ThreadPoolExecutor
        with patch.dict(sys.modules):
            dependencies=SOURCE.parents[2]/'fs-business-baseline-20261021/source'
            for name,path in [('coupon_channels',dependencies/'coupon_channels.py'),('admin_discount_analysis',dependencies/'admin_discount_analysis.py'),('full_es_permission_contract',SOURCE)]:
                spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
            for legacy_good in (False,True):
                with self.subTest(legacy_good=legacy_good),tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool:
                    root=Path(folder);path=module._receipt_paths(Q,root)[0]
                    source=Mock(return_value=self.bundle()) if legacy_good else Mock(side_effect=[self.denied(),self.bundle()])
                    if legacy_good:
                        path.write_text(json.dumps(dict(saved_at=1000,value=self.bundle(),last_attempt='es_export_permission_denied',retryable=True)));path.chmod(0o600)
                    reader=module.ESReader({'enabled':True},pool,lambda q:module._server_bundle(q,root,source))
                    recovered=module._permission_recovered
                    with patch.object(module,'_permission_recovered',side_effect=lambda q:recovered(q,root)):
                        reader.get(Q);next(iter(reader.jobs.values())).result(timeout=2)
                        value=reader.get(Q)
                        self.assertEqual(value['quality']['last_attempt_reason'] if legacy_good else value['quality']['reason'],'es_export_permission_denied')
                        sha=hashlib.sha256(path.read_bytes()).hexdigest()
                        with self.assertRaisesRegex(ValueError,'es_query_fields'):module.recheck_permission(dict(Q,force=True),sha,root,source)
                        module.recheck_permission(Q,sha,root,source)
                        self.assertEqual(reader.get(Q)['status'],'pending');next(iter(reader.jobs.values())).result(timeout=2)
                        self.assertEqual(reader.get(Q)['kind'],'es_order_structure')
                        self.assertEqual(source.call_count,1 if legacy_good else 2)
    def test_existing_unknown_and_receipt_change_after_claim_are_never_sent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);scope['_server_bundle'](Q,root,Mock(return_value=self.denied()))
            path,record,sha=self.saved(root);_,attempt,_=scope['_receipt_paths'](Q,root)
            attempt.write_text(json.dumps({'query':Q}));attempt.chmod(0o600);before=(path.read_bytes(),attempt.read_bytes())
            source=Mock();value=scope['_server_bundle'](Q,root,source)
            self.assertIn('unknown',value['reason']);self.assertEqual((path.read_bytes(),attempt.read_bytes()),before);source.assert_not_called();attempt.unlink()
            real=scope['_read_receipt'];reads=[]
            def drift(p):
                reads.append(p)
                if len(reads)==2:
                    path.write_text(json.dumps(dict(record,operator_note='changed')));path.chmod(0o600)
                return real(p)
            with patch.dict(scope,_read_receipt=drift):
                with self.assertRaisesRegex(ValueError,'receipt_changed'):scope['recheck_permission'](Q,sha,root,source)
            source.assert_not_called();self.assertFalse(attempt.exists())
    def test_denial_does_not_block_other_periods_and_unknown_failure_never_retries(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);scope['_server_bundle'](Q,root,Mock(return_value=self.denied()))
            other=dict(Q,start='2026-10-28',end='2026-10-28',profile='D4');bundle=self.bundle();bundle['snapshots'][0]['query']=other
            read=Mock(return_value=bundle);self.assertEqual(scope['_server_bundle'](other,root,read)['status'],'available');read.assert_called_once()
        for value in (dict(kind='es_order_structure_bundle',status='unavailable',reason='es_export_request_failed_or_unknown',retryable=False,stage='export_sent'),TimeoutError()):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);read=Mock(side_effect=value) if isinstance(value,Exception) else Mock(return_value=value)
                scope['_server_bundle'](Q,root,read);attempt=next(root.glob('*.attempt'));before=attempt.read_bytes()
                scope['_server_bundle'](Q,root,read);read.assert_called_once();self.assertEqual(attempt.read_bytes(),before)
    def test_legacy_unknown_appearing_during_recheck_cas_is_not_sent_or_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);scope['_server_bundle'](Q,root,Mock(return_value=self.denied()))
            path,record,sha=self.saved(root);_,attempt,legacy=scope['_receipt_paths'](Q,root)
            original=path.read_bytes();read=scope['_read_receipt'];calls=[];unknown=json.dumps({'query':Q,'state':'unknown'}).encode()
            def race(p):
                calls.append(p)
                if len(calls)==2:legacy.write_bytes(unknown);legacy.chmod(0o600)
                return read(p)
            source=Mock()
            with patch.dict(scope,_read_receipt=race):
                with self.assertRaisesRegex(ValueError,'not_definitely_unsent'):scope['recheck_permission'](Q,sha,root,source)
            source.assert_not_called();self.assertFalse(attempt.exists());self.assertEqual(legacy.read_bytes(),unknown);self.assertEqual(path.read_bytes(),original)
    def test_generation_5xx_and_invalid_json_remain_original_unknown_single_send(self):
        for status,raw in ((502,b'upstream failure'),(503,b''),(200,b'{')):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as folder:
                request=Mock(return_value=(status,raw));manager=SimpleNamespace(lock=threading.RLock(),token=None,identity_ok=lambda token:True,request=request)
                source=lambda args,deadline:dict(scope['export_bundle'](manager,args,{},None,deadline=deadline),kind='es_order_structure_bundle')
                root=Path(folder);scope['_server_bundle'](Q,root,source)
                attempt=next(root.glob('*.attempt'));original=attempt.read_bytes()
                scope['_server_bundle'](Q,root,source);request.assert_called_once();self.assertEqual(attempt.read_bytes(),original)
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
