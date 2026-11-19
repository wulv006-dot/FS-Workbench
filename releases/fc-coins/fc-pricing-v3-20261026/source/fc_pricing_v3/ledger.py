"""Durable FC ownership, allocation, outcome accounting and original-operation recovery."""
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import random
import sqlite3
import uuid
from decimal import Decimal

from .financial import fingerprint, instant, number
from .dispatch import CURVE_REJECTED, CURVE_WRITE_PROTOCOL
from . import PROGRAM_CONTRACT
from .platforms import PLATFORMS, PRICE_SCOPE_CONTRACT, native_resources, native_action, action_key

TABLES = ('pricing_plans', 'pricing_snapshots', 'strategy_decisions', 'financial_proofs',
          'market_comparisons', 'experiment_assignments', 'actual_price_windows',
          'operations', 'readback_receipts', 'budget_references', 'reservations',
          'settlements', 'monthly_targets', 'target_adjustments', 'incidents',
          'recovery_actions', 'model_versions', 'retirement_inventory', 'engine_generations')
TABLES=TABLES+('manual_previews','market_observations','historical_inputs')
TABLES=TABLES+('ladder_proposals',)
PENDING = {'PREPARED', 'AUTHORIZED', 'DISPATCHED', 'UNKNOWN', 'PARTIALLY_APPLIED',
           'BACKEND_CONFIRMED', 'CACHE_CONFIRMED', 'PUBLIC_CONFIRMED'}


def clock():
    return datetime.now(timezone.utc)


def confirmed_curve_window(op):
    """Freeze the original writer's confirmed primary rows, never its proposal."""
    from .price_curve import curve_key, read_curve
    from .business_source import _window_curve
    bundle, receipt = op['bundle'], op.get('readback') or {}
    if (receipt.get('write_protocol') != 'fc27_curve_v6' or receipt.get('status') != 'CONFIRMED'
            or receipt.get('execution_id') != op['operation_id']):
        raise ValueError('curve_window_original_receipt_unconfirmed')
    action = deepcopy(bundle['action'])
    decisions, confirmations = {}, {}
    platforms = bundle.get('affected_platforms')
    if not platforms:
        raise ValueError('curve_window_scope_missing')
    for platform in platforms:
        row = (receipt.get('curve_results') or {}).get(platform) or {}
        target = bundle['action']['curves'][platform]
        target = read_curve(target['native_payload'], target['identity'], target['native_contract'])
        target_key = curve_key(target)
        projection = row.get('projection') or {}
        mismatch = (projection.get('status') == 'unchanged_mismatch'
                    and projection.get('write_performed') is False
                    and 'send_intent' not in projection
                    and projection.get('before_read_only_rate') == projection.get('readback_rate')
                    and row.get('before_rate') == row.get('target_rate') == projection.get('expected_rate'))
        if (row.get('operation_id') != op['operation_id'] or row.get('platform') != platform
                or row.get('target_curve_key') != target_key
                or (row.get('catalog') or {}).get('status') != 'confirmed'
                or (row.get('propagation') or {}).get('status') != 'confirmed'
                or projection.get('status') not in ('confirmed', 'not_required') and not mismatch):
            raise ValueError('curve_window_full_readback_unconfirmed')
        action['curves'][platform] = row.get('actual_site266_curve')
        actual = _window_curve(action, platform)
        actual_key = curve_key(actual)
        mapping = row['propagation'].get('curve_mapping') or {}
        if (row.get('actual_site266_curve_key') != actual_key
                or mapping.get('actual_site266_curve_key') != actual_key
                or mapping.get('target_curve_key') != target_key
                or mapping.get('basis') != 'full_prices_and_tier_specs_readback'
                or target['tiers'] != actual['tiers']
                or target['unit_price_usd_per_k'] != actual['unit_price_usd_per_k']):
            raise ValueError('curve_window_primary_mapping_unconfirmed')
        action['curves'][platform] = actual
        decisions[platform] = target_key
        confirmations[platform] = dict(operation_id=op['operation_id'], **mapping)
    return action, dict(write_protocol='fc27_curve_v6', price_scope_contract=PRICE_SCOPE_CONTRACT,
                        decision_curve_keys=decisions, curve_confirmations=confirmations)


