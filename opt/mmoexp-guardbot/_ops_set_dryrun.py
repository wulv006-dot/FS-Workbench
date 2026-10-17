#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 GuardBot 的 dryRun 关掉（改为 false），其余字段原样保留。

幂等：重复执行结果一致（第二次 before 就是 false）。
先自动备份当前 config.json 到同目录 .pre-dryrun-<时间戳>。
跑法：/opt/python39/bin/python3 _ops_set_dryrun.py
"""
import json
import os
import shutil
import time

CFG = '/opt/mmoexp-guardbot/config.json'

bak = CFG + '.pre-dryrun-' + time.strftime('%Y%m%d-%H%M%S')
shutil.copy2(CFG, bak)

with open(CFG, encoding='utf-8') as f:
    c = json.load(f)

before = c.get('dryRun')
c['dryRun'] = False

with open(CFG, 'w', encoding='utf-8') as f:
    json.dump(c, f, ensure_ascii=False, indent=2)
    f.write('\n')

with open(CFG, encoding='utf-8') as f:
    d = json.load(f)

print('backup          :', bak)
print('dryRun          : %r -> %r' % (before, d.get('dryRun')))
print('action          :', repr(d.get('action')))
print('matchMode       :', repr(d.get('matchMode')))
print('guildId         :', repr(d.get('guildId')))
print('logChannelId    :', repr(d.get('logChannelId')))
print('whitelistRoleIds:', d.get('whitelistRoleIds'))
print('whitelistUserIds:', d.get('whitelistUserIds'))
print('token intact    :', bool(d.get('token')) and str(d['token']).startswith('MTU1OTgx'))
print('注释键数量      :', sum(1 for k in d if k.startswith('_')))
print('文件权限        :', oct(os.stat(CFG).st_mode & 0o777))
