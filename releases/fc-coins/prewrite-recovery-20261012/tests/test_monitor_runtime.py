"""Only the original read-only probe child uses the private compatible SQLite."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TASK=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TASK/'tests/monitor_dependencies'))
spec=importlib.util.spec_from_file_location('monitor_runtime_collector',TASK/'source/monitor/collector.py')
collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)

class MonitorRuntime(unittest.TestCase):
    def test_only_original_probe_child_gets_private_library_path(self):
        with tempfile.TemporaryDirectory() as folder:
            library=Path(folder)/'libsqlite3.so.0';library.write_bytes(b'fixture')
            result=SimpleNamespace(returncode=0,stdout=json.dumps({'status':'healthy','issues':[]}))
            with patch.object(collector,'SQLITE_LIBRARY',library,create=True),patch.dict(os.environ,{'LD_LIBRARY_PATH':'original-libraries'}),patch.object(collector.subprocess,'run',return_value=result) as run:
                self.assertEqual(collector.probe()['status'],'healthy')
                self.assertEqual(os.environ['LD_LIBRARY_PATH'],'original-libraries')
            args,kwargs=run.call_args
            self.assertEqual(args[0],[sys.executable,'-B',str(TASK/'source/monitor/probe_worker.py')])
            self.assertEqual(kwargs['env']['LD_LIBRARY_PATH'],str(library.parent)+os.pathsep+'original-libraries')
            self.assertEqual(kwargs['timeout'],40)

    def test_missing_private_library_reports_unverified_without_old_library_fallback(self):
        with patch.object(collector,'SQLITE_LIBRARY',Path('/nonexistent-private-library/libsqlite3.so.0'),create=True),patch.object(collector.subprocess,'run') as run:
            value=collector.probe()
        self.assertEqual(value['status'],'unverified')
        self.assertEqual(value['error_type'],'MonitorSQLiteRuntimeMissing')
        run.assert_not_called()

    def test_original_probe_error_remains_unverified(self):
        with tempfile.TemporaryDirectory() as folder:
            library=Path(folder)/'libsqlite3.so.0';library.write_bytes(b'fixture')
            with patch.object(collector,'SQLITE_LIBRARY',library,create=True),patch.object(collector.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='')):
                value=collector.probe()
        self.assertEqual(value['status'],'unverified')
        self.assertEqual(value['error_type'],'ProbeProcessFailed')

if __name__=='__main__':unittest.main()
