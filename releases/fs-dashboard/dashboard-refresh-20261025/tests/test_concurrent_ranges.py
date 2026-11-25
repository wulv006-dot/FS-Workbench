"""Real HTTP threads and Linux file locks exercise independent range readers."""
import ast
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from threading import Event, Lock, RLock, Thread
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
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
    names={name,'_capture'} if name=='capture' else {name}
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    namespace.setdefault('maintenance_admission',nullcontext)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), name, 'exec'), namespace)
    return namespace[name]


def query(profile):
    return dict(profile=profile, start='2026-10-27', end='2026-10-27', grain='day',
                site='all-websites', cacheSeconds=600,
                period=dict(start='2026-10-27 00:00', end='2026-10-28 00:00'))


def record(q):
    return dict(status='available', period=q['period'], currency='USD', metrics={},
                capturedAt=datetime.now(timezone.utc).isoformat())


class ConcurrentRanges(unittest.TestCase):
    def test_slow_order_queue_does_not_block_fifth_cold_admin_scope(self):
        release=Event();admin_done=[Event() for _ in range(5)];calls=[]
        def admin(q):
            calls.append(q['profile']);return record(q)
        def order(q):
            release.wait(5);return record(q)
        cache=SummaryCache(admin,order,{str(i):(str(i),str(i)) for i in range(5)})
        cache.persist_complete=lambda q:admin_done[int(q['profile'])].set()
        try:
            for i in range(4):
                cache.get_live(query(str(i)));self.assertTrue(admin_done[i].wait(1))
            cache.get_live(query('4'))
            self.assertTrue(admin_done[4].wait(1),'Order-only pending scopes blocked an independent Admin cold read')
            code,value=cache.get_live(query('4'));self.assertEqual(code,200)
            self.assertEqual(value['sources']['Order']['status'],'unavailable')
            self.assertEqual(value['sources']['Order']['phase'],'deferred')
            self.assertEqual(calls.count('4'),1)
            self.assertLessEqual(sum(any(s['state']=='pending' for n,s in e.items() if n!='Admin') for e in cache.entries.values()),4)
        finally:release.set();cache.close()

    def test_source_rate_and_pending_budgets_are_independent_and_bounded(self):
        class Pool:
            def __init__(self):self.jobs=[]
            def submit(self,*args):self.jobs.append(args)
        cache=SummaryCache(record,record,{'0':('0','0')},clock=lambda:0)
        cache.close();cache.pools={name:Pool() for name in cache.readers};cache.persist_complete=lambda q:None
        cache.starts['Order'][:]=[0]*6
        code,_=cache.get_live(query('0'));self.assertEqual(code,202)
        self.assertEqual(len(cache.pools['Admin'].jobs),1);self.assertFalse(cache.pools['Order'].jobs)
        for i in range(1,5):
            cache.profiles[str(i)]=(str(i),str(i));cache.get_live(query(str(i)))
        self.assertEqual(len(cache.pools['Admin'].jobs),4)
        self.assertEqual(cache.get_live(query('4'))[0],429)
        self.assertFalse(cache.pools['Order'].jobs)

    @unittest.skipIf(fcntl is None, 'requires real Linux flock')
    def test_profit_target_lock_is_nonblocking_process_shared_stable_and_failure_safe(self):
        from channel_effects import ChannelService
        import select
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/('a'*24+'.json');other=root/('b'*24+'.json')
            service=ChannelService(root,lambda user:True);service.pool.shutdown()
            ready_r,ready_w=os.pipe();release_r,release_w=os.pipe();pid=os.fork()
            if pid==0:
                try:
                    os.close(ready_r);os.close(release_w)
                    with service.capture_lock(target):
                        os.write(ready_w,b'1');os.read(release_r,1)
                    os._exit(0)
                except BaseException:os._exit(2)
            os.close(ready_w);os.close(release_r)
            try:
                self.assertTrue(select.select([ready_r],[],[],2)[0]);self.assertEqual(os.read(ready_r,1),b'1')
                before=time.monotonic()
                with self.assertRaises(BlockingIOError):
                    with service.capture_lock(target):self.fail('same target reader duplicated')
                self.assertLess(time.monotonic()-before,.2)
                with service.capture_lock(other):pass
                path=root/('.capture-'+target.stem+'.lock');inode=path.stat().st_ino
            finally:
                os.write(release_w,b'1');os.close(release_w);os.close(ready_r)
                _,status=os.waitpid(pid,0);self.assertEqual(status,0)
            with self.assertRaisesRegex(ValueError,'fixture read failed'):
                with service.capture_lock(target):raise ValueError('fixture read failed')
            with service.capture_lock(target):self.assertEqual(path.stat().st_ino,inode)
            self.assertFalse(target.exists())

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
            first=get({});second=get({})
            self.assertEqual((first[0],second[0]),(202,202))
            self.assertEqual((first[1]['retryAfter'],second[1]['retryAfter']),(2,2))
            self.assertEqual(first[1]['rangeId'],second[1]['rangeId'])
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


