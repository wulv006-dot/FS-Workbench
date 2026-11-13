"""One daily outcome review over saved price windows and isolated shadow results."""
from .platforms import SMART_VERSIONS, action_key, native_resources, PLATFORMS
from datetime import date as calendar_date,datetime,timedelta,timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

from .dispatch import CURVE_WRITE_PROTOCOL
from .financial import fingerprint,instant

LOCAL=timezone(timedelta(hours=8))
STATE=Path('/var/lib/fc-pricing-v3-shadow')


def due_date(now):
    local=now.astimezone(LOCAL)
    return (local.date()-timedelta(days=1)).isoformat() if (local.hour,local.minute)>=(2,20) else None


def hourly_actual(selected,coverage,date):
    complete=coverage.get('status')=='complete'
    hours=[dict(hour=h,orders=0,net_paid_usd='0') for h in range(24)]
    unplaced=0
    for archived,_ in (selected or {}).values():
        try:
            paid=instant(archived['paidAt']).astimezone(LOCAL)
            if paid.date().isoformat()!=date:raise ValueError('daily_paid_date_mismatch')
            row=hours[paid.hour]
            row['orders']+=1
            row['net_paid_usd']=str(Decimal(row['net_paid_usd'])+Decimal(archived['salesUsd']))
        except (KeyError,ValueError,TypeError):unplaced+=1
    periods=[]
    for first in range(0,24,6):
        rows=hours[first:first+6]
        periods.append(dict(start_hour=first,end_hour=first+6,orders=sum(r['orders'] for r in rows),
            net_paid_usd=str(sum((Decimal(r['net_paid_usd']) for r in rows),Decimal(0)))))
    return dict(local_date=date,timezone='Asia/Shanghai',currency='USD',basis='paid_Coins_orders_site266_game1327',
        status='complete' if complete and not unplaced else 'partial',hourly=hours,periods=periods,
        unplaced_orders=unplaced,missing_hours_are_zero=complete and not unplaced,
        low_demand_period=min(periods,key=lambda r:r['orders']) if complete and not unplaced else None,
        high_demand_period=max(periods,key=lambda r:r['orders']) if complete and not unplaced else None,
        source_sha256=fingerprint(coverage),profit_status='actual_cost_coverage_required_not_inferred_from_USD_revenue')


def exposure_scope(windows,date):
    from .business_source import _window_end
    start=datetime.fromisoformat(date).replace(tzinfo=LOCAL);stop=start+timedelta(days=1)
    periods=[]
    from .business_source import OBSERVED_PRICE_WINDOWS
    valid=[w for w in windows if w.get('origin') in OBSERVED_PRICE_WINDOWS and w.get('mode')=='production']
    for window in valid:
        opened=instant(window['opened_at'])
        for resource in window.get('mutable_resources',[]):
            group=resource.removeprefix('base:') if resource.startswith('base:') else resource.removeprefix('region:')
            if not resource.startswith(('base:','region:')):continue
            end=_window_end(window,group,valid,stop)
            if max(start,opened)<min(stop,end):periods.append((max(start,opened),min(stop,end),window['operation_id']))
    return dict(status='confirmed_windows_available' if periods else 'no_confirmed_exposure',
        first_exposure_at=min((p[0] for p in periods),default=None).isoformat() if periods else None,
        last_observed_through=max((p[1] for p in periods),default=None).isoformat() if periods else None,
        confirmed_operation_count=len({p[2] for p in periods}),source_sha256=fingerprint(windows),
        attribution='only_orders_bound_by_creation_and_actual_price_are_effect_samples; full_day_orders_are_business_context; range_is_not_continuous_coverage_proof')


def collect_outcomes(date,windows,*,shared_order_facts=None):
    """Admin/Order business reads only; no competitor, public price or write endpoint."""
    sys.path.insert(0,'/opt/fs-hermes-fc')
    from channel_source import pages,COLLECTOR
    sys.path.insert(0,COLLECTOR)
    import p2pah_auth as auth
    from .business_source import _period_population,online_window_context
    selected,coverage=_period_population(dict(start=date,end=date))
    session=auth.Session()
    token,_=auth.admin_token_from_service()
    if not token:raise ValueError('pricing_daily_shared_admin_unavailable')
    session.bind_admin_token(token);del token
    from .selective_sources import history_period
    now=datetime.now(timezone.utc)
    learning_rows,_=_period_population(history_period(now))
    learning_rows = dict(learning_rows or {}, **(selected or {}))
    payment_days={}
    try:online=online_window_context(session,pages,windows,now,learning_rows or {},payment_days=payment_days)
    finally:session.close()
    if shared_order_facts is not None:
        from .business_source import attach_shared_marketing
        online=attach_shared_marketing(online,shared_order_facts)
    return dict(actual=hourly_actual(selected,coverage,date),online=online,payment_days=payment_days)


