"""Server-only bounded, read-only weekly detail reports. No credential creation/export."""
import argparse, datetime as dt, hashlib, json, os, re, sqlite3, stat, sys, time
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

ROOT = Path('/opt/mmoexp-marketing')
CUSTOMERS = {'1430398974': ('mmoexp', 'MMOEXP-1'), '8154986819': ('rsorder', 'RSOrder-1'), '3552474396': ('rsorder', 'rsgoldfast.com')}
GA_METRICS = ['sessions','activeUsers','newUsers','engagedSessions','engagementRate','screenPageViews','averageSessionDuration','bounceRate','ecommercePurchases','purchaseRevenue']
GA_REPORTS = {'total': [], 'daily': ['date'], 'source_medium': ['sessionSourceMedium'], 'device': ['deviceCategory'], 'country': ['country'], 'landing_page': ['landingPage']}
GSC_REPORTS = {'total': [], 'daily': ['date'], 'query': ['query'], 'page': ['page'], 'page_total': [], 'country': ['country'], 'country_query': ['country','query']}
SCHEMA = '''CREATE TABLE IF NOT EXISTS detail_reports(source TEXT, resource TEXT, report TEXT, start_date TEXT, end_date TEXT, payload_json TEXT, collected_at TEXT, PRIMARY KEY(source,resource,report,start_date,end_date));
CREATE TABLE IF NOT EXISTS detail_attempts(id INTEGER PRIMARY KEY, source TEXT, resource TEXT, report TEXT, start_date TEXT, end_date TEXT, checked_at TEXT, status TEXT, error_code TEXT);
'''

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def number(value):
    value = Decimal(str(value))
    if not value.is_finite() or abs(value) > Decimal('1e20'): raise ValueError('INVALID_NUMBER')
    return str(value)
def period(end):
    end = dt.date.fromisoformat(end)
    if end.weekday() != 6: raise ValueError('SUNDAY_REQUIRED')
    return [(end-dt.timedelta(days=6)).isoformat(),end.isoformat()]
def periods(end=None):
    today = dt.datetime.now(ZoneInfo('Asia/Shanghai')).date()
    end = dt.date.fromisoformat(end) if end else today-dt.timedelta(days=today.weekday()+1)
    if end >= today or (today-end).days > 90: raise ValueError('BOUNDED_PAST_PERIOD_REQUIRED')
    return [period(end.isoformat()),period((end-dt.timedelta(days=7)).isoformat())]

def report_periods(end=None):
    """Explicit rollout switch; the existing nightly caller keeps its old ranges."""
    ranges=periods(end)
    today=dt.datetime.now(ZoneInfo('Asia/Shanghai')).date();yesterday=today-dt.timedelta(days=1)
    ranges.extend([(yesterday.isoformat(),yesterday.isoformat()),((yesterday-dt.timedelta(days=1)).isoformat(),(yesterday-dt.timedelta(days=1)).isoformat()),((yesterday-dt.timedelta(days=7)).isoformat(),(yesterday-dt.timedelta(days=7)).isoformat())])
    if today.day==1:
        month_end=today-dt.timedelta(days=1);month_start=month_end.replace(day=1);previous_end=month_start-dt.timedelta(days=1)
        ranges.extend([(month_start.isoformat(),month_end.isoformat()),(previous_end.replace(day=1).isoformat(),previous_end.isoformat())])
    return list(dict.fromkeys(tuple(r) for r in ranges))

def credential(kind):
    from google.auth.transport.requests import AuthorizedSession
    path = Path('/etc/mmoexp-marketing/'+('oauth-adc.json' if kind=='ads' else 'service-account.json'))
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600 or info.st_uid!=0: raise ValueError('CONTROLLED_CREDENTIAL_REQUIRED')
    metadata=json.loads(path.read_text())
    if kind=='ads':
        if metadata.get('type')!='authorized_user' or metadata.get('client_id')!='839381870611-2bi8vqjv2c979kmcv76a09d7lvgdm4nt.apps.googleusercontent.com': raise ValueError('OAUTH_IDENTITY_REQUIRED')
        from google.oauth2.credentials import Credentials
        creds=Credentials.from_authorized_user_file(str(path),scopes=['https://www.googleapis.com/auth/adwords'])
    else:
        if metadata.get('type')!='service_account' or metadata.get('project_id')!='ecommerce-495601': raise ValueError('SERVICE_ACCOUNT_IDENTITY_REQUIRED')
        from google.oauth2.service_account import Credentials
        scope='analytics.readonly' if kind=='ga4' else 'webmasters.readonly'
        creds=Credentials.from_service_account_file(str(path),scopes=['https://www.googleapis.com/auth/'+scope])
    metadata=None
    return AuthorizedSession(creds)