class MaintenanceGateTests(unittest.TestCase):
    def gate(self):
        path=SOURCE.parents[1]/'cache-archive-retention-20261025/source/cache_retention.py'
        spec=importlib.util.spec_from_file_location('maintenance_cache_contract',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

    def test_maintenance_rejects_new_summary_and_native_work_but_keeps_native_warm_status_fast(self):
        from contextlib import contextmanager
        @contextmanager
        def closed():raise BlockingIOError('maintenance_in_progress');yield
        reader=Mock();cache=SummaryCache(reader,reader,{'FC27':('FC27','FC27')});cache.admission=closed
        try:
            code,value=cache.get_live(query('FC27'));self.assertEqual(code,429)
            self.assertTrue(all(s['error']=='maintenance_in_progress' for s in value['sources'].values()))
            reader.assert_not_called();self.assertFalse(any(cache.starts.values()))
        finally:cache.close()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);q=dict(query('FC27'),baseSnapshotId='catalog')
            ident=hashlib.sha256(encoded(q)).hexdigest();jobs={};starts=[]
            namespace=dict(CACHE=root,snapshot=lambda:dict(snapshotId='catalog'),query=lambda p,d:q,
                hashlib=hashlib,encoded=encoded,json=json,datetime=datetime,timezone=timezone,time=time,
                LOCK=RLock(),JOBS=jobs,STARTS=starts,SUMMARY=SimpleNamespace(pools={'Admin':Mock()}),POOL=Mock(),
                maintenance_admission=closed,capture=Mock())
            get=function('get_range_live',namespace)
            self.assertEqual(get({})[0],503);self.assertFalse(jobs);self.assertFalse(starts)
            jobs[ident]=dict(status='pending');self.assertEqual(get({})[0],202);jobs.clear()
            (root/(ident+'.json')).write_text(json.dumps(dict(generatedAt=datetime.now(timezone.utc).isoformat(),value='old-complete')))
            self.assertEqual(get({})[1]['value'],'old-complete');namespace['capture'].assert_not_called()

    def test_unavailable_maintenance_lease_marks_capture_failed_instead_of_permanent_pending(self):
        from contextlib import contextmanager
        @contextmanager
        def broken():raise ValueError('fixture unsafe inode');yield
        reader=Mock();cache=SummaryCache(reader,reader,{'FC27':('FC27','FC27')});cache.admission=broken
        try:
            slot=dict(state='pending');cache.capture('Admin',query('FC27'),slot)
            self.assertEqual((slot['state'],slot['phase'],slot['error']),('unavailable','failed','source_read_failed'))
            reader.assert_not_called()
        finally:cache.close()

    def test_complete_warm_summary_and_native_survive_deferred_archive_write(self):
        from contextlib import contextmanager
        @contextmanager
        def closed():raise BlockingIOError('maintenance_in_progress');yield
        warm=dict(status='available',metrics={'orders':7});save=Mock()
        archive=SimpleNamespace(read=lambda *args:None,save=save,summary_key=lambda q:{},native_key=lambda *args:{},
            complete_summary=lambda v:True,complete_native=lambda v:True,derive_summary=lambda q:None,rebind_native=lambda v,q:v)
        cache=SummaryCache(record,record,{'FC27':('FC27','FC27')});cache.admission=closed
        try:
            with patch.dict(sys.modules,daily_archive=archive),patch.object(cache,'get_live',return_value=(200,dict(warm))):
                code,value=cache.get(query('FC27'))
                self.assertEqual((code,value['status'],value['metrics']),(200,'available',{'orders':7}))
                self.assertTrue(value['archive']['refreshDeferred'])
                namespace=dict(maintenance_admission=closed,query=lambda *args:query('FC27'),snapshot=lambda:{},
                    PROFILE_MAP={'FC27':('FC27','FC27')},get_range_live=lambda *args,**kwargs:(200,dict(warm)))
                native=function('get_range',namespace)
                code,value=native({})
                self.assertEqual((code,value['status'],value['metrics']),(200,'available',{'orders':7}))
                self.assertTrue(value['archive']['refreshDeferred']);save.assert_not_called()
        finally:cache.close()

    @unittest.skipIf(fcntl is None,'requires real Linux shared maintenance lease')
    def test_shared_reads_and_existing_controller_submit_coexist_exclusive_blocks_new_keys(self):
        import stat
        from contextlib import contextmanager
        gate=self.gate()
        path=SOURCE.parents[1]/'fc-coins-workflow-20261022/source/controller.py'
        node=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='admission_guard')
        namespace=dict(contextmanager=contextmanager,Path=Path,os=os,stat=stat)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'existing-admission-guard','exec'),namespace)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with gate.maintenance_reader(root),gate.maintenance_reader(root),namespace['admission_guard'](root/'admission.lock') as accepted:
                self.assertTrue(accepted)
                with (root/'admission.lock').open('a+b') as writer:
                    with self.assertRaises(BlockingIOError):fcntl.flock(writer,fcntl.LOCK_EX|fcntl.LOCK_NB)
            inode=(root/'admission.lock').stat().st_ino
            with (root/'admission.lock').open('a+b') as writer:
                fcntl.flock(writer,fcntl.LOCK_EX|fcntl.LOCK_NB)
                before=time.monotonic()
                with self.assertRaisesRegex(BlockingIOError,'maintenance_in_progress'):
                    with gate.maintenance_reader(root):self.fail('new key admitted during publication')
                with namespace['admission_guard'](root/'admission.lock') as accepted:self.assertFalse(accepted)
                self.assertLess(time.monotonic()-before,.2)
            self.assertEqual((root/'admission.lock').stat().st_ino,inode)

    @unittest.skipIf(fcntl is None,'requires real Linux fork and lock ordering')
    def test_legacy_outer_global_owner_releases_on_nonblocking_maintenance_gate(self):
        import select
        gate=self.gate()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with gate.maintenance_reader(root):pass
            ready_r,ready_w=os.pipe();go_r,go_w=os.pipe();done_r,done_w=os.pipe();pid=os.fork()
            if pid==0:
                try:
                    os.close(ready_r);os.close(go_w);os.close(done_r)
                    with (root/'collector.lock').open('a+b') as outer:
                        fcntl.flock(outer,fcntl.LOCK_EX|fcntl.LOCK_NB);os.write(ready_w,b'1');os.read(go_r,1)
                        try:
                            with gate.maintenance_reader(root):result=b'bad'
                        except BlockingIOError:result=b'busy'
                    os.write(done_w,result);os._exit(0)
                except BaseException:os._exit(2)
            os.close(ready_w);os.close(go_r);os.close(done_w)
            writer=(root/'admission.lock').open('a+b')
            try:
                self.assertTrue(select.select([ready_r],[],[],2)[0]);self.assertEqual(os.read(ready_r,1),b'1')
                fcntl.flock(writer,fcntl.LOCK_EX|fcntl.LOCK_NB);os.write(go_w,b'1')
                self.assertTrue(select.select([done_r],[],[],1)[0],'outer global and maintenance gate formed a wait cycle')
                self.assertEqual(os.read(done_r,4),b'busy')
                with (root/'collector.lock').open('a+b') as outer:fcntl.flock(outer,fcntl.LOCK_EX|fcntl.LOCK_NB)
            finally:
                writer.close()
                for fd in (ready_r,go_w,done_r):os.close(fd)
                _,status=os.waitpid(pid,0);self.assertEqual(status,0)


