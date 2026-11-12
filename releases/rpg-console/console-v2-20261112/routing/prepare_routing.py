"""Prepare an exact RPG route payload; never writes live files or reloads nginx.

The root release transaction owns CAS, backup, atomic replacement, nginx -t,
reload and post-deploy readback. This file is a pure payload/rollback builder.
"""
import argparse
import hashlib
import json
from pathlib import Path

BASE_SHA = '359e1116ddbb5e3bb59be4b8c53065512173a2c2add49cd2ea27db7325644df7'
MAP_BLOCK = '''# >>> rpg-console-alias-map-20261112 >>>
map $request_uri $rpg_console_auth_uri {
    default /__rpg_console_unmapped__;
    ~^/repricing(?<rpg_console_suffix>/.*)$ /d4$rpg_console_suffix;
}
# <<< rpg-console-alias-map-20261112 <<<

'''
AUTH_BLOCK = '''    # >>> rpg-console-alias-auth-20261112 >>>
    location = /__rpg_console_verify {
        internal;
        proxy_pass http://127.0.0.1:8895/verify;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $rpg_console_auth_uri;
        proxy_set_header X-Original-Method $request_method;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Cookie $http_cookie;
    }
    # <<< rpg-console-alias-auth-20261112 <<<

'''
START='    # >>> d4follow (auto) >>>'
END='    # <<< d4follow (auto) <<<'
PREFIX_LINE='        proxy_set_header X-Forwarded-Prefix /d4/;\n'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def one(text, old, new):
    if text.count(old)!=1:
        raise ValueError('Expected exactly one unchanged anchor: '+old[:90])
    return text.replace(old,new,1)


def original_section(text):
    if text.count(START)!=1 or text.count(END)!=1:
        raise ValueError('RPG block not unique')
    start=text.index(START)
    stop=text.index(END,start)+len(END)
    return text[start:stop]


def route_blocks(original):
    section=original_section(original)
    start=section.index('    location /d4/ {')
    end=section.rindex('    }')+5
    loc=section[start:end]
    loc=one(loc,'        proxy_set_header X-Forwarded-Proto $scheme;\n',
               '        proxy_set_header X-Forwarded-Proto $scheme;\n'+PREFIX_LINE)
    alias=loc.replace('    location /d4/ {','    location /repricing/ {',1)
    alias=one(alias,'auth_request /__auth_verify;','auth_request /__rpg_console_verify;')
    alias=one(alias,'X-Forwarded-Prefix /d4/;','X-Forwarded-Prefix /repricing/;')
    alias='''    # >>> rpg-console-alias-route-20261112 >>>
    location = /repricing { return 301 /repricing/$is_args$args; }
'''+alias+'''
    # <<< rpg-console-alias-route-20261112 <<<
'''
    canonical=loc.replace('    location /d4/ {','''    location = /d4/ {
        # Only the old HTML landing page changes address. All API paths stay intact.
        if ($request_method ~ ^(GET|HEAD)$) { return 302 /repricing/$is_args$args; }''',1)
    canonical='''    # >>> rpg-console-canonical-root-20261112 >>>
'''+canonical+'''
    # <<< rpg-console-canonical-root-20261112 <<<
'''
    return loc,alias,canonical


def build(before):
    if digest(before)!=BASE_SHA:
        raise ValueError('Live baseline changed; re-inspect before preparing a new payload')
    text=before.decode('utf-8')
    if 'rpg-console-alias-' in text or 'location /repricing/' in text:
        raise ValueError('Alias already exists; do not duplicate')
    old_section=original_section(text)
    loc,alias,canonical=route_blocks(text)
    new_section=one(old_section,'        proxy_set_header X-Forwarded-Proto $scheme;\n',
                  '        proxy_set_header X-Forwarded-Proto $scheme;\n'+PREFIX_LINE)
    text=one(text,old_section,new_section+'\n\n'+canonical+'\n'+alias)
    text=one(text,'    # 部署通道专用校验端点：除登录外还要求 deploy 组成员（mmoexp 不在其中）',
                  AUTH_BLOCK+'    # 部署通道专用校验端点：除登录外还要求 deploy 组成员（mmoexp 不在其中）')
    return (MAP_BLOCK+text).encode('utf-8')


def reverse(current, before):
    """Exact inverse of owned fragments; preserve unrelated later edits."""
    baseline=before.decode('utf-8')
    text=current.decode('utf-8')
    _,alias,canonical=route_blocks(baseline)
    text=one(text,MAP_BLOCK,'')
    text=one(text,AUTH_BLOCK,'')
    text=one(text,'\n\n'+canonical+'\n'+alias,'')
    current_section=original_section(text)
    restored_section=one(current_section,PREFIX_LINE,'')
    text=one(text,current_section,restored_section)
    return text.encode('utf-8')


def prepare(directory):
    before=(directory/'iggm-web.before.conf').read_bytes()
    after=build(before)
    if reverse(after,before)!=before:
        raise ValueError('Inverse payload differs from baseline')
    (directory/'iggm-web.after.conf').write_bytes(after)
    manifest={
        'scope':'rpg-console-alias-20261112','target':'/etc/nginx/conf.d/iggm-web.conf',
        'expected_sha256':digest(before),'target_sha256':digest(after),
        'before':'iggm-web.before.conf','candidate':'iggm-web.after.conf',
        'ownership':'Only RPG alias map/auth/route/canonical root and old prefix header',
        'preserved':['/d4/api/*','all existing authentication membership and RBAC policy',
                     'RPG transport 127.0.0.1:8900','all services/timers/database paths'],
        'reload':'nginx only, after existing publisher CAS/backup/atomic replace and nginx -t',
        'status':'prepared_not_deployed'
    }
    (directory/'routing-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','restore-payload'])
    parser.add_argument('--directory',type=Path,default=Path(__file__).parent)
    parser.add_argument('--current',type=Path)
    parser.add_argument('--expected-current-sha')
    args=parser.parse_args()
    if args.action=='prepare':
        print(json.dumps(prepare(args.directory),ensure_ascii=False))
    else:
        if not args.current or not args.expected_current_sha:
            parser.error('restore-payload needs --current and --expected-current-sha')
        current=args.current.read_bytes()
        if digest(current)!=args.expected_current_sha:
            raise ValueError('Rollback input changed')
        output=reverse(current,(args.directory/'iggm-web.before.conf').read_bytes())
        target=args.directory/'iggm-web.rollback.conf'
        target.write_bytes(output)
        print(json.dumps({'expected_sha256':digest(current),'target_sha256':digest(output),
                          'output':str(target),'status':'rollback_payload_only'}))
