"""Server-only transaction collector using the shared Order HTTP session."""
from pathlib import Path
from datetime import datetime,timezone,timedelta,date
import json,subprocess,sys,copy,hashlib,time
from atomic_snapshot import run_once,atomic_write,encoded,SHANGHAI,OrderSourceBusy
from fc_category_contract import cycle_requests,cycle_analysis,CONTRACT
from fc_product_contract import requests as product_requests,cycle as product_cycle
from profit_reader_adapter import expected_contracts, daily_requests, adapt_reader, failed_attempt
from profit_daily import build_history
from profit_backfill import load_caches, merge_cached, plan_requests, apply_results, coverage

# Match existing service budget; reserve publication time before optional reads.
SERVICE_BUDGET_SECONDS=1800
PROFIT_PUBLISH_RESERVE_SECONDS=90
PROFIT_MIN_READ_SECONDS=15
COLLECTION_DEADLINE=time.monotonic()+SERVICE_BUDGET_SECONDS

def profit_read_timeout():
    remaining=COLLECTION_DEADLINE-time.monotonic()-PROFIT_PUBLISH_RESERVE_SECONDS
    return min(240,int(remaining)) if remaining>=PROFIT_MIN_READ_SECONDS else 0

HERE=Path(__file__).resolve().parent
WEB=Path('/var/www/dashboard/fs-home/transactions')
PROFILES=[('MMOEXP','所有网站合计',0,'','mmoexp'),('POE2','Path Of Exile 2',552,552,'rpg'),
 ('D4','Diablo 4',456,456,'rpg'),('AION2','Aion 2',826,891,'rpg'),('FC27','FC27',1322,1327,'sports'),('NBA2K27','NBA2K27',1306,1329,'sports'),
 ('NFL27','Madden NFL27',1258,1309,'sports'),('MLB26','MLB26',922,927,'sports'),('CFB27','CFB27',1256,1307,'sports'),('FC26','FC26',824,833,'sports'),
 ('RS', 'RS', 506, 506, 'general'),
 ('MAPLESTORY_CLASSIC', 'MapleStory Classic World', 1300, 1333, 'general'),
 ('ARC_RAIDERS', 'ARC Raiders', 864, 925, 'general'),
 ('DARK_AND_DARKER', 'Dark and Darker', 588, 589, 'rpg'),
 ('WOW_FOREVER', 'WoW Forever', 1364, 1367, 'rpg'),
 ('ARENA_BREAKOUT_INFINITE', '暗区突围无限', 836, 897, 'general'),
 ('COD_BO7', 'CoD BO7', 838, 859, 'general')]

