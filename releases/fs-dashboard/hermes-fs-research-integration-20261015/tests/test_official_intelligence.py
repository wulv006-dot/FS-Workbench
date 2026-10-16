import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

SOURCE = Path(__file__).resolve().parents[1] / 'source' / 'official_intelligence.py'
spec = importlib.util.spec_from_file_location('official_intelligence', SOURCE)
official = importlib.util.module_from_spec(spec)
spec.loader.exec_module(official)
INDEX = official.INDEX
PREFIX = 'https://www.ea.com' + official.PREFIX
QUERY = dict(profile='FC27', start='2026-10-08', end='2026-10-14')
NOW = datetime(2026, 10, 15, 10, tzinfo=timezone.utc)


def html(body, title='EA SPORTS FC 27 News', extra=''):
    return ('<html><head><title>' + title + '</title>' + extra + '</head><body><nav>excluded nav</nav><main>' + body + '</main></body></html>').encode()


def index(links):
    return html('Official FC27 news. ' * 6 + ''.join('<a href="' + url + '">article</a>' for url in links))


def article(title='EA SPORTS FC 27 update', extra='', body=None):
    return html(body or 'Event begins October 16. Gameplay update and content details. ' * 5, title, extra)


class OfficialTests(unittest.TestCase):
    def reader(self, payloads):
        calls = []

        def fetch(url, hosts, deadline_at):
            self.assertEqual(hosts, ['www.ea.com'])
            self.assertIsNotNone(deadline_at.utcoffset())
            calls.append(url)
            value = payloads[url]
            if isinstance(value, Exception):
                raise value
            return value if isinstance(value, tuple) else (value, 'text/html', url)

        return official.OfficialReader(fetcher=fetch, clock=lambda: NOW), calls

    def test_query_boundary_and_import_without_host_helper(self):
        self.assertEqual(official.checked_query(QUERY), QUERY)
        for bad in (dict(QUERY, url='https://localhost'), dict(QUERY, profile='FC26'),
                    dict(QUERY, start='2026-1-01'), dict(QUERY, end='2026-10-07'),
                    dict(QUERY, end='2027-02-01'), dict(QUERY, start='2026-02-30')):
            with self.assertRaises(ValueError):
                official.checked_query(bad)
        with patch.dict(sys.modules, {'game_intelligence': None}):
            isolated = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(isolated)
            self.assertEqual(isolated.checked_query(QUERY), QUERY)

    def test_fc27_only_discovery_and_three_distinct_dates(self):
        url = PREFIX + 'fc-27-update'
        reader, calls = self.reader({INDEX: index([url, '/games/ea-sports-fc/fc-26/news/offer',
                                                 'https://localhost/private', url + '?x=1']),
                                     url: article(extra='<meta property="article:published_time" content="2026-10-13T16:00:00+01:00">')})
        result = reader(QUERY)
        self.assertEqual(calls, [INDEX, url])
        self.assertEqual(result['status'], 'available')
        doc = result['documents'][0]
        self.assertEqual(doc['published_at'], '2026-10-13T16:00:00+01:00')
        self.assertTrue(doc['publication_in_window'])
        self.assertEqual(doc['observed_at'], NOW.isoformat())
        self.assertIsNone(doc['event_date'])
        self.assertIn('October 16', doc['text'])
        self.assertNotIn('excluded nav', doc['text'])
        self.assertEqual(doc['sha256'], hashlib.sha256(doc['text'].encode()).hexdigest())

    def test_real_ea_publishing_date_shape_and_outside_window_context(self):
        url = PREFIX + 'fc-27-update'
        extra = '<script>{"publishingDate":"2026-10-15T16:00:00.000+01:00","slug":"fc-27-update"}</script>'
        reader, _ = self.reader({INDEX: index([url]), url: article(extra=extra)})
        doc = reader(QUERY)['documents'][0]
        self.assertEqual(doc['published_at'], '2026-10-15T16:00:00+01:00')
        self.assertFalse(doc['publication_in_window'])

    def test_index_date_hint_is_bound_to_slug(self):
        url = PREFIX + 'fc-27-update'
        payload = index([url]).replace(b'</head>', b'<script>{"publishingDate":"2026-10-09T18:00:00+01:00","slug":"fc-27-update"}</script></head>')
        reader, _ = self.reader({INDEX: payload, url: article()})
        self.assertEqual(reader(QUERY)['documents'][0]['published_at'], '2026-10-09T18:00:00+01:00')

    def test_unknown_publication_is_not_observation_or_event_date(self):
        url = PREFIX + 'fc-27-update'
        reader, _ = self.reader({INDEX: index([url]), url: article()})
        doc = reader(QUERY)['documents'][0]
        self.assertIsNone(doc['published_at'])
        self.assertIsNone(doc['publication_in_window'])
        self.assertIsNone(doc['event_date'])

    def test_failed_article_retains_success_and_safe_error(self):
        good, bad = PREFIX + 'good', PREFIX + 'bad'
        reader, _ = self.reader({INDEX: index([good, bad]), good: article(), bad: OSError('private secret detail')})
        result = reader(QUERY)
        self.assertEqual((result['http_status'], result['status']), (200, 'partial'))
        self.assertEqual(len(result['documents']), 1)
        self.assertEqual(result['failures'], [{'source_url': bad, 'reason': 'fetch_or_parse_failed'}])

    def test_fetch_bounds_and_truncation_are_explicit(self):
        urls = [PREFIX + 'article-' + str(i) for i in range(9)]
        reader, calls = self.reader({INDEX: index(urls), **{url: article(body='Important content. ' * 500) for url in urls}})
        result = reader(QUERY)
        self.assertEqual(len(calls), 7)
        self.assertEqual(result['coverage']['omitted_articles'], 3)
        self.assertFalse(result['coverage']['exhaustive'])
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(all(doc['text_truncated'] and len(doc['text']) == official.MAX_TEXT for doc in result['documents']))

    def test_fc26_title_and_redirect_are_rejected(self):
        for payload in (article(title='EA SPORTS FC 26 offer'),
                        (article(), 'text/html', 'https://www.ea.com/games/ea-sports-fc/fc-26/news/offer')):
            url = PREFIX + 'offer'
            reader, _ = self.reader({INDEX: index([url]), url: payload})
            result = reader(QUERY)
            self.assertEqual((result['status'], result['http_status']), ('not_available', 503))
            self.assertFalse(result['documents'])

    def test_no_article_is_not_no_activity(self):
        reader, _ = self.reader({INDEX: index([])})
        result = reader(QUERY)
        self.assertEqual(result['status'], 'empty')
        self.assertIn('does not establish no activity', result['coverage']['limitation'])

    def test_unreadable_or_failed_index_not_success(self):
        for payload in (TimeoutError(), html('Access denied ' * 10), b'x' * (official.MAX_BYTES + 1)):
            reader, calls = self.reader({INDEX: payload})
            result = reader(QUERY)
            self.assertEqual((result['status'], result['http_status']), ('not_available', 503))
            self.assertEqual(calls, [INDEX])
            self.assertTrue(result['failures'])


if __name__ == '__main__':
    unittest.main()
