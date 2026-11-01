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
