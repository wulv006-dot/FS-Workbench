"""Offline contract and sequencing tests for the read-only CDP prototype."""
from __future__ import annotations

import sys
import threading
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import lootbar_server_collector as collector


def snapshot(label: str, *, price: str = "15.99", bonus: str = "5",
             coupon: bool = False, **changes) -> dict:
    value = {
        "selected": [label], "loggedIn": True, "currencyState": "ready",
        "tierState": "ready", "baseK": 100, "priceState": "ready",
        "usdPrice": price, "giftState": "ready", "bonusK": bonus,
        "couponState": "none", "observedCouponPrice": None,
        "excludedCouponDiscount": None,
    }
    if coupon:
        value.update(usdPrice="15.99", couponState="excluded",
                     observedCouponPrice="15.04", excludedCouponDiscount="0.95")
    value.update(changes)
    return value


class FakeResponse:
    status = 200


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def click(self, **_kwargs):
        self.page.platform = {
            'a.icon-ps': 'PS', 'a.icon-xbox': 'XBOX', 'a.icon-pc': 'PC'
        }[self.selector]


class FakePage:
    def __init__(self, context, original=False):
        self.context = context
        self.url = collector.BASE_URL if original else "about:blank"
        self.closed = False
        self.is_original = original
        self.platform = "PS" if original else None

    def set_default_timeout(self, _timeout):
        pass

    def set_default_navigation_timeout(self, _timeout):
        pass

    def goto(self, url, **_kwargs):
        self.url = url
        query = urlsplit(url).query.lower()
        self.platform = "XBOX" if "platform=xbox" in query else "PC" if "platform=pc" in query else "PS"
        return FakeResponse()

    def close(self):
        self.closed = True
        if self in self.context.pages:
            self.context.pages.remove(self)

    def is_closed(self):
        return self.closed

    def locator(self, selector):
        return FakeLocator(self, selector)


class FakeContext:
    def __init__(self):
        self.original = FakePage(self, original=True)
        self.pages = [self.original]
        self.max_temporary_open = 0

    def set_default_timeout(self, _timeout):
        pass

    def set_default_navigation_timeout(self, _timeout):
        pass

    def new_page(self):
        page = FakePage(self)
        self.pages.append(page)
        open_temporary = sum(not p.is_original and not p.closed for p in self.pages)
        self.max_temporary_open = max(self.max_temporary_open, open_temporary)
        return page


class FakeBrowser:
    def __init__(self):
        self.contexts = [FakeContext()]
        self.close_called = False

    def close(self):
        self.close_called = True


class FakePlaywrightManager:
    def __init__(self, browser):
        self.browser = browser

    def __enter__(self):
        return types.SimpleNamespace(chromium=types.SimpleNamespace(
            connect_over_cdp=lambda *_args, **_kwargs: self.browser))

    def __exit__(self, *_args):
        return False


