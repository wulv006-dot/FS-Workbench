"""Prepare the learning image context and a blocked preview; --build is explicit.

No image build, service operation or publication occurs without --build. Even a verified
build remains releaseReady=false and must use the existing publisher after approval.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = Path('releases/fs-dashboard/hermes-learning-closure-20261023/deploy')
NATIVE = Path('releases/fs-dashboard/hermes-server-unify-20261022')
SKILLS = Path('releases/fs-dashboard/hermes-memory-approval-20261022/reviewed_skills.py')
OLD_DEPLOY = Path('releases/fs-dashboard/knowledge-layering-20261023/deploy')
COMMIT_INPUTS = (NATIVE / 'fs_native_entry.py', NATIVE / 'patch_factory.py', SKILLS,
    DEPLOY / 'Dockerfile.native', DEPLOY / 'native_release.py', Path('tools/prepare_learning_native_release.py'),
    NATIVE / 'fs_readonly/knowledge.py', NATIVE / 'fs_readonly/__init__.py',
    Path('releases/fs-dashboard/knowledge-layering-20261023/source/knowledge_catalog.py'))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def source_bytes(path):
    return Path(path).read_bytes().replace(b'\r\n', b'\n')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def loose_source(root, source_commit, relative):
    """Read original content-addressed Git objects when the build host has no Git binary."""
    root = Path(root).absolute()

    def object_bytes(oid, kind):
        if not re.fullmatch('[a-f0-9]{40}', oid):
            raise ValueError('learning_native_git_object_identity')
        path = root / '.git/objects' / oid[:2] / oid[2:]
        for parent in (path, *path.parents):
            if parent.is_symlink():
                raise ValueError('learning_native_git_object_link')
            if parent == root:
                break
        # shortcut: packed objects require Git; isolated builds carry only exact original loose objects.
        if path.stat().st_size > 2_000_000:
            raise ValueError('learning_native_git_object_size')
        decoder = zlib.decompressobj()
        raw = decoder.decompress(path.read_bytes(), 2_000_000)
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('learning_native_git_object_size')
        if hashlib.sha1(raw).hexdigest() != oid:
            raise ValueError('learning_native_git_object_changed')
        header, content = raw.split(b'\0', 1)
        if header != (kind + ' ' + str(len(content))).encode():
            raise ValueError('learning_native_git_object_type')
        return content

    commit = object_bytes(source_commit, 'commit')
    match = re.match(rb'tree ([a-f0-9]{40})\n', commit)
    if not match:
        raise ValueError('learning_native_git_commit_tree')
    oid = match[1].decode()
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or '..' in parts:
        raise ValueError('learning_native_git_source_path')
    for n, name in enumerate(parts):
        tree = object_bytes(oid, 'tree')
        matches, pos = [], 0
        while pos < len(tree):
            space = tree.index(b' ', pos); end = tree.index(b'\0', space + 1)
            child = tree[end + 1:end + 21]
            if len(child) != 20:
                raise ValueError('learning_native_git_tree_entry')
            if tree[space + 1:end] == name.encode():
                matches.append((tree[pos:space], child.hex()))
            pos = end + 21
        if len(matches) != 1:
            raise ValueError('learning_native_git_source_missing')
        mode, oid = matches[0]
        if mode not in ((b'100644', b'100755') if n == len(parts) - 1 else (b'40000',)):
            raise ValueError('learning_native_git_source_mode')
    return object_bytes(oid, 'blob')


def verify_commit(root, source_commit):
    if not isinstance(source_commit, str) or not re.fullmatch('[a-f0-9]{40}', source_commit):
        raise ValueError('learning_native_committed_source_required')
    for path in COMMIT_INPUTS:
        try:
            raw = subprocess.check_output(['git', '-C', str(root), 'show', source_commit + ':' + path.as_posix()], stderr=subprocess.PIPE)
        except FileNotFoundError:
            raw = loose_source(root, source_commit, path)
        except subprocess.CalledProcessError as error:
            raise ValueError('learning_native_commit_source_unavailable:' + path.as_posix()) from error
        if raw.replace(b'\r\n', b'\n') != source_bytes(root / path):
            raise ValueError('learning_native_commit_source_differs:' + path.as_posix())


def build_image(root, context, before, operation_id, *, source_commit):
    verify_commit(root, source_commit)
    for name, source in {'fs_native_entry.py': NATIVE / 'fs_native_entry.py',
                         'reviewed_skills.py': SKILLS, 'Dockerfile.native': DEPLOY / 'Dockerfile.native'}.items():
        if (context / name).read_bytes() != source_bytes(root / source):
            raise ValueError('learning_native_committed_image_input_differs')
    release = load(root / DEPLOY / 'native_release.py', 'learning_native_build_scope')
    if before != release.CURRENT_IMAGE:
        raise ValueError('learning_native_base_image_drift')
    expected_files = {'Dockerfile.native', *release.IMAGE_PAYLOADS}
    if {p.name for p in context.iterdir()} != expected_files:
        raise ValueError('learning_native_exact_context_required')
    layers = json.loads(subprocess.check_output(['docker', 'image', 'inspect', '-f', '{{json .RootFS.Layers}}', before], text=True))
    user = subprocess.check_output(['docker', 'image', 'inspect', '-f', '{{json .Config.User}}', before], text=True).strip()
    output = subprocess.check_output(['docker', 'run', '--rm', '--read-only', '--network', 'none',
        '--entrypoint', 'sha256sum', before, *sorted(release.BEFORE_SOURCES)], text=True)
    if {line.split()[1]: line.split()[0] for line in output.splitlines()} != release.BEFORE_SOURCES:
        raise ValueError('learning_native_existing_image_source_drift')
    gateway = subprocess.check_output(['docker', 'run', '--rm', '--read-only', '--network', 'none',
        '--entrypoint', 'cat', before, '/opt/hermes/gateway/run_turn_runner.py'])
    patcher = load(root / NATIVE / 'patch_factory.py', 'learning_native_gateway_patch')
    if patcher.patch_gateway(gateway) != (context / 'native_gateway_factory.py').read_bytes():
        raise ValueError('learning_native_prepared_gateway_drift')
    expected = {target: sha((context / name).read_bytes()) for name, target in release.IMAGE_PAYLOADS.items()}
    expected['/opt/hermes/tui_gateway/server.py'] = release.BEFORE_SOURCES['/opt/hermes/tui_gateway/server.py']
    tag = 'fs-hermes-native:learning-' + sha(operation_id.encode())[:24]
    subprocess.run(['docker', 'build', '--network', 'none', '--pull=false', '--build-arg', 'NATIVE_BASE=' + before,
        '-f', str(context / 'Dockerfile.native'), '-t', tag, str(context)], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    after = subprocess.check_output(['docker', 'image', 'inspect', '-f', '{{.Id}}', tag], text=True).strip()
    child = json.loads(subprocess.check_output(['docker', 'image', 'inspect', '-f', '{{json .RootFS.Layers}}', after], text=True))
    if not release.IMAGE.fullmatch(after) or after == before or child[:len(layers)] != layers or len(child) != len(layers) + 3:
        raise ValueError('learning_native_built_layers_differ')
    if subprocess.check_output(['docker', 'image', 'inspect', '-f', '{{json .Config.User}}', after], text=True).strip() != user:
        raise ValueError('learning_native_runtime_user_changed')
    result = subprocess.check_output(['docker', 'run', '--rm', '--read-only', '--network', 'none',
        '--entrypoint', 'sha256sum', after, *sorted(expected)], text=True)
    if {line.split()[1]: line.split()[0] for line in result.splitlines()} != expected:
        raise ValueError('learning_native_built_sources_differ')
    return dict(image=after, tag=tag, sources=expected, base_layers=layers, child_layers=child, runtime_user=user)


def prepare_context(root, output, gateway_before, operation_id):
    """Use already authorized source bytes when exact unit/runtime reads are still pending."""
    root, output = Path(root), Path(output)
    if output.exists():
        raise ValueError('learning_native_stage_exists_reconcile_original_operation')
    release = load(root / DEPLOY / 'native_release.py', 'learning_native_context_scope')
    patcher = load(root / NATIVE / 'patch_factory.py', 'learning_native_context_gateway')
    payloads = {'Dockerfile.native': source_bytes(root / DEPLOY / 'Dockerfile.native'),
        'fs_native_entry.py': source_bytes(root / NATIVE / 'fs_native_entry.py'),
        'reviewed_skills.py': source_bytes(root / SKILLS), 'native_gateway_factory.py': patcher.patch_gateway(gateway_before)}
    context = output / 'native-image-context'; context.mkdir(parents=True)
    for name, raw in payloads.items():
        (context / name).write_bytes(raw)
    preview = dict(scope=release.SCOPE, releaseReady=False, imageBuilt=False, operation_id=operation_id,
        status='context_only_needs_preflight', currentImage=release.CURRENT_IMAGE,
        knownBeforeSources=release.BEFORE_SOURCES, exactContextFiles=sorted(payloads),
        sources={target: sha(payloads[name]) for name, target in release.IMAGE_PAYLOADS.items()},
        reviewedSkillsMount=release.MOUNT, ordinaryKnowledgeRoutesEnabled=False,
        policyChange='none; fresh exact policy readback required',
        blocked=['exact current systemd unit bytes need approval', 'fresh native SQLite runtime version unavailable',
                 'image not built; after image digest unavailable', 'Linux root-owned directory and locks not verified'])
    (output / 'native-build-preview.json').write_text(json.dumps(preview, indent=2), encoding='utf-8')
    return preview


def prepare(root, output, preflight, operation_id, builder=None):
    root, output = Path(root), Path(output)
    if output.exists():
        raise ValueError('learning_native_stage_exists_reconcile_original_operation')
    release = load(root / DEPLOY / 'native_release.py', 'learning_native_prepare_scope')
    old = load(root / OLD_DEPLOY / 'native_release.py', 'learning_native_existing_sqlite')
    old.checked_sqlite_version(preflight.get('native_sqlite_version'))
    if preflight.get('current_image') != release.CURRENT_IMAGE or preflight.get('native_image_sources') != release.BEFORE_SOURCES:
        raise ValueError('learning_native_preflight_image_source_required')
    policy_bytes = Path(preflight['policy_before_path']).read_bytes()
    policy = json.loads(policy_bytes)
    if (policy.get('contract') != 'fs-knowledge-load-policy-v1' or not isinstance(policy.get('requests'), dict)
            or policy.get('task_routes', {}).get('enabled') is True):
        raise ValueError('learning_native_existing_policy_disabled_routes_required')
    unit = Path(preflight['unit_before_path']).read_bytes()
    release.changed_unit(unit, release.CURRENT_IMAGE, 'sha256:' + 'f' * 64)
    init = source_bytes(root / NATIVE / 'fs_readonly/__init__.py')
    for name in ('plugin/__init__.py', 'plugin/knowledge.py'):
        if not rehash(preflight['before_hashes'].get(release.TARGETS[name])):
            raise ValueError('learning_native_existing_plugin_required')
    if sha(init) != preflight['before_hashes'][release.TARGETS['plugin/__init__.py']]:
        raise ValueError('learning_native_original_registration_drift')
    patcher = load(root / NATIVE / 'patch_factory.py', 'learning_native_exact_gateway')
    gateway = patcher.patch_gateway(Path(preflight['gateway_before_path']).read_bytes())
    output.mkdir(parents=True); context = output / 'native-image-context'; context.mkdir()
    for name, raw in {'Dockerfile.native': source_bytes(root / DEPLOY / 'Dockerfile.native'),
        'fs_native_entry.py': source_bytes(root / NATIVE / 'fs_native_entry.py'),
        'reviewed_skills.py': source_bytes(root / SKILLS), 'native_gateway_factory.py': gateway}.items():
        (context / name).write_bytes(raw)
    state = dict(operation_id=operation_id, status='build_context_prepared_not_built', releaseReady=False,
        current_image=release.CURRENT_IMAGE, unit_before_sha256=sha(unit), policy_before_sha256=sha(policy_bytes),
        source_commit=preflight['source_commit'], sources={target: sha((context / name).read_bytes())
            for name, target in release.IMAGE_PAYLOADS.items()})
    state['sources']['/opt/hermes/tui_gateway/server.py'] = release.BEFORE_SOURCES['/opt/hermes/tui_gateway/server.py']
    path = output / 'native-image-state.json'; path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    preview = dict(scope=release.SCOPE, releaseReady=False, imageBuilt=False, operation_id=operation_id,
        exactContextFiles=sorted(p.name for p in context.iterdir()), sources=state['sources'],
        currentImage=release.CURRENT_IMAGE, reviewedSkillsMount=release.MOUNT, policyPreservedSha256=release.digest(policy),
        changes=['native image', 'native plugin knowledge.py', 'dedicated approved skills read-only bind'],
        blocked=['image not built', 'Linux owner/lock/SQLite runtime and service validation not executed', 'production approval required'])
    (output / 'native-build-preview.json').write_text(json.dumps(preview, indent=2), encoding='utf-8')
    if builder is None:
        return preview
    return build_prepared(root, output, preflight, operation_id, builder)


def build_prepared(root, output, preflight, operation_id, builder=build_image):
    """Promote a known unbuilt preview under the same operation id; unknown builds never re-enter."""
    root, output = Path(root), Path(output)
    path = output / 'native-image-state.json'; state = json.loads(path.read_bytes())
    if (state.get('status') != 'build_context_prepared_not_built' or state.get('operation_id') != operation_id
            or state['current_image'] != preflight['current_image'] or state['source_commit'] != preflight['source_commit']):
        raise ValueError('learning_native_prepared_operation_required_reconcile_original')
    release = load(root / DEPLOY / 'native_release.py', 'learning_native_resume_scope')
    context = output / 'native-image-context'
    if (sha(Path(preflight['unit_before_path']).read_bytes()) != state['unit_before_sha256']
            or sha(Path(preflight['policy_before_path']).read_bytes()) != state['policy_before_sha256']
            or {target: sha((context / name).read_bytes()) for name, target in release.IMAGE_PAYLOADS.items()}
                != {target: state['sources'][target] for target in release.IMAGE_PAYLOADS.values()}):
        raise ValueError('learning_native_prepared_baseline_drift')
    state['status'] = 'image_build_intent'; path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    try:
        result = builder(root, context, release.CURRENT_IMAGE, operation_id, source_commit=state['source_commit'])
        if result['sources'] != state['sources']:
            raise ValueError('learning_native_builder_receipt_changed')
        state.update(status='image_built_and_verified_not_activated', **result)
        path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    except Exception as error:
        state.update(status='unknown-needs-reconcile', failure=str(error))
        path.write_text(json.dumps(state, indent=2), encoding='utf-8')
        raise
    return finish_candidate(root, output, preflight)


def rehash(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= set('0123456789abcdef')


def finish_candidate(root, output, preflight):
    root, output = Path(root), Path(output)
    state = json.loads((output / 'native-image-state.json').read_bytes())
    if state.get('status') != 'image_built_and_verified_not_activated':
        raise ValueError('learning_native_verified_build_receipt_required')
    release = load(root / DEPLOY / 'native_release.py', 'learning_native_finish_scope')
    old = load(root / OLD_DEPLOY / 'native_release.py', 'learning_native_finish_sqlite')
    old.verify_sqlite_runtime(preflight['native_sqlite_version'])
    if state['current_image'] != preflight['current_image']:
        raise ValueError('learning_native_build_baseline_changed')
    unit = Path(preflight['unit_before_path']).read_bytes(); policy = Path(preflight['policy_before_path']).read_bytes()
    if sha(unit) != state['unit_before_sha256'] or sha(policy) != state['policy_before_sha256']:
        raise ValueError('learning_native_prepared_baseline_drift')
    payloads = {'plugin/__init__.py': source_bytes(root / NATIVE / 'fs_readonly/__init__.py'),
        'plugin/knowledge.py': source_bytes(root / NATIVE / 'fs_readonly/knowledge.py'),
        'policy/knowledge-load-policy.json': policy,
        'native/desktop.service': release.changed_unit(unit, state['current_image'], state['image'])}
    files = []
    for name, target in release.TARGETS.items():
        path = output / 'candidate' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payloads[name])
        before = sha(unit) if name.startswith('native/') else sha(policy) if name.startswith('policy/') else preflight['before_hashes'][target]
        files.append(dict(candidate=name, target=target, sha256=sha(payloads[name]), beforeSha256=before, owner='0:0', mode='0o644'))
    dependencies = {'/opt/fs-hermes-fc/knowledge_catalog.py': sha(source_bytes(root / 'releases/fs-dashboard/knowledge-layering-20261023/source/knowledge_catalog.py')),
                    '/opt/fs-hermes-fc/reviewed_skills.py': sha(source_bytes(root / SKILLS))}
    protected = {row['path']: row for row in preflight['unchangedRequired']}
    for target, expected in dependencies.items():
        if target in protected and protected[target]['sha256'] != expected:
            raise ValueError('learning_native_preflight_dependency_drift')
        protected[target] = dict(path=target, sha256=expected)
    manifest = dict(schemaVersion=1, scope=release.SCOPE, releaseReady=False, businessWrites=False, timersChanged=False,
        nativeUnits=list(release.UNITS), nativeSQLiteVersion=preflight['native_sqlite_version'],
        imageId=state['current_image'], nativeImageBefore=state['current_image'], nativeImageAfter=state['image'],
        nativeImageBeforeSources=release.BEFORE_SOURCES, nativeImageSources=state['sources'], nativeExtraSources=dependencies,
        reviewedSkillsMount=release.MOUNT, ordinaryKnowledgeRoutesEnabled=False, sourceCommit=preflight['source_commit'],
        policyPreservedSha256=release.digest(json.loads(policy)), files=files,
        unchangedRequired=list(protected.values()), runtimeRequired=preflight['runtimeRequired'])
    if 'nativeProtection' in preflight:
        manifest['nativeProtection'] = preflight['nativeProtection']
    release.checked(manifest, output)
    for name, source in {'release.py': DEPLOY / 'native_release.py', 'native_release_base.py': OLD_DEPLOY / 'native_release.py',
        'release_adapter_base.py': Path('releases/fs-dashboard/user-analytics-20261022/deploy/release.py'),
        'release_navigation_base.py': Path('releases/fs-dashboard/channel-effects-20261021/deploy/release_navigation_base.py')}.items():
        data = (root / source).read_bytes() if name == 'release_navigation_base.py' else source_bytes(root / source)
        (output / name).write_bytes(data)
    (output / 'candidate-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', type=Path); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--operation-id', required=True); parser.add_argument('--build', action='store_true')
    parser.add_argument('--context-only', action='store_true'); parser.add_argument('--gateway-before', type=Path)
    args = parser.parse_args()
    if args.context_only:
        if args.build or args.gateway_before is None:
            parser.error('--context-only requires --gateway-before and forbids --build')
        print(json.dumps(prepare_context(ROOT, args.output, args.gateway_before.read_bytes(), args.operation_id), indent=2))
        raise SystemExit(0)
    if args.preflight is None:
        parser.error('--preflight is required outside --context-only')
    action = build_prepared if args.build and args.output.exists() else prepare
    if action is build_prepared:
        result = action(ROOT, args.output, json.loads(args.preflight.read_bytes()), args.operation_id)
    else:
        result = action(ROOT, args.output, json.loads(args.preflight.read_bytes()), args.operation_id,
                        build_image if args.build else None)
    print(json.dumps(result, indent=2))