def marketing_unavailable(reason):
    return dict(status='unavailable', reason=reason, payment_date=None, review_day_coverage='unavailable')


def collect_marketing_context(review_date, outcomes, payment_days):
    """Read one represented payment day through D2 with the original publication pinned."""
    from .business_source import attach_shared_marketing
    if not payment_days:
        return marketing_unavailable('no_bound_payment_day')
    sys.path[:0] = ['/opt/fs-exact-range-20261001', '/opt/fs-hermes-fc']
    from order_facts_runtime import collect_shared
    from shared_es_facts import latest_publication
    pin = latest_publication()
    if pin is None:
        return marketing_unavailable('es_publication_unavailable')
    cutoff_date = calendar_date.fromisoformat(pin['cutoff'])
    review_day = calendar_date.fromisoformat(review_date)
    earliest = review_day - timedelta(days=365)
    bound_days = {calendar_date.fromisoformat(day) for day in payment_days.values()}
    covered = [day for day in bound_days if earliest <= day <= review_day and day < cutoff_date]
    if not covered:
        return marketing_unavailable('publication_does_not_cover_bound_payment_day')
    for date in sorted(covered, reverse=True):
        day = date.isoformat()
        facts = collect_shared(dict(start=day, end=day, site_id='266', gid='1327'),
                               publication_id=pin['publication_id'])
        source = facts['source_coverage']
        if (source.get('publication_id') != pin['publication_id'] or source.get('admin_complete') is not True
                or day not in source.get('day_revisions', {})
                or source['attribution'].get('source_revision') != pin['publication_id']):
            continue
        selected = [row for row in outcomes if payment_days.get(row['order_key']) == day]
        result = attach_shared_marketing(dict(actual_outcomes=selected),facts)['marketing_context']
        return dict(result,payment_date=day,review_day_coverage=result['status'] if day == review_date else 'unavailable')
    return marketing_unavailable('es_publication_not_observed')


