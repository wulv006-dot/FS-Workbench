"""固定六次 RPG/FC 改价巡检：复用 watch.py 的 pricing-check。

只读 pricing-snapshot.json（外部 exporter 写入），按既有签名去重，RPG 码自动 @ 大超的WorkBuddy。
无新增失败时静默（cron deliver=local，脚本自身按需发群）。
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import watch  # noqa: E402

HOME = Path('/profile/ops-watchdog')
ATTEMPTS = 6
WAIT_SECONDS = 10


def main():
    result = {'state': 'not_run'}
    for attempt in range(1, ATTEMPTS + 1):
        result = watch.run(pricing_only=True)
        if result.get('state') != 'concurrent_check_skipped':
            break
        time.sleep(WAIT_SECONDS)
    snapshot = watch.read(HOME / 'pricing-snapshot.json', {}) or {}
    record = dict(result)
    record.update({
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'trigger': 'cron-six-daily',
        'attempts': attempt,
        'snapshot_exported_at': snapshot.get('exported_at'),
        'rpg_unresolved': snapshot.get('rpg_unresolved'),
        'issues': snapshot.get('issues'),
    })
    watch.write(HOME / 'last-pricing-run.json', record)
    if result.get('state') == 'notification_unknown_no_retry':
        print('Feishu notification result unknown; preserve outbox, do not blindly resend.')
        return 1
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
