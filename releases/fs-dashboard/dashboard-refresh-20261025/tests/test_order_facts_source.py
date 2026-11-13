"""Synthetic native-source shapes; no network, credentials or raw business data."""
import copy
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'source'), str(ROOT.parent/'cache-archive-retention-20261025/source')]
from order_attribution import HEADERS, normalize_order_attribution
from order_facts_source import project_order_facts

SCOPE = {'start':'2026-11-10', 'end':'2026-11-10', 'site':'266', 'gid':'1327'}


def order(sn='O1', site='266', title='www.mmoexp.com'):
    return dict(order_no=sn, site_id=site, site={'full_title':title},
        amount_usd_format='50', amount_rmb_format='350', status_format='已完成',
        pay_status='1', paytime='2026-11-10 10:00:00', gid='1327', game_format='FC 27')


def es_row(sn='O1', channel='PPC', day='2026-11-10'):
    fact = normalize_order_attribution({'归因渠道':channel}, {'归因渠道'}, {'fields':HEADERS})
    fact.update(source_revision='uw_pinned', available_at='2026-11-12T00:00:00+00:00', evidence_ref=['manifest'])
    return {'订单号':hashlib.sha256(sn.encode()).hexdigest(), '付款时间':day+' 10:00:00', '订单状态':'已完成',
            'marketing_attribution':fact, '_signature':'original-signature'}


def dataset(rows=None):
    return dict(_private_dataset=True, revision_selection='published_pins', publication_id='uw_pinned',
        source_revision='uw_pinned', data_revision='3', status='available', hashes=['file-sha'],
        captured_at='2026-11-12T00:00:00+08:00',
        effective_scope={'start':'2026-11-01','end':'2026-11-11','site_verified':False,'game_filter_applied':False},
        rows=[es_row()] if rows is None else rows, revision_conflicts=[])


def catalog(rows=None):
    return dict(rows=[order()] if rows is None else rows, complete=True, revision='native-r1',
        scope={'site':'all','game':'all','pay_status':'1','start':'2026-11-10','end':'2026-11-10'})


def project(orders=None, data='default', identity='default', costs=(), **kwargs):
    return project_order_facts([order()] if orders is None else orders,
        dataset() if data == 'default' else data, costs, scope=SCOPE,
        source_coverage={'admin_complete':True, 'admin_revision':'native-r1'},
        identity_catalog=catalog() if identity == 'default' else identity, **kwargs)


