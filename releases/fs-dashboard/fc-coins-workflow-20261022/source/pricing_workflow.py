"""Astra FC Coins decision order; arithmetic is authoritative, business execution absent."""
from copy import deepcopy
from decimal import Decimal,InvalidOperation,ROUND_CEILING
from datetime import datetime,timezone
import hashlib
from pathlib import Path
import re
from pilot import digest

VERSION='astra-fc-coins-v2'
SOURCE='Astra FC金币固定决策流程'
STEPS=('锁定范围和来源','核对执行与实际暴露','分开采购毛利和广告后贡献','比较保持/涨/降候选','联合约束与独立尾价','明确反证和复盘候选')
PLATFORMS=('PS','XBOX','PC')


def number(value,zero=False):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,13}(?:\.[0-9]{1,10})?',value):raise ValueError('workflow_decimal_string')
    try:n=Decimal(value)
    except InvalidOperation:raise ValueError('workflow_number') from None
    if not n.is_finite() or n<0 or n>Decimal('1e12') or not zero and n==0:raise ValueError('workflow_number')
    return n


def money(value):
    n=number(value)
    if n!=n.quantize(Decimal('.01')):raise ValueError('workflow_package_cents')
    return n


def figures(price,cost,discount):
    net=price*(1-discount/100);gross=net-cost
    return {'net_usd':str(net),'procurement_gross_usd':str(gross),'procurement_margin_pct':str(gross/net*100) if net else None}


def current_accounting(market,floor):
    """Latest cost values only price current packages; they never rewrite historical COGS."""
    fx=market.get('fx') or {};costs={r.get('platform'):r for r in market.get('costs',[])};rows=[]
    console=[costs.get(p,{}) for p in ('PS','XBOX')]
    common=all(r.get('status')=='available' for r in console) and all(r.get('cny_per_1k') is not None for r in console) and Decimal(str(console[0]['cny_per_1k']))==Decimal(str(console[1]['cny_per_1k']))
    for row in (market.get('storefront') or {}).get('rows',[]):
        cost=costs.get(row.get('platform'),{})
        if row.get('platform') in ('PS','XBOX') and not common:continue
        if row.get('status')!='available' or cost.get('status')!='available' or fx.get('status')!='available':continue
        try:
            qty=number(str(row['base_k']))+number(str(row['bonus_k']),True)
            delivered=qty*number(str(cost['cny_per_1k']))/number(str(fx['cny_per_usd']))
            value=figures(number(str(row['gross_usd'])),delivered,Decimal(0))
        except (KeyError,ValueError):continue
        rows.append(dict(platform=row['platform'],delivered_k=str(qty),current_package_usd=str(row['gross_usd']),delivered_cost_usd=str(delivered),**value,
            no_additional_discount_floor_pass=Decimal(value['procurement_margin_pct'])>=Decimal(str(floor)),
            margin_basis='undiscounted_and_historical_average_v2',promotions_exempt_from_margin_floor=True))
    return {'status':'available' if len(rows)==3 else 'partial','rows':rows,'console_common_cost_status':'matching_valid_observations' if common else 'source_reconciliation_required','console_cost_observations':[{k:r.get(k) for k in ('platform','status','cny_per_1k','trade_at','checked_at')} for r in console],'basis':'PS/Xbox share one supplier-cost market and base price. Different historical/latest records require time/source reconciliation, never platform cost differentiation or automatic mean/min selection. Current public package + latest verified CNY/K × delivered K / FX; This current-package view checks the undiscounted floor only; the executable v15 receipt additionally requires last-seven-closed-day estimated average >=10%. Individual legal promotions may be loss-making.','historical_COGS_rewritten':False}


