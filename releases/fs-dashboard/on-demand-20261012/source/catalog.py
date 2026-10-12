"""Query capabilities and identities only; contains no collected business values."""
from datetime import datetime, timedelta
import hashlib, json

CONTRACT = 'all-websites-order-primary-admin-supplement-v1'

def identifier(profiles):
    raw = json.dumps(list(profiles), ensure_ascii=False, separators=(',', ':')).encode()
    return 'catalog-' + hashlib.sha256(raw).hexdigest()[:16]

def build(profiles, now):
    now = now.replace(second=0, microsecond=0)
    first = (now.date()-timedelta(days=365)).isoformat()
    last = now.date().isoformat()
    version = identifier(profiles)
    entries, dashboard = {}, {}
    for key, name, gid, game, group in profiles:
        entries[key] = {'key': key, 'name': name, 'period': {'start': first+' 00:00', 'end': now.strftime('%Y-%m-%d %H:%M')},
            'primary': {'status': 'not_provided', 'normalisedScope': 'all-websites',
                        'filters': {'gid': str(gid), 'tid': '', 'status': '3' if group == 'rpg' else ''}},
            'supplement': {'status': 'not_provided'}, 'metrics': {}, 'dimensions': {}}
        dashboard[key] = {'name': 'MMOEXP主站' if key == 'MMOEXP' else name, 'series': [], 'hourly': [],
                          'coverage': {'from': first, 'to': last, 'kind': 'query-capability-window'}, 'group': group}
    groups = [{'key': key, 'label': label, 'profiles': [p[0] for p in profiles if p[4] == key]}
              for key, label in [('mmoexp', '所有网站合计'), ('rpg', 'RPG · 已完成'),
                                 ('sports', '球类 · 全部状态'), ('general', '综合游戏 · 全部状态')]
              if any(p[4] == key for p in profiles)]
    return {'schemaVersion': 2, 'catalogId': version, 'snapshotId': version,
            'scopeContractId': CONTRACT, 'timezone': 'Asia/Shanghai', 'currency': 'USD',
            'generatedAt': now.isoformat(), 'generatedAtShanghai': now.strftime('%Y-%m-%d %H:%M'),
            'profiles': entries, 'dashboard': {'groups': groups, 'profiles': dashboard},
            'dataPolicy': 'metadata-only; native values are queried by date', 'maximumRangeDays': 366}
