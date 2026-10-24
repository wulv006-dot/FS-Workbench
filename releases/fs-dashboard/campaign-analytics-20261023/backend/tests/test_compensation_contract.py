import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from bridge import handle
from campaign_backend import benefits
from campaign_backend.core import ContractError, canonical
from campaign_backend.ledger import OperationLedger, ObjectOperationBusy, now
from campaign_backend.services import BackendServices
from test_benefit_operations import Reader, native_row, policy


class CompensationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'operations.sqlite3'
        self.ledger = OperationLedger(self.path)
        self.operation_id = 'synthetic-original-edit'
        self.reference = 'synthetic-proof-16'
        self.original = native_row()
        self.expected = dict(self.original, title='Synthetic edited title', brief=' Synthetic edited brief')
        self.payload = dict(action='benefit_edit', kind='coupon', site_id='266', native_id='123',
            scope={'site_id':'266','game_id':'1327','goods_id':'170014917'},
            before_hash=benefits.row_hash(self.original), changes={k:self.expected[k] for k in ('title','brief')})
        self.ledger.prepare(self.operation_id,self.payload)
        with self.ledger._connection() as db:
            db.execute("UPDATE operations SET state='unknown',dispatched=1 WHERE operation_id=?",(self.operation_id,))
        self.ledger.record_native_state(self.operation_id,self.original,self.expected)
        self.ledger.record_native_response(self.operation_id,self.response())
        self.reader = Reader(copy.deepcopy(self.original))
        self.gets = 0
        self.fail_get = False
        self.original_detail = self.reader.detail
        def detail(*args):
            self.gets += 1
            if self.fail_get:raise ContractError('UPSTREAM_UNAVAILABLE')
            return self.original_detail(*args)
        self.reader.detail = detail
        self.proof = self.make_proof()
        self.server_policy = policy()
        self.write_proof()
        self.before = self.history()

    def tearDown(self):
        self.temp.cleanup()

    def response(self,code=1):
        return benefits.safe_response_evidence(response=SimpleNamespace(status_code=200,
            content=json.dumps({'code':code,'msg':'synthetic success'}).encode()))

    def make_proof(self):
        with self.ledger._connection() as db:
            audit=dict(db.execute('SELECT * FROM native_response_audit WHERE operation_id=?',(self.operation_id,)).fetchone())
        return dict(schema_version=1,contract='coupon-single-leading-ascii-brief-compensation-v1',
            reference=self.reference,original_operation_id=self.operation_id,object_ref=['266','coupon','123'],
            original_payload_hash=benefits.row_hash(self.payload),
            original_snapshot_hash=benefits.row_hash(dict(original=self.original,expected=self.expected)),
            original_audit_hash=benefits.row_hash(audit),compensation=dict(reference='synthetic-native-compensation',
                linked_original_operation_id=self.operation_id,
                before_row=dict(self.expected,brief=self.expected['brief'][1:]),native_payload=copy.deepcopy(self.original),
                response_evidence=self.response(),independent_readback=copy.deepcopy(self.original),
                independent_readback_at=now()))

    def write_proof(self, approve=True):
        root=self.root/'compensation-proofs';root.mkdir(mode=0o700,exist_ok=True)
        raw=canonical(self.proof).encode()
        path=root/(self.reference+'.json')
        descriptor=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(descriptor,'wb') as output:output.write(raw)
        if approve:self.server_policy.setdefault('compensation_proofs',{})[self.reference]=hashlib.sha256(raw).hexdigest()

    def history(self):
        with self.ledger._connection() as db:
            return {name:[dict(row) for row in db.execute('SELECT * FROM '+name)] for name in
                ('operations','operation_objects','native_operation_state','native_response_audit','native_restore_claims')}

    def record(self):
        return BackendServices(self.root,self.server_policy).record_manual_compensation(self.reference,lambda:self.reader)

    def test_append_resolution_preserves_unknown_history_and_only_releases_proved_owner(self):
        result=self.record()
        self.assertEqual(result['status'],'compensated');self.assertFalse(result['native_write_authorization'])
        original=OperationLedger(self.path).lookup(self.operation_id)
        self.assertEqual(original['state'],'unknown');self.assertFalse(original['object_lock_active'])
        self.assertEqual(original['resolution'],result);self.assertEqual(self.history(),self.before)
        new=dict(self.payload,changes={'title':'Future independently authorized request'})
        self.ledger.prepare('future-request-after-compensation',new)
        self.assertEqual(self.reader.calls,[])
        self.assertNotIn('SECRET_',json.dumps(original))

    def test_repeat_after_restart_is_idempotent_even_if_later_editor_changed_current(self):
        first=self.record();self.reader.row['title']='A later operator change'
        self.assertEqual(self.record(),first);self.assertEqual(self.gets,1)
        with self.ledger._connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM operation_compensations').fetchone()[0],1)

    def test_unapproved_self_claim_and_modified_approved_file_are_rejected(self):
        with self.assertRaisesRegex(ContractError,'NOT_APPROVED'):
            BackendServices(self.root,{}).record_manual_compensation(self.reference,lambda:self.reader)
        self.proof['compensation']['reference']='tampered after approval';self.write_proof(approve=False)
        with self.assertRaisesRegex(ContractError,'NOT_APPROVED'):self.record()
        self.assertTrue(self.owner_busy());self.assertEqual(self.gets,0)

    def owner_busy(self):
        try:self.ledger.prepare('a-blocked-new-operation',dict(self.payload,changes={'title':'Another'}))
        except ObjectOperationBusy:return True
        return False

    def test_approved_but_wrong_original_object_or_payload_is_not_trusted(self):
        self.proof['object_ref']=['266','coupon','999'];self.write_proof()
        with self.assertRaisesRegex(ContractError,'PROOF_INVALID'):self.record()
        self.assertTrue(self.owner_busy());self.assertEqual(self.history(),self.before)

    def test_compensation_failure_code_or_missing_original_audit_never_unlocks(self):
        self.proof['compensation']['response_evidence']=self.response(0);self.write_proof()
        with self.assertRaisesRegex(ContractError,'PROOF_INVALID'):self.record()
        self.assertTrue(self.owner_busy())
        self.proof=self.make_proof();self.write_proof()
        with self.ledger._connection() as db:db.execute('DELETE FROM native_response_audit')
        with self.assertRaisesRegex(ContractError,'PROOF_INVALID'):self.record()
        self.assertTrue(self.owner_busy())

    def test_stale_readback_or_substantive_normalization_differences_fail_closed(self):
        self.reader.row['reduce']='An external later change'
        with self.assertRaisesRegex(ContractError,'PROOF_INVALID'):self.record()
        self.reader.row=copy.deepcopy(self.original)
        self.proof['compensation']['before_row']['title']='Different title';self.write_proof()
        with self.assertRaisesRegex(ContractError,'PROOF_INVALID'):self.record()
        self.assertTrue(self.owner_busy())

    def test_only_single_leading_ascii_loss_contract_not_general_strip(self):
        self.proof['compensation']['before_row']['brief']='Synthetic edited brief '.strip()
        # This equals the exact expected one-space removal and can be proved.
        self.assertEqual(self.record()['status'],'compensated')
        # Readback itself is never normalized: even trailing whitespace remains substantive.
        self.assertFalse(benefits.same_native(dict(self.original,brief='value '),dict(self.original,brief='value')))

    def test_interrupted_append_rolls_back_then_same_reference_can_retry_without_native_write(self):
        self.fail_get=True
        with self.assertRaisesRegex(ContractError,'UPSTREAM_UNAVAILABLE'):self.record()
        self.assertTrue(self.owner_busy());self.fail_get=False
        with self.ledger._connection() as db:
            db.execute("CREATE TRIGGER synthetic_fail_insert BEFORE INSERT ON operation_compensations BEGIN SELECT RAISE(ABORT,'synthetic interrupted append'); END")
        with self.assertRaises(ContractError):self.record()
        self.assertTrue(self.owner_busy())
        with self.ledger._connection() as db:db.execute('DROP TRIGGER synthetic_fail_insert')
        self.assertEqual(self.record()['status'],'compensated');self.assertEqual(self.reader.calls,[])

    def test_concurrent_connections_append_once_and_do_not_repeat_fresh_get(self):
        start=threading.Barrier(2)
        def record(_):start.wait(5);return self.record()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(record,range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(self.gets,1)
        self.assertEqual(self.reader.calls,[])

    def test_resolved_reconcile_and_stale_record_never_change_original_unknown(self):
        self.record();before=self.history();self.reader.row=copy.deepcopy(self.expected)
        result=benefits.operation(self.ledger,self.reader,'266',self.operation_id,True)
        self.assertEqual(result['state'],'unknown');self.assertEqual(result['resolution']['status'],'compensated')
        self.assertEqual(self.gets,1)
        self.ledger._record(self.operation_id,dict(state='confirmed',upstream_ref='123'))
        self.assertEqual(self.history(),before)
        result=self.ledger.execute(self.operation_id,self.payload,benefits.CouponEdit(self.reader,self.payload))
        self.assertEqual(result['state'],'unknown');self.assertEqual(self.reader.calls,[])

    def test_other_legacy_unknown_stays_busy_and_cannot_gain_resolution_without_its_chain(self):
        legacy=dict(self.payload)
        with self.ledger._connection() as db:
            db.execute("INSERT INTO operations VALUES (?,?,?,'unknown',1,NULL,?,?)",
                ('legacy-08-synthetic',canonical(legacy),benefits.row_hash(legacy),now(),now()))
        self.record();self.assertTrue(self.owner_busy())
        self.assertIsNone(self.ledger.lookup('legacy-08-synthetic').get('resolution'))
        with self.ledger._connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM operation_compensations')

    def test_different_approved_reference_cannot_recompensate_same_original(self):
        self.record();self.reference='another-approved-reference';self.proof['reference']=self.reference
        self.write_proof()
        with self.assertRaisesRegex(ContractError,'ALREADY_RECORDED'):self.record()
        with self.ledger._connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM operation_compensations').fetchone()[0],1)

    def test_trusted_import_has_no_http_action_or_arbitrary_path(self):
        service=BackendServices(self.root,self.server_policy)
        with self.assertRaisesRegex(ContractError,'REFERENCE_INVALID'):service.record_manual_compensation('../unsafe-path',lambda:self.reader)
        with self.assertRaisesRegex(ContractError,'ACTION_NOT_ALLOWED'):
            handle(dict(action='record_manual_compensation',site_id='266'),services=service,reader_factory=lambda:self.reader)
        self.assertTrue(self.owner_busy())


class TextInputTests(unittest.TestCase):
    def test_leading_ascii_rejected_durably_without_post_and_exact_replay_is_stable(self):
        with tempfile.TemporaryDirectory() as root:
            ledger=OperationLedger(Path(root)/'operations.sqlite3');reader=Reader()
            request=dict(action='benefit_edit',site_id='266',kind='coupon',native_id='123',operation_id='leading-space-operation',
                before_hash=benefits.row_hash(reader.row),changes={'brief':' leading ASCII space'})
            first=benefits.mutate(reader,ledger,policy(),request)
            self.assertEqual((first['state'],first['dispatch_state']),('rejected','not_started'))
            self.assertEqual(first['result']['reason_code'],'BRIEF_LEADING_ASCII_SPACE_NOT_ALLOWED')
            self.assertEqual(benefits.mutate(reader,ledger,policy(),request),first);self.assertEqual(reader.calls,[])

    def test_business_success_and_other_characters_use_exact_payload_and_readback(self):
        with tempfile.TemporaryDirectory() as root:
            ledger=OperationLedger(Path(root)/'operations.sqlite3');reader=Reader()
            request=dict(action='benefit_edit',site_id='266',kind='coupon',native_id='123',operation_id='exact-text-operation',
                before_hash=benefits.row_hash(reader.row),changes={'title':'Case-sensitive title','brief':'\u00a0NBSP preserved <literal> '})
            self.assertEqual(benefits.mutate(reader,ledger,policy(),request)['state'],'confirmed')
            self.assertEqual(reader.calls[0][1]['json']['brief'],request['changes']['brief'])
            self.assertEqual(reader.row['title'],request['changes']['title'])


if __name__=='__main__':unittest.main()
