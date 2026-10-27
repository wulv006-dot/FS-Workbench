"""V3 endpoints behind the existing FS authentication and writer roles."""
from datetime import datetime, timezone, timedelta
from contextlib import closing
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid

from . import VERSION
from .engine import evaluate, POLICIES
from .financial import fingerprint, instant, number
from .ledger import clock
from .runtime import ledger, STORE, public_snapshot_summary

SHADOW_DB=Path('/var/lib/fc-pricing-v3-shadow/shadow.sqlite3')


def request_id(actor, data, action):
    key=data.get('request_key')
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',key):
        raise ValueError('pricing_request_key_invalid')
    return str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-pricing-v3:'+action+':'+actor+':'+key))


def shadow_database():
    path=SHADOW_DB
    return sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) if path.exists() else None


def original_restore_prices(operation_id):
    from .runtime import ROOT
    ident=str(uuid.UUID(operation_id))
    audit_path=ROOT/'executions'/(ident+'.json')
    if not audit_path.exists():
        raise ValueError('pricing_restore_original_missing')
    audit=json.loads(audit_path.read_text())
    if audit.get('execution_id')!=ident or audit.get('status')!='CONFIRMED' or audit.get('sync_confirmed') is not True:
        raise ValueError('pricing_restore_original_unconfirmed')
    rows=(audit.get('before') or {}).get('rows') or []
    by={r['platform']:r for r in rows if r.get('platform') in ('PS','XBOX','PC') and r.get('b2c') is not None}
    if len(rows)!=3 or set(by)!={'PS','XBOX','PC'} or number(by['PS']['b2c'])!=number(by['XBOX']['b2c']):
        raise ValueError('pricing_restore_original_scope_invalid')
    return dict(console=str(number(by['PS']['b2c'])*100),pc=str(number(by['PC']['b2c'])*100))


def history_view(result):
    records=[]
    for row in result['records']:
        value={key:row[key] for key in ('snapshot_id','status','fixed_order_count','order_window','effect_usd','estimand','uncertainty','assumptions','as_of','revised_order_count','cumulative_actual') if key in row}
        if 'actual' in row:
            value['actual']=row['actual']
        if 'alternatives' in row:
            value['alternatives']={name:{key:item[key] for key in ('status','totals','assumptions','source_sha256','legacy_replay_status','as_of','reason') if key in item}
                                   for name,item in row['alternatives'].items()}
        if 'path' in row:
            path=row['path']
            value['path']={key:path.get(key) for key in ('policy','last_as_of','revenue','contribution','paid_orders','new_customers','backlog_k','effective_mode')}
        if row.get('gaps'):
            counts=Counter(gap.get('reason','unavailable') if isinstance(gap,dict) else gap for gap in row['gaps'])
            value['gaps']=[reason+(' ('+str(count)+')' if count>1 else '') for reason,count in counts.items()]
        records.append(value)
    view={key:result[key] for key in ('simulation_id','simulation_kind','rule_mode','created_at','execution_authorized','training_eligible')} | {'records':records}
    for key in ('requested_closed_days','paid_window','coverage'):
        if key in result:
            view[key]=result[key]
    if result.get('reconciled_actual'):
        view['reconciled_actual']=result['reconciled_actual']
    return view



def latest(db, public=False):
    if public:
        summary=db.get('metadata','latest_snapshot_summary')
        if summary:
            return summary
    with closing(db.connect()) as conn:
        for row in conn.execute('SELECT body FROM pricing_snapshots ORDER BY rowid DESC'):
            snapshot=json.loads(row[0])
            if snapshot.get('authorization_purpose') in ('original_unsent_ALL_steps_only','retire_uk_discount_v1'):
                continue
            if not public:
                return snapshot
            return public_snapshot_summary(dict(snapshot,result=snapshot.get('result') or {'rows':[]}))
    return None


def recent_market_observations(db):
    with closing(db.connect()) as conn:
        return [json.loads(row[0]) for row in conn.execute(
            'SELECT body FROM market_observations ORDER BY rowid DESC LIMIT 5')]


