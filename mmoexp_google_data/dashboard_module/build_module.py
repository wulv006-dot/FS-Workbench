"""Create a scope-limited GA4/GSC read-only view. Does not publish or authenticate."""
import argparse,datetime as dt,json,re,shutil
from decimal import Decimal,InvalidOperation
from pathlib import Path

SOURCES={'ga4':{'resource':'541418940','label':'GA4 网站行为','timezone':'Asia/Shanghai','metrics':['sessions','activeUsers','ecommercePurchases']},
         'gsc':{'resource':'sc-domain:mmoexp.com','label':'GSC 自然搜索','timezone':'America/Los_Angeles','metrics':['clicks','impressions','ctr','position']}}

ADS_ACCOUNTS={'1430398974':{'brand':'mmoexp','label':'MMOEXP-1'},'8154986819':{'brand':'rsorder','label':'RSOrder-1 · RS 游戏 / RSorders 网站'}}

def numeric(value,allow_negative=False):
    try:decimal=Decimal(str(value))
    except InvalidOperation:raise ValueError('INVALID_METRIC_VALUE') from None
    if not decimal.is_finite() or (decimal<0 and not allow_negative) or abs(decimal)>Decimal('1e20'):raise ValueError('INVALID_METRIC_VALUE')
    return str(decimal)

def valid_date(value):
    dt.date.fromisoformat(value)
    return value

def safe_timestamp(value):
    try:
        stamp=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        return stamp.astimezone(dt.timezone.utc).isoformat() if stamp.tzinfo else None
    except (AttributeError,ValueError):return None