def fully_owned_plans(db):
    """A partially replaced plan cannot execute its original full resource set."""
    ownership = {r[0]: tuple(r[1:]) for r in db.execute('SELECT resource,plan_id,revision,generation FROM plan_ownership')}
    result = []
    for ident in dict.fromkeys(row[0] for row in ownership.values()):
        row = db.execute('SELECT body FROM pricing_plans WHERE id=?', (ident,)).fetchone()
        if row:
            plan = json.loads(row[0])
            expected = (plan['plan_id'], plan['revision'], plan['generation'])
            if plan.get('resources') and all(ownership.get(resource) == expected for resource in plan['resources']):
                result.append(plan)
    return result


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

    def curve_strategy_state(self, platform, db=None):
        from .curve_strategy_v6 import curve_strategy_key
        return self.get('metadata', curve_strategy_key(platform), db)

    def start_curve_episode(self, platform, rule_revision, reason, *, expected_episode_id=None,
                            initial_curve=None, readback_ref=None, db=None):
        """Explicit internal setup from an adopted saved curve, or carry A into a new episode."""
        from .curve_strategy_v6 import curve_strategy_key, primary_reference_curve
        from .price_curve import curve_key

        if (platform not in PLATFORMS or any(not isinstance(v, str) or not v.strip()
                                            for v in (rule_revision, reason))):
            raise ValueError('strategy_episode_scope_invalid')
        key = curve_strategy_key(platform)
        with (self.transaction() if db is None else nullcontext(db)) as conn:
            state = self.curve_strategy_state(platform, conn)
            if state and initial_curve is None:
                reference = state['reference']
                episode = state['episode']
                if rule_revision == episode['rule_revision']:
                    return state
                if expected_episode_id != episode['comparison_episode_id']:
                    raise ValueError('strategy_comparison_episode_changed')
            else:
                if (expected_episode_id is not None or initial_curve is None
                        or not isinstance(readback_ref, str) or not readback_ref.strip()):
                    raise ValueError('strategy_initial_reference_evidence_required')
                initial = primary_reference_curve(initial_curve, platform)
                reference_id = fingerprint([key, curve_key(initial), readback_ref])
                if state:
                    first_episode = self.get('metadata', key + ':initial', conn)
                    if (first_episode['initial_reference_curve_id'] == reference_id
                            and first_episode['rule_revision'] == rule_revision and first_episode['reason'] == reason):
                        return state
                    raise ValueError('strategy_initial_reference_already_adopted')
                reference = dict(reference_curve=initial, reference_curve_id=reference_id,
                                 readback_ref=readback_ref, initial_adoption_reason=reason)
            prior_id = state['episode']['comparison_episode_id'] if state else None
            episode_id = fingerprint([key, prior_id, rule_revision, reference['reference_curve_id']])
            episode = dict(comparison_episode_id=episode_id, initial_reference_curve=reference['reference_curve'],
                           initial_reference_curve_id=reference['reference_curve_id'],
                           rule_revision=rule_revision, reason=reason, opened_at=clock().isoformat(),
                           prior_comparison_episode_id=prior_id)
            if state is None:
                self.put('metadata', key + ':initial', episode, conn)
            else:
                self.put('metadata', key + ':episode:' + prior_id, state['episode'], conn)
            return self.put('metadata', key, dict(reference=reference, episode=episode), conn)

    def _curve_adoption_input(self, adoption, operation_id, bundle, conn):
        from .curve_strategy_v6 import curve_proof_bound
        from .dispatch import CURVE_WRITE_PROTOCOL
        from .pricing_proof_v6 import PROVEN

        platform = adoption['platform']
        proposal, proof = adoption['proposal'], adoption['proof']
        body = {key: value for key, value in proposal.items() if key != 'adoption_id'}
        if (bundle.get('write_protocol') != CURVE_WRITE_PROTOCOL
                or platform not in bundle.get('affected_platforms', ())
                or 'base:' + platform not in bundle.get('mutable_resources', ())
                or proposal.get('operation_id') != operation_id or proposal.get('kind') != 'BUSINESS_ADOPT'
                or proposal.get('adoption_id') != fingerprint(body)
                or not curve_proof_bound(proof, proposal.get('target_curve_key'))
                or proof.get('status') != PROVEN or proof['proof_hash'] != proposal.get('proof_hash')
                or proof['scope'].get('platform') != platform or proof['scope'].get('curve_site_id') != '266'):
            raise ValueError('strategy_adoption_operation_or_proof_invalid')
        state = self.curve_strategy_state(platform, conn)
        if (not state or proposal['reference_curve_id'] != state['reference']['reference_curve_id']
                or proposal['comparison_episode_id'] != state['episode']['comparison_episode_id']
                or proposal['initial_reference_curve_id'] != state['episode']['initial_reference_curve_id']):
            raise ValueError('strategy_adoption_reference_or_episode_changed')
        return state

    def _record_curve_adoption(self, adoption, op, current, conn):
        from .curve_strategy_v6 import confirm_adoption, curve_strategy_key, primary_reference_curve, propose_adoption
        from .price_curve import curve_key

        proposal = adoption['proposal']
        ident = proposal['adoption_id']
        key = 'owned-curve-adoption-v6:' + ident
        prior = self.get('metadata', key, conn)
        if prior:
            return prior
        result = dict(adoption_id=ident, operation_id=op['operation_id'], platform=adoption['platform'])
        try:
            state = self._curve_adoption_input(adoption, op['operation_id'], op['bundle'], conn)
            current = primary_reference_curve(current, adoption['platform'])
            current_key = curve_key(current)
            candidate = dict(curve=current, curve_key=current_key)
            comparison = dict(state['episode'], candidates=[candidate], selected_segment=proposal.get('selected_segment'))
            decision = dict(status='KEEP', selected=candidate, proof_hash=adoption['proof']['proof_hash'],
                            reference_curve_id=proposal['reference_curve_id'],
                            comparison_episode_id=proposal['comparison_episode_id'])
            evidence = {field: proposal.get(field) for field in
                        ('order_revisions', 'window_ids', 'window_start', 'window_end', 'cost_revision',
                         'maturity', 'reason', 'changed_judgment', 'cumulative')}
            if propose_adoption(state['reference'], comparison, decision, evidence,
                                operation_id=op['operation_id']) != proposal:
                raise ValueError('strategy_adoption_proposal_changed')
            receipt = dict(operation_id=op['operation_id'], status=op['status'], complete_curve_readback=True,
                           curve_key=current_key, readback_ref='readback_receipts/' + op['operation_id'])
            adopted = confirm_adoption(state['reference'], proposal, current, receipt)
        except ValueError as error:
            # The writer's independently confirmed operation can still close.
            result.update(status='NOT_ADOPTED', reason=str(error))
        else:
            self.put('metadata', curve_strategy_key(adoption['platform']),
                     dict(state, reference=adopted), conn)
            result.update(status='ADOPTED', reference_curve_id=adopted['reference_curve_id'])
        return self.put('metadata', key, dict(result, proposal=proposal, proof=adoption['proof']), conn)

    def curve_cost_protection(self, platform, db=None):
        return self.get('metadata', 'owned-curve-cost-protection-v6:' + platform, db) or {}

    def restore_normal_curve_reference(self, platform, expected_reference, source_operation=None, *, db=None):
        """Repair a known historical adoption using original ledger evidence only."""
        from .curve_strategy_v6 import band_anchors, curve_strategy_key, segment_changes, update_reference_segments

        key = curve_strategy_key(platform)
        repair_key = key + ':normal-reference-repair:' + expected_reference
        with (self.transaction() if db is None else nullcontext(db)) as conn:
            prior = self.get('metadata', repair_key, conn)
            if prior:
                if prior['source_operation'] != source_operation:
                    raise ValueError('strategy_reference_repair_source_changed')
                return prior
            state = self.curve_strategy_state(platform, conn)
            reference, episode = state['reference'], state['episode']
            if reference['reference_curve_id'] != expected_reference or reference.get('event_type') != 'COST_REPAIR':
                raise ValueError('strategy_reference_repair_baseline_changed')
            if conn.execute('SELECT 1 FROM resource_leases WHERE resource=?', ('base:' + platform,)).fetchone():
                raise ValueError('strategy_reference_repair_original_operation_pending')
            previous_operation = reference['confirmed_operation_id']
            previous = self.get('operations', previous_operation, conn)
            if (not previous or previous['status'] != 'COMPLETED'
                    or self.get('readback_receipts', previous_operation, conn) != previous.get('readback')
                    or (previous.get('curve_cost_repair_result') or {}).get(platform, {}).get('reference_curve_id') != expected_reference):
                raise ValueError('strategy_reference_repair_original_receipt_missing')
            confirmed_curve_window(previous)
            initial = self.get('metadata', key + ':initial', conn)
            original_curve = initial['initial_reference_curve']
            original_ref = initial['initial_reference_curve_id']
            if source_operation:
                operation = self.get('operations', source_operation, conn)
                if (not operation or operation['status'] != 'COMPLETED' or source_operation == previous_operation
                        or self.get('readback_receipts', source_operation, conn) != operation.get('readback')):
                    raise ValueError('strategy_reference_repair_source_unconfirmed')
                selected = operation['bundle']['curve_selection'][platform]
                displaced = previous['bundle']['curve_selection'][platform]
                original_ref = displaced['reference_curve_id']
                if (operation.get('curve_cost_repair_result', {}).get(platform, {}).get('reference_curve_id') != original_ref
                        or selected.get('label') != 'COST_REPAIR'
                        or selected['reference_curve_id'] != initial['initial_reference_curve_id']):
                    raise ValueError('strategy_reference_repair_source_lineage_changed')
                curve, _ = confirmed_curve_window(operation)
                original_curve = curve['curves'][platform]
            sources = reference.get('segment_sources') or {}
            affected = [segment for segment in segment_changes(reference['reference_curve'], original_curve)
                        if not sources or (sources.get(segment) or {}).get('kind') == 'COST_REPAIR']
            if not affected:
                raise ValueError('strategy_reference_repair_segments_missing')
            source_ref = ('readback_receipts/' + source_operation) if source_operation else 'metadata/' + key + ':initial'
            updated = update_reference_segments(reference, original_curve, affected, original_ref,
                dict(operation_id=source_operation, readback_ref=source_ref), 'NORMAL_BASELINE_RESTORED')
            reference = dict(reference, **updated, event_type='NORMAL_BASELINE_RESTORED')
            state_after = dict(state, reference=reference)
            normal = band_anchors(reference['reference_curve'])
            previous_prices = band_anchors(state['reference']['reference_curve'])
            # The currently observed prices are checked at collection time.
            # Mark the affected bands so the next round prices them from A/P.
            protection = dict(status='legacy', segments={p:dict(normal=normal[p], target=previous_prices[p]) for p in affected})
            result = dict(platform=platform, prior_state=state, source_operation=source_operation,
                          restored_reference_id=reference['reference_curve_id'], restored_anchors=normal,
                          repaired_segments=affected, repaired_at=clock().isoformat())
            self.put('metadata', repair_key, result, conn)
            self.put('metadata', key, state_after, conn)
            self._save_curve_cost_protection(platform, dict(cost_protection=protection), previous_operation, conn)
            return result

    def _save_curve_cost_protection(self, platform, selection, operation_id, conn):
        protection = (selection or {}).get('cost_protection')
        if protection is not None:
            key = 'owned-curve-cost-protection-v6:' + platform
            current = self.get('metadata', key, conn) or {}
            if current.get('segments', {}) != protection['segments']:
                self.put('metadata', key, dict(protection, operation_id=operation_id), conn)

    def adopt_confirmed_curve(self, adoption, *, current_curve):
        """Apply a trusted same-round adoption to an existing confirmed operation."""
        from .curve_strategy_v6 import primary_reference_curve
        from .price_curve import curve_key

        proposal, platform = adoption['proposal'], adoption['platform']
        ident = proposal['operation_id']
        with self.transaction() as conn:
            prior = self.get('metadata', 'owned-curve-adoption-v6:' + proposal['adoption_id'], conn)
            if prior:
                if prior['proposal'] != proposal or prior['proof'] != adoption['proof'] or prior['platform'] != platform:
                    raise ValueError('strategy_adoption_payload_conflict')
                return prior
            op = self.get('operations', ident, conn)
            window = self.get('actual_price_windows', ident, conn)
            resource = 'base:' + platform
            leased = native_resources([row[0] for row in conn.execute('SELECT resource FROM resource_leases')])
            if (not op or op['status'] not in ('COMPLETED', 'NO_CHANGE') or not window or window.get('closed_at')
                    or resource not in window['resources'] or resource in window.get('resource_closed_at', {})
                    or resource in leased):
                raise ValueError('strategy_adoption_original_window_not_current')
            if self.get('readback_receipts', ident, conn) != op.get('readback'):
                raise ValueError('strategy_adoption_original_receipt_unconfirmed')
            action, _ = confirmed_curve_window(op)
            confirmed = action['curves'][platform]
            if curve_key(confirmed) != curve_key(primary_reference_curve(current_curve, platform)):
                raise ValueError('strategy_adoption_current_curve_changed')
            return self._record_curve_adoption(adoption, op, confirmed, conn)

    def current_curve_operation(self, platform, plan, expected):
        from .price_curve import curve_key

        resource = 'base:' + platform
        with self.connect() as conn:
            for raw, in conn.execute('SELECT body FROM actual_price_windows ORDER BY rowid DESC'):
                window = json.loads(raw)
                curve = (window['action'].get('curves') or {}).get(platform)
                if (window.get('closed_at') or resource in window.get('resource_closed_at', {})
                        or resource not in window.get('resources', []) or not curve):
                    continue
                original = self.get('operations', window['operation_id'], conn)
                if (original and original.get('plan_id') == plan['plan_id'] and original.get('revision') == plan['revision']
                        and original.get('status') in ('COMPLETED', 'NO_CHANGE') and curve_key(curve) == expected):
                    return window['operation_id']
                return None

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
                    daily_budget=None, actor='wulv', manual_locked=True, generation=None,plan_id=None,parameters=None,smart_strategy_version=None):
        from .engine import POLICIES,sprint_parameters
        from .financial import FINANCIAL_CONTRACT_VERSION,HISTORY_WINDOW_CONTRACT
        if (mode not in POLICIES and mode != 'smart') or not resources:
            raise ValueError('pricing_plan_scope_invalid')
        from .smart import STRATEGY_VERSION
        if mode=='smart' and smart_strategy_version is None:smart_strategy_version=STRATEGY_VERSION
        if smart_strategy_version is not None and (mode!='smart' or smart_strategy_version!=STRATEGY_VERSION):
            raise ValueError('pricing_smart_strategy_version_invalid')
        now = clock()
        parameters=dict(parameters or {})
        baseline_plan = None
        owner_snapshot = None
        if mode == 'smart':
            source = next((p for p in self.active_plans() if p['state']=='ACTIVE' and {'base:'+p for p in PLATFORMS} <= set(p['resources']) and p['mode'] in ('revenue_sprint','smart')), None)
            if not source:
                raise ValueError('pricing_smart_original_base_plan_required')
            baseline_plan = source.get('baseline_plan') if source['mode']=='smart' else source
            if not baseline_plan or baseline_plan['mode']!='revenue_sprint':
                raise ValueError('pricing_smart_original_base_plan_required')
            parameters = dict(baseline_plan.get('parameters') or {})
            if smart_strategy_version:
                baseline_plan=json.loads(json.dumps(baseline_plan))
                parameters.update(competitor_policy='lootbar_primary_arabut_secondary_v1',region_pricing='global')
                baseline_plan['parameters']=dict(parameters)
            with self.connect() as conn:
                owner_snapshot = {row['resource']:[row['plan_id'],row['revision'],row['generation']]
                                  for row in conn.execute('SELECT * FROM plan_ownership') if row['resource'] in resources}
        if set(parameters)-{'offsets_pct','allocation','capacity_reserve_ratio','preferred_undercut_pct','sprint_policy_version','competitor_policy','region_pricing'}:
            raise ValueError('pricing_plan_parameters_invalid')
        if parameters.get('competitor_policy') not in (None,'lootbar_primary_arabut_secondary_v1') or parameters.get('region_pricing') not in (None,'global'):
            raise ValueError('pricing_plan_parameters_invalid')
        parameters.update(competitor_policy='lootbar_primary_arabut_secondary_v1',region_pricing='global')
        allocation=parameters.get('allocation')
        if allocation and (set(allocation)!={'control','exploit','explore'} or sum(number(v,zero=True) for v in allocation.values())!=1):
            raise ValueError('pricing_allocation_invalid')
        if parameters.get('offsets_pct') is not None and (not parameters['offsets_pct'] or any(not Decimal('-99')<Decimal(str(v))<Decimal('100') for v in parameters['offsets_pct'])):
            raise ValueError('pricing_offsets_invalid')
        if parameters.get('capacity_reserve_ratio') is not None and not 0<=number(parameters['capacity_reserve_ratio'],zero=True)<1:
            raise ValueError('pricing_capacity_reserve_invalid')
        if mode in ('revenue_sprint','smart'):
            resolved=sprint_parameters(dict(parameters=parameters))
            parameters.update(sprint_policy_version=resolved['sprint_policy_version'],preferred_undercut_pct=resolved['preferred_undercut_pct'])
        request_hash=fingerprint(dict(mode=mode,resources=sorted(set(resources)),anchor=anchor,starts_at=starts_at,
                                     ends_at=ends_at,actor=actor,parameters=parameters))
        start = instant(starts_at) if starts_at else now
        end = instant(ends_at) if ends_at else None
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
                    created_at=now.isoformat(), review_contract=PROGRAM_CONTRACT,financial_contract_version=FINANCIAL_CONTRACT_VERSION,price_scope_contract=PRICE_SCOPE_CONTRACT,history_window_contract=HISTORY_WINDOW_CONTRACT)
        if mode=='smart':
            plan.update(baseline_plan=baseline_plan, takeover_owners=owner_snapshot)
            if smart_strategy_version:
                plan.update(smart_strategy_version=smart_strategy_version,smart_started_at=start.isoformat())
        with self.transaction() as db:
            self.put('pricing_plans', ident, plan, db)
            if end:
                self.enqueue('deadline', 'deadline:'+ident+':1', end, dict(plan_id=ident, revision=1), db)
            self.enqueue('start', 'start:'+ident+':1', start, dict(plan_id=ident, revision=1), db)
        return plan

    def migrate_smart_strategy(self, ident, expected_revision, actor):
        from .smart import STRATEGY_VERSION
        from .financial import FINANCIAL_CONTRACT_VERSION,HISTORY_WINDOW_CONTRACT
        now=clock();key='smart-strategy-migration:'+ident+':'+str(expected_revision)
        with self.transaction() as conn:
            prior=self.get('metadata',key,conn)
            if prior:
                if prior['actor']!=actor:raise ValueError('pricing_migration_actor_conflict')
                return self.get('pricing_plans',ident,conn)
            plan=self.get('pricing_plans',ident,conn)
            if type(expected_revision) is not int or not plan or plan['revision']!=expected_revision:
                raise ValueError('pricing_plan_revision_changed')
            if plan['mode']!='smart' or plan['state'] not in ('ACTIVE','SUSPENDED','DRAFT'):raise ValueError('pricing_smart_active_plan_required')
            if plan.get('write_protocol'):raise ValueError('pricing_curve_plan_requires_curve_contract')
            if plan['state']!='DRAFT':self.owns(plan,plan['resources'],conn)
            elif (self.get('metadata','generation',conn) or {}).get('id')!=plan['generation']:raise ValueError('pricing_generation_retired')
            if plan.get('smart_strategy_version')==STRATEGY_VERSION and plan.get('financial_contract_version')==FINANCIAL_CONTRACT_VERSION and plan.get('price_scope_contract')==PRICE_SCOPE_CONTRACT and set(plan['resources'])==set(native_resources(plan['resources'])):return plan
            if plan.get('ends_at') and now>=instant(plan['ends_at']):raise ValueError('pricing_plan_expired')
            for row in conn.execute('SELECT body FROM operations'):
                op=json.loads(row['body'])
                if op['status'] not in ('COMPLETED','NO_CHANGE','CANCELLED','CANCELLED_NOT_SENT','FAILED_BEFORE_WRITE','KNOWN_PARTIAL_EXITED',CURVE_REJECTED) and set(native_resources(op['resources']))&set(native_resources(plan['resources'])):
                    raise ValueError('pricing_resource_unresolved')
            for row in conn.execute("SELECT body FROM durable_jobs WHERE kind='cycle' AND state='running'"):
                if json.loads(row['body']).get('plan_id')==ident:raise ValueError('pricing_migration_cycle_running')
            if any(set(native_resources([row[0]]))&set(native_resources(plan['resources'])) for row in conn.execute('SELECT resource FROM resource_leases')):raise ValueError('pricing_resource_unresolved')
            before=json.loads(json.dumps(plan))
            from .smart import strategy_start
            from .financial import FINANCIAL_CONTRACT_VERSION,HISTORY_WINDOW_CONTRACT
            anchor=strategy_start(plan)
            next_slot=anchor+timedelta(hours=max(0,int((now-anchor).total_seconds()//3600)+1))
            plan.update(revision=expected_revision+1,smart_strategy_version=STRATEGY_VERSION,
                        smart_started_at=next_slot.isoformat(),smart_migration_id=key,
                        resources=native_resources(plan['resources']),price_scope_contract=PRICE_SCOPE_CONTRACT,
                        financial_contract_version=FINANCIAL_CONTRACT_VERSION,history_window_contract=HISTORY_WINDOW_CONTRACT)
            for target in (plan,plan['baseline_plan']):
                if target.get('price_anchor',{}).get('base_prices'):target['price_anchor']=native_action(target['price_anchor'])
                if target.get('resources'):target['resources']=native_resources(target['resources'])
                target.update(price_scope_contract=PRICE_SCOPE_CONTRACT,financial_contract_version=FINANCIAL_CONTRACT_VERSION)
            if plan.get('takeover_owners'):
                plan['takeover_owners']={r:owner for old,owner in plan['takeover_owners'].items() for r in native_resources([old])}
            control=self.get('metadata','price_control',conn)
            if control and set(control.get('manual_prices',{}))=={'console','pc'}:
                old_control=json.loads(json.dumps(control))
                control.update(revision=control['revision']+1,manual_prices={p:control['manual_prices']['pc' if p=='PC' else 'console'] for p in PLATFORMS},price_scope_contract=PRICE_SCOPE_CONTRACT)
                self.put('metadata','price_control',control,conn)
                self.put('metadata',key+':price-control',dict(before=old_control,after=control),conn)
            if plan['state']!='DRAFT':
                for resource in plan['resources']:
                    owner=conn.execute('SELECT plan_id FROM plan_ownership WHERE resource=?',(resource,)).fetchone()
                    if owner and owner[0]!=ident:raise ValueError('pricing_resource_owned')
                conn.execute('DELETE FROM plan_ownership WHERE plan_id=? AND revision=?',(ident,expected_revision))
                for resource in plan['resources']:conn.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)',(resource,ident,plan['revision'],plan['generation']))
            for target in (plan,plan['baseline_plan']):
                target.setdefault('parameters',{}).update(competitor_policy='lootbar_primary_arabut_secondary_v1',region_pricing='global')
            self.put('pricing_plans',ident,plan,conn)
            if plan.get('ends_at'):
                self.enqueue('deadline','deadline:'+ident+':'+str(plan['revision']),plan['ends_at'],dict(plan_id=ident,revision=plan['revision']),conn)
            if plan['state']=='ACTIVE':
                cycle_key='cycle:'+ident+':'+str(int(next_slot.timestamp()))+':r'+str(plan.get('resume_count',0))
                cycle_body=dict(plan_id=ident,revision=plan['revision'],scheduled_at=next_slot.isoformat())
                existing_job=conn.execute('SELECT state,body FROM durable_jobs WHERE id=?',(cycle_key,)).fetchone()
                if existing_job:
                    if existing_job['state']!='queued' or json.loads(existing_job['body']).get('plan_id')!=ident:raise ValueError('pricing_migration_slot_already_consumed')
                    conn.execute('UPDATE durable_jobs SET body=?,due_at=? WHERE id=?',(json.dumps(cycle_body),next_slot.isoformat(),cycle_key))
                else:self.enqueue('cycle',cycle_key,next_slot,cycle_body,conn)
            self.put('metadata',key,dict(actor=actor,created_at=now.isoformat(),before=before,after=plan,
                original_operations_preserved=True,price_write_performed=False),conn)
            return plan

    def migrate_financial_contract(self,ident,expected_revision,actor):
        current=self.get('pricing_plans',ident)
        if current and current.get('mode')=='smart':return self.migrate_smart_strategy(ident,expected_revision,actor)
        from .financial import FINANCIAL_CONTRACT_VERSION,HISTORY_WINDOW_CONTRACT
        from .engine import SPRINT_POLICY_VERSION,sprint_parameters
        now=clock();key='financial-plan-migration:'+ident+':'+str(expected_revision)
        with self.transaction() as db:
            old=self.get('metadata',key,db)
            if old:
                if old['actor']!=actor:raise ValueError('pricing_migration_actor_conflict')
                return self.get('pricing_plans',ident,db)
            plan=self.get('pricing_plans',ident,db)
            if not plan or type(expected_revision) is not int or plan['revision']!=expected_revision:raise ValueError('pricing_plan_revision_changed')
            if plan.get('write_protocol'):raise ValueError('pricing_curve_plan_requires_curve_contract')
            if plan.get('financial_contract_version')==FINANCIAL_CONTRACT_VERSION and plan.get('history_window_contract')==HISTORY_WINDOW_CONTRACT and plan.get('budget_policy')=='none' and (plan['mode']!='revenue_sprint' or plan.get('parameters',{}).get('sprint_policy_version')==SPRINT_POLICY_VERSION):return plan
            if plan['state'] not in ('SUSPENDED','DRAFT'):raise ValueError('pricing_migration_requires_paused_plan')
            if plan.get('ends_at') and now>=instant(plan['ends_at']):raise ValueError('pricing_plan_expired')
            for row in db.execute('SELECT body FROM operations'):
                op=json.loads(row[0])
                if op['status'] not in ('COMPLETED','NO_CHANGE','CANCELLED','CANCELLED_NOT_SENT','FAILED_BEFORE_WRITE','KNOWN_PARTIAL_EXITED',CURVE_REJECTED) and set(native_resources(op['resources']))&set(native_resources(plan['resources'])):raise ValueError('pricing_resource_unresolved')
            before=json.loads(json.dumps(plan));plan['revision']+=1
            plan['financial_contract_version']=FINANCIAL_CONTRACT_VERSION
            plan['history_window_contract']=HISTORY_WINDOW_CONTRACT
            plan['price_scope_contract']=PRICE_SCOPE_CONTRACT
            plan['resources']=native_resources(plan['resources'])
            if plan.get('price_anchor',{}).get('base_prices'):plan['price_anchor']=native_action(plan['price_anchor'])
            plan.setdefault('parameters',{}).update(competitor_policy='lootbar_primary_arabut_secondary_v1',region_pricing='global')
            plan.pop('daily_budget',None);plan.pop('total_budget',None);plan['budget_policy']='none'
            if plan['mode']=='revenue_sprint':
                try:preferred=sprint_parameters(plan)['preferred_undercut_pct']
                except ValueError:preferred='7.5'
                plan.setdefault('parameters',{}).update(sprint_policy_version=SPRINT_POLICY_VERSION,preferred_undercut_pct=preferred)
            control=self.get('metadata','price_control',db)
            if control and set(control.get('manual_prices',{}))=={'console','pc'}:
                if db.execute('SELECT 1 FROM resource_leases LIMIT 1').fetchone():raise ValueError('pricing_resource_unresolved')
                old_control=json.loads(json.dumps(control))
                control.update(revision=control['revision']+1,manual_prices={p:control['manual_prices']['pc' if p=='PC' else 'console'] for p in PLATFORMS},price_scope_contract=PRICE_SCOPE_CONTRACT)
                self.put('metadata','price_control',control,db)
                self.put('metadata',key+':price-control',dict(before=old_control,after=control),db)
            plan['financial_migration_id']=key
            self.put('pricing_plans',ident,plan,db)
            owned=[row[0] for row in db.execute('SELECT resource FROM plan_ownership WHERE plan_id=? AND revision=?',(ident,expected_revision))]
            for resource in native_resources(owned):
                other=db.execute('SELECT plan_id FROM plan_ownership WHERE resource=?',(resource,)).fetchone()
                if other and other[0]!=ident:raise ValueError('pricing_resource_owned')
            db.execute('DELETE FROM plan_ownership WHERE plan_id=? AND revision=?',(ident,expected_revision))
            for resource in native_resources(owned):db.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)',(resource,ident,plan['revision'],plan['generation']))
            block=int(now.timestamp())//(6*3600)
            prior=self.get('experiment_assignments',fingerprint([ident,expected_revision,block]),db)
            carried=bool(prior and set((prior.get('action') or {}).get('base_prices',{}))==set(PLATFORMS))
            if carried:self.put('experiment_assignments',fingerprint([ident,plan['revision'],block]),prior,db)
            if plan.get('ends_at'):self.enqueue('deadline','deadline:'+ident+':'+str(plan['revision']),plan['ends_at'],dict(plan_id=ident,revision=plan['revision']),db)
            self.put('metadata',key,dict(actor=actor,created_at=now.isoformat(),before=before,after=plan,allocation_carried=carried,budget_limits_removed=True,deadline_and_original_records_preserved=True),db)
            return plan

    def activate_plan(self, ident, *, now=None):
        from .financial import FINANCIAL_CONTRACT_VERSION
        from .engine import sprint_parameters,POLICIES
        now = now or clock()
        with self.transaction() as db:
            plan = self.get('pricing_plans', ident, db)
            if not plan:
                raise ValueError('pricing_plan_missing')
            if plan['mode'] not in POLICIES and plan['mode'] != 'smart':raise ValueError('pricing_strategy_retired')
            if plan.get('financial_contract_version')!=FINANCIAL_CONTRACT_VERSION:raise ValueError('pricing_financial_plan_migration_required')
            if plan['mode'] in ('revenue_sprint','smart') and not plan.get('write_protocol'):sprint_parameters(plan)
            if instant(plan['starts_at']) > now:
                return plan
            if plan['ends_at'] and now >= instant(plan['ends_at']):
                raise ValueError('pricing_plan_expired')
            if plan['generation'] != self.get('metadata', 'generation', db)['id']:
                raise ValueError('pricing_generation_retired')
            if any(resource in ('base:PS','base:XBOX','base:PC') for resource in plan['resources']):
                for lease in db.execute('SELECT resource FROM resource_leases'):
                    if set(native_resources([lease[0]]))&set(plan['resources']):raise ValueError('pricing_resource_unresolved')
                for owner in db.execute('SELECT * FROM plan_ownership').fetchall():
                    expanded=native_resources([owner['resource']])
                    if expanded!=[owner['resource']] and set(expanded)&set(plan['resources']):
                        for resource in expanded:
                            other=db.execute('SELECT plan_id,revision,generation FROM plan_ownership WHERE resource=?',(resource,)).fetchone()
                            if other and tuple(other)!=(owner['plan_id'],owner['revision'],owner['generation']):raise ValueError('pricing_resource_owned')
                        db.execute('DELETE FROM plan_ownership WHERE resource=?',(owner['resource'],))
                        for resource in expanded:db.execute('INSERT OR IGNORE INTO plan_ownership VALUES (?,?,?,?)',(resource,owner['plan_id'],owner['revision'],owner['generation']))
            if plan['mode']=='smart':
                actual={row['resource']:[row['plan_id'],row['revision'],row['generation']]
                        for row in db.execute('SELECT * FROM plan_ownership') if row['resource'] in plan['resources']}
                owned={resource:[ident,plan['revision'],plan['generation']] for resource in plan['resources']}
                if plan['state']=='ACTIVE' and actual==owned:
                    return plan
                if actual!=plan.get('takeover_owners'):
                    raise ValueError('pricing_smart_owner_changed')
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

    def activate_curve_plan(self, ident, expected_revision, actor, snapshot_id, check, *, strategy_revision=None):
        """Switch the original active plan under its existing ownership CAS."""
        from .competitor_offers import POLICY
        from .dispatch import CURVE_WRITE_PROTOCOL
        from .scheduler import next_cycle_at, _queued_natural_slot, _v6_hourly

        if type(expected_revision) is not int:
            raise ValueError('pricing_plan_revision_changed')
        if strategy_revision is not None:
            from .curve_strategy_v6 import MARKET_ANCHOR_VERSION, margin_band_parameters, market_anchor_parameters
            from .platforms import SMART_VERSION
            if (not isinstance(strategy_revision, dict) or set(strategy_revision) - {'margin_band'} != {'strategy_version', 'market_anchor'}
                    or strategy_revision['strategy_version'] not in (MARKET_ANCHOR_VERSION, SMART_VERSION)
                    or not isinstance(actor, str) or not actor.strip()):
                raise ValueError('pricing_curve_strategy_revision_invalid')
            strategy_revision = dict(strategy_revision,
                                     market_anchor=market_anchor_parameters(strategy_revision['market_anchor']))
            if 'margin_band' in strategy_revision:
                strategy_revision['margin_band'] = margin_band_parameters(
                    strategy_revision['margin_band'], strategy_revision['market_anchor'])
        key = ('curve-strategy-revision:' if strategy_revision else 'curve-plan-activation:') + ident + ':' + str(expected_revision)
        now = clock()
        with self.transaction() as conn:
            prior = self.get('metadata', key, conn)
            if prior:
                if ((prior['actor'], prior['snapshot_id']) != (actor, snapshot_id)
                        or prior.get('strategy_revision') != strategy_revision):
                    raise ValueError('pricing_curve_activation_request_conflict')
                return prior['after']
            plan = self.get('pricing_plans', ident, conn)
            if (not plan or plan['state'] != 'ACTIVE' or plan['revision'] != expected_revision
                    or (plan.get('write_protocol') != CURVE_WRITE_PROTOCOL if strategy_revision else bool(plan.get('write_protocol')))
                    or plan.get('ends_at') and now >= instant(plan['ends_at'])):
                raise ValueError('pricing_plan_revision_changed')
            if strategy_revision and plan['mode'] != 'smart':
                raise ValueError('pricing_curve_strategy_revision_invalid')
            if strategy_revision:
                margin_band = strategy_revision.get('margin_band', (plan.get('parameters') or {}).get('margin_band'))
                if margin_band:
                    if strategy_revision['strategy_version'] != MARKET_ANCHOR_VERSION:
                        raise ValueError('margin_band_parameters_invalid')
                    margin_band_parameters(margin_band, strategy_revision['market_anchor'])
            self.owns(plan, plan['resources'], conn)
            before = deepcopy(plan)
            resources = set(plan['resources'])
            if any(set(native_resources([r[0]])) & resources for r in conn.execute('SELECT resource FROM resource_leases')):
                raise ValueError('pricing_resource_unresolved')
            for row in conn.execute('SELECT body FROM operations'):
                operation = json.loads(row[0])
                if (operation['status'] not in ('COMPLETED','NO_CHANGE','CANCELLED','CANCELLED_NOT_SENT',
                                                'FAILED_BEFORE_WRITE','KNOWN_PARTIAL_EXITED',CURVE_REJECTED)
                        and set(native_resources(operation['resources'])) & resources):
                    raise ValueError('pricing_resource_unresolved')
            for row in conn.execute("SELECT body FROM durable_jobs WHERE kind='cycle' AND state='running'"):
                if json.loads(row[0]).get('plan_id') == ident:
                    raise ValueError('pricing_migration_cycle_running')
            if strategy_revision and margin_band:
                guard = margin_band.get('promotion_guard')
                previous_guard = ((plan.get('parameters') or {}).get('margin_band') or {}).get('promotion_guard') or {}
                if guard and any(guard[field] != previous_guard.get(field) for field in ('baseline_revision', 'baseline')):
                    from .runtime import verify_carnival_discount_baseline

                    verify_carnival_discount_baseline(self, snapshot_id, plan, guard, conn)
            proof = check(conn, plan, now)
            from automation_policy import load_policy
            queued = (_queued_natural_slot(conn, plan) if strategy_revision
                      and _v6_hourly(plan, load_policy()) else None)
            due = queued[1] if queued else next_cycle_at(conn, plan)
            plan.update(revision=expected_revision + 1, write_protocol=CURVE_WRITE_PROTOCOL,
                        activation_revision=fingerprint([ident, expected_revision, snapshot_id, proof]),
                        curve_activation_snapshot_id=snapshot_id)
            plan['parameters'] = dict(plan.get('parameters') or {}, competitor_policy=POLICY, region_pricing='global')
            if strategy_revision:
                plan['smart_strategy_version'] = strategy_revision['strategy_version']
                plan['parameters']['market_anchor'] = strategy_revision['market_anchor']
                if 'margin_band' in strategy_revision:
                    if margin_band is None:
                        plan['parameters'].pop('margin_band', None)
                    else:
                        plan['parameters']['margin_band'] = margin_band
            if plan.get('baseline_plan'):
                baseline = plan['baseline_plan']
                baseline['parameters'] = dict(baseline.get('parameters') or {}, competitor_policy=POLICY, region_pricing='global')
            conn.execute('UPDATE plan_ownership SET revision=? WHERE plan_id=? AND revision=?',
                         (plan['revision'], ident, expected_revision))
            self.put('pricing_plans', ident, plan, conn)
            body = dict(plan_id=ident, revision=plan['revision'])
            if plan.get('ends_at'):
                self.enqueue('deadline', 'deadline:' + ident + ':' + str(plan['revision']), plan['ends_at'], body, conn)
            cycle_id = (queued[0] if queued and queued[1] == due else
                        'cycle:' + ident + ':' + str(int(due.timestamp())) + ':r' + str(plan.get('resume_count', 0)))
            scheduled = dict(body, scheduled_at=due.isoformat())
            existing = conn.execute('SELECT state,body FROM durable_jobs WHERE id=?', (cycle_id,)).fetchone()
            if existing:
                if existing[0] != 'queued' or json.loads(existing[1]).get('plan_id') != ident:
                    raise ValueError('pricing_migration_slot_already_consumed')
                retained = json.loads(existing[1])
                retained.update(scheduled)
                conn.execute('UPDATE durable_jobs SET body=? WHERE id=?', (json.dumps(retained), cycle_id))
            else:
                self.enqueue('cycle', cycle_id, due, scheduled, conn)
            self.put('metadata', key, dict(actor=actor, snapshot_id=snapshot_id, before=before, after=plan,
                                           strategy_revision=strategy_revision), conn)
            return plan

    def active_plan(self):
        with self.connect() as db:
            row = db.execute('SELECT plan_id FROM plan_ownership ORDER BY resource LIMIT 1').fetchone()
            return self.get('pricing_plans', row[0], db) if row else None

    def active_plans(self):
        with self.connect() as db:
            return fully_owned_plans(db)

    def owns(self, plan, resources, db):
        if (self.get('metadata', 'generation', db) or {}).get('id') != plan['generation']:
            raise ValueError('pricing_generation_retired')
        for resource in resources:
            row = db.execute('SELECT * FROM plan_ownership WHERE resource=?', (resource,)).fetchone()
            if not row or (row['plan_id'], row['revision'], row['generation']) != (plan['plan_id'], plan['revision'], plan['generation']):
                raise ValueError('pricing_resource_taken_over')

    def assignment(self, plan, candidates, *, now=None, model_version='central-prior-e2', lifecycle_plan=None):
        from .engine import POLICIES
        now = now or clock()
        block = int(now.timestamp()) // (6*3600)
        key = fingerprint([plan['plan_id'], plan['revision'], block])
        storage_key = fingerprint([key, 'smart_lifecycle', lifecycle_plan['plan_id'], lifecycle_plan['revision']]) if lifecycle_plan else key
        deadline = lifecycle_plan.get('ends_at') if lifecycle_plan is not None else plan.get('ends_at')
        end = min(now.replace(hour=(now.hour//6)*6, minute=0, second=0, microsecond=0)+timedelta(hours=6),
                  instant(deadline) if deadline else now+timedelta(hours=6)).isoformat()
        with self.transaction() as db:
            previous = self.get('experiment_assignments', storage_key, db)
            if previous is None and lifecycle_plan is not None:
                previous = self.get('experiment_assignments', key, db)
            actions = {fingerprint(c['action']): c for c in candidates}
            if previous and fingerprint(previous['action']) in actions:
                if lifecycle_plan is not None:
                    previous = dict(previous, ends_at=end)
                    self.put('experiment_assignments', storage_key, previous, db)
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
                ends_at=end)
            if previous and lifecycle_plan is None:
                self.put('experiment_assignments',previous['assignment_id'],previous,db)
            self.put('experiment_assignments', storage_key, assignment, db)
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

    def price_control(self, db=None):
        return self.get('metadata','price_control',db) or dict(revision=0,manual_enabled=False,
            manual_prices={p:None for p in PLATFORMS},uplift_enabled=False,uplift_pct='0')

    def save_price_control(self, data, actor, request_id):
        expected={'expected_revision','manual_enabled','manual_prices','uplift_enabled','uplift_pct','request_key'}
        if not isinstance(data,dict) or set(data)!=expected or type(data['expected_revision']) is not int:
            raise ValueError('pricing_price_control_fields_invalid')
        if type(data['manual_enabled']) is not bool or type(data['uplift_enabled']) is not bool:
            raise ValueError('pricing_price_control_switch_invalid')
        prices=data['manual_prices']
        if not isinstance(prices,dict) or set(prices)!=set(PLATFORMS):
            raise ValueError('pricing_manual_price_fields')
        normalized={}
        for group,price in prices.items():
            value=number(price) if price is not None else None
            if data['manual_enabled'] and value is None:raise ValueError('pricing_manual_price_required')
            if value is not None and value*100!=(value*100).quantize(Decimal('.01')):
                raise ValueError('pricing_manual_unit_precision')
            normalized[group]=str(value) if value is not None else None
        pct=number(data['uplift_pct'],zero=True)
        key='price-control-request:'+request_id
        with self.transaction() as db:
            saved=self.get('metadata',key,db)
            if saved:
                if saved['request_sha256']!=fingerprint(data):raise ValueError('pricing_price_control_payload_conflict')
                return saved['response']
            current=self.price_control(db)
            if current['revision']!=data['expected_revision']:raise ValueError('pricing_price_control_revision_changed')
            if db.execute('SELECT 1 FROM resource_leases LIMIT 1').fetchone():
                raise ValueError('pricing_resource_unresolved')
            value=dict(revision=current['revision']+1,manual_enabled=data['manual_enabled'],manual_prices=normalized,
                uplift_enabled=data['uplift_enabled'],uplift_pct=str(pct),actor=actor,updated_at=clock().isoformat())
            self.put('metadata','price_control',value,db)
            self.put('metadata','price-control-history:'+request_id,dict(before=current,after=value),db)
            response=dict(settings=value,write_performed=False)
            self.put('metadata',key,dict(request_sha256=fingerprint(data),response=response),db)
            return response

    def prepare(self, plan, bundle, *, operation_id=None, now=None,dispatch_context=None):
        from .uk_retirement import authority_resources
        now = now or clock()
        operation_id = operation_id or bundle['decision_bundle_id']
        with self.transaction() as db:
            old = self.get('operations', operation_id, db)
            if old:
                if fingerprint(old['bundle']) != fingerprint(bundle):
                    raise ValueError('pricing_operation_payload_conflict')
                return old
            self.owns(plan, authority_resources(bundle), db)
            if not bundle.get('maintenance_purpose') and bundle.get('authorization_purpose')!='original_unsent_ALL_steps_only':
                actual_control=self.price_control(db)
                if (bundle.get('price_control') or {}).get('revision',0)!=actual_control['revision'] or bundle.get('price_control') is not None and bundle['price_control']!=actual_control:
                    raise ValueError('pricing_price_control_revision_changed')
            if now >= instant(bundle['valid_until']):
                raise ValueError('pricing_authorization_expired')
            if plan['ends_at'] and now >= instant(plan['ends_at']):
                raise ValueError('pricing_plan_expired')
            if plan['state'] != 'ACTIVE':
                raise ValueError('pricing_plan_inactive')
            adoption = bundle.get('curve_adoption')
            if adoption is not None:
                self._curve_adoption_input(adoption, operation_id, bundle, db)
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
        from .uk_retirement import authority_resources
        now = now or clock()
        with self.transaction() as db:
            op = self.get('operations', operation_id, db)
            step = next(s for s in op['steps'] if s['step_id'] == step_id)
            if op['status'] in ('COMPLETED','NO_CHANGE','CANCELLED_NOT_SENT','KNOWN_PARTIAL_EXIT_PENDING','KNOWN_PARTIAL_EXITED',CURVE_REJECTED) or step['state']=='CANCELLED_NOT_SENT':
                return None
            plan = self.get('pricing_plans', op['plan_id'], db)
            self.owns(plan, authority_resources(op['bundle']), db)
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

    def finish_curve_rejection(self, operation_id, receipt):
        """Close a submitted operation with explicit rejection and exact no-change readback."""
        from coin_all_sync_job import all_curve_changes_rejected, editable

        with self.transaction() as db:
            op = self.get('operations', operation_id, db)
            if op['status'] == CURVE_REJECTED:
                return op
            step, = op['steps']
            results = receipt.get('curve_results') or {}
            bundle = op['bundle']
            if (op['status'] not in ('DISPATCHED', 'UNKNOWN')
                    or bundle.get('write_protocol') != CURVE_WRITE_PROTOCOL
                    or step['kind'] != 'base' or not step.get('dispatched_at')
                    or receipt.get('status') != CURVE_REJECTED or receipt.get('execution_id') != operation_id
                    or set(results) != set(op['dispatch_context']['selected']) or set(results) != set(bundle['affected_platforms'])
                    or any(row.get('platform') != p or row.get('operation_id') != operation_id
                           or row.get('before_hash') != fingerprint(editable(bundle['before_action']['curves'][p]['native_payload']))
                           or row.get('target_hash') != fingerprint(editable(bundle['action']['curves'][p]['native_payload']))
                           for p, row in results.items())
                    or not all_curve_changes_rejected(results)):
                raise ValueError('pricing_curve_rejection_not_proven')
            completed = clock().isoformat()
            if step.get('receipt') is not None:
                step.setdefault('receipt_history', []).append(dict(state=step['state'], receipt=step['receipt'],
                                                                  recorded_at=completed))
            step.update(state=CURVE_REJECTED, receipt=receipt)
            op.update(status=CURVE_REJECTED, completed_at=completed, readback=receipt, write_performed=False)
            self.put('readback_receipts', operation_id, receipt, db)
            self.put('operations', operation_id, op, db)
            db.execute('DELETE FROM resource_leases WHERE operation_id=?', (operation_id,))
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
            self.put('readback_receipts', operation_id, receipt, db)
            action = self.record_price_window(op,db,no_change=no_change)
            adoption = op['bundle'].get('curve_adoption')
            if adoption is not None:
                adoption_result = self._record_curve_adoption(adoption, op, action['curves'][adoption['platform']], db)
                op['curve_adoption_result'] = {key: value for key, value in adoption_result.items()
                                               if key not in ('proposal', 'proof')}
            if not no_change and op['bundle'].get('write_protocol') == 'fc27_curve_v6':
                for platform, selection in (op['bundle'].get('curve_selection') or {}).items():
                    self._save_curve_cost_protection(platform, selection, operation_id, db)
            self.put('operations', operation_id, op, db)
            db.execute('DELETE FROM resource_leases WHERE operation_id=?', (operation_id,))
            return op

    def record_price_window(self,op,db,*,no_change=False):
        operation_id=op['operation_id']
        actual_action, curve_metadata = op['bundle']['action'], {}
        if op['bundle'].get('write_protocol') == 'fc27_curve_v6':
            actual_action, curve_metadata = confirmed_curve_window(op)
        elif 'curves' in actual_action:
            raise ValueError('curve_window_protocol_missing')
        return self._store_price_window(op, db, actual_action, curve_metadata, clock().isoformat(), no_change)

    def observe_curve_keep(self, plan, snapshot_id, platform, curve, observed_at, evidence_ref, conn, *, selection=None):
        from .curve_strategy_v6 import primary_reference_curve
        from .dispatch import CURVE_WRITE_PROTOCOL

        resource = 'base:' + platform
        current = self.get('pricing_plans', plan['plan_id'], conn)
        if (not current or current['state'] != 'ACTIVE' or current['revision'] != plan['revision']
                or current.get('write_protocol') != CURVE_WRITE_PROTOCOL or resource not in current['resources']
                or conn.execute('SELECT 1 FROM resource_leases WHERE resource=?', (resource,)).fetchone()):
            return
        self.owns(current, [resource], conn)
        curve = primary_reference_curve(curve, platform)
        ident = 'observed-curve:' + snapshot_id + ':' + platform
        if self.get('actual_price_windows', ident, conn):
            return
        self._save_curve_cost_protection(platform, selection, ident, conn)
        for row in conn.execute('SELECT body FROM actual_price_windows'):
            window = json.loads(row[0])
            if resource not in native_resources(window.get('resources', [])):
                continue
            if instant(window['opened_at']) >= instant(observed_at):
                return
            for record in window.get('continuations', []):
                if record.get('operation_id') == ident:
                    return
        observation = dict(operation_id=ident, plan_id=plan['plan_id'], generation=plan['generation'],
                           resources=[resource], bundle=dict(mutable_resources=[resource],
                               affected_platforms=[platform], assignment_id=snapshot_id,
                               curve_selection={platform: selection} if selection else {}))
        meta = dict(origin='observed_native_curve_window', write_protocol=CURVE_WRITE_PROTOCOL,
                    price_scope_contract=PRICE_SCOPE_CONTRACT, readback_ref=evidence_ref,
                    observation_id=ident, write_performed=False)
        self._store_price_window(observation, conn, {'curves': {platform: curve}}, meta, observed_at, True)
        return True

    def _store_price_window(self, op, db, actual_action, curve_metadata, opened, no_change):
        operation_id = op['operation_id']
        original_resources=op['bundle'].get('mutable_resources',op['resources'])
        normalize=native_resources if any(r in ('base:PS','base:XBOX','base:PC') for r in original_resources) else lambda resources:list(resources)
        remaining=set(normalize(original_resources))
        selections = op['bundle'].get('curve_selection') or {}
        learning = {platform: dict(assignment=row['assignment']) for platform, row in selections.items()
                    if row.get('assignment')}
        for row in db.execute('SELECT id,body FROM actual_price_windows').fetchall():
            window=json.loads(row[1])
            affected=(set(normalize(window.get('resources',[])))-set(normalize(window.get('resource_closed_at',{}))))&remaining
            if not window.get('closed_at') and affected:
                if no_change:
                    def value(action,resource):
                        kind,key=resource.split(':',1)
                        return Decimal(action.get('base_prices' if kind=='base' else 'region_coefficients',{}).get(action_key(action,key) if kind=='base' and key in PLATFORMS else key,'1'))
                    def catalog_matches(resource):
                        platforms = ('PS','XBOX') if resource == 'base:console' else ('PC',) if resource == 'base:pc' else (resource.rsplit(':',1)[-1],)
                        old, new = window.get('catalog',{}), op['bundle'].get('catalog',{})
                        return all(old.get(platform) == new.get(platform) for platform in platforms)
                    def same_curve(resource):
                        from .price_curve import curve_key
                        platform = resource.rsplit(':',1)[-1]
                        old = (window['action'].get('curves') or {}).get(platform)
                        new = (actual_action.get('curves') or {}).get(platform)
                        return resource.startswith('base:') and old is not None and new is not None and curve_key(old) == curve_key(new)
                    same={r for r in affected if (same_curve(r) if 'curves' in window['action'] or 'curves' in actual_action else
                          value(window['action'],r)==value(actual_action,r) and catalog_matches(r))}
                    if same:
                        continuation = dict(operation_id=operation_id, assignment_id=op['bundle']['assignment_id'],
                                            resources=sorted(same), at=opened)
                        if curve_metadata.get('observation_id'):
                            continuation.update(readback_ref=curve_metadata['readback_ref'], write_performed=False)
                        continuation_learning = {platform: selection for platform, selection in learning.items()
                                                 if 'base:' + platform in same}
                        if continuation_learning:
                            continuation['curve_selection'] = continuation_learning
                        window.setdefault('continuations', []).append(continuation)
                        if window.get('assignment_id')!=op['bundle']['assignment_id']:
                            window['randomization_verified']=False
                        remaining-=same
                        affected-=same
                    if not affected:
                        self.put('actual_price_windows',row[0],window,db)
                        continue
                closed=window.setdefault('resource_closed_at',{})
                for resource in affected:closed.setdefault(resource,opened)
                if all(resource in normalize(closed) for resource in normalize(window.get('resources',[]))):window['closed_at']=max(closed.values())
                self.put('actual_price_windows',row[0],window,db)
        if not remaining:
            return actual_action
        if learning:
            curve_metadata['curve_selection'] = learning
        self.put('actual_price_windows', operation_id, dict(operation_id=operation_id,plan_id=op.get('plan_id'),generation=op.get('generation'),
                 resources=[r for r in normalize(original_resources) if r in remaining],mutable_resources=[r for r in normalize(original_resources) if r in remaining],
                 assignment_id=op['bundle']['assignment_id'],action=actual_action,
                 catalog=op['bundle'].get('catalog',{}),budget_reference=op['bundle'].get('budget_reference',{}),
                 platforms=op['bundle'].get('affected_platforms',[]),assignment_probability=op['bundle'].get('assignment_probability'),
                 randomization_verified=not no_change and op['bundle'].get('randomization_verified',False),origin=curve_metadata.pop('origin','confirmed_public_price_window'),mode='production',
                 opened_at=opened,no_change=no_change,**curve_metadata), db)
        return actual_action


    def finish_known_partial(self,operation_id,receipt,actual_action,reason,*,exit_pending=True):
        with self.transaction() as db:
            op=self.get('operations',operation_id,db)
            if op['status'] in ('KNOWN_PARTIAL_EXIT_PENDING','COMPLETED'):return op
            if not any(s['state']=='CONFIRMED' for s in op['steps']) or any(s['state'] not in ('CONFIRMED','CANCELLED_NOT_SENT') for s in op['steps']):
                raise ValueError('pricing_partial_actual_state_unresolved')
            # 2026-10-28: 「Order 写成功 + Admin 单价核对一致」也算已确认，
            # 不再强制等公开页（DECOUPLE-DESIGN §6.3）。释放条件与终态白名单均未改变。
            if receipt.get('status') not in ('PUBLIC_CONFIRMED','ORDER_ADMIN_CONFIRMED'):raise ValueError('pricing_partial_public_unconfirmed')
            op.update(status='KNOWN_PARTIAL_EXIT_PENDING' if exit_pending else 'COMPLETED',actual_action=actual_action,readback=receipt,
                      target_not_completed=True,exit_reason=reason,actual_state_confirmed_at=clock().isoformat())
            if not exit_pending:op['completed_at']=op['actual_state_confirmed_at']
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
        from .cost_inputs_v6 import CURVE_COST_GAPS

        key = fingerprint([code, dependency, 'FC27'])
        with self.transaction() as db:
            old = self.get('incidents', key, db) or {}
            now = clock().isoformat()
            prior = old.get('affected_scopes', [])
            value = dict(incident_key=key, root_cause_key=code, code=code, dependency=dependency,
                         affected_scopes=sorted(set(scopes)), phase=phase, first_seen=old.get('first_seen', now),
                         last_seen=now, attempt=old.get('attempt',0)+1,
                         error=error, state='OPEN', observability_degraded=code=='MONITOR_READ_FAILED')
            if code in CURVE_COST_GAPS and dependency in ('cost', 'curve_price_insurance'):
                if old.get('state') != 'OPEN':
                    prior = []
                last_seen = old.get('scope_last_seen') or dict.fromkeys(prior, old.get('last_seen'))
                value.update(affected_scopes=sorted(set(prior) | set(scopes)),
                             scope_last_seen=dict(last_seen, **dict.fromkeys(scopes, now)),
                             recovery_history=old.get('recovery_history', []))
            self.put('incidents', key, value, db)
            if not old or set(scopes)-set(prior):
                event_key = key + ':' + fingerprint(scopes)
                if value.get('recovery_history'):
                    event_key += ':' + str(value['attempt'])
                db.execute('INSERT OR IGNORE INTO event_outbox(event_key,kind,body) VALUES (?,?,?)',
                    (event_key, 'incident', json.dumps(value)))
            return value

    def recover_curve_cost_incidents(self, snapshot_id, operation_id, conn, *, check_completed=False):
        """Resolve only the scope with proven natural evidence newer than its latest failure."""
        from .cost_inputs_v6 import COST_SAMPLE_OUTLIER, CURVE_COST_GAPS

        decision = self.get('strategy_decisions', snapshot_id, conn) or {}
        candidates = decision.get('cost_recovery') or {}
        if (not candidates or decision.get('automatic_curve_round') is not True
                or decision.get('curve_round_id') != operation_id):
            return
        completed = None
        if check_completed:
            completed = self.get('operations', operation_id, conn) or {}
            if (completed.get('status') != 'COMPLETED' or not completed.get('readback')
                    or completed['readback'] != self.get('readback_receipts', operation_id, conn)):
                return
        snapshot = self.get('pricing_snapshots', snapshot_id, conn)
        now = clock()
        if (not snapshot or snapshot.get('snapshot_id') != snapshot_id or snapshot.get('origin') != 'live_collector'
                or snapshot.get('mode') != 'production' or snapshot.get('write_protocol') != CURVE_WRITE_PROTOCOL
                or (snapshot.get('evidence') or {}).get('run_id') != snapshot_id
                or snapshot.get('authorization_purpose') or snapshot.get('curve_restore_preview_id')):
            return
        snapshot_hash = fingerprint(snapshot['evidence'])
        for platform, evidence in candidates.items():
            if platform not in PLATFORMS or evidence['snapshot_sha256'] != snapshot_hash:
                continue
            captured = instant(evidence['source_captured_at'])
            seen = (instant(completed['created_at'])
                    if completed is not None and evidence['status'] == 'READY' else now)
            if not captured <= seen < instant(evidence['valid_until']) or seen - captured > timedelta(hours=1):
                continue
            if evidence['status'] == 'KEEP':
                if not evidence.get('readback_sha256'):
                    continue
                plan = self.get('pricing_plans', snapshot['plan_id'], conn) or {}
                resource = 'base:' + platform
                if (plan.get('state') != 'ACTIVE' or plan.get('revision') != snapshot['plan_revision']
                        or not conn.execute('SELECT 1 FROM plan_ownership WHERE resource=? AND plan_id=? AND revision=? AND generation=?',
                                            (resource, plan['plan_id'], plan['revision'], plan['generation'])).fetchone()
                        or conn.execute('SELECT 1 FROM resource_leases WHERE resource=?', (resource,)).fetchone()):
                    continue
                observed_at = instant(evidence['readback_at'])
                if not captured <= observed_at <= now:
                    continue
                observation_id = 'observed-curve:' + snapshot_id + ':' + platform
                windows = (json.loads(raw) for raw, in conn.execute('SELECT body FROM actual_price_windows'))
                if any(window.get('operation_id') != observation_id and instant(window['opened_at']) >= observed_at
                       for window in windows if resource in native_resources(window.get('resources', []))):
                    continue
                readback_sha = evidence['readback_sha256']
            else:
                if completed is None:
                    continue
                bundle = completed['bundle']
                proof = (bundle.get('curve_proofs') or {}).get(platform) or {}
                if (evidence['status'] != 'READY' or not completed.get('dispatch_context', {}).get('automatic')
                        or bundle.get('snapshot_id') != snapshot_id or bundle.get('snapshot_sha256') != snapshot_hash
                        or platform not in bundle.get('affected_platforms', ())
                        or proof.get('proof_hash') != evidence['proof_hash']):
                    continue
                readback_sha = fingerprint(completed['readback'])
            for code, dependency in [(code, 'cost') for code in CURVE_COST_GAPS] + [(COST_SAMPLE_OUTLIER, 'curve_price_insurance')]:
                key = fingerprint([code, dependency, 'FC27'])
                incident = self.get('incidents', key, conn) or {}
                scopes = incident.get('affected_scopes', [])
                last_seen = (incident.get('scope_last_seen') or {}).get(platform, incident.get('last_seen'))
                if incident.get('state') != 'OPEN' or platform not in scopes or captured <= instant(last_seen):
                    continue
                remaining = [scope for scope in scopes if scope != platform]
                incident.setdefault('recovery_history', []).append(dict(
                    evidence, platform=platform, code=code, dependency=dependency, incident_last_seen=last_seen,
                    snapshot_id=snapshot_id, snapshot_created_at=snapshot.get('created_at'),
                    operation_id=operation_id, readback_sha256=readback_sha,
                    recovered_at=now.isoformat()))
                incident.update(affected_scopes=remaining)
                if not remaining:
                    incident.update(state='RESOLVED', resolved_at=now.isoformat())
                self.put('incidents', key, incident, conn)
