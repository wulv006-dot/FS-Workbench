"""Synthetic publisher/SQLite checks; not real Linux modes, deployment or login."""
from contextlib import closing, contextmanager, nullcontext, ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
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




    # Real tempFS and frozen writer; Git/OS/services are explicit fixtures.
    BEFORE = '1' * 40
    AFTER = '2' * 40
    SELECTED = ('runtime/conversation_service.py', 'runtime/report_method.py',
                'runtime/fs_native_readonly.py')

    @contextmanager
    def scope_fixture(self, new=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = {name: {'source_commit': self.BEFORE,
                             'source_path': prepare.SOFTWARE_SOURCES[name]}
                      for name in self.SELECTED}
            for name in new:before[name]=None
            blobs = {}
            for name in self.SELECTED:
                source = prepare.SOFTWARE_SOURCES[name]
                blobs[self.BEFORE + ':' + source] = ('previous Git software ' + name).encode()
                blobs[self.AFTER + ':' + source] = ('reviewed Git software ' + name).encode()
                if name=='runtime/report_method.py' and 'http/range_api.py' in self.SELECTED:
                    blobs[self.AFTER + ':' + source]+=b'\n'
                if name=='http/range_api.py':
                    blobs[self.BEFORE + ':' + source]=b'# Git before range\nvalue = 1\n'
                    blobs[self.AFTER + ':' + source]=b'# Git after range\nvalue = 2\n'
                if name in new:del blobs[self.BEFORE + ':' + source]
            # One explicitly selected dependency has no byte change: never write it.
            name = self.SELECTED[-1]
            if name not in new:
                blobs[self.AFTER + ':' + prepare.SOFTWARE_SOURCES[name]] = blobs[self.BEFORE + ':' + prepare.SOFTWARE_SOURCES[name]]
            for name in prepare.PUBLISHER_SOURCES:
                path = release.HERE/name
                if name == 'release_readiness.py':
                    path = next(parent/prepare.PUBLISHER_SOURCES[name] for parent in release.HERE.parents
                                if (parent/prepare.PUBLISHER_SOURCES[name]).is_file())
                blobs[self.AFTER + ':' + prepare.PUBLISHER_SOURCES[name]] = path.read_bytes()
            def git(command, **kwargs):
                self.assertEqual(command[:2], ['git', 'show'])
                return blobs[command[2]]
            bundle = root/'bundle'
            with patch.object(prepare.subprocess, 'check_output', side_effect=git):
                packed = prepare.pack(root, bundle, self.AFTER, software_before=before)
            descriptor = json.loads((bundle/'payload-manifest.json').read_bytes())
            system = root/'system'; system.mkdir()
            base = release.frozen()
            for name in self.SELECTED:
                path = base.rooted(system, release.SOFTWARE_TARGETS[name])
                path.parent.mkdir(parents=True, exist_ok=True)
                if name not in new:
                    body=blobs[self.BEFORE + ':' + prepare.SOFTWARE_SOURCES[name]]
                    if name=='http/range_api.py':body=body.replace(b'\n',b'\r\n')
                    path.write_bytes(body)
            # Protect the original required consumers using this prepare snapshot.
            for target in release.software_protected_paths(base, set(release.SOFTWARE_TARGETS[n] for n in self.SELECTED)):
                path = base.rooted(system, target)
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'legitimate independently updated software')
            ledger = system/'business-ledger.db'; ledger.write_bytes(b'preserve data and original IDs')
            def metadata(base, host, target, absent=False):
                path=base.rooted(host,target);base.no_target_link(path)
                if absent and not path.exists():return {'path':target,'sha256':None}
                return {'path':target,'sha256':prepare.digest(path.read_bytes()),'mode':release.payload_mode(target),'owner':'0:0'}
            with patch.object(prepare, 'file_metadata', side_effect=metadata):
                yield SimpleNamespace(root=root,system=system,bundle=bundle,payload=bundle/'payload',
                                      descriptor=descriptor,packed=packed,base=base,ledger=ledger)

    def prepare_stage(self, f, name='stage'):
        stage=f.root/name
        prepare.prepare(f.payload, stage, self.AFTER, f.packed['payload_sha256'],
                        root=f.system, followup=True, release_ready=True)
        return stage, json.loads((stage/'approved-manifest.json').read_bytes())

    @contextmanager
    def publisher(self, f, stage):
        spec=importlib.util.spec_from_file_location('scoped_software_release',stage/'runtime_release.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        base=module.load_base()
        original_stat=Path.stat
        def fixture_stat(path, *args, **kwargs):
            info=original_stat(path,*args,**kwargs)
            # CI need not run as root. Only the declared OS identity/mode fixture
            # is synthetic; nlink, inode, sizes, timestamps and bytes stay real.
            fields={k:getattr(info,k) for k in dir(info) if k.startswith('st_')}
            fields.update(st_uid=0,st_gid=0)
            if os.name=='nt':fields['st_mode']=info.st_mode & ~0o022
            return SimpleNamespace(**fields)
        if os.name=='nt':base.directory_sync=lambda path:None
        base.retirement=lambda *args:None
        base.hermes_quiescent=lambda *args:None
        fence=SimpleNamespace(modified=False,confirmed=False,stop_then_unlock_database=Mock())
        lock_calls=[]
        def lock(*args):lock_calls.append(True);return nullcontext()
        base.locks=base.live_lock=base.model_release_lock=lock
        base.hermes_admission_fence=lambda *args:nullcontext(fence)
        observed={'image':release.FROZEN_IMAGE_MARKER,'state':'active','source':'container'}
        def command(args, **kwargs):
            if args[:2]==['systemctl','show']:
                return 'ActiveState=active\n'
            raise AssertionError('unexpected service command: '+str(args))
        with patch.object(Path,'stat',fixture_stat), patch.object(module,'worker_observation',return_value=observed), \
                patch.object(base.subprocess,'check_output',side_effect=command), \
                patch.object(base.subprocess,'run',side_effect=lambda args, **kw:SimpleNamespace(stdout=command(args,**kw),returncode=0)):
            yield base,module,fence,lock_calls

    def test_selected_git_scope_ignores_unrelated_history_and_omits_unchanged_dependency(self):
        with self.scope_fixture() as f:
            self.assertEqual(set(f.descriptor['installed_baseline']['files']),set(self.SELECTED))
            stage,manifest=self.prepare_stage(f)
            self.assertEqual([r['candidate'] for r in manifest['files']],list(self.SELECTED[:2]))
            self.assertEqual(len(manifest['files']),2)
            self.assertNotIn('protectedBaseline',manifest)
            self.assertTrue(any(r['sha256']==prepare.digest(b'legitimate independently updated software')
                                for r in manifest['unchangedRequired']))
            with self.publisher(f,stage) as (base,module,fence,locks):
                result=base.inspect(manifest,stage,f.system)
                self.assertEqual(result['protectedCAS'],'passed')

    def test_exact_git_before_mismatch_rejected_before_stage_creation(self):
        with self.scope_fixture() as f:
            path=f.base.rooted(f.system,release.SOFTWARE_TARGETS[self.SELECTED[0]])
            path.write_bytes(b'arbitrary observed current bytes cannot become before')
            with self.assertRaisesRegex(ValueError,'runtime_source_baseline_drift'):
                self.prepare_stage(f)
            self.assertFalse((f.root/'stage').exists())

    def test_selected_before_source_and_payload_tampering_are_rejected(self):
        with self.scope_fixture() as f:
            descriptor=deepcopy(f.descriptor)
            descriptor['installed_baseline']['sources'][self.SELECTED[0]]['source_path']='unreviewed/source.py'
            raw=json.dumps(descriptor).encode();(f.bundle/'payload-manifest.json').write_bytes(raw)
            f.packed['payload_sha256']=prepare.digest(raw)
            with self.assertRaisesRegex(ValueError,'software_before_source'):
                self.prepare_stage(f)
            self.assertFalse((f.root/'stage').exists())

    def test_unreviewed_target_mapping_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaisesRegex(ValueError,'reviewed_software_selection'):
                prepare.pack(root,root/'bundle',self.AFTER,software_before={'runtime/business.db':{
                    'source_commit':self.BEFORE,'source_path':'unreviewed'}})
            self.assertFalse((root/'bundle').exists())

    def test_fresh_protection_after_prior_update_and_apply_window_cas(self):
        with self.scope_fixture() as f:
            stage,manifest=self.prepare_stage(f)
            protected=f.base.rooted(f.system,manifest['unchangedRequired'][0]['path'])
            protected.write_bytes(b'legitimate update after prepare')
            with self.publisher(f,stage) as (base,module,fence,locks):
                with self.assertRaisesRegex(ValueError,'protected'):
                    base.apply(manifest,stage,prepare.digest((stage/'approved-manifest.json').read_bytes()),
                               (stage/'approved-manifest.json').read_bytes(),'nav-20261106T010000Z',f.system)
            self.assertFalse(f.base.rooted(f.system,'/var/backups/fs-navigation-20261006/nav-20261106T010000Z').exists())
            fresh,fresh_manifest=self.prepare_stage(f,'fresh')
            self.assertEqual(next(r['sha256'] for r in fresh_manifest['unchangedRequired']
                                  if r['path']==manifest['unchangedRequired'][0]['path']),prepare.digest(protected.read_bytes()))
            with self.publisher(f,fresh) as (base,module,fence,locks):
                base.inspect(fresh_manifest,fresh,f.system)

    def test_original_apply_journal_rollback_and_only_affected_restart_scope(self):
        with self.scope_fixture() as f:
            stage,manifest=self.prepare_stage(f)
            raw=(stage/'approved-manifest.json').read_bytes()
            protected_before={r['path']:f.base.rooted(f.system,r['path']).read_bytes() for r in manifest['unchangedRequired']}
            with self.publisher(f,stage) as (base,module,fence,locks):
                scopes=[]
                # Service calls/readiness are a fixture; original apply/inspect/guards/rollback run.
                with patch.object(module,'software_restart',side_effect=lambda b,r,m,admission:scopes.append(m['scope'])):
                    result=base.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261106T020000Z',f.system)
                    backup=Path(result['backup']);journal=json.loads((backup/'journal.json').read_bytes())
                    self.assertEqual({r['candidate'] for r in journal['files']},set(self.SELECTED[:2]))
                    self.assertTrue(all(r.get('intent') and r.get('written') for r in journal['files']))
                    base.rollback(backup,prepare.digest(raw),f.system)
                self.assertEqual(scopes,[base.DEEP_SCOPE,base.DEEP_SCOPE])
                self.assertTrue(fence.modified and fence.confirmed);self.assertGreaterEqual(len(locks),6)
            self.assertEqual(f.ledger.read_bytes(),b'preserve data and original IDs')
            self.assertEqual({p:f.base.rooted(f.system,p).read_bytes() for p in protected_before},protected_before)
            for row in manifest['files']:
                self.assertEqual(prepare.digest(f.base.rooted(f.system,row['target']).read_bytes()),row['beforeSha256'])

    def test_hardlinked_selected_target_is_refused_even_with_identical_bytes(self):
        with self.scope_fixture() as f:
            stage,manifest=self.prepare_stage(f)
            target=f.base.rooted(f.system,manifest['files'][0]['target'])
            link=f.system/'unexpected-hardlink.py'
            os.link(target,link)
            with self.publisher(f,stage) as (base,module,fence,locks):
                with self.assertRaisesRegex(ValueError,'software_target_boundary'):
                    base.inspect(manifest,stage,f.system)

    def test_fenced_range_recovers_for_worker_or_pricing_only_apply_and_rollback(self):
        for changed in ('runtime/hermes_worker.py','pricing/hermes_pricing_bridge.py','runtime/report_artifacts.py'):
            selected=(changed,'runtime/fs_native_readonly.py')
            with self.subTest(changed=changed),patch.object(self,'SELECTED',selected),self.scope_fixture() as f:
                stage,manifest=self.prepare_stage(f)
                raw=(stage/'approved-manifest.json').read_bytes()
                with self.publisher(f,stage) as (base,module,fence,locks):
                    state={'range':True};scopes=[]
                    fence.stop_then_unlock_database.side_effect=lambda:state.update(range=False)
                    def restart(b,original,m,admission):
                        scopes.append(m['scope'])
                        if m['scope']==base.DEEP_SCOPE:state['range']=True
                    def show(args,**kwargs):
                        if args[:2]==['systemctl','show']:
                            active=state['range'] if any('fs-business-range' in str(a) for a in args) else True
                            return 'ActiveState='+('active' if active else 'inactive')+'\n'
                        raise AssertionError(args)
                    with patch.object(module,'software_restart',side_effect=restart),patch.object(base.subprocess,'check_output',side_effect=show):
                        failure=None
                        try:result=base.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261106T050000Z',f.system)
                        except (ValueError,RuntimeError) as error:failure=str(error)
                        self.assertIsNone(failure,'The original admission fence stopped range and it was not restored')
                        self.assertTrue(state['range'])
                        base.rollback(Path(result['backup']),prepare.digest(raw),f.system)
                        self.assertTrue(state['range'])
                    one=[base.HERMES_WORKER_SCOPE,base.DEEP_SCOPE] if changed.startswith('runtime/') else [base.DEEP_SCOPE]
                    self.assertEqual(scopes,one+one)

    def test_worker_and_host_changes_restart_only_their_original_consumers(self):
        selected=('runtime/hermes_worker.py','runtime/conversation_service.py','runtime/fs_native_readonly.py')
        with patch.object(self,'SELECTED',selected),self.scope_fixture() as f:
            stage,manifest=self.prepare_stage(f)
            raw=(stage/'approved-manifest.json').read_bytes()
            with self.publisher(f,stage) as (base,module,fence,locks):
                scopes=[]
                with patch.object(module,'software_restart',side_effect=lambda b,r,m,a:scopes.append(m['scope'])):
                    base.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261106T030000Z',f.system)
                self.assertEqual(scopes,[base.HERMES_WORKER_SCOPE,base.DEEP_SCOPE])

    def test_readiness_failure_uses_original_automatic_rollback(self):
        with self.scope_fixture() as f:
            stage,manifest=self.prepare_stage(f)
            raw=(stage/'approved-manifest.json').read_bytes()
            with self.publisher(f,stage) as (base,module,fence,locks):
                with patch.object(module,'software_restart',side_effect=[ValueError('fixture readiness failed'),None]), \
                        self.assertRaisesRegex(ValueError,'fixture readiness failed'):
                    base.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261106T040000Z',f.system)
                backup=f.base.rooted(f.system,'/var/backups/fs-navigation-20261006/nav-20261106T040000Z')
                journal=json.loads((backup/'journal.json').read_bytes())
                self.assertEqual(journal['status'],'rolled-back')
                self.assertEqual(len(journal['files']),2)
                self.assertTrue(all(not r['written'] for r in journal['files']))
            self.assertEqual(f.ledger.read_bytes(),b'preserve data and original IDs')
            for row in manifest['files']:
                self.assertEqual(f.base.digest(f.base.rooted(f.system,row['target'])),row['beforeSha256'])

    def test_baseline_and_after_exact_bytes_are_bound_to_approved_descriptor(self):
        for prefix in ('before/','payload/'):
            with self.subTest(prefix=prefix),self.scope_fixture() as f:
                (f.bundle/(prefix+self.SELECTED[0])).write_bytes(b'tampered software bytes')
                with self.assertRaisesRegex(ValueError,'git_payload_changed'):
                    self.prepare_stage(f)
                self.assertFalse((f.root/'stage').exists())

    def test_selected_unchanged_dependency_cannot_change_during_prepare(self):
        with self.scope_fixture() as f:
            original=prepare.file_metadata
            target=release.SOFTWARE_TARGETS[self.SELECTED[-1]]
            seen=[]
            def race(base,root,path,absent=False):
                if path==target:
                    seen.append(True)
                    if len(seen)==2:base.rooted(root,path).write_bytes(b'concurrent dependency update')
                return original(base,root,path,absent)
            with patch.object(prepare,'file_metadata',side_effect=race), \
                    self.assertRaisesRegex(ValueError,'runtime_source_baseline_drift'):
                self.prepare_stage(f)
            self.assertFalse((f.root/'stage').exists())



    def assert_report_mapping(self, name):
        self.assertIn(name,prepare.SOFTWARE_SOURCES,'actual report source needs reviewed mapping')

    def test_native_report_new_module_install_and_original_rollback_removes_only_own_file(self):
        name='runtime/native_reports.py';self.assert_report_mapping(name)
        selected=(name,'runtime/report_method.py','runtime/fs_native_readonly.py')
        with patch.object(self,'SELECTED',selected),self.scope_fixture(new=(name,)) as f:
            self.assertIsNone(f.descriptor['installed_baseline']['files'][name])
            self.assertNotIn('before/'+name,f.descriptor['files'])
            stage,manifest=self.prepare_stage(f);raw=(stage/'approved-manifest.json').read_bytes()
            target=f.base.rooted(f.system,release.SOFTWARE_TARGETS[name])
            self.assertFalse(target.exists())
            with self.publisher(f,stage) as (base,module,fence,locks), \
                    patch.object(module,'software_restart'):
                result=base.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261106T050000Z',f.system)
                self.assertTrue(target.is_file())
                base.rollback(Path(result['backup']),prepare.digest(raw),f.system)
            self.assertFalse(target.exists())
            self.assertEqual(f.ledger.read_bytes(),b'preserve data and original IDs')

    def test_native_report_new_module_unexpected_existing_file_rejected_at_prepare(self):
        name='runtime/native_reports.py';self.assert_report_mapping(name)
        selected=(name,'runtime/report_method.py','runtime/fs_native_readonly.py')
        with patch.object(self,'SELECTED',selected),self.scope_fixture(new=(name,)) as f:
            target=f.base.rooted(f.system,release.SOFTWARE_TARGETS[name]);target.write_bytes(b'unexpected current software')
            with self.assertRaisesRegex(ValueError,'runtime_source_baseline_drift'):
                self.prepare_stage(f)
            self.assertFalse((f.root/'stage').exists())

    def test_native_report_new_module_appearance_after_prepare_is_cas_conflict(self):
        name='runtime/native_reports.py';self.assert_report_mapping(name)
        selected=(name,'runtime/report_method.py','runtime/fs_native_readonly.py')
        with patch.object(self,'SELECTED',selected),self.scope_fixture(new=(name,)) as f:
            stage,manifest=self.prepare_stage(f);raw=(stage/'approved-manifest.json').read_bytes()
            target=f.base.rooted(f.system,release.SOFTWARE_TARGETS[name]);target.write_bytes(b'appeared after prepare')
            with self.publisher(f,stage) as (base,module,fence,locks):
                with self.assertRaisesRegex(ValueError,'target baseline drift'):
                    base.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261106T060000Z',f.system)
            self.assertEqual(target.read_bytes(),b'appeared after prepare')

    def test_existing_software_cannot_be_declared_new(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaisesRegex(ValueError,'software_before_source'):
                prepare.pack(root,root/'bundle',self.AFTER,software_before={'runtime/conversation_service.py':None})
            self.assertFalse((root/'bundle').exists())

    def test_range_git_and_rendered_before_after_are_both_bound(self):
        name='http/range_api.py';self.assert_report_mapping(name)
        selected=(name,'runtime/report_method.py','runtime/fs_native_readonly.py')
        with patch.object(self,'SELECTED',selected),self.scope_fixture() as f:
            files=f.descriptor['files']
            before=b'# Git before range\nvalue = 1\n';after=b'# Git after range\nvalue = 2\n'
            for prefix,body in (('git-before/',before),('git-after/',after),('before/',before.replace(b'\n',b'\r\n')),('payload/',after.replace(b'\n',b'\r\n'))):
                self.assertEqual((f.bundle/(prefix+name)).read_bytes(),body)
                self.assertEqual(files[prefix+name],prepare.digest(body))
            # Ordinary source bytes have no blanket newline conversion.
            self.assertEqual((f.payload/'runtime/report_method.py').read_bytes(),b'reviewed Git software runtime/report_method.py\n')
            stage,manifest=self.prepare_stage(f)
            row=next(r for r in manifest['files'] if r['candidate']==name)
            self.assertEqual(row['beforeSha256'],prepare.digest(before.replace(b'\n',b'\r\n')))
            self.assertEqual(row['sha256'],prepare.digest(after.replace(b'\n',b'\r\n')))
            with self.publisher(f,stage) as (base,module,fence,locks):base.inspect(manifest,stage,f.system)

    def test_range_render_must_match_exact_git_source_not_descriptor_claim(self):
        name='http/range_api.py';self.assert_report_mapping(name)
        selected=(name,'runtime/report_method.py','runtime/fs_native_readonly.py')
        for prefix in ('git-before/','git-after/'):
            with self.subTest(prefix=prefix),patch.object(self,'SELECTED',selected),self.scope_fixture() as f:
                path=f.bundle/(prefix+name);path.write_bytes(b'wrong source\n')
                f.descriptor['files'][prefix+name]=prepare.digest(path.read_bytes())
                raw=json.dumps(f.descriptor).encode();(f.bundle/'payload-manifest.json').write_bytes(raw)
                f.packed['payload_sha256']=prepare.digest(raw)
                with self.assertRaisesRegex(ValueError,'software_render_source_drift'):
                    self.prepare_stage(f)
                self.assertFalse((f.root/'stage').exists())

    def test_native_knowledge_import_changes_restart_worker_and_restore_range(self):
        for name in ('runtime/conversation_knowledge.py','runtime/fs_native_knowledge.py'):
            self.assert_report_mapping(name)
            selected=(name,'runtime/report_method.py','runtime/fs_native_readonly.py')
            with self.subTest(name=name),patch.object(self,'SELECTED',selected),self.scope_fixture() as f:
                stage,manifest=self.prepare_stage(f);raw=(stage/'approved-manifest.json').read_bytes();scopes=[]
                with self.publisher(f,stage) as (base,module,fence,locks), \
                        patch.object(module,'software_restart',side_effect=lambda b,r,m,a:scopes.append(m['scope'])):
                    base.apply(manifest,stage,prepare.digest(raw),raw,'nav-20261106T070000Z',f.system)
                self.assertEqual(scopes,[base.HERMES_WORKER_SCOPE,base.DEEP_SCOPE])


class NativePublisher(unittest.TestCase):
    def test_plain_stream_uses_current_051f_and_two_range_consumers(self):
        prepare.configure_native_capabilities()
        self.assertEqual(release.INSTALLED_COMMIT,'051f784d65b239f572cd40b319b0e1c71cad0644')
        self.assertEqual((len(release.TARGETS),len(release.NEW)),(32,0))
        self.assertEqual(release.CAPABILITIES_CHANGED,('runtime/conversation_service.py','http/conversation_http.py'))
        self.assertEqual(release.DESKTOP_EXISTING['runtime/conversation_desktop.py'],('6a24b2ab18bad8223e659d1f7559c42a0c8ae4b07ff7850d30a9504ddfb8fd6d',14795))
        self.assertEqual(release.DESKTOP_EXISTING['desktop/desktop_fs_gateway.py'],('f46e88384555b919c8660ca16e0684bc9b477ab5b5adb443d0bd52b8d3a84bfc',10350))

    def test_native_retry_fixed_before_boundary(self):
        prepare.configure_native_capabilities()
        name='runtime/proxy_gateway.py'
        body=self.diagnostic_current_bytes(name)
        self.assertEqual((prepare.digest(body),len(body)),('31c13a1b2ca439e873f4f0c4a450156766d43b6c15338b7745fe3c8e444030e7',44180))
        transport=self.diagnostic_current_bytes('runtime/transport.py')
        self.assertEqual(prepare.digest(transport),'88350c09814b61b7bdcd2abe6f117a5754190bd753299ab6701aeef75f312c76')
        path=Path(__file__).with_name('retry-before-befa.json');original=Path.read_bytes
        fixture=json.loads(original(path))
        for field,value in (('sha256','0'*64),('bytes',len(body)+1),('blob','0'*40),('source','wrong'),('utf8',body.decode()+'# after cannot be before')):
            bad=deepcopy(fixture);bad['files'][name][field]=value
            raw=json.dumps(bad).encode()
            with self.subTest(field=field),patch.object(Path,'read_bytes',lambda p:raw if p==path else original(p)):
                with self.assertRaises(AssertionError):self.diagnostic_current_bytes(name)
        bad=deepcopy(fixture);bad['source_commit']='0'*40;raw=json.dumps(bad).encode()
        with patch.object(Path,'read_bytes',lambda p:raw if p==path else original(p)):
            with self.assertRaises(AssertionError):self.diagnostic_current_bytes(name)

    def test_plain_stream_restart_does_not_restart_unchanged_Desktop(self):
        prepare.configure_native_capabilities()
        with self.desktop_restart_fixture(100,candidates=('runtime/conversation_service.py','http/conversation_http.py')) as f:
            f.call()
            f.fence.stop_then_unlock_database.assert_called_once()
            f.guards.assert_called_once()
            self.assertEqual([c[0] for c in f.calls],['range'])
            self.assertEqual(f.clock.now,0)

    def test_desktop_control_history_and_current_plain_stream_consumers(self):
        prepare.configure_native_capabilities()
        self.assertEqual(release.INSTALLED_COMMIT,'051f784d65b239f572cd40b319b0e1c71cad0644')
        self.assertEqual((len(release.TARGETS),len(release.NEW)),(32,0))
        self.assertEqual(release.CAPABILITIES_CHANGED,('runtime/conversation_service.py','http/conversation_http.py'))
        self.assertNotIn('runtime/proxy_gateway.py',release.CAPABILITIES_CHANGED)
        self.assertEqual(release.DESKTOP_EXISTING['runtime/conversation_desktop.py'],('6a24b2ab18bad8223e659d1f7559c42a0c8ae4b07ff7850d30a9504ddfb8fd6d',14795))
        self.assertEqual(release.DESKTOP_EXISTING['desktop/desktop_fs_gateway.py'],('f46e88384555b919c8660ca16e0684bc9b477ab5b5adb443d0bd52b8d3a84bfc',10350))

    def test_desktop_setup_history_and_control_current_success(self):
        prepare.configure_native_capabilities()
        self.assertEqual(release.INSTALLED_COMMIT,'051f784d65b239f572cd40b319b0e1c71cad0644')
        self.assertEqual(release.NEW,frozenset())
        self.assertEqual(release.CAPABILITIES_CHANGED,('runtime/conversation_service.py','http/conversation_http.py'))
        self.assertEqual(release.DESKTOP_EXISTING['runtime/conversation_desktop.py'],('6a24b2ab18bad8223e659d1f7559c42a0c8ae4b07ff7850d30a9504ddfb8fd6d',14795))
        self.assertEqual(release.DESKTOP_EXISTING['desktop/desktop_fs_gateway.py'],('f46e88384555b919c8660ca16e0684bc9b477ab5b5adb443d0bd52b8d3a84bfc',10350))

    def test_desktop_time_history_and_setup_current_success(self):
        prepare.configure_native_capabilities()
        self.assertEqual(release.INSTALLED_COMMIT,'051f784d65b239f572cd40b319b0e1c71cad0644')
        self.assertEqual(release.NEW,frozenset())
        self.assertEqual(release.CAPABILITIES_CHANGED,('runtime/conversation_service.py','http/conversation_http.py'))
        self.assertEqual(release.DESKTOP_EXISTING['desktop/desktop_fs_gateway.py'],('f46e88384555b919c8660ca16e0684bc9b477ab5b5adb443d0bd52b8d3a84bfc',10350))

    def test_desktop_WS_history_keeps_first_install_and_fixed_gateway(self):
        prepare.configure_native_capabilities()
        self.assertEqual(release.NEW,frozenset())
        self.assertEqual(len(release.TARGETS),32)
        self.assertEqual(release.INSTALLED_COMMIT,'051f784d65b239f572cd40b319b0e1c71cad0644')
        self.assertEqual(release.DESKTOP_FIRST_INSTALLED_EXISTING['desktop/desktop_fs_gateway.py'][0],'2409a854791293e1329098b071577e792595bb02ce4b2f19eef2d9745ba105fa')
        self.assertEqual(release.DESKTOP_EXISTING['desktop/desktop_fs_gateway.py'][0],'f46e88384555b919c8660ca16e0684bc9b477ab5b5adb443d0bd52b8d3a84bfc')
        self.assertEqual(release.CAPABILITIES_DESKTOP_INSTALL_PROOF['manifestSha256'],'10c15f738dac42fe58a0c6e335669d5ff3f245c72e8db7b99a83274c09552a2b')
        self.assertEqual(release.CAPABILITIES_DESKTOP_INSTALL_PROOF['journalSha256'],'333cfdb381e30ccb3156d21d0004cf8d0e10990c4d68ecc94cf5f4c6a2864e9a')

    def desktop_atomic_fixture(self, base, root, approved):
        import ast
        original=base.atomic;calls=[]
        def write(path,payload,mode=0o644):
            calls.append((path,payload,mode));return original(path,payload,mode)
        node=next(n for n in ast.walk(ast.parse(Path(release.__file__).read_bytes())) if isinstance(n,ast.FunctionDef) and n.name=='atomic')
        namespace=dict(base=base,publish_root=root,approved=approved,original_atomic=write,
            hashlib=__import__('hashlib'),DESKTOP_CONFIG=release.DESKTOP_CONFIG,NATIVE_CAPABILITIES_MODE=True)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'actual-publisher-atomic','exec'),namespace)
        return namespace['atomic'],calls

    def test_desktop_NEW_binding_is_private_and_original_rollback_removes_it(self):
        prepare.configure_native_capabilities();base=release.frozen()
        if os.name=='nt':base.directory_sync=lambda *args:None
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);backup=root/'backup';backup.mkdir();rows=[]
            for name,target in release.TARGETS.items():
                payload=('synthetic:'+name).encode();before=None if name in release.DESKTOP_ORIGINAL_NEW else prepare.digest(payload)
                row=dict(candidate=name,target=target,beforeSha256=before,sha256=prepare.digest(payload),owner='0:0',mode=release.payload_mode(target));rows.append(row)
                if before is not None:
                    base.atomic(base.rooted(root,target),payload,0o644)
                    base.atomic(backup/'files'/name,payload,0o600)
            approved=dict(schemaVersion=1,scope=release.SCOPE,nativeCapabilities=True,nativeArchive=True,files=rows)
            atomic,calls=self.desktop_atomic_fixture(base,root,approved)
            row=next(r for r in rows if r['target']==release.DESKTOP_CONFIG);payload=('synthetic:'+row['candidate']).encode();target=base.rooted(root,release.DESKTOP_CONFIG)
            atomic(target,payload,0o644)
            self.assertEqual(calls[-1][2],0o600)
            self.assertEqual(target.read_bytes(),payload)
            # Windows cannot express Unix0600; Linux CI asserts the actual inode mode.
            if os.name=='posix':self.assertEqual(stat.S_IMODE(os.stat(target).st_mode),0o600)
            raw=json.dumps(approved).encode();sha=prepare.digest(raw);base.atomic(backup/'approved-manifest.json',raw,0o600)
            journal=dict(manifest=approved,approvedManifestSha256=sha,files=[dict(r,beforeMode=0o644,intent=r['target']==release.DESKTOP_CONFIG,written=r['target']==release.DESKTOP_CONFIG) for r in rows])
            base.atomic=atomic;base.rollback_journal(backup,journal,root)
            self.assertFalse(target.exists());self.assertEqual(journal['status'],'rolled-back')
            self.assertEqual((backup/'removed-new-files'/row['candidate']).read_bytes(),payload)

    def test_desktop_private_mode_exception_does_not_change_other_atomic_contracts(self):
        prepare.configure_native_capabilities();base=release.frozen()
        if os.name=='nt':base.directory_sync=lambda *args:None
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);payload=b'approved synthetic binding'
            row=dict(candidate='desktop/fs-principal.json',target=release.DESKTOP_CONFIG,beforeSha256=None,sha256=prepare.digest(payload),owner='0:0',mode='0o600')
            approved=dict(nativeCapabilities=True,nativeArchive=True,files=[row]);target=base.rooted(root,release.DESKTOP_CONFIG)
            atomic,calls=self.desktop_atomic_fixture(base,root,approved)
            atomic(target,payload,0o600);self.assertEqual(calls[-1][2],0o600)
            calls.clear();prior=target.read_bytes()
            with self.assertRaisesRegex(ValueError,'desktop_binding_payload_drift'):atomic(target,b'wrong bytes',0o644)
            self.assertEqual(calls,[]);self.assertEqual(target.read_bytes(),prior)
            other=root/'other-target';atomic(other,payload,0o644);self.assertEqual(calls[-1][2],0o644)
            for changed in (dict(approved,nativeCapabilities=False),dict(approved,files=[dict(row,beforeSha256='a'*64)]),dict(approved,files=[dict(row,owner='9876:9876')]),dict(approved,files=[dict(row,mode='0o644')])):
                method,observed=self.desktop_atomic_fixture(base,root,changed);method(target,payload,0o640)
                self.assertEqual(observed[-1][2],0o640)
                if os.name=='posix':self.assertEqual(stat.S_IMODE(os.stat(target).st_mode),0o640)

    @contextmanager
    def desktop_restart_fixture(self, ready_at, *, installed='after', import_error=None, candidates=None):
        import ast
        clock=SimpleNamespace(now=0.0);calls=[]
        def sleep(seconds):clock.now+=seconds
        timer=SimpleNamespace(monotonic=lambda:clock.now,sleep=sleep)
        def connect(address,timeout):
            self.assertEqual(address,('127.0.0.1',8942));self.assertGreater(timeout,0)
            calls.append(('connect',clock.now,timeout))
            if clock.now<ready_at:raise ConnectionRefusedError('synthetic listener not ready')
            return nullcontext()
        def run(command,**kwargs):
            calls.append(('run',command,kwargs))
            if command[0]=='docker':
                if 'socket.create_connection' in command[-1]:
                    # The old exact Docker program attempted its one socket
                    # immediately; only the final process boundary is a fixture.
                    try:connect(('127.0.0.1',8942),timeout=5)
                    except OSError:raise subprocess.CalledProcessError(1,['synthetic-old-readiness']) from None
                    if import_error=='exit':raise subprocess.CalledProcessError(1,['synthetic-import'])
                    if import_error=='timeout':raise subprocess.TimeoutExpired(['synthetic-import'],kwargs['timeout'])
                else:
                    self.assertGreaterEqual(clock.now,ready_at)
                    self.assertIn('import conversation_desktop,desktop_fs_gateway',command[-1])
                    self.assertGreater(kwargs['timeout'],0);self.assertLessEqual(kwargs['timeout'],25-clock.now)
                    if import_error=='exit':raise subprocess.CalledProcessError(1,['synthetic-import'])
                    if import_error=='timeout':raise subprocess.TimeoutExpired(['synthetic-import'],kwargs['timeout'])
            return SimpleNamespace(returncode=0)
        process=SimpleNamespace(run=run,CalledProcessError=subprocess.CalledProcessError,TimeoutExpired=subprocess.TimeoutExpired)
        checked=Mock()
        namespace=dict(Path=Path,publish_root=Path('/'),time=timer,subprocess=process,
            readiness=SimpleNamespace(restart_with_hermes_readiness=lambda *args:calls.append(('range',))),original_restart=None,
            base=SimpleNamespace(DEEP_SCOPE='fixture-range',rooted=lambda root,path:Path(path),digest=lambda path:installed,guards=checked),
            running_worker=Mock(),native_runtime_readiness=Mock(),desktop_readiness=getattr(release,'desktop_readiness',None),DESKTOP_TARGETS=release.DESKTOP_TARGETS)
        source=ast.parse(Path(release.__file__).read_bytes())
        restart=next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='restart')
        factory=ast.parse('def factory():\n before_restart=True\n return None\n').body[0]
        factory.body.insert(1,restart);factory.body[-1]=ast.Return(value=ast.Name(id='restart',ctx=ast.Load()))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[factory],type_ignores=[])),'actual-desktop-restart','exec'),namespace)
        manifest=dict(nativeCapabilities=True,files=[dict(candidate='desktop/serve.py',target='/fixture/serve.py',sha256='after',beforeSha256='before')])
        if candidates is not None:manifest['files']=[dict(candidate=n,target=release.TARGETS[n],sha256='after',beforeSha256='before') for n in candidates]
        fence=SimpleNamespace(stop_then_unlock_database=Mock())
        with patch.object(release,'time',timer,create=True),patch.object(release,'socket',SimpleNamespace(create_connection=connect),create=True),patch.object(release,'subprocess',process):
            yield SimpleNamespace(call=lambda:namespace['factory']()(manifest,fence),calls=calls,clock=clock,guards=checked,fence=fence)

    def test_desktop_restart_waits_listener_with_one_shared_budget_and_import(self):
        for installed,ready_at,error,expected in (
                ('after',6,None,None),('before',6,None,None),('after',100,None,'listener_not_ready'),
                ('after',0,'exit','import_failed'),('after',0,'timeout','import_failed')):
            with self.subTest(installed=installed,error=error,ready_at=ready_at),self.desktop_restart_fixture(ready_at,installed=installed,import_error=error) as f:
                if expected:
                    with self.assertRaisesRegex(ValueError,'^'+expected+'$'):f.call()
                    f.guards.assert_not_called()
                else:
                    f.call();f.guards.assert_called_once()
                f.fence.stop_then_unlock_database.assert_called_once()
                self.assertEqual(sum(c[0]=='range' for c in f.calls),1)
                commands=[c[1] for c in f.calls if c[0]=='run']
                self.assertEqual(sum(c==['systemctl','restart','fs-hermes-desktop.service'] for c in commands),1)
                self.assertFalse(any(c[:2]==['systemctl','start'] for c in commands))
                self.assertEqual(sum(c[0]=='docker' for c in commands),0 if installed=='before' or ready_at>25 else 1)
                self.assertLessEqual(f.clock.now,25)
                if not expected:self.assertGreaterEqual(f.clock.now,6)

    def test_desktop_payload_contains_both_consumers_and_exact_before_sources(self):
        prepare.configure_native_capabilities()
        self.assertEqual(len(release.TARGETS),32,'Desktop consumers/config must be in original complete payload')
        self.assertEqual(release.INSTALLED_COMMIT,'051f784d65b239f572cd40b319b0e1c71cad0644')
        self.assertEqual(release.TARGETS['runtime/conversation_desktop.py'],'/opt/fs-hermes-fc/conversation_desktop.py')
        self.assertEqual(release.TARGETS['desktop/conversation_desktop.py'],'/opt/fs-hermes-desktop/conversation_desktop.py')
        self.assertEqual(release.TARGETS['desktop/desktop_fs_gateway.py'],'/opt/fs-hermes-desktop/desktop_fs_gateway.py')
        self.assertEqual(release.TARGETS['desktop/serve.py'],'/opt/fs-hermes-desktop/serve.py')
        self.assertEqual(release.TARGETS['http/range_api.py'],'/opt/fs-exact-range-20261001/range_api.py')
        self.assertEqual(release.NEW,frozenset())
        self.assertEqual(len(release.DESKTOP_ORIGINAL_NEW),4)
        self.assertEqual(set(prepare.SOURCES),set(release.TARGETS))
        self.assertEqual(prepare.SOURCES['runtime/conversation_desktop.py'],prepare.SOURCES['desktop/conversation_desktop.py'])
        self.assertEqual(release.DESKTOP_INITIAL_EXISTING['http/range_api.py'],('08e22627230531e06c35e661302d6f23808e07a527bbff2485d6b174303a79a6',34129))
        self.assertEqual(release.DESKTOP_INITIAL_EXISTING['desktop/serve.py'],('8211079893a3afbfaa41a6a13c85a325a49329a03006cfb0e473d839f417da30',1346))

    def test_native_knowledge_payload_closes_actual_imports_and_keeps_existing_helpers(self):
        prepare.configure_native_capabilities()
        self.assertEqual((len(release.TARGETS),len(release.NEW)),(32,0))
        self.assertEqual(release.INSTALLED_COMMIT,'051f784d65b239f572cd40b319b0e1c71cad0644')
        self.assertEqual(release.NEW,frozenset(set(release.DESKTOP_TARGETS)-set(release.DESKTOP_EXISTING)))
        self.assertEqual(release.CAPABILITIES_CHANGED,('runtime/conversation_service.py','http/conversation_http.py'))
        self.assertEqual(prepare.SOURCES['runtime/report_artifacts.py'],
            'releases/fs-dashboard/hermes-data-workspace-20261018/source/report_artifacts.py')
        self.assertEqual(prepare.SOURCES['runtime/fs_native_knowledge.py'],
            'releases/fs-dashboard/hermes-server-unify-20261022/fs_readonly/knowledge.py')
        self.assertEqual(set(release.KNOWLEDGE_INITIAL_EXISTING),{
            'runtime/knowledge_catalog.py','runtime/report_artifacts.py','runtime/reviewed_skills.py'})
        self.assertEqual(set(prepare.SOURCES),set(release.TARGETS))
        # Import the exact closed bundle, not the older pilot report fixture.
        names=('knowledge_catalog','report_artifacts','reviewed_skills','fs_native_knowledge','conversation_knowledge')
        modules={}
        with patch.dict(sys.modules):
            for name in names:
                path=Path(__file__).resolve().parents[4]/prepare.SOURCES['runtime/'+name+'.py']
                spec=importlib.util.spec_from_file_location(name,path)
                module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);modules[name]=module
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);path=root/'private-pin.json'
                modules['report_artifacts'].write_file(path,b'bound receipt')
                self.assertEqual(path.read_bytes(),b'bound receipt')
                formal=root/'formal';folder=formal/'knowledge-releases/fixed';folder.mkdir(parents=True)
                (folder/'rule.md').write_bytes(b'closed bundle rule')
                row=dict(id='fs.rule',revision='v1',layer='current',status='effective',modules=['FS'],
                    effective_at='2026-11-04',owner='fixture',authority='git',supersedes=[],provenance=['offline_fixture'],
                    source=dict(path='rule.md',sha256=prepare.digest(b'closed bundle rule')))
                index=dict(contract='fs-knowledge-index-v1',release='closed-fixed',release_state='published',
                    source_commit='a'*40,source_root='knowledge-releases/fixed',entries=[row])
                raw=json.dumps(index).encode();(folder/'index.json').write_bytes(raw)
                info=dict(owner='fixture',session_id='closed-session',profile_name='fixture',platform='api_server')
                route=dict(owner='fixture',project='FS',channel='fs',task_types=['conversation'],
                    catalog='knowledge-releases/fixed/index.json',sha256=prepare.digest(raw),modules=['FS'],
                    baseline_compatibility=dict(mode='retain_full_baseline',sha256=row['source']['sha256']))
                (formal/'knowledge-load-policy.json').write_bytes(json.dumps(dict(contract='fs-knowledge-load-policy-v1',requests={},
                    task_routes=dict(enabled=True,routes=[route]))).encode())
                receipts=root/'private'
                adapter=modules['fs_native_knowledge'].NativeKnowledge(formal,receipt_root=receipts)
                pin=adapter.pin_fs_task(info,'closed-turn',authorize=lambda current,turn:current==info and turn=='closed-turn')
                self.assertEqual(adapter.load_task(info,'closed-turn','closed-turn',expected_sha256=pin['receipt_sha256']),pin)
                with adapter.activate_task(info,'closed-turn','closed-turn',pin_sha256=pin['receipt_sha256']):
                    result=adapter.call('fs_read_knowledge',{'modules':['FS']},session_id=info['session_id'],task_id='closed-turn')
                    self.assertEqual(result['entries'][0]['content'],'closed bundle rule')
                self.assertTrue(list((receipts/'knowledge/native').glob('use-*.json')))
                self.assertFalse((formal/'knowledge/native').exists())
            self.assertTrue(callable(modules['fs_native_knowledge'].NativeKnowledge.pin_fs_task))

    def test_desktop_source_bytes_config_and_existing_runtime_dependencies(self):
        prepare.configure_native_capabilities()
        before=self.desktop_before_bytes('http/range_api.py')
        self.assertEqual(prepare.payload_bytes('http/range_api.py',before.replace(b'\r\n',b'\n')),before)
        self.assertEqual(prepare.payload_bytes('runtime/conversation_store.py',b'a\nb\r\n'),b'a\nb\r\n')
        config=json.loads((Path(__file__).parent/'desktop-fs-principal.json').read_bytes())
        self.assertEqual(config,dict(principal='wulv',credential_file='/var/lib/fs-hermes-fc/profile/.desktop-management/token'))
        self.assertEqual(release.payload_mode(release.DESKTOP_CONFIG),'0o600')
        metadata=dict(st_dev=1,st_ino=2,st_size=64,st_mtime_ns=3,st_ctime_ns=4,st_nlink=1,st_uid=9876,st_gid=9876,st_mode=stat.S_IFREG|0o600)
        mounts=[dict(Destination='/desktop',Source='/opt/fs-hermes-desktop',RW=False,Type='bind'),
                dict(Destination='/profile',Source='/var/lib/fs-hermes-fc/profile',RW=True,Type='bind')]
        helpers=dict(source_sha256='14428aa34d4297b81f7dbeb7e8fe2abae0e205a3356d9e341eb22d457ae2e55f',official_helpers=True)
        def response(value):return SimpleNamespace(stdout=json.dumps(value)+'\n"host"\ntrue\n')
        with patch.object(release,'native_path_info',return_value=SimpleNamespace(**metadata)),patch.object(release.subprocess,'run') as run,patch.object(os,'open',side_effect=AssertionError('token_must_not_be_opened')):
            run.side_effect=[response(mounts),SimpleNamespace(stdout=json.dumps(helpers))]
            self.assertEqual(release.desktop_observation(release.frozen(),Path('/'))['helpers'],helpers)
            self.assertEqual(run.call_count,2)
            for bad in ([dict(mounts[0],RW=True),mounts[1]],mounts+[mounts[0]],mounts[:1]):
                run.side_effect=[response(bad)]
                with self.assertRaisesRegex(ValueError,'desktop_existing_mount_contract_drift'):release.desktop_observation(release.frozen(),Path('/'))
            with patch.object(release,'native_path_info',return_value=SimpleNamespace(**dict(metadata,st_mode=stat.S_IFREG|0o644))):
                with self.assertRaisesRegex(ValueError,'desktop_token_metadata_boundary'):release.desktop_observation(release.frozen(),Path('/'))

    @staticmethod
    def desktop_before_bytes(name):
        row=json.loads(Path(__file__).with_name('desktop-before-aad.json').read_bytes())['files'][name]
        body=row['utf8'].encode();assert (prepare.digest(body),len(body))==release.DESKTOP_INITIAL_EXISTING[name]
        return body

    @staticmethod
    def desktop_installed_bytes(name):
        fixture=json.loads(Path(__file__).with_name('desktop-before-1f-utf8.json').read_bytes())
        assert fixture['source_commit']=='1f09b5134747a4ca6bef2dca080e5e9036388e5e'
        row=fixture['files'][name];body=row['utf8'].encode()
        assert (prepare.digest(body),len(body))==release.DESKTOP_FIRST_INSTALLED_EXISTING[name]
        return body

    @staticmethod
    def setup_installed_bytes(name):
        fixture=json.loads(Path(__file__).with_name('desktop-before-3522.json').read_bytes())
        assert fixture['source_commit']=='3522fa5d969c3bd88880de0032548b3af97ec14f'
        row=fixture['files'][name];body=row['utf8'].encode('utf8')
        assert (prepare.digest(body),len(body))==(row['sha256'],row['bytes'])
        expected={'runtime/conversation_desktop.py':('c4624b1449cf979bb9ff1129d7f8310df6f371904b3a1be6e7b3d9a5d707f7c5',11453),
                  'runtime/conversation_service.py':('5db2436dc5fb903444e8d2d95eb73c06451a18f1381fadd037c216527c590c51',38935)}
        assert (prepare.digest(body),len(body))==expected[name] and row['source']==prepare.SOURCES[name]
        return body

    @staticmethod
    def control_installed_bytes(name):
        fixture=json.loads(Path(__file__).with_name('desktop-before-679.json').read_bytes())
        assert fixture['source_commit']=='67906a53259155a0df43a334e4c0d1270dd46f9b'
        row=fixture['files'][name];body=row['utf8'].encode('utf8')
        expected={'runtime/conversation_desktop.py':('6c4d0ba68acca499e8d10ce109fc5fb333fd6986f1dd9fbbff4889dd26d802f3',14438),
                  'runtime/conversation_service.py':('80fdbae538933026fde0185642283ffe12cef34a1a674a38b8d40dfb7c69ad2f',38989)}
        assert (prepare.digest(body),len(body))==expected[name]==(row['sha256'],row['bytes']) and row['source']==prepare.SOURCES[name]
        return body

    @staticmethod
    def diagnostic_installed_bytes(name):
        fixture=json.loads(Path(__file__).with_name('diagnostic-before-119e.json').read_bytes())
        assert fixture['source_commit']=='119e960a23cbe98255cce592795d7b5eb1f302d8'
        row=fixture['files'][name];body=row['utf8'].encode('utf8')
        expected={'runtime/transport.py':('434621a025d0805c6bf0d6e221877e670517d1355dbeb63965f9c2a5edb71dcd',20924),
                  'runtime/proxy_gateway.py':('d26b108fad9835ace0acaff5ec9124277921c4f406807c731bf29d1625636a33',42846)}
        assert (prepare.digest(body),len(body))==expected[name]==(row['sha256'],row['bytes']) and row['source']==prepare.SOURCES[name]
        return body

    @staticmethod
    def diagnostic_current_bytes(name):
        if name=='runtime/proxy_gateway.py':
            fixture=json.loads(Path(__file__).with_name('retry-before-befa.json').read_bytes())
            assert fixture['source_commit']=='befa7cd8b4ccf8fa46221710831ec12d4371b294' and set(fixture['files'])=={name}
            row=fixture['files'][name];body=row['utf8'].encode('utf-8')
            assert row['source']==prepare.SOURCES[name] and row['blob']=='055d3d098a47af7149215a76daf4fc0637525701'
            assert (prepare.digest(body),len(body))==(row['sha256'],row['bytes'])==('31c13a1b2ca439e873f4f0c4a450156766d43b6c15338b7745fe3c8e444030e7',44180)
        else:
            assert name=='runtime/transport.py'
            body=(Path(__file__).resolve().parents[4]/prepare.SOURCES[name]).read_bytes()
            assert (prepare.digest(body),len(body))==('88350c09814b61b7bdcd2abe6f117a5754190bd753299ab6701aeef75f312c76',21373)
        return body

    @staticmethod
    def plain_reply_installed_bytes(name):
        expected={
            'runtime/conversation_service.py':('releases/fc-coins/fc-pricing-v3-20261026/source/conversation_service.py','80fdbae538933026fde0185642283ffe12cef34a1a674a38b8d40dfb7c69ad2f',38989,'b49488b50bb33191424ecf698ab7b0e61457c386'),
            'http/conversation_http.py':('releases/fs-dashboard/hermes-conversation-20261018/source/conversation_http.py','8d577e8493cabc2847604ab77e7539bb215c947cee842000acc86878bc2ba44d',13570,'e1b5943db3b49214f09fe107df367ce81f885b8b')}
        fixture=json.loads(Path(__file__).with_name('plain-reply-before-051f.json').read_bytes())
        assert set(fixture)=={'source_commit','files'}
        assert fixture['source_commit']=='051f784d65b239f572cd40b319b0e1c71cad0644' and set(fixture['files'])==set(expected)
        row=fixture['files'][name];body=row['utf8'].encode('utf-8')
        assert set(row)=={'source','bytes','sha256','blob','utf8'}
        assert (row['source'],row['sha256'],row['bytes'],row['blob'])==expected[name]
        assert row['source']==prepare.SOURCES[name]
        assert (prepare.digest(body),len(body))==(row['sha256'],row['bytes'])
        assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()==row['blob']
        return body

    def test_plain_stream_fixed_before_boundary(self):
        prepare.configure_native_capabilities()
        path=Path(__file__).with_name('plain-reply-before-051f.json');original=Path.read_bytes
        fixture=json.loads(original(path))
        for name in ('runtime/conversation_service.py','http/conversation_http.py'):
            body=self.plain_reply_installed_bytes(name)
            after=(Path(__file__).resolve().parents[4]/prepare.SOURCES[name]).read_bytes()
            # The installed before stays frozen; later reviewed source is not before.
            self.assertNotEqual(prepare.digest(after),prepare.digest(body))
            for field,value in (('sha256','0'*64),('bytes',len(body)+1),('blob','0'*40),('source','wrong'),('utf8',after.decode())):
                bad=deepcopy(fixture);bad['files'][name][field]=value
                raw=json.dumps(bad).encode()
                with self.subTest(name=name,field=field),patch.object(Path,'read_bytes',lambda p:raw if p==path else original(p)):
                    with self.assertRaises(AssertionError):self.plain_reply_installed_bytes(name)
            bad=deepcopy(fixture);bad['source_commit']='0'*40;raw=json.dumps(bad).encode()
            with patch.object(Path,'read_bytes',lambda p:raw if p==path else original(p)):
                with self.assertRaises(AssertionError):self.plain_reply_installed_bytes(name)

    @staticmethod
    def desktop_current_bytes(name):
        if name in ('runtime/conversation_desktop.py','desktop/conversation_desktop.py','desktop/desktop_fs_gateway.py'):
            # These sources are unchanged by this host-only patch. Their fixed119e
            # hashes reject later drift; changed proxy/transport use frozen before bytes.
            body=(Path(__file__).resolve().parents[4]/prepare.SOURCES[name]).read_bytes()
        else:body=NativePublisher.desktop_installed_bytes(name)
        assert (prepare.digest(body),len(body))==release.DESKTOP_EXISTING[name]
        return body

    @staticmethod
    def knowledge_before_bytes(name):
        fixture=json.loads(Path(__file__).with_name('knowledge-before-193.json').read_bytes())
        if name in fixture['files']:
            row=fixture['files'][name];body=row['utf8'].encode('utf-8')
            if name=='runtime/knowledge_catalog.py':
                assert row['source_commit']=='1a1a42d81107c204fac699ccb69dd223deca33b3' and row['transform']=='CRLF_to_LF'
            else:assert row['source_commit']=='193223331dd2516ad211a9366f860d6fbebaefc2'
            assert len(body)==row['bytes'] and prepare.digest(body)==row['sha256']
            expected={**release.KNOWLEDGE_INITIAL_EXISTING,
                'runtime/conversation_native.py':('de968283f4928199d21bd623a4d7f39b7bfa1dc534b2548c515467817a3399f3',56701),
                'runtime/hermes_worker.py':('51fda7e6f282628a32c3d12fb05fda5491b9137ccbc6bd9995d725b098a0b5cc',46881)}
            assert (prepare.digest(body),len(body))==expected[name] and row['source']==prepare.SOURCES[name]
            return body
        raise AssertionError('frozen_knowledge_before_required')

    def test_native_knowledge_existing_helper_before_boundary(self):
        prepare.configure_native_capabilities();base=release.frozen()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owners={};kinds={}
            with self.native_metadata(owners,kinds,root=root):
                for name,(expected,size) in release.DESKTOP_EXISTING.items():
                    path=base.rooted(root,release.TARGETS[name]);path.parent.mkdir(parents=True,exist_ok=True)
                    body=self.desktop_current_bytes(name);self.assertEqual((prepare.digest(body),len(body)),(expected,size))
                    path.write_bytes(body);owners[path]=(0,0,int(release.payload_mode(release.TARGETS[name]),8))
                    self.assertEqual(prepare.file_metadata(base,root,release.TARGETS[name])['sha256'],expected)
                    for changed in (body+b'x',b'x'+body[1:]):
                        path.write_bytes(changed)
                        with self.assertRaises(ValueError):prepare.file_metadata(base,root,release.TARGETS[name])
                    path.write_bytes(body);owners[path]=(0,0,0o666)
                    with self.assertRaises(ValueError):prepare.file_metadata(base,root,release.TARGETS[name])
                    owners[path]=(0,0,int(release.payload_mode(release.TARGETS[name]),8))
                    link=path.with_name(path.name+'.link');os.link(path,link)
                    with self.assertRaises(ValueError):prepare.file_metadata(base,root,release.TARGETS[name])
                    link.unlink()

    def test_composer_static_is_exact_existing_html_followup(self):
        self.assertTrue(callable(getattr(prepare, 'configure_native_composer_static', None)))
        prepare.configure_native_composer_static()
        self.assertEqual(release.TARGETS, {'frontend/index.html':'/var/www/dashboard/fs-home/hermes/conversation/index.html'})
        self.assertEqual(release.NEW, frozenset())
        self.assertEqual(release.INSTALLED_COMMIT, '20c481384fcd746ccb6b122c7fe57f3d6185c51f')
        self.assertEqual(release.INSTALLED_PROOF['manifestSha256'], '2f2cfcb5fac5aa9dc2ae910f25eb0ad83fa0c91e72f331cc9fe6f559593497e6')
        self.assertFalse(release.ARCHIVE_MODE or release.NATIVE_CAPABILITIES_MODE or release.NATIVE_MODE)

    @contextmanager
    def composer_fixture(self, root):
        base=release.frozen()
        paths=release.protected_paths(base) | set(release.TARGETS.values()) | set(release.CAPABILITIES_INSTALLED_TARGETS.values())
        paths.add(release.ARCHIVE_USAGE_LEDGER)
        for i in range(779-len(paths)):paths.add('/opt/synthetic-protected/'+str(i)+'.py')
        prepare.configure_native_composer_static()
        system=root/'system';owners={};kinds={}
        for path in paths:
            file=base.rooted(system,path);file.parent.mkdir(parents=True,exist_ok=True)
            file.write_bytes(('synthetic:'+path).encode())
            owners[file]=(0,0,0o600 if path in (release.NGINX,release.ARCHIVE_USAGE_LEDGER) else 0o644)
        target=base.rooted(system,release.TARGETS['frontend/index.html'])
        html=(prepare.HERE.parent/'frontend/index.html').read_text('utf-8').encode('utf-8')
        target.write_bytes(html.replace(b'rows="3"',b'rows="3" maxlength="4000"',1))
        self.assertEqual(base.digest(target),release.COMPOSER_BEFORE_SHA)
        def row(path):
            return dict(path=path,sha256=base.digest(base.rooted(system,path)),owner='0:0',mode=oct(owners[base.rooted(system,path)][2]))
        previous={'sourceCommit':release.INSTALLED_COMMIT,'scope':release.SCOPE,'nativeCapabilities':True,'nativeArchive':True,
            'files':[dict(candidate=n,target=p,sha256=row(p)['sha256'],beforeSha256='0'*64,owner='0:0',mode='0o644') for n,p in release.CAPABILITIES_INSTALLED_TARGETS.items()],
            'unchangedRequired':[row(p) for p in sorted(paths-set(release.CAPABILITIES_INSTALLED_TARGETS.values()))]}
        proof=dict(release.INSTALLED_PROOF);backup=base.rooted(system,proof['backup']);backup.mkdir(parents=True)
        def save_proof():
            raw=json.dumps(previous).encode();(backup/'approved-manifest.json').write_bytes(raw);proof['manifestSha256']=prepare.digest(raw)
            journal={'manifest':previous,'approvedManifestSha256':proof['manifestSha256'],'status':'applied-awaiting-actual-http-role-acceptance',
                'files':[dict(r,intent=True,written=True) for r in previous['files']]}
            raw=json.dumps(journal).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
        save_proof()
        for name in ('approved-manifest.json','journal.json'):owners[backup/name]=(0,0,0o600)
        bundle=root/'bundle';payload=bundle/'payload';(payload/'frontend').mkdir(parents=True)
        (payload/'frontend/index.html').write_bytes(html)
        for name,source in prepare.PUBLISHER_SOURCES.items():
            repo=Path(__file__).resolve().parents[4]
            (bundle/name).write_bytes((repo/source).read_bytes())
        descriptor={'source_commit':'a'*40,'native_composer_static':True,'material_execution':False,
            'installed_baseline':{'source_commit':release.INSTALLED_COMMIT,'files':{'frontend/index.html':release.COMPOSER_BEFORE_SHA}},
            'files':{p.relative_to(bundle).as_posix():prepare.digest(p.read_bytes()) for p in bundle.rglob('*') if p.is_file()}}
        def save_descriptor():
            raw=json.dumps(descriptor).encode();(bundle/'payload-manifest.json').write_bytes(raw);return raw
        with self.native_metadata(owners,kinds,root=system),patch.object(release,'INSTALLED_PROOF',proof),patch.object(prepare,'INSTALLED_PROOF',proof):
            yield SimpleNamespace(base=base,system=system,payload=payload,previous=previous,proof=proof,owners=owners,kinds=kinds,
                descriptor=descriptor,save_descriptor=save_descriptor,save_proof=save_proof,target=target,usage=base.rooted(system,release.ARCHIVE_USAGE_LEDGER))

    def test_composer_static_prepare_and_CAS_rejections(self):
        with tempfile.TemporaryDirectory() as directory,self.composer_fixture(Path(directory)) as f:
            root=Path(directory);raw=f.save_descriptor();f.usage.write_bytes(b'fresh dynamic usage')
            prepare.prepare(f.payload,root/'stage','a'*40,prepare.digest(raw),root=f.system,followup=True,release_ready=True)
            manifest=json.loads((root/'stage/approved-manifest.json').read_bytes())
            self.assertEqual((len(manifest['files']),len(manifest['unchangedRequired'])),(1,778))
            self.assertTrue(manifest['materialStaticOnly']);self.assertTrue(manifest['nativeComposerStatic'])
            self.assertFalse(any(manifest.get(k) for k in ('nativeArchive','nativeCapabilities','nativeChat','materialExecution')))
            self.assertEqual(next(r['sha256'] for r in manifest['unchangedRequired'] if r['path']==release.ARCHIVE_USAGE_LEDGER),f.base.digest(f.usage))
            for case in ('missing_marker','mixed','execution','old_git','git_hash','extra','zero','static','mode','owner','link','usage_mode','proof','proof_duplicate'):
                saved=deepcopy(f.descriptor);old_previous=deepcopy(f.previous);restore=None;owner=None
                if case=='missing_marker':del f.descriptor['native_composer_static']
                elif case=='mixed':f.descriptor['native_capabilities']=True
                elif case=='execution':f.descriptor['material_execution']=True
                elif case=='old_git':f.descriptor['installed_baseline']['source_commit']='1f8ddc57c37e16df7c802de358eefb6585d078ee'
                elif case=='git_hash':f.descriptor['installed_baseline']['files']['frontend/index.html']='0'*64
                elif case=='extra':f.descriptor['files']['payload/frontend/extra.html']='0'*64
                elif case in ('mode','owner','usage_mode'):
                    owner=f.usage if case=='usage_mode' else f.base.rooted(f.system,manifest['unchangedRequired'][0]['path'])
                    old_owner=f.owners[owner];f.owners[owner]=(9876,0,old_owner[2]) if case=='owner' else (0,0,0o664)
                elif case=='link':f.kinds[f.target.parent]=stat.S_IFLNK
                elif case=='proof':f.previous['sourceCommit']='0'*40;f.save_proof()
                elif case=='proof_duplicate':f.previous['unchangedRequired'].append(deepcopy(f.previous['unchangedRequired'][0]));f.save_proof()
                else:
                    p=f.payload/'frontend/index.html' if case=='zero' else f.base.rooted(f.system,manifest['unchangedRequired'][0]['path'])
                    restore=(p,p.read_bytes());p.write_bytes(f.target.read_bytes() if case=='zero' else b'static drift')
                    if case=='zero':f.descriptor['files']['payload/frontend/index.html']=f.base.digest(p)
                bad=f.save_descriptor()
                with self.subTest(case=case),self.assertRaises(ValueError):prepare.prepare(f.payload,root/('bad-'+case),'a'*40,prepare.digest(bad),root=f.system,followup=True)
                self.assertFalse((root/('bad-'+case)).exists())
                f.descriptor.clear();f.descriptor.update(saved);f.previous.clear();f.previous.update(old_previous);f.save_proof()
                if restore:restore[0].write_bytes(restore[1])
                if owner:f.owners[owner]=old_owner
                f.kinds.clear()

    def test_composer_static_original_inspect_apply_rollback_no_service_actions(self):
        for failure in (False,True):
            self.tearDown();self.setUp()
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory,self.composer_fixture(Path(directory)) as f:
                root=Path(directory);raw=f.save_descriptor();f.usage.write_bytes(b'fresh usage')
                stage=root/'stage';prepare.prepare(f.payload,stage,'a'*40,prepare.digest(raw),root=f.system,followup=True,release_ready=True)
                manifest_raw=(stage/'approved-manifest.json').read_bytes();manifest=json.loads(manifest_raw)
                untouched={r['path']:(f.base.rooted(f.system,r['path']).read_bytes(),f.base.rooted(f.system,r['path']).stat()) for r in manifest['unchangedRequired']}
                spec=importlib.util.spec_from_file_location('composer_static_publisher',stage/'runtime_release.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                module.configure_native_composer_static();module.INSTALLED_PROOF=f.proof
                base=f.base;base.retirement=Mock()
                base.locks=base.live_lock=base.model_release_lock=lambda *a:nullcontext()
                fence=SimpleNamespace(modified=False,confirmed=False,stop_then_unlock_database=Mock())
                base.hermes_admission_fence=lambda *a:nullcontext(fence)
                service=Mock();base.restart_for=service
                if os.name=='nt':base.directory_sync=lambda *a:None
                with patch.object(module,'frozen',return_value=base),patch.object(module,'running_worker'),patch.object(module,'worker_image',return_value=release.FROZEN_IMAGE_MARKER),patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='ActiveState=active\n')) as commands:
                    publisher=module.load_base();publisher.inspect(manifest,stage,f.system)
                    duplicate=deepcopy(manifest);duplicate['unchangedRequired'][-1]=deepcopy(duplicate['unchangedRequired'][0])
                    with self.assertRaisesRegex(ValueError,'exact_material_manifest_required'):publisher.guards(duplicate,f.system)
                    f.usage.write_bytes(b'after prepare change')
                    with self.assertRaisesRegex(ValueError,'archive_usage_cas_drift'):publisher.inspect(manifest,stage,f.system)
                    f.usage.write_bytes(b'fresh usage');untouched[release.ARCHIVE_USAGE_LEDGER]=(f.usage.read_bytes(),f.usage.stat())
                    parent=f.target.parent;f.owners[parent]=(9876,0,0o755)
                    with self.assertRaisesRegex(ValueError,'unsafe daily source boundary'):publisher.inspect(manifest,stage,f.system)
                    f.owners.pop(parent)
                    original_atomic=publisher.atomic;active_writes=[]
                    def atomic(path,data,mode=0o644):
                        if path==f.target:
                            active_writes.append(prepare.digest(data))
                            if failure and len(active_writes)==1:
                                original_atomic(path,data,mode);raise RuntimeError('synthetic after-rename failure')
                        return original_atomic(path,data,mode)
                    publisher.atomic=atomic
                    release_id='nav-20261103T010000Z'
                    if failure:
                        with self.assertRaisesRegex(RuntimeError,'after-rename'):publisher.apply(manifest,stage,prepare.digest(manifest_raw),manifest_raw,release_id,f.system)
                    else:
                        publisher.apply(manifest,stage,prepare.digest(manifest_raw),manifest_raw,release_id,f.system)
                        self.assertEqual(base.digest(f.target),release.COMPOSER_AFTER_SHA)
                        publisher.rollback(base.rooted(f.system,'/var/backups/fs-navigation-20261006/'+release_id),prepare.digest(manifest_raw),f.system)
                    self.assertEqual(base.digest(f.target),release.COMPOSER_BEFORE_SHA)
                    self.assertEqual(active_writes,[release.COMPOSER_AFTER_SHA,release.COMPOSER_BEFORE_SHA])
                    service.assert_not_called();fence.stop_then_unlock_database.assert_not_called()
                    self.assertTrue(all(c.args[0][:2]==['systemctl','show'] for c in commands.call_args_list))
                    for path,(data,info) in untouched.items():
                        p=base.rooted(f.system,path);now=p.stat()
                        self.assertEqual(p.read_bytes(),data)
                        self.assertEqual((now.st_uid,now.st_gid,now.st_mode,now.st_size,now.st_ino,now.st_mtime_ns),(info.st_uid,info.st_gid,info.st_mode,info.st_size,info.st_ino,info.st_mtime_ns))

    def test_composer_static_busy_databases_never_opened_and_original_file_locks_retained(self):
        with tempfile.TemporaryDirectory() as directory,self.composer_fixture(Path(directory)) as f:
            root=Path(directory);base=f.base
            databases={
                '/var/lib/fs-hermes-fc/fs/tasks.sqlite3':('CREATE TABLE requests(state);INSERT INTO requests VALUES("DISPATCH_UNKNOWN");CREATE TABLE tasks(state);INSERT INTO tasks VALUES("RUNNING");CREATE TABLE learning_events(state);INSERT INTO learning_events VALUES("unknown");'),
                '/var/lib/fs-hermes-fc/fs/conversations/conversations.db':('CREATE TABLE turns(state);INSERT INTO turns VALUES("running");'),
                '/var/lib/fs-hermes-fc/fs/pricing-reviews/conversations.db':('CREATE TABLE turns(state);INSERT INTO turns VALUES("dispatch_unknown");'),
                '/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db':('CREATE TABLE scan_jobs(state);INSERT INTO scan_jobs VALUES("pending");CREATE TABLE milestones(state);INSERT INTO milestones VALUES("claimed");'),
                '/var/lib/fs-business-ranges/advisor/advisor.sqlite3':('CREATE TABLE jobs(state);INSERT INTO jobs VALUES("running");'),
                '/var/lib/fs-business-ranges/fc-daily/daily.sqlite3':('CREATE TABLE jobs(state);INSERT INTO jobs VALUES("pending");')}
            for name,sql in databases.items():
                p=base.rooted(f.system,name);p.parent.mkdir(parents=True,exist_ok=True)
                with closing(sqlite3.connect(p)) as db:db.executescript(sql);db.commit()
            for name in ('/var/www/dashboard/fs-home/transactions/collector.lock','/var/lib/fs-hermes-fc/fs/admission.lock','/var/lib/fs-business-ranges/fc-daily/provider.lock'):
                p=base.rooted(f.system,name);p.parent.mkdir(parents=True,exist_ok=True);p.touch();p.chmod(0o600)
                f.owners[p]=(0,0,0o600)  # Project the real lock mode, not the default code-file0644.
            raw=f.save_descriptor();stage=root/'stage'
            prepare.prepare(f.payload,stage,'a'*40,prepare.digest(raw),root=f.system,followup=True,release_ready=True)
            manifest_raw=(stage/'approved-manifest.json').read_bytes();manifest=json.loads(manifest_raw)
            spec=importlib.util.spec_from_file_location('composer_static_busy',stage/'runtime_release.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            module.configure_native_composer_static();module.INSTALLED_PROOF=f.proof
            if os.name=='nt':
                # Only flock is a Windows fixture. Every original lock/context,
                # SQL admission consumer, filesystem writer and guard runs.
                lock_module=SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=Mock())
            else:import fcntl as lock_module
            with patch.dict(sys.modules,{'fcntl':lock_module}),ExitStack() as platform:
                # Root identity is the existing synthetic filesystem contract on
                # both platforms; keep native_metadata's path/FD projection.
                platform.enter_context(patch.object(os,'geteuid',return_value=0,create=True))
                # Runtime publishers retain their actual active-task/report refusals.
                with self.assertRaisesRegex(ValueError,'active or unreconciled Hermes task'):base.guards(manifest,f.system)
                with self.assertRaisesRegex(ValueError,'active or unreconciled Hermes task'):
                    with base.hermes_admission_fence(manifest,f.system):pass
                with self.assertRaisesRegex(ValueError,'active report'):
                    with base.model_release_lock(manifest,f.system):pass
                with self.assertRaisesRegex(ValueError,'active_or_unknown_material_task'):release.quiescent(base,f.system)
                preserved=[base.rooted(f.system,n) for n in databases]+[base.rooted(f.system,r['path']) for r in manifest['unchangedRequired']]
                before={p:(p.read_bytes(),p.stat()) for p in preserved}
                base.retirement=Mock()  # Retired systemd masks are an OS fixture, not task admission.
                if os.name=='nt':base.directory_sync=lambda *a:None
                with patch.object(module,'frozen',return_value=base),patch.object(module,'running_worker'),patch.object(module,'worker_image',return_value=release.FROZEN_IMAGE_MARKER),patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='ActiveState=active\n')) as commands,patch.object(sqlite3,'connect',wraps=sqlite3.connect) as connections,patch.object(lock_module,'flock',wraps=lock_module.flock) as locks:
                    publisher=module.load_base()
                    for gate in (publisher.hermes_admission_fence,publisher.model_release_lock):
                        with self.assertRaisesRegex(ValueError,'exact_material_manifest_required'):
                            gate(dict(manifest,nativeCapabilities=True),f.system)
                    publisher.inspect(manifest,stage,f.system)
                    publisher.apply(manifest,stage,prepare.digest(manifest_raw),manifest_raw,'nav-20261103T010001Z',f.system)
                    self.assertEqual(base.digest(f.target),release.COMPOSER_AFTER_SHA)
                    publisher.rollback(base.rooted(f.system,'/var/backups/fs-navigation-20261006/nav-20261103T010001Z'),prepare.digest(manifest_raw),f.system)
                    self.assertEqual(base.digest(f.target),release.COMPOSER_BEFORE_SHA)
                    connections.assert_not_called()
                    self.assertEqual(locks.call_count,6)  # original two publisher locks + collector, apply and rollback
                    self.assertTrue(all(c.args[0][:2]==['systemctl','show'] for c in commands.call_args_list))
                for p,(data,info) in before.items():
                    now=p.stat();self.assertEqual(p.read_bytes(),data)
                    self.assertEqual((now.st_uid,now.st_gid,now.st_mode,now.st_size,now.st_ino,now.st_mtime_ns),(info.st_uid,info.st_gid,info.st_mode,info.st_size,info.st_ino,info.st_mtime_ns))

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
        opened_metadata={};original_fstat=os.fstat
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
            if os.name=='nt':result['st_ctime_ns']=info.st_mtime_ns
            opened_metadata[(info.st_dev,info.st_ino)]=(uid,gid,mode)
            return SimpleNamespace(**result)
        def fd_metadata(fd):
            # The same synthetic identity must describe the opened inode, too.
            # Keep real identity/link/timestamp fields so production race checks run.
            info=original_fstat(fd);identity=opened_metadata.get((info.st_dev,info.st_ino))
            if identity is None:return info
            uid,gid,mode=identity
            result={key:getattr(info,key) for key in dir(info) if key.startswith('st_')}
            result.update(st_mode=stat.S_IFMT(info.st_mode)|mode,st_uid=uid,st_gid=gid)
            # Windows ChangeTime can refresh on handle open. This identity fixture
            # supplies Linux-style stable ctime; the explicit drift case below
            # still executes and requires the production ctime comparison.
            if os.name=='nt':result['st_ctime_ns']=info.st_mtime_ns
            return SimpleNamespace(**result)
        def kind(path, check, follow):
            try:return check(metadata(path,follow_symlinks=follow).st_mode)
            except FileNotFoundError:return False
        with patch.object(os,'fstat',fd_metadata),patch.object(Path,'stat',lambda path,**kw:metadata(path,**kw)), patch.object(Path,'lstat',lambda path:metadata(path,follow_symlinks=False)), patch.object(Path,'is_file',lambda path:kind(path,stat.S_ISREG,True)), patch.object(Path,'is_symlink',lambda path:kind(path,stat.S_ISLNK,False)):
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

    def archive_fc_fixture(self, root, base, before, owners):
        # Independent, already-applied FC release: only these three static paths.
        targets={
            'source/fc_pricing_v3/sources.py':'/opt/fc27-cloud-browser/fc_pricing_v3/sources.py',
            'source/hermes-copy/fc_pricing_v3/sources.py':'/opt/fs-hermes-fc/fc_pricing_v3/sources.py',
            'source/server_quote_job.py':'/opt/fc27-cloud-browser/server_quote_job.py'}
        rows=[];expected={}
        for name,target in targets.items():
            path=base.rooted(root,target);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(('applied FC:'+name).encode());owners[path]=(0,0,0o644)
            sha=base.digest(path);expected[name]=(target,sha)
            rows.append(dict(candidate=name,target=target,sha256=sha,beforeSha256=before[target],owner='0:0',mode='0o644'))
        manifest=dict(sourceCommit='6d395242b88ca634c5745181e16f1fec6053c065',scope='fc-pricing-v3-collection-routing-20261102',
                      releaseReady=True,businessWrites=False,timersChanged=False,files=rows)
        proof=dict(sourceCommit=manifest['sourceCommit'],backup='/var/backups/fs-navigation-20261006/nav-20261102T175000Z')
        backup=base.rooted(root,proof['backup']);backup.mkdir(parents=True)
        raw=json.dumps(manifest).encode();(backup/'approved-manifest.json').write_bytes(raw);proof['manifestSha256']=prepare.digest(raw)
        journal=dict(status='applied-awaiting-actual-http-role-acceptance',manifest=manifest,approvedManifestSha256=proof['manifestSha256'],
                     files=[dict(row,intent=True,written=True,beforeMode=0o644) for row in rows])
        raw=json.dumps(journal).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
        for name in ('approved-manifest.json','journal.json'):owners[backup/name]=(0,0,0o600)
        return proof,expected

    def test_archive_fc_overlay_requires_exact_success_and_boundaries(self):
        prepare.configure_native_archive()
        paths=('/opt/fc27-cloud-browser/fc_pricing_v3/sources.py',
               '/opt/fs-hermes-fc/fc_pricing_v3/sources.py','/opt/fc27-cloud-browser/server_quote_job.py')
        before={p:prepare.digest(('old:'+p).encode()) for p in paths}
        before['/opt/other-static.py']='a'*64
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=release.frozen();owners={};kinds={}
            proof,expected=self.archive_fc_fixture(root,base,before,owners)
            backup=base.rooted(root,proof['backup']);mp=backup/'approved-manifest.json';jp=backup/'journal.json'
            original_m=json.loads(mp.read_bytes());original_j=json.loads(jp.read_bytes())
            cases={
                'source':lambda m,j:m.update(sourceCommit='0'*40),
                'scope':lambda m,j:m.update(scope='unrelated'),
                'missing':lambda m,j:m['files'].pop(),
                'extra':lambda m,j:m['files'].append(deepcopy(m['files'][0])),
                'duplicate':lambda m,j:m['files'].__setitem__(1,deepcopy(m['files'][0])),
                'target':lambda m,j:m['files'][0].update(target='/opt/other-static.py'),
                'after':lambda m,j:m['files'][0].update(sha256='b'*64),
                'before':lambda m,j:m['files'][0].update(beforeSha256='b'*64),
                'owner':lambda m,j:m['files'][0].update(owner='9876:9876'),
                'mode':lambda m,j:m['files'][0].update(mode='0o600'),
                'status':lambda m,j:j.update(status='rolled-back'),
                'failure':lambda m,j:j.update(failure='synthetic failure'),
                'written':lambda m,j:j['files'][0].update(written=False),
                'intent':lambda m,j:j['files'][0].update(intent=False),
                'beforeMode':lambda m,j:j['files'][0].update(beforeMode=0o600),
                'rollback':lambda m,j:j['files'][0].update(rollbackIntent=True),
                'rolledBack':lambda m,j:j['files'][0].update(rolledBack=True),
                'journal_target':lambda m,j:j['files'][0].update(target='/opt/other-static.py'),
                'journal_missing':lambda m,j:j['files'].pop()}
            with self.native_metadata(owners,kinds,root=root),patch.object(release,'ARCHIVE_FC_FILES',expected):
                for drift,change in [(None,None),*cases.items()]:
                    m=deepcopy(original_m);j=deepcopy(original_j)
                    if change:change(m,j)
                    raw=json.dumps(m).encode();mp.write_bytes(raw)
                    pinned=dict(proof,manifestSha256=prepare.digest(raw))
                    j.update(manifest=m,approvedManifestSha256=pinned['manifestSha256'])
                    raw=json.dumps(j).encode();jp.write_bytes(raw);pinned['journalSha256']=prepare.digest(raw)
                    with self.subTest(drift=drift),patch.object(release,'ARCHIVE_FC_PROOF',pinned):
                        if drift:
                            with self.assertRaises(ValueError):release.archive_fc_baseline(base,root,before)
                        else:
                            merged=release.archive_fc_baseline(base,root,before)
                            self.assertEqual(merged,{**before,**{target:sha for target,sha in expected.values()}})
                mp.write_bytes(json.dumps(original_m).encode());jp.write_bytes(json.dumps(original_j).encode())
                with patch.object(release,'ARCHIVE_FC_PROOF',proof):
                    for path in (mp,jp):
                        saved=path.read_bytes();path.write_bytes(saved+b' ')
                        with self.assertRaisesRegex(ValueError,'archive_fc_proof_drift'):release.archive_fc_baseline(base,root,before)
                        path.write_bytes(saved)
                    for path,code in ((mp,'archive_fc_proof_boundary_drift'),(jp,'archive_fc_proof_boundary_drift'),(base.rooted(root,paths[0]),'archive_fc_target_boundary_drift')):
                        saved=owners[path]
                        for metadata in ((9876,0,saved[2]),(0,9876,saved[2]),(0,0,0o666)):
                            owners[path]=metadata
                            with self.assertRaisesRegex(ValueError,code):release.archive_fc_baseline(base,root,before)
                        owners[path]=saved;kinds[path]=stat.S_IFLNK
                        with self.assertRaises(ValueError):release.archive_fc_baseline(base,root,before)
                        kinds.clear()
                        alias=path.with_name(path.name+'.hardlink');os.link(path,alias)
                        with self.assertRaisesRegex(ValueError,code):release.archive_fc_baseline(base,root,before)
                        alias.unlink()
                    parent=mp.parent;kinds[parent]=stat.S_IFLNK
                    with self.assertRaises(ValueError):release.archive_fc_baseline(base,root,before)
                    kinds.clear()
                    self.assertEqual(before[paths[0]],original_m['files'][0]['beforeSha256'])
                    self.assertEqual(release.archive_fc_baseline(base,root,before)['/opt/other-static.py'],'a'*64)

    def test_native_capabilities_installed_followup(self):
        self.assertTrue(callable(getattr(prepare,'configure_native_capabilities',None)))
        prepare.configure_native_capabilities()
        self.assertEqual((len(release.TARGETS),len(release.NEW)),(32,0))
        self.assertEqual(release.INSTALLED_COMMIT,'051f784d65b239f572cd40b319b0e1c71cad0644')
        self.assertEqual(release.CAPABILITIES_CHANGED,('runtime/conversation_service.py','http/conversation_http.py'))
        self.assertEqual(release.INSTALLED_PROOF,dict(sourceCommit=release.INSTALLED_COMMIT,
            backup='/var/backups/fs-navigation-20261006/nav-20261104T130137Z',
            manifestSha256='ae4ea179bf0ce107f4487e5dc87c618f13769e9c035bef6bce44754ed5bbde5f',
            journalSha256='2e6cdffd9316b6f4d4ee778c3248fc4c120cc567245db08f41bdd25a69e51534'))
        self.assertEqual(release.CAPABILITIES_STATIC_PROOF['sourceCommit'],'d135d2b965ecdfc2d96a1e49cf9425e31eaca07e')
        self.assertEqual(set(prepare.SOURCES),set(release.CAPABILITIES_TARGETS))
        self.assertEqual(prepare.SOURCES['http/conversation_http.py'],prepare.MODULE+'source/conversation_http.py')
        self.assertNotIn('unit/native-control.conf',release.TARGETS)

    def test_native_capabilities_navigation_successful_six_path_chain(self):
        self.assertTrue(callable(getattr(release,'capabilities_navigation_overlay',None)),
                        'current six protected publication transitions are not consumed')
        prepare.configure_native_capabilities();base=release.frozen()
        first={}
        for _,_,_,_,changes in release.CAPABILITIES_NAVIGATION_PROOFS:
            for alias,(_,before,_) in changes.items():first.setdefault(alias,before)
        metadata={p:dict(path=p,sha256=first[a],owner='0:0',mode='0o600' if p==release.NGINX else '0o644')
                  for a,p in release.CAPABILITIES_NAVIGATION_TARGETS.items()}
        metadata['/opt/unrelated.py']=dict(path='/opt/unrelated.py',sha256='f'*64,owner='0:0',mode='0o644')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owners={};kinds={}
            with self.native_metadata(owners,kinds,root=root),self.capabilities_navigation_fixture(root,base,metadata,owners) as f:
                expected=f.after;original=deepcopy(metadata)
                self.assertEqual(release.capabilities_navigation_overlay(base,root,metadata),expected)
                self.assertEqual(metadata,original)
                self.assertEqual(expected['/opt/unrelated.py'],metadata['/opt/unrelated.py'])
                for alias,path in release.CAPABILITIES_NAVIGATION_TARGETS.items():
                    if alias=='range':continue
                    with patch.dict(release.TARGETS,{'unapproved/'+alias:path}),self.assertRaisesRegex(ValueError,'native_navigation_baseline_drift'):
                        release.capabilities_navigation_overlay(base,root,metadata)
                with patch.dict(release.TARGETS,{'http/range_api.py':'/opt/other-range.py'}),self.assertRaisesRegex(ValueError,'native_navigation_baseline_drift'):
                    release.capabilities_navigation_overlay(base,root,metadata)
                actual_fstat=os.fstat
                def changed_ctime(fd):
                    info=actual_fstat(fd)
                    fields={k:getattr(info,k) for k in dir(info) if k.startswith('st_')}
                    fields['st_ctime_ns']+=1
                    return SimpleNamespace(**fields)
                with patch.object(os,'fstat',changed_ctime),self.assertRaisesRegex(ValueError,'native_navigation_proof_changed'):
                    release.capabilities_navigation_overlay(base,root,metadata)
                for index in range(len(release.CAPABILITIES_NAVIGATION_PROOFS)):
                    record=f.records[index];mp,jp=record['paths']
                    raw=mp.read_bytes();mp.write_bytes(raw+b' ')
                    with self.assertRaises(ValueError):release.capabilities_navigation_overlay(base,root,metadata)
                    mp.write_bytes(raw)
                    for key,value in (('status','prepared'),('failure','synthetic'),('rollbackAttempted',True)):
                        bad=deepcopy(record['journal']);bad[key]=value;f.save(index,journal=bad)
                        with self.subTest(index=index,key=key),self.assertRaises(ValueError):release.capabilities_navigation_overlay(base,root,metadata)
                        f.save(index)
                    for field,value in (('written',False),('intent',False),('beforeMode',0o777),('rollbackIntent',True)):
                        bad=deepcopy(record['journal']);bad['files'][0][field]=value;f.save(index,journal=bad)
                        with self.subTest(index=index,field=field),self.assertRaises(ValueError):release.capabilities_navigation_overlay(base,root,metadata)
                        f.save(index)
                    for field,value in (('target','/opt/unapproved.py'),('beforeSha256','0'*64),('sha256','0'*64)):
                        bad=deepcopy(record['manifest']);bad['files'][0][field]=value;f.save(index,manifest=bad)
                        with self.subTest(index=index,field=field),self.assertRaises(ValueError):release.capabilities_navigation_overlay(base,root,metadata)
                        f.save(index)
                last=len(f.records)-1;extra=deepcopy(f.records[last]['manifest'])
                extra['files'].append(dict(candidate='unimported-range.py',target=release.CAPABILITIES_NAVIGATION_TARGETS['range'],beforeSha256='b'*64,sha256='c'*64))
                f.save(last,manifest=extra)
                self.assertEqual(release.capabilities_navigation_overlay(base,root,metadata),expected)
                f.save(last)
                mp=f.records[0]['paths'][0]
                for values in ((9876,0,0o600),(0,0,0o644)):
                    owners[mp]=values
                    with self.assertRaisesRegex(ValueError,'native_navigation_proof_boundary_drift'):release.capabilities_navigation_overlay(base,root,metadata)
                owners[mp]=(0,0,0o600)
                alias=mp.with_name('hardlink');os.link(mp,alias)
                with self.assertRaises(ValueError):release.capabilities_navigation_overlay(base,root,metadata)
                alias.unlink();kinds[mp.parent]=stat.S_IFLNK
                with self.assertRaises(ValueError):release.capabilities_navigation_overlay(base,root,metadata)
                kinds.clear()
                for field,value in (('owner','9876:9876'),('mode','0o644'),('sha256','0'*64)):
                    bad=deepcopy(metadata);bad[release.NGINX][field]=value
                    with self.assertRaises(ValueError):release.capabilities_navigation_overlay(base,root,bad)

    @contextmanager
    def capabilities_navigation_fixture(self,root,base,metadata,owners,materialize=False,range_body=None):
        proofs=deepcopy(release.CAPABILITIES_NAVIGATION_PROOFS);working=deepcopy(metadata);records=[];bodies={}
        proofs=list(proofs)
        for index,(rid,_,_,scope,changes) in enumerate(proofs):
            changes=dict(changes);rows=[]
            for alias,(candidate,before,after) in changes.items():
                target=release.CAPABILITIES_NAVIGATION_TARGETS[alias]
                if materialize:
                    before=working[target]['sha256'];bodies[target]=('synthetic '+rid+' '+alias).encode();after=prepare.digest(bodies[target])
                    if alias=='range' and range_body is not None:
                        bodies[target]=range_body;after=prepare.digest(range_body)
                    changes[alias]=(candidate,before,after)
                rows.append(dict(candidate=candidate,target=target,beforeSha256=before,sha256=after))
                working[target]=dict(working[target],sha256=after)
            manifest=dict(scope=scope,releaseReady=True,files=rows)
            journal=dict(status='applied-awaiting-actual-http-role-acceptance',files=[dict(r,intent=True,written=True,
                beforeMode=0o600 if r['target']==release.NGINX else 0o644) for r in rows])
            backup=base.rooted(root,'/var/backups/fs-navigation-20261006/'+rid);backup.mkdir(parents=True)
            paths=[backup/'approved-manifest.json',backup/'journal.json']
            for p in paths:owners[p]=(0,0,0o600)
            records.append(dict(manifest=manifest,journal=journal,paths=paths))
            proofs[index]=(rid,'','',scope,changes)
        def save(index,manifest=None,journal=None):
            record=records[index];m=deepcopy(record['manifest'] if manifest is None else manifest)
            raw=json.dumps(m).encode();record['paths'][0].write_bytes(raw);mh=prepare.digest(raw)
            j=deepcopy(record['journal'] if journal is None else journal)
            if manifest is not None and journal is None:
                j['files']=[dict(r,intent=True,written=True,beforeMode=0o600 if r['target']==release.NGINX else 0o644) for r in m['files']]
            j.update(manifest=m,approvedManifestSha256=mh)
            raw=json.dumps(j).encode();record['paths'][1].write_bytes(raw)
            rid,_,_,scope,changes=proofs[index];proofs[index]=(rid,mh,prepare.digest(raw),scope,changes)
        for index in range(len(proofs)):save(index)
        if materialize:
            for target,body in bodies.items():
                p=base.rooted(root,target);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
                owners[p]=(0,0,0o600 if target==release.NGINX else 0o644)
        with patch.object(release,'CAPABILITIES_NAVIGATION_PROOFS',proofs):
            yield SimpleNamespace(proofs=proofs,records=records,save=save,after=working)

    @contextmanager
    def capabilities_nginx_fixture(self, root, base, *, before=None, after=None):
        proof=deepcopy(release.CAPABILITIES_NGINX_PROOF)
        if before is not None:proof['beforeSha256']=before
        if after is not None:proof['sha256']=after
        backup=base.rooted(root,proof['backup']);backup.mkdir(parents=True)
        name=Path(proof['backup']).name
        row=dict(candidate='candidate/formal.conf',target=release.NGINX,beforeSha256=proof['beforeSha256'],sha256=proof['sha256'])
        page=dict(candidate='assets/game-monitor/index.html',target='/var/lib/fs-navigation-formal-static/'+name+'/game-monitor/index.html',sha256=proof['pageSha256'])
        manifest=dict(releaseId=name,releaseReady=True,scope='Hermes authorized data-only game-monitor content maintenance',targets=[row],immutableAssets=[page],
                      unchangedRequired=[dict(path='/do-not-import-other-publisher-list',sha256='f'*64)])
        journal=dict(status='applied-awaiting-real-desktop-URL-QA',activationAttempted=True,files=[dict(row,mode=0o600,intent=True)])
        def save(m=manifest,j=journal):
            raw=json.dumps(m).encode();(backup/'approved-manifest.json').write_bytes(raw);proof['manifestSha256']=prepare.digest(raw)
            j=deepcopy(j);j.setdefault('manifest',m);j.setdefault('approvedManifestSha256',proof['manifestSha256'])
            raw=json.dumps(j).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
        metadata={release.NGINX:dict(path=release.NGINX,sha256=proof['sha256'],owner='0:0',mode='0o600'),
                  '/opt/other-protected.py':dict(path='/opt/other-protected.py',sha256='e'*64,owner='0:0',mode='0o644')}
        save()
        with patch.object(release,'CAPABILITIES_NGINX_PROOF',proof):
            yield SimpleNamespace(proof=proof,backup=backup,manifest=manifest,journal=journal,save=save,metadata=metadata)

    def test_native_capabilities_nginx_current_and_historical_proof(self):
        self.assertTrue(callable(getattr(release,'capabilities_nginx_overlay',None)), 'single successful native Nginx proof is not consumed')
        prepare.configure_native_capabilities();base=release.frozen()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owners={};kinds={}
            with self.native_metadata(owners,kinds,root=root),self.capabilities_nginx_fixture(root,base) as f:
                for path in f.backup.iterdir():owners[path]=(0,0,0o600)
                before=deepcopy(f.metadata)
                result=release.capabilities_nginx_overlay(base,root,f.metadata)
                self.assertEqual(result[release.NGINX]['sha256'],'fde65e277cbb873673b7dc474483dada42e0da558756c69c63c38d0acc769da4')
                self.assertEqual(f.metadata,before);self.assertEqual(result,before)
                self.assertEqual(result['/opt/other-protected.py'],before['/opt/other-protected.py'])
                self.assertNotIn('sourceCommit',f.manifest);self.assertNotIn('written',f.journal['files'][0])
                bad=deepcopy(before);bad[release.NGINX]['sha256']=f.proof['beforeSha256']
                for changed in (bad,dict(before,**{release.NGINX:dict(before[release.NGINX],owner='9876:9876')}),
                                dict(before,**{release.NGINX:dict(before[release.NGINX],mode='0o644')})):
                    with self.assertRaises(ValueError):release.capabilities_nginx_overlay(base,root,changed)
                for name in ('approved-manifest.json','journal.json'):
                    path=f.backup/name;saved=path.read_bytes();path.write_bytes(b'drift')
                    with self.assertRaisesRegex(ValueError,'native_nginx_proof_drift'):release.capabilities_nginx_overlay(base,root,before)
                    path.write_bytes(saved)
                    for identity in ((9876,0,0o600),(0,9876,0o600),(0,0,0o644)):
                        owners[path]=identity
                        with self.assertRaisesRegex(ValueError,'native_nginx_proof_boundary_drift'):release.capabilities_nginx_overlay(base,root,before)
                    owners[path]=(0,0,0o600)
                    alias=path.with_name(name+'.hardlink');os.link(path,alias)
                    with self.assertRaises(ValueError):release.capabilities_nginx_overlay(base,root,before)
                    alias.unlink();kinds[path.parent]=stat.S_IFLNK
                    with self.assertRaises(ValueError):release.capabilities_nginx_overlay(base,root,before)
                    kinds.clear()
                for case in ('scope','release','not_ready','duplicate_target','candidate','before','after','page','duplicate_page',
                             'status','activation','failure','rollback','row_rollback','intent','mode','binding','approved_sha','duplicate_journal'):
                    m=deepcopy(f.manifest);j=deepcopy(f.journal)
                    if case=='scope':m['scope']='different'
                    elif case=='release':m['releaseId']='different'
                    elif case=='not_ready':m['releaseReady']=False
                    elif case=='duplicate_target':m['targets'].append(deepcopy(m['targets'][0]))
                    elif case in ('candidate','before','after'):m['targets'][0][{'before':'beforeSha256','after':'sha256'}.get(case,case)]='wrong'
                    elif case=='page':m['immutableAssets'][0]['sha256']='0'*64
                    elif case=='duplicate_page':m['immutableAssets'].append(deepcopy(m['immutableAssets'][0]))
                    elif case=='status':j['status']='rolled-back-immutable-history-retained'
                    elif case=='activation':j['activationAttempted']=False
                    elif case=='failure':j['failure']='synthetic failure'
                    elif case=='rollback':j['rollbackIntent']=True
                    elif case=='row_rollback':j['files'][0]['rolledBack']=True
                    elif case=='intent':j['files'][0]['intent']=False
                    elif case=='mode':j['files'][0]['mode']=0o644
                    elif case=='binding':j['manifest']={}
                    elif case=='approved_sha':j['approvedManifestSha256']='0'*64
                    elif case=='duplicate_journal':j['files'].append(deepcopy(j['files'][0]))
                    f.save(m,j)
                    with self.subTest(case=case),self.assertRaises(ValueError):release.capabilities_nginx_overlay(base,root,before)
                f.save()
                original_open=os.open
                def change_before_open(path,*args,**kwargs):
                    fd=original_open(path,*args,**kwargs)
                    if Path(path)==f.backup/'approved-manifest.json':Path(path).write_bytes(b'changed after lstat')
                    return fd
                with patch.object(release.os,'open',side_effect=change_before_open),self.assertRaisesRegex(ValueError,'native_nginx_proof_changed'):
                    release.capabilities_nginx_overlay(base,root,before)
                with patch.object(release,'NATIVE_CAPABILITIES_MODE',False),self.assertRaises(ValueError):release.capabilities_nginx_overlay(base,root,before)

    def test_native_capabilities_current_nginx_is_in_installed_proof(self):
        prepare.configure_native_capabilities();base=release.frozen()
        source=release.INSTALLED_COMMIT
        nginx_sha='fde65e277cbb873673b7dc474483dada42e0da558756c69c63c38d0acc769da4'
        rows=[dict(candidate=n,target=p,beforeSha256='0'*64,sha256=prepare.digest(n.encode()),owner='0:0',mode='0o644') for n,p in release.CAPABILITIES_RUNTIME_TARGETS.items()]
        first={}
        for _,_,_,_,changes in release.CAPABILITIES_NAVIGATION_PROOFS:
            for alias,(_,before,_) in changes.items():first.setdefault(alias,before)
        protected=[dict(path=p,sha256=first[a],owner='0:0',mode='0o600' if p==release.NGINX else '0o644')
                   for a,p in release.CAPABILITIES_NAVIGATION_TARGETS.items()]
        for p,body in zip(self.shared_update_paths(),(b'old reviewed skill',b'{"old":"ledger"}\n',b'')):
            protected.append(dict(path=p,sha256=prepare.digest(body),owner='0:0',mode='0o644'))
        protected += [dict(path='/opt/static/'+str(i),sha256='a'*64,owner='0:0',mode='0o644') for i in range(758)]
        manifest=dict(sourceCommit=source,scope=release.SCOPE,nativeCapabilities=True,nativeArchive=True,
                      nativeStaticBaseline=release.CAPABILITIES_STATIC_PROOF,files=rows,unchangedRequired=protected)
        git=dict(source_commit=source,files={r['candidate']:r['sha256'] for r in rows})
        git['files'].update({n:v[0] for n,v in release.CAMPAIGN_BEFORE.items()});git['files'].update({n:None for n in release.NEW})
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);proof=deepcopy(release.INSTALLED_PROOF);owners={};kinds={}
            backup=base.rooted(root,proof['backup']);backup.mkdir(parents=True)
            def save(m,**changes):
                raw=json.dumps(m).encode();(backup/'approved-manifest.json').write_bytes(raw);proof['manifestSha256']=prepare.digest(raw)
                journal=dict(status='applied-awaiting-actual-http-role-acceptance',manifest=m,approvedManifestSha256=proof['manifestSha256'],files=[dict(r,intent=True,written=True) for r in m['files']])
                journal.update(changes);raw=json.dumps(journal).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
            with self.native_metadata(owners,kinds,root=root),self.capabilities_nginx_fixture(root,base) as historical,patch.object(release,'INSTALLED_PROOF',proof),self.capabilities_navigation_fixture(root,base,{r['path']:r for r in protected},owners) as navigation,self.shared_update_fixture(root,base,owners) as shared:
                history_manifest=deepcopy(manifest);history_manifest['sourceCommit']=release.CAPABILITIES_HISTORY_PROOF['sourceCommit']
                history=self.save_capabilities_receipt(base,root,release.CAPABILITIES_HISTORY_PROOF,history_manifest,owners)
                manifest['unchangedRequired']=[dict(navigation.after.get(r['path'],r)) for r in protected]
                manifest['unchangedRequired']=[dict(shared.after.get(r['path'],r)) for r in manifest['unchangedRequired']]
                previous_manifest=deepcopy(manifest);previous_manifest['sourceCommit']=release.CAPABILITIES_PREVIOUS_PROOF['sourceCommit']
                previous=self.save_capabilities_receipt(base,root,release.CAPABILITIES_PREVIOUS_PROOF,previous_manifest,owners)
                previous_patch=patch.object(release,'CAPABILITIES_PREVIOUS_PROOF',previous);previous_patch.start();self.addCleanup(previous_patch.stop)
                old_rows=deepcopy(rows)
                rows[:]=[dict(r,beforeSha256=r['sha256']) for r in old_rows]
                rows.extend(dict(candidate=n,target=p,beforeSha256=release.CAMPAIGN_INITIAL_BEFORE[n][0],
                    sha256=release.CAMPAIGN_BEFORE[n][0],owner='0:0',mode='0o644') for n,p in release.CAMPAIGN_TARGETS.items())
                old_service=json.loads(Path(__file__).with_name('campaign-before-698.json').read_bytes())['files']['campaign/backend/campaign_backend/services.py']['utf8'].encode()
                next(r for r in rows if r['candidate']=='campaign/backend/campaign_backend/services.py')['sha256']=prepare.digest(old_service)
                grant_history_manifest=deepcopy(manifest);grant_history_manifest['sourceCommit']=release.CAPABILITIES_GRANT_HISTORY_PROOF['sourceCommit']
                grant_history=self.save_capabilities_receipt(base,root,release.CAPABILITIES_GRANT_HISTORY_PROOF,grant_history_manifest,owners)
                grant_patch=patch.object(release,'CAPABILITIES_GRANT_HISTORY_PROOF',grant_history);grant_patch.start();self.addCleanup(grant_patch.stop)
                rows[:]=[dict(r,beforeSha256=r['sha256'],sha256=release.CAMPAIGN_BEFORE[r['candidate']][0] if r['candidate'] in release.CAMPAIGN_BEFORE else r['sha256']) for r in rows]
                grant='campaign/backend/campaign_backend/coupon_grant.py'
                rows.append(dict(candidate=grant,target=release.TARGETS[grant],beforeSha256=None,sha256=prepare.digest(self.campaign_before_bytes(grant)),owner='0:0',mode='0o644'))
                import_history_manifest=deepcopy(manifest);import_history_manifest['sourceCommit']=release.CAPABILITIES_IMPORT_HISTORY_PROOF['sourceCommit']
                import_history=self.save_capabilities_receipt(base,root,release.CAPABILITIES_IMPORT_HISTORY_PROOF,import_history_manifest,owners)
                import_patch=patch.object(release,'CAPABILITIES_IMPORT_HISTORY_PROOF',import_history);import_patch.start();self.addCleanup(import_patch.stop)
                rows[:]=[dict(r,beforeSha256=r['sha256']) for r in rows]
                next(r for r in rows if r['candidate']=='runtime/conversation_user_data.py')['sha256']=prepare.digest(b'installed import dependency')
                transport_manifest=deepcopy(manifest);transport_manifest['sourceCommit']=release.CAPABILITIES_TRANSPORT_HISTORY_PROOF['sourceCommit']
                transport=self.save_capabilities_receipt(base,root,release.CAPABILITIES_TRANSPORT_HISTORY_PROOF,transport_manifest,owners)
                transport_patch=patch.object(release,'CAPABILITIES_TRANSPORT_HISTORY_PROOF',transport);transport_patch.start();self.addCleanup(transport_patch.stop)
                rows[:]=[dict(r,beforeSha256=r['sha256']) for r in rows]
                next(r for r in rows if r['candidate']==grant)['sha256']=prepare.digest(b'installed direct channel grant')
                knowledge_manifest=deepcopy(manifest);knowledge_manifest['sourceCommit']=release.CAPABILITIES_KNOWLEDGE_HISTORY_PROOF['sourceCommit']
                knowledge=self.save_capabilities_receipt(base,root,release.CAPABILITIES_KNOWLEDGE_HISTORY_PROOF,knowledge_manifest,owners)
                knowledge_patch=patch.object(release,'CAPABILITIES_KNOWLEDGE_HISTORY_PROOF',knowledge);knowledge_patch.start();self.addCleanup(knowledge_patch.stop)
                rows[:]=[dict(r,beforeSha256=r['sha256']) for r in rows]
                rows.extend(dict(candidate=n,target=p,beforeSha256=release.KNOWLEDGE_INITIAL_EXISTING.get(n,(None,))[0],
                    sha256=prepare.digest(n.encode()),owner='0:0',mode='0o644') for n,p in release.KNOWLEDGE_INSTALLED_TARGETS.items()
                    if n not in release.CAPABILITIES_BASELINE_TARGETS)
                desktop_stack=ExitStack();self.addCleanup(desktop_stack.close)
                desktop=self.desktop_installed_fixture(base,root,manifest,owners,desktop_stack)
                manifest=desktop.manifest;rows=manifest['files'];proof.update(desktop.proof)
                git['files']={r['candidate']:r['sha256'] for r in rows}
                history_patch=patch.object(release,'CAPABILITIES_HISTORY_PROOF',history);history_patch.start();self.addCleanup(history_patch.stop)
                save(manifest)
                for path in historical.backup.iterdir():owners[path]=(0,0,0o600)
                for path in backup.iterdir():owners[path]=(0,0,0o600)
                with patch.object(release,'capabilities_desktop_metadata',wraps=release.capabilities_desktop_metadata) as supplement:
                    result=release.installed_baseline(root,git)
                self.assertEqual(supplement.call_count,1)
                self.assertEqual(supplement.call_args.args[2][release.NGINX]['sha256'],desktop.nav['beforeSha256'])
                self.assertEqual(next(r['sha256'] for r in manifest['unchangedRequired'] if r['path']==release.NGINX),desktop.nav['sha256'])
                expected={r['target']:r['sha256'] for r in rows};expected.update({r['path']:r['sha256'] for r in protected})
                expected.update({p:r['sha256'] for p,r in navigation.after.items()})
                expected.update({p:r['sha256'] for p,r in shared.after.items()})
                expected.update({release.CAMPAIGN_TARGETS[n]:v[0] for n,v in release.CAMPAIGN_BEFORE.items()})
                expected.update({release.TARGETS[n]:v[0] for n,v in release.DESKTOP_EXISTING.items()})
                expected[release.NGINX]=desktop.nav['sha256']
                self.assertEqual(result['archive_all_hashes'],expected)
                self.assertEqual(len(release.ARCHIVE_PROTECTED),766)
                self.assertTrue(historical.backup.is_dir())
                initial_journal=base.rooted(root,desktop.initial_proof['backup']+'/journal.json');saved_initial=initial_journal.read_bytes()
                for changes in ({'written':False},{'rollbackWritten':True}):
                    bad=json.loads(saved_initial);bad['files'][0].update(changes);raw=json.dumps(bad).encode();initial_journal.write_bytes(raw)
                    desktop.initial_proof['journalSha256']=prepare.digest(raw)
                    with self.assertRaisesRegex(ValueError,'native_desktop_history_success_required'):release.installed_baseline(root,git)
                initial_journal.write_bytes(saved_initial);desktop.initial_proof['journalSha256']=prepare.digest(saved_initial)
                # The added c1 history layer must retain all original receipt
                # success and before-chain checks, not just its hash pin.
                ws_journal=base.rooted(root,desktop.ws_proof['backup']+'/journal.json');saved_ws=ws_journal.read_bytes()
                for changes in ({'written':False},{'rollbackWritten':True}):
                    bad=json.loads(saved_ws);bad['files'][0].update(changes);raw=json.dumps(bad).encode();ws_journal.write_bytes(raw)
                    desktop.ws_proof['journalSha256']=prepare.digest(raw)
                    with self.assertRaisesRegex(ValueError,'native_desktop_history_success_required'):release.installed_baseline(root,git)
                ws_journal.write_bytes(saved_ws);desktop.ws_proof['journalSha256']=prepare.digest(saved_ws)
                transport_journal=base.rooted(root,transport['backup']+'/journal.json');saved_transport=transport_journal.read_bytes()
                for changes in ({'written':False},{'rollbackWritten':True}):
                    bad=json.loads(saved_transport);bad['files'][0].update(changes);raw=json.dumps(bad).encode()
                    transport_journal.write_bytes(raw);transport['journalSha256']=prepare.digest(raw)
                    with self.assertRaisesRegex(ValueError,'native_transport_history_success_required'):release.installed_baseline(root,git)
                transport_journal.write_bytes(saved_transport);transport['journalSha256']=prepare.digest(saved_transport)
                # Newly pinned 698 must still prove the exact original 36d7
                # transition and all its older native/navigation/approval guards.
                import_journal=base.rooted(root,import_history['backup']+'/journal.json');saved_import=import_journal.read_bytes()
                for changes in ({'written':False},{'rollbackWritten':True}):
                    bad=json.loads(saved_import);bad['files'][0].update(changes);raw=json.dumps(bad).encode()
                    import_journal.write_bytes(raw);import_history['journalSha256']=prepare.digest(raw)
                    with self.assertRaisesRegex(ValueError,'native_import_history_success_required'):release.installed_baseline(root,git)
                import_journal.write_bytes(saved_import);import_history['journalSha256']=prepare.digest(saved_import)
                grant_journal=base.rooted(root,grant_history['backup']+'/journal.json');saved_grant=grant_journal.read_bytes()
                for changes in ({'written':False},{'rollbackWritten':True}):
                    bad=json.loads(saved_grant);bad['files'][0].update(changes);raw=json.dumps(bad).encode()
                    grant_journal.write_bytes(raw);grant_history['journalSha256']=prepare.digest(raw)
                    with self.assertRaisesRegex(ValueError,'native_grant_history_success_required'):release.installed_baseline(root,git)
                grant_journal.write_bytes(saved_grant);grant_history['journalSha256']=prepare.digest(saved_grant)
                previous_journal=base.rooted(root,previous['backup']+'/journal.json')
                saved_previous=previous_journal.read_bytes()
                for changes in ({'written':False},{'rollbackWritten':True}):
                    bad=json.loads(saved_previous);bad['files'][0].update(changes);raw=json.dumps(bad).encode()
                    previous_journal.write_bytes(raw);previous['journalSha256']=prepare.digest(raw)
                    with self.assertRaisesRegex(ValueError,'native_campaign_history_success_required'):
                        release.installed_baseline(root,git)
                previous_journal.write_bytes(saved_previous);previous['journalSha256']=prepare.digest(saved_previous)
                for candidate in ('runtime/conversation_native.py','campaign/backend/campaign_backend/services.py'):
                    bad=deepcopy(manifest);next(r for r in bad['files'] if r['candidate']==candidate)['beforeSha256']='0'*64;save(bad)
                    with self.assertRaisesRegex(ValueError,'native_desktop_success_chain_mismatch'):release.installed_baseline(root,git)
                save(manifest)
                for field in ('sourceCommit','nativeStaticBaseline'):
                    bad=deepcopy(history_manifest);bad[field]='untrusted'
                    history.update(self.save_capabilities_receipt(base,root,history,bad,owners))
                    with self.assertRaisesRegex(ValueError,'native_history_success_required'):release.installed_baseline(root,git)
                history.update(self.save_capabilities_receipt(base,root,history,history_manifest,owners))
                history_journal=base.rooted(root,history['backup']+'/journal.json');saved_history=history_journal.read_bytes()
                for update in ({'written':False},{'rollbackIntent':True}):
                    bad=json.loads(saved_history);bad['files'][0].update(update);raw=json.dumps(bad).encode()
                    history_journal.write_bytes(raw);history['journalSha256']=prepare.digest(raw)
                    with self.assertRaisesRegex(ValueError,'native_history_success_required'):release.installed_baseline(root,git)
                history_journal.write_bytes(saved_history);history['journalSha256']=prepare.digest(saved_history)
                for change in (dict(source_commit='bd9cb44c4233f176fb15fd14f5560a5000c750d1',files=git['files']),
                               dict(source_commit=source,files=dict(git['files'],**{'runtime/proxy_gateway.py':'0'*64}))):
                    with self.assertRaisesRegex(ValueError,'composer_static_installed_proof_mismatch'):release.installed_baseline(root,change)
                for key,value in (('sha256','75a9b57a7073771b105573ab59e4c0a227f8567a75c8accbde2991d171934b3d'),('owner','9876:9876'),('mode','0o644')):
                    bad=deepcopy(manifest);bad['unchangedRequired'][0][key]=value;save(bad)
                    with self.assertRaisesRegex(ValueError,'native_desktop_success_chain_mismatch'):release.installed_baseline(root,git)
                bad=deepcopy(manifest);bad['sourceCommit']='bd9cb44c4233f176fb15fd14f5560a5000c750d1';save(bad)
                with self.assertRaises(ValueError):release.installed_baseline(root,git)
                save(manifest,files=[dict(r,intent=True,written=False) for r in rows])
                with self.assertRaises(ValueError):release.installed_baseline(root,git)
                save(manifest,status='rolled-back')
                with self.assertRaises(ValueError):release.installed_baseline(root,git)
                save(manifest,files=[dict(r,intent=True,written=True,rollbackIntent=True) for r in rows])
                with self.assertRaises(ValueError):release.installed_baseline(root,git)
                save(manifest);(backup/'journal.json').write_bytes(b'changed proof')
                with self.assertRaisesRegex(ValueError,'installed_release_proof_drift'):release.installed_baseline(root,git)

    def test_native_campaign_fixed_git_before_boundary(self):
        prepare.configure_native_capabilities();base=release.frozen()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owners={};kinds={}
            with self.native_metadata(owners,kinds,root=root):
                for name,target in release.CAMPAIGN_TARGETS.items():
                    body=self.campaign_before_bytes(name)
                    path=base.rooted(root,target);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body);owners[path]=(0,0,0o644)
                    self.assertEqual(prepare.file_metadata(base,root,target)['sha256'],release.CAMPAIGN_BEFORE[name][0])
                    path.write_bytes(body+b'x')
                    with self.assertRaisesRegex(ValueError,'campaign_before_boundary_drift'):prepare.file_metadata(base,root,target)
                    path.write_bytes(b'x'+body[1:])
                    with self.assertRaisesRegex(ValueError,'campaign_before_git_drift'):prepare.file_metadata(base,root,target)
                    path.write_bytes(body)
                    for identity in ((9876,9876,0o644),(0,0,0o666)):
                        owners[path]=identity
                        with self.assertRaises(ValueError):prepare.file_metadata(base,root,target)
                    owners[path]=(0,0,int(release.payload_mode(release.TARGETS[name]),8))
                    link=path.with_name(path.name+'.link');os.link(path,link)
                    with self.assertRaises(ValueError):prepare.file_metadata(base,root,target)
                    link.unlink();kinds[path.parent]=stat.S_IFLNK
                    with self.assertRaises(ValueError):prepare.file_metadata(base,root,target)
                    kinds.clear()

    def test_native_grant_uses_current_success_and_no_new_module(self):
        prepare.configure_native_capabilities()
        self.assertEqual(release.INSTALLED_COMMIT,'051f784d65b239f572cd40b319b0e1c71cad0644')
        self.assertEqual((len(release.TARGETS),len(release.CAPABILITIES_BASELINE_TARGETS)),(32,21))
        self.assertNotIn('campaign/backend/campaign_backend/coupon_grant.py',release.NEW|set(release.CAPABILITIES_CHANGED))
        self.assertEqual(release.CAPABILITIES_PREVIOUS_PROOF['sourceCommit'],'36d7d92540d9153e9b1cc764f900990ded17362d')

    def campaign_before_bytes(self,name):
        # Frozen Git bytes assembled before isolation; never launch Git inside
        # the original offline runner or substitute current candidate bytes.
        fixture=json.loads(Path(__file__).with_name('campaign-before-9ca.json').read_bytes())
        historical=json.loads(Path(__file__).with_name('campaign-before-698.json').read_bytes())
        self.assertEqual(historical['source_commit'],release.CAPABILITIES_GRANT_HISTORY_PROOF['sourceCommit'])
        fixture['files']={**historical['files'],**fixture['files']}
        self.assertEqual(fixture['source_commit'],release.CAPABILITIES_IMPORT_HISTORY_PROOF['sourceCommit'])
        self.assertEqual(set(fixture['files']),{*release.CAMPAIGN_TARGETS,'campaign/backend/campaign_backend/coupon_grant.py'})
        row=fixture['files'][name];self.assertEqual(row['source'],prepare.SOURCES[name])
        body=row['utf8'].encode('utf8')
        if name in release.CAMPAIGN_BEFORE:self.assertEqual((prepare.digest(body),len(body)),release.CAMPAIGN_BEFORE[name])
        else:self.assertEqual((prepare.digest(body),len(body)),(row['sha256'],row['bytes']))
        return body

    def test_native_capabilities_original_apply_rollback(self):
        self._archive_apply_contract(capabilities=True)

    @staticmethod
    def customer_daily_source_bytes(name, role):
        fixture=json.loads(Path(__file__).with_name('customer-daily-source-7312.json').read_bytes())
        row=fixture['files'][name][role];body=row['utf8'].encode('utf-8')
        expected={
            ('runtime/user_runtime.py','before'):('601c1b3e40930c4c8d2b7c48b4393e52b1dda8199747707cf6ac3373da2c99c9',5008,'404767812903568d423da2aefda82e1403497135'),
            ('runtime/user_runtime.py','after'):('a41e138d1ea6f79688d3ba0044f53ad3f08134a4e46591f271c1b3483809015a',5007,'f8ae6fab0dea8bbcd213efe35899e2f85b9ad869'),
            ('runtime/a2_query_context.py','before'):('31162d0c1d09c637c26a2f3a6f3afd6a84f7b9545bf21a942ed8c7cfae2f5bc6',20848,'ed8b864827ca96fa5c90c90ac864f16a938b7912'),
            ('runtime/a2_query_context.py','after'):('980a6a27d539954c75f20753d8411babb20c910b0c6591dedd148e6671715df3',20921,'94fd8714540a030bf5ba7889b9a2cb6829139e17')}
        assert row['source_commit']==('051f784d65b239f572cd40b319b0e1c71cad0644' if role=='before' else '7312aa3170724ba31dd12aedf1fd92dbe7bc7578')
        assert row['source']=='releases/fs-dashboard/user-analytics-20261022/source/'+name.split('/')[1]
        assert (prepare.digest(body),len(body),row['blob'])==expected[name,role]
        assert row['sha256']==prepare.digest(body) and row['bytes']==len(body)
        assert hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()==row['blob']
        return body

    @contextmanager
    def customer_daily_fixture(self, root, base, owners):
        rows=[dict(candidate='source/'+n,target='/opt/fs-hermes-fc/'+n,beforeSha256=prepare.digest(('before:'+n).encode()),
                   sha256=prepare.digest(('after:'+n).encode()),owner='0:0',mode='0o644')
              for n in ('user_weekly.py','user_runtime.py','user_jobs.py','user_query.py','user_customer_types.py','user_tools.py','a2_query_context.py')]
        rows += [dict(candidate='ui/'+n,target='/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/'+n,
                      beforeSha256='1'*64,sha256='2'*64,owner='0:0',mode='0o644') for n in ('index.html','users.js')]
        before={}
        for name in ('runtime/user_runtime.py','runtime/a2_query_context.py'):
            row=next(r for r in rows if r['target']==release.TARGETS[name])
            row.update(beforeSha256=prepare.digest(self.customer_daily_source_bytes(name,'before')),
                       sha256=prepare.digest(self.customer_daily_source_bytes(name,'after')))
            before[row['target']]=dict(path=row['target'],sha256=row['beforeSha256'],owner='0:0',mode='0o644')
        manifest=dict(scope='user-daily-20261105',sourceCommit='7312aa3170724ba31dd12aedf1fd92dbe7bc7578',releaseReady=True,schemaVersion=1,files=rows)
        proof=deepcopy(release.CUSTOMER_DAILY_PROOF)
        backup=base.rooted(root,proof['backup']);backup.mkdir(parents=True,exist_ok=True)
        def save(m=manifest, **changes):
            raw=json.dumps(m).encode();(backup/'approved-manifest.json').write_bytes(raw);proof['manifestSha256']=prepare.digest(raw)
            journal=dict(status='applied-awaiting-actual-http-role-acceptance',manifest=m,approvedManifestSha256=proof['manifestSha256'],
                         files=[dict(r,intent=True,written=True) for r in m['files']])
            journal.update(changes);raw=json.dumps(journal).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
            for path in backup.iterdir():owners[path]=(0,0,0o600)
        save()
        with patch.object(release,'CUSTOMER_DAILY_PROOF',proof):
            yield SimpleNamespace(proof=proof,before=before,manifest=manifest,backup=backup,save=save)

    def test_customer_daily_source_fixture_is_exact_git_before_and_after(self):
        prepare.configure_native_capabilities();path=Path(__file__).with_name('customer-daily-source-7312.json');original=Path.read_bytes
        fixture=json.loads(original(path))
        for name in fixture['files']:
            for role in ('before','after'):
                self.customer_daily_source_bytes(name,role)
                for field,value in (('source_commit','0'*40),('source','wrong'),('blob','0'*40),('sha256','0'*64),('bytes',1),('utf8','wrong')):
                    bad=deepcopy(fixture);bad['files'][name][role][field]=value;raw=json.dumps(bad).encode()
                    with self.subTest(name=name,role=role,field=field),patch.object(Path,'read_bytes',lambda p:raw if p==path else original(p)):
                        with self.assertRaises(AssertionError):self.customer_daily_source_bytes(name,role)

    def test_customer_daily_overlay_exact_success_and_only_two_metadata_transitions(self):
        prepare.configure_native_capabilities();base=release.frozen()
        self.assertEqual(release.CUSTOMER_DAILY_PROOF,dict(sourceCommit='7312aa3170724ba31dd12aedf1fd92dbe7bc7578',
            backup='/var/backups/fs-navigation-20261006/nav-20261105T052700Z',
            manifestSha256='006f87c82fa253c4644682685cda5df2c42fbca738cddb105678c39011d6607c',
            journalSha256='5fc992b0712ca778ec6b9f5581ecd3c364ce7aa9d70e66fcb22f6f004a349ed8'))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owners={}
            with self.native_metadata(owners,root=root),self.customer_daily_fixture(root,base,owners) as f:
                metadata=dict(f.before,unrelated=dict(path='unrelated',sha256='3'*64,owner='0:0',mode='0o600'));original=deepcopy(metadata)
                updated=release.capabilities_customer_daily_overlay(base,root,metadata)
                self.assertEqual(metadata,original);self.assertEqual(set(updated),set(metadata))
                self.assertEqual({p for p in metadata if metadata[p]!=updated[p]},set(f.before))
                for name in ('runtime/user_runtime.py','runtime/a2_query_context.py'):
                    self.assertEqual(updated[release.TARGETS[name]]['sha256'],prepare.digest(self.customer_daily_source_bytes(name,'after')))
                for field,value in (('sourceCommit','0'*40),('scope','wrong'),('releaseReady',1),('schemaVersion',2)):
                    bad=deepcopy(f.manifest);bad[field]=value;f.save(bad)
                    with self.subTest(field=field),self.assertRaisesRegex(ValueError,'customer_daily_success_required'):release.capabilities_customer_daily_overlay(base,root,metadata)
                for change in (dict(status='rolled-back'),dict(failure='failed'),dict(rollback=True),dict(rollbackIntent=True),dict(rolledBack=True),dict(rollbackAttempted=True),dict(manifest={}),dict(approvedManifestSha256='0'*64)):
                    f.save(**change)
                    with self.subTest(change=change),self.assertRaisesRegex(ValueError,'customer_daily_success_required'):release.capabilities_customer_daily_overlay(base,root,metadata)
                for field,value in (('intent',False),('intent',1),('written',False),('rollbackIntent',True),('rolledBack',True),('rollbackWritten',True),('target','/other'),('beforeSha256','0'*64),('sha256','0'*64),('owner','1:0'),('mode','0o600')):
                    rows=[dict(r,intent=True,written=True) for r in f.manifest['files']];rows[0][field]=value;f.save(files=rows)
                    with self.subTest(field=field),self.assertRaisesRegex(ValueError,'customer_daily_success_required'):release.capabilities_customer_daily_overlay(base,root,metadata)
                for change in (lambda m:m['files'].pop(),lambda m:m['files'].append(m['files'][0]),lambda m:m['files'][1].update(beforeSha256='0'*64),lambda m:m['files'][1].update(sha256='0'*64),lambda m:m['files'][1].update(target='/other')):
                    bad=deepcopy(f.manifest);change(bad);f.save(bad)
                    with self.assertRaises(ValueError):release.capabilities_customer_daily_overlay(base,root,metadata)
                f.save()
                for field,value in (('sha256','0'*64),('owner','1:0'),('mode','0o600')):
                    bad=deepcopy(metadata);bad[next(iter(f.before))][field]=value
                    with self.subTest(metadata_field=field),self.assertRaisesRegex(ValueError,'customer_daily_transition_drift'):release.capabilities_customer_daily_overlay(base,root,bad)
                with patch.object(release,'NATIVE_CAPABILITIES_MODE',False),self.assertRaises(ValueError):release.capabilities_customer_daily_overlay(base,root,metadata)

    def test_customer_daily_proof_keeps_nine_fields_cap_links_and_nofollow(self):
        prepare.configure_native_capabilities();base=release.frozen()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owners={};kinds={}
            with self.native_metadata(owners,kinds,root=root),self.customer_daily_fixture(root,base,owners) as f:
                path=f.backup/'journal.json';saved=path.read_bytes();actual_fstat=os.fstat;identity=(path.stat().st_dev,path.stat().st_ino)
                path.write_bytes(saved+b' ')
                with self.assertRaisesRegex(ValueError,'customer_daily_proof_drift'):release.capabilities_customer_daily_overlay(base,root,f.before)
                path.write_bytes(saved)
                for value in ((1,0,0o600),(0,1,0o600),(0,0,0o644)):
                    owners[path]=value
                    with self.assertRaisesRegex(ValueError,'customer_daily_proof_boundary_drift'):release.capabilities_customer_daily_overlay(base,root,f.before)
                owners[path]=(0,0,0o600)
                for linked in (path,path.parent):
                    kinds[linked]=stat.S_IFLNK
                    with self.assertRaises(ValueError):release.capabilities_customer_daily_overlay(base,root,f.before)
                    kinds.clear()
                alias=path.with_name('hardlink');os.link(path,alias)
                try:
                    with self.assertRaisesRegex(ValueError,'customer_daily_proof_boundary_drift'):release.capabilities_customer_daily_overlay(base,root,f.before)
                finally:alias.unlink()
                for phase in ('opened','read'):
                    for field in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink','st_uid','st_gid','st_mode'):
                        calls=[0]
                        def changed(fd):
                            info=actual_fstat(fd)
                            if (info.st_dev,info.st_ino)!=identity:return info
                            calls[0]+=1
                            if calls[0]!=(1 if phase=='opened' else 2):return info
                            values={k:getattr(info,k) for k in dir(info) if k.startswith('st_')};values[field]+=1
                            return SimpleNamespace(**values)
                        with self.subTest(phase=phase,field=field),patch.object(os,'fstat',changed),self.assertRaisesRegex(ValueError,'customer_daily_proof_changed'):
                            release.capabilities_customer_daily_overlay(base,root,f.before)
                path.write_bytes(b'x'*(8*1024*1024+1))
                with self.assertRaisesRegex(ValueError,'customer_daily_proof_boundary_drift'):release.capabilities_customer_daily_overlay(base,root,f.before)

    def test_desktop_followup_pack_reads_all_installed_git_bytes(self):
        prepare.configure_native_capabilities();calls=[];before={}
        changed=('runtime/conversation_service.py','http/conversation_http.py')
        for name,path in prepare.SOURCES.items():
            raw=self.plain_reply_installed_bytes(name) if name in changed else self.desktop_current_bytes(name) if name in release.DESKTOP_EXISTING else self.customer_daily_source_bytes(name,'before') if name in ('runtime/user_runtime.py','runtime/a2_query_context.py') else ('installed:'+name).encode()
            if name=='http/range_api.py':raw=raw.replace(b'\r\n',b'\n')
            if path in before:self.assertEqual(before[path],raw)
            before[path]=raw
        gateway=prepare.SOURCES['desktop/desktop_fs_gateway.py'];after=dict(before)
        for name in changed:
            path=prepare.SOURCES[name];after[path]=before[path]+b'\n# synthetic setup delta\n'
        daily={prepare.SOURCES[n]:self.customer_daily_source_bytes(n,'after') for n in ('runtime/user_runtime.py','runtime/a2_query_context.py')}
        after.update(daily)
        after.update({path:b'synthetic publisher boundary' for path in prepare.PUBLISHER_SOURCES.values()})
        def git_bytes(argv,**kwargs):
            self.assertEqual(argv[:2],['git','show']);ref,path=argv[2].split(':',1);calls.append((ref,path))
            self.assertIn(ref,(release.INSTALLED_COMMIT,'b'*40,'7312aa3170724ba31dd12aedf1fd92dbe7bc7578'))
            return (before if ref==release.INSTALLED_COMMIT else daily if ref=='7312aa3170724ba31dd12aedf1fd92dbe7bc7578' else after)[path]
        with tempfile.TemporaryDirectory() as directory,patch.object(prepare.subprocess,'check_output',side_effect=git_bytes):
            root=Path(directory);prepare.pack(root,root/'valid','b'*40)
            descriptor=json.loads((root/'valid/payload-manifest.json').read_bytes())
            self.assertEqual({n for n in prepare.SOURCES if descriptor['files']['payload/'+n]!=descriptor['installed_baseline']['files'][n]},set(changed))
            self.assertEqual(descriptor['installed_baseline']['source_overlays'],{n:'7312aa3170724ba31dd12aedf1fd92dbe7bc7578' for n in ('runtime/user_runtime.py','runtime/a2_query_context.py')})
            for name in ('runtime/user_runtime.py','runtime/a2_query_context.py'):
                self.assertEqual(descriptor['installed_baseline']['files'][name],prepare.digest(self.customer_daily_source_bytes(name,'after')))
                self.assertIn(('7312aa3170724ba31dd12aedf1fd92dbe7bc7578',prepare.SOURCES[name]),calls)
            self.assertFalse(any(v is None for v in descriptor['installed_baseline']['files'].values()))
            for name in prepare.SOURCES:self.assertIn((release.INSTALLED_COMMIT,prepare.SOURCES[name]),calls)
            self.assertEqual(descriptor['installed_baseline']['files']['http/range_api.py'],release.DESKTOP_EXISTING['http/range_api.py'][0])
            for name in changed:
                path=prepare.SOURCES[name];saved=after[path];after[path]=before[path]
                with self.subTest(missing_delta=name),self.assertRaisesRegex(ValueError,'exact_native_capabilities_git_delta_required'):
                    prepare.pack(root,root/('missing-'+name.replace('/','-')),'b'*40)
                after[path]=saved
            for name in ('runtime/user_runtime.py','runtime/a2_query_context.py'):
                path=prepare.SOURCES[name]
                for mapping,body in ((before,self.customer_daily_source_bytes(name,'after')),(daily,self.customer_daily_source_bytes(name,'before')),(after,self.customer_daily_source_bytes(name,'before'))):
                    saved=mapping[path];mapping[path]=body
                    with self.subTest(daily_drift=name),self.assertRaises(ValueError):prepare.pack(root,root/('daily-'+str(len(list(root.iterdir())))),'b'*40)
                    mapping[path]=saved
            original=before[gateway];before[gateway]+=b'x'
            with self.assertRaisesRegex(ValueError,'desktop_installed_git_before_drift'):prepare.pack(root,root/'bad-before','b'*40)
            before[gateway]=original;after[prepare.SOURCES['runtime/conversation_store.py']]+=b'x'
            with self.assertRaisesRegex(ValueError,'exact_native_capabilities_git_delta_required'):prepare.pack(root,root/'extra','b'*40)

    def test_desktop_followup_supplements_are_exact_read_only_transitions(self):
        prepare.configure_native_capabilities();base=release.frozen()
        rows=[dict(candidate=n,target=p,beforeSha256='0'*64,sha256=prepare.digest(n.encode()),owner='0:0',mode='0o644') for n,p in release.KNOWLEDGE_INSTALLED_TARGETS.items()]
        protected=[dict(path=release.NGINX,sha256=release.DESKTOP_NAVIGATION_PROOF['beforeSha256'],owner='0:0',mode='0o600')]
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            root=Path(directory);owners={};kinds={};stack.enter_context(self.native_metadata(owners,kinds,root=root))
            fixture=self.desktop_installed_fixture(base,root,dict(files=rows,unchangedRequired=protected),owners,stack)
            manifest=fixture.initial_manifest;metadata={r['target']:dict(path=r['target'],sha256=r['sha256'],owner=r['owner'],mode=r['mode']) for r in manifest['files']}
            metadata.update({r['path']:dict(r) for r in protected});original=deepcopy(metadata)
            result=release.capabilities_desktop_metadata(base,root,metadata,manifest)
            self.assertEqual(metadata,original)
            self.assertEqual([p for p in metadata if metadata[p]!=result[p]],[release.NGINX])
            self.assertEqual(result[release.NGINX]['sha256'],fixture.nav['sha256']);self.assertEqual(result[release.DESKTOP_CONFIG]['mode'],'0o600')
            saved=fixture.mode.read_bytes();fixture.mode.write_bytes(saved+b' ')
            with self.assertRaisesRegex(ValueError,'desktop_supplement_proof_drift'):release.capabilities_desktop_metadata(base,root,metadata,manifest)
            fixture.mode.write_bytes(saved)
            for field,value in (('source','untrusted'),('target','/other'),('fchmod_calls',2),('manifest_journal_changed',True)):
                bad=json.loads(saved);bad[field]=value;raw=json.dumps(bad).encode();fixture.mode.write_bytes(raw)
                with patch.object(release,'DESKTOP_MODE_CORRECTION_SHA',prepare.digest(raw)),self.assertRaisesRegex(ValueError,'desktop_mode_correction_binding_required'):
                    release.capabilities_desktop_metadata(base,root,metadata,manifest)
            bad=json.loads(saved);bad['after']['inode']+=1;raw=json.dumps(bad).encode();fixture.mode.write_bytes(raw)
            with patch.object(release,'DESKTOP_MODE_CORRECTION_SHA',prepare.digest(raw)),self.assertRaisesRegex(ValueError,'desktop_mode_correction_binding_required'):
                release.capabilities_desktop_metadata(base,root,metadata,manifest)
            fixture.mode.write_bytes(saved)
            journal=base.rooted(root,fixture.nav['backup']+'/journal.json');saved_journal=journal.read_bytes()
            for changes in ({'written':False},{'intent':False},{'beforeMode':0o644},{'rollbackWritten':True},{'beforeSha256':'f'*64}):
                bad=json.loads(saved_journal);bad['files'][0].update(changes);raw=json.dumps(bad).encode();journal.write_bytes(raw)
                with patch.dict(fixture.nav,journalSha256=prepare.digest(raw)),self.assertRaisesRegex(ValueError,'desktop_navigation_transition_drift'):
                    release.capabilities_desktop_metadata(base,root,metadata,manifest)
            journal.write_bytes(saved_journal)
            bad=deepcopy(metadata);bad[release.NGINX]['sha256']='f'*64
            with self.assertRaisesRegex(ValueError,'desktop_navigation_transition_drift'):release.capabilities_desktop_metadata(base,root,bad,manifest)
            owners[fixture.mode]=(0,0,0o644)
            with self.assertRaisesRegex(ValueError,'desktop_supplement_boundary_drift'):release.capabilities_desktop_metadata(base,root,metadata,manifest)
            owners[fixture.mode]=(0,0,0o600)
            hardlink=fixture.mode.with_name('hardlink');os.link(fixture.mode,hardlink)
            with self.assertRaisesRegex(ValueError,'desktop_supplement_boundary_drift'):release.capabilities_desktop_metadata(base,root,metadata,manifest)
            hardlink.unlink()
            kinds[fixture.mode]=stat.S_IFLNK
            with self.assertRaises(ValueError):release.capabilities_desktop_metadata(base,root,metadata,manifest)
            kinds.clear();actual=os.fstat
            def changed(fd):
                info=actual(fd);fields={k:getattr(info,k) for k in dir(info) if k.startswith('st_')};fields['st_ctime_ns']+=1
                return SimpleNamespace(**fields)
            with patch.object(os,'fstat',changed),self.assertRaisesRegex(ValueError,'desktop_supplement_changed'):
                release.capabilities_desktop_metadata(base,root,metadata,manifest)

    def desktop_installed_fixture(self,base,root,manifest,owners,stack,materialize=False):
        history_manifest=dict(manifest,sourceCommit=release.CAPABILITIES_DESKTOP_HISTORY_PROOF['sourceCommit'])
        history=self.save_capabilities_receipt(base,root,release.CAPABILITIES_DESKTOP_HISTORY_PROOF,history_manifest,owners)
        stack.enter_context(patch.object(release,'CAPABILITIES_DESKTOP_HISTORY_PROOF',history))
        previous={r['candidate']:r for r in manifest['files']};rows=[]
        for name,target in release.TARGETS.items():
            prior=release.DESKTOP_INITIAL_EXISTING[name][0] if name in release.DESKTOP_INITIAL_EXISTING else None if name in release.DESKTOP_ORIGINAL_NEW else previous[name]['sha256']
            sha=release.DESKTOP_FIRST_INSTALLED_EXISTING[name][0] if name in release.DESKTOP_FIRST_INSTALLED_EXISTING else previous[name]['sha256']
            rows.append(dict(candidate=name,target=target,beforeSha256=prior,sha256=sha,owner='0:0',mode=release.payload_mode(target)))
            if materialize and name in release.DESKTOP_EXISTING:
                path=base.rooted(root,target);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(self.desktop_installed_bytes(name))
                owners[path]=(0,0,int(release.payload_mode(target),8))
        current=dict(manifest,sourceCommit=release.CAPABILITIES_DESKTOP_INSTALL_PROOF['sourceCommit'],files=rows,
            unchangedRequired=[dict(r) for r in manifest['unchangedRequired'] if r['path'] not in release.TARGETS.values()])
        proof=self.save_capabilities_receipt(base,root,release.CAPABILITIES_DESKTOP_INSTALL_PROOF,current,owners)
        stack.enter_context(patch.object(release,'CAPABILITIES_DESKTOP_INSTALL_PROOF',proof))
        state=dict(sha256=release.DESKTOP_EXISTING['desktop/fs-principal.json'][0],uid=0,gid=0,mode='0o644',size=106,inode=123,mtime_ns=456,ctime_ns=456,device=1,nlink=1,type='regular')
        receipt=dict(kind='single-approved-desktop-binding-mode-correction',source=proof['sourceCommit'],release=Path(proof['backup']).name,
            approved_manifest_sha256=proof['manifestSha256'],original_journal_sha256=proof['journalSha256'],target=release.DESKTOP_CONFIG,
            before=state,after=dict(state,mode='0o600',ctime_ns=457),fchmod_calls=1,content_writes=0,manifest_journal_changed=False)
        mode=base.rooted(root,proof['backup']+'/desktop-binding-mode-correction.json');mode.write_bytes(json.dumps(receipt).encode());owners[mode]=(0,0,0o600)
        mode_sha=prepare.digest(mode.read_bytes());stack.enter_context(patch.object(release,'DESKTOP_MODE_CORRECTION_SHA',mode_sha))
        nav=deepcopy(release.DESKTOP_NAVIGATION_PROOF)
        nav['beforeSha256']=next(r['sha256'] for r in current['unchangedRequired'] if r['path']==release.NGINX)
        body=b'independent navigation release after Desktop'
        if materialize:
            path=base.rooted(root,release.NGINX);path.write_bytes(body);owners[path]=(0,0,0o600);nav['sha256']=prepare.digest(body)
        row=dict(candidate='generated/navigation.conf',target=release.NGINX,beforeSha256=nav['beforeSha256'],sha256=nav['sha256'],owner='0:0',mode='0o644')
        nav_manifest=dict(scope='management-config-20261104',releaseReady=True,files=[row])
        nav_saved=self.save_capabilities_receipt(base,root,nav,nav_manifest,owners);nav.update(nav_saved)
        nav_journal=base.rooted(root,nav['backup']+'/journal.json');journal=json.loads(nav_journal.read_bytes());journal['files'][0]['beforeMode']=0o600
        nav_journal.write_bytes(json.dumps(journal).encode());nav['journalSha256']=prepare.digest(nav_journal.read_bytes())
        stack.enter_context(patch.object(release,'DESKTOP_NAVIGATION_PROOF',nav))
        initial_manifest=current;initial_proof=proof
        current=dict(current,sourceCommit=release.CAPABILITIES_DESKTOP_WS_PROOF['sourceCommit'],
            files=[dict(r,beforeSha256=r['sha256'],sha256=release.DESKTOP_WS_INSTALLED_EXISTING[r['candidate']][0] if r['candidate'] in release.DESKTOP_WS_INSTALLED_EXISTING else r['sha256']) for r in rows],
            unchangedRequired=[dict(r,sha256=nav['sha256']) if r['path']==release.NGINX else dict(r) for r in current['unchangedRequired']])
        if materialize:
            gateway=base.rooted(root,release.TARGETS['desktop/desktop_fs_gateway.py']);gateway.write_bytes(self.desktop_current_bytes('desktop/desktop_fs_gateway.py'))
        ws_proof=self.save_capabilities_receipt(base,root,release.CAPABILITIES_DESKTOP_WS_PROOF,current,owners)
        stack.enter_context(patch.object(release,'CAPABILITIES_DESKTOP_WS_PROOF',ws_proof))
        current=dict(current,sourceCommit=release.CAPABILITIES_DESKTOP_TIME_PROOF['sourceCommit'],
            files=[dict(r,beforeSha256=r['sha256'],sha256=release.DESKTOP_TIME_INSTALLED_EXISTING[r['candidate']][0] if r['candidate'] in release.DESKTOP_TIME_INSTALLED_EXISTING else r['sha256']) for r in current['files']])
        if materialize:
            for name in release.DESKTOP_EXISTING:
                base.rooted(root,release.TARGETS[name]).write_bytes(self.desktop_current_bytes(name))
        time_proof=self.save_capabilities_receipt(base,root,release.CAPABILITIES_DESKTOP_TIME_PROOF,current,owners)
        stack.enter_context(patch.object(release,'CAPABILITIES_DESKTOP_TIME_PROOF',time_proof))
        current=dict(current,sourceCommit=release.CAPABILITIES_DESKTOP_SETUP_PROOF['sourceCommit'],
            files=[dict(r,beforeSha256=r['sha256'],sha256=prepare.digest(self.control_installed_bytes('runtime/conversation_service.py')) if r['candidate']=='runtime/conversation_service.py' else release.DESKTOP_SETUP_INSTALLED_EXISTING[r['candidate']][0] if r['candidate'] in release.DESKTOP_SETUP_INSTALLED_EXISTING else r['sha256']) for r in current['files']])
        if materialize:
            for name in release.DESKTOP_EXISTING:
                base.rooted(root,release.TARGETS[name]).write_bytes(self.desktop_current_bytes(name))
            base.rooted(root,release.TARGETS['runtime/conversation_service.py']).write_bytes(self.control_installed_bytes('runtime/conversation_service.py'))
        setup_proof=self.save_capabilities_receipt(base,root,release.CAPABILITIES_DESKTOP_SETUP_PROOF,current,owners)
        stack.enter_context(patch.object(release,'CAPABILITIES_DESKTOP_SETUP_PROOF',setup_proof))
        current=dict(current,sourceCommit=release.CAPABILITIES_DIAGNOSTIC_HISTORY_PROOF['sourceCommit'],files=[dict(r,beforeSha256=r['sha256'],sha256=release.DESKTOP_EXISTING[r['candidate']][0] if r['candidate'] in release.DESKTOP_EXISTING else r['sha256']) for r in current['files']])
        diagnostic_history=self.save_capabilities_receipt(base,root,release.CAPABILITIES_DIAGNOSTIC_HISTORY_PROOF,current,owners)
        stack.enter_context(patch.object(release,'CAPABILITIES_DIAGNOSTIC_HISTORY_PROOF',diagnostic_history))
        current=dict(current,sourceCommit=release.CAPABILITIES_RETRY_HISTORY_PROOF['sourceCommit'],files=[dict(r,beforeSha256=r['sha256'],sha256=prepare.digest(self.diagnostic_current_bytes(r['candidate'])) if r['candidate'] in ('runtime/transport.py','runtime/proxy_gateway.py') else r['sha256']) for r in current['files']])
        if materialize:
            for name in ('runtime/transport.py','runtime/proxy_gateway.py'):
                base.rooted(root,release.TARGETS[name]).write_bytes(self.diagnostic_current_bytes(name))
        retry_history=self.save_capabilities_receipt(base,root,release.CAPABILITIES_RETRY_HISTORY_PROOF,current,owners)
        stack.enter_context(patch.object(release,'CAPABILITIES_RETRY_HISTORY_PROOF',retry_history))
        bodies={'runtime/proxy_gateway.py':(Path(__file__).resolve().parents[4]/prepare.SOURCES['runtime/proxy_gateway.py']).read_bytes(),
                'runtime/conversation_service.py':self.plain_reply_installed_bytes('runtime/conversation_service.py'),
                 'http/conversation_http.py':self.plain_reply_installed_bytes('http/conversation_http.py')}
        assert (prepare.digest(bodies['runtime/proxy_gateway.py']),len(bodies['runtime/proxy_gateway.py']))==('29467fd4deb8d128ab157825db37429456b23503a5b34f5b9c4fe41f8abaa6e8',44186)
        current=dict(current,sourceCommit=release.INSTALLED_COMMIT,files=[dict(r,beforeSha256=r['sha256'],sha256=prepare.digest(bodies[r['candidate']]) if r['candidate'] in bodies else r['sha256']) for r in current['files']])
        if materialize:
            for name,body_bytes in bodies.items():base.rooted(root,release.TARGETS[name]).write_bytes(body_bytes)
        proof=self.save_capabilities_receipt(base,root,release.NATIVE_CAPABILITIES_PROOF,current,owners)
        stack.enter_context(patch.object(release,'NATIVE_CAPABILITIES_PROOF',proof))
        return SimpleNamespace(manifest=current,proof=proof,initial_manifest=initial_manifest,initial_proof=initial_proof,ws_proof=ws_proof,time_proof=time_proof,setup_proof=setup_proof,diagnostic_history=diagnostic_history,retry_history=retry_history,history=history,mode_sha=mode_sha,mode=mode,nav=nav,nav_body=body)

    @staticmethod
    def save_capabilities_receipt(base,root,pin,manifest,owners):
        proof=deepcopy(pin);backup=base.rooted(root,proof['backup']);backup.mkdir(parents=True,exist_ok=True)
        raw=json.dumps(manifest).encode();(backup/'approved-manifest.json').write_bytes(raw);proof['manifestSha256']=prepare.digest(raw)
        journal=dict(status='applied-awaiting-actual-http-role-acceptance',manifest=manifest,approvedManifestSha256=proof['manifestSha256'],
                     files=[dict(r,intent=True,written=True) for r in manifest['files']])
        raw=json.dumps(journal).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
        for path in backup.iterdir():owners[path]=(0,0,0o600)
        return proof

    @staticmethod
    def shared_update_paths():
        home='/var/lib/fs-hermes-fc/profile/skills/'
        return (home+'data-storytelling/SKILL.md',home+'.curator_ledger.jsonl',
                home+'.locks/3a5f084db662a96c0e0055faa20055fa4a350a328b9f2223388f96b31af2fe9a.lock')

    @contextmanager
    def shared_update_fixture(self,root,base,owners):
        skill,ledger,lock=(base.rooted(root,p) for p in self.shared_update_paths())
        for p,raw in ((skill,b'old reviewed skill'),(ledger,b'{"old":"ledger"}\n'),(lock,b'')):
            p.parent.mkdir(parents=True,exist_ok=True)
            if not p.exists():p.write_bytes(raw)
            owners[p]=(0,0,0o644)
        before={name:dict(path=name,sha256=base.digest(p),owner='0:0',mode='0o644') for name,p in zip(self.shared_update_paths(),(skill,ledger,lock))}
        prefix=ledger.read_bytes();new_skill=b'new independently reviewed skill'
        proof=dict(candidate_id='skill:6e5464d7',target_sha='e'*64,after_sha='a'*64,package_sha='b'*64,
                   skill_before=before[self.shared_update_paths()[0]]['sha256'],skill_after=prepare.digest(new_skill),
                   ledger_before=prepare.digest(prefix),ledger_prefix_bytes=len(prefix),ledger_last_id='15b63d181884')
        record=dict(id='6e5464d7',payload=dict(action='patch',name='data-storytelling',old_string='old',new_string='new'))
        canonical=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        proof['expected_sha']=prepare.digest(canonical(record))
        decision=dict(id=proof['candidate_id'],decision='approve',expected_sha=proof['expected_sha'],target_sha=proof['target_sha'],reason='Synthetic external review',evidence='Synthetic complete package')
        proof['request_id']=prepare.digest(canonical(decision))
        old_entry=dict(path='SKILL.md',kind='file',sha256=proof['skill_before'],uid=0,gid=0,mode=0o644)
        new_entry=dict(old_entry,sha256=proof['skill_after'])
        receipt=dict(request_id=proof['request_id'],reviewer='Codex',status='completed',decision=decision,
            candidate=dict(id=proof['candidate_id'],record=record,sha256=proof['expected_sha'],target_sha256=proof['target_sha']),
            backup=dict(sha256=proof['target_sha'],snapshots=[dict(path='data-storytelling',entries=[old_entry])]),
            result=dict(success=True,applied=True,after_sha256=proof['after_sha'],packages=[dict(path='data-storytelling',sha256=proof['package_sha'],entries=[new_entry])]))
        last=dict(id=proof['ledger_last_id'],skill='data-storytelling',action='patch',actor='agent',
                  before=[dict(path='/profile/skills/data-storytelling/SKILL.md',sha256=proof['skill_before'])],
                  after=[dict(path='/profile/skills/data-storytelling/SKILL.md',sha256=proof['skill_after'])])
        ledger_bytes=prefix+json.dumps(dict(action='write_file',skill='data-storytelling')).encode()+b'\n'+json.dumps(last).encode()+b'\n'
        proof.update(ledger_after=prepare.digest(ledger_bytes),ledger_bytes=len(ledger_bytes))
        receipt_path=base.rooted(root,'/var/lib/fs-hermes-memory-approval/'+proof['request_id']+'.json');receipt_path.parent.mkdir(parents=True,exist_ok=True)
        owners[receipt_path]=(0,0,0o600)
        def save(value=receipt):
            raw=json.dumps(value).encode();receipt_path.write_bytes(raw);proof['receipt_sha']=prepare.digest(raw)
        save();skill.write_bytes(new_skill);ledger.write_bytes(ledger_bytes);owners[lock]=(9876,9876,0o644)
        for name,identity in (('/var/lib/fs-hermes-fc',(0,9876,0o750)),('/var/lib/fs-hermes-fc/profile',(9876,9876,0o700)),
                              ('/var/lib/fs-hermes-fc/profile/skills',(9876,9876,0o755)),('/var/lib/fs-hermes-fc/profile/skills/.locks',(9876,9876,0o755))):
            owners[base.rooted(root,name)]=identity
        after={p:dict(v) for p,v in before.items()}
        after[self.shared_update_paths()[0]]['sha256']=proof['skill_after']
        after[self.shared_update_paths()[1]]['sha256']=proof['ledger_after']
        after[self.shared_update_paths()[2]]['owner']='9876:9876'
        with patch.object(release,'CAPABILITIES_SHARED_PROOF',proof,create=True):
            yield SimpleNamespace(proof=proof,before=before,after=after,skill=skill,ledger=ledger,lock=lock,receipt=receipt,receipt_path=receipt_path,save=save)

    def test_native_capabilities_shared_approved_update_is_exact_and_readonly(self):
        self.assertTrue(callable(getattr(release,'capabilities_shared_overlay',None)))
        prepare.configure_native_capabilities();base=release.frozen()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owners={};kinds={}
            with self.native_metadata(owners,kinds,root=root),self.shared_update_fixture(root,base,owners) as f:
                original=deepcopy(f.before)
                self.assertEqual(release.capabilities_shared_overlay(base,root,f.before)[0],f.after)
                self.assertEqual(f.before,original)
                f.receipt_path.write_bytes(f.receipt_path.read_bytes()+b' ')
                with self.assertRaisesRegex(ValueError,'native_shared_review_drift'):release.capabilities_shared_overlay(base,root,f.before)
                f.save()
                for field,value in (('status','applying'),('reviewer','Hermes'),('request_id','0'*64)):
                    bad=deepcopy(f.receipt);bad[field]=value;f.save(bad)
                    with self.subTest(field=field),self.assertRaises(ValueError):release.capabilities_shared_overlay(base,root,f.before)
                for change in (lambda x:x['decision'].update(reason='different canonical'),lambda x:x['result'].update(applied=False),
                               lambda x:x['result']['packages'][0]['entries'][0].update(sha256='0'*64)):
                    bad=deepcopy(f.receipt);change(bad);f.save(bad)
                    with self.assertRaises(ValueError):release.capabilities_shared_overlay(base,root,f.before)
                f.save();raw=f.ledger.read_bytes()
                saved_ledger_sha=f.proof['ledger_after']
                for body in (b'x'+raw[1:],raw.replace(b'15b63d181884',b'15b63d181885')):
                    f.ledger.write_bytes(body)
                    f.proof['ledger_after']=prepare.digest(body)
                    with self.assertRaises(ValueError):release.capabilities_shared_overlay(base,root,f.before)
                f.ledger.write_bytes(raw);f.proof['ledger_after']=saved_ledger_sha
                owners[f.lock]=(0,0,0o644)
                with self.assertRaises(ValueError):release.capabilities_shared_overlay(base,root,f.before)
                owners[f.lock]=(9876,9876,0o644);f.lock.write_bytes(b'x')
                with self.assertRaises(ValueError):release.capabilities_shared_overlay(base,root,f.before)
                f.lock.write_bytes(b'')
                with patch.object(release,'NATIVE_CAPABILITIES_MODE',False),self.assertRaises(ValueError):release.capabilities_shared_overlay(base,root,f.before)

    def test_native_shared_complete_append_is_protected_without_reapproving_it(self):
        prepare.configure_native_capabilities();base=release.frozen()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owners={}
            with self.native_metadata(owners,root=root),self.shared_update_fixture(root,base,owners) as f:
                checkpoint=f.ledger.read_bytes();proof=deepcopy(f.proof);before=deepcopy(f.before)
                # This is audit data, not an instruction or an approval source.
                appended=b'{"action":"approve","skill":"unrelated","after_sha256":"untrusted"}\n{"action":"read","skill":"data-storytelling"}\n'
                audit=checkpoint+appended;f.ledger.write_bytes(audit)
                identity=(f.ledger.stat().st_ino,f.ledger.stat().st_mtime_ns)
                expected=deepcopy(f.after)
                expected[release.CAPABILITIES_CURATOR_LEDGER]['sha256']=prepare.digest(audit)
                try:observed,prefixes=release.capabilities_shared_overlay(base,root,f.before)
                except ValueError as error:self.fail('complete append after the exact checkpoint was rejected: '+str(error))
                self.assertEqual(observed,expected)
                self.assertTrue({proof['ledger_after'],prepare.digest(audit)}<=prefixes)
                self.assertEqual(f.proof,proof);self.assertEqual(f.before,before)
                self.assertEqual(f.ledger.read_bytes(),audit)
                self.assertEqual((f.ledger.stat().st_ino,f.ledger.stat().st_mtime_ns),identity)
                self.assertNotEqual(observed[release.CAPABILITIES_CURATOR_LEDGER]['sha256'],proof['ledger_after'])
                f.skill.write_bytes(b'unreviewed skill from an appended audit row')
                # The overlay supplies the original approved skill SHA; normal observation
                # must reject changed skill bytes instead of accepting appended claims.
                self.assertNotEqual(base.digest(f.skill),observed[release.CAPABILITIES_SKILL_FILE]['sha256'])

    def test_native_shared_append_keeps_historical_checkpoint_comparisons(self):
        prepare.configure_native_capabilities();base=release.frozen();first={}
        for _,_,_,_,changes in release.CAPABILITIES_NAVIGATION_PROOFS:
            for alias,(_,before,_) in changes.items():first.setdefault(alias,before)
        rows=[dict(candidate=n,target=p,beforeSha256='0'*64,sha256=prepare.digest(n.encode()),owner='0:0',mode='0o644')
              for n,p in release.CAPABILITIES_RUNTIME_TARGETS.items()]
        protected=[dict(path=p,sha256=first[a],owner='0:0',mode='0o600' if p==release.NGINX else '0o644')
                   for a,p in release.CAPABILITIES_NAVIGATION_TARGETS.items()]
        for p,body in zip(self.shared_update_paths(),(b'old reviewed skill',b'{"old":"ledger"}\n',b'')):
            protected.append(dict(path=p,sha256=prepare.digest(body),owner='0:0',mode='0o644'))
        protected += [dict(path='/opt/static/'+str(i),sha256='a'*64,owner='0:0',mode='0o644') for i in range(758)]
        manifest=dict(sourceCommit=release.CAPABILITIES_HISTORY_PROOF['sourceCommit'],scope=release.SCOPE,
                      nativeCapabilities=True,nativeArchive=True,nativeStaticBaseline=release.CAPABILITIES_STATIC_PROOF,
                      files=rows,unchangedRequired=protected)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owners={}
            with self.native_metadata(owners,root=root),self.capabilities_nginx_fixture(root,base) as nginx,self.capabilities_navigation_fixture(root,base,{r['path']:r for r in protected},owners) as navigation,self.shared_update_fixture(root,base,owners) as shared:
                for path in nginx.backup.iterdir():owners[path]=(0,0,0o600)
                proof=self.save_capabilities_receipt(base,root,release.CAPABILITIES_HISTORY_PROOF,manifest,owners)
                current={r['target']:dict(path=r['target'],sha256=r['sha256'],owner=r['owner'],mode=r['mode']) for r in rows}
                current.update(navigation.after);current.update(shared.after);original=deepcopy(current)
                audit=shared.ledger.read_bytes()+b'{"action":"read"}\n';shared.ledger.write_bytes(audit)
                with patch.object(release,'CAPABILITIES_HISTORY_PROOF',proof):
                    self.assertEqual(release.capabilities_history_matches(base,root,current)[0],prepare.digest(audit))
                    self.assertEqual(current,original)
                    reflected=deepcopy(current);reflected[release.CAPABILITIES_CURATOR_LEDGER]['sha256']=prepare.digest(audit)
                    with self.assertRaisesRegex(ValueError,'native_current_history_protection_mismatch'):
                        release.capabilities_history_matches(base,root,reflected)
                self.assertEqual(shared.ledger.read_bytes(),audit)

    def test_native_shared_append_rejects_changed_checkpoint_and_malformed_tail(self):
        prepare.configure_native_capabilities();base=release.frozen()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owners={}
            with self.native_metadata(owners,root=root),self.shared_update_fixture(root,base,owners) as f:
                checkpoint=f.ledger.read_bytes();append=b'{"action":"read"}\n'
                for case,raw in (
                        ('old_prefix',b'x'+checkpoint[1:]+append),
                        ('authored_row',checkpoint.replace(b'15b63d181884',b'15b63d181885')+append),
                        ('truncated',checkpoint[:-1]),
                        ('partial_line',checkpoint+b'{"action":"read"}'),
                        ('blank_line',checkpoint+b'\n'),
                        ('malformed_json',checkpoint+b'{bad}\n'),
                        ('non_object',checkpoint+b'[]\n'),
                        ('null',checkpoint+b'null\n'),
                        ('non_json_number',checkpoint+b'{"cost":NaN}\n'),
                        ('invalid_utf8',checkpoint+b'{"action":"\xff"}\n')):
                    f.ledger.write_bytes(raw)
                    with self.subTest(case=case),self.assertRaises(ValueError):
                        release.capabilities_shared_overlay(base,root,f.before)
                    self.assertEqual(f.ledger.read_bytes(),raw)

    def test_native_shared_append_keeps_link_metadata_and_open_descriptor_guards(self):
        prepare.configure_native_capabilities();base=release.frozen()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);owners={};kinds={}
            with self.native_metadata(owners,kinds,root=root),self.shared_update_fixture(root,base,owners) as f:
                f.ledger.write_bytes(f.ledger.read_bytes()+b'{"action":"read"}\n')
                audit=f.ledger.read_bytes()
                for identity in ((9876,0,0o644),(0,9876,0o644),(0,0,0o600)):
                    owners[f.ledger]=identity
                    with self.subTest(identity=identity),self.assertRaisesRegex(ValueError,'native_shared_source_boundary_drift'):
                        release.capabilities_shared_overlay(base,root,f.before)
                owners[f.ledger]=(0,0,0o644)
                for linked in (f.ledger,f.ledger.parent):
                    kinds[linked]=stat.S_IFLNK
                    with self.subTest(linked=linked.name),self.assertRaises(ValueError):
                        release.capabilities_shared_overlay(base,root,f.before)
                    kinds.clear()
                alias=f.ledger.with_name('synthetic-hard-link');os.link(f.ledger,alias)
                try:
                    with self.assertRaisesRegex(ValueError,'native_shared_source_boundary_drift'):
                        release.capabilities_shared_overlay(base,root,f.before)
                finally:alias.unlink()
                original_fstat=os.fstat;ledger_identity=(f.ledger.stat().st_dev,f.ledger.stat().st_ino)
                for field in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink','st_uid','st_gid','st_mode'):
                    def changed(fd):
                        info=original_fstat(fd)
                        if (info.st_dev,info.st_ino)!=ledger_identity:return info
                        values={k:getattr(info,k) for k in dir(info) if k.startswith('st_')}
                        values[field]=getattr(info,field)+1
                        return SimpleNamespace(**values)
                    with self.subTest(field=field),patch.object(os,'fstat',changed),self.assertRaisesRegex(ValueError,'native_shared_source_changed'):
                        release.capabilities_shared_overlay(base,root,f.before)
                self.assertEqual(f.ledger.read_bytes(),audit)

    def test_native_capabilities_static_overlay_requires_exact_success(self):
        base=release.frozen();html='/var/www/dashboard/fs-home/hermes/conversation/index.html'
        metadata={html:dict(path=html,sha256=release.COMPOSER_BEFORE_SHA,owner='0:0',mode='0o644')}
        metadata.update({('/opt/static/'+str(i)):dict(path='/opt/static/'+str(i),sha256='a'*64,owner='0:0',mode='0o644') for i in range(778)})
        row=dict(candidate='frontend/index.html',target=html,beforeSha256=release.COMPOSER_BEFORE_SHA,sha256=release.COMPOSER_AFTER_SHA,owner='0:0',mode='0o644')
        manifest=dict(sourceCommit=release.CAPABILITIES_STATIC_PROOF['sourceCommit'],scope=release.SCOPE,nativeComposerStatic=True,materialStaticOnly=True,files=[row],unchangedRequired=[v for p,v in metadata.items() if p!=html])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);proof=dict(release.CAPABILITIES_STATIC_PROOF);backup=base.rooted(root,proof['backup']);backup.mkdir(parents=True)
            def save(candidate,**journal_changes):
                raw=json.dumps(candidate).encode();(backup/'approved-manifest.json').write_bytes(raw);proof['manifestSha256']=prepare.digest(raw)
                journal=dict(manifest=candidate,status='applied-awaiting-actual-http-role-acceptance',approvedManifestSha256=proof['manifestSha256'],files=[dict(candidate['files'][0],intent=True,written=True)])
                journal.update(journal_changes);raw=json.dumps(journal).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
            with patch.object(release,'CAPABILITIES_STATIC_PROOF',proof):
                save(manifest);result=release.capabilities_static_overlay(base,root,metadata)
                self.assertEqual(result[html]['sha256'],release.COMPOSER_AFTER_SHA)
                self.assertEqual({p:v for p,v in result.items() if p!=html},{p:v for p,v in metadata.items() if p!=html})
                for change in (lambda m:m.update(sourceCommit='0'*40),lambda m:m['files'][0].update(beforeSha256='0'*64),
                               lambda m:m['unchangedRequired'].pop(),lambda m:m['unchangedRequired'].append(m['unchangedRequired'][0]),
                               lambda m:m['unchangedRequired'][0].update(sha256='0'*64),lambda m:m['unchangedRequired'][0].update(mode='0o666')):
                    bad=deepcopy(manifest);change(bad);save(bad)
                    with self.assertRaisesRegex(ValueError,'native_static_'):release.capabilities_static_overlay(base,root,metadata)
                save(manifest,status='rolled-back')
                with self.assertRaises(ValueError):release.capabilities_static_overlay(base,root,metadata)
                save(manifest,files=[dict(row,intent=True,written=True,rollbackIntent=True)])
                with self.assertRaises(ValueError):release.capabilities_static_overlay(base,root,metadata)
                save(manifest);(backup/'journal.json').write_bytes(b'altered proof')
                with self.assertRaisesRegex(ValueError,'native_static_successful_proof_drift'):release.capabilities_static_overlay(base,root,metadata)

    def test_archive_three_source_original_apply_rollback_and_locked_maintenance(self):
        self._archive_apply_contract()

    def _archive_apply_contract(self, capabilities=False):
        for failure in ((None,'desktop','range','readiness') if capabilities and any(n in release.DESKTOP_TARGETS for n in release.CAPABILITIES_CHANGED) else (None,'range','readiness')):
            self.tearDown();self.setUp()
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory,self.admission_fixture(Path(directory)) as f,ExitStack() as proof_stack:
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
                    p=base.rooted(f.system,target);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(self.desktop_before_bytes('http/range_api.py') if capabilities and target==release.DESKTOP_TARGETS['http/range_api.py'] else ('live:'+str(i)).encode())
                    records.append(dict(candidate='live/'+str(i),target=target,sha256=base.digest(p),beforeSha256='0'*64,owner='0:0',mode='0o600' if target==release.NGINX else '0o644'))
                fc_paths={'/opt/fc27-cloud-browser/fc_pricing_v3/sources.py','/opt/fs-hermes-fc/fc_pricing_v3/sources.py','/opt/fc27-cloud-browser/server_quote_job.py'}
                eligible=[p for p in oldmap if p not in live_targets and p not in (release.TARGETS['runtime/conversation_store.py'],release.TARGETS['runtime/conversation_native.py'])]
                overlap=[p for p in eligible if p in fc_paths]+[p for p in eligible if p not in fc_paths]
                overlap=overlap[:49]
                keep=[{'path':p,'sha256':oldmap[p]} for p in overlap]
                for target in sorted(fc_paths-set(oldmap)):
                    path=base.rooted(f.system,target);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'old FC')
                    keep.append(dict(path=target,sha256=base.digest(path)))
                usage_path='/var/lib/fs-hermes-fc/profile/skills/.usage.json'
                usage=base.rooted(f.system,usage_path);usage.parent.mkdir(parents=True,exist_ok=True)
                usage.write_bytes(b'historical usage');usage.chmod(0o600);f.owners[usage]=(0,0,0o600)
                keep.append(dict(path=usage_path,sha256=base.digest(usage)))
                if capabilities:
                    for target in release.CAPABILITIES_NAVIGATION_TARGETS.values():
                        if target in oldmap or target in live_targets or any(r['path']==target for r in keep):continue
                        path=base.rooted(f.system,target);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'original shared static')
                        f.owners[path]=(0,0,0o644);keep.append(dict(path=target,sha256=base.digest(path)))
                    for target,body in zip(self.shared_update_paths(),(b'old reviewed skill',b'{"old":"ledger"}\n',b'')):
                        path=base.rooted(f.system,target);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
                        f.owners[path]=(0,0,0o644);keep.append(dict(path=target,sha256=base.digest(path)))
                while len(keep)<743:
                    p='/opt/live-protected/file'+str(len(keep))+'.py';target=base.rooted(f.system,p);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'live protected')
                    keep.append(dict(path=p,sha256=base.digest(target)))
                previous=dict(sourceCommit=release.INSTALLED_PROOF['sourceCommit'],scope='user-admin-live-page-20261102',files=records,unchangedRequired=keep)
                proof=deepcopy(release.INSTALLED_PROOF);backup=base.rooted(f.system,proof['backup']);backup.mkdir(parents=True)
                raw=json.dumps(previous).encode();(backup/'approved-manifest.json').write_bytes(raw);proof['manifestSha256']=prepare.digest(raw)
                journal=dict(status='applied-awaiting-actual-http-role-acceptance',manifest=previous,approvedManifestSha256=proof['manifestSha256'])
                raw=json.dumps(journal).encode();(backup/'journal.json').write_bytes(raw);proof['journalSha256']=prepare.digest(raw)
                merged=dict(oldmap);merged.update({r['path']:r['sha256'] for r in keep})
                fc_proof,fc_files=self.archive_fc_fixture(f.system,base,merged,f.owners)
                if capabilities:
                    # Already installed archive-aware release with its exact static protection union.
                    for name in release.TARGETS:
                        target=base.rooted(f.system,release.TARGETS[name])
                        target.write_bytes(source_body if name=='runtime/conversation_store.py' else self.diagnostic_installed_bytes(name) if name in ('runtime/transport.py','runtime/proxy_gateway.py') else self.setup_installed_bytes(name) if name=='runtime/conversation_service.py' else self.plain_reply_installed_bytes(name) if name=='http/conversation_http.py' else target.read_bytes()+b'\n# installed archive aware\n')
                    current=dict(merged);current.update({r['target']:r['sha256'] for r in records});current.update({target:sha for target,sha in fc_files.values()})
                    installed_targets=dict(release.CAPABILITIES_RUNTIME_TARGETS)
                    for name,target in installed_targets.items():
                        if target in current:continue
                        # These two existed in the pre-relay protected union;
                        # the four relay helpers were installed by bd9 itself.
                        if name in ('runtime/b2_customer_followup.py','runtime/user_runtime.py'):
                            filler=next(p for p in current if p.startswith('/opt/live-protected/'))
                            del current[filler]
                        path=base.rooted(f.system,target);path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_bytes(b'# installed promoted consumer\n');f.owners[path]=(0,0,0o644)
                        current[target]=base.digest(path)
                    html_path='/var/www/dashboard/fs-home/hermes/conversation/index.html'
                    html=(prepare.HERE.parent/'frontend/index.html').read_text('utf-8').encode('utf-8')
                    html_target=base.rooted(f.system,html_path)
                    html_target.write_bytes(html)
                    self.assertEqual(base.digest(html_target),release.COMPOSER_AFTER_SHA)
                    current[html_path]=base.digest(html_target)
                    self.assertEqual(len(current),783)
                    def metadata(path):
                        info=base.rooted(f.system,path).stat()
                        return dict(path=path,sha256=current[path],owner=str(info.st_uid)+':'+str(info.st_gid),mode=oct(stat.S_IMODE(info.st_mode)))
                    # The two read-only daily consumers keep their real 051f Git identity throughout history.
                    for name in ('runtime/user_runtime.py','runtime/a2_query_context.py'):
                        target=installed_targets[name];path=base.rooted(f.system,target)
                        path.write_bytes(self.customer_daily_source_bytes(name,'before'));current[target]=base.digest(path)
                    cap_rows=[dict(candidate=name,target=target,beforeSha256='0'*64,sha256=base.digest(base.rooted(f.system,target)),owner='0:0',mode='0o644') for name,target in installed_targets.items()]
                    current.update({r['target']:r['sha256'] for r in cap_rows})
                    static_proof=deepcopy(release.CAPABILITIES_STATIC_PROOF)
                    cap_manifest=dict(sourceCommit=release.CAPABILITIES_HISTORY_PROOF['sourceCommit'],scope=release.SCOPE,nativeArchive=True,nativeCapabilities=True,
                        nativeStaticBaseline=static_proof,files=cap_rows,unchangedRequired=[metadata(p) for p in current if p not in installed_targets.values()])
                    history_proof=self.save_capabilities_receipt(base,f.system,release.CAPABILITIES_HISTORY_PROOF,cap_manifest,f.owners)
                    proof_stack.enter_context(patch.object(release,'CAPABILITIES_HISTORY_PROOF',history_proof))
                    # Current successful 3c45 proof already protects this route;
                    # historical receipt remains verified without reassigning any SHA.
                    nginx=base.rooted(f.system,release.NGINX)
                    advanced_nginx=nginx.read_bytes()
                    nginx_proof=proof_stack.enter_context(self.capabilities_nginx_fixture(f.system,base,
                        before=prepare.digest(b'historical route before transition'),after=current[release.NGINX]))
                    for path in nginx_proof.backup.iterdir():f.owners[path]=(0,0,0o600)
                    navigation=proof_stack.enter_context(self.capabilities_navigation_fixture(f.system,base,
                        {p:metadata(p) for p in current},f.owners,materialize=True,range_body=self.desktop_before_bytes('http/range_api.py')))
                    current.update({p:r['sha256'] for p,r in navigation.after.items()})
                    advanced_nginx=nginx.read_bytes()
                    shared=proof_stack.enter_context(self.shared_update_fixture(f.system,base,f.owners))
                    current.update({p:r['sha256'] for p,r in shared.after.items()})
                    cap_manifest=dict(cap_manifest,sourceCommit=release.CAPABILITIES_PREVIOUS_PROOF['sourceCommit'],
                        unchangedRequired=[dict(r,**metadata(r['path'])) for r in cap_manifest['unchangedRequired']])
                    previous_proof=self.save_capabilities_receipt(base,f.system,release.CAPABILITIES_PREVIOUS_PROOF,cap_manifest,f.owners)
                    proof_stack.enter_context(patch.object(release,'CAPABILITIES_PREVIOUS_PROOF',previous_proof))
                    with patch.object(store_module,'SYNTHETIC_ARCHIVE',pins):archived_before=store.archive_synthetic_unknown(owner)
                    prepare.configure_native_capabilities()
                    for name,target in release.CAMPAIGN_TARGETS.items():
                        body=self.campaign_before_bytes(name)
                        path=base.rooted(f.system,target);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
                        f.owners[path]=(0,0,0o644);current[target]=prepare.digest(body)
                    installed_rows=[dict(r,beforeSha256=r['sha256']) for r in cap_manifest['files']]
                    installed_rows.extend(dict(candidate=n,target=p,beforeSha256=release.CAMPAIGN_INITIAL_BEFORE[n][0],
                        sha256=current[p],owner='0:0',mode='0o644') for n,p in release.CAMPAIGN_TARGETS.items())
                    old_service=json.loads(Path(__file__).with_name('campaign-before-698.json').read_bytes())['files']['campaign/backend/campaign_backend/services.py']['utf8'].encode()
                    next(r for r in installed_rows if r['candidate']=='campaign/backend/campaign_backend/services.py')['sha256']=prepare.digest(old_service)
                    grant_history_manifest=dict(cap_manifest,sourceCommit=release.CAPABILITIES_GRANT_HISTORY_PROOF['sourceCommit'],files=installed_rows)
                    grant_history_proof=self.save_capabilities_receipt(base,f.system,release.CAPABILITIES_GRANT_HISTORY_PROOF,grant_history_manifest,f.owners)
                    proof_stack.enter_context(patch.object(release,'CAPABILITIES_GRANT_HISTORY_PROOF',grant_history_proof))
                    installed_rows=[dict(r,beforeSha256=r['sha256'],sha256=current[r['target']]) for r in installed_rows]
                    grant='campaign/backend/campaign_backend/coupon_grant.py';target=release.TARGETS[grant]
                    body=self.campaign_before_bytes(grant);path=base.rooted(f.system,target);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
                    f.owners[path]=(0,0,0o644);current[target]=prepare.digest(body)
                    installed_rows.append(dict(candidate=grant,target=target,beforeSha256=None,sha256=current[target],owner='0:0',mode='0o644'))
                    import_history_manifest=dict(cap_manifest,sourceCommit=release.CAPABILITIES_IMPORT_HISTORY_PROOF['sourceCommit'],files=installed_rows)
                    import_history_proof=self.save_capabilities_receipt(base,f.system,release.CAPABILITIES_IMPORT_HISTORY_PROOF,import_history_manifest,f.owners)
                    proof_stack.enter_context(patch.object(release,'CAPABILITIES_IMPORT_HISTORY_PROOF',import_history_proof))
                    user_data=base.rooted(f.system,release.TARGETS['runtime/conversation_user_data.py'])
                    user_data.write_bytes(user_data.read_bytes()+b'\n# installed import dependency\n');current[release.TARGETS['runtime/conversation_user_data.py']]=base.digest(user_data)
                    installed_rows=[dict(r,beforeSha256=r['sha256'],sha256=current[r['target']]) for r in installed_rows]
                    transport_manifest=dict(cap_manifest,sourceCommit=release.CAPABILITIES_TRANSPORT_HISTORY_PROOF['sourceCommit'],files=installed_rows)
                    transport_proof=self.save_capabilities_receipt(base,f.system,release.CAPABILITIES_TRANSPORT_HISTORY_PROOF,transport_manifest,f.owners)
                    proof_stack.enter_context(patch.object(release,'CAPABILITIES_TRANSPORT_HISTORY_PROOF',transport_proof))
                    # The two changed runtime before files are exact installed
                    # 193 Git bytes frozen before the offline runner starts.
                    for name in ('runtime/conversation_native.py','runtime/hermes_worker.py'):
                        target=release.TARGETS[name];base.rooted(f.system,target).write_bytes(self.knowledge_before_bytes(name));current[target]=base.digest(base.rooted(f.system,target))
                        next(r for r in installed_rows if r['candidate']==name).update(sha256=current[target])
                        next(r for r in transport_manifest['files'] if r['candidate']==name).update(sha256=current[target])
                    # Save the actual unchanged runtime relationship in fb70,
                    # then the one-URL grant transition in 193.
                    transport_proof.update(self.save_capabilities_receipt(base,f.system,transport_proof,transport_manifest,f.owners))
                    body=self.campaign_before_bytes(grant).replace(b"url='https://admin-api.p2pah.cn'+self.route",b"url='http://127.0.0.1:8912'+self.route")
                    base.rooted(f.system,release.TARGETS[grant]).write_bytes(body);current[release.TARGETS[grant]]=prepare.digest(body)
                    installed_rows=[dict(r,beforeSha256=r['sha256'],sha256=current[r['target']]) for r in installed_rows]
                    cap_manifest=dict(cap_manifest,sourceCommit=release.CAPABILITIES_KNOWLEDGE_HISTORY_PROOF['sourceCommit'],files=installed_rows)
                    knowledge_proof=self.save_capabilities_receipt(base,f.system,release.CAPABILITIES_KNOWLEDGE_HISTORY_PROOF,cap_manifest,f.owners)
                    proof_stack.enter_context(patch.object(release,'CAPABILITIES_KNOWLEDGE_HISTORY_PROOF',knowledge_proof))
                    knowledge_rows=[]
                    for name,target in release.KNOWLEDGE_INSTALLED_TARGETS.items():
                        prior=release.KNOWLEDGE_INITIAL_EXISTING.get(name,(current.get(target),))[0]
                        if name in ('runtime/conversation_native.py','runtime/hermes_worker.py') or target not in current:
                            path=base.rooted(f.system,target);path.parent.mkdir(parents=True,exist_ok=True)
                            path.write_bytes((Path(__file__).resolve().parents[4]/prepare.SOURCES[name]).read_bytes());f.owners[path]=(0,0,0o644);current[target]=base.digest(path)
                        knowledge_rows.append(dict(candidate=name,target=target,beforeSha256=prior,sha256=current[target],owner='0:0',mode='0o644'))
                    # Range was protected in all earlier receipts: freeze its real bytes
                    # before saving those receipts rather than manufacturing a new before.
                    cap_manifest=dict(cap_manifest,files=knowledge_rows)
                    desktop=self.desktop_installed_fixture(base,f.system,cap_manifest,f.owners,proof_stack,materialize=True)
                    proof=desktop.proof;current.update({r['target']:r['sha256'] for r in desktop.manifest['files']})
                    current[release.NGINX]=desktop.nav['sha256'];advanced_nginx=desktop.nav_body
                    # frozen() captures NEW at construction; this reused fixture
                    # base predates mode selection, unlike the staged runtime.
                    base.MATERIAL_NEW=release.NEW
                    before_cap={name:None if name in release.NEW else current[target] for name,target in release.TARGETS.items()}
                    compat_store_sha=current[release.TARGETS['runtime/conversation_store.py']]
                descriptor=json.loads((f.payload.parent/'payload-manifest.json').read_bytes())
                descriptor.update(native_admission=False,native_archive=not capabilities,native_capabilities=capabilities,native_chat=False,installed_baseline={'source_commit':release.INSTALLED_COMMIT,'files':{name:oldmap.get(target) for name,target in release.TARGETS.items()}})
                if capabilities:
                    daily=proof_stack.enter_context(self.customer_daily_fixture(f.system,base,f.owners))
                    for name in ('runtime/user_runtime.py','runtime/a2_query_context.py'):
                        self.assertEqual(before_cap[name],prepare.digest(self.customer_daily_source_bytes(name,'before')))
                        body=self.customer_daily_source_bytes(name,'after')
                        base.rooted(f.system,release.TARGETS[name]).write_bytes(body);before_cap[name]=prepare.digest(body)
                    descriptor['installed_baseline']['files']=before_cap
                    descriptor['installed_baseline']['source_overlays']={n:'7312aa3170724ba31dd12aedf1fd92dbe7bc7578' for n in ('runtime/user_runtime.py','runtime/a2_query_context.py')}
                descriptor['files']={key:value for key,value in descriptor['files'].items() if not key.startswith('payload/')}
                for name in prepare.SOURCES:
                    p=f.payload/name;p.parent.mkdir(parents=True,exist_ok=True)
                    p.write_bytes(((Path(__file__).resolve().parents[4]/prepare.SOURCES[name]).read_bytes() if name in release.CAPABILITIES_CHANGED else base.rooted(f.system,release.TARGETS[name]).read_bytes()) if capabilities else source_body if name=='runtime/conversation_store.py' else (base.rooted(f.system,release.TARGETS[name]).read_bytes()+b'\n# archive consumer\n'))
                    descriptor['files']['payload/'+name]=prepare.digest(p.read_bytes())
                raw=json.dumps(descriptor).encode();(f.payload.parent/'payload-manifest.json').write_bytes(raw)
                stage=root/'archive-stage'
                if capabilities:
                    # Historical manifests stay pinned to the approved two-row checkpoint;
                    # current complete audit bytes, including later rows, must reach CAS.
                    approved_checkpoint=shared.ledger.read_bytes()
                    recorded_audit=approved_checkpoint+b'{"action":"read","skill":"unrelated"}\n'
                    recorded_manifest=json.loads((base.rooted(f.system,proof['backup'])/'approved-manifest.json').read_bytes())
                    for entry in recorded_manifest['unchangedRequired']:
                        if entry['path']==release.CAPABILITIES_CURATOR_LEDGER:entry['sha256']=prepare.digest(recorded_audit)
                    recorded_proof=self.save_capabilities_receipt(base,f.system,proof,recorded_manifest,f.owners)
                    proof.update(recorded_proof)
                    # A subsequent valid row must preserve the prior release's complete audit prefix.
                    complete_audit=recorded_audit+b'{"action":"read","skill":"later"}\n'
                    shared.ledger.write_bytes(complete_audit)
                    current[release.CAPABILITIES_CURATOR_LEDGER]=prepare.digest(complete_audit)
                usage.write_bytes(b'fresh usage before prepare')
                with patch.object(release,'INSTALLED_PROOF',proof),patch.object(prepare,'INSTALLED_PROOF',proof),patch.object(release,'ARCHIVE_NATIVE_PROOF',old_proof),patch.object(release,'ARCHIVE_FC_PROOF',fc_proof,create=True),patch.object(release,'ARCHIVE_FC_FILES',fc_files,create=True),patch.object(release,'CAPABILITIES_STATIC_PROOF',static_proof if capabilities else release.CAPABILITIES_STATIC_PROOF):
                    static=base.rooted(f.system,keep[0]['path']);saved_static=static.read_bytes()
                    static.write_bytes(b'unapproved static change')
                    with self.assertRaisesRegex(ValueError,'installed_protected_baseline_drift'):
                        prepare.prepare(f.payload,root/'static-rejected','a'*40,prepare.digest(raw),root=f.system,followup=True,release_ready=True)
                    static.write_bytes(saved_static)
                    if capabilities:
                        rewritten=approved_checkpoint+b'{"action":"rewritten"}\n{"action":"read","skill":"later"}\n'
                        shared.ledger.write_bytes(rewritten)
                        with self.assertRaisesRegex(ValueError,'native_shared_ledger_drift'):
                            prepare.prepare(f.payload,root/'rewritten-audit-rejected','a'*40,prepare.digest(raw),root=f.system,followup=True,release_ready=True)
                        shared.ledger.write_bytes(complete_audit)
                    for owner_mode in ((9876,0,0o600),(0,9876,0o600),(0,0,0o644)):
                        f.owners[usage]=owner_mode
                        with self.subTest(owner_mode=owner_mode),self.assertRaisesRegex(ValueError,'archive_usage_boundary_drift'):
                            prepare.prepare(f.payload,root/'usage-rejected','a'*40,prepare.digest(raw),root=f.system,followup=True,release_ready=True)
                    f.owners[usage]=(0,0,0o600)
                    if capabilities:
                        if failure is None:
                            for name in release.NEW:
                                path=base.rooted(f.system,release.TARGETS[name]);path.write_bytes(b'unexpected existing helper');f.owners[path]=(0,0,0o644)
                                with self.assertRaisesRegex(ValueError,'desktop_new_target_already_exists'):
                                    prepare.prepare(f.payload,root/'existing-new-rejected','a'*40,prepare.digest(raw),root=f.system,followup=True,release_ready=True)
                                path.unlink();f.owners.pop(path)
                        for zero,extra in ((True,False),(False,True)):
                            names=tuple(n for n in release.CAPABILITIES_CHANGED if n not in release.NEW) if zero else ('runtime/conversation_store.py',)
                            saved={name:(f.payload/name).read_bytes() for name in names}
                            bad_descriptor=deepcopy(descriptor)
                            for name in names:
                                body=base.rooted(f.system,release.TARGETS[name]).read_bytes()+(b'\n# unauthorized third delta' if extra else b'')
                                (f.payload/name).write_bytes(body);bad_descriptor['files']['payload/'+name]=prepare.digest(body)
                            bad_raw=json.dumps(bad_descriptor).encode();(f.payload.parent/'payload-manifest.json').write_bytes(bad_raw)
                            with self.assertRaisesRegex(ValueError,'exact_material_diagnostics_delta_required'):
                                prepare.prepare(f.payload,root/('zero-delta' if zero else 'extra-delta'),'a'*40,prepare.digest(bad_raw),root=f.system,followup=True,release_ready=True)
                            for name,body in saved.items():(f.payload/name).write_bytes(body)
                            (f.payload.parent/'payload-manifest.json').write_bytes(raw)
                    prepare.prepare(f.payload,stage,'a'*40,prepare.digest(raw),root=f.system,followup=True,release_ready=True)
                manifest=json.loads((stage/'approved-manifest.json').read_bytes());self.assertEqual(len(manifest['files']),32 if capabilities else 3);self.assertEqual(len(manifest['unchangedRequired']),766 if capabilities else 776)
                untouched={r['path']:(base.rooted(f.system,r['path']).read_bytes(),base.rooted(f.system,r['path']).stat().st_ino,base.rooted(f.system,r['path']).stat().st_mtime_ns) for r in manifest['unchangedRequired']}
                if capabilities:
                    ledger_row=next(r for r in manifest['unchangedRequired'] if r['path']==release.CAPABILITIES_CURATOR_LEDGER)
                    self.assertEqual(ledger_row['sha256'],prepare.digest(complete_audit))
                    self.assertNotEqual(ledger_row['sha256'],shared.proof['ledger_after'])
                    self.assertEqual(shared.ledger.read_bytes(),complete_audit)
                    self.assertEqual(manifest['nativeStaticBaseline'],static_proof)
                    self.assertEqual(manifest['materialChangedTargets'],[release.TARGETS[n] for n in release.CAPABILITIES_CHANGED])
                    for row in manifest['files']:
                        if row['candidate'] not in release.CAPABILITIES_CHANGED:
                            path=base.rooted(f.system,row['target']);untouched[row['target']]=(path.read_bytes(),path.stat().st_ino,path.stat().st_mtime_ns)
                    self.assertEqual(len(untouched),796)
                    changed=[r for r in manifest['files'] if r['beforeSha256']!=r['sha256']]
                    service_after=(Path(__file__).resolve().parents[4]/prepare.SOURCES['runtime/conversation_service.py']).read_bytes()
                    self.assertEqual([(r['candidate'],r['beforeSha256'],r['sha256']) for r in changed],[('runtime/conversation_service.py','80fdbae538933026fde0185642283ffe12cef34a1a674a38b8d40dfb7c69ad2f',prepare.digest(service_after)),('http/conversation_http.py','8d577e8493cabc2847604ab77e7539bb215c947cee842000acc86878bc2ba44d','5c750b27097a7a95a7986f6e8cb2def6a29b541db8c54e3d68592c1b601c6d86')])
                    self.assertFalse(release.NEW)
                    self.assertEqual({row['candidate'] for row in manifest['files'] if row['beforeSha256'] is None},set(release.NEW))
                untouched_modes={p:(base.rooted(f.system,p).stat().st_uid,base.rooted(f.system,p).stat().st_gid,stat.S_IMODE(base.rooted(f.system,p).stat().st_mode)) for p in untouched}
                spec=importlib.util.spec_from_file_location('archive_publisher_fixture',stage/'runtime_release.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                module.configure_native_capabilities() if capabilities else module.configure_native_archive();module.INSTALLED_PROOF=proof;module.ARCHIVE_NATIVE_PROOF=old_proof
                if capabilities:
                    module.CUSTOMER_DAILY_PROOF=daily.proof
                    module.CAPABILITIES_STORE_BEFORE_SHA=compat_store_sha;module.CAPABILITIES_STATIC_PROOF=static_proof
                    module.CAPABILITIES_PREVIOUS_PROOF=previous_proof
                    module.CAPABILITIES_GRANT_HISTORY_PROOF=grant_history_proof
                    module.CAPABILITIES_IMPORT_HISTORY_PROOF=import_history_proof
                    module.CAPABILITIES_TRANSPORT_HISTORY_PROOF=transport_proof
                    module.CAPABILITIES_KNOWLEDGE_HISTORY_PROOF=knowledge_proof
                    module.CAPABILITIES_DESKTOP_HISTORY_PROOF=desktop.history
                    module.CAPABILITIES_DESKTOP_INSTALL_PROOF=desktop.initial_proof
                    module.CAPABILITIES_DESKTOP_WS_PROOF=desktop.ws_proof
                    module.CAPABILITIES_DESKTOP_TIME_PROOF=desktop.time_proof
                    module.CAPABILITIES_DESKTOP_SETUP_PROOF=desktop.setup_proof
                    module.CAPABILITIES_DIAGNOSTIC_HISTORY_PROOF=desktop.diagnostic_history
                    module.CAPABILITIES_RETRY_HISTORY_PROOF=desktop.retry_history
                    module.NATIVE_CAPABILITIES_PROOF=desktop.proof
                    module.DESKTOP_MODE_CORRECTION_SHA=desktop.mode_sha
                    module.DESKTOP_NAVIGATION_PROOF=desktop.nav
                    module.CAPABILITIES_NGINX_PROOF=nginx_proof.proof
                    module.CAPABILITIES_NAVIGATION_PROOFS=navigation.proofs
                    module.CAPABILITIES_SHARED_PROOF=shared.proof
                    module.CAPABILITIES_HISTORY_PROOF=history_proof
                module.ARCHIVE_FC_PROOF=fc_proof;module.ARCHIVE_FC_FILES=fc_files
                base.hermes_quiescent=Mock();base.retirement=Mock();base.locks=base.live_lock=base.model_release_lock=lambda *a:nullcontext()
                fence=SimpleNamespace(modified=False,confirmed=False,stop_then_unlock_database=Mock());base.hermes_admission_fence=lambda *a:nullcontext(fence)
                effects=([RuntimeError('synthetic range failure'),None] if capabilities else [RuntimeError('synthetic range failure'),None]) if failure=='range' else [RuntimeError('synthetic worker failure'),None,None] if failure=='worker' else None
                restart=Mock(side_effect=effects);base.restart_for=restart
                if os.name=='nt':base.directory_sync=lambda *a:None
                readiness=Mock(side_effect=[None,None,RuntimeError('synthetic readiness failure'),None] if failure=='readiness' else None)
                service_calls=[]
                def service_run(argv,**kwargs):
                    service_calls.append(argv)
                    if argv==['systemctl','restart','fs-hermes-desktop.service']:
                        count=service_calls.count(argv)
                        if failure=='desktop' and count==1:raise RuntimeError('synthetic campaign failure')
                        if failure and count>1:
                            for row in manifest['files']:
                                path=base.rooted(f.system,row['target']);self.assertEqual(base.digest(path) if path.exists() else None,row['beforeSha256'])
                    return SimpleNamespace(returncode=0,stdout='ActiveState=active\n')
                with patch.object(module,'frozen',return_value=base),patch.object(module,'running_worker'),patch.object(module,'native_runtime_readiness',readiness),patch.object(module.subprocess,'run',side_effect=service_run):
                    publisher=module.load_base();publisher.inspect(manifest,stage,f.system)
                    if capabilities:
                        if failure is None:
                            for name in (*release.NEW,'runtime/knowledge_catalog.py'):
                                path=base.rooted(f.system,release.TARGETS[name]);saved=path.read_bytes() if path.exists() else None
                                path.write_bytes(b'helper changed after prepare');f.owners[path]=(0,0,0o644)
                                with self.assertRaises(ValueError):publisher.inspect(manifest,stage,f.system)
                                if saved is None:path.unlink();f.owners.pop(path)
                                else:
                                    path.write_bytes(saved)
                                    if row_target:=next((r['target'] for r in manifest['files'] if r['candidate']==name and r['target'] in untouched),None):
                                        untouched[row_target]=(saved,path.stat().st_ino,path.stat().st_mtime_ns)
                        nginx_row=next(r for r in manifest['unchangedRequired'] if r['path']==release.NGINX)
                        self.assertEqual(nginx_row['sha256'],current[release.NGINX])
                        nginx.write_bytes(b'changed route after prepare')
                        with self.assertRaises(ValueError):publisher.inspect(manifest,stage,f.system)
                        rejected_raw=(stage/'approved-manifest.json').read_bytes()
                        with self.assertRaises(ValueError):
                            publisher.apply(manifest,stage,prepare.digest(rejected_raw),rejected_raw,'nav-20261103T000000Z',f.system)
                        nginx.write_bytes(advanced_nginx)
                        # The deliberate drift/restore above changes mtime;
                        # measure non-writing apply/rollback from this point.
                        untouched[release.NGINX]=(nginx.read_bytes(),nginx.stat().st_ino,nginx.stat().st_mtime_ns)
                        for protected_path in self.shared_update_paths():
                            path=base.rooted(f.system,protected_path);saved=path.read_bytes()
                            path.write_bytes(saved+(b'{"action":"read","skill":"late"}\n' if protected_path==release.CAPABILITIES_CURATOR_LEDGER else b'x'))
                            with self.assertRaises(ValueError):publisher.inspect(manifest,stage,f.system)
                            rejected_raw=(stage/'approved-manifest.json').read_bytes()
                            with self.assertRaises(ValueError):publisher.apply(manifest,stage,prepare.digest(rejected_raw),rejected_raw,'nav-20261103T000000Z',f.system)
                            path.write_bytes(saved);untouched[protected_path]=(saved,path.stat().st_ino,path.stat().st_mtime_ns)
                    usage_row=next(r for r in manifest['unchangedRequired'] if r['path']==usage_path)
                    self.assertEqual((usage_row['sha256'],usage_row['owner'],usage_row['mode']),
                                     (base.digest(usage),'0:0','0o600'))
                    usage.write_bytes(b'changed after prepare')
                    with self.assertRaisesRegex(ValueError,'archive_usage_cas_drift'):
                        publisher.inspect(manifest,stage,f.system)
                    cas_raw=(stage/'approved-manifest.json').read_bytes()
                    with self.assertRaisesRegex(ValueError,'archive_usage_cas_drift'):
                        publisher.apply(manifest,stage,prepare.digest(cas_raw),cas_raw,'nav-20261103T000000Z',f.system)
                    for row in manifest['files']:
                        path=base.rooted(f.system,row['target']);self.assertEqual(base.digest(path) if path.exists() else None,row['beforeSha256'])
                    usage.write_bytes(b'fresh usage before prepare')
                    untouched[usage_path]=(usage.read_bytes(),usage.stat().st_ino,usage.stat().st_mtime_ns)
                    bad_manifest=deepcopy(manifest)
                    next(r for r in bad_manifest['unchangedRequired'] if r['path']!=usage_path)['sha256']='0'*64
                    with self.assertRaisesRegex(ValueError,'archive_static_protection_drift'):publisher.guards(bad_manifest,f.system)
                    bad_git=deepcopy(descriptor['installed_baseline']);bad_git['files']['runtime/conversation_native.py']='0'*64
                    with self.assertRaisesRegex(ValueError,'composer_static_installed_proof_mismatch' if capabilities else 'archive_installed_git_mismatch'):module.installed_baseline(f.system,bad_git)
                    if capabilities:
                        for overlays in ({},{'runtime/user_runtime.py':'7312aa3170724ba31dd12aedf1fd92dbe7bc7578'},
                                         dict(descriptor['installed_baseline']['source_overlays'],unexpected='7312aa3170724ba31dd12aedf1fd92dbe7bc7578'),
                                         dict(descriptor['installed_baseline']['source_overlays'],**{'runtime/user_runtime.py':'0'*40})):
                            bad_git=deepcopy(descriptor['installed_baseline']);bad_git['source_overlays']=overlays
                            with self.assertRaisesRegex(ValueError,'composer_static_installed_proof_mismatch'):module.installed_baseline(f.system,bad_git)
                        for name in descriptor['installed_baseline']['source_overlays']:
                            daily_row=next(r for r in manifest['files'] if r['candidate']==name)
                            self.assertEqual(daily_row['beforeSha256'],daily_row['sha256'])
                            self.assertEqual(daily_row['sha256'],prepare.digest(self.customer_daily_source_bytes(name,'after')))
                            path=base.rooted(f.system,daily_row['target']);saved=path.read_bytes();path.write_bytes(b'daily CAS drift')
                            with self.assertRaises(ValueError):publisher.inspect(manifest,stage,f.system)
                            path.write_bytes(saved);untouched[daily_row['target']]=(saved,path.stat().st_ino,path.stat().st_mtime_ns)
                        for bad_git in (dict(descriptor['installed_baseline'],source_commit='94b7c9fb0420817ce71115737e937cf7b69b8228'),
                                        dict(descriptor['installed_baseline'],files=dict(descriptor['installed_baseline']['files'],**{'runtime/conversation_user_data.py':None}))):
                            with self.assertRaisesRegex(ValueError,'composer_static_installed_proof_mismatch'):module.installed_baseline(f.system,bad_git)
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
                    elif capabilities:
                        publisher.apply(manifest,stage,prepare.digest(manifest_raw),manifest_raw,release_id,f.system)
                        saved=json.loads((base.rooted(f.system,'/var/backups/fs-navigation-20261006/'+release_id)/'journal.json').read_bytes())
                        module.archive_rollback_guard(base,saved,f.system)
                        bad=deepcopy(saved);next(r for r in bad['files'] if r['candidate']=='runtime/conversation_store.py')['beforeSha256']='0'*64
                        with self.assertRaisesRegex(ValueError,'archived_unknown_requires_archive_aware_forward_repair'):module.archive_rollback_guard(base,bad,f.system)
                        with self.assertRaisesRegex(ValueError,'exact_archive_maintenance_manifest_required'):module.archive_synthetic_maintenance(release_id,prepare.digest(manifest_raw),f.system)
                    else:
                        publisher.apply(manifest,stage,prepare.digest(manifest_raw),manifest_raw,release_id,f.system)
                        if capabilities and os.name=='posix':
                            self.assertEqual(stat.S_IMODE(os.stat(base.rooted(f.system,release.DESKTOP_CONFIG)).st_mode),0o600)
                        receipt=module.archive_synthetic_maintenance(release_id,prepare.digest(manifest_raw),f.system)
                        self.assertEqual((receipt['archived'],receipt['deleted'],receipt['outcome']),(1,0,'unknown'))
                        self.assertEqual(module.archive_synthetic_maintenance(release_id,prepare.digest(manifest_raw),f.system),receipt)
                        saved=json.loads((base.rooted(f.system,'/var/backups/fs-navigation-20261006/'+release_id)/'journal.json').read_bytes())
                        with self.assertRaisesRegex(ValueError,'archived_unknown_requires_archive_aware_forward_repair'):publisher.rollback_journal(base.rooted(f.system,'/var/backups/fs-navigation-20261006/'+release_id),saved,f.system)
                        with store.db() as db:db.execute("UPDATE synthetic_turn_archives SET receipt_sha256='drift'")
                        with self.assertRaisesRegex(ValueError,'archive_audit_drift'):publisher.guards(manifest,f.system)
                    self.assertTrue(all(c.args[0]['scope'] in ({base.DEEP_SCOPE,base.HERMES_WORKER_SCOPE} if capabilities else {base.DEEP_SCOPE}) for c in restart.call_args_list))
                    if capabilities and not failure:self.assertEqual([c.args[0]['scope'] for c in restart.call_args_list],[base.DEEP_SCOPE])
                    if capabilities:
                        self.assertEqual(['systemctl','restart','fs-hermes-desktop.service'] in service_calls,any(n in release.DESKTOP_TARGETS for n in release.CAPABILITIES_CHANGED))
                        self.assertTrue(all(argv[1] in ('show','restart','is-active') for argv in service_calls if argv[0]=='systemctl'))
                        self.assertTrue(all(argv[-1]=='fs-hermes-desktop.service' for argv in service_calls if argv[:2]==['systemctl','restart']))
                if capabilities:
                    with store.db() as db:self.assertEqual(json.loads(db.execute('SELECT receipt FROM synthetic_turn_archives WHERE turn_id=?',(turn['turn_id'],)).fetchone()[0]),archived_before)
                for p,values in untouched.items():self.assertEqual((base.rooted(f.system,p).read_bytes(),base.rooted(f.system,p).stat().st_ino,base.rooted(f.system,p).stat().st_mtime_ns),values)
                for p,values in untouched_modes.items():self.assertEqual((base.rooted(f.system,p).stat().st_uid,base.rooted(f.system,p).stat().st_gid,stat.S_IMODE(base.rooted(f.system,p).stat().st_mode)),values)
                if failure:
                    for row in manifest['files']:
                        path=base.rooted(f.system,row['target']);self.assertEqual(base.digest(path) if path.exists() else None,row['beforeSha256'])
                    if capabilities:
                        self.assertTrue(all(not base.rooted(f.system,release.TARGETS[name]).exists() for name in release.NEW))

    def test_archive_usage_requires_real_single_file_and_no_linked_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=release.frozen();path=base.rooted(root,release.ARCHIVE_USAGE_LEDGER)
            path.parent.mkdir(parents=True);path.write_bytes(b'usage');path.chmod(0o600)
            owners={path:(0,0,0o600)};kinds={}
            with self.native_metadata(owners,kinds,root=root):
                self.assertEqual(release.archive_usage_metadata(base,root)['sha256'],base.digest(path))
                alias=path.with_name('hard-link');os.link(path,alias)
                with self.assertRaisesRegex(ValueError,'archive_usage_boundary_drift'):release.archive_usage_metadata(base,root)
                alias.unlink()
                if os.name=='posix':
                    original=path.with_name('original');path.rename(original);path.symlink_to(original)
                    with self.assertRaises(ValueError):release.archive_usage_metadata(base,root)
                    path.unlink();original.rename(path)
                    parent=path.parent;original_parent=parent.with_name('original-skills');parent.rename(original_parent);parent.symlink_to(original_parent,target_is_directory=True)
                    with self.assertRaises(ValueError):release.archive_usage_metadata(base,root)
                    parent.unlink();original_parent.rename(parent)
                else:
                    # Windows path metadata fixture; Linux above uses real symlinks.
                    for linked in (path,path.parent):
                        kinds[linked]=stat.S_IFLNK
                        with self.assertRaises(ValueError):release.archive_usage_metadata(base,root)
                        kinds.clear()
                self.assertEqual(path.read_bytes(),b'usage')

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
        self._control_readiness_checks()

    def test_archive_readiness_uses_installed_dependencies_outside_three_targets(self):
        prepare.configure_native_archive()
        self.assertEqual(len(release.TARGETS),3)
        self.assertNotIn('runtime/native-backend.json',release.TARGETS)
        self.assertNotIn('approval/daily_review.py',release.TARGETS)
        self._control_readiness_checks()

    def _control_readiness_checks(self):
        # Execute the actual readiness function; only file and Docker IO are fixtures.
        contract=release.native_backend_bytes()
        mounts=[{'Destination':destination,'Source':source,'RW':rw} for destination,source,rw in (
            ('/opt/fs-native-bin/docker','/usr/bin/docker',False),
            ('/var/run/docker.sock','/run/docker.sock',True),
            (release.NATIVE_ROOT,release.NATIVE_ROOT,True),
            ('/opt/fs-native-backend-home',release.NATIVE_EMPTY_SOURCE,False),
            (release.NATIVE_DAILY_CONTAINER,release.NATIVE_EXTRA_TARGETS['approval/daily_review.py'],False))]
        user=['9876:9876'];failure=[False];version=['24.0.0|24.0.0']
        def observed(command,**kwargs):
            if '{{.Config.User}}' in command:return user[0]
            if 'version' in command:
                if failure[0]:raise OSError('synthetic daemon refusal')
                return version[0]
            return json.dumps(mounts)
        def read_contract(path):
            self.assertEqual(path,Path(release.NATIVE_EXTRA_TARGETS['runtime/native-backend.json']))
            return contract
        with patch.object(Path,'read_bytes',autospec=True,side_effect=read_contract),patch.object(Path,'is_symlink',return_value=False),patch.object(release.subprocess,'check_output',side_effect=observed):
            release.native_runtime_readiness()
            user[0]='0:0'
            with self.assertRaisesRegex(ValueError,'native_control_user_readback'):release.native_runtime_readiness()
            user[0]='9876:9876';mounts[0]['RW']=True
            with self.assertRaisesRegex(ValueError,'native_control_mount_readback'):release.native_runtime_readiness()
            mounts[0]['RW']=False;failure[0]=True
            with self.assertRaises(OSError):release.native_runtime_readiness()
            failure[0]=False;version[0]='invalid-version'
            with self.assertRaisesRegex(ValueError,'native_control_daemon_unavailable'):release.native_runtime_readiness()
            version[0]='24.0.0|24.0.0'
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
