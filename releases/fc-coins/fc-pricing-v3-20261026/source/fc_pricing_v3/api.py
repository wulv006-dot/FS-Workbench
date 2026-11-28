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
from .dispatch import CURVE_WRITE_PROTOCOL
from .engine import evaluate, PLATFORMS, POLICIES
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
    if (audit.get('execution_id')!=ident or audit.get('status')!='CONFIRMED'
            or audit.get('sync_confirmed') is not True or audit.get('write_protocol') is not None):
        raise ValueError('pricing_restore_original_unconfirmed')
    rows=(audit.get('before') or {}).get('rows') or []
    by={r['platform']:r for r in rows if r.get('platform') in ('PS','XBOX','PC') and r.get('b2c') is not None}
    if len(rows)!=3 or set(by)!={'PS','XBOX','PC'}:
        raise ValueError('pricing_restore_original_scope_invalid')
    return {p:str(number(by[p]['b2c'])*100) for p in ('PS','XBOX','PC')}


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
        snapshot = _latest_snapshot(conn)
    if public and snapshot:
        return public_snapshot_summary(dict(snapshot,result=snapshot.get('result') or {'rows':[]}))
    return snapshot


def _owned_curve_snapshot(db, plan):
    latest = db.get('metadata', 'latest_snapshot:' + plan['plan_id']) or {}
    sources = ((latest.get('snapshot_id'), (plan['plan_id'],)),
               (plan.get('curve_activation_snapshot_id'), (plan['plan_id'], None)))
    for ident, owners in sources:
        snapshot = db.get('pricing_snapshots', ident) if ident else None
        if (snapshot and snapshot.get('snapshot_id') == ident
                and snapshot.get('write_protocol') == CURVE_WRITE_PROTOCOL
                and snapshot.get('plan_id') in owners):
            return snapshot
    return None


def _curve_decision(snapshot, plan):
    if not snapshot or snapshot.get('plan_id') != plan['plan_id']:
        return None
    result = snapshot.get('result') or {}
    rows = []
    for row in result.get('rows', []):
        selection = row.get('selection') or {}
        chosen = {key: selection[key] for key in ('segment', 'label', 'reference_anchors', 'normal_anchors',
                                                   'final_anchors', 'cost_protection', 'large_market_reference', 'external_change') if key in selection}
        margin_band = selection.get('margin_band') or {}
        if margin_band and snapshot.get('plan_revision') == plan['revision']:
            if margin_band.get('promotion_guard'):
                chosen['promotion_guard'] = margin_band['promotion_guard']
            chosen['margin_band'] = dict(target=margin_band.get('target'), bands={
                band: {key: margin.get(key) for key in ('margin_at_current', 'business_margin_at_current',
                      'margin_at_target', 'business_margin_at_target', 'capped_by_market', 'action') if key in margin}
                for band, margin in (margin_band.get('bands') or {}).items() if band in ('small', 'large')
            })
        costs = selection.get('cost_by_band') or margin_band.get('cost_by_band')
        if costs:
            chosen['cost_by_band'] = costs
        actual_label = (selection.get('assignment') or {}).get('actual_label')
        if actual_label:
            chosen['actual_label'] = actual_label
        rows.append(dict(platform=row['platform'], status=row['status'], gaps=row.get('gaps', []), selection=chosen))
    return dict(status=result.get('status'), rows=rows) if rows else None


def _latest_snapshot(conn, *, curve=False):
    candidate = None
    for row in conn.execute('SELECT body FROM pricing_snapshots ORDER BY rowid DESC'):
        snapshot = json.loads(row[0])
        if (snapshot.get('authorization_purpose') in ('original_unsent_ALL_steps_only','retire_uk_discount_v1')
                or snapshot.get('curve_restore_preview_id')):
            continue
        if snapshot.get('write_protocol') == CURVE_WRITE_PROTOCOL:
            if curve:
                return snapshot
        elif not curve:
            return snapshot
        elif candidate is None:
            candidate = snapshot
    return candidate


