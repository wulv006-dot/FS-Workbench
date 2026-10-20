from pathlib import Path
import importlib.util,sys,types,stat,os
from unittest.mock import patch
import unittest
HERE=Path(__file__).resolve().parent
ORIGINAL=next(p for p in (HERE.parent/'hermes-v2-strategy-20261021',HERE.parent/'hermes_v2_strategy_20261021') if p.exists())
spec=importlib.util.spec_from_file_location('strategy_support',ORIGINAL/'test_strategy.py');support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
spec=importlib.util.spec_from_file_location('fixed_bridge',HERE/'source/pricing_simulation.py');fixed=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixed)
support.ps=fixed
support.st.SimulationBridge=fixed.SimulationBridge
OriginalEngine=support.OriginalEngine
Records=support.Records
TaskBoundary=support.TaskBoundary
FrontendContract=support.FrontendContract


class ExistingServiceOwner(unittest.TestCase):
    def test_only_explicit_policy_owner_is_allowed_and_group_write_is_denied(self):
        path=Path(__file__);size=path.stat().st_size
        def info(owner,mode):return types.SimpleNamespace(st_uid=owner,st_mode=stat.S_IFREG|mode,st_nlink=1,st_size=size)
        with patch.object(Path,'is_symlink',return_value=False),patch.object(fixed,'os',types.SimpleNamespace(name='posix')):
            with patch.object(Path,'stat',return_value=info(994,0o640)):
                self.assertTrue(fixed.read(path,owners=(0,994))[0])
                with self.assertRaisesRegex(ValueError,'source_permissions'):fixed.read(path)
            for owner,mode in ((1000,0o640),(994,0o660),(0,0o666)):
                with self.subTest(owner=owner,mode=mode),patch.object(Path,'stat',return_value=info(owner,mode)):
                    with self.assertRaisesRegex(ValueError,'source_permissions'):fixed.read(path,owners=(0,994))

    def test_existing_policy_owner_exception_is_exact_and_publisher_has_one_target(self):
        source=(HERE/'source/pricing_simulation.py').read_text('utf-8')
        self.assertEqual(source.count('owners=(0,994)'),1)
        self.assertIn("read(self.root/'config/automation.json',owners=(0,994))",source)
        spec=importlib.util.spec_from_file_location('repair_release',HERE/'deploy/release.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
        self.assertEqual(r.TARGETS,{'source/pricing_simulation.py':'/opt/fs-hermes-fc/pricing_simulation.py'});self.assertEqual(r.NEW,frozenset())


if __name__=='__main__':unittest.main()
