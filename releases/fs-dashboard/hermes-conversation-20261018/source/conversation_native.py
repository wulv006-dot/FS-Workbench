"""Host binding between the original conversation store and official Hermes Runs.

This module contains no model client or agent loop. User text and attachment bytes
remain unchanged; the runtime supplies the actual native tools and their sandbox.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import tempfile
import time

NATIVE_ROOT = '/var/lib/fs-hermes-fc/native'
NATIVE_IMAGE = 'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'
NATIVE_DOCKER = '/opt/fs-native-bin/docker'
BACKEND_HOME = '/opt/fs-native-backend-home'
_NATIVE_BACKEND = ContextVar('fs_native_backend', default=None)
_NATIVE_PROFILE = ContextVar('fs_native_profile', default=None)


def current_native_backend():
    return _NATIVE_BACKEND.get()


def current_native_profile():
    return _NATIVE_PROFILE.get()


@contextmanager
def native_owner_scope(item):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from agent.secret_scope import (build_profile_secret_scope, set_secret_scope, reset_secret_scope,
                                    set_multiplex_context, reset_multiplex_context)
    validate_native_admission(item)
    profile = Path(item['native_chat']['environment']['profile'])
    profile_token = _NATIVE_PROFILE.set(profile)
    home_token = set_hermes_home_override(profile)
    secret_token = multiplex_token = None
    try:
        secret_token = set_secret_scope(build_profile_secret_scope(profile), profile_home=str(profile))
        multiplex_token = set_multiplex_context(True)
        yield
    finally:
        if multiplex_token is not None:reset_multiplex_context(multiplex_token)
        if secret_token is not None:reset_secret_scope(secret_token)
        reset_hermes_home_override(home_token)
        _NATIVE_PROFILE.reset(profile_token)


def native_profile_config():
    # Native tools write proposals. Only the existing independent review applies them.
    return {'memory': {'memory_enabled': True, 'user_profile_enabled': True, 'write_approval': True},
            'skills': {'write_approval': True},
            'model': {'default': 'deepseek-flash', 'provider': 'custom',
                      'base_url': 'http://127.0.0.1:8940/v1', 'context_length': 1048576}}


def validate_native_profile(config, profile):
    # Owner settings remain editable; approval and owner path boundaries do not.
    if type(config) is not dict or any(type(config.get(section)) is not dict or
            config[section].get('write_approval') is not True for section in ('memory','skills')):
        raise PermissionError('native_write_approval_required')
    directories=config['skills'].get('external_dirs',[])
    if type(directories) is not list:
        raise PermissionError('native_skill_directory')
    profile=Path(profile).resolve()
    for directory in directories:
        if type(directory) is not str:
            raise PermissionError('native_skill_directory')
        path=profile/directory[2:] if directory.startswith('~/') else (profile if directory=='~' else Path(directory))
        if not path.is_absolute():path=profile/path
        try:path.resolve().relative_to(profile)
        except ValueError:raise PermissionError('native_skill_directory') from None
    return config


def validate_native_admission(item):
    value = item.get('native_chat')
    fields = {'owner','conversation_id','turn_id','request_id','session_id','lease','run_id'}
    if type(value) is not dict or set(value) != {'binding','environment','key','fingerprint'}:
        raise PermissionError('native_admission_invalid')
    bound = value['binding']
    if (type(bound) is not dict or set(bound) != fields or bound['session_id'] != item['session_id'] or
            any(type(bound[key]) is not str or not bound[key] for key in fields-{'run_id'}) or
            not re.fullmatch('[a-f0-9]{32}', bound['conversation_id']) or
            not re.fullmatch('[a-f0-9]{32}', bound['turn_id']) or
            not re.fullmatch('[a-f0-9]{32}', bound['lease']) or
            not re.fullmatch('hn-[a-f0-9]{64}', value['key'] or '') or
            not re.fullmatch('[a-f0-9]{64}', value['fingerprint'] or '')):
        raise PermissionError('native_admission_invalid')
    if item.get('ready') is True and (bound['run_id'] != item.get('run_id') or
            not re.fullmatch('run_[a-f0-9]{32}', bound['run_id'] or '')):
        raise PermissionError('native_admission_run')
    environment = value['environment']
    if (type(environment) is not dict or set(environment) != {'profile','workspace','files'} or
            environment['workspace'] != NATIVE_ROOT+'/workspaces/'+bound['conversation_id'] or
            environment['profile'] != NATIVE_ROOT+'/profiles/'+sha(bound['owner'].encode()) or
            type(environment['files']) is not list):
        raise PermissionError('native_admission_paths')
    return bound


def docker_policy(binding, root=NATIVE_ROOT):
    cid = binding.get('conversation_id')
    if not re.fullmatch('[a-f0-9]{32}', cid or ''):
        raise ValueError('native_backend_conversation')
    workspace = str(Path(root) / 'workspaces' / cid)
    return {'TERMINAL_ENV': 'docker', 'TERMINAL_CWD': workspace,
            'TERMINAL_DOCKER_IMAGE': NATIVE_IMAGE, 'TERMINAL_DOCKER_IMAGE_PINNED': '1',
            'TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE': 'true',
            'TERMINAL_DOCKER_VOLUMES': '[]', 'TERMINAL_DOCKER_ENV': '{}',
            'TERMINAL_DOCKER_FORWARD_ENV': '[]', 'TERMINAL_DOCKER_NETWORK': 'true',
            'TERMINAL_DOCKER_RUN_AS_HOST_USER': 'true', 'TERMINAL_CONTAINER_DISK': '0',
            'TERMINAL_CONTAINER_PERSISTENT': 'false', 'TERMINAL_DOCKER_PERSIST_ACROSS_PROCESSES': 'false',
            'TERMINAL_DOCKER_ORPHAN_REAPER': 'false', 'TERMINAL_DOCKER_SHARED_CONTAINER_KEY': '',
            'TERMINAL_DOCKER_EXTRA_ARGS': canonical(['--pull=never', '--entrypoint=/usr/bin/env'])}


def validate_docker_command(command, workspace, image=NATIVE_IMAGE):
    """Check the SDK's *actual* launch argv before its first daemon write."""
    if (type(command) is not list or command[:3] != [NATIVE_DOCKER, 'run', '-d'] or
            command[-3:] != [image, 'sleep', 'infinity']):
        raise ValueError('native_docker_command')
    args, mounts = command[3:-3], []
    denied = {'--privileged', '--volumes-from', '--device', '--device-cgroup-rule', '--env-file', '--publish', '-p', '-P', '--group-add'}
    for index, value in enumerate(args):
        name, equal, suffix = value.partition('=')
        if name in denied or name in {'-e', '--env'}:
            raise PermissionError('native_docker_authority')
        if name in {'--net', '--network'} and (suffix if equal else args[index+1]) != 'bridge':
            raise PermissionError('native_docker_network')
        if name in {'--pid', '--ipc', '--userns', '--cgroupns'} and (suffix if equal else args[index+1]) == 'host':
            raise PermissionError('native_docker_host_namespace')
        if name in {'-v', '--volume'}:
            mounts.append(suffix if equal else args[index+1])
        elif value.startswith('-v') and value != '-v':
            raise PermissionError('native_docker_mount')
        if name == '--mount':
            raise PermissionError('native_docker_mount')
    users=[value.partition('=')[2] if '=' in value else args[index+1]
           for index,value in enumerate(args) if value.partition('=')[0] in {'--user','-u'}]
    if users!=['9876:9876']:raise PermissionError('native_docker_user')
    if mounts != [workspace + ':/workspace']:
        raise PermissionError('native_docker_mount')
    if not any(value in {'--cap-drop=ALL', '--cap-drop=all'} for value in args) and not any(
            args[i:i+2] in (['--cap-drop', 'ALL'], ['--cap-drop', 'all']) for i in range(len(args))):
        raise PermissionError('native_docker_capabilities')
    if not any('no-new-privileges' in value for value in args):
        raise PermissionError('native_docker_privileges')
    return True


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(value).hexdigest()


