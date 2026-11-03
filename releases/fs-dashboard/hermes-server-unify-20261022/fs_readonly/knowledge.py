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
    def __init__(self, root='/fs', profile_root='/profile', approved_skills_root='/approved-skills', *, receipt_root=None):
        self.root = Path(root)
        self.receipt_root = self.root if receipt_root is None else Path(receipt_root)
        self.profile_root = Path(profile_root)
        self.approved_skills_root = Path(approved_skills_root)

    def _name(self, kind, key):
        return 'knowledge/native/' + kind + '-' + catalog.digest(key) + '.json'

    def _read(self, name):
        value = json.loads(catalog.read_bound(self.receipt_root, name))
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
        parent = self.receipt_root / 'knowledge/native'
        if any(p.is_symlink() for p in (parent, *parent.parents)):
            raise ValueError('native_knowledge_path_link')
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._receipt_lock(parent):
            # Extend the existing writer's check+atomic-replace to a cross-process CAS.
            write_file(self.receipt_root / name, raw)
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
            if (self.receipt_root / name).exists():
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

    def task_selection(self, info):
        if info.get('platform') not in ('desktop', 'tui', 'feishu'):
            return None
        if not info.get('owner') or not info.get('profile_name'):
            return None
        if info['platform'] == 'feishu' and not info.get('chat_id'):
            return None
        return catalog.task_selection(self.root, owner=info['owner'], project='FS',
            channel=info['platform'], task_type='conversation', profile_name=info['profile_name'],
            chat_id=info.get('chat_id'), thread_id=info.get('thread_id'))

    def pin_task(self, info, task_key, native_task_id):
        session = identity(info.get('session_id'))
        identity(task_key); identity(native_task_id)
        key = dict(session_id=session, task_key=task_key)
        name = self._name('task', key)
        scope = {k: info.get(k) for k in ('owner', 'platform', 'profile_name', 'chat_id', 'thread_id')}
        with LOCK:
            if (self.receipt_root / name).exists():
                pin = self._read(name)
                if pin['identity'] != key or pin['scope'] != scope or pin['native_task_id'] != native_task_id:
                    raise ValueError('native_knowledge_task_identity_changed')
                return pin
            selected = self.task_selection(info)
            if selected is None:
                return None
            catalog.verify_selection(selected)
            if selected['status'] != 'available' or selected['history']:
                raise ValueError('native_knowledge_task_selection_not_current')
            raw = catalog.read_bound(self.root, selected['catalog'])
            if hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() != selected['catalog_sha256']:
                raise ValueError('native_knowledge_catalog_changed')
            index = catalog.validate(json.loads(raw))
            allowed_ids = selected.get('entry_ids')
            history_ids = set(selected.get('history_entry_ids', []))
            archive_ids = {row['id'] for row in index['entries'] if row['layer'] == 'archive'
                           and set(row['modules']) & set(selected['modules'])}
            if history_ids - archive_ids:
                raise ValueError('native_knowledge_history_entry_scope')
            entries = [{k: row[k] for k in ('id', 'revision', 'layer', 'status', 'modules', 'effective_at', 'source', 'supersedes')}
                       for row in index['entries'] if row['layer'] != 'candidate'
                       and set(row['modules']) & set(selected['modules'])
                       and (allowed_ids is None or row['id'] in allowed_ids
                            or row['layer'] == 'archive' and row['id'] in history_ids)]
            skills = dict(status='not_configured', items=[], documents=[])
            reviewed = selected.get('reviewed_skills')
            if reviewed is not None:
                from reviewed_skills import current_catalog, list_reviewed, read_reviewed_skill
                if reviewed == {'source': 'approved_current'}:
                    listing = current_catalog(self.profile_root / 'skills', self.approved_skills_root,
                                              [m.lower() for m in selected['modules']])
                    index_path = self.approved_skills_root / 'versions' / (str(listing['sha256']) + '.json')
                else:
                    if reviewed['index'] != 'knowledge/reviewed-skills.json':
                        raise ValueError('native_reviewed_skill_index_boundary')
                    try:
                        catalog.read_bound(self.root, reviewed['index'])
                    except FileNotFoundError:
                        listing = dict(missing=True, items=[], sha256=None)
                    else:
                        listing = list_reviewed(self.profile_root / 'skills', self.root / reviewed['index'],
                            [m.lower() for m in selected['modules']], expected_index_sha=reviewed['sha256'])
                    index_path = self.root / reviewed['index']
                skills = dict(status='unavailable' if listing.get('missing') else 'indexed', index_sha256=listing['sha256'],
                    items=[{k: row[k] for k in ('id', 'package_sha256', 'modules', 'description', 'review_request_id')}
                           for row in listing['items']],
                    documents=[read_reviewed_skill(self.profile_root / 'skills', index_path,
                        [m.lower() for m in selected['modules']], row['id'], row['package_sha256'],
                        expected_index_sha=listing['sha256']) for row in listing['items']])
            return self._save(name, dict(contract='fs-native-knowledge-task-v1', identity=key, scope=scope,
                native_task_id=native_task_id, session_id=session, platform=info['platform'],
                profile_name=info['profile_name'], catalog=selected['catalog'],
                catalog_sha256=selected['catalog_sha256'], release=selected['release'],
                source_commit=selected['source_commit'], modules=selected['modules'],
                entries=entries, entry_ids=allowed_ids, selection_sha256=selected['selection_sha256'],
                reviewed_skills=skills, readonly=None))

    def load_task(self, info, task_key, native_task_id, *, expected_sha256):
        """Load the caller's pinned turn; never select a newer policy or release."""
        key = dict(session_id=identity(info.get('session_id')), task_key=identity(task_key))
        identity(native_task_id)
        pin = self._read(self._name('task', key))
        scope = {k: info.get(k) for k in ('owner', 'platform', 'profile_name', 'chat_id', 'thread_id')}
        if (pin.get('contract') != 'fs-native-knowledge-task-v1' or pin['identity'] != key
                or pin['scope'] != scope or pin['native_task_id'] != native_task_id):
            raise ValueError('native_knowledge_task_identity_changed')
        if pin['receipt_sha256'] != expected_sha256:
            raise ValueError('native_knowledge_task_pin_changed')
        return pin

    def active_task(self, session, native_task_id):
        name = self._name('active', identity(session))
        try:
            active = self._read(name)
        except FileNotFoundError:
            return None
        if (active['session_id'] != session or active['native_task_id'] != native_task_id
                or active.get('pid') != os.getpid()):
            raise ValueError('native_knowledge_active_task_mismatch')
        pin = self._read(active['pin'])
        if pin['receipt_sha256'] != active['pin_sha256'] or pin['native_task_id'] != native_task_id:
            raise ValueError('native_knowledge_active_pin_changed')
        return pin

    def link_task_session(self, pin, session, native_task_id):
        """Called by the native subclass after its own compaction rotates the stored session id."""
        identity(session)
        if native_task_id != pin['native_task_id']:
            raise ValueError('native_knowledge_link_task_mismatch')
        name = self._name('active', session)
        self._save(name, dict(session_id=session, native_task_id=native_task_id, pid=os.getpid(),
            pin=self._name('task', pin['identity']), pin_sha256=pin['receipt_sha256']))
        return name

    def unlink_task_session(self, name, pin):
        if self._read(name)['pin_sha256'] != pin['receipt_sha256']:
            raise ValueError('native_knowledge_active_pin_changed')
        (self.receipt_root / name).unlink()

    @contextmanager
    def activate_task(self, info, task_key, native_task_id, *, pin_sha256=None):
        # Serialize readers of a session; FS native passes its original turn_id as task_id.
        parent = self.receipt_root / 'knowledge/native' / ('turn-' + catalog.digest(info['session_id']))
        if any(p.is_symlink() for p in (parent, *parent.parents)):
            raise ValueError('native_knowledge_path_link')
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._receipt_lock(parent):
            pin = (self.pin_task(info, task_key, native_task_id) if pin_sha256 is None else
                   self.load_task(info, task_key, native_task_id, expected_sha256=pin_sha256))
            name = self._name('active', info['session_id'])
            if (self.receipt_root / name).exists():
                stale = self._read(name)
                previous = self._read(stale['pin'])
                if stale['session_id'] != info['session_id'] or previous['receipt_sha256'] != stale['pin_sha256']:
                    raise ValueError('native_knowledge_active_pin_changed')
                # Holding the turn lease proves this transient alias has no active reader; immutable task/use receipts stay intact.
                self._save(self._name('retired-active', stale['receipt_sha256']), dict(previous_active=stale))
                (self.receipt_root / name).unlink()
            if pin is None:
                yield None
                return
            self._save(name, dict(session_id=info['session_id'], native_task_id=native_task_id, pid=os.getpid(),
                pin=self._name('task', pin['identity']), pin_sha256=pin['receipt_sha256']))
            try:
                yield pin
            finally:
                (self.receipt_root / name).unlink()

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
        return self.pin_prompt(pin)

    def pin_prompt(self, pin):
        active = [{k: row[k] for k in ('id', 'revision', 'layer', 'status', 'modules', 'effective_at')}
                  for row in pin['entries'] if catalog.ACTIVE.get(row['layer']) == row['status'] or row['status'] == 'conflict']
        scope = '本任务' if pin.get('contract') == 'fs-native-knowledge-task-v1' else '会话'
        header = ('FS知识短索引；' + scope + '固定已发布版本，按模块/ID调用fs_read_knowledge，冲突或缺项如实返回。'
                  '候选不作规则；默认索引仅有效条目；历史查询先以history=true读索引，再以history=true及所需revision读原文，不作为当前执行约束。'
                  '路径日期不代表文件修订或生效时间；按条目revision、effective_at与time_precision陈述，未记载就说未知。'
                  '不要自报调用次数；成功、失败和重试以原生工具事件审计为准。文本不授予业务权限；索引用fs_get_knowledge_index。\n')
        if scope == '本任务':
            header = '本轮知识版本以此任务receipt为准，旧会话索引只代表原时点；未列出的原有能力及权限保持。' + header
        summary = dict(release=pin['release'], catalog_sha256=pin['catalog_sha256'],
                       receipt_sha256=pin['receipt_sha256'], modules=pin['modules'], entries=active, additional_entries=0)
        if pin.get('reviewed_skills') is not None:
            summary['reviewed_skills'] = {k: v for k, v in pin['reviewed_skills'].items() if k != 'documents'}
            summary['reviewed_skills'].update(items=list(pin['reviewed_skills']['items']), additional_items=0)
            header = header.rstrip('\n') + ('已审技能目录及SKILL.md按本任务模块及包哈希冻结；'
                       '用fs_read_knowledge传modules及skill_id按需读固定正文，原skill_view能力保持。'
                       '目录存在不代表本轮已读正文或已成功运用；缺失目录不取消原技能能力。\n')
        while len(header + json.dumps(summary, ensure_ascii=False, sort_keys=True)) > 4000:
            if summary['entries']:
                summary['entries'].pop()
                summary['additional_entries'] += 1
            elif summary.get('reviewed_skills', {}).get('items'):
                summary['reviewed_skills']['items'].pop()
                summary['reviewed_skills']['additional_items'] += 1
            else:
                return 'FS知识索引超过原生提示限额；使用fs_get_knowledge_index读取固定版本，不猜规则。'
        return header + json.dumps(summary, ensure_ascii=False, sort_keys=True)

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
        allowed = {'history'} if name == 'fs_get_knowledge_index' else {'modules', 'entry_ids', 'revision', 'history', 'skill_id'}
        if set(args) - allowed:
            raise ValueError('native_knowledge_tool_fields')
        if 'history' in args and type(args['history']) is not bool:
            raise ValueError('native_knowledge_history_type')
        identity(task_id)
        pin = self.active_task(session_id, task_id) or self.bound(session_id)
        if self.guard(name, args, session_id, task_id):
            raise PermissionError('native_knowledge_test_scope')
        key = dict(session_id=session_id, task_id=task_id, tool=name, args=args)
        if pin['contract'] == 'fs-native-knowledge-task-v1':
            key['task_key'] = pin['identity']['task_key']
            key['pin_sha256'] = pin['receipt_sha256']
        if name == 'fs_get_knowledge_index':
            # Keep old receipts immutable; their unfiltered index is a different response contract.
            key['index_version'] = 2
        path = self._name('use', key)
        with LOCK:
            if (self.receipt_root / path).exists():
                saved = self._read(path)
                if saved['identity'] != key or saved['pin_sha256'] != pin['receipt_sha256']:
                    raise ValueError('native_knowledge_use_conflict')
                return saved['result']
            if name == 'fs_get_knowledge_index':
                result = {k: pin[k] for k in ('release', 'catalog_sha256', 'source_commit', 'modules', 'entries')}
                if pin['contract'] == 'fs-native-knowledge-task-v1':
                    result['entries'] = [{k: v for k, v in row.items() if k not in ('content', 'artifact_path')}
                                         for row in result['entries']]
                    result['reviewed_skills'] = {k: v for k, v in pin['reviewed_skills'].items() if k != 'documents'}
                result['history'] = args.get('history', False)
                result['history_available'] = any(r['layer'] == 'archive' for r in pin['entries'])
                if not result['history']:
                    result['entries'] = [r for r in result['entries'] if
                                         catalog.ACTIVE.get(r['layer']) == r['status'] or r['status'] == 'conflict']
                result['status'] = 'index_only'
            else:
                modules = args.get('modules')
                if not isinstance(modules, list) or not modules or not all(isinstance(x, str) for x in modules) or not set(modules) <= set(pin['modules']):
                    raise ValueError('native_knowledge_module_scope')
                if 'skill_id' in args:
                    if (pin['contract'] != 'fs-native-knowledge-task-v1' or set(args) != {'modules', 'skill_id'}
                            or not isinstance(args['skill_id'], str)):
                        raise ValueError('native_knowledge_skill_scope')
                    skills = pin['reviewed_skills']
                    item = next((row for row in skills['items'] if row['id'] == args['skill_id']
                                 and {m.casefold() for m in row['modules']} & {m.casefold() for m in modules}), None)
                    if item is None:
                        raise ValueError('native_knowledge_skill_scope')
                    doc = next(row for row in skills['documents'] if row['id'] == item['id'])
                    if hashlib.sha256(doc['content'].encode()).hexdigest() != doc['sha256']:
                        raise ValueError('native_knowledge_skill_content_changed')
                    result = dict(contract='fs-native-reviewed-skill-read-v1', status='available',
                        modules=modules, index_sha256=skills['index_sha256'], **doc)
                    self._save(path, dict(contract='fs-native-knowledge-use-v1', identity=key,
                        pin_sha256=pin['receipt_sha256'], result=result))
                    return result
                ids = args.get('entry_ids')
                if pin['contract'] == 'fs-native-knowledge-task-v1':
                    permitted = {row['id'] for row in pin['entries']}
                    if ids is not None and not set(ids) <= permitted:
                        raise ValueError('native_knowledge_entry_scope')
                    if ids is None:
                        ids = pin['entry_ids']
                result = catalog.select(self.root, pin['catalog'], pin['catalog_sha256'], modules,
                                        ids, args.get('revision'), args.get('history', False))
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
    platforms = {'desktop', 'tui', 'feishu'}
    if previous is not None and set(previous) not in ({'desktop', 'tui'}, platforms):
        raise ValueError('native_knowledge_toolset_platform_conflict')
    # Native defaults exclude gated toolsets; other platforms also subtract them explicitly.
    TOOLSET_SESSION_PLATFORMS['fs_knowledge'] = platforms
    adapter = NativeKnowledge()
    ctx.register_system_prompt_section('fs.knowledge', adapter.prompt, max_chars=4000)
    ctx.register_hook('pre_tool_call', adapter.guard)
    fields = {'modules': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1},
              'skill_id': {'type': 'string', 'description': 'Ordinary approved task only: read a selected reviewed skill SKILL.md frozen for this task. Combine only with modules; never available in isolated readonly tests.'},
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