def evaluate(case,floor):
    """Declared scenarios never become observations, demand forecasts or execution authority."""
    from price_ending import package_ending
    if not isinstance(case,dict) or set(case)-{'currency','delivered_cost_includes_gifts','platforms','discounts_pct','economics','historical_retained_ratio'} or not {'currency','delivered_cost_includes_gifts','platforms','discounts_pct','historical_retained_ratio'}<=set(case):raise ValueError('workflow_case_fields')
    if case['currency']!='USD' or case['delivered_cost_includes_gifts'] is not True:raise ValueError('workflow_case_units')
    rows=case['platforms'];discounts=case['discounts_pct']
    if not isinstance(rows,list) or not 2<=len(rows)<=3 or not isinstance(discounts,list) or not 1<=len(discounts)<=10:raise ValueError('workflow_case_coverage')
    ds=[number(v,True) for v in discounts]
    if len(set(ds))!=len(ds) or any(d>100 for d in ds):raise ValueError('workflow_discount')
    floor=number(str(floor),True)
    if floor>=100:raise ValueError('workflow_floor')
    historical=number(case['historical_retained_ratio'])
    if historical>1:raise ValueError('workflow_historical_ratio')
    parsed={}
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'platform','current_usd','main_usd','delivered_cost_usd'} or row['platform'] not in PLATFORMS or row['platform'] in parsed:raise ValueError('workflow_platform')
        parsed[row['platform']]=(money(row['current_usd']),money(row['main_usd']),number(row['delivered_cost_usd']))
    if not {'PS','XBOX'}<=set(parsed) or parsed['PS'][:2]!=parsed['XBOX'][:2]:raise ValueError('workflow_console_linkage')
    if parsed['PS'][2]!=parsed['XBOX'][2]:raise ValueError('workflow_console_common_cost_required')
    endings={p:package_ending(str(main),str(cost),str(floor)) for p,(old,main,cost) in parsed.items()}
    candidates={p:Decimal(v['package_usd']) for p,v in endings.items()}
    # One console parameter cannot apply two different ending choices.
    if candidates['PS']!=candidates['XBOX']:
        for p in ('PS','XBOX'):candidates[p]=parsed[p][1]
    output=[]
    for p,(old,main,cost) in parsed.items():
        proposed=main if main%1==Decimal('.99') else main.to_integral_value(rounding='ROUND_FLOOR')-Decimal('.01')
        transactions=[]
        undiscounted={label:figures(price,cost,Decimal(0)) for label,price in (('current',old),('main',main),('ending',candidates[p]))}
        average={label:figures(price*historical,cost,Decimal(0)) for label,price in (('current',old),('main',main),('ending',candidates[p]))}
        for d in ds:
            f={label:figures(price,cost,d) for label,price in (('current',old),('main',main),('ending',candidates[p]))}
            for label,value in f.items():
                value['floor_pass']=Decimal(undiscounted[label]['procurement_margin_pct'])>=floor and Decimal(average[label]['procurement_margin_pct'])>=floor
                value['margin_floor_basis']='undiscounted_and_historical_average_v2'
            net=Decimal(undiscounted['main']['net_usd']);g=Decimal(undiscounted['main']['procurement_gross_usd']);loss=main-candidates[p]
            ending_budget_pass=(loss<=net*Decimal('.01') and loss<=max(Decimal(0),g)*Decimal('.05') and Decimal(undiscounted['main']['procurement_margin_pct'])-Decimal(undiscounted['ending']['procurement_margin_pct'])<=1)
            g0=Decimal(f['current']['procurement_gross_usd']);g1=Decimal(f['main']['procurement_gross_usd']);gt=Decimal(f['ending']['procurement_gross_usd'])
            transactions.append({'discount_pct':str(d),**f,'ending_budget_pass':ending_budget_pass,'main_break_even_order_multiplier':str(max(Decimal(0),g0/g1)) if g1>0 else None,'ending_vs_current_break_even_order_multiplier':str(max(Decimal(0),g0/gt)) if gt>0 else None})
        main_pass=all(r['main']['floor_pass'] for r in transactions)
        ending_pass=main_pass and all(r['ending']['floor_pass'] and r['ending_budget_pass'] for r in transactions)
        output.append({'platform':p,'current_usd':str(old),'main_usd':str(main),'main_change_pct':str((main/old-1)*100),'main_pass':main_pass,
          'ending_preview':endings[p],'proposed_ending_usd':str(proposed),'linked_ending_usd':str(candidates[p]),'ending_pass':ending_pass,'transactions':transactions,'undiscounted':undiscounted,'estimated_average':average})
    consoles=[r for r in output if r['platform'] in ('PS','XBOX')]
    main_pass=all(r['main_pass'] for r in consoles);ending_pass=all(r['ending_pass'] for r in consoles)
    if not ending_pass:
        for r in consoles:r['selected_usd']=r['main_usd'] if main_pass else None
    else:
        for r in consoles:r['selected_usd']=r['linked_ending_usd']
    for r in output:
        if r['platform']=='PC':r['selected_usd']=r['linked_ending_usd'] if r['ending_pass'] else r['main_usd'] if r['main_pass'] else None
        selected=None if r['selected_usd'] is None else Decimal(r['selected_usd'])
        r['selected_change_pct']=None if selected is None else str((selected/Decimal(r['current_usd'])-1)*100)
        r['selected_direction']='blocked' if selected is None else 'hold' if selected==Decimal(r['current_usd']) else 'up' if selected>Decimal(r['current_usd']) else 'down'
    result={'basis':'declared_hypothesis','currency':'USD','rows':output,'console_main_pass':main_pass,'console_ending_pass':ending_pass,
      'margin_basis':'undiscounted_and_historical_average_v2','historical_retained_ratio':str(historical),'promotions_exempt_from_margin_floor':True,
      'rule':'PS/Xbox share one cost market and base price. Both undiscounted actual package margin and estimated average under the declared historical mix must be >=10%, incl all gifts. Individual legal promotions may lose money. P0→P1 is not limited by ending budgets; tail changes still obey them. Scenario is not execution authority or a future demand prediction.'}
    if 'economics' in case:
        pair=case['economics']
        if not isinstance(pair,dict) or set(pair)!={'before','after'}:raise ValueError('workflow_economics_fields')
        totals={}
        for label,row in pair.items():
            if not isinstance(row,dict) or set(row)!={'orders','net_unit_usd','delivered_cost_unit_usd','ads_usd'} or type(row['orders']) is not int or not 0<=row['orders']<=1000000000:raise ValueError('workflow_economics_fields')
            net,cost=number(row['net_unit_usd']),number(row['delivered_cost_unit_usd'],True);g=net-cost;gp=g*row['orders'];ads=None if row['ads_usd'] is None else number(row['ads_usd'],True)
            totals[label]={'orders':row['orders'],'gross_unit_usd':str(g),'procurement_gross_usd':str(gp),'ads_usd':None if ads is None else str(ads),'ad_after_contribution_usd':None if ads is None else str(gp-ads)}
        before,after=totals['before'],totals['after'];g1=Decimal(after['gross_unit_usd'])
        target=None
        gross_target=max(Decimal(0),Decimal(before['procurement_gross_usd'])/g1) if g1>0 else None
        if before['ad_after_contribution_usd'] is not None and after['ads_usd'] is not None and g1>0:
            target=max(Decimal(0),(Decimal(before['ad_after_contribution_usd'])+Decimal(after['ads_usd']))/g1)
        result['economics']={'totals':totals,'procurement_break_even_orders':str(gross_target) if gross_target is not None else None,'procurement_minimum_whole_orders':int(gross_target.to_integral_value(rounding=ROUND_CEILING)) if gross_target is not None else None,'break_even_orders':str(target) if target is not None else None,'minimum_whole_orders':int(target.to_integral_value(rounding=ROUND_CEILING)) if target is not None else None,'break_even_basis':'same-scope ad-after contribution; unknown Ads stays null while procurement threshold remains separately calculable','causal_effect':'not_identified_by_two_period_accounting','assumptions':'declared comparable cohort, mature refunds, net income, delivered costs and same-scope Ads in USD; no double discount deduction'}
    return result


