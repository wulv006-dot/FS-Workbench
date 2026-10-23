"""Exact learning image/mount scope over the original native CAS/SQLite publisher."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess
import types

HERE = Path(__file__).resolve().parent
SCOPE = 'hermes-learning-native-20261023'
NATIVE_BASE_SHA = '964bcb5e990caa660f0bb3e5713504f8556ca5e17a4aebcde5d73d343ec650ee'
ADAPTER_SHA = '1ce25dae41a5bac8317d0ab2b9b719964085b3a1d1481708692ec099111775dc'
CURRENT_IMAGE = 'sha256:d51507514f3f52fdcc3cb6bc0d36e2b12863517aa590ae1338dd462ffe1636a4'
IMAGE = re.compile(r'sha256:[a-f0-9]{64}')
HOST_SKILLS = '/var/lib/fs-hermes-memory-approval/published-skills'
MOUNT = '--mount=type=bind,src=' + HOST_SKILLS + ',dst=/approved-skills,readonly'
PLUGIN = '/var/lib/fs-hermes-fc/profile/plugins/fs-readonly/'
TARGETS = {'plugin/__init__.py': PLUGIN + '__init__.py', 'plugin/knowledge.py': PLUGIN + 'knowledge.py',
    'policy/knowledge-load-policy.json': '/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json',
    'native/desktop.service': '/etc/systemd/system/fs-hermes-desktop.service'}
UNITS = ('fs-hermes-desktop.service', 'hermes-dingtalk.service')
BEFORE_SOURCES = {
    '/opt/hermes/tui_gateway/server.py': '5e69b1d2290d5cca7ea9fd8be543585ad393d65fd9a8d9d1d9645437dc853252',
    '/opt/hermes/fs_native_entry.py': '3ec3401b894bd576260b87a6e29f2b406bbc06b3e3f1cb0ad63aea2499e1e278',
    '/opt/hermes/gateway/run_turn_runner.py': '6ec879a91aa09765515a69368c886d1ce4d3174b159868c966e8740e9cf1b347'}
IMAGE_PAYLOADS = {'fs_native_entry.py': '/opt/hermes/fs_native_entry.py',
    'native_gateway_factory.py': '/opt/hermes/gateway/run_turn_runner.py',
    'reviewed_skills.py': '/opt/hermes/reviewed_skills.py'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def changed_unit(raw, before, after):
    if (before != CURRENT_IMAGE or not IMAGE.fullmatch(after) or before == after
            or raw.count(before.encode()) != 1 or b'docker run ' not in raw
            or b'/approved-skills' in raw or HOST_SKILLS.encode() in raw):
        raise ValueError('learning_native_exact_unit_baseline_required')
    return raw.replace(before.encode(), (MOUNT + ' ' + after).encode(), 1)


def checked(manifest, stage=None):
    if (manifest.get('scope') != SCOPE or manifest.get('businessWrites') is not False
            or manifest.get('timersChanged') is not False or manifest.get('nativeUnits') != list(UNITS)
            or len(manifest.get('files', [])) != len(TARGETS)
            or {r['candidate']: r['target'] for r in manifest['files']} != TARGETS
            or manifest.get('nativeImageBefore') != CURRENT_IMAGE or manifest.get('imageId') != CURRENT_IMAGE
            or not IMAGE.fullmatch(manifest.get('nativeImageAfter', ''))
            or manifest.get('nativeImageAfter') == CURRENT_IMAGE
            or manifest.get('nativeImageBeforeSources') != BEFORE_SOURCES
            or manifest.get('reviewedSkillsMount') != MOUNT
            or manifest.get('ordinaryKnowledgeRoutesEnabled') is not False):
        raise ValueError('learning_native_exact_scope_required')
    sources = manifest.get('nativeImageSources', {})
    if (set(sources) != {*IMAGE_PAYLOADS.values(), '/opt/hermes/tui_gateway/server.py'}
            or sources['/opt/hermes/tui_gateway/server.py'] != BEFORE_SOURCES['/opt/hermes/tui_gateway/server.py']
            or any(not re.fullmatch('[a-f0-9]{64}', v) for v in sources.values())):
        raise ValueError('learning_native_exact_image_sources_required')
    dependencies = manifest.get('nativeExtraSources', {})
    if (set(dependencies) != {'/opt/fs-hermes-fc/knowledge_catalog.py', '/opt/fs-hermes-fc/reviewed_skills.py'}
            or any(not re.fullmatch('[a-f0-9]{64}', v) for v in dependencies.values())
            or dependencies['/opt/fs-hermes-fc/reviewed_skills.py'] != sources['/opt/hermes/reviewed_skills.py']):
        raise ValueError('learning_native_exact_source_dependencies_required')
    protected = {r['path']: r['sha256'] for r in manifest['unchangedRequired']}
    if any(protected.get(p) != sha for p, sha in dependencies.items()):
        raise ValueError('learning_native_source_dependency_not_guarded')
    if manifest.get('releaseReady') is True and not all(manifest.get('nativeProtection', {}).get(k) for k in ('metadata', 'trees')):
        raise ValueError('native_complete_protection_required')
    if stage is not None:
        stage = Path(stage)
        for name, target in IMAGE_PAYLOADS.items():
            if hashlib.sha256((stage / 'native-image-context' / name).read_bytes()).hexdigest() != sources[target]:
                raise ValueError('learning_native_image_payload_changed')
        rows = {r['candidate']: r for r in manifest['files']}
        for name in ('plugin/__init__.py', 'policy/knowledge-load-policy.json'):
            row = rows[name]
            if row['beforeSha256'] != row['sha256']:
                raise ValueError('learning_native_existing_registration_policy_required')
        raw = (stage / 'candidate/native/desktop.service').read_bytes()
        inserted = (MOUNT + ' ' + manifest['nativeImageAfter']).encode()
        if raw.count(inserted) != 1 or hashlib.sha256(raw.replace(inserted, CURRENT_IMAGE.encode(), 1)).hexdigest() != rows['native/desktop.service']['beforeSha256']:
            raise ValueError('learning_native_unit_only_image_and_readonly_mount')
        policy = json.loads((stage / 'candidate/policy/knowledge-load-policy.json').read_bytes())
        if digest(policy) != manifest['policyPreservedSha256'] or policy.get('task_routes', {}).get('enabled') is True:
            raise ValueError('learning_native_policy_preserved_disabled_required')
    return manifest


def native_base():
    raw = (HERE / 'native_release_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != NATIVE_BASE_SHA:
        raise ValueError('native_existing_scope_drift')
    spec = importlib.util.spec_from_file_location('frozen_native_learning_fence', HERE / 'native_release_base.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.HERE, module.SCOPE, module.TARGETS = HERE, SCOPE, TARGETS
    return module


def check_published_root(root):
    path = Path(root) / HOST_SKILLS.lstrip('/')
    for item in (path, *path.parents):
        info = item.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('learning_native_unsafe_readonly_catalog_root')
        if item == Path(root):
            return
    raise ValueError('learning_native_catalog_root_boundary')


def load_base():
    approved = checked(json.loads((HERE / 'approved-manifest.json').read_text('utf-8')), HERE)
    old = native_base(); old.verify_sqlite_runtime(approved['nativeSQLiteVersion'])
    raw = (HERE / 'release_adapter_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != ADAPTER_SHA:
        raise ValueError('existing_adapter_drift')
    source = raw.decode()
    anchor = "    source=raw.decode('utf-8')\n"
    if source.count(anchor) != 1:
        raise ValueError('learning_native_frozen_image_anchor_drift')
    insertion = ("    original_image='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'\n"
        "    if source.count(original_image)!=4 or approved.get('imageId')!=" + repr(CURRENT_IMAGE) + ":\n"
        "        raise ValueError('learning_native_frozen_image_boundary')\n"
        "    source=source.replace(original_image," + repr(CURRENT_IMAGE) + ")\n")
    adapter = types.ModuleType('existing_learning_scope'); adapter.__file__ = str(HERE / 'release_adapter_base.py')
    exec(compile(source.replace(anchor, anchor + insertion, 1), adapter.__file__, 'exec'), adapter.__dict__)
    adapter.HERE, adapter.SCOPE, adapter.TARGETS = HERE, SCOPE, TARGETS
    adapter.AUTHORIZED_TIMERS = frozenset(); adapter.NEW = frozenset()
    base = adapter.load_base()
    validate, guards, inspect = base.validate, base.guards, base.inspect

    def validate_learning(manifest, stage):
        checked(manifest, stage)
        return validate(manifest, stage)

    def guards_learning(manifest, root, reader_stopped=False):
        old.verify_protection(manifest, root); check_published_root(root)
        return guards(manifest, root, reader_stopped)

    def inspect_learning(manifest, stage, root=Path('/')):
        old.probe_native_database(base, root, manifest['nativeSQLiteVersion'])
        policy = json.loads(base.rooted(root, TARGETS['policy/knowledge-load-policy.json']).read_bytes())
        if digest(policy) != manifest['policyPreservedSha256']:
            raise ValueError('learning_native_current_policy_drift')
        current = subprocess.check_output(['docker', 'inspect', '-f', '{{.Image}}', 'fs-hermes-desktop'], text=True).strip()
        if current != CURRENT_IMAGE:
            raise ValueError('native_running_image_baseline_drift')
        for image, expected in ((CURRENT_IMAGE, BEFORE_SOURCES), (manifest['nativeImageAfter'], manifest['nativeImageSources'])):
            result = subprocess.check_output(['docker', 'run', '--rm', '--read-only', '--network', 'none',
                '--entrypoint', 'sha256sum', image, *sorted(expected)], text=True)
            if {line.split()[1]: line.split()[0] for line in result.splitlines()} != expected:
                raise ValueError('learning_native_image_readback_differs')
        return inspect(manifest, stage, root)

    base.validate, base.guards, base.inspect = validate_learning, guards_learning, inspect_learning
    return old.install_native_scope(base, approved)


if __name__ == '__main__':
    load_base().main()
