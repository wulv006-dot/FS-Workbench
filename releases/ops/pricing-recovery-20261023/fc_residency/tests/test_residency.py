import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
import lootbar_server_collector as collector
from test_lootbar_server_collector import FakeBrowser, FakePage, snapshot
import test_lootbar_server_collector as fixtures


class ResidencyTests(unittest.TestCase):
    def setUp(self):
        self.harness = fixtures.ServerCollectorTests()
        self.offers = {'XBOX': snapshot('Xbox'), 'PC': snapshot('PC')}

    def run_collection(self, **kwargs):
        return self.harness._run_collection(self.offers, **kwargs)

    def test_full_collection_replaces_document_in_same_context_and_releases_worker(self):
        browser, result, error = self.run_collection()
        page = browser.contexts[0].original
        self.assertIsNone(error)
        self.assertEqual(set(result['offers']), {'PS', 'XBOX', 'PC'})
        self.assertEqual(page.url, collector.IDLE_URL)
        self.assertEqual(page.workers, [])
        self.assertEqual(page.rendered_link, collector.BASE_URL)
        self.assertEqual(browser.contexts[0].pages, [page])
        self.assertFalse(browser.close_called)
        self.assertEqual(len(browser.contexts[0].closed_pages), 1)
        self.assertEqual(browser.contexts[0].global_workers, {})

    def test_next_full_cycle_wakes_idle_then_replaces_document_again(self):
        browser, _, _ = self.run_collection()
        page = browser.contexts[0].original
        previous_reloads = page.reload_count
        _, result, error = self.run_collection(browser=browser)
        self.assertIsNone(error)
        self.assertEqual(set(result['offers']), {'PS', 'XBOX', 'PC'})
        self.assertEqual(page.reload_count, previous_reloads)
        self.assertEqual(page.goto_calls, [collector.IDLE_URL, collector.BASE_URL])
        self.assertTrue(page.closed)
        self.assertIsNot(browser.contexts[0].original, page)
        self.assertEqual(browser.contexts[0].original.url, collector.IDLE_URL)
        self.assertEqual(browser.contexts[0].global_workers, {})

    def test_ps_only_active_page_keeps_manual_document(self):
        browser, result, error = self.run_collection(single_ps=True)
        page = browser.contexts[0].original
        self.assertIsNone(error)
        self.assertEqual(set(result['offers']), {'PS'})
        self.assertEqual(page.reload_count, 0)
        self.assertEqual(page.goto_calls, [])
        self.assertEqual(page.url, collector.BASE_URL)
        self.assertEqual(len(page.workers), 1)

    def test_ps_only_owned_idle_wakes_then_parks(self):
        browser = FakeBrowser()
        page = browser.contexts[0].original
        page.url = collector.IDLE_URL
        _, result, error = self.run_collection(single_ps=True, browser=browser)
        self.assertIsNone(error)
        self.assertEqual(set(result['offers']), {'PS'})
        self.assertEqual(page.goto_calls, [collector.BASE_URL])
        self.assertTrue(page.closed)
        self.assertEqual(browser.contexts[0].original.url, collector.IDLE_URL)
        self.assertEqual(page.reload_count, 0)

    def test_ps_only_owned_idle_waits_for_original_controls(self):
        browser = FakeBrowser()
        browser.contexts[0].original.url = collector.IDLE_URL
        ready = [{'label': label} for label in ('ps4/5', 'xbox', 'pc')]
        _, result, error = self.run_collection(single_ps=True, browser=browser, control_reads=[[], ready])
        self.assertIsNone(error)
        self.assertEqual(set(result['offers']), {'PS'})

    def test_failed_full_collection_parks_without_hiding_primary_error(self):
        self.offers['XBOX'] = snapshot('Xbox', loggedIn=False)
        browser, result, error = self.run_collection()
        self.assertIsNone(result)
        self.assertIn('XBOX', error)
        self.assertEqual(browser.contexts[0].original.url, collector.IDLE_URL)

    def test_failed_parking_preserves_primary_error(self):
        self.offers['XBOX'] = snapshot('Xbox', loggedIn=False)
        with patch.object(collector, '_park_product_page', side_effect=RuntimeError('private detail')):
            _, result, error = self.run_collection()
        self.assertIsNone(result)
        self.assertIn('XBOX', error)
        self.assertNotIn('private detail', error)

    def test_failed_parking_does_not_block_valid_collection(self):
        with patch.object(collector, '_park_product_page', side_effect=RuntimeError('private detail')):
            _, result, error = self.run_collection()
        self.assertIsNone(error)
        self.assertEqual(set(result['offers']), {'PS', 'XBOX', 'PC'})

    def test_unowned_blank_is_not_woken(self):
        browser = FakeBrowser()
        page = browser.contexts[0].original
        page.url = 'about:blank'
        _, result, error = self.run_collection(browser=browser)
        self.assertIsNone(result)
        self.assertIn('只保留一个', error)
        self.assertEqual(page.goto_calls, [])

    def test_two_owned_targets_fail_before_mutating_either(self):
        browser = FakeBrowser()
        context = browser.contexts[0]
        other = FakePage(context)
        other.url = collector.IDLE_URL
        context.pages.append(other)
        _, result, error = self.run_collection(browser=browser)
        self.assertIsNone(result)
        self.assertIn('只保留一个', error)
        self.assertEqual(context.original.goto_calls, [])
        self.assertEqual(other.goto_calls, [])

    def test_wake_does_not_bypass_login_guard(self):
        browser = FakeBrowser()
        browser.contexts[0].original.url = collector.IDLE_URL
        _, result, error = self.run_collection(browser=browser, single_ps=True,
                                             original_snapshot=snapshot('PS4/5', loggedIn=False))
        self.assertIsNone(result)
        self.assertIn('登录', error)

    def test_wake_redirect_keeps_login_page_for_manual_repair(self):
        browser = FakeBrowser()
        page = browser.contexts[0].original
        page.url = collector.IDLE_URL
        def redirected(target, url, **_kwargs):
            target.url = 'https://www.lootbar.com/login'
            return type('Response', (), {'status': 200})()
        with patch.object(FakePage, 'goto', redirected):
            _, result, error = self.run_collection(browser=browser)
        self.assertIsNone(result)
        self.assertEqual(error, 'product_page_refresh_failed')
        self.assertEqual(page.url, 'https://www.lootbar.com/login')

    def test_owned_idle_marker_requires_exact_url(self):
        for url in ('about:blank#fc27-idle-other', 'https://invalid.test/#fc27-idle'):
            browser = FakeBrowser()
            page = browser.contexts[0].original
            page.url = url
            with self.subTest(url=url):
                _, result, error = self.run_collection(browser=browser)
                self.assertIsNone(result)
                self.assertIn('只保留一个', error)
                self.assertEqual(page.goto_calls, [])

    def test_parking_checks_no_worker_remains(self):
        browser = FakeBrowser()
        page = browser.contexts[0].original
        original_goto = page.goto
        def leave_worker(url, **kwargs):
            result = original_goto(url, **kwargs)
            page.workers = [object()]
            return result
        with patch.object(page, 'goto', side_effect=leave_worker), patch.object(collector, 'emit'):
            with self.assertRaisesRegex(collector.CollectionError, 'idle_unverified'):
                collector._park_product_page(page)

    def test_parking_checks_exact_final_idle_identity(self):
        browser = FakeBrowser()
        page = browser.contexts[0].original
        original_goto = page.goto
        def redirected(url, **kwargs):
            result = original_goto(url, **kwargs)
            page.url = 'about:blank#unowned'
            return result
        with patch.object(page, 'goto', side_effect=redirected), patch.object(collector, 'emit'):
            with self.assertRaisesRegex(collector.CollectionError, 'idle_unverified'):
                collector._park_product_page(page)

    def test_failed_active_ps_only_never_parks_manual_document(self):
        browser, result, error = self.run_collection(single_ps=True,
            original_snapshot=snapshot('PS4/5', loggedIn=False))
        self.assertIsNone(result)
        self.assertIn('登录', error)
        self.assertEqual(browser.contexts[0].original.goto_calls, [])

    def test_parking_uses_one_shared_budget_for_navigation_and_dom(self):
        page = FakeBrowser().contexts[0].original
        with patch.object(collector.time, 'monotonic', side_effect=[100.5, 102.75]), \
             patch.object(page, 'goto', wraps=page.goto) as navigate, \
             patch.object(page, 'wait_for_function', wraps=page.wait_for_function) as wait, \
             patch.object(collector, 'emit'):
            collector._park_product_page(page, deadline=104)
        self.assertEqual(navigate.call_args.kwargs['timeout'], 3500)
        self.assertEqual(wait.call_args.kwargs['timeout'], 1250)

    def test_exhausted_parking_budget_never_uses_zero_infinite_timeout(self):
        page = FakeBrowser().contexts[0].original
        with patch.object(collector.time, 'monotonic', return_value=104), \
             patch.object(page, 'goto') as navigate:
            with self.assertRaisesRegex(collector.CollectionError, 'budget_exhausted'):
                collector._park_product_page(page, deadline=104)
        navigate.assert_not_called()

    def test_parking_never_uses_unbounded_evaluate(self):
        page = FakeBrowser().contexts[0].original
        with patch.object(page, 'evaluate', side_effect=AssertionError('unbounded evaluate')) as evaluate, \
             patch.object(collector, 'emit'):
            collector._park_product_page(page)
        evaluate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
