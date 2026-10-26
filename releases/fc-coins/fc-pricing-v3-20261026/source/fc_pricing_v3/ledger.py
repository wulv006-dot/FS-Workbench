"""Durable FC ownership, allocation, outcome accounting and original-operation recovery."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import random
import sqlite3
import uuid
from decimal import Decimal

from .financial import fingerprint, instant, number
from . import PROGRAM_CONTRACT

TABLES = ('pricing_plans', 'pricing_snapshots', 'strategy_decisions', 'financial_proofs',
          'market_comparisons', 'experiment_assignments', 'actual_price_windows',
          'operations', 'readback_receipts', 'budget_references', 'reservations',
          'settlements', 'monthly_targets', 'target_adjustments', 'incidents',
          'recovery_actions', 'model_versions', 'retirement_inventory', 'engine_generations')
TABLES=TABLES+('manual_previews','market_observations','historical_inputs')
PENDING = {'PREPARED', 'AUTHORIZED', 'DISPATCHED', 'UNKNOWN', 'PARTIALLY_APPLIED',
           'BACKEND_CONFIRMED', 'CACHE_CONFIRMED', 'PUBLIC_CONFIRMED'}


def clock():
    return datetime.now(timezone.utc)


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS metadata (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS plan_ownership (
                    resource TEXT PRIMARY KEY, plan_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    generation TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS resource_leases (
                    resource TEXT PRIMARY KEY, operation_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS durable_jobs (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, due_at TEXT NOT NULL,
                    state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS event_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT UNIQUE NOT NULL,
                    kind TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS consumer_cursors (id TEXT PRIMARY KEY, value INTEGER NOT NULL);
            ''')
            for table in TABLES:
                db.execute('CREATE TABLE IF NOT EXISTS '+table+' (id TEXT PRIMARY KEY, body TEXT NOT NULL)')

    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=5, factory=Connection)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            yield db

    def get(self, table, key, db=None):
        if db is None:
            with self.connect() as conn:
                return self.get(table, key, conn)
        row = db.execute('SELECT body FROM '+table+' WHERE id=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, table, key, body, db=None):
        if db is None:
            with self.transaction() as conn:
                return self.put(table, key, body, conn)
        value=json.dumps(body, ensure_ascii=False, sort_keys=True)
        if db.execute('UPDATE '+table+' SET body=? WHERE id=?',(value,key)).rowcount==0:
            db.execute('INSERT INTO '+table+' (id,body) VALUES (?,?)',(key,value))
        return body

    def all(self, table):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM '+table)]

    def generation(self):
        return self.get('metadata', 'generation')

    def activate_generation(self, generation, retirement, unresolved=()):
        with self.transaction() as db:
            for op in unresolved:
                self.put('operations', op['operation_id'], op, db)
                for resource in op['resources']:
                    db.execute('INSERT OR IGNORE INTO resource_leases VALUES (?,?)',
                               (resource, op['operation_id']))
            old = self.get('metadata', 'generation', db)
            if old and old['id'] == generation:
                return old
            record = dict(id=generation, activated_at=clock().isoformat(), previous=old,
                          legacy_dispatch_enabled=False)
            self.put('metadata', 'generation', record, db)
            self.put('engine_generations', generation, record, db)
            for item in retirement:
                self.put('retirement_inventory', item['id'], item, db)
            return record

    def enqueue(self, kind, key, due, body, db=None):
        if db is None:
            with self.transaction() as conn:
                return self.enqueue(kind, key, due, body, conn)
        db.execute('INSERT OR IGNORE INTO durable_jobs(id,kind,due_at,state,body) VALUES (?,?,?,\'queued\',?)',
                   (key, kind, due.isoformat() if isinstance(due, datetime) else due, json.dumps(body)))

    def create_plan(self, mode, resources, anchor, *, starts_at=None, ends_at=None,
                    daily_budget=None, actor='wulv', manual_locked=True, generation=None,plan_id=None,parameters=None):
        from .engine import POLICIES,sprint_parameters
        from .financial import FINANCIAL_CONTRACT_VERSION
        if mode not in POLICIES or not resources:
            raise ValueError('pricing_plan_scope_invalid')
        now = clock()
        parameters=dict(parameters or {})
        if set(parameters)-{'offsets_pct','allocation','capacity_reserve_ratio','preferred_undercut_pct','sprint_policy_version'}:
            raise ValueError('pricing_plan_parameters_invalid')
        allocation=parameters.get('allocation')
        if allocation and (set(allocation)!={'control','exploit','explore'} or sum(number(v,zero=True) for v in allocation.values())!=1):
            raise ValueError('pricing_allocation_invalid')
        if parameters.get('offsets_pct') is not None and (not parameters['offsets_pct'] or any(not Decimal('-99')<Decimal(str(v))<Decimal('100') for v in parameters['offsets_pct'])):
            raise ValueError('pricing_offsets_invalid')
        if parameters.get('capacity_reserve_ratio') is not None and not 0<=number(parameters['capacity_reserve_ratio'],zero=True)<1:
            raise ValueError('pricing_capacity_reserve_invalid')
        if mode=='revenue_sprint':
            resolved=sprint_parameters(dict(parameters=parameters))
            parameters.update(sprint_policy_version=resolved['sprint_policy_version'],preferred_undercut_pct=resolved['preferred_undercut_pct'])
        request_hash=fingerprint(dict(mode=mode,resources=sorted(set(resources)),anchor=anchor,starts_at=starts_at,
                                     ends_at=ends_at,actor=actor,parameters=parameters))
        start = instant(starts_at) if starts_at else now
        end = instant(ends_at) if ends_at else None
        if end is None and mode in ('acquisition','flash_sale','revenue_sprint'):
            if mode=='acquisition':
                end=start+timedelta(days=7)
            elif mode=='flash_sale':
                end=start+timedelta(hours=72)
            else:
                local=start.astimezone(timezone(timedelta(hours=8)))
                end=(local.replace(day=28)+timedelta(days=4)).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
        if end and end <= start:
            raise ValueError('pricing_plan_deadline_invalid')
        generation = generation or (self.generation() or {}).get('id')
        if not generation:
            raise ValueError('pricing_generation_not_active')
        ident = plan_id or str(uuid.uuid4())
        existing=self.get('pricing_plans',ident)
        if existing:
            if existing.get('request_hash')!=request_hash:
                raise ValueError('pricing_plan_payload_conflict')
            return existing
        plan = dict(plan_id=ident, revision=1, mode=mode, generation=generation,
                    resources=sorted(set(resources)), price_anchor=anchor,
                    starts_at=start.isoformat(), ends_at=end.isoformat() if end else None,
                    state='SCHEDULED' if start > now else 'DRAFT', actor=actor,
                    budget_policy='none', manual_locked=manual_locked,
                    parameters=parameters,request_hash=request_hash,
                    created_at=now.isoformat(), review_contract=PROGRAM_CONTRACT,financial_contract_version=FINANCIAL_CONTRACT_VERSION)
        with self.transaction() as db:
            self.put('pricing_plans', ident, plan, db)
            if end:
                self.enqueue('deadline', 'deadline:'+ident+':1', end, dict(plan_id=ident, revision=1), db)
            self.enqueue('start', 'start:'+ident+':1', start, dict(plan_id=ident, revision=1), db)
        return plan

    def migrate_financial_contract(self,ident,expected_revision,actor):
        from .financial import FINANCIAL_CONTRACT_VERSION
        from .engine import SPRINT_POLICY_VERSION
        now=clock();key='financial-plan-migration:'+ident+':'+str(expected_revision)
        with self.transaction() as db:
            old=self.get('metadata',key,db)
            if old:
                if old['actor']!=actor:raise ValueError('pricing_migration_actor_conflict')
                return self.get('pricing_plans',ident,db)
            plan=self.get('pricing_plans',ident,db)
            if not plan or type(expected_revision) is not int or plan['revision']!=expected_revision:raise ValueError('pricing_plan_revision_changed')
            if plan.get('financial_contract_version')==FINANCIAL_CONTRACT_VERSION and plan.get('budget_policy')=='none' and (plan['mode']!='revenue_sprint' or plan.get('parameters',{}).get('sprint_policy_version')==SPRINT_POLICY_VERSION):return plan
            if plan['state'] not in ('SUSPENDED','DRAFT'):raise ValueError('pricing_migration_requires_paused_plan')
            if plan.get('ends_at') and now>=instant(plan['ends_at']):raise ValueError('pricing_plan_expired')
            for row in db.execute('SELECT body FROM operations'):
                op=json.loads(row[0])
                if op['status'] not in ('COMPLETED','NO_CHANGE','CANCELLED','CANCELLED_NOT_SENT') and set(op['resources'])&set(plan['resources']):raise ValueError('pricing_resource_unresolved')
            before=json.loads(json.dumps(plan));plan['revision']+=1
            plan['financial_contract_version']=FINANCIAL_CONTRACT_VERSION
            plan.pop('daily_budget',None);plan.pop('total_budget',None);plan['budget_policy']='none'
            if plan['mode']=='revenue_sprint':plan.setdefault('parameters',{}).update(sprint_policy_version=SPRINT_POLICY_VERSION,preferred_undercut_pct='7.5')
            plan['financial_migration_id']=key
            self.put('pricing_plans',ident,plan,db)
            db.execute('UPDATE plan_ownership SET revision=? WHERE plan_id=? AND revision=?',(plan['revision'],ident,expected_revision))
            block=int(now.timestamp())//(6*3600)
            prior=self.get('experiment_assignments',fingerprint([ident,expected_revision,block]),db)
            if prior:self.put('experiment_assignments',fingerprint([ident,plan['revision'],block]),prior,db)
            if plan.get('ends_at'):self.enqueue('deadline','deadline:'+ident+':'+str(plan['revision']),plan['ends_at'],dict(plan_id=ident,revision=plan['revision']),db)
            self.put('metadata',key,dict(actor=actor,created_at=now.isoformat(),before=before,after=plan,allocation_carried=bool(prior),budget_limits_removed=True,deadline_and_original_records_preserved=True),db)
            return plan

    def activate_plan(self, ident, *, now=None):
        from .financial import FINANCIAL_CONTRACT_VERSION
        from .engine import sprint_parameters
        now = now or clock()
        with self.transaction() as db:
            plan = self.get('pricing_plans', ident, db)
            if not plan:
                raise ValueError('pricing_plan_missing')
            if plan.get('financial_contract_version')!=FINANCIAL_CONTRACT_VERSION:raise ValueError('pricing_financial_plan_migration_required')
            if plan['mode']=='revenue_sprint':sprint_parameters(plan)
            if instant(plan['starts_at']) > now:
                return plan
            if plan['ends_at'] and now >= instant(plan['ends_at']):
                raise ValueError('pricing_plan_expired')
            if plan['generation'] != self.get('metadata', 'generation', db)['id']:
                raise ValueError('pricing_generation_retired')
            for resource in plan['resources']:
                if db.execute('SELECT 1 FROM resource_leases WHERE resource=?', (resource,)).fetchone():
                    raise ValueError('pricing_resource_unresolved')
                if db.execute('UPDATE plan_ownership SET plan_id=?,revision=?,generation=? WHERE resource=?',
                              (ident,plan['revision'],plan['generation'],resource)).rowcount==0:
                    db.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)',
                               (resource,ident,plan['revision'],plan['generation']))
            plan['state'] = 'ACTIVE'
            self.put('pricing_plans', ident, plan, db)
            return plan

    def active_plan(self):
        with self.connect() as db:
            row = db.execute('SELECT plan_id FROM plan_ownership ORDER BY resource LIMIT 1').fetchone()
            return self.get('pricing_plans', row[0], db) if row else None

    def active_plans(self):
        with self.connect() as db:
            return [self.get('pricing_plans',row[0],db) for row in db.execute('SELECT DISTINCT plan_id FROM plan_ownership')]

    def owns(self, plan, resources, db):
        if (self.get('metadata', 'generation', db) or {}).get('id') != plan['generation']:
            raise ValueError('pricing_generation_retired')
        for resource in resources:
            row = db.execute('SELECT * FROM plan_ownership WHERE resource=?', (resource,)).fetchone()
            if not row or (row['plan_id'], row['revision'], row['generation']) != (plan['plan_id'], plan['revision'], plan['generation']):
                raise ValueError('pricing_resource_taken_over')

    def assignment(self, plan, candidates, *, now=None, model_version='central-prior-e2'):
        from .engine import POLICIES
        now = now or clock()
        block = int(now.timestamp()) // (6*3600)
        key = fingerprint([plan['plan_id'], plan['revision'], block])
        with self.transaction() as db:
            previous = self.get('experiment_assignments', key, db)
            actions = {fingerprint(c['action']): c for c in candidates}
            if previous and fingerprint(previous['action']) in actions:
                return previous
            ordered = sorted(candidates, key=lambda c: (Decimal(c['score']['objective']),
                             Decimal(c['score'].get('revenue_index',c['score'].get('revenue') or '0'))), reverse=True)
            if not ordered:
                raise ValueError('pricing_no_feasible_candidate')
            custom=plan.get('parameters',{}).get('allocation')
            weights = [float(custom[k]) for k in ('control','exploit','explore')] if custom else POLICIES[plan['mode']]['allocation']
            probabilities = {}
            labels = {}
            for label, allocation in zip(('control','exploit','explore'), weights):
                pool = ordered[:1] if label == 'exploit' else [c for c in ordered if c.get('control')] if label == 'control' else ordered
                if not pool:
                    pool = ordered[:1]
                for c in pool:
                    h = fingerprint(c['action'])
                    probabilities[h] = probabilities.get(h, 0) + allocation/len(pool)
                    labels.setdefault(h, []).append(label)
            seed = previous['seed'] if previous else fingerprint([key, None, model_version])
            draw = previous['draw'] if previous else random.Random(seed).random()
            cumulative = 0
            selected = next(iter(probabilities))
            for h, probability in probabilities.items():
                cumulative += probability
                if draw <= cumulative:
                    selected = h
                    break
            assignment = dict(assignment_id=str(uuid.uuid4()), plan_id=plan['plan_id'],
                revision=plan['revision'], generation=plan['generation'], block=block,
                action=actions[selected]['action'], candidate=actions[selected], probabilities=probabilities,
                labels=labels[selected], seed=seed, draw=draw, model_version=model_version,
                deterministic=len(probabilities)==1, created_at=now.isoformat(),
                parent_assignment_id=previous['assignment_id'] if previous else None,
                ends_at=min(now.replace(hour=(now.hour//6)*6, minute=0, second=0, microsecond=0)+timedelta(hours=6),
                            instant(plan['ends_at']) if plan.get('ends_at') else now+timedelta(hours=6)).isoformat())
            if previous:
                self.put('experiment_assignments',previous['assignment_id'],previous,db)
            self.put('experiment_assignments', key, assignment, db)
            return assignment

    def budget_usage(self,plan,now=None,db=None):
        """One six-hour assignment has one forecast; actual order keys are counted once."""
        if db is None:
            with self.connect() as conn:return self.budget_usage(plan,now,conn)
        now=now or clock();buckets={}
        def bucket(ident,group,plan_id,at):
            return buckets.setdefault((ident,group),dict(plan_id=plan_id,latest=at,outstanding=False,cost_pending=False,
                predicted={k:Decimal(0) for k in ('concession','negative_contribution')},actual={k:Decimal(0) for k in ('concession','negative_contribution')}))
        for row in db.execute('SELECT body FROM reservations'):
            r=json.loads(row[0])
            for group,predicted in r['groups'].items():
                b=bucket(r.get('assignment_id') or r['operation_id'],group,r['plan_id'],r['created_at'])
                b['outstanding']|=r['state']!='SETTLED';b['latest']=max(b['latest'],r['created_at'])
                if r['state']!='SETTLED':
                    for kind in b['predicted']:b['predicted'][kind]=max(b['predicted'][kind],number(predicted.get(kind) or '0',zero=True))
        for row in db.execute('SELECT body FROM settlements'):
            r=json.loads(row[0]);op=self.get('operations',r.get('operation_id',''),db) or {}
            ident=(op.get('bundle') or {}).get('assignment_id') or r.get('operation_id') or 'legacy:'+fingerprint(r)
            b=bucket(ident,r['group'],op.get('plan_id',r.get('plan_id')),r['occurred_at'])
            b['latest']=max(b['latest'],r['occurred_at'])
            for kind in b['actual']:
                if r.get(kind) is None:b['cost_pending']=True
                else:b['actual'][kind]+=number(r[kind],zero=True)
        groups={};total={k:Decimal(0) for k in ('concession','negative_contribution')};assignments={};pending=0
        for (ident,group),b in buckets.items():
            pending+=int(b['cost_pending'])
            values={k:max(b['predicted'][k],b['actual'][k]) for k in total}
            if b['plan_id']==plan['plan_id']:
                for kind,value in values.items():total[kind]+=value
            if b['outstanding'] or instant(b['latest'])>now-timedelta(hours=24):
                amounts=groups.setdefault(group,{k:Decimal(0) for k in total})
                for kind,value in values.items():amounts[kind]+=value
            assignments.setdefault(ident,{})[group]={k:str(v) for k,v in values.items()}
        return dict(groups={g:{k:str(v) for k,v in a.items()} for g,a in groups.items()},
                    plan_total={k:str(v) for k,v in total.items()},assignment_usage=assignments,cost_pending_operations=pending,
                    basis='max_assignment_forecast_and_actual; repeated_same_assignment_does_not_reserve_six_hours_again')

    def reserve(self, operation_id, group_amounts, plan, now, db,assignment_id=None):
        existing=self.get('reservations',operation_id,db)
        if existing:return existing
        # Historical accounting compatibility; new executions do not reserve or enforce budgets.
        value=dict(operation_id=operation_id,assignment_id=assignment_id,groups=group_amounts,state='RESERVED',plan_id=plan['plan_id'],
                   created_at=now.isoformat(),budget_kind='soft_known_orders_and_quotes')
        return self.put('reservations',operation_id,value,db)

    def override_assignment(self,plan,prior,candidate,reason):
        block=prior['block']
        key=fingerprint([plan['plan_id'],plan['revision'],block])
        value=dict(prior,assignment_id=str(uuid.uuid4()),action=candidate['action'],candidate=candidate,
                   parent_assignment_id=prior['assignment_id'],original_assignment_id=prior['assignment_id'],
                   deviation_reason=reason,effective_choice='explicit_business_decision_not_new_random_draw')
        with self.transaction() as db:
            self.put('experiment_assignments',prior['assignment_id'],prior,db)
            self.put('experiment_assignments',value['assignment_id'],value,db)
            self.put('experiment_assignments',key,value,db)
        return value

    def prepare(self, plan, bundle, *, operation_id=None, now=None,dispatch_context=None):
        now = now or clock()
        operation_id = operation_id or bundle['decision_bundle_id']
        with self.transaction() as db:
            old = self.get('operations', operation_id, db)
            if old:
                if fingerprint(old['bundle']) != fingerprint(bundle):
                    raise ValueError('pricing_operation_payload_conflict')
                return old
            self.owns(plan, bundle.get('mutable_resources',bundle['resources']), db)
            if now >= instant(bundle['valid_until']):
                raise ValueError('pricing_authorization_expired')
            if plan['ends_at'] and now >= instant(plan['ends_at']):
                raise ValueError('pricing_plan_expired')
            if plan['state'] != 'ACTIVE':
                raise ValueError('pricing_plan_inactive')
            for resource in bundle['resources']:
                if db.execute('SELECT 1 FROM resource_leases WHERE resource=?', (resource,)).fetchone():
                    raise ValueError('pricing_resource_unresolved')
                db.execute('INSERT INTO resource_leases VALUES (?,?)', (resource, operation_id))
            op = dict(operation_id=operation_id, plan_id=plan['plan_id'], revision=plan['revision'],
                      generation=plan['generation'], status='AUTHORIZED', resources=bundle['resources'],
                      bundle=bundle, steps=bundle['steps'], created_at=now.isoformat())
            op['dispatch_context']=dispatch_context or {}
            self.put('operations', operation_id, op, db)
            return op

    def claim_dispatch(self, operation_id, step_id, *, now=None):
        now = now or clock()
        with self.transaction() as db:
            op = self.get('operations', operation_id, db)
            plan = self.get('pricing_plans', op['plan_id'], db)
            self.owns(plan, op['bundle'].get('mutable_resources',op['resources']), db)
            step = next(s for s in op['steps'] if s['step_id'] == step_id)
            if step.get('dispatched_at'):
                return None
            if plan['state'] != 'ACTIVE':
                raise ValueError('pricing_plan_inactive')
            before = op['steps'][:op['steps'].index(step)]
            if any(s.get('state')!='CONFIRMED' for s in before):
                raise ValueError('pricing_previous_step_unresolved')
            if now >= instant(op['bundle']['valid_until']) or (plan['ends_at'] and now >= instant(plan['ends_at'])):
                raise ValueError('pricing_authorization_expired')
            step['dispatched_at'] = now.isoformat()
            step['state'] = 'DISPATCHED'
            op['status'] = 'DISPATCHED'
            self.put('operations', operation_id, op, db)
            return step

    def step_result(self, operation_id, step_id, state, receipt):
        with self.transaction() as db:
            op = self.get('operations', operation_id, db)
            step = next(s for s in op['steps'] if s['step_id'] == step_id)
            if step.get('receipt') is not None:
                step.setdefault('receipt_history',[]).append(dict(state=step['state'],receipt=step['receipt'],recorded_at=clock().isoformat()))
            step.update(state=state, receipt=receipt)
            op['status'] = state if state in ('UNKNOWN','PARTIALLY_APPLIED') else 'BACKEND_CONFIRMED'
            self.put('operations', operation_id, op, db)
            return op

    def settle_order(self,record):
        """Source-owned order key updates one original settlement, including late refunds/costs."""
        ident=record['order_key']
        if record.get('origin')!='actual_bound_order' or not record.get('price_window_id') or record.get('mode')!='production':
            raise ValueError('pricing_budget_unbound_order')
        with self.transaction() as db:
            op=self.get('operations',record['operation_id'],db)
            if not op or record['price_window_id']!=op['operation_id']:
                raise ValueError('pricing_budget_exposure_mismatch')
            old=self.get('settlements',ident,db)
            if old and old['operation_id']!=record['operation_id']:
                raise ValueError('pricing_budget_order_rebound')
            value=dict(record,plan_id=op['plan_id'],concession=str(max(Decimal(0),Decimal(record['reference_net_usd'])-Decimal(record['actual_net_usd']))),
                       updated_at=clock().isoformat(),previous_versions=(old or {}).get('previous_versions',[]))
            if old and old.get('source_sha256')!=record.get('source_sha256'):
                value['previous_versions'].append({k:v for k,v in old.items() if k!='previous_versions'})
            if record.get('actual_contribution_usd') is None:
                value.update(negative_contribution=None,status='COST_PENDING')
            else:
                value.update(negative_contribution=str(max(Decimal(0),-Decimal(record['actual_contribution_usd']))),status='SETTLED')
            return self.put('settlements',ident,value,db)

    def cancel_not_sent(self,operation_id,reason):
        """Release only a durably proven zero-business-dispatch operation."""
        with self.transaction() as db:
            op=self.get('operations',operation_id,db)
            if op['status']=='CANCELLED_NOT_SENT':return op
            if any(step.get('dispatched_at') and step.get('receipt',{}).get('status')!='NOT_SENT' for step in op['steps']):
                raise ValueError('pricing_cancellation_dispatch_not_proven_zero')
            if any(step.get('state')=='CONFIRMED' or step.get('transport_claimed_at') or step.get('state')=='UNKNOWN' and step.get('receipt',{}).get('status')!='NOT_SENT' for step in op['steps']):
                raise ValueError('pricing_cancellation_dispatch_not_proven_zero')
            for step in op['steps']:
                step.setdefault('receipt_history',[]).append(dict(state=step.get('state'),receipt=step.get('receipt'),recorded_at=clock().isoformat()))
                step.update(state='CANCELLED_NOT_SENT',cancellation_reason=reason)
            op.update(status='CANCELLED_NOT_SENT',completed_at=clock().isoformat(),cancellation_reason=reason,write_performed=False)
            reservation=self.get('reservations',operation_id,db)
            if reservation:
                reservation.update(state='SETTLED',settlement_basis='durable_zero_business_dispatch',closed_at=clock().isoformat())
                self.put('reservations',operation_id,reservation,db)
            self.put('operations',operation_id,op,db)
            db.execute('DELETE FROM resource_leases WHERE operation_id=?',(operation_id,))
            return op

    def finish(self, operation_id, receipt, *, no_change=False):
        with self.transaction() as db:
            op = self.get('operations', operation_id, db)
            if op['status'] in ('COMPLETED','NO_CHANGE'):
                return op
            if not no_change and not all(s.get('state') == 'CONFIRMED' for s in op['steps']):
                raise ValueError('pricing_steps_unconfirmed')
            op.update(status='NO_CHANGE' if no_change else 'COMPLETED', readback=receipt,
                      completed_at=clock().isoformat())
            self.put('operations', operation_id, op, db)
            self.put('readback_receipts', operation_id, receipt, db)
            self.record_price_window(op,db,no_change=no_change)
            db.execute('DELETE FROM resource_leases WHERE operation_id=?', (operation_id,))
            return op

    def record_price_window(self,op,db,*,no_change=False):
        operation_id=op['operation_id']
        opened=clock().isoformat()
        for row in db.execute('SELECT id,body FROM actual_price_windows').fetchall():
            window=json.loads(row[1])
            affected=set(window.get('resources',[]))&set(op['bundle'].get('mutable_resources',op['resources']))
            if not window.get('closed_at') and affected:
                closed=window.setdefault('resource_closed_at',{})
                for resource in affected:closed.setdefault(resource,opened)
                if all(resource in closed for resource in window.get('resources',[])):window['closed_at']=max(closed.values())
                self.put('actual_price_windows',row[0],window,db)
        self.put('actual_price_windows', operation_id, dict(operation_id=operation_id,plan_id=op.get('plan_id'),generation=op.get('generation'),
                 resources=op['bundle'].get('mutable_resources',op['resources']),mutable_resources=op['bundle'].get('mutable_resources',op['resources']),
                 assignment_id=op['bundle']['assignment_id'],action=op['bundle']['action'],
                 catalog=op['bundle'].get('catalog',{}),budget_reference=op['bundle'].get('budget_reference',{}),
                 platforms=op['bundle'].get('affected_platforms',[]),assignment_probability=op['bundle'].get('assignment_probability'),
                 randomization_verified=op['bundle'].get('randomization_verified',False),origin='confirmed_public_price_window',mode='production',
                 opened_at=opened,no_change=no_change), db)


    def finish_known_partial(self,operation_id,receipt,actual_action,reason):
        with self.transaction() as db:
            op=self.get('operations',operation_id,db)
            if op['status']=='KNOWN_PARTIAL_EXIT_PENDING':return op
            if not any(s['state']=='CONFIRMED' for s in op['steps']) or any(s['state'] not in ('CONFIRMED','CANCELLED_NOT_SENT') for s in op['steps']):
                raise ValueError('pricing_partial_actual_state_unresolved')
            if receipt.get('status')!='PUBLIC_CONFIRMED':raise ValueError('pricing_partial_public_unconfirmed')
            op.update(status='KNOWN_PARTIAL_EXIT_PENDING',actual_action=actual_action,readback=receipt,
                      target_not_completed=True,exit_reason=reason,actual_state_confirmed_at=clock().isoformat())
            self.put('operations',operation_id,op,db)
            self.put('readback_receipts',operation_id,receipt,db)
            actual_resources=[]
            for g,value in actual_action['base_prices'].items():
                if Decimal(value)!=Decimal(op['bundle']['before_action']['base_prices'][g]):actual_resources.append('base:'+g)
            for key,value in actual_action.get('region_coefficients',{}).items():
                if Decimal(value)!=Decimal(op['bundle']['before_action'].get('region_coefficients',{}).get(key,'1')):actual_resources.append('region:'+key)
            exposure=dict(op,bundle=dict(op['bundle'],action=actual_action,mutable_resources=actual_resources))
            self.record_price_window(exposure,db)
            db.execute('DELETE FROM resource_leases WHERE operation_id=?',(operation_id,))
            return op

    def deadline(self, plan_id, revision):
        with self.transaction() as db:
            plan = self.get('pricing_plans', plan_id, db)
            if not plan or plan['revision'] != revision:
                return {'status':'superseded'}
            if plan['state']=='ENDED':
                return plan
            if plan['state']=='SUSPENDED' or plan.get('deadline_pending_while_suspended'):
                pending=any(json.loads(row[0]).get('plan_id')==plan_id and
                            json.loads(row[0]).get('status') in PENDING|{'KNOWN_PARTIAL_PUBLIC_PENDING','KNOWN_PARTIAL_EXIT_PENDING'}
                            for row in db.execute('SELECT body FROM operations'))
                if pending:
                    plan['deadline_pending_while_suspended']=True
                    self.put('pricing_plans',plan_id,plan,db)
                    return dict(status='suspended_deadline_original_reconciliation_pending',plan_id=plan_id)
                db.execute('DELETE FROM plan_ownership WHERE plan_id=? AND revision=?',(plan_id,revision))
                plan.update(state='ENDED',ended_at=clock().isoformat(),exit_reason='suspended_deadline_no_new_price')
                self.put('pricing_plans',plan_id,plan,db)
                return plan
            plan['state'] = 'ENDING'
            self.put('pricing_plans', plan_id, plan, db)
            owned = [r[0] for r in db.execute('SELECT resource FROM plan_ownership WHERE plan_id=? AND revision=?', (plan_id, revision))]
            if owned:
                self.enqueue('exit', 'exit:'+plan_id+':'+str(revision), clock(),
                             dict(plan_id=plan_id, revision=revision, resources=owned), db)
            else:
                plan['state'] = 'ENDED'
                self.put('pricing_plans', plan_id, plan, db)
            return plan

    def incident(self, code, dependency, scopes, *, phase='collection', error=None):
        key = fingerprint([code, dependency, 'FC27'])
        with self.transaction() as db:
            old = self.get('incidents', key, db)
            value = dict(incident_key=key, root_cause_key=code, code=code, dependency=dependency,
                         affected_scopes=sorted(set(scopes)), phase=phase, first_seen=(old or {}).get('first_seen',clock().isoformat()),
                         last_seen=clock().isoformat(), attempt=(old or {}).get('attempt',0)+1,
                         error=error, state='OPEN', observability_degraded=code=='MONITOR_READ_FAILED')
            self.put('incidents', key, value, db)
            if not old or set(scopes)-set(old['affected_scopes']):
                db.execute('INSERT OR IGNORE INTO event_outbox(event_key,kind,body) VALUES (?,?,?)',
                    (key+':'+fingerprint(scopes), 'incident', json.dumps(value)))
            return value
