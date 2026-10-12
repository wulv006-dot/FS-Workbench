"""Check the original monitor publisher's fixed single-hooks-file scope."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'monitor-publisher.py'
if not SOURCE.exists():SOURCE=HERE.parents[3]/'fc27_noncore_emergency_20261009/publishers/monitor-publisher.py'
spec=importlib.util.spec_from_file_location('dashboard_publisher',SOURCE)
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
if sys.platform=='win32':
    lock=types.ModuleType('fcntl');lock.LOCK_EX=1;lock.LOCK_NB=2;lock.flock=lambda *args:None
else:
    import fcntl as lock


def ast_value(value):
    if isinstance(value,ast.AST):
        return {'node':type(value).__name__,'fields':{k:ast_value(v) for k,v in ast.iter_fields(value)
                if v is not None and v != []}}
    if isinstance(value,list):return [ast_value(v) for v in value]
    if isinstance(value,bytes):return {'bytes':value.hex()}
    return value


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.app=self.root/'app';self.data=self.root/'data';self.stage=self.root/'stage'
        self.app.mkdir();self.data.mkdir();(self.stage/'source').mkdir(parents=True)
        (self.app/'hooks.py').write_text('old = 1\n')
        (self.stage/'source/hooks.py').write_text('new = 2\n')
        self.sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        self.baseline={'sha256':{'protected':'original'},'services':{'worker':'PID unchanged'}}
        self.manifest={'scope':'dashboard-on-demand-monitor-20261012',
            'files':[{'name':'hooks.py','before':self.sha(self.app/'hooks.py'),
                      'after':self.sha(self.stage/'source/hooks.py')}],
            'protected':self.baseline['sha256'],'checks':{'test_count':7}}
        self.write_manifest()
        self.patches=[patch.object(publisher,'APP',self.app),patch.object(publisher,'DATA',self.data),
            patch.object(publisher.os,'geteuid',return_value=0,create=True),
            patch.object(publisher,'baseline',return_value=self.baseline),
            patch.object(publisher,'noncore_checks'),patch('builtins.print'),
            patch.dict(sys.modules,{'fcntl':lock})]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def write_manifest(self):
        (self.stage/'hooks-monitor-manifest.json').write_text(json.dumps(self.manifest))

    def test_check_does_not_write_restart_or_expand_scope(self):
        with patch.object(publisher,'run') as run:
            publisher.upgrade(self.stage,False)
        run.assert_not_called()
        self.assertEqual((self.app/'hooks.py').read_text(),'old = 1\n')
        self.assertFalse((self.data/'gates').exists())
        self.manifest['files'].append({'name':'collector.py'});self.write_manifest()
        with self.assertRaisesRegex(ValueError,'exact_monitor_upgrade_required'):
            publisher.upgrade(self.stage,False)

    def test_failed_post_rename_restores_only_hook_without_changing_data_mode(self):
        before=self.data.stat().st_mode
        count=0
        def swap(source,target):
            nonlocal count
            target.write_bytes(source.read_bytes());count+=1
            if count==1:raise OSError('post-rename failure')
        with patch.object(publisher,'noncore_swap',side_effect=swap):
            with self.assertRaisesRegex(OSError,'post-rename'):
                publisher.upgrade(self.stage,True)
        self.assertEqual(count,2)
        self.assertEqual((self.app/'hooks.py').read_text(),'old = 1\n')
        self.assertEqual(self.data.stat().st_mode,before)

    def test_existing_scope_and_protected_drift_still_rejected(self):
        self.manifest.pop('scope');self.write_manifest()
        with self.assertRaisesRegex(ValueError,'exact_monitor_upgrade_required'):
            publisher.upgrade(self.stage,False)
        self.manifest['scope']='dashboard-on-demand-monitor-20261012'
        self.manifest['protected']={'protected':'changed'};self.write_manifest()
        with self.assertRaisesRegex(ValueError,'catalogue_monitor_protected_baseline_changed'):
            publisher.upgrade(self.stage,False)

    def test_other_publisher_modes_remain_identical_ast(self):
        fixture=HERE/'baseline-functions.json'
        wanted=json.loads(fixture.read_text())
        actual={n.name:hashlib.sha256(json.dumps(ast_value(n),sort_keys=True).encode()).hexdigest()
                for n in ast.parse(SOURCE.read_text()).body if isinstance(n,ast.FunctionDef) and n.name!='upgrade'}
        self.assertEqual(actual,wanted)


if __name__=='__main__':unittest.main()
