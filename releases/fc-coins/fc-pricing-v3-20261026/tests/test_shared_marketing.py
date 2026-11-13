import copy
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fc_pricing_v3 import business_source as source
import test_business_source as fixtures


class SharedMarketing(unittest.TestCase):
    def setUp(self):
        self.now,self.order,self.window=fixtures.BusinessSourceTest().window_fixture()
        self.facts=dict(private=True,version='same-order-facts-20261113-v1',
            input_scope=dict(site_id='266',gid='1327'),
            source_coverage=dict(source_revision='admin1',attribution=dict(source_revision='es1',data_revision='1',status='available')),
            orders=[dict(site_id='266',gid='1327',order_no=self.order['order_no'],
                admin_paid_usd=self.order['amount_usd_format'],paid_at='2026-10-27 00:00:00',
                channel='SEO',marketing_attribution=dict(status='available',channel_raw='SEO',
                    source_raw='private referral text',source_revision='es1',available_at='2026-11-12T04:00:00+08:00'))])

    def bind(self,facts):
        return source.bind_price_windows([self.order],[self.window],self.now,shared_order_facts=facts)

    def test_channel_revision_does_not_move_price_window(self):
        old=source.bind_price_windows([self.order],[self.window],self.now)
        first=self.bind(self.facts)
        changed=copy.deepcopy(self.facts)
        changed['source_coverage']['attribution'].update(source_revision='es2',data_revision='2')
        changed['orders'][0].update(channel='PPC')
        changed['orders'][0]['marketing_attribution'].update(channel_raw='PPC',source_revision='es2')
        second=self.bind(changed)
        for value in (first,second):
            self.assertEqual(value['budget_settlements'],old['budget_settlements'])
            self.assertEqual(value['training_observations'],old['training_observations'])
            self.assertEqual(value['learning_coverage'],old['learning_coverage'])
            stripped=[{k:v for k,v in row.items() if k!='marketing_attribution'} for row in value['actual_outcomes']]
            self.assertEqual(stripped,old['actual_outcomes'])
            self.assertNotIn('private referral text',str(value))
        self.assertNotEqual(first['marketing_context']['revision'],second['marketing_context']['revision'])
        self.assertEqual(self.facts['orders'][0]['channel'],'SEO')

    def test_channel_unknown_keeps_revenue_and_cost_meaning(self):
        self.facts['orders'][0].update(channel='unknown')
        self.facts['orders'][0]['marketing_attribution']['status']='field_absent'
        result=self.bind(self.facts)
        row=result['actual_outcomes'][0]
        self.assertEqual(result['marketing_context']['channels']['unknown']['known_paid_usd'],row['actual_net_usd'])
        self.assertEqual(row['cost_status'],'pending')
        self.assertIsNone(row['actual_contribution_usd'])

    def test_repeat_lift_from_split_not_retention_proof(self):
        result=self.bind(self.facts)
        self.assertIsNone(result['actual_outcomes'][0]['marketing_attribution']['first_purchase_channel'])
        self.assertEqual(result['marketing_context']['retention_status'],'mature_cohort_not_proven')

    def test_cross_site_or_amount_revision_cannot_attach_channel(self):
        for field,value in [('site_id','320'),('admin_paid_usd','999')]:
            changed=copy.deepcopy(self.facts);changed['orders'][0][field]=value
            result=self.bind(changed)
            self.assertEqual(result['actual_outcomes'][0]['marketing_attribution']['channel'],'unknown')
            self.assertEqual(sum(x['orders'] for x in result['marketing_context']['channels'].values()),1)
            self.assertEqual(len(result['training_observations']),len(self.bind(self.facts)['training_observations']))

    def test_conflicting_same_order_revision_is_unknown_not_last_wins(self):
        self.facts['orders'].append(dict(self.facts['orders'][0],channel='PPC'))
        result=self.bind(self.facts)
        self.assertEqual(result['actual_outcomes'][0]['marketing_attribution']['status'],'shared_order_revision_conflict')

    def test_private_bridge_crosses_original_source_process_not_quote_output(self):
        from fc_pricing_v3 import sources, runtime
        evidence=dict(run_id='fixture',storefront={},shared_order_facts=self.facts)
        with patch.object(sources.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{}')) as process:
            sources.collect_context(evidence)
        self.assertEqual(json.loads(process.call_args.kwargs['input'])['shared_order_facts'],self.facts)
        db=Mock()
        db.all.return_value=[]
        db.get.side_effect=lambda table,key: {'base_prices':{}} if table=='budget_references' else None
        enriched=self.bind(self.facts)
        with patch.object(runtime,'ledger',return_value=db), patch.object(runtime,'collection_scope',return_value=dict(active_mode='smart',scope={})), patch.object(runtime,'enrich_segments'), patch.object(sources,'collect_context',return_value=dict(private_updates={},context=enriched)) as collect:
            result=runtime.context(evidence)
        self.assertEqual(collect.call_args.args[0]['shared_order_facts'],self.facts)
        self.assertNotIn('shared_order_facts',result)
        self.assertNotIn(self.order['order_no'],str(result))
        self.assertIn('marketing_context',result)

    def test_missing_or_invalid_optional_facts_do_not_claim_available(self):
        baseline=source.bind_price_windows([self.order],[self.window],self.now)
        variants=[dict(self.facts,orders=[]),dict(self.facts,input_scope=None),
            dict(self.facts,orders=[None]),dict(self.facts,source_coverage=None)]
        for facts in variants:
            result=self.bind(facts)
            self.assertNotEqual(result['marketing_context']['status'],'available')
            self.assertEqual(result['budget_settlements'],baseline['budget_settlements'])
            self.assertEqual(result['learning_coverage'],baseline['learning_coverage'])
        self.assertEqual(self.bind(dict(self.facts,orders=[]))['marketing_context']['unmatched_orders'],1)
        complete=self.bind(self.facts)
        self.assertEqual(complete['marketing_context']['status'],'available')
        self.assertEqual(complete['actual_outcomes'][0]['marketing_attribution']['basis'],'pinned_ES_order_channel_with_Admin_same_order_identity')

    def test_daily_financial_summary_hash_ignores_only_marketing_revision(self):
        import test_daily_profit as fixture
        from fc_pricing_v3 import daily
        case=fixture.DailyProfit();case.setUp()
        original=daily.profit_summary(case.online,case.windows,case.ops,'2026-11-06','p')
        for channel in ('SEO','PPC'):
            value=copy.deepcopy(case.online)
            for row in value['actual_outcomes']:row['marketing_attribution']=dict(channel=channel)
            self.assertEqual(daily.profit_summary(value,case.windows,case.ops,'2026-11-06','p'),original)
        value['actual_outcomes'][0]['actual_contribution_usd']='24'
        self.assertNotEqual(daily.profit_summary(value,case.windows,case.ops,'2026-11-06','p')['source_sha256'],original['source_sha256'])


if __name__=='__main__':unittest.main()
