"""Prepare the exact native scope using an isolated image build and the existing publisher.

Run only within an approved build/publish scope. Never switches an image, service or timer.
An existing output means reconcile the original operation, never build a second attempt blindly.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NATIVE = Path('releases/fs-dashboard/hermes-server-unify-20261022')
DEPLOY = Path('releases/fs-dashboard/knowledge-layering-20261023/deploy')
BASE_TAG = 'fs-hermes-fc:71d34bad-precheck'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def source_bytes(path):
    return Path(path).read_bytes().replace(b'\r\n', b'\n')


def build_image(root, context, before, operation_id):
    patcher = load(root / NATIVE / 'patch_factory.py', 'native_exact_factory_patch')
    lifecycle = load(root / 'releases/fs-dashboard/hermes-fc-pilot-20261013/shared_candidate/capability_image_lifecycle.py', 'existing_image_identity')
    if lifecycle.image_id(before) != before or lifecycle.image_id(BASE_TAG) != before:
        raise ValueError('native_base_image_drift')
    layers = json.loads(subprocess.check_output(['docker', 'image', 'inspect', '-f', '{{json .RootFS.Layers}}', before], text=True))
    base_user = subprocess.check_output(['docker', 'image', 'inspect', '-f', '{{json .Config.User}}', before], text=True).strip()
    original = subprocess.check_output(['docker', 'run', '--rm', '--read-only', '--network', 'none',
                                       '--entrypoint', 'cat', before, '/opt/hermes/tui_gateway/server.py'])
    patched = patcher.patch_source(original)
    factory = context / 'native_factory.py'
    if factory.exists() and factory.read_bytes() != patched: raise ValueError('native_generated_factory_drift')
    factory.write_bytes(patched)
    if {p.name for p in context.iterdir()} != {'Dockerfile.native', 'fs_native_entry.py', 'native_factory.py'}:
        raise ValueError('native_exact_three_file_context_required')
    expected = {'/opt/hermes/tui_gateway/server.py': hashlib.sha256(patched).hexdigest(),
                '/opt/hermes/fs_native_entry.py': hashlib.sha256((context / 'fs_native_entry.py').read_bytes()).hexdigest()}
    tag = 'fs-hermes-native:knowledge-' + hashlib.sha256(operation_id.encode()).hexdigest()[:24]
    subprocess.run(['docker', 'build', '--network', 'none', '--pull=false', '--build-arg', 'NATIVE_BASE=' + BASE_TAG,
                    '-f', str(context / 'Dockerfile.native'), '-t', tag, str(context)], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    after = lifecycle.image_id(tag)
    child_layers = json.loads(subprocess.check_output(['docker', 'image', 'inspect', '-f', '{{json .RootFS.Layers}}', after], text=True))
    if lifecycle.image_id(BASE_TAG) != before or child_layers[:len(layers)] != layers or len(child_layers) != len(layers) + 2:
        raise ValueError('native_built_image_base_layers_differ')
    if subprocess.check_output(['docker', 'image', 'inspect', '-f', '{{json .Config.User}}', after], text=True).strip() != base_user:
        raise ValueError('native_built_image_runtime_user_changed')
    out = subprocess.check_output(['docker', 'run', '--rm', '--read-only', '--network', 'none',
                                   '--entrypoint', 'sha256sum', after, *sorted(expected)], text=True)
    if {line.split()[1]: line.split()[0] for line in out.splitlines()} != expected:
        raise ValueError('native_image_build_readback_differs')
    return dict(image=after, tag=tag, sources=expected, base_tag=BASE_TAG, base_layers=layers, child_layers=child_layers, runtime_user=base_user)


def prepare(root, output, preflight, operation_id, builder=build_image):
    root, output = Path(root), Path(output)
    if output.exists():
        raise ValueError('native_stage_exists_reconcile_original_operation')
    release = load(root / DEPLOY / 'native_release.py', 'native_exact_scope')
    sqlite_version = preflight.get('native_sqlite_version')
    release.verify_sqlite_runtime(sqlite_version)
    before = preflight['current_image']
    if not release.IMAGE.fullmatch(before):
        raise ValueError('native_preflight_image_required')
    unit = Path(preflight['unit_before_path']).read_bytes()
    if unit.count(before.encode()) != 1:
        raise ValueError('native_existing_unit_image_not_exact')
    candidate_init = source_bytes(root / NATIVE / 'fs_readonly/__init__.py')
    if release.original_plugin_sha(candidate_init) != preflight['before_hashes'][release.TARGETS['plugin/__init__.py']]:
        raise ValueError('native_original_tools_source_drift')
    policy_path = preflight.get('policy_before_path')
    prior = json.loads(Path(policy_path).read_bytes()) if policy_path else {'contract': 'fs-knowledge-load-policy-v1', 'requests': {}}
    if prior.get('contract') != 'fs-knowledge-load-policy-v1' or not isinstance(prior.get('requests'), dict):
        raise ValueError('native_existing_policy_contract')
    policy = dict(prior, native=preflight['native'])
    preserved = {k: v for k, v in prior.items() if k != 'native'}
    output.mkdir(parents=True)
    state = dict(operation_id=operation_id, status='image_build_intent', current_image=before)
    state_path = output / 'native-image-state.json'
    state_path.write_text(json.dumps(state, indent=2), 'utf-8')
    context = output / 'native-image-context'; context.mkdir()
    for name in ('Dockerfile.native', 'fs_native_entry.py'):
        (context / name).write_bytes(source_bytes(root / NATIVE / name))
    try:
        built = builder(root, context, before, operation_id)
        state.update(status='image_built_and_verified_not_activated', **built)
        state_path.write_text(json.dumps(state, indent=2), 'utf-8')
    except Exception as error:
        state.update(status='unknown-needs-reconcile', failure=str(error))
        state_path.write_text(json.dumps(state, indent=2), 'utf-8')
        raise
    return finish_candidate(root, output, preflight)


def finish_candidate(root, output, preflight):
    """Complete a verified build's preview; never rebuild or activate an image."""
    root, output = Path(root), Path(output)
    built = json.loads((output / 'native-image-state.json').read_text('utf-8'))
    if built.get('status') != 'image_built_and_verified_not_activated':
        raise ValueError('native_verified_build_receipt_required')
    release = load(root / DEPLOY / 'native_release.py', 'native_exact_scope_finish')
    sqlite_version = preflight.get('native_sqlite_version'); release.verify_sqlite_runtime(sqlite_version)
    before = preflight['current_image']
    if built['current_image'] != before: raise ValueError('native_build_base_changed')
    unit = Path(preflight['unit_before_path']).read_bytes()
    candidate_init = source_bytes(root / NATIVE / 'fs_readonly/__init__.py')
    policy_path = preflight.get('policy_before_path')
    prior = json.loads(Path(policy_path).read_bytes()) if policy_path else {'contract': 'fs-knowledge-load-policy-v1', 'requests': {}}
    if prior.get('contract') != 'fs-knowledge-load-policy-v1' or not isinstance(prior.get('requests'), dict):
        raise ValueError('native_existing_policy_contract')
    policy = dict(prior, native=preflight['native'])
    preserved = {k: v for k, v in prior.items() if k != 'native'}
    payloads = {'plugin/__init__.py': candidate_init,
                'plugin/knowledge.py': source_bytes(root / NATIVE / 'fs_readonly/knowledge.py'),
                'policy/knowledge-load-policy.json': (json.dumps(policy, ensure_ascii=False, indent=2) + '\n').encode(),
                'native/desktop.service': unit.replace(before.encode(), built['image'].encode())}
    rows = []
    for name, target in release.TARGETS.items():
        path = output / 'candidate' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payloads[name])
        expected = (hashlib.sha256(unit).hexdigest() if name.startswith('native/') else
                    hashlib.sha256(Path(policy_path).read_bytes()).hexdigest() if name.startswith('policy/') and policy_path else
                    None if name.startswith('policy/') else preflight['before_hashes'][target])
        rows.append(dict(candidate=name, target=target, sha256=hashlib.sha256(payloads[name]).hexdigest(),
                         beforeSha256=expected, owner='0:0', mode='0o644'))
    manifest = dict(schemaVersion=1, scope=release.SCOPE, releaseReady=False, businessWrites=False, timersChanged=False,
                    nativeUnits=list(release.UNITS), nativeImageBefore=before, nativeImageAfter=built['image'],
                    nativeSQLiteVersion=sqlite_version,
                    nativeImageSources=built['sources'], imageId=before, sourceCommit=preflight['source_commit'],
                    policyPreservedSha256=hashlib.sha256(json.dumps(preserved, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                    files=rows, unchangedRequired=preflight['unchangedRequired'], runtimeRequired=preflight['runtimeRequired'])
    release.checked(manifest, output)
    for name, source in {'release.py': DEPLOY / 'native_release.py',
                         'release_adapter_base.py': Path('releases/fs-dashboard/user-analytics-20261022/deploy/release.py'),
                         'release_navigation_base.py': Path('releases/fs-dashboard/channel-effects-20261021/deploy/release_navigation_base.py')}.items():
        # The frozen publisher hash binds original CRLF bytes; only the adapter uses Git LF.
        data = (root / source).read_bytes() if name == 'release_navigation_base.py' else source_bytes(root / source)
        (output / name).write_bytes(data)
    (output / 'candidate-manifest.json').write_text(json.dumps(manifest, indent=2), 'utf-8')
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preflight', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--operation-id', required=True)
    args = p.parse_args()
    print(json.dumps(prepare(ROOT, args.output, json.loads(args.preflight.read_text('utf-8')), args.operation_id)))
