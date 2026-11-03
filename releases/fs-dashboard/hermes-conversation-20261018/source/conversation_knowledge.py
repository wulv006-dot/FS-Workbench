"""Native knowledge consumption on the original turn/grant chain; no executor or publisher."""
from contextlib import contextmanager
import json
from pathlib import Path
import re

SHARED_PROFILE = Path('/var/lib/fs-hermes-fc/profile')
APPROVED_SKILLS = Path('/var/lib/fs-hermes-memory-approval/published-skills')
READ_TOOLS = frozenset({'fs_get_knowledge_index', 'fs_read_knowledge'})


def helper(root, receipts):
    # Publisher supplies this exact existing helper, not a second resolver.
    from fs_native_knowledge import NativeKnowledge
    return NativeKnowledge(root, SHARED_PROFILE, APPROVED_SKILLS, receipt_root=receipts)


def validate_reference(reference, binding):
    if reference is None:
        return
    if (type(reference) is not dict or set(reference) != {'info', 'pin_sha256'}
            or not re.fullmatch('[a-f0-9]{64}', reference.get('pin_sha256') or '')):
        raise PermissionError('native_knowledge_reference')
    info = reference['info']
    if (type(info) is not dict or set(info) != {'owner', 'session_id', 'platform', 'profile_name'}
            or info['owner'] != binding['owner'] or info['session_id'] != binding['session_id']
            or info['platform'] != 'api_server' or type(info['profile_name']) is not str
            or not 1 <= len(info['profile_name']) <= 200):
        raise PermissionError('native_knowledge_identity')


def host_paths(native, binding):
    from conversation_native import private_directory, sha
    root = private_directory(native.store.path.parent / 'knowledge', sha(binding['owner'].encode()))
    return root, root / (binding['turn_id'] + '.json')


def reference_for(native, binding):
    from conversation_native import regular_bytes
    root, path = host_paths(native, binding)
    value = json.loads(regular_bytes(path, 8192, root=root))
    if type(value) is not dict or set(value) != {'reference'}:
        raise PermissionError('native_knowledge_reference')
    validate_reference(value['reference'], binding)
    return value['reference']


def lock_knowledge(native, binding, environment):
    """Freeze before POST; the durable original turn never chooses current again."""
    from conversation_native import regular_bytes, sha
    from controller import atomic
    root, path = host_paths(native, binding)
    if path.exists():
        return reference_for(native, binding)
    reference = None
    configured = False
    if (native.hermes.root / 'knowledge-load-policy.json').exists():
        from knowledge_catalog import load_policy
        routes = load_policy(native.hermes.root).get('task_routes', {})
        configured = routes.get('enabled') is True and any(
            row.get('owner') == binding['owner'] and row.get('project') == 'FS'
            and row.get('channel') == 'fs' and 'conversation' in row.get('task_types', [])
            for row in routes.get('routes', []))
    if configured:
        # Official SDK pin 71d34bad treats the stored profiles/<name> home as authoritative.
        # NativeWorkspace already derives this exact home from _owned and sha(owner); no arbitrary basename.
        profile_key = sha(binding['owner'].encode('utf-8'))
        if Path(environment['profile']) != native.workspace.root / 'profiles' / profile_key:
            raise PermissionError('native_knowledge_profile')
        info = dict(owner=binding['owner'], session_id=binding['session_id'], platform='api_server',
                    profile_name=profile_key)
        def authorized(candidate, turn):
            if candidate != info or turn != binding['turn_id'] or native.hermes.authorizer(info['owner']) is not True:
                return False
            row = native.row(info['owner'], binding['conversation_id'], turn)
            with native.store.db() as db:
                conversation = native.store._owned(db, info['owner'], binding['conversation_id'])
            return row is not None and row['binding'] == binding and not row['stopped'] and conversation['session_id'] == info['session_id']
        pin = helper(native.hermes.root, root).pin_fs_task(info, binding['turn_id'], authorize=authorized)
        if pin is not None:
            reference = dict(info=info, pin_sha256=pin['receipt_sha256'])
    # Persist even the unconfigured result; a later publication cannot change this turn.
    atomic(path, dict(reference=reference), mode=0o600)
    regular_bytes(path, 8192, root=root)
    return reference


def host_call(native, binding, value):
    if (type(value) is not dict or value.get('binding') != binding
            or native.authorized(binding) is not True):
        raise PermissionError('native_chat_inactive')
    reference = reference_for(native, binding)
    if reference is None or value.get('reference') != reference:
        raise PermissionError('native_knowledge_reference')
    root, _ = host_paths(native, binding)
    knowledge = helper(native.hermes.root, root)
    info, turn = reference['info'], binding['turn_id']
    pin = knowledge.load_task(info, turn, turn, expected_sha256=reference['pin_sha256'])
    if value.get('operation') == 'load' and set(value) == {'binding', 'reference', 'operation'}:
        result = pin
    elif (value.get('operation') == 'read' and set(value) == {'binding', 'reference', 'operation', 'name', 'arguments'}
          and value['name'] in READ_TOOLS):
        # Host receipts and worker activation have different roots: no cross-process turn-lock cycle.
        with knowledge.activate_task(info, turn, turn, pin_sha256=reference['pin_sha256']):
            if native.authorized(binding) is not True:
                raise PermissionError('native_chat_inactive')
            result = knowledge.call(value['name'], value['arguments'], session_id=info['session_id'], task_id=turn)
    else:
        raise PermissionError('native_knowledge_operation')
    if native.authorized(binding) is not True:
        raise PermissionError('native_chat_inactive')
    return result


