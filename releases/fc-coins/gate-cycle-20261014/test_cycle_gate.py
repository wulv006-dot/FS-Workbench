"""Current-cycle gate regressions; no business requests, jobs, or control writes."""
import ast, json, os, stat, tempfile, types, sys, unittest
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
NOW = datetime.now(timezone.utc)
POLICY = {'revision':30, 'system_enabled':True, 'mode':'auto'}

def function(file, name, ns):
    node = next(n for n in ast.parse((HERE/'source'/file).read_text(encoding='utf-8')).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), file, 'exec'), ns)
    return ns[name]

class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'control.json'
        self.cost = Mock(return_value=[])
        self.ns = {'Path':lambda _:self.path, 'os':os, 'json':json,
                   'datetime':datetime, 'timezone':timezone, 'check_write':self.cost}
        self.gate = function('automation_policy.py','hooks_before_write',self.ns)
        self.control = {'schema_version':1, 'module_id':'fc-coins', 'mode':'RULES_ARMED',
            'user_intent':'ENABLED','policy_revision':30,'unknown_operations':[],
            'observed_at':(NOW-timedelta(minutes=2)).isoformat(),
            'valid_until':(NOW+timedelta(minutes=12)).isoformat(),
            'platforms':{p:{'reasons':['collection_stale_or_clock_invalid'],
                'pause_source':'system_fault'} for p in ('PS','XBOX','PC')}}
        self.quote = {'evidence':{'checked_at':(NOW-timedelta(minutes=1)).isoformat()}}
        self.current = Mock(return_value=self.quote)
        self.meta = types.SimpleNamespace(st_mode=stat.S_IFREG|0o640, st_uid=0,
                                          st_size=1024,st_nlink=1)
    def call(self, provider=True, **kwargs):
        self.path.write_text(json.dumps(self.control),encoding='utf-8')
        with patch.object(Path,'lstat',return_value=self.meta):
            return self.gate(kwargs.get('policy',POLICY),kwargs.get('selected',['PS']),
                             kwargs.get('automatic',True), self.current if provider else None)
    def test_fresh_current_cycle_supersedes_only_old_collection_age(self):
        self.call();self.current.assert_called_once()
    def test_no_cycle_proof_remains_paused(self):
        with self.assertRaisesRegex(ValueError,'hook_scope_paused'):self.call(False)
    def test_pending_recovery_requires_original_collection_only_provenance(self):
        scope=self.control['platforms']['PS'];scope['recovery_from']={'reasons':list(scope['reasons']),'observed_at':self.control['observed_at']}
        scope['reasons']=['recovery_confirmation_pending']
        self.control['observed_at']=NOW.isoformat();self.call()
        for basis in ({}, {'reasons':['unknown_operation:original'],'observed_at':NOW.isoformat()}):
            scope['recovery_from']=basis
            with self.assertRaisesRegex(ValueError,'hook_scope_paused'):self.call()
    def test_other_faults_and_mixed_faults_are_not_waived(self):
        for reasons in (['published_price_unverified'],['unknown_operation:original'],['p2pah_session_unhealthy_or_unknown'],
                        ['latest_coin_job_failed'],['collection_stale_or_clock_invalid','source_coverage_unverified']):
            self.control['platforms']['PS']['reasons']=reasons
            with self.assertRaisesRegex(ValueError,'hook_scope_paused'):self.call()
        self.current.assert_not_called()
    def test_unknown_or_unverified_operations_are_not_waived(self):
        for unknown in (None,[{'operation_id':'original','state':'UNKNOWN'}]):
            self.control['unknown_operations']=unknown
            with self.assertRaisesRegex(ValueError,'hook_scope_paused'):self.call()
    def test_old_expired_future_or_naive_cycle_evidence_rejected(self):
        for when in (NOW-timedelta(minutes=3),NOW-timedelta(minutes=16),NOW+timedelta(seconds=5),NOW.replace(tzinfo=None)):
            self.quote['evidence']['checked_at']=when.isoformat()
            with self.assertRaises(ValueError):self.call()
    def test_changed_source_or_cost_guard_failure_is_not_swallowed(self):
        self.current.side_effect=ValueError('snapshot_hash_changed')
        with self.assertRaises(ValueError):self.call()
        self.current.side_effect=ValueError('automatic_margin_floor:PS')
        with self.assertRaises(ValueError):self.call()
    def test_user_disable_policy_change_and_stale_control_still_block(self):
        for key,value in (('user_intent','DISABLED'),('policy_revision',31),('observed_at',(NOW-timedelta(minutes=16)).isoformat())):
            original=self.control[key];self.control[key]=value
            with self.assertRaises(ValueError):self.call()
            self.control[key]=original
    def test_untrusted_control_still_blocks(self):
        self.meta.st_nlink=2
        with self.assertRaisesRegex(ValueError,'hook_control_untrusted'):self.call()
    def test_clean_scope_and_manual_paths_do_not_invoke_exception(self):
        self.control['platforms']['PS']['reasons']=[];self.call();self.call(automatic=False)
        self.current.assert_not_called();self.cost.assert_not_called()
    def test_all_selected_scopes_must_be_safe(self):
        self.control['platforms']['XBOX']['reasons']=['unknown_operation:original']
        with self.assertRaisesRegex(ValueError,'hook_scope_paused'):self.call(selected=['PS','XBOX'])

