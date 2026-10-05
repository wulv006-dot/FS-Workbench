"""Reduce stored detail reports to a credential-free, audited dashboard contract."""
import argparse, datetime as dt, json, re, sqlite3
from decimal import Decimal
from pathlib import Path

CUSTOMERS={'1430398974':{'brand':'mmoexp','label':'MMOEXP-1'},'8154986819':{'brand':'rsorder','label':'RSOrder-1'},'3552474396':{'brand':'rsorder','label':'rsgoldfast.com · RSOrder业务'}}
QUERY_RULES={'version':'mmoexp-query-v1','precedence':['brand','transaction','content','other'],'brand':r'\bmmo\s*exp\b|mmoexp','transaction':r'\b(buy|buying|sale|cheap|price|gold|coins?|currency|gil|gp|accounts?|boost|boosting)\b','content':r'\b(how|guide|guides|best|build|builds|quest|quests|news|wiki|tips|tutorial|leveling)\b','unmatched':'other','anonymous_or_unreturned_queries':'not_inferred'}
MARKETS=[('usa','美国'),('gbr','英国'),(None,'未知国家'),('deu','德国'),('aus','澳大利亚')]

def ratio(n,d):
    if n is None or d is None or Decimal(str(d))<=0:return None
    return str(Decimal(str(n))/Decimal(str(d)))
def query_category(query):
    for category in ['brand','transaction','content']:
        if re.search(QUERY_RULES[category],query,re.I):return category
    return 'other'
def date_coverage(report,start,end):
    dates=sorted({r['dimensions']['date'] for r in (report or {}).get('rows',[]) if 'date' in r['dimensions']})
    requested=[(dt.date.fromisoformat(start)+dt.timedelta(days=i)).isoformat() for i in range((dt.date.fromisoformat(end)-dt.date.fromisoformat(start)).days+1)]
    return {'requested_start':start,'requested_end':end,'returned_dates':dates,'latest_data_date':max(dates,default=None),'returned_days':len(dates),'requested_days':len(requested),'missing_dates':[d for d in requested if d not in dates],'complete_dates':dates==requested}
def ads_sum(rows):
    if not rows:return None
    result={n:str(sum((Decimal(r['metrics'][n]) for r in rows),Decimal(0))) for n in ['impressions','clicks','costMicros','conversions','conversionsValue']}
    result['cost']=str(Decimal(result.pop('costMicros'))/Decimal(1000000))
    result.update(cpc=ratio(result['cost'],result['clicks']),cpa=ratio(result['cost'],result['conversions']),platformRoas=ratio(result['conversionsValue'],result['cost']))
    return result
def ads_coverage(report,start,end):
    value=date_coverage(report,start,end)
    complete=bool(report and report.get('start_date')==start and report.get('end_date')==end and report.get('quality',{}).get('pagination_complete'))
    value['query_range_complete']=complete
    value['no_metric_row_dates']=value['missing_dates'] if complete else []
    if complete:value['missing_dates']=[]
    value['zero_metric_rows_omitted_by_api']=True
    value['zero_rows_materialized']=False
    return value
def gsc_sum(rows):
    if not rows:return None
    clicks=sum((Decimal(r['metrics']['clicks']) for r in rows),Decimal(0)); impressions=sum((Decimal(r['metrics']['impressions']) for r in rows),Decimal(0))
    pos=sum((Decimal(r['metrics']['position'])*Decimal(r['metrics']['impressions']) for r in rows),Decimal(0))
    return {'clicks':str(clicks),'impressions':str(impressions),'ctr':ratio(clicks,impressions),'position':ratio(pos,impressions)}
def metric_change(current,previous,complete):
    if not complete or not current or not previous:return {}
    result={}
    for metric in current.keys() & previous.keys():
        if current[metric] is None or previous[metric] is None:continue
        a,b=Decimal(str(current[metric])),Decimal(str(previous[metric]))
        if metric in ['ctr','bounceRate','engagementRate']:result[metric]={'kind':'percentage_points','value':str((a-b)*100)}
        elif b>0:result[metric]={'kind':'relative_percent','value':str((a-b)/b*100)}
    return result
def report_status(report):
    if not report:return {'status':'not_collected','retained_previous':False}
    attempt=report.get('last_attempt',{})
    return {'status':attempt.get('status','success'),'retained_previous':attempt.get('status') in ['failed','empty'],'collected_at':report.get('collected_at'),'last_attempt_at':attempt.get('checked_at'),'quality':report.get('quality',{})}
def sorted_rows(report,metric):
    return sorted((report or {}).get('rows',[]),key=lambda r:Decimal(r['metrics'].get(metric,'0')),reverse=True)
def top_table(report,metric,limit,total):
    allrows=sorted_rows(report,metric)
    shown=[]
    for row in allrows[:limit]:
        shown.append({'dimensions':row['dimensions'],'metrics':dict(row['metrics'],share=ratio(row['metrics'].get(metric),total))})
    amount=str(sum((Decimal(r['metrics'].get(metric,0)) for r in allrows),Decimal(0))) if allrows else None
    return {'rows':shown,'returned_dimension_rows':len(allrows),'displayed_rows':len(shown),'row_coverage':ratio(amount,total),'coverage_metric':metric,'status':report_status(report)}

