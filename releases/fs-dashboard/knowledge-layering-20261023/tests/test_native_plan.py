import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/'deploy/native_plan.py'
spec=importlib.util.spec_from_file_location('native_plan',p);np=importlib.util.module_from_spec(spec);spec.loader.exec_module(np)


class Isolation(unittest.TestCase):
    def test_plan_never_authorizes_production(self):
        v=np.plan(np.TARGETS,np.NATIVE_UNITS)
        self.assertFalse(v['production_actions_allowed'])
        self.assertIn('existing_admission_fence',v['must_preserve'])

    def test_no_business_service_can_be_restarted(self):
        for unit in ['fs-hermes-fc.service','fs-business-range.service','nginx.service']:
            with self.assertRaises(ValueError):np.plan(np.TARGETS,[unit])

    def test_no_fc_formula_or_extra_file_enters_payload(self):
        with self.assertRaises(ValueError):np.plan(np.TARGETS|{'/opt/fs-hermes-fc/business-baseline.md'},np.NATIVE_UNITS)


if __name__=='__main__':unittest.main()
