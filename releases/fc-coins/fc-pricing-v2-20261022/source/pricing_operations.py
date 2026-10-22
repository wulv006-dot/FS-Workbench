"""Owned, leased Hermes pricing operations; reuse FS task and FC execution ledgers."""
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPRedirectHandler

NAME='fs.pricing.control'
ACTIONS=('capabilities','state','read_quote','evaluate','recommend','apply_recommendation','collect','preview','execute','read_job','restore_preview','restore')
MUTATING=frozenset(ACTIONS)-{'capabilities','state','read_quote','evaluate','read_job'}
AUTO=('capabilities','state','read_quote','evaluate','recommend','read_job')
ROOT=Path('/var/lib/fs-hermes-fc/fs')
FIELDS={a:set(v.split()) for a,v in {
    'capabilities':'action','state':'action','read_job':'action job_id','read_quote':'action run_id path',
    'evaluate':'action run_id console_usd pc_usd reason',
    'recommend':'action request_key run_id console_choice pc_choice reason counterexample evidence_refs',
    'apply_recommendation':'action request_key recommendation_id','collect':'action request_key',
    'preview':'action request_key run_id','execute':'action request_key preview_id',
    'restore_preview':'action request_key source_execution_id',
    'restore':'action request_key source_execution_id restore_preview_id'}.items()}


def schema():
    text={'type':'string'}
    fields=dict(action={'enum':list(ACTIONS)},request_key={'type':'string','pattern':'^[A-Za-z0-9_-]{1,48}$'},
        run_id=text,job_id=text,preview_id=text,source_execution_id=text,restore_preview_id=text,recommendation_id=text,
        path={'type':'string','maxLength':256,'description':'JSON pointer beginning /evidence, /result or /edits. Use current_quote.run_id or historical_quote.run_id, never an execution/job id. Historical fragments remain readable when quote_evidence_ref is null.'},console_usd=text,pc_usd=text,console_choice={'enum':['baseline','hold','parity','evaluated']},
        pc_choice={'enum':['baseline','hold','parity','evaluated']},reason={'type':'string','minLength':4,'maxLength':200},
        counterexample={'type':'string','minLength':4,'maxLength':400},
        evidence_refs={'type':'array','items':text,'minItems':1,'maxItems':20})
    return {'type':'function','function':{'name':'mcp__fcro__fs_pricing_control',
            'description':'FC Coins real control. First capabilities/state; state is a bounded decision summary, read_quote(run_id,path JSON pointer) reads full source fragments. read_job includes the original execution audit: failed writer response does NOT prove no write. PARTIAL/UNCERTAIN/changed requires original reconciliation, never another execute key. Follow action_fields exactly. recommend baseline/hold/parity has no explicit prices; custom requires BOTH evaluated and BOTH prices. Use quote_evidence_ref verbatim. Scenario/100K-only receipts do not prove full-catalog feasibility; evaluate current run does. Automatic-review may evaluate/recommend, not enqueue. Operator may apply_recommendation→read_job→preview→read_job→execute→read_job and state public readback. Every price/restore must pass >=10% procurement margin incl promotions/gifts/packages. Stable request_key; UNKNOWN reads original, never resubmits. No order/coupon/credential/source-code writes.',
        'parameters':{'type':'object','properties':fields,'required':['action'],'additionalProperties':False}}}


def tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS pricing_grants(conversation TEXT PRIMARY KEY,owner TEXT NOT NULL,mode TEXT NOT NULL,runs TEXT NOT NULL,expires_at TEXT NOT NULL,source TEXT NOT NULL,restore_sources TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS pricing_operations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,task TEXT NOT NULL,action TEXT NOT NULL,payload_hash TEXT NOT NULL,request_id TEXT NOT NULL,state TEXT NOT NULL,result TEXT,created_at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS pricing_recommendations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,task TEXT NOT NULL,conversation TEXT NOT NULL,run_id TEXT NOT NULL,quote_sha256 TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL)')