def profit_summary(online,windows,operations,date,plan_id):
    """Freeze existing same-order outcomes; never collect or infer missing costs."""
    rows=[{k:v for k,v in row.items() if k!='marketing_attribution'} for row in online.get('actual_outcomes',[])]
    by_window={w['operation_id']:w for w in windows}
    contexts={o['operation_id']:dict(plan_id=o.get('plan_id'),status=o.get('status'),completed_at=o.get('completed_at'),
        resources=((o.get('bundle') or {}).get('mutable_resources',o.get('resources',[])) if ((o.get('bundle') or {}).get('smart_assignment') or {}).get('strategy_version')=='smart-three-platform-v3' else (o.get('bundle') or {}).get('authorized_resources') or o.get('resources',[])),
        action=o.get('actual_action') or (o.get('bundle') or {}).get('action') or {},catalog=(o.get('bundle') or {}).get('catalog') or {},
        assignment=(o.get('bundle') or {}).get('smart_assignment') or {}) for o in operations}
    confirmed=[(instant(v['completed_at']),key,set(native_resources(v['resources']))) for key,v in contexts.items() if v['status'] in ('COMPLETED','NO_CHANGE') and v['completed_at']]
    def attribution(row):
        # A policy can change while this platform's physical price window stays open.
        window=by_window.get(row['price_window_id'],{})
        group=row.get('platform') or (row['group'] if row['group'] in PLATFORMS else row['group'].rsplit(':',1)[-1] if ':' in row['group'] else row['group'])
        price_group=row.get('price_group') or row['group']
        resources=set(native_resources(['base:'+group]))
        if ':' in price_group:resources.add('region:'+price_group)
        created=instant(row['occurred_at'])
        events=[(at,index,key) for index,(at,key,scope) in enumerate(confirmed) if at<=created and resources.intersection(scope)]
        saved=[dict(operation_id=window.get('operation_id'),at=window.get('opened_at'),resources=window.get('resources',[]))]+window.get('continuations',[])
        events += [(instant(e['at']),len(confirmed)+index,e['operation_id']) for index,e in enumerate(saved) if e.get('at') and instant(e['at'])<=created and resources.intersection(native_resources(e.get('resources',[])))]
        if not events:return None,group,'unlabelled'
        operation_id=max(events,key=lambda item:(item[0],item[1]))[2]
        context=contexts.get(operation_id)
        if context is None:
            return (window.get('plan_id') if operation_id==window.get('operation_id') else None),group,'unlabelled'
        actual=(window.get('action') or {}).get('base_prices',{}).get(action_key(window.get('action') or {},group) if group in PLATFORMS else group)
        expected=context['action'].get('base_prices',{}).get(action_key(context['action'],group) if group in PLATFORMS else group)
        regional=':' in price_group and Decimal((window.get('action') or {}).get('region_coefficients',{}).get(price_group,'1'))!=Decimal(context['action'].get('region_coefficients',{}).get(price_group,'1'))
        platform=row.get('platform')
        if actual is None or expected is None or Decimal(actual)!=Decimal(expected) or regional or platform and window.get('catalog',{}).get(platform)!=context['catalog'].get(platform):
            return None,group,'unlabelled'
        return context['plan_id'],group,(context['assignment'].get('group_labels') or {}).get(action_key(context['action'],group) if group in PLATFORMS else group) or context['assignment'].get('label') or 'unlabelled'
    def totals(selected):
        paid=[r for r in selected if r.get('actual_net_usd') is not None]
        known=[r for r in paid if r.get('actual_contribution_usd') is not None]
        unknown=[r for r in paid if r.get('actual_contribution_usd') is None]
        customers=[r for r in selected if r.get('new_customer') is not None]
        amount=lambda rr,key:str(sum((Decimal(r[key]) for r in rr),Decimal(0))) if rr else None
        covered=amount(known,'actual_net_usd');gross=amount(known,'actual_contribution_usd')
        return dict(status='no_sample' if not selected else 'complete' if len(known)==len(selected) else 'partial',
            orders=len(selected),paid_usd=amount(paid,'actual_net_usd'),unknown_revenue_orders=len(selected)-len(paid),
            cost_known_orders=len(known),covered_paid_usd=covered,procurement_gross_usd=gross,
            procurement_cost_usd=str(Decimal(covered)-Decimal(gross)) if known else None,
            unknown_cost_orders=len(selected)-len(known),unknown_cost_paid_usd=amount(unknown,'actual_net_usd'),
            customer_known_orders=len(customers),new_customers=len({r['customer_key'] for r in customers if r.get('new_customer') and r.get('customer_key')}) if customers else None,
            unknown_customer_orders=sum(r.get('new_customer') is None or r.get('new_customer') and not r.get('customer_key') for r in selected))
    attributed=[(row,attribution(row)) for row in rows]
    selected=[(r,key) for r,key in attributed if instant(r['occurred_at']).astimezone(LOCAL).date().isoformat()==date]
    grouped={}
    for row,key in selected:grouped.setdefault(key,[]).append(row)
    coverage=online.get('learning_coverage') or {}
    return dict(version='pricing-daily-profit-v1',currency='USD',observed_at=coverage.get('observed_at'),
        query_complete=coverage.get('query_complete'),attribution='confirmed_window_continuations_at_creation_time_not_full_payment_day',
        cost_basis='same_order_actual_USD_receipt_minus_all_Order_procurement_USD; before_ads_payment_and_other_fees',
        review_day=dict(local_date=date,totals=totals([r for r,_ in selected]),groups=[dict(plan_id=p,group=g,label=l,**totals(rr)) for (p,g,l),rr in sorted(grouped.items(),key=lambda item:str(item[0]))]),
        active_plan=dict(plan_id=plan_id,totals=totals([r for r,key in attributed if key[0]==plan_id])) if plan_id else None,
        source_sha256=fingerprint(dict(date=date,plan_id=plan_id,rows=rows,windows=windows,contexts=contexts)))


