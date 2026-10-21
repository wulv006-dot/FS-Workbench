import ast
import sys
import threading
import types
import unittest
from unittest.mock import patch
from admin_read_patch import transform


FIXTURE = '''class SessionManager:
    def business_summary(self, game, start, end):
        from admin_summary import collect
        def existing_read(path, **kwargs):
            with self.lock:
                if self.status != "ready" or not self.token:
                    raise OSError("existing_session_unavailable")
                return self.request(path, token=self.token, **kwargs)
        return collect(existing_read, game, start, end)
    def marketing_summary(self, start, end):
        from admin_links import collect
        def existing_read(path, **kwargs):
            with self.lock:
                if self.status != "ready" or not self.token:
                    raise OSError("existing_session_unavailable")
                return self.request(path, token=self.token, **kwargs)
        return collect(existing_read, start, end)
    def new_customers(self, target):
        payload = {}
        with self.lock:
            if not self.ensure():
                raise RuntimeError("admin_es_auth_unavailable")
            status, raw = self.request("/admin/order.Order/orderStaticsDetailByEs", data=payload, token=self.token)
        return status, raw
    def daily_summary(self, target, game_id, product_type):
        payload = {}
        with self.lock:
            if not self.ensure():
                raise RuntimeError("admin_es_auth_unavailable")
            status, raw = self.request("/admin/order.Order/orderStaticsDetailByEs", data=payload, token=self.token)
        return status, raw
'''

CAPABILITY = '''    def fc_capability(self, query):
        if query['kind']=='cohort_paid_orders':
            from cohort_paid_source import collect
            args={}
            with self.lock:
                if not self.identity_ok(self.token):
                    return {'kind':'cohort_paid_orders','query':args,'status':'unavailable','reason':'existing_auth_unavailable'}
                return collect(lambda path,timeout:self.request(path,token=self.token,timeout=timeout),args)
        if query['kind']=='product_orders':
            from admin_product_orders import collect
            args=checked=query
            with self.lock:
                token=self.token
                if not self.identity_ok(token,timeout=10):
                    return {'status':'unavailable'}
                if 'model_id' in checked and 'platform' not in checked:
                    # The 540-second read runs after manager.lock is released.
                    pass
                else:
                    return collect(lambda path,timeout:self.request(path,token=token,timeout=timeout),args)
            return self.model_product(checked,token)
'''


class AdminReadPatchTests(unittest.TestCase):
    def test_capability_reads_release_lock_and_preserve_budgets(self):
        scope = {}
        exec(transform(FIXTURE + CAPABILITY), scope)
        manager = scope['SessionManager']()
        manager.lock = threading.RLock()
        manager.token = 'synthetic'
        manager.identity_ok = lambda *a, **k: True
        calls = []
        def request(path, **kwargs):
            self.assertFalse(manager.lock._is_owned())
            self.assertEqual(kwargs['timeout'], 180)
            calls.append(path)
            return {'status': 'complete'}
        manager.request = request
        manager.model_product = lambda *a: 'existing-model-job'
        module = types.SimpleNamespace(collect=lambda read, *a: read('/admin/read', 180))
        with patch.dict(sys.modules, {'cohort_paid_source': module, 'admin_product_orders': module}):
            manager.fc_capability({'kind': 'cohort_paid_orders'})
            manager.fc_capability({'kind': 'product_orders', 'platform': 'PS'})
            self.assertEqual(manager.fc_capability({'kind': 'product_orders', 'model_id': 'test'}), 'existing-model-job')
        self.assertEqual(len(calls), 2)

    def test_long_read_releases_identity_lock_and_keeps_failure_guard(self):
        scope = {}
        exec(transform(FIXTURE), scope)
        manager = scope['SessionManager']()
        manager.lock = threading.RLock()
        manager.status, manager.token = 'ready', 'synthetic'
        manager.ensure = lambda: True
        calls = []
        def request(path, **kwargs):
            self.assertFalse(manager.lock._is_owned())
            self.assertEqual(kwargs['timeout'], 90)
            self.assertEqual(kwargs['token'], 'synthetic')
            calls.append(path)
            return 200, b'{}'
        manager.request = request
        module = types.SimpleNamespace(collect=lambda read, *args: read('/admin/read'))
        with patch.dict(sys.modules, {'admin_summary': module, 'admin_links': module}):
            manager.business_summary('fc', '2026-10-01', '2026-10-21')
            manager.marketing_summary('2026-10-01', '2026-10-21')
            manager.new_customers('2026-10-21')
            manager.daily_summary('2026-10-21', 1327, '')
            manager.status = 'unavailable'
            with self.assertRaisesRegex(OSError, 'existing_session_unavailable'):
                manager.business_summary('fc', '2026-10-01', '2026-10-21')
        self.assertEqual(len(calls), 4)

    def test_changed_es_source_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'admin_read_source_changed'):
            transform(FIXTURE.replace('data=payload, token=self.token)', 'data=payload, token=self.token, extra=probe())', 1))