def strategy_summary(decisions):
    """Keep every selectable action while leaving repeated proofs in the private ledger."""
    result={}
    for mode,decision in (decisions or {}).items():
        candidates=[]
        for candidate in decision.get('candidates',[]):
            proof=candidate.get('financial_proof') or {}
            prices=proof.get('prices') or {}
            margins={key:{field:value for field,value in (row.get('catalog') or {}).items()
                          if field in ('minimum_estimated_average_margin_pct','minimum_undiscounted_margin_pct')}
                     for key,row in prices.items()}
            candidates.append(dict(action=candidate.get('action'),action_sha256=candidate.get('action_sha256'),
                                   score=candidate.get('score'),financial_proof=dict(pass_all=proof.get('pass_all'),
                                   minimum_pct=proof.get('minimum_pct'),margins=margins)))
        selected=decision.get('selected')
        result[mode]={key:value for key,value in decision.items()
                      if key not in ('candidates','selected')}
        result[mode]['candidates']=candidates
        result[mode]['selected']=selected
    return result


def shadow_projection(row):
    fields=('snapshot_id','external_snapshot_id','as_of','last_as_of','policy','sequence','revenue','contribution',
            'paid_orders','new_customers','delivered_k','backlog_k','effective_mode','simulation_kind','model_version',
            'policy_version','assumptions','status','reason')
    value={key:row[key] for key in fields if key in row}
    decision=row.get('result') or row.get('last_result') or {}
    selected=decision.get('selected') or {}
    value.update(result=dict(status=decision.get('status'),action=selected.get('action'),score=selected.get('score'),
                 candidate_count=len(decision.get('candidates',[]))),gaps=row.get('gaps',[])[-10:],
                 original_record_sha256=fingerprint(row),execution_authorized=False,training_eligible=False)
    return value


