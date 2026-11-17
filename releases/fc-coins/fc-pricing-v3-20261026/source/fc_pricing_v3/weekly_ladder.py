"""Deterministic weekly positioning proposals; prices still use the original hourly writer."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import sys
import uuid

from .curve_strategy_v6 import ANCHORS, MARKET_ANCHOR_VERSION, market_anchor_parameters
from .financial import fingerprint, instant
from .platforms import PLATFORMS

LOCAL = timezone(timedelta(hours=8))


def week_start(now):
    day = now.astimezone(LOCAL).date()
    return day - timedelta(days=day.weekday())


def money(value):
    if isinstance(value, bool):
        raise ValueError('weekly_amount_missing')
    value = Decimal(str(value))
    if not value.is_finite() or abs(value) > Decimal('1e12'):
        raise ValueError('weekly_amount_invalid')
    return value


def validate_week(week, start):
    days = [(start+timedelta(days=i)).isoformat() for i in range(7)]
    if (week.get('complete') is not True or week.get('start') != days[0] or week.get('end') != days[-1]
            or week.get('days') != days or not week.get('source_revision')):
        raise ValueError('weekly_days_incomplete')
    for platform in PLATFORMS:
        for row in week['platforms'][platform].values():
            if type(row['orders']) is not int or row['orders'] < 0:
                raise ValueError('weekly_order_count_invalid')
            for field in ('merchandise_usd', 'revenue_cny', 'procurement_gross_cny'):
                amount = money(row[field])
                if field != 'procurement_gross_cny' and amount < 0:
                    raise ValueError('weekly_amount_invalid')
        if set(week['platforms'][platform]) != set(ANCHORS):
            raise ValueError('weekly_bands_incomplete')


def propose_adoption(previous, current, parameters, *, now, history=(), blocked=None):
    """W is the last closed week; the proposal takes effect during this week."""
    monday = week_start(now)
    try:
        parameters = market_anchor_parameters(parameters)
        validate_week(previous, monday-timedelta(days=14))
        validate_week(current, monday-timedelta(days=7))
    except (ValueError, KeyError, TypeError, ArithmeticError) as error:
        return dict(proposals=[], gaps=[str(error)], week_start=monday.isoformat())
    totals = lambda week, platform, field: sum((money(row[field]) for row in week['platforms'][platform].values()), Decimal(0))
    proposals = []
    for platform in PLATFORMS:
        others = [p for p in PLATFORMS if p != platform]
        denominator = sum(totals(previous,p,'orders') for p in others)
        if denominator <= 0:
            return dict(proposals=[], gaps=['weekly_market_comparison_unavailable'], week_start=monday.isoformat())
        market = max(Decimal('.85'), min(Decimal('1.15'), sum(totals(current,p,'orders') for p in others)/denominator))
        actions = sorted((r for r in history if r.get('platform') == platform and r.get('status') == 'CONFIRMED'
                          and r['week_start'] < monday.isoformat()), key=lambda r:r['week_start'])
        last = next((r for r in reversed(actions) if r['week_start'] == (monday-timedelta(days=7)).isoformat()), {})
        frozen = {r['band'] for r in actions if r.get('freeze_until') and r['freeze_until'] > monday.isoformat()}
        unavailable = (blocked or {}).get(platform) or {}
        band, delta, freeze = 'small', Decimal(0), None
        if last and money(last['delta_p']) == Decimal('.01'):
            band = last['band']
            before, after = previous['platforms'][platform][band], current['platforms'][platform][band]
            keep = (after['orders'] >= money(before['orders'])*market*Decimal('.92')
                    and money(after['procurement_gross_cny']) >= money(before['procurement_gross_cny'])*market)
            rule = 'retain_raise' if keep else 'rollback_raise'
            if not keep:
                delta, freeze = Decimal('-.01'), (monday+timedelta(days=14)).isoformat()
        elif totals(current,platform,'orders') < totals(previous,platform,'orders')*market*Decimal('.85'):
            rule = 'recover_orders'
            available = [b for b in ANCHORS if b not in frozen and money(parameters[platform][b]['p']) >= Decimal('.02')]
            if available:
                band, delta = available[0], Decimal('-.02')
        else:
            rule = 'raise_position'
            last_raise = next((r for r in reversed(actions) if money(r['delta_p']) == Decimal('.01')), None)
            order = ['large','small'] if last_raise and last_raise['band'] == 'small' else ['small','large']
            available = [b for b in order if b not in frozen and not unavailable.get(b)
                         and money(parameters[platform][b]['p']) <= Decimal('.14')]
            if available:
                band, delta = available[0], Decimal('.01')
        before = money(parameters[platform][band]['p'])
        if not Decimal(0) <= before+delta <= Decimal('.15'):
            delta, freeze = Decimal(0), None
        revenue = totals(current,platform,'revenue_cny')
        proposals.append(dict(platform=platform, band=band, delta_p=str(delta), before_p=str(before),
            after_p=str(before+delta), rule=rule, market_ratio=str(market), freeze_until=freeze,
            week_start=monday.isoformat(), expires_at=datetime.combine(monday+timedelta(days=3),datetime.min.time(),LOCAL).isoformat(),
            prior=deepcopy(previous['platforms'][platform]), current=deepcopy(current['platforms'][platform]),
            blocked=deepcopy(unavailable), frozen_bands=sorted(frozen),
            margin_ratio=str(totals(current,platform,'procurement_gross_cny')/revenue) if revenue > 0 else None))
    proposals.sort(key=lambda r:(money(r['margin_ratio']) if r['margin_ratio'] is not None else Decimal('Infinity'),r['platform']))
    return dict(proposals=proposals, gaps=[], week_start=monday.isoformat())


def read_week(start, now, *, publication_id=None):
    """Use the existing ES/Admin population and same-order archived procurement facts."""
    from .business_source import shared_curve_attachment, _period_population
    sys.path[:0] = ['/opt/fs-exact-range-20261001', '/opt/fs-hermes-fc']
    from shared_es_facts import read

    scope = dict(start=start.isoformat(), end=(start+timedelta(days=6)).isoformat(), site_id='266', gid='1327')
    shared = read(scope, **({'publication_id':publication_id} if publication_id else {}))
    coverage = shared['coverage']
    attachment = shared_curve_attachment(shared, scope, as_of=now)
    days = [(start+timedelta(days=i)).isoformat() for i in range(7)]
    if (not attachment or not attachment['historical_orders_coverage']['window_complete']
            or not set(days) <= set(coverage.get('day_revisions') or {})):
        raise ValueError('weekly_days_incomplete')
    archived, provenance = _period_population({k:scope[k] for k in ('start','end')})
    if archived is None or provenance.get('status') != 'complete':
        raise ValueError('weekly_actual_cost_archive_unavailable')
    costs = {hashlib.sha256(('site266:FC27:Coins:'+sn).encode()).hexdigest():row for sn,(row,_) in archived.items()}
    admin = {hashlib.sha256(('site266:FC27:Coins:'+row['order_no']).encode()).hexdigest():row for row in shared['rows']}
    totals = {p:{b:dict(orders=0, merchandise_usd=Decimal(0), revenue_cny=Decimal(0), procurement_gross_cny=Decimal(0))
                 for b in ANCHORS} for p in PLATFORMS}
    seen = set()
    for row in attachment['historical_orders']:
        key, platform = row['order_key'], row['platform']
        if key in seen or platform not in PLATFORMS or not row.get('base_k'):
            raise ValueError('weekly_order_identity_or_quantity_missing')
        seen.add(key)
        actual, original = costs.get(key) or {}, admin.get(key) or {}
        if (actual.get('status') != '已完成' or actual.get('costCny') is None
                or not ((actual.get('deliveryRows') or 0) > 0 or actual.get('zeroCost') is True)
                or money(actual.get('salesUsd')) != money(original.get('amount_usd_format'))):
            raise ValueError('weekly_same_order_procurement_missing')
        paid, cost = money(original.get('amount_rmb_format')), money(actual['costCny'])
        if paid < 0 or cost < 0 or money(row['base_k']) <= 0 or not start <= instant(row['paid_at']).astimezone(LOCAL).date() <= start+timedelta(days=6):
            raise ValueError('weekly_order_scope_invalid')
        band = 'small' if money(row['base_k']) < 1000 else 'large'
        target = totals[platform][band]
        target['orders'] += 1
        target['merchandise_usd'] += money(row['merchandise_before_discount_usd'])
        target['revenue_cny'] += paid
        target['procurement_gross_cny'] += paid-cost
    for bands in totals.values():
        for row in bands.values():
            for key in ('merchandise_usd','revenue_cny','procurement_gross_cny'):row[key]=str(row[key])
    return dict(start=scope['start'], end=scope['end'], days=days, complete=True, platforms=totals,
                publication_id=coverage['publication_id'], source_revision=fingerprint(dict(
                    shared=coverage['source_revision'], days=coverage['day_revisions'], procurement=provenance)))


def expire(db, now):
    with db.transaction() as conn:
        for row in conn.execute('SELECT id,body FROM ladder_proposals'):
            value = json.loads(row['body'])
            if value['status'] == 'PROPOSED' and instant(value['expires_at']) <= now:
                db.put('ladder_proposals', row['id'], dict(value,status='EXPIRED',expired_at=now.isoformat()),conn)


def confirm_adoption(db, ident, actor, expected_revision, now, *, automatic=False):
    if type(expected_revision) is not int:raise ValueError('pricing_plan_revision_changed')
    expire(db,now)
    proposal = db.get('ladder_proposals',ident)
    if not proposal:
        raise ValueError('weekly_proposal_missing')
    if proposal['status'] == 'CONFIRMED':
        if proposal['confirmed_by'] != actor:raise ValueError('weekly_confirmation_conflict')
        return proposal
    plan = db.get('pricing_plans',proposal['plan_id'])
    if not plan or plan.get('smart_strategy_version') != MARKET_ANCHOR_VERSION:
        raise ValueError('weekly_market_plan_required')
    control = db.get('metadata','weekly-ladder-control:'+plan['plan_id']) or {}
    if automatic:
        if actor != 'system-weekly-ladder' or not control.get('automatic') or instant(control['eligible_after']) > now:
            raise PermissionError('weekly_automatic_not_authorized')
    elif actor != plan.get('actor'):
        raise PermissionError('weekly_plan_owner_required')
    parameters = market_anchor_parameters((plan.get('parameters') or {}).get('market_anchor'))
    parameters[proposal['platform']][proposal['band']]['p'] = proposal['after_p']
    def check(conn,current,at):
        value = db.get('ladder_proposals',ident,conn)
        actual = market_anchor_parameters((current.get('parameters') or {}).get('market_anchor'))
        if (value['status'] != 'PROPOSED' or instant(value['expires_at']) <= at
                or money(actual[value['platform']][value['band']]['p']) != money(value['before_p'])):
            raise ValueError('weekly_proposal_expired_or_parameters_changed')
        value.update(status='CONFIRMED',confirmed_by=actor,confirmed_at=at.isoformat(),
                     confirmed_revision=expected_revision+1)
        db.put('ladder_proposals',ident,value,conn)
        return dict(weekly_proposal=ident,evidence_hash=value['evidence_hash'])
    if money(proposal['delta_p']) == 0:
        with db.transaction() as conn:
            current = db.get('pricing_plans',plan['plan_id'],conn)
            if current['revision'] != expected_revision:raise ValueError('pricing_plan_revision_changed')
            db.owns(current,current['resources'],conn)
            check(conn,current,now)
            value=db.get('ladder_proposals',ident,conn)
            value['confirmed_revision']=expected_revision
            db.put('ladder_proposals',ident,value,conn)
    else:
        db.activate_curve_plan(plan['plan_id'],expected_revision,actor,ident,check,
            strategy_revision=dict(strategy_version=MARKET_ANCHOR_VERSION,market_anchor=parameters))
    return db.get('ladder_proposals',ident)


def reject(db, ident, actor, now):
    expire(db,now)
    with db.transaction() as conn:
        row=db.get('ladder_proposals',ident,conn)
        plan=db.get('pricing_plans',row['plan_id'],conn) if row else None
        if not plan or actor != plan.get('actor'):raise PermissionError('weekly_plan_owner_required')
        if row['status']=='REJECTED' and row.get('rejected_by')==actor:return row
        if row['status']!='PROPOSED':raise ValueError('weekly_proposal_not_pending')
        return db.put('ladder_proposals',ident,dict(row,status='REJECTED',rejected_by=actor,rejected_at=now.isoformat()),conn)


def set_automatic(db, plan_id, actor, enabled, expected_revision, now):
    if type(enabled) is not bool:raise ValueError('weekly_automatic_invalid')
    if type(expected_revision) is not int:raise ValueError('pricing_plan_revision_changed')
    with db.transaction() as conn:
        plan=db.get('pricing_plans',plan_id,conn)
        control=db.get('metadata','weekly-ladder-control:'+plan_id,conn)
        if not plan or actor != plan.get('actor'):raise PermissionError('weekly_plan_owner_required')
        if plan['revision']!=expected_revision:raise ValueError('pricing_plan_revision_changed')
        db.owns(plan,plan['resources'],conn)
        if not control or enabled and now < instant(control['eligible_after']):
            raise ValueError('weekly_four_manual_weeks_required')
        return db.put('metadata','weekly-ladder-control:'+plan_id,
                      dict(control,automatic=enabled,actor=actor,updated_at=now.isoformat()),conn)


def run(db, plan_id, now):
    """Called after an original natural job completes; never create a timer or a price operation."""
    expire(db,now)
    plan=db.get('pricing_plans',plan_id)
    if not plan or plan['state']!='ACTIVE' or plan.get('smart_strategy_version')!=MARKET_ANCHOR_VERSION:
        return dict(status='inactive')
    if not {'base:'+p for p in PLATFORMS} <= set(plan['resources']):
        return dict(status='three_platform_owner_required')
    monday=week_start(now)
    if now.astimezone(LOCAL).weekday()!=0:return dict(status='not_monday')
    from .average_discount_v6 import yesterday_es_ready
    if not yesterday_es_ready(now):return dict(status='waiting_for_yesterday_es')
    key='weekly-ladder-control:'+plan_id
    control=db.get('metadata',key)
    ids=[str(uuid.uuid5(uuid.NAMESPACE_URL,'fc-weekly-ladder:'+monday.isoformat()+':'+p)) for p in PLATFORMS]
    existing=[db.get('ladder_proposals',ident) for ident in ids]
    if not all(existing):
        current=read_week(monday-timedelta(days=7),now)
        previous=read_week(monday-timedelta(days=14),now,publication_id=current['publication_id'])
        snapshot=db.get('metadata','latest_snapshot:'+plan_id) or {}
        decision=db.get('strategy_decisions',snapshot.get('snapshot_id')) or {}
        selections={r['platform']:r.get('selection') or {} for r in decision.get('curve') or []}
        blocked={}
        for p in PLATFORMS:
            selected=selections.get(p) or {}
            position=selected.get('market_anchor') or {}
            if selected.get('source')!='market_anchor' or not position.get('reference_usd_per_100k'):
                raise ValueError('weekly_current_position_unverified')
            prices=position['reference_usd_per_100k'];terms=position['parameters']
            blocked[p]={b:[] for b in ANCHORS}
            for band in ANCHORS:
                if position.get('floor_only'):blocked[p][band].append('market_quotes_missing')
                if 'U7Buy' in prices and 'Lootbar' in prices and money(prices['Lootbar'])*(1+money(terms[band]['p'])) >= money(prices['U7Buy'])*(1+money(terms[band]['u'])):
                    blocked[p][band].append('u7_cap')
                if band in ((selected.get('cost_protection') or {}).get('segments') or {}):blocked[p][band].append('financial_floor')
        assessment=propose_adoption(previous,current,(plan.get('parameters') or {}).get('market_anchor'),
                                    now=now,history=db.all('ladder_proposals'),blocked=blocked)
        if assessment['gaps']:raise ValueError('weekly_assessment_incomplete:'+','.join(assessment['gaps']))
        with db.transaction() as conn:
            latest=db.get('pricing_plans',plan_id,conn)
            if latest['revision']!=plan['revision']:raise ValueError('pricing_plan_revision_changed')
            for proposal in assessment['proposals']:
                ident=ids[PLATFORMS.index(proposal['platform'])]
                if not db.get('ladder_proposals',ident,conn):
                    row=dict(proposal,proposal_id=ident,plan_id=plan_id,plan_revision=plan['revision'],status='PROPOSED',
                        created_at=now.isoformat(),source_revisions=[previous['source_revision'],current['source_revision']])
                    row['evidence_hash']=fingerprint(row)
                    db.put('ladder_proposals',ident,row,conn)
        for ident in ids:db.incident('weekly_ladder_proposal','daily_effect_review',[db.get('ladder_proposals',ident)['platform']],error='proposal:'+ident)
    if not control:
        control=dict(automatic=False,started_week=monday.isoformat(),
                     eligible_after=datetime.combine(monday+timedelta(days=28),datetime.min.time(),LOCAL).isoformat())
        db.put('metadata',key,control)
    for ident in ids:
        proposal=db.get('ladder_proposals',ident)
        if control.get('automatic') and proposal['status']=='PROPOSED':
            confirm_adoption(db,ident,'system-weekly-ladder',db.get('pricing_plans',plan_id)['revision'],now,automatic=True)
    notification_key='weekly-ladder-notification:'+monday.isoformat()
    notification=db.get('metadata',notification_key)
    if not notification:
        run_id=str(uuid.uuid5(uuid.NAMESPACE_URL,notification_key))
        notification=dict(run_id=run_id,quote=dict(run_id=run_id,daily_report=dict(
            report_kind='weekly_ladder_proposals',local_date=monday.isoformat(),weekly_ladder=ordered_proposals([db.get('ladder_proposals',i) for i in ids])),
            result=dict(decision_receipt=dict(sha256=fingerprint(ids)))))
        db.put('metadata',notification_key,notification)
    if (notification.get('receipt') or {}).get('phase') not in ('completed','failed','timeout','unknown'):
        import hermes_pricing_bridge as bridge
        receipt=bridge.review(dict(job_id=notification['run_id'],actor=plan['actor']),notification['quote'],mode='daily_review',wait_seconds=0)
        db.put('metadata',notification_key,dict(notification,receipt=receipt))
    return dict(status='assessed',proposal_ids=ids)


def ordered_proposals(rows):
    return sorted(rows,key=lambda r:(r['week_start'], -money(r['margin_ratio'])
                  if r.get('margin_ratio') is not None else Decimal('-Infinity'),r['platform']),reverse=True)


def state(db):
    plan=db.active_plan() or {}
    return dict(plan_id=plan.get('plan_id'),owner=plan.get('actor'),
                control=db.get('metadata','weekly-ladder-control:'+plan.get('plan_id','')) or {'automatic':False},
                proposals=ordered_proposals(r for r in db.all('ladder_proposals') if r['plan_id']==plan.get('plan_id'))[:12])
