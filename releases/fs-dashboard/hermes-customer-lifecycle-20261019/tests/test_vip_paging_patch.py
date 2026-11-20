"""Exercise the actual Range dispatch branch without starting production services."""
import ast
from hashlib import sha256
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch as mock_patch
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'source'))
import vip_paging_patch

FIXTURE = ROOT.parent / 'order-email-export-20261111' / 'integration' / 'fixtures' / 'range_api.py'


def route(raw):
    tree = ast.parse(raw)
    branch = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                  and ast.unparse(node.test) == "uri.path == '/advisor' and parse_qs(uri.query).get('structure') == ['customer_tracking']")
    code = ast.parse('def route(self, uri): pass')
    code.body[0].body = [branch]
    mock = SimpleNamespace(get=lambda actor, params: (200, (actor, params)))
    context = {'parse_qs': parse_qs, 'CUSTOMER_TRACKING': mock}
    exec(compile(ast.fix_missing_locations(code), 'tracking_route', 'exec'), context)
    return context['route']


class VipPagingBudgetTest(unittest.TestCase):
    def test_full_preferred_continuation_reaches_controller(self):
        original = FIXTURE.read_bytes().replace(b'\r\n', b'\n')
        with mock_patch.object(vip_paging_patch, 'BASELINE_SHA', sha256(original).hexdigest()):
            candidate = vip_paging_patch.patch(original)
            with self.assertRaisesRegex(ValueError, 'vip_paging_range_baseline_changed'):
                vip_paging_patch.patch(candidate)
        self.assertEqual(sum(a != b for a, b in zip(original, candidate)), 1)
        params = {'mode':'hermes', 'structure':'customer_tracking', 'view':'vip_period', 'start':'2026-10-21',
                  'end':'2026-11-19', 'as_of':'2026-11-20T10:48:00+08:00', 'scope':'global_preferred',
                  'segment':'due', 'offset':'20'}
        replies = []
        handler = SimpleNamespace(headers={'X-Auth-User':'admin_fixture'}, reply=lambda *args: replies.append(args))
        uri = '/advisor?' + urlencode(params)
        route(original)(handler, urlsplit(uri))
        self.assertEqual(replies.pop(), (422, {'error':'invalid_tracking_request'}))
        route(candidate)(handler, urlsplit(uri))
        self.assertEqual(replies.pop(), (200, ('admin_fixture', {key:[value] for key, value in params.items()})))
        route(candidate)(handler, urlsplit(uri + '&offset=40'))
        self.assertEqual(replies.pop(), (422, {'error':'invalid_tracking_request'}))
