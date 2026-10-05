"""Server daily runner; each source keeps its own previous calendar day."""
import argparse,copy,datetime as dt,json,os,sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo
import collector

def previous_source_day(now,zone):
    return (now.astimezone(ZoneInfo(zone)).date()-dt.timedelta(days=1)).isoformat()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mode',choices=['mock','live'],default='mock')
    p.add_argument('--config',type=Path,required=True);p.add_argument('--schema',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();c=json.loads(a.config.read_text(encoding='utf-8'))
    if a.mode=='live' and not(c.get('network_enabled') and c.get('production_writes_enabled') and os.getenv('MMOEXP_MARKETING_LIVE')=='approved'):
        raise SystemExit('LIVE_DISABLED')
    zones={'ga4':c['ga4'].get('property_timezone'),'gsc':'America/Los_Angeles','ads':c['ads'].get('customer_timezone')}
    if a.mode=='mock':zones.update(ga4='Asia/Shanghai',ads='America/New_York')
    if a.mode=='live' and not zones['ga4']:raise SystemExit('GA4_PROPERTY_TIMEZONE_REQUIRED')
    if a.mode=='live' and len(c['ads'].get('customer_ids',[]))==1 and not zones['ads']:raise SystemExit('ADS_CUSTOMER_TIMEZONE_REQUIRED')
    executions=[('ga4',zones['ga4'],c),('gsc',zones['gsc'],c)]
    for customer in c['ads'].get('customer_ids',[]):
        subset=copy.deepcopy(c);subset['ads']['customer_ids']=[customer]
        metadata=c['ads'].get('customer_metadata',{}).get(customer,{})
        customer_zone=metadata.get('timezone') or zones['ads']
        if not customer_zone or (a.mode=='live' and len(c['ads']['customer_ids'])>1 and not metadata.get('timezone')):raise SystemExit('PER_CUSTOMER_TIMEZONE_REQUIRED')
        subset['ads']['customer_timezone']=customer_zone
        executions.append(('ads',customer_zone,subset))
    a.output.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(':memory:' if a.mode=='mock' else a.output/'marketing.db')
    db.execute('PRAGMA foreign_keys=ON');db.executescript(a.schema.read_text(encoding='utf-8'))
    now=dt.datetime.now(dt.timezone.utc);failed=0;planned=0
    for source,zone,source_config in executions:
        date=previous_source_day(now,zone)
        for plan in collector.plans(source_config,date,sources=[source]):
            planned+=1
            try:
                if a.mode=='live':payload=collector.adc_reader(plan)
                else:
                    payload=json.loads((Path(__file__).parent/'fixtures'/f'{source}.json').read_text(encoding='utf-8'))
                    if source=='ga4':payload['rows'][0]['dimensionValues'][0]['value']=date.replace('-','')
                    if source=='gsc':payload['rows'][0]['keys']=[date]
                    if source=='ads':payload['results'][0]['segments']['date']=date
                collector.ingest(db,plan,date,collector.normalise(plan,payload,date,source_config),is_mock=a.mode=='mock')
            except Exception as ex:
                collector.error_run(db,plan,date,type(ex).__name__,a.mode=='mock');failed+=1
    collector.write_outputs(a.output,collector.snapshot(db,a.mode=='mock'))
    db.close()
    print(json.dumps({'mode':a.mode,'requests_planned':planned,'failed_sources':failed,'ads_customer_ids_missing':not bool(c['ads'].get('customer_ids')),'source_days_computed_separately':True}))
    if failed:raise SystemExit(2)

if __name__=='__main__':main()
