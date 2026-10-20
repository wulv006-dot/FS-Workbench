"""Hermes native no-agent cron: bounded checks, change-only Feishu alerts."""
import argparse
import json
import os
import re
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from common import age, sha

HOME = Path('/profile/ops-watchdog')

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

def run(home=HOME, transport=send, now=None):
    now = now or datetime.now(timezone.utc)
    snapshot = read(home/'snapshot.json', {})
    issues = list(snapshot.get('issues', []))
    try:
        if not -60 <= age(snapshot['exported_at'], now) <= 900:
            issues.append('watchdog_export_stale')
    except (KeyError, TypeError, ValueError): issues.append('watchdog_export_missing')
    repair = snapshot.get('repair') or {}
    issues = sorted(set(issues))
    signature = sha(json.dumps({'issues': issues, 'repair': {k: repair.get(k) for k in ('incident', 'status', 'error')}}, sort_keys=True).encode())
    previous = read(home/'watch-state.json', {})
    if signature == previous.get('signature'):
        write(home/'last-check.json', {'checked_at': now.isoformat(), 'issues': issues, 'state': 'unchanged_quiet'})
        return {'state': 'unchanged_quiet'}
    if not issues and not previous.get('issues') and not repair:
        write(home/'watch-state.json', {'signature': signature, 'issues': [], 'checked_at': now.isoformat()})
        return {'state': 'healthy_quiet'}
    incident = None
    if issues == previous.get('issues'):
        # Pre-incident state files still have live requests/claims using this ID.
        # Migrate a continuing fault without orphaning those records.
        incident = previous.get('incident') or sha(json.dumps(issues).encode())[:16]
    if not incident:
        incident = sha((str(previous.get('signature')) + str(previous.get('checked_at')) + json.dumps(issues)).encode())[:16]
    config = read(home/'private-target.json')
    def request_repair():
        action = 'brain-theme' if snapshot.get('brain', {}).get('repairable') and 'brain_ui_dependencies_missing' in issues else 'monitor-health' if snapshot.get('monitor_repairable') and 'monitor_known_health_schema_regression' in issues else None
        if action:
            write(home/'request.json', {'incident': incident, 'action': action, 'created_at': now.isoformat()})
    if issues:
        text = 'Hermes 业务巡检发现异常\n' + task_text(issues, config, incident)
        text += '\n巡检时间（北京）：' + now.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
        text += '\n接单后请 @Hermes 回复“Codex接管 ' + incident + '”或“WorkBuddy接管 ' + incident + '”。FC未接单10分钟后，仅执行已验证自修白名单；RPG由WorkBuddy处理。未覆盖故障保留现场并升级。'
    else:
        text = 'Hermes 业务巡检：此前异常已恢复。\n核对时间（北京）：' + now.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    if repair:
        text += '\n修复状态：' + str(repair.get('status'))
        if repair.get('url'): text += '\nPR：' + repair['url']
        if repair.get('error'): text += '\n待处理：' + repair['error']
    event = sha((str(previous.get('signature')) + str(previous.get('checked_at')) + signature).encode())
    pending = home/'outbox'/ (event + '.json')
    old = read(pending, {})
    if old.get('state') in {'sending', 'unknown'}:
        return {'state': 'notification_unknown_no_retry'}
    if old.get('state') == 'sent':
        # Old releases did not persist the delivered ID. During migration it
        # could be either the legacy ID or #249's fresh ID: never guess or resend.
        delivered = old.get('incident')
        if not isinstance(delivered, str) or not re.fullmatch('[a-f0-9]{16}', delivered):
            return {'state': 'notification_unknown_no_retry'}
        incident = delivered
        request_repair()
        write(home/'watch-state.json', {'signature': signature, 'issues': issues, 'incident': incident, 'checked_at': now.isoformat()})
        return {'state': 'reconciled_sent'}
    write(pending, {'state': 'sending', 'incident': incident, 'signature': signature, 'created_at': now.isoformat()})
    try:
        receipt = transport(text, config['target'])
        mid = message_id(receipt)
        write(pending, {'state': 'sent' if mid else 'unknown', 'incident': incident, 'message_id': mid, 'checked_at': now.isoformat()})
        if not mid: return {'state': 'notification_unknown_no_retry'}
    except Exception as error:
        write(pending, {'state': 'unknown', 'incident': incident, 'error': type(error).__name__, 'checked_at': now.isoformat()})
        return {'state': 'notification_unknown_no_retry'}
    write(home/'watch-state.json', {'signature': signature, 'issues': issues, 'incident': incident, 'checked_at': now.isoformat()})
    request_repair()
    return {'state': 'sent', 'message_id': mid}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', nargs='?', choices=['check', 'claim', 'release', 'status'], default='check')
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
        result = run()
        write(HOME/'last-run.json', result)
        # Native cron records failures and uses failure_deliver; successful runs stay local.
        if result['state'] == 'notification_unknown_no_retry':
            print('Feishu notification result unknown; preserve outbox, do not blindly resend.')
            raise SystemExit(1)