def curve_decision_basis(db, plan):
    from .api import catalogue_tiers

    basis = dict(write_protocol=CURVE_WRITE_PROTOCOL, plan_id=plan['plan_id'],
                 plan_revision=plan['revision'], plan_state=plan['state'], mode=plan.get('mode'),
                 parameters=plan.get('parameters'), budget_policy='none',
                 status='confirmed_execution_unavailable', snapshot_id=None, snapshot_sha256=None,
                 operation_id=None)
    confirmed = []
    for operation in db.all('operations'):
        bundle, receipt = operation.get('bundle') or {}, operation.get('readback') or {}
        if (operation.get('status') == 'COMPLETED' and operation.get('completed_at')
                and (operation.get('plan_id'), operation.get('revision'), operation.get('generation')) ==
                (plan['plan_id'], plan['revision'], plan['generation'])
                and bundle.get('write_protocol') == CURVE_WRITE_PROTOCOL
                and receipt.get('status') == 'CONFIRMED' and receipt.get('write_protocol') == CURVE_WRITE_PROTOCOL
                and receipt.get('execution_id') == operation['operation_id']):
            confirmed.append(operation)
    if not confirmed:
        return basis

    operation = max(confirmed, key=lambda row: instant(row['completed_at']))
    bundle = operation['bundle']
    basis.update(operation_id=operation['operation_id'], completed_at=operation['completed_at'],
                 financial_contract_version=bundle.get('financial_contract_version'))
    if bundle.get('restore_source_execution_id'):
        basis['restore_source_execution_id'] = bundle['restore_source_execution_id']
    snapshot_id = bundle.get('snapshot_id')
    snapshot = db.get('pricing_snapshots', snapshot_id) if snapshot_id else None
    evidence = (snapshot or {}).get('evidence')
    if (not snapshot or snapshot.get('snapshot_id') != snapshot_id
            or (snapshot.get('plan_id'), snapshot.get('plan_revision')) != (plan['plan_id'], plan['revision'])
            or snapshot.get('write_protocol') != CURVE_WRITE_PROTOCOL
            or snapshot.get('origin') != 'live_collector' or snapshot.get('mode') != 'production'
            or not isinstance(evidence, dict) or fingerprint(evidence) != bundle.get('snapshot_sha256')):
        return dict(basis, status='execution_snapshot_unavailable')

    basket_fields = ('status', 'selection', 'net_receipt_usd', 'safe_cost_usd',
                     'safe_procurement_margin', 'evidence_ref')
    discount_fields = ('contract', 'status', 'start', 'end_exclusive', 'eligible_orders',
                       'matched_orders', 'merchandise_before_discount_usd', 'actual_discount_usd',
                       'retained_ratio', 'publication_id', 'revision')
    before = bundle['before_action']['curves']
    results = operation['readback']['curve_results']
    platforms = {}
    for platform in bundle['affected_platforms']:
        proof = bundle['curve_proofs'][platform]
        selection = bundle['curve_selection'][platform]
        chosen = {key: selection[key] for key in ('segment', 'label', 'reference_curve_id',
                                                 'comparison_episode_id') if key in selection}
        actual_label = (selection.get('assignment') or {}).get('actual_label')
        if actual_label is not None:
            chosen['actual_label'] = actual_label
        baskets = proof['baskets']
        discount = proof.get('average_discount')
        platforms[platform] = dict(
            before_tiers=catalogue_tiers(before[platform]),
            confirmed_tiers=catalogue_tiers(results[platform]['actual_site266_curve']),
            selection=chosen, proof_hash=proof['proof_hash'], proof_status=proof['status'],
            hard_margin=proof.get('hard_margin'), target=proof.get('target'),
            planning_baskets={name: {key: baskets[name][key] for key in basket_fields if key in baskets[name]}
                              for name in ('main', 'recent')},
            average_discount={key: discount[key] for key in discount_fields if key in discount}
            if discount else None)
    return dict(basis, status='confirmed_execution', snapshot_id=snapshot_id,
                snapshot_sha256=bundle['snapshot_sha256'], source_plan=evidence.get('source_plan'),
                planning_basis='forecast_from_original_execution_proof', confirmed_platforms=platforms)


