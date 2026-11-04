from datetime import datetime, timedelta, timezone
import unittest

from fc_pricing_v3.smart import assignment, candidates, build_candidate, candidate_or_baseline, effective_key, assess, observed_blocks, epoch_policy, early_correction, scope_gaps


class SmartScheduleTest(unittest.TestCase):
    def test_balanced_stable_blocks_and_epoch_rollover(self):
        start = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)
        plan = {'plan_id': 'plan-1', 'revision': 1, 'starts_at': start.isoformat()}
        blocks = [assignment(plan, start + timedelta(hours=3 * i)) for i in range(16)]
        labels = [b['label'] for b in blocks]
        self.assertEqual((labels.count('A'), labels.count('B'), labels.count('C')), (6, 6, 4))
        for i in range(8):
            self.assertNotEqual(labels[i], labels[i + 8])
        self.assertEqual(assignment(plan, start + timedelta(hours=1)), blocks[0])
        self.assertEqual(assignment(plan, start + timedelta(hours=48))['epoch'], 1)

    def test_mature_winner_retains_control_and_exploration(self):
        start = datetime(2026, 11, 5, tzinfo=timezone.utc)
        plan = {'plan_id': 'plan-1', 'revision': 1, 'starts_at': start.isoformat()}
        policy = {'winner': 'B', 'excluded': []}
        result = assignment(plan, start + timedelta(hours=48), policy=policy)
        self.assertEqual((result['schedule'].count('A'), result['schedule'].count('B'), result['schedule'].count('C')), (3,12,1))
        self.assertEqual(result['marginal_probabilities'], {'A': '0.1875', 'B': '0.75', 'C': '0.0625'})

    def test_stop_loss_never_rewrites_current_block(self):
        start = datetime(2026, 11, 5, tzinfo=timezone.utc)
        plan = {'plan_id':'p','revision':1,'starts_at':start.isoformat()}
        original = [assignment(plan,start+timedelta(hours=3*i)) for i in range(16)]
        next_b = next(i for i in range(1,16) if original[i]['label']=='B')
        correction = {'excluded':['B'],'effective_from_block':next_b}
        before = assignment(plan,start+timedelta(hours=3*(next_b-1)),correction=correction)
        after = assignment(plan,start+timedelta(hours=3*next_b),correction=correction)
        self.assertEqual(before['label'],original[next_b-1]['label'])
        self.assertEqual(after['original_label'],'B')
        self.assertEqual(after['label'],'A')
        self.assertFalse(after['randomization_verified'])
        self.assertEqual(after['marginal_probabilities']['A'],'1')

    def test_late_daily_data_is_assessed_without_changing_current_schedule(self):
        class Memory:
            def __init__(self): self.rows = {}
            def get(self, table, key): return self.rows.get((table, key))
            def put(self, table, key, value): self.rows[(table, key)] = value
            def all(self, table): return []
        start = datetime(2026, 11, 5, tzinfo=timezone.utc)
        plan = {'plan_id': 'p', 'revision': 1, 'starts_at': start.isoformat()}
        db = Memory()
        first = epoch_policy(db, plan, start + timedelta(hours=48), 1)
        db.put('metadata', 'daily_online_context', {'learning_coverage': {'query_complete': True,
               'customer_coverage': {'status': 'complete'}, 'gap_events': [], 'unscoped_time_gaps': False,
               'observed_at': (start + timedelta(hours=49)).isoformat()}, 'actual_outcomes': []})
        current = epoch_policy(db, plan, start + timedelta(hours=49), 1)
        self.assertEqual(current, first)
        pending = db.get('metadata', 'smart-pending:p:1')
        self.assertEqual(pending['assessed_epoch'], 0)
        db.put('metadata', 'smart-policy:p:1:1', {'status':'WAITING_MORE_DATA', 'winner':None, 'excluded':['B']})
        later = epoch_policy(db, plan, start + timedelta(hours=96), 2)
        self.assertIn('B', later['excluded'])

    def test_candidates_use_delivered_price_cap_and_merge(self):
        tiers = {'PS': {'base_k': '100', 'bonus_k': '5', 'retained_ratio': '1'},
                 'XBOX': {'base_k': '100', 'bonus_k': '5', 'retained_ratio': '1'}}
        result = candidates('10.00', tiers, {'PS': '10', 'XBOX': '9.75'})
        self.assertEqual(result['A'], '10.00')
        self.assertEqual(result['B'], '10.30')
        self.assertEqual(result['C'], '10.54')
        no_room = candidates('11.00', tiers, {'PS': '10', 'XBOX': '9.90'})
        self.assertEqual(set(no_room.values()), {'11.00'})
        self.assertEqual(set(candidates('10.00', tiers, {'PS': None, 'XBOX': '10'}).values()), {'10.00'})

    def test_no_platforms_is_not_competition_evidence(self):
        with self.assertRaises(ValueError):
            candidates('10.00', {}, {})

    def test_dedup_uses_rounded_actual_delivery_price(self):
        tier = {'base_k': '100', 'bonus_k': '5', 'retained_ratio': '.5'}
        evidence = {'promotion_envelope': {'packages': {p: {'tiers': [tier]} for p in ('PS', 'XBOX', 'PC')}}, 'regional_controls': []}
        a = {'base_prices': {'console': '10.01', 'pc': '10.00'}, 'region_coefficients': {}}
        b = {'base_prices': {'console': '10.02', 'pc': '10.00'}, 'region_coefficients': {}}
        self.assertEqual(effective_key(evidence, a), effective_key(evidence, b))

    def test_candidate_reproves_sprint_baseline_financially(self):
        from test_dual20_sprint import source, NOW
        from fc_pricing_v3 import engine
        data = source(loot='10', item='11', cost='.1', bonus='5')
        plan = {'mode': 'revenue_sprint', 'resources': ['base:console', 'base:pc'],
                'price_anchor': engine.current_action(data), 'parameters': {}}
        evaluation = engine.evaluate(data, 'revenue_sprint', plan=plan, now=NOW)
        baseline = evaluation['selected']
        self.assertIsNotNone(baseline, evaluation['failures'])
        selected = build_candidate(data, plan, evaluation['current'], baseline, 'B', NOW)
        self.assertTrue(selected['financial_proof']['pass_all'])
        self.assertGreaterEqual(float(selected['action']['base_prices']['pc']),
                                float(baseline['action']['base_prices']['pc']))

    def test_a_preserves_baseline_floor_fallback_reason(self):
        from test_dual20_sprint import source, NOW
        from fc_pricing_v3 import engine
        data=source(loot='1',item='2',cost='.35',bonus='5')
        plan={'mode':'revenue_sprint','resources':['base:console','base:pc'],
              'price_anchor':engine.current_action(data),'parameters':{}}
        evaluation=engine.evaluate(data,'revenue_sprint',plan=plan,now=NOW)
        baseline=evaluation['selected']
        self.assertEqual(baseline['decision_type'],'floor_fallback')
        candidate=build_candidate(data,plan,evaluation['current'],baseline,'A',NOW)
        self.assertEqual(candidate['decision_type'],'floor_fallback')
        self.assertEqual(candidate['decision_reason'],baseline['decision_reason'])

    def test_failed_uplift_does_not_block_legal_baseline(self):
        from unittest.mock import patch
        baseline = {'action': {'base_prices': {'pc': '10'}}, 'financial_proof': {'pass_all': True}}
        def fail_candidate(evidence, plan, current, base, label, now):
            if label=='A': return base.copy()
            raise ValueError('NO_SAFE_COMMIT_PATH')
        with patch('fc_pricing_v3.smart.build_candidate', side_effect=fail_candidate):
            result = candidate_or_baseline({}, {}, {}, baseline, 'C', None)
        self.assertEqual(result['action'], baseline['action'])
        self.assertEqual(result['smart_reason'], 'NO_SAFE_COMMIT_PATH')
        with patch('fc_pricing_v3.smart.build_candidate', side_effect=ValueError('unexpected_input_error')):
            with self.assertRaisesRegex(ValueError, 'unexpected_input_error'):
                candidate_or_baseline({}, {}, {}, baseline, 'C', None)

    def test_assessment_requires_complete_paired_outcomes_and_can_select_winner(self):
        blocks = []
        def events(count, net, gross, new):
            return [dict(offset=100+i, actual_net_usd=str(net/count), actual_contribution_usd=str(gross/count),
                         new_customer=i<new, customer_key=str(i)) for i in range(count)]
        for slot in (0, 1):
            blocks.extend([dict(slot=slot, label='A', hours=3, complete=True, prices=['a'], intervals=[[0,10800]], events=events(20, 100, 30, 10)),
                           dict(slot=slot + 8, label='B', hours=3, complete=True, prices=['b'], intervals=[[0,10800]], events=events(19, 97, 34, 9))])
        self.assertEqual(assess(blocks, complete=False)['status'], 'WAITING_MORE_DATA')
        self.assertEqual(assess(blocks, complete=True)['winner'], 'B')
        blocks[1]['events'].append(dict(offset=500,gap_usd='0'))
        self.assertEqual(assess(blocks, complete=True)['status'], 'WAITING_MORE_DATA')
        blocks[1]['events'].pop()
        blocks[1]['events'].append(dict(offset=500,gap_usd='0.01'))
        self.assertEqual(assess(blocks, complete=True)['status'], 'WAITING_MORE_DATA')
        blocks[1]['events'][-1]['gap_usd']='50'
        self.assertEqual(assess(blocks, complete=True)['status'], 'WAITING_MORE_DATA')
        blocks[1]['complete'] = False
        self.assertEqual(assess(blocks, complete=True)['status'], 'WAITING_MORE_DATA')

    def test_opposing_pair_directions_do_not_choose_winner(self):
        def block(slot, label, gross):
            return dict(slot=slot,label=label,hours=3,complete=True,prices=[label],intervals=[[0,10800]],
                        events=[dict(offset=10+i,actual_net_usd='5',actual_contribution_usd=str(gross/20),new_customer=i<10,customer_key=str(i)) for i in range(20)])
        blocks=[block(0,'A',100),block(8,'B',50),block(1,'A',100),block(9,'B',180)]
        self.assertIsNone(assess(blocks,complete=True)['winner'])

    def test_financial_stop_does_not_require_customer_identity(self):
        def block(slot, label, gross):
            return dict(slot=slot,label=label,hours=3,complete=True,prices=[label],intervals=[[0,10800]],
                        events=[dict(offset=10+i,actual_net_usd='5',actual_contribution_usd=str(gross/20),new_customer=None,customer_key=None) for i in range(20)])
        result=assess([block(0,'A',100),block(8,'B',70),block(1,'A',100),block(9,'B',70)],complete=True)
        self.assertIn('B',result['excluded'])
        self.assertIsNone(result['winner'])

    def test_mature_loss_is_recorded_for_next_block(self):
        from pathlib import Path
        import tempfile
        from fc_pricing_v3.ledger import Ledger
        start=datetime(2026,11,5,tzinfo=timezone.utc)
        plan={'plan_id':'p','revision':1,'starts_at':start.isoformat(),'resources':['base:console']}
        labels=assignment(plan,start)['schedule']
        pairs=[i for i in range(8) if {labels[i],labels[i+8]}=={'A','B'}][:2]
        slots=sorted(pairs+[i+8 for i in pairs])
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'test.db')
            outcomes=[]
            for slot in slots:
                t=start+timedelta(hours=3*slot)
                info=assignment(plan,t)
                action={'base_prices':{'console':'10' if info['label']=='A' else '11'},'region_coefficients':{}}
                info.update(effective_key=info['label'],group_keys={'console':info['label']},
                            no_space_by_group={'console':False},merged_with_A_by_group={'console':info['label']=='A'})
                ident='w'+str(slot)
                db.put('operations',ident,dict(plan_id='p',status='COMPLETED',completed_at=t.isoformat(),resources=['base:console'],
                                               bundle={'action':action,'smart_assignment':info}))
                db.put('actual_price_windows',ident,dict(operation_id=ident,action=action))
                for i in range(20):
                    outcomes.append(dict(occurred_at=(t+timedelta(minutes=i+1)).isoformat(),price_window_id=ident,group='console',
                        actual_net_usd='5',actual_contribution_usd='5' if info['label']=='A' else '3',new_customer=None))
            now=start+timedelta(hours=3*(slots[-1]+1))
            db.put('metadata','daily_online_context',dict(actual_outcomes=outcomes,learning_coverage=dict(query_complete=True,
                observed_at=now.isoformat(),gap_events=[],unscoped_time_gaps=False)))
            block=int((now-start).total_seconds()//10800)
            correction=early_correction(db,plan,now,block)
            self.assertEqual(correction['effective_blocks']['B'],block+1)

    def test_exposure_starts_only_when_operation_is_confirmed(self):
        start = datetime(2026, 11, 5, tzinfo=timezone.utc)
        plan = {'plan_id': 'p', 'revision': 1, 'starts_at': start.isoformat()}
        allocation = assignment(plan, start)
        action = {'base_prices': {'console': '10'}, 'region_coefficients': {}}
        op = {'plan_id': 'p', 'status': 'NO_CHANGE', 'completed_at': (start + timedelta(hours=1)).isoformat(),
              'bundle': {'action': action, 'smart_assignment': dict(allocation, effective_key='price-1')}}
        outcomes = [{'occurred_at': (start + timedelta(minutes=30)).isoformat(), 'price_window_id': 'w', 'group': 'console', 'actual_net_usd': '10', 'actual_contribution_usd': '2', 'new_customer': False, 'customer_key': 'a'},
                    {'occurred_at': (start + timedelta(hours=2)).isoformat(), 'price_window_id': 'w', 'group': 'console', 'actual_net_usd': '10', 'actual_contribution_usd': '2', 'new_customer': True, 'customer_key': 'b'}]
        blocks = observed_blocks(plan, [op], outcomes, [{'operation_id': 'w', 'action': action}], start + timedelta(hours=3), epoch=0)
        self.assertEqual(blocks[0]['hours'], '2.0')
        self.assertEqual(blocks[0]['orders'], 1)
        self.assertEqual(blocks[0]['new_customers'], 1)

    def test_old_gap_does_not_block_current_epoch_but_current_gap_does(self):
        start=datetime(2026,11,5,tzinfo=timezone.utc)
        plan={'plan_id':'p','revision':1,'starts_at':start.isoformat()}
        row={'slot':0,'complete':True,'intervals':[[0,10800]]}
        coverage={'gap_events':[{'group':'console','occurred_at':(start-timedelta(hours=1)).isoformat()}]}
        scope_gaps(plan,[row],'console',0,coverage)
        self.assertTrue(row['complete'])
        coverage['gap_events'].append({'group':'console','occurred_at':(start+timedelta(hours=1)).isoformat()})
        scope_gaps(plan,[row],'console',0,coverage)
        self.assertFalse(row['complete'])


if __name__ == '__main__':
    unittest.main()
