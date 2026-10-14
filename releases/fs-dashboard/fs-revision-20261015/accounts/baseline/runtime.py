"""Inert production seams. Explicit factory only; no listener, secret or native writes.

Activation requires separate deployment review. Vendor bytes are frozen v5.
"""
from contextlib import contextmanager, closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
import types
from urllib.parse import urlsplit, unquote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'vendor'))
import auth_candidate as core
import module_permissions
from native_integration import Namespace, NativeAdapter
from schema_contract import validate, NATIVE_SCHEMA
import storage_checkpoint as checkpoint


def secure_path(path, *, directory=False):
    """Reject redirects and non-private ownership before opening runtime storage."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('storage link rejected')
    st = path.stat()
    if directory and not path.is_dir():
        raise ValueError('storage directory required')
    if not directory and (not path.is_file() or st.st_nlink != 1):
        raise ValueError('private regular database required')
    if os.name == 'posix' and (st.st_uid != os.geteuid() or st.st_mode & 0o077):
        raise ValueError('storage owner/mode conflict; explicit operator action required')
    return path


class RuntimeStore(module_permissions.StorePermissions, core.Store):
    """Separate production constructor; frozen Store's temp restriction stays intact.

    Only registration-approval beneath the operator-selected existing AUTH_DATA_DIR.
    Unknown existing structure is rejected; no account or native membership migration.
    """
    def __init__(self, data_dir, portal, *, isolated=False, clock=time.time):
        base = Path(data_dir).absolute()
        if isolated:
            temp = Path(tempfile.gettempdir()).resolve()
            if temp not in base.resolve().parents or not base.name.startswith('fs-registration-'):
                raise ValueError('dedicated synthetic temp root required')
        elif os.name != 'posix':
            raise ValueError('production runtime requires POSIX; Windows is isolated QA only')
        # No mkdir parents: must bind an explicitly selected existing portal data dir.
        if not base.is_dir() or any(p.is_symlink() for p in (base, *base.parents)):
            raise ValueError('existing nonlinked auth data directory required')
        root = base / 'registration-approval'
        secure_path(root, directory=True)
        self.namespace = Namespace(root, portal)
        self.policy = portal._fs_policy
        self.reserved_names, self.clock = self.namespace.names, clock
        self.path = root / 'registration.sqlite3'
        self.witness = base / '.registration-checkpoint' / 'state.json'
        secure_path(self.witness.parent, directory=True)
        secure_path(self.witness)
        self.namespace.store = self
        with self.namespace.fence():
            secure_path(self.path)
            with self.connection() as db:
                self._validate(db)
        self.dummy = core.password_hash('Synthetic-only-dummy-42')

    @classmethod
    def initialize_fresh(cls, data_dir, portal, *, isolated=False):
        """Operator-only first creation, never called by build/install/restart.

        No existing root/witness may be present, even from interrupted init.
        Failure leaves a visible fence; no automated repair/reset/retry exists.
        """
        base = Path(data_dir).absolute()
        if isolated:
            temp = Path(tempfile.gettempdir()).resolve()
            if temp not in base.resolve().parents or not base.name.startswith('fs-registration-'):
                raise ValueError('dedicated synthetic temp root required')
        elif os.name != 'posix':
            raise ValueError('production runtime requires POSIX')
        if not base.is_dir() or any(p.is_symlink() for p in (base, *base.parents)):
            raise ValueError('existing nonlinked data directory required')
        root, anchor = base / 'registration-approval', base / '.registration-checkpoint'
        # Anchor is outside registration root so deleting that root cannot permit
        # another first initialization. No cleanup of these persistent fences.
        if os.path.lexists(root) or os.path.lexists(anchor):
            raise ValueError('initialization requires never-initialized paths; reviewed recovery required')
        anchor.mkdir(mode=0o700)
        cls._sync_dir(base)
        root.mkdir(mode=0o700)
        cls._sync_dir(base)
        obj = object.__new__(cls)
        obj.path = root / 'registration.sqlite3'
        obj._initialize(root)
        with closing(sqlite3.connect(obj.path)) as db:
            validate(db, core.SCHEMA, 3)
            value = {'version': 1, 'generation': 0, 'status': 'ready', 'digest': checkpoint.state_digest(db)}
        checkpoint.write(anchor / 'state.json', value, cls._sync_dir)
        return cls(base, portal, isolated=isolated)

    def _initialize(self, root):
        fd, stage = tempfile.mkstemp(prefix='.init-', suffix='.sqlite3', dir=root)
        os.close(fd)
        try:
            db = sqlite3.connect(stage)
            try:
                db.executescript('BEGIN IMMEDIATE;\n' + core.SCHEMA + '\n' + NATIVE_SCHEMA + ';\nPRAGMA user_version=3;\nCOMMIT;')
                validate(db, core.SCHEMA, 3)
            finally:
                db.close()
            with open(stage, 'r+b') as fh:
                os.fsync(fh.fileno())
            # Namespace fence serializes first creation; hard-link publication never
            # replaces an existing DB even if another writer ignores that fence.
            os.link(stage, self.path)
            os.unlink(stage)
            self._sync_dir(root)
        finally:
            if os.path.exists(stage):
                os.unlink(stage)

    @staticmethod
    def _sync_dir(root):
        if os.name == 'posix':
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(fd)
            finally: os.close(fd)

    @contextmanager
    def connection(self):
        with self.namespace.fence():
            secure_path(self.path)
            secure_path(self.witness.parent, directory=True)
            secure_path(self.witness)
            # mode=rw prohibits accidental SQLite creation in a path race.
            db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            try:
                self._validate(db)
                yield db
            finally:
                db.close()

    def _validate(self, db):
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (3, 4) or version == 3 and db.execute("SELECT 1 FROM audit WHERE action='permissions' LIMIT 1").fetchone():
            raise ValueError('permission ledger/schema version conflict; reviewed recovery required')
        validate(db, core.SCHEMA, 3)
        current = checkpoint.read(self.witness)
        if checkpoint.state_digest(db) != current['digest']:
            raise ValueError('database rollback/corruption detected; reviewed recovery required')
        return current

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            current = self._validate(db)
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                after = checkpoint.state_digest(db)
                next_state = {'version': 1, 'generation': current['generation'] + 1,
                    'status': 'pending', 'digest': after}
                # Pending is persisted BEFORE DB commit. Any interruption after
                # this point rejects normal restart, even if the DB committed.
                checkpoint.write(self.witness, next_state, self._sync_dir)
                db.commit()
                next_state['status'] = 'ready'
                checkpoint.write(self.witness, next_state, self._sync_dir)
            except BaseException:
                db.rollback()
                raise

    def register(self, *args, **kw):
        with self.namespace.fence():
            return super().register(*args, **kw)


class RouteGuard:
    def __init__(self, contract):
        self.paths = frozenset(contract['exact_reads'])
        self.patterns = tuple(re.compile(p) for p in contract['read_patterns'])
        self.admin_only = frozenset(contract['admin_only'])
        self.query_keys = {key: frozenset(value) for key, value in contract['query_keys'].items()}

    def allowed(self, method, uri, group='dashboard'):
        if not isinstance(uri, str) or len(uri) > 2048: return False
        try:
            decoded = uri
            for _ in range(4): decoded = unquote(decoded, errors='strict')
            path = urlsplit(decoded).path
        except (ValueError, UnicodeError): return False
        if path in self.admin_only or (path not in self.paths and not any(p.fullmatch(path) for p in self.patterns)):
            return False
        keys = self.query_keys['static_assets'] if path.endswith(('.js', '.css')) else self.query_keys['business']
        controls = core.CONTROL
        if path in ('/dashboard/marketing/range.json', '/dashboard/marketing/business-links.json'):
            keys = frozenset(('start', 'end'))
            controls = core.CONTROL - {'start'}
        fn = types.FunctionType(core.readonly_allowed.__code__,
            dict(core.readonly_allowed.__globals__, READ_ROUTES=frozenset((path,)), READ_QUERY_KEYS=keys, CONTROL=controls))
        return fn(method, uri, group)


class RuntimeAdapter(NativeAdapter):
    def __init__(self, store, portal, guard):
        super().__init__(store, portal, store.namespace)
        self.guard = guard

    def verify(self, cookies, method, uri, group=''):
        try:
            code, headers = module_permissions.verify(self, cookies, method, uri, group)
        except Exception:
            return 503, {}
        if code == 200:
            if headers['X-Auth-Role'] == 'admin':
                headers['X-Auth-Groups'] = ','.join(sorted(set(headers['X-Auth-Groups'].split(',')) | {'deploy'}))
            headers['X-Fc27-User'] = headers['X-Auth-User']
            headers['X-Fc27-Role'] = headers['X-Auth-Role']
        return code, headers

    def native_login(self, name, password):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{1,39}', name) or not isinstance(password, str) or not 1 <= len(password) <= 128:
            raise core.Denied(400, 'invalid login')
        with self.namespace.fence():
            self.namespace.snapshot()
            groups = self.portal.authenticate(name, password)
            if not groups: raise core.Denied(401, 'invalid credentials')
            token = self.portal.make_token(name, groups, core.TTL)
            identity = self.resolve_native({self.portal.CFG['cookie']: token})
            if not identity: raise core.Denied(401, 'invalid identity')
            return token, identity

    def native_cookie(self, token):
        return super().native_cookie(token) + '; Secure'

    def ledger_read_token(self, token):
        """Bind old status/verifier callers to this after preserving original parser.

        Database failure raises: callers must fail closed, never old-FC fallback.
        """
        payload = self.portal.read_token(token)
        if payload:
            with self.store.connection() as db:
                if db.execute('SELECT 1 FROM native_revocations WHERE token_hash=?',
                    (hashlib.sha256(token.encode()).hexdigest(),)).fetchone():
                    return None
        return payload


class RuntimeApp(core.App):
    def __init__(self, adapter, origin):
        if adapter.portal.CFG.get('secure') not in (True, 1):
            raise ValueError('HTTPS runtime requires secure native cookie configuration')
        parsed = urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError('explicit HTTPS canonical origin required')
        if origin != 'https://' + parsed.netloc:
            raise ValueError('canonical origin required')
        self.adapter, self.store, self.origin = adapter, adapter.store, origin


def build(data_dir, portal, origin, *, isolated=False):
    """Called by a reviewed boot hook, never at import. Portal is live native module.

    Caller preserves original parser in portal view before wiring ledger_read_token;
    caller must reject activation until all consumers and namespace writers pass QA.
    """
    if portal.CFG.get('secure') not in (True, 1):
        raise ValueError('HTTPS runtime refuses insecure native cookie configuration')
    store = RuntimeStore(data_dir, portal, isolated=isolated)
    guard = RouteGuard(json.loads((HERE / 'route-contract.json').read_text(encoding='utf-8')))
    adapter = RuntimeAdapter(store, portal, guard)
    return store, adapter, RuntimeApp(adapter, origin)
