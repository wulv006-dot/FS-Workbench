"""V3 edit controls follow the existing writer role, independently of retired bands."""
import ast
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))


class V3UiPermissionTest(unittest.TestCase):
    def test_read_and_writer_roles(self):
        tree = ast.parse((SOURCE / 'fc27_cloud_api.py').read_text(encoding='utf-8'))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'automation_view')
        namespace = {'WRITERS': {'wulv'}, 'ROOT': Path('/unused')}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<automation_view>', 'exec'), namespace)
        with patch('fc_pricing_v3.monitoring.projection', return_value={'enabled': True, 'schedule': {}}):
            writer = namespace['automation_view']({'system_enabled': True}, 'wulv')
            reader = namespace['automation_view']({'system_enabled': True}, 'observer')
        self.assertTrue(writer['can_manage_v3'])
        self.assertFalse(reader['can_manage_v3'])
        self.assertFalse(writer['can_edit_discount_rules'])
        self.assertFalse(reader['can_edit_discount_rules'])
        script = (SOURCE / 'fc-pricing-v3.js').read_text(encoding='utf-8')
        self.assertIn('(await response.json()).can_manage_v3===true', script)
        self.assertNotIn('(await response.json()).can_edit_discount_rules', script)


if __name__ == '__main__':
    unittest.main()