def read(path):
    if path=='versions':
        folder=Path(__file__).parent
        from .legacy_simulation import SOURCES
        return dict(version=VERSION,engine_sha256=hashlib.sha256((folder/'engine.py').read_bytes()).hexdigest(),
                    financial_sha256=hashlib.sha256((folder/'financial.py').read_bytes()).hexdigest(),
                    legacy_sources={name:hashlib.sha256((folder/'legacy_simulation'/filename).read_bytes()).hexdigest()
                                    for name,(filename,_) in SOURCES.items()},
                    execution_authorized=False)
    db=ledger()
    snapshot=latest(db,public=True) if path in ('state','','region-rules','market') else None
    if path in ('state',''):
        target=(snapshot or {}).get('evidence',{}).get('monthly_target') or {}
        configured=db.get('monthly_targets','current')
        if configured:
            target=dict(target,amount=configured['amount'],target_scope=configured['target_scope'],target_basis=configured['target_basis'],currency='USD')
        return dict(version=VERSION,generation=db.generation(),plan=db.active_plan(),
                    plans=sorted(db.all('pricing_plans'),key=lambda p:p['created_at'],reverse=True),active_plans=db.active_plans(),
                    snapshot_id=snapshot['snapshot_id'] if snapshot else None,
                    captured_at=snapshot['created_at'] if snapshot else None,
                    strategies=strategy_summary(db.get('strategy_decisions',snapshot['snapshot_id'])) if snapshot else {},
                    operations=sorted(db.all('operations'),key=lambda o:o['created_at'],reverse=True)[:30],
                    incidents=db.all('incidents'),target=target,
                    region_rules=(snapshot or {}).get('evidence',{}).get('region_rules',[]),
                    regional_controls=(snapshot or {}).get('evidence',{}).get('regional_controls',[]),
                    current_prices=(snapshot or {}).get('result',{}).get('rows',[]),
                    latest_market_observations=recent_market_observations(db),
                    daily_review=db.get('metadata','latest_daily_review'),retirement=db.all('retirement_inventory'),effect_status='long_term_business_effect_not_established')
    if path=='daily-review':
        return db.get('metadata','latest_daily_review') or dict(status='not_started',schedule='daily_02:20_Asia_Shanghai',per_cycle_model_required=False)
    if path=='strategies':
        return dict(version=VERSION,strategies=POLICIES)
    if path.startswith('strategy-decisions/'):
        parts=path.split('/')
        if len(parts) not in (2,4):
            raise ValueError('pricing_strategy_decision_path_invalid')
        ident=str(uuid.UUID(parts[1]))
        decisions=db.get('strategy_decisions',ident)
        observed=db.get('pricing_snapshots',ident)
        if not decisions or not observed or observed.get('origin')!='live_collector':
            raise ValueError('pricing_strategy_decision_missing')
        result=dict(snapshot_id=ident,snapshot_sha256=fingerprint(observed['evidence']),
                    strategy_version=observed.get('policy_version'),execution_authorized=False)
        if len(parts)==4:
            mode,action_sha=parts[2:]
            if mode not in POLICIES or not re.fullmatch('[a-f0-9]{64}',action_sha):
                raise ValueError('pricing_strategy_candidate_invalid')
            candidate=next((item for item in decisions.get(mode,{}).get('candidates',[])
                            if item.get('action_sha256')==action_sha),None)
            if candidate is None:
                raise ValueError('pricing_strategy_candidate_missing')
            return dict(result,candidate=candidate,mode=mode)
        return dict(result,results=strategy_summary(decisions))
    if path.startswith('legacy-replay/'):
        from .legacy_simulation import replay, SOURCES
        parts=path.split('/')
        if len(parts)!=3 or not re.fullmatch(r'[0-9a-f-]{36}',parts[1]) or parts[2] not in SOURCES:
            raise ValueError('pricing_legacy_replay_request_invalid')
        original=db.get('pricing_snapshots',parts[1])
        if original is None:raise ValueError('pricing_legacy_replay_snapshot_missing')
        return dict(replay(original,parts[2]),snapshot_id=parts[1],legacy_policy=parts[2],read_only=True,execution_authorized=False)
    if path=='plans':
        return dict(plans=sorted(db.all('pricing_plans'),key=lambda p:p['created_at'],reverse=True))
    if path=='region-rules':
        return dict(rules=(snapshot or {}).get('evidence',{}).get('region_rules',[]),
                    contract=(snapshot or {}).get('evidence',{}).get('region_contract'))
    if path=='market':
        from .engine import price_basis
        original=db.get('pricing_snapshots',snapshot['snapshot_id']) if snapshot else None
        try:basis=price_basis(original['evidence'],instant(original['created_at'])) if original else dict(status='unavailable')
        except (ValueError,KeyError,TypeError) as error:basis=dict(status='unavailable',reason=str(error) if isinstance(error,ValueError) else type(error).__name__)
        reference=dict((snapshot or {}).get('evidence',{}).get('reference_market') or {})
        return dict(snapshot_id=(snapshot or {}).get('snapshot_id'),
                    global_offers=(snapshot or {}).get('evidence',{}).get('offers'),
                    reference=reference,
                    arab=(snapshot or {}).get('evidence',{}).get('arab_ut_quotes',[]),price_basis=basis,
                    saudi_missing_price_policy='follow_global')
    if path=='experiments':
        return dict(assignments=db.all('experiment_assignments'),exposure=db.all('actual_price_windows'))
    if path=='incidents':
        return dict(incidents=db.all('incidents'))
    if path=='retirement':
        return dict(generation=db.generation(),items=db.all('retirement_inventory'))
    if path.startswith('operations/'):
        op=db.get('operations',path.split('/')[-1])
        if not op:
            raise ValueError('pricing_operation_missing')
        return op
    if path=='shadow':
        conn=shadow_database()
        if conn is None:
            return dict(status='not_started',mode='shadow')
        try:
            paths=[shadow_projection(json.loads(r[0])) for r in conn.execute('SELECT body FROM paths')]
            return dict(status='available' if paths else 'not_started',mode='shadow',cadence='daily_saved_snapshots',paths=paths,
                        comparisons=[shadow_projection(json.loads(r[0])) for r in conn.execute('SELECT body FROM runs ORDER BY rowid DESC LIMIT 10')])
        finally:
            conn.close()
    if path=='shadow/summary':
        conn=shadow_database()
        if conn is None:
            return dict(status='not_started',summaries=[])
        try:
            return dict(status='available',summaries=[json.loads(r[0]) for r in conn.execute('SELECT body FROM summaries ORDER BY rowid DESC LIMIT 150')])
        finally:
            conn.close()
    if path.startswith('simulations/'):
        ident=path.split('/')[-1]
        if not re.fullmatch(r'[0-9a-f-]{36}',ident):
            raise ValueError('pricing_simulation_id_invalid')
        request=db.get('metadata','simulation:'+ident)
        pending=dict(status=(request or {}).get('phase','queued_or_missing'),simulation_id=ident,
            paid_window=(request or {}).get('paid_window'),coverage=(request or {}).get('coverage'),
            original_shadow_request=(request or {}).get('shadow'),execution_authorized=False)
        conn=shadow_database()
        if conn is None:
            return pending
        try:
            row=conn.execute('SELECT body FROM history WHERE id=?',(ident,)).fetchone()
            return history_view(json.loads(row[0])) if row else pending
        finally:
            conn.close()
    if path.startswith('manual-previews/'):
        ident=path.split('/')[-1]
        if not re.fullmatch(r'[0-9a-f-]{36}',ident):
            raise ValueError('pricing_manual_preview_id_invalid')
        result=db.get('manual_previews',ident)
        if not result:
            raise ValueError('pricing_manual_preview_missing')
        return result
    raise ValueError('pricing_v3_route_missing')


