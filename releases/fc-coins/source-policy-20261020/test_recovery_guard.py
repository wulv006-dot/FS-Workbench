import ast,hashlib,json,tempfile,unittest,uuid
from pathlib import Path
from datetime import datetime,timezone,timedelta

class RecoveryGuard(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for d in ('jobs','requests','executions','all-coin-sync','player-sync'):(self.root/d).mkdir()
        self.jid='b5ef086d-ec83-40d6-b7a5-9203b99679bd'
        self.job={'job_id':self.jid,'kind':'auto_cycle','actor':'system-automation','status':'interrupted',
                  'error':'worker_restarted_during_job','request':{'policy_revision':38},
                  'created_at':'2026-10-20T04:03:40Z','completed_at':'2026-10-20T04:05:20Z'}
        self.path=self.root/'jobs'/(self.jid+'.json');self.path.write_text(json.dumps(self.job))
        self.env={'ROOT':self.root,'Path':Path,'datetime':datetime,'timezone':timezone,'timedelta':timedelta,
                  'valid_job_id':lambda v:str(uuid.UUID(v))==v,'read_record':lambda p:json.loads(p.read_text()),
                  'resolved_execution':lambda x:x.get('status')=='CONFIRMED',
                  'AUDITED_PREWRITE_INTERRUPTS':{self.jid:hashlib.sha256(self.path.read_bytes()).hexdigest()},
                  'utc':lambda s:datetime.fromisoformat(s.replace('Z','+00:00')),'retry_plan':lambda *a:None}
        tree=ast.parse((Path(__file__).parent/'source/automation_tick.py').read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('proven_readonly_cycle_failure','due')]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'scheduler','exec'),self.env)
    def accepts(self):return self.env['proven_readonly_cycle_failure'](self.job,38)
    def test_exact_audit_allowed_without_modifying_original(self):
        before=self.path.read_bytes();self.assertTrue(self.accepts());self.assertEqual(before,self.path.read_bytes())
    def test_changed_bytes_not_allowed(self):
        self.path.write_text(self.path.read_text()+' ');self.assertFalse(self.accepts())
    def test_any_write_artifact_blocks(self):
        for d in ('requests','executions','all-coin-sync','player-sync'):
            p=self.root/d/(self.jid+'.json');p.write_text('{}');self.assertFalse(self.accepts());p.unlink()
    def test_unknown_ledger_blocks(self):
        (self.root/'executions/other.json').write_text('{"status":"UNKNOWN"}');self.assertFalse(self.accepts())
    def test_other_interrupt_not_allowed(self):
        self.job['job_id']=str(uuid.uuid4());self.assertFalse(self.accepts())
    def test_revision_and_user_off_stay_protected(self):
        self.assertFalse(self.env['proven_readonly_cycle_failure'](self.job,39))
        p={'system_enabled':False,'mode':'auto','platforms':['PS'],'revision':38,'interval_minutes':120}
        self.assertEqual(self.env['due'](p,self.job),'system_off')
    def test_natural_interval_not_immediate(self):
        p={'system_enabled':True,'mode':'auto','platforms':['PS'],'revision':38,'interval_minutes':120}
        t=datetime(2026,10,20,6,5,20,tzinfo=timezone.utc)
        self.assertEqual(self.env['due'](p,self.job,t-timedelta(seconds=1)),'waiting')
        self.assertEqual(self.env['due'](p,self.job,t),'due')
    def test_new_typed_source_failure_allowed_without_audit(self):
        self.job.update(status='failed',error='automation_source_incomplete:Lootbar')
        self.assertTrue(self.accepts())
    def test_written_flags_and_symlink_block(self):
        self.job['writer_result']={};self.assertFalse(self.accepts());self.job.pop('writer_result')
        p=self.root/'requests'/(self.jid+'.json');p.symlink_to('/nonexistent');self.assertFalse(self.accepts())

if __name__=='__main__':unittest.main()
