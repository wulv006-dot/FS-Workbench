"""Contract checks for read-only MMOEXP 100K monitoring."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
with patch.dict(sys.modules, {'sports_outbound': SimpleNamespace(fetch=lambda *a, **k: None)}):
    import storefront_monitor as monitor


PAGE = ("<h1>Buy FC 27 Coins</h1><div id='container' data-cid='9623'></div>"
        "<li data-code='ps' data-id='21587' data-gid='1327' data-sign='$'></li>"
        "<li data-code='xbox' data-id='21585' data-gid='1327' data-sign='$'></li>"
        "<li data-code='pc' data-id='21589' data-gid='1327' data-sign='$'></li>"
        "<script>const site_id = `266`;</script>")


def response(price):
    return json.dumps({"goods": {"index": {"list": [{"id": 101, "unit": "K",
        "goods_list": {"a": {"num": 100, "price_discount": price, "give": 0}}}]}}})


def public_display_response():
    # Real anonymous USD FC27 response, 2026-11-09; only public product fields.
    return {'goods': {'index': {'list': [{'id': 163329311, 'unit': 'K', 'site_id': 266,
        'gid': 1327, 'cid': 9623, 'aid': 21587, 'unit_price': '0.08490000',
        'goods_list': {'100': {'num': 100, 'price': 8.49, 'price_discount': 8.49,
            'price_discount_format': '7.22', 'give': 5, 'display_promo_title': 'New User Exclusive',
            'display_discount_off': 15, 'display_coupon_off': 15, 'max_reduce': 50}}}]}}}


class StorefrontMonitorTest(unittest.TestCase):
    def test_real_display_keeps_raw_price_and_received_quantity(self):
        result = monitor.offer_from_response(public_display_response())
        self.assertEqual(result['package_usd'], '8.49')
        self.assertEqual(result['usd_per_k'], '0.080857')
        self.assertEqual(result['bonus_k'], '5')
        self.assertEqual(result['display_package_usd'], '7.22')
        self.assertEqual(result['display_price_format'], '7.22')
        self.assertEqual(result['display_status'], 'verified')
        self.assertEqual(result['display_metadata'], dict(basis='anonymous_public_display', currency='USD',
            site_id=266, gid=1327, cid=9623, title='New User Exclusive', coupon_off_pct='15',
            discount_off_pct='15', max_reduce_usd='50'))
        self.assertRegex(result['display_regime_key'], r'^[a-f0-9]{64}$')

    def test_old_response_retains_raw_display_without_claiming_known_terms(self):
        result = monitor.offer_from_response(json.loads(response('13.25')))
        self.assertEqual(result['package_usd'], '13.25')
        self.assertEqual(result['display_package_usd'], '13.25')
        self.assertEqual(result['display_status'], 'legacy')
        self.assertIsNone(result['display_regime_key'])

    def test_standard_tier_uses_backend_display_even_when_cap_changes_effective_rate(self):
        payload = public_display_response();tier = payload['goods']['index']['list'][0]['goods_list']['100']
        tier.update(price_discount=400, price_discount_format='350.00')
        result = monitor.offer_from_response(payload)
        self.assertEqual(result['display_package_usd'], '350.00')
        self.assertEqual(result['display_price_format'], '350.00')
        self.assertEqual(result['display_metadata']['max_reduce_usd'], '50')
        self.assertEqual(result['display_status'], 'verified')

    def test_display_amount_must_match_proven_percent_and_cap_formula(self):
        for shown in ('0.01', '7.20', '7.24'):
            with self.subTest(shown=shown):
                payload = public_display_response();payload['goods']['index']['list'][0]['goods_list']['100']['price_discount_format'] = shown
                result = monitor.offer_from_response(payload)
                self.assertEqual(result['package_usd'], '8.49')
                self.assertEqual(result['display_status'], 'invalid')
                self.assertIsNone(result['display_package_usd'])
                self.assertIsNone(result['display_regime_key'])
        payload = public_display_response();payload['goods']['index']['list'][0]['goods_list']['100']['display_discount_off'] = 30
        self.assertEqual(monitor.offer_from_response(payload)['display_package_usd'], '7.22')

    def test_unproven_coupon_zero_reduction_is_unknown_and_plain_raw_price_is_verified(self):
        payload = public_display_response();tier = payload['goods']['index']['list'][0]['goods_list']['100']
        tier['display_coupon_off'] = 0
        self.assertEqual(monitor.offer_from_response(payload)['display_status'], 'unknown')
        self.assertIsNone(monitor.offer_from_response(payload)['display_regime_key'])
        tier['price_discount_format'] = '8.49'
        self.assertEqual(monitor.offer_from_response(payload)['display_status'], 'verified')
        tier.pop('display_coupon_off')
        self.assertEqual(monitor.offer_from_response(payload)['display_status'], 'unknown')

    def test_display_failures_do_not_discard_valid_base_price(self):
        mutations = [('display_coupon_off', True), ('display_coupon_off', 101),
            ('display_coupon_off', -1), ('display_discount_off', float('nan')),
            ('max_reduce', -1), ('max_reduce', 'Infinity'), ('max_reduce', '1e999999999'),
            ('price_discount_format', '7.22 USD'),
            ('price_discount_format', {'unexpected': 'object'}), ('price_discount_format', '8.51'),
            ('display_promo_title', '<script>bad</script>'), ('display_promo_title', 'bad\nheader')]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                payload = public_display_response();payload['goods']['index']['list'][0]['goods_list']['100'][key] = value
                result = monitor.offer_from_response(payload)
                self.assertEqual(result['package_usd'], '8.49')
                self.assertEqual(result['display_status'], 'invalid')
                self.assertIsNone(result['display_package_usd'])
                self.assertIsNone(result['display_regime_key'])

    def test_display_identity_requires_actual_public_product_scope(self):
        for key, value in [('site_id', 267), ('gid', 1326), ('cid', 9624)]:
            with self.subTest(key=key):
                payload = public_display_response();payload['goods']['index']['list'][0][key] = value
                result = monitor.offer_from_response(payload)
                self.assertEqual(result['package_usd'], '8.49')
                self.assertEqual(result['display_status'], 'invalid')
                self.assertIsNone(result['display_regime_key'])

    def test_incomplete_new_display_is_unknown_not_legacy_or_base_failure(self):
        payload = public_display_response();payload['goods']['index']['list'][0]['goods_list']['100'].pop('max_reduce')
        result = monitor.offer_from_response(payload)
        self.assertEqual(result['package_usd'], '8.49')
        self.assertEqual(result['display_status'], 'unknown')
        self.assertIsNone(result['display_package_usd'])
        self.assertIsNone(result['display_regime_key'])

    def test_display_regime_tracks_terms_not_prices_or_capture_time(self):
        first = monitor.offer_from_response(public_display_response())
        payload = public_display_response();tier = payload['goods']['index']['list'][0]['goods_list']['100']
        tier.update(price_discount=10, price_discount_format='8.50', display_coupon_off='15.0', max_reduce='50.00')
        second = monitor.offer_from_response(payload)
        self.assertEqual(first['display_regime_key'], second['display_regime_key'])
        for key, value in [('max_reduce', 40), ('display_promo_title', 'Another public offer'), ('display_coupon_off', 10)]:
            changed = public_display_response();changed['goods']['index']['list'][0]['goods_list']['100'][key] = value
            if key == 'display_coupon_off':
                changed['goods']['index']['list'][0]['goods_list']['100']['price_discount_format'] = '7.64'
            current = monitor.offer_from_response(changed)
            self.assertEqual(current['display_status'], 'verified')
            self.assertNotEqual(first['display_regime_key'], current['display_regime_key'])

    def test_collection_stamps_verified_display_but_keeps_invalid_display_base_available(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(monitor, 'STATE_FILE', Path(directory)/'state.json'):
            payload = public_display_response()
            def fetch(url, form=None, limit=2000000, cookie_jar=None):
                return PAGE if form is None else json.dumps(payload)
            with patch.object(monitor, 'fetch', side_effect=fetch):
                result = monitor.collect('display-contract')
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(json.loads(monitor.STATE_FILE.read_text()), result)
            for row in result['rows'].values():
                self.assertEqual(row['display_observed_at'], row['checked_at'])
            payload['goods']['index']['list'][0]['goods_list']['100']['price_discount_format'] = 'bad'
            with patch.object(monitor, 'fetch', side_effect=fetch):
                result = monitor.collect('display-invalid')
            self.assertEqual(result['status'], 'ok')
            for row in result['rows'].values():
                self.assertEqual(row['display_status'], 'invalid')
                self.assertIsNone(row['display_observed_at'])
                self.assertEqual(row['package_usd'], '8.49')

    def test_page_mapping_accepts_json_encoded_public_html(self):
        expected = monitor.page_mapping(PAGE)
        self.assertEqual(monitor.page_mapping(json.dumps(PAGE)), expected)

    def test_page_mapping_rejects_invalid_encoded_html(self):
        with self.assertRaisesRegex(ValueError, "product_page_invalid"):
            monitor.page_mapping('"broken\\q"')

    def test_page_mapping_rejects_missing_platform(self):
        with self.assertRaisesRegex(ValueError, "product_mapping_changed"):
            monitor.page_mapping(PAGE.replace("data-code='pc'", "data-code='other'"))

    def test_effective_price_uses_received_quantity(self):
        payload = json.loads(response("13.25"))
        payload["goods"]["index"]["list"][0]["goods_list"]["a"]["give"] = 5
        self.assertEqual(monitor.offer_from_response(payload)["usd_per_k"], "0.126190")

    def test_public_requests_reuse_one_temporary_session_and_bypass_local_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            jar = Path(directory) / "cookies.txt"
            result = SimpleNamespace(returncode=0, stdout=b"ok")
            with patch.object(monitor.subprocess, "run", return_value=result) as run:
                monitor.fetch(monitor.PAGE_URL, cookie_jar=jar)
                first = run.call_args.args[0]
                self.assertIn("--cookie-jar", first)
                self.assertNotIn("--cookie", first)
                self.assertIn("Cache-Control: no-cache", first)
                jar.touch()
                monitor.fetch(monitor.GOODS_URL, form={"aid": "123"}, cookie_jar=jar)
                second = run.call_args.args[0]
                self.assertEqual(second[second.index("--cookie") + 1], str(jar))

    def test_failed_refresh_keeps_last_value_but_marks_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "storefront.json"
            with patch.object(monitor, "STATE_FILE", state):
                def first(url, form=None, limit=2000000, cookie_jar=None):
                    self.assertIsNotNone(cookie_jar)
                    return PAGE if form is None else response("13.25")
                with patch.object(monitor, "fetch", side_effect=first):
                    complete = monitor.collect("test-run")
                self.assertEqual(complete["status"], "ok")
                self.assertEqual(complete["collection_run_id"], "test-run")
                old = complete["rows"]["PS"]["checked_at"]
                with patch.object(monitor, "fetch", side_effect=ValueError("unavailable")):
                    failed = monitor.collect()
                self.assertEqual(failed["status"], "unavailable")
                self.assertEqual(failed["rows"]["PS"]["checked_at"], old)
                self.assertEqual(failed["rows"]["PS"]["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
