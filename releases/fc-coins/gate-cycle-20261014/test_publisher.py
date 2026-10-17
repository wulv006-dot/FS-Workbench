"""Isolated Order/public acceptance and publication tests; no live requests."""
import ast,importlib.util,json,sys,tempfile,types,unittest
from pathlib import Path
from contextlib import nullcontext,redirect_stdout
from io import StringIO
from unittest.mock import Mock,patch
from copy import deepcopy
HERE=Path(__file__).resolve().parent

def function(name,file,namespace):
    tree=ast.parse((HERE/'source'/file).read_text(encoding='utf-8'))
    selected=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[selected],type_ignores=[]),file,'exec'),namespace)
    return namespace[name]

class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        (self.root/'rollback').mkdir()
        self.stage=self.root/'stage';self.stage.mkdir()
        (self.stage/'candidate').mkdir()
        self.runtime=self.root/'runtime';self.runtime.mkdir()
        self.state=self.root/'state';self.state.mkdir()
        (self.state/'price-writer.lock').write_text('')
        for site in ('IGGM','U4GM','U7Buy'):(self.state/(site+'.lock')).write_text('')
        self.mapping={}
        targets={}
        for name,remote in {'price_writer.py':'/opt/fc27-cloud-browser/price_writer.py',
                            'automation_policy.py':'/opt/fc27-cloud-browser/automation_policy.py', 'coin_all_sync_job.py':'/opt/fc27-cloud-browser/coin_all_sync_job.py',
                            'hooks.py':'/opt/fc-ops-readonly-monitor/hooks.py'}.items():
            target=self.runtime/name;target.write_bytes(b'value=1\n')
            candidate=self.stage/'candidate'/name;candidate.write_bytes(b'value=2\n')
            self.mapping[remote]=target
            import hashlib
            targets[name]={'target':remote,'before':hashlib.sha256(target.read_bytes()).hexdigest(),
                           'after':hashlib.sha256(candidate.read_bytes()).hexdigest()}
        self.manifest={'targets':targets,'before':{r['target']:r['before'] for r in targets.values()}}
        control=self.runtime/'control.json';control.write_text(json.dumps({'mode':'RULES_ARMED','unknown_operations':[], 'policy_revision':30}))
        self.mapping['/var/lib/fc-ops-readonly-monitor/gates/control.json']=control
        stub=types.SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=lambda *a:None)
        with patch.dict(sys.modules,{'fcntl':stub,'automation_tick':types.SimpleNamespace(queue_mutation=nullcontext,retry_guard=lambda:'ready')}):
            spec=importlib.util.spec_from_file_location('scoped_publisher',HERE/'publish.py')
            self.pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.pub)
        self.pub.ROOT=self.root;self.pub.STAGE=self.stage;self.pub.HARDENING=True;self.pub.ORDER_PUBLIC=True
        self.commands=[]
        self.monitor={'health':{'worker':'ok'},'automation':{'revision':30,'schedule':{'status':'waiting'}},'player_sync':{}}
        self.pub.command=lambda *args:self.commands.append(args)
        self.pub.urlopen=lambda *a,**kw:StringIO(json.dumps(self.monitor))
        self.pub.Path=lambda name:self.mapping.get(str(name),Path(name))
        self.pub.idle=lambda:None
        self.uid=patch.object(self.pub.os,'geteuid',lambda:0,create=True);self.uid.start();self.addCleanup(self.uid.stop)
        self.chown=patch.object(self.pub.os,'chown',lambda *a:None,create=True);self.chown.start();self.addCleanup(self.chown.stop)
    def run_publish(self,apply=True):
        (self.stage/'manifest.json').write_text(json.dumps(self.manifest))
        with patch.object(sys,'argv',['publisher']+(['--apply'] if apply else [])),redirect_stdout(StringIO()):
            self.pub.main()
    def test_exact_four_targets_apply_without_service_restart(self):
        self.run_publish()
        self.assertTrue(all(p.read_bytes()==b'value=2\n' for p in self.mapping.values() if p.suffix=='.py'))
        self.assertFalse(any('stop' in cmd or 'start' in cmd for cmd in self.commands))
    def test_check_only_does_not_replace_files(self):
        self.run_publish(False)
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))
        self.assertFalse(list((self.root/'rollback').iterdir()))
    def test_extra_or_remapped_target_is_rejected(self):
        self.manifest['targets']['price_writer.py']['target']='/opt/unrelated.py'
        with self.assertRaisesRegex(ValueError,'exact_fc_hardening_scope'):self.run_publish()
    def test_baseline_or_payload_drift_is_rejected(self):
        self.runtime.joinpath('price_writer.py').write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'baseline_changed'):self.run_publish()
    def test_partial_rename_failure_restores_both_original_files(self):
        original=self.pub.swap;counter=[0]
        def swap(source,target):
            original(source,target);counter[0]+=1
            if counter[0]==2:raise OSError('simulated fsync failure after second rename')
        self.pub.swap=swap
        with self.assertRaises(OSError):self.run_publish()
        self.assertEqual(counter[0],6)
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))
    def test_health_failure_restores_original_files(self):
        self.monitor['health']['worker']='unverified'
        with patch.object(self.pub.time,'sleep',lambda _:None):
            with self.assertRaisesRegex(RuntimeError,'runtime_rule_not_effective'):self.run_publish()
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))
    def test_known_unknown_operation_blocks_publication(self):
        self.mapping['/var/lib/fc-ops-readonly-monitor/gates/control.json'].write_text(json.dumps(
            {'mode':'RULES_ARMED','unknown_operations':[{'id':'original'}],'policy_revision':30}))
        self.pub.retry_guard=lambda:'all_sync_unconfirmed'
        with self.assertRaisesRegex(RuntimeError,'order_public_unresolved_operation'):self.run_publish()
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))
    def test_busy_collector_lock_prevents_any_replacement(self):
        count=[0]
        def lock(*args):
            count[0]+=1
            if count[0]==2:raise BlockingIOError('real collector still active')
        self.pub.fcntl.flock=lock
        with self.assertRaises(BlockingIOError):self.run_publish()
        self.assertTrue(all(p.read_bytes()==b'value=1\n' for p in self.mapping.values() if p.suffix=='.py'))

if __name__=='__main__':unittest.main()
