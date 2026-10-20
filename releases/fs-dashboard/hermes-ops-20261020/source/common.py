"""Small, deterministic checks; no business writes or pricing calculations."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

UI_ROOT = '/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/'
UI_TAGS = tuple('<link rel="stylesheet" href="' + UI_ROOT + name + '">' for name in ('fs-tokens.css', 'fs-ui.css')) + ('<script src="' + UI_ROOT + 'fs-theme.js"></script>',)
IGNORED = {'gallery_automation_disabled', 'coin_automation_disabled_or_manual'}
MONITOR_BEFORE = 'b326c54808bacdda43d0f5b29e065d503256502d7765a0e75eee35b674223f0d'
MONITOR_AFTER = '792b84ee67f0441ba7da6e591d8029ef25eb3c41c6085d195c2dc1cf2856d753'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def age(stamp, now):
    value = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if value.utcoffset() is None:
        raise ValueError('timezone_required')
    return (now - value).total_seconds()

def repair_html(before):
    text = before.decode('utf-8')
    if text.count('<head>') != 1 or text.count('</head>') != 1 or text.count('<link rel="stylesheet" href="brain.css">') != 1:
        raise ValueError('unrecognized_brain_page')
    missing = [tag for tag in UI_TAGS if tag not in text]
    # Only the known missing-dependency fault is automatic; changed versions need review.
    if any(name in text and tag not in text for name, tag in zip(('fs-tokens.css', 'fs-ui.css', 'fs-theme.js'), UI_TAGS)):
        raise ValueError('different_ui_version_requires_review')
    if not missing:
        return before
    return text.replace('<link rel="stylesheet" href="brain.css">', ''.join(missing) + '<link rel="stylesheet" href="brain.css">', 1).encode('utf-8')

def repair_content(recipe, before):
    if recipe == 'brain-theme': return repair_html(before)
    if recipe == 'monitor-health':
        if sha(before) == MONITOR_AFTER: return before
        if sha(before) != MONITOR_BEFORE: raise ValueError('monitor_source_drift')
        after = (Path(__file__).parent/'recipes/monitor-health/hooks.py').read_bytes()
        if sha(after) != MONITOR_AFTER: raise ValueError('reviewed_monitor_recipe_drift')
        return after
    raise ValueError('unknown_recipe')

def assess(snapshot, now=None):
    now = now or datetime.now(timezone.utc)
    issues = set()
    try:
        if not -60 <= age(snapshot['captured_at'], now) <= 900:
            issues.add('monitor_stale_or_clock_invalid')
    except (KeyError, TypeError, ValueError):
        issues.add('monitor_unavailable')
    for item in snapshot.get('issues', []):
        code = item.get('code', '')
        if item.get('level') == 'warning' and code.startswith('noncore_source_unavailable:'):
            continue
        if code and code not in IGNORED:
            issues.add(code)
    if snapshot.get('status') not in {'healthy', 'warning', 'critical'}:
        issues.add('monitor_unverified')
    coin = snapshot.get('coin', {})
    schedule = coin.get('schedule', {})
    job = coin.get('job', {})
    enabled = coin.get('config', {}).get('system_enabled') is True and coin.get('config', {}).get('mode') == 'auto'
    if enabled:
        if schedule.get('status') in {'failed', 'blocked', 'needs_reconcile', 'unknown'}:
            issues.add('coin_schedule_' + schedule['status'])
        if job.get('result') in {'deferred_player_sync', 'unknown', 'partial', 'failed'}:
            issues.add('coin_result_' + job['result'])
        next_at = schedule.get('next_at')
        if next_at:
            try:
                if age(next_at, now) > 900:
                    issues.add('coin_schedule_overdue')
            except (TypeError, ValueError):
                issues.add('coin_schedule_time_invalid')
    if snapshot.get('health', {}).get('incomplete_executions', 0):
        issues.add('business_write_unresolved')
    return sorted(issues)
