"""Private, administrator-only customer tracking ledger; no outreach or pricing writes."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

CONTRACT = 'fs-customer-tracking-20261019-pool-v2'
SHANGHAI = timezone(timedelta(hours=8))
DEFAULT_CONFIG = {'profile':'FC27','site_id':266,'product_types':['Coins','Items'],
    'min_order_usd_exclusive':'500','max_discount_usd_exclusive':'25',
    'customer_flags':['new','old'],'enabled':True}
FLAGS = {'是':'new','否':'old','new':'new','old':'old'}
ID = re.compile(r'[a-f0-9]{32}')
ORDER = re.compile(r'[A-Za-z0-9_-]{1,80}')
EMAIL = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')
UTC = timezone.utc
FC_PRODUCT_LABELS = {'Coins':'货币(Gold)','Items':'物品(Items)'}


def scan_permission_denied(job):
    # Older failed rows used retry_after=60 for the same explicit pre-generation denial.
    return bool(job and job['state']=='failed' and job.get('reason')=='es_export_permission_denied')


def scan_job_sha256(job):
    return hashlib.sha256(json.dumps(job,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def payment_moment(value):
    if not isinstance(value,str):return None
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=SHANGHAI)
    except ValueError:return None


def lifecycle_clock(orders,coverage,now=None):
    now=now or datetime.now(UTC)
    paid=[row for row in orders if str(row.get('pay_status'))=='1']
    times=[payment_moment(row.get('paid_at')) for row in paid]
    valid=[t for t in times if t is not None and t<=now]
    verified=bool(valid) and (coverage or {}).get('complete') is True and len(valid)==len(times)
    first=min(valid) if verified else None
    day=(now.astimezone(SHANGHAI).date()-first.astimezone(SHANGHAI).date()).days+1 if first else None
    return {'first_paid_at':first.isoformat() if first else None,
        'first_paid_status':'verified' if first else 'unverified',
        'first_paid_scope':'Admin · MMOEXP站点266 · 该客户全部游戏已付款订单',
        'lifecycle_day':day,'phase':('30天及以后' if day>=30 else '14–29天' if day>=14 else '7–13天' if day>=7 else '1–6天') if day else '首付日期待核实',
        'stage_markers':[{'days':n,'reached':day>=n if day else None,'date':(first.astimezone(SHANGHAI).date()+timedelta(days=n-1)).isoformat() if first else None} for n in (7,14,30)],
        'clock_rule':'北京时间首次付款自然日为第1天；7/14/30天只作阶段标记，不自动生成单人报告。'}


def game_scope(profile):
    from admin_product_orders import GAME_IDS
    from es_order_structure import GAME_LABELS
    if profile not in GAME_IDS or profile not in GAME_LABELS:raise ValueError('profile_unavailable')
    return GAME_IDS[profile],GAME_LABELS[profile]


def money(value):
    try:
        number = Decimal(str(value).strip())
        if number.is_finite() and abs(number) < Decimal('1e15'):
            return number
    except (InvalidOperation, TypeError, ValueError):
        pass
    return None


def checked_config(value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULT_CONFIG):raise ValueError('config_fields')
    if value['profile']!='FC27':raise ValueError('phase_one_fc_only')
    game_scope(value['profile'])
    if value['site_id']!=266:
        raise ValueError('config_scope')
    if type(value['enabled']) is not bool:raise ValueError('config_enabled')
    kinds=value['product_types']
    if (not isinstance(kinds,list) or not 1<=len(kinds)<=12 or len(kinds)!=len(set(kinds)) or
        any(not isinstance(kind,str) or not 1<=len(kind)<=80 or re.search(r'[@<>\r\n]|https?://',kind) for kind in kinds)):
        raise ValueError('config_product_types')
    if value['profile']=='FC27' and set(kinds)-set(FC_PRODUCT_LABELS):
        raise ValueError('config_fc_product_types')
    flags=value['customer_flags']
    if not isinstance(flags,list) or not flags or len(flags)!=len(set(flags)) or set(flags)-{'new','old','unknown'}:
        raise ValueError('config_flags')
    lo=money(value['min_order_usd_exclusive']);hi=money(value['max_discount_usd_exclusive'])
    if lo is None or hi is None or lo<0 or hi<0 or lo>1000000 or hi>1000000:
        raise ValueError('config_threshold')
    return dict(value,min_order_usd_exclusive=str(lo),max_discount_usd_exclusive=str(hi))


def classify(row,config,apply_criteria=True):
    """Only exact approved ES labels; ambiguity stays out of a candidate list."""
    _,label=game_scope(config['profile'])
    game=str(row.get('游戏') or '').strip()
    product=str(row.get('产品类型') or '').strip()
    chosen={FC_PRODUCT_LABELS[k] for k in config['product_types']} if config['profile']=='FC27' else set(config['product_types'])
    if game!=label or product not in chosen:
        return None,'scope_or_product_unknown'
    amount=money(row.get('订单金额（美元）'))
    discount=money(row.get('折扣金额'))
    paid=money(row.get('实付金额'))
    currency=str(row.get('实付币种') or '').strip().upper()
    flag=FLAGS.get(str(row.get('是否新客户') or '').strip(),'unknown')
    order=str(row.get('订单号') or '').strip()
    if not ORDER.fullmatch(order) or discount is None or discount<0 or amount is not None and amount<0 or paid is not None and paid<0:
        return None,'order_or_money_missing'
    if apply_criteria and (not discount<Decimal(config['max_discount_usd_exclusive']) or flag not in config['customer_flags']):
        return None,'criteria_not_met'
    paid_at=str(row.get('付款时间') or '').strip()
    try:
        parsed=datetime.fromisoformat(paid_at.replace('/','-'))
        if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone(timedelta(hours=8)))
    except ValueError:return None,'paid_at_missing'
    return {'order_no':order,'paid_at':parsed.isoformat(),'es_order_usd':str(amount) if amount is not None else None,
        'payment':{'amount':str(paid) if paid is not None else None,'currency':currency or None},
        'discount_usd':str(discount),'customer_flag':flag,'product_type':product},None


def verified_identity(es,admin):
    """Exact source-order match. A UID of zero is fine only with a verified email."""
    if not isinstance(admin,dict) or admin.get('order_no')!=es['order_no']:
        return {'identity_status':'unavailable','identity_reason':'order_no_unmatched'}
    gid,_=game_scope(es['profile'])
    if str(admin.get('gid'))!=str(gid) or str(admin.get('site_id'))!='266' or str(admin.get('pay_status'))!='1':
        return {'identity_status':'unavailable','identity_reason':'admin_scope_mismatch'}
    email=admin.get('email')
    if not isinstance(email,str) or not EMAIL.fullmatch(email.strip()) or len(email)>254:
        return {'identity_status':'unavailable','identity_reason':'email_missing_or_invalid'}
    admin_usd=money(admin.get('amount'))
    uid=admin.get('uid')
    if str(uid).isdigit():uid=int(uid)
    else:uid=None
    return {'identity_status':'verified','email':email.strip(),'uid':uid,
            'site_id':266,'gid':gid,'pay_status':1,'selected_game':True,
            'admin_order_usd':str(admin_usd) if admin_usd is not None else None,
            'identity_source':'Admin exact order_no, gid, site_id, paid status and customer email'}


def candidate_rows(es_rows,admin_by_order,config):
    """Admin matching is injected by a private session adapter, never by the browser."""
    config=checked_config(config);items=[];coverage={'es_rows':0,'criteria_matches':0,
        'identity_verified':0,'identity_unavailable':0,'excluded':{},'conflicts':0}
    seen={};conflicted=set()
    for row in es_rows:
        coverage['es_rows']+=1
        item,reason=classify(row,config,False)
        if reason:
            number=str(row.get('订单号') or '').strip()
            if reason!='scope_or_product_unknown' and ORDER.fullmatch(number):conflicted.add(number)
            coverage['excluded'][reason]=coverage['excluded'].get(reason,0)+1
            continue
        number=item['order_no']
        item['profile']=config['profile']
        item['product_types']=[item['product_type']]
        old=seen.get(number)
        if old is not None:
            baseline={k:v for k,v in old.items() if k not in ('product_type','product_types')}
            current={k:v for k,v in item.items() if k not in ('product_type','product_types')}
            if baseline!=current:
                conflicted.add(number)
            elif item['product_type'] not in old['product_types']:
                old['product_types'].append(item['product_type'])
            continue
        seen[number]=item
    coverage['conflicts']=len(conflicted)
    for number,item in seen.items():
        if number in conflicted:
            coverage['excluded']['conflicting_order_rows']=coverage['excluded'].get('conflicting_order_rows',0)+1
            continue
        if not money(item['discount_usd'])<Decimal(config['max_discount_usd_exclusive']) or item['customer_flag'] not in config['customer_flags']:
            coverage['excluded']['criteria_not_met']=coverage['excluded'].get('criteria_not_met',0)+1
            continue
        identity=verified_identity(item,admin_by_order.get(item['order_no']))
        if identity.get('identity_reason') in ('order_no_unmatched','admin_scope_mismatch'):
            reason=identity['identity_reason']
            coverage['excluded'][reason]=coverage['excluded'].get(reason,0)+1
            continue
        item.update(identity)
        chosen_usd=money(identity.get('admin_order_usd'))
        amount_source='Admin'
        if chosen_usd is None:
            chosen_usd=money(item['es_order_usd']);amount_source='Admin_ES_export'
        if chosen_usd is None or chosen_usd<0:
            coverage['excluded']['order_usd_missing']=coverage['excluded'].get('order_usd_missing',0)+1
            continue
        item['order_usd']=str(chosen_usd);item['order_usd_source']=amount_source
        item['amount_conflict']=identity.get('admin_order_usd') is not None and item['es_order_usd'] is not None and money(identity['admin_order_usd'])!=money(item['es_order_usd'])
        if not chosen_usd>Decimal(config['min_order_usd_exclusive']):
            coverage['excluded']['criteria_not_met']=coverage['excluded'].get('criteria_not_met',0)+1
            continue
        coverage['criteria_matches']+=1
        coverage['identity_verified' if identity['identity_status']=='verified' else 'identity_unavailable']+=1
        items.append(item)
    return items,coverage


class Store:
    """PII never enters workspace_evidence or the shared report database."""
    def __init__(self,root):
        self.root=Path(root)
        if any(path.is_symlink() for path in (self.root,*self.root.parents)):raise ValueError('tracking_linked_root')
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        if os.name=='posix' and self.root.stat().st_mode&0o077:raise ValueError('tracking_root_permissions')
        self.path=self.root/'tracking.db'
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600);os.close(fd)
        if os.name=='posix' and self.path.stat().st_mode&0o077:raise ValueError('tracking_db_permissions')
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS config(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL,body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY,order_no TEXT NOT NULL UNIQUE,first_body TEXT NOT NULL,latest_body TEXT NOT NULL,updated_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS candidate_history(id TEXT NOT NULL,updated_at TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(id,updated_at));
              CREATE TABLE IF NOT EXISTS scans(day TEXT NOT NULL,config_version INTEGER NOT NULL,captured_at TEXT NOT NULL,coverage TEXT NOT NULL,PRIMARY KEY(day,config_version));
              CREATE TABLE IF NOT EXISTS scan_items(day TEXT NOT NULL,config_version INTEGER NOT NULL,candidate_id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(day,config_version,candidate_id));
              CREATE TABLE IF NOT EXISTS scan_jobs(day TEXT NOT NULL,config_version INTEGER NOT NULL,state TEXT NOT NULL,request_id TEXT NOT NULL,updated_at TEXT NOT NULL,reason TEXT,retry_after INTEGER,PRIMARY KEY(day,config_version));
              CREATE TABLE IF NOT EXISTS tracks(id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL UNIQUE,email TEXT NOT NULL UNIQUE,uid TEXT,tracked_at TEXT NOT NULL,status TEXT NOT NULL,owner TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS orders(track_id TEXT NOT NULL,order_no TEXT NOT NULL,body TEXT NOT NULL,observed_at TEXT NOT NULL,PRIMARY KEY(track_id,order_no));
              CREATE TABLE IF NOT EXISTS history_coverage(track_id TEXT PRIMARY KEY,body TEXT NOT NULL,observed_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS history_attempts(track_id TEXT PRIMARY KEY,last_attempt_at TEXT NOT NULL,state TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS milestones(track_id TEXT NOT NULL,days INTEGER NOT NULL,due_at TEXT NOT NULL,state TEXT NOT NULL,request_id TEXT NOT NULL UNIQUE,evidence_id TEXT,conversation_id TEXT,turn_id TEXT,artifact_id TEXT,prompt TEXT,PRIMARY KEY(track_id,days));
              CREATE TABLE IF NOT EXISTS requests(request_id TEXT PRIMARY KEY,action TEXT NOT NULL,fingerprint TEXT NOT NULL,result TEXT NOT NULL);''')
            db.execute('INSERT OR IGNORE INTO config VALUES(1,1,?)',(json.dumps(DEFAULT_CONFIG),))
            # Retire only unsubmitted legacy jobs; preserve completed/failed/unknown receipts.
            db.execute("UPDATE milestones SET state='cancelled' WHERE state='scheduled'")

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def config(self):
        with self.db() as db:
            row=db.execute('SELECT version,body FROM config WHERE id=1').fetchone()
            last=db.execute("SELECT request_id,result FROM requests WHERE action='save_config' ORDER BY rowid DESC LIMIT 1").fetchone()
        return dict(json.loads(row['body']),version=row['version'],enabled_profiles=['FC27'],
            last_request_id=last['request_id'] if last and json.loads(last['result']).get('version')==row['version'] else None)

    def save_config(self,value,expected_version,request_id):
        value=checked_config(value)
        if type(expected_version) is not int or not ID.fullmatch(request_id):raise ValueError('config_request')
        fingerprint=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
            if prior:
                if prior['action']!='save_config' or prior['fingerprint']!=fingerprint:raise ValueError('idempotency_conflict')
                return json.loads(prior['result'])
            row=db.execute('SELECT version FROM config WHERE id=1').fetchone()
            if row['version']!=expected_version:raise ValueError('config_version_conflict')
            result=dict(value,version=expected_version+1)
            db.execute('UPDATE config SET version=?,body=? WHERE id=1',(result['version'],json.dumps(value)))
            db.execute("UPDATE scan_jobs SET state='failed',reason='scan_config_changed',retry_after=NULL WHERE state='pending'")
            db.execute('INSERT INTO requests VALUES(?,?,?,?)',(request_id,'save_config',fingerprint,json.dumps(result)))
            return result

    def save_candidates(self,day,items,coverage=None,config_version=None):
        if date.fromisoformat(day).isoformat()!=day:raise ValueError('candidate_day')
        now=datetime.now(UTC).isoformat();saved=[]
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            active=db.execute('SELECT version FROM config WHERE id=1').fetchone()['version']
            if config_version is not None and config_version!=active:raise ValueError('scan_config_changed')
            db.execute('DELETE FROM scan_items WHERE day=? AND config_version=?',(day,active))
            for item in items:
                old=db.execute('SELECT id,latest_body FROM candidates WHERE order_no=?',(item['order_no'],)).fetchone()
                if old:
                    ident=old['id']
                    previous=json.loads(old['latest_body'])
                    if previous.get('email') and item.get('email') and previous['email']!=item['email']:
                        item=dict(item,identity_status='unavailable',identity_reason='customer_email_conflict')
                        item.pop('email',None)
                    if json.loads(old['latest_body'])!=item:
                        db.execute('INSERT INTO candidate_history VALUES(?,?,?)',(ident,now,old['latest_body']))
                        db.execute('UPDATE candidates SET latest_body=?,updated_at=? WHERE id=?',(json.dumps(item),now,ident))
                else:
                    ident=uuid.uuid4().hex
                    db.execute('INSERT INTO candidates VALUES(?,?,?,?,?)',(ident,item['order_no'],json.dumps(item),json.dumps(item),now))
                db.execute('INSERT INTO scan_items VALUES(?,?,?,?)',(day,active,ident,json.dumps(item)))
                saved.append(dict(item,candidate_id=ident))
            db.execute('INSERT OR REPLACE INTO scans VALUES(?,?,?,?)',(day,active,now,json.dumps(coverage or {})))
        return {'status':'available','date':day,'config_version':active,'captured_at':now,'items':saved,'coverage':coverage or {}}

    def candidates(self,day):
        if date.fromisoformat(day).isoformat()!=day:raise ValueError('candidate_day')
        with self.db() as db:
            version=db.execute('SELECT version FROM config WHERE id=1').fetchone()['version']
            rows=db.execute('SELECT candidate_id,body FROM scan_items WHERE day=? AND config_version=? ORDER BY candidate_id',(day,version)).fetchall()
            scan=db.execute('SELECT captured_at,coverage FROM scans WHERE day=? AND config_version=?',(day,version)).fetchone()
            job=db.execute('SELECT state,reason,retry_after FROM scan_jobs WHERE day=? AND config_version=?',(day,version)).fetchone()
        if job and job['state'] in ('pending','failed'):
            return {'status':job['state'],'date':day,'config_version':version,'items':[],
                'captured_at':None,'coverage':{},'reason':job['reason'],
                'retry_after':None if scan_permission_denied(dict(job)) else job['retry_after'],
                **({'retryable':False} if scan_permission_denied(dict(job)) else {})}
        return {'status':'available' if scan else 'unavailable','date':day,
            'config_version':version,'items':[dict(json.loads(row['body']),candidate_id=row['candidate_id']) for row in rows],
            'captured_at':scan['captured_at'] if scan else None,
            'coverage':json.loads(scan['coverage']) if scan else {},
            **({} if scan else {'reason':'daily_scan_not_available'})}

    def begin_scan(self,day,request_id):
        if date.fromisoformat(day).isoformat()!=day or not ID.fullmatch(request_id):raise ValueError('scan_request')
        now=datetime.now(UTC).isoformat()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
            if prior:
                if prior['action']!='scan' or prior['fingerprint']!=day:raise ValueError('idempotency_conflict')
                return json.loads(prior['result'])
            version=db.execute('SELECT version FROM config WHERE id=1').fetchone()['version']
            job=db.execute('SELECT * FROM scan_jobs WHERE day=? AND config_version=?',(day,version)).fetchone()
            if job and job['state']=='pending':
                result={'status':'pending','date':day,'config_version':version,'request_id':request_id,'reused':True}
            else:
                db.execute('INSERT OR REPLACE INTO scan_jobs VALUES(?,?,?,?,?,?,?)',(day,version,'pending',request_id,now,None,5))
                result={'status':'pending','date':day,'config_version':version,'request_id':request_id,'reused':False}
            db.execute('INSERT INTO requests VALUES(?,?,?,?)',(request_id,'scan',day,json.dumps(result)))
            return result

    def scan_job(self,day):
        with self.db() as db:
            version=db.execute('SELECT version FROM config WHERE id=1').fetchone()['version']
            row=db.execute('SELECT * FROM scan_jobs WHERE day=? AND config_version=?',(day,version)).fetchone()
        return dict(row) if row else None

    def pending_scans(self,limit=8):
        if type(limit) is not int or not 1<=limit<=32:raise ValueError('scan_limit')
        with self.db() as db:
            version=db.execute('SELECT version FROM config WHERE id=1').fetchone()['version']
            rows=db.execute("SELECT day FROM scan_jobs WHERE config_version=? AND state='pending' ORDER BY updated_at LIMIT ?",(version,limit)).fetchall()
        return [row['day'] for row in rows]

    def finish_scan(self,day,version,result):
        if result.get('status')=='available':
            with self.db() as db:
                current=db.execute('SELECT version FROM config WHERE id=1').fetchone()['version']
            if current!=version:raise ValueError('scan_config_changed')
            coverage=dict(result.get('coverage') or {},source_captured_at=result.get('captured_at'),
                source_version=result.get('source_version'))
            self.save_candidates(day,result['items'],coverage,version)
            state,reason,retry='available',None,None
        elif result.get('status')=='pending':return
        else:
            state,reason,retry='failed',str(result.get('reason') or 'scan_source_unavailable')[:80],60
            if reason=='es_export_permission_denied':retry=None
        with self.db() as db:
            db.execute('UPDATE scan_jobs SET state=?,updated_at=?,reason=?,retry_after=? WHERE day=? AND config_version=?',
                (state,datetime.now(UTC).isoformat(),reason,retry,day,version))

    def permission_scan(self,day,version,request_id,expected_sha,es_receipt_sha,db=None):
        if (date.fromisoformat(day).isoformat()!=day or type(version) is not int or not ID.fullmatch(request_id)
                or not all(isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) for v in (expected_sha,es_receipt_sha))):
            raise ValueError('scan_recovery_request')
        if db is None:
            with self.db() as conn:return self.permission_scan(day,version,request_id,expected_sha,es_receipt_sha,conn)
        if db.execute('SELECT version FROM config WHERE id=1').fetchone()['version']!=version:raise ValueError('scan_config_changed')
        row=db.execute('SELECT * FROM scan_jobs WHERE day=? AND config_version=?',(day,version)).fetchone()
        request=db.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
        if row is None or row['request_id']!=request_id or request is None or request['action']!='scan' or request['fingerprint']!=day:
            raise ValueError('scan_recovery_original_request')
        job=dict(row);receipt=json.loads(request['result']);previous=receipt.get('permission_recovery')
        if previous:
            if (previous['expected_job_sha256']!=expected_sha or previous['es_receipt_sha256']!=es_receipt_sha
                    or job['state'] not in ('pending','available')):raise ValueError('scan_recovery_already_observed')
            return job,True
        if not scan_permission_denied(job):raise ValueError('scan_recovery_not_permission_denied')
        if scan_job_sha256(job)!=expected_sha:raise ValueError('scan_recovery_job_changed')
        if receipt.get('config_version')!=version:raise ValueError('scan_recovery_original_config')
        return job,False

    def resume_permission_scan(self,day,version,request_id,expected_sha,proof,user):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            job,reused=self.permission_scan(day,version,request_id,expected_sha,proof['receipt_sha256'],db)
            if reused:return dict(job,reused=True)
            row=db.execute('SELECT result FROM requests WHERE request_id=?',(request_id,)).fetchone()
            receipt=json.loads(row['result'])
            receipt['permission_recovery']=dict(expected_job_sha256=expected_sha,es_receipt_sha256=proof['receipt_sha256'],
                prior_failure=job,proof=proof,actor=user,resumed_at=datetime.now(UTC).isoformat())
            db.execute('UPDATE requests SET result=? WHERE request_id=?',(json.dumps(receipt),request_id))
            db.execute("UPDATE scan_jobs SET state='pending',updated_at=?,reason=NULL,retry_after=5 WHERE day=? AND config_version=?",
                (datetime.now(UTC).isoformat(),day,version))
        return dict(job,state='pending',reason=None,retry_after=5,reused=False)

    def track(self,candidate_id,request_id,now=None,owner='admin'):
        if not ID.fullmatch(candidate_id) or not ID.fullmatch(request_id):raise ValueError('tracking_request')
        if not isinstance(owner,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',owner):raise ValueError('tracking_owner')
        now=now or datetime.now(UTC)
        if now.tzinfo is None:raise ValueError('tracking_clock')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
            if prior:
                if prior['action']!='track' or prior['fingerprint']!=candidate_id:raise ValueError('idempotency_conflict')
                return dict(json.loads(prior['result']),reused=True)
            row=db.execute('SELECT latest_body FROM candidates WHERE id=?',(candidate_id,)).fetchone()
            if row is None:raise LookupError('candidate_not_found')
            version=db.execute('SELECT version FROM config WHERE id=1').fetchone()['version']
            linked=db.execute('SELECT 1 FROM scan_items WHERE candidate_id=? AND config_version=?',(candidate_id,version)).fetchone()
            if linked is None:raise ValueError('candidate_config_stale')
            item=json.loads(row['latest_body'])
            if item.get('identity_status')!='verified' or not item.get('email'):raise ValueError('candidate_identity_unavailable')
            current=db.execute('SELECT id,tracked_at,status FROM tracks WHERE candidate_id=? OR email=?',(candidate_id,item['email'])).fetchone()
            ident=current['id'] if current else uuid.uuid4().hex
            if current is None:
                db.execute('INSERT INTO tracks VALUES(?,?,?,?,?,?,?)',(ident,candidate_id,item['email'],str(item.get('uid')) if item.get('uid') is not None else None,now.isoformat(),'active',owner))
                db.execute('INSERT OR IGNORE INTO orders VALUES(?,?,?,?)',(ident,item['order_no'],json.dumps(item),now.isoformat()))
            start=datetime.fromisoformat(current['tracked_at']) if current else now
            result={'status':current['status'] if current else 'active','tracking_id':ident,'tracked_at':start.isoformat(),
                'candidate_id':candidate_id,'reused':current is not None,
                'milestones':[],'report_policy':'manual_pool_only'}
            db.execute('INSERT INTO requests VALUES(?,?,?,?)',(request_id,'track',candidate_id,json.dumps(result)))
            return result

    def observe(self,tracking_id,admin_orders,observed_at=None,coverage=None):
        if not ID.fullmatch(tracking_id):raise ValueError('tracking_id')
        observed_at=observed_at or datetime.now(UTC).isoformat()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            track=db.execute('SELECT * FROM tracks WHERE id=?',(tracking_id,)).fetchone()
            if track is None:raise LookupError('tracking_not_found')
            if track['status']!='active':return {'status':'stopped','tracking_id':tracking_id}
            count=0
            for item in admin_orders:
                if (item.get('email')!=track['email'] or str(item.get('site_id'))!='266' or
                    not ORDER.fullmatch(str(item.get('order_no') or ''))):
                    continue
                amount=money(item.get('order_usd'))
                projection={'order_no':item['order_no'],'email':track['email'],
                    'uid':int(item['uid']) if str(item.get('uid')).isdigit() else None,
                    'gid':int(item['gid']) if str(item.get('gid')).isdigit() else None,
                    'site_id':266,'paid_at':item.get('paid_at') if isinstance(item.get('paid_at'),str) else None,
                    'pay_status':int(item['pay_status']) if str(item.get('pay_status')).isdigit() else None,
                    'current_status':str(item.get('current_status') or 'unknown')[:80],
                    'order_usd':str(amount) if amount is not None and amount>=0 else None,
                    'order_usd_source':'Admin' if amount is not None and amount>=0 else None,
                    'selected_game':str(item.get('gid'))=='1327',
                    'discount_usd':None,'payment':{'amount':None,'currency':None}}
                previous=db.execute('SELECT body FROM orders WHERE track_id=? AND order_no=?',(tracking_id,item['order_no'])).fetchone()
                if previous:
                    original=json.loads(previous['body'])
                    for field in ('discount_usd','payment','product_type','product_types','customer_flag','es_order_usd'):
                        if field in original and original[field] is not None:
                            projection[field]=original[field]
                if previous and json.loads(previous['body'])!=projection:
                    # Current order status may change; retain latest observed state with timestamp.
                    db.execute('UPDATE orders SET body=?,observed_at=? WHERE track_id=? AND order_no=?',(json.dumps(projection),observed_at,tracking_id,item['order_no']))
                elif previous is None:
                    db.execute('INSERT INTO orders VALUES(?,?,?,?)',(tracking_id,item['order_no'],json.dumps(projection),observed_at))
                count+=1
            if coverage is not None:
                db.execute('INSERT OR REPLACE INTO history_coverage VALUES(?,?,?)',
                    (tracking_id,json.dumps(coverage),observed_at))
            return {'status':'available','tracking_id':tracking_id,'matched_source_orders':count,'observed_at':observed_at}

    def note_history_attempt(self,tracking_id,state):
        if not ID.fullmatch(tracking_id) or state not in ('available','partial','pending','unavailable'):
            raise ValueError('history_attempt')
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO history_attempts VALUES(?,?,?)',
                (tracking_id,datetime.now(UTC).isoformat(),state))

    def due_histories(self,limit=32,now=None):
        now=now or datetime.now(UTC)
        if type(limit) is not int or not 1<=limit<=32:raise ValueError('history_limit')
        observed_before=datetime.combine(now.astimezone(SHANGHAI).date(),datetime.min.time(),tzinfo=SHANGHAI).astimezone(UTC).isoformat()
        attempt_before=(now-timedelta(minutes=5)).isoformat()
        with self.db() as db:
            rows=db.execute('''SELECT t.id FROM tracks t
                LEFT JOIN history_coverage h ON h.track_id=t.id
                LEFT JOIN history_attempts a ON a.track_id=t.id
                WHERE t.status='active' AND (h.observed_at IS NULL OR h.observed_at<?)
                    AND (a.last_attempt_at IS NULL OR a.last_attempt_at<?)
                ORDER BY COALESCE(a.last_attempt_at,''),t.tracked_at LIMIT ?''',
                (observed_before,attempt_before,limit)).fetchall()
        return [row['id'] for row in rows]

    def detail(self,tracking_id):
        if not ID.fullmatch(tracking_id):raise ValueError('tracking_id')
        with self.db() as db:
            row=db.execute('SELECT * FROM tracks WHERE id=?',(tracking_id,)).fetchone()
            if row is None:raise LookupError('tracking_not_found')
            orders=db.execute('SELECT body,observed_at FROM orders WHERE track_id=? ORDER BY observed_at',(tracking_id,)).fetchall()
            milestones=db.execute('SELECT days,due_at,state,evidence_id,conversation_id,turn_id,artifact_id FROM milestones WHERE track_id=? ORDER BY days',(tracking_id,)).fetchall()
            history=db.execute('SELECT body,observed_at FROM history_coverage WHERE track_id=?',(tracking_id,)).fetchone()
        order_rows=[dict(json.loads(item['body']),observed_at=item['observed_at']) for item in orders]
        history_body=json.loads(history['body']) if history else None
        return dict(lifecycle_clock(order_rows,history_body),**{'status':row['status'],'tracking_id':tracking_id,'email':row['email'],
            'uid':int(row['uid']) if row['uid'] is not None else None,'tracked_at':row['tracked_at'],'owner':row['owner'],
            'orders':order_rows,
            'milestones':[dict(item) for item in milestones],
            'history_coverage':json.loads(history['body']) if history else None,
            'history_observed_at':history['observed_at'] if history else None,'report_policy':'manual_pool_only'})

    def due_reports(self,now=None):
        # Legacy automatic per-customer reports are retired, including day zero.
        return []

    def stop(self,tracking_id,request_id,owner):
        if not ID.fullmatch(tracking_id) or not ID.fullmatch(request_id):raise ValueError('tracking_request')
        fingerprint=tracking_id+':'+owner
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
            if prior:
                if prior['action']!='stop' or prior['fingerprint']!=fingerprint:raise ValueError('idempotency_conflict')
                return dict(json.loads(prior['result']),reused=True)
            row=db.execute('SELECT id FROM tracks WHERE id=?',(tracking_id,)).fetchone()
            if row is None:raise LookupError('tracking_not_found')
            db.execute("UPDATE tracks SET status='paused' WHERE id=?",(tracking_id,))
            db.execute("UPDATE milestones SET state='cancelled' WHERE track_id=? AND state='scheduled'",(tracking_id,))
            result={'state':'stopped','tracking_id':tracking_id,'status':'paused','request_id':request_id}
            db.execute('INSERT INTO requests VALUES(?,?,?,?)',(request_id,'stop',fingerprint,json.dumps(result)))
            return result

    def claim_report(self,tracking_id,days):
        raise ValueError('individual_automatic_reports_retired')

    def bind_report(self,tracking_id,days,expected_state,**fields):
        allowed={'state','conversation_id','turn_id','artifact_id','evidence_id','prompt'}
        if not ID.fullmatch(tracking_id) or days not in (0,7,14,30) or not fields or set(fields)-allowed:
            raise ValueError('report_binding')
        if 'prompt' in fields and (not isinstance(fields['prompt'],str) or len(fields['prompt'])>16000 or re.search(r'[\w.+-]+@[\w.-]+',fields['prompt'])):
            raise ValueError('report_prompt_private_data')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM milestones WHERE track_id=? AND days=?',(tracking_id,days)).fetchone()
            if row is None:raise LookupError('report_node_not_found')
            if row['state']!=expected_state:raise ValueError('report_state_changed')
            clause=','.join(key+'=?' for key in fields)
            db.execute(f'UPDATE milestones SET {clause} WHERE track_id=? AND days=?',(*fields.values(),tracking_id,days))

    def listed(self):
        with self.db() as db:
            rows=db.execute('SELECT id,candidate_id,email,uid,tracked_at,status FROM tracks ORDER BY tracked_at DESC').fetchall()
        clocks={row['id']:self.detail(row['id']) for row in rows}
        return {'status':'available','report_policy':'manual_pool_only','items':[dict({k:clocks[row['id']][k] for k in ('first_paid_at','first_paid_status','lifecycle_day','phase','stage_markers','history_observed_at')},tracking_id=row['id'],candidate_id=row['candidate_id'],email=row['email'],uid=int(row['uid']) if row['uid'] is not None else None,
            tracked_at=row['tracked_at'],status=row['status']) for row in rows]}

    def request(self,request_id):
        if not ID.fullmatch(request_id):raise ValueError('request_id')
        with self.db() as db:row=db.execute('SELECT action,result FROM requests WHERE request_id=?',(request_id,)).fetchone()
        return {'status':'available','action':row['action'],'result':json.loads(row['result'])} if row else {'status':'unknown','reason':'request_receipt_not_found'}


class AdminService:
    def __init__(self,store,authorizer):self.store,self.authorizer=store,authorizer
    def _admin(self,user):
        if not user:raise PermissionError('login_required')
        if not self.authorizer(user):raise PermissionError('admin_required')
    def get(self,user,view,**params):
        self._admin(user)
        if view=='config' and not params:return self.store.config()
        if view=='candidates' and set(params)=={'date'}:return self.store.candidates(params['date'])
        if view=='tracked' and not params:return self.store.listed()
        if view=='detail' and set(params)=={'id'}:return self.store.detail(params['id'])
        if view=='request' and set(params)=={'id'}:return self.store.request(params['id'])
        raise ValueError('tracking_view')
    def post(self,user,body):
        self._admin(user)
        if not isinstance(body,dict) or body.get('kind')!='hermes_customer_tracking':raise ValueError('tracking_kind')
        if body.get('action')=='track' and set(body)=={'kind','action','candidate_id','request_id'}:
            return self.store.track(body['candidate_id'],body['request_id'],owner=user)
        if body.get('action')=='stop' and set(body)=={'kind','action','tracking_id','request_id'}:
            return self.store.stop(body['tracking_id'],body['request_id'],user)
        if body.get('action')=='save_config' and set(body)=={'kind','action','config','expected_version','request_id'}:
            return self.store.save_config(body['config'],body['expected_version'],body['request_id'])
        raise ValueError('tracking_action')