class Reader:
    def __init__(self): self.calls=0; self.sessions={}; self.ga_compatibility={}; self.metadata={}; self.quota={}
    def close(self):
        for session in self.sessions.values(): session.close()
    def request(self,source,url,body=None):
        if source not in self.sessions: self.sessions[source]=credential(source)
        headers={'login-customer-id':'6039826478'} if source=='ads' else None
        for attempt in range(3):
            self.calls+=1
            if self.calls>160: raise ValueError('RUN_REQUEST_BUDGET_EXCEEDED')
            response=self.sessions[source].request('GET' if body is None else 'POST',url,json=body,headers=headers,timeout=45)
            if response.status_code in [429,500,502,503,504] and attempt<2:
                time.sleep(2**attempt); continue
            if response.status_code!=200: raise ValueError('HTTP_'+str(response.status_code))
            result=response.json()
            if not isinstance(result,dict): raise ValueError('INVALID_REPORT_RESPONSE')
            return result
    def ga_fields(self):
        base='https://analyticsdata.googleapis.com/v1beta/properties/541418940'
        data=self.request('ga4',base+'/metadata')
        dims={v['apiName'] for v in data.get('dimensions',[])}; metrics={v['apiName'] for v in data.get('metrics',[])}
        required={v for vals in GA_REPORTS.values() for v in vals}
        self.metadata['ga4']={'required_dimensions_available':sorted(required & dims),'missing_dimensions':sorted(required-dims),'required_metrics_available':sorted(set(GA_METRICS)&metrics),'missing_metrics':sorted(set(GA_METRICS)-metrics),'game_custom_dimensions':[n for n in sorted(dims) if n.startswith('custom') and re.search(r'game|product|item|type',n,re.I)]}
        for name,dimensions in GA_REPORTS.items():
            requested=GA_METRICS if name in ['total','daily'] else ['sessions','activeUsers','bounceRate']
            data=self.request('ga4',base+':checkCompatibility',{'dimensions':[{'name':n} for n in dimensions],'metrics':[{'name':n} for n in requested]})
            dc={v['dimensionMetadata']['apiName']:v['compatibility'] for v in data.get('dimensionCompatibilities',[])}
            mc={v['metricMetadata']['apiName']:v['compatibility'] for v in data.get('metricCompatibilities',[])}
            self.ga_compatibility[name]=all(dc.get(n)=='COMPATIBLE' for n in dimensions) and all(mc.get(n)=='COMPATIBLE' for n in requested)
        self.metadata['ga4']['compatibility']=self.ga_compatibility
    def ga(self,name,start,end):
        if not self.ga_compatibility.get(name): raise ValueError('GA4_FIELDS_INCOMPATIBLE')
        dimensions=GA_REPORTS[name]; metrics=GA_METRICS if name in ['total','daily'] else ['sessions','activeUsers','bounceRate']
        body={'dateRanges':[{'startDate':start,'endDate':end}],'dimensions':[{'name':n} for n in dimensions],'metrics':[{'name':n} for n in metrics],'limit':10000,'returnPropertyQuota':True}
        if name not in ['total','daily']: body['orderBys']=[{'metric':{'metricName':'sessions'},'desc':True}]
        rows=[]; quality={}; total=None
        while True:
            body['offset']=len(rows)
            data=self.request('ga4','https://analyticsdata.googleapis.com/v1beta/properties/541418940:runReport',body)
            meta=data.get('metadata',{})
            if meta.get('timeZone')!='Asia/Shanghai' or meta.get('currencyCode')!='USD': raise ValueError('GA4_METADATA_MISMATCH')
            if [v['name'] for v in data.get('dimensionHeaders',[])]!=dimensions or [v['name'] for v in data.get('metricHeaders',[])]!=metrics: raise ValueError('GA4_HEADERS_MISMATCH')
            if total is not None and total!=data.get('rowCount',0): raise ValueError('GA4_REPORT_CHANGED_DURING_PAGINATION')
            total=data.get('rowCount',0)
            self.quota=data.get('propertyQuota',self.quota)
            quality={'subject_to_thresholding':bool(meta.get('subjectToThresholding')),'sampling_present':bool(meta.get('samplingMetadatas')),'data_loss_from_other_row':bool(meta.get('dataLossFromOtherRow')),'active_metric_restrictions':meta.get('schemaRestrictionResponse',{}).get('activeMetricRestrictions',[]),'data_state':'provisional'}
            for row in data.get('rows',[]):
                d={n:v['value'] for n,v in zip(dimensions,row.get('dimensionValues',[]))}
                if 'date' in d:
                    date=dt.datetime.strptime(d['date'],'%Y%m%d').date().isoformat()
                    if not start<=date<=end: raise ValueError('REPORT_DATE_MISMATCH')
                    d['date']=date
                rows.append({'dimensions':d,'metrics':{n:number(v['value']) for n,v in zip(metrics,row['metricValues'])}})
            if len(rows)>=total: break
            if not data.get('rows') or len(rows)>=50000: quality['pagination_capped']=True; break
        return {'rows':rows,'quality':dict(quality,api_row_count=total,returned_rows=len(rows),pagination_complete=len(rows)==total),'timezone':'Asia/Shanghai','currency':'USD'}
    def gsc(self,name,start,end):
        dimensions=GSC_REPORTS[name]; rows=[]; page_size=25000; complete=False
        body={'startDate':start,'endDate':end,'dimensions':dimensions,'type':'web','dataState':'final','rowLimit':page_size}
        if name=='page_total':body['aggregationType']='byPage'
        elif name not in ['page']: body['aggregationType']='byProperty'
        while len(rows)<50000:
            body['startRow']=len(rows)
            data=self.request('gsc','https://www.googleapis.com/webmasters/v3/sites/'+quote('sc-domain:mmoexp.com',safe='')+'/searchAnalytics/query',body)
            page=data.get('rows',[])
            for row in page:
                dims=dict(zip(dimensions,row.get('keys',[])))
                if len(dims)!=len(dimensions): raise ValueError('GSC_DIMENSION_MISMATCH')
                if 'date' in dims and not start<=dims['date']<=end: raise ValueError('REPORT_DATE_MISMATCH')
                rows.append({'dimensions':dims,'metrics':{n:number(row[n]) for n in ['clicks','impressions','ctr','position']}})
            if len(page)<page_size: complete=True; break
        redacted=0
        if name=='page':
            merged={}
            for row in rows:
                url=row['dimensions']['page']; parts=urlsplit(url); clean=urlunsplit((parts.scheme,parts.netloc,parts.path,'',''))
                redacted+=int(clean!=url); key=clean; values=row['metrics']; state=merged.setdefault(key,{'clicks':Decimal(0),'impressions':Decimal(0),'position_sum':Decimal(0)})
                state['clicks']+=Decimal(values['clicks']); state['impressions']+=Decimal(values['impressions']); state['position_sum']+=Decimal(values['position'])*Decimal(values['impressions'])
            rows=[{'dimensions':{'page':key},'metrics':{'clicks':str(v['clicks']),'impressions':str(v['impressions']),'ctr':str(v['clicks']/v['impressions']) if v['impressions'] else '0','position':str(v['position_sum']/v['impressions']) if v['impressions'] else '0'}} for key,v in merged.items()]
        return {'rows':rows,'quality':{'pagination_complete':complete,'pagination_capped':not complete,'returned_rows':len(rows),'data_state':'final','top_rows_not_all_queries':name in ['query','page','country_query'],'url_query_fragments_removed':redacted,'aggregation':data.get('responseAggregationType')},'timezone':'America/Los_Angeles','currency':None}
    def ads_metadata(self,customer):
        if customer not in CUSTOMERS: raise ValueError('SELECTED_CUSTOMER_REQUIRED')
        data=self.request('ads','https://googleads.googleapis.com/v25/customers/'+customer+'/googleAds:search',{'query':'SELECT customer.id, customer.descriptive_name, customer.manager, customer.status, customer.currency_code, customer.time_zone FROM customer'})
        rows=data.get('results',[])
        if len(rows)!=1 or data.get('nextPageToken'): raise ValueError('ADS_METADATA_INCOMPLETE')
        meta=rows[0]['customer']
        if str(meta['id'])!=customer or meta.get('manager') or meta.get('currencyCode')!='USD' or meta.get('timeZone')!='Asia/Hong_Kong': raise ValueError('ADS_METADATA_MISMATCH')
        self.metadata[customer]={n:meta.get(n) for n in ['id','descriptiveName','status','currencyCode','timeZone']}
    def ads(self,customer,name,start,end):
        if self.metadata.get(customer,{}).get('id')!=customer: raise ValueError('ADS_METADATA_REQUIRED')
        fields='segments.date, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.conversions_value, metrics.interactions, metrics.conversions_from_interactions_rate, metrics.conversions_value_per_cost'
        if name in ('campaign','campaign_total','ad_group_total'): fields='campaign.id, campaign.name, campaign.advertising_channel_type, '+fields
        if name == 'ad_group_total': fields='ad_group.id, ad_group.name, ad_group.status, '+fields.replace(', metrics.conversions_value_per_cost','')
        if name in ('total','campaign_total','ad_group_total'): fields=fields.replace('segments.date, ', '')
        table='ad_group' if name == 'ad_group_total' else 'campaign' if name in ('campaign','campaign_total') else 'customer'
        body={'query':"SELECT "+fields+" FROM "+table+" WHERE segments.date BETWEEN '"+start+"' AND '"+end+"' "+(" ORDER BY segments.date" if name not in ('total','campaign_total','ad_group_total') else "")}; rows=[]; seen=set(); complete=False
        for page in range(10):
            data=self.request('ads','https://googleads.googleapis.com/v25/customers/'+customer+'/googleAds:search',body)
            for row in data.get('results',[]):
                date=row['segments']['date'] if name not in ('total','campaign_total','ad_group_total') else start
                if not start<=date<=end: raise ValueError('REPORT_DATE_MISMATCH')
                dims={'customerId':customer}
                if name not in ('total','campaign_total','ad_group_total'):dims['date']=date
                if name in ('campaign','campaign_total','ad_group_total'): dims.update(campaignId=str(row['campaign']['id']),campaignName=row['campaign'].get('name',''),channelType=row['campaign'].get('advertisingChannelType',''))
                if name == 'ad_group_total':
                    if dims.get('channelType') == 'PERFORMANCE_MAX': raise ValueError('PMAX_AD_GROUP_UNEXPECTED')
                    dims.update(adGroupId=str(row['adGroup']['id']),adGroupName=row['adGroup'].get('name',''),adGroupStatus=row['adGroup'].get('status'))
                key=(date,dims.get('campaignId'),dims.get('adGroupId'))
                if key in seen: raise ValueError('DUPLICATE_ADS_DATE_ID')
                seen.add(key)
                metrics={n:number(row.get('metrics',{}).get(n,0)) for n in ['impressions','clicks','costMicros','conversions','conversionsValue']}
                for n in ('interactions','conversionsFromInteractionsRate','conversionsValuePerCost'):
                    metrics[n]=number(row['metrics'][n]) if n in row.get('metrics',{}) else None
                rows.append({'dimensions':dims,'metrics':metrics})
            if not data.get('nextPageToken'): complete=True; break
            body['pageToken']=data['nextPageToken']
        if not complete: raise ValueError('ADS_PAGINATION_BUDGET_EXCEEDED')
        return {'rows':rows,'quality':{'pagination_complete':True,'returned_rows':len(rows),'data_state':'provisional_ads_attribution','conversion_scope':'primary_conversions','attribution_time_basis':'interaction_date','conversion_goals_status':'not_collected','platform_roas_basis':'sum_conversionsValue / (sum_costMicros / 1000000); derived, not native ratio'},'timezone':'Asia/Hong_Kong','currency':'USD','account':self.metadata[customer]}

