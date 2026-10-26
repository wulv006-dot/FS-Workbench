import copy
import unittest
from datetime import datetime, timedelta, timezone

from campaign_backend.provider import preview_eligibility, project_source
from test_model_provider import model, goods


NOW=datetime(2026,1,2,3,4,5,tzinfo=timezone.utc)


def observed_pool():
    items=[]
    for mid,gid in [(700,1007),(600,1006)]:
        args=dict(site_id='266',game_id='1327',category_id='9623',model_id=str(mid))
        provider=dict(source='admin_readonly',observed_at=NOW.isoformat(),coverage={'complete':True},
            model=project_source(model(mid),args,True),products=[project_source(goods(gid,mid=mid),args)],currency=None)
        items.append(dict(model_id=str(mid),game_id='1327',category_id='9623',association=provider))
    return dict(source='admin_readonly',observed_at=NOW.isoformat(),coverage={'complete':True},
        association_coverage={'complete':True},items=items)


def policy(**changes):
    # Synthetic explicit server policy, never a production/business default.
    value=dict(site_id='266',game_id='1327',category_id='9623',max_age_seconds=60,fixed_model_ids=[])
    value.update(changes);return value


class PreviewEligibilityTests(unittest.TestCase):
    def evaluate(self,pool=None,config=None,now=NOW):
        return preview_eligibility(observed_pool() if pool is None else pool,policy() if config is None else config,now=now)

    def test_two_fresh_observed_guards_are_display_candidates_only_with_unknown_currency(self):
        source=observed_pool();before=copy.deepcopy(source)
        result=self.evaluate(source)
        self.assertTrue(result['eligible_for_preview']);self.assertEqual(result['candidate_count'],2)
        self.assertEqual({v['model_id'] for v in result['candidates']},{'700','600'})
        self.assertTrue(all(v['original_guard_observation']=='observed_original_guard' for v in result['candidates']))
        self.assertFalse(result['eligible_for_draw']);self.assertFalse(result['checkout_enabled']);self.assertFalse(result['authoritative'])
        self.assertIn('TRANSACTION_SELLABILITY_UNVERIFIED',result['warnings'])
        self.assertIn('CURRENCY_MAPPING_REQUIRED',result['warnings']);self.assertEqual(source,before)

    def test_freshness_and_fixed_references_require_explicit_server_policy_and_utc_clock(self):
        missing_age=policy();missing_age.pop('max_age_seconds')
        missing_fixed=policy();missing_fixed.pop('fixed_model_ids')
        for config in ({},missing_age,missing_fixed,policy(max_age_seconds=None),policy(max_age_seconds=0),
                policy(max_age_seconds=True),policy(max_age_seconds=float('inf')),policy(site_id=99)):
            result=self.evaluate(config=config);self.assertFalse(result['eligible_for_preview']);self.assertEqual(result['candidates'],[])
        self.assertFalse(self.evaluate(now=NOW.replace(tzinfo=None))['eligible_for_preview'])

    def test_missing_future_or_expired_sources_are_not_selected_even_when_outer_timestamp_is_fresh(self):
        for stamp in (None,(NOW-timedelta(seconds=61)).isoformat(),(NOW+timedelta(seconds=1)).isoformat(),'bad timestamp'):
            source=observed_pool();source['items'][0]['association']['observed_at']=stamp
            result=self.evaluate(source)
            self.assertFalse(result['eligible_for_preview']);self.assertEqual(result['candidate_count'],1);self.assertEqual(result['candidates'],[])
        for key,value in [('source','client_supplied'),('observed_at',(NOW-timedelta(seconds=61)).isoformat())]:
            source=observed_pool();source[key]=value
            result=self.evaluate(source);self.assertIn('CATEGORY_SOURCE_MISSING_OR_STALE',result['blocked_reasons'])

    def test_incomplete_category_or_association_is_never_a_complete_preview_pool(self):
        for key in ('coverage','association_coverage'):
            source=observed_pool();source[key]['complete']=False
            result=self.evaluate(source);self.assertFalse(result['eligible_for_preview'])
            self.assertIn('CATEGORY_OR_ASSOCIATIONS_INCOMPLETE',result['blocked_reasons'])
        source=observed_pool();source['items'][0]['association']['coverage']['complete']=False
        self.assertFalse(self.evaluate(source)['eligible_for_preview'])

    def test_offline_unknown_state_wrong_scope_missing_products_and_fixed_model_are_excluded(self):
        for mutation in ('model_offline','product_offline','unknown_state','bool_state','wrong_site','wrong_game','wrong_category','no_products'):
            source=observed_pool();item=source['items'][0];association=item['association'];product=association['products'][0]
            if mutation=='model_offline':association['model']['raw_state']['status']=0
            elif mutation=='product_offline':product['raw_state']['auto_off']=1
            elif mutation=='unknown_state':product['raw_state']['status']=None
            elif mutation=='bool_state':product['raw_state']['status']=True
            elif mutation=='wrong_site':product['product_ref']['site_id']='99'
            elif mutation=='wrong_game':product['product_ref']['game_id']='99'
            elif mutation=='wrong_category':product['category_id']='99'
            else:association['products']=[]
            with self.subTest(mutation=mutation):
                result=self.evaluate(source);self.assertFalse(result['eligible_for_preview']);self.assertEqual(result['candidate_count'],1)
        result=self.evaluate(config=policy(fixed_model_ids=['700']))
        self.assertFalse(result['eligible_for_preview']);self.assertEqual(result['excluded'][0]['reason'],'FIXED_MODEL_EXCLUDED')

    def test_global_dedup_and_product_identity_conflicts_cannot_make_two_models_from_one(self):
        source=observed_pool();source['items']=[source['items'][0],copy.deepcopy(source['items'][0])]
        result=self.evaluate(source);self.assertFalse(result['eligible_for_preview']);self.assertEqual(result['candidate_count'],1)
        source=observed_pool();source['items'].append(copy.deepcopy(source['items'][0]))
        self.assertEqual(self.evaluate(source)['candidate_count'],2)
        source=observed_pool();source['items'][1]['association']['products'][0]['product_ref']['goods_id']='1007'
        result=self.evaluate(source);self.assertFalse(result['eligible_for_preview'])
        self.assertIn('SOURCE_IDENTITY_CONFLICT',result['blocked_reasons'])


if __name__=='__main__':unittest.main()
