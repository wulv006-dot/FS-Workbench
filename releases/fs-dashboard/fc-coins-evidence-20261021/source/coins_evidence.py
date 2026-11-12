"""FC Coins aggregates over existing FS archives. No login, collection or writer."""
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
import hashlib,json,re,stat,uuid

TZ=timezone(timedelta(hours=8))
CONTRACT='fc-coins-existing-evidence-v1'
KINDS=('price_history','order_costs','readiness')
GOLD='货币(Gold)'

def baseline_identity():
    raw=Path(__file__).with_name('business-baseline.md').read_bytes()
    match=re.search(r'business-baseline-(?:\d+-v\d+|fc-v\d+-\d+)',raw.decode('utf-8'))
    if not match:raise ValueError('coins_business_baseline_version')
    return {'version':match[0],'sha256':hashlib.sha256(raw).hexdigest()}

def checked_query(args):
    if not isinstance(args,dict) or set(args)-{'profile','kind','start','end','page'} or not {'profile','kind','start','end'}<=set(args):raise ValueError('coins_evidence_fields')
    if args['profile']!='FC27' or args['kind'] not in KINDS:raise ValueError('coins_evidence_scope')
    lo,hi=(date.fromisoformat(args[k]) for k in ('start','end'))
    if lo.isoformat()!=args['start'] or hi.isoformat()!=args['end'] or not 0<=(hi-lo).days<=30 or hi>datetime.now(TZ).date():raise ValueError('coins_evidence_period')
    if type(args.get('page',1)) is not int or not 1<=args.get('page',1)<=1000:raise ValueError('coins_evidence_page')
    return dict(args,page=args.get('page',1))

def schema():
    return {'type':'function','function':{'name':'mcp__fcro__fc_query_pricing_evidence',
      'description':'Read existing FC27 Coins evidence only. price_history: original execution status, before/after backend USD/K parameters, proposed package/gifts and run IDs; backend confirmation is not independent public readback. order_costs: exact ES Gold orders joined privately to existing channel/coupon/delivery archives, completed-only CNY accounting and USD sales/discounts kept separate; all FC or Items are not Coins. readiness: current baseline hash and existing source coverage, with explicit pending/missing. Never exports order/customer identities or changes schedules, prices, formulas or collectors. Use fc.query_marketing_snapshot for same-period Ads; no order-level ad attribution. Partial archive/unknown platform or package remain explicit.',
      'parameters':{'type':'object','properties':{'profile':{'type':'string','enum':['FC27']},'kind':{'type':'string','enum':list(KINDS)},'start':{'type':'string'},'end':{'type':'string'},'page':{'type':'integer','minimum':1,'maximum':1000}},'required':['profile','kind','start','end'],'additionalProperties':False}}}

def read_json(path):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('coins_evidence_symlink')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>64*1024*1024:raise ValueError('coins_evidence_file')
    raw=path.read_bytes()
    if len(raw)>64*1024*1024:raise ValueError('coins_evidence_file')
    return json.loads(raw),hashlib.sha256(raw).hexdigest()

def numeric(value):
    if isinstance(value,bool):return None
    try:n=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError):return None
    return str(n) if n.is_finite() else None

def safe_label(value):
    text=str(value or 'unknown')
    return 'unknown' if len(text)>120 or re.search(r'[@<>\r\n]|https?://|Bearer|Cookie|password',text,re.I) else text

