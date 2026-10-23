import io
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
import lootbar_server_collector as collector
from test_lootbar_server_collector import FakeBrowser


class DocumentReleaseTests(unittest.TestCase):
    def setUp(self):
        self.browser = FakeBrowser()
        self.context = self.browser.contexts[0]
        self.old = self.context.original
        self.events = []
        self.deadline = time.monotonic() + 4
        self.patches = [patch.object(collector, '_cdp_http', side_effect=self.context.cdp_http),
                        patch.object(collector, 'emit', side_effect=lambda stage,**kw:self.events.append(dict(stage=stage,**kw)))]
        for item in self.patches: item.start()
        self.addCleanup(patch.stopall)

    def test_navigation_alone_can_leave_global_worker_but_replacement_removes_it(self):
        collector._park_product_page(self.old)
        self.assertEqual(self.old.workers, [])
        self.assertTrue(self.context.global_workers)
        self.old.goto(collector.BASE_URL)
        collector._release_product_document(self.old, deadline=self.deadline)
        self.assertTrue(self.old.closed)
        self.assertEqual(self.context.global_workers, {})
        self.assertEqual(len(self.context.pages), 1)
        self.assertEqual(self.events[-1]['http_lootbar_workers_after'], 0)
        self.assertFalse(self.events[-1]['global_workers_verified'])
        self.assertTrue(self.events[-1]['document_replaced'])

    def test_new_idle_must_be_ready_before_original_can_close(self):
        def prepare(page, **_kwargs):
            self.assertFalse(self.old.closed)
            self.assertIs(page.context, self.old.context)
            raise RuntimeError('prepare failed')
        with patch.object(collector, '_park_product_page', side_effect=prepare):
            with self.assertRaisesRegex(RuntimeError, 'prepare failed'):
                collector._release_product_document(self.old, deadline=self.deadline)
        self.assertFalse(self.old.closed)
        self.assertEqual(self.context.pages, [self.old])
        closes = [path for path,_,_ in self.context.http_calls if path.startswith('/json/close/')]
        self.assertEqual(closes, ['/json/close/new-1'])

    def test_unknown_old_close_is_not_replayed_or_followed_by_closing_new_idle(self):
        native = self.context.cdp_http
        def request(path, **kwargs):
            if path == '/json/close/old-1':
                self.context.http_calls.append((path,kwargs.get('method','GET'),kwargs['deadline']))
                raise TimeoutError('unknown close outcome')
            return native(path, **kwargs)
        with patch.object(collector, '_cdp_http', side_effect=request):
            with self.assertRaises(TimeoutError):
                collector._release_product_document(self.old, deadline=self.deadline)
        closes = [path for path,_,_ in self.context.http_calls if path.startswith('/json/close/')]
        self.assertEqual(closes, ['/json/close/old-1'])
        self.assertEqual(len(self.context.pages), 2)
        self.assertEqual(self.events[-1]['phase'], 'close_original')
        self.assertEqual(self.events[-1]['old_target'], 'old-1')
        self.assertEqual(self.events[-1]['idle_target'], 'new-1')

    def test_unknown_creation_is_not_replayed_or_blindly_closed(self):
        native = self.context.cdp_http
        def request(path, **kwargs):
            result = native(path, **kwargs)
            if path.startswith('/json/new?'):
                raise TimeoutError('unknown create outcome')
            return result
        with patch.object(collector, '_cdp_http', side_effect=request):
            with self.assertRaises(TimeoutError):
                collector._release_product_document(self.old, deadline=self.deadline)
        self.assertFalse(self.old.closed)
        self.assertEqual(len(self.context.pages), 2)
        self.assertFalse(any(path.startswith('/json/close/') for path,_,_ in self.context.http_calls))
        self.assertEqual(self.events[-1]['phase'], 'create_idle')
        self.assertIsNone(self.events[-1]['idle_target'])

    def test_global_worker_after_closure_prevents_false_release_success(self):
        native = self.context.cdp_http
        def request(path, **kwargs):
            result = native(path, **kwargs)
            if path == '/json/close/old-1': self.context.global_workers['cached-ghost'] = True
            return result
        clock = [self.deadline - 4]
        with patch.object(collector, '_cdp_http', side_effect=request), \
             patch.object(collector.time, 'monotonic', side_effect=lambda:clock[0]), \
             patch.object(collector.time, 'sleep', side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
            with self.assertRaisesRegex(collector.CollectionError, 'release_unverified'):
                collector._release_product_document(self.old, deadline=self.deadline)
        self.assertNotIn('product_page_parked', [row['stage'] for row in self.events])
        self.assertEqual(self.events[-1]['phase'], 'verify_release')

    def test_close_ack_with_temporarily_listed_old_target_is_read_back_without_reclosing(self):
        native = self.context.cdp_http
        closing = [False]
        reads = [0]
        def request(path, **kwargs):
            result = native(path, **kwargs)
            if path == '/json/close/old-1': closing[0] = True
            if path == '/json/list' and closing[0]:
                reads[0] += 1
                if reads[0] < 3:
                    result.append({'id':'old-1','type':'page','url':collector.BASE_URL})
            return result
        with patch.object(collector, '_cdp_http', side_effect=request), \
             patch.object(collector.time, 'sleep') as pause:
            collector._release_product_document(self.old, deadline=self.deadline)
        self.assertEqual(reads[0], 3)
        self.assertEqual(pause.call_count, 2)
        self.assertTrue(all(call.args[0] <= 0.05 for call in pause.call_args_list))
        self.assertEqual(sum(path == '/json/close/old-1' for path,_,_ in self.context.http_calls), 1)
        self.assertEqual(sum(path.startswith('/json/new?') for path,_,_ in self.context.http_calls), 1)
        self.assertEqual(self.events[-1]['stage'], 'product_page_parked')

    def test_permanently_listed_old_target_stops_at_original_budget_without_replay(self):
        native = self.context.cdp_http
        closing = [False]
        clock = [self.deadline - 4]
        def request(path, **kwargs):
            result = native(path, **kwargs)
            if path == '/json/close/old-1': closing[0] = True
            if path == '/json/list' and closing[0]:
                result.append({'id':'old-1','type':'page','url':collector.BASE_URL})
            return result
        with patch.object(collector, '_cdp_http', side_effect=request), \
             patch.object(collector.time, 'monotonic', side_effect=lambda:clock[0]), \
             patch.object(collector.time, 'sleep', side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
            with self.assertRaisesRegex(collector.CollectionError, 'release_unverified'):
                collector._release_product_document(self.old, deadline=self.deadline)
        self.assertLessEqual(clock[0], self.deadline)
        self.assertEqual(sum(path == '/json/close/old-1' for path,_,_ in self.context.http_calls), 1)
        self.assertEqual(sum(path.startswith('/json/new?') for path,_,_ in self.context.http_calls), 1)
        self.assertNotIn('product_page_parked', [row['stage'] for row in self.events])
        self.assertEqual(self.events[-1]['phase'], 'verify_release')

    def test_invalid_original_target_never_creates_or_closes_a_page(self):
        self.old.target_id = '../other'
        with self.assertRaisesRegex(collector.CollectionError, 'identity_invalid'):
            collector._release_product_document(self.old, deadline=self.deadline)
        self.assertEqual([path for path,_,_ in self.context.http_calls], ['/json/list'])

    def test_preparation_and_rollback_share_budget_without_unbounded_page_calls(self):
        collector._release_product_document(self.old, deadline=self.deadline)
        self.assertLessEqual(max(deadline for _,_,deadline in self.context.http_calls), self.deadline)
        self.assertEqual(self.context.http_calls[0][2], self.deadline - 1)
        self.assertEqual(self.context.http_calls[-1][2], self.deadline)


class CdpHttpTests(unittest.TestCase):
    def test_create_uses_put_and_remaining_socket_timeout(self):
        reply = io.BytesIO(b'{"id":"new-1","type":"page","url":"about:blank#fc27-idle"}')
        with patch.object(collector.time, 'monotonic', return_value=100), \
             patch.object(collector, 'urlopen', return_value=reply) as request:
            value = collector._cdp_http('/json/new?about%3Ablank%23fc27-idle', method='PUT', deadline=103)
        self.assertEqual(value['id'], 'new-1')
        self.assertEqual(request.call_args.args[0].get_method(), 'PUT')
        self.assertEqual(request.call_args.kwargs['timeout'], 3)

    def test_close_preserves_native_plain_text_reply(self):
        with patch.object(collector, 'urlopen', return_value=io.BytesIO(b'Target is closing')):
            self.assertEqual(collector._cdp_http('/json/close/old-1', deadline=time.monotonic()+1), 'Target is closing')

    def test_expired_http_budget_never_uses_zero_or_unbounded_timeout(self):
        with patch.object(collector.time, 'monotonic', return_value=100), \
             patch.object(collector, 'urlopen') as request:
            with self.assertRaisesRegex(collector.CollectionError, 'budget_exhausted'):
                collector._cdp_http('/json/list', deadline=100)
        request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
