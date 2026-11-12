"""RPG monitoring follows confirmed cutover while retaining real remote failures."""
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(SOURCE),str(ROOT/'ops/hooks')]
spec=importlib.util.spec_from_file_location('current_probe_worker',SOURCE/'probe_worker.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

class RPGRoles(unittest.TestCase):
    def observe(self,cutover=True,link='active',task=None,api_error=None):
        payload={'ok':True,'data':{'tasks':[] if task is None else [task],
            'serverTime':'2026-11-10T15:00:00+08:00','health':{'ourTs':'2026-11-10T14:59:00+08:00','ourStaleHours':0.02}}}
        opener=SimpleNamespace(open=lambda *a,**k:io.BytesIO(json.dumps(payload).encode()))
        with patch.object(probe,'RPG_CUTOVER',SimpleNamespace(is_file=lambda:cutover),create=True), \
             patch.object(probe,'state',side_effect=lambda u:link if u=='rpg183-link.service' else 'inactive') as states, \
             patch.object(probe.urllib.request,'build_opener',return_value=opener):
            if api_error:
                opener.open=lambda *a,**k:(_ for _ in ()).throw(api_error)
            return probe.rpg_probe(),states

    def test_cutover_does_not_treat_retired_local_services_as_failures(self):
        value,states=self.observe()
        self.assertEqual(value['runtime_owner'],'183')
        self.assertEqual(value['status'],'warning')
        self.assertEqual(value['remote_service_states']['p2pah-srv-exec.service'],'unverified')
        self.assertEqual(states.call_args_list[0].args,('rpg183-link.service',))
        self.assertEqual(states.call_count,1)
        self.assertEqual(value['source_freshness']['ourStaleHours'],0.02)
        self.assertFalse(any(x['code'].endswith('d4follow.service') for x in value['issues']))

    def test_cutover_link_and_api_failures_remain_critical(self):
        value,_=self.observe(link='inactive')
        self.assertEqual(value['status'],'critical')
        self.assertIn({'level':'critical','code':'rpg_dependency_unavailable:rpg183-link.service'},value['issues'])
        value,_=self.observe(api_error=TimeoutError())
        self.assertEqual(value['status'],'critical')
        self.assertIn({'level':'critical','code':'rpg_state_unavailable'},value['issues'])

    def test_remote_original_task_failure_remains_critical(self):
        value,_=self.observe(task={'id':'abcdef123456','kind':'sync','params':{'game':'暗黑破坏神4'},'status':'error'})
        self.assertEqual(value['status'],'critical')
        self.assertIn({'level':'critical','code':'rpg_task_failed:d4:sync:abcdef123456'},value['issues'])

    def test_without_cutover_original_local_checks_remain(self):
        value,states=self.observe(cutover=False)
        self.assertEqual(value['runtime_owner'],'187')
        self.assertEqual(value['status'],'critical')
        self.assertEqual({x.args[0] for x in states.call_args_list},{'d4follow.service','p2pah-srv-exec.service'})

if __name__=='__main__':unittest.main()
