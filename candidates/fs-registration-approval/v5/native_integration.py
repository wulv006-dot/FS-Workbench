"""Source-bound native portal integration. Runtime paths restricted to synthetic temp."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import threading
import time
import types
import uuid

import native_access_policy as policy
import native_portal_functions as functions
import native_taskboard_member as board_source
from auth_candidate import Adapter, Denied, LegacyIdentity, Store, readonly_allowed, SCHEMA
from schema_contract import validate as validate_schema, NATIVE_SCHEMA

PORTAL_COOKIE = 'MMOEXP_AUTH'


def bind_functions(cfg, groups, policy_module=policy):
    # Code objects are verbatim approved portal functions; no fake signature verifier.
    ns = dict(functions.__dict__, CFG=cfg, GROUPS=groups, _fs_policy=policy_module, _ht_cache={}, _ht_lock=threading.Lock())
    for key, value in functions.__dict__.items():
        if isinstance(value, types.FunctionType) and value.__module__ == functions.__name__:
            ns[key] = types.FunctionType(value.__code__, ns, key, value.__defaults__)
    return types.SimpleNamespace(**ns)


class Namespace:
    """Shared file fence for local native creator + registered creator, names never exported."""
    def __init__(self, root, portal):
        self.root, self.portal = Path(root), portal
        self.policy = portal._fs_policy
        self.lock = threading.RLock()
        self.depth = threading.local()
        self.store = None

    @contextmanager
    def fence(self):
        with self.lock:
            depth = getattr(self.depth, 'value', 0)
            if depth:
                self.depth.value = depth + 1
                try: yield
                finally: self.depth.value = depth
                return
            fd = None
            try:
                fd = os.open(self.root / 'namespace.lock', os.O_RDWR | os.O_CREAT, 0o600)
                if os.name == 'nt':
                    import msvcrt
                    if os.fstat(fd).st_size == 0: os.write(fd, b'0')
                    os.lseek(fd, 0, 0); msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX)
                self.depth.value = 1
                try: yield
                finally:
                    if os.name == 'nt':
                        os.lseek(fd, 0, 0); msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else: fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                # Reset even when open/acquire/unlock/close raises. Nested entry is
                # permitted only after this thread actually acquired the OS lock.
                self.depth.value = 0
                if fd is not None:
                    os.close(fd)

    def snapshot(self):
        with self.fence():
            names = set()
            for path in self.portal.GROUPS.values():
                path = Path(path)
                if not path.is_file() or path.is_symlink():
                    raise Denied(503, '账号来源不完整')
                self.portal._ht_cache.pop(str(path), None)
                entries = self.portal.load_htpasswd(str(path))
                if not entries:
                    raise Denied(503, '账号来源不可用')
                names.update(entries)
            if any(name.casefold().startswith('reg:') for name in names):
                raise Denied(503, '身份命名空间冲突')
            return {'names':frozenset(names),'complete':True,
                    'version':hashlib.sha256('\0'.join(sorted(names)).encode()).hexdigest(),
                    'observedAt':int(time.time())}

    def names(self):
        return self.snapshot()['names']

    def create_native(self, name, password, group='dashboard'):
        """Local controlled account writer only; no HTTP route grants native membership."""
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{1,39}', name):
            raise Denied(400, '账号无效')
        if group not in self.portal.GROUPS:
            raise Denied(400, '组无效')
        if name.casefold() in {n.casefold() for n in self.policy.ADMINS}:
            raise Denied(403, '普通创建接口不能授予管理员')
        with self.fence():
            snapshot = self.snapshot()
            if name.casefold() in {n.casefold() for n in snapshot['names']}:
                raise Denied(409, '账号冲突')
            with self.store.connection() as db:
                if db.execute('SELECT 1 FROM users WHERE name_key=?',(name.casefold(),)).fetchone():
                    raise Denied(409, '账号冲突')
            encoded = self.portal.apr1_md5(password, 'local123')
            path = Path(self.portal.GROUPS[group])
            with path.open('a',encoding='utf-8') as fh:
                fh.write(name+':'+encoded+'\n'); fh.flush(); os.fsync(fh.fileno())
            self.portal._ht_cache.clear()


class Registry(Store):
    def __init__(self, root, namespace, **kw):
        self.namespace = namespace
        super().__init__(root, reserved_names=namespace.names, policy_module=namespace.policy, **kw)
        namespace.store = self
        with self.transaction() as db:
            # Additive candidate schema2→3 migration, preserving users/epochs/history.
            if db.execute('PRAGMA user_version').fetchone()[0] == 2:
                db.execute(NATIVE_SCHEMA)
                db.execute('PRAGMA user_version=3')
            validate_schema(db, SCHEMA, 3)

    def register(self, *args, **kw):
        with self.namespace.fence():
            return super().register(*args, **kw)


class NativeAdapter(Adapter):
    def __init__(self, store, portal, namespace):
        self.portal, self.namespace = portal, namespace
        self.policy = namespace.policy
        super().__init__(store,legacy_resolver=self.resolve_native,legacy_authorize=self.authorize_native)

    def resolve_native(self, cookies):
        token = cookies.get(self.portal.CFG['cookie'],'')
        try:
            payload = self.portal.read_token(token)
        except (ValueError, TypeError, UnicodeError):
            return None
        if not payload: return None
        with self.store.connection() as db:
            if db.execute('SELECT 1 FROM native_revocations WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone():
                return None
        with self.namespace.fence():
            self.namespace.snapshot()  # completeness; unavailable sources produce 503, not anonymous.
            user = payload['u']
            if not isinstance(user,str) or user.casefold().startswith('reg:'): return None
            live = tuple(self.portal.groups_of(user))
            if not live: return None
            role = 'admin' if user in self.policy.ADMINS else 'readonly'
            return LegacyIdentity(user,live,role)

    def authorize_native(self, identity, method, uri, group):
        if group and group not in identity.groups and group != 'deploy': return 403
        return self.policy.authorize(identity.user,method,uri,group)

    def native_login(self, name, password):
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{1,39}', name) or not isinstance(password,str) or not 1 <= len(password) <=128:
            raise Denied(400,'登录参数无效')
        with self.namespace.fence():
            self.namespace.snapshot()
            groups = self.portal.authenticate(name,password)
            if not groups: raise Denied(401,'账号或密码不正确')
            token = self.portal.make_token(name,groups,43200)
            identity = self.resolve_native({PORTAL_COOKIE:token})
            if not identity: raise Denied(401,'请重新登录')
            return token,identity

    def native_cookie(self, token):
        return f'{self.portal.CFG["cookie"]}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={43200 if token else 0}'

    def logout(self, session_token, cookies):
        """Logout needs a signed token, never membership or a granted role.

        Session deletion and native denylist insertion commit together. Failure
        propagates to 503; callers must not clear cookies or claim success.
        """
        token = cookies.get(self.portal.CFG['cookie'],'')
        try:
            payload = self.portal.read_token(token) if token else None
        except (ValueError, TypeError, UnicodeError):
            payload = None
        with self.store.transaction() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?',
                       (hashlib.sha256(session_token.encode()).hexdigest(),))
            if payload:
                db.execute('INSERT OR REPLACE INTO native_revocations VALUES(?,?)',
                    (hashlib.sha256(token.encode()).hexdigest(),payload['e']))
            db.execute('DELETE FROM native_revocations WHERE expires<?',(int(time.time()),))

    def verify(self, cookies, method, uri, group=''):
        code,headers=super().verify(cookies,method,uri,group)
        if code==200 and headers.get('X-Auth-Role')=='admin':
            headers['X-Auth-Groups']=','.join(sorted(set(headers['X-Auth-Groups'].split(','))|{'deploy'}))
        return code,headers


def taskboard_role(conn, subject, role, policy_module=policy):
    """Candidate consumer increment: registered UUID is viewer, never name-based admin."""
    if subject.startswith('reg:'):
        try: uuid.UUID(subject[4:])
        except ValueError: raise Denied(403,'身份无效')
        if role != 'readonly': raise Denied(403,'角色无效')
        return 'viewer',True
    ns=dict(board_source.__dict__,GUARD_ADMINS=policy_module.ADMINS,ROLES=('admin','editor','viewer'),
            q=lambda c,sql,args,one=False:c.execute(sql,args).fetchone())
    original=types.FunctionType(board_source.member_state.__code__,ns)
    return original(conn,subject)
