"""Bounded read-only problem-order evidence using the shared Order HTTP session and lock."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import time

SHANGHAI = timezone(timedelta(hours=8))
CATEGORIES = ('credentials','market_locked','account_restriction','cooldown','supply','customer_wait','unclear')
PATTERNS = {
    'credentials': r'密码错误|密码不对|账密错误|验证码错误|备份码错误|无法登录|wrong\s+password|invalid\s+(?:credential|backup\s*code)',
    'market_locked': r'市场未解锁|未解锁市场|市场未开启|转会市场.*未开放|market\s+(?:is\s+)?locked',
    'account_restriction': r'账号被封|账户受限|软封|交易受限|account\s+(?:banned|restricted)',
    'cooldown': r'冷却中|等待冷却|小时后继续|小时后再试|cooldown',
    'supply': r'缺货|库存不足|金币不足|供货不足|out\s+of\s+stock',
    'customer_wait': r'等待客户回复|客户未回复|等客户确认|等待买家|awaiting\s+(?:customer|buyer)',
}


def classify_logs(rows):
    """Use fixed historical clues only. Negation/resolution/ambiguity remains unclear."""
    clues=[]
    for row in rows[:100]:
        text=str(row.get('content',''))[:4000]
        stamp=str(row.get('time',''))
        if not re.fullmatch(r'\d{2,4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}',stamp):
            continue
        parsed=datetime.strptime(stamp,'%Y-%m-%d %H:%M:%S' if len(stamp)==19 else '%y-%m-%d %H:%M:%S').replace(tzinfo=SHANGHAI)
        if re.search(r'已解决|已恢复|已修复|现已正常|不是.*(?:密码|库存|市场)|没有.*(?:错误|问题)|无需|并非|resolved|not\s+(?:locked|banned)|no\s+(?:password|stock)\s+(?:issue|problem)',text,re.I):
            matches=[]
        else:
            matches=[key for key,pattern in PATTERNS.items() if re.search(pattern,text,re.I)]
        if len(matches)==1:
            clues.append({'category':matches[0],'logged_at':parsed.isoformat(),'status':'problem' if str(row.get('status','')).strip()=='问题单' else 'other'})
    clues.sort(key=lambda r:r['logged_at'],reverse=True)
    return {'category':clues[0]['category'] if clues else 'unclear', 'last_matching_log_at':clues[0]['logged_at'] if clues else None,
            'basis':'historical_keyword_clue_not_current_cause', 'requires_latest_state_review':True}


def choose_sample(rows, limit=12):
    if not 1<=limit<=12:raise ValueError('invalid_sample_limit')
    seen=set();groups=defaultdict(list)
    for row in rows:
        if row['id'] in seen:continue
        if not re.fullmatch(r'[0-9]{1,12}',row['id']) or row['platform'] not in ('PS','PC','XBOX','unknown'):
            raise ValueError('invalid_order_projection')
        seen.add(row['id']);groups[row['platform']].append(row)
    # Deterministic platform-balanced selection, highest amount first inside each platform.
    for batch in groups.values():batch.sort(key=lambda r:(-(r.get('amount_usd') or 0),r['id']))
    result=[]
    while len(result)<limit and any(groups.values()):
        for platform in ('PS','PC','XBOX','unknown'):
            if groups[platform] and len(result)<limit:result.append(groups[platform].pop(0))
    return result


def summarize(rows, samples, pages, errors, captured_at):
    categories=Counter(s['category'] for s in samples)
    return {'contract':'fc-order-problem-clues-v1','status':'partial' if errors else 'available',
            'captured_at':captured_at,'source':'Order FC27 / www.mmoexp.com / status=6',
            'sampled':len(samples),'listed':len({r['id'] for r in rows}),'pages':pages,
            'coverage':'只读取列表前几页，再按平台与金额选择样本；不代表总体比例',
            'categories':{k:categories[k] for k in CATEGORIES},
            'platform_counts':dict(Counter(s['platform'] for s in samples)),
            'errors':errors,'samples':samples,
            'note':'日志只作历史关键词线索，需人工复核最新状态；不含原文、账户、联系人或商户订单号。'}


def read_live(root, web, timeout=120):
    """One process on an existing lock; no new daemon, credentials, or model ledger."""
    import fcntl
    root=Path(root);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    cache=root/'order-problem-clues.json'
    if cache.is_file():
        try:
            value=json.loads(cache.read_text('utf-8'))
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(value['captured_at'])).total_seconds()
            ttl=900 if value.get('status') in ('available','partial') else 60
            if value.get('contract')=='fc-order-problem-clues-v1' and 0<=age<ttl:return value
        except (OSError,ValueError,KeyError):pass
    with (Path(web)/'collector.lock').open('a+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'not_sent','reason':'collector_busy'}
        reader=Path(__file__).with_name('fc_order_reader.py')
        try:
            proc=subprocess.run([sys.executable,'-B',str(reader)],
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
            if proc.returncode or len(proc.stdout)>48000:return {'status':'unavailable','reason':'reader_failed'}
            result=json.loads(proc.stdout)
            if result.get('contract')!='fc-order-problem-clues-v1':raise ValueError('contract')
            from fc_detail import atomic
            atomic(cache,result)
            cache.chmod(0o600)
            return result
        except subprocess.TimeoutExpired:return {'status':'unavailable','reason':'reader_timeout'}
        except (OSError,ValueError):return {'status':'unavailable','reason':'reader_failed'}