def build_view_model(snapshot,collection=None):
    if snapshot.get('schemaVersion')!=1 or snapshot.get('isMock') is not False:raise ValueError('REAL_VERIFIED_SNAPSHOT_REQUIRED')
    if len(snapshot.get('rows',[]))>10000:raise ValueError('SNAPSHOT_TOO_LARGE')
    view={'schemaVersion':1,'isMock':False,'title':'营销数据','financialSource':'existing_transaction_dashboard','crossSourceFinancialRatios':None,'adsStatus':'已验证两个指定账号，只读、分品牌统计','sources':[],'adsAccounts':[],'data_generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'collection_schedule':{'timezone':'Asia/Shanghai','daily_time':'00:10'},'ui_refresh_seconds':300}
    for source,settings in SOURCES.items():
        days={};revenues={}
        for row in snapshot.get('rows',[]):
            if row.get('source')!=source or row.get('resource')!=settings['resource']:continue
            if row.get('sourceTimezone')!=settings['timezone']:raise ValueError('SOURCE_TIMEZONE_REQUIRES_REVIEW')
            if source=='gsc' and row.get('dataState')!='final':continue
            metric=row.get('metric');date=valid_date(row['sourceDate'])
            if source=='ga4' and row.get('currency')!='USD':raise ValueError('GA4_CURRENCY_REQUIRES_REVIEW')
            if source=='ga4' and metric=='purchaseRevenue':revenues[date]=numeric(row['value'],allow_negative=True)
            if metric not in settings['metrics']:continue
            values=days.setdefault(date,{})
            if metric in values:raise ValueError('DUPLICATE_DAILY_AGGREGATE')
            values[metric]=numeric(row['value'])
        attempt=snapshot.get('lastAttempts',{}).get(source+':'+settings['resource'],{})
        status=attempt.get('status','not_collected')
        if status not in ['success','empty','failed','not_collected']:status='unknown'
        request_dates=[v['requested_date'] for v in (collection or {}).get('daily_attempts',[]) if v.get('source')==source]
        requested=max((valid_date(v) for v in request_dates),default=None)
        latest=max(days,default=None)
        source_view={'id':source,'label':settings['label'],'timezone':settings['timezone'],'currency':'USD' if source=='ga4' else None,
                     'latestDate':latest,'requestedThrough':requested,'lastAttemptStatus':status,'lastCollectedAt':safe_timestamp(attempt.get('collectedAt')),
                     'freshness':'final_delayed' if source=='gsc' and latest and requested and latest<requested else ('provisional' if source=='ga4' and latest else 'final' if latest else 'no_verified_data'),
                     'latestMetrics':days.get(latest,{}),'days':[{'date':date,'metrics':values} for date,values in sorted(days.items())]}
        if source=='ga4':source_view['revenueDiagnostic']={'reportedValue':revenues.get(latest),'currency':'USD','financialRevenueTrusted':False,'explanation':'GA4 报告收入仅作核查；经营销售额继续使用原交易看板。零值原因尚未确定。'}
        view['sources'].append(source_view)
    for customer,settings in ADS_ACCOUNTS.items():
        days={}
        for row in snapshot.get('rows',[]):
            if row.get('source')!='ads' or row.get('resource')!=customer:continue
            if row.get('sourceTimezone')!='Asia/Hong_Kong' or row.get('currency')!='USD':raise ValueError('ADS_METADATA_REQUIRES_REVIEW')
            if row.get('dataState')!='provisional':raise ValueError('ADS_ATTRIBUTION_STATE_REQUIRES_REVIEW')
            metric=row.get('metric')
            if metric not in ['impressions','clicks','costMicros','conversions','conversionsValue']:continue
            date=valid_date(row['sourceDate']);values=days.setdefault(date,{})
            if metric in values:raise ValueError('DUPLICATE_DAILY_AGGREGATE')
            values[metric]=numeric(row['value'],allow_negative=metric in ['conversions','conversionsValue'])
        for values in days.values():
            if 'costMicros' in values:values['cost']=str(Decimal(values.pop('costMicros'))/Decimal(1000000))
        latest=max(days,default=None);attempt=snapshot.get('lastAttempts',{}).get('ads:'+customer,{})
        status=attempt.get('status','not_collected')
        if status not in ['success','empty','failed','not_collected']:status='unknown'
        view['adsAccounts'].append({'id':'ads','resource':customer,'brand':settings['brand'],'label':settings['label'],'timezone':'Asia/Hong_Kong','currency':'USD','latestDate':latest,'lastAttemptStatus':status,'lastCollectedAt':safe_timestamp(attempt.get('collectedAt')),'freshness':'provisional' if latest else 'no_verified_data','latestMetrics':days.get(latest,{}),'days':[{'date':date,'metrics':values} for date,values in sorted(days.items())]})
    for card in view['sources']+view['adsAccounts']:card['data_date']=card['latestDate'];card['collected_at']=card['lastCollectedAt']
    return view

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--snapshot',type=Path,required=True);parser.add_argument('--collection-record',type=Path);parser.add_argument('--details',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();snapshot=json.loads(args.snapshot.read_text(encoding='utf-8'));record=json.loads(args.collection_record.read_text(encoding='utf-8')) if args.collection_record else None
    value=build_view_model(snapshot,record)
    if args.details:
        details=json.loads(args.details.read_text(encoding='utf-8'))
        if details.get('isMock') is not False or details.get('schemaVersion')!=1 or set(details.get('allowed_customers',[]))!={'1430398974','8154986819','3552474396'}:raise ValueError('REVIEWED_DETAIL_SCOPE_REQUIRED')
        value['details']=details
        value['adsStatus']='MMOEXP一个customer；RSOrder两个不同customer按用户归属分别列示，ID去重'
    args.output.mkdir(parents=True,exist_ok=True)
    temporary=args.output/'data.json.tmp';temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(args.output/'data.json')
    for name in ['index.html','marketing-module.js','marketing-module.css','business-module.js']:shutil.copyfile(Path(__file__).parent/name,args.output/name)
    print(json.dumps({'sources':[s['id'] for s in value['sources']],'is_mock':False,'publication_performed':False,'output':str(args.output)},ensure_ascii=True))

if __name__=='__main__':main()