def _curve_preview_history(conn, snapshot, as_of, *, require_snapshot_binding=True):
    from .business_source import historical_period

    snapshot_at = instant(snapshot['created_at'])
    window = historical_period('7d', now=snapshot_at)['paid_window']
    selected, selected_at = None, None
    conflict = False
    for row in conn.execute('SELECT body FROM historical_inputs ORDER BY rowid DESC'):
        attachment = json.loads(row[0])
        if (attachment.get('schema_version') != 'fc-pricing-v3-history-input-v1'
                or attachment.get('paid_window') != window
                or require_snapshot_binding and snapshot['snapshot_id'] not in attachment.get('snapshot_ids', ())):
            continue
        available = instant(attachment['available_at'])
        if available > as_of:
            continue
        if selected_at is None or available > selected_at:
            selected, selected_at = attachment, available
            conflict = False
        elif available == selected_at and attachment['source_sha256'] != selected['source_sha256']:
            conflict = True
    if conflict:
        raise ValueError('pricing_curve_preview_history_revision_conflict')
    return selected


def recent_market_observations(db):
    from .competitor_offers import MONITORING_SOURCES
    with closing(db.connect()) as conn:
        results = []
        for (raw,) in conn.execute('SELECT body FROM market_observations ORDER BY rowid DESC LIMIT 5'):
            result = json.loads(raw)
            if 'package_offers' in result:
                result['package_offers'] = [row for row in result['package_offers']
                                            if row.get('source') in MONITORING_SOURCES]
            if 'package_status' in result:
                result['package_status'] = {source: info for source, info in result['package_status'].items()
                                            if source in MONITORING_SOURCES}
            if 'retired_automatic_sources' in result:
                result['retired_automatic_sources'] = [source for source in result['retired_automatic_sources']
                                                       if source != 'IGGM']
            results.append(result)
        return results


def strategy_summary(decisions):
    """Keep every selectable action while leaving repeated proofs in the private ledger."""
    result={}
    for mode,decision in (decisions or {}).items():
        if mode not in POLICIES and mode!='smart':continue
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


def catalogue_tiers(curve):
    return [{key: tier[key] for key in ('purchase_k','promised_bonus_k','native_price_usd')}
            for tier in (curve or {}).get('tiers', ()) if tier.get('purchase_k') in ('100','1000')]


def catalogue_readbacks(operations):
    observed = {}
    for operation in operations:
        if operation.get('status') != 'COMPLETED':
            continue
        receipt = operation.get('readback') or {}
        if (receipt.get('write_protocol') != CURVE_WRITE_PROTOCOL or receipt.get('status') != 'CONFIRMED'
                or receipt.get('execution_id') != operation['operation_id']):
            continue
        for platform, row in (receipt.get('curve_results') or {}).items():
            propagation = row.get('propagation') or {}
            if (platform not in PLATFORMS or platform in observed or propagation.get('status') != 'confirmed'
                    or row.get('operation_id') != operation['operation_id']):
                continue
            tiers = catalogue_tiers(row.get('actual_site266_curve'))
            if tiers and propagation.get('confirmed_at'):
                observed[platform] = dict(tiers=tiers, observed_at=propagation['confirmed_at'], basis='confirmed_readback')
    return observed


