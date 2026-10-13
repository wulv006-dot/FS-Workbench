"""Private, provenance-bearing operational memory; never model weights or shared chat history."""
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
import hashlib
import json
import re
import sqlite3

SENSITIVE = re.compile(r'sk-[A-Za-z0-9]|Bearer\s|password\s*[:=]|密码\s*[:：=]|Cookie\s*[:=]|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://|\b\d{10,}\b', re.I)


def clean(value, limit=600):
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= limit or SENSITIVE.search(value) or any(ord(c)<32 and c not in '\n\t' for c in value):
        raise ValueError('invalid_or_sensitive_memory')
    return value.strip()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Memory:
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root/'operating-memory.sqlite3'
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS context (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL,
                project TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
                effective_start TEXT NOT NULL, effective_end TEXT, created_at TEXT NOT NULL,
                revoked_at TEXT, UNIQUE(owner,request_id));
                CREATE TABLE IF NOT EXISTS observations (
                owner TEXT NOT NULL, report_id TEXT NOT NULL, project TEXT NOT NULL,
                start TEXT NOT NULL, end TEXT NOT NULL, created_at TEXT NOT NULL,
                content TEXT NOT NULL, PRIMARY KEY(owner,report_id));''')
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(str(self.path), timeout=5); db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally:
            db.close()

    def add_context(self, owner, body, at):
        if not owner or set(body) != {'request_id','project','kind','text','effective_start','effective_end'}:
            raise ValueError('invalid_memory_request')
        if body['project'] != 'FC27' or body['kind'] not in ('target','strategy','constraint','business_fact'):
            raise ValueError('invalid_memory_kind')
        if not isinstance(body['request_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', body['request_id']):
            raise ValueError('invalid_request_id')
        text = clean(body['text'])
        start = date.fromisoformat(body['effective_start'])
        end = date.fromisoformat(body['effective_end']) if body['effective_end'] else None
        if start.isoformat()!=body['effective_start'] or end and (end<start or end.isoformat()!=body['effective_end']):
            raise ValueError('invalid_memory_dates')
        payload = dict(body, text=text)
        key = hashlib.sha256((owner+'\0'+body['request_id']).encode()).hexdigest()[:24]
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM context WHERE owner=? AND request_id=?',(owner,body['request_id'])).fetchone()
            if old:
                if any(old[k]!=payload[k] for k in payload):
                    raise ValueError('request_id_conflict')
                return dict(old, provenance='user_asserted', verified_by_source=False)
            if db.execute('SELECT COUNT(*) FROM context WHERE owner=? AND revoked_at IS NULL',(owner,)).fetchone()[0] >= 60:
                raise ValueError('memory_limit')
            db.execute('INSERT INTO context VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                       (key,owner,body['request_id'],'FC27',body['kind'],text,body['effective_start'],body['effective_end'],at.isoformat()))
        return {'id':key,'provenance':'user_asserted','verified_by_source':False,**payload,'created_at':at.isoformat()}

    def revoke(self, owner, key, at):
        with self.db() as db:
            row = db.execute('SELECT id FROM context WHERE id=? AND owner=?',(key,owner)).fetchone()
            if not row:
                return False
            # Revoke and erase text, preserving only the idempotency tombstone.
            db.execute("UPDATE context SET text='',revoked_at=COALESCE(revoked_at,?) WHERE id=? AND owner=?",(at.isoformat(),key,owner))
        return True

    def contexts(self, owner, project='FC27', period=None):
        with self.db() as db:
            rows = db.execute('SELECT * FROM context WHERE owner=? AND project=? AND revoked_at IS NULL ORDER BY created_at DESC LIMIT 60',(owner,project)).fetchall()
        out = []
        for row in rows:
            if period and (row['effective_start']>period['end'] or row['effective_end'] and row['effective_end']<period['start']):
                continue
            out.append({k:row[k] for k in ('id','project','kind','text','effective_start','effective_end','created_at')})
            out[-1].update(provenance='user_asserted', verified_by_source=False)
        return out

    def remember(self, owner, report_id, evidence, analysis, at):
        if not owner or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',report_id):
            raise ValueError('invalid_observation_owner')
        target = next((w for w in evidence['windows'] if w['key']=='target' and w['status']=='available'),None)
        if not target or not target['complete_days']:
            return False
        refs = {e['ref'] for e in evidence['evidence']}
        # Only validated enums and fact refs persist; AI prose is never promoted to a business fact.
        reviews = []
        for item in analysis.get('findings',[])[:5]:
            verify = item.get('verify',{})
            if verify.get('metric') not in ('orders','revenue_usd','average_order_usd','backlog_issues','backlog_over72h'):
                continue
            if verify.get('direction') not in ('increase','decrease','review') or type(verify.get('window_days')) is not int or not 1<=verify['window_days']<=30:
                continue
            reviews.append({'provenance':'unconfirmed_suggestion','verify':verify,
                            'refs':[r for r in item.get('refs',[]) if r in refs], 'implementation_confirmed':False})
        backlog = evidence.get('backlog')
        payload = {'provenance':'source_observation','snapshot_id':evidence['snapshot_id'],
                   'scope_fingerprint':evidence['scope_fingerprint'],'main':target['main'],
                   'backlog':{'issues':backlog['main']['issues'],
                              'over72h':backlog['age_bands']['72to168h']+backlog['age_bands']['over168h'],
                              'captured_at':backlog['as_of']} if backlog else None,
                   'reviews':reviews}
        text = encode(payload)
        with self.db() as db:
            old = db.execute('SELECT content FROM observations WHERE owner=? AND report_id=?',(owner,report_id)).fetchone()
            if old:
                if old[0]!=text:
                    raise ValueError('observation_immutable')
                return False
            db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?)',(owner,report_id,'FC27',target['start'],target['end'],at.isoformat(),text))
        return True

    def recall(self, owner, evidence, limit=5):
        if type(limit) is not int or not 1<=limit<=10:
            raise ValueError('invalid_memory_limit')
        p = evidence['plan']; results=[]
        with self.db() as db:
            rows = db.execute('SELECT * FROM observations WHERE owner=? AND project=? AND end<? ORDER BY end DESC,created_at DESC LIMIT 50',(owner,'FC27',p['start'])).fetchall()
        seen=set()
        for row in rows:
            content=json.loads(row['content'])
            if content['scope_fingerprint']!=evidence['scope_fingerprint'] or (row['start'],row['end']) in seen:
                continue
            seen.add((row['start'],row['end']))
            results.append({'report_id':row['report_id'],'start':row['start'],'end':row['end'],'created_at':row['created_at'],**content})
            if len(results)>=limit:break
        return {'contexts':self.contexts(owner,period=p)[:10], 'observations':results,
                'rule':'用户输入是带生效期的背景，尚非源数据核验事实；过往建议未经执行确认，变化不证明建议效果。'}

    def forget_observations(self, owner):
        with self.db() as db:
            count=db.execute('DELETE FROM observations WHERE owner=?',(owner,)).rowcount
        return count
