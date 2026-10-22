"""Offline host/tool contracts. Runtime/model and browser acceptance are separate."""
import ast
from copy import deepcopy
from datetime import datetime
import importlib.util
from pathlib import Path
import re
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch
from unittest import TestCase

import test_users as fixtures
from test_users import order
from user_contract import digest
from user_tools import invoke

ROOT = Path(__file__).resolve().parents[4]
LOCAL = ROOT / '.agent_runtime/fs-user-analytics-20261022/integration'


def source(path, local):
    candidate = ROOT / path
    return candidate if candidate.is_file() else LOCAL / local


class Integration(TestCase):
    setUp, load, query = fixtures.Users.setUp, fixtures.Users.load, fixtures.Users.query
    def test_native_and_research_use_same_snapshot_and_keep_original_tools(self):
        self.load([order(1, '2026-10-01')])
        frozen = self.query()
        args = dict(snapshot_id=frozen['snapshot_id'])
        native_path = source('releases/fs-dashboard/hermes-server-unify-20261022/fs_readonly/__init__.py', 'fs_readonly.py')
        spec = importlib.util.spec_from_file_location('users_native_fixture', native_path)
        native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
        original = {'fs_get_data_catalog', 'fs_query_native_statistics', 'fs_query_es_order_structure', 'fs_query_discount_analysis', 'fs_query_product_orders'}
        self.assertTrue(original.issubset(native.TOOLS))
        from user_http import get
        def through_http(path, query):
            status, value = get(self.service, path, {k: [str(v)] for k, v in query.items()}, 'admin')
            self.assertEqual(status, 200)
            return value
        with patch.object(native, 'read', through_http):
            normal = native.call('fs_query_user_analytics', args)
        research_path = source('releases/fs-dashboard/fc-coins-workflow-20261022/source/research.py', 'research.py')
        tree = ast.parse(research_path.read_text('utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ResearchBook' or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'RESEARCH_NAMES' for t in n.targets) or isinstance(n, ast.FunctionDef) and n.name == 'model_evidence']
        env = dict(deepcopy=deepcopy, datetime=datetime, re=re, threading=threading, digest=digest)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(research_path), 'exec'), env)
        book = env['ResearchBook'](dict(snapshot_id='fc-detail-fixture', as_of='2026-10-22T12:00:00+08:00'), {}, {})
        book.user_analytics = lambda query: invoke(self.service, 'admin', query)
        with patch.dict(sys.modules, {'evidence_access': SimpleNamespace(model_view=lambda value: value)}):
            researched = book.call('fc.query_user_analytics', args)
        self.assertIn('fc.run_pricing_workflow', env['RESEARCH_NAMES'])
        self.assertEqual(researched['data']['snapshot_id'], normal['snapshot_id'])
        self.assertEqual(researched['data']['metrics'], normal['metrics'])
        self.assertEqual(researched['snapshot_id'], frozen['snapshot_id'])
        self.assertEqual(invoke(self.service, 'admin', {'evidence_id': frozen['evidence_id']})['metrics'], frozen['metrics'])

    def test_users_reuse_current_analytics_resource_and_admin_boundary(self):
        path = source('opt/fs-access-policy/rbac.py', 'rbac.py')
        spec = importlib.util.spec_from_file_location('users_rbac_fixture', path)
        rbac = importlib.util.module_from_spec(spec); spec.loader.exec_module(rbac)
        self.assertEqual(rbac.resolve_resource('/dashboard/users/'), 'unified-business')
        self.assertEqual(rbac.resolve_resource('/dashboard/users/private.json'), 'unified-business')
        self.assertEqual(rbac.evaluate(rbac.default_policy(), '', 'GET', '/dashboard/users/').code, 401)
