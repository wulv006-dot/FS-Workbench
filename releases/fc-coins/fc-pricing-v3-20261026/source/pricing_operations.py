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
from urllib.parse import urlencode
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
    props['action']['description']='Use exactly the fields listed for this action: '+json.dumps({action:sorted(fields) for action,fields in FIELDS.items()},sort_keys=True)
    props['path']['description']='Required for read_quote: JSON pointer into the original quote, starting with /evidence, /result or /edits (for example /result/decision_receipt). Omit for state; state returns daily_review directly.'
    props['mode']['description']='Required for compare_strategies. Use an available mode from state.strategies or the returned available_modes; a saved smart run may contain only smart. This read never computes missing alternatives.'
    props['action_sha256']['description']='SHA256 of the exact candidate action canonical JSON from the same run; this selects the reviewed candidate, including a nondefault feasible candidate.'
    props['bundle_sha256']['description']='Original V3 decision receipt SHA256 from read_quote for run_id.'
    props['reason']['description']='Explain why this candidate serves the chosen objective, its actual order/AOV/cost and competitor basis, tradeoffs against alternatives, and missing evidence.'
    props['evidence_refs']={'type':'array','items':{'type':'string'},'description':'Include pricing:<bundle_sha256> and any inspected same-run evidence references.'}
    props['simulation_id']['description']='Original ID returned by simulate; read the result with simulation_read.'
    return {'type':'function','function':{'name':'mcp__fcro__fs_pricing_control','description':'FC27 Pricing V3 review and decision tool. state requires only action; read_quote requires action, run_id, path; compare_strategies requires action, mode. Other exact fields are listed in action.description and capabilities.action_fields. State returns the saved daily_review (missing historical profit fields remain unavailable), compact operation references and available strategy results; use operation_read for each full original operation. Use state, compare_strategies and the same-run quote receipt to inspect daily operations and revenue sprint, real paid-order/AOV and delivered-K units, dual 20% proofs, scope and missing evidence. State lists every action and its hash with compact score and margins; use candidate_detail with the exact run, mode and action hash for its full original proof. Hermes reviews effects once daily without recommend or price approval. Only separately authorized strategy research may record a candidate recommendation with its exact action hash and substantive reason. Routine cycles choose and reprove candidates in the program without waiting for Hermes. There are no pricing budgets or spending caps. Use operation_read and simulation_read for outcomes and historical review. Old 80/15/5 and parity are read-only historical replays, never current pricing rules. UNKNOWN must reconcile the original operation ID. Shadow projections are estimates, never observed profit or execution authority.','parameters':{'type':'object','properties':props,'required':['action'],'additionalProperties':False}}}



def tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS pricing_grants(conversation TEXT PRIMARY KEY,owner TEXT NOT NULL,mode TEXT NOT NULL,runs TEXT NOT NULL,expires_at TEXT NOT NULL,source TEXT NOT NULL,restore_sources TEXT NOT NULL)')
    # Keep the installed writer's seven-column contract usable after rollback.
    db.execute('CREATE TABLE IF NOT EXISTS pricing_grant_sources(conversation TEXT PRIMARY KEY,source_quote_run TEXT,source_quote_sha256 TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS pricing_operations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,task TEXT NOT NULL,action TEXT NOT NULL,payload_hash TEXT NOT NULL,request_id TEXT NOT NULL,state TEXT NOT NULL,result TEXT,created_at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS pricing_recommendations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,task TEXT NOT NULL,conversation TEXT NOT NULL,run_id TEXT NOT NULL,quote_sha256 TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL)')


def quote_reference(db,conversation):
    row=db.execute('SELECT source_quote_run,source_quote_sha256 FROM pricing_grant_sources WHERE conversation=?',(conversation,)).fetchone()
    return tuple(row) if row is not None else (None,None)


def grant(db,owner,conversation,run,mode,expires,source,restore_sources=(),*,source_quote_run=None,source_quote_sha256=None):
    if mode!='daily_review' or not re.fullmatch('[a-f0-9]{32}',conversation):
        raise ValueError('pricing_grant_scope')
    uuid.UUID(run)
    if source_quote_run is not None or source_quote_sha256 is not None:
        source_quote_run=str(uuid.UUID(source_quote_run))
        if not isinstance(source_quote_sha256,str) or not re.fullmatch('[a-f0-9]{64}',source_quote_sha256):
            raise ValueError('pricing_source_quote_binding_invalid')
    if len(restore_sources)>1 or restore_sources and mode!='operator_workflow':raise ValueError('pricing_restore_grant_scope')
    sources=json.dumps([str(uuid.UUID(value)) for value in restore_sources])
    values=(owner,mode,json.dumps([run]),expires,source,sources)
    reference=(source_quote_run,source_quote_sha256)
    own_transaction=not db.in_transaction
    db.execute('BEGIN IMMEDIATE' if own_transaction else 'SAVEPOINT pricing_grant_binding')
    try:
        tables(db)
        old=db.execute('SELECT owner,mode,runs,expires_at,source,restore_sources FROM pricing_grants WHERE conversation=?',(conversation,)).fetchone()
        if old is not None and (tuple(old)!=values or quote_reference(db,conversation)!=reference):
            raise ValueError('pricing_grant_conflict')
        db.execute('INSERT OR IGNORE INTO pricing_grants(conversation,owner,mode,runs,expires_at,source,restore_sources) VALUES(?,?,?,?,?,?,?)',(conversation,*values))
        db.execute('INSERT OR IGNORE INTO pricing_grant_sources VALUES(?,?,?)',(conversation,*reference))
        if own_transaction:db.commit()
        else:db.execute('RELEASE pricing_grant_binding')
    except Exception:
        if own_transaction:db.rollback()
        else:
            db.execute('ROLLBACK TO pricing_grant_binding')
            db.execute('RELEASE pricing_grant_binding')
        raise


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
        reference=quote_reference(db,bindings[0])
    if r is None:return None
    value=dict(r,source_quote_run=reference[0],source_quote_sha256=reference[1])
    if datetime.fromisoformat(value['expires_at'])<=now:
        if value['mode']=='daily_review':raise PermissionError('pricing_daily_grant_expired')
        return None
    value['runs']=json.loads(value['runs'])
    value['restore_sources']=json.loads(value['restore_sources'])
    return value


