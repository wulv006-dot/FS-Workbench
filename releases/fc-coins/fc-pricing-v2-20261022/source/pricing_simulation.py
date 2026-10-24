"""Read qualified existing FC quotes; call only the original pure price functions."""
import builtins
import ast
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import types
import uuid

from pilot import digest

ENGINE_SHA='7c8980894a16b3a539d30ac0cc221df4d629a02edec00bdb4a00166544db36cb'
POLICY_CODE_SHA='317b657817701965147068629d7a3c97605e537ecd969c7f6f8e13ef1995b9d2'
V2_CODE_SHA='d408fcfbbab4da1b0443550fecc17ea2ac8ea174268a5b34774855a081c0b829'
PLATFORMS=('PS','XBOX','PC')
GUARD='fc27-readonly-qualified-quote-v1'
EXECUTION_GUARD_SHA='8771385cf5a6ef14fa3a42915108d7a699c511c09c089da76319993188ba3b4d'
CANDIDATE_EVALUATOR='original-engine-extended-discount-research-v1'
CANDIDATE_EVALUATOR_SHA=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def normalize_candidate_rules(value):
    """User 2026-10-21 permits wider research discounts; production stays unchanged."""
    bands=('at_least_40','30_to_40','20_to_30','below_20')
    if (not isinstance(value,dict) or set(value)!={'schema_version','bands'} or type(value['schema_version']) is not int
            or value['schema_version']!=1 or not isinstance(value['bands'],dict) or set(value['bands'])!=set(bands)):raise ValueError('candidate_rules_invalid')
    result={'schema_version':1,'bands':{}}
    for tier in bands:
        row=value['bands'][tier]
        if not isinstance(row,dict) or set(row)!={'min_discount_pct','max_discount_pct'}:raise ValueError('candidate_band_fields')
        numbers={}
        for key,text in row.items():
            if type(text) is not str or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?',text):raise ValueError('candidate_discount_invalid')
            number=Decimal(text)
            if not 0<=number<100:raise ValueError('candidate_discount_requires_positive_price')
            numbers[key]=number
        if numbers['min_discount_pct']>numbers['max_discount_pct']:raise ValueError('candidate_discount_range_invalid')
        result['bands'][tier]={k:f'{v:.2f}' for k,v in numbers.items()}
    return result


def read(path,owners=(0,)):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('simulation_source_link')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>16*1024*1024:raise ValueError('simulation_source_file')
    if os.name=='posix' and (info.st_uid not in owners or info.st_mode&0o022):raise ValueError('simulation_source_permissions')
    raw=path.read_bytes()
    return raw,hashlib.sha256(raw).hexdigest()


def fresh(value, now):
    at=datetime.fromisoformat(value.replace('Z','+00:00'))
    if at.tzinfo is None or not 0<=(now-at).total_seconds()<=3600:raise ValueError('simulation_source_stale')


