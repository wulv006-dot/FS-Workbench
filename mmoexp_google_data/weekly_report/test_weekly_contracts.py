"""Synthetic contracts only; no historical business snapshots or live requests."""
import copy,datetime as dt,unittest
import weekly_report as w
import range_adapter as a

class WeeklyContracts(unittest.TestCase):
    def setUp(self):self.period=w.period('2026-09-21');self.base='EXAMPLE-only-base'
    def exact(self,key):
        p=self.period;period={'start':p['startAt'],'end':p['endExclusiveAt']}
        query={'profile':key,'grain':'day','start':p['start'],'end':p['end'],'baseSnapshotId':self.base}
        metrics={k:{'value':v,'source':'primary'} for k,v in zip(w.CORE,[10,100,12,-5])}
        profile={'key':key,'period':period,'metrics':metrics,
                 'primary':{'system':'order.p2pah.cn','status':'available','period':period,'rows':[]},
                 'supplement':{'system':'admin.p2pah.cn','status':'available','period':period}}
        value={'schemaVersion':1,'status':'available','consistentPeriod':True,
               'query':query,'rangeId':w.sha(w.encoded(query)),'baseSnapshotId':self.base,
               'scopeContractId':w.CONTRACT,'currency':'USD','timezone':'Asia/Shanghai',
               'profile':profile,'generatedAt':'2026-09-28T01:00:00+00:00'}
        return self.sign(value)
    def sign(self,v):v.pop('resultSha256',None);v['resultSha256']=w.sha(w.encoded(v));return v
    def test_week_boundary(self):
        self.assertEqual(self.period['endExclusive'],'2026-09-28')
        self.assertEqual(self.period['end'],'2026-09-27')
    def test_monday_required(self):
        with self.assertRaisesRegex(ValueError,'MONDAY'):w.period('2026-09-22')
    def test_utc_to_shanghai(self):
        self.assertEqual(w.preceding_week(dt.datetime.fromisoformat('2026-10-04T18:00:00+00:00'))['start'],'2026-09-28')
    def test_next_monday_two(self):
        self.assertEqual(w.next_monday(dt.datetime.fromisoformat('2026-10-01T02:00:00+00:00')),'2026-10-05T02:00:00+08:00')
    def test_signed_native_core_preserved(self):
        v=a.adapt({k:self.exact(k) for k in w.PROFILES},self.period,self.base)
        m=v['profiles']['MMOEXP']['metrics'];self.assertEqual(m['averageOrderUsd']['value'],12)
        self.assertNotEqual(m['averageOrderUsd']['value'],m['revenueUsd']['value']/m['orders']['value'])
        self.assertEqual(m['profitMarginPct']['value'],-5)
    def test_tampered_sha_rejected(self):
        v=self.exact('MMOEXP');v['profile']['metrics']['orders']['value']=11
        with self.assertRaisesRegex(ValueError,'SHA'):a.validate(v,'MMOEXP',self.period,self.base)
    def test_foreign_base_rejected(self):
        with self.assertRaisesRegex(ValueError,'BASE'):a.validate(self.exact('MMOEXP'),'MMOEXP',self.period,'foreign')
    def test_source_period_mismatch_rejected(self):
        v=copy.deepcopy(self.exact('MMOEXP'));v['profile']['supplement']['period']={'start':self.period['startAt'],'end':'2026-09-27T00:00:00+08:00'};self.sign(v)
        with self.assertRaisesRegex(ValueError,'PERIOD'):a.validate(v,'MMOEXP',self.period,self.base)
    def test_incomplete_profiles_rejected(self):
        with self.assertRaisesRegex(ValueError,'PROFILES'):a.adapt({'MMOEXP':self.exact('MMOEXP')},self.period,self.base)
    def test_only_zero_exclusive_midnight_dropped(self):
        rows=[{'date':'2026-09-21 01:00','orders':1,'amount':2},{'date':'2026-09-28 00:00','orders':0,'amount':0}]
        self.assertEqual(a.daily_rows(rows,self.period),[{'date':'2026-09-21','orders':1,'amount':2}])
        rows[-1]['orders']=1
        with self.assertRaisesRegex(ValueError,'OUTSIDE'):a.daily_rows(rows,self.period)
    def test_non_finite_row_rejected(self):
        with self.assertRaisesRegex(ValueError,'INVALID'):a.daily_rows([{'date':'2026-09-21','orders':float('nan'),'amount':0}],self.period)

if __name__=='__main__':unittest.main()
