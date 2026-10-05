"""Real isolated daily collection, seeded from bounded verified report aggregates."""
import datetime as dt,json,os,sqlite3,sys,subprocess
from decimal import Decimal
from pathlib import Path
ROOT=Path('/opt/mmoexp-marketing')
sys.path.insert(0,str(ROOT/'implementation'))
import collector
import server_run_daily

def main():
    os.umask(0o077)
    if os.environ.get('MMOEXP_MARKETING_LIVE')!='approved':raise SystemExit('LIVE_DISABLED')
    if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')!='/etc/mmoexp-marketing/service-account.json':raise SystemExit('CONTROLLED_EXISTING_ADC_PATH_REQUIRED')
    verification=ROOT/'verification-20260930'
    ga=json.loads((verification/'ga4.json').read_text());gsc=json.loads((verification/'gsc.json').read_text())
    if not ga.get('report',{}).get('success') or not gsc.get('report_final',{}).get('success'):raise SystemExit('SUCCESSFUL_VERIFICATION_REQUIRED')
    if not ga.get('pagination_complete') or ga.get('metric_restrictions'):raise SystemExit('GA4_REPORT_RESTRICTIONS_REQUIRE_REVIEW')
    config=json.loads(Path('/etc/mmoexp-marketing/config.json').read_text())
    config.update(mode='verified_readonly_isolated_collection',network_enabled=True,production_writes_enabled=True)
    config['ga4'].update(property_timezone=ga['timezone'],currency=ga['currency'],viewer_permission='report_access_verified')
    config['gsc']['restricted_permission']=gsc.get('permission_level');config['ads']['customer_ids']=[]
    config_path=Path('/etc/mmoexp-marketing/config.verified.json')
    config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2));config_path.chmod(0o600)
    output=ROOT/'data/verified-readonly';output.mkdir(parents=True,exist_ok=True,mode=0o700)
    seed_required=not (output/'marketing.db').exists()
    db=sqlite3.connect(output/'marketing.db');db.execute('PRAGMA foreign_keys=ON');db.executescript((ROOT/'preparation/schema.sql').read_text())
    # These are real API aggregate results, not fixtures. Retain the known final GSC slice.
    for row in ga.get('daily_aggregate_rows',[]) if seed_required else []:
        date=dt.datetime.strptime(row['date'],'%Y%m%d').date().isoformat();plan=collector.plans(config,date,sources=['ga4'])[0]
        collector.ingest(db,plan,date,([(k,str(Decimal(v))) for k,v in row['metrics'].items()],ga['timezone'],ga['currency'],'provisional'),is_mock=False)
    for row in gsc['report_final'].get('daily_aggregate_rows',[]) if seed_required else []:
        date=row['date'];plan=collector.plans(config,date,sources=['gsc'])[0]
        collector.ingest(db,plan,date,([(k,str(Decimal(str(row[k])))) for k in ['clicks','impressions','ctr','position']],'America/Los_Angeles','','final'),is_mock=False)
    failures=0;now=dt.datetime.now(dt.timezone.utc);attempts=[]
    for source,zone in [('ga4',ga['timezone']),('gsc','America/Los_Angeles')]:
        previous=dt.date.fromisoformat(server_run_daily.previous_source_day(now,zone))
        offsets=list(reversed(range(3))) if source=='gsc' else [0]
        # GSC final data is delayed. Recheck a bounded recent window, oldest first.
        for offset in offsets:
            date=(previous-dt.timedelta(days=offset)).isoformat();plan=collector.plans(config,date,sources=[source])[0]
            try:
                payload=collector.adc_reader(plan);normalized=collector.normalise(plan,payload,date,config)
                if source=='ga4' and payload.get('metadata',{}).get('schemaRestrictionResponse',{}).get('activeMetricRestrictions'):raise ValueError('GA4_METRIC_RESTRICTION')
                collector.ingest(db,plan,date,normalized,is_mock=False)
                attempts.append({'source':source,'requested_date':date,'status':'success' if normalized[0] else 'empty_not_assumed_zero'})
            except Exception as exc:
                collector.error_run(db,plan,date,type(exc).__name__,False);failures+=1;attempts.append({'source':source,'requested_date':date,'status':'failed','error_class':type(exc).__name__})
    value=collector.snapshot(db,False)
    final_gsc=db.execute("SELECT MAX(source_date) FROM metric_rows WHERE source='gsc' AND data_state='final'").fetchone()[0]
    value['sourceQuality']={'ga4':{'revenueStatus':'zero_reported_by_analytics_tracking_not_reconciled_with_orders','financialRevenueTrusted':False,'recentDataState':'provisional'},'gsc':{'latestFinalDate':final_gsc,'recentAllDataDates':[r['date'] for r in gsc.get('report_all',{}).get('daily_aggregate_rows',[])],'missingFinalDatesAreZero':False},'ads':{'status':'blocked','reason':'NOT_ADS_USER','customerSelectionPending':True}}
    value['audience']='authorized_internal_marketing_and_operations_pending_dashboard_access_review'
    collector.write_outputs(output,value);db.close()
    banner='<p style="background:#fff3cd;padding:16px">真实隔离验证数据：GA4收入当前返回零，未与订单核对；GSC最终数据截至'+str(final_gsc)+'，较新日期缺少最终行表示延迟，不能当零；Ads因NOT_ADS_USER暂不可用。本页尚未接入生产看板。</p>'
    preview=output/'preview.html';html=preview.read_text();preview.write_text(html.replace('<table>',banner+'<table>',1))
    record={'collected_at_utc':now.isoformat(),'is_mock':False,'database':str(output/'marketing.db'),'snapshot':str(output/'marketing-data.json'),'internal_preview':str(preview),'runtime':sys.executable,'config':str(config_path),'daily_attempts':attempts,'metric_row_count':len(value['rows']),'latest_gsc_final_date':final_gsc,'ads':'blocked_NOT_ADS_USER','cross_source_financial_ratios_calculated':False,'timer_enabled':False,'production_page_connected':False,'credentials_copied':False,'status':'isolated_real_daily_collection_complete' if not failures else 'isolated_real_collection_has_failures'}
    (verification/'real-collection-record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
    print(json.dumps(record,ensure_ascii=False))

if __name__=='__main__':main()