class TransactionLockScopeTests(unittest.TestCase):
    def atomic(self):
        # Import-only dependencies are not exercised by a non-profit snapshot fixture.
        def unused(*args, **kwargs):
            raise AssertionError('profit history is outside the lock fixture')
        daily = ModuleType('profit_daily'); daily.validate_history = unused
        adapter = ModuleType('profit_reader_adapter'); adapter.contracts_from_snapshot = unused
        spec = importlib.util.spec_from_file_location('atomic_lock_contract', SOURCE / 'atomic_snapshot.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'profit_daily': daily, 'profit_reader_adapter': adapter}):
            spec.loader.exec_module(module)
        return module

    def value(self):
        period = {'start': '2026-10-27 00:00', 'end': '2026-10-28 00:00'}
        primary = dict(system='order.p2pah.cn', status='available', period=period,
                       filters={'gid': '826'}, capturedAt='2026-10-28T00:00:00+00:00')
        return dict(timezone='Asia/Shanghai', currency='USD', scopeApproved=True,
                    scopeContractId='lock-contract', requiredProfiles=['AION2'],
                    profiles={'AION2': dict(period=period, primary=primary,
                        metrics={'orders': {'value': 1, 'source': 'primary'},
                                 'revenueUsd': {'value': 5, 'source': 'primary'}})})

    def order(self, root, reader, atomic=None):
        text = (SOURCE / 'collector.py').read_text(encoding='utf8')
        node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == 'order_call')
        namespace = {'WEB': root, 'call': reader, 'OrderSourceBusy': (atomic or self.atomic()).OrderSourceBusy}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'actual-collector-order-call', 'exec'), namespace)
        return namespace['order_call']

    def test_original_live_publish_validation_and_atomic_functions_are_unchanged(self):
        text = (SOURCE / 'atomic_snapshot.py').read_text(encoding='utf8')
        tree = ast.parse(text)
        expected = {'encoded': 'e3a6eebb31055e93e35a3e5ae9f39af8fcc2b823d4f0a7c10889774036d0c5af',
                    'atomic_write': '8c4333e0444d4e8afbeb81381e165d7820ac5d10d51733d0d75705585a917287',
                    'validate': '3ce217f7c3b82ae88825a470e4fb7aac2ff70a1f037acd51af5aa6954edf3532',
                    'publish': '28d8cd5d904bdae7bee072bdd7c553ab6b18ed3f520aeb680edb6a352437a0df'}
        for name, digest in expected.items():
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertEqual(hashlib.sha256(ast.get_source_segment(text, node).encode()).hexdigest(), digest)

    def test_transaction_selects_snapshot_lock_and_only_real_order_calls_use_browser_lock(self):
        tree = ast.parse((SOURCE / 'collector.py').read_text(encoding='utf8'))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        entry = next(n for n in calls if n.func.id == 'run_once')
        self.assertEqual({k.arg: ast.literal_eval(k.value) for k in entry.keywords}, {'lock_name': 'transaction-snapshot.lock'})
        self.assertEqual({n.args[0].value for n in calls if n.func.id == 'order_call'},
                         {'primary_reader.py', 'fc_category_reader.py', 'profit_daily_reader.py'})
        self.assertEqual({n.args[1].value for n in calls if n.func.id == 'call' and isinstance(n.args[1], ast.Constant)},
                         {'supplement_reader.py', 'fc_product_reader.py'})

    @unittest.skipIf(fcntl is None, 'requires real Linux flock')
    def test_blocked_admin_releases_browser_but_same_snapshot_writer_stays_exclusive(self):
        atomic = self.atomic(); started = Event(); release = Event()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); reader = Mock(return_value={}); order = self.order(root, reader, atomic)
            def collect():
                order('primary_reader.py', [{'key': 'original'}], 900)
                started.set()
                if not release.wait(3):raise TimeoutError('fixture_admin_timeout')
                return self.value()
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(atomic.run_once, root, collect, lock_name='transaction-snapshot.lock')
                try:
                    self.assertTrue(started.wait(1))
                    with (root / 'collector.lock').open('a+b') as browser:
                        fcntl.flock(browser, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    second = Mock(return_value=self.value())
                    self.assertEqual(atomic.run_once(root, second, lock_name='transaction-snapshot.lock'),
                                     {'status': 'skipped', 'reason': 'already_running'})
                    second.assert_not_called(); self.assertFalse((root / 'current.json').exists())
                finally:
                    release.set(); manifest = future.result(timeout=2)
            reader.assert_called_once_with(None, 'primary_reader.py', [{'key': 'original'}], 900)
            self.assertEqual(json.loads((root / 'current.json').read_text())['snapshotId'], manifest['snapshotId'])
            self.assertEqual(json.loads((root / 'attempt.json').read_text())['status'], 'success')

    @unittest.skipIf(fcntl is None, 'requires real Linux flock')
    def test_default_caller_still_holds_old_browser_lock_and_preserves_failure_semantics(self):
        atomic = self.atomic(); entered = Event(); release = Event()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def collect():
                entered.set()
                if not release.wait(3):raise TimeoutError('fixture_timeout')
                return self.value()
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(atomic.run_once, root, collect)
                try:
                    self.assertTrue(entered.wait(1))
                    with (root / 'collector.lock').open('a+b') as lock:
                        with self.assertRaises(BlockingIOError):fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:release.set(); future.result(timeout=2)
            def busy():raise BlockingIOError('original_default_failure')
            with self.assertRaises(BlockingIOError):atomic.run_once(root, busy)
            self.assertEqual(json.loads((root / 'attempt.json').read_text())['status'], 'failed')
            with self.assertRaisesRegex(ValueError, 'unknown_snapshot_lock'):
                atomic.run_once(root, Mock(), lock_name='../other.lock')

    @unittest.skipIf(fcntl is None, 'requires real Linux flock')
    def test_order_same_session_excludes_second_batch_and_releases_lock(self):
        entered = Event(); release = Event()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def read(*args):
                entered.set()
                if not release.wait(3):raise TimeoutError('fixture_order_timeout')
                return {'original': True}
            reader = Mock(side_effect=read); order = self.order(root, reader)
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(order, 'primary_reader.py', [], 900)
                try:
                    self.assertTrue(entered.wait(1))
                    with self.assertRaises(BlockingIOError):order('fc_category_reader.py', [], 600)
                    self.assertEqual(reader.call_count, 1)
                finally:release.set(); self.assertEqual(first.result(timeout=2), {'original': True})
            with (root / 'collector.lock').open('a+b') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for script in ('supplement_reader.py', 'fc_product_reader.py'):
                with self.assertRaisesRegex(ValueError, 'order_reader_required'):order(script, [], 600)
            self.assertEqual(reader.call_count, 1)

    @unittest.skipIf(fcntl is None, 'requires real Linux flock')
    def test_source_busy_is_deferred_and_read_failure_keeps_original_history_and_unlocks(self):
        atomic = self.atomic()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); previous = atomic.publish(root, self.value())
            original = (root / 'current.json').read_bytes()
            body = (root / previous['path']).read_bytes()
            reader = Mock(); order = self.order(root, reader, atomic)
            with (root / 'collector.lock').open('a+b') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = atomic.run_once(root, lambda: order('primary_reader.py', [], 900), lock_name='transaction-snapshot.lock')
                self.assertEqual(result, {'status': 'skipped', 'reason': 'collector_busy'})
                reader.assert_not_called()
            self.assertEqual(json.loads((root / 'attempt.json').read_text())['status'], 'deferred')
            for error in (TimeoutError('fixture_read_failed'), BlockingIOError('unrelated_reader_io_failure')):
                reader.side_effect = error
                with self.assertRaises(type(error)):
                    atomic.run_once(root, lambda: order('primary_reader.py', [], 900), lock_name='transaction-snapshot.lock')
                self.assertEqual(json.loads((root / 'attempt.json').read_text())['status'], 'failed')
            self.assertEqual((root / 'current.json').read_bytes(), original)
            self.assertEqual((root / previous['path']).read_bytes(), body)
            for name in ('collector.lock', 'transaction-snapshot.lock'):
                with (root / name).open('a+b') as lock:fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


if __name__ == '__main__':
    unittest.main()
