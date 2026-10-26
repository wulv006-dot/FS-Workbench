from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import json,sys,tempfile,unittest
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parents[1]/'source';sys.path.insert(0,str(SOURCE))
from fc_pricing_v3 import api,runtime
from fc_pricing_v3.ledger import Ledger
from fixtures import fixture,NOW


class InfeasibleSnapshot(unittest.TestCase):
    def test_infeasible_round_publishes_complete_readonly_snapshot_once_and_replaces_old_page_decision(self):
        evidence=fixture()[0];ident='00000000-0000-4000-8000-000000000088';evidence['run_id']=ident
        failure=dict(status='INFEASIBLE',candidates=[],selected=None,failures=[dict(scope='joint',code='NO_SAFE_COMMIT_PATH')])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=Ledger(root/'control.sqlite3')
            old=dict(snapshot_id='old',origin='live_collector',mode='production',evidence=deepcopy(evidence),result=dict(rows=[]),created_at=(NOW-timedelta(hours=2)).isoformat())
            db.put('pricing_snapshots','old',old);db.put('strategy_decisions','old',dict(revenue_sprint=dict(status='READY',candidates=[])))
            with patch.object(runtime,'ROOT',root),patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'clock',return_value=NOW),patch.object(runtime,'evaluate',return_value=failure),patch.object(api,'ledger',return_value=db):
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError,'pricing_v3_infeasible:NO_SAFE_COMMIT_PATH'):runtime.calculate(evidence)
                page=api.read('state');detail=api.read('strategy-decisions/'+ident)
            snapshot=db.get('pricing_snapshots',ident)
            self.assertIsNotNone(snapshot);self.assertEqual(snapshot['evidence'],evidence)
            self.assertFalse(snapshot['result']['execution_authorized']);self.assertEqual(snapshot['result']['rows'],[])
            self.assertEqual(page['snapshot_id'],ident);self.assertEqual(page['strategies']['revenue_sprint']['status'],'INFEASIBLE')
            self.assertEqual(detail['results']['revenue_sprint']['failures'],failure['failures'])
            with db.connect() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM event_outbox WHERE event_key=?",('snapshot:'+ident,)).fetchone()[0],1)
            self.assertEqual(db.all('operations'),[]);self.assertEqual(db.all('experiment_assignments'),[])
            with self.assertRaisesRegex(ValueError,'pricing_simulation_execution_forbidden'):
                runtime.verify_quote(dict(evidence=evidence,result=snapshot['result']),dict(minimum_gross_margin_pct='20'),['PS','XBOX','PC'],now=NOW,for_execution=True)


if __name__=='__main__':unittest.main()
