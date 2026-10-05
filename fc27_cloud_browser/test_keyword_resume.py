from copy import deepcopy
import unittest
import coin_all_sync_job as sync
from test_coin_all_sync import fixtures,Manager

class NativeManager(Manager):
    def request(self,path,data=None,token=None):
        result=super().request(path,data,token)
        if data is not None:
            product_id=int(path.rsplit('=',1)[1])
            platform=next(p for p,ids in sync.PRODUCTS.items() if ids[0]==product_id)
            for ident in sync.PRODUCTS[platform][:2]:
                if not self.rows[ident]['keywords']:self.rows[ident]['keywords']=sync.DEFAULT_KEYWORDS[platform]
        return result

class KeywordResumeTest(unittest.TestCase):
    def setUp(self):
        self.rows,self.audit,self.policy=fixtures()
        for r in self.rows.values():r['keywords']=''
        self.manager=NativeManager(self.rows);self.saved=[];self.record={}
    def persist(self,x):self.record=deepcopy(x)
    def test_normal_three_platform_keyword_generation_passes(self):
        sync.synchronize(self.manager,self.audit,self.policy,lambda x:self.saved.append(deepcopy(x)),self.persist,self.persist,lambda:self.policy)
        self.assertEqual(self.audit['status'],'CONFIRMED');self.assertEqual(len(self.manager.posts),3)
        for p,ids in sync.PRODUCTS.items():
            self.assertEqual(self.rows[ids[0]]['keywords'],sync.DEFAULT_KEYWORDS[p])
    def test_wrong_keywords_and_nonempty_rewrite_rejected(self):
        before=self.rows[163329309];after=deepcopy(before);after['keywords']='other'
        self.assertFalse(sync.unchanged(before,after,'PS',True))
        before['keywords']='custom';after['keywords']=sync.DEFAULT_KEYWORDS['PS']
        self.assertFalse(sync.unchanged(before,after,'PS',True))
    def landed(self):
        steps=sync.plan(self.manager,self.audit,self.policy)
        record={'execution_id':self.audit['execution_id'],'status':'needs_reconcile',
                'steps':[deepcopy(s)|{'status':'dispatching' if s['platform']=='PS' else 'pending'} for s in steps]}
        self.manager.request('/admin/goods.Goods/edit?id=163329309',steps[0]['payload'])
        self.manager.posts=[]
        self.audit.update(kind='all_baseline_repair',status='PARTIAL',stage='all_baseline_pending')
        return record
    def resume(self,record):
        return sync.resume_synchronize(self.manager,self.audit,self.policy,record,lambda x:self.saved.append(deepcopy(x)),self.persist,lambda:self.policy)
    def test_resume_reads_ps_never_reposts_then_finishes(self):
        result=self.resume(self.landed())
        self.assertEqual(result['status'],'confirmed')
        self.assertEqual(self.manager.posts,[163329275,163329343])
        self.assertIn('reconciled_read_only_at',self.record['steps'][0])
    def test_landed_other_protected_change_blocks_all_remaining_writes(self):
        record=self.landed();self.rows[163329309]['is_rec']=0
        with self.assertRaisesRegex(ValueError,'readback_mismatch'):self.resume(record)
        self.assertEqual(self.manager.posts,[])
    def test_pending_change_or_source_price_change_blocks_resume(self):
        record=self.landed();self.rows[163329277]['unit_price']=0.13
        with self.assertRaisesRegex(ValueError,'source_changed'):self.resume(record)
        self.assertEqual(self.manager.posts,[])
    def test_tampered_resume_payload_rejected(self):
        record=self.landed();record['steps'][1]['payload']['is_rec']=0
        with self.assertRaisesRegex(ValueError,'payload_changed'):self.resume(record)
        self.assertEqual(self.manager.posts,[])
    def test_unknown_dispatched_second_product_not_retried(self):
        record=self.landed();record['steps'][1]['status']='dispatching'
        with self.assertRaisesRegex(ValueError,'scope_changed'):self.resume(record)
        self.assertEqual(self.manager.posts,[])

if __name__=='__main__':unittest.main()
