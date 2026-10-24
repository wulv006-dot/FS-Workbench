import copy
import json
import os
import sqlite3
import tempfile
import threading
import stat
from concurrent.futures import ThreadPoolExecutor
import unittest
from pathlib import Path
from types import SimpleNamespace

from bridge import handle
from campaign_backend import benefits
from campaign_backend.core import ContractError, canonical
from campaign_backend.ledger import OperationLedger, private_metadata
from campaign_backend.services import BackendServices
from test_benefit_operations import Reader, native_row, policy


class NativeReader(Reader):
    def __init__(self, body=b'{"code":1,"msg":"synthetic success"}', status=200):
        super().__init__()
        self.body, self.status, self.gets = body, status, 0
        self.fail_after_post = False
        self.after_post = None
        self.before_detail = None
        self.retry_total = 0
        self.session.admin.get_adapter = lambda url: SimpleNamespace(max_retries=SimpleNamespace(total=self.retry_total))

    def detail(self, *args):
        self.gets += 1
        if self.before_detail:
            self.before_detail(self)
        if self.calls and self.fail_after_post:
            raise ContractError('UPSTREAM_UNAVAILABLE')
        return copy.deepcopy(self.row)

    def post(self, url, **kwargs):
        self.calls.append((url, copy.deepcopy(kwargs)))
        self.row = copy.deepcopy(kwargs['json'])
        self.row['update_time'] += 1
        if self.after_post:
            self.after_post(self)
        if self.timeout:
            raise TimeoutError('PRIVATE_TRANSPORT_TOKEN')
        return SimpleNamespace(status_code=self.status, content=self.body)


class FullPreserveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'operations.sqlite3'
        self.ledger = OperationLedger(self.path)
        self.reader = NativeReader()

    def tearDown(self):
        self.temp.cleanup()

    def request(self, op='full-operation-edit', **changes):
        return dict(action='benefit_edit', site_id='266', kind='coupon', native_id='123',
            operation_id=op, before_hash=benefits.row_hash(self.reader.row), changes=changes or {'title':'Changed synthetic title','brief':'Changed synthetic brief'})

    def mutate(self, request):
        return benefits.mutate(self.reader, OperationLedger(self.path), policy(), request)

    def restore(self, source='full-operation-edit', op='full-operation-restore', **overrides):
        request = dict(action='benefit_restore', site_id='266', kind='coupon', native_id='123',
            operation_id=op, restore_of=source, before_hash=benefits.row_hash(self.reader.row))
        request.update(overrides)
        return self.mutate(request)

    def test_complete_payload_types_headers_and_private_durable_material(self):
        self.reader.row.update(goods_id=0, start_time='', end_time=0)
        p = policy();p['coupon_objects']['123']['goods_id']='0'
        original=copy.deepcopy(self.reader.row)
        request=self.request()
        result=benefits.mutate(self.reader,self.ledger,p,request)
        self.assertEqual(result['state'],'confirmed')
        native=self.reader.calls[0][1]['json']
        self.assertEqual(set(native), benefits.NATIVE_FIELDS)
        self.assertEqual(len(native),28)
        self.assertEqual(native,dict(original,**request['changes']))
        self.assertTrue(all(type(native[k]) is type(original[k]) for k in native))
        options=self.reader.calls[0][1]
        self.assertEqual(options['headers'],{'batoken':'fixture-only','server':'true','think-lang':'zh-cn'})
        self.assertFalse(options['allow_redirects'])
        state=OperationLedger(self.path).native_state(request['operation_id'])
        self.assertEqual(state['original'],original)
        self.assertEqual(state['expected'],native)
        self.assertNotIn('SECRET_PARAM',json.dumps(result))
        self.assertNotIn('original',result)
        if os.name=='posix':self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

    def test_old_partial_policy_does_not_enable_any_write(self):
        p=policy();p['coupon_objects']['123'].pop('fs_bridge_acceptance_verified')
        view=benefits.detail(self.reader,p,'coupon','123','266')
        self.assertEqual(view['editability']['allowed_changes'],[])
        self.assertFalse(view['editability']['can_disable'])
        self.assertEqual(benefits.mutate(self.reader,self.ledger,p,self.request())['state'],'rejected')
        self.assertEqual(self.reader.calls,[])

    def test_toggle_requires_own_full_preserve_proof_not_text_proof(self):
        p=policy();p['coupon_objects']['123'].pop('full_preserve_toggle_verified')
        self.reader.row['status']=1
        req=self.request();req.update(action='benefit_toggle',enabled=False);req.pop('changes')
        self.assertEqual(benefits.mutate(self.reader,self.ledger,p,req)['state'],'rejected')
        self.assertEqual(self.reader.calls,[])

    def test_unknown_schema_or_type_never_posts(self):
        variants=[dict(native_row(),unexpected='not allowed'),dict(native_row(),goods_id='0'),dict(native_row(),start_time=None),dict(native_row(),status=True)]
        missing=native_row();missing.pop('remark');variants.append(missing)
        for index,row in enumerate(variants):
            with self.subTest(index=index):
                self.reader.row=row
                result=self.mutate(self.request('invalid-schema-'+str(index)))
                self.assertEqual(result['state'],'rejected')
        self.assertEqual(self.reader.calls,[])

    def test_explicit_success_required_and_even_matching_row_stays_unknown(self):
        for index,body in enumerate([b'{"code":0}',b'{"code":"1"}',b'{"code":true}',b'not json',b'{"data":{"code":1}}']):
            with self.subTest(body=body):
                path=Path(self.temp.name)/('failure'+str(index)+'.sqlite3')
                ledger=OperationLedger(path);reader=NativeReader(body=body)
                req=dict(self.request('non-success-'+str(index)),before_hash=benefits.row_hash(reader.row))
                first=benefits.mutate(reader,ledger,policy(),req)
                self.assertEqual(first['state'],'unknown')
                self.assertEqual(reader.gets,3) # detail gate + two pre-dispatch reads, no post-response GET
                self.assertEqual(benefits.operation(OperationLedger(path),reader,'266',req['operation_id'],True)['state'],'unknown')
                self.assertEqual(benefits.mutate(reader,OperationLedger(path),policy(),req),OperationLedger(path).lookup(req['operation_id']))
                self.assertEqual(len(reader.calls),1)

    def test_success_audit_then_get_failure_recovers_original_only_after_restart(self):
        request=self.request()
        self.reader.fail_after_post=True
        first=self.mutate(request)
        self.assertEqual(first['state'],'unknown')
        self.assertEqual(len(self.ledger.native_response_audit(request['operation_id'])),1)
        self.reader.fail_after_post=False
        self.assertEqual(benefits.operation(OperationLedger(self.path),self.reader,'266',request['operation_id'],True)['state'],'confirmed')
        self.assertEqual(len(self.reader.calls),1)

    def test_timeout_never_confirms_matching_row_and_cannot_restore(self):
        self.reader.timeout=True
        request=self.request();self.assertEqual(self.mutate(request)['state'],'unknown')
        self.assertEqual(benefits.operation(self.ledger,self.reader,'266',request['operation_id'],True)['state'],'unknown')
        response=self.restore()
        self.assertTrue(response['object_busy'])
        self.assertEqual(len(self.reader.calls),1)

    def test_snapshot_or_audit_failure_never_retries_or_restores(self):
        for attribute,expected_posts in [('record_native_state',0),('record_native_response',1)]:
            with self.subTest(attribute=attribute):
                path=Path(self.temp.name)/(attribute+'.sqlite3');ledger=OperationLedger(path);reader=NativeReader()
                req=self.request(attribute)
                def broken(*args):raise OSError('PRIVATE_STORAGE_FAILURE')
                setattr(ledger,attribute,broken)
                first=benefits.mutate(reader,ledger,policy(),req)
                self.assertEqual(first['state'],'unknown')
                self.assertEqual(len(reader.calls),expected_posts)
                restarted=OperationLedger(path)
                self.assertEqual(benefits.operation(restarted,reader,'266',req['operation_id'],True)['state'],'unknown')
                self.assertEqual(benefits.mutate(reader,restarted,policy(),req),restarted.lookup(req['operation_id']))
                self.assertEqual(len(reader.calls),expected_posts)

    def test_retry_adapter_unknown_or_nonzero_blocks_before_post(self):
        for index,total in enumerate([None,False,1,3]):
            self.reader.retry_total=total
            self.assertEqual(self.mutate(self.request('retry-total-'+str(index)))['state'],'rejected')
        self.assertEqual(self.reader.calls,[])

    def test_second_fresh_read_catches_concurrent_change_with_zero_posts(self):
        def change(reader):
            if reader.gets==3:reader.row['reduce']='7.00'
        self.reader.before_detail=change
        result=self.mutate(self.request())
        self.assertEqual((result['state'],result['dispatch_state']),('rejected','not_started'))
        self.assertEqual(self.reader.calls,[])

    def test_nontext_post_change_or_type_change_cannot_confirm(self):
        self.reader.after_post=lambda reader:reader.row.update(reduce='changed after dispatch')
        req=self.request();self.assertEqual(self.mutate(req)['state'],'unknown')
        self.assertEqual(benefits.operation(self.ledger,self.reader,'266',req['operation_id'],True)['state'],'unknown')
        self.assertEqual(len(self.reader.calls),1)

    def test_restore_original_text_preserves_latest_other_fields_and_has_one_permanent_owner(self):
        original=copy.deepcopy(self.reader.row)
        req=self.request();self.assertEqual(self.mutate(req)['state'],'confirmed')
        self.reader.row.update(status=1,start_time='2030-01-02 03:04:05',end_time='',reduce='73.25',remark='Later safe management change')
        latest=copy.deepcopy(self.reader.row)
        first=self.restore()
        self.assertEqual(first['state'],'confirmed')
        self.assertEqual(self.reader.calls[1][1]['json'],dict(latest,title=original['title'],brief=original['brief']))
        # Another accepted edit after restoration must never be overwritten by a new compensation ID.
        self.reader.row['title']='Later operator title'
        repeated=self.restore(op='different-restore-id')
        self.assertTrue(repeated['object_busy'])
        self.assertEqual(repeated['operation_id'],'full-operation-restore')
        self.assertEqual(len(self.reader.calls),2)
        self.assertEqual(self.reader.row['title'],'Later operator title')

    def test_restore_refuses_changed_text_scope_or_claims(self):
        for index,change in enumerate([{'title':'Someone else changed text'},{'fetch_qty':1},{'used_qty':1},{'game_id':100},{'product_type':2}]):
            path=Path(self.temp.name)/('restore-change-'+str(index)+'.sqlite3');reader=NativeReader();ledger=OperationLedger(path)
            req=dict(self.request('source-'+str(index)),before_hash=benefits.row_hash(reader.row))
            self.assertEqual(benefits.mutate(reader,ledger,policy(),req)['state'],'confirmed')
            reader.row.update(change)
            restore=dict(action='benefit_restore',site_id='266',kind='coupon',native_id='123',restore_of=req['operation_id'],
                operation_id='restore-'+str(index),before_hash=benefits.row_hash(reader.row))
            self.assertEqual(benefits.mutate(reader,ledger,policy(),restore)['state'],'rejected')
            self.assertEqual(len(reader.calls),1)

    def test_restore_cannot_reference_toggle_or_accept_browser_rows(self):
        self.reader.row['status']=1
        req=self.request();req.update(action='benefit_toggle',enabled=False);req.pop('changes')
        self.assertEqual(self.mutate(req)['state'],'confirmed')
        self.assertEqual(self.restore()['state'],'rejected')
        self.assertEqual(len(self.reader.calls),1)
        with self.assertRaisesRegex(ContractError,'REQUEST_FIELDS_NOT_ALLOWED'):
            handle(dict(action='benefit_restore',site_id='266',original_row={}),services=BackendServices(self.temp.name,policy()))

    def test_service_restore_action_is_reachable_but_snapshot_never_returned(self):
        service=BackendServices(self.temp.name,policy())
        req=self.request()
        self.assertEqual(handle(req,services=service,reader_factory=lambda:self.reader)['state'],'confirmed')
        restore=dict(action='benefit_restore',site_id='266',kind='coupon',native_id='123',restore_of=req['operation_id'],
            operation_id='reachable-restore',before_hash=benefits.row_hash(self.reader.row))
        result=handle(restore,services=service,reader_factory=lambda:self.reader)
        self.assertEqual(result['state'],'confirmed')
        self.assertNotIn('SECRET_PARAM',json.dumps(result))
        self.assertNotIn('original',result)

    def test_legacy_unknown_without_snapshot_cannot_be_upgraded_from_current_text(self):
        req=self.request();payload=dict(action='benefit_edit',kind='coupon',site_id='266',native_id='123',
            changes=req['changes'],before_hash=req['before_hash'],scope={'site_id':'266','game_id':'1327','goods_id':'170014917'})
        self.ledger.prepare(req['operation_id'],payload)
        with self.ledger._connection() as db:db.execute("UPDATE operations SET state='unknown',dispatched=1")
        self.reader.row.update(req['changes'])
        self.assertEqual(benefits.operation(self.ledger,self.reader,'266',req['operation_id'],True)['state'],'unknown')
        self.assertEqual(self.reader.gets,0)

    def test_client_int_zero_time_retains_its_exact_type_and_business_failure_freezes(self):
        self.reader.row.update(start_time=0,end_time=0)
        self.reader.body=b'{"code":0,"msg":"PRIVATE_NATIVE_VALIDATION_DETAILS"}'
        req=self.request();self.assertEqual(self.mutate(req)['state'],'unknown')
        self.assertIs(type(self.reader.calls[0][1]['json']['start_time']),int)
        self.assertEqual(self.reader.calls[0][1]['json']['start_time'],0)
        self.assertNotIn('PRIVATE_NATIVE',json.dumps(self.ledger.native_response_audit(req['operation_id'])))
        self.assertTrue(self.restore()['object_busy'])
        self.assertEqual(len(self.reader.calls),1)

    def test_http_201_with_code_one_never_confirms_or_restores(self):
        self.reader.status=201
        req=self.request();self.assertEqual(self.mutate(req)['state'],'unknown')
        self.assertEqual(benefits.operation(self.ledger,self.reader,'266',req['operation_id'],True)['state'],'unknown')
        self.assertTrue(self.restore()['object_busy'])
        self.assertEqual(len(self.reader.calls),1)

    def test_private_metadata_rejects_broad_permissions_owner_symlinks_and_hardlinks(self):
        private_metadata(SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=21,st_nlink=2),True,21)
        private_metadata(SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=21,st_nlink=1),False,21)
        for mode,owner,links,directory in [(stat.S_IFDIR|0o755,21,2,True),(stat.S_IFREG|0o644,21,1,False),
            (stat.S_IFREG|0o600,22,1,False),(stat.S_IFLNK|0o600,21,1,False),(stat.S_IFREG|0o600,21,2,False)]:
            with self.assertRaisesRegex(ContractError,'PRIVATE_LEDGER_REQUIRED'):
                private_metadata(SimpleNamespace(st_mode=mode,st_uid=owner,st_nlink=links),directory,21)

    def test_conflicting_same_id_never_posts_twice(self):
        req=self.request();self.assertEqual(self.mutate(req)['state'],'confirmed')
        conflict=dict(req,changes={'title':'Conflicting new text'})
        self.assertEqual(self.mutate(conflict)['state'],'unknown')
        self.assertEqual(len(self.reader.calls),1)
        self.assertEqual(self.ledger.lookup(req['operation_id'])['state'],'confirmed')

    def test_concurrent_reconcile_while_response_outstanding_cannot_unlock(self):
        entered,resume=threading.Event(),threading.Event()
        original=self.reader.post
        def slow(*args,**kwargs):
            entered.set()
            if not resume.wait(5):raise AssertionError('fixture not resumed')
            return original(*args,**kwargs)
        self.reader.session.admin.post=slow
        req=self.request();results=[]
        worker=threading.Thread(target=lambda:results.append(self.mutate(req)))
        worker.start();self.assertTrue(entered.wait(5))
        try:
            self.assertEqual(benefits.operation(OperationLedger(self.path),self.reader,'266',req['operation_id'],True)['state'],'unknown')
            self.assertTrue(self.mutate(self.request('different-concurrent-id'))['object_busy'])
        finally:resume.set();worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]['state'],'confirmed')
        self.assertEqual(len(self.reader.calls),1)

    def test_concurrent_restore_ids_have_one_permanent_owner_across_connections(self):
        req=self.request();self.assertEqual(self.mutate(req)['state'],'confirmed')
        before=benefits.row_hash(self.reader.row);start=threading.Barrier(2)
        def run(index):
            start.wait(5)
            return self.restore(op='parallel-restore-'+str(index),before_hash=before)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
        self.assertEqual(len(self.reader.calls),2)
        self.assertEqual(len({row['operation_id'] for row in results}),1)
        self.assertEqual(len([row for row in results if row.get('object_busy')]),1)
        owner=results[0]['operation_id']
        self.assertEqual(OperationLedger(self.path).lookup(owner)['state'],'confirmed')

    def test_snapshot_immutable_and_wrong_audit_binding_cannot_confirm(self):
        self.reader.fail_after_post=True
        req=self.request();self.assertEqual(self.mutate(req)['state'],'unknown')
        state=self.ledger.native_state(req['operation_id'])
        with self.assertRaisesRegex(ContractError,'NATIVE_SNAPSHOT_CONFLICT'):
            self.ledger.record_native_state(req['operation_id'],state['original'],dict(state['expected'],brief='different snapshot'))
        with self.ledger._connection() as db:
            db.execute("UPDATE native_response_audit SET request_payload_hash=?",('0'*64,))
        self.reader.fail_after_post=False
        self.assertEqual(benefits.operation(OperationLedger(self.path),self.reader,'266',req['operation_id'],True)['state'],'unknown')
        self.assertEqual(len(self.reader.calls),1)

    def test_restore_missing_source_is_durable_rejection_and_cannot_take_client_text(self):
        req=dict(action='benefit_restore',site_id='266',kind='coupon',native_id='123',operation_id='missing-source-restore',
            before_hash=benefits.row_hash(self.reader.row))
        result=self.mutate(req)
        self.assertEqual((result['state'],result['dispatch_state']),('rejected','not_started'))
        self.assertEqual(self.reader.calls,[])
        self.assertEqual(self.mutate(req),result)
        self.assertEqual(self.mutate(self.request())['state'],'confirmed')
        self.assertEqual(self.restore(changes={'title':'Browser supplied recovery'})['state'],'rejected')
        self.assertEqual(len(self.reader.calls),1)

    def test_unstarted_invalid_restore_never_consumes_original_compensation_slot(self):
        for index,failure in enumerate(('before_hash','wrong_scope','policy_denied')):
            with self.subTest(failure=failure):
                path=Path(self.temp.name)/('unstarted-restore-'+str(index)+'.sqlite3')
                ledger=OperationLedger(path);reader=NativeReader();req=dict(self.request('source-restore-'+str(index)),before_hash=benefits.row_hash(reader.row))
                self.assertEqual(benefits.mutate(reader,ledger,policy(),req)['state'],'confirmed')
                restore=dict(action='benefit_restore',site_id='266',kind='coupon',native_id='123',restore_of=req['operation_id'],
                    operation_id='invalid-restore-'+str(index),before_hash=benefits.row_hash(reader.row))
                private_policy=policy()
                if failure=='before_hash':restore['before_hash']='wrong'
                if failure=='wrong_scope':restore['native_id']='124'
                if failure=='policy_denied':private_policy={}
                rejected=benefits.mutate(reader,ledger,private_policy,restore)
                self.assertEqual((rejected['state'],rejected['dispatch_state']),('rejected','not_started'))
                with ledger._connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM native_restore_claims').fetchone()[0],0)
                valid=dict(restore,native_id='123',operation_id='valid-restore-'+str(index),before_hash=benefits.row_hash(reader.row))
                self.assertEqual(benefits.mutate(reader,OperationLedger(path),policy(),valid)['state'],'confirmed')
                self.assertEqual(len(reader.calls),2)

    def test_restore_final_fresh_cas_rejection_releases_only_unstarted_claim(self):
        self.assertEqual(self.mutate(self.request())['state'],'confirmed')
        baseline_gets=self.reader.gets
        def concurrent(reader):
            # Restore detail, source preflight, dispatch first read, dispatch second fresh read.
            if reader.gets==baseline_gets+4:reader.row['reduce']='66.75'
        self.reader.before_detail=concurrent
        rejected=self.restore(op='cas-rejected-restore')
        self.assertEqual((rejected['state'],rejected['dispatch_state']),('rejected','not_started'))
        self.assertEqual(len(self.reader.calls),1)
        self.reader.before_detail=None
        self.assertEqual(self.restore(op='fresh-after-cas-restore')['state'],'confirmed')
        self.assertEqual(len(self.reader.calls),2)


if __name__=='__main__':unittest.main()