def readonly_native_run(path, *, scope, key, fingerprint, session_id, owner_alive, now=None):
    """SELECT-only official lookup. Missing/expired never proves non-submission."""
    import hmac
    path = Path(path or '')
    if path.is_symlink() or not path.is_file():
        raise OSError('native_official_store_unavailable')
    now = time.time() if now is None else now
    db = None
    try:
        db = sqlite3.connect(path.absolute().as_uri() + '?mode=ro', uri=True, timeout=5)
        db.execute('PRAGMA query_only=ON')
        row = db.execute("SELECT fingerprint,run_id,json_extract(status_json,'$.session_id'),"
                         "json_extract(status_json,'$.status'),owner_pid,owner_started,updated_at "
                         'FROM run_idempotency WHERE scope=? AND idempotency_key=?', (scope, key)).fetchone()
    except sqlite3.Error:
        raise OSError('native_official_store_unavailable') from None
    finally:
        if db is not None:db.close()
    if row is None:
        return {'status': 'unknown', 'run_id': None}
    if (type(row[0]) is not str or not hmac.compare_digest(row[0], fingerprint) or
            row[2] != session_id or not re.fullmatch('run_[a-f0-9]{32}', row[1] or '')):
        raise PermissionError('native_official_binding_changed')
    state = row[3]
    terminal = state in {'completed', 'failed', 'cancelled', 'interrupted'}
    live = owner_alive(row[4], row[5]) is True
    if now - row[6] > 86400 or (not terminal and not live):
        state = 'unknown'
    if state not in {'queued', 'running', 'waiting_for_approval', 'completed', 'failed', 'cancelled', 'interrupted', 'unknown'}:
        state = 'unknown'
    return {'status': state, 'run_id': row[1], 'session_id': session_id, 'owner_alive': live}


def private_directory(root, *parts):
    root = Path(root).absolute()
    for parent in [*reversed(root.parents), root]:
        if parent.is_symlink():
            raise ValueError('native_linked_directory')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for part in parts:
        root = root / part
        if root.is_symlink():
            raise ValueError('native_linked_directory')
        root.mkdir(mode=0o700, exist_ok=True)
    return root


@contextmanager
def workspace_file(root, relative, flags, mode=0o600):
    """Linux openat chain: a racing parent symlink must never reach host files."""
    root=Path(root);relative=Path(relative)
    if relative.is_absolute() or not relative.parts or any(p in ('.','..') for p in relative.parts):
        raise ValueError('native_relative_file')
    if os.name!='posix':
        # Local Windows fixtures only; the deployed backend/publisher is Linux.
        current=root
        for part in relative.parts:
            current=current/part
            if current.is_symlink():raise ValueError('native_linked_file')
        fd=os.open(current,flags,mode)
        try:yield fd
        finally:os.close(fd)
        return
    directories=[]
    try:
        directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);directories.append(directory)
        for part in relative.parts[:-1]:
            directory=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
            directories.append(directory)
        fd=os.open(relative.parts[-1],flags|os.O_NOFOLLOW,mode,dir_fd=directory)
        try:yield fd
        finally:os.close(fd)
    finally:
        for directory in reversed(directories):os.close(directory)


