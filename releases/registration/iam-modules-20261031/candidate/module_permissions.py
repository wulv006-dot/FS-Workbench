"""Registered account module grants in the existing append-only audit ledger.

v2 (2026-10-19): 权限模型从「7 个平铺模块」升级为「大模块(section) → 子模块(tool)」
两层。section 仅用于前端分组与授权便利；真实授权粒度在 tool 上。授权默认覆盖
navigation.json 里的全部工作区与工具入口。
"""
import json
import re
import types
from urllib.parse import unquote, urlsplit
import auth_candidate as core

# 大模块（工作区）→ 子模块（工具）两层。
SECTIONS = (
    ('analytics',     '数据分析'),
    ('brain',         'Hermes 智体'),
    ('sports',        '球类工作区'),
    ('arpg',          'RPG 工作区'),
    ('sales',         '销售部系统'),
    ('bots',          '机器人管理'),
    ('collaboration', '协作工具'),
)

# (id, label, section, can_edit, href)
MODULES = (
    ('unified-business',    '数据看板',           'analytics',     False, '/dashboard/analytics/'),
    ('data-analysis-tools', '数据分析工具',       'analytics',     False, '/dashboard/data-tools/'),
    ('management',          '经营管理台',         'analytics',     False, '/dashboard/management/'),
    ('game-monitor',        '游戏监控台',         'analytics',     False, '/dashboard/game-monitor/'),
    ('brain',               'Hermes 智体',        'brain',         False, '/dashboard/fs-home/brain/'),
    ('coins',               'FC27 金币控制台',    'sports',        False, '/dashboard/fc27-coins.html'),
    ('fc27-bundles',        'FC27 捆绑包改价',    'sports',        False, '/dashboard/modules/sports/bundles/'),
    ('fc27-sbc',            'FC27 SBC 上架工具',  'sports',        False, '/dashboard/fc27-sbc/'),
    ('ops',                 'FC27 运营看板',      'sports',        False, '/s/wulv/fc27-ops/'),
    ('players',             'FC27 球员维护',      'sports',        False, '/tools/fc27-players/'),
    ('gallery',             'FC27 收藏馆调价',    'sports',        False, '/tools/fc27-gallery/'),
    ('odds',                'FC26 库存与交付',    'sports',        False, '/s/wulv/fc-odds/'),
    ('mlb',                 'MLB 新卡工作台',     'sports',        False, '/mlb/'),
    ('nba',                 'NBA2K 自动改价台',   'sports',        False, '/nba2k27/'),
    ('madden',              'Madden 金币看板',    'sports',        False, '/dashboard/madden27-coins.html'),
    ('d4',                  'RPG 游戏改价系统',   'arpg',          False, '/d4/'),
    ('g2g',                 'G2G 自动改价',       'arpg',          False, '/g2g/'),
    ('sales',               '销售部系统',         'sales',          False, '/sales/'),
    ('bot-console',         'Discord 机器人控制台','bots',         False, '/bots/'),
    ('tasks',               '项目工作任务台',     'collaboration', True,  '/dashboard/tasks/'),
    ('green_plan',          '绿茵计划',           'collaboration', True,  '/dashboard/tasks/green-plan/'),
    ('docs',                '部门手册',           'collaboration', False, '/docs/'),
    ('sites',               '团队工具目录',       'collaboration', False, '/s/'),
    ('deploy',              '现有部署工作台',     'collaboration', False, '/deploy/'),
)

DEFAULT = {key: 'readonly' for key, *_ in MODULES}
SECTION_OF = {key: section for key, _, section, _, _ in MODULES}

# 明确不开放给注册账号的路径：这些走独立 API-key / 后端门禁，模块映射必须返回 None。
BLOCKED_PREFIXES = (
    '/dashboard/api/',
    '/dashboard/fc27-quote-api/',
    '/dashboard/fc27-activity-api/',
    '/api/fc27/cloud/',
    '/dashboard/tasks/api/members',
    '/s/wulv/fc27-ops/api/collect',
)


def options():
    """分组后的模块清单，供前端渲染「大模块 → 子模块」层级。"""
    sections = []
    for sid, slabel in SECTIONS:
        tools = [dict(id=key, label=label, can_edit=edit, href=href)
                 for key, label, sec, edit, href in MODULES if sec == sid]
        sections.append(dict(id=sid, label=slabel, tools=tools))
    return sections


