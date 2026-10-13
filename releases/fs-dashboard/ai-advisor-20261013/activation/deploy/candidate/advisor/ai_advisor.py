"""Private report workspace over the existing catalog and bounded summary readers.

No new collectors, credentials, business-write tools or web search. Models explain;
native period metrics and deterministic rules remain the evidence.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
from fc_daily import now, encoded, digest, admin, model_daily_limit
from ai_advisor_model import clean_question, projection, explain, explain_boss
from boss_insights import project_context

CONTRACT = 'fs-ai-advisor-v1'
METRICS = ('orders','revenueUsd','averageOrderUsd','newCustomers','repeatRatePct','fulfillmentRatePct','profitMarginPct')
MAIN='MMOEXP主站'
ADMIN_REF='Admin原统计范围（含其他站点）'
ORDER_REF='Order全站参考；RPG沿用已完成状态'


def period(spec, at):
    kind=spec.get('kind'); today=at.date()
    if kind in ('last7','last30'):
        hi=today-timedelta(days=1);lo=today-timedelta(days=7 if kind=='last7' else 30)
    elif kind=='custom':lo=date.fromisoformat(spec['start']);hi=date.fromisoformat(spec['end'])
    else:
        anchor=date.fromisoformat(spec.get('anchor',''))
        if anchor>today:raise ValueError('future_date')
        if kind=='day':lo=hi=anchor
        elif kind=='week':lo=anchor-timedelta(days=anchor.weekday());hi=lo+timedelta(days=6)
        elif kind=='month':
            lo=anchor.replace(day=1);hi=(lo.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
        elif kind=='quarter':
            month=(anchor.month-1)//3*3+1;lo=date(anchor.year,month,1)
            hi=(date(anchor.year+1,1,1) if month==10 else date(anchor.year,month+3,1))-timedelta(days=1)
        else:raise ValueError('invalid_period_kind')
        hi=min(hi,today)
    if hi>today or lo>hi or (hi-lo).days>365 or lo<today-timedelta(days=365):raise ValueError('invalid_period')
    return {'kind':kind,'start':lo.isoformat(),'end':hi.isoformat(),
            'end_exclusive':(hi+timedelta(days=1)).isoformat(),'in_progress':hi==today,'timezone':'Asia/Shanghai'}


def selection(spec,catalog,at):
    if not isinstance(spec,dict) or set(spec)-{'scope','project','kind','anchor','start','end'}:raise ValueError('invalid_selection')
    selected=period(spec,at);scope=spec.get('scope')
    groups={g['key']:g['profiles'] for g in catalog['dashboard']['groups']}
    if scope=='project':keys=[spec.get('project')]
    elif scope=='global':keys=['MMOEXP']
    elif scope in ('sports','rpg','general'):keys=groups.get(scope,[])
    else:raise ValueError('invalid_scope')
    if not keys or any(k not in catalog['profiles'] for k in keys):raise ValueError('unknown_project')
    return dict(scope=scope,projects=keys,period=selected,catalog_id=catalog['catalogId'])


def numeric(v):return type(v) in (int,float) and math.isfinite(v)


def project_facts(key,name,raw,requested):
    if raw.get('scopeContractId')!='admin-main-order-labelled-supplement-v1' or raw.get('currency')!='USD' or raw.get('profile',{}).get('key')!=key:
        raise ValueError('source_contract_mismatch')
    q=raw.get('query',{})
    if any(q.get(k)!=requested[k] for k in ('start','end')):raise ValueError('source_period_mismatch')
    profile=raw['profile'];a=profile.get('supplement') or {};o=profile.get('primary') or {}
    expected_start=requested['start']+' 00:00';expected_end=requested['end_exclusive']+' 00:00'
    actual=profile.get('period',{})
    if actual.get('start')!=expected_start or not actual.get('end'):raise ValueError('source_period_mismatch')
    if not requested['in_progress'] and actual['end']!=expected_end:raise ValueError('source_period_mismatch')
    if requested['in_progress'] and not expected_start<actual['end']<=expected_end:raise ValueError('source_period_mismatch')
    # Admin's deployed aggregate schema labels USD at the envelope/metric level.
    # An explicit contradictory source currency must still fail closed.
    def available(source):return source.get('status')=='available' and source.get('period')==actual and source.get('currency',raw['currency'])=='USD'
    metrics={}
    for field in METRICS:
        metrics[field]={'value':None,'source':'Admin','scope':ADMIN_REF,'status':'not_provided','captured_at':a.get('capturedAt')}
        native=(a.get('metrics') or {}).get(field,{})
        if available(a) and native.get('status')=='available' and numeric(native.get('value')):
            metrics[field].update(value=native['value'],status='available')
    rows=(a.get('dimensions') or {}).get('channels') or []
    mains=[r for r in rows if (r.get('code') or r.get('name'))=='www.mmoexp.com'] if available(a) else []
    for field in ('orders','revenueUsd'):
        value=mains[0].get(field) if len(mains)==1 else None
        if available(a) and not rows and all((a.get('metrics') or {}).get(k,{}).get('value')==0 for k in ('orders','revenueUsd')):value=0
        if not numeric(value) or field=='orders' and (value<0 or int(value)!=value):value=None
        metrics[field].update(value=value,source='Admin',scope=MAIN,status='available' if value is not None else 'not_provided')
    for field in ('averageOrderUsd','fulfillmentRatePct','profitMarginPct'):
        if metrics[field]['value'] is not None:continue
        native=(o.get('metrics') or {}).get(field,{})
        value=native.get('value') if available(o) and not o.get('stale') and native.get('status')=='available' else None
        metrics[field]={'value':value if numeric(value) else None,'source':'Order','scope':ORDER_REF,
                        'captured_at':o.get('capturedAt'),'status':'available' if numeric(value) else 'not_provided'}
    for field,item in metrics.items():
        item['unit']='USD' if field.endswith('Usd') else '%' if field.endswith('Pct') else 'count'
        if item['value'] is not None and field.endswith('Usd'):item['value']=float(Decimal(str(item['value'])).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    complete=not raw.get('stale') and all(metrics[k]['value'] is not None for k in ('orders','revenueUsd'))
    warnings=[]
    if not complete:warnings.append('主站核心值缺项或缓存过期，不能当完整项目经营结果。')
    if not available(o) or o.get('stale'):warnings.append('Order参考指标暂缺或未完成读取。')
    return {'key':key,'name':name,'status':'available' if complete else 'partial','metrics':metrics,
            'period':actual,'captured_at':raw.get('generatedAt'),'range_id':raw.get('rangeId'),
            'source_watermark':'unknown','warnings':warnings}


def report_from(selection_value,projects,at):
    available=[p for p in projects if p['status']=='available']
    totals={k:None for k in ('orders','revenueUsd')}
    # Only additive, same-site complete facts; never sum a global profile with games,
    # and never sum period unique people or rates across dates/projects.
    if len(available)==len(projects) and not selection_value['period']['in_progress']:
        for k in totals:totals[k]=sum(Decimal(str(p['metrics'][k]['value'])) for p in projects)
        totals={'orders':int(totals['orders']),'revenueUsd':float(totals['revenueUsd'].quantize(Decimal('.01')))}
    warnings=['主站订单/金额来自Admin；其他指标逐项标注原来源与范围，不拼成同口径利润或跨项目去重人数。',
              '订单数量与订单金额为后台区间统计原值；FC自动日报按支付明细统计，不直接比较不同扣除或退款范围的金额。',
              '目录给出可查询区间，不保证上游历史覆盖；源数据水位未提供，显示实际读取时间。',
              '独立分销可靠业务归属仍缺，未声明已完整剔除；本期不读原始客户资料或订单备注。',
              '未接联网搜索，游戏热点与外部活动节点尚不提供；本模块没有改价、派单、退款或订单写权限。']
    if selection_value['period']['in_progress']:warnings.append('区间含今天，当前进行中；各项目截止时刻分别标注，不把当日当完整日。')
    return {'contractId':CONTRACT,'selection':selection_value,'period':selection_value['period'],
            'generated_at':at.isoformat(),'currency':'USD','projects':projects,'totals':totals,
            'coverage':{'available':len(available),'requested':len(projects),'missing':[p['key'] for p in projects if p['status']!='available']},
            'status':'ready' if len(available)==len(projects) else 'partial','warnings':warnings,
            'findings':['先核对缺项项目与来源覆盖，再比较同口径项目结构。' if len(available)<len(projects) else '本期核心金额和订单可用；人数与比率保留各项目原生区间值。'],
            'ai':{'status':'not_run'}}


class Advisor:
    def __init__(self,catalog,read_range,daily,root,clock=now,wait=time.sleep,authorizer=admin,model=explain):
        self.catalog,self.read_range,self.daily=catalog,read_range,daily
        self.root=Path(root);self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.path=self.root/'advisor.sqlite3';self.clock,self.wait=clock,wait
        self.authorizer,self.model=authorizer,model;self.lock=threading.Lock()
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,request_id TEXT NOT NULL,kind TEXT NOT NULL,
                params TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL,finished_at TEXT,error TEXT,
                progress TEXT,result TEXT,UNIQUE(owner,request_id));''')
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db=sqlite3.connect(str(self.path),timeout=5);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def get_job(self,owner,jobid):
        with self.db() as db:row=db.execute('SELECT * FROM jobs WHERE owner=? AND id=?',(owner,jobid)).fetchone()
        if not row:return None
        item=dict(row)
        for k in ('params','progress','result'):item[k]=json.loads(item[k]) if item[k] else None
        return item

    def get(self,params,user):
        if not user:return 401,{'error':'login_required'}
        if set(params)-{'id'} or any(len(v)!=1 for v in params.values()):return 422,{'error':'invalid_parameters'}
        if 'id' in params:
            item=self.get_job(user,params['id'][0]);return (200,{'job':item}) if item else (404,{'error':'not_found'})
        catalog=self.catalog()
        with self.db() as db:
            rows=db.execute('SELECT id,kind,state,created_at,finished_at,error,params FROM jobs WHERE owner=? ORDER BY created_at DESC LIMIT 60',(user,)).fetchall()
        history=[dict(r,params=json.loads(r['params'])) for r in rows]
        return 200,{'contractId':CONTRACT,'user':user,'can_generate':self.authorizer(user),
                    'catalog':catalog,'history':history,'privacy':'only_me',
                    'model':{'configured':self.daily.is_configured(),'daily_limit':model_daily_limit() or None,'shared_with_fc_daily':True},
                    'capabilities':{'reports':True,'data_followup':True,'operations_memory':False,'web_search':False,'business_writes':False},
                    'daily_schedule':{'time':'09:15','timezone':'Asia/Shanghai','scope':'FC27昨日','url':'/dashboard/analytics/?mode=business&fc_tab=review&b_profile=FC27&b_range=yesterday'}}

    def post(self,body,user,headers):
        if not user:return 401,{'error':'login_required'}
        if not self.authorizer(user):return 403,{'error':'admin_required'}
        if headers.get('X-FS-Advisor-Action')!='submit' or headers.get('Sec-Fetch-Site')!='same-origin':return 403,{'error':'same_origin_required'}
        if not isinstance(body,dict) or set(body)-{'request_id','kind','selection','report_id','question','ai'}:return 422,{'error':'invalid_request'}
        request_id=body.get('request_id','');kind=body.get('kind')
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',request_id):return 422,{'error':'invalid_request_id'}
        try:
            if kind=='report':
                params={'selection':selection(body.get('selection'),self.catalog(),self.clock()),'ai':body.get('ai') is True}
            elif kind=='question':
                original=self.get_job(user,body.get('report_id'))
                if not original or original['kind']!='report' or original['state']!='completed':return 404,{'error':'report_not_found'}
                params={'report_id':original['id'],'question':clean_question(body.get('question')),'ai':body.get('ai') is True}
            else:return 422,{'error':'invalid_kind'}
        except (ValueError,TypeError,KeyError):return 422,{'error':'invalid_selection_or_sensitive_question'}
        return self.enqueue(user,request_id,kind,params)

    def post_boss(self,body,user,headers):
        if not user:return 401,{'error':'login_required'}
        if not self.authorizer(user):return 403,{'error':'admin_required'}
        if headers.get('X-FS-Advisor-Action')!='submit' or headers.get('Sec-Fetch-Site')!='same-origin':return 403,{'error':'same_origin_required'}
        try:
            params=project_context(body)
            if params['scope']=='management':
                catalog=self.catalog();keys=[p['key'] for p in params['context']['projects']]
                if any(k not in catalog['profiles'] for k in keys):raise ValueError('unknown_project')
                params['selection']={'scope':'management','projects':keys,'catalog_id':catalog['catalogId'],
                                     'period':period(dict(params['context']['period'],kind='custom'),self.clock())}
        except (ValueError,TypeError,KeyError):return 422,{'error':'invalid_boss_context'}
        code,result=self.enqueue(user,body['request_id'],'boss',params)
        return code,dict(result,status='pending',retryAfter=3) if code in (200,202) else result

    def enqueue(self,user,request_id,kind,params):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT id,kind,params FROM jobs WHERE owner=? AND request_id=?',(user,request_id)).fetchone()
            if old:
                if old['kind']!=kind or old['params']!=encoded(params):return 409,{'error':'request_id_conflict'}
                return 200,{'job_id':old['id'],'reused':True}
            active=db.execute("SELECT id,owner,kind,params FROM jobs WHERE state IN ('pending','running')").fetchall()
            for item in active:
                if item['owner']==user and item['kind']==kind and item['params']==encoded(params):return 200,{'job_id':item['id'],'reused':True}
            if len(active)>=8:return 429,{'error':'workspace_limit'}
            jobid=digest({'owner':user,'request_id':request_id})[:24]
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,'pending',?,NULL,NULL,NULL,NULL)",(jobid,user,request_id,kind,encoded(params),self.clock().isoformat()))
        return 202,{'job_id':jobid}

    def source(self,key,period_value,deadline):
        p={k:[v] for k,v in {'mode':'summary','profile':key,'start':period_value['start'],'end':period_value['end'],'grain':'day'}.items()}
        partial=None;first=None
        while time.monotonic()<deadline:
            status,data=self.read_range(p)
            if status==403:raise PermissionError('source_permission_denied')
            if status==200 and not data.get('stale'):
                if first is None:first=time.monotonic()
                partial=data
                if data.get('profile',{}).get('primary',{}).get('status')=='available' or time.monotonic()-first>=20:return data
            if status not in (200,202,429,503):break
            self.wait(3)
        if partial:return partial
        raise ValueError('source_unavailable')

    def run_one(self):
        if not self.lock.acquire(False):return False
        try:
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE');row=db.execute("SELECT * FROM jobs WHERE state='pending' ORDER BY created_at LIMIT 1").fetchone()
                if not row:return False
                job=dict(row);db.execute("UPDATE jobs SET state='running' WHERE id=?",(job['id'],))
            params=json.loads(job['params'])
            try:
                if not self.authorizer(job['owner']):raise PermissionError('source_permission_denied')
                if job['kind']=='report':
                    result=self.collect_report(params['selection'],job['id'])
                    projected=projection(result)
                    result['ai']=self.daily.bounded_model(projected,self.model) if params['ai'] and projected['facts'] else {'status':'not_requested' if not params['ai'] else 'no_verified_facts'}
                    result['report_id']=job['id']
                elif job['kind']=='question':
                    original=self.get_job(job['owner'],params['report_id']);report=original['result']
                    with self.db() as db:previous=db.execute("SELECT params FROM jobs WHERE owner=? AND kind='question' AND state='completed' ORDER BY created_at DESC LIMIT 12",(job['owner'],)).fetchall()
                    context=[json.loads(r[0])['question'] for r in reversed(previous) if json.loads(r[0])['report_id']==params['report_id']][-3:]
                    projected=projection(report,params['question'],context)
                    ai=self.daily.bounded_model(projected,self.model) if params['ai'] and projected['facts'] else {'status':'not_requested' if not params['ai'] else 'no_verified_facts'}
                    result={'report_id':params['report_id'],'question':params['question'],'ai':ai,
                            'facts':report['projects'],'period':report['period'],
                            'message':'追问仅依据所选报告的已保存快照；事实卡可核对数值，未读取其他人的对话。',
                            'generated_at':self.clock().isoformat()}
                else:
                    projected={k:params[k] for k in ('scope','context')}
                    if params['scope']=='management':
                        report=self.collect_report(params['selection'],job['id'])
                        targets={p['key']:p['target_revenue_usd'] for p in params['context']['projects']}
                        facts=[]
                        for p in report['projects']:
                            metrics=p['metrics'];revenue=metrics.get('revenueUsd',{}).get('value');rate=metrics.get('profitMarginPct',{}).get('value')
                            estimated=math.floor(math.floor(revenue*100+.5)*math.floor(rate*100+.5)/10000+.5)/100 if revenue is not None and rate is not None else None
                            item={'key':p['key'],'orders':metrics.get('orders',{}).get('value'),'revenue_usd':revenue,
                                  'estimated_profit_usd':estimated,'target_revenue_usd':targets[p['key']]}
                            item['missing']=[k for k,v in item.items() if v is None];facts.append(item)
                        projected={'scope':'management','context':{'period':params['context']['period'],'projects':facts}}
                        # Revalidate projected server facts. Browser amounts are never evidence.
                        projected=project_context(dict(projected,request_id='server_verified_facts'))
                    result=self.daily.bounded_model(projected,explain_boss)
                    result.setdefault('source_kind','imported_snapshot' if params['scope']=='game-monitor' else 'fs_summary')
                    if result['status']!='succeeded':result['reason']=result['status']
                    if params['scope']=='management':result['actuals_verified_on_server']=True
                with self.db() as db:db.execute("UPDATE jobs SET state='completed',finished_at=?,result=? WHERE id=?",(self.clock().isoformat(),encoded(result),job['id']))
            except Exception as error:
                code='source_permission_denied' if isinstance(error,PermissionError) else 'catalog_changed' if str(error)=='catalog_changed' else 'generation_failed'
                with self.db() as db:db.execute("UPDATE jobs SET state='failed',finished_at=?,error=? WHERE id=?",(self.clock().isoformat(),code,job['id']))
            return True
        finally:self.lock.release()

    def collect_report(self,sel,jobid):
        catalog=self.catalog()
        if catalog['catalogId']!=sel['catalog_id']:raise ValueError('catalog_changed')
        projects=[];deadline=time.monotonic()+900
        for key in sel['projects']:
            with self.db() as db:db.execute('UPDATE jobs SET progress=? WHERE id=?',(encoded({'done':len(projects),'total':len(sel['projects']),'project':key}),jobid))
            try:
                raw=self.source(key,sel['period'],min(deadline,time.monotonic()+150))
                item=project_facts(key,catalog['profiles'][key]['name'],raw,sel['period'])
            except PermissionError:raise
            except (ValueError,KeyError,TypeError,OSError):
                item={'key':key,'name':catalog['profiles'][key]['name'],'status':'unavailable','metrics':{},'warnings':['来源未完整返回；未补零，请稍后重生成。']}
            projects.append(item)
        return report_from(sel,projects,self.clock())

    def start(self):
        import fcntl
        self.process_lock=(self.root/'worker.lock').open('a+b')
        try:fcntl.flock(self.process_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:self.process_lock.close();return
        with self.db() as db:db.execute("UPDATE jobs SET state='failed',error='process_interrupted',finished_at=? WHERE state='running'",(self.clock().isoformat(),))
        def loop():
            while True:
                try:self.run_one()
                except Exception:pass
                self.wait(2)
        threading.Thread(target=loop,daemon=True,name='ai-advisor').start()