def grant(db,owner,conversation,run,mode,expires,source,restore_sources=()):
    if mode not in ('automatic_review','operator_workflow') or not re.fullmatch('[a-f0-9]{32}',conversation):
        raise ValueError('pricing_grant_scope')
    uuid.UUID(run)
    if len(restore_sources)>1 or restore_sources and mode!='operator_workflow':raise ValueError('pricing_restore_grant_scope')
    sources=json.dumps([str(uuid.UUID(value)) for value in restore_sources]);tables(db)
    raw=json.dumps([run])
    old=db.execute('SELECT owner,mode,runs,expires_at,source,restore_sources FROM pricing_grants WHERE conversation=?',(conversation,)).fetchone()
    values=(owner,mode,raw,expires,source,sources)
    if old is not None and tuple(old)!=values:raise ValueError('pricing_grant_conflict')
    db.execute('INSERT OR IGNORE INTO pricing_grants VALUES(?,?,?,?,?,?,?)',(conversation,*values))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):return None


def native(path,owner,body=None):
    req=Request('http://127.0.0.1:8879'+path,data=None if body is None else json.dumps(body).encode(),
        headers={'X-Authenticated-User':owner,'X-Forwarded-Proto':'https','Host':'47.85.224.112',
                 'Origin':'https://47.85.224.112','Content-Type':'application/json'},method='GET' if body is None else 'POST')
    with build_opener(NoRedirect()).open(req,timeout=15) as response:
        raw=response.read(1024*1024+1)
    if len(raw)>1024*1024:raise ValueError('pricing_native_reply_too_large')
    return json.loads(raw)


def quote_view(quote):
    if not quote:return None
    evidence=quote.get('evidence',{});envelope=evidence.get('promotion_envelope',{})
    fields='platform cost_cny cost_record_id cost_trade_at target_page_usd main_page_usd floor_usd_per_1k gross_margin_pct pre_change_margin_pct minimum_gross_margin_pct decision_reason ending_reason change_pct break_even_order_multiplier proof'.split()
    result=quote.get('result',{})
    return dict(run_id=quote['run_id'],created_at=quote.get('created_at'),status=quote.get('status'),
        view='decision_summary; use read_quote for complete original fragments',
        evidence={k:evidence[k] for k in ('checked_at','costs','fx') if k in evidence},
        promotion_envelope={k:envelope[k] for k in ('sha256','checked_at','status','minimum_retained_ratio','scope') if k in envelope},
        result=dict(decision_receipt=result.get('decision_receipt'),rows=[{k:r[k] for k in fields if k in r} for r in result.get('rows',[])]))


