"""Observed guest checkout shapes, version-bound consumption and candidate arithmetic."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from fc_pricing_v3 import native_checkout_evidence as native
from fc_pricing_v3.native_checkout_evidence import (build_anonymous_observation,
    collect_anonymous_observations, project_anonymous_fixed_tiers)
from fc_pricing_v3.price_curve import (EDITOR_ASSET_SHA256, EDITOR_HANDLER_SHA256, IDENTITY_FIELDS,
    compile_curve, curve_key, read_curve)


NOW = datetime(2026, 11, 13, 8, 36, tzinfo=timezone.utc)
RUN = '00000000-0000-4000-8000-000000000061'
EDITOR = dict(editor_asset_sha256=EDITOR_ASSET_SHA256, editor_handler_sha256=EDITOR_HANDLER_SHA256)


def packed(value):
    return json.dumps(value).encode()


def saved(goods=163329311, site=266):
    row = dict(id=goods, site_id=site, aid=21587, mid=41217957, gid=1327, cid=9623, unit='K', status=1,
               unit_price='0.0816', more=dict(gold=[100, 1000], give=[0, 30],
                                             discount=[100, 100], price=['8.16', '81.60']))
    return read_curve(row, {key: row[key] for key in IDENTITY_FIELDS}, dict(source='fixed fixture'))


def observation_data():
    product = saved()['native_payload']
    goods = {field:product[field] for field in ('id','site_id','aid','mid','gid','cid','unit','unit_price')}
    goods.update(_region_factor=1, goods_list={'100':dict(num=100,full_price_format='8.16')})
    rows = {f'GOLD_163329311_{qty}':dict(group=qty, num=1, free_num=gift, id='163329311', aid=21587, gid=1327,
             goods_cid=9623, top_cid=1, unit='K', coin='new_gold', amount_format=amount,
             discount_amount_format=amount, off_amount_format='0.00')
            for qty,gift,amount in [(100,0,'8.16'),(1001,30,'81.68')]}
    def payload(group):
        details = dict(new_gold=rows) if group == 'detach' else {'1327': [
            dict(value,cart_key=key) for key,value in rows.items()]}
        return dict(code=1,time=int(NOW.timestamp()),data={'cart':{group:dict(total=2,item_total=2,
                   amount_format='89.84',details=details,has_removed=False,removed_items=[])}})
    html = '''<div class="lang-currency">US | USD</div>
      <li data-cart-category="new_gold" :class="'cart_key_' + 'new_gold' + 'GOLD_163329311_100'">
        <input class="item-num" value="1">
      </li>
      <li data-cart-category="new_gold" :class="'cart_key_' + 'new_gold' + 'GOLD_163329311_1001'">
        <input class="item-num" value="1">
      </li>
      <span class="amount-price" data-compute-price="$ 89.84"></span>
      <span class="amount-price gree-price" data-coupon-id="0" data-coupon-price="0" data-discount-price="0"
         data-count-coupon-price="89.84" data-count-discount-price="89.84"></span>
      <span class="total-price" data-compute-price="$ 92.75"></span>'''
    return dict(goods_raw=packed(dict(goods=dict(index=dict(list=[goods])))), detach_raw=packed(payload('detach')),
                cart_show_raw=packed(payload('cartshow')), cart_html_raw=html.encode())


class CheckoutEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.current = saved()
        self.raw = observation_data()

    def build(self):
        return build_anonymous_observation(RUN, 'PS', self.current, captured_at=NOW, **self.raw)

    def test_native_subtotal_excludes_buyer_fee_and_keeps_custom_sample_observed(self):
        result = self.build()
        first, second = result['lines']
        self.assertEqual(result['coverage_status'], 'partial')
        self.assertEqual((first['proof_status'], first['promised_delivered_k'], first['net_receipt_usd']),
                         ('verified', '100', '8.16'))
        self.assertEqual((second['proof_status'], second['promised_delivered_k'], second['net_receipt_usd']),
                         ('observed', '1031', '81.68'))
        self.assertEqual((first['quote_basis'], first['site_id'], first['currency']), ('observed_native_cart', '266', 'USD'))

    def test_checkout_coupon_currency_and_line_amount_conflicts_fail(self):
        for old,new in [(b'data-coupon-id="0"',b'data-coupon-id="9"'), (b'US | USD',b'US | CAD'),
                        (b'$ 89.84',b'$ 92.75')]:
            with self.subTest(new=new):
                self.raw = observation_data()
                self.raw['cart_html_raw'] = self.raw['cart_html_raw'].replace(old,new)
                with self.assertRaisesRegex(ValueError, 'native_cart_checkout_path_unverified'):
                    self.build()

    def test_explicit_run_curve_time_and_scope_binding(self):
        observed = self.build()
        evidence = dict(run_id=RUN, checked_at=NOW.isoformat(),
                        native_checkout_observations=dict(run_id=RUN,platforms={'PS':observed}))
        def collect(value, as_of=NOW):
            return collect_anonymous_observations(value, {'PS':self.current}, {'PS':('100','1001')},as_of=as_of)
        self.assertEqual([row['purchase_k'] for row in collect(evidence)['PS']['lines']], ['100'])
        self.assertEqual(collect(evidence,NOW+timedelta(minutes=16)), {})
        self.assertEqual(collect(dict(evidence,run_id='another-run')), {})
        self.assertEqual(collect(dict(evidence,native_checkout_observations=None)), {})
        bad = deepcopy(evidence)
        bad['native_checkout_observations']['platforms']['PS']['curve_key'] = 'other'
        self.assertEqual(collect(bad), {})

    def test_unknown_add_reconciles_same_cart_without_replay_then_clears(self):
        class Guest:
            def __init__(self):
                self.events = []

            def confirm_empty(self):
                self.events.append('empty')

            def request(self, path, form=None):
                self.events.append(path)
                if path == native.CART_ADD:
                    raise TimeoutError('response lost')
                if path == native.CART_CLEAR:
                    raise TimeoutError('clear response lost')
                return b'{}'

        guest = Guest()
        with patch.object(native, '_GuestCart', return_value=guest):
            result = native._collect_platform(RUN, 'PS', self.current, ('100', '1000'))
        self.assertEqual((result['reason'], result['lines']), ('native_guest_cart_add_readback_unavailable', []))
        self.assertEqual(guest.events, ['/ajax/goods', 'empty', native.CART_ADD, native.CART_SHOW,
                                        native.CART_CLEAR, 'empty'])

    def test_cleanup_must_be_confirmed_and_failure_survives_collection(self):
        class Guest:
            checks = 0

            def confirm_empty(self):
                self.checks += 1
                if self.checks == 2:
                    raise ValueError('nonempty cart after clear')

            def request(self, path, form=None):
                return b'{}'

        with patch.object(native, '_GuestCart', return_value=Guest()):
            result = native._collect_platform(RUN, 'PS', self.current, ('100',))
        self.assertEqual((result['reason'],result['lines']), ('native_guest_cart_cleanup_unverified',[]))
        evidence = dict(run_id=RUN, checked_at=result['captured_at'],
                        native_checkout_observations=dict(run_id=RUN, platforms={'PS':result}))
        observations = collect_anonymous_observations(evidence, {'PS':self.current}, {'PS':('100',)},
                                                     as_of=native.instant(result['captured_at']))
        self.assertEqual(observations['PS']['coverage_gaps'], ['native_guest_cart_cleanup_unverified'])

    def test_live_collection_is_explicit_and_does_not_replay_frozen_attachment(self):
        evidence = dict(run_id=RUN, checked_at=NOW.isoformat())
        with patch.object(native, '_collect_live', return_value={}) as live:
            self.assertEqual(collect_anonymous_observations(evidence, {'PS':self.current}, {}, as_of=NOW), {})
            self.assertEqual(collect_anonymous_observations(
                dict(evidence, native_checkout_observations={'run_id':RUN, 'platforms':{}}),
                {'PS':self.current}, {}, as_of=NOW, live=True), {})
            live.assert_not_called()
            self.assertEqual(collect_anonymous_observations(
                evidence, {'PS':self.current}, {}, as_of=NOW, live=True), {})
            live.assert_called_once()

    def test_candidate_and_all_projection_bind_new_amount_without_reusing_observed_checkout(self):
        observed = self.build()
        proposed = compile_curve(self.current, dict(anchor_prices_usd={'100':'7.99'}),EDITOR)
        candidate = project_anonymous_fixed_tiers(self.current, proposed, observed)
        line, = candidate['lines']
        self.assertEqual((line['regular_usd'],line['net_goods_usd'],line['quote_basis'],line['curve_key']),
                         ('7.99','7.99','derived_candidate_fixed_tier',curve_key(proposed)))
        self.assertNotEqual(line['quote_ref'],observed['lines'][0]['quote_ref'])
        fallback = saved(163329309,0)
        payload = dict(fallback['native_payload'],unit_price=proposed['native_payload']['unit_price'],
                       more=proposed['native_payload']['more'])
        all_target = read_curve(payload,fallback['identity'],proposed['native_contract'])
        all_line, = project_anonymous_fixed_tiers(self.current, all_target, observed)['lines']
        self.assertEqual((all_line['site_id'],all_line['goods_id'],all_line['curve_key']),
                         ('266','163329311',curve_key(all_target)))
        all_target['native_payload']['more']['give'][0] = 5
        self.assertEqual(project_anonymous_fixed_tiers(self.current,all_target,observed), {})


if __name__ == '__main__':
    unittest.main()