def workspace_regular_files(root):
    """Enumerate descriptors, not paths a model process can redirect mid-walk."""
    root=Path(root)
    if os.name!='posix':
        for directory,dirs,names in os.walk(root,followlinks=False):
            for name in [*dirs,*names]:
                if (Path(directory)/name).is_symlink():raise ValueError('native_linked_file')
            for name in sorted(names):yield (Path(directory)/name).relative_to(root).as_posix()
        return
    def walk(fd,prefix):
        with os.scandir(fd) as entries:
            names=sorted(entry.name for entry in entries)
        for name in names:
            info=os.stat(name,dir_fd=fd,follow_symlinks=False)
            relative=prefix+name
            if stat.S_ISDIR(info.st_mode):
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                try:yield from walk(child,relative+'/')
                finally:os.close(child)
            elif stat.S_ISREG(info.st_mode):yield relative
            else:raise ValueError('native_nonregular_workspace_entry')
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:yield from walk(fd,'')
    finally:os.close(fd)


def regular_bytes(path, maximum, *, root=None):
    """Never publish a link or bytes changing while a terminal run is collected."""
    if root is None and path.is_symlink():
        raise ValueError('native_linked_file')
    @contextmanager
    def opened():
        if root is not None:
            with workspace_file(root,Path(path).relative_to(root),os.O_RDONLY|getattr(os,'O_NONBLOCK',0)) as fd:yield fd
        else:
            fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
            try:yield fd
            finally:os.close(fd)
    with opened() as fd,os.fdopen(os.dup(fd),'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise ValueError('native_file_kind_or_size')
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    if (len(raw) > maximum or len(raw) != after.st_size or
            (before.st_ino, before.st_dev, before.st_mtime_ns, before.st_size) !=
            (after.st_ino, after.st_dev, after.st_mtime_ns, after.st_size)):
        raise ValueError('native_file_changed')
    return raw


def workspace_digest(root, relative, maximum):
    try:return sha(regular_bytes(Path(root)/relative,maximum,root=root))
    except FileNotFoundError:return None


class NativeWorkspace:
    """Conversation-scoped raw files and owner-scoped approved memory/skills."""
    def __init__(self, store, root, *, runtime_owner=None):
        self.store, self.root = store, private_directory(root)
        self.runtime_owner = runtime_owner
        self._own(self.root)
        from conversation_files import ConversationFiles
        self.files = ConversationFiles(store)
        with store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS native_workspace_files ('
                       'cid TEXT NOT NULL,path TEXT NOT NULL,file_id TEXT NOT NULL,sha256 TEXT NOT NULL,'
                       'PRIMARY KEY(cid,path))')
            db.execute('CREATE TABLE IF NOT EXISTS native_file_exports ('
                       'cid TEXT NOT NULL,run_id TEXT NOT NULL,path TEXT NOT NULL,file_id TEXT NOT NULL,'
                       'PRIMARY KEY(cid,run_id,path))')
            db.execute('CREATE TABLE IF NOT EXISTS native_collected_runs ('
                       'cid TEXT NOT NULL,run_id TEXT NOT NULL,PRIMARY KEY(cid,run_id))')

    def _own(self, path):
        if self.runtime_owner is not None:
            os.chown(path, *self.runtime_owner, follow_symlinks=False)

    def _directory(self, *parts):
        path = private_directory(self.root, *parts)
        current = self.root
        for part in parts:
            current = current / part
            self._own(current)
        return path

    def paths(self, owner, cid):
        if not re.fullmatch('[a-f0-9]{32}', cid or ''):
            raise LookupError('conversation_not_found')
        with self.store.db() as db:
            self.store._owned(db, owner, cid)
        return (self._directory('workspaces', cid), self._directory('profiles', sha(owner.encode('utf-8'))))

    def prepare(self, owner, cid, file_ids=()):
        from conversation_files import MAX_BYTES
        workspace, profile = self.paths(owner, cid)
        config = profile / 'config.yaml'
        expected = canonical(native_profile_config()).encode()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store._owned(db, owner, cid)
            # The original DB writer lock also serializes first profile creation
            # across two conversations of the same owner.
            if config.exists():
                regular_bytes(config,65536)  # SDK parses this owner's existing YAML; never overwrite it.
            else:
                with config.open('xb') as stream:
                    os.chmod(config,0o600)
                    self._own(config)
                    stream.write(expected)
            for fid in file_ids:
                item = self.files.read(owner, cid, fid, _db=db)
                # The display name never determines the storage root or a host path.
                suffix = Path(item['filename']).suffix
                suffix = suffix if re.fullmatch(r'\.[A-Za-z0-9]{1,16}',suffix) else '.bin'
                relative = 'uploads/' + fid + suffix
                parent = private_directory(workspace, 'uploads')
                self._own(parent)
                for previous in db.execute('SELECT path FROM native_workspace_files WHERE cid=? AND file_id=? AND sha256=?',
                                           (cid,fid,item['sha256'])):
                    if workspace_digest(workspace,previous['path'],MAX_BYTES)==item['sha256']:
                        relative=previous['path'];break
                target = workspace / relative
                current=workspace_digest(workspace,relative,MAX_BYTES)
                if current is not None and current != item['sha256']:
                    # Preserve a previous edit. Explicitly choosing an immutable
                    # older version gets a fresh copy rather than a hidden reset.
                    relative='uploads/'+fid+'-'+secrets.token_hex(8)+suffix
                    target=workspace/relative
                    current=None
                if current is None:
                    with workspace_file(workspace,relative,os.O_WRONLY|os.O_CREAT|os.O_EXCL) as fd,os.fdopen(os.dup(fd),'wb') as stream:
                        if os.name=='posix':os.fchmod(fd,0o600)
                        if self.runtime_owner is not None:os.fchown(fd,*self.runtime_owner)
                        stream.write(item['content'])
                elif current != item['sha256']:
                    raise ValueError('native_input_changed')
                db.execute('INSERT OR IGNORE INTO native_workspace_files VALUES(?,?,?,?)',
                           (cid, relative, fid, item['sha256']))
            attachments = []
            for row in db.execute('SELECT * FROM native_workspace_files WHERE cid=? ORDER BY path', (cid,)):
                item = self.files.describe(owner, cid, row['file_id'], _db=db)
                if (item['status'] == 'available' and
                        workspace_digest(workspace,row['path'],MAX_BYTES) == row['sha256']):
                    attachments.append({'file_id': row['file_id'], 'filename': item['filename'],
                                        'path': row['path'], 'sha256': row['sha256'], 'size': item['size']})
        return {'workspace': str(workspace), 'profile': str(profile), 'files': attachments}

    def collect(self, owner, cid, run_id, *, authorize=None, publish=None):
        from conversation_files import MAX_BYTES
        if not re.fullmatch('run_[a-f0-9]{32}', run_id or ''):
            raise ValueError('native_run_id')
        workspace, _ = self.paths(owner, cid)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store._owned(db, owner, cid)
            if authorize is not None and authorize(db) is not True:
                return []
            if db.execute('SELECT 1 FROM native_collected_runs WHERE cid=? AND run_id=?', (cid, run_id)).fetchone():
                rows = db.execute('SELECT file_id FROM native_file_exports WHERE cid=? AND run_id=? ORDER BY path', (cid, run_id))
                cards = [self.files.describe(owner, cid, row['file_id'], _db=db) for row in rows]
                if publish is not None:publish(db,cards)
                return cards
            known = {row['path']: dict(row) for row in db.execute('SELECT * FROM native_workspace_files WHERE cid=?', (cid,))}
            cards = []
            count = 0
            for relative in workspace_regular_files(workspace):
                count += 1
                if count > 1000:raise ValueError('native_file_count')
                raw=regular_bytes(workspace/relative,MAX_BYTES,root=workspace)
                # Caches and empty intermediate files are not downloadable
                # outputs. Keep them in the workspace without failing valid
                # exports; the link/kind/size/stability checks above still run.
                if not raw or any(part.startswith('.') for part in Path(relative).parts):continue
                digest=sha(raw);previous=known.get(relative)
                if previous and previous['sha256']==digest:continue
                filename=(self.files.metadata(self.files.directory(cid),previous['file_id'])['filename']
                          if previous else Path(relative).name)
                request_id='native_'+sha((run_id+'\0'+relative+'\0'+digest).encode())[:64]
                item=self.files.save(owner,cid,filename,raw,request_id,
                                     previous['file_id'] if previous else None,generated=True,_db=db)
                db.execute('INSERT OR REPLACE INTO native_workspace_files VALUES(?,?,?,?)',(cid,relative,item['file_id'],digest))
                db.execute('INSERT INTO native_file_exports VALUES(?,?,?,?)',(cid,run_id,relative,item['file_id']))
                cards.append(self.files.describe(owner,cid,item['file_id'],_db=db))
            db.execute('INSERT INTO native_collected_runs VALUES(?,?)', (cid, run_id))
            if publish is not None:publish(db,cards)
            return cards


class NativeDockerBackend:
    """FS scopes around the unchanged official Docker/file/tool implementation."""
    def __init__(self, item, authorize):
        self.binding = item['native_chat']['binding']
        self.item = item
        self.environment = item['native_chat']['environment']
        self.authorize = authorize
        bound = self.binding
        if (type(bound) is not dict or not bound.get('run_id') or
                item.get('run_id') != bound['run_id'] or item['session_id'] != bound['session_id']):
            raise PermissionError('native_worker_binding')
        self.profile = Path(NATIVE_ROOT) / 'profiles' / sha(bound['owner'].encode())
        self.workspace = Path(NATIVE_ROOT) / 'workspaces' / bound['conversation_id']
        if (self.environment['profile'] != str(self.profile) or
                self.environment['workspace'] != str(self.workspace)):
            raise PermissionError('native_worker_paths')
        from tools.terminal_scope import build_profile_terminal_scope
        inherited=build_profile_terminal_scope(self.profile)
        self.policy = docker_policy(bound, root=NATIVE_ROOT)
        for key in ('TERMINAL_CONTAINER_CPU','TERMINAL_CONTAINER_MEMORY'):
            if key in inherited:self.policy[key]=inherited[key]

    def check(self, task_id=None):
        if task_id not in (None, self.binding['session_id']) or self.authorize() is not True:
            raise PermissionError('native_worker_inactive')

    @contextmanager
    def scope(self, *, check=True):
        from tools.terminal_scope import set_terminal_scope, reset_terminal_scope
        from agent.runtime_cwd import set_session_cwd, reset_session_cwd
        if check:self.check()
        native_token = _NATIVE_BACKEND.set(self)
        terminal_token = set_terminal_scope(dict(self.policy))
        cwd_token = set_session_cwd(str(self.workspace))
        try:
            with native_owner_scope(self.item):
                yield self
        finally:
            reset_session_cwd(cwd_token)
            reset_terminal_scope(terminal_token)
            _NATIVE_BACKEND.reset(native_token)

    def ensure_environment(self):
        from tools.terminal_tool_lifecycle import ensure_task_env
        from tools.terminal_tool import register_task_env_overrides
        from tools.environments.docker import DockerEnvironment
        with self.scope():
            register_task_env_overrides(self.binding['session_id'],
                                       {'env_type': 'docker', 'cwd': str(self.workspace),
                                        'cwd_source': 'session', 'docker_image': NATIVE_IMAGE})
            environment = ensure_task_env(self.binding['session_id'])
            if not isinstance(environment, DockerEnvironment):
                raise PermissionError('native_backend_not_docker')
            previous=getattr(environment,'_fs_native_backend',None)
            keys=('owner','conversation_id','session_id')
            if (previous is None or any(previous.binding[key]!=self.binding[key] for key in keys) or
                    getattr(environment,'_image',None)!=NATIVE_IMAGE or
                    getattr(environment,'host_cwd',None)!=str(self.workspace)):
                raise PermissionError('native_backend_cache_binding')
            environment._fs_native_backend=self
            return environment

    @contextmanager
    def empty_backend_home(self):
        """SDK auto-mount discovery sees an empty read-only home, not user secrets."""
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        root = Path(BACKEND_HOME)
        if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
            raise PermissionError('native_backend_home_not_empty')
        if not os.statvfs(root).f_flag & os.ST_RDONLY:
            raise PermissionError('native_backend_home_not_readonly')
        token = set_hermes_home_override(root)
        try:
            yield
        finally:
            reset_hermes_home_override(token)

    def observe_pending(self, name, result, register):
        subsystem = {'memory': 'memory', 'skill_manage': 'skills'}.get(name)
        if subsystem is None:
            return
        try:
            value = json.loads(result) if isinstance(result, str) else result
        except (TypeError, ValueError):
            return
        if (type(value) is not dict or value.get('staged') is not True or
                not re.fullmatch('[a-f0-9]{8}', value.get('pending_id', ''))):
            return
        from tools import write_approval
        record = write_approval.get_pending(subsystem, value['pending_id'])
        if (type(record) is dict and record.get('id') == value['pending_id'] and
                record.get('subsystem') == subsystem):
            register({'binding': self.binding, 'subsystem': subsystem, 'pending_id': record['id'],
                      'record_sha256': sha(canonical(record).encode())})


def install_native_backend_guards():
    """Wrap FS's SDK boundary once; no SDK files, loop, or handlers are copied."""
    import functools
    import model_tools
    from tools.environments import docker
    from agent.inline_tool_executors import INLINE_TOOL_EXECUTORS
    for name, original in list(INLINE_TOOL_EXECUTORS.items()):
        if getattr(original,'_fs_native_guard',False):
            continue
        def guard_inline(function, tool_name):
            @functools.wraps(function)
            def execute(agent, arguments, context):
                backend = current_native_backend()
                if backend is not None:
                    backend.check(context.effective_task_id)
                    if tool_name == 'memory':
                        from tools.write_approval import write_approval_enabled
                        if write_approval_enabled('memory') is not True:
                            raise PermissionError('native_memory_approval_unavailable')
                return function(agent,arguments,context)
            execute._fs_native_guard=True
            return execute
        INLINE_TOOL_EXECUTORS[name]=guard_inline(original,name)
    DockerEnvironment = docker.DockerEnvironment
    if not getattr(DockerEnvironment.__init__, '_fs_native_guard', False):
        original_init = DockerEnvironment.__init__
        original_command = DockerEnvironment._run_command
        original_mounts = docker._readonly_skill_mount_args
        @functools.wraps(original_mounts)
        def automatic_mounts():
            backend = current_native_backend()
            if backend is None:
                return original_mounts()
            backend.check()
            # Only mount discovery sees the empty home. Configuration loading
            # elsewhere in the constructor needs the real owner profile.
            with backend.empty_backend_home():
                return original_mounts()
        @functools.wraps(original_init)
        def initialize(environment, *args, **kwargs):
            backend = current_native_backend()
            if backend is None:
                return original_init(environment, *args, **kwargs)
            backend.check()
            environment._fs_native_backend = backend
            return original_init(environment, *args, **kwargs)
        @functools.wraps(original_command)
        def command(environment, name, workdir):
            result = original_command(environment, name, workdir)
            backend = getattr(environment, '_fs_native_backend', None)
            if backend is not None:
                backend.check()
                validate_docker_command(result, str(backend.workspace))
            return result
        initialize._fs_native_guard = True
        DockerEnvironment.__init__ = initialize
        DockerEnvironment._run_command = command
        docker._readonly_skill_mount_args = automatic_mounts
    if not getattr(model_tools.handle_function_call, '_fs_native_guard', False):
        original_call = model_tools.handle_function_call
        @functools.wraps(original_call)
        def call(name, arguments, *args, **kwargs):
            backend = current_native_backend()
            if backend is not None:
                task_id = kwargs.get('task_id', args[0] if args else None)
                if task_id != backend.binding['session_id']:
                    raise PermissionError('native_tool_session_missing')
                backend.check(task_id)
                if name == 'skill_manage':
                    from tools.write_approval import write_approval_enabled
                    if write_approval_enabled('skills') is not True:
                        raise PermissionError('native_skill_approval_unavailable')
                from tools.terminal_scope import get_terminal_scope
                if get_terminal_scope() != backend.policy:
                    raise PermissionError('native_terminal_policy_changed')
            return original_call(name, arguments, *args, **kwargs)
        call._fs_native_guard = True
        model_tools.handle_function_call = call
        # A module imported before make_adapter may already hold the same function.
        import sys
        executor = sys.modules.get('agent.tool_executor')
        if executor is not None and getattr(executor, 'handle_function_call', None) is original_call:
            executor.handle_function_call = call


class NativeConversation:
    """Durable native Runs binding; an internal turn is not an FC report task."""
    def __init__(self, service):
        self.service, self.store, self.hermes = service, service.store, service.hermes
        self.reconciling = set()
        self.workspace = NativeWorkspace(self.store, getattr(self.hermes, 'native_root', self.hermes.root / 'native'),
                                         runtime_owner=getattr(self.hermes, 'native_ownership', None))
        with self.store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS native_conversation_runs ('
                       'turn_id TEXT PRIMARY KEY,binding TEXT NOT NULL,body TEXT NOT NULL,'
                       'idempotency_key TEXT NOT NULL UNIQUE,fingerprint TEXT NOT NULL,'
                       'schemas TEXT,stopped INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS native_pending_sources ('
                       'owner TEXT NOT NULL,cid TEXT NOT NULL,turn_id TEXT NOT NULL,session_id TEXT NOT NULL,'
                       'run_id TEXT NOT NULL,profile_key TEXT NOT NULL,lease TEXT NOT NULL,subsystem TEXT NOT NULL,'
                       'pending_id TEXT NOT NULL,record_sha256 TEXT NOT NULL,'
                       'PRIMARY KEY(owner,subsystem,pending_id,record_sha256))')
        previous=getattr(self.hermes.tasks,'_native_active_model_tasks',None)
        if previous is not None and getattr(getattr(getattr(previous,'__self__',None),'store',None),'path',None) != self.store.path:
            raise RuntimeError('native_liveness_store_conflict')
        self.hermes.tasks._native_active_model_tasks=self.native_only_active_tasks

    def row(self, owner, cid, turn_id):
        if self.store.is_archived(owner,cid,turn_id):return None
        with self.store.db() as db:
            self.store._owned(db, owner, cid)
            row = db.execute('SELECT * FROM native_conversation_runs WHERE turn_id=?', (turn_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result['binding'] = json.loads(result['binding'])
        if (result['binding']['owner'], result['binding']['conversation_id']) != (owner, cid):
            raise PermissionError('native_binding_owner')
        return result

    def authorized(self, binding):
        if self.hermes.authorizer(binding['owner']) is not True:
            return False
        row = self.row(binding['owner'], binding['conversation_id'], binding['turn_id'])
        if row is None or row['stopped'] or row['binding'] != binding or not binding['run_id']:
            return False
        turn = self.store.run(binding['owner'], binding['conversation_id'], binding['run_id'])
        return (turn['state'] in {'queued', 'running'} and
                (turn['task_id'], turn['lease']) == (binding['turn_id'], binding['lease']))

    def active_tasks(self):
        from fs_inprocess import active_model_tasks
        return set(active_model_tasks(self.hermes.tasks))

    def native_only_active_tasks(self):
        """Host liveness for all existing FC/native budget consumers, no recursion."""
        result=set()
        if self.store.path.is_symlink() or not self.store.path.is_file():
            raise OSError('native_liveness_unavailable')
        from contextlib import closing
        with closing(sqlite3.connect(self.store.path.absolute().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
            db.row_factory=sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            for row in db.execute('SELECT n.binding,t.id,t.conversation_id,t.task_id,t.lease,t.run_id,c.owner '
                                  'FROM native_conversation_runs n JOIN turns t ON t.id=n.turn_id '
                                  'JOIN conversations c ON c.id=t.conversation_id '
                                  "WHERE t.state IN ('queued','running') AND n.stopped=0"):
                bound=json.loads(row['binding'])
                if (set(bound) != {'owner','conversation_id','turn_id','request_id','session_id','lease','run_id'} or
                        any(type(v) is not str or not v for v in bound.values()) or
                        (bound['owner'],bound['conversation_id'],bound['turn_id'],bound['turn_id'],bound['lease'],bound['run_id']) !=
                        (row['owner'],row['conversation_id'],row['id'],row['task_id'],row['lease'],row['run_id'])):
                    raise PermissionError('native_liveness_binding')
                result.add((bound['owner'],bound['turn_id']))
        return result

    def register_schemas(self, binding, value):
        """Only the admitted worker's private grant calls this, never a turn body."""
        if not self.authorized(binding):
            raise PermissionError('native_chat_inactive')
        expected = {'binding', 'model_schemas', 'catalog_sha256', 'registry_generation', 'reasoning_effort'}
        if (type(value) is not dict or set(value) != expected or value['binding'] != binding or
                type(value['model_schemas']) is not list or
                not re.fullmatch('[a-f0-9]{64}', value['catalog_sha256'] or '') or
                type(value['registry_generation']) is not int or value['registry_generation'] < 0):
            raise ValueError('native_schema_registration')
        if value['reasoning_effort'] not in ('none','minimal','low','medium','high','xhigh','max','ultra'):
            raise ValueError('native_reasoning_config')
        raw = canonical(value)
        if len(raw.encode()) > 2 * 1024 * 1024:
            raise ValueError('native_schema_size')
        # NativeChatScope independently validates every model-visible definition.
        from native_chat import NativeChatScope
        NativeChatScope(binding, lambda: self.authorized(binding), model_schemas=lambda: value['model_schemas']).schemas()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store._owned(db, binding['owner'], binding['conversation_id'])
            previous = db.execute('SELECT schemas,stopped,binding FROM native_conversation_runs WHERE turn_id=?',
                                  (binding['turn_id'],)).fetchone()
            if (previous is None or previous['stopped'] or json.loads(previous['binding']) != binding or
                    previous['schemas'] not in (None, raw)):
                raise PermissionError('native_schema_changed')
            db.execute('UPDATE native_conversation_runs SET schemas=? WHERE turn_id=?', (raw, binding['turn_id']))
        return {'registered': True, 'model_schema_sha256': sha(canonical(value['model_schemas']).encode())}

    def schemas(self, binding):
        if not self.authorized(binding):
            raise PermissionError('native_chat_inactive')
        row = self.row(binding['owner'], binding['conversation_id'], binding['turn_id'])
        if row['schemas'] is None:
            raise PermissionError('native_schema_not_measured')
        return json.loads(row['schemas'])['model_schemas']

    def reasoning_effort(self, binding):
        if not self.authorized(binding):raise PermissionError('native_chat_inactive')
        row=self.row(binding['owner'],binding['conversation_id'],binding['turn_id'])
        if row['schemas'] is None:raise PermissionError('native_schema_not_measured')
        return json.loads(row['schemas']).get('reasoning_effort','none')

    def register_pending(self, binding, value):
        if (type(value) is not dict or set(value) != {'binding', 'subsystem', 'pending_id', 'record_sha256'} or
                value['binding'] != binding or value['subsystem'] not in {'memory', 'skills'} or
                not re.fullmatch('[a-f0-9]{8}', value['pending_id'] or '') or
                not re.fullmatch('[a-f0-9]{64}', value['record_sha256'] or '')):
            raise ValueError('native_pending_source')
        if not self.authorized(binding):
            raise PermissionError('native_chat_inactive')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store._owned(db, binding['owner'], binding['conversation_id'])
            db.execute('INSERT OR IGNORE INTO native_pending_sources VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (binding['owner'], binding['conversation_id'], binding['turn_id'], binding['session_id'],
                        binding['run_id'], sha(binding['owner'].encode()), binding['lease'],
                        value['subsystem'], value['pending_id'], value['record_sha256']))
        return {'registered': True}

    def host_tool(self, binding, name, arguments):
        if name == 'fs.native.check':
            if arguments != {'binding': binding} or not self.authorized(binding):
                raise PermissionError('native_chat_inactive')
            return {'authorized': True}
        if name == 'fs.native.register_schemas':
            return self.register_schemas(binding, arguments)
        if name == 'fs.native.pending_source':
            return self.register_pending(binding, arguments)
        raise PermissionError('native_host_tool_unavailable')

    def dispatch(self, owner, cid, turn_id, session_id, text, request_id):
        from conversation_file_bindings import FileBindings
        from fs_inprocess import native_gateway
        from native_chat import NativeChatScope
        token = None
        bound = dict(owner=owner, conversation_id=cid, turn_id=turn_id, request_id=request_id,
                     session_id=session_id, lease=secrets.token_hex(16), run_id=None)
        body = {'input': text, 'session_id': session_id}
        key = 'hn-' + sha(canonical([owner, cid, request_id]).encode())
        fingerprint = sha(canonical({'body': body, 'gateway_session_key': ''}).encode())
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            conversation = self.store._owned(db, owner, cid)
            turn = db.execute('SELECT text,request_id,state FROM turns WHERE id=? AND conversation_id=?', (turn_id, cid)).fetchone()
            if (turn is None or turn['text'] != text or turn['request_id'] != request_id or
                    conversation['session_id'] != session_id):
                raise PermissionError('native_turn_binding')
            if db.execute('SELECT 1 FROM native_conversation_runs WHERE turn_id=?', (turn_id,)).fetchone():
                return  # A persisted original request is looked up, never submitted again.
            if turn['state'] != 'preparing':
                raise PermissionError('native_turn_state')
            files = FileBindings(self.store).bound(db, owner, cid, turn_id)['inputs']
            db.execute('INSERT INTO native_conversation_runs(turn_id,binding,body,idempotency_key,fingerprint) '
                       'VALUES(?,?,?,?,?)', (turn_id, canonical(bound), canonical(body), key, fingerprint))
        try:
            if self.hermes.authorizer(owner) is not True:
                raise PermissionError('native_chat_revoked')
            environment = self.workspace.prepare(owner, cid, files)
            self.store.bind_task(owner, cid, turn_id, turn_id, bound['lease'])
            token = self.hermes.grants.mint(owner, turn_id, bound['lease'], reasoning_effort='none')
            admission = {'session_id': session_id, 'token': token, 'model': 'deepseek-flash',
                         'prompt': '', 'conversation': True, 'ready': False,
                         'native_chat': {'binding': bound, 'environment': environment,
                                         'key': key, 'fingerprint': fingerprint}}
            self.write_admission(session_id, admission)
            # Exactly one POST. Loss of 202 leaves the original persisted key unknown.
            code, result = self.service._request('POST', '/v1/runs', body, key)
            if code != 202 or not re.fullmatch('run_[a-f0-9]{32}', result.get('run_id', '')):
                raise ValueError('native_admission_unknown')
            bound['run_id'] = result['run_id']
            self.store.bind_run(owner, cid, turn_id, bound['run_id'])
            with self.store.db() as db:
                db.execute('UPDATE native_conversation_runs SET binding=? WHERE turn_id=?', (canonical(bound), turn_id))
            scope = NativeChatScope(bound, lambda: self.authorized(bound), model_schemas=lambda: self.schemas(bound),
                                    reasoning_effort=lambda: self.reasoning_effort(bound), call_tool=lambda name, args: self.host_tool(bound, name, args))
            item_gateway = native_gateway(self.hermes.daily, scope, active_tasks=self.active_tasks)
            with self.hermes.lock:
                self.hermes.tokens[turn_id] = token
                self.hermes.books[turn_id] = scope
                self.hermes.gateways[turn_id] = item_gateway
            live = (turn_id, bound['lease'], token)
            with self.service.lock:
                self.service.live[turn_id] = live
            admission['native_chat']['binding'] = bound
            admission.update(run_id=bound['run_id'], ready=True)
            self.write_admission(session_id, admission)
            self.service._monitor(owner, cid, turn_id, bound['run_id'], live)
        except Exception:
            # Retain the mapping/body/key and every file; no alternate request is made.
            self.store.set_state(owner, cid, turn_id, 'dispatch_unknown')
            if token:
                self.hermes.grants.revoke(token)
            self.fence(owner,cid,turn_id)
            with self.service.lock:
                live=self.service.live.get(turn_id)
            self.service._release_live(turn_id,live)
            raise

    def reconcile_unknown(self, owner, cid, turn_id):
        """Find the original reserved run without a new POST or execution grant."""
        if self.hermes.authorizer(owner) is not True:
            raise PermissionError('native_chat_revoked')
        row = self.row(owner, cid, turn_id)
        if row is None or row['binding']['run_id']:
            return
        bound = row['binding']
        code, found = self.service._request('GET', '/v1/native/' + bound['session_id'])
        if code != 200 or type(found) is not dict:
            raise OSError('native_lookup_unavailable')
        run_id = found.get('run_id')
        if run_id is None or found.get('status') == 'unknown':
            return  # Missing/expired/stale is unknown, never permission to resubmit.
        if (found.get('session_id') != bound['session_id'] or
                not re.fullmatch('run_[a-f0-9]{32}', run_id or '') or
                found.get('status') not in {'queued','running','waiting_for_approval','completed','failed','cancelled','interrupted'}):
            raise PermissionError('native_lookup_binding')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store._owned(db, owner, cid)
            current = db.execute('SELECT binding FROM native_conversation_runs WHERE turn_id=?', (turn_id,)).fetchone()
            if current is None or current['binding'] != canonical(bound):
                raise PermissionError('native_lookup_race')
            turn = db.execute('SELECT run_id,state FROM turns WHERE id=? AND conversation_id=?', (turn_id,cid)).fetchone()
            if turn is None or turn['run_id'] not in (None,run_id) or turn['state'] != 'dispatch_unknown':
                raise PermissionError('native_lookup_race')
            bound['run_id'] = run_id
            db.execute('UPDATE native_conversation_runs SET binding=? WHERE turn_id=?', (canonical(bound),turn_id))
            db.execute("UPDATE turns SET run_id=?,state='queued' WHERE id=?", (run_id,turn_id))
        self.service._recover(owner,cid,turn_id,run_id)

    def schedule_reconcile(self, owner, cid, turn_id):
        # One in-flight lookup per turn. No lock is held across HTTP or the
        # original monitor; a refresh cannot create a second execution.
        with self.service.lock:
            if turn_id in self.reconciling:
                return
            self.reconciling.add(turn_id)
        def reconcile():
            try:
                self.reconcile_unknown(owner,cid,turn_id)
            except (OSError,ValueError,LookupError,PermissionError):
                pass  # Original UNKNOWN remains visible; no grant or POST retry.
            finally:
                with self.service.lock:
                    self.reconciling.discard(turn_id)
        self.service.pool.submit(reconcile)

    def write_admission(self, session_id, value):
        from controller import atomic
        # Match the existing root-writer/nonroot-worker admission contract.
        atomic(self.service.run_root / 'admissions' / (session_id + '.json'), value, mode=0o640)

    def fence(self, owner, cid, turn_id):
        if self.store.is_archived(owner,cid,turn_id):return
        row = self.row(owner, cid, turn_id)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store._owned(db, owner, cid)
            db.execute('UPDATE native_conversation_runs SET stopped=1 WHERE turn_id=?', (turn_id,))
        if row:
            path = self.service.run_root / 'admissions' / (row['binding']['session_id'] + '.json')
            if path.exists() and not path.is_symlink():
                value = json.loads(path.read_text('utf-8'))
                if value.get('native_chat', {}).get('binding') == row['binding']:
                    value['ready'] = False
                    self.write_admission(row['binding']['session_id'], value)

    def complete(self, owner, cid, turn_id, run_id):
        row = self.row(owner, cid, turn_id)
        if row is None or row['stopped']:
            return []
        from conversation_file_bindings import FileBindings
        def authorized(db):
            current=db.execute('SELECT binding,stopped FROM native_conversation_runs WHERE turn_id=?',(turn_id,)).fetchone()
            return (current is not None and not current['stopped'] and
                    json.loads(current['binding'])['run_id']==run_id and self.hermes.authorizer(owner) is True)
        def publish(db,cards):
            bindings = FileBindings(self.store)
            files = bindings.bound(db, owner, cid, turn_id)
            files['generated'] = sorted(set(files['generated']) | {item['file_id'] for item in cards})
            bindings.write(cid, turn_id, files)
        return self.workspace.collect(owner,cid,run_id,authorize=authorized,publish=publish)

    def append_event(self, owner, cid, turn_id, run_id, sequence, event):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store._owned(db,owner,cid)
            row=db.execute('SELECT binding,stopped FROM native_conversation_runs WHERE turn_id=?',(turn_id,)).fetchone()
            if row is None or json.loads(row['binding'])['run_id']!=run_id:
                raise PermissionError('native_event_binding')
            if row['stopped'] and event.get('event') in {'message.delta','message.interim','run.completed'}:
                return None
            return self.store.append_event(owner,cid,run_id,sequence,event,_db=db)
