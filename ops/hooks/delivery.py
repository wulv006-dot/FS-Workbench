"""No outbound requests until an approved, root-only config exists.

Only empty success/failure pings leave the server. HTTP acceptance is not inbox delivery.
"""
import json, os, re, stat
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, build_opener, HTTPRedirectHandler
from collector import atomic
from report import reader_health

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def send(url):
    with build_opener(NoRedirect).open(Request(url, data=b'', method='POST'), timeout=8) as response:
        if response.status != 200 or response.read(64).strip() != b'OK':
            raise ValueError('provider_did_not_accept')

def load_config(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        raise ValueError('private_config_required')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('approved') is not True or set(data) != {'approved','activated_at','heartbeat_url','business_url'}:
        raise ValueError('approval_config_invalid')
    for name in ('heartbeat_url','business_url'):
        if not re.fullmatch(r'https://hc-ping\.com/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', data[name]):
            raise ValueError('provider_endpoint_invalid')
    if data['heartbeat_url'] == data['business_url']:
        raise ValueError('separate_checks_required')
    activated = datetime.fromisoformat(data['activated_at'].replace('Z','+00:00'))
    if activated.utcoffset() is None or activated > datetime.now(timezone.utc):
        raise ValueError('activation_time_invalid')
    return data

def deliver(directory, config_path, transport=send, config_loader=load_config):
    result = {'state':'not_configured','delivered':False,'heartbeat':'not_sent','business':'not_sent',
              'accepted_event_ids':[], 'checked_at':datetime.now(timezone.utc).isoformat()}
    bot_path = Path('/etc/fc-ops-readonly-monitor/hooks-bot.json')
    if bot_path.exists():
        from hooks_notifier import deliver_bot
        return deliver_bot(directory, bot_path)
    if not config_path.exists():
        atomic(directory / 'delivery-latest.json', result)
        return result
    try:
        config = config_loader(config_path)
        latest = json.loads((directory / 'latest.json').read_text(encoding='utf-8'))
        status = reader_health(latest, datetime.now(timezone.utc))
        if status in {'monitor_stale_or_clock_invalid','monitor_unavailable'}:
            raise ValueError('fresh_snapshot_required')
        transport(config['heartbeat_url'])
        result['heartbeat'] = 'accepted'
        pending = []
        for path in (directory / 'outbox').glob('*.json'):
            event = json.loads(path.read_text(encoding='utf-8'))
            if event['delivery_state'] != 'pending':
                continue
            if datetime.fromisoformat(event['created_at']) < datetime.fromisoformat(config['activated_at']):
                event['delivery_state'] = 'retained_pre_activation'
                atomic(path, event)
                continue
            pending.append((path,event))
        pending.sort(key=lambda row:row[1]['created_at'])
        # ponytail: at most two queued transitions per tick; five-minute retries, no worker daemon.
        for path,event in pending[:2]:
            event['attempt_count'] += 1
            atomic(path,event)
            transport(config['business_url'] + ('/fail' if event['kind']=='incident' else ''))
            event.update(delivery_state='accepted', acknowledged_at=datetime.now(timezone.utc).isoformat(),
                         provider_receipt={'provider':'healthchecks','response':'OK','delivered':False})
            atomic(path,event)
            result['accepted_event_ids'].append(event['event_id'])
        if len(pending) <= 2:
            transport(config['business_url'] + ('' if status=='healthy' else '/fail'))
            result['business']='accepted'
        result['state']='accepted' if len(pending)<=2 else 'pending_backlog'
    except Exception as exc:
        result['state']='unconfirmed'
        result['error_type']=type(exc).__name__  # Never log URLs or provider exception messages.
    atomic(directory / 'delivery-latest.json', result)
    return result
