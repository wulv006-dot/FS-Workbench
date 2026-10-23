import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).parent
spec=importlib.util.spec_from_file_location('isolated_reader_runner',ROOT/'source/order_reader_runner.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
STATE=dict(Id='a'*64,Image='sha256:'+'b'*64,State=dict(Running=True,Restarting=False))


class RunnerTests(unittest.TestCase):
    def execute(self,effect=None,state=STATE):
        process=Mock(returncode=0,stdout=b'{"synthetic":true}',stderr=b'')
        calls=[]
        def run(args,**kwargs):
            calls.append((args,kwargs))
            if args[1]=='run' and effect:raise effect
            return process
        with patch.object(Path,'is_socket',return_value=True),patch.object(Path,'is_file',return_value=True),\
             patch.object(R.subprocess,'check_output',return_value=json.dumps(state)),patch.object(R.subprocess,'run',side_effect=run):
            try:result=R.run(b"endpoint='http://127.0.0.1:9226'",[{'synthetic':True}],900)
            except Exception as error:result=error
        return result,calls

    def test_separate_process_domain_same_image_and_order_network(self):
        result,calls=self.execute();args,options=calls[0]
        self.assertEqual(args[:3],['docker','run','--rm'])
        self.assertIn('-i',args)
        self.assertIn('container:'+STATE['Id'],args);self.assertIn(STATE['Image'],args)
        self.assertNotIn('fc27-cloud-browser',str(args));self.assertEqual(args[args.index('--memory')+1],'1g')
        self.assertIn('--read-only',args);self.assertIn('no-new-privileges',args)
        self.assertEqual(args[args.index('--user')+1],'11027:11027')
        self.assertEqual(options['timeout'],900)

    def test_only_endpoint_changes_and_no_cookie_or_profile_transport(self):
        _,calls=self.execute();args,options=calls[0]
        self.assertEqual(options['input'],b"endpoint='http://127.0.0.1:9225'")
        self.assertIn('type=bind,src=/run/fs-order-session/session.sock,dst=/run/fs-order-session/session.sock,readonly',args)
        self.assertIn('type=bind,src=/opt/fs-order-session/fs_order_client.py,dst=/opt/fs-order-session/fs_order_client.py,readonly',args)
        self.assertNotIn('profile',str(args));self.assertNotIn('cookies',str(args));self.assertNotIn('google-chrome',args)
        self.assertEqual(args[args.index('--entrypoint')+1],'timeout')
        self.assertIn('900s',args)

    def test_success_removes_only_own_ephemeral_runner(self):
        _,calls=self.execute();name=calls[0][0][calls[0][0].index('--name')+1]
        self.assertRegex(name,r'^fs-transaction-reader-[a-f0-9]{32}$')
        self.assertEqual(calls[1][0],['docker','rm','--force',name])
        self.assertEqual(calls[1][1]['timeout'],10)

    def test_timeout_cleans_runner_before_propagating_original_failure(self):
        result,calls=self.execute(subprocess.TimeoutExpired('synthetic',900))
        self.assertIsInstance(result,subprocess.TimeoutExpired)
        self.assertEqual(len(calls),2);self.assertEqual(calls[1][0][:3],['docker','rm','--force'])

    def test_failed_cli_still_cleans_own_runner(self):
        result,calls=self.execute(OSError('synthetic'))
        self.assertIsInstance(result,OSError);self.assertEqual(len(calls),2)

    def test_stopped_or_restarting_browser_rejected_without_runner(self):
        for flags in (dict(Running=False,Restarting=False),dict(Running=True,Restarting=True)):
            result,calls=self.execute(state=dict(STATE,State=flags))
            self.assertIsInstance(result,RuntimeError);self.assertEqual(calls,[])

    def test_invalid_identity_not_used_as_network_or_image_argument(self):
        for field in ('Id','Image'):
            result,calls=self.execute(state=dict(STATE,**{field:'untrusted'}))
            self.assertIsInstance(result,ValueError);self.assertEqual(calls,[])

    def test_endpoint_and_budget_require_original_contract(self):
        for program,budget in ((b'none',900),(b'http://127.0.0.1:9226'*2,900),(b'http://127.0.0.1:9226',False),(b'http://127.0.0.1:9226',901)):
            with self.assertRaises(ValueError):R.run(program,[],budget)

    def test_missing_original_socket_is_not_replaced_with_login(self):
        with patch.object(Path,'is_socket',return_value=False),patch.object(R.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'original_order_session'):R.run(b'http://127.0.0.1:9226',[],900)
        run.assert_not_called()

    def test_already_removed_is_verified_but_daemon_failure_preserves_timeout_context(self):
        name='fs-transaction-reader-'+'c'*32
        with patch.object(R.subprocess,'run',side_effect=[Mock(returncode=1),Mock(returncode=1,stderr='Error: No such object: '+name)]):
            R.cleanup(name)
        failure=subprocess.TimeoutExpired('synthetic',900)
        results=[failure,Mock(returncode=1),Mock(returncode=1,stderr='daemon unavailable')]
        with patch.object(Path,'is_socket',return_value=True),patch.object(Path,'is_file',return_value=True),\
             patch.object(R.subprocess,'check_output',return_value=json.dumps(STATE)),patch.object(R.subprocess,'run',side_effect=results):
            with self.assertRaisesRegex(RuntimeError,'cleanup_unverified') as raised:
                R.run(b'http://127.0.0.1:9226',[],900)
        self.assertIs(raised.exception.__context__,failure)
        with self.assertRaisesRegex(ValueError,'owned_reader'):R.cleanup('fs-order-browser')


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.source=(ROOT/'source/collector.py').read_text(encoding='utf-8')

    def test_only_call_adapter_and_three_consumers_change(self):
        insertion="""    if script in ('primary_reader.py','fc_category_reader.py','profit_daily_reader.py'):
        if container != 'fs-order-browser':raise ValueError('order_reader_isolation_required')
        from order_reader_runner import run
        r=run(program,requests,timeout)
    else:
        r=subprocess.run(['docker','exec','-i',container,'python3','-',json.dumps(requests)],input=program,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)"""
        original="    r=subprocess.run(['docker','exec','-i',container,'python3','-',json.dumps(requests)],input=program,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)"
        self.assertEqual(self.source.count(insertion),1)
        restored=self.source.replace(insertion,original)
        for reader in ('primary_reader.py','fc_category_reader.py','profit_daily_reader.py'):
            anchor="call('fs-order-browser','"+reader+"'"
            self.assertEqual(restored.count(anchor),1)
            restored=restored.replace(anchor,"call('fc27-cloud-browser','"+reader+"'")
        # The live byte baseline is separately CAS checked; this checks its normalized text.
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(),'33e77f75298d308c48ec2f8deab5be83b9f1a4ea363c9c8fd557d60f75ce81d4')

    def call_entry(self,root,runner):
        tree=ast.parse(self.source);node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='call')
        scope=dict(HERE=root,subprocess=subprocess,json=json)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'isolated-call-test','exec'),scope)
        module=types.ModuleType('order_reader_runner');module.run=runner
        return scope['call'],module

    def test_each_order_reader_routes_to_isolated_runner_without_changing_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'primary_fields.py').write_text('SYNTHETIC=True')
            for reader in ('primary_reader.py','fc_category_reader.py','profit_daily_reader.py'):
                (root/reader).write_text("endpoint='http://127.0.0.1:9226'")
                runner=Mock(return_value=Mock(returncode=0,stdout=b'{"synthetic":true}',stderr=b''))
                call,module=self.call_entry(root,runner)
                with patch.dict('sys.modules',{'order_reader_runner':module}),patch.object(subprocess,'run') as old:
                    self.assertEqual(call('fs-order-browser',reader,[{'synthetic':True}],600),{'synthetic':True})
                old.assert_not_called();self.assertEqual(runner.call_args.args[1:],[([{'synthetic':True}],600)][0])

    def test_admin_reader_uses_original_container_and_field_mapper(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'supplement_fields.py').write_text('SYNTHETIC=True');(root/'supplement_reader.py').write_text('pass')
            runner=Mock();call,module=self.call_entry(root,runner)
            with patch.dict('sys.modules',{'order_reader_runner':module}),patch.object(subprocess,'run',return_value=Mock(returncode=0,stdout=b'{}',stderr=b'')) as old:
                self.assertEqual(call('fc27-p2pah-session','supplement_reader.py',[],600),{})
            self.assertEqual(old.call_args.args[0][:4],['docker','exec','-i','fc27-p2pah-session']);runner.assert_not_called()

    def test_original_known_error_contract_and_no_stderr_disclosure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'primary_fields.py').write_text('pass');(root/'primary_reader.py').write_text('pass')
            runner=Mock(return_value=Mock(returncode=1,stdout=b'',stderr=b'private upstream details'))
            call,module=self.call_entry(root,runner)
            with patch.dict('sys.modules',{'order_reader_runner':module}):
                with self.assertRaisesRegex(RuntimeError,'^container_reader_failed_1$'):call('fs-order-browser','primary_reader.py',[],900)

    def test_byte_generator_preserves_mixed_line_endings_and_rejects_drift(self):
        spec=importlib.util.spec_from_file_location('collector_byte_generator',ROOT/'prepare_candidate.py')
        generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
        insertion="""    if script in ('primary_reader.py','fc_category_reader.py','profit_daily_reader.py'):
        if container != 'fs-order-browser':raise ValueError('order_reader_isolation_required')
        from order_reader_runner import run
        r=run(program,requests,timeout)
    else:
        r=subprocess.run(['docker','exec','-i',container,'python3','-',json.dumps(requests)],input=program,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)"""
        baseline=self.source.replace(insertion,generator.OLD.decode())
        for reader in ('primary_reader.py','fc_category_reader.py','profit_daily_reader.py'):
            baseline=baseline.replace("call('fs-order-browser','"+reader+"'","call('fc27-cloud-browser','"+reader+"'")
        mixed=baseline.encode().replace(b'\n',b'\r\n').replace(b'import ',b'import ',1)
        candidate=generator.transform(mixed)
        self.assertEqual(candidate.replace(b'\r\n',b'\n'),self.source.encode())
        self.assertEqual(candidate.count(b'\r\n')-mixed.count(b'\r\n'),5)
        with tempfile.TemporaryDirectory() as directory:
            original=Path(directory)/'old.py';output=Path(directory)/'new.py';original.write_bytes(mixed)
            with self.assertRaisesRegex(ValueError,'baseline_drift'):generator.prepare(original,output)
            self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