def es_metadata(start,end,archive):
    from es_order_structure import archived_dataset
    manifests=[]
    paths=list(archive.glob('*.json'))
    if len(paths)>512:raise ValueError('coins_es_archive_capacity')
    for p in paths:
        v,_=read_json(p)
        if isinstance(v,dict) and isinstance(v.get('query'),dict) and {'start','end'}<=set(v['query']):manifests.append(v)
    cursor=start;selected={}
    while cursor<=end:
        choices=[v for v in manifests if v['query']['start']<=cursor<=v['query']['end']]
        if not choices:break
        v=max(choices,key=lambda v:(v.get('captured_at') or '',v['query']['end']))
        key=json.dumps(v['query'],sort_keys=True)
        if key not in selected:selected[key]=(v,set())
        selected[key][1].add(cursor)
        cursor=(date.fromisoformat(cursor)+timedelta(days=1)).isoformat()
    rows=defaultdict(set);discounts=defaultdict(set);hashes=set();captures=[];complete=cursor>end
    for manifest,selected_days in selected.values():
        query=dict(manifest['query'])
        # ALL exports support exact-range projection. Do not apply today's TTL
        # to closed days merely because their covering export includes today.
        # FC27 exports still require their original exact query.
        if query.get('profile')=='ALL':
            query.update(start=min(selected_days),end=max(selected_days))
        d=archived_dataset(query,root=archive)
        if d is None:complete=False;continue
        complete &= d['parse_failures']==0 and d['failed_files']==0 and d['declared_files']==len(d['hashes'])
        hashes.update(d['hashes']);captures.append(d.get('captured_at'))
        for row in d['rows']:
            day=str(row.get('付款时间') or '').replace('/','-')[:10]
            if row.get('游戏')=='FC 27' and day in selected_days and row.get('订单号'):
                rows[row['订单号']].add(str(row.get('产品类型') or 'unknown'))
                discounts[row['订单号']].add(numeric(row.get('折扣金额')))
    return {k:{'product':next(iter(v)) if len(v)==1 else 'ambiguous','discount_usd':next(iter(discounts[k])) if len(discounts[k])==1 else None} for k,v in rows.items()}, {'complete':bool(complete),'files':len(hashes),'source_sha256':hashlib.sha256(''.join(sorted(hashes)).encode()).hexdigest(),'captured_at':min((v for v in captures if v),default=None)}