class WorkerKnowledge:
    def __init__(self, item, backend, call):
        from hermes_constants import profile_name_for_home
        self.binding = item['native_chat']['binding']
        self.reference = item['native_chat']['knowledge']
        validate_reference(self.reference, self.binding)
        if self.reference['info']['profile_name'] != profile_name_for_home(backend.profile):
            raise PermissionError('native_knowledge_profile')
        self.backend, self.call_host = backend, call
        self.aliases = set()
        self.agent = None
        self.knowledge = helper(backend.profile, backend.profile / '.fs-native-knowledge')
        pin = self.rpc('load')
        material = {k: v for k, v in pin.items() if k != 'receipt_sha256'}
        # Exact host pin is transported privately; no release selection or formal-directory write here.
        from fs_native_knowledge import catalog
        if catalog.digest(material) != self.reference['pin_sha256'] or pin.get('receipt_sha256') != self.reference['pin_sha256']:
            raise PermissionError('native_knowledge_pin_changed')
        name = self.knowledge._name('task', pin['identity'])
        if not (self.knowledge.receipt_root / name).exists():
            self.knowledge._save(name, material)
        self.pin = self.knowledge.load_task(self.reference['info'], self.binding['turn_id'],
            self.binding['turn_id'], expected_sha256=self.reference['pin_sha256'])

    def rpc(self, operation, **fields):
        self.backend.check()
        value = self.call_host('fs.native.knowledge', dict(binding=self.binding,
            reference=self.reference, operation=operation, **fields), session_id=self.binding['session_id'])
        self.backend.check()
        return json.loads(value)

    def prompt(self):
        return self.knowledge.pin_prompt(self.pin)

    def read(self, name, arguments, task_id):
        self.backend.check(task_id)
        if task_id != self.binding['turn_id'] or self.agent is None:
            raise PermissionError('native_knowledge_task')
        if self.knowledge.active_task(self.agent.session_id, task_id) != self.pin:
            raise PermissionError('native_knowledge_inactive')
        return self.rpc('read', name=name, arguments=arguments)

    def link(self, child):
        self.backend.check(self.binding['turn_id'])
        if self.knowledge.active_task(self.pin['session_id'], self.binding['turn_id']) != self.pin:
            raise PermissionError('native_knowledge_inactive')
        if child != self.pin['session_id']:
            self.aliases.add(self.knowledge.link_task_session(self.pin, child, self.binding['turn_id']))

    @contextmanager
    def scope(self):
        turn = self.binding['turn_id']
        with self.knowledge.activate_task(self.reference['info'], turn, turn, pin_sha256=self.reference['pin_sha256']):
            try:
                yield
            finally:
                for name in self.aliases:
                    self.knowledge.unlink_task_session(name, self.pin)
                self.aliases.clear()


def register_scope(registry, scope):
    """Only the admitted native agent explicitly enables this profile overlay."""
    from toolsets import create_custom_toolset
    fields = dict(modules=dict(type='array', items=dict(type='string'), minItems=1),
        entry_ids=dict(type='array', items=dict(type='string')), revision=dict(type='string'),
        history=dict(type='boolean'), skill_id=dict(type='string'))
    for name in sorted(READ_TOOLS):
        schema = dict(name=name, description='Read the current turn pinned formal knowledge; no business action.',
            parameters=dict(type='object', properties={'history': fields['history']} if name == 'fs_get_knowledge_index' else fields,
                            required=[] if name == 'fs_get_knowledge_index' else ['modules'], additionalProperties=False))
        def handler(arguments, _name=name, **context):
            from conversation_native import current_native_backend
            backend = current_native_backend()
            knowledge = getattr(backend, 'knowledge', None)
            if knowledge is None:
                raise PermissionError('native_knowledge_inactive')
            return json.dumps(knowledge.read(_name, arguments, context.get('task_id')), ensure_ascii=False)
        previous = registry.get_entry(name, scope=scope)
        if previous is None or previous.handler.__module__ != __name__ or previous.schema != schema:
            registry.register(name=name, toolset='fs_native_knowledge', schema=schema, handler=handler, scope=scope)
    create_custom_toolset('fs_native_knowledge', 'This admitted native turn pinned knowledge', tools=sorted(READ_TOOLS))
