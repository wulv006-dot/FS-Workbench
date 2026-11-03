import hashlib
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[4]
DEPLOY = Path(__file__).resolve().parents[1] / 'deploy' / 'native_release.py'
spec = importlib.util.spec_from_file_location('native_registration_guard', DEPLOY)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)

UNCONDITIONAL = (b'    from .knowledge import register as register_knowledge\n'
                 b'    register_knowledge(ctx)\n')
CONDITIONAL = (b'    if include_knowledge:\n'
               b'        from .knowledge import register as register_knowledge\n'
               b'        register_knowledge(ctx)\n')
BEFORE = b'def register(ctx):\n    ctx.keep()\n'


class RegistrationGuard(unittest.TestCase):
    def test_exact_registered_delta_derives_original_bytes_for_both_layouts(self):
        for addition in (UNCONDITIONAL, CONDITIONAL):
            for newline in (b'\n', b'\r\n'):
                with self.subTest(addition=addition, newline=newline):
                    before = BEFORE.replace(b'\n', newline)
                    raw = before + addition.replace(b'\n', newline)
                    self.assertEqual(native.original_plugin_sha(raw), hashlib.sha256(before).hexdigest())

    def test_real_conditional_registration_restores_valid_exact_preimage(self):
        raw = (ROOT / 'releases/fs-dashboard/hermes-server-unify-20261022/fs_readonly/__init__.py').read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(raw.count(CONDITIONAL), 1)
        before = raw.replace(CONDITIONAL, b'', 1)
        compile(before, 'synthetic-preimage', 'exec')
        self.assertEqual(native.original_plugin_sha(raw), hashlib.sha256(before).hexdigest())

    def test_ambiguous_duplicate_or_modified_registration_fails_closed(self):
        for invalid in (BEFORE, BEFORE + CONDITIONAL + CONDITIONAL,
                        BEFORE + UNCONDITIONAL + CONDITIONAL,
                        BEFORE + b'    if include_knowledge:\n' + UNCONDITIONAL,
                        BEFORE + CONDITIONAL.replace(b'register_knowledge(ctx)', b'register_knowledge(other)'),
                        BEFORE + CONDITIONAL.replace(b'        register_knowledge', b'    register_knowledge')):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'native_plugin_exact_registration_delta_required'):
                native.original_plugin_sha(invalid)

    def test_unrelated_candidate_change_remains_visible_to_before_hash(self):
        expected = hashlib.sha256(BEFORE).hexdigest()
        self.assertNotEqual(native.original_plugin_sha(BEFORE + CONDITIONAL + b'changed = True\n'), expected)


if __name__ == '__main__':
    unittest.main()