def manual_execution_progress(db, operations):
    """Project the original manual task, never a previous plan cycle."""
    from .runtime import ROOT

    with closing(db.connect()) as conn:
        saved = conn.execute("""SELECT id,state,attempt,body FROM durable_jobs
            WHERE kind='cycle' AND id LIKE 'manual:%' ORDER BY rowid DESC LIMIT 1""").fetchone()
    if not saved:
        return None
    key, status, attempt, raw = saved
    body = json.loads(raw)
    result = body.get('result') or {}
    progress = dict(job_key=key, plan_id=body.get('plan_id'), status=status, phase=status)
    if result.get('status') == 'original_operation_reconciliation_pending':
        return dict(progress, phase=result['status'])
    preview_id = body.get('manual_preview_id')
    preview = db.get('manual_previews', preview_id) if preview_id else None
    operation_id = ((preview or {}).get('operation_id')
                    or str(uuid.uuid5(uuid.NAMESPACE_URL, 'fc-v3-operation:' + key)))
    operation = next((row for row in operations if row['operation_id'] == operation_id), None)
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'fc-v3-collection:{key}:{attempt}'))
    job = {}
    if status == 'running':
        try:
            job = json.loads((ROOT / 'jobs' / (run_id + '.json')).read_text(encoding='utf-8'))
        except (FileNotFoundError, PermissionError):
            pass
    if job.get('job_id') == run_id and job.get('request', {}).get('request_id') == key:
        source = job.get('snapshot') or {}
        if status == 'running' and job.get('status') == 'running':
            progress['phase'] = 'pricing' if source.get('status') == 'ready_for_quote' else 'collecting'
    run_snapshot = db.get('pricing_snapshots', run_id) or {}
    checked_at = (run_snapshot.get('evidence') or {}).get('checked_at')
    if checked_at:
        progress['source_checked_at'] = checked_at
    if operation:
        stage = operation['status']
        if stage == 'AUTHORIZED':
            progress['phase'] = 'checked'
        elif stage in ('DISPATCHED', 'RUNNING'):
            progress['phase'] = 'writing'
        elif stage == 'COMPLETED':
            progress['phase'] = 'completed'
        elif stage == 'NO_CHANGE':
            progress['phase'] = 'no_change'
        elif stage == 'REJECTED_NO_CHANGE':
            progress['phase'] = 'rejected_no_change'
        elif stage in ('BACKEND_CONFIRMED','CACHE_CONFIRMED','PUBLIC_PENDING','UNKNOWN','PARTIALLY_APPLIED',
                        'KNOWN_PARTIAL_PUBLIC_PENDING'):
            progress['phase'] = 'readback'
        elif stage in ('FAILED_BEFORE_WRITE','REJECTED_PREWRITE','CANCELLED_NOT_SENT'):
            progress['phase'] = 'failed'
    elif result.get('status') in ('INFEASIBLE','REJECTED_PREWRITE','FAILED_BEFORE_WRITE'):
        progress['phase'] = 'failed'
    elif preview and preview.get('write_protocol') == CURVE_WRITE_PROTOCOL and result:
        progress.update(phase=result['status'].lower(), rows=result.get('rows', []))
    return progress


def _curve_market_quotes(snapshot, observation=None):
    from .competitor_offers import (CURRENT_QUANTITIES, FOUR_SOURCE_POLICY, LEGACY_POLICY, LEGACY_SOURCES,
                                    MONITORING_SOURCES, POLICY, PRICING_SOURCES, quantity_coverage)
    policy = snapshot['evidence'].get('competitor_policy', LEGACY_POLICY)
    requested = CURRENT_QUANTITIES if policy in (POLICY, FOUR_SOURCE_POLICY) else ('100',)
    sources = {POLICY: PRICING_SOURCES, FOUR_SOURCE_POLICY: PRICING_SOURCES + MONITORING_SOURCES}.get(
        policy, LEGACY_SOURCES)
    def public_quote(row):
        return {key:row.get(key) for key in ('source','platform','purchase_k','bonus_k','currency',
                'regular_price','display_price','eligible_net_price','comparable','delivery_method','delivery_tier','captured_at')}
    offers = [row for row in snapshot['evidence'].get('competitor_offers') or []
              if row.get('purchase_k') in requested and row.get('source') in sources]
    monitoring, monitoring_status, monitoring_attempts = {}, {}, {}
    if policy == POLICY:
        same_run = observation if observation and observation.get('run_id') == snapshot['snapshot_id'] else {}
        for source in MONITORING_SOURCES:
            result = same_run.get('package_status', {}).get(source) or {}
            status = result.get('status')
            monitoring_status[source] = status if status in ('captured','partial','missing') else 'pending'
            if result.get('attempts'):
                monitoring_attempts[source] = result['attempts']
            elif 'source_access_restricted' in result.get('errors', []):
                monitoring_attempts[source] = [dict(errors=['source_access_restricted'])]
            monitoring[source] = [dict(public_quote(r), collection_node=r.get('collection_node'))
                                  for r in same_run.get('package_offers', [])
                                  if r.get('source') == source and r.get('run_id') == snapshot['snapshot_id']
                                  and r.get('purchase_k') in requested]
    return dict(write_protocol=CURVE_WRITE_PROTOCOL, competitor_policy=policy, monitoring=monitoring,
                monitoring_status=monitoring_status, monitoring_attempts=monitoring_attempts,
                snapshot_id=snapshot['snapshot_id'], captured_at=snapshot['created_at'],
                competitor_coverage=quantity_coverage(offers, requested=requested, sources=sources),
                  competitor_offers=[public_quote(row) for row in offers])


