"""Unified account overrides in the existing protected registration ledger.

Original credential stores remain untouched. Every active login and verifier must
consume this ledger; schema5 prevents restoring an older runtime after a write.
"""
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
import auth_candidate as core
import module_permissions as permissions

SCHEMA = '''
CREATE TABLE account_state(subject TEXT PRIMARY KEY,version INTEGER NOT NULL,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),password TEXT NOT NULL,
 modules TEXT NOT NULL,custom INTEGER NOT NULL CHECK(custom IN (0,1)));
CREATE TABLE account_events(id INTEGER PRIMARY KEY,at INTEGER NOT NULL,
 actor TEXT NOT NULL,action TEXT NOT NULL,subject TEXT NOT NULL,
 version INTEGER NOT NULL,reason TEXT NOT NULL);
CREATE TRIGGER account_events_no_update BEFORE UPDATE ON account_events
 BEGIN SELECT RAISE(ABORT,'append-only account audit'); END;
CREATE TRIGGER account_events_no_delete BEFORE DELETE ON account_events
 BEGIN SELECT RAISE(ABORT,'append-only account audit'); END;
'''


def private_source(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise core.Denied(503, '账号来源路径异常')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise core.Denied(503, '账号来源不是独立普通文件')
    if os.name == 'posix' and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
        raise core.Denied(503, '账号来源权限异常')
    return path


class Accounts:
    def __init__(self, store, portal, *, isolated=False):
        self.store, self.portal = store, portal
        self.gate_path = Path(portal.CFG.get('account_gate_db', '/opt/fc27-gate/data/gate.db'))
        if isolated and Path(portal.CFG['data_dir']).resolve() not in self.gate_path.resolve().parents:
            raise ValueError('isolated legacy database must stay in synthetic root')

    def native_sources(self):
        rows = {}
        for group, file in self.portal.GROUPS.items():
            path = private_source(file)
            self.portal._ht_cache.pop(str(path), None)
            entries = self.portal.load_htpasswd(str(path))
            if not entries:
                raise core.Denied(503, '账号来源不可用')
            for name, encoded in entries.items():
                if not core.re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{1,39}', name):
                    raise core.Denied(503, '账号名称冲突')
                row = rows.setdefault(name, dict(name=name, groups=[], sources=[], _original=[]))
                row['groups'].append(group)
                row['_original'].append(encoded)
                if 'portal' not in row['sources']:
                    row['sources'].append('portal')
        path = private_source(self.gate_path)
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            for name, scheme, salt, encoded, banned in db.execute('SELECT username,pw_scheme,salt,pwhash,is_banned FROM users'):
                row = rows.setdefault(name, dict(name=name, groups=[], sources=[], _original=[]))
                row['sources'].append('fc_legacy')
                row['_original'].extend((scheme, salt, encoded, banned))
        keys = [name.casefold() for name in rows]
        if len(set(keys)) != len(keys):
            raise core.Denied(503, '账号大小写存在冲突')
        return rows

    def reserved(self):
        with self.store.namespace.fence():
            return frozenset(self.native_sources())

    @staticmethod
    def has_schema(db):
        return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_state'").fetchone())

    def inventory(self, db):
        native = self.native_sources()
        rows = {}
        for name, row in native.items():
            rows['native:' + name] = dict(row, subject='native:' + name,
                enabled=bool(row['groups']), role='admin' if name in self.store.policy.ADMINS else 'readonly',
                modules=dict(permissions.DEFAULT), custom=False, version=0, _password='', state='native' if row['groups'] else 'legacy_only')
        for user in db.execute('SELECT id,name,state,epoch,password FROM users'):
            if user['name'].casefold() in {name.casefold() for name in native}:
                raise core.Denied(503, '新旧账号命名冲突')
            uid = user['id']
            modules = self.store.permission_state(uid)['modules'] if user['state'] == 'readonly' else dict(permissions.DEFAULT)
            rows['reg:' + uid] = dict(subject='reg:' + uid, name=user['name'], groups=['dashboard'],
                sources=['registration'], enabled=user['state'] == 'readonly', role='readonly', modules=modules,
                custom=True, version=0, _password='', _original=[user['password'], user['epoch'], user['state']], state=user['state'])
        if self.has_schema(db):
            for item in db.execute('SELECT * FROM account_state'):
                if item['subject'] not in rows:
                    raise core.Denied(503, '账号记录与来源不一致')
                row = rows[item['subject']]
                row.update(version=item['version'], _password=item['password'], custom=bool(item['custom']),
                    modules=permissions.validate_grants(json.loads(item['modules'])))
                row['enabled'] = bool(item['enabled']) and (row['state'] in ('native', 'legacy_only', 'readonly'))
                if row['enabled'] and not row['groups']:
                    row['groups'] = ['dashboard']
        for row in rows.values():
            # A keyed opaque CAS revision detects external credential/source drift.
            payload = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
            row['revision'] = hmac.new(self.portal.CFG['secret'].encode(), payload, hashlib.sha256).hexdigest()
        return rows

    def row(self, subject):
        with self.store.connection() as db:
            row = self.inventory(db).get(subject)
            if not row:
                raise core.Denied(404, '找不到账号')
            return row

    def listing(self):
        with self.store.connection() as db:
            items = sorted(self.inventory(db).values(), key=lambda item: (item['name'].casefold(), item['subject']))
            return [{key: value for key, value in row.items() if not key.startswith('_')} for row in items]

    def authenticate(self, name, password):
        try:
            row = self.row('native:' + name)
        except core.Denied as error:
            if error.code == 404:
                return []
            raise
        if not row['enabled']:
            return []
        valid = core.password_matches(password, row['_password']) if row['_password'] else bool(self.portal.authenticate(name, password))
        return list(row['groups']) if valid else []

    def groups_of(self, name):
        try:
            row = self.row('native:' + name)
            return row['groups'] if row['enabled'] else []
        except core.Denied as error:
            if error.code == 404:
                return []
            raise

    def make_token(self, name, groups, ttl_seconds):
        row = self.row('native:' + name)
        if not row['enabled']:
            raise core.Denied(401, '账号已停用')
        old = self.portal.read_token(self.portal.make_token(name, groups, ttl_seconds))
        old['account_epoch'] = row['version']
        body = self.portal._b64e(json.dumps(old, separators=(',', ':'), ensure_ascii=False).encode())
        return body + '.' + self.portal._sign(body)

    def read_token(self, token):
        payload = self.portal.read_token(token)
        if not payload:
            return None
        try:
            row = self.row('native:' + payload['u'])
        except core.Denied as error:
            if error.code == 404:
                return None
            raise
        epoch = payload.get('account_epoch', 0)
        if type(epoch) is not int or not row['enabled'] or epoch != row['version']:
            return None
        return payload

    def authorize(self, identity, method, uri, group, guard):
        row = self.row('native:' + identity.user)
        if not row['enabled']:
            return 401
        if group and group not in row['groups'] and group != 'deploy':
            return 403
        if row['role'] == 'admin' or not row['custom']:
            return self.store.policy.authorize(identity.user, method, uri, group)
        if permissions.module_for(uri) is None:
            return self.store.policy.authorize(identity.user, method, uri, group)
        return 200 if permissions.permitted(guard, row['modules'], method, uri, group) else 403

    def mutate(self, actor, action, form):
        if not isinstance(actor, core.LegacyIdentity) or actor.role != 'admin' or actor.user not in self.store.policy.ADMINS:
            raise core.Denied(403, '仅现有管理员可管理账号')
        reason = core.text_field(form['reason'])
        if not isinstance(form['subject'], str) or not core.re.fullmatch(r'(?:native:[A-Za-z][A-Za-z0-9_.-]{1,39}|reg:[a-f0-9-]{36})', form['subject']):
            raise core.Denied(400, '账号标识无效')
        if not isinstance(form['revision'], str) or not core.re.fullmatch(r'[a-f0-9]{64}', form['revision']):
            raise core.Denied(400, '账号版本无效')
        password = form['admin_password']
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            raise core.Denied(400, '请填写管理员当前密码')
        encoded = None
        if action == 'password':
            if form['new_password'] != form['confirm_password']:
                raise core.Denied(400, '两次新密码不一致')
            encoded = core.password_hash(form['new_password'])
        with self.store.transaction() as db:
            if not self.authenticate(actor.user, password):
                raise core.Denied(401, '管理员当前密码不正确或账号已停用')
            rows = self.inventory(db)
            row = rows.get(form['subject'])
            if not row:
                raise core.Denied(404, '找不到账号')
            if not hmac.compare_digest(row['revision'], form['revision']):
                raise core.Denied(409, '账号或来源已变化，请刷新后重试')
            enabled, modules, custom = row['enabled'], row['modules'], row['custom']
            stored_password = row['_password']
            if action == 'permissions':
                if type(form['enabled']) is not bool:
                    raise core.Denied(400, '账号启用状态无效')
                enabled = form['enabled']
                modules = permissions.validate_grants(form['modules'])
                if row['role'] == 'admin' and modules != permissions.DEFAULT:
                    raise core.Denied(400, '现有管理员保留完整管理范围')
                if row['state'] == 'legacy_only' and enabled and not stored_password:
                    raise core.Denied(400, '旧库账号须先设置统一密码，再明确启用')
                if row['subject'].startswith('reg:') and enabled and row['state'] != 'readonly':
                    raise core.Denied(403, '新注册账号须先完成审批')
                if row['role'] == 'admin' and not enabled and sum(item['enabled'] and item['role'] == 'admin' for item in rows.values()) <= 1:
                    raise core.Denied(409, '必须保留至少一个可登录管理员')
                custom = row['role'] != 'admin'
            elif action != 'password':
                raise core.Denied(400, '账号操作无效')
            if not self.has_schema(db):
                buffer = ''
                for line in SCHEMA.splitlines(True):
                    buffer += line
                    if sqlite3.complete_statement(buffer):
                        db.execute(buffer); buffer = ''
                if buffer.strip():
                    raise ValueError('incomplete account schema')
            version = row['version'] + 1
            if row['subject'].startswith('reg:'):
                uid = row['subject'][4:]
                if encoded:
                    db.execute('UPDATE users SET password=? WHERE id=?', (encoded, uid))
                db.execute('UPDATE users SET epoch=epoch+1 WHERE id=?', (uid,))
                db.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
            else:
                if encoded:
                    stored_password = encoded
                db.execute('DELETE FROM sessions WHERE legacy_user=?', (row['name'],))
            db.execute('INSERT OR REPLACE INTO account_state VALUES(?,?,?,?,?,?)',
                (row['subject'], version, int(enabled), stored_password, json.dumps(modules, separators=(',', ':')), int(custom)))
            safe_reason = json.dumps({'reason': reason, 'enabled': enabled, 'modules': modules}, ensure_ascii=False, separators=(',', ':')) if action == 'permissions' else reason
            db.execute('INSERT INTO account_events(at,actor,action,subject,version,reason) VALUES(?,?,?,?,?,?)',
                (self.store.now(), actor.user, action, row['subject'], version, safe_reason))
            db.execute('PRAGMA user_version=5')
        return dict(ok=True, version=version, sessions_revoked=True, self_changed=row['name'] == actor.user)

    def audit(self, after):
        if type(after) is not int or after < 0:
            raise core.Denied(400, '审计分页无效')
        with self.store.connection() as db:
            if not self.has_schema(db):
                return []
            return [dict(row) for row in db.execute('SELECT * FROM account_events WHERE id>? ORDER BY id LIMIT 50', (after,))]
