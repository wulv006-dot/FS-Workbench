import unittest,tempfile,json,copy
from pathlib import Path
from atomic_snapshot import publish

def fixture():
    period={'start':'2026-09-30 00:00:00','end':'2026-09-30 22:18:00'}
    source={'system':'order.p2pah.cn','status':'available','period':period,'filters':{'gid':0,'status':''},'normalisedScope':'all-websites','capturedAt':'2026-09-30T14:18:01Z'}
    supplement=dict(source,system='admin.p2pah.cn')
    return {'scopeApproved':True,'scopeContractId':'test-all-websites','timezone':'Asia/Shanghai','currency':'USD','requiredProfiles':['all'],
            'profiles':{'all':{'period':period,'primary':source,'supplement':supplement,'metrics':{'orders':{'value':1,'source':'primary'},'revenueUsd':{'value':5,'source':'primary'},'newCustomers':{'value':0,'source':'supplement'}}}}}

class PublicationTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_pinned_versions(self):
        first=publish(self.root,fixture());before=(self.root/first['path']).read_bytes()
        changed=fixture();changed['profiles']['all']['metrics']['orders']['value']=2
        second=publish(self.root,changed)
        self.assertNotEqual(first['snapshotId'],second['snapshotId']);self.assertEqual((self.root/first['path']).read_bytes(),before)
        self.assertEqual(json.loads((self.root/'current.json').read_text())['snapshotId'],second['snapshotId'])
    def test_failed_primary_keeps_old(self):
        publish(self.root,fixture());before=(self.root/'current.json').read_bytes()
        changed=fixture();changed['profiles']['all']['primary']['status']='unavailable'
        with self.assertRaises(ValueError):publish(self.root,changed)
        self.assertEqual((self.root/'current.json').read_bytes(),before)
    def test_pending_scope_does_not_publish(self):
        changed=fixture();changed['scopeApproved']=False
        with self.assertRaises(ValueError):publish(self.root,changed)
        self.assertFalse((self.root/'current.json').exists())
    def test_wrong_supplement_scope_rejected(self):
        changed=fixture();changed['profiles']['all']['supplement']['normalisedScope']='site266'
        with self.assertRaises(ValueError):publish(self.root,changed)
    def test_wrong_supplement_period_rejected(self):
        changed=copy.deepcopy(fixture());changed['profiles']['all']['supplement']['period']={'start':'2026-09-29','end':'2026-09-30'}
        with self.assertRaises(ValueError):publish(self.root,changed)
    def test_no_admin_revenue_fallback(self):
        changed=fixture();changed['profiles']['all']['metrics']['revenueUsd']['source']='supplement'
        with self.assertRaises(ValueError):publish(self.root,changed)
    def test_missing_supplement_remains_null(self):
        changed=fixture();changed['profiles']['all']['metrics']['newCustomers']={'value':None,'source':'supplement','status':'unavailable'}
        publish(self.root,changed)
    def test_non_finite_metric_rejected(self):
        changed=fixture();changed['profiles']['all']['metrics']['revenueUsd']['value']=float('nan')
        with self.assertRaises(ValueError):publish(self.root,changed)

if __name__=='__main__':unittest.main()