def run(body):
    from .runtime import ledger,write_json,ROOT
    from .scheduler import export_shadow_snapshot
    import hermes_pricing_bridge as bridge
    db=ledger();date=body['local_date'];key='daily:'+date
    record=db.get('metadata',key) or dict(local_date=date,request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-v3-daily:'+date)),
        phase='created',price_write_performed=False,automatic_strategy_switch=False)
    if record.get('phase')=='completed':return record
    if 'actual' not in record:
        process=subprocess.run(['/opt/python39/bin/python3','-B','-m','fc_pricing_v3.daily'],
            input=json.dumps(dict(local_date=date,windows=db.all('actual_price_windows'))),text=True,
            capture_output=True,timeout=600,cwd='/opt/fc27-cloud-browser')
        if process.returncode:raise ValueError('pricing_daily_outcome_collection_failed')
        outcomes=json.loads(process.stdout)
        record['actual']=outcomes['actual']
        record['price_exposure']=exposure_scope(db.all('actual_price_windows'),date)
        from .smart import STRATEGY_VERSION
        if not any(p.get('smart_strategy_version') in SMART_VERSIONS for p in db.active_plans()):
            db.put('metadata','daily_online_context',outcomes['online'])
        for settlement in outcomes['online'].get('budget_settlements',[]):db.settle_order(settlement)
        record['learning_coverage']=outcomes['online'].get('learning_coverage')
        if 'marketing_context' in outcomes['online']:
            record['marketing_context']=outcomes['online']['marketing_context']
        elif outcomes.get('payment_days'):
            try:
                marketing = subprocess.run(['/opt/python39/bin/python3','-B','-m','fc_pricing_v3.daily'],
                    input=json.dumps(dict(action='marketing_context',local_date=date,
                        outcomes=[{k:row[k] for k in ('order_key','actual_net_usd')}
                            for row in outcomes['online']['actual_outcomes']],payment_days=outcomes['payment_days'])),
                    text=True,capture_output=True,timeout=190,cwd='/opt/fc27-cloud-browser')
                record['marketing_context']=json.loads(marketing.stdout) if not marketing.returncode else marketing_unavailable('shared_order_facts_process_failed')
            except subprocess.TimeoutExpired:
                record['marketing_context']=marketing_unavailable('shared_order_facts_timeout')
            except (OSError,ValueError):
                record['marketing_context']=marketing_unavailable('shared_order_facts_process_failed')
        record['actual_profit_summary']=profit_summary(outcomes['online'],db.all('actual_price_windows'),db.all('operations'),date,(db.active_plan() or {}).get('plan_id'))
        db.put('metadata',key,record)
    export_shadow_snapshot(db,force=True)
    from .history import ensure_shadow
    dispatched=ensure_shadow(db,'daily',record['request_id'],date)
    if dispatched['status']=='pending':raise ValueError('pricing_daily_shadow_pending')
    if dispatched['status']=='unknown':
        record.update(phase='unknown',shadow=dispatched)
        db.put('metadata',key,record);db.put('metadata','latest_daily_review',record)
        return record
    record['shadow']=dispatched.get('result') or dispatched
    if 'decision_basis' not in record:
        plan=db.active_plan() or {}
        if plan.get('write_protocol') == CURVE_WRITE_PROTOCOL:
            record['decision_basis'] = curve_decision_basis(db, plan)
        else:
            with db.connect() as conn:
                row=conn.execute('SELECT body FROM pricing_snapshots ORDER BY rowid DESC LIMIT 1').fetchone()
            snapshot=json.loads(row[0]) if row else {}
            evidence=snapshot.get('evidence') or {}
            model=evidence.get('demand_model') or {}
            mix=evidence.get('historical_discount_mix') or {}
            record['decision_basis']=dict(snapshot_id=snapshot.get('snapshot_id'),mode=plan.get('mode'),plan_state=plan.get('state'),
                write_protocol=plan.get('write_protocol'),
                snapshot_sha256=fingerprint(evidence) if snapshot.get('snapshot_id') and isinstance(snapshot.get('evidence'),dict) else None,
                parameters=plan.get('parameters'),budget_policy='none',financial_contract_version=((snapshot.get('result') or {}).get('decision_receipt') or {}).get('financial_contract_version'),
                history={k:mix.get(k) for k in ('period','net_order_usd','discount_usd','undiscounted_order_usd','by_platform','platform_contract','sha256')},
                demand_model={k:model.get(k) for k in ('status','elasticity','groups','observed_window_hours','rate_window_hours')},
                source_plan=evidence.get('source_plan'),basis_is_latest_saved_input=True)
    report={k:record.get(k) for k in ('local_date','actual','learning_coverage','shadow','decision_basis','price_exposure')}
    # Existing submitted reviews keep their original frozen input and request ID.
    if 'actual_profit_summary' in record:report['actual_profit_summary']=record['actual_profit_summary']
    if 'marketing_context' in record:report['marketing_context']=record['marketing_context']
    quote=dict(run_id=record['request_id'],daily_report=report,result=dict(decision_receipt=dict(sha256=fingerprint(report))))
    record['phase']='review_prepared'
    db.put('metadata',key,record);db.put('metadata','latest_daily_review',record)
    receipt=bridge.review(dict(job_id=record['request_id'],actor='wulv'),quote,mode='daily_review',wait_seconds=0)
    record['hermes']=receipt
    record['phase']='completed' if receipt['phase']=='completed' else receipt['phase']
    db.put('metadata',key,record)
    db.put('metadata','latest_daily_review',record)
    if receipt['phase'] in ('unknown','failed','timeout'):
        db.incident('pricing_daily_hermes_'+receipt['phase'],'daily_effect_review',['FC27'],phase='daily_review',error='original_request_id:'+record['request_id'])
        return record
    if receipt['phase']!='completed':raise ValueError('pricing_daily_hermes_pending')
    return record


