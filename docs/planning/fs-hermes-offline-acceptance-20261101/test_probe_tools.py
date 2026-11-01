"""Test diagnostic tooling with synthetic inputs, never claim FS properties pass."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from probe_support import install_guard,read_sources,run_diagnostic
PROBES=sorted(p for p in HERE.glob('probe_*.py') if p.name!='probe_support.py')


class DiagnosticTools(unittest.TestCase):
    def test_actual_five_probes_fail_when_local_objects_are_unavailable(self):
        # No fake FS implementation. Real scripts invoke real git on an empty
        # directory, never fetch, and must not convert missing objects to success.
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(len(PROBES),5)
            for probe in PROBES:
                with self.subTest(probe=probe.name):
                    value=run_diagnostic(probe,Path(directory))
                    self.assertNotEqual(value['returncode'],0)
                    self.assertIsNone(value['observation'])
                    self.assertTrue(value['stderr_present'])

    def test_local_loader_disables_lazy_fetch_and_preserves_source_and_error(self):
        with patch('probe_support.subprocess.run',return_value=subprocess.CompletedProcess([],0,stdout=b'VALUE=7')) as git:
            self.assertEqual(read_sources(Path('/synthetic'),'a'*40,{'fixture':'fixture.py'}),{'fixture':b'VALUE=7'})
            args,kwargs=git.call_args
            self.assertEqual(args[0],['git','-C',str(Path('/synthetic')),'show','a'*40+':fixture.py'])
            self.assertIs(kwargs['check'],True)
            self.assertEqual(kwargs['env']['GIT_NO_LAZY_FETCH'],'1')
            self.assertFalse(kwargs.get('shell',False))
        with patch('probe_support.subprocess.run',side_effect=subprocess.CalledProcessError(128,['git'])):
            with self.assertRaises(subprocess.CalledProcessError):
                read_sources(Path('/synthetic'),'a'*40,{'fixture':'fixture.py'})

    def test_observations_and_nonzero_status_are_preserved_not_relabelled_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/'synthetic_diagnostic.py'
            for code in (0,1):
                script.write_text('import json\nprint(json.dumps({"synthetic_observation":"violation","property_passed":False}))\nraise SystemExit('+str(code)+')\n',encoding='utf-8')
                value=run_diagnostic(script,Path(directory))
                self.assertEqual(value['returncode'],code)
                self.assertEqual(value['observation']['synthetic_observation'],'violation')
                self.assertIs(value['observation']['property_passed'],False)

    def test_network_and_subprocess_guard_runs_in_isolated_worker(self):
        result=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--guard-worker'],capture_output=True,text=True,check=True,timeout=10)
        self.assertEqual(json.loads(result.stdout),{'blocked':['socket.getaddrinfo','socket.connect','subprocess.Popen','os.system']})

    def test_all_scripts_use_shared_transport_and_python39_grammar(self):
        for path in [*PROBES,HERE/'probe_support.py',Path(__file__)]:
            with self.subTest(path=path.name):
                tree=ast.parse(path.read_text(encoding='utf-8'),feature_version=(3,9))
                if path in PROBES:
                    calls=[n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
                    self.assertIn('read_sources',calls)
                    self.assertIn('install_guard',calls)
                    revisions=[n.value.value for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and any(isinstance(t,ast.Name) and t.id=='SHA' for t in n.targets)]
                    self.assertEqual(len(revisions),1)
                    self.assertEqual(len(revisions[0]),40)

    def test_dispatcher_maps_package_without_unmapped_exemption(self):
        root=HERE.parents[2]
        spec=importlib.util.spec_from_file_location('acceptance_pr_fast',root/'tools/pr_fast.py')
        dispatcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(dispatcher)
        files=[p.relative_to(root).as_posix() for p in HERE.iterdir() if p.is_file()]
        self.assertEqual(dispatcher.select(files),['fs-hermes-offline-acceptance'])
        self.assertEqual(dispatcher.select(files+['tools/pr_fast.py']),['fs-hermes-offline-acceptance','self'])
        with self.assertRaisesRegex(RuntimeError,'UNMAPPED'):
            dispatcher.select(['unregistered_synthetic_module.py'])


def guard_worker():
    install_guard();blocked=[]
    operations=[('socket.getaddrinfo',lambda:socket.getaddrinfo('example.invalid',443)),
                ('socket.connect',lambda:socket.create_connection(('127.0.0.1',1),timeout=.1)),
                ('subprocess.Popen',lambda:subprocess.Popen([sys.executable,'-c','raise SystemExit(0)'])),
                ('os.system',lambda:os.system('never-executed-offline-probe'))]
    for expected,operation in operations:
        try:operation()
        except RuntimeError as error:
            # create_connection resolves first; connect is checked separately.
            if expected=='socket.connect' and str(error)=='OFFLINE_DENY:socket.getaddrinfo':
                with socket.socket() as stream:
                    try:stream.connect(('127.0.0.1',1))
                    except RuntimeError as direct:
                        if str(direct)!='OFFLINE_DENY:socket.connect':raise
            elif str(error)!='OFFLINE_DENY:'+expected:raise
            blocked.append(expected)
        else:raise AssertionError('operation was not blocked: '+expected)
    print(json.dumps({'blocked':blocked}))


if __name__=='__main__':
    if sys.argv[1:]==['--guard-worker']:guard_worker()
    else:unittest.main(verbosity=2)