class SimulationBridge:
    def __init__(self,root='/var/lib/fc27-cloud',code='/opt/fc27-cloud-browser',clock=None):
        self.root,self.code=Path(root),Path(code)
        self.clock=clock or (lambda:datetime.now(timezone.utc))

    def modules(self):
        raw,v2_sha=read(self.code/'pricing_v2.py')
        if v2_sha!=V2_CODE_SHA:raise ValueError('simulation_v2_code_changed')
        v2=types.ModuleType('qualified_pricing_v2');v2.__file__=str(self.code/'pricing_v2.py')
        exec(compile(raw,v2.__file__,'exec'),v2.__dict__)
        raw,sha=read(self.code/'fc27_quote_engine.py')
        if sha!=ENGINE_SHA:raise ValueError('simulation_engine_changed')
        imports=dict(vars(builtins))
        def importing(name,*args,**kwargs):
            return v2 if name=='pricing_v2' else builtins.__import__(name,*args,**kwargs)
        imports['__import__']=importing
        engine=types.ModuleType('simulation_original_engine');engine.__dict__['__builtins__']=imports
        exec(compile(raw,'<original-fc-engine>','exec'),engine.__dict__)
        raw,sha=read(self.code/'automation_policy.py')
        if sha!=POLICY_CODE_SHA:raise ValueError('simulation_policy_code_changed')
        policy=types.ModuleType('simulation_original_policy')
        imports=dict(vars(builtins))
        def importing(name,*args,**kwargs):
            return engine if name=='fc27_quote_engine' else builtins.__import__(name,*args,**kwargs)
        imports['__import__']=importing;policy.__dict__['__builtins__']=imports
        exec(compile(raw,'<original-fc-policy>','exec'),policy.__dict__)
        return engine,policy

    def baseline(self):
        engine,normalizer=self.modules();raw,sha=read(self.root/'config/automation.json',owners=(0,994))
        # Existing fc27api UID994 owns this one policy; code and snapshots stay root-only.
        policy=normalizer.normalize_policy(json.loads(raw),stored=True)
        return engine,policy,{'revision':policy['revision'],'sha256':sha}

    def capabilities(self):
        engine,policy,identity=self.baseline()
        newest=max((self.root/'runs').glob('*.json'),key=lambda p:p.stat().st_mtime,default=None)
        return dict(contract=GUARD,baseline_policy=identity,engine_sha256=ENGINE_SHA,
            pricing_rules=policy['pricing_rules'],minimum_gross_margin_pct=policy['minimum_gross_margin_pct'],
            snapshot_id=newest.stem if newest else None,granularity='common_console_independent_pc_verified_promotion_package_floor',
            rule_ideas_supported=True,research_discount_range={'minimum':'0','exclusive_maximum':'100','decimal_places':2},
            candidate_evaluator=CANDIDATE_EVALUATOR,candidate_evaluator_sha256=CANDIDATE_EVALUATOR_SHA,
            platforms=list(PLATFORMS),unsupported=['legacy_band_numerical_simulation','new_products'],
            current_candidate_tool='fs.pricing.control evaluate/recommend; task capabilities govern execution',
            write_performed=False,execution_authorized=False)

    def execution_checks(self,policy):
        checks=[dict(status='pass' if policy['system_enabled'] else 'block',reason='Existing system ON' if policy['system_enabled'] else 'Existing system OFF')]
        try:
            raw,sha=read(self.code/'automation_tick.py')
            if sha!=EXECUTION_GUARD_SHA:raise ValueError('original_execution_guard_changed')
            tree=ast.parse(raw);nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('utc','resolved_execution')]
            if len(nodes)!=2:raise ValueError('original_execution_guard_unavailable')
            scope={'datetime':datetime,'timezone':timezone}
            exec(compile(ast.Module(body=nodes,type_ignores=[]),'<original-readonly-execution-guard>','exec'),scope)
            for folder in ('queue','jobs','executions','all-coin-sync'):
                directory=self.root/folder
                if directory.is_symlink() or not directory.is_dir():raise ValueError('execution_ledger_unavailable')
                paths=list(directory.glob('*.json'))
                if len(paths)>5000:raise ValueError('execution_ledger_coverage_incomplete')
                blocked=False
                for p in paths:
                    record=json.loads(read(p)[0])
                    if folder=='queue' or folder=='jobs' and record.get('status')=='running' or folder=='executions' and not scope['resolved_execution'](record) or folder=='all-coin-sync' and record.get('status')!='confirmed':blocked=True
                checks.append(dict(status='block' if blocked else 'pass',reason='Original '+folder+' ledger',observed_at=self.clock().isoformat(),records=len(paths)))
        except (OSError,ValueError,TypeError,KeyError) as error:
            checks.append(dict(status='incomplete',reason=str(error) if isinstance(error,ValueError) else 'execution_ledger_unavailable'))
        checks.append(dict(status='incomplete',reason='Original Player/lock guard is not exercised by simulation; original writer must recheck it'))
        return checks

    def rules(self,engine,policy,changes):
        if not isinstance(changes,list) or not 1<=len(changes)<=4:raise ValueError('strategy_band_changes')
        result=deepcopy(policy['pricing_rules']);seen=set()
        for change in changes:
            if not isinstance(change,dict) or set(change)!={'tier','min_discount_pct','max_discount_pct'}:raise ValueError('strategy_band_fields')
            tier=change['tier']
            if tier not in result['bands'] or tier in seen:raise ValueError('strategy_band_identity')
            seen.add(tier);result['bands'][tier]={k:change[k] for k in ('min_discount_pct','max_discount_pct')}
        return normalize_candidate_rules(result)

    def load(self,snapshot_id,engine,policy,identity):
        if str(uuid.UUID(snapshot_id))!=snapshot_id:raise ValueError('simulation_snapshot_identity')
        source=self.root/'runs'/(snapshot_id+'.json');raw,snapshot_sha=read(source);snapshot=json.loads(raw)
        newest=max((self.root/'runs').glob('*.json'),key=lambda p:p.stat().st_mtime,default=None)
        if newest!=source:raise ValueError('simulation_newer_snapshot')
        if snapshot.get('run_id')!=snapshot_id or snapshot.get('status')!='ready_for_quote':raise ValueError('simulation_snapshot_incomplete')
        fresh(snapshot['created_at'],self.clock())
        raw,quote_sha=read(self.root/'quotes'/(snapshot_id+'.json'));quote=json.loads(raw)
        if (quote.get('status') not in ('ready_for_preview','margin_review_required') or quote.get('run_id')!=snapshot_id or quote.get('snapshot_sha256')!=snapshot_sha or quote.get('quote_engine_sha256')!=ENGINE_SHA
                or quote.get('automation_policy_revision')!=identity['revision']):raise ValueError('simulation_qualified_quote_conflict')
        edits=quote['edits']
        if any(edits.get(k) for k in ('costs','quotes','offers','reason')):raise ValueError('simulation_manual_source_forbidden')
        if (engine.normalize_discount_rules(quote['pricing_rules'])!=policy['pricing_rules'] or edits.get('pricing_rules')!=policy['pricing_rules']
                or Decimal(edits['minimum_gross_margin_pct'])!=Decimal(policy['minimum_gross_margin_pct'])):raise ValueError('simulation_policy_changed')
        evidence=quote['evidence']
        if evidence.get('game')!='FC27' or evidence.get('product')!='Game Coins' or evidence.get('checked_at')!=snapshot['created_at']:raise ValueError('simulation_scope')
        costs={}
        for cost in snapshot['costs']:
            platform=cost.get('platform')
            if (platform not in PLATFORMS or platform in costs or cost.get('run_id')!=snapshot_id or cost.get('status')!='valid'
                    or cost.get('genre')!='1' or cost.get('delivery_type')!='订单发货' or cost.get('game')!='FC27'
                    or cost.get('product')!='Game Coins' or cost.get('unit')!='CNY/K'
                    or not str(cost.get('record_id','')).isdigit() or not cost.get('trade_at') or Decimal(cost['cny_per_1k'])<=0):raise ValueError('simulation_cost_unverified')
            fresh(cost['checked_at'],self.clock());costs[platform]=cost
        if set(costs)!=set(PLATFORMS) or evidence.get('costs')!=costs:raise ValueError('simulation_cost_coverage')
        offers={p:{} for p in PLATFORMS};seen=set()
        for offer in snapshot['competitors']:
            platform,site=offer.get('platform'),offer.get('source')
            if platform not in PLATFORMS or site not in engine.SITES or (platform,site) in seen or offer.get('run_id')!=snapshot_id:raise ValueError('simulation_competitor_identity')
            seen.add((platform,site))
            if offer.get('status')=='missing' and site!='Lootbar':continue
            if offer.get('status')!='valid' or offer.get('currency')!='USD':raise ValueError('simulation_competitor_unverified')
            fresh(offer['captured_at'],self.clock())
            offers[platform][site]=dict(usd_price=offer['gross_usd'],base_k=offer['purchase_k'],bonus_k=offer['bonus_k'],
                conditional=offer.get('conditional',False),comparable=offer.get('comparable',True),url=offer['url'],checked_at=offer['captured_at'],status='已核对')
        if not engine.source_coverage(snapshot['competitors'])['ready'] or evidence.get('offers')!=offers:raise ValueError('simulation_comparability_unverified')
        fx=snapshot.get('fx') or {};fresh(fx['checked_at'],self.clock())
        if fx.get('status')!='valid' or Decimal(fx['cny_per_usd'])<=0 or evidence.get('fx')!=fx:raise ValueError('simulation_fx_unverified')
        store=snapshot.get('storefront') or {}
        if (store.get('source')!='https://www.mmoexp.com/Fc-27/Coins.html' or store.get('currency')!='USD'
                or store.get('collection_run_id')!=snapshot_id or store.get('status')!='ok' or store.get('package_k')!=100
                or set(store.get('rows',{}))!=set(PLATFORMS) or evidence.get('storefront')!=store):raise ValueError('simulation_storefront_unverified')
        for platform,row in store['rows'].items():
            fresh(row['checked_at'],self.clock())
            total,bonus=Decimal(row['package_usd']),Decimal(row['bonus_k'])
            if (row.get('platform')!=platform or row.get('status')!='ok' or row.get('base_k')!='100' or not str(row.get('sku_id','')).isdigit()
                    or not total.is_finite() or total<=0 or total!=total.quantize(Decimal('.01')) or not bonus.is_finite() or not 0<=bonus<=100
                    or Decimal(row['usd_per_k'])!=(total/(100+bonus)).quantize(Decimal('.000001'),rounding=ROUND_HALF_UP)):raise ValueError('simulation_storefront_units')
        baseline=engine.calculate(evidence,{'minimum_gross_margin_pct':policy['minimum_gross_margin_pct'],'pricing_rules':policy['pricing_rules']})
        if baseline!=quote['result']:raise ValueError('simulation_baseline_disagrees_with_original')
        return evidence,baseline,{'snapshot_sha256':snapshot_sha,'qualified_quote_sha256':quote_sha}

    def simulate(self,draft,snapshot_id,expected_policy):
        raise ValueError('simulation_legacy_bands_retired_use_fs_pricing_control_evaluate')
