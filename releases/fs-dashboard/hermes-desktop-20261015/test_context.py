import tempfile
import unittest
from pathlib import Path
from business_context import read_desktop_context
import importlib.util
import json
import hashlib
from datetime import date, timedelta
from types import SimpleNamespace


class ContextTest(unittest.TestCase):
    def test_freeze_update_missing_and_size(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(read_desktop_context(root), ('', None))
            path = root / 'desktop-business-context.md'
            path.write_text('已确认业务约定一', encoding='utf-8')
            frozen = read_desktop_context(root)
            path.write_text('已确认业务约定二', encoding='utf-8')
            self.assertEqual(frozen[0], '已确认业务约定一')
            self.assertNotEqual(frozen[1], read_desktop_context(root)[1])
            path.write_bytes(b'x' * 131073)
            with self.assertRaises(ValueError):
                read_desktop_context(root)

    def test_actual_controller_task_identity_freezes_business_version(self):
        source = (Path(__file__).parent / 'release/candidate/hermes/runtime/controller.py').read_text(encoding='utf-8')
        block = source[source.index('            book.background=self.proxy.background'):source.index('            with self.lock:', source.index('            book.background=self.proxy.background'))]
        code = '\n'.join(line[12:] for line in block.splitlines())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = root / 'desktop-business-context.md'
            scope = dict(self=SimpleNamespace(root=root, proxy=SimpleNamespace(background={})),
                         book=SimpleNamespace(capture_id='fixture', skills={'version': 'fixture'}),
                         body={'request_id': 'same-request', 'question': 'same question', 'start': '2026-10-01', 'end': '2026-10-02'},
                         digest=lambda value: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(),
                         date=date, timedelta=timedelta, POLICY_ID='fixture', read_desktop_context=read_desktop_context)
            exec(compile(code, '<actual-controller>', 'exec'), scope)
            before = scope['spec']['template_version']
            context.write_text('已确认约定一', encoding='utf-8')
            exec(compile(code, '<actual-controller>', 'exec'), scope)
            frozen = scope['desktop_context']
            first = scope['spec']['template_version']
            context.write_text('已确认约定二', encoding='utf-8')
            self.assertEqual(frozen, '已确认约定一')
            exec(compile(code, '<actual-controller>', 'exec'), scope)
            self.assertEqual(len({before, first, scope['spec']['template_version']}), 3)

    def test_publisher_scope_and_payload_tamper_rejection(self):
        release = Path(__file__).parent / 'release'
        spec = importlib.util.spec_from_file_location('desktop_publisher', release / 'release_navigation.py')
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)
        manifest = json.loads((release / 'candidate-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(publisher.validate(manifest, release)), 5)
        manifest['files'][0]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            publisher.validate(manifest, release)


if __name__ == '__main__':
    unittest.main()
