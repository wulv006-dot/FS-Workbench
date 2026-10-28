"""Real HTTP threads and Linux file locks exercise independent range readers."""
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from threading import Event, Lock, RLock, Thread
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit

SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
from live_summary import SummaryCache

try:
    if os.name != 'posix':
        raise ImportError('real Linux flock unavailable')
    import fcntl
except ImportError:
    fcntl = None


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def function(name, namespace):
    tree = ast.parse((SOURCE / 'range_api.py').read_text(encoding='utf8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), name, 'exec'), namespace)
    return namespace[name]


def query(profile):
    return dict(profile=profile, start='2026-10-27', end='2026-10-27', grain='day',
                site='all-websites', cacheSeconds=600,
                period=dict(start='2026-10-27 00:00', end='2026-10-28 00:00'))


def record(q):
    return dict(status='available', period=q['period'], currency='USD', metrics={},
                capturedAt=datetime.now(timezone.utc).isoformat())


class ConcurrentRanges(unittest.TestCase):
    def test_two_cold_admin_scopes_use_parallel_upstream_and_cached_http_stays_fast(self):
        release = Event()
        both_started = Event()
        counts = {}
        counts_lock = Lock()

        class Upstream(BaseHTTPRequestHandler):
            def do_GET(self):
                profile = self.path.strip('/')
                with counts_lock:
                    counts[profile] = counts.get(profile, 0) + 1
                    if counts.get('AION2') and counts.get('FC27'):
                        both_started.set()
                if profile != 'NBA2K27' and not release.wait(5):
                    self.send_error(504)
                    return
                body = encoded({'profile': profile})
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass

        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        upstream_thread = Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        def admin(q):
            with urllib.request.urlopen('http://127.0.0.1:%s/%s' % (upstream.server_port, q['profile']), timeout=6) as response:
                self.assertEqual(json.load(response)['profile'], q['profile'])
            return record(q)
        profiles = {name: (name, name) for name in ('AION2', 'FC27', 'NBA2K27')}
        cache = SummaryCache(admin, record, profiles)
        cache.persist_complete = lambda q: None
        queries = {name: query(name) for name in profiles}
        queries['FC27'].update(site='www.mmoexp.com', admin_site='266', profit_site='main')
        tree = ast.parse((SOURCE / 'range_api.py').read_text(encoding='utf8'))
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
        namespace = dict(BaseHTTPRequestHandler=BaseHTTPRequestHandler, urlsplit=urlsplit,
                         parse_qs=parse_qs, encoded=encoded, CONVERSATION_PREFIX='/conversations',
                         get_range=lambda params: cache.get_live(queries[params['profile'][0]]))
        exec(compile(ast.Module(body=[handler], type_ignores=[]), 'actual-range-handler', 'exec'), namespace)
        server = ThreadingHTTPServer(('127.0.0.1', 0), namespace['Handler'])
        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        def read(profile, user):
            request = urllib.request.Request('http://127.0.0.1:%s/range?profile=%s' % (server.server_port, profile),
                                             headers={'X-Auth-User': user})
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.load(response)
        try:
            read('NBA2K27', 'cache-user')
            deadline = time.monotonic() + 2
            while cache.get_live(queries['NBA2K27'])[0] != 200 and time.monotonic() < deadline:
                time.sleep(.01)
            with ThreadPoolExecutor(max_workers=3) as clients:
                first = clients.submit(read, 'AION2', 'alice')
                second = clients.submit(read, 'FC27', 'bob')
                self.assertEqual(first.result(timeout=2)[0], 202)
                self.assertEqual(second.result(timeout=2)[0], 202)
                self.assertTrue(both_started.wait(2), 'independent Admin requests were serialized')
                cached = clients.submit(read, 'NBA2K27', 'charlie').result(timeout=1)
                self.assertEqual(cached[0], 200)
                self.assertEqual(cached[1]['profile']['key'], 'NBA2K27')
                self.assertEqual(read('AION2', 'another-user')[0], 202)
                self.assertEqual(counts, {'NBA2K27': 1, 'AION2': 1, 'FC27': 1})
                self.assertFalse(release.is_set(), 'cached request waited for the slow sources')
                release.set()
                for name, site in [('AION2', 'all-websites'), ('FC27', 'www.mmoexp.com')]:
                    deadline = time.monotonic() + 2
                    while cache.get_live(queries[name])[0] != 200 and time.monotonic() < deadline:
                        time.sleep(.01)
                    result = read(name, 'alice')[1]
                    self.assertEqual(result['query']['site'], site)
        finally:
            release.set()
            cache.close()
            server.shutdown(); server.server_close(); server_thread.join()
            upstream.shutdown(); upstream.server_close(); upstream_thread.join()

    def test_admin_finishes_while_shared_order_worker_remains_serial(self):
        release = Event(); first_order = Event(); calls = []
        def order(q):
            calls.append(q['profile']); first_order.set()
            if not release.wait(3):
                raise TimeoutError('fixture_order_timeout')
            return record(q)
        profiles = {name: (name, name) for name in ('AION2', 'FC27')}
        cache = SummaryCache(record, order, profiles)
        cache.persist_complete = lambda q: None
        try:
            for name in profiles:
                cache.get_live(query(name))
            self.assertTrue(first_order.wait(1))
            deadline = time.monotonic() + 1
            while any(cache.get_live(query(name))[0] != 200 for name in profiles) and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual([cache.get_live(query(name))[0] for name in profiles], [200, 200])
            self.assertEqual(len(calls), 1)
            self.assertEqual(cache.pools['Order']._max_workers, 1)
        finally:
            release.set(); cache.close()

    def test_product_jobs_reuse_admin_pool_and_same_key_is_coalesced(self):
        admin_pool, order_pool = Mock(), Mock()
        with tempfile.TemporaryDirectory() as folder:
            namespace = dict(snapshot=lambda: {'snapshotId': 'catalog'}, query=lambda params, d: dict(query('FC27'),
                             analysis='fc27-products', baseSnapshotId='catalog'), CACHE=Path(folder),
                             hashlib=hashlib, encoded=encoded, json=json, LOCK=RLock(), JOBS={}, STARTS=[],
                             time=time, capture=Mock(), POOL=order_pool, SUMMARY=SimpleNamespace(pools={'Admin': admin_pool}))
            get = function('get_range_live', namespace)
            self.assertEqual(get({})[0], 202)
            self.assertEqual(get({})[0], 202)
            admin_pool.submit.assert_called_once()
            order_pool.submit.assert_not_called()

    @unittest.skipIf(fcntl is None, 'requires Linux flock; also run this suite on the server')
    def test_product_capture_ignores_browser_lock_and_order_capture_preserves_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); jobs = {}; published = []
            period = query('FC27')['period']
            extension = dict(contractId='native-product', status='available', period=period, coverage={'complete': True})
            def source(container, script, requests, timeout):
                self.assertIsNone(container)
                self.assertEqual(script, 'fc_product_reader.py')
                return {'range': extension}
            namespace = dict(WEB=root, LOCK=RLock(), JOBS=jobs, PROFILE_MAP={'FC27': ('FC27', 'FC27', 1322, 1327, 'sports')},
                             snapshot=lambda: {'snapshotId': 'catalog'}, existing_call=source,
                             PRODUCT_CONTRACT='native-product', datetime=datetime, timezone=timezone,
                             publish_cache=lambda key, value: published.append(key), time=time,
                             ThreadPoolExecutor=ThreadPoolExecutor, fcntl=fcntl)
            capture = function('capture', namespace)
            with (root / 'collector.lock').open('a+b') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                capture(dict(query('FC27'), analysis='fc27-products', baseSnapshotId='catalog'), 'product')
                self.assertEqual(published, ['product'])
                admin_calls = []
                def call(container, script, requests, timeout):
                    admin_calls.append(script)
                    return {'range': {'period': period}}
                namespace['call'] = call
                capture(dict(query('FC27'), baseSnapshotId='catalog'), 'order')
                self.assertEqual(jobs['order']['error'], 'collector_busy')
                self.assertEqual(admin_calls, ['supplement_reader.py'])

    @unittest.skipIf(fcntl is None, 'requires Linux flock; also run this suite on the server')
    def test_browser_lock_releases_before_slow_admin_supplement_finishes(self):
        release = Event(); admin_started = Event(); primary_done = Event()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); period = query('AION2')['period']
            def call(container, script, requests, timeout):
                if script == 'primary_reader.py':
                    primary_done.set()
                else:
                    admin_started.set()
                    if not release.wait(3):
                        raise TimeoutError('fixture_admin_timeout')
                return {'range': {'period': period, 'status': 'available'}}
            namespace = dict(WEB=root, LOCK=RLock(), JOBS={}, PROFILE_MAP={'AION2': ('AION2', 'Aion 2', 826, 891, 'rpg')},
                             call=call, ThreadPoolExecutor=ThreadPoolExecutor, fcntl=fcntl, datetime=datetime,
                             timezone=timezone, time=time, profile_record=lambda *args: {}, dimensions=lambda value: {},
                             publish_cache=Mock())
            capture = function('capture', namespace)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(capture, dict(query('AION2'), baseSnapshotId='catalog'), 'native')
                try:
                    self.assertTrue(primary_done.wait(1)); self.assertTrue(admin_started.wait(1))
                    with (root / 'collector.lock').open('a+b') as lock:
                        deadline = time.monotonic() + 1
                        while True:
                            try:
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                break
                            except BlockingIOError:
                                if time.monotonic() >= deadline:
                                    self.fail('slow Admin read retained the browser collector lock')
                                time.sleep(.01)
                finally:
                    release.set(); future.result(timeout=2)
            namespace['publish_cache'].assert_called_once()


if __name__ == '__main__':
    unittest.main()
