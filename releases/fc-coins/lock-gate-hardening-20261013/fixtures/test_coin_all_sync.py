from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import coin_all_sync_job as sync


def fixtures():
    rows = {}
    for platform, (all_id, site_id, aid) in sync.PRODUCTS.items():
        for site, product_id in ((0,all_id),(266,site_id)):
            rows[product_id] = {'id':product_id,'mid':41217957,'gid':1327,'cid':9623,
                'site_id':site,'aid':aid,'unit':'K','title':'coins','status':1,'total':0,
                'unit_price':0.124 if site==0 else 0.1252,
                'keywords':'preserved','is_rec':1,'shelf_time':12345,'stat_view':12,
                'more':{'gold':[10,100],'discount':[100,100],'give':[0,5],
                        'delivery_time':['',''],'hot':[False,True],
                        'price':[1.24,12.4] if site==0 else [1.25,12.52]}}
    audit={'execution_id':'coin-test','status':'CONFIRMED','sync_confirmed':True,
           'automatic':True,'automation_policy_revision':18,
           'after':{'rows':[{'platform':p,'b2c':'0.1252'} for p in sync.PRODUCTS]}}
    policy={'revision':18,'system_enabled':True,'mode':'auto','platforms':list(sync.PRODUCTS)}
    return rows,audit,policy


class Manager:
    token='fixture'
    def __init__(self, rows):
        self.rows=rows; self.posts=[]; self.before_post=lambda *args:None
        self.reject=False; self.corrupt=False; self.lose_response=False
    def request(self,path,data=None,token=None):
        if path=='/admin/index/index':return 200,json.dumps({'code':1,'data':{'adminInfo':{'username':'chenchao'}}})
        product_id=int(path.rsplit('=',1)[1])
        if data is not None:
            self.before_post(product_id,data)
            self.posts.append(product_id)
            if self.reject:return 200,json.dumps({'code':0})
            self.rows[product_id].update(deepcopy(data))
            if self.corrupt:self.rows[product_id]['is_rec']=0
            if self.lose_response:raise OSError('simulated lost response')
        return 200,json.dumps({'code':1,'data':{'row':deepcopy(self.rows[product_id])}})


