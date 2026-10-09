"""Registered account module grants in the existing append-only audit ledger."""
import json
import re
import types
from urllib.parse import unquote, urlsplit
import auth_candidate as core

MODULES = (
    ('business', '经营分析', False, '/dashboard/'),
    ('marketing', '营销分析', False, '/dashboard/marketing/'),
    ('weekly', '运营周报', False, '/dashboard/marketing/weekly/'),
    ('tasks', '工作任务台', True, '/dashboard/tasks/'),
    ('green_plan', '绿茵计划', True, '/dashboard/tasks/green-plan/'),
    ('fc_ops', 'FC运营看板', False, '/s/wulv/fc27-ops/'),
    ('players', 'FC球员维护', False, '/tools/fc27-players/'),
)
DEFAULT = {key: 'readonly' for key, *_ in MODULES}

def options():
    return [dict(id=key, label=label, can_edit=edit, href=href) for key,label,edit,href in MODULES]

def validate_grants(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT):
        raise core.Denied(400, '模块范围无效')
    for key, _, edit, _ in MODULES:
        if value[key] not in ('none', 'readonly', 'editor') or value[key] == 'editor' and not edit:
            raise core.Denied(400, '该模块不支持所选权限')
    return dict(value)

def record(db, rid, uid):
    row = db.execute("SELECT id,reason FROM audit WHERE action='permissions' AND request_id=? AND subject=? ORDER BY id DESC LIMIT 1", (rid,uid)).fetchone()
    if not row:
        return dict(version=0, modules=dict(DEFAULT))
    data = json.loads(row['reason'])
    if set(data) != {'schema', 'reason', 'modules'} or data['schema'] != 1:
        raise ValueError('permission audit conflict')
    core.text_field(data['reason'])
    return dict(version=row['id'], modules=validate_grants(data['modules']))

class StorePermissions:
    def permission_state(self, uid):
        with self.connection() as db:
            row = db.execute("SELECT r.id FROM requests r JOIN users u ON u.id=r.user_id WHERE r.user_id=? AND r.status='approved' AND u.state='readonly' ORDER BY r.rowid DESC LIMIT 1", (uid,)).fetchone()
            if not row:
                raise core.Denied(403, '账号尚未批准或授权已撤销')
            return record(db,row['id'],uid)

    def status(self, uid):
        result = super().status(uid)
        if result['state'] == 'readonly': result['permissions'] = self.permission_state(uid)
        return result

    def listing(self, kind, after=0):
        rows = super().listing(kind, after)
        if kind == 'requests':
            with self.connection() as db:
                for row in rows:
                    if row['status'] == 'approved': row['permissions'] = record(db,row['id'],row['user_id'])
        return rows

    def permission_update(self, actor, rid, request_version, version, permissions, reason):
        if not isinstance(actor,core.LegacyIdentity) or actor.role != 'admin' or actor.user not in self.policy.ADMINS or not actor.groups:
            raise core.Denied(403, '仅现有管理员可调整权限')
        if not isinstance(rid,str) or not re.fullmatch(r'[a-f0-9-]{36}',rid) or any(type(v) is not int or v < 0 for v in (request_version,version)):
            raise core.Denied(400, '权限参数无效')
        grants = validate_grants(permissions); reason = core.text_field(reason)
        with self.transaction() as db:
            row = db.execute('SELECT r.*,u.state,u.name FROM requests r JOIN users u ON u.id=r.user_id WHERE r.id=?',(rid,)).fetchone()
            if not row or row['status'] != 'approved' or row['state'] != 'readonly' or row['version'] != request_version:
                raise core.Denied(409, '申请已变化，请刷新后重试')
            if record(db,rid,row['user_id'])['version'] != version:
                raise core.Denied(409, '权限已变化，请刷新后重试')
            # Old runtime rejects schema4 instead of silently restoring global reads.
            db.execute('PRAGMA user_version=4')
            encoded = json.dumps(dict(schema=1, reason=reason, modules=grants),ensure_ascii=False,separators=(',',':'))
            self.audit(db,'legacy:'+actor.user,'permissions',rid,row['user_id'],encoded)
            next_version = db.execute('SELECT last_insert_rowid()').fetchone()[0]
            db.execute('UPDATE users SET epoch=epoch+1 WHERE id=?',(row['user_id'],))
            db.execute('DELETE FROM sessions WHERE user_id=?',(row['user_id'],))
            member = dict(username='reg:'+row['user_id'],displayName=row['name'],role='viewer',active=True,note='注册账号；编辑权限由账号与权限管理按模块控制') if 'editor' in grants.values() else None
        return dict(version=next_version,modules=grants,member=member,sessions_revoked=True)

def module_for(uri):
    path = urlsplit(uri).path
    for _ in range(4): path = unquote(path,errors='strict')
    if path == '/dashboard/tasks/api/session': return 'task_session'
    if path.startswith(('/dashboard/tasks/green-plan/', '/dashboard/tasks/api/green-plan')): return 'green_plan'
    if path.startswith('/dashboard/tasks/'): return 'tasks'
    if path.startswith('/dashboard/marketing/weekly/'): return 'weekly'
    if path.startswith('/dashboard/marketing/'): return 'marketing'
    if path.startswith('/tools/fc27-players/'): return 'players'
    if path.startswith(('/s/wulv/fc27-ops/', '/fc27/')): return 'fc_ops'
    if path.startswith('/dashboard/'): return 'business'
    return None

def mode_for(grants, module):
    if module == 'task_session':
        return 'editor' if any(grants[k]=='editor' for k in ('tasks','green_plan')) else 'readonly' if any(grants[k]=='readonly' for k in ('tasks','green_plan')) else 'none'
    return grants.get(module,'none')

def permitted(guard, grants, method, uri, group):
    mode = mode_for(grants,module_for(uri))
    if mode == 'none': return False
    if method in ('GET','HEAD'): return guard.allowed(method,uri,group)
    if mode != 'editor' or group not in ('','dashboard'): return False
    # Writes match the literal public route: no encoded paths, queries or aliases.
    patterns = {
        ('green_plan','PATCH'): r'/dashboard/tasks/api/green-plan/tasks/G[0-9]+',
        ('tasks','PATCH'): r'/dashboard/tasks/api/tasks/[1-9][0-9]{0,11}',
        ('tasks','POST'): r'/dashboard/tasks/api/tasks/[1-9][0-9]{0,11}/(?:ack|submit|checks)',
    }
    return bool(re.fullmatch(patterns.get((module_for(uri),method),r'(?!)'),uri))

def verify(adapter, cookies, method, uri, group):
    with adapter.store.namespace.fence():
        session = adapter.store.session(cookies.get(core.COOKIE,''))
        grants = adapter.store.permission_state(session['user_id'])['modules'] if session and session['user_id'] and session['live_state']=='readonly' else dict(DEFAULT)
        fn = types.FunctionType(core.Adapter.verify.__code__,dict(core.Adapter.verify.__globals__,readonly_allowed=lambda m,u,g: permitted(adapter.guard,grants,m,u,g)),argdefs=core.Adapter.verify.__defaults__)
        code,headers = types.MethodType(fn,adapter)(cookies,method,uri,group)
        if code == 200 and headers['X-Auth-User'].startswith('reg:'):
            headers['X-Auth-Role'] = mode_for(grants,module_for(uri))
        return code,headers
