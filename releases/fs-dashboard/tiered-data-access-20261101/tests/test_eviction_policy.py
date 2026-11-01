from contextlib import contextmanager
from copy import deepcopy
import hashlib,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from eviction_policy import CHECKS,dry_run,recheck
from recovery_contract import decision,rollback_read_configuration


class Eviction(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'managed';self.root.mkdir()
        raw=b'{"fixture":"synthetic-current-response"}';ident=hashlib.sha256(raw).hexdigest();self.path=self.root/(ident+'.data.json');self.path.write_bytes(raw)
        self.policy=dict(contract='fs-cache-eviction-dryrun-v1',policy_id='fixture-only-v1',roots=[str(self.root)],datasets=['orders.detail'],quarantine_days=7,max_object_bytes=10000,max_batch_bytes=10000)
        self.item=dict(path=str(self.path),object_id=ident,dataset_id='orders.detail',scope_hash='fixture-scope',source_contract='fixture-contract',classification='L1',active_job=False,mode='fresh',expires_at=1,start='2026-10-01',end_exclusive='2026-10-02',fields=['order_id'],proof_id='synthetic-proof')
        self.proof=dict(proof_id='synthetic-proof',evidence_kind='synthetic',evidence_sha256='0'*64,verified=True,mode='current_state',dataset_id='orders.detail',scope_hash='fixture-scope',source_contract='fixture-contract',start='2026-10-01',end_exclusive='2026-10-02',fields=['order_id'],stable_key='order_id',checks={k:True for k in CHECKS})
        self.refs=dict(complete=True,epoch='r1',pins={ident:0},references=[])

    def plan(self,item=None,proof=None,refs=None,fixture=True):
        return dry_run([self.item if item is None else item],self.policy,{self.item['proof_id']:self.proof if proof is None else proof},lambda d:self.refs if refs is None else refs,now=2,fixture=fixture)

    def test_valid_l1_is_dryrun_only_and_does_not_change_files(self):
        before=self.path.read_bytes(),self.path.stat().st_mtime_ns
        result=self.plan();self.assertEqual(len(result['candidates']),1);self.assertEqual(result['mutations'],0)
        self.assertEqual(before,(self.path.read_bytes(),self.path.stat().st_mtime_ns))

    def test_synthetic_proof_cannot_authorize_live_inspection_and_missing_checks_hold(self):
        self.assertFalse(self.plan(fixture=False)['candidates'])
        proof=deepcopy(self.proof);proof['checks']['pagination_complete']=False
        self.assertFalse(self.plan(proof=proof)['candidates'])
        proof=deepcopy(self.proof);proof['mode']='historical_as_of'
        self.assertFalse(self.plan(proof=proof)['candidates'])

    def test_l0_frozen_active_unknown_main_key_and_excel_are_protected(self):
        for change in (dict(classification='L0'),dict(classification='L3'),dict(mode='frozen'),dict(active_job=True),dict(active_job=None)):
            with self.subTest(change=change):self.assertFalse(self.plan(dict(self.item,**change))['candidates'])
        for name in ('customers.sqlite3','identity.key','evidence.xlsx','UNKNOWN.journal','receipt.json'):
            path=self.root/name;path.write_bytes(b'fixture')
            self.assertFalse(self.plan(dict(self.item,path=str(path)))['candidates'])

    def test_outside_root_expired_proof_and_scope_mismatch_hold(self):
        outside=self.root.parent/self.path.name;outside.write_bytes(self.path.read_bytes())
        for change in (dict(path=str(outside)),dict(expires_at=10),dict(expires_at=float('nan')),dict(scope_hash='other'),dict(start='2020-01-01')):
            with self.subTest(change=change):self.assertFalse(self.plan(dict(self.item,**change))['candidates'])

    def test_reference_scan_failure_unknown_pins_and_new_reference_hold(self):
        for refs in (dict(self.refs,complete=False),dict(self.refs,pins={}),dict(self.refs,pins={self.item['object_id']:False}),dict(self.refs,references=[self.item['object_id']])):
            self.assertFalse(self.plan(refs=refs)['candidates'])
        result=dry_run([self.item],self.policy,{self.item['proof_id']:self.proof},lambda d:(_ for _ in ()).throw(OSError('fixture unreadable')),now=2,fixture=True)
        self.assertFalse(result['candidates']);self.assertEqual(result['held'][0]['reason'],'inspection_failed')

    def test_recheck_under_injected_original_lock_rejects_pin_or_generation_race(self):
        proposal=self.plan()['candidates'][0];locked=[False]
        @contextmanager
        def existing_lock():
            locked[0]=True
            try:yield
            finally:locked[0]=False
        def reader(dataset):
            self.assertTrue(locked[0]);return dict(self.refs,pins={self.item['object_id']:1},epoch='r2')
        self.assertFalse(recheck(proposal,self.item,self.policy,self.proof,reader,existing_lock,now=2,fixture=True)['eligible_under_existing_lock'])
        self.assertFalse(recheck(proposal,self.item,self.policy,self.proof,lambda d:dict(self.refs,epoch='r2'),existing_lock,now=2,fixture=True)['eligible_under_existing_lock'])
        self.assertTrue(self.path.exists())

    def test_changed_bytes_lock_failure_and_batch_budget_fail_closed(self):
        proposal=self.plan()['candidates'][0];self.path.write_bytes(b'changed')
        @contextmanager
        def busy():raise BlockingIOError('fixture busy');yield
        self.assertFalse(recheck(proposal,self.item,self.policy,self.proof,lambda d:self.refs,busy,now=2,fixture=True)['eligible_under_existing_lock'])
        self.assertFalse(self.plan()['candidates'])
        self.path.write_bytes(b'{"fixture":"synthetic-current-response"}');self.policy['max_batch_bytes']=1
        self.assertFalse(self.plan()['candidates'])

    def test_real_symlink_escape_is_protected(self):
        link=self.root/'alias'
        try:link.symlink_to(self.root.parent,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest('real symlink privilege unavailable; Linux must run this case')
        self.assertFalse(self.plan(dict(self.item,path=str(link/self.path.name)))['candidates'])


class Recovery(unittest.TestCase):
    def test_three_missing_scenarios_and_frozen_history_never_imply_full_restore(self):
        f=Eviction();f.setUp();self.addCleanup(f.doCleanups)
        for kind in ('cache_miss','empty_read_model'):
            value=decision(kind,proof=f.proof,query=f.item,fixture=True)
            self.assertFalse(value['full_import']);self.assertFalse(value['whole_database_backup']);self.assertFalse(value['complete'])
            self.assertNotIn('path',value['query'])
        lost=decision('authoritative_store_missing',accept_new_baseline=True)
        self.assertEqual(lost['action'],'explicit_bounded_new_baseline');self.assertFalse(lost['promises_original_asof'])
        frozen=decision('frozen_inputs_missing',accept_new_baseline=True)
        self.assertEqual(frozen['status'],'missing_history');self.assertFalse(frozen['fresh_fallback'])
        self.assertFalse(decision('authoritative_store_missing',identity_available=False)['automatic'])

    def test_rollback_only_changes_read_route_and_keeps_new_authoritative_writes(self):
        current=dict(read_route='candidate',orders_revision=9,UNKNOWN=['new-u'],receipts=['new-r'],identity='existing-key-fingerprint',journal=['new-event'])
        before=deepcopy(current);value=rollback_read_configuration(current,'legacy')
        self.assertEqual(current,before)
        for key in current:
            if key!='read_route':self.assertEqual(value[key],before[key])

if __name__=='__main__':unittest.main()
