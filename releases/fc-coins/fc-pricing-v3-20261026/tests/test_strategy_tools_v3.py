import hashlib
import importlib.util
import json
import sqlite3
import sys
import types
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))


def load_strategy_tools():
    pilot = types.ModuleType('pilot')
    pilot.encoded = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)
    pilot.digest = lambda value: hashlib.sha256(pilot.encoded(value).encode()).hexdigest()
    with patch.dict(sys.modules, {'pilot': pilot}):
        spec = importlib.util.spec_from_file_location('strategy_tools_v3_under_test', SOURCE / 'strategy_tools.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class StrategyToolsV3(unittest.TestCase):
    def test_advertised_tools_keep_v3_decision_and_legacy_review_without_old_band_selector(self):
        tools = load_strategy_tools()
        schemas = tools.schemas()
        names = [tool['function']['name'] for tool in schemas]
        self.assertEqual(len(names), len(tools.NAMES))
        self.assertIn('mcp__fcro__fs_pricing_control', names)
        self.assertIn('mcp__fcro__fs_strategy_read_review', names)
        self.assertNotIn('mcp__fcro__fs_pricing_simulate_candidate', names)
        self.assertIn('simulation_read', str(schemas[-1]))
        self.assertNotIn('at_least_40', str(schemas))
        self.assertNotIn('shared-band', str(schemas))

    def test_new_research_idea_uses_v3_snapshot_and_old_draft_remains_readable(self):
        tools = load_strategy_tools()
        run = '00000000-0000-4000-8000-000000000070'
        idea = dict(name='basket signal', description='Review observed basket mix', entry_conditions='complete order data',
                    pricing_formula='No production formula until evaluated', stop_conditions='source coverage falls')
        args = dict(project='FC27', intent='draft_only', snapshot_id=run, question='How does basket mix change?',
                    hypothesis='Larger baskets may change revenue sensitivity', risk_notes='Initial estimate only',
                    review_plan='Compare mature price windows', evidence_refs=['pricing:source'], rule_idea=idea)
        bridge = Mock()
        bridge.capabilities.return_value = dict(snapshot_id=run)
        with sqlite3.connect(':memory:') as db, patch.object(tools, 'text'):
            db.row_factory = sqlite3.Row
            result = tools.create(db, 'wulv', 'task-1', args, {'pricing:source'}, bridge, datetime.now(timezone.utc))
            self.assertEqual(result['research_state'], 'DRAFT')
            self.assertFalse(result['execution_authorized'])
            review = tools.read_review(db, 'wulv', dict(decision_id=result['id'], start='2026-10-01', end='2026-10-31'), [])
            self.assertEqual(review['research_state'], 'DRAFT')
            old = dict(review_plan='Original review remains', band_changes=[dict(tier='at_least_40')])
            old_id = tools.digest(dict(old='historical'))
            db.execute('INSERT INTO strategy_drafts VALUES(?,?,?,?,?,?,?)',
                       (old_id, 'wulv', 'FC27', 'old-task', tools.encoded(old), tools.digest(old), datetime.now(timezone.utc).isoformat()))
            historical = tools.read_review(db, 'wulv', dict(decision_id=old_id, start='2026-10-01', end='2026-10-31'), [])
            self.assertEqual(historical['research_state'], 'EVIDENCE_READY')

    def test_disabled_legacy_control_still_allows_v3_readback_but_blocks_recommendation(self):
        tools = load_strategy_tools()
        scope = Mock()
        scope.book.capture_id = 'fc-detail-test'
        scope.clock.return_value = datetime.now(timezone.utc)
        @contextmanager
        def connection():
            with sqlite3.connect(':memory:') as db:
                tools.schema(db)
                db.execute('INSERT INTO strategy_control VALUES (?,?)', ('wulv', 0))
                yield db
        scope.tasks.db.side_effect = connection
        with patch('pricing_operations.call', return_value=dict(status='available')) as operate:
            result = tools.call(scope, 'wulv', 'task', 'lease', 'fs.pricing.control',
                                dict(action='simulation_read', simulation_id='00000000-0000-4000-8000-000000000071'))
            self.assertEqual(result['status'], 'available')
            self.assertEqual(operate.call_count, 1)
            with self.assertRaisesRegex(PermissionError, 'strategy_control_disabled'):
                tools.call(scope, 'wulv', 'task', 'lease', 'fs.pricing.control', dict(action='recommend'))


if __name__ == '__main__':
    unittest.main()
