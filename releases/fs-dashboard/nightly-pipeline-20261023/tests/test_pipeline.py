import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'source'))
sys.modules.setdefault('pilot', types.SimpleNamespace(encoded=lambda v:json.dumps(v).encode(), digest=lambda v:hashlib.sha256(json.dumps(v).encode()).hexdigest()))
import nightly
import nightly_data
import nightly_ops
from source_snapshots import atomic, SnapshotStore


class Pipeline(unittest.TestCase):
    def at(self, hour, minute=0):
        return datetime(2026, 11, 2, hour, minute, tzinfo=nightly.SHANGHAI)

    def test_no_report_before_two(self):
        self.assertEqual(nightly.due(self.at(1,59)), [])
        self.assertEqual([r['kind'] for r in nightly.due(self.at(2))], ['management'])

    def test_weekly_and_monthly_closed_dates(self):
        self.assertEqual(nightly.closed_period(self.at(3).date(),'weekly'), ('2026-10-26','2026-11-01'))
        self.assertEqual(nightly.closed_period(self.at(3).date(),'monthly'), ('2026-10-01','2026-10-31'))
        self.assertNotIn('monthly',[r['kind'] for r in nightly.due(self.at(6))])

    def test_cutoff_before_eight(self):
        self.assertFalse(nightly.inside(self.at(0,9)))
        self.assertFalse(nightly.inside(self.at(7,50)))
        self.assertTrue(all(r['deadline'].endswith('07:49:00+08:00') for r in nightly.due(self.at(6))))

    def test_gap_wait_then_fallback(self):
        with patch.object(nightly,'source_status',return_value=(True,[])), patch.object(nightly_data,'preparation_gaps',return_value=['missing']):
            self.assertFalse(nightly.preparation_status(self.at(5,29))[0])
            self.assertEqual(nightly.preparation_status(self.at(5,30)), (True,['missing']))

    def test_archive_verified_before_ready(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'archive'; source=Path(d)/'sources';SnapshotStore(source).directory()
            day=self.at(3).date().isoformat();start=end='2026-11-01'
            book=types.SimpleNamespace(capture_id='test-original',evidence={'ev_1':{'amount':10}})
            brief={'collection_readiness':{'status':'ready','gaps':[]}}
            entry=nightly_data.save_book(day,'daily',start,end,book,brief,root)
            atomic(source/('preparation-'+day+'.json'),{'day':day,'status':'ready','results':[{'kind':'daily','native_statuses':['ready'],'supplements':[{'status':'available'}]}]})
            self.assertEqual(nightly_data.preparation_gaps(self.at(3),'daily',source,root),[])
            target=root/day/entry['file'];target.write_bytes(b'{}')
            self.assertEqual(nightly_data.preparation_gaps(self.at(3),'daily',source,root),['nightly_evidence_missing_or_invalid'])

    def test_missing_and_old_receipt_not_ready(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(nightly_data.preparation_gaps(self.at(3),'daily',Path(d),Path(d)))

    def test_running_service_never_restarted(self):
        for state in ('active','activating','deactivating','reloading'):
            self.assertFalse(nightly_ops.retry_decision(self.at(2),{'ActiveState':state,'Result':'exit-code'},[]))

    def test_success_never_restarted(self):
        self.assertFalse(nightly_ops.retry_decision(self.at(2),{'ActiveState':'inactive','Result':'success'},[]))

    def test_unknown_not_replayed(self):
        for state in ('requesting','unknown'):
            a=[{'state':state,'at':self.at(1).isoformat(),'before_start':'old'}]
            self.assertFalse(nightly_ops.retry_decision(self.at(2),{'ActiveState':'failed','Result':'exit-code'},a))

    def test_failure_retry_budget(self):
        status={'ActiveState':'failed','Result':'exit-code','ExecMainStartTimestamp':'new'}
        self.assertTrue(nightly_ops.retry_decision(self.at(2),status,[]))
        attempts=[{'state':'submitted','at':self.at(1).isoformat(),'before_start':'old'}]*3
        self.assertFalse(nightly_ops.retry_decision(self.at(2),status,attempts))
        self.assertFalse(nightly_ops.retry_decision(self.at(5,10),status,[]))

    def test_submitted_request_needs_new_execution(self):
        a=[{'state':'submitted','at':self.at(1).isoformat(),'before_start':'same'}]
        self.assertFalse(nightly_ops.retry_decision(self.at(2),{'ActiveState':'failed','Result':'exit-code','ExecMainStartTimestamp':'same'},a))

    def test_all_sources_compile(self):
        for p in (Path(__file__).resolve().parents[1]/'source').glob('*.py'):
            compile(p.read_bytes(),str(p),'exec')


if __name__=='__main__':unittest.main()
