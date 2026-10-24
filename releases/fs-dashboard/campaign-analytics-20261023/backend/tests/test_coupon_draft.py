import sys,unittest,tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from campaign_backend.coupon_draft import DisabledCouponDraft,draft_payload
from campaign_backend.ledger import OperationLedger
from campaign_backend.core import ContractError

OP='ec21a854-b072-4ba4-94e2-f8ad4451b5a8'
class Reader:
    def __init__(self,timeout=False):
        self.rows=[];self.calls=[];self.timeout=timeout
        self.session=SimpleNamespace(token='fixture-only',admin=SimpleNamespace(post=self.post))
    def pages(self,*a,**kw):
        for r in self.rows:
            if not kw['validate'](r):raise ContractError('UPSTREAM_SCOPE_MISMATCH')
        return self.rows
    def post(self,url,**kw):
        self.calls.append((url,kw));self.rows=[dict(kw['json'],id=123)]
        if self.timeout:raise TimeoutError()
        return SimpleNamespace(status_code=200)

class DraftTests(unittest.TestCase):
    def test_disabled_native_readback_and_single_dispatch(self):
        reader=Reader();adapter=DisabledCouponDraft(reader);payload=draft_payload(OP)
        with tempfile.TemporaryDirectory() as d:
            ledger=OperationLedger(Path(d)/'ledger.sqlite')
            adapter.validate(OP,payload)
            self.assertEqual(ledger.execute(OP,payload,adapter)['state'],'confirmed')
            self.assertEqual(ledger.execute(OP,payload,adapter)['result']['upstream_ref'],'123')
            self.assertEqual(len(reader.calls),1)
            self.assertFalse(reader.calls[0][1]['allow_redirects'])
            self.assertEqual(reader.calls[0][1]['json']['status'],0)
    def test_timeout_resolves_original_without_post_retry(self):
        reader=Reader(timeout=True);adapter=DisabledCouponDraft(reader);payload=draft_payload(OP)
        with tempfile.TemporaryDirectory() as d:
            ledger=OperationLedger(Path(d)/'ledger.sqlite')
            self.assertEqual(ledger.execute(OP,payload,adapter)['state'],'unknown')
            self.assertEqual(ledger.reconcile(OP,adapter)['state'],'confirmed')
            self.assertEqual(len(reader.calls),1)
    def test_never_activate_or_change_scope(self):
        payload=draft_payload(OP);payload['status']=1
        with self.assertRaises(ContractError):DisabledCouponDraft.validate(OP,payload)
        with self.assertRaises(ContractError):draft_payload(OP,'999')
    def test_duplicate_or_changed_native_row_not_confirmed(self):
        r=Reader();p=draft_payload(OP);r.rows=[dict(p,id=1),dict(p,id=2)]
        self.assertEqual(DisabledCouponDraft(r).readback(OP,p)['state'],'unknown')
        r.rows=[dict(p,id=1,status=1)]
        self.assertEqual(DisabledCouponDraft(r).readback(OP,p)['state'],'unknown')
if __name__=='__main__':unittest.main()
