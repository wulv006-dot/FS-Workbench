"""Existing monitor outbox -> the user's existing DingTalk bot; no new service."""
import base64, hashlib, hmac, json, re, stat, time
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs, urlencode
from urllib.request import Request, build_opener
from delivery import NoRedirect
from collector import atomic


def load_bot(path):
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o077 or meta.st_size > 8192:
        raise ValueError('private_bot_config_required')
    config = json.loads(path.read_text())
    if (set(config) != {'approved','group','activated_at','webhook','secret'}
            or config['approved'] is not True or config['group'] != '服务器及Github报警'):
        raise ValueError('bot_scope_invalid')
    url = urlsplit(config['webhook'])
    query = parse_qs(url.query)
    if (url.scheme != 'https' or url.netloc != 'oapi.dingtalk.com' or url.path != '/robot/send'
            or url.fragment or set(query) != {'access_token'} or len(query['access_token']) != 1
            or not re.fullmatch(r'[a-fA-F0-9]{64}', query['access_token'][0])):
        raise ValueError('bot_endpoint_invalid')
    activated = datetime.fromisoformat(config['activated_at'])
    if activated.utcoffset() is None or activated > datetime.now(timezone.utc):
        raise ValueError('bot_activation_invalid')
    if not isinstance(config['secret'], str):raise ValueError('bot_secret_invalid')
    return config


def send_bot(config, event):
    # Official signing contract; don't try altered keys or repeated signature variants.
    url = config['webhook']
    if config['secret']:
        stamp = str(int(time.time()*1000))
        raw = (stamp+'\n'+config['secret']).encode()
        sign = base64.b64encode(hmac.new(config['secret'].encode(),raw,hashlib.sha256).digest()).decode()
        url += '&'+urlencode({'timestamp':stamp,'sign':sign})
    codes = [x['code'] for x in event['issues'] if re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',x['code'])]
    content = 'FS服务器巡检 '+('演练 ' if event.get('synthetic') else '')+event['kind']+' '+event['status']
    content += '\n'+event['created_at']+'\n事件 '+event['event_id']+'\n'+'\n'.join(codes[:24])
    for operation in event.get('operation_ids', [])[:24]:
        if re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', operation):
            content += '\n原操作 '+operation
    if any('publication' in code or 'published_price' in code for code in codes):
        content += '\n售价核对未通过；自动写入受保护，售卖风险未完全隔离。'
    body = json.dumps({'msgtype':'text','text':{'content':content}},ensure_ascii=False).encode()
    request = Request(url, data=body, headers={'Content-Type':'application/json'},method='POST')
    with build_opener(NoRedirect).open(request, timeout=8) as response:
        data = json.loads(response.read(8192))
    if type(data.get('errcode')) is not int or data['errcode'] != 0:
        raise ValueError('bot_not_accepted')


def deliver_bot(directory, path, transport=send_bot, loader=load_bot):
    result = {'state':'not_configured','accepted_event_ids':[],'delivered':False}
    if not path.exists():return result
    try:
        config = loader(path)
        pending = []
        for target in (directory/'outbox').glob('*.json'):
            event = json.loads(target.read_text())
            if event.get('delivery_state') != 'pending':continue
            if datetime.fromisoformat(event['created_at']) < datetime.fromisoformat(config['activated_at']):
                event['delivery_state'] = 'retained_pre_activation';atomic(target,event);continue
            pending.append((target,event))
        pending.sort(key=lambda row:row[1]['created_at'])
        # ponytail: two transitions per five-minute tick; reuse existing bounded outbox.
        for target,event in pending[:2]:
            event['attempt_count'] += 1;atomic(target,event)
            transport(config,event)
            event.update(delivery_state='accepted',acknowledged_at=datetime.now(timezone.utc).isoformat(),
                         provider_receipt={'provider':'dingtalk','accepted':True,'delivered':False})
            atomic(target,event);result['accepted_event_ids'].append(event['event_id'])
        result['state'] = 'accepted' if len(pending) <= 2 else 'pending_backlog'
    except Exception as exc:
        result['state'] = 'unconfirmed';result['error_type'] = type(exc).__name__
    atomic(directory/'delivery-latest.json',result)
    return result