def validate_grants(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT):
        raise core.Denied(400, '模块范围无效')
    for key, _, _, edit, _ in MODULES:
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
            if hasattr(self, 'accounts') and self.accounts.has_schema(db) and db.execute('SELECT 1 FROM account_state WHERE subject=?', ('reg:' + row['user_id'],)).fetchone():
                raise core.Denied(409, '请使用完整账号列表调整该账号权限')
            if db.execute('PRAGMA user_version').fetchone()[0] < 4:
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
    if not path.startswith('/'):
        return None
    # 独立门禁/敏感路径：注册账号不可访问（映射为 None → mode 'none' → 403）
    if path.startswith(BLOCKED_PREFIXES):
        return None
    # 工作任务台（含绿茵计划子页与任务 API）
    if path == '/dashboard/tasks/api/session': return 'task_session'
    if path.startswith(('/dashboard/tasks/green-plan/', '/dashboard/tasks/api/green-plan')): return 'green_plan'
    if path.startswith('/dashboard/tasks/'): return 'tasks'
    # 球类工作区
    if path.startswith('/dashboard/modules/sports/bundles/'): return 'fc27-bundles'
    if path.startswith('/dashboard/fc27-sbc/'): return 'fc27-sbc'
    if path == '/dashboard/fc27-coins.html' or path.startswith('/dashboard/fc27-coins.'): return 'coins'
    if path == '/dashboard/madden27-coins.html' or path.startswith('/dashboard/madden27-coins.'): return 'madden'
    if path.startswith('/tools/fc27-players/'): return 'players'
    if path.startswith('/tools/fc27-gallery/'): return 'gallery'
    if path.startswith('/s/wulv/fc27-ops/'): return 'ops'
    if path.startswith('/s/wulv/fc-odds/'): return 'odds'
    if path.startswith('/mlb/'): return 'mlb'
    if path.startswith('/nba2k27/'): return 'nba'
    # RPG 工作区
    if path.startswith('/d4/'): return 'd4'
    if path.startswith('/g2g/'): return 'g2g'
    if path.startswith('/sales/'): return 'sales'
    # 机器人管理
    if path.startswith('/bots/'): return 'bot-console'
    # 协作工具
    if path.startswith('/docs/'): return 'docs'
    if path.startswith('/deploy/'): return 'deploy'
    # 数据分析
    if path.startswith('/dashboard/analytics/'): return 'unified-business'
    if path.startswith('/dashboard/data-tools/'): return 'data-analysis-tools'
    if path.startswith('/dashboard/management/'): return 'management'
    if path.startswith('/dashboard/game-monitor/'): return 'game-monitor'
    # Hermes 智体
    if path.startswith('/dashboard/fs-home/brain/'): return 'brain'
    # 团队工具目录（须在 /s/wulv/... 之后，避免被 sites 吞掉）
    if path.startswith('/s/'): return 'sites'
    # 平台首页 / 工作区首页 / 共享主题资源 / 导航清单 → 已批准账号可读
    if path.startswith('/dashboard/'): return 'home'
    return None


def mode_for(grants, module):
    if module == 'home':
        return 'readonly'
    if module == 'task_session':
        return 'editor' if grants.get('tasks') == 'editor' or grants.get('green_plan') == 'editor' else 'readonly' if grants.get('tasks') == 'readonly' or grants.get('green_plan') == 'readonly' else 'none'
    return grants.get(module, 'none')


def permitted(guard, grants, method, uri, group):
    mode = mode_for(grants,module_for(uri))
    if mode == 'none': return False
    if method in ('GET','HEAD'): return guard.allowed(method,uri,group)
    if mode != 'editor' or group not in ('','dashboard'): return False
    # 写操作只匹配明确的公开路由：无编码路径、无查询、无别名。
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
        if session and session['user_id'] and hasattr(adapter.store, 'accounts'):
            account = adapter.store.accounts.row('reg:' + session['user_id'])
            if not account['enabled']:
                return 403, {}
            grants = account['modules']
        def _readonly_allowed(m,u,g):
            # Authentication, expiry, collision, approval/revocation and account disable
            # remain in the original Adapter. IAM is the sole business grant source.
            if not session or not session.get('user_id'):
                return False
            policy = adapter.store.policy
            if not hasattr(policy, 'status') or policy.status().get('degraded'):
                return False
            return policy.authorize('reg:' + session['user_id'], m, u, g) == 200
        fn = types.FunctionType(core.Adapter.verify.__code__,dict(core.Adapter.verify.__globals__,readonly_allowed=_readonly_allowed),argdefs=core.Adapter.verify.__defaults__)
        code,headers = types.MethodType(fn,adapter)(cookies,method,uri,group)
        if code == 200 and headers['X-Auth-User'].startswith('reg:'):
            subject = headers['X-Auth-User']
            # Legacy consumers accept editor only for registered taskboard members.
            # Do not turn module operators into platform administrators.
            matrix = adapter.store.policy.matrix(subject)
            resource = module_for(uri)
            writable = any(a in matrix.get(resource, []) for a in ('edit', 'execute'))
            headers['X-Auth-Role'] = 'editor' if resource in ('tasks', 'green_plan', 'task_session') and writable else 'readonly'
            if group == 'deploy':
                headers['X-Auth-Groups'] = 'dashboard,deploy'
        return code,headers
