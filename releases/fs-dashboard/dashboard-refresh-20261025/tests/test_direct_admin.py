"""Existing aggregate readers use the direct API without the retired session container."""
import ast,contextlib,io,json,runpy,sys,tempfile,time,types,unittest
from datetime import datetime,timezone
from pathlib import Path
from threading import RLock
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]

class DirectAdmin(unittest.TestCase):
    def test_product_reader_keeps_native_query_and_deadline_on_direct_api(self):
        request=dict(key='rank',start='2026-10-27 00:00',end='2026-10-28 00:00')
        session=Mock();session.get_admin.side_effect=[(200,dict(code=1,data=dict(list=[dict(id=1)]))),(200,dict(code=1,data=dict(total=1,list=[dict(pid=10,gid=1327,cid=1,title='fixture',sale_total=3,order_count=1,paytime='2026-10-27 12:00',goods=dict(id=10,cid=1))])))]
        normalise=Mock(return_value=dict(status='available',coverage={}))
        contract=types.SimpleNamespace(native_query=Mock(return_value={'native_field':'kept'}),normalise=normalise)
        auth=types.SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('dc-placeholder',None))
        alarm=Mock();signal=types.SimpleNamespace(SIGALRM=14,signal=Mock(),alarm=alarm)
        script=ROOT/'source/fc_product_reader.py';out=io.StringIO()
        with patch.dict(sys.modules,{'p2pah_auth':auth,'fc_product_contract':contract,'signal':signal}),patch.object(sys,'argv',[str(script),json.dumps([request])]),contextlib.redirect_stdout(out):
            runpy.run_path(str(script),run_name='__main__')
        self.assertEqual(session.get_admin.call_args_list[0].args,('/admin/goods.GoodsCategory/categorySelect',))
        self.assertEqual(session.get_admin.call_args_list[0].kwargs,dict(gid=1327))
        self.assertEqual(session.get_admin.call_args_list[1].args,('/admin/stats.productSalesByEs/index',))
        self.assertEqual(session.get_admin.call_args_list[1].kwargs,dict(native_field='kept'))
        self.assertEqual(json.loads(out.getvalue())['rank']['coverage']['retrievalStrategy'],'complete-native-batch-with-total-check')
        session.ensure.assert_not_called();session.close.assert_called_once()
        self.assertEqual([call.args[0] for call in alarm.call_args_list],[65,0])

    def test_product_deadline_bypasses_api_retry_catch_and_still_closes(self):
        signal=types.SimpleNamespace(SIGALRM=14,signal=Mock(),alarm=Mock())
        def request(*args,**kwargs):
            try:signal.signal.call_args.args[1]()
            except Exception:self.fail('API retry swallowed the product deadline')
        session=Mock();session.get_admin.side_effect=request
        auth=types.SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('dc-placeholder',None))
        contract=types.SimpleNamespace(native_query=Mock(),normalise=Mock())
        script=ROOT/'source/fc_product_reader.py';out=io.StringIO()
        with patch.dict(sys.modules,{'p2pah_auth':auth,'fc_product_contract':contract,'signal':signal}),patch.object(sys,'argv',[str(script),json.dumps([dict(key='rank')])]),contextlib.redirect_stdout(out):
            runpy.run_path(str(script),run_name='__main__')
        self.assertEqual(json.loads(out.getvalue()),{})
        session.get_admin.assert_called_once();session.close.assert_called_once()
        self.assertEqual(signal.alarm.call_args.args,(0,))

    def test_supplement_payload_mapping_row_failure_and_close(self):
        requests=[dict(key='paid',game=891,status='',start='2026-10-27 00:00',end='2026-10-28 00:00',product_type='1'),dict(key='failed',game=891,status='101',start='2026-10-26 00:00',end='2026-10-27 00:00')]
        session=Mock();session.post_admin.side_effect=[(200,dict(code=1,data=dict(data=dict(total=192,amount='18,114.27')))),OSError('api_down')]
        fields=types.SimpleNamespace(extract=lambda v:dict(metrics={'newCustomers':{'value':23}},dimensions={'kept':True},definitionVersion='original'))
        auth=types.SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('dc-placeholder',None))
        out=io.StringIO();script=ROOT/'source/supplement_reader.py'
        with patch.dict(sys.modules,{'p2pah_auth':auth,'supplement_fields':fields}),patch.object(sys,'argv',[str(script),json.dumps(requests)]),contextlib.redirect_stdout(out):
            runpy.run_path(str(script),run_name='__main__')
        value=json.loads(out.getvalue());payload=session.post_admin.call_args_list[0].kwargs['payload']
        self.assertEqual(payload,dict(order_status='',pay_status=1,game=891,site='',country_code='',client='',date=['2026-10-27 00:00','2026-10-28 00:00'],pay_type='',time_unit=1,cid='',discount_code='',product_type='1'))
        self.assertEqual(session.post_admin.call_args_list[1].kwargs['payload']['order_status'],'101')
        self.assertEqual(value['paid']['comparisonOnly'],dict(orders=192,revenueUsd='18,114.27'))
        self.assertEqual(value['paid']['newCustomers'],23);self.assertEqual(value['failed']['status'],'unavailable')
        session.bind_admin_token.assert_called_once_with('dc-placeholder');session.close.assert_called_once()

    def test_collector_dispatches_admin_on_host_and_keeps_order_runner(self):
        tree=ast.parse((ROOT/'source/collector.py').read_text(encoding='utf-8'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='call')
        result=types.SimpleNamespace(returncode=0,stdout=b'{"fixture":1}')
        process=types.SimpleNamespace(run=Mock(return_value=result),PIPE=-1)
        runner=Mock(return_value=result)
        with tempfile.TemporaryDirectory() as folder:
            here=Path(folder)
            for name in ('supplement_reader.py','fc_product_reader.py','primary_reader.py','supplement_fields.py','fc_product_contract.py','primary_fields.py'):(here/name).write_text('# fixture\n')
            namespace=dict(HERE=here,json=json,subprocess=process,sys=sys)
            exec(compile(ast.Module(body=[function],type_ignores=[]),'collector-call','exec'),namespace)
            for script in ('supplement_reader.py','fc_product_reader.py'):
                self.assertEqual(namespace['call'](None,script,[dict(key='fixture')],30),{'fixture':1})
                self.assertEqual(process.run.call_args.args[0][:3],[sys.executable,'-B','-'])
            process.run.reset_mock()
            with patch.dict(sys.modules,{'order_reader_runner':types.SimpleNamespace(run=runner)}):
                self.assertEqual(namespace['call']('fs-order-browser','primary_reader.py',[],30),{'fixture':1})
            runner.assert_called_once();process.run.assert_not_called()
            with self.assertRaisesRegex(ValueError,'order_reader_isolation_required'):namespace['call']('other','primary_reader.py',[],30)

    def test_cold_category_capture_reaches_actual_collector_order_dispatch(self):
        def actual_function(file,name,namespace):
            tree=ast.parse((ROOT/'source'/file).read_text(encoding='utf-8'))
            names={name,'_capture'} if file=='range_api.py' and name=='capture' else {name}
            nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
            namespace.setdefault('maintenance_admission',contextlib.nullcontext)
            exec(compile(ast.Module(body=nodes,type_ignores=[]),file,'exec'),namespace)
            return namespace[name]
        period=dict(start='2026-10-27 00:00',end='2026-10-28 00:00')
        kinds=(('coins','1','Coins'),('items','2','Items'),('boosting','4','Boosting'))
        records={key:dict(status='available',period=period) for key in ('all','coins','items','boosting')}
        result=types.SimpleNamespace(returncode=0,stdout=json.dumps(records).encode())
        process=types.SimpleNamespace(run=Mock(),PIPE=-1)
        runner=Mock(return_value=result)
        with tempfile.TemporaryDirectory() as folder:
            here=Path(folder)
            for name in ('fc_category_reader.py','primary_fields.py'):(here/name).write_text('# reader fixture\n')
            collector=dict(HERE=here,json=json,subprocess=process,sys=sys)
            existing_call=actual_function('collector.py','call',collector)
            published=[];jobs={};flock=Mock()
            namespace=dict(WEB=here,LOCK=RLock(),JOBS=jobs,PROFILE_MAP={'FC27':('FC27','FC 27',1322,1327,'sports')},
                           snapshot=lambda:dict(snapshotId='catalog'),existing_call=existing_call,TYPES=kinds,
                           fcntl=types.SimpleNamespace(flock=flock,LOCK_EX=2,LOCK_NB=4),datetime=datetime,timezone=timezone,time=time,
                           analysis=lambda total,rows,labels,scope,extra:dict(period=scope,records=rows),
                           publish_cache=lambda key,data:published.append((key,data)))
            capture=actual_function('range_api.py','capture',namespace)
            with patch.dict(sys.modules,{'order_reader_runner':types.SimpleNamespace(run=runner)}):
                capture(dict(profile='FC27',analysis='fc27-categories',period=period,baseSnapshotId='catalog'),'cold-category')
                with self.assertRaisesRegex(ValueError,'order_reader_isolation_required'):
                    existing_call('fc27-cloud-browser','fc_category_reader.py',[],200)
            self.assertEqual(len(published),1,jobs)
            self.assertEqual(published[0][0],'cold-category')
            self.assertEqual(published[0][1]['fc27Analytics']['records'],records)
            self.assertNotIn('cold-category',jobs)
            runner.assert_called_once();process.run.assert_not_called();flock.assert_called_once()
            program,requests,timeout=runner.call_args.args
            self.assertIn(b'sys.modules[\'primary_fields\']',program)
            self.assertEqual(timeout,200)
            self.assertEqual(requests,[dict(key='all',gid=1322,tid='',batchBudgetSeconds=170,**period),
                                       *[dict(key=key,gid=1322,tid=tid,**period) for key,tid,_ in kinds]])

if __name__=='__main__':unittest.main()