class ServerCollectorTests(unittest.TestCase):
    def test_navigation_context_change_resets_stability_and_is_bounded(self):
        Error = type('Error', (Exception,), {'__module__': 'playwright._impl._errors'})
        failure = Error('Page.evaluate: Execution context was destroyed, most likely because of a navigation')
        values = [snapshot('Xbox'), failure] + [snapshot('Xbox')] * 3
        with patch.object(collector, '_read_snapshot', side_effect=values) as read, \
             patch.object(collector.time, 'sleep'), patch.object(collector, 'emit') as events:
            offer, stable = collector._stable_offer(None, 'unused', 'XBOX', 'Xbox')
        self.assertEqual((read.call_count, stable, offer['base_k']), (5, 3, '100'))
        self.assertTrue(any(c.kwargs.get('reason_code') == 'navigation_context_changed' for c in events.call_args_list))
        with patch.object(collector, '_read_snapshot', side_effect=failure) as read, \
             patch.object(collector.time, 'sleep'), patch.object(collector, 'emit'):
            with self.assertRaises(collector.CollectionError):
                collector._stable_offer(None, 'unused', 'XBOX', 'Xbox')
        self.assertEqual(read.call_count, 24)

    def test_other_read_errors_are_not_retried_or_disclosed(self):
        Error = type('Error', (Exception,), {'__module__': 'playwright._impl._errors'})
        failures = [Error('Target closed https://private.invalid/secret'),
                    RuntimeError('Execution context was destroyed, most likely because of a navigation')]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), \
                 patch.object(collector, '_read_snapshot', side_effect=failure) as read, \
                 patch.object(collector.time, 'sleep'), patch.object(collector, 'emit') as events:
                with self.assertRaises(type(failure)):
                    collector._stable_offer(None, 'unused', 'XBOX', 'Xbox')
                self.assertEqual(read.call_count, 1)
                self.assertEqual(events.call_args_list[-1].kwargs['reason_code'], 'page_read_failed')
                self.assertNotIn('private.invalid', str(events.call_args_list))

    def test_failure_diagnostics_keep_spec_count_and_platform_without_page_text(self):
        for tier, count, base, code in [('missing', 0, None, 'spec_missing'),
                                        ('multiple', 2, None, 'spec_multiple'),
                                        ('ready', 0, 200, 'spec_quantity_mismatch')]:
            value = snapshot('Xbox', tierState=tier, tierCandidateCount=count,
                             visibleCardCount=4, baseK=base, rawPage='private page text')
            with self.subTest(tier=tier), \
                 patch.object(collector, '_read_snapshot', return_value=value), \
                 patch.object(collector.time, 'sleep'), patch.object(collector, 'emit') as events:
                with self.assertRaises(collector.CollectionError):
                    collector._stable_offer(None, 'unused', 'XBOX', 'Xbox')
            last = events.call_args_list[-1].kwargs
            self.assertEqual((last['reason_code'], last['candidate_count'], last['selected_platforms']),
                             (code, count, ['Xbox']))
            self.assertNotIn('private page text', str(events.call_args_list))

    def test_reuses_extension_parser_and_fails_closed_on_missing_source(self):
        source = collector.load_reader()
        self.assertIn("function readVisibleOffer()", source)
        self.assertIn("couponState", source)
        self.assertIn("excludedCouponDiscount", source)

        with self.assertRaises(collector.CollectionError):
            collector.load_reader(collector.READER_SOURCE.with_name("absent.js"))

    def test_three_platform_labels_and_coupon_price_basis_are_preserved(self):
        expectations = (("PS", "PS4/5", "15.99"),
                        ("XBOX", "Xbox", "16.29"),
                        ("PC", "PC", "16.59"))
        for platform, label, price in expectations:
            with self.subTest(platform=platform):
                self.assertIsNone(collector.snapshot_error(snapshot(label, price=price), label))
                offer = collector._offer(platform, snapshot(label, coupon=True))
                self.assertEqual(offer["platform"], platform)
                self.assertEqual(offer["usd_price"], "15.99")
                self.assertTrue(offer["coupon_excluded"])
                self.assertEqual(offer["observed_coupon_price"], "15.04")

    def test_rejects_platform_login_currency_tier_gift_and_price_ambiguity(self):
        cases = [
            (snapshot("Xbox"), "PS4/5", "平台"),
            (snapshot("PS4/5", loggedIn=False), "PS4/5", "登录"),
            (snapshot("PS4/5", currencyState="currency"), "PS4/5", "币种"),
            (snapshot("PS4/5", currencyState="language"), "PS4/5", "币种"),
            (snapshot("PS4/5", tierState="multiple"), "PS4/5", "规格"),
            (snapshot("PS4/5", baseK=200), "PS4/5", "规格"),
            (snapshot("PS4/5", priceState="multiple"), "PS4/5", "售价"),
            (snapshot("PS4/5", usdPrice="NaN"), "PS4/5", "售价"),
            (snapshot("PS4/5", giftState="missing"), "PS4/5", "赠送量"),
            (snapshot("PS4/5", bonusK="Infinity"), "PS4/5", "赠送量"),
            (snapshot("PS4/5", couponState="discount_missing"), "PS4/5", "优惠券"),
            (snapshot("PS4/5", coupon=True,
                      excludedCouponDiscount="0.94"), "PS4/5", "关系不符"),
        ]
        for value, expected_label, reason in cases:
            with self.subTest(reason=reason, value=value):
                result = collector.snapshot_error(value, expected_label)
                self.assertIsNotNone(result)
                self.assertIn(reason, result)

    def test_requires_three_consecutive_stable_reads(self):
        value = snapshot("PS4/5")
        self.assertIn("稳定", collector.snapshot_error(value, "PS4/5", stable_reads=2))
        self.assertIsNone(collector.snapshot_error(value, "PS4/5", stable_reads=3))

    def _run_collection(self, per_platform, *, original_snapshot=None, single_ps=False):
        browser = FakeBrowser()
        manager = FakePlaywrightManager(browser)
        playwright_api = types.ModuleType("playwright.sync_api")
        playwright_api.TimeoutError = type("PlaywrightTimeoutError", (Exception,), {})
        playwright_api.sync_playwright = lambda: manager
        package = types.ModuleType("playwright")
        package.sync_api = playwright_api
        module_map = {"playwright": package, "playwright.sync_api": playwright_api}

        def read(page, _source):
            if page.is_original and page.platform == "PS":
                return original_snapshot or snapshot("PS4/5")
            label = {"PS": "PS4/5", "XBOX": "Xbox", "PC": "PC"}[page.platform]
            value = per_platform[page.platform]
            return value(label) if callable(value) else value

        with patch.dict(sys.modules, module_map), \
             patch.object(collector, "_read_snapshot", side_effect=read), \
             patch.object(collector, "_platform_controls", return_value=[
                 {"label": "ps4/5"}, {"label": "xbox"}, {"label": "pc"}]), \
             patch.object(collector.time, "sleep", return_value=None), \
             patch.object(collector, "emit"):
            try:
                result = collector.collect(single_ps=single_ps)
                error = None
            except collector.CollectionError as exc:
                result, error = None, str(exc)
        return browser, result, error

    def test_reads_all_platforms_in_existing_tab_and_restores_ps(self):
        browser, result, error = self._run_collection({
            "PS": snapshot("PS4/5", price="15.99"),
            "XBOX": snapshot("Xbox", price="16.29"),
            "PC": snapshot("PC", price="16.59", coupon=True),
        })
        self.assertIsNone(error)
        self.assertEqual(set(result["offers"]), {"PS", "XBOX", "PC"})
        context = browser.contexts[0]
        self.assertEqual(context.max_temporary_open, 0)
        self.assertEqual(context.pages, [context.original])
        self.assertEqual(context.original.platform, "PS")
        self.assertFalse(context.original.closed)
        self.assertFalse(browser.close_called)

    def test_ps_failure_does_not_open_a_temporary_tab(self):
        browser, result, error = self._run_collection({
            "PS": snapshot("PS4/5"),
            "XBOX": snapshot("Xbox"),
            "PC": snapshot("PC"),
        }, original_snapshot=snapshot("PS4/5", couponState="unknown"))
        self.assertIsNone(result)
        self.assertIn("PS", error)
        self.assertEqual(browser.contexts[0].pages, [browser.contexts[0].original])
        self.assertEqual(browser.contexts[0].max_temporary_open, 0)

    def test_single_ps_mode_reads_existing_page_only(self):
        browser, result, error = self._run_collection({}, single_ps=True)
        self.assertIsNone(error)
        self.assertEqual(set(result["offers"]), {"PS"})
        self.assertEqual(browser.contexts[0].pages, [browser.contexts[0].original])
        self.assertEqual(browser.contexts[0].max_temporary_open, 0)

    def test_failure_stops_run_and_restores_existing_ps_tab(self):
        browser, result, error = self._run_collection({
            "PS": snapshot("PS4/5"),
            "XBOX": snapshot("Xbox", loggedIn=False),
            "PC": snapshot("PC"),
        })
        self.assertIsNone(result)
        self.assertIn("XBOX", error)
        context = browser.contexts[0]
        self.assertEqual(len(context.pages), 1)
        self.assertFalse(context.original.closed)
        self.assertEqual(context.original.platform, "PS")
        self.assertEqual(context.max_temporary_open, 0)
        self.assertFalse(browser.close_called)

    def test_wall_deadline_bounds_a_stalled_cdp_operation(self):
        release = threading.Event()

        def stalled_operation(**_kwargs):
            release.wait(1)

        with patch.object(collector, "_collect_attached", side_effect=stalled_operation), \
             patch.object(collector, "COLLECT_TIMEOUT_SECONDS", 0.01):
            with self.assertRaisesRegex(collector.CollectionError, "总时限"):
                collector.collect()
        release.set()


if __name__ == "__main__":
    unittest.main()