def post(path,data,actor):
    if path=='interval':
        if not isinstance(data,dict) or set(data)!={'interval_minutes','expected_revision'}:
            raise ValueError('pricing_interval_request_invalid')
        from automation_policy import load_policy,save_policy
        current=load_policy()
        settings={key:current[key] for key in ('system_enabled','mode','interval_minutes','platforms','minimum_gross_margin_pct')}
        settings['interval_minutes']=data['interval_minutes']
        updated=save_policy(settings,actor,data['expected_revision'])
        return dict(interval_minutes=updated['interval_minutes'],revision=updated['revision'],updated_at=updated['updated_at'],
                    plan_state=(ledger().active_plan() or {}).get('state'),write_performed=False)
    db=ledger()
    if path=='retire-uk-discount':
        if set(data)!={'request_key','plan_id'}:raise ValueError('pricing_uk_retirement_fields_invalid')
        ident=request_id(actor,data,'retire-uk-discount');key='uk-retirement:'+ident
        saved=db.get('metadata',key)
        if saved:
            if saved['request_sha256']!=fingerprint(data):raise ValueError('pricing_uk_retirement_payload_conflict')
            return saved['response']
        plan=db.get('pricing_plans',data['plan_id'])
        if not plan or plan['state']!='ACTIVE':raise ValueError('pricing_uk_retirement_plan_inactive')
        with db.transaction() as conn:
            db.owns(plan,['base:console','base:pc'],conn)
            response=dict(status='queued',job_key=key,operation_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-uk-retirement:'+key)))
            db.put('metadata',key,dict(request_sha256=fingerprint(data),response=response),conn)
            db.enqueue('uk_retirement',key,clock(),dict(plan_id=plan['plan_id'],revision=plan['revision'],actor=actor),conn)
        return response
    snapshot=latest(db) if path in ('plans','evaluate','preview','manual-previews') else None
    if path=='plans':
        if set(data)-{'request_key','mode','resources','parameters','starts_at','ends_at'}:
            raise ValueError('pricing_plan_fields_invalid')
        mode=data['mode']
        if mode not in POLICIES:
            raise ValueError('pricing_strategy_unknown')
        ident=request_id(actor,data,'plan')
        client_hash=fingerprint(data)
        existing=db.get('pricing_plans',ident)
        if existing and existing.get('client_request_sha256') not in (None,client_hash):
            raise ValueError('pricing_plan_payload_conflict')
        if existing and existing.get('client_request_sha256')==client_hash:
            return existing
        if not snapshot:
            raise ValueError('pricing_snapshot_required')
        resources=data.get('resources',['base:console','base:pc'])
        allowed={'base:console','base:pc'}|{r['resource'] for r in snapshot['evidence'].get('regional_controls',[])
                                            if r.get('resource') and r.get('region_id')==21}
        if set(resources)-allowed:
            raise ValueError('pricing_plan_scope_invalid')
        resources=sorted(set(resources))
        anchor={'base_prices':{g:str(max(number(snapshot['evidence']['storefront']['rows'][p]['package_usd']) for p in ps))
                               for g,ps in {'console':('PS','XBOX'),'pc':('PC',)}.items()},
                'region_coefficients':{str(r['region_id'])+':'+p:str(r['factor']) for r in snapshot['evidence'].get('region_rules',[]) for p in r['platforms']}}
        if existing:
            resources,anchor=existing['resources'],existing['price_anchor']
        parameters=data.get('parameters') or {}
        if not isinstance(parameters,dict) or set(parameters)-({'allocation','offsets_pct','capacity_reserve_ratio'} if mode=='backlog' else {'allocation','preferred_undercut_pct','sprint_policy_version'} if mode=='revenue_sprint' else {'allocation','offsets_pct'}):
            raise ValueError('pricing_plan_parameters_invalid')
        plan=db.create_plan(mode,resources,anchor,starts_at=data.get('starts_at'),ends_at=data.get('ends_at'),
                            actor=actor,parameters=parameters,plan_id=ident)
        if plan.get('client_request_sha256')!=client_hash:
            plan['client_request_sha256']=client_hash
            db.put('pricing_plans',ident,plan)
        return plan
    if path=='monthly-target':
        ident=request_id(actor,data,'monthly-target')
        amount=data.get('amount')
        if amount is not None:
            amount=str(number(amount,zero=True))
        if data.get('currency','USD')!='USD' or data.get('target_basis','net_paid_USD')!='net_paid_USD':
            raise ValueError('pricing_target_basis_invalid')
        scope=data.get('target_scope','site266_FC27_Coins')
        if scope!='site266_FC27_Coins':
            raise ValueError('pricing_target_scope_invalid')
        value=dict(request_id=ident,version=ident,request_sha256=fingerprint(data),amount=amount,currency='USD',
                   target_basis='net_paid_USD',target_scope=scope,actor=actor,updated_at=clock().isoformat())
        old=db.get('target_adjustments',ident)
        if old:
            if old['request_sha256']!=value['request_sha256']:
                raise ValueError('pricing_target_payload_conflict')
            return old
        with db.transaction() as conn:
            db.put('target_adjustments',ident,value,conn)
            db.put('monthly_targets','current',value,conn)
        return value
    if path.startswith('plans/'):
        _,ident,action=path.split('/')
        if action=='migrate-financial-contract':
            if set(data)!={'expected_revision'}:raise ValueError('pricing_migration_fields_invalid')
            return db.migrate_financial_contract(ident,data['expected_revision'],actor)
        if action=='activate':
            result=db.activate_plan(ident)
            db.enqueue('cycle','initial:'+ident,clock(),dict(plan_id=ident,revision=result['revision']))
            return result
        if action=='stop':
            plan=db.get('pricing_plans',ident)
            if not plan:
                raise ValueError('pricing_plan_missing')
            return db.deadline(ident,plan['revision'])
        if action in ('pause','resume'):
            plan=db.get('pricing_plans',ident)
            if not plan:
                raise ValueError('pricing_plan_missing')
            if action=='resume' and plan.get('ends_at') and clock()>=instant(plan['ends_at']):
                raise ValueError('pricing_plan_expired')
            if action=='resume':
                from .financial import FINANCIAL_CONTRACT_VERSION
                from .engine import sprint_parameters
                if plan.get('financial_contract_version')!=FINANCIAL_CONTRACT_VERSION:raise ValueError('pricing_financial_plan_migration_required')
                if plan['mode']=='revenue_sprint':sprint_parameters(plan)
            desired='SUSPENDED' if action=='pause' else 'ACTIVE'
            if plan['state']==desired:
                return plan
            if plan['state']!=('ACTIVE' if action=='pause' else 'SUSPENDED'):
                raise ValueError('pricing_plan_state_invalid')
            with db.connect() as conn:
                db.owns(plan,plan['resources'],conn)
            plan['state']=desired
            if action=='resume':
                plan['resume_count']=plan.get('resume_count',0)+1
                plan['resumed_at']=clock().isoformat()
            else:
                plan['paused_at']=clock().isoformat()
            db.put('pricing_plans',ident,plan)
            return plan
    if path in ('evaluate','preview'):
        if not snapshot:
            raise ValueError('pricing_snapshot_required')
        modes=[data['mode']] if data.get('mode') else list(POLICIES)
        plan=db.get('pricing_plans',data['plan_id']) if data.get('plan_id') else None
        return dict(results={m:evaluate(snapshot['evidence'],m,plan=plan if plan and plan['mode']==m else None) for m in modes},
                    execution_authorized=False,write_performed=False,snapshot_id=snapshot['snapshot_id'])
    if path=='manual-previews':
        ident=request_id(actor,data,'manual-preview')
        request_hash=fingerprint(data)
        old=db.get('manual_previews',ident)
        if old:
            if old['request_sha256']!=request_hash:
                raise ValueError('pricing_manual_preview_payload_conflict')
            return old
        if not snapshot:
            raise ValueError('pricing_snapshot_required')
        reason=data.get('reason')
        if not isinstance(reason,str) or not 4<=len(reason.strip())<=200:
            raise ValueError('pricing_manual_reason_required')
        restore_id=data.get('restore_source_execution_id')
        if bool(restore_id)==bool(data.get('explicit_prices')):
            raise ValueError('pricing_manual_action_source_invalid')
        plan=db.get('pricing_plans',data['plan_id']) if data.get('plan_id') else db.active_plan()
        if not plan:
            raise ValueError('pricing_plan_required')
        prices=original_restore_prices(restore_id) if restore_id else data['explicit_prices']
        if not isinstance(prices,dict) or not prices or set(prices)-{'console','pc'}:
            raise ValueError('pricing_manual_price_fields')
        if restore_id:
            prices={group:value for group,value in prices.items() if 'base:'+group in plan['resources']}
        if not prices:
            raise ValueError('pricing_manual_scope_not_owned')
        prices={group:str(number(value)) for group,value in prices.items()}
        from .runtime import override_quote
        proof=override_quote(snapshot['evidence'],prices,reason.strip(),restore_id,plan)
        record=dict(proof,manual_preview_id=ident,operation_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-pricing-v3:manual-operation:'+ident)),
                    request_sha256=request_hash,actor=actor,created_at=clock().isoformat(),snapshot_id=snapshot['snapshot_id'],
                    explicit_prices=prices,reason=reason.strip(),restore_source_execution_id=restore_id,
                    execution_authorized=False,write_performed=False)
        db.put('manual_previews',ident,record)
        return record
    if path=='execute':
        key='manual:'+request_id(actor,data,'execute')
        accepted=db.get('metadata',key)
        if accepted:
            if accepted['request_sha256']!=fingerprint(data):
                raise ValueError('pricing_execute_payload_conflict')
            with db.connect() as conn:
                job=conn.execute('SELECT state FROM durable_jobs WHERE id=?',(key,)).fetchone()
            return dict(status=job[0] if job else 'confirmation_pending',job_key=key,
                        manual_preview_id=accepted['body'].get('manual_preview_id'))
        plan=db.get('pricing_plans',data['plan_id']) if data.get('plan_id') else db.active_plan()
        if not plan or plan['state']!='ACTIVE' or plan not in db.active_plans():
            raise ValueError('pricing_plan_required')
        preview_id=data.get('manual_preview_id')
        if preview_id:
            preview=db.get('manual_previews',str(uuid.UUID(preview_id)))
            if not preview or preview['actor']!=actor or preview['plan_id']!=plan['plan_id']:
                raise ValueError('pricing_manual_preview_scope_invalid')
            if clock()>=instant(preview['valid_until']):
                raise ValueError('pricing_manual_preview_expired')
        body=dict(plan_id=plan['plan_id'],revision=plan['revision'],actor=actor,manual_requested=True,
                  manual_preview_id=preview_id,request_id=key)
        with db.transaction() as conn:
            old=db.get('metadata',key,conn)
            if old and old['request_sha256']!=fingerprint(data):
                raise ValueError('pricing_execute_payload_conflict')
            if not old:
                db.put('metadata',key,dict(request_sha256=fingerprint(data),body=body),conn)
            db.enqueue('cycle',key,clock(),body,conn)
        return dict(status='queued',job_key=key,manual_preview_id=preview_id)
    if path.startswith('reconcile/'):
        ident=path.split('/')[-1]
        if not db.get('operations',ident):
            raise ValueError('pricing_operation_missing')
        key='operator-reconcile:'+request_id(actor,data,'reconcile:'+ident)
        db.enqueue('reconcile',key,clock(),dict(operation_id=ident))
        return dict(status='queued',operation_id=ident)
    if path=='simulations':
        if data.get('kind') not in ('actual_reconstruction','fixed_orders_reprice','demand_counterfactual','causal_evaluation') or data.get('closed_days',7) not in (7,14,28,'month'):
            raise ValueError('pricing_simulation_request_invalid')
        from .simulation import historical_window
        ident=request_id(actor,data,'simulation');requested=clock().isoformat()
        with db.transaction() as conn:
            old=db.get('metadata','simulation:'+ident,conn)
            if old and old['request_sha256']!=fingerprint(data):raise ValueError('pricing_simulation_payload_conflict')
            if not old:
                old=dict(request_sha256=fingerprint(data),simulation_id=ident,kind=data['kind'],closed_days=data.get('closed_days',7),
                    requested_at=requested,actor=actor,phase='queued',**historical_window(data.get('closed_days',7),requested))
                db.put('metadata','simulation:'+ident,old,conn)
                db.enqueue('history','history:'+ident,clock(),dict(simulation_id=ident),conn)
        return dict(status=old['phase'],simulation_id=ident,paid_window=old['paid_window'],execution_authorized=False)
    raise ValueError('pricing_v3_route_missing')