def schema():
    decimal={'type':'string','pattern':r'^[0-9]+(?:\.[0-9]+)?$'}
    platform={'type':'object','properties':{'platform':{'enum':list(PLATFORMS)},**{k:decimal for k in ('current_usd','main_usd','delivered_cost_usd')}},'required':['platform','current_usd','main_usd','delivered_cost_usd'],'additionalProperties':False}
    economics={'type':'object','properties':{'orders':{'type':'integer','minimum':0},'net_unit_usd':decimal,'delivered_cost_unit_usd':decimal,'ads_usd':{'anyOf':[decimal,{'type':'null'}]}},'required':['orders','net_unit_usd','delivered_cost_unit_usd','ads_usd'],'additionalProperties':False}
    case={'type':'object','properties':{'currency':{'const':'USD'},'delivered_cost_includes_gifts':{'const':True},'historical_retained_ratio':dict(decimal,description='Declared historical revenue retention, >0 and <=1; source/window must be stated. Fictional scenarios are not production evidence.'),'platforms':{'type':'array','items':platform,'minItems':2,'maxItems':3},'discounts_pct':{'type':'array','items':decimal,'minItems':1,'maxItems':10},'economics':{'type':'object','properties':{'before':economics,'after':economics},'required':['before','after'],'additionalProperties':False}},'required':['currency','delivered_cost_includes_gifts','historical_retained_ratio','platforms','discounts_pct'],'additionalProperties':False}
    return {'type':'function','function':{'name':'mcp__fcro__fc_run_pricing_workflow','description':'Mandatory Astra FC Coins fixed decision receipt. review reads existing task-bound execution, completed Gold cost/coupon, exact marketing and current market; source gaps never stop existing automation. scenario requires common PS/Xbox cost and base price in their shared market; different source records need reconciliation, not platform base-price differentiation. scenario performs deterministic joint PS/Xbox and separate PC net-discount, margin, independent ending budgets and break-even accounting. Scenario values are declared hypotheses, never observed prices or execution permission. Read receipt values instead of recalculating in prose. Propose evidence-backed exceptions and falsifiers separately; changes enter existing reviewed learning, never auto-modify the workflow or business rules.',
      'parameters':{'type':'object','properties':{'profile':{'const':'FC27'},'action':{'enum':['review','scenario']},'start':{'type':'string'},'end':{'type':'string'},'case':case},'required':['profile','action','start','end'],'additionalProperties':False}}}


