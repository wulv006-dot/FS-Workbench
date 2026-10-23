"""Hermes native no-agent cron: bounded checks, change-only Feishu alerts."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import fcntl
from datetime import datetime, timezone, timedelta
from common import age, sha

HOME = Path('/profile/ops-watchdog')
PRICING_PREFIXES = ('fc_pricing_', 'rpg_pricing_', 'pricing_monitor_')

def pricing_owned(code):
    return isinstance(code, str) and code.startswith(PRICING_PREFIXES)

def pricing_issues(home, previous, now, pricing_only):
    path = home/'pricing-snapshot.json'
    installed = previous.get('pricing_installed', False) or path.exists() or pricing_only
    retained = [code for code in previous.get('issues', []) if isinstance(code, str) and code.startswith(('fc_pricing_', 'rpg_pricing_'))]
    if not installed:
        return None, False, None, []
    try:
        supplement = read(path)
        if supplement is None:
            return sorted(set(retained + ['pricing_monitor_snapshot_missing'])), True, previous.get('pricing_exported_at'), []
        stamp = supplement['exported_at']
        if not -60 <= age(stamp, now) <= 600:
            return sorted(set(retained + ['pricing_monitor_snapshot_stale'])), True, previous.get('pricing_exported_at'), []
        codes = supplement['issues']
        if not isinstance(codes, list) or not all(pricing_owned(code) for code in codes):
            raise ValueError('owned_codes_required')
        legacy = supplement.get('legacy_issue_codes', [])
        if not isinstance(legacy, list) or len(legacy) > 1000 or not all(isinstance(code, str) and 0 < len(code) <= 512 for code in legacy):
            raise ValueError('bounded_legacy_codes_required')
        old_stamp = previous.get('pricing_exported_at')
        if old_stamp and age(stamp, now) > age(old_stamp, now):
            return sorted(set(retained + ['pricing_monitor_snapshot_regressed'])), True, old_stamp, []
        return sorted(set(codes)), True, stamp, sorted(set(legacy))
    except (KeyError, TypeError, ValueError, AttributeError, OSError):
        return sorted(set(retained + ['pricing_monitor_snapshot_invalid'])), True, previous.get('pricing_exported_at'), []

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.ops-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def read(path, default=None):
    try: return json.loads(path.read_text('utf-8'))
    except FileNotFoundError: return default

def send(message, target):
    sys.path.insert(0, '/opt/hermes')
    from hermes_cli.env_loader import load_hermes_dotenv
    load_hermes_dotenv(hermes_home='/profile')
    from tools.send_message_tool import send_message_tool
    response = send_message_tool({'target': target, 'message': message})
    result = json.loads(response) if isinstance(response, str) else response
    return result

def message_id(result):
    # An accepted send without an actual ID is retained as unknown, never retried.
    if result.get('success') is False or result.get('error'):
        return None
    return result.get('message_id') or (result.get('raw_response') or {}).get('message_id')

def task_text(issues, config, incident):
    sections = []
    rpg = [code for code in issues if code.startswith(('rpg_', 'd4_', 'poe2_', 'aion2_'))]
    fc = [code for code in issues if code not in rpg]
    for label, codes, owner in (('FC / FS', fc, 'codex'), ('RPG', rpg, 'workbuddy')):
        if not codes: continue
        identity = config.get('owners', {}).get(owner)
        mention = '<at user_id="' + identity + '"></at> ' if identity else ''
        sections.append(mention + label + ' 故障任务\n' + '\n'.join('• ' + code for code in codes))
    return '\n\n'.join(sections) + '\n事件：' + incident

def run(home=HOME, transport=send, now=None, pricing_only=False):
    home.mkdir(parents=True, exist_ok=True)
    with (home/'.watch.lock').open('a+b') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'state': 'concurrent_check_skipped'}
        return _run_locked(home, transport, now, pricing_only)

def _run_locked(home, transport, now, pricing_only):
    now = now or datetime.now(timezone.utc)
    previous = read(home/'watch-state.json', {})
    # Keep the original event across both modes, including a crash before state commit.
    event_id = previous.get('pending_event')
    pending_path = home/'outbox'/(event_id + '.json') if event_id else None
    old_pending = read(pending_path, {}) if pending_path else {}
    if pending_path and old_pending.get('state') == 'sent' and old_pending.get('message_id') and old_pending.get('target_state'):
        write(home/'watch-state.json', old_pending['target_state'])
        if old_pending.get('repair_action'):
            write(home/'request.json', {'incident': old_pending['target_state']['incident'], 'action': old_pending['repair_action'], 'created_at': old_pending['created_at']})
        return {'state': 'reconciled_sent'}
    unresolved = [(p.stem, read(p, {})) for p in sorted((home/'outbox').glob('*.json'))]
    unresolved = [(event, value) for event, value in unresolved if value.get('state') in {'sending', 'unknown'}]
    unknown_codes, unknown_recoveries = set(), set()
    for _, value in unresolved:
        scope = value.get('notification_scope')
        unknown_codes.update(scope.get('new', []) if scope else value.get('target_state', {}).get('issues', []))
        if scope: unknown_recoveries.update(scope.get('recovered', []))
    snapshot = read(home/'snapshot.json', {})
    if pricing_only:
        issues = [code for code in previous.get('issues', []) if not pricing_owned(code)]
        repair = previous.get('repair_summary')
        if repair is None:
            legacy = snapshot.get('repair') or {}
            legacy_signature = sha(json.dumps({'issues': sorted(set(previous.get('issues', []))), 'repair': {k: legacy.get(k) for k in ('incident', 'status', 'error')}}, sort_keys=True).encode())
            repair = legacy if legacy_signature == previous.get('signature') else {}
    else:
        issues = list(snapshot.get('issues', []))
        try:
            if not -60 <= age(snapshot['exported_at'], now) <= 900:
                issues.append('watchdog_export_stale')
        except (KeyError, TypeError, ValueError): issues.append('watchdog_export_missing')
        repair = snapshot.get('repair') or {}
    supplement, installed, pricing_stamp, legacy_codes = pricing_issues(home, previous, now, pricing_only)
    if supplement is not None:
        issues = [code for code in issues if not pricing_owned(code) and code not in legacy_codes] + supplement
    repair_summary = {key: repair.get(key) for key in ('incident', 'status', 'error', 'url')} if repair else {}
    issues = sorted(set(issues))
    signature = sha(json.dumps({'issues': issues, 'repair': {k: repair.get(k) for k in ('incident', 'status', 'error')}}, sort_keys=True).encode())
    def state(incident=None):
        value = {'signature': signature, 'issues': issues, 'checked_at': now.isoformat(), 'repair_summary': repair_summary, 'pricing_installed': installed, 'pricing_exported_at': pricing_stamp, 'unknown_notification_events': [event for event, _ in unresolved]}
        if incident: value['incident'] = incident
        return value
    if signature == previous.get('signature') and not ((unknown_codes-set(issues))-unknown_recoveries):
        # Freshness metadata is not an alert change, but must advance monotonically.
        write(home/'watch-state.json', state(previous.get('incident')))
        write(home/'last-check.json', {'checked_at': now.isoformat(), 'issues': issues, 'state': 'unchanged_quiet'})
        return {'state': 'unchanged_quiet'}
    if not issues and not previous.get('issues') and not repair and not unknown_codes:
        write(home/'watch-state.json', state())
        return {'state': 'healthy_quiet'}
    incident = previous.get('incident') if issues == previous.get('issues') else None
    if not incident:
        incident = sha((str(previous.get('signature')) + str(previous.get('checked_at')) + json.dumps(issues)).encode())[:16]
    config = read(home/'private-target.json')
    action = None if pricing_only else 'brain-theme' if snapshot.get('brain', {}).get('repairable') and 'brain_ui_dependencies_missing' in issues else 'monitor-health' if snapshot.get('monitor_repairable') and 'monitor_known_health_schema_regression' in issues else None
    def request_repair():
        if action:
            write(home/'request.json', {'incident': incident, 'action': action, 'created_at': now.isoformat()})
    eligible = lambda code: pricing_owned(code) if pricing_only else True
    before_codes = set(previous.get('issues', []))
    shown_issues = sorted(code for code in set(issues)-before_codes-unknown_codes if eligible(code))
    recovered = sorted(code for code in (before_codes | unknown_codes)-set(issues)-unknown_recoveries if eligible(code))
    changed_repair = not pricing_only and repair_summary != previous.get('repair_summary', {})
    scope = {'new': shown_issues, 'recovered': recovered, 'repair': repair_summary if changed_repair else {}}
    same_unknown = next((event for event, value in unresolved if value.get('notification_scope') == scope), None)
    if same_unknown or (not shown_issues and not recovered and not changed_repair and unresolved):
        return {'state': 'notification_unknown_no_retry', 'event': same_unknown or event_id or unresolved[0][0]}
    if shown_issues:
        text = 'Hermes 业务巡检发现新增异常\n' + task_text(shown_issues, config, incident)
        if pricing_only:
            text = 'Hermes FC/RPG自动改价即时检查发现异常\n' + task_text(shown_issues, config, incident)
        text += '\n巡检时间（北京）：' + now.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
        if not pricing_only:
            text += '\n接单后请 @Hermes 回复“Codex接管 ' + incident + '”或“WorkBuddy接管 ' + incident + '”。FC未接单10分钟后，仅执行已验证自修白名单；RPG由WorkBuddy处理。未覆盖故障保留现场并升级。'
    else:
        text = ('Hermes FC/RPG自动改价：异常恢复状态更新。' if pricing_only else 'Hermes 业务巡检：状态更新。') + '\n核对时间（北京）：' + now.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    if recovered:
        recovered_price = [code for code in recovered if pricing_owned(code)]
        recovered_general = [code for code in recovered if not pricing_owned(code)]
        if recovered_price: text += '\nFC/RPG价格巡检已恢复项：\n' + '\n'.join('• ' + code for code in recovered_price)
        if recovered_general: text += '\n其他巡检已恢复项：\n' + '\n'.join('• ' + code for code in recovered_general)
    if unresolved:
        text += '\n此前独立通知仍待对账（本次不重发其正文）：' + ', '.join(event for event, _ in unresolved)
    if repair and not pricing_only:
        text += '\n修复状态：' + str(repair.get('status'))
        if repair.get('url'): text += '\nPR：' + repair['url']
        if repair.get('error'): text += '\n待处理：' + repair['error']
    event = sha((str(previous.get('signature')) + str(previous.get('checked_at')) + signature).encode())
    pending = home/'outbox'/ (event + '.json')
    old = read(pending, {})
    if old.get('state') in {'sending', 'unknown'}:
        return {'state': 'notification_unknown_no_retry'}
    if old.get('state') == 'sent':
        if not old.get('message_id'):
            return {'state': 'notification_unknown_no_retry', 'event': event}
        request_repair()
        write(home/'watch-state.json', state(incident))
        return {'state': 'reconciled_sent'}
    journal = {'state': 'sending', 'signature': signature, 'created_at': now.isoformat(), 'event': event, 'target_state': state(incident), 'repair_action': action, 'notification_scope': scope}
    write(pending, journal)
    write(home/'watch-state.json', dict(previous, pending_event=event, unknown_notification_events=[item for item, _ in unresolved] + [event]))
    try:
        receipt = transport(text, config['target'])
        mid = message_id(receipt)
        write(pending, dict(journal, state='sent' if mid else 'unknown', message_id=mid, checked_at=now.isoformat()))
        if not mid: return {'state': 'notification_unknown_no_retry'}
    except Exception as error:
        write(pending, dict(journal, state='unknown', error=type(error).__name__, checked_at=now.isoformat()))
        return {'state': 'notification_unknown_no_retry'}
    write(home/'watch-state.json', state(incident))
    request_repair()
    return {'state': 'sent', 'message_id': mid}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', nargs='?', choices=['check', 'pricing-check', 'claim', 'release', 'status'], default='check')
    parser.add_argument('incident', nargs='?')
    parser.add_argument('--owner', choices=['codex', 'workbuddy'], default='codex')
    args = parser.parse_args()
    if args.action in {'claim', 'release'}:
        import re
        if not args.incident or not re.fullmatch('[a-f0-9]{16}', args.incident): raise SystemExit('valid_incident_required')
        write(HOME/('claim-'+args.owner+'.json'), {'incident': args.incident, 'owner': args.owner, 'active': args.action == 'claim', 'claimed_at': datetime.now(timezone.utc).isoformat()})
        print(json.dumps({'state': 'claimed' if args.action == 'claim' else 'released', 'lease_minutes': 60}))
    elif args.action == 'status': print(json.dumps(read(HOME/'snapshot.json', {}), ensure_ascii=False))
    else:
        result = run(pricing_only=args.action == 'pricing-check')
        write(HOME/'last-run.json', result)
        # Native cron records failures and uses failure_deliver; successful runs stay local.
        if result['state'] == 'notification_unknown_no_retry':
            print('Feishu notification result unknown; preserve outbox, do not blindly resend.')
            raise SystemExit(1)
