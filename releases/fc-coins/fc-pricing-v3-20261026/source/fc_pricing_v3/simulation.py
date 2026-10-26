"""Read-only scenarios: simulated orders never enter production or training labels."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile

from . import VERSION
from .engine import evaluate, POLICIES, render, replay_promotion, demand
from .financial import fingerprint, instant

LOCAL = timezone(timedelta(hours=8))
ZERO = Decimal(0)
LEGACY_NAMES = ('legacy_80_15_5', 'legacy_itemd2r_parity')


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def dec(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('simulation_number_invalid')
    return result


def day(value):
    return value.astimezone(LOCAL).date()


def month(value):
    return value.astimezone(LOCAL).strftime('%Y-%m')


def sprint_window(now):
    local = now.astimezone(LOCAL)
    next_month = (local.replace(day=28)+timedelta(days=4)).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    if local.day <= 5:
        return local.replace(day=1,hour=0,minute=0,second=0,microsecond=0),local.replace(day=6,hour=0,minute=0,second=0,microsecond=0)
    if local >= next_month-timedelta(days=7):
        return next_month-timedelta(days=7),next_month
    return None


def calendar_mode(mode, now, started):
    if mode == 'flash_sale' and now >= started+timedelta(hours=72) or mode == 'acquisition' and now >= started+timedelta(days=7):
        return 'daily'
    if mode == 'revenue_sprint' and sprint_window(now) is None:
        return 'daily'
    return mode


def plan_end(mode, started):
    if mode in ('flash_sale','acquisition'):
        return started+timedelta(hours=72 if mode=='flash_sale' else 168)
    if mode == 'revenue_sprint':
        window = sprint_window(started)
        return window[1] if window else None
    return None


def action_now(evidence):
    rows = evidence['storefront']['rows']
    return dict(base_prices={'console':str(max(dec(rows[p]['package_usd']) for p in ('PS','XBOX'))),'pc':str(rows['PC']['package_usd'])},
        region_coefficients={str(r['region_id'])+':'+p:str(r['factor']) for r in evidence.get('region_rules',[]) for p in r['platforms']})


def reference_prices(evidence, action):
    prices = deepcopy(action['base_prices'])
    for rule in evidence.get('region_rules',[]):
        for platform in rule['platforms']:
            key = str(rule['region_id'])+':'+platform
            tier = next(t for t in evidence['promotion_envelope']['packages'][platform]['tiers'] if dec(t['base_k'])==100)
            prices[key] = render(dec(action['base_prices']['pc' if platform=='PC' else 'console'])/100,tier,
                action['region_coefficients'][key])['regular_usd']
    return prices


def initial_path(mode, evidence, now):
    action = action_now(evidence)
    mix = evidence['historical_discount_mix']
    daily = evidence.get('discount_mix_daily')
    buckets = [dict(day=r['day'],net_usd=str(r['net_usd']),list_usd=str(r['list_usd']),origin='actual_seed') for r in daily] if daily else [
        dict(day=(day(now)-timedelta(days=i)).isoformat(),net_usd=str(dec(mix['net_order_usd'])/7),
             list_usd=str(dec(mix['undiscounted_order_usd'])/7),origin='equal_daily_seed_scenario') for i in range(1,8)]
    limits = {g:str(max(dec(POLICIES[mode]['floor']),dec(v)*dec(POLICIES[mode]['revenue_ratio']))) if v is not None else POLICIES[mode]['floor']
              for g in ('console','pc') for v in [(evidence.get('daily_net_revenue_7d') or {}).get(g)]}
    end = plan_end(mode,now)
    return dict(policy=mode,started_at=now.isoformat(),last_as_of=None,action=None,price_anchor=action,
        budget_reference=reference_prices(evidence,action),budget_limits=limits,budget_entries=[],budget_used='0',negative_budget_used='0',
        budget_initial_fixed=not bool(evidence.get('daily_net_revenue_7d')),
        finite_total_budget={g:str(dec(v)*dec((end-now).total_seconds())/86400) if end else None for g,v in limits.items()},
        revenue='0',contribution='0',paid_orders='0',new_customers='0',delivered_k='0',backlog_k=evidence.get('backlog_k'),
        monthly_revenue={month(now):str(evidence['monthly_target']['mtd']) if (evidence.get('monthly_target') or {}).get('mtd') is not None else None},
        discount_net_usd='0',discount_list_usd='0',discount_days=buckets,
        discount_seed_basis='observed_daily_seed' if daily else 'equal_daily_seed_scenario_not_observed_daily_distribution',
        simulated_customer_cohorts=[],order_batches=[],commitments=deepcopy(evidence.get('quote_commitments',[])),applied_adjustments=[],
        sequence=0,gaps=[],origin='simulation',mode='shadow',training_eligible=False,active_deadline=end.isoformat() if end else None,
        window_started_at=sprint_window(now)[0].isoformat() if mode=='revenue_sprint' and sprint_window(now) else None,
        customer_assumption='expected new-customer cohorts; returning orders allocated FIFO before unidentified initial customers')


def context_for(path, now):
    first,last = day(now)-timedelta(days=7),day(now)-timedelta(days=1)
    rows = [r for r in path['discount_days'] if first.isoformat()<=r['day']<=last.isoformat()]
    net = sum((dec(r['net_usd']) for r in rows),ZERO)
    gross = sum((dec(r['list_usd']) for r in rows),ZERO)
    return dict(mode='shadow',training_eligible=False,retained_ratio=str(net/gross) if gross else None,origin='simulated_path',
        verified_actual=False,source_scope='path_seven_closed_days',count_unit='simulated_day_buckets',bucket_count=len(rows),seed_basis=path['discount_seed_basis'])


def own_evidence(path, evidence, now):
    own = deepcopy(evidence)
    own['origin'] = own['mode'] = 'shadow'
    action = path['action'] or path['price_anchor']
    for platform,row in own['storefront']['rows'].items():
        row['package_usd'] = action['base_prices']['pc' if platform=='PC' else 'console']
    own['region_rules'] = [dict(rule,platforms=[p],factor=action['region_coefficients'].get(str(rule['region_id'])+':'+p,rule['factor']))
                           for rule in own.get('region_rules',[]) for p in rule['platforms']]
    own['backlog_k'] = path['backlog_k']
    own.setdefault('monthly_target',{})['mtd'] = path['monthly_revenue'].get(month(now))
    own['simulation_budget_state'] = dict(entries=path['budget_entries'],limits=path['budget_limits'])
    own['budget_reference'] = deepcopy(path['price_anchor'])
    for group,model in (own.get('demand_model') or {}).get('groups',{}).items():
        if model.get('orders_per_block') is not None:
            p = 'PC' if group=='pc' else 'PS'
            ref = model.get('reference_regular_usd',evidence['storefront']['rows'][p]['package_usd'])
            anchor = path['price_anchor']['base_prices'][group]
            model['orders_per_block'] = str(demand(anchor,ref,model['orders_per_block'],model.get('elasticity','2')))
            if model.get('target_revenue_per_order_usd') is not None:
                model['target_revenue_per_order_usd'] = str(dec(model['target_revenue_per_order_usd'])*dec(anchor)/dec(ref))
            model['reference_regular_usd'] = anchor
    return own


def components(candidate, evidence, reference):
    rating = candidate['score']
    result = []
    regional_concession = {}
    for row in rating.get('regional_predictions',[]):
        group = 'pc' if row['key'].endswith(':PC') else 'console'
        regional_concession[group] = regional_concession.get(group,ZERO)+dec(row['concession'])
    for group,row in rating['groups'].items():
        model = (evidence.get('demand_model') or {}).get('groups',{}).get(group,{})
        result.append(dict(row,key=group,group=group,regular_usd=candidate['action']['base_prices'][group],
            delivered_k_per_order=model.get('delivered_k_per_order'),
            concession=str(dec(row['concession'])-regional_concession.get(group,ZERO)) if row.get('concession') is not None else None))
    models = {str(r['region_id'])+':'+r['platform']:r for r in (evidence.get('demand_model') or {}).get('segments',[])}
    for row in rating.get('regional_predictions',[]):
        model = models[row['key']]
        result.append(dict(row,group='pc' if model['platform']=='PC' else 'console',
            regular_usd=candidate['financial_proof']['prices'][row['key']]['price']['regular_usd'],
            new_customers=str(dec(row['orders'])*dec(model['new_customer_ratio'])) if model.get('new_customer_ratio') is not None else None,
            delivered_k_per_order=model.get('delivered_k_per_order')))
    for row in result:
        if row.get('revenue') is None or row.get('contribution') is None or row.get('concession') is None:
            raise ValueError('simulation_absolute_component_missing')
        retained = dec(evidence.get('shadow_retained_ratio') or evidence['historical_discount_mix']['retained_ratio'])
        if retained<=ZERO:
            raise ValueError('simulation_retained_ratio_invalid')
        row['list_usd'] = str(dec(row['revenue'])/retained)
        row['list_usd_basis'] = 'projected_score_net_divided_by_shadow_path_retained_ratio_frozen_basket'
        row['negative_contribution'] = str(max(ZERO,-dec(row['contribution'])))
    return result


def budget_fits(path, rows, now, mode):
    for group,limit in path['budget_limits'].items():
        for kind in ('concession','negative_contribution'):
            amount = sum((dec(r[kind]) for r in rows if r['group']==group),ZERO)
            recent = sum((dec(r[kind]) for r in path['budget_entries'] if r['group']==group and instant(r['at'])>now-timedelta(hours=24)),ZERO)
            lifetime = sum((dec(r[kind]) for r in path['budget_entries'] if r['group']==group and
                            (not path.get('window_started_at') or instant(r['at'])>instant(path['window_started_at']))),ZERO)
            total = path['finite_total_budget'].get(group) if mode==path['policy'] else None
            if amount and (recent+amount>dec(limit) or total is not None and lifetime+amount>dec(total)):
                return False
    return True


def decide(path, evidence, now):
    own = own_evidence(path,evidence,now)
    mode = calendar_mode(path['policy'],now,instant(path['started_at']))
    context = context_for(path,now)
    if context['retained_ratio'] is None:
        return dict(status='DATA_PENDING',selected=None,candidates=[],failures=[dict(code='simulated_history_empty')]),own
    own['shadow_retained_ratio'] = context['retained_ratio']
    plan = dict(price_anchor=path['price_anchor'],resources=['base:console','base:pc'],ends_at=path['active_deadline'] if mode==path['policy'] else None)
    result = evaluate(own,mode,plan=plan,now=now,evaluation_context=context)
    candidates = [c for c in result['candidates'] if not c['score']['absolute_forecast_available'] or budget_fits(path,components(c,own,path['budget_reference']),now,mode)]
    if not candidates and result['status']=='READY':
        result.update(status='BUDGET_EXHAUSTED',failures=result['failures']+[dict(code='path_rolling_or_finite_budget_exhausted')])
    result.update(candidates=candidates,selected=candidates[0] if candidates else None,simulation_context=context,execution_authorized=False)
    return result,own


def cohort_orders(path, row, orders, new, at, batch):
    if new is None:
        path['customer_identity_status'] = 'new_customer_rate_pending'
        return
    remaining = max(ZERO,orders-new)
    for cohort in path['simulated_customer_cohorts']:
        if cohort['segment']!=row['key'] or remaining<=0:
            continue
        unique = min(remaining,max(ZERO,dec(cohort['customers'])-dec(cohort['returning_customers'])))
        if unique:
            cohort['returning_customers'] = str(dec(cohort['returning_customers'])+unique)
            cohort['returns'].append(dict(at=at.isoformat(),customers=str(unique)))
            remaining -= unique
    if new:
        path['simulated_customer_cohorts'].append(dict(cohort_id=fingerprint([path['policy'],batch,row['key']]),segment=row['key'],
            first_paid_at=at.isoformat(),customers=str(new),returning_customers='0',returns=[]))
    if remaining:
        path['unidentified_initial_returning_orders'] = str(dec(path.get('unidentified_initial_returning_orders','0'))+remaining)


def advance(path, now):
    if not path['last_as_of']:
        return
    start = instant(path['last_as_of'])
    if now<=start:
        return
    if not path.get('last_components'):
        path['gaps'].append(dict(start=start.isoformat(),end=now.isoformat(),reason='absolute_forecast_unavailable'))
        if month(start)!=month(now):
            path['monthly_revenue'][month(now)] = None
        path['absolute_rollforward_status'] = 'baseline_pending_no_simulated_orders_fabricated'
        return
    end = min(now,start+timedelta(hours=6))
    due = instant(path['active_deadline']) if path.get('active_deadline') and path.get('effective_mode')==path['policy'] else None
    if due and start<due<end:
        end = due
    if end<now:
        path['gaps'].append(dict(start=end.isoformat(),end=now.isoformat(),reason='exit_pending_sources' if due and end==due else 'external_snapshot_gap_over_six_hours'))
        path['monthly_revenue'][month(now)] = None
    if not path.get('last_forecast_absolute'):
        path['absolute_rollforward_status'] = 'baseline_pending_no_simulated_orders_fabricated'
        return
    while start<end:
        midnight = (start.astimezone(LOCAL)+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        stop = min(end,midnight)
        fraction = dec((stop-start).total_seconds())/21600
        batch = fingerprint([path['policy'],start.isoformat(),stop.isoformat(),path['action']])
        revenue = profit = orders = new_customers = incoming = gross = ZERO
        group_revenue = {}
        quantity_known = identity_known = True
        for row in path['last_components']:
            count = dec(row['orders'])*fraction
            new = dec(row['new_customers'])*fraction if row.get('new_customers') is not None else None
            identity_known = identity_known and new is not None
            revenue += dec(row['revenue'])*fraction
            group_revenue[row['group']] = group_revenue.get(row['group'],ZERO)+dec(row['revenue'])*fraction
            profit += dec(row['contribution'])*fraction
            gross += dec(row['list_usd'])*fraction
            orders += count
            new_customers += new or ZERO
            cohort_orders(path,row,count,new,stop,batch)
            if row.get('delivered_k_per_order') is None:
                quantity_known = False
            else:
                incoming += count*dec(row['delivered_k_per_order'])
            path['budget_entries'].append(dict(at=stop.isoformat(),group=row['group'],concession=str(dec(row['concession'])*fraction),
                                              negative_contribution=str(dec(row['negative_contribution'])*fraction)))
        delivered = None
        if quantity_known and path['backlog_k'] is not None and path.get('last_capacity_k_per_block') is not None:
            available = dec(path['backlog_k'])+incoming
            delivered = min(available,dec(path['last_capacity_k_per_block'])*fraction)
            path['backlog_k'] = str(available-delivered)
            path['delivered_k'] = str(dec(path['delivered_k'])+delivered)
        else:
            path['delivery_state'] = 'capacity_quantity_or_initial_backlog_pending'
        for key,value in (('revenue',revenue),('contribution',profit),('paid_orders',orders)):
            path[key] = str(dec(path[key])+value)
        path['new_customers'] = str(dec(path['new_customers'])+new_customers) if identity_known and path['new_customers'] is not None else None
        period = month(start)
        if period not in path['monthly_revenue']:
            path['monthly_revenue'][period] = '0' if day(start).day==1 and start.astimezone(LOCAL).hour==0 and start.astimezone(LOCAL).minute==0 else None
        if path['monthly_revenue'].get(period) is not None:
            path['monthly_revenue'][period] = str(dec(path['monthly_revenue'][period])+revenue)
        bucket = next((r for r in path['discount_days'] if r['day']==day(start).isoformat()),None)
        if bucket is None:
            bucket = dict(day=day(start).isoformat(),net_usd='0',list_usd='0',origin='simulated_path')
            path['discount_days'].append(bucket)
        bucket['net_usd'],bucket['list_usd'] = str(dec(bucket['net_usd'])+revenue),str(dec(bucket['list_usd'])+gross)
        path['discount_net_usd'],path['discount_list_usd'] = str(dec(path['discount_net_usd'])+revenue),str(dec(path['discount_list_usd'])+gross)
        path['order_batches'].append(dict(batch_id=batch,opened_at=start.isoformat(),closed_at=stop.isoformat(),action=deepcopy(path['action']),
            orders=str(orders),new_customers=str(new_customers) if identity_known else None,net_usd=str(revenue),contribution_usd=str(profit),
            delivered_k=str(delivered) if delivered is not None else None,revenue_by_group={g:str(v) for g,v in group_revenue.items()},
            month=period,source_snapshot_id=path.get('external_snapshot_id'),origin='expected_simulated_batch'))
        start = stop
    local_now=now.astimezone(LOCAL)
    if end==now and local_now.day==1 and local_now.hour==0 and local_now.minute==0 and month(now) not in path['monthly_revenue']:
        path['monthly_revenue'][month(now)]='0'
    path['budget_used'] = str(sum((dec(r['concession']) for r in path['budget_entries']),ZERO))
    path['negative_budget_used'] = str(sum((dec(r['negative_contribution']) for r in path['budget_entries']),ZERO))


def apply_adjustments(path, snapshot, now):
    for adjustment in snapshot.get('simulation_adjustments',[]):
        key = adjustment['adjustment_id']
        if key in path['applied_adjustments'] or instant(adjustment['available_at'])>now:
            continue
        batch = next((b for b in path['order_batches'] if b['batch_id']==adjustment['order_batch_id']),None)
        if batch is None:
            path['gaps'].append(dict(reason='adjustment_original_batch_missing',adjustment_id=key))
            continue
        income,cost = dec(adjustment.get('revenue_delta_usd','0')),dec(adjustment.get('cost_delta_usd','0'))
        batch['net_usd'],batch['contribution_usd'] = str(dec(batch['net_usd'])+income),str(dec(batch['contribution_usd'])+income-cost)
        path['revenue'],path['contribution'] = str(dec(path['revenue'])+income),str(dec(path['contribution'])+income-cost)
        period = adjustment.get('target_month',batch['month'])
        if path['monthly_revenue'].get(period) is not None:
            path['monthly_revenue'][period] = str(dec(path['monthly_revenue'][period])+income)
        path['applied_adjustments'].append(key)
    path['commitments'] = [q for q in path['commitments'] if not q.get('expires_at') or instant(q['expires_at'])>now]


def renew_sprint_window(path, evidence, now):
    if path['policy']!='revenue_sprint':
        return
    window=sprint_window(now)
    if not window or path.get('window_started_at')==window[0].isoformat():
        return
    path['window_started_at'],path['active_deadline']=window[0].isoformat(),window[1].isoformat()
    path['price_anchor']=deepcopy(path['action'] or path['price_anchor'])
    path['budget_reference']=reference_prices(evidence,path['price_anchor'])
    first=day(now)-timedelta(days=7)
    batches=[b for b in path['order_batches'] if first.isoformat()<=day(instant(b['opened_at'])).isoformat()<day(now).isoformat()]
    coverage={}
    for batch in batches:
        key=day(instant(batch['opened_at']))
        coverage[key]=coverage.get(key,0)+(instant(batch['closed_at'])-instant(batch['opened_at'])).total_seconds()
    complete=all(coverage.get(first+timedelta(days=i))==86400 for i in range(7)) and all('revenue_by_group' in b for b in batches)
    for group in ('console','pc'):
        daily=sum((dec(b['revenue_by_group'].get(group,'0')) for b in batches),ZERO)/7 if complete and all('revenue_by_group' in b for b in batches) else None
        path['budget_limits'][group]=str(max(dec(POLICIES['revenue_sprint']['floor']),daily*dec(POLICIES['revenue_sprint']['revenue_ratio']))) if daily is not None else POLICIES['revenue_sprint']['floor']
        path['finite_total_budget'][group]=str(dec(path['budget_limits'][group])*dec((window[1]-now).total_seconds())/86400)
    path['budget_initial_fixed']=not complete
    path['window_history']=path.get('window_history',[])+[dict(start=path['window_started_at'],end=path['active_deadline'],budget_limits=deepcopy(path['budget_limits']),budget_basis='own_seven_closed_days' if complete else 'fixed_initial')]


class Shadow:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.legacy_registry = {}
        with self.connect() as db:
            db.executescript('''PRAGMA journal_mode=DELETE;
                CREATE TABLE IF NOT EXISTS cursor(id TEXT PRIMARY KEY,value INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS paths(id TEXT PRIMARY KEY,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS history(id TEXT PRIMARY KEY,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS summaries(id TEXT PRIMARY KEY,body TEXT NOT NULL);''')

    def connect(self):
        return sqlite3.connect(str(self.path),timeout=5,factory=Connection)

    def snapshot(self, snapshot, *, cursor=None):
        evidence,ident = snapshot['evidence'],snapshot['snapshot_id']
        # The collector records checked_at before its later FX, cost, public and
        # historical reads. The immutable snapshot creation is the first as-of
        # that can contain every source used by the original decision.
        if snapshot.get('origin')=='live_collector' and not snapshot.get('created_at'):
            raise ValueError('pricing_shadow_snapshot_time_missing')
        now = instant(snapshot.get('created_at') or evidence['checked_at'])
        history_available=(evidence.get('historical_orders_coverage') or {}).get('available_at')
        if history_available and instant(history_available)>now:
            raise ValueError('pricing_shadow_snapshot_before_history_available')
        version = (evidence.get('demand_model') or {}).get('version','central-prior-e2')
        records = []
        with self.connect() as db:
            for mode in POLICIES:
                key = fingerprint([ident,VERSION,version,'same_real_snapshot',mode])
                if not db.execute('SELECT 1 FROM runs WHERE id=?',(key,)).fetchone():
                    comparison = evaluate(evidence,mode,now=now,evaluation_context=dict(mode='shadow',training_eligible=False,
                        retained_ratio=evidence['historical_discount_mix']['retained_ratio'],origin='same_real_snapshot'))
                    row = dict(mode='shadow',origin='simulation',simulation_kind='same_real_snapshot',policy=mode,as_of=now.isoformat(),
                        model_version=version,policy_version=VERSION,snapshot_id=ident,result=comparison,training_eligible=False,
                        assumptions='same real state; do not sum these comparisons into continuous earnings')
                    db.execute('INSERT INTO runs VALUES (?,?)',(key,json.dumps(row)))
                    records.append(row)
                old = db.execute('SELECT body FROM paths WHERE id=?',(mode,)).fetchone()
                path = json.loads(old[0]) if old else initial_path(mode,evidence,now)
                if path['last_as_of'] and now<=instant(path['last_as_of']):
                    continue
                advance(path,now)
                apply_adjustments(path,snapshot,now)
                renew_sprint_window(path,evidence,now)
                calculation,own = decide(path,evidence,now)
                chosen = calculation['selected']
                if chosen:
                    path['action'] = chosen['action']
                    path['last_forecast_absolute'] = chosen['score']['absolute_forecast_available']
                    path['last_components'] = components(chosen,own,path['budget_reference']) if path['last_forecast_absolute'] else []
                else:
                    path['last_components'] = []
                    path['gaps'].append(dict(start=now.isoformat(),reason=calculation['status']))
                path['last_capacity_k_per_block'] = own.get('capacity_k_per_block')
                path.update(last_as_of=now.isoformat(),sequence=path['sequence']+1,effective_mode=calendar_mode(mode,now,instant(path['started_at'])),
                    simulation_kind='independent_state_rollforward',model_version=version,policy_version=VERSION,seed=fingerprint([mode,path['started_at']]),
                    last_result=calculation,external_snapshot_id=ident,
                    assumptions='previous action and previous known rates advance elapsed exposure; independent expected cohorts and state; never production labels')
                encoded=json.dumps(path)
                if db.execute('UPDATE paths SET body=? WHERE id=?',(encoded,mode)).rowcount==0:
                    db.execute('INSERT INTO paths VALUES (?,?)',(mode,encoded))
                key = fingerprint([ident,VERSION,version,'independent_state_rollforward',mode])
                db.execute('INSERT OR IGNORE INTO runs VALUES (?,?)',(key,json.dumps(path)))
            if cursor is not None:
                if db.execute("UPDATE cursor SET value=? WHERE id='production'",(cursor,)).rowcount==0:
                    db.execute("INSERT INTO cursor VALUES ('production',?)",(cursor,))
        return records

    def consume(self, production_path):
        with self.connect() as db:
            row = db.execute("SELECT value FROM cursor WHERE id='production'").fetchone()
            cursor = row[0] if row else 0
        source = sqlite3.connect('file:'+str(Path(production_path).resolve())+'?mode=ro',uri=True)
        try:
            events = source.execute("SELECT id,kind,body FROM event_outbox WHERE kind IN ('snapshot_ready','simulation_requested') AND id>? ORDER BY id LIMIT 100",(cursor,)).fetchall()
            processed = 0
            for sequence,kind,raw in events:
                body = json.loads(raw)
                if kind=='snapshot_ready':
                    row = source.execute('SELECT body FROM pricing_snapshots WHERE id=?',(body['snapshot_id'],)).fetchone()
                    if not row:
                        return dict(events=processed,cursor=cursor,status='source_snapshot_missing',snapshot_id=body['snapshot_id'])
                    self.snapshot(json.loads(row[0]),cursor=sequence)
                else:
                    now = instant(body['requested_at']) if body.get('requested_at') else datetime.now(timezone.utc)
                    end = datetime.combine(day(now),datetime.min.time(),LOCAL)
                    start = end.replace(day=1) if body.get('closed_days') in ('month','current_month') else end-timedelta(days=int(body.get('closed_days',7)))
                    snapshots = [json.loads(r[0]) for r in source.execute('SELECT body FROM pricing_snapshots')]
                    snapshots = sorted((s for s in snapshots if start<=instant(s['evidence']['checked_at'])<end),key=lambda s:instant(s['evidence']['checked_at']))
                    self.historical(snapshots,kind=body['kind'],simulation_id=body['simulation_id'],
                                    closed_days=body.get('closed_days',7))
                    with self.connect() as db:
                        if db.execute("UPDATE cursor SET value=? WHERE id='production'",(sequence,)).rowcount==0:
                            db.execute("INSERT INTO cursor VALUES ('production',?)",(sequence,))
                processed += 1
                cursor = sequence
            return dict(events=processed,cursor=cursor,status='processed')
        finally:
            source.close()

    def register_legacy(self, name, evaluator, source_sha256):
        from .legacy_simulation import SOURCES
        if name not in LEGACY_NAMES or source_sha256!=SOURCES[name][1] or not callable(evaluator):
            raise ValueError('simulation_legacy_registry_invalid')
        self.legacy_registry[name] = evaluator,source_sha256

    def legacy_actions(self, snapshot):
        from .legacy_simulation import replay
        results = {}
        for name in LEGACY_NAMES:
            if name in self.legacy_registry:
                evaluator,sha = self.legacy_registry[name]
                value = dict(action=evaluator(deepcopy(snapshot)),source_sha256=sha,status='available')
            else:
                value = replay(snapshot,name)
            results[name] = dict(value,read_only=True,execution_authorized=False,training_eligible=False)
        return results

    def historical(self, snapshots, *, kind='actual_reconstruction', rule_mode='historical_asof', simulation_id=None, closed_days=None):
        if kind not in ('actual_reconstruction','fixed_orders_reprice','demand_counterfactual','causal_evaluation'):
            raise ValueError('pricing_historical_kind_invalid')
        if rule_mode not in ('historical_asof','common_guard_benchmark'):
            raise ValueError('pricing_historical_rule_mode_invalid')
        request_hash = fingerprint([snapshots,kind,rule_mode])
        if simulation_id:
            with self.connect() as db:
                old = db.execute('SELECT body FROM history WHERE id=?',(simulation_id,)).fetchone()
            if old:
                value = json.loads(old[0])
                if (value['simulation_kind']!=kind or value['rule_mode']!=rule_mode or
                        value.get('requested_closed_days')!=closed_days or
                        closed_days is None and value['request_sha256']!=request_hash):
                    raise ValueError('simulation_request_payload_conflict')
                return value
        records,eligible,seen_orders = [],[],set()
        latest_orders,revised_keys = {},set()
        for original in sorted(snapshots,key=lambda s:instant(s['evidence']['checked_at'])):
            snapshot = deepcopy(original)
            asof = instant(snapshot['evidence']['checked_at'])
            if instant(snapshot.get('available_at',snapshot['evidence']['checked_at']))>asof or future_sources(snapshot['evidence'],asof):
                records.append(dict(snapshot_id=snapshot['snapshot_id'],status='missing_at_historical_asof'))
                continue
            if rule_mode=='common_guard_benchmark':
                if not snapshot.get('common_guard_rules'):
                    records.append(dict(snapshot_id=snapshot['snapshot_id'],status='common_guard_contract_missing'))
                    continue
                snapshot['evidence']['promotion_envelope'] = snapshot['common_guard_rules']['promotion_envelope']
            eligible.append(snapshot)
            orders,gaps = historical_orders(snapshot,asof)
            if kind=='actual_reconstruction':
                revised=0
                for order in orders:
                    prior=latest_orders.get(order['order_key'])
                    if prior is not None and prior!=order:
                        revised+=1;revised_keys.add(order['order_key'])
                    latest_orders[order['order_key']]=order
            elif kind=='fixed_orders_reprice':
                revised=0
                for order in orders:
                    prior=latest_orders.get(order['order_key'])
                    if prior is not None and prior!=order:
                        revised+=1
                    latest_orders[order['order_key']]=order
            observed_orders=orders
            orders = [order for order in orders if order['order_key'] not in seen_orders]
            seen_orders.update(order['order_key'] for order in orders)
            if not observed_orders and gaps and kind in ('actual_reconstruction','fixed_orders_reprice'):
                record=dict(snapshot_id=snapshot['snapshot_id'],status='historical_orders_missing',gaps=gaps,
                            order_window='incremental_unique_across_snapshots')
                if kind=='actual_reconstruction':
                    record['actual']=dict(order_count=None,net_revenue_usd=None,
                                          procurement_contribution_usd=None,delivered_k=None)
                else:
                    record['fixed_order_count']=None
                    record['alternatives']={mode:dict(status='historical_orders_missing',totals=None) for mode in POLICIES}
                    for name,legacy in self.legacy_actions(snapshot).items():
                        record['alternatives'][name]=dict(status='historical_orders_missing',totals=None,
                            source_sha256=legacy.get('source_sha256'),legacy_replay_status=legacy.get('status'),
                            as_of=legacy.get('as_of'))
                records.append(record)
                continue
            if kind=='fixed_orders_reprice' and revised and not orders:
                records.append(dict(snapshot_id=snapshot['snapshot_id'],status='late_order_revision_not_repriced',
                    fixed_order_count=0,revised_order_count=revised,alternatives={},
                    gaps=gaps+[dict(reason='later_order_revision_excluded_from_prior_asof_fixed_reprice',count=revised)],
                    as_of=asof.isoformat(),order_window='no_future_terms_from_later_order_revisions'))
                continue
            if kind=='actual_reconstruction':
                records.append(dict(snapshot_id=snapshot['snapshot_id'],status='partial' if gaps else 'available',actual=order_totals(orders),orders=orders,gaps=gaps,
                    revised_order_count=revised,cumulative_actual=order_totals(list(latest_orders.values())),
                    as_of=asof.isoformat(),order_window='incremental_unique_across_snapshots_with_later_revisions'))
            elif kind=='fixed_orders_reprice':
                alternatives = {}
                context = dict(mode='shadow',training_eligible=False,retained_ratio=snapshot['evidence']['historical_discount_mix']['retained_ratio'],origin='fixed_historical_actual_mix')
                for mode in POLICIES:
                    candidate = evaluate(snapshot['evidence'],mode,now=asof,evaluation_context=context)['selected']
                    alternatives[mode] = reprice_orders(orders,candidate,snapshot['evidence']) if candidate else dict(status='no_feasible_price',orders=[])
                for name,legacy in self.legacy_actions(snapshot).items():
                    alternatives[name] = (dict(reprice_orders(orders,dict(action=legacy['action']),snapshot['evidence']),
                                               source_sha256=legacy['source_sha256'],legacy_replay_status=legacy['status'],
                                               as_of=legacy.get('as_of')) if legacy.get('action') else legacy)
                records.append(dict(snapshot_id=snapshot['snapshot_id'],status='partial' if gaps or any(alternatives[m]['status']!='available' for m in POLICIES) else 'available',fixed_order_count=len(orders),gaps=gaps,alternatives=alternatives,
                    order_window='incremental_unique_across_snapshots'))
        if kind=='demand_counterfactual':
            with tempfile.TemporaryDirectory() as folder:
                replay = Shadow(Path(folder)/'counterfactual.sqlite3')
                for snapshot in eligible:
                    replay.snapshot(snapshot)
                with replay.connect() as db:
                    records += [dict(status='scenario_projection',path=json.loads(r[0])) for r in db.execute('SELECT body FROM paths')]
        elif kind=='causal_evaluation':
            records += [causal_estimate(eligible)]
        result = dict(simulation_id=simulation_id or request_hash,request_sha256=request_hash,created_at=datetime.now(timezone.utc).isoformat(),
            mode='shadow',origin='simulation',simulation_kind=kind,rule_mode=rule_mode,policy_version=VERSION,records=records,
            requested_closed_days=closed_days,
            write_performed=False,execution_authorized=False,training_eligible=False,
            historical_gaps='only observations available at each as_of; missing quantity, paths and frozen legacy evidence retained')
        if kind=='actual_reconstruction' and eligible:
            result['reconciled_actual']=dict(as_of=instant(eligible[-1]['evidence']['checked_at']).isoformat(),
                revised_order_count=len(revised_keys),actual=order_totals(list(latest_orders.values())),
                basis='latest_available_revision_per_original_order_within_selected_snapshots; earlier_asof_records_not_rewritten')
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO history VALUES (?,?)',(result['simulation_id'],json.dumps(result)))
        return result

    def summary(self, as_of=None):
        now = as_of or datetime.now(timezone.utc)
        results = []
        with self.connect() as db:
            for raw, in db.execute('SELECT body FROM paths').fetchall():
                path = json.loads(raw)
                for label,days in (('daily',1),('7d',7),('14d',14),('30d',30),('monthly',None)):
                    start = datetime.combine(day(now),datetime.min.time(),LOCAL).replace(day=1) if days is None else now-timedelta(days=days)
                    batches = [b for b in path['order_batches'] if start<instant(b['closed_at'])<=now]
                    matured = {}
                    for horizon in (7,14,30):
                        cohorts = [c for c in path['simulated_customer_cohorts'] if instant(c['first_paid_at'])<=now-timedelta(days=horizon)]
                        count = sum((dec(c['customers']) for c in cohorts),ZERO)
                        returned = sum((dec(r['customers']) for c in cohorts for r in c['returns'] if instant(r['at'])<=instant(c['first_paid_at'])+timedelta(days=horizon)),ZERO)
                        matured[str(horizon)] = dict(matured_customers=str(count),repeat_customers=str(returned),repeat_rate=str(returned/count) if count else None)
                    row = dict(mode='shadow',origin='simulation',policy=path['policy'],period=label,as_of=now.isoformat(),
                        model_version=path['model_version'],policy_version=path['policy_version'],
                        revenue=str(sum((dec(b['net_usd']) for b in batches),ZERO)),contribution=str(sum((dec(b['contribution_usd']) for b in batches),ZERO)),
                        orders=str(sum((dec(b['orders']) for b in batches),ZERO)),new_customers=str(sum((dec(b['new_customers']) for b in batches),ZERO)) if all(b['new_customers'] is not None for b in batches) else None,
                        backlog_k=path['backlog_k'],budget_used=path['budget_used'],matured_repurchase=matured,gaps=path['gaps'],training_eligible=False,assumptions=path['assumptions'])
                    db.execute('INSERT OR REPLACE INTO summaries VALUES (?,?)',(fingerprint([path['policy'],label,now.isoformat()]),json.dumps(row)))
                    results.append(row)
        return results

    def prune(self, as_of=None):
        now = as_of or datetime.now(timezone.utc)
        cutoff = now-timedelta(days=180)
        monthly = now.astimezone(LOCAL).replace(day=1)
        for _ in range(24):
            monthly = (monthly-timedelta(days=1)).replace(day=1)
        removed = 0
        with self.connect() as db:
            for table in ('runs','history','summaries'):
                for key,raw in db.execute('SELECT id,body FROM '+table).fetchall():
                    row = json.loads(raw)
                    stamp = row.get('as_of') or row.get('created_at') or row.get('last_as_of')
                    after = monthly if table=='summaries' and row.get('period')=='monthly' else cutoff
                    if stamp and instant(stamp)<after:
                        db.execute('DELETE FROM '+table+' WHERE id=?',(key,))
                        removed += 1
        return dict(removed=removed,detail_retention_days=180,monthly_retention_months=24,active_paths_preserved=True)


def future_sources(value, asof):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('available_at','checked_at') and item is not None and instant(item)>asof:
                return True
            if future_sources(item,asof):
                return True
    elif isinstance(value, list):
        return any(future_sources(item,asof) for item in value)
    return False


def historical_orders(snapshot, asof):
    rows,gaps,seen = [],[],set()
    source = snapshot.get('historical_orders')
    if source is None:
        return [],[dict(reason='historical_orders_missing')]
    required = ('order_key','paid_usd','available_at')
    optional = ('base_k','bonus_k','cost_usd')
    for order in source:
        missing = [key for key in required if order.get(key) is None]
        if missing:
            gaps.append(dict(order_key=order.get('order_key'),reason='historical_order_fields_missing',fields=missing))
            continue
        if instant(order['available_at'])>asof:
            gaps.append(dict(order_key=order['order_key'],reason='order_not_available_at_asof'))
            continue
        if dec(order.get('refund_usd','0'))<ZERO or dec(order.get('refund_usd','0'))>ZERO and not isinstance(order.get('paid_is_net_of_refunds'),bool):
            gaps.append(dict(order_key=order['order_key'],reason='refund_basis_unknown_or_negative'))
            continue
        if order['order_key'] not in seen:
            seen.add(order['order_key'])
            missing = [key for key in optional if order.get(key) is None]
            if missing:
                gaps.append(dict(order_key=order['order_key'],reason='historical_order_partial_fields',fields=missing))
            rows.append(deepcopy(order))
    return rows,gaps


def order_totals(orders):
    net = lambda row:dec(row['paid_usd'])-(ZERO if row.get('paid_is_net_of_refunds') else dec(row.get('refund_usd','0')))
    paid = sum((net(r) for r in orders),ZERO)
    cost_rows=[r for r in orders if r.get('cost_usd') is not None]
    cny_rows=[r for r in orders if r.get('revenue_cny') is not None and r.get('cost_cny') is not None]
    quantity_rows=[r for r in orders if r.get('base_k') is not None and r.get('bonus_k') is not None]
    covered_cost=sum((dec(r['cost_usd']) for r in cost_rows),ZERO)
    covered_paid=sum((net(r) for r in cost_rows),ZERO)
    cny_revenue=sum((dec(r['revenue_cny']) for r in cny_rows),ZERO)
    cny_cost=sum((dec(r['cost_cny']) for r in cny_rows),ZERO)
    return dict(order_count=len(orders),net_revenue_usd=str(paid),
        procurement_contribution_usd=str(paid-covered_cost) if len(cost_rows)==len(orders) else None,
        historical_cost_covered_orders=len(cost_rows),covered_net_revenue_usd=str(covered_paid),
        covered_cost_usd=str(covered_cost),
        covered_procurement_contribution_usd=str(covered_paid-covered_cost) if cost_rows else None,
        cny_covered_orders=len(cny_rows),admin_snapshot_revenue_cny=str(cny_revenue) if cny_rows else None,
        historical_cost_cny=str(cny_cost) if cny_rows else None,
        actual_cny_gross=str(cny_revenue-cny_cost) if len(cny_rows)==len(orders) else None,
        covered_procurement_gross_cny=str(cny_revenue-cny_cost) if cny_rows else None,
        cny_basis='same_order_Admin_amount_rmb_format_snapshot_revenue_minus_Order_historical_actual_cost_CNY; Admin_snapshot_uses_current_FX_not_USD_settlement',
        delivered_k=str(sum((dec(r['base_k'])+dec(r['bonus_k']) for r in quantity_rows),ZERO)) if len(quantity_rows)==len(orders) else None,
        quantity_covered_orders=len(quantity_rows),
        revenue_basis='observed_paid_usd_minus_refunds_only_when_not_already_net; tax_and_payment_fee_scope_unverified',
        contribution_scope='purchase_cost_only_other_fees_not_assumed_zero; full_contribution_only_with_complete_historical_cost')


def reprice_orders(orders, candidate, evidence):
    rows,gaps,action = [],[],candidate['action']
    for order in orders:
        required=('base_k','bonus_k','platform','region_id','regular_usd','promotion_path','price_version','package_retained_ratio')
        missing=[key for key in required if order.get(key) is None]
        if missing:
            gaps.append(dict(order_key=order['order_key'],reason='fixed_order_fields_missing',fields=missing))
            continue
        p = order['platform']
        retained = order['package_retained_ratio']
        coefficient = '1'
        if order['region_id'] not in (0,'0','global'):
            key = str(order['region_id'])+':'+p
            rule = next((r for r in evidence.get('region_rules',[]) if str(r['region_id'])==str(order['region_id']) and p in r['platforms']),None)
            if not rule:
                gaps.append(dict(order_key=order['order_key'],reason='historical_region_rule_missing'))
                continue
            coefficient = action.get('region_coefficients',{}).get(key,rule['factor'])
        price = render(dec(action['base_prices']['pc' if p=='PC' else 'console'])/100,
            dict(base_k=order['base_k'],bonus_k=order['bonus_k'],retained_ratio=retained),coefficient)
        paid = replay_promotion(price['regular_usd'],order['promotion_path'])
        rows.append(dict(order,regular_usd=price['regular_usd'],paid_usd=str(paid),revenue_cny=None,
                         price_version='counterfactual_fixed_orders',paid_is_net_of_refunds=False))
    return dict(status='historical_orders_missing' if gaps and not rows else 'partial' if gaps else 'available',
        orders=rows,totals=order_totals(rows) if rows or not gaps else None,gaps=gaps,
        assumptions='same real order identities, quantities, eligibility, historical refunds and purchase cost; merchandise price before refunds, no demand response or fee projection',execution_authorized=False)


def causal_estimate(snapshots):
    rows,seen,gaps = [],set(),[]
    for snapshot in snapshots:
        design = snapshot.get('causal_design') or {}
        if design.get('kind')!='randomized_block' or design.get('all_assignments_included') is not True or design.get('unit')!='affected_resource_bundle':
            gaps.append('randomized_design_and_complete_assignment_ledger_required')
            continue
        for row in snapshot.get('experiment_observations',[]):
            required = ('assignment_id','unit_key','block_id','arm','treatment_probability','outcome_revenue_usd','outcome_matured','available_at')
            if any(row.get(key) is None for key in required) or row['outcome_matured'] is not True:
                gaps.append('assignment_outcome_or_maturity_missing')
                continue
            if instant(row['available_at'])>instant(snapshot['evidence']['checked_at']):
                gaps.append('outcome_not_available_at_asof')
                continue
            key = row['unit_key'],row['block_id']
            if key in seen:
                gaps.append('duplicate_randomization_unit')
                continue
            if not ZERO<dec(row['treatment_probability'])<1 or row['arm'] not in ('control','treatment'):
                gaps.append('randomization_probability_or_arm_invalid')
                continue
            seen.add(key)
            rows.append(row)
    if gaps or not rows or {r['arm'] for r in rows}!={'control','treatment'}:
        return dict(status='causal_identification_unavailable',gaps=sorted(set(gaps or ['both_randomized_arms_required'])),estimate=None)
    treated = sum((dec(r['outcome_revenue_usd'])/dec(r['treatment_probability']) for r in rows if r['arm']=='treatment'),ZERO)
    control = sum((dec(r['outcome_revenue_usd'])/(1-dec(r['treatment_probability'])) for r in rows if r['arm']=='control'),ZERO)
    return dict(status='identified_randomized_estimate',estimand='revenue_per_assigned_resource_time_block',assignments=len(rows),
        method='Horvitz_Thompson_difference',propensity_basis='treatment_probability_for_both_arms',effect_usd=str((treated-control)/len(rows)),
        uncertainty='point_estimate_only_cluster_uncertainty_not_estimated',
        assumptions='verified random assignment, complete failure/exit ledger, mature comparable outcomes; no interference assumed')