def make_period(start,end,reports):
    def get(source,resource,name):return reports.get((source,resource,name))
    period={'id':start+'_'+end,'start':start,'end':end,'sources':{},'adsAccounts':[],'query_rules':QUERY_RULES}
    ga_total=get('ga4','541418940','total'); ga_daily=get('ga4','541418940','daily')
    ga_values=ga_total['rows'][0]['metrics'] if ga_total and len(ga_total['rows'])==1 else None
    ga={'resource':'541418940','brand':'mmoexp','timezone':'Asia/Shanghai','currency':'USD','metrics':ga_values,'daily':(ga_daily or {}).get('rows',[]),'coverage':date_coverage(ga_daily,start,end),'status':report_status(ga_total),'breakdowns':{},'revenue_financial_source':False,'new_users_definition':'首次触发first_visit/first_open的用户；不代表后台首购客户'}
    for name,limit in [('source_medium',15),('device',20),('country',10),('landing_page',15)]:ga['breakdowns'][name]=top_table(get('ga4','541418940',name),'sessions',limit,(ga_values or {}).get('sessions'))
    period['sources']['ga4']=ga
    total=get('gsc','sc-domain:mmoexp.com','total'); daily=get('gsc','sc-domain:mmoexp.com','daily')
    values=total['rows'][0]['metrics'] if total and len(total['rows'])==1 else None
    gsc={'resource':'sc-domain:mmoexp.com','brand':'mmoexp','timezone':'America/Los_Angeles','metrics':values,'daily':(daily or {}).get('rows',[]),'coverage':date_coverage(daily,start,end),'status':report_status(total),'breakdowns':{},'markets':[],'query_rows_are_exhaustive':False}
    for name,limit in [('query',20),('page',15),('country',10)]:
        denominator=(values or {}).get('clicks')
        if name=='page':
            page_total=get('gsc','sc-domain:mmoexp.com','page_total')
            denominator=page_total['rows'][0]['metrics']['clicks'] if page_total and len(page_total['rows'])==1 else None
        gsc['breakdowns'][name]=top_table(get('gsc','sc-domain:mmoexp.com',name),'clicks',limit,denominator)
        gsc['breakdowns'][name]['coverage_basis']='byPage_total' if name=='page' else 'byProperty_total'
    countries={r['dimensions']['country']:r['metrics'] for r in (get('gsc','sc-domain:mmoexp.com','country') or {}).get('rows',[])}
    cq=get('gsc','sc-domain:mmoexp.com','country_query'); queryrows=(cq or {}).get('rows',[])
    unknown=[key for key in countries if key.lower() in ['','unknown','(unknown)','(not set)','xxx']]
    for code,label in MARKETS:
        codes=[code] if code else unknown
        rows=[r for r in queryrows if r['dimensions']['country'] in codes]
        denominators=[{'dimensions':{},'metrics':countries[key]} for key in codes if key in countries]
        countrytotal=gsc_sum(denominators)
        market={'country_codes':codes,'label':label,'available':bool(rows),'country_total':countrytotal,'query_row_coverage':ratio((gsc_sum(rows) or {}).get('clicks'),(countrytotal or {}).get('clicks')),'categories':[],'top_queries':sorted(rows,key=lambda r:Decimal(r['metrics']['clicks']),reverse=True)[:15],'status':report_status(cq)}
        for category in ['brand','transaction','content','other']:
            matches=[r for r in rows if query_category(r['dimensions']['query'])==category]
            m=gsc_sum(matches)
            if m:m.update(impressionShare=ratio(m['impressions'],(countrytotal or {}).get('impressions')))
            market['categories'].append({'category':category,'returned_query_rows':len(matches),'metrics':m})
        gsc['markets'].append(market)
    period['sources']['gsc']=gsc
    for customer,settings in CUSTOMERS.items():
        daily=get('ads',customer,'daily'); campaign=get('ads',customer,'campaign')
        rows=(daily or {}).get('rows',[]); metrics=ads_sum(rows)
        groups={}
        for row in (campaign or {}).get('rows',[]):
            dims=row['dimensions']; key=(customer,dims['campaignId'])
            groups.setdefault(key,[]).append(row)
        campaigns=[]
        for key,items in groups.items():
            campaigns.append({'customerId':key[0],'campaignId':key[1],'campaignName':items[-1]['dimensions']['campaignName'],'channelType':items[-1]['dimensions'].get('channelType'),'currency':'USD','timezone':'Asia/Hong_Kong','metrics':ads_sum(items),'dates':sorted({r['dimensions']['date'] for r in items})})
        campaigns.sort(key=lambda r:Decimal(r['metrics']['cost']),reverse=True)
        period['adsAccounts'].append({'customerId':customer,**settings,'observed_name':(daily or {}).get('account',{}).get('descriptiveName'),'timezone':'Asia/Hong_Kong','currency':'USD','metrics':metrics,'daily':rows,'coverage':ads_coverage(daily,start,end),'status':report_status(daily),'campaigns':campaigns[:12],'campaign_count':len(campaigns),'campaign_row_cost_coverage':ratio(str(sum((Decimal(r['metrics']['cost']) for r in campaigns),Decimal(0))), (metrics or {}).get('cost')),'campaign_status':report_status(campaign),'platform_attributed_metrics_not_financial_revenue':True})
    return period

