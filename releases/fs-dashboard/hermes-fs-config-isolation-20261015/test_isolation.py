"""Process-local config selection must not alter profile ownership or safety gates."""
import ast,difflib,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent

class Isolation(unittest.TestCase):
    def select(self,worker,config):
        source=(HERE/'candidate/hermes/runtime/hermes_worker.py').read_text()
        make=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='make_adapter')
        prefix=[]
        for node in make.body:
            if isinstance(node,ast.ImportFrom) and node.module=='aiohttp':break
            prefix.append(node)
        tree=ast.fix_missing_locations(ast.Module(body=prefix,type_ignores=[]))
        module=types.ModuleType('hermes_cli');module.config=config
        with patch.dict(sys.modules,{'hermes_cli':module}):exec(compile(tree,'config-selection','exec'),{'Path':Path,'__file__':str(worker)})

    def test_selects_worker_config_without_changing_home(self):
        config=types.SimpleNamespace(get_config_path=lambda:Path('/profile/config.yaml'))
        self.select(Path('/opt/pilot/hermes_worker.py'),config)
        self.assertEqual(config.get_config_path(),Path('/opt/pilot/runtime-config.yaml'))

    def test_desktop_write_does_not_redirect_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/'config.yaml';runtime=root/'runtime-config.yaml'
            profile.write_text('{"model":{"base_url":"https://api.deepseek.com/v1"}}')
            runtime.write_text('{"model":{"context_length":1048576}}')
            config=types.SimpleNamespace(get_config_path=lambda:profile)
            self.select(root/'hermes_worker.py',config)
            before=config.get_config_path().read_text();profile.write_text('{}')
            self.assertEqual(config.get_config_path().read_text(),before)

    def test_context_and_tool_guards_are_preserved(self):
        baseline=(HERE/'baseline-hermes_worker.py').read_text()
        candidate=(HERE/'candidate/hermes/runtime/hermes_worker.py').read_text()
        added=[r[1:] for r in difflib.ndiff(baseline.splitlines(),candidate.splitlines()) if r.startswith('+ ')]
        removed=[r for r in difflib.ndiff(baseline.splitlines(),candidate.splitlines()) if r.startswith('- ')]
        self.assertFalse(removed)
        self.assertEqual(len(added),3)
        for guard in ('context_window_configuration_mismatch','unexpected_context_compressor','unexpected_runtime_tools:'):
            self.assertIn(guard,candidate)

if __name__=='__main__':unittest.main()
