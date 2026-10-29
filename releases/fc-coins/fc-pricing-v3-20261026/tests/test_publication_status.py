"""A V3 public-confirmed write must supersede the previous Order audit."""
import ast
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'source/fc27_cloud_api.py'
function = next(node for node in ast.parse(SOURCE.read_text(encoding='utf-8')).body
                if isinstance(node, ast.FunctionDef) and node.name == 'publication_view')


class PublicationStatusTest(unittest.TestCase):
    def test_latest_v3_public_confirmation_is_compared(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'executions').mkdir()
            (root / 'previews').mkdir()
            old, new = '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002'
            for ident, when, status, console in ((old, '2026-10-29T14:00:00+00:00', 'CONFIRMED', '0.0715'),
                                                 (new, '2026-10-29T15:00:00+00:00', 'PUBLIC_CONFIRMED', '0.0782')):
                audit = {'execution_id': ident, 'created_at': when, 'status': status, 'sync_confirmed': True,
                         'after': {'rows': [{'platform': platform, 'b2c': console if platform != 'PC' else '0.0831'}
                                            for platform in ('PS', 'XBOX', 'PC')]}}
                (root/'executions'/f'{ident}.json').write_text(json.dumps(audit), encoding='utf-8')
            namespace = {'ROOT': root, 'datetime': datetime, 'Decimal': Decimal,
                         'ROUND_HALF_UP': ROUND_HALF_UP, 'InvalidOperation': InvalidOperation,
                         'valid_id': lambda value: value in {old, new},
                         'read_json': lambda path: json.loads(path.read_text(encoding='utf-8'))}
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), 'exec'), namespace)
            storefront = {'rows': {platform: {'status': 'ok', 'package_usd': price,
                                              'checked_at': '2026-10-29T15:01:00+00:00'}
                                    for platform, price in (('PS', '7.82'), ('XBOX', '7.82'), ('PC', '8.31'))}}
            result = namespace['publication_view'](storefront)
            self.assertEqual((result['status'], result['execution_id']), ('matched', new))
            self.assertEqual([row['status'] for row in result['platforms']], ['matched'] * 3)


if __name__ == '__main__':
    unittest.main()