def collect_hourly_outcomes(windows,previous):
    import sys
    sys.path.insert(0,'/opt/fs-hermes-fc')
    from channel_source import pages,COLLECTOR
    sys.path.insert(0,COLLECTOR)
    import p2pah_auth as auth
    from .business_source import incremental_window_context
    session=auth.Session()
    try:
        token,_=auth.admin_token_from_service()
        if not token:raise ValueError('pricing_hourly_shared_admin_unavailable')
        session.bind_admin_token(token);del token
        return incremental_window_context(session,pages,windows,datetime.now(timezone.utc),previous)
    finally:session.close()


def run_hourly(body):
    from .runtime import ledger,clock
    from .smart import STRATEGY_VERSION,policy_suffix,strategy_start
    db=ledger();plan=db.get('pricing_plans',body['plan_id'])
    curve = (plan or {}).get('write_protocol') == CURVE_WRITE_PROTOCOL
    if (not plan or plan['state'] != 'ACTIVE' or plan['revision'] != body['revision']
            or not curve and plan.get('smart_strategy_version') not in SMART_VERSIONS):
        return dict(status='superseded')
    start=strategy_start(plan)
    if clock()<start:return dict(status='await_strategy_start')
    # Include a physically unchanged earlier window when its confirmed continuation enters this version.
    windows=[w for w in db.all('actual_price_windows') if not w.get('closed_at') or instant(w['closed_at'])>=start]
    for window in windows:
        window['observation_original_opened_at']=window['opened_at']
        window['opened_at']=max(start,instant(window['opened_at'])).isoformat()
    if not windows:return dict(status='await_first_confirmed_exposure')
    key=('curve-outcome-source:' if curve else 'smart-outcome-source:')+policy_suffix(plan)
    process=subprocess.run(['/opt/python39/bin/python3','-B','-m','fc_pricing_v3.daily'],
        input=json.dumps(dict(action='hourly_outcomes',windows=windows,previous=db.get('metadata',key) or {})),
        text=True,capture_output=True,timeout=600,cwd='/opt/fc27-cloud-browser')
    if process.returncode:raise ValueError('pricing_hourly_outcome_collection_failed')
    result=json.loads(process.stdout)
    online=result['online']
    if online.get('learning_coverage',{}).get('query_complete') is not True:
        raise ValueError('pricing_hourly_outcome_coverage_incomplete')
    online.update(smart_strategy_version=plan.get('smart_strategy_version'),smart_plan_id=plan['plan_id'],smart_revision=plan['revision'])
    with db.transaction() as conn:
        current=db.get('pricing_plans',plan['plan_id'],conn)
        if not current or current['state']!='ACTIVE' or current['revision']!=plan['revision'] or current.get('smart_started_at')!=plan.get('smart_started_at'):
            return dict(status='superseded')
        db.put('metadata',key,result['state'],conn)
        db.put('metadata', 'curve-online-context:' + plan['plan_id'] if curve else 'daily_online_context', online, conn)
    for settlement in online.get('budget_settlements',[]):db.settle_order(settlement)
    return dict(status='updated',plan_id=plan['plan_id'],strategy_version=plan.get('smart_strategy_version'),
                observed_at=online['learning_coverage']['observed_at'],outcomes=len(online.get('actual_outcomes',[])),
                gaps=len(online['learning_coverage']['gap_events']),price_write_performed=False,model_called=False)


if __name__=='__main__':
    data=json.load(sys.stdin)
    if data.get('action') == 'marketing_context':
        try:
            result=collect_marketing_context(data['local_date'],data['outcomes'],data['payment_days'])
        except (ImportError,OSError,sqlite3.Error,ValueError,KeyError,TypeError) as error:
            reason = str(error) if isinstance(error,ValueError) and str(error) in (
                'es_publication_changed','es_publication_timezone') else type(error).__name__
            result=marketing_unavailable('shared_order_facts_read_failed:'+reason)
    elif data.get('action')=='hourly_outcomes':
        result=collect_hourly_outcomes(data['windows'],data.get('previous',{}))
    else:
        result=collect_outcomes(data['local_date'],data['windows'],shared_order_facts=data.get('shared_order_facts'))
    print(json.dumps(result))
