"""Manual isolated Ads collection; no schedule or production page is enabled."""
import argparse,datetime as dt,json,os,sqlite3,sys
from pathlib import Path
from zoneinfo import ZoneInfo
from ads_selected_account_check import CUSTOMERS,read_report
ROOT=Path('/opt/mmoexp-marketing')
sys.path.insert(0,str(ROOT/'implementation'))
import collector

def apply_report(db,customer,report):
    if customer not in CUSTOMERS:raise ValueError('SELECTED_CUSTOMER_REQUIRED')
    first,last=map(dt.date.fromisoformat,report['requested_dates']);attempts=[]
    successful=report.get('report',{}).get('success') and report.get('status')!='verification_failed'
    metadata=report.get('customer_metadata',{})
    if successful and (metadata.get('id')!=customer or metadata.get('currencyCode')!='USD' or metadata.get('timeZone')!='Asia/Hong_Kong'):raise ValueError('SOURCE_METADATA_MISMATCH')
    days={v['date']:v for v in report.get('daily_aggregate_rows',[])}
    for offset in range((last-first).days+1):
        date=(first+dt.timedelta(days=offset)).isoformat();plan={'source':'ads','resource':customer}
        if not successful:
            collector.error_run(db,plan,date,'AdsReadFailed',False);attempts.append({'customer_id':customer,'requested_date':date,'status':'failed'});continue
        row=days.get(date);metrics=list(row['metrics'].items()) if row else []
        if row and (row.get('currency')!='USD' or row.get('timezone')!='Asia/Hong_Kong'):raise ValueError('SOURCE_METADATA_MISMATCH')
        collector.ingest(db,plan,date,(metrics,'Asia/Hong_Kong','USD','provisional'),is_mock=False)
        attempts.append({'customer_id':customer,'requested_date':date,'status':'success' if row else 'empty_not_assumed_zero'})
    return attempts

def main():
    p=argparse.ArgumentParser();p.add_argument('--use-verified-reports',action='store_true');a=p.parse_args();os.umask(0o077)
    if os.getenv('MMOEXP_MARKETING_LIVE')!='approved':raise SystemExit('LIVE_DISABLED')
    output=ROOT/'data/verified-readonly';verification=ROOT/'verification-20260930'
    if not (output/'marketing.db').is_file():raise SystemExit('VERIFIED_DATABASE_REQUIRED')
    db=sqlite3.connect(output/'marketing.db');db.execute('PRAGMA foreign_keys=ON');attempts=[]
    end=dt.datetime.now(ZoneInfo('Asia/Hong_Kong')).date()-dt.timedelta(days=1);start=end-dt.timedelta(days=2)
    for customer in CUSTOMERS:
        report=json.loads((verification/('ads-'+customer+'.json')).read_text()) if a.use_verified_reports else read_report(customer,start.isoformat(),end.isoformat())
        if report.get('customer_id')!=customer:raise ValueError('CUSTOMER_REPORT_MISMATCH')
        attempts.extend(apply_report(db,customer,report))
        (output/('ads-'+customer+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    value=collector.snapshot(db,False)
    value['sourceQuality']={'ads':{'status':'two_selected_advertisers_only','customer_ids':list(CUSTOMERS),'separate_brand_tabs':True,'financialRevenueTrusted':False},'ga4':{'financialRevenueTrusted':False},'gsc':{'missingFinalDatesAreZero':False}}
    collector.write_outputs(output,value);db.close()
    record={'collected_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'read_only_google_operations':True,'is_mock':False,'selected_customer_ids':list(CUSTOMERS),'brand_aggregation_performed':False,'daily_attempts':attempts,'metric_row_count':len(value['rows']),'database':str(output/'marketing.db'),'timer_enabled':False,'production_page_connected':False,'credentials_copied':False}
    (verification/'ads-collection-record.json').write_text(json.dumps(record,indent=2));print(json.dumps(record))
    if any(v['status']=='failed' for v in attempts):raise SystemExit(2)

if __name__=='__main__':main()
