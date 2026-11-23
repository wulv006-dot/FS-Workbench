from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from collection_cases import NOW, context, identity, policy
from fc_collection.contracts import build_job, validate_observation, to_fc_quote_rows
from fc_collection.coordinator import Coordinator
from fc_collection.worker import Worker


def trigger():
    return [dict(stage='cdp_connecting'), dict(stage='failed', reason='browser_connection_timeout')]


def snapshot(platform='PS', coupon='none'):
    return dict(selected=[dict(PS='PS4/5', XBOX='Xbox', PC='PC')[platform]], loggedIn=False,
                currencyState='ready', tierState='ready', baseK=100, priceState='ready',
                usdPrice='10.00', giftState='ready', bonusK='5', couponState=coupon,
                observedCouponPrice='9.00' if coupon == 'excluded' else None,
                excludedCouponDiscount='1.00' if coupon == 'excluded' else None, stable_reads=3, observed_at=NOW.isoformat())


class LootbarContract(unittest.TestCase):
    def test_primary_guard_honors_only_live_source_limits_not_expired_unknown_read(self):
        from fc_collection import lootbar, client
        from fc_collection.lootbar import VERSION, REQUEST_BUDGET
        with tempfile.TemporaryDirectory() as folder, patch.object(client,'utc',return_value=NOW):
            database=Path(folder)/'collection.sqlite3'
            with patch.object(client,'DATABASE',database):
                self.assertTrue(lootbar.primary_ready())
                c=Coordinator(database)
                self.assertTrue(lootbar.primary_ready())
                c.configure_source('Lootbar',dict(policy(),origin='https://www.lootbar.com',nodes=['183'],stable_seconds=0,
                    max_requests=REQUEST_BUDGET,adapter_version=VERSION,request_timeout_seconds=90))
                c.register_node(identity(),['Lootbar'],NOW)
                task=build_job(dict(run_id='original-run',created_at=NOW.isoformat()),'Lootbar',
                    dict(context(),adapter_version=VERSION,total_attempt_limit=1,total_request_budget=REQUEST_BUDGET),
                    (NOW+timedelta(seconds=100)).isoformat())
                c.enqueue(task);leased=c.claim_job(identity(),['Lootbar'],NOW)
                c.reserve_request(identity(),task['job_id'],leased['lease_epoch'],dict(count=128),NOW)
                self.assertFalse(lootbar.primary_ready())
                with patch.object(client,'utc',return_value=NOW+timedelta(seconds=121)):
                    self.assertTrue(lootbar.primary_ready())
                with c.transaction() as db:
                    source=c._get(db,'collection_sources','Lootbar');source['blocked']=True;c._put(db,'collection_sources','Lootbar',source)
                with patch.object(client,'utc',return_value=NOW+timedelta(seconds=121)):
                    self.assertFalse(lootbar.primary_ready())

    def test_empty_187_sku_then_pre_egress_cdp_failure_preserves_183_renderer_budget(self):
        from fc_collection import client, lootbar, package_routes

        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'collection.sqlite3'
            route = Path(folder) / 'lootbar-routing.json'
            route.write_text(json.dumps(dict(schema_version=1, remote_result_mode='consume', assignment_generation=1)))
            route.chmod(0o600)
            coordinator = Coordinator(database)
            coordinator.configure_source('Lootbar', lootbar.source_policy(1))
            with coordinator.package_requests('Lootbar', 'original-run', 3, NOW):
                pass
            current = [NOW + timedelta(seconds=8)]
            coordinator.register_node(identity(), ['Lootbar'], NOW)

            def advance(seconds):
                current[0] += timedelta(seconds=seconds)

            def reserve_renderer(parent, routing, trigger_hash):
                self.assertEqual(parent['run_id'], 'original-run')
                self.assertEqual(parent['created_at'], NOW.isoformat())
                task = build_job(parent, 'Lootbar', dict(context(), adapter_version=lootbar.VERSION,
                                 policy_version=lootbar.source_policy(1)['policy_version'],
                                 total_attempt_limit=1, total_request_budget=128), parent['deadline_at'])
                coordinator.enqueue(task)
                lease = coordinator.claim_job(identity(), ['Lootbar'], current[0])
                return coordinator.reserve_request(identity(), task['job_id'], lease['lease_epoch'],
                                                   dict(count=128), current[0])

            with patch.object(client, 'DATABASE', database), patch.object(lootbar, 'ROUTING', route), \
                    patch.object(lootbar, 'datetime') as dt, patch('time.sleep', side_effect=advance) as sleep, \
                    patch.object(lootbar, 'collect_remote', side_effect=reserve_renderer):
                dt.now.side_effect = lambda _: current[0]
                trace = Path(folder) / 'cdp-trace.jsonl'
                trace.write_text('\n'.join(json.dumps(event) for event in trigger()))
                with patch.object(client, 'utc', side_effect=lambda: current[0]):
                    package_routes.wait_for_lootbar_renderer('original-run', trace)
                permit = lootbar.after_primary_failure('original-run', trigger(), NOW)
            sleep.assert_called_once_with(52)
            self.assertEqual(permit['count'], 128)
            self.assertEqual(current[0], NOW + timedelta(seconds=60))

    def test_same_original_trace_reuses_job_and_ACK_without_SSH_or_new_clock(self):
        from fc_collection import lootbar, client
        from fc_collection.lootbar import VERSION, REQUEST_BUDGET, lootbar_adapter
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);database=base/'collection.sqlite3';route=base/'lootbar-routing.json'
            route.write_text(json.dumps(dict(schema_version=1,remote_result_mode='consume',assignment_generation=1)))
            route.chmod(0o600)
            c=Coordinator(database)
            c.configure_source('Lootbar',dict(policy(),origin='https://www.lootbar.com',nodes=['183'],stable_seconds=0,
                max_requests=REQUEST_BUDGET,adapter_version=VERSION,request_timeout_seconds=90))
            parent=dict(run_id='original-run',created_at=NOW.isoformat(),deadline_at=(NOW+timedelta(seconds=110)).isoformat())
            task=build_job(parent,'Lootbar',dict(context(),adapter_version=VERSION,total_attempt_limit=1,total_request_budget=REQUEST_BUDGET),parent['deadline_at'])
            c.enqueue(task);c.register_node(identity(),['Lootbar'],NOW)
            Worker(c,identity(),{'Lootbar':lootbar_adapter},base/'spool',
                lambda *_:json.dumps(dict(snapshots={p:snapshot(p) for p in ['PS','XBOX','PC']},platform_errors={},browser_requests_allowed=12)).encode(),clock=lambda:NOW).run_once()
            events=trigger();events[0]['at']=NOW.isoformat();events[-1]['at']=(NOW+timedelta(seconds=8)).isoformat()
            with patch.object(lootbar,'ROUTING',route),patch.object(client,'DATABASE',database), \
                    patch.object(client,'Session',side_effect=AssertionError('original ACK, no remote read')), \
                    patch.object(lootbar,'datetime') as dt,patch.object(client,'utc',return_value=NOW+timedelta(seconds=20)):
                dt.now.return_value=NOW+timedelta(seconds=20)
                result=lootbar.after_primary_failure('original-run',events,NOW+timedelta(seconds=20))
                dt.now.return_value=NOW+timedelta(seconds=30)
                replay=lootbar.after_primary_failure('original-run',events,NOW+timedelta(seconds=30))
            self.assertEqual(result,replay)
            self.assertEqual([r['captured_at'] for r in replay['offers']],[NOW.isoformat()]*3)
            with c.transaction() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM collection_jobs').fetchone()[0],1)
                saved=c._get(db,'collection_jobs',task['job_id'])
                self.assertEqual(saved['deadline_at'],parent['deadline_at'])
                self.assertEqual(saved['request_budget_reserved'],REQUEST_BUDGET)

    def test_reserved_budget_is_not_reported_as_observed_browser_requests(self):
        from fc_collection.lootbar import lootbar_adapter, REQUEST_BUDGET
        transport=Mock();transport.used=REQUEST_BUDGET;transport.clock.return_value=NOW
        transport.get.return_value=json.dumps(dict(snapshots={'PS':snapshot()},platform_errors={},browser_requests_allowed=7)).encode()
        result=lootbar_adapter(dict(region_scope=[0],total_request_budget=REQUEST_BUDGET,requested_platforms=['PS']),transport)
        self.assertEqual(result['request_accounting'],dict(basis='reserved_browser_group',charged=128,browser_requests_allowed=7))

    def test_187_mixed_none_and_excluded_are_the_same_no_coupon_basis(self):
        from datetime import datetime, timezone
        from snapshot_layer import lootbar_snapshots
        stamp=datetime.now(timezone.utc).isoformat()
        offers={p:dict(platform=p,base_k='100',bonus_k='5',usd_price='10.00',coupon_excluded=False,
                       price_basis='当前无券商品价') for p in ['PS','XBOX','PC']}
        offers['XBOX'].update(coupon_excluded=True, price_basis='券前原价（已排除账号新客券）',
            observed_coupon_price='8.00',excluded_coupon_discount='2.00',
            reconstruction=dict(method='derived_actual_discount',exact=True,precision='USD_cent',paid_usd='8.00',discount_usd='2.00'))
        events=[dict(stage='ps_restored'),dict(stage='complete',read_only=True,checked_at=stamp,offers=offers)]
        rows=lootbar_snapshots('original-run',events)
        self.assertEqual(len(rows),3)
        self.assertTrue(all(r['coupon_excluded'] for r in rows))
        self.assertEqual([r['raw_coupon_excluded'] for r in rows],[False,True,False])
        offers['XBOX']['excluded_coupon_discount']='1.00'
        with self.assertRaises(ValueError):lootbar_snapshots('original-run',events)

    def test_conflicting_original_is_never_bypassed_by_amount_or_percentage(self):
        from fc_collection.lootbar import reconstruct_price
        for state in ['relation_mismatch','original_multiple','original_format','discount_multiple']:
            with self.subTest(state=state), self.assertRaises(ValueError):
                reconstruct_price(dict(snapshot(),couponState=state,couponEvidence=dict(paid_usd='8.00',actual_discount_usd='1.00',actual_discount_verified=True)))

    def test_visible_actual_coupon_amount_reconstructs_without_strike_or_guessed_percentage(self):
        from fc_collection.lootbar import reconstruct_price
        raw = dict(snapshot(), couponState='original_missing',
            couponEvidence=dict(paid_usd='8.00', actual_discount_usd='2.00', actual_discount_verified=True))
        amount, proof = reconstruct_price(raw)
        self.assertEqual(amount, Decimal('10.00'))
        self.assertEqual(proof['method'], 'derived_actual_discount')
        raw['couponEvidence']['actual_discount_verified'] = False
        with self.assertRaises(ValueError):
            reconstruct_price(raw)

    def test_actual_observation_time_is_preserved_and_expired_capture_is_rejected(self):
        from fc_collection.lootbar import snapshot_offer
        raw = snapshot()
        self.assertEqual(snapshot_offer(raw, 'PS', NOW+timedelta(seconds=70))['observed_at'], NOW.isoformat())
        with self.assertRaises(ValueError):
            snapshot_offer(raw, 'PS', NOW+timedelta(seconds=901))

    def test_percentage_coupon_inverse_honors_cap_and_half_up_cent(self):
        from fc_collection.lootbar import reconstruct_price
        terms = dict(paid_usd='8.00', percent_off='20', cap_usd=None,
            cap_verified=True, minimum_spend_usd='0', eligibility_verified=True, rounding='half_up_cent')
        amount, proof = reconstruct_price(dict(snapshot(), couponState='original_missing', couponEvidence=terms))
        self.assertEqual(amount, Decimal('10.00'))
        self.assertEqual(proof['method'], 'derived_percent')
        terms.update(paid_usd='15.00', cap_usd='1.00')
        amount, proof = reconstruct_price(dict(snapshot(), couponState='original_missing', couponEvidence=terms))
        self.assertEqual(amount, Decimal('16.00'))
        self.assertEqual(proof['cap_applied'], True)

    def test_inverse_cent_multiple_solutions_keeps_interval_and_uses_lower_bound(self):
        from fc_collection.lootbar import reconstruct_price
        terms = dict(paid_usd='0.01', percent_off='50', cap_usd=None,
            cap_verified=True, minimum_spend_usd='0', eligibility_verified=True, rounding='half_up_cent')
        amount, proof = reconstruct_price(dict(snapshot(), couponState='original_missing', couponEvidence=terms))
        self.assertEqual(amount, Decimal('0.02'))
        self.assertEqual(proof['gross_interval_usd'], ['0.02','0.03'])
        self.assertFalse(proof['exact'])

    def test_direct_strike_preferred_and_missing_coupon_conditions_never_guessed(self):
        from fc_collection.lootbar import reconstruct_price
        terms = dict(paid_usd='8.00', original_usd='10.00')
        amount, proof = reconstruct_price(dict(snapshot(), couponState='discount_missing', couponEvidence=terms))
        self.assertEqual(amount, Decimal('10.00'))
        self.assertEqual(proof['method'], 'direct_strike')
        full = dict(paid_usd='8.00', percent_off='20', cap_usd=None,
            cap_verified=True, minimum_spend_usd='0', eligibility_verified=True, rounding='half_up_cent')
        for field in full:
            bad = dict(full); bad.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                reconstruct_price(dict(snapshot(), couponState='original_missing', couponEvidence=bad))

    def test_only_original_attach_failure_before_egress_is_eligible(self):
        from fc_collection.lootbar import eligible_trigger
        self.assertTrue(eligible_trigger(trigger()))
        for events in [[], trigger()[:1], trigger() + [dict(stage='cdp_connected')],
                       [dict(stage='failed', reason='browser_connection_timeout')],
                       trigger() + [dict(stage='platform_collected', platform='PS')]]:
            with self.subTest(events=events):
                self.assertFalse(eligible_trigger(events))
        for reason in ['http_403', 'http_429', 'challenge', 'captcha', 'product_page_refresh_timeout',
                       'platform_timeout:XBOX', 'browser_connection_timeout:unknown']:
            self.assertFalse(eligible_trigger([dict(stage='cdp_connecting'), dict(stage='failed', reason=reason)]))

    def test_public_no_coupon_and_excluded_coupon_keep_raw_auth_and_financial_proof(self):
        from fc_collection.lootbar import snapshot_offer
        for coupon in ['none', 'excluded']:
            raw = snapshot(coupon=coupon)
            row = snapshot_offer(raw, 'PS', NOW)
            self.assertTrue(row['coupon_excluded'])
            self.assertEqual(row['auth_state'], 'public')
            self.assertEqual(row['source_metadata']['coupon_state'], coupon)
            self.assertEqual(row['source_metadata']['raw_coupon_excluded'], coupon == 'excluded')
            self.assertEqual((row['purchase_quantity'], row['bonus_quantity'], row['delivered_quantity']), ('100', '5', '105'))
            raw['loggedIn'] = True
            self.assertEqual(snapshot_offer(raw, 'PS', NOW)['auth_state'], 'logged_in')

    def test_bad_currency_platform_coupon_amount_gift_are_rejected(self):
        from fc_collection.lootbar import snapshot_offer
        for update in [dict(currencyState='currency'), dict(selected=['Xbox']), dict(bonusK=None),
                       dict(couponState='unknown'), dict(loggedIn=None), dict(baseK=105),
                       dict(couponState='excluded', observedCouponPrice='8.99', excludedCouponDiscount='1.00')]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                snapshot_offer(dict(snapshot(), **update), 'PS', NOW)

    def test_original_coordinator_seals_partial_and_does_not_retry_other_exit(self):
        from fc_collection.lootbar import VERSION, REQUEST_BUDGET, lootbar_adapter
        with tempfile.TemporaryDirectory() as folder:
            c = Coordinator(Path(folder) / 'collection.sqlite3')
            c.configure_source('Lootbar', dict(policy(), origin='https://www.lootbar.com',
                nodes=['183'], stable_seconds=0, max_requests=REQUEST_BUDGET,
                adapter_version=VERSION, request_timeout_seconds=90))
            principal = identity()
            c.register_node(principal, ['Lootbar'], NOW)
            task = build_job(dict(run_id='original-run', created_at=NOW.isoformat()), 'Lootbar',
                dict(context(), requested_platforms=['PS','XBOX','PC'], region_scope=[0],
                    adapter_version=VERSION, total_request_budget=REQUEST_BUDGET, total_attempt_limit=1),
                (NOW + timedelta(seconds=100)).isoformat())
            c.enqueue(task)
            fetch = Mock(return_value=json.dumps(dict(snapshots={'PS':snapshot()},
                platform_errors={'XBOX':'http_403','PC':'http_403'})).encode())
            receipt = Worker(c, principal, {'Lootbar':lootbar_adapter}, Path(folder)/'spool', fetch,
                             clock=lambda:NOW).run_once()
            self.assertEqual(receipt['status'], 'accepted')
            accepted = c.accepted(task['job_id'], NOW)
            self.assertEqual(accepted[0]['status'], 'partial')
            result = to_fc_quote_rows(accepted, c._get_job_for_test(task['job_id']) if hasattr(c, '_get_job_for_test') else dict(task, **{k:accepted[0][k] for k in ('node_id','node_boot_id','attempt_id','lease_epoch')}), NOW)
            self.assertEqual([r['platform'] for r in result['offers']], ['PS'])
            self.assertEqual(result['offers'][0]['gross_usd'], '10.00')
            self.assertEqual(fetch.call_count, 1)
            with c.transaction() as db:
                self.assertTrue(c._get(db, 'collection_sources', 'Lootbar')['blocked'])
                self.assertEqual(c._get(db, 'collection_jobs', task['job_id'])['request_budget_reserved'], REQUEST_BUDGET)
                self.assertEqual(db.execute('SELECT state FROM collection_jobs').fetchone()[0], 'COMPLETED')

    def test_request_group_is_reserved_before_browser_and_never_refunded(self):
        from fc_collection.lootbar import REQUEST_BUDGET
        from fc_collection.worker import BudgetedTransport
        endpoint = Mock()
        task = dict(source_id='Lootbar',job_id='job',attempt_id='a',lease_epoch=1,
                    deadline_at=(NOW+timedelta(seconds=100)).isoformat())
        endpoint.renew_lease.return_value = dict(task,lease_expires_at=(NOW+timedelta(seconds=100)).isoformat())
        endpoint.reserve_request.return_value = dict(permit_id='permit',clock_margin_seconds=0,
                    issued_at=NOW.isoformat(),expires_at=(NOW+timedelta(seconds=90)).isoformat())
        fetch = Mock(return_value=b'{}')
        transport = BudgetedTransport(endpoint, identity(), task, fetch, lambda:NOW)
        transport.get('lootbar_capture', count=REQUEST_BUDGET)
        self.assertEqual(endpoint.reserve_request.call_args.args[3], dict(count=REQUEST_BUDGET))
        self.assertEqual(transport.used, REQUEST_BUDGET)
        self.assertEqual(endpoint.complete_request.call_count, 1)

    def test_browser_route_gate_blocks_writes_hosts_budget_and_after_site_denial(self):
        from fc_collection.lootbar_browser import RequestGate
        gate = RequestGate(2)
        self.assertTrue(gate.allow('https://www.lootbar.com/game-coins/fc27', 'GET'))
        self.assertFalse(gate.allow('https://www.lootbar.com/order/create', 'POST'))
        self.assertFalse(gate.allow('https://evil.invalid/', 'GET'))
        self.assertTrue(gate.allow('https://www.lootbar.com/static/app.js', 'GET'))
        self.assertFalse(gate.allow('https://www.lootbar.com/static/extra.js', 'GET'))
        self.assertEqual(gate.used, 2)
        gate = RequestGate(20)
        gate.response(401,critical=False)
        gate.response(403,critical=False)
        self.assertTrue(gate.allow('https://www.lootbar.com/game-coins/fc27','GET'))
        gate.response(403)
        self.assertFalse(gate.allow('https://www.lootbar.com/game-coins/fc27', 'GET'))
        self.assertEqual(gate.reason, 'http_403')

    def test_no_route_file_keeps_primary_and_invalid_primary_trace_never_calls_remote(self):
        from fc_collection import lootbar
        with tempfile.TemporaryDirectory() as folder, patch.object(lootbar, 'ROUTING', Path(folder)/'absent'), \
                patch.object(lootbar, 'collect_remote', side_effect=AssertionError('no remote')):
            self.assertIsNone(lootbar.after_primary_failure('original-run', trigger(), NOW))
            self.assertIsNone(lootbar.after_primary_failure('original-run', [dict(stage='failed', reason='http_403')], NOW))


if __name__ == '__main__':
    unittest.main()
