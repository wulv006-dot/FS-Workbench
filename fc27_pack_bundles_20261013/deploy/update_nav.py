import json
import os
import shutil

P = '/var/www/dashboard/fs-home/navigation.json'
BAK = P + '.bak-bundles-20261013'
TOOL_ID = 'fc27-bundles'

if not os.path.exists(BAK):
    shutil.copy2(P, BAK)
with open(P, encoding='utf-8') as fh:
    d = json.load(fh)

changed = False
for s in d.get('sections', []):
    if s.get('id') == 'sports' and TOOL_ID not in s.get('ids', []):
        s['ids'].append(TOOL_ID)
        changed = True

tool = {
    'id': TOOL_ID,
    'label': 'FC27 捆绑包定价',
    'path': '/dashboard/modules/sports/bundles/',
    'icon': 'Σ',
    'short': 'Futbin 球员捆绑包自动定价 · 原价与折扣售价',
    'ownerId': None,
    'serverGuard': '/__auth_verify',
    'scope': 'global-portal',
    'section': 'sports',
    'requiredGroup': 'dashboard',
}
if not any(t.get('id') == TOOL_ID for t in d.get('tools', [])):
    d['tools'].append(tool)
    changed = True

if changed:
    tmp = P + '.tmp-bundles'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=2)
        fh.write('\n')
    os.replace(tmp, P)
    print('NAV_UPDATED')
else:
    print('NAV_ALREADY_OK')
