from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import coin_all_once as once
import coin_all_sync_job as sync
import player_verify_once as players
from test_coin_all_sync import fixtures,Manager


class OnceTest(unittest.TestCase):
    def setUp(self):
        self.rows,self.reference,self.policy=fixtures()
        self.reference['execution_id']='00000000-0000-4000-8000-000000000001'
        self.manager=Manager(self.rows)
        self.packet=once.preview(self.manager,self.reference,self.policy,'original-hash')
        self.packet.update(approved_once=True,actor='approved-validation')
    def run_apply(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'executions').mkdir();(root/'all-coin-sync').mkdir()
            return once.apply_once(self.manager,self.packet,self.reference,self.policy,'original-hash',root,lambda:self.policy)
    def test_default_preview_has_no_posts_or_approval(self):
        self.assertEqual(self.manager.posts,[])
        self.assertNotEqual(self.packet['execution_id'],self.reference['execution_id'])
    def test_expired_preview_stops_before_post(self):
        self.packet['prepared_at']=(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()
        with self.assertRaisesRegex(ValueError,'expired'):self.run_apply()
        self.assertEqual(self.manager.posts,[])
    def test_missing_single_use_authorization_stops(self):
        self.packet['approved_once']=False
        with self.assertRaisesRegex(ValueError,'approval_missing'):self.run_apply()
    def test_reference_change_stops(self):
        self.packet['reference_hash']='different'
        with self.assertRaisesRegex(ValueError,'preview_changed'):self.run_apply()
    def test_fresh_price_change_stops(self):
        self.rows[163329309]['unit_price']=0.123
        with self.assertRaisesRegex(ValueError,'preview_changed'):self.run_apply()
    def test_cannot_reuse_original_job_id(self):
        self.packet['execution_id']=self.reference['execution_id']
        with self.assertRaisesRegex(ValueError,'identity_invalid'):self.run_apply()
    def test_new_audit_original_immutable_and_no_replay(self):
        original=deepcopy(self.reference)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'executions').mkdir();(root/'all-coin-sync').mkdir()
            def mirror(record,policy,save,root,read_policy):
                record.update(status='CONFIRMED',all_baseline={'status':'confirmed'});save(record)
                return {'status':'confirmed'}
            def atomic(path,value):path.write_text(json.dumps(value))
            original_api=sync.api
            def api(manager,path,payload=None):
                return {} if path.startswith('/admin/tools.Caches/') else original_api(manager,path,payload)
            with patch.object(sync,'mirror_confirmed',side_effect=mirror),patch.object(sync,'atomic',side_effect=atomic),patch.object(sync,'api',side_effect=api):
                once.apply_once(self.manager,self.packet,self.reference,self.policy,'original-hash',root,lambda:self.policy)
                audit=json.loads((root/'executions'/(self.packet['execution_id']+'.json')).read_text())
                self.assertEqual(audit['status'],'ALL_ALIGNED')
                self.assertFalse(audit['mmoexp_write_performed'])
                with self.assertRaises(FileExistsError):
                    once.apply_once(self.manager,self.packet,self.reference,self.policy,'original-hash',root,lambda:self.policy)
        self.assertEqual(self.reference,original)
    def test_player_entry_rejects_missing_approval_without_post(self):
        with self.assertRaisesRegex(ValueError,'approval_missing'):
            players.execute(None,None,{}, {},lambda:{},lambda:{},Path('.'))
    def test_player_category_scope_cannot_be_changed(self):
        packet={'scope':'fc27_players_category_validation_once','approved_once':True,
                'native_request':{'gid':1327,'cid':9623,'id':[]}}
        with self.assertRaisesRegex(ValueError,'category_changed'):
            players.execute(None,None,packet,{},lambda:{},lambda:{},Path('.'))
    def test_player_preview_requires_global_switch_off_and_all_confirmed(self):
        with self.assertRaisesRegex(ValueError,'preflight_changed'):
            players.prepare(None,None,{'status':'PARTIAL'},{},{'enabled':False})


class PlayerOnceExecutionTest(unittest.TestCase):
    def run_validation(self,transport_error=False,mismatch=False):
        cp={'revision':18};pp={'revision':7,'enabled':False}
        model={'id':players.TARGET_MODEL,'gid':1327,'cid':9627,'status':1,'title':'Player / Gold'}
        sample={'id':players.TARGET_MODEL,'title':'Player','product_ids':[11,12,13]}
        parts=[{'platform':p,'our_price_coins':'100000','coefficient':'1.1',
                'backend_match':not mismatch,'public_match':not mismatch} for p in ('PS','XBOX','PC')]
        packet={'scope':'fc27_players_category_validation_once','approved_once':True,
            'native_request':{'gid':1327,'cid':9627,'id':[]},
            'job_id':'00000000-0000-4000-8000-000000000099',
            'prepared_at':datetime.now(timezone.utc).isoformat(),
            'coin_policy_hash':once.digest(cp),'player_policy_hash':once.digest(pp),
            'model_ids_hash':once.digest([players.TARGET_MODEL]),'samples':[sample],
            'sample_before':{str(players.TARGET_MODEL):parts},
            'rates':{p:'0.1252' for p in ('PS','XBOX','PC')}}
        alignment={'status':'ALL_ALIGNED','execution_id':'00000000-0000-4000-8000-000000000001'}
        calls=[]
        def recalc(_):
            calls.append('category_post')
            if transport_error:raise OSError('unknown result')
        player=types.SimpleNamespace(list_models=lambda _:[model],products=lambda *a:[{'id':i} for i in (11,12,13)],
            api=lambda *a:{'row':model},public_formula_status=lambda *a:parts,recalculate_category=recalc)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'executions').mkdir()
            def atomic(path,value):path.write_text(json.dumps(value))
            with patch.object(sync,'plan',return_value=[{'changed':False}]),patch.object(sync,'api',return_value={}),patch.object(sync,'atomic',side_effect=atomic),patch.object(players.time,'monotonic',side_effect=[0,181]):
                if transport_error or mismatch:
                    with self.assertRaises(OSError if transport_error else ValueError):
                        players.execute(None,player,packet,alignment,lambda:cp,lambda:pp,root)
                else:
                    result=players.execute(None,player,packet,alignment,lambda:cp,lambda:pp,root)
                    self.assertEqual(result['status'],'validated')
                audit=json.loads((root/'executions'/(packet['job_id']+'.json')).read_text())
                self.assertEqual(audit['status'],'UNCERTAIN' if transport_error or mismatch else 'VALIDATED')
                self.assertFalse(pp['enabled'])
        self.assertEqual(calls,['category_post'])
    def test_one_category_request_and_actual_readbacks_leave_global_switch_off(self):self.run_validation()
    def test_transport_failure_is_not_replayed(self):self.run_validation(transport_error=True)
    def test_formula_mismatch_keeps_new_task_uncertain(self):self.run_validation(mismatch=True)


if __name__=='__main__':unittest.main()