def authorization(scope,owner,task,now):
    root=Path(scope.tasks.path).parent
    with closing(sqlite3.connect((root/'conversations/conversations.db').as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        row=db.execute('SELECT t.conversation_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.task_id=? AND c.owner=?',(task,owner)).fetchone()
    if row is None:return None
    with scope.tasks.db() as db:
        tables(db);db.row_factory=sqlite3.Row
        r=db.execute('SELECT * FROM pricing_grants WHERE conversation=? AND owner=?',(row[0],owner)).fetchone()
    if r is None:return None
    value=dict(r)
    if datetime.fromisoformat(value['expires_at'])<=now:return None
    value['runs']=json.loads(value['runs'])
    value['restore_sources']=json.loads(value['restore_sources'])
    return value


def call(scope,owner,task,lease,args,request=native):
    scope.context(owner,task,lease)
    if not isinstance(args,dict) or args.get('action') not in ACTIONS:
        raise ValueError('pricing_tool_fields')
    action=args['action'];now=scope.clock();auth=authorization(scope,owner,task,now)
    allowed=list(AUTO if auth and auth['mode']=='automatic_review' else ACTIONS if auth else ('capabilities','state','read_quote','evaluate','read_job'))
    if action not in allowed:raise PermissionError('pricing_task_not_authorized')
    if action=='capabilities':
        if set(args)!={'action'}:raise ValueError('pricing_tool_fields')
        return dict(allowed_actions=allowed,mode=auth['mode'] if auth else 'read_only',hard_margin_pct='10',
                    scoped_runs=auth['runs'] if auth else [],restore_sources=auth['restore_sources'] if auth else [],lease_required=True,unknown_replay=False,
                    action_fields={a:sorted(FIELDS[a]) for a in allowed},quote_read_contract='read_quote uses current_quote.run_id or historical_quote.run_id; paths /evidence, /result, /edits. Null executable quote reference does not deny historical reads; use returned child paths for large fragments.',custom_recommendation='Both choices evaluated; add console_usd and pc_usd only for that case.')
    if action=='state':
        if set(args)!={'action'}:raise ValueError('pricing_tool_fields')
        data=request('/pricing/state',owner);quote=data.pop('quote',None)
        usable=bool(data.get('quote_usable'))
        digest=hashlib.sha256(json.dumps(quote,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest() if quote else None
        data['current_quote']=quote_view(quote) if usable else None
        data['historical_quote']=quote_view(quote) if not usable else None
        data['quote_sha256']=digest if usable else None
        data['historical_quote_sha256']=digest if not usable else None
        data['quote_evidence_ref']='pricing:'+digest if usable and digest else None
        data['allowed_actions']=allowed
        policy=request('/automation',owner);monitor=request('/monitor',owner)
        data['policy']={k:policy[k] for k in ('system_enabled','mode','platforms','interval_minutes','minimum_gross_margin_pct','revision','schedule') if k in policy}
        data['monitor']={k:monitor[k] for k in ('publication','cache_refresh','page_readback','latest_attempt') if k in monitor}
        data['monitor']['health']={k:monitor.get('health',{}).get(k) for k in ('incomplete_executions','queue_depth','automation_timer','api','worker')}
        return data
    if action=='read_quote':
        if set(args)!=FIELDS[action]:raise ValueError('pricing_tool_fields')
        run=str(uuid.UUID(args['run_id']));path=args['path']
        if not isinstance(path,str) or len(path)>256 or not re.fullmatch(r'/(evidence|result|edits)(/[^/]+)*',path):raise ValueError('pricing_quote_path_invalid')
        quote=request('/quotes/'+run,owner);value=quote
        for part in path[1:].split('/'):
            key=part.replace('~1','/').replace('~0','~')
            try:value=value[int(key)] if isinstance(value,list) else value[key]
            except (KeyError,IndexError,ValueError,TypeError):raise ValueError('pricing_quote_path_missing') from None
        result=dict(run_id=run,quote_sha256=hashlib.sha256(json.dumps(quote,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),path=path)
        if len(json.dumps(value,ensure_ascii=False).encode())>10000:
            keys=list(value) if isinstance(value,dict) else list(range(len(value))) if isinstance(value,list) else []
            return dict(result,complete=False,read_subpaths=[path+'/'+str(k).replace('~','~0').replace('/','~1') for k in keys])
        return dict(result,complete=True,value=value)
    if action=='read_job':
        if set(args)!={'action','job_id'}:raise ValueError('pricing_tool_fields')
        job=str(uuid.UUID(args['job_id']));result=request('/jobs/'+job,owner)
        if result.get('kind') in ('execute','restore'):
            try:audit=request('/audits/'+job,owner)
            except HTTPError as exc:
                if exc.code!=404:raise
                result.update(execution_audit=None,audit_absence='no durable audit found; writer error alone does not prove no dispatch')
            else:
                result['execution_audit']={k:audit[k] for k in ('execution_id','preview_id','run_id','status','stage','changed','sync_confirmed','all_baseline','error','created_at','updated_at','recovery_history') if k in audit}
                result['execution_audit']['after']=[{k:r[k] for k in ('id','platform','b2c','costPrice') if k in r} for r in audit.get('after',{}).get('rows',[])]
                result.update(price_write_observed=bool(audit.get('changed')),reconciliation_required=audit.get('status') in ('RUNNING','PARTIAL','UNCERTAIN'),do_not_replay=True)
        return result
    if action=='evaluate':
        if set(args)!={'action','run_id','console_usd','pc_usd','reason'}:raise ValueError('pricing_tool_fields')
        return request('/pricing/evaluate',owner,{k:v for k,v in args.items() if k!='action'})
    if auth is None:raise PermissionError('pricing_task_not_authorized')
    key=args.get('request_key')
    if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_-]{1,48}',key):raise ValueError('pricing_stable_request_key_required')
    ident=hashlib.sha256((owner+':'+task+':'+key).encode()).hexdigest()
    payload_hash=hashlib.sha256(json.dumps(args,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'fs-pricing:'+ident))
    with scope.tasks.db() as db:
        tables(db);db.row_factory=sqlite3.Row
        old=db.execute('SELECT * FROM pricing_operations WHERE id=?',(ident,)).fetchone()
        if old:
            if old['payload_hash']!=payload_hash:raise ValueError('pricing_request_key_payload_conflict')
            return dict(operation_id=ident,intent_id=old['request_id'],job_id=None if action=='recommend' else old['request_id'],recommendation_id=ident if action=='recommend' and old['state']=='accepted' else None,state=old['state'],result=json.loads(old['result']) if old['result'] else None,reused=True,do_not_replay=old['state'] in {'reserved','unknown'})
        db.execute('INSERT INTO pricing_operations VALUES(?,?,?,?,?,?,?,?,?)',(ident,owner,task,action,payload_hash,request_id,'reserved',None,now.isoformat()))
    scope.context(owner,task,lease)
    try:
        if action=='recommend':
            fields={'action','request_key','run_id','console_choice','pc_choice','reason','counterexample','evidence_refs'}
            custom=args.get('console_choice')=='evaluated' or args.get('pc_choice')=='evaluated'
            if custom:fields|={'console_usd','pc_usd'}
            if set(args)!=fields or custom and (args['console_choice']!='evaluated' or args['pc_choice']!='evaluated'):
                raise ValueError('pricing_tool_fields')
            state=request('/pricing/state',owner);quote=state['quote']
            if not state['quote_usable'] or quote['run_id']!=args['run_id'] or args['run_id'] not in auth['runs']:
                raise ValueError('pricing_authorized_run_changed')
            canonical=hashlib.sha256(json.dumps(quote,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            refs=args['evidence_refs']
            if not isinstance(refs,list) or not refs or len(refs)>20 or any(r not in scope.book.evidence and r!='pricing:'+canonical for r in refs):
                raise ValueError('pricing_recommendation_evidence_required')
            if not isinstance(args['reason'],str) or not 4<=len(args['reason'])<=200 or not isinstance(args['counterexample'],str) or not 4<=len(args['counterexample'])<=400:
                raise ValueError('pricing_recommendation_reason_required')
            decisions=quote['result']['decision_receipt']['decisions']
            if custom:
                evaluated=request('/pricing/evaluate',owner,{k:args[k] for k in ('run_id','console_usd','pc_usd','reason')})
                if evaluated['canonical_quote_sha256']!=canonical:raise ValueError('pricing_evaluation_basis_changed')
                rows={r['platform']:r for r in evaluated['result']['rows']}
                prices={'console':rows['PS']['target_page_usd'],'pc':rows['PC']['target_page_usd']}
                if rows['PS']['proposal']!=rows['XBOX']['proposal']:raise ValueError('pricing_evaluation_console_conflict')
            else:
                prices={name:decisions[i]['candidates'].get(args[name+'_choice']) for i,name in enumerate(('console','pc'))}
            if any(v is None for v in prices.values()):raise ValueError('pricing_candidate_not_available')
            result=dict(operation_id=ident,run_id=args['run_id'],quote_sha256=canonical,console_usd=prices['console'],pc_usd=prices['pc'],
                        reason=args['reason'],counterexample=args['counterexample'],evidence_refs=refs,
                        source='program_verified_evaluation' if custom else 'program_generated_choices',write_performed=False)
            with scope.tasks.db() as db:
                tables(db);db.execute('INSERT INTO pricing_recommendations VALUES(?,?,?,?,?,?,?,?)',(ident,owner,task,auth['conversation'],args['run_id'],canonical,json.dumps(result,ensure_ascii=False),now.isoformat()))
        else:
            fields={'apply_recommendation':{'action','request_key','recommendation_id'},'collect':{'action','request_key'},'preview':{'action','request_key','run_id'},
                'execute':{'action','request_key','preview_id'},'restore_preview':{'action','request_key','source_execution_id'},
                'restore':{'action','request_key','source_execution_id','restore_preview_id'}}[action]
            if set(args)!=fields:raise ValueError('pricing_tool_fields')
            if action=='apply_recommendation':
                with scope.tasks.db() as db:
                    row=db.execute('SELECT run_id,content FROM pricing_recommendations WHERE id=? AND owner=? AND task=?',(args['recommendation_id'],owner,task)).fetchone()
                if row is None or row[0] not in auth['runs']:raise PermissionError('pricing_recommendation_not_owned')
                value=json.loads(row[1]);current=request('/pricing/state',owner)
                if not current['quote_usable'] or current['quote']['run_id']!=row[0] or hashlib.sha256(json.dumps(current['quote'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=value['quote_sha256']:
                    raise ValueError('pricing_recommendation_basis_changed')
                policy=request('/automation',owner)
                from decimal import Decimal
                console=str(Decimal(value['console_usd'])/100);pc=str(Decimal(value['pc_usd'])/100)
                path='/pricing/recalculate';body={'run_id':row[0],'edits':{'quotes':{'PS':console,'XBOX':console,'PC':pc},'reason':value['reason'],'minimum_gross_margin_pct':policy['minimum_gross_margin_pct']}}
            elif action=='collect':path='/pricing/collect';body={}
            elif action=='preview':
                run=str(uuid.UUID(args['run_id']))
                if run not in auth['runs']:raise PermissionError('pricing_run_not_granted')
                path='/pricing/preview';body={'run_id':run}
            elif action=='execute':
                if request('/monitor',owner).get('health',{}).get('incomplete_executions',0):raise ValueError('pricing_execution_reconciliation_required')
                preview=request('/previews/'+str(uuid.UUID(args['preview_id'])),owner)
                if preview['run_id'] not in auth['runs']:raise PermissionError('pricing_run_not_granted')
                path='/reprice/execute';body={'preview_id':preview['preview_id'],'selected_platforms':request('/automation',owner)['platforms'],'margin_confirmed_platforms':[],'margin_exception_reason':''}
            elif action in {'restore_preview','restore'}:
                source=str(uuid.UUID(args['source_execution_id']));audit=request('/audits/'+source,owner)
                if audit.get('execution_id')!=source or audit.get('status')!='CONFIRMED' or not audit.get('sync_confirmed'):
                    raise ValueError('pricing_restore_source_not_confirmed')
                run=audit.get('run_id')
                if not run:run=request('/previews/'+str(uuid.UUID(audit['preview_id'])),owner)['run_id']
                if run not in auth['runs'] and source not in auth['restore_sources']:raise PermissionError('pricing_restore_source_not_granted')
                if action=='restore_preview':path='/pricing/restore-preview';body={'source_execution_id':source}
                else:
                    if request('/monitor',owner).get('health',{}).get('incomplete_executions',0):raise ValueError('pricing_execution_reconciliation_required')
                    preview=request('/restore-previews/'+str(uuid.UUID(args['restore_preview_id'])),owner)
                    if preview['source_execution_id']!=source:raise ValueError('pricing_restore_source_changed')
                    path='/reprice/'+source+'/restore';body={'restore_preview_id':preview['restore_preview_id'],'selected_platforms':preview['available_platforms']}
            else:
                raise ValueError('pricing_tool_fields')
            if action=='collect':
                with scope.tasks.db() as db:
                    runs=auth['runs']+[request_id];db.execute('UPDATE pricing_grants SET runs=? WHERE conversation=? AND owner=?',(json.dumps(runs),auth['conversation'],owner))
            scope.context(owner,task,lease)
            result=request(path,owner,dict(body,client_event_id=request_id))
            if result.get('job_id')!=request_id:raise RuntimeError('pricing_operation_receipt_mismatch')
        state='accepted'
    except (ValueError,PermissionError,HTTPError) as exc:
        state='unknown' if isinstance(exc,HTTPError) and exc.code>=500 else 'rejected'
        result={'error':str(exc) if isinstance(exc,(ValueError,PermissionError)) else 'native_http_'+str(exc.code),
                'original_intent_id':request_id,'original_job_id':None if action=='recommend' else request_id,'do_not_replay':state=='unknown'}
        if isinstance(exc,HTTPError):
            try:code=json.loads(exc.read(4096)).get('error')
            except (OSError,ValueError,AttributeError):code=None
            if isinstance(code,str) and re.fullmatch('[A-Za-z0-9_:-]{1,100}',code):result['native_error']=code
        if isinstance(exc,ValueError) and str(exc)=='pricing_tool_fields':
            result.update(expected_fields=sorted(fields),received_fields=sorted(args))
        if isinstance(exc,ValueError) and str(exc)=='pricing_recommendation_evidence_required':
            result['expected_evidence_ref']='pricing:'+canonical
    except Exception as exc:
        state='unknown';result={'error':type(exc).__name__,'original_intent_id':request_id,'original_job_id':None if action=='recommend' else request_id,'do_not_replay':True}
    with scope.tasks.db() as db:
        db.execute('UPDATE pricing_operations SET state=?,result=? WHERE id=?',(state,json.dumps(result,ensure_ascii=False),ident))
    scope.context(owner,task,lease)
    return dict(operation_id=ident,intent_id=request_id,job_id=None if action=='recommend' else request_id,recommendation_id=ident if action=='recommend' and state=='accepted' else None,state=state,result=result,
                queue_write_performed=state=='accepted' and action!='recommend',price_write_confirmed=False,
                execution_status='not_dispatched' if action=='recommend' else 'read_original_job_for_terminal_state',
                do_not_replay=state=='unknown')
