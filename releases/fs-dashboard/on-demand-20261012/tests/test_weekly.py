import copy,datetime as dt,json,tempfile,unittest
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'tests/helpers')]
import range_adapter as a
import weekly_report as w
HERE=Path(__file__).parent
P=w.period('2026-09-21');BASE='catalog-0123456789abcdef'
period={'start':P['start']+' 00:00','end':P['endExclusive']+' 00:00'}
metrics={key:{'value':value,'source':'primary','status':'available'} for key,value in zip(w.CORE,[7,70,10,20])}
query={'profile':'MMOEXP','start':P['start'],'end':P['end'],'grain':'day','baseSnapshotId':BASE,'period':period}
REAL={'schemaVersion':1,'status':'available','consistentPeriod':True,'query':query,'baseSnapshotId':BASE,'rangeId':w.sha(w.encoded(query)),
 'scopeContractId':w.CONTRACT,'currency':'USD','timezone':'Asia/Shanghai','generatedAt':'2026-10-12T02:00:00+00:00',
 'profile':{'key':'MMOEXP','period':period,'metrics':metrics,'primary':{'system':'order.p2pah.cn','status':'available','period':period,
  'rows':[{'date':(dt.date.fromisoformat(P['start'])+dt.timedelta(days=i)).isoformat(),'orders':1,'amount':10} for i in range(7)]},
 'supplement':{'system':'admin.p2pah.cn','status':'available','period':period,'metrics':{}}}}
for value in [REAL['profile'],REAL['profile']['primary'],REAL['profile']['supplement']]:value['period']=copy.deepcopy(period)
REAL['resultSha256']=w.sha(w.encoded(REAL))

def signed(value):
    value.pop('resultSha256',None);value['resultSha256']=w.sha(w.encoded(value));return value
def nine():
    results={}
    for key in w.PROFILES:
        value=copy.deepcopy(REAL);value['query']['profile']=key;value['profile']['key']=key;value['rangeId']=w.sha(w.encoded(value['query']));results[key]=signed(value)
    return results
class RangeAdapterTests(unittest.TestCase):
    def test_native_week_certificate_and_synthetic_four(self):
        a.validate(REAL,'MMOEXP',P,BASE);result=a.adapt(nine(),P,BASE);m=result['profiles']['MMOEXP']['metrics'];self.assertEqual([m[k]['value'] for k in w.CORE],[7,70,10,20]);self.assertEqual(result['reportRange']['endExclusive'],'2026-09-28T00:00:00+08:00')
    def test_mutated_sha_rejected(self):
        value=copy.deepcopy(REAL);value['profile']['metrics']['orders']['value']=0
        with self.assertRaisesRegex(ValueError,'SHA_MISMATCH'):a.validate(value,'MMOEXP',P,BASE)
    def test_base_changed_rejected(self):
        with self.assertRaisesRegex(ValueError,'BASE_CHANGED'):a.validate(REAL,'MMOEXP',P,'different')
    def test_wrong_inclusive_end_rejected(self):
        value=copy.deepcopy(REAL);value['query']['end']='2026-09-28';signed(value)
        with self.assertRaisesRegex(ValueError,'QUERY_MISMATCH'):a.validate(value,'MMOEXP',P,BASE)
    def test_foreign_supplement_period_rejected(self):
        value=copy.deepcopy(REAL);value['profile']['supplement']['period']['end']='2026-09-27 00:00';signed(value)
        with self.assertRaisesRegex(ValueError,'PERIOD_MISMATCH'):a.validate(value,'MMOEXP',P,BASE)
    def test_nine_profiles_required(self):
        with self.assertRaisesRegex(ValueError,'NINE_PROFILES'):a.adapt({'MMOEXP':REAL},P,BASE)
    def test_hourly_additive_rows_only(self):
        rows=a.daily_rows(REAL['profile']['primary']['rows'],P);self.assertEqual(sum(r['orders'] for r in rows),7);self.assertAlmostEqual(sum(r['amount'] for r in rows),70,places=2)
    def test_undated_native_series_not_faked(self):self.assertEqual(a.daily_rows([],P),[])
    def test_nonzero_exclusive_endpoint_rejected(self):
        with self.assertRaisesRegex(ValueError,'OUTSIDE_WEEK'):a.daily_rows([{'date':'2026-09-28 00:00','orders':1,'amount':1}],P)
    def test_partial_source_blocks_certificate(self):
        value=copy.deepcopy(REAL);value['profile']['supplement']['status']='unavailable';signed(value)
        with self.assertRaisesRegex(ValueError,'SOURCE_UNAVAILABLE'):a.validate(value,'MMOEXP',P,BASE)
    def test_catalog_replaces_base_pointer_and_is_validated(self):
        with patch.object(a,'read_request',return_value=(200,{'schemaVersion':2,'catalogId':BASE})) as read:
            self.assertEqual(a.catalog_id(),BASE);read.assert_called_once_with({'mode':'catalog'})
        with patch.object(a,'read_request',return_value=(200,{'schemaVersion':2,'catalogId':'catalog-invalid'})):
            with self.assertRaises(ValueError):a.catalog_id()

if __name__=='__main__':unittest.main()
