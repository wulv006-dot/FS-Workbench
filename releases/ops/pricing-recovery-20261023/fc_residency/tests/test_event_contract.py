import ast
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
import lootbar_server_collector as collector
import test_lootbar_server_collector as fixtures


BASELINE = Path(__file__).resolve().parents[1] / 'baseline'


class EventContractTests(unittest.TestCase):
    def run_main(self):
        browser = fixtures.FakeBrowser()
        api = types.ModuleType('playwright.sync_api')
        api.TimeoutError = fixtures.FakePlaywrightTimeoutError
        api.sync_playwright = lambda: fixtures.FakePlaywrightManager(browser)
        package = types.ModuleType('playwright')
        package.sync_api = api
        events = []
        def read(page, _source):
            return fixtures.snapshot({'PS':'PS4/5', 'XBOX':'Xbox', 'PC':'PC'}[page.platform])
        with patch.dict(sys.modules, {'playwright':package, 'playwright.sync_api':api}), \
             patch.object(collector, '_cdp_http', side_effect=browser.contexts[0].cdp_http), \
             patch.object(collector, '_read_snapshot', side_effect=read), \
             patch.object(collector, '_platform_controls', return_value=[{'label':s} for s in ('ps4/5','xbox','pc')]), \
             patch.object(collector.time, 'sleep'), \
             patch.object(collector, 'emit', side_effect=lambda stage,**fields:events.append(dict(stage=stage,**fields))), \
             patch.object(sys, 'argv', ['lootbar_server_collector.py']):
            status = collector.main()
        return status, events

    def shell_parse(self, events):
        path = BASELINE / 'collect_lootbar.sh'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
            '21dcec3f8dcae2dd034355d3dfa9fdc1b497601a23cd8f1ef221ef7504b03dc3')
        parser = path.read_text(encoding='utf-8').split("if summary=$(python3 - \"$trace\" <<'PY'\n",1)[1].split('\nPY\n); then',1)[0]
        with tempfile.TemporaryDirectory() as folder:
            trace = Path(folder) / 'events.jsonl'
            trace.write_text(''.join(json.dumps(event)+'\n' for event in events), encoding='utf-8')
            output, errors = io.StringIO(), io.StringIO()
            code = 0
            with patch.object(sys, 'argv', ['-', str(trace)]), \
                 redirect_stdout(output), redirect_stderr(errors):
                try:
                    exec(compile(parser, str(path) + '::summary', 'exec'), {})
                except SystemExit as exit_status:
                    code = exit_status.code or 0
            return types.SimpleNamespace(returncode=code, stdout=output.getvalue(), stderr=errors.getvalue())

    def snapshot_parser(self):
        path = BASELINE / 'snapshot_layer.py'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
            '1d8a40c2bd0489f36444e74abc6e8ff3bc8543522cb5c58dfe305e052b36f4fd')
        tree = ast.parse(path.read_text(encoding='utf-8'))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {'positive', 'lootbar_snapshots'}]
        namespace = dict(datetime=datetime, timezone=timezone, Decimal=Decimal,
                         InvalidOperation=InvalidOperation, PLATFORMS=('PS','XBOX','PC'),
                         LOOTBAR_URL=collector.BASE_URL)
        exec(compile(ast.Module(body=nodes,type_ignores=[]), str(path), 'exec'), namespace)
        return namespace['lootbar_snapshots']

    def test_real_main_parks_before_complete_and_active_shell_parser_accepts(self):
        status, events = self.run_main()
        self.assertEqual(status, 0)
        stages = [event['stage'] for event in events]
        self.assertLess(stages.index('ps_restored'), stages.index('product_page_parked'))
        self.assertEqual(stages[-1], 'complete')
        self.assertEqual(stages.count('complete'), 1)
        parsed = self.shell_parse(events)
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        self.assertEqual(json.loads(parsed.stdout)['platforms'], ['PS','XBOX','PC'])
        rows = self.snapshot_parser()('test-run', events)
        self.assertEqual([row['platform'] for row in rows], ['PS','XBOX','PC'])
        self.assertTrue(all(row['status'] == 'valid' for row in rows))

    def test_actual_shell_and_snapshot_reject_an_event_after_complete(self):
        _, events = self.run_main()
        events.append({'stage':'product_page_parked'})
        self.assertNotEqual(self.shell_parse(events).returncode, 0)
        with self.assertRaisesRegex(ValueError, 'collector_incomplete'):
            self.snapshot_parser()('test-run', events)

    def test_real_main_keeps_valid_input_and_separate_resource_alarm_when_parking_fails(self):
        with patch.object(collector, '_park_product_page', side_effect=RuntimeError('private detail')):
            status, events = self.run_main()
        self.assertEqual(status, 0)
        self.assertEqual(events[-1]['stage'], 'complete')
        self.assertIn({'stage':'product_page_idle_failed','reason':'RuntimeError'}, events)
        self.assertNotIn('product_page_parked', [event['stage'] for event in events])
        self.assertEqual(self.shell_parse(events).returncode, 0)
        self.assertEqual(len(self.snapshot_parser()('test-run', events)), 3)

    def test_insufficient_remaining_deadline_skips_parking_and_keeps_valid_input(self):
        with patch.object(collector, '_release_product_document') as park, \
             patch.object(collector, 'COLLECT_TIMEOUT_SECONDS', 0.05):
            status, events = self.run_main()
        park.assert_not_called()
        self.assertEqual(status, 0)
        self.assertEqual(events[-1]['stage'], 'complete')
        self.assertIn({'stage':'product_page_idle_failed','reason':'insufficient_cleanup_budget'}, events)
        self.assertEqual(self.shell_parse(events).returncode, 0)
        self.assertEqual(len(self.snapshot_parser()('test-run', events)), 3)

    def test_bounded_parking_timeout_keeps_valid_input(self):
        original_goto = fixtures.FakePage.goto
        def goto(page, url, **kwargs):
            if url == collector.IDLE_URL:
                self.assertGreater(kwargs['timeout'], 0)
                self.assertLessEqual(kwargs['timeout'], 4000)
                raise fixtures.FakePlaywrightTimeoutError()
            return original_goto(page, url, **kwargs)
        with patch.object(fixtures.FakePage, 'goto', goto):
            status, events = self.run_main()
        self.assertEqual(status, 0)
        self.assertEqual(events[-1]['stage'], 'complete')
        self.assertIn({'stage':'product_page_idle_failed','reason':'FakePlaywrightTimeoutError'}, events)
        self.assertEqual(self.shell_parse(events).returncode, 0)
        self.assertEqual(len(self.snapshot_parser()('test-run', events)), 3)


if __name__ == '__main__':
    unittest.main()
