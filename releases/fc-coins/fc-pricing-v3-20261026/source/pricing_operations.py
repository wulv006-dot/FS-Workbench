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
ACTIONS=('capabilities','state','read_quote','candidate_detail','compare_strategies','region_impact','sprint_target','simulate','simulation_read','plan_propose','plan_execute_authorized','operation_read','incident_read','recommend')
MUTATING=frozenset(('simulate','plan_propose','plan_execute_authorized','recommend'))
AUTO=('capabilities','state','read_quote','candidate_detail','compare_strategies','region_impact','sprint_target','simulation_read','operation_read','incident_read','recommend')
ROOT=Path('/var/lib/fs-hermes-fc/fs')
FIELDS={a:{'action'} for a in ACTIONS}
FIELDS.update(read_quote={'action','run_id','path'},candidate_detail={'action','run_id','mode','action_sha256'},compare_strategies={'action','mode'},region_impact={'action'},sprint_target={'action'},simulate={'action','request_key','kind'},simulation_read={'action','simulation_id'},plan_propose={'action','request_key','mode'},plan_execute_authorized={'action','request_key','plan_id'},operation_read={'action','operation_id'},recommend={'action','request_key','run_id','bundle_sha256','action_sha256','reason','evidence_refs'})



def schema():
    props={name:{'type':'string'} for name in ('action','mode','request_key','run_id','path','plan_id','operation_id','simulation_id','bundle_sha256','action_sha256','reason','kind')}
    props['action']={'enum':list(ACTIONS)}
    props['action_sha256']['description']='SHA256 of the exact candidate action canonical JSON from the same run; this selects the reviewed candidate, including a nondefault feasible candidate.'
    props['bundle_sha256']['description']='Original V3 decision receipt SHA256 from read_quote for run_id.'
    props['reason']['description']='Explain why this candidate serves the chosen objective, its actual order/AOV/cost and competitor basis, tradeoffs against alternatives, and missing evidence.'
    props['evidence_refs']={'type':'array','items':{'type':'string'},'description':'Include pricing:<bundle_sha256> and any inspected same-run evidence references.'}
    props['simulation_id']['description']='Original ID returned by simulate; read the result with simulation_read.'
    return {'type':'function','function':{'name':'mcp__fcro__fs_pricing_control','description':'FC27 Pricing V3 review and decision tool. Use state, compare_strategies and the same-run quote receipt to inspect all five objectives, real paid-order/AOV and delivered-K units, dual 10% proofs, scope, budget and missing evidence. State lists every action and its hash with compact score and margins; use candidate_detail with the exact run, mode and action hash for its full original proof. Hermes may choose any feasible candidate from that run through recommend with its exact action hash and a substantive reason; the later V3 cycle recollects and rechecks before execution and records any departure from the original assignment. Use operation_read and simulation_read for outcomes and historical review. Old 80/15/5 and parity are read-only historical replays, never current pricing rules. UNKNOWN must reconcile the original operation ID. Shadow projections are estimates, never observed profit or execution authority.','parameters':{'type':'object','properties':props,'required':['action'],'additionalProperties':False}}}



def tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS pricing_grants(conversation TEXT PRIMARY KEY,owner TEXT NOT NULL,mode TEXT NOT NULL,runs TEXT NOT NULL,expires_at TEXT NOT NULL,source TEXT NOT NULL,restore_sources TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS pricing_operations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,task TEXT NOT NULL,action TEXT NOT NULL,payload_hash TEXT NOT NULL,request_id TEXT NOT NULL,state TEXT NOT NULL,result TEXT,created_at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS pricing_recommendations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,task TEXT NOT NULL,conversation TEXT NOT NULL,run_id TEXT NOT NULL,quote_sha256 TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL)')


def grant(db,owner,conversation,run,mode,expires,source,restore_sources=()):
    if mode!='daily_review' or not re.fullmatch('[a-f0-9]{32}',conversation):
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
    fields='platform cost_cny cost_record_id cost_trade_at target_page_usd main_page_usd floor_usd_per_1k gross_margin_pct pre_change_margin_pct minimum_gross_margin_pct decision_reason ending_reason change_pct break_even_order_multiplier estimated_average_margin margin_basis proof'.split()
    result=quote.get('result',{})
    return dict(run_id=quote['run_id'],created_at=quote.get('created_at'),status=quote.get('status'),
        view='decision_summary; use read_quote for complete original fragments',
        evidence={k:evidence[k] for k in ('checked_at','costs','fx') if k in evidence},
        promotion_envelope={k:envelope[k] for k in ('sha256','checked_at','status','minimum_retained_ratio','scope') if k in envelope},
        result=dict(decision_receipt=result.get('decision_receipt'),rows=[{k:r[k] for k in fields if k in r} for r in result.get('rows',[])]))


