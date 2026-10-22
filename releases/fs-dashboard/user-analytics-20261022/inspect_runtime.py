"""W0 read-only probe. Output hashes/health flags only; no credentials or order contents."""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.request import ProxyHandler, build_opener
from zoneinfo import ZoneInfo

FILES = (
    '/opt/fs-exact-range-20261001/range_api.py', '/opt/fs-hermes-fc/channel_source.py',
    '/opt/fs-hermes-fc/research.py', '/opt/fs-hermes-fc/controller.py',
    '/opt/fs-access-policy/rbac.py', '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf',
    '/var/www/dashboard/fs-home/navigation.json', '/var/www/hub/hubnav.js',
)


def probe():
    report = dict(observed_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), mutation=False,
                  files=[], services={}, live_order_samples='not_read_by_this_probe')
    for name in FILES:
        path = Path(name)
        item = dict(path=name, exists=path.is_file())
        if path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)):
            raw = path.read_bytes()
            item.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), owner=path.stat().st_uid)
        report['files'].append(item)
    opener = build_opener(ProxyHandler({}))
    for port in (8767, 8768):
        try:
            with opener.open('http://127.0.0.1:%s/health' % port, timeout=5) as response:
                value = json.loads(response.read(65536))
                report['services'][str(port)] = {k: value[k] for k in ('ready', 'login_attempts') if k in value}
        except Exception:
            report['services'][str(port)] = dict(status='unavailable')
    return report


if __name__ == '__main__':
    print(json.dumps(probe(), ensure_ascii=False, indent=2))
