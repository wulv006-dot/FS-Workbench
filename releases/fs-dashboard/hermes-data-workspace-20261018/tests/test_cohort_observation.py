import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from cohort_observation import update, read


class ObservationTests(unittest.TestCase):
    def test_initial_missing_key_does_not_freeze_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'private.db'
            row={'id':'a','customer_key':None,'paid_at':'2026-10-01T12:00:00+08:00','customer':'new'}
            partial=update(path,'group','2026-10-01','2026-10-01',[row],complete_through='2026-10-08',source_complete=True,source_version='a')
            self.assertFalse(partial['persisted']);self.assertIsNone(partial['members'])
            row['customer_key']='site:anon'
            recovered=update(path,'group','2026-10-01','2026-10-01',[row],complete_through='2026-10-08',source_complete=True,source_version='b')
            self.assertEqual(recovered['members'],1)

    def test_timezone_and_site_local_order_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=[{'id':'same-order-number','customer_key':'site-A-customer','paid_at':'2026-10-01T18:00:00+00:00','customer':'new'},
                  {'id':'same-order-number','customer_key':'site-B-customer','paid_at':'2026-10-02T02:00:00+08:00','customer':'new'}]
            result=update(Path(tmp)/'private.db','site-separated','2026-10-02','2026-10-02',rows,complete_through='2026-10-09',source_complete=True,source_version='test')
            self.assertEqual(result['members'],2)
            self.assertEqual(result['windows'][0]['mature_customers'],2)
            self.assertEqual(result['windows'][0]['repeat_customers'],0)

    def test_frozen_maturity_repeat_and_privacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'private.db'
            rows=[{'id':'private-order-A','customer_key':'site-anon-A','paid_at':'2026-10-01T12:00:00+08:00','customer':'new'},
                  {'id':'private-order-B','customer_key':'site-anon-A','paid_at':'2026-10-05T12:00:00+08:00','customer':'returning'}]
            args=(path,'FC27-main-20261001','2026-10-01','2026-10-01',rows)
            result=update(*args,complete_through='2026-10-08',source_complete=True,source_version='v1')
            self.assertEqual(result['windows'][0]['repeat_rate'],1)
            self.assertIsNone(result['windows'][1]['repeat_rate'])
            self.assertNotIn('site-anon-A',json.dumps(result))
            self.assertNotIn('private-order-A',path.read_bytes().decode('latin1'))
            failed=update(*args,complete_through='2026-10-09',source_complete=False,source_version='v2')
            self.assertFalse(failed['persisted'])
            self.assertEqual(read(path,'FC27-main-20261001'),result)
            again=update(*args,complete_through='2026-10-31',source_complete=True,source_version='v3')
            self.assertEqual(again['members'],1)
            self.assertEqual(again['windows'][2]['repeat_rate'],1)
            with self.assertRaises(ValueError):
                update(*args,complete_through='2026-10-30',source_complete=True,source_version='v4')

if __name__=='__main__':unittest.main()
