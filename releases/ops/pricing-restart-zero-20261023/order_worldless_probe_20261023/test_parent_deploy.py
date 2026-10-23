"""Synthetic helper-only publication; no service or browser commands execute."""
import ast
from contextlib import ExitStack, nullcontext
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class ParentDeploymentTests(unittest.TestCase):
    def fixture(self, apply=True, native_failure=False, drift=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'source').mkdir()
            service=root/'service.py'; service.write_text('protected service')
            helper=root/'helper.js'; helper.write_text('old helper')
            candidate=root/'source/raw_node_helper.js'; candidate.write_text('new helper')
            sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
            service_sha=sha(service);before=sha(helper);after=sha(candidate)
            (root/'parent-domain-manifest.json').write_text(json.dumps({'helper_after':after}))
            state={'Id':'same-container','State':{'Running':True,'StartedAt':'same-start'},'Config':{'Cmd':['--restore-last-session']},
                   'Mounts':[{'Source':'/var/lib/fs-order-session/browser','Destination':'/var/lib/fs-order-session/browser'}]}
            proof=root/'proof.json';old={'status':'verified','durability_verified':True,'service_sha256':service_sha,'probe_helper_sha256':before,
                   'worldless_probe_recovery':{'container_id':'same-container','started_at':'same-start'},'old_durability':'preserved'}
            proof.write_text(json.dumps(old));(root/'exec.lock').touch()
            calls=[]
            def publish(values,op):
                calls.append(('publish',list(values)))
                for name,text in values.items():Path(name).write_text(text)
                (root/'backups'/op).mkdir(parents=True)
            def atomic(path,value):path.write_text(json.dumps(value))
            ready={'ready':True,'login_attempts':0,'verified_age_seconds':0}
            original=SimpleNamespace(sha=sha,business_idle=nullcontext,idle=Mock(),no_active_rpg_container=Mock(),
                ISOLATION_LOCK=root/'isolation.lock',EXEC_LOCK=root/'exec.lock',inspect=Mock(return_value=state),
                health=Mock(side_effect=[ready,OSError('synthetic')] if native_failure else None,return_value=ready),
                pid=Mock(side_effect=[10,11]),publish=publish,atomic_json=atomic)
            operation='synthetic-parent-helper'
            scope=dict(ROOT=root,SERVICE=service,HELPER=helper,SERVICE_SHA=service_sha,BEFORE=before,PROOF=proof,RECEIPT=root/'receipt.json',OP=operation,
                original=original,ExitStack=ExitStack,datetime=datetime,timezone=timezone,json=json,
                fcntl=SimpleNamespace(flock=Mock(),LOCK_EX=1,LOCK_NB=2,LOCK_UN=3),
                subprocess=SimpleNamespace(check_output=Mock(return_value='active\n'),run=lambda args,**kw:calls.append(('system',args))),
                time=SimpleNamespace(monotonic=Mock(side_effect=[0,46]) if native_failure else Mock(return_value=0),sleep=Mock()),
                Path=lambda value:root/'backups' if value=='/var/backups' else Path(value))
            tree=ast.parse(Path(__file__).with_name('deploy_parent_domain.py').read_text(encoding='utf-8'))
            main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
            exec(compile(ast.Module(body=[main],type_ignores=[]),'helper-publisher','exec'),scope)
            if drift:helper.write_text('other publisher')
            if native_failure or drift:
                with self.assertRaises((AssertionError,RuntimeError)):scope['main'](apply)
            else:self.assertEqual(scope['main'](apply)['status'],'verified' if apply else 'checked')
            self.assertEqual(sha(service),service_sha)
            if drift or not apply:
                self.assertEqual(calls,[]);self.assertFalse((root/'receipt.json').exists())
            else:
                self.assertEqual(calls[-1],('system',['systemctl','start','p2pah-srv-exec.service']))
                published=json.loads(proof.read_text())
                if native_failure:
                    self.assertEqual(published,old);self.assertEqual(json.loads((root/'receipt.json').read_text())['status'],'unknown')
                else:
                    self.assertEqual(published['probe_helper_sha256'],after);self.assertEqual(published['old_durability'],'preserved')
                    self.assertEqual(published['service_sha256'],service_sha)
                self.assertFalse(any(c[0]=='system' and 'docker' in c[1] for c in calls))

    def test_publishes_only_helper_and_advances_proof_after_native_ready(self):self.fixture()
    def test_unknown_native_failure_preserves_proof_and_resumes_executor(self):self.fixture(native_failure=True)
    def test_check_and_drift_never_publish_or_restart(self):self.fixture(apply=False);self.fixture(drift=True)


if __name__=='__main__':unittest.main()