def authorization(scope,owner,task,now):
    root=Path(scope.tasks.path).parent
    bindings=[]
    for store in ('pricing-reviews','conversations'):
        path=root/store/'conversations.db'
        if not path.is_file():continue
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            row=db.execute('SELECT t.conversation_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.task_id=? AND c.owner=?',(task,owner)).fetchone()
        if row:bindings.append(row[0])
    if not bindings:return None
    if len(bindings)!=1:raise ValueError('pricing_task_binding_conflict')
    with scope.tasks.db() as db:
        tables(db);db.row_factory=sqlite3.Row
        r=db.execute('SELECT * FROM pricing_grants WHERE conversation=? AND owner=?',(bindings[0],owner)).fetchone()
    if r is None:return None
    value=dict(r)
    if datetime.fromisoformat(value['expires_at'])<=now:return None
    value['runs']=json.loads(value['runs'])
    value['restore_sources']=json.loads(value['restore_sources'])
    return value


def call(scope,owner,task,lease,args,request=native):
    scope.context(owner,task,lease)
    action=args.get('action') if isinstance(args,dict) else None
    if action not in ACTIONS or set(args)!=FIELDS[action]:
        raise ValueError('pricing_tool_fields')
    auth=authorization(scope,owner,task,scope.clock())
    allowed=list(set(ACTIONS)-MUTATING-{'compare_strategies'} if auth and auth['mode']=='daily_review' else AUTO if auth and auth['mode']=='automatic_review' else ACTIONS if auth else
                 set(ACTIONS)-MUTATING)
    if action not in allowed:
        raise PermissionError('pricing_task_not_authorized')
    if action=='capabilities':
        return dict(version='fc-pricing-v3-20261026',allowed_actions=allowed,
                    action_fields={a:sorted(FIELDS[a]) for a in allowed},scoped_runs=auth['runs'] if auth else [],
                    separate_shadow=True,unknown_replay=False,hard_margin_pct='10',average_hard_margin_pct='10')
    state=request('/pricing/v3/state',owner) if action in ('state','sprint_target') else None
    if action=='state':
        return state
    if action=='compare_strategies':
        if auth and auth['mode'] in ('automatic_review','daily_review'):
            if len(auth['runs'])!=1:
                raise ValueError('pricing_review_run_scope_invalid')
            run=auth['runs'][0]
            decisions=request('/pricing/v3/strategy-decisions/'+run,owner)
            if decisions.get('snapshot_id')!=run or args['mode'] not in decisions.get('results',{}):
                raise ValueError('pricing_review_run_basis_changed')
            return dict(snapshot_id=run,results={args['mode']:decisions['results'][args['mode']]},
                        execution_authorized=False,source='original_run_strategy_decisions')
        return request('/pricing/v3/evaluate',owner,dict(mode=args['mode']))
    if action=='region_impact':
        return request('/pricing/v3/region-rules',owner)
    if action=='sprint_target':
        return state.get('target')
    if action=='incident_read':
        return request('/pricing/v3/incidents',owner)
    if action=='operation_read':
        return request('/pricing/v3/operations/'+str(uuid.UUID(args['operation_id'])),owner)
    if action=='simulation_read':
        return request('/pricing/v3/simulations/'+str(uuid.UUID(args['simulation_id'])),owner)
    if action=='read_quote':
        run=str(uuid.UUID(args['run_id']))
        quote=request('/quotes/'+run,owner)
        if not args['path'].startswith(('/evidence','/result','/edits')):
            raise ValueError('pricing_quote_path_invalid')
        value=quote
        for key in args['path'].strip('/').split('/'):
            value=value[int(key)] if isinstance(value,list) else value[key]
        return dict(run_id=run,path=args['path'],value=value,execution_authorized=False)
    if action=='candidate_detail':
        run=str(uuid.UUID(args['run_id']))
        mode=args['mode']
        action_sha=args['action_sha256']
        if mode not in ('daily','acquisition','backlog','flash_sale','revenue_sprint') or not re.fullmatch('[a-f0-9]{64}',action_sha):
            raise ValueError('pricing_strategy_candidate_invalid')
        return request('/pricing/v3/strategy-decisions/'+run+'/'+mode+'/'+action_sha,owner)
    key=args.get('request_key')
    if not re.fullmatch('[A-Za-z0-9_-]{1,48}',str(key or '')):
        raise ValueError('pricing_request_key_invalid')
    if not auth:
        raise PermissionError('pricing_task_not_authorized')
    ident=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-pricing-v3:'+owner+':'+task+':'+key))
    if action=='recommend':
        run=str(uuid.UUID(args['run_id']))
        if run not in auth['runs']:
            raise PermissionError('pricing_run_not_granted')
        with scope.tasks.db() as db:
            tables(db)
            old=db.execute('SELECT content FROM pricing_recommendations WHERE id=?',(ident,)).fetchone()
        if old:
            saved=json.loads(old[0])
            saved_action=hashlib.sha256(json.dumps(saved['action_vector'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
            if (saved['run_id']!=run or saved['bundle_sha256']!=args['bundle_sha256'] or
                    saved_action!=args['action_sha256'] or saved['reason']!=args['reason'] or
                    saved['evidence_refs']!=args['evidence_refs']):
                raise ValueError('pricing_operation_payload_conflict')
            return saved
        quote=request('/quotes/'+run,owner)
        bundle=quote['result']['decision_receipt']
        signed=hashlib.sha256(json.dumps({k:v for k,v in bundle.items() if k!='sha256'},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        if (quote.get('run_id')!=run or bundle.get('snapshot_id')!=run or
                bundle.get('schema_version')!='fc-pricing-v3-20261026' or
                bundle.get('sha256')!=signed or signed!=args['bundle_sha256']):
            raise ValueError('pricing_recommendation_basis_changed')
        if 'pricing:'+bundle['sha256'] not in args['evidence_refs'] or len(args['reason'].strip())<4:
            raise ValueError('pricing_recommendation_evidence_required')
        canonical=quote.get('original_quote_sha256')
        if not isinstance(canonical,str) or not re.fullmatch('[a-f0-9]{64}',canonical):
            raise ValueError('pricing_original_quote_sha256_missing')
        decisions=request('/pricing/v3/strategy-decisions/'+run,owner)
        if (decisions['snapshot_id']!=bundle.get('snapshot_id') or
                decisions['snapshot_sha256']!=bundle.get('snapshot_sha256') or
                decisions['strategy_version']!=bundle.get('schema_version')):
            raise ValueError('pricing_recommendation_basis_changed')
        candidates=decisions['results'].get(bundle['mode'],{}).get('candidates',[])
        candidate=next((c for c in candidates if hashlib.sha256(json.dumps(c['action'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()==args['action_sha256']),None)
        if candidate is None:raise ValueError('pricing_recommendation_candidate_not_available')
        value=dict(operation_id=ident,run_id=run,quote_sha256=canonical,bundle_sha256=bundle['sha256'],
                   action_vector=candidate['action'],reason=args['reason'],evidence_refs=args['evidence_refs'],
                   source='v3_program_confirmed_assignment',write_performed=False)
        with scope.tasks.db() as db:
            tables(db)
            old=db.execute('SELECT content FROM pricing_recommendations WHERE id=?',(ident,)).fetchone()
            if old:
                if json.loads(old[0])!=value:
                    raise ValueError('pricing_operation_payload_conflict')
                return value
            db.execute('INSERT INTO pricing_recommendations VALUES(?,?,?,?,?,?,?,?)',
                       (ident,owner,task,auth['conversation'],run,canonical,json.dumps(value),scope.clock().isoformat()))
        return value
    if action=='simulate':
        return request('/pricing/v3/simulations',owner,dict(request_key=ident,kind=args['kind'],closed_days=7))
    if action=='plan_propose':
        # Proposal has no plan ownership, start job or execution authority.
        evaluation=request('/pricing/v3/evaluate',owner,dict(mode=args['mode']))
        result=evaluation['results'][args['mode']]
        return dict(proposal_id=ident,mode=args['mode'],snapshot_id=evaluation['snapshot_id'],
                    status=result['status'],selected=result.get('selected'),failures=result.get('failures',[]),
                    resources_required='operator_must_choose_mutable_scope',plan_created=False,
                    execution_authorized=False,write_performed=False)
    if action=='plan_execute_authorized':
        if auth['mode']!='operator_workflow':
            raise PermissionError('pricing_automatic_review_no_dispatch')
        payload_hash=hashlib.sha256(json.dumps(args,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        with scope.tasks.db() as db:
            tables(db)
            old=db.execute('SELECT owner,task,action,payload_hash FROM pricing_operations WHERE id=?',(ident,)).fetchone()
        if old and tuple(old)!=(owner,task,action,payload_hash):
            raise ValueError('pricing_operation_payload_conflict')
        if not old:
            current=request('/pricing/v3/state',owner)
            plan=next((p for p in current.get('active_plans',[]) if p['plan_id']==args['plan_id']),None)
            if not plan or plan['state']!='ACTIVE' or current['snapshot_id'] not in auth['runs']:
                raise PermissionError('pricing_plan_not_granted')
            with scope.tasks.db() as db:
                tables(db)
                db.execute('INSERT OR IGNORE INTO pricing_operations VALUES (?,?,?,?,?,?,?,?,?)',
                           (ident,owner,task,action,payload_hash,ident,'pending',None,scope.clock().isoformat()))
                saved=db.execute('SELECT owner,task,action,payload_hash FROM pricing_operations WHERE id=?',(ident,)).fetchone()
                if tuple(saved)!=(owner,task,action,payload_hash):
                    raise ValueError('pricing_operation_payload_conflict')
        result=request('/pricing/v3/execute',owner,dict(request_key=ident,plan_id=args['plan_id']))
        with scope.tasks.db() as db:
            tables(db)
            db.execute('UPDATE pricing_operations SET state=?,result=? WHERE id=?',
                       ('accepted',json.dumps(result,ensure_ascii=False),ident))
        return result
    raise ValueError('pricing_tool_fields')

