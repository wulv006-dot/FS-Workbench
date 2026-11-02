"""Synthetic publisher/SQLite checks; not real Linux modes, deployment or login."""
from contextlib import closing, contextmanager, nullcontext, ExitStack
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
import socket
import stat
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

import runtime_prepare as prepare
import runtime_release as release


NGINX = (b'# unrelated\r\nlocation = /api/hermes/conversations {\r\n'
         b' if ($request_method !~ ^(GET|POST)$) { return 405; }\r\n'
         b' auth_request /__auth_verify;\r\n client_max_body_size 16k;\r\n}\r\n'
         b'location ^~ /api/hermes/conversations/ {\r\n client_max_body_size 16k;\r\n}\r\n'
         b'location /other { client_max_body_size 16k; }\r\n')


class RuntimeMaterials(unittest.TestCase):
    def test_material_guard_8e2a_transport_delta_and_rollback(self):
        self.assertTrue(callable(getattr(prepare, 'configure_material_guard', None)),
                        '8e2a material-guard followup missing')
        self._transport_followup(stream=True, guard=True)

    def test_material_stream_b362_existing_transport_delta_and_rollback(self):
        self.assertTrue(callable(getattr(prepare, 'configure_material_stream', None)),
                        'b362 existing-transport stream followup missing')
        self._transport_followup(stream=True)

    def test_transport_82edf_promoted_protection_delta_and_rollback(self):
        self._transport_followup(stream=False)

    def test_bindings_9edb_single_target_and_rollback(self):
        self.assertTrue(callable(getattr(prepare, "configure_bindings_auth", None)),
                        "bindings-only installed followup missing")
        self._transport_followup(stream=True, bindings=True)

    def _transport_followup(self, stream, bindings=False, guard=False):
        configure = prepare.configure_material_stream if stream else prepare.configure_material_transport
        if bindings: configure = prepare.configure_bindings_auth
        if guard: configure = prepare.configure_material_guard
        candidate = "runtime/conversation_file_bindings.py" if bindings else "runtime/transport.py"
        marker = "materialGuard" if guard else "bindingsAuth" if bindings else "materialStream" if stream else "materialTransport"
        before_key = "GUARD_BEFORE_SHA" if guard else "BINDINGS_BEFORE_SHA" if bindings else "STREAM_BEFORE_SHA" if stream else "TRANSPORT_BEFORE_SHA"
        self.assertTrue(callable(getattr(prepare, 'configure_material_transport', None)), 'transport-only installed followup missing')
        names = ('TARGETS', 'NEW', 'INSTALLED_COMMIT', 'INSTALLED_PROOF', 'EXECUTION_MODE', 'DIAGNOSTICS_MODE', 'TASK_INDEX_MODE', 'WORKER_DIAGNOSTICS_MODE', 'TRANSPORT_MODE', 'STREAM_MODE', 'BINDINGS_MODE', 'GUARD_MODE')
        saved_release = {k: deepcopy(getattr(release, k)) for k in names}
        saved_prepare = {k: deepcopy(getattr(prepare, k)) for k in ('TARGETS', 'NEW', 'INSTALLED_COMMIT', 'INSTALLED_PROOF', 'SOURCES')}
        try:
            configure()
            self.assertEqual(release.STREAM_MODE, stream and not bindings and not guard); self.assertEqual(release.TRANSPORT_MODE, not stream); self.assertFalse(release.WORKER_DIAGNOSTICS_MODE); self.assertFalse(release.TASK_INDEX_MODE); self.assertFalse(release.DIAGNOSTICS_MODE)
            self.assertEqual(release.NEW, frozenset())
            if guard:
                self.assertTrue(release.GUARD_MODE); self.assertFalse(release.BINDINGS_MODE)
                self.assertEqual(release.GUARD_BEFORE_SHA, 'a71849b7e5e8f3c5b55967c21d5383e2ff6afa7c7c5e3c6772dc0c80209ba945')
                self.assertEqual(release.INSTALLED_PROOF, {
                    'sourceCommit':'8e2a456631fc5aa916c1366d087b9adbccb02f91',
                    'backup':'/var/backups/fs-navigation-20261006/nav-20261102T002030Z',
                    'manifestSha256':'e3a949b35d55aac5048f22094d81bc9f7db7e4f684f7463a83044371f5d4d3a4',
                    'journalSha256':'fc33024f58bb1222e288e6ab1374be16b543f93756f135833238b29be9e22c74'})
            elif bindings:
                self.assertTrue(release.BINDINGS_MODE)
                self.assertEqual(release.INSTALLED_PROOF, {
                    'sourceCommit':'9edb8827c0bc21fce4173030bd09b7388b19c866',
                    'backup':'/var/backups/fs-navigation-20261006/nav-20261101T175040Z',
                    'manifestSha256':'74270ff2d91e195a8279572ba48aaa35a4189a75597bceaa9496a4fbe9116088',
                    'journalSha256':'831ca7e02476aa50ef9fb25c2b3cc52c28ad562979fff26a938992746a6fc3e7'})
            elif stream:
                self.assertEqual(release.STREAM_BEFORE_SHA, '2ef021e7b3bc3efd76632cf1924b538860da5422a08a4a751d2a932ff6f1a23d')
                self.assertEqual(release.INSTALLED_PROOF, {
                    'sourceCommit':'b362bd3bfb3fc4eca4bcf1d47cb3f0550c8c6c04',
                    'backup':'/var/backups/fs-navigation-20261006/nav-20261101T123702Z',
                    'manifestSha256':'02d2d4623467aaf62f617775a7c47084b6005cf26e8da150025d12be7a052833',
                    'journalSha256':'92b65d1a2d17a8d979b5b1011002c35ff1b80997e51b3e7e8db01cc43699a82d'})
            else:
                self.assertEqual(release.INSTALLED_PROOF, {
                'sourceCommit':'82edf03573c3fed796d7a7ed2784134c5dd1f7ec',
                'backup':'/var/backups/fs-navigation-20261006/nav-20261101T110803Z',
                'manifestSha256':'a9be5243f473129379e6662854be5236d9c69f08d86f97693d66039be86d5656',
                'journalSha256':'46b6f0f1258fb190330544ae0b1538504f0024457d0b2b7336999c42dc3bce67'})
            with tempfile.TemporaryDirectory() as packed:
                def blob(command, **kwargs):
                    self.assertEqual(command[:2], ['git', 'show'])
                    return ('git-blob:'+command[2]).encode()
                with patch.object(prepare.subprocess, 'check_output', side_effect=blob):
                    prepare.pack(Path(packed), Path(packed)/'bundle', 'b'*40)
                descriptor=json.loads((Path(packed)/'bundle/payload-manifest.json').read_bytes())
                self.assertEqual(descriptor['material_stream'], stream and not bindings and not guard)
                self.assertEqual(descriptor['bindings_auth'], bindings)
                self.assertEqual(descriptor['material_guard'], guard)
                self.assertEqual(descriptor['material_transport'], not stream); self.assertFalse(descriptor['material_diagnostics'])
                self.assertEqual(descriptor['installed_baseline']['source_commit'], release.INSTALLED_COMMIT)
                self.assertEqual(set(descriptor['installed_baseline']['files']), set(release.TARGETS))
                self.assertTrue(all(v is not None for v in descriptor['installed_baseline']['files'].values()))
            for fail in (None, 'restart', 'container'):
                with self.subTest(rollback=fail), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    base, system, payload, metadata, _, proof, previous = self.installed_fixture(root)
                    transport = release.TARGETS['runtime/transport.py']
                    transport_row = next(r for r in previous['files'] if r['candidate']=='runtime/transport.py')
                    if not stream:
                        previous['files'] = [r for r in previous['files'] if r['candidate']!='runtime/transport.py']
                        previous['unchangedRequired'].append({'path':transport,'sha256':transport_row['sha256']})
                    self.assertEqual((len(previous['files']),len(previous['unchangedRequired'])),(25,45) if stream else (24,46))
                    backup = base.rooted(system,proof['backup'])
                    def save_previous():
                        raw=json.dumps(previous).encode();(backup/'approved-manifest.json').write_bytes(raw)
                        proof['manifestSha256']=prepare.digest(raw)
                        journal={'status':'applied-awaiting-actual-http-role-acceptance','manifest':previous,'approvedManifestSha256':proof['manifestSha256']}
                        raw=json.dumps(journal).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
                    save_previous()
                    descriptor_path = payload.parent/'payload-manifest.json'
                    descriptor = json.loads(descriptor_path.read_bytes())
                    descriptor.update(material_execution=True, material_diagnostics=False, goal_task_index_compat=False, worker_diagnostics=False, material_transport=not stream, material_stream=stream and not bindings and not guard, bindings_auth=bindings, material_guard=guard)
                    for name in prepare.SOURCES:
                        before = base.rooted(system, release.TARGETS[name]).read_bytes()
                        body = before+b'\n# material transport\n' if name == candidate else before
                        (payload/name).write_bytes(body); descriptor['files']['payload/'+name] = prepare.digest(body)
                    raw = json.dumps(descriptor).encode(); descriptor_path.write_bytes(raw)
                    stage = root/'transport-stage'
                    with patch.object(release, 'INSTALLED_PROOF', proof), patch.object(prepare, 'INSTALLED_PROOF', proof), \
                            patch.object(prepare, 'file_metadata', metadata), \
                            patch.object(release, 'BINDINGS_TRANSPORT_SHA', transport_row['sha256'], create=True), \
                            patch.object(release, before_key, next(r['sha256'] for r in previous['files'] if r['candidate']==candidate) if bindings else transport_row['sha256']):
                        observed = prepare.observe(system, previous)
                        for key, value in (('worker_state','failed'), ('worker_state','inactive'),
                                           ('worker_image_source','configured_unit_and_local_image')):
                            with patch.object(prepare,'observe',return_value=dict(observed, **{key:value})), self.assertRaises(ValueError):
                                prepare.prepare(payload, root/'bad-runtime', 'a'*40, prepare.digest(raw), root=system, followup=True)
                            self.assertFalse((root/'bad-runtime').exists())
                        prepare.prepare(payload, stage, 'a'*40, prepare.digest(raw), root=system, followup=True, release_ready=True)
                        protected_before=deepcopy(previous['unchangedRequired'])
                        files_before=deepcopy(previous['files'])
                        cases = ('target_missing','target_duplicate','target_hash','missing_protection','duplicate_protection','extra_protected','transport_protected') if stream else ('missing','duplicate','wrong_hash','extra_protected','fake_target')
                        for error in cases:
                            previous['unchangedRequired']=deepcopy(protected_before)
                            previous['files']=deepcopy(files_before)
                            if error=='missing':previous['unchangedRequired']=[r for r in protected_before if r['path']!=transport]
                            elif error=='duplicate':previous['unchangedRequired'].append({'path':transport,'sha256':transport_row['sha256']})
                            elif error=='wrong_hash':next(r for r in previous['unchangedRequired'] if r['path']==transport)['sha256']='0'*64
                            elif error=='extra_protected':previous['unchangedRequired'].append({'path':'/opt/unrelated.py','sha256':'0'*64})
                            elif error=='target_missing':previous['files']=[r for r in previous['files'] if r['candidate']!='runtime/transport.py']
                            elif error in ('target_duplicate','fake_target'):previous['files'].append(deepcopy(transport_row))
                            elif error=='target_hash':next(r for r in previous['files'] if r['candidate']=='runtime/transport.py')['sha256']='0'*64
                            elif error=='missing_protection':previous['unchangedRequired'].pop()
                            elif error=='duplicate_protection':previous['unchangedRequired'].append(deepcopy(previous['unchangedRequired'][0]))
                            else:previous['unchangedRequired'].append({'path':transport,'sha256':transport_row['sha256']})
                            save_previous()
                            with self.subTest(proof=error),self.assertRaises(ValueError):
                                prepare.prepare(payload,root/('bad-proof-'+error),'a'*40,prepare.digest(raw),root=system,followup=True)
                            self.assertFalse((root/('bad-proof-'+error)).exists())
                        previous['unchangedRequired']=protected_before;previous['files']=files_before;save_previous()
                        for case in ('old_proof', 'git', 'journal', 'protected', 'extra_http', 'worker_before', 'no_delta', 'mixed_mode') + (('missing_execution',) if stream else ()):
                            changed = deepcopy(descriptor); restore = None
                            if case == 'old_proof': changed['installed_baseline']['source_commit'] = 'c12a273387a7811c71b3fbf1c040c8a7b4d1639a' if guard else '82edf03573c3fed796d7a7ed2784134c5dd1f7ec' if stream else 'f79e29f0d5921b103a218c5e6ed967a754858b9c'
                            elif case == 'mixed_mode':changed['material_transport' if stream else 'material_stream']=True
                            elif case == 'missing_execution':changed['material_execution']=False
                            elif case == 'git': changed['installed_baseline']['files']['runtime/transport.py'] = '0'*64
                            else:
                                path = (payload/candidate if case == 'no_delta' else payload/'http/conversation_http.py' if case == 'extra_http' else
                                        base.rooted(system, proof['backup']+'/journal.json') if case == 'journal' else
                                        base.rooted(system, previous['unchangedRequired'][0]['path']) if case == 'protected' else
                                        base.rooted(system, release.TARGETS[candidate]))
                                restore = (path, path.read_bytes())
                                path.write_bytes(base.rooted(system, release.TARGETS[candidate]).read_bytes() if case == 'no_delta' else b'unapproved drift')
                                if case == 'extra_http': changed['files']['payload/http/conversation_http.py'] = prepare.digest(path.read_bytes())
                                if case == 'no_delta': changed['files']['payload/'+candidate] = prepare.digest(path.read_bytes())
                            bad = json.dumps(changed).encode(); descriptor_path.write_bytes(bad)
                            with self.subTest(rejected=case), self.assertRaises(ValueError):
                                prepare.prepare(payload, root/('reject-'+case), 'a'*40, prepare.digest(bad), root=system, followup=True)
                            self.assertFalse((root/('reject-'+case)).exists())
                            if restore: restore[0].write_bytes(restore[1])
                        descriptor_path.write_bytes(raw)
                    manifest = json.loads((stage/'approved-manifest.json').read_bytes())
                    self.assertTrue(manifest[marker]); self.assertNotIn('materialTransport' if stream else 'materialStream', manifest); self.assertNotIn('materialDiagnostics', manifest)
                    self.assertFalse(manifest['materialStaticOnly'])
                    self.assertEqual((len(manifest['files']), len(manifest['unchangedRequired'])), (25, 45))
                    self.assertTrue(all(r['beforeSha256'] is not None for r in manifest['files']))
                    target = release.TARGETS[candidate]
                    self.assertEqual(manifest['materialChangedTargets'], [target])
                    unchanged = {r['target']:(base.rooted(system,r['target']).stat().st_ino,base.rooted(system,r['target']).stat().st_mtime_ns)
                                 for r in manifest['files'] if r['target'] != target}
                    spec = importlib.util.spec_from_file_location('material_transport_publisher', stage/'runtime_release.py')
                    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                    (module.configure_material_guard if guard else module.configure_bindings_auth if bindings else module.configure_material_stream if stream else module.configure_material_transport)()
                    module.INSTALLED_PROOF = proof; module.BINDINGS_TRANSPORT_SHA = transport_row['sha256']; setattr(module, before_key, next(r['sha256'] for r in previous['files'] if r['candidate']==candidate) if bindings else transport_row['sha256'])
                    guards = []
                    def check_guard(current, host, reader_stopped=False):
                        guards.append(True)
                        self.assertEqual(current['runtimeRequired'], manifest['runtimeRequired'])
                        for row in current['unchangedRequired']:
                            self.assertEqual(base.digest(base.rooted(host, row['path'])), row['sha256'])
                    base.guards = check_guard; base.retirement = lambda *a: None
                    base.locks = base.live_lock = base.model_release_lock = lambda *a: nullcontext()
                    fence = SimpleNamespace(modified=False, confirmed=False, stop_then_unlock_database=Mock())
                    base.hermes_admission_fence = lambda *a: nullcontext(fence)
                    def restart_result(*args):
                        if fail == 'restart' and original_restart.call_count == 1:
                            raise RuntimeError('worker health failure')
                    original_restart = Mock(side_effect=restart_result)
                    base.restart_for = original_restart
                    writes = []; original_atomic = base.atomic
                    targets = {base.rooted(system,r['target']) for r in manifest['files']}
                    def atomic(path, body, mode=0o644):
                        if path in targets: writes.append(path)
                        return original_atomic(path, body, mode)
                    base.atomic = atomic
                    if os.name == 'nt': base.directory_sync = lambda *a: None
                    def worker_result(**kwargs):
                        self.assertFalse(kwargs.get('allow_stopped',False))
                        if fail == 'container' and original_restart.call_count == 1:
                            raise ValueError('current_worker_container_unavailable')
                        return {'image':manifest['workerImageId'], 'state':'active', 'source':'container'}
                    with patch.object(module, 'frozen', return_value=base), \
                            patch.object(module, 'worker_observation', side_effect=worker_result), \
                            patch.object(module.subprocess, 'run', side_effect=AssertionError('no worker or nginx command')):
                        publisher = module.load_base()
                        if os.name == 'nt':
                            original_wire = publisher.atomic
                            def windows_atomic(path, body, mode=0o644):
                                row = next((r for r in manifest['files'] if path == base.rooted(system,r['target'])), None)
                                return original_wire(path, body, int(row['mode'],8) if row else mode)
                            publisher.atomic = windows_atomic
                        raw = (stage/'approved-manifest.json').read_bytes()
                        for error in ('protection_missing','protection_duplicate','extra_target','mode','owner','before','expired','mixed_mode','zero_delta','duplicate_target'):
                            altered=deepcopy(manifest)
                            if error=='protection_missing':altered['unchangedRequired'].pop()
                            elif error=='protection_duplicate':altered['unchangedRequired'].append(deepcopy(altered['unchangedRequired'][0]))
                            elif error=='extra_target':altered['files'].append({'candidate':'runtime/unrelated.py','target':'/opt/unrelated.py','beforeSha256':'a'*64,'sha256':'b'*64})
                            elif error in ('mode','owner','before'):
                                row=next(r for r in altered['files'] if r['candidate']==candidate)
                                row[{'mode':'mode','owner':'owner','before':'beforeSha256'}[error]]={'mode':'0o600','owner':'1:1','before':'0'*64}[error]
                            elif error=='expired':altered['baselineObservedAt']=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
                            elif error=='mixed_mode':altered['materialTransport' if stream else 'materialStream']=True
                            elif error=='duplicate_target':altered['files'].append(deepcopy(altered['files'][0]))
                            else:
                                row=next(r for r in altered['files'] if r['candidate']==candidate);row['sha256']=row['beforeSha256'];altered['materialChangedTargets']=[]
                            (stage/'approved-manifest.json').write_bytes(json.dumps(altered).encode())
                            # A fresh frozen validator observes this as its own
                            # approved file, so manifest-identity alone cannot pass.
                            # Each rejected CLI run exits with its own mode globals;
                            # do not leak a deliberately mixed mode into apply below.
                            with patch.multiple(module, **{k:deepcopy(getattr(module,k)) for k in names}), \
                                    patch.object(module,'frozen',return_value=release.frozen()):
                                alternate=module.load_base()
                                with self.subTest(loaded_manifest=error),self.assertRaises(ValueError):alternate.validate(altered,stage)
                        (stage/'approved-manifest.json').write_bytes(raw)
                        publisher.inspect(manifest,stage,system)
                        for field, value in (('runtimeBefore', dict(manifest['runtimeBefore'], **{'fs-hermes-fc.service':{'ActiveState':'failed'}})),
                                             ('workerImageSource','configured_unit_and_local_image'),
                                             ('workerDiagnostics',True), ('materialChangedTargets',[]),
                                             ('baselineObservedAt',(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat())):
                            bad = deepcopy(manifest); bad[field] = value
                            with self.subTest(field=field), self.assertRaises(ValueError): publisher.validate(bad,stage)
                        for observation in ({'image':manifest['workerImageId'],'state':'failed','source':'container'},
                                            {'image':manifest['workerImageId'],'state':'active','source':'configured_unit_and_local_image'},
                                            {'image':'sha256:'+'1'*64,'state':'active','source':'container'}):
                            with patch.object(module,'worker_observation',return_value=observation), self.assertRaises(ValueError):
                                publisher.inspect(manifest,stage,system)
                        with patch.object(module,'worker_observation',side_effect=ValueError('current_worker_container_unavailable')), self.assertRaises(ValueError):
                            publisher.inspect(manifest,stage,system)
                        if fail:
                            error, message = (RuntimeError,'worker health failure') if fail == 'restart' else (ValueError,'current_worker_container_unavailable')
                            with self.assertRaisesRegex(error,message):
                                publisher.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261101T000005Z',system)
                        else: publisher.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261101T000005Z',system)
                        self.assertEqual(set(writes),{base.rooted(system,target)})
                        self.assertGreaterEqual(len(guards),28)
                        self.assertTrue(original_restart.called)
                        self.assertTrue(all(c.args[0]['scope']==base.DEEP_SCOPE for c in original_restart.call_args_list))
                        self.assertTrue(fence.stop_then_unlock_database.called)
                        for row in manifest['files']:
                            path=base.rooted(system,row['target']); self.assertTrue(path.exists())
                            self.assertEqual(base.digest(path),row['beforeSha256'] if fail else row['sha256'])
                            if row['target'] in unchanged:
                                self.assertEqual((path.stat().st_ino,path.stat().st_mtime_ns),unchanged[row['target']])
        finally:
            for key,value in saved_release.items():setattr(release,key,value)
            for key,value in saved_prepare.items():setattr(prepare,key,value)
            prepare.TARGETS=release.TARGETS

    def test_worker_diagnostics_1b20_single_module_proof_delta_and_rollback(self):
        self.assertTrue(callable(getattr(prepare, 'configure_worker_diagnostics', None)), 'worker-only installed followup missing')
        names = ('TARGETS', 'NEW', 'INSTALLED_COMMIT', 'INSTALLED_PROOF', 'EXECUTION_MODE', 'DIAGNOSTICS_MODE', 'TASK_INDEX_MODE', 'WORKER_DIAGNOSTICS_MODE')
        saved_release = {k: deepcopy(getattr(release, k)) for k in names}
        saved_prepare = {k: deepcopy(getattr(prepare, k)) for k in ('TARGETS', 'NEW', 'INSTALLED_COMMIT', 'INSTALLED_PROOF', 'SOURCES')}
        try:
            prepare.configure_worker_diagnostics()
            self.assertTrue(release.WORKER_DIAGNOSTICS_MODE); self.assertFalse(release.TASK_INDEX_MODE); self.assertFalse(release.DIAGNOSTICS_MODE)
            self.assertEqual(release.NEW, frozenset())
            self.assertEqual(release.INSTALLED_PROOF, {
                'sourceCommit':'1b20b91f2e7e023d90a0197053916ba9a59978e6',
                'backup':'/var/backups/fs-navigation-20261006/nav-20261101T062133Z',
                'manifestSha256':'16615694e66cda7dcfffa4ba55381d21071b51cf45b3597be303f5ba2af4f235',
                'journalSha256':'912511fd8fc877d9155ca6fec30ec8bdf9ff5bd94b94d6443d4f764e529c2446'})
            with tempfile.TemporaryDirectory() as packed:
                def blob(command, **kwargs):
                    self.assertEqual(command[:2], ['git', 'show'])
                    return ('git-blob:'+command[2]).encode()
                with patch.object(prepare.subprocess, 'check_output', side_effect=blob):
                    prepare.pack(Path(packed), Path(packed)/'bundle', 'b'*40)
                descriptor=json.loads((Path(packed)/'bundle/payload-manifest.json').read_bytes())
                self.assertTrue(descriptor['worker_diagnostics']); self.assertFalse(descriptor['material_diagnostics'])
                self.assertEqual(descriptor['installed_baseline']['source_commit'], release.INSTALLED_COMMIT)
                self.assertEqual(set(descriptor['installed_baseline']['files']), set(release.TARGETS))
                self.assertTrue(all(v is not None for v in descriptor['installed_baseline']['files'].values()))
            for fail in (None, 'restart', 'container'):
                with self.subTest(rollback=fail), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    base, system, payload, metadata, _, proof, previous = self.installed_fixture(root)
                    descriptor_path = payload.parent/'payload-manifest.json'
                    descriptor = json.loads(descriptor_path.read_bytes())
                    descriptor.update(material_execution=True, material_diagnostics=False, goal_task_index_compat=False, worker_diagnostics=True)
                    for name in prepare.SOURCES:
                        before = base.rooted(system, release.TARGETS[name]).read_bytes()
                        body = before+b'\n# worker diagnostics\n' if name == 'runtime/hermes_worker.py' else before
                        (payload/name).write_bytes(body); descriptor['files']['payload/'+name] = prepare.digest(body)
                    raw = json.dumps(descriptor).encode(); descriptor_path.write_bytes(raw)
                    stage = root/'worker-stage'
                    with patch.object(release, 'INSTALLED_PROOF', proof), patch.object(prepare, 'INSTALLED_PROOF', proof), \
                            patch.object(prepare, 'file_metadata', metadata):
                        observed = prepare.observe(system, previous)
                        for key, value in (('worker_state','failed'), ('worker_state','inactive'),
                                           ('worker_image_source','configured_unit_and_local_image')):
                            with patch.object(prepare,'observe',return_value=dict(observed, **{key:value})), self.assertRaises(ValueError):
                                prepare.prepare(payload, root/'bad-runtime', 'a'*40, prepare.digest(raw), root=system, followup=True)
                            self.assertFalse((root/'bad-runtime').exists())
                        prepare.prepare(payload, stage, 'a'*40, prepare.digest(raw), root=system, followup=True, release_ready=True)
                        for case in ('old_proof', 'git', 'journal', 'protected', 'extra_http', 'worker_before', 'no_delta'):
                            changed = deepcopy(descriptor); restore = None
                            if case == 'old_proof': changed['installed_baseline']['source_commit'] = 'f79e29f0d5921b103a218c5e6ed967a754858b9c'
                            elif case == 'git': changed['installed_baseline']['files']['runtime/hermes_worker.py'] = '0'*64
                            else:
                                path = (payload/'runtime/hermes_worker.py' if case == 'no_delta' else payload/'http/conversation_http.py' if case == 'extra_http' else
                                        base.rooted(system, proof['backup']+'/journal.json') if case == 'journal' else
                                        base.rooted(system, previous['unchangedRequired'][0]['path']) if case == 'protected' else
                                        base.rooted(system, release.TARGETS['runtime/hermes_worker.py']))
                                restore = (path, path.read_bytes())
                                path.write_bytes(base.rooted(system, release.TARGETS['runtime/hermes_worker.py']).read_bytes() if case == 'no_delta' else b'unapproved drift')
                                if case == 'extra_http': changed['files']['payload/http/conversation_http.py'] = prepare.digest(path.read_bytes())
                                if case == 'no_delta': changed['files']['payload/runtime/hermes_worker.py'] = prepare.digest(path.read_bytes())
                            bad = json.dumps(changed).encode(); descriptor_path.write_bytes(bad)
                            with self.subTest(rejected=case), self.assertRaises(ValueError):
                                prepare.prepare(payload, root/('reject-'+case), 'a'*40, prepare.digest(bad), root=system, followup=True)
                            self.assertFalse((root/('reject-'+case)).exists())
                            if restore: restore[0].write_bytes(restore[1])
                        descriptor_path.write_bytes(raw)
                    manifest = json.loads((stage/'approved-manifest.json').read_bytes())
                    self.assertTrue(manifest['workerDiagnostics']); self.assertNotIn('materialDiagnostics', manifest)
                    self.assertFalse(manifest['materialStaticOnly'])
                    self.assertEqual((len(manifest['files']), len(manifest['unchangedRequired'])), (24, 46))
                    self.assertTrue(all(r['beforeSha256'] is not None for r in manifest['files']))
                    target = release.TARGETS['runtime/hermes_worker.py']
                    self.assertEqual(manifest['materialChangedTargets'], [target])
                    unchanged = {r['target']:(base.rooted(system,r['target']).stat().st_ino,base.rooted(system,r['target']).stat().st_mtime_ns)
                                 for r in manifest['files'] if r['target'] != target}
                    spec = importlib.util.spec_from_file_location('worker_diagnostics_publisher', stage/'runtime_release.py')
                    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                    module.configure_worker_diagnostics(); module.INSTALLED_PROOF = proof
                    guards = []
                    def guard(current, host, reader_stopped=False):
                        guards.append(True)
                        self.assertEqual(current['runtimeRequired'], manifest['runtimeRequired'])
                        for row in current['unchangedRequired']:
                            self.assertEqual(base.digest(base.rooted(host, row['path'])), row['sha256'])
                    base.guards = guard; base.retirement = lambda *a: None
                    base.locks = base.live_lock = base.model_release_lock = lambda *a: nullcontext()
                    fence = SimpleNamespace(modified=False, confirmed=False, stop_then_unlock_database=Mock())
                    base.hermes_admission_fence = lambda *a: nullcontext(fence)
                    def restart_result(*args):
                        if fail == 'restart' and original_restart.call_count == 1:
                            raise RuntimeError('worker health failure')
                    original_restart = Mock(side_effect=restart_result)
                    base.restart_for = original_restart
                    writes = []; original_atomic = base.atomic
                    targets = {base.rooted(system,r['target']) for r in manifest['files']}
                    def atomic(path, body, mode=0o644):
                        if path in targets: writes.append(path)
                        return original_atomic(path, body, mode)
                    base.atomic = atomic
                    if os.name == 'nt': base.directory_sync = lambda *a: None
                    def worker_result(**kwargs):
                        self.assertFalse(kwargs.get('allow_stopped',False))
                        if fail == 'container' and original_restart.call_count == 1:
                            raise ValueError('current_worker_container_unavailable')
                        return {'image':manifest['workerImageId'], 'state':'active', 'source':'container'}
                    with patch.object(module, 'frozen', return_value=base), \
                            patch.object(module, 'worker_observation', side_effect=worker_result), \
                            patch.object(module.subprocess, 'run', side_effect=AssertionError('no worker or nginx command')):
                        publisher = module.load_base()
                        if os.name == 'nt':
                            original_wire = publisher.atomic
                            def windows_atomic(path, body, mode=0o644):
                                row = next((r for r in manifest['files'] if path == base.rooted(system,r['target'])), None)
                                return original_wire(path, body, int(row['mode'],8) if row else mode)
                            publisher.atomic = windows_atomic
                        raw = (stage/'approved-manifest.json').read_bytes()
                        publisher.inspect(manifest,stage,system)
                        for field, value in (('runtimeBefore', dict(manifest['runtimeBefore'], **{'fs-hermes-fc.service':{'ActiveState':'failed'}})),
                                             ('workerImageSource','configured_unit_and_local_image'),
                                             ('goalTaskIndexCompat',True), ('materialChangedTargets',[]),
                                             ('baselineObservedAt',(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat())):
                            bad = deepcopy(manifest); bad[field] = value
                            with self.subTest(field=field), self.assertRaises(ValueError): publisher.validate(bad,stage)
                        for observation in ({'image':manifest['workerImageId'],'state':'failed','source':'container'},
                                            {'image':manifest['workerImageId'],'state':'active','source':'configured_unit_and_local_image'},
                                            {'image':'sha256:'+'1'*64,'state':'active','source':'container'}):
                            with patch.object(module,'worker_observation',return_value=observation), self.assertRaises(ValueError):
                                publisher.inspect(manifest,stage,system)
                        with patch.object(module,'worker_observation',side_effect=ValueError('current_worker_container_unavailable')), self.assertRaises(ValueError):
                            publisher.inspect(manifest,stage,system)
                        if fail:
                            error, message = (RuntimeError,'worker health failure') if fail == 'restart' else (ValueError,'current_worker_container_unavailable')
                            with self.assertRaisesRegex(error,message):
                                publisher.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261101T000005Z',system)
                        else: publisher.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261101T000005Z',system)
                        self.assertEqual(set(writes),{base.rooted(system,target)})
                        self.assertGreaterEqual(len(guards),27)
                        self.assertTrue(original_restart.called)
                        self.assertTrue(all(c.args[0]['scope']==base.HERMES_WORKER_SCOPE for c in original_restart.call_args_list))
                        self.assertFalse(fence.stop_then_unlock_database.called)
                        for row in manifest['files']:
                            path=base.rooted(system,row['target']); self.assertTrue(path.exists())
                            self.assertEqual(base.digest(path),row['beforeSha256'] if fail else row['sha256'])
                            if row['target'] in unchanged:
                                self.assertEqual((path.stat().st_ino,path.stat().st_mtime_ns),unchanged[row['target']])
        finally:
            for key,value in saved_release.items():setattr(release,key,value)
            for key,value in saved_prepare.items():setattr(prepare,key,value)
            prepare.TARGETS=release.TARGETS

    def test_goal_task_index_f79_single_module_proof_delta_and_rollback(self):
        names = ('TARGETS', 'NEW', 'INSTALLED_COMMIT', 'INSTALLED_PROOF', 'EXECUTION_MODE', 'DIAGNOSTICS_MODE', 'TASK_INDEX_MODE')
        saved_release = {k: deepcopy(getattr(release, k)) for k in names}
        saved_prepare = {k: deepcopy(getattr(prepare, k)) for k in ('TARGETS', 'NEW', 'INSTALLED_COMMIT', 'INSTALLED_PROOF', 'SOURCES')}
        try:
            prepare.configure_task_index_compat()
            self.assertTrue(release.TASK_INDEX_MODE); self.assertFalse(release.DIAGNOSTICS_MODE)
            self.assertEqual(release.NEW, frozenset())
            self.assertEqual(release.INSTALLED_PROOF, {
                'sourceCommit':'f79e29f0d5921b103a218c5e6ed967a754858b9c',
                'backup':'/var/backups/fs-navigation-20261006/nav-20261101T024500Z',
                'manifestSha256':'25cd452cfb25790502cab7a7561187f04da5af6e2096baf9a71fabb11ad199ee',
                'journalSha256':'534a813b17ea54422131403075156ec82fa2696959c575211e29cee3c0c6cdab'})
            with tempfile.TemporaryDirectory() as packed:
                def blob(command, **kwargs):
                    self.assertEqual(command[:2], ['git', 'show'])
                    return ('git-blob:'+command[2]).encode()
                with patch.object(prepare.subprocess, 'check_output', side_effect=blob):
                    prepare.pack(Path(packed), Path(packed)/'bundle', 'b'*40)
                descriptor=json.loads((Path(packed)/'bundle/payload-manifest.json').read_bytes())
                self.assertTrue(descriptor['goal_task_index_compat']); self.assertFalse(descriptor['material_diagnostics'])
                self.assertEqual(descriptor['installed_baseline']['source_commit'], release.INSTALLED_COMMIT)
                self.assertEqual(set(descriptor['installed_baseline']['files']), set(release.TARGETS))
                self.assertTrue(all(v is not None for v in descriptor['installed_baseline']['files'].values()))
            for fail in (False, True):
                with self.subTest(rollback=fail), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    base, system, payload, metadata, _, proof, previous = self.installed_fixture(root)
                    descriptor_path = payload.parent/'payload-manifest.json'
                    descriptor = json.loads(descriptor_path.read_bytes())
                    descriptor.update(material_execution=True, material_diagnostics=False, goal_task_index_compat=True)
                    for name in prepare.SOURCES:
                        before = base.rooted(system, release.TARGETS[name]).read_bytes()
                        body = before+b'\n# index compat\n' if name == 'runtime/conversation_goal_tasks.py' else before
                        (payload/name).write_bytes(body); descriptor['files']['payload/'+name] = prepare.digest(body)
                    raw = json.dumps(descriptor).encode(); descriptor_path.write_bytes(raw)
                    stage = root/'index-stage'
                    with patch.object(release, 'INSTALLED_PROOF', proof), patch.object(prepare, 'INSTALLED_PROOF', proof), \
                            patch.object(prepare, 'file_metadata', metadata):
                        prepare.prepare(payload, stage, 'a'*40, prepare.digest(raw), root=system, followup=True, release_ready=True)
                        for case in ('old_proof', 'extra_http'):
                            changed = deepcopy(descriptor)
                            if case == 'old_proof': changed['installed_baseline']['source_commit'] = '5f99f5b3eeca8bdf974de1dcd913508ff4c89c1f'
                            else:
                                (payload/'http/conversation_http.py').write_bytes(b'unapproved HTTP delta')
                                changed['files']['payload/http/conversation_http.py'] = prepare.digest(b'unapproved HTTP delta')
                            bad = json.dumps(changed).encode(); descriptor_path.write_bytes(bad)
                            with self.assertRaises(ValueError):
                                prepare.prepare(payload, root/('reject-'+case), 'a'*40, prepare.digest(bad), root=system, followup=True)
                            self.assertFalse((root/('reject-'+case)).exists())
                        descriptor_path.write_bytes(raw)
                        (payload/'http/conversation_http.py').write_bytes(base.rooted(system, release.TARGETS['http/conversation_http.py']).read_bytes())
                    manifest = json.loads((stage/'approved-manifest.json').read_bytes())
                    self.assertTrue(manifest['goalTaskIndexCompat']); self.assertNotIn('materialDiagnostics', manifest)
                    self.assertFalse(manifest['materialStaticOnly'])
                    self.assertEqual((len(manifest['files']), len(manifest['unchangedRequired'])), (24, 46))
                    self.assertTrue(all(r['beforeSha256'] is not None for r in manifest['files']))
                    target = release.TARGETS['runtime/conversation_goal_tasks.py']
                    self.assertEqual(manifest['materialChangedTargets'], [target])
                    unchanged = {r['target']:(base.rooted(system,r['target']).stat().st_ino,base.rooted(system,r['target']).stat().st_mtime_ns)
                                 for r in manifest['files'] if r['target'] != target}
                    spec = importlib.util.spec_from_file_location('index_compat_publisher', stage/'runtime_release.py')
                    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                    module.configure_task_index_compat(); module.INSTALLED_PROOF = proof
                    guards = []
                    def guard(current, host, reader_stopped=False):
                        guards.append(True)
                        self.assertEqual(current['runtimeRequired'], manifest['runtimeRequired'])
                        for row in current['unchangedRequired']:
                            self.assertEqual(base.digest(base.rooted(host, row['path'])), row['sha256'])
                    base.guards = guard; base.retirement = lambda *a: None
                    base.locks = base.live_lock = base.model_release_lock = lambda *a: nullcontext()
                    fence = SimpleNamespace(modified=False, confirmed=False, stop_then_unlock_database=Mock())
                    base.hermes_admission_fence = lambda *a: nullcontext(fence)
                    original_restart = Mock(side_effect=[RuntimeError('index range failure'), None] if fail else None)
                    base.restart_for = original_restart
                    writes = []; original_atomic = base.atomic
                    targets = {base.rooted(system,r['target']) for r in manifest['files']}
                    def atomic(path, body, mode=0o644):
                        if path in targets: writes.append(path)
                        return original_atomic(path, body, mode)
                    base.atomic = atomic
                    if os.name == 'nt': base.directory_sync = lambda *a: None
                    with patch.object(module, 'frozen', return_value=base), \
                            patch.object(module, 'worker_image', return_value=manifest['workerImageId']), \
                            patch.object(module.subprocess, 'run', side_effect=AssertionError('no worker or nginx command')):
                        publisher = module.load_base()
                        if os.name == 'nt':
                            original_wire = publisher.atomic
                            def windows_atomic(path, body, mode=0o644):
                                row = next((r for r in manifest['files'] if path == base.rooted(system,r['target'])), None)
                                return original_wire(path, body, int(row['mode'],8) if row else mode)
                            publisher.atomic = windows_atomic
                        raw = (stage/'approved-manifest.json').read_bytes()
                        publisher.inspect(manifest,stage,system)
                        if fail:
                            with self.assertRaisesRegex(RuntimeError,'index range failure'):
                                publisher.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261101T000005Z',system)
                        else: publisher.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261101T000005Z',system)
                        self.assertEqual(set(writes),{base.rooted(system,target)})
                        self.assertGreaterEqual(len(guards),27)
                        self.assertTrue(original_restart.called)
                        self.assertTrue(all(c.args[0]['scope']==base.DEEP_SCOPE for c in original_restart.call_args_list))
                        self.assertTrue(fence.stop_then_unlock_database.called)
                        for row in manifest['files']:
                            path=base.rooted(system,row['target']); self.assertTrue(path.exists())
                            self.assertEqual(base.digest(path),row['beforeSha256'] if fail else row['sha256'])
                            if row['target'] in unchanged:
                                self.assertEqual((path.stat().st_ino,path.stat().st_mtime_ns),unchanged[row['target']])
        finally:
            for key,value in saved_release.items():setattr(release,key,value)
            for key,value in saved_prepare.items():setattr(prepare,key,value)
            prepare.TARGETS=release.TARGETS

    def test_diagnostics_5f99_existing24_proof_delta_cas_and_original_apply_rollback(self):
        names = ('TARGETS', 'NEW', 'INSTALLED_COMMIT', 'INSTALLED_PROOF', 'EXECUTION_MODE', 'DIAGNOSTICS_MODE')
        saved_release = {k: deepcopy(getattr(release, k)) for k in names}
        saved_prepare = {k: deepcopy(getattr(prepare, k)) for k in ('TARGETS', 'NEW', 'INSTALLED_COMMIT', 'INSTALLED_PROOF', 'SOURCES')}
        try:
            prepare.configure_diagnostics()
            self.assertEqual(release.INSTALLED_COMMIT, '5f99f5b3eeca8bdf974de1dcd913508ff4c89c1f')
            self.assertEqual(release.INSTALLED_PROOF, {
                'sourceCommit': release.INSTALLED_COMMIT,
                'backup': '/var/backups/fs-navigation-20261006/nav-20261101T013519Z',
                'manifestSha256': '4057435dce473622c5ef2f88ba0d55255a9f7b588a6e193f70a41cffca409881',
                'journalSha256': '3f6d474d37716610de334f14b9b7a699f879aae170471c065f5007c47e3ab93d'})
            self.assertEqual(len(release.TARGETS), 24); self.assertEqual(release.NEW, frozenset())
            with tempfile.TemporaryDirectory() as packed:
                calls = []
                def git_blob(command, **kwargs):
                    self.assertEqual(command[:2], ['git', 'show'])
                    calls.append(command[2])
                    return ('exact-git-blob:' + command[2]).encode()
                with patch.object(prepare.subprocess, 'check_output', side_effect=git_blob):
                    prepare.pack(Path(packed), Path(packed)/'bundle', 'b'*40)
                descriptor = json.loads((Path(packed)/'bundle/payload-manifest.json').read_bytes())
                self.assertTrue(descriptor['material_diagnostics']); self.assertTrue(descriptor['material_execution'])
                self.assertEqual(descriptor['installed_baseline']['source_commit'], release.INSTALLED_COMMIT)
                self.assertEqual(set(descriptor['installed_baseline']['files']), set(release.TARGETS))
                self.assertTrue(all(v is not None for v in descriptor['installed_baseline']['files'].values()))
                for name in release.EXECUTION_MODULES:
                    self.assertIn(release.INSTALLED_COMMIT+':'+prepare.SOURCES['runtime/'+name], calls)
            for fail in (False, True):
                with self.subTest(rollback=fail), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    base, system, payload, metadata, _, proof, previous = self.installed_fixture(root)
                    descriptor_path = payload.parent / 'payload-manifest.json'
                    descriptor = json.loads(descriptor_path.read_bytes())
                    descriptor.update(material_execution=True, material_diagnostics=True)
                    changed_names = ('http/conversation_http.py', 'http/range_api.py')
                    for name in prepare.SOURCES:
                        before = base.rooted(system, release.TARGETS[name]).read_bytes()
                        body = before + b'\n# diagnostic\n' if name in changed_names else before
                        (payload / name).write_bytes(body)
                        descriptor['files']['payload/' + name] = prepare.digest(body)
                    raw = json.dumps(descriptor).encode(); descriptor_path.write_bytes(raw)
                    stage = root / 'diagnostics-stage'
                    with patch.object(release, 'INSTALLED_PROOF', proof), patch.object(prepare, 'INSTALLED_PROOF', proof), \
                            patch.object(prepare, 'file_metadata', metadata):
                        prepare.prepare(payload, stage, 'a'*40, prepare.digest(raw), root=system, followup=True, release_ready=True)
                        manifest = json.loads((stage/'approved-manifest.json').read_bytes())
                        self.assertTrue(manifest['materialDiagnostics']); self.assertFalse(manifest['materialStaticOnly'])
                        self.assertEqual(len(manifest['files']), 24); self.assertEqual(len(manifest['unchangedRequired']), 46)
                        self.assertTrue(all(r['beforeSha256'] is not None for r in manifest['files']))
                        self.assertEqual(manifest['materialChangedTargets'], [release.TARGETS[n] for n in changed_names])
                        # Existing NEW8 must never be accepted as absent, nor may
                        # another target/protected byte or the proof be reflected
                        # into a newly invented baseline.
                        for key in ('missing_module', 'target', 'protected', 'proof'):
                            path = (base.rooted(system, release.TARGETS['runtime/conversation_material_runs.py']) if key == 'missing_module' else
                                    base.rooted(system, release.TARGETS['runtime/conversation_store.py']) if key == 'target' else
                                    base.rooted(system, previous['unchangedRequired'][0]['path']) if key == 'protected' else
                                    base.rooted(system, proof['backup']+'/journal.json'))
                            saved = path.read_bytes()
                            if key == 'missing_module': path.unlink()
                            else: path.write_bytes(b'drift')
                            try:
                                with self.assertRaises((OSError, ValueError)):
                                    prepare.prepare(payload, root/('rejected-'+key), 'a'*40, prepare.digest(raw), root=system, followup=True)
                                self.assertFalse((root/('rejected-'+key)).exists())
                            finally: path.write_bytes(saved)
                    spec = importlib.util.spec_from_file_location('diagnostics_publisher', stage/'runtime_release.py')
                    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                    module.configure_diagnostics(); module.INSTALLED_PROOF = proof
                    guard_calls = []
                    def guards(current, host, reader_stopped=False):
                        guard_calls.append(current['runtimeRequired'])
                        self.assertEqual(current['runtimeRequired'], manifest['runtimeRequired'])
                        for row in current['unchangedRequired']:
                            self.assertEqual(base.digest(base.rooted(host, row['path'])), row['sha256'])
                    base.guards = guards; base.retirement = lambda *a: None
                    base.locks = base.live_lock = base.model_release_lock = lambda *a: nullcontext()
                    fence = SimpleNamespace(modified=False, confirmed=False, stop_then_unlock_database=Mock())
                    base.hermes_admission_fence = lambda *a: nullcontext(fence)
                    original_restart = Mock(side_effect=[RuntimeError('synthetic range failure'), None] if fail else None)
                    base.restart_for = original_restart
                    writes = []; original_atomic = base.atomic
                    target_paths = {base.rooted(system, r['target']) for r in manifest['files']}
                    def atomic(path, body, mode=0o644):
                        if path in target_paths: writes.append(path)
                        if os.name == 'nt':
                            row = next((r for r in manifest['files'] if path == base.rooted(system, r['target'])), None)
                            if row: mode = int(row['mode'], 8)
                        return original_atomic(path, body, mode)
                    base.atomic = atomic
                    if os.name == 'nt': base.directory_sync = lambda *a: None
                    with patch.object(module, 'frozen', return_value=base), \
                            patch.object(module, 'worker_image', return_value=manifest['workerImageId']), \
                            patch.object(module.subprocess, 'run', side_effect=AssertionError('no worker or nginx command')):
                        publisher = module.load_base()
                        if os.name == 'nt':
                            original_wire = publisher.atomic
                            def windows_atomic(path, body, mode=0o644):
                                row = next((r for r in manifest['files'] if path == base.rooted(system, r['target'])), None)
                                return original_wire(path, body, int(row['mode'], 8) if row else mode)
                            publisher.atomic = windows_atomic
                        raw = (stage/'approved-manifest.json').read_bytes()
                        publisher.inspect(manifest, stage, system)
                        if fail:
                            with self.assertRaisesRegex(RuntimeError, 'synthetic range failure'):
                                publisher.apply(manifest, stage, prepare.digest(raw), raw, 'nav-20261101T000004Z', system)
                        else:
                            publisher.apply(manifest, stage, prepare.digest(raw), raw, 'nav-20261101T000004Z', system)
                        self.assertGreaterEqual(len(guard_calls), 27)
                        self.assertEqual(set(writes), {base.rooted(system, release.TARGETS[n]) for n in changed_names})
                        for call in original_restart.call_args_list:
                            self.assertEqual(call.args[0]['scope'], base.DEEP_SCOPE)
                        self.assertGreaterEqual(fence.stop_then_unlock_database.call_count, 1)
                        for row in manifest['files']:
                            path = base.rooted(system, row['target'])
                            self.assertTrue(path.exists())
                            self.assertEqual(base.digest(path), row['beforeSha256'] if fail else row['sha256'])
                        journal = json.loads((base.rooted(system, '/var/backups/fs-navigation-20261006/nav-20261101T000004Z')/'journal.json').read_bytes())
                        self.assertEqual(journal['status'], 'rolled-back' if fail else 'applied-awaiting-actual-http-role-acceptance')
        finally:
            for key, value in saved_release.items(): setattr(release, key, value)
            for key, value in saved_prepare.items(): setattr(prepare, key, value)
            prepare.TARGETS = release.TARGETS

    def test_material_execution_501f_proof_composition_and_failed_apply_restore_installed_modules(self):
        # Isolate the explicit new publisher mode from the old first-install and
        # static-followup fixtures in this same existing test entry.
        names=('TARGETS','NEW','INSTALLED_COMMIT','INSTALLED_PROOF','EXECUTION_MODE')
        old_release={k:deepcopy(getattr(release,k)) for k in names}
        old_prepare={k:deepcopy(getattr(prepare,k)) for k in ('TARGETS','NEW','INSTALLED_COMMIT','INSTALLED_PROOF','SOURCES')}
        try:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                base,system,payload,metadata,_,_,previous=self.installed_fixture(root)
                prepare.configure_execution()
                base=release.frozen()
                proof=dict(release.INSTALLED_PROOF)
                previous['sourceCommit']=release.INSTALLED_COMMIT
                backup=base.rooted(system,proof['backup']);backup.mkdir(parents=True)
                raw=json.dumps(previous).encode();(backup/'approved-manifest.json').write_bytes(raw)
                proof['manifestSha256']=prepare.digest(raw)
                raw=json.dumps(dict(status='applied-awaiting-actual-http-role-acceptance',manifest=previous,
                    approvedManifestSha256=proof['manifestSha256'])).encode()
                (backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
                old={v['candidate']:v['sha256'] for v in previous['files']}
                protected={v['path']:v['sha256'] for v in previous['unchangedRequired']}
                baseline={}
                for name,target in release.TARGETS.items():
                    baseline[name]=old[name] if name in old else None if name in release.NEW else protected[target]
                    if name!='http/formal.conf':
                        path=payload/name;path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_bytes(('execution-candidate:'+name).encode())
                descriptor=json.loads((payload.parent/'payload-manifest.json').read_bytes())
                descriptor.update(material_execution=True,installed_baseline={'source_commit':release.INSTALLED_COMMIT,'files':baseline})
                descriptor['files'].update({'payload/'+name:prepare.digest((payload/name).read_bytes()) for name in prepare.SOURCES})
                raw=json.dumps(descriptor).encode();(payload.parent/'payload-manifest.json').write_bytes(raw)
                stage=root/'execution-stage'
                with patch.object(release,'INSTALLED_PROOF',proof),patch.object(prepare,'INSTALLED_PROOF',proof),patch.object(prepare,'file_metadata',metadata):
                    prepare.prepare(payload,stage,'a'*40,prepare.digest(raw),root=system,followup=True,release_ready=True)
                    manifest=json.loads((stage/'approved-manifest.json').read_bytes())
                    self.assertTrue(manifest['materialExecution']);self.assertFalse(manifest['materialStaticOnly'])
                    self.assertEqual(len(manifest['files']),24);self.assertEqual(len(manifest['unchangedRequired']),46)
                    self.assertEqual(sum(r['beforeSha256'] is None for r in manifest['files']),8)
                    for name in ('conversation_files.py','conversation_file_bindings.py','conversation_file_tools.py','material_evidence.py'):
                        self.assertIsNotNone(next(r['beforeSha256'] for r in manifest['files'] if r['candidate']=='runtime/'+name))
                    # A drift is refused before creating another stage.
                    target=base.rooted(system,release.TARGETS['runtime/fs_inprocess.py']);saved=target.read_bytes();target.write_bytes(b'drift')
                    with self.assertRaisesRegex(ValueError,'baseline_drift'):
                        prepare.prepare(payload,root/'drift-stage','a'*40,prepare.digest(raw),root=system,followup=True)
                    target.write_bytes(saved)
                spec=importlib.util.spec_from_file_location('execution_publisher_fixture',stage/'runtime_release.py')
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                module.configure_execution();module.INSTALLED_PROOF=proof
                base.guards=lambda *a,**kw:None
                base.retirement=lambda *a:None
                base.locks=base.live_lock=base.model_release_lock=lambda *a:nullcontext()
                base.hermes_admission_fence=lambda *a:nullcontext(SimpleNamespace(modified=False,confirmed=False))
                base.restart_for=Mock(side_effect=RuntimeError('synthetic restart failure'))
                if os.name=='nt':base.directory_sync=lambda *a:None
                with patch.object(module,'frozen',return_value=base),patch.object(module,'worker_image',return_value=manifest['workerImageId']),patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=0)):
                    publisher=module.load_base()
                    if os.name=='nt':
                        original=publisher.atomic
                        def atomic(path,data,mode=0o644):
                            row=next((r for r in manifest['files'] if path==base.rooted(system,r['target'])),None)
                            return original(path,data,int(row['mode'],8) if row else mode)
                        publisher.atomic=atomic
                    manifest_raw=(stage/'approved-manifest.json').read_bytes()
                    publisher.inspect(manifest,stage,system)
                    with self.assertRaises(RuntimeError):publisher.apply(manifest,stage,prepare.digest(manifest_raw),manifest_raw,'nav-20261101T000003Z',system)
                for row in manifest['files']:
                    self.assertEqual(base.digest(base.rooted(system,row['target'])),row['beforeSha256'])
        finally:
            for key,value in old_release.items():setattr(release,key,value)
            for key,value in old_prepare.items():setattr(prepare,key,value)
            # prepare and release intentionally share the authoritative target map.
            prepare.TARGETS=release.TARGETS

    def installed_fixture(self, root):
        base, system, payload, known, metadata, sha = self.fixture(root)
        previous = {'sourceCommit': release.INSTALLED_COMMIT, 'scope': release.SCOPE, 'files': [],
                    'unchangedRequired': [], 'workerImageId': 'sha256:' + '0' * 64}
        descriptor = json.loads((payload.parent / 'payload-manifest.json').read_bytes())
        for name, target in release.TARGETS.items():
            body = prepare.patch_nginx(NGINX) if target == release.NGINX else ('installed:' + name).encode()
            path = base.rooted(system, target); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
            if os.name == 'posix': path.chmod(0o600 if target == release.NGINX else 0o644)
            previous['files'].append({'candidate': name, 'target': target, 'sha256': prepare.digest(body)})
            if name in prepare.SOURCES and name not in ('frontend/conversation.js', 'frontend/conversation.css'):
                (payload / name).write_bytes(body)
            if name in prepare.SOURCES:
                descriptor['files']['payload/' + name] = prepare.digest((payload / name).read_bytes())
        previous['unchangedRequired'] = [{'path': p, 'sha256': prepare.digest(base.rooted(system, p).read_bytes())}
                                         for p in sorted(release.protected_paths(base))]
        descriptor['installed_baseline'] = {'source_commit': release.INSTALLED_COMMIT,
                                          'files': {r['candidate']: r['sha256'] for r in previous['files']}}
        proof = dict(release.INSTALLED_PROOF)
        backup = base.rooted(system, proof['backup']); backup.mkdir(parents=True)
        raw = json.dumps(previous).encode(); (backup / 'approved-manifest.json').write_bytes(raw)
        proof['manifestSha256'] = prepare.digest(raw)
        journal = {'status': 'applied-awaiting-actual-http-role-acceptance', 'manifest': previous,
                   'approvedManifestSha256': proof['manifestSha256']}
        raw = json.dumps(journal).encode(); (backup / 'journal.json').write_bytes(raw)
        proof['journalSha256'] = prepare.digest(raw)
        raw = json.dumps(descriptor).encode(); (payload.parent / 'payload-manifest.json').write_bytes(raw)
        return base, system, payload, metadata, prepare.digest(raw), proof, previous

    def test_installed_followup_proof_git_cas_and_nginx_are_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            base, system, payload, metadata, sha, proof, previous = self.installed_fixture(Path(directory))
            with patch.object(release, 'INSTALLED_PROOF', proof), patch.object(prepare, 'INSTALLED_PROOF', proof), \
                    patch.object(prepare, 'file_metadata', metadata):
                with self.assertRaisesRegex(ValueError, 'installed_worker_image_drift'):
                    prepare.observe(system, dict(previous, workerImageId='sha256:' + '1' * 64))
                for drift in ('git', 'journal', 'module', 'nginx', 'protected'):
                    descriptor_path = payload.parent / 'payload-manifest.json'
                    descriptor_raw = descriptor_path.read_bytes(); restore = None
                    if drift == 'git':
                        value = json.loads(descriptor_raw)
                        value['installed_baseline']['files']['runtime/conversation_files.py'] = '0' * 64
                        descriptor_path.write_text(json.dumps(value), encoding='utf-8')
                    else:
                        target = (proof['backup'] + '/journal.json' if drift == 'journal' else
                                  release.TARGETS['runtime/conversation_files.py'] if drift == 'module' else
                                  release.NGINX if drift == 'nginx' else previous['unchangedRequired'][0]['path'])
                        path = base.rooted(system, target); restore = (path, path.read_bytes()); path.write_bytes(b'changed')
                    current_sha = prepare.digest(descriptor_path.read_bytes())
                    stage = Path(directory) / ('bad-' + drift)
                    with self.subTest(drift=drift), self.assertRaises(ValueError):
                        prepare.prepare(payload, stage, 'a' * 40, current_sha, root=system, followup=True)
                    self.assertFalse(stage.exists())
                    if restore: restore[0].write_bytes(restore[1])
                    descriptor_path.write_bytes(descriptor_raw)
                stage = Path(directory) / 'valid'
                prepare.prepare(payload, stage, 'a' * 40, sha, root=system, followup=True, release_ready=True)
                manifest = json.loads((stage / 'approved-manifest.json').read_bytes())
                self.assertEqual(len(manifest['files']), 14)
                self.assertEqual(len(manifest['unchangedRequired']), 48)
                self.assertTrue(manifest['materialStaticOnly'])
                self.assertEqual(manifest['installedBaseline'], proof)
                self.assertTrue(all(r['beforeSha256'] is not None for r in manifest['files']))
                self.assertEqual((stage / 'candidate/http/formal.conf').read_bytes(), prepare.patch_nginx(NGINX))

    def test_static_followup_original_apply_no_runtime_writes_restart_or_delete_on_rollback(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                base, system, payload, metadata, sha, proof, previous = self.installed_fixture(Path(directory))
                stage = Path(directory) / 'stage'
                with patch.object(release, 'INSTALLED_PROOF', proof), patch.object(prepare, 'INSTALLED_PROOF', proof), \
                        patch.object(prepare, 'file_metadata', metadata):
                    prepare.prepare(payload, stage, 'a' * 40, sha, root=system, followup=True, release_ready=True)
                raw = (stage / 'approved-manifest.json').read_bytes(); manifest = json.loads(raw)
                spec = importlib.util.spec_from_file_location('static_followup', stage / 'runtime_release.py')
                module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                module.INSTALLED_PROOF = proof
                guards = []
                def host_guards(current, root, reader_stopped=False):
                    guards.append(current['runtimeRequired'])
                    self.assertEqual(current['runtimeRequired'], manifest['runtimeRequired'])
                    for row in current['unchangedRequired']:
                        self.assertEqual(base.digest(base.rooted(system, row['path'])), row['sha256'])
                base.guards = host_guards
                base.retirement = lambda *a: None
                base.locks = base.live_lock = base.model_release_lock = lambda *a: nullcontext()
                base.hermes_admission_fence = lambda *a: nullcontext(SimpleNamespace(modified=False, confirmed=False))
                base.restart_for = Mock(side_effect=AssertionError('static followup must not restart'))
                writes = []
                original_atomic = base.atomic
                def host_atomic(path, data, mode=0o644):
                    if path in [base.rooted(system, r['target']) for r in manifest['files']]: writes.append(path)
                    return original_atomic(path, data, mode)
                base.atomic = host_atomic
                if os.name == 'nt': base.directory_sync = lambda *a: None
                css = next(r for r in manifest['files'] if r['candidate'] == 'frontend/conversation.css')
                def image():
                    if fail and base.digest(base.rooted(system, css['target'])) == css['sha256']:
                        raise ValueError('static postcondition lost')
                    return manifest['workerImageId']
                with patch.object(module, 'frozen', return_value=base), \
                        patch.object(module, 'worker_image', side_effect=image), \
                        patch.object(module.subprocess, 'run', side_effect=AssertionError('no static child process')):
                    publisher = module.load_base()
                    if os.name == 'nt':
                        # Normalize only Windows temp target modes at the host
                        # boundary; real Linux CI retains original POSIX modes.
                        wire_atomic = publisher.atomic
                        def windows_atomic(path, data, mode=0o644):
                            for row in manifest['files']:
                                if path == base.rooted(system, row['target']): mode = int(row['mode'], 8)
                            return wire_atomic(path, data, mode)
                        publisher.atomic = windows_atomic
                    publisher.inspect(manifest, stage, system)
                    if fail:
                        with self.assertRaisesRegex(ValueError, 'static postcondition lost'):
                            publisher.apply(manifest, stage, prepare.digest(raw), raw, 'nav-20261101T000002Z', system)
                    else:
                        publisher.apply(manifest, stage, prepare.digest(raw), raw, 'nav-20261101T000002Z', system)
                    self.assertGreaterEqual(len(guards), 17)  # Original per-row guards remain.
                    changed = {base.rooted(system, r['target']) for r in manifest['files'] if r['beforeSha256'] != r['sha256']}
                    self.assertEqual(set(writes), changed)
                    for row in manifest['files']:
                        self.assertEqual(base.digest(base.rooted(system, row['target'])), row['beforeSha256'] if fail else row['sha256'])
                    for name in release.NEW: self.assertTrue(base.rooted(system, release.TARGETS[name]).exists())
                    journal = json.loads((base.rooted(system, '/var/backups/fs-navigation-20261006/nav-20261101T000002Z') / 'journal.json').read_bytes())
                    self.assertEqual(journal['status'], 'rolled-back' if fail else 'applied-awaiting-actual-http-role-acceptance')

    def test_live_image_and_post_restart_require_real_container(self):
        live = subprocess.CompletedProcess([], 0, release.FROZEN_IMAGE_MARKER + '\n', '')
        def old_systemctl(command, **kwargs):
            self.assertEqual(command, ['systemctl', 'show', 'fs-hermes-fc.service', '-p', 'ActiveState'])
            return 'ActiveState=active\n'
        with patch.object(release.subprocess, 'run', return_value=live), \
                patch.object(release.subprocess, 'check_output', side_effect=old_systemctl), \
                patch.object(release, 'Path') as path:
            self.assertEqual(release.worker_image(), release.FROZEN_IMAGE_MARKER)
            path.assert_not_called()
        absent = subprocess.CompletedProcess([], 1, '', 'Error: No such object: fs-hermes-fc\n')
        with patch.object(release.subprocess, 'run', return_value=absent):
            with self.assertRaisesRegex(ValueError, 'current_worker_container_unavailable'):
                release.worker_image()

    def test_stopped_image_recovery_is_exact_and_pre_install_only(self):
        absent = subprocess.CompletedProcess([], 1, '', 'Error: No such object: fs-hermes-fc\n')
        unit = '/etc/systemd/system/fs-hermes-fc.service'
        dropin = unit + '.d/install-state-isolation.conf'
        pinned = {unit: '94b9cf19547ad0a4b68307ea35d4f5317fca0136048b90d78d5f9cea1dbaf011',
                  dropin: '2a4eeada8c0acd27db04aa14838af7cc5c7fe3355677581d53f1f3509c74321a'}
        state = ('ActiveState=failed\nFragmentPath=' + unit + '\nDropInPaths=' + dropin + '\nNeedDaemonReload=no\n')
        # Inject host/process boundaries only. No unit/config/secrets are read and
        # the original offline runner continues to forbid real child processes.
        info = SimpleNamespace(st_mode=0o100644, st_nlink=1, st_uid=0, st_gid=0)
        fake_paths = {name: SimpleNamespace(stat=lambda: info, read_bytes=lambda n=name: n.encode())
                      for name in pinned}
        sha = lambda raw: SimpleNamespace(hexdigest=lambda: pinned[raw.decode()])
        values = {'containers': '', 'state': state, 'image': release.FROZEN_IMAGE_MARKER}
        def output(command, **kwargs):
            if command[:2] == ['docker', 'ps']:
                self.assertIn('name=^/fs-hermes-fc$', command)
                return values['containers']
            if command[0] == 'systemctl':
                return values['state']
            self.assertEqual(command, ['docker', 'image', 'inspect', '--format', '{{.Id}}', release.FROZEN_IMAGE_MARKER])
            return values['image']
        with patch.object(release.subprocess, 'run', return_value=absent) as run, \
                patch.object(release.subprocess, 'check_output', side_effect=output), \
                patch.object(release, 'Path', side_effect=lambda n: fake_paths[n]), \
                patch.object(release, 'frozen', return_value=SimpleNamespace(no_target_link=Mock())), \
                patch.object(release.hashlib, 'sha256', side_effect=sha):
            self.assertEqual(release.worker_image(allow_stopped=True), release.FROZEN_IMAGE_MARKER)
            values['state'] = state.replace('failed', 'inactive')
            self.assertEqual(release.worker_image(allow_stopped=True), release.FROZEN_IMAGE_MARKER)
            values['state'] = state
            for key, bad, error in (
                    ('containers', 'new-container', 'container_changed'),
                    ('state', state.replace('failed', 'active'), 'unit_state_changed'),
                    ('state', state.replace('NeedDaemonReload=no', 'NeedDaemonReload=yes'), 'unit_state_changed'),
                    ('state', state.replace(dropin, dropin + ' /other.conf'), 'unit_state_changed'),
                    ('state', state.replace('FragmentPath=' + unit, 'FragmentPath=/other'), 'unit_state_changed'),
                    ('image', 'sha256:' + '0' * 64, 'pinned_image_unavailable')):
                old = values[key]; values[key] = bad
                with self.subTest(key=key, bad=bad), self.assertRaisesRegex(ValueError, error):
                    release.worker_image(allow_stopped=True)
                values[key] = old
            info.st_mode = 0o100666
            with self.assertRaisesRegex(ValueError, 'unit_drift'):
                release.worker_image(allow_stopped=True)
            info.st_mode = 0o100644
            pinned[unit] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'unit_drift'):
                release.worker_image(allow_stopped=True)
            run.return_value = subprocess.CompletedProcess([], 1, '', 'Cannot connect to Docker daemon')
            with self.assertRaisesRegex(ValueError, 'container_unavailable'):
                release.worker_image(allow_stopped=True)

    def test_recovery_inspect_apply_guards_switch_to_actual_active_postcondition(self):
        for failure in (None, 'restart', 'missing_container', 'stopped_after_health'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                base, system, payload, known, metadata, sha = self.fixture(root)
                stage = root / 'stage'
                with patch.object(prepare, 'KNOWN', known), patch.object(prepare, 'file_metadata', metadata):
                    prepare.prepare(payload, stage, 'a' * 40, sha, root=system, release_ready=True)
                manifest_path = stage / 'approved-manifest.json'
                manifest = json.loads(manifest_path.read_bytes())
                manifest['runtimeBefore']['fs-hermes-fc.service']['ActiveState'] = 'failed'
                manifest['workerImageSource'] = 'configured_unit_and_local_image'
                raw = json.dumps(manifest).encode(); manifest_path.write_bytes(raw)
                spec = importlib.util.spec_from_file_location('staged_recovery', stage / 'runtime_release.py')
                module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                state = {'worker': 'failed', 'container': False, 'restarted': False}
                phases = []
                def host_guards(current, host, reader_stopped=False):
                    expected = current['runtimeRequired']['fs-hermes-fc.service']['ActiveState']
                    phases.append(expected)
                    if state['worker'] != expected:
                        raise ValueError('protected unit changed: fs-hermes-fc.service')
                    for row in current['unchangedRequired']:
                        self.assertEqual(base.digest(base.rooted(system, row['path'])), row['sha256'])
                def observation(*, allow_stopped=False):
                    if not state['container'] and not allow_stopped:
                        raise ValueError('current_worker_container_unavailable')
                    return {'image': manifest['workerImageId'], 'state': state['worker'],
                            'source': 'container' if state['container'] else 'configured_unit_and_local_image'}
                def restart(current, fence):
                    state['restarted'] = True
                    if failure == 'restart':
                        raise RuntimeError('real startup failed')
                    state.update(worker='active', container=True)
                    if failure == 'missing_container':
                        state['container'] = False
                    if failure == 'stopped_after_health':
                        state['worker'] = 'failed'
                base.guards = host_guards
                base.restart_for = restart
                base.retirement = lambda *a: None
                base.locks = base.live_lock = base.model_release_lock = lambda *a: nullcontext()
                base.hermes_admission_fence = lambda *a: nullcontext(SimpleNamespace(modified=False, confirmed=False))
                if os.name == 'nt':
                    base.directory_sync = lambda *a: None
                with patch.object(module, 'frozen', return_value=base), \
                        patch.object(module, 'worker_observation', side_effect=observation), \
                        patch.object(module.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
                    publisher = module.load_base()
                    publisher.inspect(manifest, stage, system)
                    self.assertEqual(phases, ['failed'])
                    # A baseline-state change is rejected before any install.
                    state['worker'] = 'inactive'
                    with self.assertRaisesRegex(ValueError, 'protected unit changed'):
                        publisher.inspect(manifest, stage, system)
                    state['worker'] = 'failed'
                    if failure:
                        with self.assertRaises((RuntimeError, ValueError)):
                            publisher.apply(manifest, stage, prepare.digest(raw), raw, 'nav-20261101T000001Z', system)
                    else:
                        result = publisher.apply(manifest, stage, prepare.digest(raw), raw, 'nav-20261101T000001Z', system)
                        self.assertEqual(result['status'], 'applied-awaiting-actual-http-role-acceptance')
                    self.assertTrue(state['restarted'])
                    self.assertEqual(manifest['runtimeRequired']['fs-hermes-fc.service'], {'ActiveState': 'active'})
                    journal = json.loads((base.rooted(system, '/var/backups/fs-navigation-20261006/nav-20261101T000001Z') / 'journal.json').read_bytes())
                    self.assertEqual(journal['status'], 'rolled-back' if failure else result['status'])
                    for row in manifest['files']:
                        self.assertEqual(base.digest(base.rooted(system, row['target'])),
                                         row['beforeSha256'] if failure else row['sha256'])
                    if failure != 'restart':
                        if failure != 'missing_container':
                            self.assertEqual(phases[-1], 'active')

    def test_nginx_patch_preserves_all_other_bytes_and_rejects_anchor_drift(self):
        changed = prepare.patch_nginx(NGINX)
        self.assertEqual(changed.replace(b'10m;', b'16k;'), NGINX)
        self.assertEqual(changed.count(b'10m;'), 2)
        self.assertIn(b'location /other { client_max_body_size 16k; }', changed)
        for raw in (NGINX.replace(b'16k;', b'20k;', 1), NGINX + NGINX, b'location /other {}'):
            with self.assertRaises(ValueError):
                prepare.patch_nginx(raw)

    def test_pack_consumes_injected_git_blob_bytes_not_working_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / 'repo'; repo.mkdir()
            sources = {'runtime/a.py': 'a.py'}
            files = {'a.py': b'committed\n', **{path: b'publisher\n' for path in prepare.PUBLISHER_SOURCES.values()}}
            for name, body in files.items():
                target = repo / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(body)
            commit = 'a' * 40
            (repo / 'a.py').write_bytes(b'uncommitted\r\n')
            def git_blob(command, cwd):
                self.assertEqual(command[:2], ['git', 'show'])
                self.assertEqual(cwd, repo)
                selected, name = command[2].split(':', 1)
                self.assertIn(selected, (commit, prepare.INSTALLED_COMMIT))
                return b'prior-merged-LF\n' if selected == prepare.INSTALLED_COMMIT else files[name]
            # The normal pr-fast runner forbids child processes. Inject only the
            # Git blob boundary; production pack still calls git show directly.
            with patch.object(prepare, 'SOURCES', sources), patch.object(prepare.subprocess, 'check_output', git_blob):
                result = prepare.pack(repo, root / 'payload', commit)
            self.assertEqual((root / 'payload/payload/runtime/a.py').read_bytes(), b'committed\n')
            self.assertEqual(result['payload_sha256'], prepare.digest((root / 'payload/payload-manifest.json').read_bytes()))
            descriptor = json.loads((root / 'payload/payload-manifest.json').read_bytes())
            self.assertEqual(descriptor['installed_baseline']['files']['runtime/a.py'], prepare.digest(b'prior-merged-LF\n'))

    def fixture(self, root):
        system = root / 'system'; system.mkdir()
        base = release.frozen()
        hashes = {}
        for name, target in release.TARGETS.items():
            if name in release.NEW:
                continue
            path = base.rooted(system, target); path.parent.mkdir(parents=True, exist_ok=True)
            body = NGINX if target == release.NGINX else ('old:' + name).encode()
            path.write_bytes(body); hashes[name] = prepare.digest(body)
        for target in release.protected_paths(base):
            path = base.rooted(system, target); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'protected')
        payload = root / 'bundle/payload'; payload.mkdir(parents=True)
        descriptor = {'source_commit': 'a' * 40, 'files': {}}
        for name in prepare.SOURCES:
            path = payload / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(('new:' + name).encode())
            descriptor['files']['payload/' + name] = prepare.digest(path.read_bytes())
        for name, source in prepare.PUBLISHER_SOURCES.items():
            source = next(parent / source for parent in release.HERE.parents if (parent / source).is_file())
            path = payload.parent / name; path.write_bytes(source.read_bytes())
            descriptor['files'][name] = prepare.digest(path.read_bytes())
        raw = json.dumps(descriptor).encode(); (payload.parent / 'payload-manifest.json').write_bytes(raw)

        def metadata(base, host, name, absent=False):
            # Only Windows temp fixture ownership/modes are synthetic. Byte hashes,
            # exact target sets, manifests, CAS and rollback use real files.
            path = base.rooted(host, name)
            if not path.exists():
                if not absent:
                    raise ValueError('fixture_missing')
                return {'path': name, 'sha256': None}
            return {'path': name, 'sha256': prepare.digest(path.read_bytes()),
                    'mode': '0o600' if name == release.NGINX else '0o644'}
        return base, system, payload, hashes, metadata, prepare.digest(raw)

    def test_fresh_manifest_validate_and_existing_target_cas(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, system, payload, known, metadata, sha = self.fixture(root)
            stage = root / 'stage'
            with patch.object(prepare, 'KNOWN', known), patch.object(prepare, 'file_metadata', metadata):
                result = prepare.prepare(payload, stage, 'a' * 40, sha, root=system)
            self.assertEqual(result['production_writes'], 0)
            spec = importlib.util.spec_from_file_location('staged_materials', stage / 'runtime_release.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            publisher = module.load_base()
            manifest = json.loads((stage / 'approved-manifest.json').read_bytes())
            self.assertFalse(manifest['releaseReady'])
            publisher.validate(manifest, stage)
            for invalid in ('activating', 'active'):
                bad = json.loads((stage / 'approved-manifest.json').read_bytes())
                bad['runtimeBefore']['fs-hermes-fc.service']['ActiveState'] = invalid
                bad['workerImageSource'] = 'configured_unit_and_local_image'
                (stage / 'approved-manifest.json').write_text(json.dumps(bad), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'runtime_before_required'):
                    module.load_base().validate(bad, stage)
                (stage / 'approved-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            # OS/service/retirement checks are intentionally outside this fixture.
            publisher.guards = lambda *a, **kw: None
            publisher.retirement = lambda *a: None
            publisher.inspect(manifest, stage, system)
            target = base.rooted(system, release.TARGETS['runtime/conversation_store.py'])
            target.write_bytes(b'concurrent change')
            with self.assertRaisesRegex(ValueError, 'target baseline drift'):
                publisher.inspect(manifest, stage, system)
            with self.assertRaisesRegex(ValueError, 'exact_material_manifest_required'):
                publisher.validate(dict(manifest, businessWrites=True), stage)
            manifest['baselineObservedAt'] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            (stage / 'approved-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'fresh_material_baseline_required'):
                module.load_base().validate(manifest, stage)

    def test_payload_tamper_and_existing_new_file_stop_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, system, payload, known, metadata, sha = self.fixture(root)
            target = base.rooted(system, release.TARGETS['runtime/conversation_files.py'])
            target.write_bytes(b'unknown existing module')
            with patch.object(prepare, 'KNOWN', known), patch.object(prepare, 'file_metadata', metadata):
                with self.assertRaisesRegex(ValueError, 'runtime_source_baseline_drift'):
                    prepare.prepare(payload, root / 'stage', 'a' * 40, sha, root=system)
            self.assertFalse((root / 'stage').exists())
            (payload / 'runtime/conversation_files.py').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'git_payload_changed'):
                prepare.prepare(payload, root / 'stage', 'a' * 40, sha, root=system)

    def test_sqlite_active_unknown_and_pricing_lane_are_not_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); base = release.frozen()
            names = {'conversations/conversations.db': ['turns'], 'pricing-reviews/conversations.db': ['turns'],
                     'tasks.sqlite3': ['tasks', 'learning_events']}
            for name, tables in names.items():
                path = base.rooted(root, '/var/lib/fs-hermes-fc/fs/' + name); path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(path)) as db:
                    for table in tables:
                        db.execute('CREATE TABLE ' + table + '(state TEXT)')
            release.quiescent(base, root)
            path = base.rooted(root, '/var/lib/fs-hermes-fc/fs/pricing-reviews/conversations.db')
            with closing(sqlite3.connect(path)) as db:
                db.execute("INSERT INTO turns VALUES('dispatch_unknown')"); db.commit()
            with self.assertRaisesRegex(ValueError, 'active_or_unknown_material_task'):
                release.quiescent(base, root)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT state FROM turns').fetchall(), [('dispatch_unknown',)])

    def test_original_rollback_restores_code_and_preserves_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); base = release.frozen(); backup = root / 'backup'; backup.mkdir()
            if os.name == 'nt':
                # Windows cannot fsync directories. Linux CI uses the real
                # original primitive; this local case checks byte/CAS semantics.
                base.directory_sync = lambda path: None
            target = '/opt/fs-hermes-fc/conversation_store.py'
            data = root / 'business.db'; data.write_bytes(b'preserve actual state')
            rows = []
            for name, path in release.TARGETS.items():
                code = base.rooted(root, path); code.parent.mkdir(parents=True, exist_ok=True); code.write_bytes(b'new')
                old = None if name in release.NEW else prepare.digest(b'old')
                if old:
                    saved = backup / 'files' / name; saved.parent.mkdir(parents=True, exist_ok=True); saved.write_bytes(b'old')
                rows.append({'candidate': name, 'target': path, 'beforeSha256': old, 'sha256': prepare.digest(b'new')})
            manifest = {'schemaVersion': 1, 'scope': release.SCOPE, 'files': rows}
            raw = json.dumps(manifest).encode(); (backup / 'approved-manifest.json').write_bytes(raw)
            journal = {'files': [dict(row, beforeMode=0o600 if row['target'] == release.NGINX else 0o644,
                                     intent=True, written=True) for row in rows],
                       'manifest': manifest, 'approvedManifestSha256': prepare.digest(raw)}
            base.rollback_journal(backup, journal, root)
            code = base.rooted(root, target)
            self.assertEqual(code.read_bytes(), b'old')
            self.assertEqual(data.read_bytes(), b'preserve actual state')
            self.assertFalse(base.rooted(root, release.TARGETS['runtime/conversation_files.py']).exists())
            if os.name == 'posix':
                self.assertEqual(base.rooted(root, release.NGINX).stat().st_mode & 0o777, 0o600)
            code.write_bytes(b'other operator')
            with self.assertRaises(ValueError):
                base.rollback_journal(backup, journal, root)




class NativePublisher(unittest.TestCase):
    def test_daily_consumer_keeps_container_entry_and_sibling_import(self):
        prepare.configure_native_chat()
        source=Path(__file__).resolve().parents[2]/'hermes-memory-approval-20261022'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);host=root/'root-code.py';host.write_bytes((source/'daily_review.py').read_bytes())
            entry=root/'container'/release.NATIVE_DAILY_CONTAINER.lstrip('/')
            entry.parent.mkdir(parents=True);entry.write_bytes(host.read_bytes())  # bind-file bytes fixture, no Docker invocation
            sibling=entry.with_name('inspect_runtime.py');sibling.write_bytes((source/'inspect_runtime.py').read_bytes())
            spec=importlib.util.spec_from_file_location('inspect_runtime',sibling);helper=importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules,{'inspect_runtime':helper}),patch('zoneinfo.ZoneInfo',return_value=timezone(timedelta(hours=8))):
                spec.loader.exec_module(helper)
                spec=importlib.util.spec_from_file_location('synthetic_daily_consumer',entry);daily=importlib.util.module_from_spec(spec);spec.loader.exec_module(daily)
            self.assertEqual(daily.PROFILE,Path('/profile'))
            self.assertIs(daily.redact,helper.redact)
            self.assertEqual(Path(daily.__file__).with_name('inspect_runtime.py'),sibling)
            self.assertEqual(Path(daily.__file__).read_bytes(),host.read_bytes())

    def test_daily_legacy_protection_rejects_hash_owner_mode_and_links(self):
        prepare.configure_native_chat()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=release.frozen();legacy=base.rooted(root,release.NATIVE_LEGACY_DAILY)
            legacy.parent.mkdir(parents=True);legacy.write_bytes(b'old host daily')
            profile=base.rooted(root,'/var/lib/fs-hermes-fc/profile')
            owners={profile:(9876,9876,0o700),legacy:(0,0,0o644)};kinds={}
            with self.native_metadata(owners,kinds,root=root),patch.object(release,'NATIVE_LEGACY_DAILY_SHA',base.digest(legacy)):
                release.native_legacy_daily_guard(base,root)
                for bad in ((9876,9876,0o644),(0,0,0o664)):
                    owners[legacy]=bad
                    with self.assertRaisesRegex(ValueError,'native_legacy_daily_drift'):release.native_legacy_daily_guard(base,root)
                owners[legacy]=(0,0,0o644)
                with patch.object(release,'NATIVE_LEGACY_DAILY_SHA','0'*64):
                    with self.assertRaisesRegex(ValueError,'native_legacy_daily_drift'):release.native_legacy_daily_guard(base,root)
                for item in (legacy,legacy.parent):
                    kinds[item]=stat.S_IFLNK
                    with self.assertRaises(ValueError):release.native_legacy_daily_guard(base,root)
                    kinds.clear()

    def test_daily_overlay_uses_root_code_and_keeps_original_guard_on_private_profile(self):
        prepare.configure_native_chat()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=release.frozen()
            legacy=base.rooted(root,'/var/lib/fs-hermes-fc/profile/scripts/hermes-memory-review/daily_review.py')
            legacy.parent.mkdir(parents=True);legacy.write_bytes(b'unchanged host daily')
            profile=base.rooted(root,'/var/lib/fs-hermes-fc/profile')
            target=base.rooted(root,release.TARGETS['approval/daily_review.py'])
            target.parent.mkdir(parents=True,exist_ok=True)
            if target!=legacy:target.write_bytes(b'new root daily')
            owners={p:(0,0,0o755 if p.is_dir() else 0o644) for p in (root,*root.rglob('*'))}
            owners[profile]=(9876,9876,0o700)
            before=(legacy.read_bytes(),legacy.stat().st_ino,legacy.stat().st_mtime_ns)
            base.hermes_quiescent=Mock()  # DB liveness IO only; original guards stays intact.
            manifest={'scope':release.SCOPE,'runtimeRequired':{},'unchangedRequired':[]}
            kinds={}
            with self.native_metadata(owners,kinds):
                base.HERMES_HISTORY_TARGETS={'daily':str(legacy.relative_to(root)).replace('\\','/')}
                base.HERMES_HISTORY_TARGETS={'daily':'/'+base.HERMES_HISTORY_TARGETS['daily']}
                with self.assertRaisesRegex(ValueError,'unsafe daily source boundary'):base.guards(manifest,root)
                base.HERMES_HISTORY_TARGETS={'daily':release.TARGETS['approval/daily_review.py']}
                base.guards(manifest,root)
                for item in (target,target.parent):
                    saved=owners[item];owners[item]=(9876,9876,saved[2])
                    with self.assertRaisesRegex(ValueError,'unsafe daily source boundary'):base.guards(manifest,root)
                    owners[item]=saved;kinds[item]=stat.S_IFLNK
                    with self.assertRaises(ValueError):base.guards(manifest,root)
                    kinds.clear()
            self.assertEqual(release.TARGETS['approval/daily_review.py'],'/opt/fs-hermes-memory-approval/daily_review.py')
            self.assertEqual((legacy.read_bytes(),legacy.stat().st_ino,legacy.stat().st_mtime_ns),before)

    @contextmanager
    def native_metadata(self, owners, kinds=None, root=None):
        # Keep real filesystem types (including a real Unix socket on Linux).
        # Root/9876 ownership cannot be created by the unprivileged CI runner.
        kinds={} if kinds is None else kinds
        def metadata(path, *, follow_symlinks=True):
            path=Path(path);info=os.stat(path,follow_symlinks=follow_symlinks)
            inside=root is not None and (path==root or root in path.parents)
            if path not in owners and path not in kinds and not inside:return info
            default=(0,0,0o755 if stat.S_ISDIR(info.st_mode) else 0o600 if path==root/release.NGINX.lstrip('/') else 0o644) if inside else (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))
            fields=list(info);uid,gid,mode=owners.get(path,default)
            fields[0]=kinds.get(path,stat.S_IFMT(info.st_mode))|mode
            fields[4]=uid;fields[5]=gid
            result={key:getattr(info,key) for key in dir(info) if key.startswith('st_')}
            result.update(st_mode=fields[0],st_uid=uid,st_gid=gid)
            return SimpleNamespace(**result)
        def kind(path, check, follow):
            try:return check(metadata(path,follow_symlinks=follow).st_mode)
            except FileNotFoundError:return False
        with patch.object(Path,'stat',lambda path,**kw:metadata(path,**kw)), patch.object(Path,'lstat',lambda path:metadata(path,follow_symlinks=False)), patch.object(Path,'is_file',lambda path:kind(path,stat.S_ISREG,True)), patch.object(Path,'is_symlink',lambda path:kind(path,stat.S_ISLNK,False)):
            yield

    def test_native_metadata_keeps_formal_nginx_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=release.frozen()
            nginx=base.rooted(root,release.NGINX)
            other=base.rooted(root,'/opt/fs-hermes-fc/unchanged.py')
            for path in (nginx,other):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'unchanged fixture')
            if os.name=='posix':
                nginx.chmod(0o600);other.chmod(0o644)
            with self.native_metadata({},root=root):
                self.assertEqual(stat.S_IMODE(nginx.stat().st_mode),0o600)
                self.assertEqual(stat.S_IMODE(other.stat().st_mode),0o644)

    def test_native_dependencies_accept_unix_socket_and_keep_type_owner_parent_guards(self):
        prepare.configure_native_chat()
        with tempfile.TemporaryDirectory(prefix='fs-native-sock-') as directory:
            root=Path(directory);base=release.frozen()
            cli=root/'usr/bin/docker';cli.parent.mkdir(parents=True);cli.write_bytes(b'fixed cli')
            target=root/'run/docker.sock';target.parent.mkdir()
            sock=None;kinds={}
            try:
                if hasattr(socket,'AF_UNIX'):
                    sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.bind(str(target))
                    self.assertTrue(stat.S_ISSOCK(os.lstat(target).st_mode))
                else:
                    # Windows Python lacks AF_UNIX; only this platform uses a
                    # type fixture. Linux must exercise the real bound socket.
                    target.write_bytes(b'Windows socket metadata fixture');kinds[target]=stat.S_IFSOCK
                owners={cli:(0,0,0o755),target:(0,994,0o660)}
                with self.native_metadata(owners,kinds), patch.object(release,'NATIVE_CLI_SHA',base.digest(cli)):
                    result=release.native_dependencies(base,root)
                    self.assertEqual(result['socket']['gid'],994)
                    self.assertEqual(result['socket']['mode'],'0o660')
                    with patch.object(release,'NATIVE_CLI_SHA','0'*64):
                        with self.assertRaisesRegex(ValueError,'native_docker_cli_drift'):release.native_dependencies(base,root)
                    owners[target]=(9876,994,0o660)
                    with self.assertRaisesRegex(ValueError,'native_docker_socket_unavailable'):release.native_dependencies(base,root)
                    owners[target]=(0,994,0o600)
                    with self.assertRaisesRegex(ValueError,'native_docker_socket_unavailable'):release.native_dependencies(base,root)
                    owners[target]=(0,994,0o660);kinds[target]=stat.S_IFREG
                    with self.assertRaisesRegex(ValueError,'native_docker_socket_unavailable'):release.native_dependencies(base,root)
                    kinds[target]=stat.S_IFSOCK;kinds[target.parent]=stat.S_IFLNK
                    with self.assertRaises(ValueError):release.native_dependencies(base,root)
            finally:
                if sock is not None:sock.close()

    def test_native_existing_directories_keep_type_ownership_and_empty_home_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            native=Path(directory)/'native';empty=Path(directory)/'empty-home'
            paths=[native,native/'profiles',native/'workspaces',empty]
            for path in paths:path.mkdir()
            owners={path:((0,0,0o555) if path==empty else (9876,9876,0o700)) for path in paths};kinds={}
            with patch.object(release,'NATIVE_ROOT',str(native)), patch.object(release,'NATIVE_EMPTY_SOURCE',str(empty)), self.native_metadata(owners,kinds), patch.object(os,'chown',create=True) as chown:
                release.ensure_native_directories();chown.assert_not_called()
                (native/'profiles').rmdir()
                release.ensure_native_directories()
                chown.assert_called_once_with(native/'profiles',9876,9876)
                for bad in ((0,9876,0o700),(9876,9876,0o755)):
                    owners[native/'profiles']=bad
                    with self.assertRaisesRegex(ValueError,'native_directory_owner_mode'):release.ensure_native_directories()
                owners[native/'profiles']=(9876,9876,0o700)
                kinds[native/'workspaces']=stat.S_IFREG
                with self.assertRaises(ValueError):release.ensure_native_directories()
                kinds[native/'workspaces']=stat.S_IFLNK
                with self.assertRaises(ValueError):release.ensure_native_directories()
                kinds.clear();kinds[native.parent]=stat.S_IFLNK
                with self.assertRaises(ValueError):release.ensure_native_directories()
                kinds.clear();(empty/'unexpected').write_bytes(b'must not be mounted')
                with self.assertRaisesRegex(ValueError,'native_empty_backend_home_changed'):release.ensure_native_directories()

    def setUp(self):
        self.release_state={key:deepcopy(value) for key,value in vars(release).items() if key.isupper()}
        self.prepare_state={key:deepcopy(value) for key,value in vars(prepare).items() if key.isupper()}
    def tearDown(self):
        for module,saved in ((release,self.release_state),(prepare,self.prepare_state)):
            for key,value in saved.items():setattr(module,key,value)
        prepare.TARGETS=release.TARGETS

    @contextmanager
    def admission_fixture(self, root):
        prepare.configure_native_admission()
        base,system,payload,_,_,proof,previous=RuntimeMaterials().installed_fixture(root)
        # Installed unit/backend are existing generated files, not bootstrap recipes.
        old_unit=b'[Service]\nExecStart=/usr/bin/docker run --user 9876:9876 '+release.FROZEN_IMAGE_MARKER.encode()+b' worker\n'
        with patch.object(release,'NATIVE_UNIT_BEFORE_SHA',prepare.digest(old_unit)):
            unit=prepare.render_native_unit(old_unit,{'socket':{'gid':994}})
        base.rooted(system,release.NATIVE_UNIT).write_bytes(unit)
        release.NATIVE_CLI_SHA=prepare.digest(b'fixed cli')
        base.rooted(system,release.TARGETS['runtime/native-backend.json']).write_bytes(release.native_backend_bytes())
        legacy=base.rooted(system,release.NATIVE_LEGACY_DAILY)
        legacy.write_bytes(b'unchanged legacy daily')
        cli=base.rooted(system,release.NATIVE_CLI);cli.write_bytes(b'fixed cli')
        profile=base.rooted(system,'/var/lib/fs-hermes-fc/profile')
        owners={profile:(9876,9876,0o700),cli:(0,0,0o755)}
        candidate=release.NATIVE_ADMISSION_CANDIDATE
        before=base.rooted(system,release.TARGETS[candidate]).read_bytes()
        after=before+b'\n# admission group read\n'
        deps={'cli':{'sha256':prepare.digest(b'fixed cli')},'socket':{'gid':994},'worker_user':'9876:9876'}
        descriptor=json.loads((payload.parent/'payload-manifest.json').read_bytes())
        descriptor.update(material_execution=True,native_admission=True,native_chat=False)
        previous['nativeChat']=True
        for row in previous['files']:
            row.update(sha256=base.digest(base.rooted(system,row['target'])),owner='0:0',mode='0o600' if row['target']==release.NGINX else '0o644')
            if row['candidate'] in prepare.SOURCES:
                body=after if row['candidate']==candidate else base.rooted(system,row['target']).read_bytes()
                (payload/row['candidate']).write_bytes(body)
                descriptor['files']['payload/'+row['candidate']]=prepare.digest(body)
        previous['unchangedRequired']=[{'path':path,'sha256':base.digest(base.rooted(system,path))} for path in sorted(release.protected_paths(base))]
        descriptor['installed_baseline']={'source_commit':release.INSTALLED_COMMIT,
            'files':{row['candidate']:row['sha256'] for row in previous['files']},
            'protected':{release.NATIVE_LEGACY_DAILY:base.digest(legacy)}}
        backup=base.rooted(system,proof['backup'])
        def save_proof():
            raw=json.dumps(previous).encode();(backup/'approved-manifest.json').write_bytes(raw);proof['manifestSha256']=prepare.digest(raw)
            journal={'status':'applied-awaiting-actual-http-role-acceptance','manifest':previous,'approvedManifestSha256':proof['manifestSha256']}
            raw=json.dumps(journal).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
        save_proof()
        raw=json.dumps(descriptor).encode();(payload.parent/'payload-manifest.json').write_bytes(raw)
        pins={'NATIVE_ADMISSION_BEFORE_SHA':prepare.digest(before),'NATIVE_ADMISSION_AFTER_SHA':prepare.digest(after),
              'NATIVE_CURRENT_UNIT_SHA':prepare.digest(unit),'NATIVE_LEGACY_DAILY_SHA':base.digest(legacy),'NATIVE_CLI_SHA':deps['cli']['sha256']}
        with self.native_metadata(owners,root=system),ExitStack() as stack:
            for key,value in pins.items():stack.enter_context(patch.object(release,key,value))
            stack.enter_context(patch.object(release,'INSTALLED_PROOF',proof));stack.enter_context(patch.object(prepare,'INSTALLED_PROOF',proof))
            stack.enter_context(patch.object(release,'native_dependencies',return_value=deps))
            yield SimpleNamespace(base=base,system=system,payload=payload,descriptor=descriptor,raw=raw,proof=proof,
                previous=previous,save_proof=save_proof,pins=pins,deps=deps,owners=owners)

    def test_native_admission_prepare_rejects_drift_proof_extra_zero_and_mixed(self):
        with tempfile.TemporaryDirectory() as directory,self.admission_fixture(Path(directory)) as f:
            root=Path(directory);descriptor_path=f.payload.parent/'payload-manifest.json'
            stage=root/'valid';prepare.prepare(f.payload,stage,'a'*40,prepare.digest(f.raw),root=f.system,followup=True,release_ready=True)
            manifest=json.loads((stage/'approved-manifest.json').read_bytes())
            self.assertTrue(manifest['nativeAdmission']);self.assertNotIn('nativeChat',manifest)
            self.assertEqual((len(manifest['files']),len(manifest['unchangedRequired'])),(34,45))
            self.assertTrue(all(row['beforeSha256'] is not None for row in manifest['files']))
            self.assertEqual(manifest['materialChangedTargets'],[release.TARGETS[release.NATIVE_ADMISSION_CANDIDATE]])
            for case in ('zero','extra','unit','old_recipe','backend','old_source','git','mixed','missing_execution','journal','protected','legacy','missing','mode','owner'):
                value=deepcopy(f.descriptor);restore=None;saved_owner=None
                if case=='old_source':value['installed_baseline']['source_commit']='23a27325b00f27a5c5696657c7c4141a06135f18'
                elif case=='git':value['installed_baseline']['files'][release.NATIVE_ADMISSION_CANDIDATE]='0'*64
                elif case=='mixed':value['native_chat']=True
                elif case=='missing_execution':value['material_execution']=False
                elif case in ('mode','owner'):
                    path=f.base.rooted(f.system,release.TARGETS['runtime/conversation_store.py'])
                    saved_owner=path;f.owners[path]=(0,0,0o664) if case=='mode' else (9876,9876,0o644)
                else:
                    name=release.NATIVE_ADMISSION_CANDIDATE if case=='zero' else 'http/conversation_http.py' if case=='extra' else 'unit/native-control.conf' if case in ('unit','old_recipe') else 'runtime/native-backend.json'
                    path=f.payload/name if case in ('zero','extra','unit','old_recipe','backend') else f.base.rooted(f.system,
                        f.proof['backup']+'/journal.json' if case=='journal' else release.NATIVE_LEGACY_DAILY if case=='legacy' else
                        release.TARGETS['runtime/native_chat.py'] if case=='missing' else f.previous['unchangedRequired'][0]['path'])
                    restore=(path,path.read_bytes())
                    if case=='zero':body=f.base.rooted(f.system,release.TARGETS[name]).read_bytes()
                    elif case=='old_recipe':body=prepare.native_generated()['unit/native-control.conf']
                    else:body=b'drift'
                    if case=='missing':path.unlink()
                    else:path.write_bytes(body)
                    if str(path).startswith(str(f.payload)):value['files']['payload/'+name]=prepare.digest(body)
                raw=json.dumps(value).encode();descriptor_path.write_bytes(raw)
                with self.subTest(rejection=case),self.assertRaises((OSError,ValueError)):
                    prepare.prepare(f.payload,root/('bad-'+case),'a'*40,prepare.digest(raw),root=f.system,followup=True)
                self.assertFalse((root/('bad-'+case)).exists())
                if restore:restore[0].write_bytes(restore[1])
                if saved_owner:f.owners.pop(saved_owner)
                descriptor_path.write_bytes(f.raw)
            saved=deepcopy(f.previous)
            for case in ('target_missing','target_duplicate','protected_missing','protected_duplicate','unit','new'):
                f.previous.clear();f.previous.update(deepcopy(saved))
                if case=='target_missing':f.previous['files'].pop()
                elif case=='target_duplicate':f.previous['files'].append(deepcopy(f.previous['files'][0]))
                elif case=='protected_missing':f.previous['unchangedRequired'].pop()
                elif case=='protected_duplicate':f.previous['unchangedRequired'].append(deepcopy(f.previous['unchangedRequired'][0]))
                else:next(r for r in f.previous['files'] if r['candidate']==('unit/native-control.conf' if case=='unit' else 'runtime/native_chat.py'))['sha256']=None if case=='new' else '0'*64
                f.save_proof()
                with self.subTest(proof=case),self.assertRaises(ValueError):release.installed_baseline(f.system,f.descriptor['installed_baseline'])

    def test_native_admission_original_apply_range_only_and_rollback(self):
        for failure in (None,'range','readiness'):
            self.tearDown();self.setUp()
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory,self.admission_fixture(Path(directory)) as f:
                stage=Path(directory)/'stage'
                prepare.prepare(f.payload,stage,'a'*40,prepare.digest(f.raw),root=f.system,followup=True,release_ready=True)
                raw=(stage/'approved-manifest.json').read_bytes();manifest=json.loads(raw)
                spec=importlib.util.spec_from_file_location('native_admission_fixture',stage/'runtime_release.py')
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                module.configure_native_admission();module.INSTALLED_PROOF=f.proof
                for key,value in f.pins.items():setattr(module,key,value)
                base=f.base;original_guards=base.guards
                base.hermes_quiescent=Mock();base.retirement=Mock()  # Only host DB/retired-service IO, real guards remain.
                base.locks=base.live_lock=base.model_release_lock=lambda *a:nullcontext()
                fence=SimpleNamespace(modified=False,confirmed=False,stop_then_unlock_database=Mock())
                base.hermes_admission_fence=lambda *a:nullcontext(fence)
                restart=Mock(side_effect=[RuntimeError('synthetic range failure'),None] if failure=='range' else None);base.restart_for=restart
                if os.name=='nt':base.directory_sync=lambda *a:None
                readiness=Mock(side_effect=[None,None,RuntimeError('synthetic readiness failure'),None] if failure=='readiness' else None)
                untouched={path:(path.read_bytes(),path.stat().st_ino,path.stat().st_mtime_ns,path.stat().st_uid,path.stat().st_gid,stat.S_IMODE(path.stat().st_mode))
                    for path in (base.rooted(f.system,row['target']) for row in manifest['files'] if row['candidate']!=release.NATIVE_ADMISSION_CANDIDATE)}
                untouched.update({base.rooted(f.system,row['path']):(base.rooted(f.system,row['path']).read_bytes(),base.rooted(f.system,row['path']).stat().st_ino,base.rooted(f.system,row['path']).stat().st_mtime_ns,base.rooted(f.system,row['path']).stat().st_uid,base.rooted(f.system,row['path']).stat().st_gid,stat.S_IMODE(base.rooted(f.system,row['path']).stat().st_mode)) for row in manifest['unchangedRequired']})
                with patch.object(module,'frozen',return_value=base),patch.object(module,'quiescent'),patch.object(module,'running_worker') as worker,patch.object(module,'native_dependencies',return_value=f.deps),patch.object(module,'native_runtime_readiness',readiness),patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='ActiveState=active\n')) as commands:
                    publisher=module.load_base();self.assertIsNot(publisher.guards,original_guards)
                    publisher.inspect(manifest,stage,f.system)
                    # Original parent ownership guard, not a no-op fixture.
                    parent=base.rooted(f.system,'/opt/fs-hermes-fc');f.owners[parent]=(9876,9876,0o755)
                    with self.assertRaisesRegex(ValueError,'unsafe daily source boundary'):publisher.guards(manifest,f.system)
                    f.owners.pop(parent)
                    for mutate in (lambda m:m.update(nativeChat=True),lambda m:m['files'].pop(),lambda m:m['unchangedRequired'].append(m['unchangedRequired'][0]),lambda m:m.update(baselineObservedAt='2020-01-01T00:00:00+00:00'),lambda m:m['runtimeBefore']['fs-hermes-fc.service'].update(ActiveState='failed'),lambda m:m.update(workerImageSource='configured_unit_and_local_image'),lambda m:m['nativeDependencies']['socket'].update(gid=995)):
                        bad=deepcopy(manifest);mutate(bad)
                        with self.assertRaises((ValueError,KeyError)):publisher.validate(bad,stage)
                    if failure:
                        with self.assertRaisesRegex(RuntimeError,'synthetic .* failure'):publisher.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261102T120001Z',f.system)
                    else:publisher.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261102T120001Z',f.system)
                    self.assertTrue(worker.called)
                    self.assertTrue(all(call.args[0]['scope']==base.DEEP_SCOPE for call in restart.call_args_list))
                    self.assertEqual(restart.call_count,2 if failure else 1)
                    self.assertEqual(readiness.call_count,3 if failure=='range' else 4 if failure=='readiness' else 3)
                    self.assertFalse(any(call.args[0][:2] in (['systemctl','daemon-reload'],['systemctl','restart'],['systemctl','reload']) for call in commands.call_args_list))
                for row in manifest['files']:
                    self.assertEqual(base.digest(base.rooted(f.system,row['target'])),row['beforeSha256'] if failure else row['sha256'])
                for path,metadata in untouched.items():
                    self.assertEqual((path.read_bytes(),path.stat().st_ino,path.stat().st_mtime_ns,path.stat().st_uid,path.stat().st_gid,stat.S_IMODE(path.stat().st_mode)),metadata)
                journal=json.loads((base.rooted(f.system,'/var/backups/fs-navigation-20261006/nav-20261102T120001Z')/'journal.json').read_bytes())
                self.assertEqual(journal['status'],'rolled-back' if failure else 'applied-awaiting-actual-http-role-acceptance')

    def test_native_admission_pack_uses_git_v2_unit_and_rejects_other_deltas(self):
        prepare.configure_native_admission()
        candidate=release.NATIVE_ADMISSION_CANDIDATE
        old=b'[Service]\nExecStart=/usr/bin/docker run --user 9876:9876 '+release.FROZEN_IMAGE_MARKER.encode()+b' worker\n'
        legacy=b'fixed legacy';before=b'old admission';after=b'group read admission'
        calls=[];extra=[False]
        def git_blob(command,**kwargs):
            self.assertEqual(command[:2],['git','show']);calls.append(command[2])
            commit,path=command[2].split(':',1)
            if path.endswith('worker-install-state-isolation.conf'):return old
            if commit=='23a27325b00f27a5c5696657c7c4141a06135f18':return legacy
            if path==prepare.SOURCES[candidate]:return before if commit==release.INSTALLED_COMMIT else after
            return (('changed:' if extra[0] and commit=='b'*40 and path==prepare.SOURCES['runtime/hermes_worker.py'] else 'same:')+path).encode()
        with patch.object(release,'NATIVE_UNIT_BEFORE_SHA',prepare.digest(old)),patch.object(release,'NATIVE_LEGACY_DAILY_SHA',prepare.digest(legacy)),patch.object(release,'NATIVE_ADMISSION_BEFORE_SHA',prepare.digest(before)),patch.object(release,'NATIVE_ADMISSION_AFTER_SHA',prepare.digest(after)),patch.object(prepare.subprocess,'check_output',side_effect=git_blob),tempfile.TemporaryDirectory() as directory:
            unit=prepare.render_native_unit(old,{'socket':{'gid':994}})
            with patch.object(release,'NATIVE_CURRENT_UNIT_SHA',prepare.digest(unit)):
                out=Path(directory)/'pack';prepare.pack(Path(directory),out,'b'*40)
                value=json.loads((out/'payload-manifest.json').read_bytes())
                self.assertTrue(value['native_admission']);self.assertFalse(value['native_chat'])
                self.assertEqual((out/'payload/unit/native-control.conf').read_bytes(),unit)
                self.assertEqual(value['installed_baseline']['files']['unit/native-control.conf'],prepare.digest(unit))
                self.assertTrue(all(sha is not None for sha in value['installed_baseline']['files'].values()))
                self.assertIn(release.INSTALLED_COMMIT+':'+prepare.MODULE+'source/worker-install-state-isolation.conf',calls)
                extra[0]=True
                with self.assertRaisesRegex(ValueError,'exact_native_admission_git_delta_required'):prepare.pack(Path(directory),Path(directory)/'extra','b'*40)
            with patch.object(release,'NATIVE_CURRENT_UNIT_SHA','0'*64):
                with self.assertRaisesRegex(ValueError,'native_admission_generated_unit_drift'):prepare.admission_generated(Path(directory))

    def test_archive_three_source_original_apply_rollback_and_locked_maintenance(self):
        for failure in (None,'range','readiness'):
            self.tearDown();self.setUp()
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory,self.admission_fixture(Path(directory)) as f:
                root=Path(directory);base=f.base;old_proof=deepcopy(f.proof);old=deepcopy(f.previous)
                oldmap={r['target']:r['sha256'] for r in old['files']};oldmap.update({r['path']:r['sha256'] for r in old['unchangedRequired']})
                prepare.configure_native_archive()
                # Real Store/CAS functions; only identity pins are synthetic.
                source=Path(__file__).resolve().parents[1]/'source/conversation_store.py'
                spec=importlib.util.spec_from_file_location('archive_fixture_store',source);store_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(store_module)
                path=base.rooted(f.system,'/var/lib/fs-hermes-fc/fs/conversations/conversations.db')
                store=store_module.ConversationStore(path.parent);owner='archive-owner';cid=store.create(owner)['conversation_id'];text='Synthetic archive fixture';req='archive_fixture_01'
                with patch.object(sys,'path',[str(source.parent),*sys.path]):
                    from conversation_files import ConversationFiles
                    file=ConversationFiles(store).save(owner,cid,'archive.csv',b'value\n1\n','archive_upload_01')
                    turn=store.reserve_turn(owner,cid,text,req,file_ids=[file['file_id']],native=True)
                lease='a'*32;store.bind_task(owner,cid,turn['turn_id'],turn['turn_id'],lease)
                canonical=lambda v:json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
                with store.db() as db:
                    session=store._owned(db,owner,cid)['session_id']
                    db.execute('CREATE TABLE native_conversation_runs(turn_id PRIMARY KEY,binding,body,idempotency_key,fingerprint,schemas,stopped)')
                    binding=dict(owner=owner,conversation_id=cid,turn_id=turn['turn_id'],request_id=req,session_id=session,lease=lease,run_id=None)
                    body={'input':text,'session_id':session};fp=prepare.digest(canonical({'body':body,'gateway_session_key':''}).encode())
                    db.execute('INSERT INTO native_conversation_runs VALUES(?,?,?,?,?,NULL,1)',(turn['turn_id'],canonical(binding),canonical(body),'hn-'+prepare.digest(canonical([owner,cid,req]).encode()),fp))
                store.set_state(owner,cid,turn['turn_id'],'dispatch_unknown')
                pins=dict(cid=cid,turn_id=turn['turn_id'],request_id=req,session_id=session,lease=lease,owner_sha256=prepare.digest(owner.encode()),fingerprint=fp,input_sha256=prepare.digest(text.encode()),file_ids=[file['file_id']],file_size=file['size'],file_sha256=file['sha256'])
                source_body=source.read_bytes()+('\nSYNTHETIC_ARCHIVE='+repr(pins)+'\n').encode()
                for name,table in (('tasks.sqlite3','tasks'),('pricing-reviews/conversations.db','turns'),('customer-tracking/tracking.db','scan_jobs')):
                    p=base.rooted(f.system,'/var/lib/fs-hermes-fc/fs/'+name);p.parent.mkdir(parents=True,exist_ok=True)
                    with closing(sqlite3.connect(p)) as db:
                        db.execute('CREATE TABLE IF NOT EXISTS '+table+'(state TEXT)')
                        if table=='tasks':db.execute('CREATE TABLE IF NOT EXISTS learning_events(state TEXT)')
                        if table=='scan_jobs':db.execute('CREATE TABLE IF NOT EXISTS milestones(state TEXT)')
                        db.commit()
                live_targets=[release.NGINX,'/opt/fs-exact-range-20261001/range_api.py']+['/opt/fs-hermes-fc/live'+str(i)+'.py' for i in range(6)]
                records=[]
                for i,target in enumerate(live_targets):
                    p=base.rooted(f.system,target);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(('live:'+str(i)).encode())
                    records.append(dict(candidate='live/'+str(i),target=target,sha256=base.digest(p),beforeSha256='0'*64,owner='0:0',mode='0o600' if target==release.NGINX else '0o644'))
                overlap=[p for p in oldmap if p not in live_targets and p not in (release.TARGETS['runtime/conversation_store.py'],release.TARGETS['runtime/conversation_native.py'])][:49]
                keep=[{'path':p,'sha256':oldmap[p]} for p in overlap]
                while len(keep)<743:
                    p='/opt/live-protected/file'+str(len(keep))+'.py';target=base.rooted(f.system,p);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'live protected')
                    keep.append(dict(path=p,sha256=base.digest(target)))
                previous=dict(sourceCommit=release.INSTALLED_PROOF['sourceCommit'],scope='user-admin-live-page-20261102',files=records,unchangedRequired=keep)
                proof=deepcopy(release.INSTALLED_PROOF);backup=base.rooted(f.system,proof['backup']);backup.mkdir(parents=True)
                raw=json.dumps(previous).encode();(backup/'approved-manifest.json').write_bytes(raw);proof['manifestSha256']=prepare.digest(raw)
                journal=dict(status='applied-awaiting-actual-http-role-acceptance',manifest=previous,approvedManifestSha256=proof['manifestSha256'])
                raw=json.dumps(journal).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
                descriptor=json.loads((f.payload.parent/'payload-manifest.json').read_bytes())
                descriptor.update(native_admission=False,native_archive=True,native_chat=False,installed_baseline={'source_commit':release.INSTALLED_COMMIT,'files':{name:oldmap[target] for name,target in release.TARGETS.items()}})
                descriptor['files']={key:value for key,value in descriptor['files'].items() if not key.startswith('payload/')}
                for name in prepare.SOURCES:
                    p=f.payload/name
                    p.write_bytes(source_body if name=='runtime/conversation_store.py' else (base.rooted(f.system,release.TARGETS[name]).read_bytes()+b'\n# archive consumer\n'))
                    descriptor['files']['payload/'+name]=prepare.digest(p.read_bytes())
                raw=json.dumps(descriptor).encode();(f.payload.parent/'payload-manifest.json').write_bytes(raw)
                stage=root/'archive-stage'
                with patch.object(release,'INSTALLED_PROOF',proof),patch.object(prepare,'INSTALLED_PROOF',proof),patch.object(release,'ARCHIVE_NATIVE_PROOF',old_proof):
                    prepare.prepare(f.payload,stage,'a'*40,prepare.digest(raw),root=f.system,followup=True,release_ready=True)
                manifest=json.loads((stage/'approved-manifest.json').read_bytes());self.assertEqual(len(manifest['files']),3);self.assertEqual(len(manifest['unchangedRequired']),776)
                untouched={r['path']:(base.rooted(f.system,r['path']).read_bytes(),base.rooted(f.system,r['path']).stat().st_ino,base.rooted(f.system,r['path']).stat().st_mtime_ns) for r in manifest['unchangedRequired']}
                spec=importlib.util.spec_from_file_location('archive_publisher_fixture',stage/'runtime_release.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                module.configure_native_archive();module.INSTALLED_PROOF=proof;module.ARCHIVE_NATIVE_PROOF=old_proof
                base.hermes_quiescent=Mock();base.retirement=Mock();base.locks=base.live_lock=base.model_release_lock=lambda *a:nullcontext()
                fence=SimpleNamespace(modified=False,confirmed=False,stop_then_unlock_database=Mock());base.hermes_admission_fence=lambda *a:nullcontext(fence)
                restart=Mock(side_effect=[RuntimeError('synthetic range failure'),None] if failure=='range' else None);base.restart_for=restart
                if os.name=='nt':base.directory_sync=lambda *a:None
                readiness=Mock(side_effect=[None,None,RuntimeError('synthetic readiness failure'),None] if failure=='readiness' else None)
                with patch.object(module,'frozen',return_value=base),patch.object(module,'running_worker'),patch.object(module,'native_runtime_readiness',readiness),patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='ActiveState=active\n')):
                    publisher=module.load_base();publisher.inspect(manifest,stage,f.system)
                    bad_git=deepcopy(descriptor['installed_baseline']);bad_git['files']['runtime/conversation_native.py']='0'*64
                    with self.assertRaisesRegex(ValueError,'archive_installed_git_mismatch'):module.installed_baseline(f.system,bad_git)
                    proof_file=base.rooted(f.system,proof['backup']+'/journal.json');proof_bytes=proof_file.read_bytes();proof_file.write_bytes(b'proof drift')
                    with self.assertRaisesRegex(ValueError,'installed_release_proof_drift'):publisher.guards(manifest,f.system)
                    proof_file.write_bytes(proof_bytes)
                    # Other UNKNOWNs and changes to the one exception still block.
                    with store.db() as db:db.execute("INSERT INTO turns(id,conversation_id,request_id,input_sha256,text,state) VALUES('other','other','other','h','x','running')")
                    with self.assertRaises(ValueError):publisher.guards(manifest,f.system)
                    with store.db() as db:db.execute("DELETE FROM turns WHERE id='other'")
                    with store.db() as db:db.execute('UPDATE native_conversation_runs SET stopped=0')
                    with self.assertRaises(ValueError):publisher.guards(manifest,f.system)
                    with store.db() as db:db.execute('UPDATE native_conversation_runs SET stopped=1')
                    candidate=stage/'candidate/runtime/conversation_store.py';saved_source=candidate.read_bytes();candidate.write_bytes(b"raise AssertionError('untrusted source must not execute')")
                    with self.assertRaisesRegex(ValueError,'archive_store_source_drift'):publisher.guards(manifest,f.system)
                    candidate.write_bytes(saved_source)
                    for change in (lambda m:m.update(nativeAdmission=True),lambda m:m['files'].pop(),lambda m:m['unchangedRequired'].pop(),lambda m:m.update(materialChangedTargets=[]),lambda m:m.update(workerImageSource='configured_unit_and_local_image')):
                        bad=deepcopy(manifest);change(bad)
                        with self.assertRaises((ValueError,KeyError)):publisher.validate(bad,stage)
                    manifest_raw=(stage/'approved-manifest.json').read_bytes();release_id='nav-20261103T000001Z'
                    if failure:
                        with self.assertRaisesRegex(RuntimeError,'synthetic .* failure'):publisher.apply(manifest,stage,prepare.digest(manifest_raw),manifest_raw,release_id,f.system)
                    else:
                        publisher.apply(manifest,stage,prepare.digest(manifest_raw),manifest_raw,release_id,f.system)
                        receipt=module.archive_synthetic_maintenance(release_id,prepare.digest(manifest_raw),f.system)
                        self.assertEqual((receipt['archived'],receipt['deleted'],receipt['outcome']),(1,0,'unknown'))
                        self.assertEqual(module.archive_synthetic_maintenance(release_id,prepare.digest(manifest_raw),f.system),receipt)
                        saved=json.loads((base.rooted(f.system,'/var/backups/fs-navigation-20261006/'+release_id)/'journal.json').read_bytes())
                        with self.assertRaisesRegex(ValueError,'archived_unknown_requires_archive_aware_forward_repair'):publisher.rollback_journal(base.rooted(f.system,'/var/backups/fs-navigation-20261006/'+release_id),saved,f.system)
                        with store.db() as db:db.execute("UPDATE synthetic_turn_archives SET receipt_sha256='drift'")
                        with self.assertRaisesRegex(ValueError,'archive_audit_drift'):publisher.guards(manifest,f.system)
                    self.assertTrue(all(c.args[0]['scope']==base.DEEP_SCOPE for c in restart.call_args_list))
                for p,values in untouched.items():self.assertEqual((base.rooted(f.system,p).read_bytes(),base.rooted(f.system,p).stat().st_ino,base.rooted(f.system,p).stat().st_mtime_ns),values)
                if failure:
                    for row in manifest['files']:self.assertEqual(base.digest(base.rooted(f.system,row['target'])),row['beforeSha256'])

    def test_archive_followup_only_three_existing_host_targets(self):
        self.assertTrue(callable(getattr(prepare,'configure_native_archive',None)))
        prepare.configure_native_archive()
        self.assertEqual(set(release.TARGETS),{'runtime/conversation_store.py','runtime/conversation_native.py','runtime/conversation_service.py'})
        self.assertEqual(release.NEW,frozenset())
        self.assertEqual(release.INSTALLED_PROOF['manifestSha256'],'68e907842a53f744e77a6eb30b7c4b4d207ce922ae6a827542835accd8e3079e')

    def test_native_archive_marker_cannot_borrow_installed89_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            stage=Path(directory);(stage/'approved-manifest.json').write_text(json.dumps({'nativeArchive':True,'nativeAdmission':True}),encoding='utf-8')
            with patch.object(release,'HERE',stage),self.assertRaisesRegex(ValueError,'conflicting_material_followup_modes'):
                release.load_base()

    def test_archive_rollback_guard_preserves_unknown_and_denies_blind_restore(self):
        self.assertTrue(callable(getattr(release,'archive_rollback_guard',None)), 'archive rollback guard missing')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=release.frozen()
            journal={'manifest':{'nativeArchive':True},'files':[{'target':'/opt/fs-hermes-fc/conversation_store.py'}]}
            with self.assertRaisesRegex(ValueError,'archive_rollback_ledger_missing'):release.archive_rollback_guard(base,journal,root)
            path=base.rooted(root,'/var/lib/fs-hermes-fc/fs/conversations/conversations.db');path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE turns(id,state)');db.execute("INSERT INTO turns VALUES('original','dispatch_unknown')");db.commit()
            release.archive_rollback_guard(base,journal,root)
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE synthetic_turn_archives(turn_id,receipt,receipt_sha256)');db.commit()
            release.archive_rollback_guard(base,journal,root)
            with closing(sqlite3.connect(path)) as db:
                db.execute("INSERT INTO synthetic_turn_archives VALUES('original','audit','fixed')");db.commit()
            before=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'archived_unknown_requires_archive_aware_forward_repair'):
                release.archive_rollback_guard(base,journal,root)
            self.assertEqual(path.read_bytes(),before)
            # Existing modes and unrelated FC rollback keep their original contract.
            release.archive_rollback_guard(base,dict(journal,manifest={'materialGuard':True}),root)
            release.archive_rollback_guard(base,dict(journal,files=[{'target':'/opt/unrelated.py'}]),root)

    def test_native_admission_is_existing_89_single_file_followup(self):
        self.assertTrue(callable(getattr(prepare, 'configure_native_admission', None)),
                        'installed native admission mode missing')
        prepare.configure_native_admission()
        self.assertTrue(release.NATIVE_ADMISSION_MODE)
        self.assertEqual(release.INSTALLED_COMMIT, '89e5db08edba36cf3d88efdb37601ee1ca53bc38')
        self.assertEqual(release.INSTALLED_PROOF['manifestSha256'],
                         '642d78db24159c3c79f04ca3f67f4e8cda2abdbcd5680022ba6c9e9f71969084')
        self.assertEqual((len(release.TARGETS),len(release.protected_paths(release.frozen())),len(release.NEW)),(34,45,0))
        self.assertEqual(release.NATIVE_CURRENT_UNIT_SHA, '5f31448a6396d8d702d2cda1df7d192cd022e7d42f53d04a2a97e1664e9955e3')

    def test_native_mode_exact_installed_proof_targets_and_new_modules(self):
        self.assertTrue(callable(getattr(prepare,'configure_native_chat',None)),'native publisher mode is missing')
        prepare.configure_native_chat()
        self.assertEqual(release.INSTALLED_COMMIT,'23a27325b00f27a5c5696657c7c4141a06135f18')
        self.assertEqual(release.INSTALLED_PROOF['manifestSha256'],'ae010cb6b11a1a7c7c4ed877ae7534dbfc63b443143955cdd990ed96dfe19cf4')
        self.assertEqual(len(release.TARGETS),34)
        self.assertEqual(len(release.protected_paths(release.frozen())),45)
        self.assertEqual(release.TARGETS['runtime/direct_provider.py'],'/opt/fs-hermes-fc/direct_provider.py')
        self.assertEqual(prepare.SOURCES['runtime/direct_provider.py'],prepare.CORE+'direct_provider.py')
        self.assertEqual(release.NATIVE_PROVIDER_BEFORE_SHA,'91d301ebe3578d0e6c60c23252510ebb34416a57f9f5dfc4ffd744f5ae0c74fa')
        self.assertNotIn(release.TARGETS['runtime/direct_provider.py'],release.protected_paths(release.frozen()))
        self.assertEqual(release.NEW,frozenset({'runtime/conversation_native.py','runtime/native_chat.py','runtime/native-backend.json','approval/native_review.py','approval/daily_review.py'}))
        self.assertEqual(release.TARGETS['approval/daily_review.py'],'/opt/fs-hermes-memory-approval/daily_review.py')
        self.assertIn(release.NATIVE_LEGACY_DAILY,release.protected_paths(release.frozen()))
        self.assertNotIn(release.NATIVE_UNIT,release.protected_paths(release.frozen()))
        self.assertIn('/usr/bin/docker',release.protected_paths(release.frozen()))
        self.assertFalse(release.GUARD_MODE)

    def test_native_provider_promotion_requires_exact_old_proof_and_git_before(self):
        prepare.configure_native_chat()
        candidate='runtime/direct_provider.py';target=release.TARGETS[candidate]
        previous={'sourceCommit':release.INSTALLED_COMMIT,'scope':release.SCOPE,
                  'files':[{'candidate':name,'target':path,'sha256':'a'*64}
                           for name,path in release.NATIVE_INSTALLED_TARGETS.items()],
                  'unchangedRequired':[{'path':path,'sha256':release.NATIVE_UNIT_BEFORE_SHA if path==release.NATIVE_UNIT else
                                       release.NATIVE_PROVIDER_BEFORE_SHA if path==target else 'b'*64}
                                       for path in sorted(release.NATIVE_INSTALLED_PROTECTED)]}
        baseline={'source_commit':release.INSTALLED_COMMIT,'files':{row['candidate']:row['sha256'] for row in previous['files']}}
        baseline['files'].update({name:None for name in release.NEW})
        baseline['files'].update(release.NATIVE_EXTERNAL_BEFORE)
        baseline['files'].update({'unit/native-control.conf':release.NATIVE_UNIT_BEFORE_SHA,candidate:release.NATIVE_PROVIDER_BEFORE_SHA})
        baseline['protected']={release.NATIVE_LEGACY_DAILY:release.NATIVE_LEGACY_DAILY_SHA}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=release.frozen();backup=base.rooted(root,release.INSTALLED_PROOF['backup']);backup.mkdir(parents=True)
            for drift in (None,'missing','duplicate','protection_hash','git_hash','source'):
                with self.subTest(drift=drift):
                    manifest=deepcopy(previous);git_before=deepcopy(baseline)
                    if drift=='missing':manifest['unchangedRequired']=[r for r in manifest['unchangedRequired'] if r['path']!=target]
                    elif drift=='duplicate':manifest['unchangedRequired'].append(next(r for r in manifest['unchangedRequired'] if r['path']==target).copy())
                    elif drift=='protection_hash':next(r for r in manifest['unchangedRequired'] if r['path']==target)['sha256']='c'*64
                    elif drift=='git_hash':git_before['files'][candidate]='c'*64
                    elif drift=='source':manifest['sourceCommit']='0'*40
                    raw=json.dumps(manifest).encode();(backup/'approved-manifest.json').write_bytes(raw)
                    proof=dict(release.INSTALLED_PROOF,manifestSha256=prepare.digest(raw))
                    journal={'manifest':manifest,'status':'applied-awaiting-actual-http-role-acceptance','approvedManifestSha256':proof['manifestSha256']}
                    raw=json.dumps(journal).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
                    with patch.object(release,'INSTALLED_PROOF',proof):
                        if drift:
                            with self.assertRaisesRegex(ValueError,'native_installed_git_and_journal_mismatch'):
                                release.installed_baseline(root,git_before)
                        else:self.assertEqual(release.installed_baseline(root,git_before),manifest)

    def test_native_prepare_original_apply_rollback_and_unchanged_metadata(self):
        for fail in (False,'worker','native_readiness'):
            # Start from an installed 25-target material-guard package, then promote
            # precisely the new native dependencies. All IO uses real temp files.
            self.tearDown(); self.setUp()
            with self.subTest(failure=fail),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                prepare.configure_material_guard()
                old_case=RuntimeMaterials()
                base,system,payload,metadata,_,_,previous=old_case.installed_fixture(root)
                old_targets=dict(release.TARGETS)
                old_unit=b'[Service]\nExecStart=\nExecStart=/usr/bin/docker run --rm --user 9876:9876 '+release.FROZEN_IMAGE_MARKER.encode()+b' worker\n'
                unit=base.rooted(system,release.NATIVE_UNIT);unit.write_bytes(old_unit)
                prepare.configure_native_chat()
                release.NATIVE_UNIT_BEFORE_SHA=prepare.digest(old_unit)
                legacy=base.rooted(system,release.NATIVE_LEGACY_DAILY);legacy.parent.mkdir(parents=True,exist_ok=True);legacy.write_bytes(b'old host daily')
                release.NATIVE_LEGACY_DAILY_SHA=prepare.digest(legacy.read_bytes())
                profile=base.rooted(system,'/var/lib/fs-hermes-fc/profile')
                owners={profile:(9876,9876,0o700)}
                legacy_before=(legacy.read_bytes(),legacy.stat().st_ino,legacy.stat().st_mtime_ns)
                release.NATIVE_PROVIDER_BEFORE_SHA=prepare.digest(base.rooted(system,release.TARGETS['runtime/direct_provider.py']).read_bytes())
                release.NATIVE_EXTERNAL_BEFORE={name:prepare.digest(('old:'+name).encode()) for name in release.NATIVE_EXTERNAL_BEFORE}
                for name in release.NATIVE_EXTERNAL_BEFORE:
                    path=base.rooted(system,release.TARGETS[name]);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('old:'+name).encode())
                cli=base.rooted(system,release.NATIVE_CLI);cli.parent.mkdir(parents=True,exist_ok=True);cli.write_bytes(b'fixed CLI')
                release.NATIVE_CLI_SHA=prepare.digest(b'fixed CLI')
                previous['sourceCommit']=release.INSTALLED_COMMIT
                previous['files']=[row for row in previous['files'] if row['candidate'] in old_targets]
                previous['unchangedRequired']=[{'path':path,'sha256':prepare.digest(base.rooted(system,path).read_bytes())} for path in sorted(release.NATIVE_INSTALLED_PROTECTED)]
                proof=dict(release.INSTALLED_PROOF)
                backup=base.rooted(system,proof['backup']);backup.mkdir(parents=True,exist_ok=True)
                raw=json.dumps(previous).encode();(backup/'approved-manifest.json').write_bytes(raw);proof['manifestSha256']=prepare.digest(raw)
                journal={'status':'applied-awaiting-actual-http-role-acceptance','manifest':previous,'approvedManifestSha256':proof['manifestSha256']}
                raw=json.dumps(journal).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
                descriptor=json.loads((payload.parent/'payload-manifest.json').read_bytes())
                descriptor.update(material_execution=True,material_diagnostics=False,goal_task_index_compat=False,worker_diagnostics=False,material_transport=False,material_stream=False,bindings_auth=False,material_guard=False,native_chat=True)
                git_before={row['candidate']:row['sha256'] for row in previous['files']}
                git_before.update({name:None for name in release.NEW});git_before.update(release.NATIVE_EXTERNAL_BEFORE);git_before['unit/native-control.conf']=release.NATIVE_UNIT_BEFORE_SHA
                git_before['runtime/direct_provider.py']=release.NATIVE_PROVIDER_BEFORE_SHA
                descriptor['installed_baseline']={'source_commit':release.INSTALLED_COMMIT,'files':git_before,'protected':{release.NATIVE_LEGACY_DAILY:release.NATIVE_LEGACY_DAILY_SHA}}
                generated=prepare.native_generated()
                for name in prepare.SOURCES:
                    path=payload/name;path.parent.mkdir(parents=True,exist_ok=True)
                    if name in generated:body=generated[name]
                    elif name=='approval/reviewed_skills.py':body=base.rooted(system,release.TARGETS[name]).read_bytes()
                    else:body=('native:'+name).encode() if name in release.NATIVE_ALLOWED else base.rooted(system,release.TARGETS[name]).read_bytes()
                    path.write_bytes(body);descriptor['files']['payload/'+name]=prepare.digest(body)
                raw=json.dumps(descriptor).encode();(payload.parent/'payload-manifest.json').write_bytes(raw)
                deps={'cli':{'sha256':release.NATIVE_CLI_SHA},'socket':{'gid':998},'worker_user':'9876:9876'}
                stage=root/'native-stage'
                with self.native_metadata(owners,root=system),patch.object(release,'INSTALLED_PROOF',proof),patch.object(prepare,'INSTALLED_PROOF',proof),patch.object(prepare,'file_metadata',metadata),patch.object(release,'native_dependencies',return_value=deps):
                    if not fail:
                        daily=base.rooted(system,release.TARGETS['approval/daily_review.py'])
                        daily.parent.mkdir(parents=True,exist_ok=True);daily.write_bytes(b'already installed elsewhere')
                        with self.assertRaisesRegex(ValueError,'runtime_source_baseline_drift'):
                            prepare.prepare(payload,root/'daily-already-present','a'*40,prepare.digest(raw),root=system,followup=True,release_ready=True)
                        self.assertFalse((root/'daily-already-present').exists());daily.unlink()
                        recipe=payload/'unit/native-control.conf';recipe_bytes=recipe.read_bytes()
                        for variant in ('old_recipe','writable','source','target','extra'):
                            bad=json.loads(recipe_bytes)
                            if variant=='old_recipe':bad={'recipe':'native_worker_mounts_v1'}
                            elif variant=='writable':bad['daily_readonly']=False
                            elif variant=='source':bad['daily_source']=release.NATIVE_LEGACY_DAILY
                            elif variant=='target':bad['daily_target']='/profile/scripts/other.py'
                            else:bad['extra_mount']='/profile/extra'
                            recipe.write_bytes(json.dumps(bad).encode())
                            changed=deepcopy(descriptor);changed['files']['payload/unit/native-control.conf']=prepare.digest(recipe.read_bytes())
                            bad_raw=json.dumps(changed).encode();(payload.parent/'payload-manifest.json').write_bytes(bad_raw)
                            with self.subTest(recipe=variant),self.assertRaisesRegex(ValueError,'native_unit_recipe_changed'):
                                prepare.prepare(payload,root/('bad-recipe-'+variant),'a'*40,prepare.digest(bad_raw),root=system,followup=True,release_ready=True)
                            self.assertFalse((root/('bad-recipe-'+variant)).exists())
                        recipe.write_bytes(recipe_bytes);(payload.parent/'payload-manifest.json').write_bytes(raw)
                        provider=base.rooted(system,release.TARGETS['runtime/direct_provider.py'])
                        before=provider.read_bytes();provider.write_bytes(b'other writer')
                        with self.assertRaisesRegex(ValueError,'runtime_source_baseline_drift'):
                            prepare.prepare(payload,root/'provider-drift', 'a'*40,prepare.digest(raw),root=system,followup=True,release_ready=True)
                        self.assertFalse((root/'provider-drift').exists())
                        provider.write_bytes(before)
                    prepare.prepare(payload,stage,'a'*40,prepare.digest(raw),root=system,followup=True,release_ready=True)
                    manifest=json.loads((stage/'approved-manifest.json').read_bytes())
                    self.assertTrue(manifest['nativeChat']);self.assertEqual(len(manifest['files']),34)
                    self.assertEqual(len(manifest['unchangedRequired']),45)
                    provider_row=next(r for r in manifest['files'] if r['candidate']=='runtime/direct_provider.py')
                    self.assertEqual(provider_row['beforeSha256'],release.NATIVE_PROVIDER_BEFORE_SHA)
                    self.assertNotIn('runtime/direct_provider.py',release.NEW)
                    self.assertEqual(manifest['nativeDependencies'],deps)
                    original_meta={row['target']:(base.rooted(system,row['target']).stat().st_ino,base.rooted(system,row['target']).stat().st_mtime_ns) for row in manifest['files'] if row['beforeSha256']==row['sha256']}
                spec=importlib.util.spec_from_file_location('native_publisher_fixture',stage/'runtime_release.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                module.configure_native_chat();module.INSTALLED_PROOF=proof
                base.MATERIAL_NEW=module.NEW
                module.NATIVE_UNIT_BEFORE_SHA=release.NATIVE_UNIT_BEFORE_SHA;module.NATIVE_EXTERNAL_BEFORE=dict(release.NATIVE_EXTERNAL_BEFORE);module.NATIVE_CLI_SHA=release.NATIVE_CLI_SHA
                module.NATIVE_PROVIDER_BEFORE_SHA=release.NATIVE_PROVIDER_BEFORE_SHA
                module.NATIVE_LEGACY_DAILY_SHA=release.NATIVE_LEGACY_DAILY_SHA
                module.native_dependencies=lambda *a:deps
                base.hermes_quiescent=Mock();base.retirement=Mock()  # Keep original guards and source-parent checks.
                base.locks=base.live_lock=base.model_release_lock=lambda *a:nullcontext()
                fence=SimpleNamespace(modified=False,confirmed=False,stop_then_unlock_database=Mock())
                base.hermes_admission_fence=lambda *a:nullcontext(fence)
                def restart_effect(*args,**kwargs):
                    if fail=='worker' and restart_spy.call_count==1:
                        raise RuntimeError('native worker restart failed')
                    if fail and restart_spy.call_count>1 and (fail=='worker' or restart_spy.call_count>2):
                        for row in manifest['files']:
                            self.assertEqual(base.digest(base.rooted(system,row['target'])),row['beforeSha256'])
                restart_spy=Mock(side_effect=restart_effect)
                base.restart_for=restart_spy
                if os.name=='nt':base.directory_sync=lambda *a:None
                native_readback=Mock(side_effect=RuntimeError('native worker restart failed') if fail=='native_readiness' else None)
                with self.native_metadata(owners,root=system),patch.object(module,'frozen',return_value=base),patch.object(module,'quiescent'),patch.object(module,'running_worker'),patch.object(module,'native_runtime_readiness',native_readback),patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='ActiveState=active\n')):
                    publisher=module.load_base()
                    publisher.inspect(manifest,stage,system)
                    for change in (
                        lambda m:m.update(materialGuard=True),
                        lambda m:m['installedBaseline'].update(sourceCommit='0'*40),
                        lambda m:m['runtimeBefore']['fs-hermes-fc.service'].update(ActiveState='failed'),
                        lambda m:m.update(workerImageSource='configured_unit_and_local_image'),
                        lambda m:m['files'].pop(),
                        lambda m:m['unchangedRequired'].pop(),
                        lambda m:m['nativeDependencies'].update(worker_user='0:0'),
                        lambda m:m['nativeDependencies']['cli'].update(sha256='0'*64),
                    ):
                        invalid=deepcopy(manifest);change(invalid)
                        with self.assertRaises((ValueError,KeyError)):publisher.validate(invalid,stage)
                    manifest_raw=(stage/'approved-manifest.json').read_bytes()
                    if fail:
                        with self.assertRaisesRegex(RuntimeError,'native worker restart failed'):
                            publisher.apply(manifest,stage,prepare.digest(manifest_raw),manifest_raw,'nav-20261102T030001Z',system)
                    else:publisher.apply(manifest,stage,prepare.digest(manifest_raw),manifest_raw,'nav-20261102T030001Z',system)
                    for row in manifest['files']:
                        path=base.rooted(system,row['target'])
                        if fail and row['beforeSha256'] is None:self.assertFalse(path.exists())
                        else:self.assertEqual(base.digest(path),row['beforeSha256'] if fail else row['sha256'])
                        if row['target'] in original_meta:self.assertEqual((path.stat().st_ino,path.stat().st_mtime_ns),original_meta[row['target']])
                    scopes=[call.args[0]['scope'] for call in restart_spy.call_args_list]
                    self.assertIn(base.HERMES_WORKER_SCOPE,scopes)
                    self.assertIn(base.DEEP_SCOPE,scopes)
                    self.assertEqual(native_readback.call_count,0 if fail=='worker' else 1)
                    self.assertFalse(any(call.args and call.args[0][:2]==['systemctl','reload'] for call in module.subprocess.run.call_args_list))
                    self.assertEqual((legacy.read_bytes(),legacy.stat().st_ino,legacy.stat().st_mtime_ns),legacy_before)

    def test_native_unit_is_exact_increment_cli_socket_only_control_plane(self):
        prepare.configure_native_chat()
        self.assertTrue(callable(getattr(prepare,'render_native_unit',None)),'native unit generation missing')
        old=b'[Service]\nExecStart=\nExecStart=/usr/bin/docker run --rm --user 9876:9876 --name fs-hermes-fc '+release.FROZEN_IMAGE_MARKER.encode()+b' old-entry\n'
        with patch.object(release,'NATIVE_UNIT_BEFORE_SHA',prepare.digest(old),create=True):
            changed=prepare.render_native_unit(old,{'socket':{'gid':998}})
            self.assertIn(b'--group-add 998',changed)
            self.assertIn(b'source=/usr/bin/docker,target=/opt/fs-native-bin/docker,readonly',changed)
            self.assertIn(b'source=/run/docker.sock,target=/var/run/docker.sock',changed)
            mount=b'--mount type=bind,source=/opt/fs-hermes-memory-approval/daily_review.py,target=/profile/scripts/hermes-memory-review/daily_review.py,readonly'
            self.assertEqual(changed.count(mount),1)
            self.assertEqual(changed.count(release.FROZEN_IMAGE_MARKER.encode()),1)
            self.assertIn(b'--user 9876:9876',changed)
            self.assertEqual(prepare.render_native_unit(old,{'socket':{'gid':998}}),changed)
            with self.assertRaises(ValueError):prepare.render_native_unit(old+b'drift',{'socket':{'gid':998}})
            with self.assertRaises(ValueError):prepare.render_native_unit(changed,{'socket':{'gid':998}})

    def test_control_readiness_checks_exact_contract_user_daemon_and_mounts(self):
        prepare.configure_native_chat()
        contract=prepare.native_generated()['runtime/native-backend.json']
        mounts=[{'Destination':destination,'Source':source,'RW':rw} for destination,source,rw in (
            ('/opt/fs-native-bin/docker','/usr/bin/docker',False),
            ('/var/run/docker.sock','/run/docker.sock',True),
            (release.NATIVE_ROOT,release.NATIVE_ROOT,True),
            ('/opt/fs-native-backend-home',release.NATIVE_EMPTY_SOURCE,False),
            (release.NATIVE_DAILY_CONTAINER,release.TARGETS['approval/daily_review.py'],False))]
        user=['9876:9876'];failure=[False]
        def observed(command,**kwargs):
            if '{{.Config.User}}' in command:return user[0]
            if 'version' in command:
                if failure[0]:raise OSError('synthetic daemon refusal')
                return '24.0.0|24.0.0'
            return json.dumps(mounts)
        with patch.object(Path,'read_bytes',return_value=contract),patch.object(Path,'is_symlink',return_value=False),patch.object(release.subprocess,'check_output',side_effect=observed):
            release.native_runtime_readiness()
            user[0]='0:0'
            with self.assertRaisesRegex(ValueError,'native_control_user_readback'):release.native_runtime_readiness()
            user[0]='9876:9876';mounts[0]['RW']=True
            with self.assertRaisesRegex(ValueError,'native_control_mount_readback'):release.native_runtime_readiness()
            mounts[0]['RW']=False;failure[0]=True
            with self.assertRaises(OSError):release.native_runtime_readiness()
            failure[0]=False
            original=deepcopy(mounts)
            daily=next(row for row in mounts if row['Destination']==release.NATIVE_DAILY_CONTAINER)
            for variant in ('writable','source','target','duplicate','extra','missing'):
                mounts[:]=deepcopy(original);daily=next(row for row in mounts if row['Destination']==release.NATIVE_DAILY_CONTAINER)
                if variant=='writable':daily['RW']=True
                elif variant=='source':daily['Source']=release.NATIVE_LEGACY_DAILY
                elif variant=='target':daily['Destination']='/profile/scripts/hermes-memory-review/other.py'
                elif variant=='duplicate':mounts.append(daily.copy())
                elif variant=='extra':mounts.append(dict(daily,Destination='/profile/scripts/hermes-memory-review/extra.py'))
                else:mounts.remove(daily)
                with self.subTest(variant=variant),self.assertRaisesRegex(ValueError,'native_control_mount_readback'):release.native_runtime_readiness()
            mounts[:]=original
            with patch.object(Path,'read_bytes',return_value=b'{}'):
                with self.assertRaisesRegex(ValueError,'native_control_contract_drift'):release.native_runtime_readiness()

if __name__ == '__main__':
    unittest.main()