class Workflow:
    def __init__(self,book,bridge):self.book,self.bridge,self.frozen=book,bridge,{}
    def read(self,name,args):
        value=self.book.call(name,args)
        if isinstance(value,dict) and value.get('evidence_id') in self.book.evidence:return deepcopy(self.book.evidence[value['evidence_id']])
        return {'data':value}
    def __call__(self,args):
        from coins_evidence import checked_query,baseline_identity
        if not isinstance(args,dict) or set(args)-{'profile','action','start','end','case'} or args.get('action') not in ('review','scenario'):raise ValueError('workflow_fields')
        checked_query({k:v for k,v in dict(args,kind='readiness').items() if k not in ('action','case')})
        if ('case' in args)!=(args['action']=='scenario'):raise ValueError('workflow_case_boundary')
        engine,policy,identity=self.bridge.baseline();floor=policy['minimum_gross_margin_pct']
        result={'workflow_version':VERSION,'workflow_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'captured_at':datetime.now(timezone.utc).isoformat(),'steps':list(STEPS),'scope':{k:args[k] for k in ('profile','start','end')},'baseline_policy':identity,'business_baseline':baseline_identity(),
          'minimum_procurement_margin_pct':str(floor),'minimum_estimated_average_margin_pct':str(floor),'margin_basis':'undiscounted_and_historical_average_v2','write_performed':False,'execution_authorized':False,'existing_automation_changed':False}
        if args['action']=='scenario':result.update(status='available',scenario=evaluate(args['case'],floor),source_kind='declared_hypothesis')
        else:
            key=digest(dict(args,policy=identity))
            if key in self.frozen:return deepcopy(self.frozen[key])
            period={k:args[k] for k in ('profile','start','end')};sources={}
            for label,name,query in (('order_costs','fc.query_pricing_evidence',dict(period,kind='order_costs')),('executions','fc.query_pricing_evidence',dict(period,kind='price_history')),('marketing','fc.query_marketing_snapshot',period),('market','fc.query_market_snapshot',{'profile':'FC27'})):
                sources[label]=self.read(name,query)
            refs={k:v.get('evidence_id') for k,v in sources.items()};data={k:v.get('data') or {} for k,v in sources.items()}
            states={k:v.get('status','not_available') for k,v in data.items()}
            pending=any(s in ('pending','reading','running','queued','busy') for s in states.values())
            costs=data['order_costs'];market=data['market'];history=data['executions'];events=list(history.get('events',[]));pages=1
            while history.get('pagination',{}).get('has_more'):
                pages+=1
                if pages>250:raise ValueError('workflow_execution_pagination')
                row=self.read('fc.query_pricing_evidence',dict(period,kind='price_history',page=pages));history=row.get('data') or {}
                if history.get('status')!='available':break
                refs['executions_page_'+str(pages)]=row.get('evidence_id');events.extend(history.get('events',[]))
            complete=bool(history.get('pagination')) and history['pagination'].get('has_more') is False and len(events)==history['pagination'].get('total_events')
            summary=costs.get('summary',{});accounting=costs.get('quality_checks',{})
            gaps=[]
            if not complete:gaps.append('execution_pages_incomplete')
            if not accounting or not all(accounting.values()):gaps.append('cost_accounting_not_verified')
            if summary.get('missingCostOrders'):gaps.append('completed_cost_missing')
            if costs.get('revenue_basis')!='admin_order_cny':gaps.append('admin_order_revenue_backfill_pending')
            if not market.get('can_recommend_price'):gaps.append('qualified_comparable_market_missing')
            gaps.extend(['package_quantity_not_retained','Coins_same_scope_Ads_not_attributed','net_refund_settlement_unverified','public_exposure_not_proven_by_backend_ledger'])
            if any(s not in ('available','partial') for s in states.values()):gaps.append('one_or_more_sources_not_terminal_usable')
            result.update(status='pending' if pending else 'partial' if gaps else 'available',source_kind='existing_task_evidence',source_refs=refs,source_statuses=states,
              source_times={k:{field:v[field] for field in ('captured_at','observed_at','source_times') if field in v} for k,v in data.items()},
              checks={'execution_pages_complete':complete,'execution_events':len(events),'accounting_identities':accounting,'cost_coverage':{k:summary.get(k) for k in ('completedOrders','coveredOrders','missingCostOrders')},'whole_source_coverage':costs.get('coverage')},
              procurement_accounting={k:summary.get(k) for k in ('saleCny','costCny','profitCny','margin')},procurement_revenue_basis=costs.get('revenue_basis','legacy_delivery'),accounting_currency='CNY',
              current_package_accounting=current_accounting(market,floor),
              ad_after_contribution={'status':'not_identified','value':None,'rule':'FC project Ads in USD is not Coins attributed cost; never subtract from CNY covered-order gross profit'},
              candidates={'keep':'must include actual storefront P0; not an assertion that it is safe','original_engine':'use original qualified snapshot simulation as a separate baseline','research':'smallest necessary comparable change first; greater change requires a stated demand hypothesis','numeric_new_price_recommendation':False},
              gaps=gaps,hermes_responsibility=['explain why a candidate is worth testing','state competing explanations and the smallest missing evidence','declare demand assumptions; break-even is not demand prediction','name falsifiers and retrospective outcome window'],
              learning_path='owned completed source → candidate review → counterexample replay → human CAS publish/revoke; no self-modification or business execution')
            snapshot=(market.get('storefront') or {}).get('collection_run_id')
            try:
                if not snapshot:raise ValueError('current_collection_identity_missing')
                if not hasattr(self.bridge,'load'):raise ValueError('legacy_engine_baseline_retired_use_v3_pricing_control')
                _,original,original_refs=self.bridge.load(snapshot,engine,policy,identity)
                result['original_engine_baseline']={'status':'available','calculation':original,'source_refs':original_refs,'snapshot_id':snapshot,'rule':'original-engine baseline, not actual storefront or execution'}
            except (ValueError,FileNotFoundError) as error:
                result['original_engine_baseline']={'status':'not_available','reason':str(error) if isinstance(error,ValueError) else 'qualified_snapshot_missing'}
        result['receipt_sha256']=digest(result)
        if args['action']=='review' and not pending:self.frozen[key]=deepcopy(result)
        return result
