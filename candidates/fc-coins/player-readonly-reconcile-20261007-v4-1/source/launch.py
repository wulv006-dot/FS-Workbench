"""Approved inline launcher, invoked with -I -S -B; never execute this from disk.

The controller must supply these exact reviewed bytes with python -c and approved
source-manifest/binding hashes. No candidate or production dependency is imported
until every source artifact entry has been validated and sealed.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import PurePosixPath

CANDIDATE_MODULES = {'runner', 'probe', 'reconcile', 'secure_fs', 'storage', 'verified_loader', 'player_readonly_reconcile_guard'}
APP_MODULES = {'fc27_cloud_api', 'fc27_cloud_worker', 'player_sync_job', 'automation_tick',
    'coin_all_sync_job', 'automation_policy', 'player_sync_policy', 'server_quote_job',
    'activity_log_store', 'fc27_quote_engine', 'snapshot_layer', 'storefront_monitor',
    'p2pah_session_service'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_names(actual_files, actual_dirs, manifest):
    names = set(manifest['files'])
    for name in names:
        parts = PurePosixPath(name).parts
        if (not parts or name.startswith('/') or any(p in {'.', '..'} for p in parts)
                or any(not re.fullmatch('[A-Za-z0-9_.-]+', p) for p in parts)):
            raise ValueError('artifact_entry_name_invalid')
    dirs = {'/'.join(PurePosixPath(name).parts[:i]) for name in names
            for i in range(1, len(PurePosixPath(name).parts))}
    if set(actual_files) != names | {'SOURCE-MANIFEST.json'} or set(actual_dirs) != dirs:
        raise ValueError('artifact_extra_or_missing_entry')
    py = {name for name in names if name.endswith('.py')}
    expected_py = {name + '.py' for name in CANDIDATE_MODULES | {'launch'}} | {
        'app/' + name + '.py' for name in APP_MODULES}
    if py != expected_py or names != expected_py | {'README.md','BINDING-SCHEMA.json'}:
        raise ValueError('artifact_python_closure_changed')


def metadata(st, directory=False, binding=False):
    mode = 0o700 if directory else (0o600 if binding else 0o640)
    gid = 0 if directory or binding else 11028
    if (st.st_uid != 0 or st.st_gid != gid or stat.S_IMODE(st.st_mode) != mode
            or not (stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode))
            or (not directory and st.st_nlink != 1)):
        raise ValueError('artifact_or_binding_metadata_untrusted')


def read_fd(parent, name, binding=False):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        before = os.fstat(fd);metadata(before, binding=binding)
        parts = [];length = 0
        while True:
            part = os.read(fd, 1048576)
            if not part:
                break
            length += len(part)
            if length > 32000000:
                raise ValueError('bounded_input_exceeded')
            parts.append(part)
        after = os.fstat(fd);current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError('input_changed_during_read')
        return b''.join(parts)
    finally:
        os.close(fd)


def open_directory(path, private=False):
    parts = PurePosixPath(path).parts
    if not parts or parts[0] != '/' or '..' in parts:
        raise ValueError('absolute_trusted_path_required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(parts[1:]):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            st = os.fstat(child);current = os.stat(part, dir_fd=fd, follow_symlinks=False)
            if (st.st_uid != 0 or stat.S_IMODE(st.st_mode) & 0o022
                    or (st.st_dev, st.st_ino) != (current.st_dev, current.st_ino)):
                os.close(child);raise ValueError('trusted_parent_changed')
            os.close(fd);fd = child
        if private:
            metadata(os.fstat(fd), directory=True)
        return fd
    except BaseException:
        os.close(fd);raise


def collect(folder):
    files = {};dirs = set();root = open_directory(folder, private=True)
    def walk(fd, prefix=''):
        metadata(os.fstat(fd), directory=True)
        for name in os.listdir(fd):
            if not re.fullmatch('[A-Za-z0-9_.-]+', name) or name in {'.', '..'}:
                raise ValueError('artifact_entry_name_invalid')
            relative = prefix + name;st = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(st.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    metadata(st, directory=True)
                    if (st.st_dev, st.st_ino) != (os.fstat(child).st_dev, os.fstat(child).st_ino):
                        raise ValueError('artifact_directory_changed')
                    dirs.add(relative);walk(child, relative + '/')
                finally:
                    os.close(child)
            else:
                files[relative] = read_fd(fd, name)
    try:
        walk(root)
        return files, dirs
    finally:
        os.close(root)


def validate_bundle(files, dirs, manifest_sha):
    raw = files['SOURCE-MANIFEST.json']
    if sha(raw) != manifest_sha:
        raise ValueError('source_manifest_changed')
    manifest = json.loads(raw)
    if set(manifest) != {'version', 'files'} or manifest['version'] != 4:
        raise ValueError('source_manifest_schema_invalid')
    validate_names(files, dirs, manifest)
    for name, expected in manifest['files'].items():
        if sha(files[name]) != expected:
            raise ValueError('candidate_hash_changed_before_import')
    return manifest


def validate_writer_receipts(scope):
    """Receipts come from the separately approved, SHA-pinned private binding.

    The approved controller must collect them from the resident HTTP service and
    systemd effective unit, never from candidate functions or disk SHA alone.
    Revalidate age/identity on every context check; no receipt is manufactured here.
    """
    def reject(reason):
        raise ValueError('writer_adoption_receipt_invalid:' + reason)
    def fresh(receipt, source):
        if not isinstance(receipt, dict) or receipt.get('source') != source:
            reject(source + ':missing_or_wrong_origin')
        try:
            captured = datetime.fromisoformat(receipt['captured_at'])
            if captured.utcoffset() is None:
                reject(source + ':timezone_required')
            age = (datetime.now(timezone.utc) - captured).total_seconds()
        except (KeyError, TypeError, ValueError):
            reject(source + ':timestamp_invalid')
        if not 0 <= age <= 300:
            reject(source + ':stale')
    evidence = scope['writer_protocol_evidence']
    api = evidence['api'];receipt = api.get('health_receipt')
    fresh(receipt, 'resident-api-http')
    if (receipt.get('method') != 'GET' or receipt.get('endpoint_path') != '/health'
            or receipt.get('http_status') != 200
            or receipt.get('pid') != api['pid']
            or str(receipt.get('start_ticks')) != str(api['start_ticks'])
            or api['pid'] == os.getpid()):
        reject('api:resident_identity_or_http')
    response = receipt.get('response', {})
    if (not isinstance(response, dict)
            or response.get('queue_protocol') != 'existing-tick-inode-v4'
            or response.get('api_pid') != api['pid']):
        reject('api:resident_health_protocol')
    timer = evidence['timer'];unit = timer.get('effective_unit_receipt')
    fresh(unit, 'systemd-effective-unit')
    script = '/opt/fc27-cloud-browser/automation_tick.py'
    argv = ['/usr/bin/python3', script]
    if (unit.get('unit_id') != 'fc27-automation-tick.service'
            or unit.get('load_state') != 'loaded' or unit.get('exec_start_argv') != argv
            or unit.get('source_sha256') != scope['expected_sources'][script]
            or unit.get('interpreter_sha256') != scope['host_python']['executable_sha256']):
        reject('timer:effective_unit_command_or_source')
    def unit_file(item):
        return (isinstance(item, dict) and isinstance(item.get('path'), str)
            and item['path'].startswith(('/etc/systemd/system/', '/usr/lib/systemd/system/', '/lib/systemd/system/'))
            and '..' not in PurePosixPath(item['path']).parts
            and isinstance(item.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', item['sha256']))
    if (not unit_file(unit.get('fragment')) or not isinstance(unit.get('drop_ins'), list)
            or any(not unit_file(item) for item in unit['drop_ins'])):
        reject('timer:effective_unit_provenance')
    probe = timer.get('protocol_probe_receipt')
    fresh(probe, 'effective-unit-readonly-probe')
    result = probe.get('result', {})
    if (probe.get('argv') != argv + ['--queue-protocol'] or probe.get('returncode') != 0
            or probe.get('source_sha256') != unit['source_sha256']
            or probe.get('interpreter_sha256') != unit['interpreter_sha256']
            or not isinstance(result, dict) or result.get('queue_protocol') != 'existing-tick-inode-v4'
            or result.get('read_only') is not True or result.get('status') not in ['ready', 'busy']):
        reject('timer:effective_unit_probe')


def validate_binding(scope, schema, manifest_sha, artifact, files=None):
    if set(scope) != set(schema['required_types']):
        raise ValueError('binding_field_set_changed')
    types={'str':str,'int':int,'bool':bool,'dict':dict,'list':list}
    for name,kind in schema['required_types'].items():
        if type(scope[name]) is not types[kind]:raise ValueError('binding_field_type_invalid:'+name)
    if (scope['binding_version'] != 4 or scope['binding_status'] != 'APPROVED'
            or scope['source_manifest_sha256'] != manifest_sha or scope['artifact_root'] != artifact):
        raise ValueError('fresh_v4_binding_required')
    if scope['state_root']!='/var/lib/fc27-cloud/state' or scope['rollback_root']!='/var/lib/fc27-cloud/rollback':
        raise ValueError('binding_common_runtime_root_changed')
    pid=scope['player_job_id'];cid=scope['coin_execution_id']
    if any(not re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',item) for item in [pid,cid]):
        raise ValueError('binding_job_identity_invalid')
    if scope['allowed_metadata_targets'] != ['player-sync/'+pid+'.json','jobs/'+pid+'.json']:
        raise ValueError('binding_metadata_target_changed')
    expected_files={'player-sync/'+pid+'.json','jobs/'+pid+'.json','executions/'+cid+'.json',
        'jobs/'+cid+'.json','all-coin-sync/'+cid+'.json','config/automation.json',
        'config/player-sync.json','/var/lib/fc27-gallery/settings.json'}
    if set(scope['expected_files'])!=expected_files:raise ValueError('binding_cas_closure_incomplete')
    if set(scope['source_metadata']) != set(scope['expected_sources']) or set(scope['expected_sources']) != {'/opt/fc27-cloud-browser/'+name+'.py' for name in APP_MODULES-{'p2pah_session_service'}}:
        raise ValueError('binding_source_closure_incomplete')
    if set(scope['file_metadata']) != set(scope['expected_files']):
        raise ValueError('binding_file_metadata_incomplete')
    for digest in list(scope['expected_sources'].values())+list(scope['expected_files'].values()):
        if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('binding_digest_invalid')
    policy_root=scope['state_root'].rsplit('/',1)[0]+'/config/'
    if set(scope['policy_lock_metadata']) != {policy_root+'automation.lock',policy_root+'player-sync.lock'}:
        raise ValueError('binding_policy_locks_incomplete')
    for metadata in list(scope['lock_metadata'].values())+list(scope['policy_lock_metadata'].values()):
        if (any(type(metadata.get(k)) is not int for k in ['uid','gid','device','inode'])
                or metadata['uid']!=0 or metadata['gid'] not in [0,scope['service_gid']]
                or metadata['device']<0 or metadata['inode']<=0
                or int(metadata['mode'],8)&0o002 or metadata.get('nlink',1)!=1):
            raise ValueError('binding_lock_metadata_invalid')
    evidence=scope['writer_protocol_evidence']
    if set(evidence) != {'api','worker','timer'}:raise ValueError('binding_writer_evidence_incomplete')
    for role in ['api','worker','timer']:
        if evidence[role].get('protocol') != 'existing-tick-inode-v4':raise ValueError('binding_writer_protocol_not_proven')
        if role!='timer' and (type(evidence[role].get('pid')) is not int or evidence[role]['pid']<=0 or not re.fullmatch('[0-9]+',str(evidence[role].get('start_ticks','')))):
            raise ValueError('binding_writer_identity_invalid')
    validate_writer_receipts(scope)
    if scope['proof_provenance'].get('loader') != 'sealed-memory-v1':raise ValueError('binding_snapshot_provenance_required')
    modules=scope['proof_provenance'].get('modules',{})
    if set(modules)!={'player_sync_job','coin_all_sync_job','storefront_monitor','p2pah_session_service'}:
        raise ValueError('binding_proof_closure_incomplete')
    for name,value in modules.items():
        path='/usr/local/bin/p2pah_session_service.py' if name=='p2pah_session_service' else '/opt/fc27-cloud-browser/'+name+'.py'
        if set(value)!={'path','sha256'} or value['path']!=path or not re.fullmatch('[0-9a-f]{64}',value['sha256']):
            raise ValueError('binding_proof_origin_invalid')
        if name!='p2pah_session_service' and scope['expected_sources'][path]!=value['sha256']:
            raise ValueError('binding_proof_source_mismatch')
    if files is not None:
        for path,wanted in scope['expected_sources'].items():
            if sha(files['app/'+PurePosixPath(path).name])!=wanted:raise ValueError('binding_source_artifact_mismatch')
        if sha(files['app/p2pah_session_service.py'])!=modules['p2pah_session_service']['sha256']:
            raise ValueError('binding_image_helper_artifact_mismatch')


def main():
    if '__file__' in globals():
        raise ValueError('approved_inline_launcher_required')
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact', required=True)
    parser.add_argument('--manifest-sha', required=True)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--binding-sha', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.no_site or os.name != 'posix' or os.geteuid() != 0:
        raise ValueError('isolated_native_root_launcher_required')
    files, dirs = collect(args.artifact)
    manifest = validate_bundle(files, dirs, args.manifest_sha)
    binding_path = PurePosixPath(args.binding)
    if str(binding_path).startswith(args.artifact.rstrip('/') + '/'):
        raise ValueError('runtime_binding_must_be_separate')
    parent = open_directory(str(binding_path.parent), private=True)
    try:
        binding_raw = read_fd(parent, binding_path.name, binding=True)
    finally:
        os.close(parent)
    if sha(binding_raw) != args.binding_sha:
        raise ValueError('runtime_binding_changed')
    scope = json.loads(binding_raw)
    validate_binding(scope,json.loads(files['BINDING-SCHEMA.json']),args.manifest_sha,args.artifact,files)
    if (sys.version != scope['host_python']['version']
            or sha(open(sys.executable, 'rb').read()) != scope['host_python']['executable_sha256']):
        raise ValueError('host_interpreter_changed_before_candidate_exec')
    # This is the first candidate execution, after closure and binding validation.
    loader = type(sys)('verified_loader')
    loader.__file__ = 'verified-memory:' + sha(files['verified_loader.py']) + '/verified_loader.py'
    exec(compile(files['verified_loader.py'], loader.__file__, 'exec'), loader.__dict__)
    sys.modules['verified_loader'] = loader
    names = CANDIDATE_MODULES - {'verified_loader'}
    finder = loader.install({n: files[n + '.py'] for n in names},
        {n: manifest['files'][n + '.py'] for n in names},
        {n: args.artifact + '/' + n + '.py' for n in names}, names)
    import runner
    runner.run(scope, args.manifest_sha, args.binding_sha, files, args.apply, validate_writer_receipts)


if __name__ == '__main__':
    try:
        main()
    except BlockingIOError:
        print(json.dumps({'status':'stopped_without_business_replay','business_posts':0,
            'reason':'reconcile_mutex_busy','retryable':True}))
        raise SystemExit(2)
    except Exception as exc:
        print(json.dumps({'status': 'stopped_without_business_replay', 'business_posts': 0,
            'reason': str(exc)[:120] if isinstance(exc, ValueError) else type(exc).__name__}))
        raise SystemExit(2)
