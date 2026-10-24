import ast, json, sys, tempfile, unittest, uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
SOURCE = Path(__file__).parents[1] / 'source/automation_tick.py'

class WriterResultTests(unittest.TestCase):

    def test_hook_rejection_retains_original_shape(self):
        nodes = ast.parse((SOURCE.parent / 'price_writer.py').read_text()).body
        main = next((n for n in nodes if isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name) and (n.test.left.id == '__name__')))

        class MissingRequest:

            def read_text(self, **kw):
                raise ValueError('hook_scope_paused')
        output = []
        env = {'__name__': '__main__', 'Path': lambda path: MissingRequest(), 'json': json, 'print': output.append}
        with self.assertRaises(SystemExit):
            exec(compile(ast.Module(body=[main], type_ignores=[]), 'writer-main', 'exec'), env)
        self.assertEqual(json.loads(output[0]), {'status': 'FAILED', 'reason': 'hook_scope_paused'})
