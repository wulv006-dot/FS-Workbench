"""Synthetic publisher/SQLite checks; not real Linux modes, deployment or login."""
from contextlib import closing, nullcontext
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
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
    def test_material_stream_b362_existing_transport_delta_and_rollback(self):
        self.assertTrue(callable(getattr(prepare, 'configure_material_stream', None)),
                        'b362 existing-transport stream followup missing')
        self._transport_followup(stream=True)

    def test_transport_82edf_promoted_protection_delta_and_rollback(self):
        self._transport_followup(stream=False)

    def _transport_followup(self, stream):
        configure = prepare.configure_material_stream if stream else prepare.configure_material_transport
        marker = "materialStream" if stream else "materialTransport"
        before_key = "STREAM_BEFORE_SHA" if stream else "TRANSPORT_BEFORE_SHA"
        self.assertTrue(callable(getattr(prepare, 'configure_material_transport', None)), 'transport-only installed followup missing')
        names = ('TARGETS', 'NEW', 'INSTALLED_COMMIT', 'INSTALLED_PROOF', 'EXECUTION_MODE', 'DIAGNOSTICS_MODE', 'TASK_INDEX_MODE', 'WORKER_DIAGNOSTICS_MODE', 'TRANSPORT_MODE', 'STREAM_MODE')
        saved_release = {k: deepcopy(getattr(release, k)) for k in names}
        saved_prepare = {k: deepcopy(getattr(prepare, k)) for k in ('TARGETS', 'NEW', 'INSTALLED_COMMIT', 'INSTALLED_PROOF', 'SOURCES')}
        try:
            configure()
            self.assertEqual(release.STREAM_MODE, stream); self.assertEqual(release.TRANSPORT_MODE, not stream); self.assertFalse(release.WORKER_DIAGNOSTICS_MODE); self.assertFalse(release.TASK_INDEX_MODE); self.assertFalse(release.DIAGNOSTICS_MODE)
            self.assertEqual(release.NEW, frozenset())
            if stream:
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
                self.assertEqual(descriptor['material_stream'], stream)
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
                    descriptor.update(material_execution=True, material_diagnostics=False, goal_task_index_compat=False, worker_diagnostics=False, material_transport=not stream, material_stream=stream)
                    for name in prepare.SOURCES:
                        before = base.rooted(system, release.TARGETS[name]).read_bytes()
                        body = before+b'\n# material transport\n' if name == 'runtime/transport.py' else before
                        (payload/name).write_bytes(body); descriptor['files']['payload/'+name] = prepare.digest(body)
                    raw = json.dumps(descriptor).encode(); descriptor_path.write_bytes(raw)
                    stage = root/'transport-stage'
                    with patch.object(release, 'INSTALLED_PROOF', proof), patch.object(prepare, 'INSTALLED_PROOF', proof), \
                            patch.object(prepare, 'file_metadata', metadata), \
                            patch.object(release, before_key, transport_row['sha256']):
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
                            if case == 'old_proof': changed['installed_baseline']['source_commit'] = '82edf03573c3fed796d7a7ed2784134c5dd1f7ec' if stream else 'f79e29f0d5921b103a218c5e6ed967a754858b9c'
                            elif case == 'mixed_mode':changed['material_transport' if stream else 'material_stream']=True
                            elif case == 'missing_execution':changed['material_execution']=False
                            elif case == 'git': changed['installed_baseline']['files']['runtime/transport.py'] = '0'*64
                            else:
                                path = (payload/'runtime/transport.py' if case == 'no_delta' else payload/'http/conversation_http.py' if case == 'extra_http' else
                                        base.rooted(system, proof['backup']+'/journal.json') if case == 'journal' else
                                        base.rooted(system, previous['unchangedRequired'][0]['path']) if case == 'protected' else
                                        base.rooted(system, release.TARGETS['runtime/transport.py']))
                                restore = (path, path.read_bytes())
                                path.write_bytes(base.rooted(system, release.TARGETS['runtime/transport.py']).read_bytes() if case == 'no_delta' else b'unapproved drift')
                                if case == 'extra_http': changed['files']['payload/http/conversation_http.py'] = prepare.digest(path.read_bytes())
                                if case == 'no_delta': changed['files']['payload/runtime/transport.py'] = prepare.digest(path.read_bytes())
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
                    target = release.TARGETS['runtime/transport.py']
                    self.assertEqual(manifest['materialChangedTargets'], [target])
                    unchanged = {r['target']:(base.rooted(system,r['target']).stat().st_ino,base.rooted(system,r['target']).stat().st_mtime_ns)
                                 for r in manifest['files'] if r['target'] != target}
                    spec = importlib.util.spec_from_file_location('material_transport_publisher', stage/'runtime_release.py')
                    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                    (module.configure_material_stream if stream else module.configure_material_transport)()
                    module.INSTALLED_PROOF = proof; setattr(module, before_key, transport_row['sha256'])
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
                        for error in ('protection_missing','protection_duplicate','extra_target','mode','owner','before','expired','mixed_mode','zero_delta','duplicate_target'):
                            altered=deepcopy(manifest)
                            if error=='protection_missing':altered['unchangedRequired'].pop()
                            elif error=='protection_duplicate':altered['unchangedRequired'].append(deepcopy(altered['unchangedRequired'][0]))
                            elif error=='extra_target':altered['files'].append({'candidate':'runtime/unrelated.py','target':'/opt/unrelated.py','beforeSha256':'a'*64,'sha256':'b'*64})
                            elif error in ('mode','owner','before'):
                                row=next(r for r in altered['files'] if r['candidate']=='runtime/transport.py')
                                row[{'mode':'mode','owner':'owner','before':'beforeSha256'}[error]]={'mode':'0o600','owner':'1:1','before':'0'*64}[error]
                            elif error=='expired':altered['baselineObservedAt']=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
                            elif error=='mixed_mode':altered['materialTransport' if stream else 'materialStream']=True
                            elif error=='duplicate_target':altered['files'].append(deepcopy(altered['files'][0]))
                            else:
                                row=next(r for r in altered['files'] if r['candidate']=='runtime/transport.py');row['sha256']=row['beforeSha256'];altered['materialChangedTargets']=[]
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


if __name__ == '__main__':
    unittest.main()
