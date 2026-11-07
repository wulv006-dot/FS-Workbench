import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_feed import (DefinitelyNotSent, NewsStore, canonical_x_url, parse_listing,
                       publish_pending, validate_config, fetch_listing, MAX_RESPONSE, SOURCE_URL)


LISTING = '''<section class="news-blog areas"><ul class="bolg-ul selected">
<li><a class="imgbox" href="/News/fc-27-lois-openda-sbc-guide-requirements-cheapest-solutions-and-rttk-rewards.html"><img data-original="https://assets.mmoexp.com/images/202611/7c9963ee03b0d950a4bf8dd627efb8104898e64c.png"></a><div class="boig-content"><h3 class="title">FC 27 Lois Openda SBC Guide: Requirements, Cheapest Solutions, and RTTK Rewards</h3><div class="text">Complete the SBC with a short guide ...</div><span class="time">Nov 6, 2026</span></div></li>
<li><a class="imgbox" href="/News/fc-27-test-older.html"></a><h3 class="title">FC 27 older news</h3><div class="text">Short preview &amp; source.</div><span class="time">Nov 5, 2026</span></li>
</ul></section>'''


class NewsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'news.sqlite3'
        self.store = NewsStore(self.path)

    def test_parser_extracts_source_metadata_and_deduplicates_sections(self):
        rows = parse_listing(LISTING + LISTING)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['published_date'], 'Nov 6, 2026')
        self.assertEqual(rows[0]['source'], 'MMOEXP FC27')
        self.assertTrue(rows[0]['cover_url'].startswith('https://assets.mmoexp.com/images/'))
        self.assertEqual(rows[1]['summary'], 'Short preview & source.')
        with self.assertRaises(ValueError):
            parse_listing(LISTING.replace('/News/fc-27-', 'https://evil.example/News/fc-27-'))

    def test_bootstrap_only_latest_then_persistent_dedup_and_old_content_baseline(self):
        rows = parse_listing(LISTING)
        self.assertEqual(self.store.ingest(rows, 1), 1)
        self.assertEqual(sorted(r['status'] for r in self.store.items()), ['baseline', 'pending'])
        reopened = NewsStore(self.path)
        self.assertEqual(reopened.ingest(rows, 2), 0)
        old = dict(rows[1], url='https://www.mmoexp.com/News/fc-27-resurfaced.html')
        self.assertEqual(reopened.ingest(rows + [old], 3), 0)
        new = dict(rows[0], url='https://www.mmoexp.com/News/fc-27-new.html')
        self.assertEqual(reopened.ingest(rows + [new], 4), 1)

    def test_x_allowlist_and_manual_repeats(self):
        self.assertEqual(canonical_x_url('https://twitter.com/FutSheriff/status/123?s=20'), 'https://x.com/FutSheriff/status/123')
        for url in ['http://x.com/test/status/123', 'https://x.com.evil/test/status/123',
                    'https://x.com@127.0.0.1/test/status/123', 'https://x.com/test/status/nope',
                    'https://x.com:443/test/status/123', 'https://x.com/test/status/123/extra',
                    'https://x.com/test/status/123#x', 'https://x.com/test/status/123\n',
                    'https://twitter.com/test/status/123?url=https://evil.example']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                canonical_x_url(url)
        first = self.store.enqueue_x('https://x.com/A/status/123', '@everyone summary')
        other = self.store.enqueue_x('https://twitter.com/B/status/123', 'changed')
        self.assertNotEqual(first['id'], other['id'])
        self.assertEqual(other['summary'], 'changed')

    def test_acknowledged_ambiguous_and_definite_failures_never_replay(self):
        for number in range(1, 4):
            self.store.enqueue_x('https://x.com/test/status/%s' % number)
        calls = []
        async def send(item, channel):
            calls.append(item['id'])
            if len(calls) == 1:
                return 1234
            if len(calls) == 2:
                raise TimeoutError('sensitive response body is never saved')
            raise DefinitelyNotSent()
        self.assertEqual(asyncio.run(publish_pending(self.store, '123456789012345678', send)), 1)
        self.assertEqual({r['status'] for r in self.store.items()}, {'published', 'uncertain', 'failed'})
        self.assertEqual(asyncio.run(publish_pending(self.store, '123456789012345678', send)), 0)
        self.assertEqual(len(calls), 3)
        self.assertFalse(any('sensitive' in (r['error_code'] or '') for r in self.store.items()))

    def test_process_interruption_is_not_reclaimed(self):
        self.store.enqueue_x('https://x.com/test/status/123')
        self.assertIsNotNone(self.store.claim('123456789012345678'))
        self.assertIsNone(NewsStore(self.path).claim('123456789012345678'))
        self.store.recover_sending()
        self.assertEqual(self.store.items()[0]['status'], 'uncertain')

    def test_invalid_persisted_link_is_failed_without_calling_sender(self):
        item = self.store.enqueue_x('https://x.com/test/status/123')
        with self.store.db() as db, db:
            db.execute('UPDATE news_items SET url=? WHERE id=?', ('https://127.0.0.1/private', item['id']))
        async def send(*args):
            self.fail('Invalid persisted URL must never reach Discord')
        self.assertEqual(asyncio.run(publish_pending(self.store, '123456789012345678', send)), 0)
        self.assertEqual(self.store.items()[0]['status'], 'failed')

    def test_fetch_is_fixed_bounded_and_does_not_follow_redirects(self):
        from news_feed import _NoRedirect
        with self.assertRaises(ValueError):
            _NoRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/')
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def geturl(self): return SOURCE_URL
            def read(self, count):
                self.count = count
                return b'x' * count
        response = Response()
        class Opener:
            def open(inner, request, timeout):
                self.assertEqual(request.full_url, SOURCE_URL)
                return response
        with patch('news_feed.urllib.request.build_opener', return_value=Opener()):
            with self.assertRaises(ValueError):
                fetch_listing()
        self.assertEqual(response.count, MAX_RESPONSE + 1)

    def test_config_and_mentions(self):
        config = {'guild_id': 1, 'channel_id': '123456789012345678', 'enabled': True, 'poll_seconds': 900}
        self.assertEqual(validate_config(config, 1), config)
        for bad in [dict(config, guild_id=2), dict(config, poll_seconds=1), dict(config, url='https://evil.example')]:
            with self.assertRaises(ValueError):
                validate_config(bad, 1)
        from news_feed import news_embed
        item = self.store.enqueue_x('https://x.com/test/status/123', '@everyone <@123>')
        self.assertNotIn('@everyone', news_embed(item).description)


if __name__ == '__main__':
    unittest.main()
