import ast
import copy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import Mock, patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
OBSERVER=SOURCE/'observe.py'
if not OBSERVER.is_file():
    OBSERVER=SOURCE.parents[2]/'ops/fc-reference-observer-ui-20261023/trigger/source/observe.py'
sys.path.insert(0,str(SOURCE))
from test_pricing_v2 import fixture,NOW
import pricing_v2 as pricing


def original_function(name,filename,**scope):
    tree=ast.parse((SOURCE/filename).read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE/filename),'exec'),scope)
    return scope[name]


def snapshot():
    rows=[dict(source='ItemD2R',platform=p,run_id='original',currency='USD',purchase_k='100',bonus_k='0',gross_usd='19.5',
               url='https://www.itemd2r.com/ea-sports-fc/fc-27-coins',status='valid',conditional=False,comparable=True,
               captured_at=NOW.isoformat()) for p in ('PS','XBOX','PC')]
    return dict(run_id='original',competitors=[dict(status='valid',captured_at=NOW.isoformat())],
                reference_competitors=dict(status='captured',run_id='original',offers=rows))


class Bidirectional(unittest.TestCase):
    def test_anchor_can_raise_and_lower_without_cost_change(self):
        for market,direction in [('21','up'),('19.5','down'),('19.99','hold')]:
            evidence,rows,_=fixture()
            if direction=='hold':
                for own in evidence['storefront']['rows'].values():own['package_usd']='19.99'
            for offers in evidence['offers'].values():offers['Lootbar']['usd_price']=market
            receipt=pricing.apply_decision(rows,evidence,{},now=NOW)
            self.assertEqual(receipt['decisions'][0]['direction'],direction)
            self.assertEqual(rows[0]['proposal'],rows[1]['proposal'])
            self.assertEqual(pricing.number(rows[0]['main_page_usd']),pricing.number(market))

    def test_unchanged_pc_is_independent_of_console_rise(self):
        evidence,rows,_=fixture()
        evidence['storefront']['rows']['PC']['package_usd']='19.99'
        evidence['offers']['PC']['Lootbar']['usd_price']='19.99'
        for p in ('PS','XBOX'):evidence['offers'][p]['Lootbar']['usd_price']='21'
        receipt=pricing.apply_decision(rows,evidence,{},now=NOW)
        self.assertEqual([d['direction'] for d in receipt['decisions']],['up','hold'])
        self.assertEqual(rows[2]['target_page_usd'],'19.99')

    def test_higher_cost_floor_can_exceed_anchor_and_unsafe_hold_is_absent(self):
        evidence,rows,_=fixture()
        for row in evidence['costs'].values():row['cny_per_1k']='2'
        receipt=pricing.apply_decision(rows,evidence,{},now=NOW)
        self.assertEqual(receipt['decisions'][0]['reason'],'cost_or_promotion_floor')
        self.assertNotIn('hold',receipt['decisions'][0]['candidates'])
        for row in rows:
            self.assertGreaterEqual(pricing.number(row['proof']['catalog']['minimum_estimated_average_margin_pct']),10)

    def test_evaluated_middle_price_and_hold_are_not_clamped_to_anchor(self):
        for candidate in ('20','20.5','21'):
            evidence,rows,_=fixture()
            for offers in evidence['offers'].values():offers['Lootbar']['usd_price']='21'
            edits=dict(quotes={'PS':str(pricing.number(candidate)/100),'XBOX':str(pricing.number(candidate)/100)})
            pricing.apply_decision(rows,evidence,edits,now=NOW)
            self.assertEqual(pricing.number(rows[0]['target_page_usd']),pricing.number(candidate))
            self.assertEqual(rows[0]['ending_reason'],'explicit_candidate_no_hidden_adjustment')
            self.assertGreaterEqual(pricing.number(rows[0]['proof']['catalog']['minimum_estimated_average_margin_pct']),10)

    def test_stale_anchor_and_simultaneous_conflicting_cost_still_reject(self):
        for fault in ('stale','conflict'):
            evidence,rows,_=fixture()
            if fault=='stale':evidence['offers']['PS']['Lootbar']['checked_at']=(NOW-timedelta(hours=2)).isoformat()
            else:evidence['costs']['PS']['cny_per_1k']='.8'
            with self.subTest(fault=fault),self.assertRaises(ValueError):pricing.apply_decision(rows,evidence,{},now=NOW)

    def test_simulation_consumer_pins_the_new_core(self):
        import hashlib
        tree=ast.parse((SOURCE/'pricing_simulation.py').read_text(encoding='utf-8'))
        pin=next(n.value.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='V2_CODE_SHA' for t in n.targets))
        self.assertEqual(pin,hashlib.sha256((SOURCE/'pricing_v2.py').read_bytes()).hexdigest())

    def test_actual_review_input_carries_two_way_and_reference_contract(self):
        import hermes_pricing_bridge as bridge
        from test_control import quoted,RUN
        quote=quoted();quote['evidence']['reference_market']=dict(status='available',offers=snapshot()['reference_competitors']['offers'])
        calls=[]
        def request(owner,path,body=None):
            calls.append((path,body))
            return dict(conversation_id='review-conversation') if path=='/api/hermes/conversations' else dict(turn_id='review-turn')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'evidence').mkdir()
            with patch.object(bridge,'ROOT',root),patch.object(bridge,'FS',root),patch.object(bridge,'request',request),patch.object(bridge,'save',lambda p,d:p.write_text(json.dumps(d))),patch.object(bridge.os,'chown',lambda *a:None,create=True),patch('pricing_operations.grant'),patch.object(bridge,'turn_state',return_value=dict(state='completed',task_id='task')),patch.object(bridge,'recommendation',return_value=None):
                result=bridge.review(dict(job_id=RUN,actor='wulv'),quote,wait_seconds=0)
        self.assertEqual(result['phase'],'completed')
        text=calls[1][1]['text']
        for required in ('不论上涨还是下跌','当前价不再是上调上限','每实际交付K','第二梯队','实验权重仍只模拟','itemd2r.com','80/15/5','ItemD2R第二梯队15%','U7Buy第二梯队5%','不额外给多站一致奖励'):
            self.assertIn(required,text)
        self.assertEqual(len(calls),2)

    def test_missing_model_uses_current_program_without_capping_valid_choice(self):
        evidence,rows,_=fixture()
        for own in evidence['storefront']['rows'].values():own['package_usd']='19.99'
        for offers in evidence['offers'].values():offers['Lootbar']['usd_price']='21'
        receipt=pricing.apply_decision(rows,evidence,{},now=NOW)
        self.assertGreater(pricing.number(rows[0]['target_page_usd']),pricing.number('19.99'))
        self.assertEqual(pricing.number(receipt['decisions'][0]['model_unavailable_fallback_usd']),pricing.number('20.99'))
        for cost in evidence['costs'].values():cost['cny_per_1k']='2'
        receipt=pricing.apply_decision(rows,evidence,{},now=NOW)
        self.assertGreater(pricing.number(receipt['decisions'][0]['model_unavailable_fallback_usd']),pricing.number('19.99'))

    def test_worker_fallback_recomputes_original_price_and_preserves_rejection_reason(self):
        from decimal import Decimal
        from test_control import quoted,RUN
        quote=quoted();quote['result']['decision_receipt']['decisions'][0]['model_unavailable_fallback_usd']='19.50'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'quotes').mkdir()
            module=ModuleType('server_quote_job')
            def recalculate(jid,edits,hermes_decision):
                (root/'quotes'/(jid+'.json')).write_text(json.dumps(dict(recomputed=True)))
            module._quote_for_run=Mock(side_effect=recalculate)
            function=original_function('apply_program_fallback','fc27_cloud_worker.py',Decimal=Decimal,json=json,ROOT=root,load_policy=lambda:dict(minimum_gross_margin_pct='10'))
            job=dict(job_id=RUN,hermes_review=dict(phase='completed'),hermes_candidate_rejected='pricing_hard_margin_floor')
            with patch.dict(sys.modules,{'server_quote_job':module}):
                result=function(job,quote)
            self.assertTrue(result['recomputed']);self.assertEqual(module._quote_for_run.call_count,1)
            args=module._quote_for_run.call_args
            self.assertEqual(args.args[1]['quotes']['PS'],'0.195')
            self.assertEqual(args.args[1]['quotes']['PS'],args.args[1]['quotes']['XBOX'])
            self.assertEqual(args.kwargs['hermes_decision']['reason'],'pricing_hard_margin_floor')

    def test_worker_fallback_still_stops_on_changed_basis(self):
        from decimal import Decimal
        from test_control import quoted,RUN
        quote=quoted();quote['result']['decision_receipt']['decisions'][0]['model_unavailable_fallback_usd']='19.50'
        module=ModuleType('server_quote_job');module._quote_for_run=Mock(side_effect=ValueError('newer_run_exists'))
        function=original_function('apply_program_fallback','fc27_cloud_worker.py',Decimal=Decimal,json=json,ROOT=Path('.'),load_policy=lambda:dict(minimum_gross_margin_pct='10'))
        with patch.dict(sys.modules,{'server_quote_job':module}),self.assertRaisesRegex(ValueError,'newer_run_exists'):
            function(dict(job_id=RUN),quote)
        self.assertEqual(module._quote_for_run.call_count,1)


