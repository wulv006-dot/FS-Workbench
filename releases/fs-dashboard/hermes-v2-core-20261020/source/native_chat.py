"""Host-bound native conversation scope, independent of FC report tasks.

The host supplies current authorization and the measured SDK model tool surface.
Neither a browser payload nor a model request can register capabilities here.
Native tools execute in the official runtime; this is only the model gateway scope.
"""
from copy import deepcopy
import json
import re
import threading


class NativeChatScope:
    native_chat = True
    _FIELDS = frozenset({'owner', 'conversation_id', 'turn_id', 'request_id',
                         'session_id', 'lease', 'run_id'})

    def __init__(self, binding, authorize, *, model_schemas, call_tool=None):
        if (type(binding) is not dict or set(binding) != self._FIELDS or
                any(type(value) is not str or not 1 <= len(value) <= 256 or
                    any(ord(char) < 32 or ord(char) == 127 for char in value)
                    for value in binding.values())):
            raise ValueError('native_chat_binding')
        if not callable(authorize) or not callable(model_schemas):
            raise ValueError('native_chat_host_callbacks')
        if call_tool is not None and not callable(call_tool):
            raise ValueError('native_chat_tool_callback')
        self._binding = deepcopy(binding)
        self._authorize, self._schemas, self._call = authorize, model_schemas, call_tool
        self._surface = None
        self._lock = threading.Lock()
        self.book = self  # Compatibility with the existing budget gateway.

    def context(self, owner, task_id, lease):
        bound = self._binding
        if ((owner, task_id, lease) != (bound['owner'], bound['turn_id'], bound['lease']) or
                self._authorize() is not True):
            raise PermissionError('native_chat_inactive')
        return deepcopy(bound)

    def schemas(self):
        bound = self._binding
        self.context(bound['owner'], bound['turn_id'], bound['lease'])
        schemas = deepcopy(self._schemas())
        if type(schemas) is not list:
            raise ValueError('native_chat_tool_surface')
        names = set()
        for item in schemas:
            function = item.get('function') if type(item) is dict else None
            name = function.get('name') if type(function) is dict else None
            if (type(item) is not dict or item.get('type') != 'function' or type(name) is not str or
                    not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', name) or name in names or
                    type(function.get('parameters')) is not dict):
                raise ValueError('native_chat_tool_surface')
            names.add(name)
        try:
            surface = json.dumps(schemas, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                 separators=(',', ':'))
        except (TypeError, ValueError):
            raise ValueError('native_chat_tool_surface') from None
        # Host callbacks and any ledger I/O run outside this short memory lock.
        with self._lock:
            if self._surface is None:
                self._surface = surface
            elif self._surface != surface:
                raise PermissionError('native_chat_tool_surface_changed')
        self.context(bound['owner'], bound['turn_id'], bound['lease'])
        return schemas

    def call(self, owner, task_id, lease, name, arguments):
        self.context(owner, task_id, lease)
        if self._call is None:
            raise PermissionError('native_chat_host_tool_unavailable')
        # Only a host-injected capability adapter can serve this optional route.
        # SDK-native file/terminal tools do not come through this HTTP endpoint.
        return self._call(name, arguments)
