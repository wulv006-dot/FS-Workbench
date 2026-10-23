"""Native session knowledge adapter. No publisher, model call or business transport."""
import hashlib
import json
import os
import re
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

import knowledge_catalog as catalog
from report_artifacts import write_file

READ_TOOLS = {'fs_get_knowledge_index', 'fs_read_knowledge'}
LOCK = RLock()


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', value):
        raise ValueError('native_knowledge_identity')
    return value


class NativeKnowledge:
    def __init__(self, root='/fs'):
        self.root = Path(root)

    def _name(self, kind, key):
        return 'knowledge/native/' + kind + '-' + catalog.digest(key) + '.json'

    def _read(self, name):
        value = json.loads(catalog.read_bound(self.root, name))
        material = {k: v for k, v in value.items() if k != 'receipt_sha256'}
        if value.get('receipt_sha256') != catalog.digest(material):
            raise ValueError('native_knowledge_receipt_changed')
        return value

    @contextmanager
    def _receipt_lock(self, parent):
        fd = os.open(parent / '.receipt.lock', os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (os.name == 'posix' and (
                    info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077)):
                raise ValueError('native_knowledge_unsafe_receipt_lock')
            if info.st_size == 0:
                os.write(fd, b'0')
            deadline = time.monotonic() + 10
            while True:
                try:
                    if os.name == 'posix':
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    else:
                        import msvcrt
                        os.lseek(fd, 0, 0); msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except (BlockingIOError, PermissionError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError('native_knowledge_receipt_busy')
                    time.sleep(0.01)
            yield
        finally:
            os.close(fd)

    def _save(self, name, value):
        value = dict(value, receipt_sha256=catalog.digest(value))
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
        if len(raw) > 1048576:
            raise ValueError('native_knowledge_receipt_too_large')
        parent = self.root / 'knowledge/native'
        if any(p.is_symlink() for p in (parent, *parent.parents)):
            raise ValueError('native_knowledge_path_link')
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._receipt_lock(parent):
            # Extend the existing writer's check+atomic-replace to a cross-process CAS.
            write_file(self.root / name, raw)
            if os.name == 'posix':
                fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            return value

    def _policy(self):
        try:
            info = (self.root / 'knowledge-load-policy.json').lstat()
            if os.name == 'posix' and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022):
                raise ValueError('native_knowledge_policy_owner')
            value = json.loads(catalog.read_bound(self.root, 'knowledge-load-policy.json'))
        except FileNotFoundError:
            return {}
        if not isinstance(value, dict) or value.get('contract') != 'fs-knowledge-load-policy-v1':
            raise ValueError('native_knowledge_policy_contract')
        native = value.get('native', {})
        if not isinstance(native, dict) or not isinstance(native.get('routes', []), list) or not isinstance(native.get('readonly_sessions', {}), dict):
            raise ValueError('native_knowledge_policy_shape')
        return native

    def pin(self, info):
        session = identity(info.get('session_id'))
        name = self._name('session', session)
        with LOCK:
            if (self.root / name).exists():
                value = self._read(name)
                if any(value[k] != info.get(k) for k in ('session_id', 'platform', 'profile_name')):
                    raise ValueError('native_knowledge_session_identity_changed')
                return value
            policy = self._policy()
            if policy.get('enabled') is not True:
                return None
            # Native metadata is supplied by core, never by model tool arguments.
            if info.get('platform') not in ('desktop', 'tui'):
                return None
            routes = [r for r in policy.get('routes', []) if
                      r['platform'] == info.get('platform') and r['profile_name'] == info.get('profile_name')]
            if not routes:
                return None
            if len(routes) != 1:
                raise ValueError('native_knowledge_route_conflict')
            route = routes[0]
            sessions = route.get('session_ids')
            if sessions is not None and (not isinstance(sessions, list) or not sessions or
                                         any(not isinstance(x, str) for x in sessions)):
                raise ValueError('native_knowledge_route_sessions')
            if sessions is not None and session not in sessions:
                return None
            pointer = route['catalog']
            if not pointer.startswith('knowledge-releases/') or not pointer.endswith('/index.json'):
                raise ValueError('native_knowledge_release_boundary')
            raw = catalog.read_bound(self.root, pointer)
            if hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() != route['sha256']:
                raise ValueError('native_knowledge_catalog_changed')
            index = catalog.validate(json.loads(raw))
            if index['release_state'] != 'published':
                raise ValueError('native_knowledge_not_published')
            modules = route['modules']
            if not isinstance(modules, list) or not modules or not all(isinstance(x, str) for x in modules):
                raise ValueError('native_knowledge_modules')
            entries = [{k: row[k] for k in ('id', 'revision', 'layer', 'status', 'modules', 'effective_at', 'source', 'supersedes')}
                       for row in index['entries'] if row['layer'] != 'candidate' and set(row['modules']) & set(modules)]
            readonly = policy.get('readonly_sessions', {}).get(session)
            if readonly is not None:
                if not isinstance(readonly, dict) or not isinstance(readonly.get('task_ids'), list) or not readonly['task_ids']:
                    raise ValueError('native_knowledge_test_tasks_required')
                for task in readonly['task_ids']:
                    identity(task)
            return self._save(name, dict(contract='fs-native-knowledge-pin-v1', session_id=session,
                              platform=info['platform'], profile_name=info['profile_name'], catalog=pointer,
                              catalog_sha256=route['sha256'], release=index['release'], source_commit=index['source_commit'],
                              modules=modules, entries=entries, readonly=readonly))

    def bound(self, session):
        value = self._read(self._name('session', identity(session)))
        if value['session_id'] != session:
            raise ValueError('native_knowledge_session_mismatch')
        return value

    def prompt(self, info):
        # A missing/malformed session identity must not restrict ordinary unrelated chats.
        if not info.get('session_id'):
            return ''
        try:
            pin = self.bound(info['session_id'])
            if any(pin[k] != info.get(k) for k in ('platform', 'profile_name')):
                raise ValueError('native_knowledge_session_identity_changed')
        except FileNotFoundError:
            return ''
        except (ValueError, OSError, KeyError, TypeError):
            return 'FS知识加载不可用；不可声称已加载现行正式知识，保留原会话能力，勿猜版本。'
        if pin is None:
            return ''
        active = [{k: row[k] for k in ('id', 'revision', 'layer', 'status', 'modules', 'effective_at')}
                  for row in pin['entries'] if catalog.ACTIVE.get(row['layer']) == row['status'] or row['status'] == 'conflict']
        header = ('FS知识短索引；会话固定已发布版本，按模块/ID调用fs_read_knowledge，冲突或缺项如实返回。'
                  '候选不作规则；默认索引仅有效条目；历史查询先以history=true读索引，再以history=true及所需revision读原文，不作为当前执行约束。'
                  '路径日期不代表文件修订或生效时间；按条目revision、effective_at与time_precision陈述，未记载就说未知。'
                  '不要自报调用次数；成功、失败和重试以原生工具事件审计为准。文本不授予业务权限；索引用fs_get_knowledge_index。\n')
        summary = dict(release=pin['release'], catalog_sha256=pin['catalog_sha256'],
                       receipt_sha256=pin['receipt_sha256'], modules=pin['modules'], entries=active, additional_entries=0)
        while len(header + json.dumps(summary, ensure_ascii=False)) > 4000:
            if not summary['entries']:
                return 'FS知识索引超过原生提示限额；使用fs_get_knowledge_index读取固定版本，不猜规则。'
            summary['entries'].pop()
            summary['additional_entries'] += 1
        return header + json.dumps(summary, ensure_ascii=False)

    def guard(self, tool_name='', args=None, session_id='', task_id='', **kwargs):
        if not session_id:
            return None
        try:
            pin = self.bound(session_id)
        except FileNotFoundError:
            # Declared tests must be admitted/pinned before any model or tool execution.
            try:
                declared = self._policy().get('readonly_sessions', {})
            except (ValueError, OSError, TypeError):
                return None  # Test admission still refuses; unrelated normal tools stay unchanged.
            if session_id not in declared:
                return None
            return {'action': 'block', 'message': 'FS只读测试尚未准入，禁止工具执行。'}
        if pin.get('readonly') is None:
            return None
        if task_id not in pin['readonly']['task_ids'] or tool_name not in READ_TOOLS:
            return {'action': 'block', 'message': 'FS只读测试仅允许已绑定请求读取知识；该工具或任务不在范围。'}
        return None

    def call(self, name, args, session_id='', task_id='', **kwargs):
        if name not in READ_TOOLS or not isinstance(args, dict):
            raise ValueError('native_knowledge_tool_fields')
        allowed = {'history'} if name == 'fs_get_knowledge_index' else {'modules', 'entry_ids', 'revision', 'history'}
        if set(args) - allowed:
            raise ValueError('native_knowledge_tool_fields')
        if 'history' in args and type(args['history']) is not bool:
            raise ValueError('native_knowledge_history_type')
        identity(task_id)
        pin = self.bound(session_id)
        if self.guard(name, args, session_id, task_id):
            raise PermissionError('native_knowledge_test_scope')
        key = dict(session_id=session_id, task_id=task_id, tool=name, args=args)
        if name == 'fs_get_knowledge_index':
            # Keep old receipts immutable; their unfiltered index is a different response contract.
            key['index_version'] = 2
        path = self._name('use', key)
        with LOCK:
            if (self.root / path).exists():
                saved = self._read(path)
                if saved['identity'] != key or saved['pin_sha256'] != pin['receipt_sha256']:
                    raise ValueError('native_knowledge_use_conflict')
                return saved['result']
            if name == 'fs_get_knowledge_index':
                result = {k: pin[k] for k in ('release', 'catalog_sha256', 'source_commit', 'modules', 'entries')}
                result['history'] = args.get('history', False)
                result['history_available'] = any(r['layer'] == 'archive' for r in pin['entries'])
                if not result['history']:
                    result['entries'] = [r for r in pin['entries'] if
                                         catalog.ACTIVE.get(r['layer']) == r['status'] or r['status'] == 'conflict']
                result['status'] = 'index_only'
            else:
                modules = args.get('modules')
                if not isinstance(modules, list) or not modules or not all(isinstance(x, str) for x in modules) or not set(modules) <= set(pin['modules']):
                    raise ValueError('native_knowledge_module_scope')
                result = catalog.select(self.root, pin['catalog'], pin['catalog_sha256'], modules,
                                        args.get('entry_ids'), args.get('revision'), args.get('history', False))
            self._save(path, dict(contract='fs-native-knowledge-use-v1', identity=key,
                                 pin_sha256=pin['receipt_sha256'], result=result))
            return result

    def test_admission(self, info, task_id):
        pin = self.pin(info)
        if pin is None or pin.get('readonly') is None or task_id not in pin['readonly']['task_ids']:
            raise PermissionError('native_knowledge_test_not_admitted')
        return dict(enabled_toolsets=['fs_knowledge'], skip_memory=True, skip_background_review=True)

    def test_agent(self, factory, info, task_id, **model_options):
        """Only the approved isolated test caller uses this; ordinary agent construction is unchanged."""
        grants = self.test_admission(info, task_id)
        agent = factory(**dict(model_options, **grants, session_id=info['session_id'], platform=info['platform']))
        self.verify_test_agent(agent, info['session_id'], task_id)
        return agent

    def verify_test_agent(self, agent, session_id, task_id):
        pin = self.bound(session_id)
        if (pin.get('readonly') is None or task_id not in pin['readonly']['task_ids']
                or getattr(agent, 'session_id', None) != session_id
                or set(getattr(agent, 'valid_tool_names', ())) != READ_TOOLS
                or {x['function']['name'] for x in getattr(agent, 'tools', [])} != READ_TOOLS):
            raise PermissionError('native_knowledge_test_agent_grants_changed')


def register(ctx):
    from toolsets import TOOLSET_SESSION_PLATFORMS
    previous = TOOLSET_SESSION_PLATFORMS.get('fs_knowledge')
    if previous is not None and set(previous) != {'desktop', 'tui'}:
        raise ValueError('native_knowledge_toolset_platform_conflict')
    # Native defaults exclude gated toolsets; other platforms also subtract them explicitly.
    TOOLSET_SESSION_PLATFORMS['fs_knowledge'] = {'desktop', 'tui'}
    adapter = NativeKnowledge()
    ctx.register_system_prompt_section('fs.knowledge', adapter.prompt, max_chars=4000)
    ctx.register_hook('pre_tool_call', adapter.guard)
    fields = {'modules': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1},
              'entry_ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1},
              'revision': {'type': 'string', 'description': 'Exact historical revision; requires history=true. Use when an id has multiple versions.'},
              'history': {'type': 'boolean', 'description': 'Default false: current effective content. True only for an explicit historical question; archived/retired content is not a current rule.'}}
    for name in sorted(READ_TOOLS):
        index = name == 'fs_get_knowledge_index'
        properties = {'history': fields['history']} if index else fields
        description = ('Read the pinned index. Default lists active entries only; history=true also lists archive/retired metadata for explicit historical questions.' if index else
                       'Read pinned original text by modules and entry_ids. For history use history=true and exact revision when an id has multiple versions. Never mix archive ids into a default current read.')
        schema = dict(name=name, description=description + ' No business action. Preserve scope, status, source and hashes; call counts come from native events, not self-estimates.',
                      parameters=dict(type='object', properties=properties, required=[] if index else ['modules'], additionalProperties=False))
        def handler(args, _name=name, **context):
            return json.dumps(adapter.call(_name, args, **context), ensure_ascii=False)
        ctx.register_tool(name=name, toolset='fs_knowledge', schema=schema, handler=handler)
