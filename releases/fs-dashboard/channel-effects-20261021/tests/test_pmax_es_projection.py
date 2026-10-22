"""Current rules must apply to retained exports without restarting the auth session."""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'mmoexp_google_data/details'))
spec=importlib.util.spec_from_file_location('pmax_es_archive_projection',ROOT/'releases/fs-dashboard/fs-business-baseline-20261021/source/hermes/es_order_structure.py')
es=importlib.util.module_from_spec(spec)
with patch.dict(sys.modules,{'coupon_channels':SimpleNamespace(retained=lambda x:x,mapping=lambda:({},'fixture')),'admin_discount_analysis':SimpleNamespace(GROUPS=('discount_channel',),FIELDS=())}):spec.loader.exec_module(es)

class CurrentProjection(unittest.TestCase):
    def setUp(self):
        self.query=dict(profile='FC27',start='2026-10-20',end='2026-10-20',group_by='source_game',status='all')

    def test_archive_uses_current_rules_without_remote_or_new_export(self):
        row=dict(订单号='synthetic',游戏='FC 27',付款时间='2026/10/20 12:00:00',订单状态='已完成',订单来源='google-FC27-PMAX-Coins-US',**{'订单金额（美元）':'30','实付币种':'USD','实付金额':'30'})
        dataset=dict(rows=[row],hashes=['a'*64],parse_failures=0,declared_files=1,failed_files=0,captured_at='2026-10-21T00:00:00Z')
        with patch.object(es,'archived_dataset',return_value=dataset),patch.object(es,'_server_bundle',side_effect=AssertionError('must not call old session')):
            value=es.server_bundle(self.query)['snapshots'][0]['value']
        self.assertEqual(value['advertising_source_totals']['by_game'][0]['pmax_amount_usd'],'30')
        self.assertEqual(value['quality']['rule_version'],es.RULE_VERSION)
        self.assertEqual(value['captured_at'],dataset['captured_at'])
        self.assertEqual(value['quality']['source_origin'],'existing_private_export')

    def test_no_archive_preserves_original_remote_and_poll_boundary(self):
        with patch.object(es,'archived_dataset',return_value=None),patch.object(es,'_server_bundle',return_value={'status':'pending'}) as remote:
            self.assertEqual(es.server_bundle(self.query),{'status':'pending'})
            remote.assert_called_once()

    def test_discount_without_archive_stays_unavailable(self):
        with patch.object(es,'archived_dataset',return_value=None),patch.object(es,'_server_bundle',side_effect=AssertionError('must not export')):
            self.assertEqual(es.server_bundle(dict(self.query,group_by='discount_channel'))['reason'],'coupon_period_export_unavailable')

if __name__=='__main__':unittest.main()