def save(db,source,resource,name,start,end,value=None,error=None):
    timestamp=now(); status='failed' if error else 'success' if value and value['rows'] else 'empty'
    with db:
        db.execute('INSERT INTO detail_attempts(source,resource,report,start_date,end_date,checked_at,status,error_code) VALUES(?,?,?,?,?,?,?,?)',(source,resource,name,start,end,timestamp,status,error))
        if status=='success':
            value.update(source=source,resource=resource,report=name,start_date=start,end_date=end,collected_at=timestamp)
            db.execute('INSERT OR REPLACE INTO detail_reports VALUES(?,?,?,?,?,?,?)',(source,resource,name,start,end,json.dumps(value,ensure_ascii=False),timestamp))
    return {'source':source,'resource':resource,'report':name,'start':start,'end':end,'status':status,'rows':len(value['rows']) if value else None,'error_code':error}

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--week-end'); parser.add_argument('--parent-lock-held',action='store_true'); parser.add_argument('--retry-failed-only',action='store_true'); parser.add_argument('--report-periods',action='store_true'); args=parser.parse_args()
    os.umask(0o077)
    if os.getenv('MMOEXP_MARKETING_LIVE')!='approved': raise SystemExit('LIVE_DISABLED')
    lock=None
    if not args.parent_lock_held:
        import fcntl
        lock=(ROOT/'data/verified-readonly/collector.lock').open('a')
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: print('{"status":"skipped_existing_collection"}');return
    ranges=report_periods(args.week_end) if args.report_periods else periods(args.week_end); db=sqlite3.connect(ROOT/'data/verified-readonly/marketing.db'); db.executescript(SCHEMA)
    reader=Reader(); results=[]; started=now()
    try:
        try: reader.ga_fields()
        except Exception as exc: reader.metadata['ga4']={'status':'metadata_failed','exception_class':type(exc).__name__}
        for customer in CUSTOMERS:
            try: reader.ads_metadata(customer)
            except Exception as exc: reader.metadata[customer]={'status':'metadata_failed','exception_class':type(exc).__name__}
        for start,end in ranges:
            specs=[('ga4','541418940',n) for n in GA_REPORTS]+[('gsc','sc-domain:mmoexp.com',n) for n in GSC_REPORTS]+[('ads',c,n) for c in CUSTOMERS for n in ['total','daily','campaign','campaign_total','ad_group_total']]
            for source,resource,name in specs:
                try:
                    old=db.execute('SELECT collected_at FROM detail_reports WHERE source=? AND resource=? AND report=? AND start_date=? AND end_date=?',(source,resource,name,start,end)).fetchone()
                    if args.retry_failed_only and old:
                        results.append({'source':source,'resource':resource,'report':name,'start':start,'end':end,'status':'reused_existing_report'});continue
                    if old and dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(old[0])<dt.timedelta(minutes=45):
                        results.append({'source':source,'resource':resource,'report':name,'start':start,'end':end,'status':'reused_recent_report'});continue
                    # Final GSC tables are expensive; successful tables are reused for a week.
                    if source=='gsc' and old and dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(old[0])<dt.timedelta(days=7):
                        daily=db.execute("SELECT payload_json FROM detail_reports WHERE source='gsc' AND resource=? AND report='daily' AND start_date=? AND end_date=?",(resource,start,end)).fetchone()
                        if daily and len(json.loads(daily[0])['rows'])==7:
                            results.append({'source':source,'resource':resource,'report':name,'start':start,'end':end,'status':'reused_final_complete_week'});continue
                    value=reader.ga(name,start,end) if source=='ga4' else reader.gsc(name,start,end) if source=='gsc' else reader.ads(resource,name,start,end)
                    results.append(save(db,source,resource,name,start,end,value))
                except Exception as exc:
                    code=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'[A-Z0-9_]{1,100}',str(exc)) else type(exc).__name__
                    results.append(save(db,source,resource,name,start,end,error=code))
        record={'started_at_utc':started,'completed_at_utc':now(),'read_only_google_calls':True,'request_count':reader.calls,'periods':ranges,'selected_customers':CUSTOMERS,'metadata':reader.metadata,'last_ga4_quota':reader.quota,'results':results,'credentials_exported':False,'date_timezone_by_source':{'ga4':'Asia/Shanghai','gsc':'America/Los_Angeles','ads':'Asia/Hong_Kong'}}
        (ROOT/'verification-20260930/detail-collection-record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
        print(json.dumps({'periods':ranges,'request_count':reader.calls,'successful_reports':sum(r['status'] in ['success','reused_final_complete_week'] for r in results),'failed_reports':[r for r in results if r['status']=='failed'],'empty_reports':[r for r in results if r['status']=='empty'],'credential_values_suppressed':True}))
        if any(r['status']=='failed' for r in results):raise SystemExit(2)
    finally: reader.close(); db.close()

if __name__=='__main__': main()
