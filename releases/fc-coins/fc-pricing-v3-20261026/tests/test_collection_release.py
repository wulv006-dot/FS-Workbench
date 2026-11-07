from copy import deepcopy
import ast
from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'
sys.path.insert(0, str(DEPLOY))
import fc_v3_release_adapter as adapter
import target_map


def manifest(scope, mapping):
    return dict(scope=scope, businessWrites=False, timersChanged=False, releaseReady=True,
        files=[dict(candidate=name, target=target, owner='0:0', mode='0o644',
                    beforeSha256='a'*64, sha256='b'*64) for name,target in mapping.items()])


class CollectionRelease(unittest.TestCase):
    def test_collection_entry_is_loaded_by_fresh_processes_and_has_no_used_daemon_import(self):
        source = DEPLOY.parent/'source'
        for name, imported in (('fc27_cloud_worker.py','quote_for_run'),('fc27_cloud_api.py','preview_discount_rules')):
            tree=ast.parse((source/name).read_text(encoding='utf-8'))
            self.assertFalse(any(isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load) and n.id==imported for n in ast.walk(tree)))
        worker=ast.parse((source/'fc27_cloud_worker.py').read_text(encoding='utf-8'))
        self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='run'
            and any(isinstance(v,ast.Constant) and v.value=='server_quote_job.py' for v in ast.walk(n)) for n in ast.walk(worker)))
        text=(source/'fc_pricing_v3/sources.py').read_text(encoding='utf-8')
        self.assertIn("subprocess.run(['/opt/python39/bin/python3','-B','-m','fc_pricing_v3.sources']", text)

    def test_collection_apply_and_rollback_restart_hook_is_noop(self):
        tree=ast.parse((DEPLOY/'fc_v3_release_adapter.py').read_text(encoding='utf-8'))
        load=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='load_base')
        restart=next(n for n in load.body if isinstance(n,ast.FunctionDef) and n.name=='restart')
        process=SimpleNamespace(run=Mock())
        ready=Mock()
        scope=dict(subprocess=process,base=SimpleNamespace(),original_restart=Mock(),restart_with_hermes_readiness=ready,
            SCOPE='full',DELTA_SCOPE='delta',SHADOW_SCOPE='shadow',OPERATING_SCOPE='operating',COLLECTION_SCOPE='collection')
        exec(compile(ast.Module(body=[restart],type_ignores=[]),'collection-restart','exec'),scope)
        for _ in range(2):
            scope['restart'](dict(scope='collection'))
        process.run.assert_not_called()
        ready.assert_not_called()

    def test_collection_ignores_other_Hermes_tasks_but_keeps_original_FC_unknown_guard(self):
        tree=ast.parse((DEPLOY/'fc_v3_release_adapter.py').read_text(encoding='utf-8'))
        load=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='load_base')
        quiet=next(n for n in load.body if isinstance(n,ast.FunctionDef) and n.name=='quiescent')
        original=Mock(side_effect=ValueError('other Hermes unknown'))
        environment=dict(scope='collection',COLLECTION_SCOPE='collection',original_quiescent=original)
        exec(compile(ast.Module(body=[quiet],type_ignores=[]),'collection-quiescent','exec'),environment)
        environment['quiescent'](Path('/'))
        original.assert_not_called()
        environment['scope']='operating'
        with self.assertRaisesRegex(ValueError,'other Hermes unknown'):
            environment['quiescent'](Path('/'))
        guard=next(n for n in load.body if isinstance(n,ast.FunctionDef) and n.name=='guards')
        checked=Mock()
        environment=dict(original_guards=checked,fc_release_quiescent=lambda *a,**kw:False,
                         fc=SimpleNamespace(tick=None,api=None),holding_fc_locks=True)
        exec(compile(ast.Module(body=[guard],type_ignores=[]),'collection-fc-guard','exec'),environment)
        with self.assertRaisesRegex(ValueError,'original_fc_execution_not_quiescent'):
            environment['guards'](dict(files=[]),Path('/'))
        checked.assert_called_once()

    def test_only_exact_collection_scope_avoids_Hermes_and_model_fences(self):
        tree=ast.parse((DEPLOY/'fc_v3_release_adapter.py').read_text(encoding='utf-8'))
        load=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='load_base')
        branch=next(n for n in load.body if isinstance(n,ast.If)
            and any(isinstance(v,ast.Attribute) and v.attr=='hermes_admission_fence' for v in ast.walk(n)))
        original=Mock(side_effect=AssertionError('other business fence'))
        base=SimpleNamespace(hermes_admission_fence=original, model_release_lock=original)
        environment=dict(scope='collection',COLLECTION_SCOPE='collection',base=base,nullcontext=nullcontext)
        module=ast.Module(body=[branch],type_ignores=[])
        exec(compile(module,'collection-fences','exec'),environment)
        for fence in (base.hermes_admission_fence,base.model_release_lock):
            with fence({},Path('/')) as held:
                self.assertIsNone(held)
        original.assert_not_called()
        base=SimpleNamespace(hermes_admission_fence=original,model_release_lock=original)
        environment.update(scope='operating',base=base)
        exec(compile(module,'collection-fences','exec'),environment)
        self.assertIs(base.hermes_admission_fence,original)
        self.assertIs(base.model_release_lock,original)

    def test_collection_scope_is_exactly_three_existing_entry_files(self):
        self.assertEqual(set(target_map.COLLECTION_NAMES), {
            'source/fc_pricing_v3/sources.py', 'source/hermes-copy/fc_pricing_v3/sources.py', 'source/server_quote_job.py'})
        self.assertEqual(adapter.COLLECTION_TARGETS, {
            'source/fc_pricing_v3/sources.py':'/opt/fc27-cloud-browser/fc_pricing_v3/sources.py',
            'source/hermes-copy/fc_pricing_v3/sources.py':'/opt/fs-hermes-fc/fc_pricing_v3/sources.py',
            'source/server_quote_job.py':'/opt/fc27-cloud-browser/server_quote_job.py'})

    def test_collection_manifest_cannot_add_target_writer_or_business_write(self):
        value = manifest(target_map.COLLECTION_SCOPE, adapter.COLLECTION_TARGETS)
        self.assertEqual(adapter.checked_manifest(value), value)
        mutations = []
        added = deepcopy(value); added['files'][0]['beforeSha256'] = None; mutations.append(added)
        writer = deepcopy(value); writer['files'][0].update(candidate='source/price_writer.py', target='/opt/fc27-cloud-browser/price_writer.py'); mutations.append(writer)
        missing = deepcopy(value); missing['files'].pop(); mutations.append(missing)
        for field in ('businessWrites','timersChanged'):
            change=deepcopy(value); change[field]=True; mutations.append(change)
        for changed in mutations:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                adapter.checked_manifest(changed)

    def test_existing_delta_scope_remains_exact_and_accepted(self):
        value = manifest(target_map.DELTA_SCOPE, adapter.DELTA_TARGETS)
        for row in value['files']:
            if row['candidate'] in target_map.DELTA_NEW: row['beforeSha256'] = None
        self.assertEqual(adapter.checked_manifest(value), value)

    def test_bidirectional_scope_excludes_shared_sol_and_writer_configuration(self):
        value=manifest(target_map.BIDIRECTIONAL_SCOPE,adapter.BIDIRECTIONAL_TARGETS)
        self.assertEqual(adapter.checked_manifest(value),value)
        self.assertEqual(len(value['files']),25)
        self.assertFalse(any(name.rsplit('/',1)[-1] in ('conversation_native.py','conversation_service.py',
            'conversation_http.py','fs_inprocess.py','direct_provider.py','price_writer.py') for name in adapter.BIDIRECTIONAL_TARGETS))
        altered=deepcopy(value);altered['files'].pop()
        with self.assertRaisesRegex(ValueError,'exact_fc_v3_targets'):adapter.checked_manifest(altered)

    def test_existing_manifest_preparer_exposes_collection_as_exclusive_mode(self):
        result = subprocess.run([sys.executable, '-B', str(DEPLOY/'prepare_manifest.py'), '--help'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--collection', result.stdout)


if __name__ == '__main__':
    unittest.main()
