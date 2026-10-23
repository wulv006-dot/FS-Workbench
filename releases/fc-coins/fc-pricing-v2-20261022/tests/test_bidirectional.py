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
        for required in ('不论上涨还是下跌','当前价不再是上调上限','每实际交付K','第二梯队','实验权重仍只模拟','itemd2r.com'):
            self.assertIn(required,text)
        self.assertEqual(len(calls),2)

    def test_missing_model_fallback_preserves_original_direction_without_capping_valid_choice(self):
        evidence,rows,_=fixture()
        for own in evidence['storefront']['rows'].values():own['package_usd']='19.99'
        for offers in evidence['offers'].values():offers['Lootbar']['usd_price']='21'
        receipt=pricing.apply_decision(rows,evidence,{},now=NOW)
        self.assertGreater(pricing.number(rows[0]['target_page_usd']),pricing.number('19.99'))
        self.assertEqual(pricing.number(receipt['decisions'][0]['model_unavailable_fallback_usd']),pricing.number('19.99'))
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
        self.assertEqual(value['authority'],'qualitative_reference_only_no_experimental_weights')

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


if __name__=='__main__':unittest.main()