def call(scope,owner,task,lease,args,request=native):
    scope.context(owner,task,lease)
    action=args.get('action') if isinstance(args,dict) else None
    if action not in ACTIONS or set(args)!=FIELDS[action]:
        return dict(status='invalid_arguments',error_code='pricing_tool_fields',
                    required_fields=sorted(FIELDS.get(action,{'action'})),execution_authorized=False,
                    help='Pass exactly the required_fields for this action; state takes only action. read_quote requires a path such as /result/decision_receipt.')
    auth=authorization(scope,owner,task,scope.clock())
    daily=bool(auth and auth['mode']=='daily_review')
    bound=bool(daily and auth.get('source_quote_run') and auth.get('source_quote_sha256'))
    if daily and action=='compare_strategies' and not bound:
        raise ValueError('pricing_daily_compare_basis_unavailable')
    allowed=list(set(ACTIONS)-MUTATING-({'compare_strategies'} if not bound else set()) if daily else AUTO if auth and auth['mode']=='automatic_review' else ACTIONS if auth else
                 set(ACTIONS)-MUTATING)
    if action not in allowed:
        raise PermissionError('pricing_task_not_authorized')
    if action=='capabilities':
        return dict(version='fc-pricing-v3-20261026',allowed_actions=allowed,
                    action_fields={a:sorted(FIELDS[a]) for a in allowed},scoped_runs=auth['runs'] if auth else [],
                     source_quote_run=auth.get('source_quote_run') if daily else None,
                     source_quote_sha256=auth.get('source_quote_sha256') if daily else None,
                    separate_shadow=True,unknown_replay=False,hard_margin_pct='20',average_hard_margin_pct='20')
    state_path='/pricing/v3/review-state'
    if daily and action=='state':
        if len(auth['runs'])!=1:raise ValueError('pricing_daily_review_request_invalid')
        state_path+='/'+str(uuid.UUID(auth['runs'][0]))
    state=request(state_path,owner) if action in ('state','sprint_target') else None
    if action=='state':
        return state
    if action=='compare_strategies':
        if daily:
            run=auth['source_quote_run']
            decisions=request('/pricing/v3/strategy-decisions/'+run,owner)
            if decisions.get('snapshot_id')!=run or decisions.get('snapshot_sha256')!=auth['source_quote_sha256']:
                raise ValueError('pricing_review_run_basis_changed')
            if args['mode'] not in decisions.get('results',{}):
                return dict(status='invalid_arguments',error_code='pricing_review_mode_unavailable',
                            snapshot_id=run,available_modes=sorted(decisions.get('results',{})),execution_authorized=False,
                            help='Only these modes were calculated for the original snapshot; select one to read its saved result.')
            return dict(snapshot_id=run,snapshot_sha256=auth['source_quote_sha256'],
                        results={args['mode']:decisions['results'][args['mode']]},
                        execution_authorized=False,source='original_run_strategy_decisions')
        if auth and auth['mode'] in ('automatic_review','daily_review'):
            if len(auth['runs'])!=1:
                raise ValueError('pricing_review_run_scope_invalid')
            run=auth['runs'][0]
            decisions=request('/pricing/v3/strategy-decisions/'+run,owner)
            if decisions.get('snapshot_id')!=run:
                raise ValueError('pricing_review_run_basis_changed')
            if args['mode'] not in decisions.get('results',{}):
                return dict(status='invalid_arguments',error_code='pricing_review_mode_unavailable',
                            snapshot_id=run,available_modes=sorted(decisions.get('results',{})),execution_authorized=False)
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
        path=args['path']
        if not isinstance(path,str) or not path.startswith('/') or path.split('/')[1] not in ('evidence','result','edits'):
            raise ValueError('pricing_quote_path_invalid')
        fragment=request('/quotes/'+run+'?'+urlencode({'path':path}),owner)
        if (fragment.get('run_id')!=run or fragment.get('path')!=path or
                not re.fullmatch('[a-f0-9]{64}',str(fragment.get('original_quote_sha256',''))) or
                fragment.get('execution_authorized') is not False or 'value' not in fragment):
            raise ValueError('pricing_quote_fragment_basis_changed')
        return fragment
    if action=='candidate_detail':
        run=str(uuid.UUID(args['run_id']))
        mode=args['mode']
        action_sha=args['action_sha256']
        if mode not in ('daily','revenue_sprint') or not re.fullmatch('[a-f0-9]{64}',action_sha):
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
            current=request('/pricing/v3/review-state',owner)
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

