"""Isolated deployment contracts; never loads production code or runs services."""
import ast
from contextlib import ExitStack, nullcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE=Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name):
    fake_fcntl=SimpleNamespace(LOCK_EX=1,LOCK_NB=4,flock=Mock())
    spec=importlib.util.spec_from_file_location('publisher_'+name,HERE/'publishers'/(name+'-publisher.py'))
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'fcntl':fake_fcntl,'automation_tick':SimpleNamespace(queue_mutation=lambda:nullcontext())}),patch.object(sys,'argv',['publisher']):
        spec.loader.exec_module(module)
    return module


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.print_patch=patch('builtins.print');self.print_patch.start();self.addCleanup(self.print_patch.stop)
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name);self.stage=self.root/'stage'
        (self.stage/'source'/'monitor').mkdir(parents=True);(self.stage/'tests').mkdir()
        self.fc=load('fc');self.monitor=load('monitor')

    def fc_fixture(self):
        data=self.root/'data'
        for name in ('queue','jobs','executions','state','config','rollback'):(data/name).mkdir(parents=True)
        (data/'state'/'price-writer.lock').write_text('')
        self.fc.ROOT=data;self.fc.STAGE=self.stage
        names=('fc27_quote_engine.py','snapshot_layer.py','server_quote_job.py','automation_policy.py',
               'fc27_cloud_api.py','repricing_logic.js','automation_tick.py','fc27-quote-cloud.js')
        targets={};before={}
        self.app=self.root/'app';self.app.mkdir()
        for name in names:
            target=('/var/www/dashboard/' if name=='fc27-quote-cloud.js' else '/opt/fc27-cloud-browser/')+name
            actual=self.app/name;actual.write_text('# old\n' if name.endswith('.py') else '// old\n')
            source=self.stage/'source'/name;source.write_text('# new\n' if name.endswith('.py') else '// new\n')
            targets[name]={'target':target,'before':digest(actual),'after':digest(source)};before[target]=digest(actual)
        for name in ('fc27_cloud_worker.py','price_writer.py','coin_all_sync_job.py','execute_price.sh'):
            actual=self.app/name;actual.write_text('protected');before['/opt/fc27-cloud-browser/'+name]=digest(actual)
        for name in ('automation.json','player-sync.json'):
            actual=data/'config'/name;actual.write_text('protected');before[str(actual)]=digest(actual)
        manifest={'targets':targets,'before':before,'checks':{'files':{},'test_count':1,'node_count':75}}
        (self.stage/'noncore-fc-manifest.json').write_text(json.dumps(manifest))
        return manifest

    def fc_patches(self):
        stack=ExitStack()
        def mapped(value):
            value=str(value)
            if value.startswith(('/opt/fc27-cloud-browser/','/var/www/dashboard/')):return self.app/Path(value).name
            return Path(value)
        original_copy=shutil.copy2
        stack.enter_context(patch.dict(sys.modules,{'automation_tick':SimpleNamespace(retry_guard=lambda:'ready')}))
        stack.enter_context(patch.object(self.fc,'Path',mapped))
        stack.enter_context(patch.object(self.fc.os,'geteuid',return_value=0,create=True))
        stack.enter_context(patch.object(self.fc.os,'O_NOFOLLOW',0,create=True))
        stack.enter_context(patch.object(self.fc,'noncore_checks'))
        self.commands=stack.enter_context(patch.object(self.fc,'command'))
        stack.enter_context(patch.object(self.fc.shutil,'copy2',side_effect=lambda a,b:original_copy(mapped(a),mapped(b))))
        stack.enter_context(patch.object(self.fc,'swap',side_effect=lambda a,b:original_copy(a,b)))
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        stack.enter_context(patch.object(self.fc,'urlopen',return_value=response))
        original_load=json.load
        stack.enter_context(patch.object(self.fc.json,'load',side_effect=lambda stream: {'health':{'worker':'ok'},'automation':{'revision':29}} if stream is response else original_load(stream)))
        return stack

    def test_fc_scope_and_idle_dry_run(self):
        self.fc_fixture()
        with self.fc_patches():
            receipt=self.fc.noncore_emergency(False)
        self.assertFalse(receipt['applied']);self.assertFalse(any('stop' in call.args for call in self.commands.call_args_list))
        self.assertFalse(list((self.fc.ROOT/'rollback').iterdir()))

    def test_fc_success_preserves_config_and_protected_code(self):
        manifest=self.fc_fixture()
        with self.fc_patches():receipt=self.fc.noncore_emergency(True)
        self.assertTrue(receipt['applied']);self.assertEqual(receipt['policy_revision'],29)
        for name,row in manifest['targets'].items():self.assertEqual(digest(self.app/name),row['after'])
        self.assertEqual((self.fc.ROOT/'config'/'automation.json').read_text(),'protected')
        self.assertEqual((self.app/'price_writer.py').read_text(),'protected')

    def test_fc_failure_restores_only_code(self):
        manifest=self.fc_fixture()
        with self.fc_patches(),patch.object(self.fc,'urlopen',side_effect=OSError('isolated failure')),patch.object(self.fc.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'runtime_not_ready'):self.fc.noncore_emergency(True)
        for name,row in manifest['targets'].items():self.assertEqual(digest(self.app/name),row['before'])
        self.assertEqual((self.fc.ROOT/'config'/'automation.json').read_text(),'protected')

    def test_fc_queue_and_unknown_refuse_without_stopping(self):
        self.fc_fixture()
        for directory,record,reason in [('queue',{},'queue_not_idle'),('jobs',{'status':'running'},'job_not_idle'),('executions',{'status':'UNCERTAIN'},'coin_execution_unresolved')]:
            path=self.fc.ROOT/directory/'fixture.json';path.write_text(json.dumps(record))
            with self.fc_patches(),self.assertRaisesRegex(RuntimeError,reason):self.fc.noncore_emergency(True)
            self.assertFalse(any('stop' in call.args for call in self.commands.call_args_list));path.unlink()

    def test_fc_scope_and_drift_refuse_without_stopping(self):
        manifest=self.fc_fixture();manifest['targets']['price_writer.py']=manifest['targets'].pop('snapshot_layer.py')
        (self.stage/'noncore-fc-manifest.json').write_text(json.dumps(manifest))
        with self.fc_patches(),self.assertRaisesRegex(ValueError,'exact_noncore_fc_scope'):self.fc.noncore_emergency(True)
        self.assertFalse(any('stop' in call.args for call in self.commands.call_args_list))
        manifest=self.fc_fixture_after_cleanup()
        (self.app/'snapshot_layer.py').write_text('drift')
        with self.fc_patches(),self.assertRaisesRegex(RuntimeError,'baseline_changed'):self.fc.noncore_emergency(True)
        self.assertFalse(any('stop' in call.args for call in self.commands.call_args_list))

    def fc_fixture_after_cleanup(self):
        shutil.rmtree(self.app);shutil.rmtree(self.fc.ROOT)
        return self.fc_fixture()

    def monitor_fixture(self):
        self.monitor.APP=self.root/'monitor';self.monitor.APP.mkdir()
        self.monitor.DATA=self.root/'monitor-data';self.monitor.DATA.mkdir()
        rows=[]
        for name in ('collector.py','read_only_status.py','hooks_notifier.py'):
            target=self.monitor.APP/name;target.write_text('# old\n');source=self.stage/'source'/'monitor'/name;source.write_text('# new\n')
            rows.append({'name':name,'before':digest(target),'after':digest(source)})
        baseline={'sha256':{'config':'unchanged'},'services':{'worker':'active PID 123'}}
        manifest={'files':rows,'protected':baseline['sha256'],'checks':{'files':{},'test_count':1}}
        (self.stage/'noncore-monitor-manifest.json').write_text(json.dumps(manifest))
        return manifest,baseline

    def test_monitor_dry_run_never_restarts_services(self):
        manifest,baseline=self.monitor_fixture()
        fake_fcntl=SimpleNamespace(LOCK_EX=1,LOCK_NB=4,flock=Mock())
        with patch.dict(sys.modules,{'fcntl':fake_fcntl}),patch.object(self.monitor.os,'geteuid',return_value=0,create=True),patch.object(self.monitor,'baseline',return_value=baseline),patch.object(self.monitor,'noncore_checks'),patch.object(self.monitor,'run') as run:
            result=self.monitor.noncore_emergency(self.stage,False)
        self.assertFalse(result['applied']);run.assert_not_called()
        for row in manifest['files']:self.assertEqual(digest(self.monitor.APP/row['name']),row['before'])

    def test_monitor_apply_and_rollback_preserve_business_services(self):
        manifest,baseline=self.monitor_fixture()
        fake_fcntl=SimpleNamespace(LOCK_EX=1,LOCK_NB=4,flock=Mock())
        with patch.dict(sys.modules,{'fcntl':fake_fcntl}),patch.object(self.monitor.os,'geteuid',return_value=0,create=True),patch.object(self.monitor,'baseline',side_effect=[baseline,baseline,{'sha256':{'config':'drift'},'services':baseline['services']}]),patch.object(self.monitor,'noncore_checks'),patch.object(self.monitor,'noncore_swap',side_effect=lambda a,b:shutil.copy2(a,b)),patch.object(self.monitor,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'protected_changed'):self.monitor.noncore_emergency(self.stage,True)
        run.assert_not_called()
        for row in manifest['files']:self.assertEqual(digest(self.monitor.APP/row['name']),row['before'])

    def test_monitor_success_installs_only_three_files(self):
        manifest,baseline=self.monitor_fixture()
        untouched=self.monitor.APP/'probe_worker.py';untouched.write_text('# RPG probe retained')
        fake_fcntl=SimpleNamespace(LOCK_EX=1,LOCK_NB=4,flock=Mock())
        with patch.dict(sys.modules,{'fcntl':fake_fcntl}),patch.object(self.monitor.os,'geteuid',return_value=0,create=True),patch.object(self.monitor,'baseline',return_value=baseline),patch.object(self.monitor,'noncore_checks'),patch.object(self.monitor,'noncore_swap',side_effect=lambda a,b:shutil.copy2(a,b)),patch.object(self.monitor,'run') as run:
            result=self.monitor.noncore_emergency(self.stage,True)
        self.assertTrue(result['applied']);run.assert_not_called();self.assertEqual(untouched.read_text(),'# RPG probe retained')
        for row in manifest['files']:self.assertEqual(digest(self.monitor.APP/row['name']),row['after'])

    def test_monitor_unchanged_notifier_is_cas_checked_without_replace(self):
        manifest,baseline=self.monitor_fixture();row=manifest['files'][-1]
        target=self.monitor.APP/row['name'];source=self.stage/'source'/'monitor'/row['name']
        source.write_bytes(target.read_bytes());row['after']=row['before']
        (self.stage/'noncore-monitor-manifest.json').write_text(json.dumps(manifest))
        before=target.stat().st_ino
        fake_fcntl=SimpleNamespace(LOCK_EX=1,LOCK_NB=4,flock=Mock())
        with patch.dict(sys.modules,{'fcntl':fake_fcntl}),patch.object(self.monitor.os,'geteuid',return_value=0,create=True), \
             patch.object(self.monitor,'baseline',return_value=baseline),patch.object(self.monitor,'noncore_checks'), \
             patch.object(self.monitor,'noncore_swap',side_effect=lambda a,b:shutil.copy2(a,b)) as swap:
            result=self.monitor.noncore_emergency(self.stage,True)
        self.assertTrue(result['applied']);self.assertEqual(target.stat().st_ino,before)
        self.assertEqual([call.args[1].name for call in swap.call_args_list],['collector.py','read_only_status.py'])

    def test_fc_existing_retry_guard_blocks_unknown_without_stopping(self):
        self.fc_fixture()
        for reason in ('ledger_unavailable','write_unconfirmed','all_sync_unconfirmed','player_sync_unconfirmed'):
            with self.fc_patches(),patch.dict(sys.modules,{'automation_tick':SimpleNamespace(retry_guard=lambda:reason)}),self.assertRaisesRegex(RuntimeError,'unresolved_operation'):
                self.fc.noncore_emergency(True)
            self.assertFalse(any('stop' in call.args for call in self.commands.call_args_list))

    def test_atomic_swaps_preserve_existing_metadata(self):
        for module,function in ((self.fc,self.fc.swap),(self.monitor,self.monitor.noncore_swap)):
            target=self.root/'installed.py';source=self.root/'source.py'
            target.write_text('# old');source.write_text('# new');metadata=target.stat()
            original_open=module.os.open;original_close=module.os.close;original_fsync=module.os.fsync
            with patch.object(module.os,'O_DIRECTORY',0,create=True),patch.object(module.os,'open',side_effect=lambda path,flags,*args:999999 if Path(path)==target.parent else original_open(path,flags,*args)),patch.object(module.os,'close',side_effect=lambda fd:None if fd==999999 else original_close(fd)),patch.object(module.os,'fsync',side_effect=lambda fd:None if fd==999999 else original_fsync(fd)),patch.object(module.os,'chown',create=True) as owner:
                function(source,target)
            self.assertEqual(target.read_bytes(),source.read_bytes());self.assertEqual(target.stat().st_mode&0o7777,metadata.st_mode&0o7777)
            self.assertEqual(owner.call_args.args[1:],(metadata.st_uid,metadata.st_gid))

    def test_frozen_tests_reject_changes_skips_and_wrong_count(self):
        for module in (self.fc,self.monitor):
            patterns=['test_pipeline.py','test_selfheal.py'] if module is self.fc else ['test_monitor.py']
            names=patterns+(['legacy_engine.py','legacy_repricing_logic.js','test_js.cjs'] if module is self.fc else [])
            for name in names:(self.stage/'tests'/name).write_text('# fixture')
            checks={'files':{'tests/'+name:digest(self.stage/'tests'/name) for name in names},'test_count':3*len(patterns),'patterns':patterns,'node_count':75}
            for output in ('Ran 3 tests\n\nOK (skipped=1)','Ran 2 tests\n\nOK'):
                with patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=0,stderr=output)),self.assertRaisesRegex(RuntimeError,'linux_checks_failed'):
                    module.noncore_checks(self.stage,checks)
            def result(args,**kwargs):
                return SimpleNamespace(returncode=0,stdout=json.dumps({'checks':75,'passed':True}),stderr='' if args[0]=='node' else 'Ran 3 tests\n\nOK')
            with patch.object(module.subprocess,'run',side_effect=result):module.noncore_checks(self.stage,checks)
            if module is self.fc:
                for summary in ({'checks':74,'passed':True},{'checks':75,'passed':False}):
                    def wrong_node(args,**kwargs):
                        return SimpleNamespace(returncode=0,stdout=json.dumps(summary),stderr='' if args[0]=='node' else 'Ran 3 tests\n\nOK')
                    with patch.object(module.subprocess,'run',side_effect=wrong_node),self.assertRaisesRegex(RuntimeError,'node_checks_failed'):
                        module.noncore_checks(self.stage,checks)
            (self.stage/'tests'/patterns[0]).write_text('# changed')
            with self.assertRaisesRegex(ValueError,'check_input_changed'):module.noncore_checks(self.stage,checks)

    def test_existing_modes_functions_remain_byte_for_byte_ast(self):
        pairs=[('fc',HERE.parents[0]/'fs_hooks_20261008'/'fc-publisher.py'),('monitor',HERE.parents[0]/'fc_ops_readonly_monitor_20261008'/'deploy.py')]
        for name,original in pairs:
            if not original.is_file():original=HERE/'tests'/'legacy'/(name+'-publisher.py')
            previous={node.name:ast.dump(node) for node in ast.parse(original.read_text()).body if isinstance(node,ast.FunctionDef)}
            functions=[node for node in ast.parse((HERE/'publishers'/(name+'-publisher.py')).read_text()).body if isinstance(node,ast.FunctionDef)]
            for function in functions:
                if function.name=='main':
                    function.body=[statement for statement in function.body if not (
                        isinstance(statement,ast.If) and any((isinstance(node,ast.Name) and node.id=='NONCORE') or (isinstance(node,ast.Attribute) and node.attr=='noncore_emergency') for node in ast.walk(statement.test))
                        or isinstance(statement,ast.Expr) and isinstance(statement.value,ast.Call) and isinstance(statement.value.func,ast.Attribute) and statement.value.func.attr=='add_argument' and any(isinstance(argument,ast.Constant) and argument.value=='--noncore-emergency' for argument in statement.value.args))]
            candidate={node.name:ast.dump(node) for node in functions}
            for function,tree in previous.items():
                self.assertEqual(candidate[function],tree,(name,function))


if __name__=='__main__':unittest.main()