def build(db):
    ends=[r[0] for r in db.execute('SELECT DISTINCT end_date FROM detail_reports ORDER BY end_date DESC LIMIT 8')]
    output=[]
    for end in ends:
        start=(dt.date.fromisoformat(end)-dt.timedelta(days=6)).isoformat(); reports={}
        for source,resource,name,payload in db.execute('SELECT source,resource,report,payload_json FROM detail_reports WHERE start_date=? AND end_date=?',(start,end)):
            if (source=='ads' and resource not in CUSTOMERS) or (source=='ga4' and resource!='541418940') or (source=='gsc' and resource!='sc-domain:mmoexp.com'):raise ValueError('UNREVIEWED_DETAIL_SCOPE')
            value=json.loads(payload)
            seen=set()
            for row in value['rows']:
                key=json.dumps(row['dimensions'],sort_keys=True)
                if key in seen:raise ValueError('DUPLICATE_REPORT_DIMENSIONS')
                seen.add(key)
                for v in row['metrics'].values():
                    if not Decimal(str(v)).is_finite():raise ValueError('INVALID_NUMBER')
            attempt=db.execute('SELECT checked_at,status,error_code FROM detail_attempts WHERE source=? AND resource=? AND report=? AND start_date=? AND end_date=? ORDER BY id DESC LIMIT 1',(source,resource,name,start,end)).fetchone()
            if attempt:value['last_attempt']=dict(zip(['checked_at','status','error_code'],attempt))
            reports[(source,resource,name)]=value
        output.append(make_period(start,end,reports))
    by_end={v['end']:v for v in output}
    for current in output:
        previous=by_end.get((dt.date.fromisoformat(current['end'])-dt.timedelta(days=7)).isoformat())
        current['comparison_period']=previous['id'] if previous else None
        for source,values in current['sources'].items():
            before=previous['sources'][source] if previous else None
            complete=values['coverage']['complete_dates'] and before and before['coverage']['complete_dates']
            for report in [values,before or {}]:
                quality=report.get('status',{}).get('quality',{})
                if any(quality.get(k) for k in ['subject_to_thresholding','sampling_present','data_loss_from_other_row','pagination_capped','active_metric_restrictions']):complete=False
            values['changes']=metric_change(values['metrics'],before['metrics'] if before else None,complete)
            values['comparison_status']='complete_source_dates' if complete else 'insufficient_dates'
        for account in current['adsAccounts']:
            before=next((v for v in previous['adsAccounts'] if v['customerId']==account['customerId']),None) if previous else None
            complete=account['coverage']['query_range_complete'] and before and before['coverage']['query_range_complete']
            account['changes']=metric_change(account['metrics'],before['metrics'] if before else None,complete)
            account['comparison_status']='complete_query_ranges' if complete else 'incomplete_query_range'
    return {'schemaVersion':1,'isMock':False,'periods':output,'allowed_customers':list(CUSTOMERS),'account_dedup_key':['customerId','campaignId','date'],'brand_evidence':'用户明确rsgoldfast.com属于RSOrder业务；不同customerID单独列示','cross_source_conversion_rates':None,'financial_revenue_source':'order.p2pah_all_sites_versioned_snapshot','business_contract':{'schemaVersion':2,'scope':'all-websites','scopeContractId':'all-websites-order-primary-admin-supplement-v1','server_manifest':'/var/www/dashboard/fs-home/transactions/current.json','join_performed':False},'phase2_gaps':[
        {'module':'订单/游戏/类型/渠道/国家/新老客','status':'aggregate_source_available_dimensions_pending','reason':'统一全网站订单快照已上线：主源order.p2pah，admin仅补新客；首版细分dimensions尚未填充，未用单站GA4替代'},
        {'module':'KOL/折扣码','status':'not_connected','reason':'待交易主源渠道、折扣码、已付/已交付GMV、新客定义；粉丝/播放/点赞/佣金/花名册未接入'},
        {'module':'跨源漏斗','status':'unmatched','reason':'未取得同站、同日期、渠道/游戏/国家映射及订单归因键；购物车埋点未验证'},
        {'module':'RSOrder GA4/GSC','status':'not_connected','reason':'现有property仅验证MMOEXP，未假定rsgoldfast/RSOrder共用其流量'}]}

def main():
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    db=sqlite3.connect('file:'+str(a.database)+'?mode=ro',uri=True)
    try:value=build(db)
    finally:db.close()
    tmp=a.output.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(a.output)
    print(json.dumps({'periods':len(value['periods']),'scope':value['allowed_customers'],'mock':False}))
if __name__=='__main__':main()