class OrderFactsSource(unittest.TestCase):
    def test_pinned_projection_forward_hash_preserves_evidence_and_input(self):
        inputs=([order()], dataset(), catalog())
        previous=copy.deepcopy(inputs)
        result=project(inputs[0], inputs[1], inputs[2])
        self.assertEqual(inputs, previous)
        fact=result['orders'][0]
        self.assertEqual((fact['site_id'],fact['order_no'],fact['channel']), ('266','O1','PPC'))
        self.assertEqual(fact['marketing_attribution']['evidence_ref'], ['manifest'])
        proof=result['source_coverage']['attribution']
        self.assertEqual(proof['data_revision'],'3')
        self.assertEqual(proof['effective_scope']['start'],'2026-11-01')
        self.assertEqual(proof['selected_scope']['start'],'2026-11-10')
        self.assertEqual(proof['bridge_counts'],{'linked':1})

    def test_pinned_order_source_carries_fixed_capture_revision(self):
        attr=es_row(channel=''); attr['订单来源']='google-FC27-PMAX-Coins-US'
        attr['marketing_attribution']['source_captured_at']='2026-11-11T01:00:00+08:00'
        fact=project(data=dataset([attr]))['orders'][0]
        self.assertEqual(fact['pinned_order_source'],'google-FC27-PMAX-Coins-US')
        self.assertEqual(fact['pinned_order_source_revision'],'uw_pinned')
        self.assertEqual(fact['pinned_order_source_at'],'2026-11-11T01:00:00+08:00')

    def test_later_admin_capture_cannot_override_newer_same_order_source_observation(self):
        from channel_effects import Attribution
        from order_facts_runtime import effective_attribution
        attr=es_row(channel=''); attr['订单来源']='google-FC27-PMAX-Coins-US'
        attr['marketing_attribution']['source_captured_at']='2026-11-11T01:00:00+08:00'
        facts=project(data=dict(dataset([attr]),captured_at='2026-11-13T01:00:00+08:00'))
        evidence=effective_attribution(facts['orders'][0],{},dict(sourceStatus='available',
            sourceRaw='Google organic',sourceCapturedAt='2026-11-12T01:00:00+08:00'),Attribution({'entries':[]},[],{}))
        self.assertEqual(evidence['channel'],'pending_classification')
        self.assertTrue(evidence['conflict'])

    def test_scoped_identity_uniqueness_never_proves_global_uniqueness(self):
        partial=catalog(); partial['scope']['site']='266'
        wrong_game=catalog(); wrong_game['scope']['game']='1327'
        incomplete=catalog(); incomplete['complete']=False
        no_paid_scope=catalog(); no_paid_scope['scope'].pop('pay_status')
        for identity in (None,partial,wrong_game,incomplete,no_paid_scope):
            with self.subTest(identity=identity):
                result=project(identity=identity)
                self.assertEqual(result['orders'][0]['channel'],'unknown')
                self.assertEqual(len(result['unlinked_attribution_rows']),1)

    def test_status_revision_mismatch_keeps_attribution_unlinked(self):
        row=es_row();row['订单状态']='已退款'
        result=project(data=dataset([row]))
        self.assertEqual(result['orders'][0]['channel'],'unknown')
        self.assertEqual(result['unlinked_attribution_rows'][0]['_bridge_status'],'order_status_revision_mismatch')
        self.assertNotIn('order_no',result['unlinked_attribution_rows'][0])
        self.assertEqual(result['source_coverage']['attribution']['identity_scope']['pay_status'],'1')

    def test_cross_site_collision_in_catalog_outside_selected_members_stays_unlinked(self):
        other=order(site='320',title='www.rsorders.com')
        result=project(identity=catalog([order(),other]))
        self.assertEqual(result['orders'][0]['channel'],'unknown')
        self.assertEqual(result['source_coverage']['attribution']['bridge_counts'],{'cross_site_ambiguous':1})
        self.assertNotIn('order_no',result['unlinked_attribution_rows'][0])

    def test_full_month_archive_is_selected_without_rewriting_source_scope(self):
        rows=[es_row(),es_row('other',day='2026-11-09'),es_row('O2')]
        identity=catalog([order(),order('O2',site='320',title='www.rsorders.com')])
        result=project(data=dataset(rows),identity=identity)
        self.assertEqual(result['totals']['orders'],1)
        proof=result['source_coverage']['attribution']
        self.assertEqual(proof['excluded_source_rows'],2)
        self.assertEqual(proof['effective_scope']['end'],'2026-11-11')

    def test_unpinned_archive_and_short_period_are_not_silently_accepted(self):
        legacy=dataset(); legacy['revision_selection']='legacy_capture_unverified'
        with self.assertRaisesRegex(ValueError,'publication_required'):project(data=legacy)
        short=dataset();short['effective_scope']['start']='2026-11-11'
        with self.assertRaisesRegex(ValueError,'attribution_period'):project(data=short)
        short=catalog();short['scope']['end']='2026-11-09';short['scope']['start']='2026-11-09'
        self.assertEqual(project(identity=short)['orders'][0]['channel'],'unknown')

    def test_missing_or_conflicting_site_labels_never_infer_mmoexp(self):
        missing=order();missing.pop('site')
        result=project([missing],identity=catalog([missing]))
        self.assertEqual(result['totals']['orders'],0)
        self.assertEqual(len(result['unlinked_admin_rows']),1)
        conflict=order(title='other.example')
        with self.assertRaisesRegex(ValueError,'site_revision_conflict'):project([order(),conflict])
        with self.assertRaisesRegex(ValueError,'site_revision_conflict'):project(identity=catalog([conflict]))
        duplicate=order('O2',site='320')
        with self.assertRaisesRegex(ValueError,'site_mapping_ambiguous'):project([order(),duplicate])

    def test_cost_cache_observations_do_not_certify_whole_order_cost(self):
        costs=[dict(delivery_id='D1',source='www.mmoexp.com',sn='O1',genre='1',cost_total='150',sale_total='350.22'),
               dict(delivery_id='D2',source='www.mmoexp.com',sn='O1',genre='1',cost_total='50',sale_total='0')]
        result=project(costs=costs+[copy.deepcopy(costs[0])])
        self.assertEqual(result['orders'][0]['observed_cost_cny'],'200')
        self.assertIsNone(result['orders'][0]['actual_cost_cny'])
        self.assertEqual(result['coverage']['duplicate_cost_rows'],1)
        result=project(costs=costs,complete_cost_orders=[('266','O1')])
        self.assertEqual(result['orders'][0]['actual_cost_cny'],'200')

    def test_unavailable_archive_retains_paid_income_and_unknown_channel(self):
        result=project(data=None)
        self.assertEqual(result['orders'][0]['admin_paid_usd'],'50')
        self.assertEqual(result['orders'][0]['channel'],'unknown')
        self.assertEqual(result['source_coverage']['attribution']['status'],'unavailable')

    def test_missing_catalog_identity_does_not_certify_other_rows_unique(self):
        broken=order('O2');broken.pop('site_id')
        result=project(identity=catalog([order(),broken]))
        self.assertEqual(result['orders'][0]['channel'],'unknown')
        self.assertEqual(result['source_coverage']['attribution']['identity_status'],'identity_missing')

    def test_conflicting_attribution_remains_unknown_and_hash_cannot_smuggle_identity(self):
        row=es_row();row['marketing_attribution']['status']='conflict'
        result=project(data=dataset([row]))
        self.assertEqual(result['orders'][0]['channel'],'unknown')
        row=es_row();row.update(site_id='266',order_no='O1')
        result=project(data=dataset([row]),identity=None)
        self.assertEqual(result['orders'][0]['channel'],'unknown')


if __name__ == '__main__':
    unittest.main()