class CoinsEvidence:
    def __init__(self,root=Path('/var/lib/fc27-cloud'),channel_root=Path('/var/lib/fs-channel-effects'),archive=Path('/var/lib/fc27-es-exports'),dataset=None,clock=None):
        self.root,self.channel_root,self.archive=map(Path,(root,channel_root,archive))
        self.dataset=dataset or (lambda:{})
        self.clock=clock or (lambda:datetime.now(timezone.utc))

    def channel_data(self,period):
        from channel_cache import compose,apply_delivery_cache
        from channel_source import apply_customer_types,apply_cost_overrides
        from channel_effects import VERSION
        data=compose(period,root=self.channel_root)
        if data is None:
            # Today is not a closed-day archive; reuse its exact canonical FS cache.
            key=hashlib.sha256((VERSION+json.dumps(period,sort_keys=True)).encode()).hexdigest()[:24]
            path=self.channel_root/(key+'.json')
            if not path.exists():return None
            data,_=read_json(path)
            if data.get('period')!=period or any(data.get('sources',{}).get(n,{}).get('status')!='complete' for n in ('orders','coupons')):
                raise ValueError('coins_live_cache_scope_or_coverage')
            data=dict(data,coinsCacheBasis='canonical_exact_range_cache; generatedAt_is_source_time_not_freshness_guarantee')
        return apply_cost_overrides(apply_customer_types(apply_delivery_cache(data,root=self.channel_root)))

    def history(self,q):
        paths=list((self.root/'executions').glob('*.json'))
        if len(paths)>5000:raise ValueError('coins_execution_capacity')
        rows=[];skipped=0
        for path in paths:
            if not re.fullmatch(r'[a-f0-9-]{36}\.json',path.name):continue
            v,sha=read_json(path)
            try:
                when=datetime.fromisoformat(v['created_at'].replace('Z','+00:00'))
                if when.tzinfo is None:raise ValueError('missing_timezone')
            except (KeyError,ValueError,TypeError):skipped+=1;continue
            if not q['start']<=when.astimezone(TZ).date().isoformat()<=q['end']:continue
            try:
                execution=str(uuid.UUID(v['execution_id']));run=str(uuid.UUID(v['run_id']))
                if execution!=path.stem or v['execution_id']!=execution or v['run_id']!=run:raise ValueError('coins_execution_identity')
                identity={'basis':'legacy_execution_and_run_same_id'};job_status=None;reconciliation=None
                if run!=execution:
                    # V2 separates a quote run from each execution; verify the original chain.
                    preview_id=str(uuid.UUID(v['preview_id']))
                    if preview_id!=v['preview_id']:raise ValueError('coins_preview_identity')
                    preview,preview_sha=read_json(self.root/'previews'/(preview_id+'.json'))
                    quote,quote_sha=read_json(self.root/'quotes'/(run+'.json'))
                    if preview.get('preview_id')!=preview_id or preview.get('run_id')!=run or quote.get('run_id')!=run:raise ValueError('coins_quote_chain')
                    identity={'basis':'execution_preview_quote_chain','preview_id':preview_id,'preview_sha256':preview_sha,'quote_sha256':quote_sha}
                    job_path=self.root/'jobs'/(execution+'.json')
                    if job_path.exists():
                        job,_=read_json(job_path)
                        if job.get('job_id')!=execution:raise ValueError('coins_job_identity')
                        job_status=safe_label(job.get('status'));record=job.get('reconciliation')
                        if record:
                            if record.get('execution_id')!=execution:raise ValueError('coins_reconciliation_identity')
                            reconciliation={k:record.get(k) for k in ('status','completed_at','original_job_status','mmoexp_replayed','public_readback')}
            except (KeyError,ValueError,TypeError,OSError):skipped+=1;continue
            def prices(name):
                return {r.get('expectedPlatform',r.get('platform')):numeric(r.get('b2c')) for r in (v.get(name) or {}).get('rows',[]) if r.get('expectedPlatform',r.get('platform')) in ('PS','XBOX','PC')}
            before,after=prices('before'),prices('after')
            targets=[{'platform':r['platform'],'planned_package_usd':numeric(r.get('targetPageUsd')),'own_bonus_k':numeric(r.get('ownBonusK')),'source_cost_cny_per_k':numeric(r.get('sourceCost')),'effective_cost_cny_per_k':numeric(r.get('effectiveCost')),'cost_trade_at':safe_label(r.get('recordTradeAt'))} for r in v.get('targets',[]) if r.get('platform') in ('PS','XBOX','PC')]
            rows.append({'execution_id':v['execution_id'],'run_id':v['run_id'],'identity_check':identity,'job_status':job_status,'reconciliation':reconciliation,'record_sha256':sha,'created_at':v['created_at'],'updated_at':v.get('updated_at'),'status':safe_label(v.get('status')),'automatic':v.get('automatic') is True,'changed_platforms':[p for p in v.get('changed',[]) if p in ('PS','XBOX','PC')],
              'before_backend_usd_per_k':before,'after_backend_usd_per_k':after,'proposed_targets':targets,'sync_confirmed':v.get('sync_confirmed') is True,
              'execution_confirmed':v.get('status')=='CONFIRMED','independent_public_after_readback':'not_proven_by_this_execution_record'})
        rows.sort(key=lambda v:(v['created_at'],v['execution_id']),reverse=True)
        size=20;page=q['page']
        return {'status':'partial' if skipped else 'available','events':rows[(page-1)*size:page*size],'pagination':{'page':page,'page_size':size,'total_events':len(rows),'has_more':page*size<len(rows)},'coverage':{'ledger_files':len(paths),'invalid_identity_or_time':skipped},'status_counts':dict(Counter(v['status'] for v in rows)),
          'rule':'Original execution ledger, not the empty manual action table. Preserve failed/unknown states. Parameters and proposed targets are not independent public price exposure or proof of business effect; no-change is not a price cut.'}

    def costs(self,q):
        from channel_effects import accounting_row,metrics,completed,fraud
        data=self.channel_data({k:q[k] for k in ('start','end')})
        if data is None:return {'status':'not_available','reason':'existing_channel_day_cache_missing','next_step':'Use original FS /channels exact period; original background refresh and nightly backfill remain enabled. This adapter never launches a duplicate collector.'}
        if data.get('period')!={k:q[k] for k in ('start','end')} or any(data['sources'][n]['status']!='complete' for n in ('orders','coupons')):raise ValueError('coins_channel_scope')
        meta,coverage=es_metadata(q['start'],q['end'],self.archive)
        fc=[r for r in data['orders'] if str(r['gid'])=='1327']
        if len({r['orderNo'] for r in fc})!=len(fc):raise ValueError('coins_duplicate_order')
        revenue_ready=all('adminSaleCny' in r for r in data['orders'])
        selected=[];excluded=Counter()
        paid=self.dataset();platforms={r['id']:r.get('platform','unknown') for r in paid.get('orders',[]) if r.get('site_group')=='main'}
        for raw in fc:
            if not q['start']<=raw['day']<=q['end']:raise ValueError('coins_order_period')
            info=meta.get(hashlib.sha256(raw['orderNo'].encode()).hexdigest())
            if not info or info['product']!=GOLD:excluded[info['product'] if info else 'missing_es_product']+=1;continue
            row=accounting_row(raw,data.get('costOverrides',{}),data.get('testOrders',{}),admin_revenue=revenue_ready)
            row['platform']=platforms.get(row['orderNo'],'unknown')
            row['es_discount_usd']=info['discount_usd'];selected.append(row)
        def stats(items):
            m=metrics(items)
            applicable=[r for r in items if not r.get('testOrder') and not fraud(r) and numeric(r.get('es_discount_usd')) is not None]
            m.update(actual_discount_usd=str(sum((Decimal(r['es_discount_usd']) for r in applicable),Decimal(0))) if applicable else None,known_discount_orders=len(applicable))
            return m
        groups={}
        for field in ('day','platform','customerType','project'):
            buckets=defaultdict(list)
            for row in selected:buckets[safe_label(row.get(field))].append(row)
            groups[field]=[{'label':k,**stats(v)} for k,v in sorted(buckets.items())]
        coupon=[r for r in selected if r['coupons']]
        codes=[r for r in selected if r.get('codeKey') or r.get('promoterUid')]
        valid=[r for r in selected if not r.get('testOrder') and not fraud(r) and not r['refunded']]
        promotion_population=[r for r in valid if str(r.get('payStatus'))=='1']
        observed=[r for r in promotion_population if numeric(r.get('salesUsd')) is not None and numeric(r.get('es_discount_usd')) is not None
                  and Decimal(str(r['salesUsd']))>=0 and Decimal(r['es_discount_usd'])>=0]
        net_usd=sum((Decimal(str(r['salesUsd'])) for r in observed),Decimal(0))
        discount_usd=sum((Decimal(r['es_discount_usd']) for r in observed),Decimal(0))
        before_discount=net_usd+discount_usd
        promotion_mix=dict(status='available' if len(observed)==len(promotion_population) and coverage['complete'] and not excluded.get('missing_es_product') else 'partial',
            observed_orders=len(observed),eligible_orders=len(promotion_population),net_order_usd=str(net_usd),actual_discount_usd=str(discount_usd),
            undiscounted_order_usd=str(before_discount),retained_ratio=str(net_usd/before_discount) if before_discount else None,
            population='identified main-site Coins paid nonrefund nonfraud nontest orders; all platforms combined',
            formula='sum(Admin order USD) / sum(Admin order USD + matched ES actual discount USD)',
            limitation='revenue-weighted observed discount intensity, not eligibility redemption rate, platform mix, quantity mix or future probability')
        usage=defaultdict(list)
        for row in valid:
            usage[tuple(sorted({safe_label(c['templateId']) for c in row['coupons']}))].append(row)
        promotion_usage=dict(population='identified_Coins_nonrefund_nonfraud_nontest_orders',orders=len(valid),
            groups=[dict(coupon_template_ids=list(k),**stats(v)) for k,v in sorted(usage.items())],
            eligibility_denominator='unknown_not_inferred_from_new_customer_flag',
            historical_usage_is_not_future_probability=True,
            no_coupon_does_not_mean_no_discount=True,
            forecast_status='not_computed_requires_package_quantities_current_terms_and_demand_assumptions')
        summary=stats(selected)
        checks={'counts_reconcile':summary['orders']==summary['completedOrders']+summary['pendingOrders']+summary['refundedOrders'],
            'cost_coverage_reconciles':summary['completedOrders']==summary['coveredOrders']+summary['missingCostOrders'],
            'covered_profit_identity':summary['profitCny'] is None or abs(Decimal(str(summary['saleCny']))-Decimal(str(summary['costCny']))-Decimal(str(summary['profitCny'])))<=Decimal('.01')}
        if not all(checks.values()):raise ValueError('coins_accounting_identity_failed')
        return {'status':'available' if revenue_ready and coverage['complete'] and not excluded.get('missing_es_product') and not summary['missingCostOrders'] and not summary['missingRevenueOrders'] else 'partial','revenue_basis':'admin_order_cny' if revenue_ready else 'legacy_delivery','captured_at':data['generatedAt'],'source_times':{'orders_and_coupons':data['generatedAt'],'cost':data['sources']['cost'].get('generatedAt'),'es':coverage['captured_at'],'platform':paid.get('as_of')},
          'cache_basis':data.get('coinsCacheBasis','closed_day_archive'),
          'summary':summary,'groups':groups,'coupon_orders':stats(coupon),'code_or_referrer_orders':stats(codes),'coupon_and_code_overlap':stats([r for r in coupon if r.get('codeKey') or r.get('promoterUid')]),
          'promotion_usage':promotion_usage,'historical_discount_mix':promotion_mix,
          'coverage':{'fc_project_orders':len(fc),'coins_selected':len(selected),'excluded_product_orders':dict(excluded),'es':coverage,'platform_unknown_orders':sum(r['platform']=='unknown' for r in selected),'package_quantity':'not_retained_in_channel_archive','historical_net_refund_settlement':'unverified'},
          'quality_checks':checks,'sources':data['sources'],
          'rule':'FC27 main-site ES exact Gold orders only. Admin whole-order CNY revenue is counted once against actual linked purchase cost for completed covered orders; legacy_delivery means the whole range still uses old delivery income pending migration. Fraud is excluded. USD order/discount amounts remain separate. These are not SKU net revenue, USD profit, ad-after contribution, final settlement or causal price effects. Do not deduct already-net discounts twice. Coupon and code groups overlap; do not sum them. Existing product formulas and automation remain unchanged.'}

    def __call__(self,args):
        q=checked_query(args)
        if q['kind']=='price_history':value=self.history(q)
        elif q['kind']=='order_costs':value=self.costs(q)
        else:
            costs=self.costs(q);history=self.history(dict(q,page=1))
            value={'status':'available' if costs['status']=='available' else 'partial','business_baseline':baseline_identity(),'cost_status':costs['status'],'cost_coverage':costs.get('coverage'),'cost_quality_checks':costs.get('quality_checks'),'execution_coverage':history['coverage'],'execution_status_counts':history['status_counts'],
              'marketing_query':{'tool':'fc.query_marketing_snapshot','profile':'FC27','start':q['start'],'end':q['end']},'marketing_status':'query_required_not_missing','rule':'Read exact-period marketing to terminal status through original query. No platform/order ad allocation or cross-currency subtraction. Never substitute total FC/Items for Coins or Top rows for population. Scope is Coins strategy only; existing other-product formulas remain unchanged.'}
        value.update(http_status=200 if value['status'] in ('available','partial') else 503,contract=CONTRACT,query=q,readonly=True,collection_triggered=False,business_writes=False,observed_at=self.clock().isoformat())
        return value
