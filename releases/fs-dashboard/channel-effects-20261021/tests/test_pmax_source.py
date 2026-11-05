"""Fictional regression: project ownership is not metric allocation or code assistance."""
import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'mmoexp_google_data/details'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
sys.path.insert(0, str(ROOT / 'releases/fs-dashboard/dashboard-refresh-20261025/source'))
from traffic_contract import campaign_scope
from channel_effects import view
import test_channel_effects as baseline


class PMaxSource(unittest.TestCase):
    def test_project_is_fc_but_platform_metrics_remain_cross_game(self):
        scope = campaign_scope('google-FC27-PMAX-Coins-US')
        self.assertEqual(scope['project_game'], 'FC27')
        self.assertEqual(scope['metric_scope'], 'cross_game')
        self.assertEqual(scope['campaign_scope'], 'global_brand')
        self.assertIsNone(scope['game_target'])

    def test_primary_advertising_does_not_erase_code_assistance(self):
        helper = baseline.Effects(); helper.setUp(); data = helper.data()
        a, b, c, d = data['orders']
        a.update(gid='1327', game='FC27', project='分销', sourceStatus='available', sourceRaw='google-FC27-PMAX-Coins-US', sourceGame='FC 27')
        b.update(sourceStatus='available', sourceRaw='', sourceGame='Game A')
        d.update(sourceStatus='available', sourceRaw='google-FC27-PMAX-Coins-US', sourceGame='Game A')
        result = view(data, {'mode':'code'})
        primary = result['sourceAttribution']
        groups = {r['key']:r for r in primary['projects']}
        self.assertEqual((groups['广告来源']['orders'], groups['广告来源']['salesUsd']), (2, 50))
        self.assertEqual((primary['pmaxFc']['orders'], primary['pmaxFc']['salesUsd']), (1, 10))
        self.assertEqual(primary['unknownSourceOrders'], 1)
        self.assertEqual(sum(r['orders'] for r in primary['projects']), primary['summary']['orders'])
        self.assertEqual(a['project'], '分销')
        self.assertFalse(primary['platformCostsAllocated'])
        self.assertEqual(result['summary']['orders'], 3)  # existing code/referrer cohort unchanged

    def test_missing_source_is_not_natural_or_zero(self):
        helper = baseline.Effects(); helper.setUp(); result = view(helper.data(), {'mode':'code'})
        primary = result['sourceAttribution']
        self.assertEqual(primary['unknownSourceOrders'], 4)
        self.assertEqual(primary['projects'][0]['key'], '订单来源未核')

    def test_cards_pmax_uses_actual_game_and_preserves_ad_total(self):
        helper = baseline.Effects(); helper.setUp(); data = helper.data()
        a, b, c, d = data['orders']
        a.update(gid='1327', game='FC27', sourceStatus='available', sourceRaw='FC27-Pmax-Cards-EN')
        b.update(sourceStatus='available', sourceRaw='google-FC27-PMAX-Cards-EN')
        result = view(data, {'mode':'code'})['sourceAttribution']
        self.assertEqual(result['pmaxFc']['orders'], 1)
        self.assertEqual(sum(r['orders'] for r in result['projects']), result['summary']['orders'])

    def test_es_full_source_sum_precedes_top_and_uses_actual_game(self):
        path = ROOT / 'releases/fs-dashboard/cache-archive-retention-20261025/source/es_order_structure.py'
        spec = importlib.util.spec_from_file_location('pmax_es_regression', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'coupon_channels':SimpleNamespace(retained=lambda x:x, mapping=lambda:({},'fixture')), 'admin_discount_analysis':SimpleNamespace(GROUPS=(),FIELDS=())}):
            spec.loader.exec_module(module)
        def row(sn, game, source, usd):
            return dict(订单号=sn, 游戏=game, 付款时间='2026/10/20 12:00:00', 订单状态='已完成', 订单来源=source,
                        **{'订单金额（美元）':str(usd),'实付币种':'USD','实付金额':str(usd)})
        rows = [row('P','FC 27','google-FC27-PMAX-Coins-US',30),row('D','Diablo 4','google-FC27-PMAX-Coins-US',50),
                row('C','FC 27','google-FC27-PMAX-Cards-EN',20)]
        rows += [row(str(i),'FC 27','google-FC27-Coins-'+str(i),10) for i in range(25)]
        rows.append(dict(rows[0]))
        result = module.aggregate_rows(rows, ['a'*64], 0, dict(profile='ALL',start='2026-10-20',end='2026-10-20',group_by='source_game',status='all'),1,0)
        groups = {r['game']:r for r in result['advertising_source_totals']['by_game']}
        self.assertEqual(groups['FC 27']['orders'],27)
        self.assertEqual(groups['FC 27']['order_amount_usd'],'300')
        self.assertEqual(groups['FC 27']['pmax_amount_usd'],'50')
        self.assertEqual(groups['Diablo 4']['pmax_amount_usd'],'50')
        self.assertEqual(result['structure_totals']['orders'],28)
        self.assertEqual(result['groups'][-1]['key'],'__other__')
        self.assertFalse(result['advertising_source_totals']['costs_allocated'])


if __name__ == '__main__': unittest.main()