def order_call(script,requests,timeout):
    """Hold the existing Order mutex only for a real Order batch."""
    import fcntl
    if script not in ('primary_reader.py','fc_category_reader.py','profit_daily_reader.py'):
        raise ValueError('order_reader_required')
    with (WEB/'collector.lock').open('a+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise OrderSourceBusy('collector_busy') from None
        return call(None,script,requests,timeout)


def call(container,script,requests,timeout):
    if script in ('primary_reader.py','fc_category_reader.py','profit_daily_reader.py'):
        r=subprocess.run([sys.executable,'-B',str(HERE/script),json.dumps(requests)],
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    else:
        program=(HERE/script).read_bytes()
        if script in ('supplement_reader.py','fc_product_reader.py'):
            module_name='fc_product_contract' if script=='fc_product_reader.py' else 'supplement_fields'
            helper=(HERE/(module_name+'.py')).read_text()
            prefix='import types,sys\nmodule=types.ModuleType('+repr(module_name)+')\nexec('+repr(helper)+',module.__dict__)\nsys.modules['+repr(module_name)+']=module\n'
            program=prefix.encode()+program
            r=subprocess.run([sys.executable,'-B','-',json.dumps(requests)],input=program,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
        else:
            r=subprocess.run(['docker','exec','-i',container,'python3','-',json.dumps(requests)],input=program,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    if r.returncode:
        # Known contract errors only; never print arbitrary upstream stderr/session data.
        last=r.stderr.decode('utf-8','replace').strip().splitlines()
        code=last[-1] if last and last[-1].startswith('ValueError: primary_') else 'container_reader_failed_'+str(r.returncode)
        raise RuntimeError(code)
    return json.loads(r.stdout)

def profile_record(key,name,source,supplement):
    return {'key':key,'name':name,'period':source['period'],'primary':source,'supplement':supplement,
      'metrics':{**source.get('metrics',{}),'orders':{'value':source['orders'],'source':'primary'},'revenueUsd':{'value':source['revenueUsd'],'source':'primary'},
                 'newCustomers':{'value':supplement.get('newCustomers'),'source':'supplement','status':supplement['status']}}}

def dimensions(record):
    result={'period':record['period'],'source':'order.p2pah.cn','channels':None,'statuses':None,'products':None,
            'country':None,'coupon':None,'payment':None,'currency':'USD'}
    for chart in record.get('charts') or []:
        if not chart:continue
        title=chart.get('title') or []
        if '来源' in title and chart.get('series'):
            result['channels']=[{'name':str(n),'amountUsd':float(v),'orders':None} for n,v in zip(chart['labels'],chart['series'][0]['data'])]
        for label,field in [('订单状态','statuses'),('产品类型','products')]:
            if label in title and chart.get('series'):
                result[field]=chart['series'][0]['data']
    return result

def collect_profit_history(today,previous_data):
    # Native complete-day gaps share this existing collector lock and timer.
    # Cache reuse is local/read-only; one bounded reader batch never duplicates range jobs.
    profit_started=time.monotonic()
    profit_contracts=expected_contracts(PROFILES)
    profit_previous=(previous_data or {}).get('profitHistory',{}).get('daily',[])
    if not profit_previous:
        seed=json.loads((HERE/'profit-history-seed.json').read_text(encoding='utf-8'))
        profit_previous=build_history([],seed['records'],profit_contracts)['daily']
    # Validate durable history before touching optional inputs. Never mask corruption.
    profit_previous=build_history(profit_previous,[],profit_contracts)['daily']
    cached=[];chosen=[];cache_audit={'stopReason':'skipped_remaining_budget'}
    cache_ignored=0
    if profit_read_timeout():
        try:
            cached,chosen,cache_audit=load_caches(Path('/var/lib/fs-business-ranges'),profit_contracts,today)
        except (OSError,ValueError,TypeError,KeyError,AttributeError,OverflowError):
            cache_audit={'stopReason':'cache_read_unavailable'}
    profit_previous,cache_ignored=merge_cached(profit_previous,cached,profit_contracts)
    profit_wanted,queue=plan_requests(today,profit_previous,profit_contracts,chosen)
    profit_records=[];profit_timeout=profit_read_timeout() if profit_wanted else 0
    profit_read_status='not_required'
    read_audit={'attempted':0,'available':0,'failed':0,'deferred':len(profit_wanted),'rejected':0}
    if profit_wanted:
        if not profit_timeout:
            profit_read_status='skipped_remaining_budget'
        else:
            try:
                profit_reads=order_call('profit_daily_reader.py',
                    {'requests':profit_wanted,'budgetSeconds':profit_timeout},profit_timeout)
                profit_records,read_audit=apply_results(profit_wanted,profit_reads,profit_contracts)
                profit_read_status='unavailable' if read_audit.get('batchProgressUnknown') else 'partial' if read_audit['failed'] or read_audit['deferred'] or read_audit['rejected'] else 'available'
            except OrderSourceBusy:
                profit_read_status='deferred'
                read_audit['stopReason']='collector_busy'
            except (OSError,RuntimeError,subprocess.TimeoutExpired,ValueError,KeyError,TypeError,AttributeError,OverflowError):
                # Unknown batch progress cannot manufacture per-day attempt timestamps.
                # Existing valid values remain; explicit collection failure records the limit.
                profit_read_status='unavailable'
                read_audit['batchProgressUnknown']=True
    profit_merged,read_merge_rejected=merge_cached(profit_previous,profit_records,profit_contracts)
    read_audit['mergeRejected']=read_merge_rejected
    if read_merge_rejected and profit_read_status=='available':profit_read_status='partial'
    profit_history=build_history(profit_merged,[],profit_contracts)
    profit_history['collection']={
        'optionalReadStatus':profit_read_status,'optionalReadTimeoutSeconds':profit_timeout,
        'serviceBudgetSeconds':SERVICE_BUDGET_SECONDS,'publicationReserveSeconds':PROFIT_PUBLISH_RESERVE_SECONDS,
        'phaseElapsedSeconds':max(0,time.monotonic()-profit_started),
        'readerMaxRequestSeconds':20,'readerCleanupReserveSeconds':10,
        'cache':cache_audit,'cacheMergeRejected':cache_ignored,'queue':queue,'reads':read_audit}
    profit_history['recentCompleteDayCoverage']=coverage(today,profit_history['daily'],profit_contracts)
    return profit_history

def collect(backfill=None):
    now=datetime.now(SHANGHAI).replace(second=0,microsecond=0)
    today=now.date();cutoff=now.strftime('%Y-%m-%d %H:%M');start=today.isoformat()+' 00:00'
    history=(today-timedelta(days=90)).isoformat()+' 00:00'
    previous_analytics=None;previous_products=None;previous_snapshot=None;previous_data=None
    try:
        last=json.loads((WEB/'current.json').read_text())
        if last['path']!='snapshots/'+last['snapshotId']+'/snapshot.json':raise ValueError('previous_path')
        raw=(WEB/last['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=last['sha256']:raise ValueError('previous_hash')
        previous_data=json.loads(raw);candidate=previous_data.get('fc27Analytics')
        previous_products=previous_data.get('fc27ProductRankings');previous_snapshot=last['snapshotId']
        if candidate and candidate.get('contractId')==CONTRACT and candidate.get('scope')=='all-websites':previous_analytics=candidate
    except (OSError,KeyError,ValueError):pass
    order=[];admin=[]
    for key,name,gid,game,group in PROFILES:
        status='3' if group=='rpg' else ''
        order.extend([{'key':key+':today','gid':gid,'status':status,'start':start,'end':cutoff},
                      {'key':key+':history','gid':gid,'status':status,'start':history,'end':start}])
        admin.append({'key':key+':today','game':game,'status':'', 'start':start,'end':cutoff})
    # FC27 detailed orders/amounts and FC26 prior-year comparison stay on the same primary.
    baseline_start=(today-timedelta(days=90)).replace(year=today.year-1).isoformat()+' 00:00'
    baseline_end=today.replace(year=today.year-1).isoformat()+' 00:00'
    for key,gid,begin,end in [('FC27',1322,history,start),('FC26-prior',824,baseline_start,baseline_end)]:
        for suffix,tid in [('all',''),('coins','1'),('items','2')]:order.append({'key':key+':'+suffix,'gid':gid,'tid':tid,'start':begin,'end':end})
    if backfill:
        target=date.fromisoformat(backfill)
        if target>=today:raise ValueError('backfill_requires_complete_day')
        for suffix,d,gid in [('now',target,1322),('prior',target.replace(year=target.year-1),824)]:
            for kind,tid in [('all',''),('coins','1'),('items','2')]:
                order.append({'key':'backfill:'+suffix+':'+kind,'gid':gid,'tid':tid,'start':d.isoformat()+' 00:00','end':(d+timedelta(days=1)).isoformat()+' 00:00'})
    # Full historical customer figures are not fabricated from orders. Refresh the existing
    # maintained date range, plus yesterday; older missing customer fields remain null.
    old=Path('/var/www/sites/wulv/fc27-ops/data/daily.json')
    maintained=[]
    if old.is_file():maintained=[r['d'] for r in json.loads(old.read_text()).get('rows',[]) if isinstance(r,dict) and 'd' in r]
    days=set(maintained+[ (today-timedelta(days=1)).isoformat() ])
    if backfill:days.add(backfill)
    for day in sorted(days):
        d=date.fromisoformat(day)
        if d>=today:continue
        for suffix,target,game in [('now',d,1327),('prior',d.replace(year=d.year-1),833)]:
            admin.append({'key':'fc-customer:'+day+':'+suffix,'game':game,'start':target.isoformat()+' 00:00','end':(target+timedelta(days=1)).isoformat()+' 00:00'})
    primary=order_call('primary_reader.py',order,900)
    supplements=call(None,'supplement_reader.py',admin,600)
    # FC aggregate extension only. No new timer, price reads/writes or customer allocation.
    # Category failure never discards the successful legacy transaction snapshot.
    try:extra=order_call('fc_category_reader.py',cycle_requests(today,history,cutoff,previous_analytics),600)
    except (OrderSourceBusy,RuntimeError,subprocess.TimeoutExpired,ValueError):extra={}
    fc_analytics=cycle_analysis(primary,extra,today,previous_analytics)
    profiles={};dashboard={};range_meta={}
    for key,name,gid,game,group in PROFILES:
        current=primary[key+':today'];supp=supplements[key+':today'];profiles[key]=profile_record(key,name,current,supp)
        profiles[key]['dimensions']=dimensions(current)
        rows=[]
        for r in primary[key+':history']['rows']:
            if len(r['date'])==10 and r['date']<today.isoformat():rows.append(r)
        hourly=[dict(ts=r['date'],orders=r['orders'],amount=r['amount']) for r in current['rows'] if len(r['date'])>10 and r['date']<=cutoff]
        # A day is represented by the primary page aggregate, not summed estimates.
        rows.append({'date':today.isoformat(),'orders':current['orders'],'amount':current['revenueUsd'],'partial':True})
        rows.sort(key=lambda r:r['date'])
        ranks={'category':[]}
        for chart in primary[key+':history']['charts']:
            if chart and '产品类型' in (chart.get('title') or []):
                for s in chart['series']:
                    for item in s.get('data') or []:
                        if isinstance(item,dict) and 'count' in item and 'value' in item:
                            ranks['category'].append({'name':item['name'],'orders':int(item['count']),'amount':float(item['value'])})
        dashboard[key]={'key':key,'name':name,'group':group,'subtitle':'所有网站 · 按支付时间 · '+('已完成' if group=='rpg' else '全部状态'),
            'collectedAt':current['capturedAt'],'filters':{'site':'','game':gid,'order_status':'3' if group=='rpg' else '',
            'order_status_label':'已完成' if group=='rpg' else '全部状态','primarySystem':'order.p2pah.cn'},
            'coverage':{'from':rows[0]['date'],'to':rows[-1]['date'],'days':len(rows)},'window':{'start':history,'end':cutoff,'days':90},
            'series':rows,'hourly':hourly,'ranks':ranks,'status':'ok','errors':[],
            'latestDay':{'date':today.isoformat(),'orders':current['orders'],'revenueUsd':current['revenueUsd'],'hasData':True},
            'source':{'primary':current,'supplement':supp},'newCustomersToday':supp.get('newCustomers'),
            'primaryMetrics':current.get('metrics',{}),'supplementMetrics':supp.get('metrics',{}),'supplementDimensions':supp.get('dimensions',{}),'supplementPeriod':supp.get('period')}
        # Strip redundant graphs/series from field-source metadata. Retain filter/date provenance.
        for source in [profiles[key]['primary'],dashboard[key]['source']['primary']]:
            source.pop('rows',None);source.pop('charts',None)
        range_meta[key]={'primaryHistory':{k:v for k,v in primary[key+':history'].items() if k not in ('rows','charts')},'today':current['period']}
    fc=fc_rows(primary,supplements,today,backfill)
    product_history=min((r['d'] for r in fc),default=history[:10])+' 00:00'
    wanted_products=product_requests(today,product_history,cutoff)
    try:product_results=call(None,'fc_product_reader.py',wanted_products,75)
    except (RuntimeError,subprocess.TimeoutExpired,ValueError):product_results={}
    fc_products=product_cycle(product_results,wanted_products,previous_products,previous_snapshot)
    profit_history=collect_profit_history(today,previous_data)
    return {'profitHistory':profit_history,'scopeApproved':True,'scopeContractId':'all-websites-order-primary-admin-supplement-v1',
            'scope':'all-websites','supplementContractVersion':1,'timezone':'Asia/Shanghai','currency':'USD','date':today.isoformat(),
            'requiredProfiles':[p[0] for p in PROFILES],'profiles':profiles,'dashboard':{
                'schemaVersion':1,'source':{'host':'order.p2pah.cn','ui':'订单统计主源；admin仅补缺字段','ttz':'Asia/Shanghai'},
                'groups':[{'key':'mmoexp','label':'所有网站合计','profiles':['MMOEXP']},
                {'key':'rpg','label':'RPG','profiles':[p[0] for p in PROFILES if p[4]=='rpg']},
                {'key':'sports','label':'球类 · 全部状态','profiles':[p[0] for p in PROFILES if p[4]=='sports']},
                {'key':'general','label':'综合游戏 · 全部状态','profiles':[p[0] for p in PROFILES if p[4]=='general']}],
                'profiles':dashboard,'failedProfiles':[]},'rangeMeta':range_meta,'fcOps':{'schema':3,'source_system':'order-primary-admin-supplement',
                'site':'all','rows':fc,'historicalCustomerCoverage':sorted(days)},
            'fieldAvailability':{'game':{'status':'available','mapping':'two-system IDs'},'productType':{'status':'available','source':'order tid/category'},
                'channel':{'status':'amount-only','source':'order 来源图','note':'no verified per-channel order counts'},
                'country':{'status':'available','source':'admin country_rank'},'coupon':{'status':'unavailable'},'payment':{'status':'available','source':'admin chart_pay_style'},
                'device':{'status':'available','source':'admin chart_pay_device'},'profitMargin':{'status':'available','source':'order 利润率','unit':'percent','definition':'Upstream margin; gross/net formula unspecified'},
                'currency':{'status':'available','value':'USD'},'status':{'status':'available','source':'order 状态图/filter'}},
            'fc27Analytics':fc_analytics,'fc27ProductRankings':fc_products,'noCustomerConversionRate':True}

def fc_rows(primary,supplements,today,backfill=None):
    maps={k:{r['date']:r for r in v['rows'] if len(r['date'])==10} for k,v in primary.items() if k.startswith(('FC27:','FC26-prior:')) and 'rows' in v}
    if backfill:
        target=date.fromisoformat(backfill)
        for suffix,d,group in [('now',target,'FC27'),('prior',target.replace(year=target.year-1),'FC26-prior')]:
            for kind in ['all','coins','items']:
                record=primary['backfill:'+suffix+':'+kind]
                maps[group+':'+kind][d.isoformat()]={'date':d.isoformat(),'orders':record['orders'],'amount':record['revenueUsd']}
    # Preserve previous verified primary history beyond the rolling window. Each historical
    # row retains its own publication date/source; never merge legacy site266 rows as all-sites.
    previous=[]
    try:
        m=json.loads((WEB/'current.json').read_text());previous=json.loads((WEB/m['path']).read_text())['fcOps']['rows']
    except (OSError,KeyError,ValueError):pass
    rows=[]
    for day,r in sorted(maps['FC27:all'].items()):
        if day>=today.isoformat():continue
        prior=date.fromisoformat(day).replace(year=int(day[:4])-1).isoformat()
        row={'d':day,'yoy':{},'newU':supplements.get('fc-customer:'+day+':now',{}).get('newCustomers'),
             'source_schema':3,'source_system':'order-primary-admin-supplement','site':'all','sales_metric':'order_amount',
             'sources':{'ordersAndSales':'order.p2pah.cn','newCustomers':'admin.p2pah.cn','normalisedScope':'all-websites'}}
        for label,kind,metric in [('orders','all','orders'),('sales','all','amount'),('coinO','coins','orders'),('coinS','coins','amount'),('cardO','items','orders'),('cardS','items','amount')]:
            current=maps['FC27:'+kind].get(day,{}).get(metric)
            baseline=maps['FC26-prior:'+kind].get(prior,{}).get(metric)
            row[label]=current
            row['yoy'][label]=round((current/baseline-1)*100,2) if current is not None and baseline else None
        prior_new=supplements.get('fc-customer:'+day+':prior',{}).get('newCustomers')
        row['yoy']['newU']=round((row['newU']/prior_new-1)*100,2) if row['newU'] is not None and prior_new else None
        rows.append(row)
    merged={r['d']:r for r in previous if r.get('source_schema')==3 and r.get('site')=='all'}
    for r in rows:
        r['publishedAt']=datetime.now(timezone.utc).isoformat();merged[r['d']]=r
    return [merged[d] for d in sorted(merged)]

if __name__=='__main__':
    backfill=sys.argv[2] if len(sys.argv)==3 and sys.argv[1]=='--backfill' else None
    manifest=run_once(WEB,lambda:collect(backfill),lock_name="transaction-snapshot.lock")
    print(json.dumps({'status':'success' if 'snapshotId' in manifest else manifest.get('status'),'snapshotId':manifest.get('snapshotId')}),flush=True)