class ProvenanceTests(unittest.TestCase):
    def test_recovery_keeps_actual_fault_and_clears_after_two_clean_observations(self):
        ns={'PLATFORMS':('PS','XBOX','PC'),'datetime':datetime,'timezone':timezone,
            'timedelta':timedelta,'bot_ready':lambda:False,'can_resume':lambda **kw:kw['unknown_operations']==[]}
        controls=function('hooks.py','controls',ns)
        value={'coin':{'config':POLICY,'job':{'job_id':'synthetic','result':'confirmed'}},
            'publication':{'platforms':[{'platform':p,'status':'matched'} for p in ns['PLATFORMS']]},
            'issues':[{'code':'collection_stale_or_clock_invalid'}], 'unknown_operations':[]}
        fault=controls(value,at=NOW);value['issues']=[]
        pending=controls(value,fault,at=NOW+timedelta(minutes=5))
        self.assertEqual(pending['platforms']['PS']['recovery_from'],fault['platforms']['PS']['recovery_from'])
        self.assertEqual(pending['platforms']['PS']['reasons'],['recovery_confirmation_pending'])
        cleared=controls(value,pending,at=NOW+timedelta(minutes=10))
        self.assertEqual(cleared['platforms']['PS']['reasons'],[])
        self.assertIsNone(cleared['platforms']['PS']['recovery_from'])
    def test_unknown_origin_is_never_relabelled_as_collection_age(self):
        ns={'PLATFORMS':('PS','XBOX','PC'),'datetime':datetime,'timezone':timezone,'timedelta':timedelta,'bot_ready':lambda:False,'can_resume':lambda **kw:True}
        controls=function('hooks.py','controls',ns)
        value={'coin':{'config':POLICY},'publication':{'platforms':[{'platform':p,'status':'matched'} for p in ns['PLATFORMS']]},
               'issues':[],'unknown_operations':[{'operation_id':'original','platforms':['PS']}]}
        fault=controls(value,at=NOW);value['unknown_operations']=[]
        pending=controls(value,fault,at=NOW+timedelta(minutes=5))
        self.assertEqual(pending['platforms']['PS']['recovery_from']['reasons'],['unknown_operation:original'])

class CallersTests(unittest.TestCase):
    def test_writer_validator_reuses_authorized_snapshot_and_original_selected_cost_checks(self):
        quote={'synthetic':True};load=Mock(return_value=({},quote));cost=Mock()
        ns={'load_authorized':load,'load_policy':lambda:dict(POLICY),'check_write':cost}
        validate=function('price_writer.py','current_cycle_quote',ns)
        self.assertIs(validate('original-preview',['PS'],30),quote)
        load.assert_called_once_with('original-preview');cost.assert_called_once_with(POLICY,quote,['PS'],automatic=True)
        with self.assertRaisesRegex(ValueError,'automation_policy_changed'):validate('original-preview',['PS'],29)
        cost.side_effect=ValueError('automatic_margin_floor:PS')
        with self.assertRaisesRegex(ValueError,'automatic_margin_floor'):validate('original-preview',['PS'],30)
        load.side_effect=ValueError('newer_run_exists')
        with self.assertRaisesRegex(ValueError,'newer_run_exists'):validate('original-preview',['PS'],30)
    def test_every_order_and_all_price_dispatch_receives_cycle_validator(self):
        writer=ast.parse((HERE/'source/price_writer.py').read_text(encoding='utf-8'))
        calls=[n for n in ast.walk(writer) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='hooks_before_write']
        self.assertEqual(len(calls),3)
        self.assertTrue(all(any(k.arg=='current_quote' and isinstance(k.value,ast.Lambda) for k in n.keywords) for n in calls))
        coins=ast.parse((HERE/'source/coin_all_sync_job.py').read_text(encoding='utf-8'))
        hook=next(n for n in ast.walk(coins) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='hooks_before_write')
        self.assertTrue(any(k.arg=='current_quote' for k in hook.keywords))
    def test_all_continuation_forwards_original_validator(self):
        coins=types.ModuleType('cycle_coins')
        exec(compile((HERE/'source/coin_all_sync_job.py').read_text(encoding='utf-8'),'coins','exec'),coins.__dict__)
        provider=Mock()
        session=types.SimpleNamespace(SessionManager=lambda _:types.SimpleNamespace(ensure=lambda:True),read_private_config=lambda:{})
        with tempfile.TemporaryDirectory() as t,patch.dict(sys.modules,{'p2pah_session_service':session}),patch.object(coins,'synchronize',return_value={'status':'confirmed'}) as sync:
            (Path(t)/'all-coin-sync').mkdir()
            coins.mirror_confirmed({'execution_id':'synthetic'},POLICY,Mock(),Path(t),Mock(),provider)
            self.assertIs(sync.call_args.args[-1],provider)

if __name__=='__main__':unittest.main()
