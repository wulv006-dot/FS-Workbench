"""Exercise the real error boundary without a browser or session request."""
import ast
from pathlib import Path
import unittest

tree=ast.parse((Path(__file__).resolve().parents[1]/'source/preview_backend.py').read_text())
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='failure_reason')
namespace={};exec(compile(ast.Module(body=[node],type_ignores=[]),'preview_backend.py','exec'),namespace)
failure_reason=namespace['failure_reason']

class PreviewFailureTests(unittest.TestCase):
    def test_global_session_error_is_actionable_and_redacted(self):
        self.assertEqual(failure_reason(RuntimeError('global_order_unavailable:private broker details')),'global_order_session_unavailable')

    def test_unrelated_runtime_details_stay_private(self):
        self.assertEqual(failure_reason(RuntimeError('private details')),'RuntimeError')

    def test_existing_validation_reason_and_limit_are_preserved(self):
        self.assertEqual(failure_reason(ValueError('backend_login_expired')),'backend_login_expired')
        self.assertEqual(len(failure_reason(ValueError('x'*200))),100)

if __name__=='__main__':unittest.main()