class ReferenceInputs(unittest.TestCase):
    def setUp(self):
        self.context=original_function('reference_context','server_quote_job.py',PLATFORMS=('PS','XBOX','PC'))

    def test_same_run_fresh_source_keeps_delivered_quantity(self):
        value=self.context(snapshot(),NOW)
        self.assertEqual(value['status'],'available')
        self.assertEqual(value['offers'][0]['bonus_k'],'0')
        self.assertEqual(value['authority'],'fc-reference-weighting-20261024-v2')

    def test_missing_or_failed_reference_never_reuses_old_sample(self):
        for raw in (None,{},'invalid',dict(status='unavailable',reason='reader_failed',offers=[])):
            value=self.context(dict(snapshot(),reference_competitors=raw),NOW)
            self.assertEqual(value['status'],'unavailable');self.assertEqual(value['offers'],[])

    def test_cross_run_future_stale_or_mixed_capture_rejected(self):
        for fault in ('cross_run','future','stale','span'):
            data=snapshot()
            if fault=='cross_run':data['reference_competitors']['offers'][0]['run_id']='other'
            elif fault=='future':data['reference_competitors']['offers'][0]['captured_at']=(NOW+timedelta(minutes=1)).isoformat()
            elif fault=='stale':data['reference_competitors']['offers'][0]['captured_at']=(NOW-timedelta(minutes=16)).isoformat()
            else:data['competitors'][0]['captured_at']=(NOW-timedelta(minutes=6)).isoformat()
            with self.subTest(fault=fault):
                value=self.context(data,NOW);self.assertEqual(value['status'],'unavailable');self.assertEqual(value['offers'],[])

    def test_conditional_currency_identity_and_amount_contracts(self):
        for field,value in [('conditional',True),('currency','EUR'),('comparable',False),('gross_usd','NaN'),
                            ('source','IGGM'),('url','https://example.com'),('purchase_k','10'),('platform','PS4')]:
            data=snapshot();data['reference_competitors']['offers'][0][field]=value
            with self.subTest(field=field):self.assertEqual(self.context(data,NOW)['status'],'unavailable')

    def test_worker_calls_original_reader_once_and_retains_failure(self):
        read=Mock(return_value=snapshot()['reference_competitors']['offers'])
        loader=SimpleNamespace(exec_module=lambda m:setattr(m,'public_read',read))
        function=original_function('collect_reference_market','fc27_cloud_worker.py')
        with patch('importlib.util.spec_from_file_location',return_value=SimpleNamespace(loader=loader)),patch('importlib.util.module_from_spec',return_value=SimpleNamespace()):
            captured=function('original');self.assertEqual(captured['status'],'captured');self.assertEqual(read.call_count,1)
            read.side_effect=TimeoutError('budget')
            missing=function('original');self.assertEqual(missing['status'],'unavailable');self.assertEqual(missing['reason'],'TimeoutError')
            self.assertEqual(read.call_count,2)

    def test_observer_reuses_capture_and_never_refetches_failed_capture(self):
        spec=importlib.util.spec_from_file_location('bidirectional_observer',OBSERVER)
        observer=importlib.util.module_from_spec(spec);spec.loader.exec_module(observer)
        import contextlib,uuid
        jid=str(uuid.uuid4())
        for state in ('captured','unavailable','legacy'):
            with self.subTest(state=state),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);fc=root/'fc';(fc/'jobs').mkdir(parents=True);(fc/'runs').mkdir()
                (fc/'jobs'/(jid+'.json')).write_text(json.dumps(dict(job_id=jid,kind='auto_cycle',status='ready',created_at=NOW.isoformat())))
                data=snapshot();data.update(run_id=jid,status='ready_for_quote',created_at=NOW.isoformat())
                data['reference_competitors'].update(status=state,run_id=jid)
                if state=='legacy':del data['reference_competitors']
                path=fc/'runs'/(jid+'.json');path.write_text(json.dumps(data));before=path.read_bytes()
                modules={name:ModuleType(name) for name in ('automation_tick','fc27_cloud_api','snapshot_layer','reference_shadow','fcntl')}
                modules['fcntl'].LOCK_EX=1;modules['fcntl'].LOCK_NB=2;modules['fcntl'].flock=lambda *a:None
                modules['automation_tick'].queue_mutation=contextlib.nullcontext
                modules['automation_tick'].RETRY_LOCKS=[];modules['automation_tick'].retry_guard=lambda:'ready'
                modules['fc27_cloud_api'].health=lambda:dict(incomplete_executions=0)
                modules['snapshot_layer'].atomic_json=lambda p,d:p.write_text(json.dumps(d))
                modules['reference_shadow'].experimental_scenarios=lambda *a,**kw:dict(status='test')
                clock=SimpleNamespace(now=lambda tz:NOW,fromisoformat=__import__('datetime').datetime.fromisoformat)
                with patch.dict(sys.modules,modules),patch.object(observer,'FC',fc),patch.object(observer,'STATE',root/'observer'),patch.object(observer,'datetime',clock),patch.object(observer,'public_read',return_value=snapshot()['reference_competitors']['offers']) as reader:
                    result=observer.main()
                    self.assertEqual(result['status'],'failed' if state=='unavailable' else 'observed')
                    self.assertEqual(reader.call_count,1 if state=='legacy' else 0)
                    observer.main();self.assertEqual(reader.call_count,1 if state=='legacy' else 0)
                self.assertEqual(path.read_bytes(),before)


