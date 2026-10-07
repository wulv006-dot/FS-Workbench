"""Read-only audit of actual private binding against approved real artifact bytes.

No binding generation, receipt renewal, lock acquisition, metadata write, network
request, or candidate runner/probe import. This is not runtime proof acceptance.
"""
import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath

SOURCE_SHA = '8f97e23b3a63480fd8fd142ab977a85558203a7c7400739cb31186120b50c90f'
LAUNCH_SHA = '874c0f6efba568a4068bb3fe9a4e3bde97189efe0ece166ed2b0aed1f72fc4d3'
digest = lambda raw: hashlib.sha256(raw).hexdigest()

def trusted_parent(path):
    parts = PurePosixPath(path).parts
    if not parts or parts[0] != '/' or any(p in ('.', '..') for p in parts):
        raise ValueError('absolute_trusted_path_required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            current = os.fstat(child)
            visible = os.stat(part, dir_fd=fd, follow_symlinks=False)
            if (current.st_uid != 0 or stat.S_IMODE(current.st_mode) & 0o022
                    or (current.st_dev, current.st_ino) != (visible.st_dev, visible.st_ino)):
                os.close(child)
                raise ValueError('trusted_parent_changed')
            os.close(fd)
            fd = child
        root = os.fstat(fd)
        if root.st_uid != 0 or root.st_gid != 0 or stat.S_IMODE(root.st_mode) != 0o700:
            raise ValueError('private_directory_metadata_untrusted')
        return fd
    except BaseException:
        os.close(fd)
        raise

def read_at(parent, name, gid, mode):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != 0 or before.st_gid != gid
                or stat.S_IMODE(before.st_mode) != mode):
            raise ValueError('artifact_or_binding_metadata_untrusted')
        parts = []
        length = 0
        while True:
            part = os.read(fd, 1048576)
            if not part:
                break
            length += len(part)
            if length > 32000000:
                raise ValueError('bounded_input_exceeded')
            parts.append(part)
        after = os.fstat(fd)
        visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
        attrs = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if (tuple(getattr(before, n) for n in attrs) != tuple(getattr(after, n) for n in attrs)
                or (before.st_dev, before.st_ino) != (visible.st_dev, visible.st_ino)):
            raise ValueError('input_changed_during_read')
        return b''.join(parts)
    finally:
        os.close(fd)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact', required=True)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--binding-sha', required=True)
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.no_site or os.name != 'posix' or os.geteuid() != 0:
        raise ValueError('isolated_native_root_audit_required')
    artifact = PurePosixPath(args.artifact)
    binding = PurePosixPath(args.binding)
    if str(binding).startswith(str(artifact).rstrip('/') + '/'):
        raise ValueError('runtime_binding_must_be_separate')
    parent = trusted_parent(str(artifact))
    try:
        manifest_raw = read_at(parent, 'SOURCE-MANIFEST.json', 11028, 0o640)
        launcher = read_at(parent, 'launch.py', 11028, 0o640)
    finally:
        os.close(parent)
    if digest(manifest_raw) != SOURCE_SHA or digest(launcher) != LAUNCH_SHA:
        raise ValueError('approved_controller_source_pin_changed')
    namespace = {'__name__': 'approved_private_contract_audit'}
    exec(compile(launcher, 'verified-inline-launch', 'exec'), namespace)
    files, dirs = namespace['collect'](str(artifact))
    namespace['validate_bundle'](files, dirs, SOURCE_SHA)
    parent = trusted_parent(str(binding.parent))
    try:
        binding_raw = read_at(parent, binding.name, 0, 0o600)
    finally:
        os.close(parent)
    if digest(binding_raw) != args.binding_sha:
        raise ValueError('runtime_binding_changed')
    scope = json.loads(binding_raw)
    schema = json.loads(files['BINDING-SCHEMA.json'])
    namespace['validate_binding'](scope, schema, SOURCE_SHA, str(artifact), files)
    if scope['production_approval'] is not True:
        raise ValueError('production_approval_required')
    expected = {'coin_revision': 28, 'schedule_revision': 28, 'interval_minutes': 120,
                'player_revision': 8, 'gallery_revision': 8}
    if any(scope[k] != v for k, v in expected.items()):
        raise ValueError('binding_policy_contract_changed')
    if not scope['supersession'] or scope['supersession']['mode'] != 'later_confirmed_coin':
        raise ValueError('supersession_binding_required')
    if len(scope['expected_files']) != 11 or len(scope['expected_sources']) != 12:
        raise ValueError('binding_cas_or_source_count_changed')
    if len(scope['sample_model_ids']) != 5 or any(len(scope[k]) != 15 for k in ['tier_gold', 'tier_give', 'tier_discount']):
        raise ValueError('binding_sample_or_tier_count_changed')
    if not {'automation-tick.lock', 'price-writer.lock'} <= set(scope['lock_metadata']):
        raise ValueError('binding_writer_locks_incomplete')
    if scope['host_python']['version'] != sys.version or scope['host_python']['executable_sha256'] != digest(Path(sys.executable).resolve().read_bytes()):
        raise ValueError('host_interpreter_changed')
    print(json.dumps({
        'status': 'actual_private_binding_static_contract_validated',
        'source_manifest_sha256': SOURCE_SHA,
        'binding_sha256': args.binding_sha,
        'binding_fields': len(scope),
        'cas_files': len(scope['expected_files']),
        'host_sources': len(scope['expected_sources']),
        'business_posts': 0,
        'metadata_writes': 0,
        'runner_or_probe_imported': False,
        'runtime_preflight_completed': False,
    }, sort_keys=True))

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({
            'status': 'stopped_without_business_replay',
            'business_posts': 0,
            'metadata_writes': 0,
            'reason': str(exc)[:120] if isinstance(exc, ValueError) else type(exc).__name__,
        }, sort_keys=True))
        raise SystemExit(2)