def read(path):
    if path=='versions':
        folder=Path(__file__).parent
        from .legacy_simulation import SOURCES
        return dict(version=VERSION,engine_sha256=hashlib.sha256((folder/'engine.py').read_bytes()).hexdigest(),
                    financial_sha256=hashlib.sha256((folder/'financial.py').read_bytes()).hexdigest(),
                    legacy_sources={name:hashlib.sha256((folder/'legacy_simulation'/filename).read_bytes()).hexdigest()
                                    for name,(filename,_) in SOURCES.items()},
                    execution_authorized=False)
    if path.startswith('market/'):
        snapshot_id = path.split('/', 1)[1]
        if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', snapshot_id) is None:
            raise ValueError('pricing_market_snapshot_id_invalid')
        store = STORE / 'control.sqlite3'
        snapshot = {}
        if store.exists():
            with closing(sqlite3.connect(store.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
                row = conn.execute('SELECT body FROM pricing_snapshots WHERE id=?', (snapshot_id,)).fetchone()
                snapshot = json.loads(row[0]) if row else {}
        if (snapshot.get('snapshot_id') != snapshot_id or snapshot.get('origin') != 'live_collector'
                or snapshot.get('write_protocol') != CURVE_WRITE_PROTOCOL or snapshot.get('plan_id') is not None
                or (snapshot.get('evidence') or {}).get('run_id') != snapshot_id
                or (snapshot.get('result') or {}).get('execution_authorized') is not False):
            raise ValueError('pricing_readonly_market_snapshot_unavailable')
        return dict(_curve_market_quotes(snapshot), basis='readonly_collection', execution_authorized=False,
                    write_performed=False)
    db=ledger()
    daily_request=None
    if path.startswith('review-state/'):
        parts=path.split('/')
        if len(parts)!=2:raise ValueError('pricing_daily_review_request_invalid')
        daily_request=str(uuid.UUID(parts[1]));path='review-state'
    state_read = path in ('state', 'review-state', '')
    plan = db.active_plan() if state_read or path == 'market' else None
    curve = (plan or {}).get('write_protocol') == CURVE_WRITE_PROTOCOL
    current = _owned_curve_snapshot(db, plan) if curve else None
    if curve:
        snapshot = (public_snapshot_summary(dict(current, result={'rows': []})) if current and state_read else None)
    else:
        snapshot = latest(db, public=True) if state_read or path in ('region-rules', 'market') else None
    if state_read:
        target=(snapshot or {}).get('evidence',{}).get('monthly_target') or {}
        configured=db.get('monthly_targets','current')
        if configured:
            target=dict(target,amount=configured['amount'],target_scope=configured['target_scope'],target_basis=configured['target_basis'],currency='USD')
        operations=sorted(db.all('operations'),key=lambda o:o['created_at'],reverse=True)[:30]
        if path=='review-state':
            # Full bundles repeat proofs and exceed the model reader's wire limit.
            # Keep every operation ID and the original per-operation read endpoint.
            operations=[dict({key:operation[key] for key in ('operation_id','plan_id','status','created_at','completed_at','resources','error') if key in operation},
                             action=(operation.get('bundle') or {}).get('action'),
                             detail_source=dict(action='operation_read',operation_id=operation['operation_id'])) for operation in operations]
        result=dict(version=VERSION,generation=db.generation(),plan=plan,price_control=db.price_control(),
                    plans=sorted(db.all('pricing_plans'),key=lambda p:p['created_at'],reverse=True),active_plans=db.active_plans(),
                    snapshot_id=snapshot['snapshot_id'] if snapshot else None,
                    captured_at=snapshot['created_at'] if snapshot else None,
                    strategies=strategy_summary(db.get('strategy_decisions',snapshot['snapshot_id'])) if snapshot and not curve else {},
                    operations=operations,
                    incidents=db.all('incidents'),target=target,
                    region_rules=(snapshot or {}).get('evidence',{}).get('region_rules',[]),
                    regional_controls=(snapshot or {}).get('evidence',{}).get('regional_controls',[]),
                    current_prices=(snapshot or {}).get('result',{}).get('rows',[]),
                    latest_market_observations=recent_market_observations(db),
                    daily_review=db.get('metadata','latest_daily_review'),retirement=db.all('retirement_inventory'),effect_status='long_term_business_effect_not_established')
        from .weekly_ladder import state as weekly_state
        result['weekly_ladder']=weekly_state(db)
        if curve:
            result.update(write_protocol=CURVE_WRITE_PROTOCOL, curve_decision=_curve_decision(current, plan),
                          source_checked_at=(snapshot or {}).get('source_checked_at'))
        if path=='state':
            result['manual_execution']=manual_execution_progress(db,operations)
            result['catalogue_readbacks']=catalogue_readbacks(operations)
        if path=='review-state':
            if daily_request:
                with db.connect() as conn:
                    matches=[value for row in conn.execute("SELECT body FROM metadata WHERE id LIKE 'daily:%' AND body LIKE ?",('%'+daily_request+'%',))
                             if (value:=json.loads(row[0])).get('request_id')==daily_request]
                if len(matches)!=1:raise ValueError('pricing_daily_review_missing')
                result['daily_review']=matches[0]
            result['daily_review_profit_status']='available' if isinstance((result['daily_review'] or {}).get('actual_profit_summary'),dict) else 'not_recorded'
        return result
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
        if curve:
            from .competitor_offers import POLICY
            from .runtime import _curve_proof_inputs
            from .price_curve import curve_key
            from .pricing_proof_v6 import frozen_curve_proof

            if not current:
                return dict(write_protocol=CURVE_WRITE_PROTOCOL, competitor_policy=POLICY, snapshot_id=None)
            evidence = current['evidence']
            inputs = _curve_proof_inputs(db, evidence)
            rows, catalogues = {}, {}
            selections = {row['platform']: row.get('selection') or {} for row in (current.get('result') or {}).get('rows', [])}
            for platform, entry in inputs.items():
                curve = entry.get('primary_curve')
                tiers = catalogue_tiers(curve)
                observed = next((row.get('received_at') for row in entry.get('readbacks', ())
                                 if row.get('http_status') == 200 and row.get('response_code') == 1), None)
                if tiers and observed:
                    catalogues[platform] = dict(tiers=tiers, observed_at=observed, basis='admin_sample')
                if curve is None:
                    continue
                try:
                    _, proof = frozen_curve_proof(curve, curve_key(curve), entry.get('primary_inputs'))
                except (KeyError, TypeError, ValueError):
                    proof = None
                if proof is None:
                    continue
                rows[platform] = dict(status=proof['status'], average_discount=proof.get('average_discount'),
                    minimum_safe_procurement_margin=proof['minimum_safe_procurement_margin'])
                selection = selections.get(platform, {})
                rows[platform].update({key: selection[key] for key in ('reference_anchors', 'normal_anchors',
                    'final_anchors', 'cost_protection', 'large_market_reference', 'external_change') if key in selection})
                rows[platform]['market_observations'] = (selection.get('market_anchor') or {}).get('observations', [])
            observation = db.get('market_observations',current['snapshot_id'])
            return dict(_curve_market_quotes(current,observation), price_basis={'rows': rows}, catalogue_samples=catalogues)
        from .engine import price_basis
        original=db.get('pricing_snapshots',snapshot['snapshot_id']) if snapshot else None
        try:basis=price_basis(original['evidence'],instant(original['created_at'])) if original else dict(status='unavailable')
        except (ValueError,KeyError,TypeError) as error:basis=dict(status='unavailable',reason=str(error) if isinstance(error,ValueError) else type(error).__name__)
        reference=dict((snapshot or {}).get('evidence',{}).get('reference_market') or {})
        if original and 'ItemD2R' in (original['evidence'].get('source_plan') or {}).get('auxiliary_markets',[]):
            observation=db.get('market_observations',snapshot['snapshot_id']) or {}
            reference=dict(observation.get('reference_market') or dict(status='pending',offers=[]),
                           observation_only=True,source_snapshot_id=snapshot['snapshot_id'])
        return dict(snapshot_id=(snapshot or {}).get('snapshot_id'),
                    global_offers=(snapshot or {}).get('evidence',{}).get('offers'),
                    reference=reference,
                    competitor_diagnostics=(snapshot or {}).get('evidence',{}).get('competitor_diagnostics',[]),
                    competitor_missing_policy='available_current_quote_or_100k_margin_floor',
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
            paths=[shadow_projection(json.loads(r[0])) for r in conn.execute('SELECT body FROM paths') if json.loads(r[0]).get('policy') in POLICIES]
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
    if path.startswith('weekly-ladder/'):
        from . import weekly_ladder
        parts=path.split('/')
        if len(parts)!=3 or not isinstance(data,dict):raise ValueError('weekly_request_invalid')
        _,ident,action=parts
        if action=='confirm' and set(data)=={'expected_revision'}:
            return weekly_ladder.confirm_adoption(ledger(),ident,actor,data['expected_revision'],datetime.now(timezone.utc))
        if action=='reject' and not data:
            return weekly_ladder.reject(ledger(),ident,actor,datetime.now(timezone.utc))
        if action=='automatic' and set(data)=={'enabled','expected_revision'}:
            return weekly_ladder.set_automatic(ledger(),ident,actor,data['enabled'],data['expected_revision'],datetime.now(timezone.utc))
        raise ValueError('weekly_request_invalid')
    if isinstance(data, dict) and 'write_protocol' in data and (
            path == 'preview' or data['write_protocol'] == CURVE_WRITE_PROTOCOL):
        if path != 'preview':
            raise ValueError('pricing_curve_preview_route_required')
        segment = data.get('segment', 'large')
        if (data['write_protocol'] != CURVE_WRITE_PROTOCOL or data.get('platform') not in PLATFORMS
                or segment not in ('small', 'large') or set(data) - {'write_protocol', 'platform', 'snapshot_id', 'segment'}):
            raise ValueError('pricing_curve_preview_fields_invalid')
        snapshot_id = data.get('snapshot_id')
        if 'snapshot_id' in data and (not isinstance(snapshot_id, str) or
                re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', snapshot_id) is None):
            raise ValueError('pricing_curve_preview_snapshot_id_invalid')
        from .runtime import _bound_curve_proof_inputs, preview_curve
        evidence_as_of = clock()
        store = STORE / 'control.sqlite3'
        snapshot, strategy_state, history, frozen = None, None, None, None
        latest_selected = False
        if store.exists():
            with closing(sqlite3.connect(store.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
                from .curve_strategy_v6 import curve_strategy_key
                conn.execute('BEGIN')
                newest = _latest_snapshot(conn, curve=True)
                latest_selected = newest is not None and (snapshot_id is None or snapshot_id == newest['snapshot_id'])
                if latest_selected:
                    snapshot = newest
                    row = conn.execute('SELECT body FROM metadata WHERE id=?',
                                       (curve_strategy_key(data['platform']),)).fetchone()
                    strategy_state = json.loads(row[0]) if row else None
                    history = _curve_preview_history(conn, snapshot, evidence_as_of)
                    row = conn.execute('SELECT body FROM metadata WHERE id=?',
                                       ('curve-proof-inputs:' + snapshot['snapshot_id'],)).fetchone()
                    if row:
                        frozen = _bound_curve_proof_inputs(json.loads(row[0]), snapshot['evidence']).get(data['platform'])
                elif snapshot_id is not None:
                    row = conn.execute('SELECT body FROM pricing_snapshots WHERE id=?', (snapshot_id,)).fetchone()
                    snapshot = json.loads(row[0]) if row else None
        return preview_curve(snapshot, data['platform'], requested_snapshot_id=snapshot_id, strategy_state=strategy_state,
                             segment=segment, closed_attachment=history, latest_selected=latest_selected,
                             evidence_as_of=evidence_as_of, frozen_inputs=frozen)
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
    if path=='price-control':
        if not isinstance(data,dict):raise ValueError('pricing_price_control_fields_invalid')
        return db.save_price_control(data,actor,request_id(actor,data,'price-control'))
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
            db.owns(plan,['base:'+p for p in ('PS','XBOX','PC')],conn)
            response=dict(status='queued',job_key=key,operation_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-uk-retirement:'+key)))
            db.put('metadata',key,dict(request_sha256=fingerprint(data),response=response),conn)
            db.enqueue('uk_retirement',key,clock(),dict(plan_id=plan['plan_id'],revision=plan['revision'],actor=actor),conn)
        return response
    snapshot=latest(db) if path in ('plans','evaluate','preview','manual-previews') else None
    if path=='plans':
        if set(data)-{'request_key','mode','resources','parameters','starts_at','ends_at'}:
            raise ValueError('pricing_plan_fields_invalid')
        mode=data['mode']
        if mode not in POLICIES and mode != 'smart':
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
        resources=data.get('resources',['base:'+p for p in ('PS','XBOX','PC')])
        allowed={'base:'+p for p in ('PS','XBOX','PC')}|{r['resource'] for r in snapshot['evidence'].get('regional_controls',[])
                                            if r.get('resource') and r.get('region_id')==21}
        if set(resources)-allowed:
            raise ValueError('pricing_plan_scope_invalid')
        resources=sorted(set(resources))
        if mode=='smart' and any(r.startswith('region:21:') and r not in allowed for p in db.active_plans() for r in p['resources']):
            raise ValueError('pricing_smart_region_evidence_missing')
        if mode=='smart' and set(resources)!=allowed:
            raise ValueError('pricing_smart_scope_requires_all_owned_resources')
        anchor={'base_prices':{p:str(number(snapshot['evidence']['storefront']['rows'][p]['package_usd']))
                               for p in ('PS','XBOX','PC')},
                'region_coefficients':{str(r['region_id'])+':'+p:str(r['factor']) for r in snapshot['evidence'].get('region_rules',[]) for p in r['platforms']}}
        if existing:
            resources,anchor=existing['resources'],existing['price_anchor']
        parameters=data.get('parameters') or {}
        if not isinstance(parameters,dict) or set(parameters)-({'allocation','preferred_undercut_pct','sprint_policy_version'} if mode in ('revenue_sprint','smart') else {'allocation','offsets_pct'}):
            raise ValueError('pricing_plan_parameters_invalid')
        from .smart import STRATEGY_VERSION
        plan=db.create_plan(mode,resources,anchor,starts_at=data.get('starts_at'),ends_at=data.get('ends_at'),
                            actor=actor,parameters=parameters,plan_id=ident,
                            smart_strategy_version=STRATEGY_VERSION if mode=='smart' else None)
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
        if action=='revise-curve-strategy':
            if (not isinstance(data, dict) or set(data) - {'margin_band'} != {'expected_revision', 'snapshot_id', 'strategy_version', 'market_anchor'}
                    or not isinstance(data['snapshot_id'], str)
                    or re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', data['snapshot_id']) is None):
                raise ValueError('pricing_curve_strategy_revision_fields_invalid')
            from .runtime import revise_curve_strategy
            return revise_curve_strategy(db, ident, data['expected_revision'], actor, data['snapshot_id'],
                                         data['strategy_version'], data['market_anchor'],
                                         **({'margin_band': data['margin_band']} if 'margin_band' in data else {}))
        if action=='activate-curve':
            if (set(data) != {'expected_revision', 'snapshot_id'} or not isinstance(data['snapshot_id'], str)
                    or re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', data['snapshot_id']) is None):
                raise ValueError('pricing_curve_activation_fields_invalid')
            from .runtime import activate_curve_plan
            return activate_curve_plan(db, ident, data['expected_revision'], actor, data['snapshot_id'])
        if action=='migrate-smart-strategy':
            if set(data)!={'expected_revision'}:raise ValueError('pricing_migration_fields_invalid')
            return db.migrate_smart_strategy(ident,data['expected_revision'],actor)
        if action=='migrate-financial-contract':
            if set(data)!={'expected_revision'}:raise ValueError('pricing_migration_fields_invalid')
            return db.migrate_financial_contract(ident,data['expected_revision'],actor)
        if action=='activate':
            result=db.activate_plan(ident)
            body=dict(plan_id=ident,revision=result['revision'])
            if result.get('smart_strategy_version'):
                body['scheduled_at']=result['smart_started_at']
            db.enqueue('cycle','initial:'+ident,clock(),body)
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
                if plan['mode'] in ('revenue_sprint','smart'):sprint_parameters(plan)
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
        reason=data.get('reason')
        if not isinstance(reason,str) or not 4<=len(reason.strip())<=200:
            raise ValueError('pricing_manual_reason_required')
        restore_id=data.get('restore_source_execution_id')
        if bool(restore_id)==bool(data.get('explicit_prices')):
            raise ValueError('pricing_manual_action_source_invalid')
        plan=db.get('pricing_plans',data['plan_id']) if data.get('plan_id') else db.active_plan()
        if not plan:
            raise ValueError('pricing_plan_required')
        if plan.get('write_protocol') == CURVE_WRITE_PROTOCOL:
            if not restore_id:
                raise ValueError('pricing_curve_scalar_override_unsupported')
            if plan['state'] != 'ACTIVE':
                raise ValueError('pricing_plan_required')
            restore_id = str(uuid.UUID(restore_id))
            from .runtime import original_restore_curves
            with db.connect() as conn:
                db.owns(plan, plan['resources'], conn)
                source = original_restore_curves(db, restore_id, plan, conn)
            snapshot = _owned_curve_snapshot(db, plan)
            proof = dict(plan_id=plan['plan_id'], revision=plan['revision'], write_protocol=CURVE_WRITE_PROTOCOL,
                         valid_until=(clock() + timedelta(minutes=15)).isoformat(),
                         restore_before_sha256=fingerprint(source),
                         restore_tiers={p: [{k: row[k] for k in ('purchase_k', 'native_price_usd')}
                                            for row in curve['tiers']] for p, curve in source.items()})
        else:
            if not snapshot:
                raise ValueError('pricing_snapshot_required')
            prices=original_restore_prices(restore_id) if restore_id else data['explicit_prices']
            if not isinstance(prices,dict) or not prices or set(prices)-{'PS','XBOX','PC'}:
                raise ValueError('pricing_manual_price_fields')
            if restore_id:
                prices={group:value for group,value in prices.items() if 'base:'+group in plan['resources']}
            if not prices:
                raise ValueError('pricing_manual_scope_not_owned')
            prices={group:str(number(value)) for group,value in prices.items()}
            from .runtime import override_quote
            proof=override_quote(snapshot['evidence'],prices,reason.strip(),restore_id,plan)
            proof['explicit_prices']=prices
        record=dict(proof,manual_preview_id=ident,operation_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-pricing-v3:manual-operation:'+ident)),
                    request_sha256=request_hash,actor=actor,created_at=clock().isoformat(),snapshot_id=(snapshot or {}).get('snapshot_id'),
                    reason=reason.strip(),restore_source_execution_id=restore_id,
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
            preview_id=str(uuid.UUID(preview_id))
            preview=db.get('manual_previews',preview_id)
            if not preview or preview['actor']!=actor or preview['plan_id']!=plan['plan_id']:
                raise ValueError('pricing_manual_preview_scope_invalid')
            if (preview.get('revision') != plan['revision']
                    or preview.get('write_protocol') != plan.get('write_protocol')):
                raise ValueError('pricing_manual_preview_scope_changed')
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
