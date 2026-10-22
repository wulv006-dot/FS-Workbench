"""Append only this module's routes and byte-patch the current registry/fallback."""
import hashlib
import json
import re

BASELINES = {
    'navigation.json': '04259ecbf0d910e3994b64093875ae124151b3c666ac846e6f05055a35acedc6',
    'hubnav.js': 'c5917e0c188cff15ee0c289e95b1a1df88958a121f198a8802623c755b3da73c',
    'navigation.conf': '8a565e993ba4c4ba6586d5cb5ff9f090c987c5cae345639c5f4869fb298da426',
}
STATIC = '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/'
TOOL = dict(id='user-analytics', label='用户分析', path='/dashboard/users/', icon='◎',
            short='购买客户、复购与生命周期；覆盖范围按实际数据展示', section='analytics',
            scope='global-portal', requiredGroup='dashboard', serverGuard='/__auth_verify')


def patch(files):
    for name, expected in BASELINES.items():
        if hashlib.sha256(files[name]).hexdigest() != expected:
            raise ValueError('navigation_baseline_drift:' + name)
    raw = files['navigation.json']
    newline = b'\r\n' if b'\r\n' in raw else b'\n'
    anchor = b'        "channel-effects",'
    if raw.count(anchor) != 1:
        raise ValueError('navigation_section_anchor')
    raw = raw.replace(anchor, anchor + newline + b'        "user-analytics",', 1)
    anchor = b'  "tools": ['
    if raw.count(anchor) != 1:
        raise ValueError('navigation_tools_anchor')
    tool = json.dumps(TOOL, ensure_ascii=False, separators=(',', ':')).encode()
    raw = raw.replace(anchor, anchor + newline + b'    ' + tool + b',', 1)
    registry = json.loads(raw)
    js = files['hubnav.js']
    builtin = json.dumps({k: registry[k] for k in ('schemaVersion', 'sections', 'tools')}, ensure_ascii=False, separators=(',', ':')).encode()
    js, count = re.subn(rb'const BUILTIN=\{[^\r\n]+\};', lambda _: b'const BUILTIN=' + builtin + b';', js)
    if count != 1 or js.count(b"REG_CACHE='fs-nav-registry-channel-v1'") != 1:
        raise ValueError('hubnav_anchor')
    js = js.replace(b"REG_CACHE='fs-nav-registry-channel-v1'", b"REG_CACHE='fs-nav-registry-users-v1'", 1)
    blocks = ['# User analytics: existing portal/IAM and loopback reader only.\nlocation = /dashboard/users { return 302 /dashboard/users/; }\nlocation = /dashboard/users/ { rewrite ^ /dashboard/users/index.html last; }\n']
    for name in ('index.html', 'users.js', 'users.css'):
        blocks.append('location = /dashboard/users/' + name + ' {\n'
                      '    if ($request_method !~ ^(GET|HEAD)$) { return 405; }\n'
                      '    auth_request /__auth_verify;\n    error_page 401 = @auth_login;\n'
                      '    alias ' + STATIC + name + ';\n    disable_symlinks on;\n'
                      '    add_header Cache-Control "no-store" always;\n}\n')
    for name, endpoint in (('data.json', '/users'), ('private.json', '/users/private')):
        blocks.append('location = /dashboard/users/' + name + ' {\n'
                      '    if ($request_method !~ ^(GET|HEAD)$) { return 405; }\n'
                      '    auth_request /__auth_verify;\n    auth_request_set $fs_users_user $upstream_http_x_auth_user;\n'
                      '    proxy_set_header X-Auth-User $fs_users_user;\n    proxy_set_header X-Auth-Role "";\n'
                      '    proxy_set_header Cookie "";\n    proxy_set_header Authorization "";\n'
                      '    proxy_pass http://127.0.0.1:8931' + endpoint + ';\n'
                      '    proxy_connect_timeout 3s;\n    proxy_read_timeout 25s;\n'
                      '    add_header Cache-Control "no-store" always;\n}\n')
    return {'navigation.json': raw, 'hubnav.js': js, 'navigation.conf': files['navigation.conf'] + b'\n' + '\n'.join(blocks).encode()}