class ReferenceWeights(unittest.TestCase):
    def test_baseline_compatibility_update_preserves_exact_policy_bindings_and_other_bytes(self):
        spec=importlib.util.spec_from_file_location('weighting_compatibility',SOURCE.parent/'deploy/weighting_compatibility.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        old,new='a'*64,'b'*64
        policy=dict(contract='fs-knowledge-load-policy-v1',unknown={'keep':[1,2]},native={'enabled':True},
                    task_routes=dict(enabled=True,routes=[dict(owner='wulv',project='FS',channel='fs',task_types=['report','data','conversation'],
                        baseline_compatibility=dict(mode='retain_full_baseline',sha256=old)),dict(owner='other',project='FS',channel='feishu')]))
        raw=json.dumps(policy,indent=3).encode()
        self.assertEqual(module.candidate(raw,old,new),raw.replace(old.encode(),new.encode(),1))
        for fault in ('owner','duplicate','unknown_digest'):
            changed=copy.deepcopy(policy)
            if fault=='owner':changed['task_routes']['routes'][0]['owner']='other'
            elif fault=='duplicate':changed['task_routes']['routes'].append(copy.deepcopy(changed['task_routes']['routes'][0]))
            else:changed['extra']=old
            with self.subTest(fault=fault),self.assertRaises(ValueError):module.candidate(json.dumps(changed).encode(),old,new)

    def prepared(self):
        evidence,rows,_=fixture();evidence['run_id']='original'
        offers=snapshot()['reference_competitors']['offers']
        for r in offers:r.update(gross_usd='20',bonus_k='5')
        evidence['reference_market']=dict(status='available',run_id='original',offers=offers)
        for p in ('PS','XBOX','PC'):
            evidence['offers'][p]['U7Buy']=dict(usd_price='20',base_k='100',bonus_k='5',
                checked_at=NOW.isoformat(),conditional=False,comparable=True,url='https://www.u7buy.com/fc27/coins')
        return evidence,rows

    def reference(self,evidence,rows):
        receipt=pricing.apply_decision(rows,evidence,{},now=NOW)
        return receipt,rows[0]['reference_adjustment']

    def test_same_target_formula_supports_both_directions_and_caps_outliers(self):
        from decimal import Decimal
        for value,expected in [('1','-.01'),('19','-.01'),('20','0'),('21','.01'),('200','.01')]:
            e,rows=self.prepared()
            for r in e['reference_market']['offers']:r['gross_usd']=value
            for offers in e['offers'].values():offers['U7Buy']['usd_price']=value
            receipt,ref=self.reference(e,rows)
            self.assertEqual(Decimal(ref['raw_offset']),Decimal(expected))
            self.assertEqual(Decimal(receipt['decisions'][0]['raw_weighted_usd']),Decimal(20)*(1+Decimal(expected)))
            self.assertGreaterEqual(Decimal(rows[0]['proof']['catalog']['minimum_estimated_average_margin_pct']),10)

    def test_unequal_weights_do_not_count_sources_as_equal_votes(self):
        from decimal import Decimal
        e,rows=self.prepared()
        for r in e['reference_market']['offers']:r['gross_usd']='19'
        for offers in e['offers'].values():offers['U7Buy']['usd_price']='21'
        _,ref=self.reference(e,rows)
        self.assertEqual(Decimal(ref['raw_offset']),Decimal('-.005'))
        self.assertEqual(ref['sources']['ItemD2R']['weight'],'0.15')
        self.assertEqual(ref['sources']['U7Buy']['weight'],'0.05')

    def test_missing_references_do_not_redistribute_or_borrow_another_run(self):
        from decimal import Decimal
        for missing,expected in [('ItemD2R','.0025'),('U7Buy','.0075'),('both','0')]:
            e,rows=self.prepared()
            for r in e['reference_market']['offers']:r['gross_usd']='21'
            for offers in e['offers'].values():offers['U7Buy']['usd_price']='21'
            if missing in ('ItemD2R','both'):e['reference_market']['run_id']='other'
            if missing in ('U7Buy','both'):
                for offers in e['offers'].values():del offers['U7Buy']
            _,ref=self.reference(e,rows)
            self.assertEqual(Decimal(ref['raw_offset']),Decimal(expected))
            self.assertFalse(ref['missing_weight_reallocated'])

    def test_optional_invalid_reference_cannot_change_baseline(self):
        for fault in ('conditional','stale','future','coverage','currency','url','quantity','span'):
            e,rows=self.prepared();item=e['reference_market']['offers'][0]
            item['gross_usd']='1'
            if fault=='conditional':item['conditional']=True
            elif fault=='stale':item['captured_at']=(NOW-timedelta(minutes=16)).isoformat()
            elif fault=='future':item['captured_at']=(NOW+timedelta(minutes=1)).isoformat()
            elif fault=='coverage':e['reference_market']['offers'].pop()
            elif fault=='currency':item['currency']='EUR'
            elif fault=='url':item['url']='https://other.example/coins'
            elif fault=='quantity':item['purchase_k']='50'
            else:item['captured_at']=(NOW-timedelta(minutes=6)).isoformat()
            with self.subTest(fault=fault):
                _,ref=self.reference(e,rows)
                self.assertEqual(ref['sources']['ItemD2R']['status'],'unavailable')
                self.assertEqual(pricing.number(ref['raw_weighted_usd']),20)

    def test_console_uses_lower_adjusted_market_and_pc_is_independent(self):
        from decimal import Decimal
        e,rows=self.prepared();e['reference_market']['offers'][0]['gross_usd']='19'
        e['reference_market']['offers'][1]['gross_usd']='21'
        receipt,_=self.reference(e,rows)
        self.assertEqual(Decimal(receipt['decisions'][0]['raw_weighted_usd']),Decimal('19.85'))
        self.assertEqual(rows[0]['proposal'],rows[1]['proposal'])
        self.assertEqual(Decimal(receipt['decisions'][1]['raw_weighted_usd']),20)

    def test_cost_floor_and_original_missing_model_fallback_are_preserved(self):
        e,rows=self.prepared()
        for r in e['reference_market']['offers']:r['gross_usd']='21'
        receipt,_=self.reference(e,rows)
        self.assertEqual(pricing.number(receipt['decisions'][0]['model_unavailable_fallback_usd']),pricing.number('19.99'))
        self.assertGreater(pricing.number(receipt['decisions'][0]['raw_weighted_usd']),20)
        for cost in e['costs'].values():cost['cny_per_1k']='2'
        receipt,_=self.reference(e,rows)
        self.assertEqual(receipt['decisions'][0]['reason'],'cost_or_promotion_floor')
        self.assertGreater(pricing.number(receipt['decisions'][0]['model_unavailable_fallback_usd']),20)

    def test_reference_receipt_and_row_cannot_be_tampered_after_preview(self):
        e,rows=self.prepared();receipt,_=self.reference(e,rows)
        quote=dict(evidence=e,edits={'minimum_gross_margin_pct':'10'},result=dict(rows=rows,decision_receipt=receipt))
        policy={'minimum_gross_margin_pct':'10'}
        pricing.verify_quote(quote,policy,['PS','XBOX'],now=NOW)
        rows[0]['reference_adjustment']['raw_offset']='.9'
        with self.assertRaises(ValueError):pricing.verify_quote(quote,policy,['PS','XBOX'],now=NOW)


if __name__=='__main__':unittest.main()