class AllBaselineTest(unittest.TestCase):
    def setUp(self):
        self.rows,self.audit,self.policy=fixtures(); self.manager=Manager(self.rows)
        self.saved=[];self.ledger=None;self.records=[]
    def claim(self,record):
        if self.ledger is not None:raise FileExistsError('existing ledger')
        self.ledger=deepcopy(record)
    def persist(self,record):self.ledger=deepcopy(record);self.records.append(deepcopy(record))
    def run_sync(self,read_policy=None):
        return sync.synchronize(self.manager,self.audit,self.policy,
            lambda x:self.saved.append(deepcopy(x)),self.claim,self.persist,
            read_policy or (lambda:self.policy))
    def test_mirrors_exact_three_all_rows_without_touching_sites_or_protected_fields(self):
        before=deepcopy(self.rows)
        result=self.run_sync()
        self.assertEqual(result['status'],'confirmed')
        self.assertEqual(self.manager.posts,[v[0] for v in sync.PRODUCTS.values()])
        for all_id,source_id,aid in sync.PRODUCTS.values():
            self.assertEqual(self.rows[source_id],before[source_id])
            self.assertEqual(sync.protected(self.rows[all_id]),sync.protected(before[all_id]))
            self.assertEqual(self.rows[all_id]['more']['price'],before[source_id]['more']['price'])
        self.assertEqual(self.audit['status'],'CONFIRMED')
    def test_plan_is_read_only_and_copies_actual_tier_prices(self):
        steps=sync.plan(self.manager,self.audit,self.policy)
        self.assertEqual(self.manager.posts,[])
        self.assertEqual(steps[0]['payload']['more']['price'],[1.25,12.52])
    def test_zero_coin_stock_does_not_disqualify_unlimited_coin_product(self):
        self.assertTrue(all(step['changed'] for step in sync.plan(self.manager,self.audit,self.policy)))
    def test_identity_or_platform_remap_stops_before_any_post(self):
        self.rows[163329309]['aid']=21589
        with self.assertRaisesRegex(ValueError,'scope_changed'):self.run_sync()
        self.assertEqual(self.manager.posts,[]);self.assertEqual(self.audit['status'],'PARTIAL')
    def test_mmoexp_rate_disagrees_with_confirmed_audit_stops(self):
        self.rows[163329311]['unit_price']=0.2
        with self.assertRaisesRegex(ValueError,'source_or_before_changed'):self.run_sync()
        self.assertEqual(self.manager.posts,[])
    def test_tier_basis_change_stops_before_any_post(self):
        self.rows[163329309]['more']['give'][1]=10
        with self.assertRaisesRegex(ValueError,'tier_basis_changed'):self.run_sync()
        self.assertEqual(self.manager.posts,[])
    def test_already_equal_requires_no_post(self):
        for all_id,site_id,aid in sync.PRODUCTS.values():
            self.rows[all_id]['unit_price']=self.rows[site_id]['unit_price']
            self.rows[all_id]['more']['price']=deepcopy(self.rows[site_id]['more']['price'])
        self.run_sync();self.assertEqual(self.manager.posts,[])
    def test_policy_revision_change_keeps_execution_blocked(self):
        with self.assertRaisesRegex(ValueError,'preflight_changed'):
            self.run_sync(lambda:{**self.policy,'revision':19})
        self.assertEqual(self.manager.posts,[]);self.assertEqual(self.audit['status'],'PARTIAL')
    def test_dispatch_intent_is_durable_and_main_execution_is_not_confirmed_before_post(self):
        def check(product_id,payload):
            self.assertEqual(self.audit['status'],'PARTIAL')
            item=next(x for x in self.ledger['steps'] if x['product_id']==product_id)
            self.assertEqual(item['status'],'dispatching')
        self.manager.before_post=check;self.run_sync()
    def test_lost_post_response_is_not_retried(self):
        self.manager.lose_response=True
        with self.assertRaises(OSError):self.run_sync()
        self.assertEqual(len(self.manager.posts),1)
        self.assertEqual(self.ledger['status'],'needs_reconcile')
        self.assertEqual(self.audit['status'],'PARTIAL')
    def test_native_save_side_effect_stops_at_first_product(self):
        self.manager.corrupt=True
        with self.assertRaisesRegex(ValueError,'readback_mismatch'):self.run_sync()
        self.assertEqual(len(self.manager.posts),1);self.assertEqual(self.audit['status'],'PARTIAL')
    def test_rejected_post_is_not_retried(self):
        self.manager.reject=True
        with self.assertRaisesRegex(ValueError,'backend_request_rejected'):self.run_sync()
        self.assertEqual(len(self.manager.posts),1)
    def test_unconfirmed_original_execution_cannot_be_promoted(self):
        self.audit['status']='UNCERTAIN'
        with self.assertRaisesRegex(ValueError,'preflight_changed'):self.run_sync()
        self.assertEqual(self.manager.posts,[]);self.assertEqual(self.audit['status'],'UNCERTAIN')
    def test_source_change_between_plan_and_post_stops(self):
        def changed():
            self.rows[163329311]['unit_price']=0.2
            return self.policy
        with self.assertRaisesRegex(ValueError,'source_or_before_changed'):self.run_sync(changed)
        self.assertEqual(self.manager.posts,[])
    def test_other_platform_source_change_before_final_readback_prevents_confirmation(self):
        def changed(product_id,payload):
            if product_id==163329343:self.rows[163329311]['unit_price']=0.2
        self.manager.before_post=changed
        with self.assertRaisesRegex(ValueError,'six_product_readback_mismatch'):self.run_sync()
        self.assertEqual(self.audit['status'],'PARTIAL')
    def test_existing_ledger_cannot_be_replayed_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'all-coin-sync').mkdir()
            ledger=root/'all-coin-sync/coin-test.json'
            ledger.write_text('{"status":"dispatching","original":true}')
            original=ledger.read_bytes()
            self.manager.ensure=lambda:True
            service=types.SimpleNamespace(SessionManager=lambda _:self.manager,read_private_config=lambda:{})
            with patch.dict(sys.modules,{'p2pah_session_service':service}):
                with self.assertRaises(FileExistsError):
                    sync.mirror_confirmed(self.audit,self.policy,lambda _:None,root,lambda:self.policy)
            self.assertEqual(self.manager.posts,[])
            self.assertEqual(ledger.read_bytes(),original)


if __name__=='__main__':unittest.main()
