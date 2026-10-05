"""Read-only Google report collector. Default CLI mode is offline mock."""
from __future__ import annotations
import argparse
import datetime as dt
import html
import json
import os
import re
import sqlite3
import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

SCOPES = {'ga4':'https://www.googleapis.com/auth/analytics.readonly',
          'gsc':'https://www.googleapis.com/auth/webmasters.readonly',
          'ads':'https://www.googleapis.com/auth/adwords'}

def identifier(value):
    value=str(value)
    if not re.fullmatch(r'[0-9]+',value): raise ValueError('INVALID_RESOURCE_ID')
    return value

def plans(config, date, sources=None):
    dt.date.fromisoformat(date)
    result=[]
    prop=identifier(config['ga4']['property_id'])
    result.append({'source':'ga4','resource':prop,'url':f'https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport',
                   'body':{'dateRanges':[{'startDate':date,'endDate':date}], 'dimensions':[{'name':'date'}],
                           'metrics':[{'name':n} for n in ['sessions','activeUsers','ecommercePurchases','purchaseRevenue']],
                           'limit':10000,'returnPropertyQuota':True}})
    site=config['gsc']['property']
    if not isinstance(site,str) or not site.startswith(('sc-domain:','https://','http://')): raise ValueError('INVALID_GSC_PROPERTY')
    result.append({'source':'gsc','resource':site,'url':f'https://www.googleapis.com/webmasters/v3/sites/{quote(site,safe="")}/searchAnalytics/query',
                   'body':{'startDate':date,'endDate':date,'dimensions':['date'],'type':'web','dataState':'final','aggregationType':'byProperty','rowLimit':25000}})
    for customer in config['ads'].get('customer_ids',[]):
        customer=identifier(customer)
        if customer==config['ads'].get('login_customer_id'): raise ValueError('ADVERTISER_ID_REQUIRED_NOT_MANAGER')
        version=config['ads'].get('api_version','v25')
        if not re.fullmatch(r'v[0-9]+',version): raise ValueError('INVALID_API_VERSION')
        manager=config['ads'].get('login_customer_id')
        headers={'login-customer-id':identifier(manager)} if manager else {}
        result.append({'source':'ads','resource':customer,'url':f'https://googleads.googleapis.com/{version}/customers/{customer}/googleAds:search',
                       'headers':headers,'body':{'query':f"SELECT customer.currency_code, customer.time_zone, segments.date, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.conversions_value FROM customer WHERE segments.date = '{date}'"}})
    return [p for p in result if sources is None or p['source'] in sources]

def normalise(plan, payload, date, config):
    source=plan['source']; rows=[]
    if source=='ga4':
        raw=payload.get('rows',[])
        if int(payload.get('rowCount',len(raw)))>len(raw): raise ValueError('INCOMPLETE_GA4_PAGINATION')
        if len(raw)>1: raise ValueError('EXPECTED_SINGLE_DATE_AGGREGATE')
        zone=payload.get('metadata',{}).get('timeZone') or config['ga4'].get('property_timezone')
        currency=payload.get('metadata',{}).get('currencyCode') or config['ga4'].get('currency')
        if not zone or not currency: raise ValueError('GA4_METADATA_REQUIRED')
        if config['ga4'].get('property_timezone') and zone!=config['ga4']['property_timezone']: raise ValueError('GA4_TIMEZONE_MISMATCH')
        metrics=[h['name'] for h in payload.get('metricHeaders',[])]
        required={'sessions','activeUsers','ecommercePurchases','purchaseRevenue'}
        if raw and not required.issubset(metrics): raise ValueError('GA4_HEADERS_MISSING')
        for row in raw:
            if row['dimensionValues'][0]['value']!=date.replace('-',''): raise ValueError('SOURCE_DATE_MISMATCH')
            if len(row['metricValues'])!=len(metrics): raise ValueError('GA4_METRIC_LENGTH_MISMATCH')
            rows.extend((n,str(Decimal(v['value']))) for n,v in zip(metrics,row['metricValues']))
        return rows,zone,currency,'unknown'
    if source=='gsc':
        if payload.get('responseAggregationType') not in (None,'byProperty'): raise ValueError('GSC_AGGREGATION_MISMATCH')
        raw=payload.get('rows',[])
        if len(raw)>1: raise ValueError('EXPECTED_SINGLE_DATE_AGGREGATE')
        for row in raw:
            if row['keys']!=[date]: raise ValueError('SOURCE_DATE_MISMATCH')
            rows.extend((n,str(Decimal(str(row[n])))) for n in ['clicks','impressions','ctr','position'])
        return rows,'America/Los_Angeles','','final'
    if payload.get('nextPageToken'): raise ValueError('INCOMPLETE_ADS_PAGINATION')
    raw=payload.get('results',[])
    if len(raw)>1: raise ValueError('EXPECTED_SINGLE_DATE_AGGREGATE')
    zone=config['ads'].get('customer_timezone'); currency=config['ads'].get('currency')
    for row in raw:
        if row['segments']['date']!=date: raise ValueError('SOURCE_DATE_MISMATCH')
        zone=row['customer']['timeZone'];currency=row['customer']['currencyCode']
        if config['ads'].get('customer_timezone') and zone!=config['ads']['customer_timezone']: raise ValueError('ADS_TIMEZONE_MISMATCH')
        rows.extend((n,str(Decimal(str(row['metrics'][n])))) for n in ['impressions','clicks','costMicros','conversions','conversionsValue'])
    if raw and (not zone or not currency): raise ValueError('ADS_METADATA_REQUIRED')
    return rows,zone or 'unknown',currency or '', 'provisional'

def ingest(db, plan, date, normalized, *, is_mock):
    rows,zone,currency,state=normalized
    run_id=uuid.uuid4().hex
    with db:
        db.execute('INSERT INTO collection_runs VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (run_id,plan['source'],plan['resource'],'site-daily-v1',dt.datetime.now(dt.timezone.utc).isoformat(),
                    date,date if rows else None,'success' if rows else 'empty',None,int(is_mock)))
        if not rows: return
        db.execute('DELETE FROM metric_rows WHERE source=? AND resource_id=? AND source_date=? AND grain=?',
                   (plan['source'],plan['resource'],date,'site_daily'))
        db.executemany('INSERT INTO metric_rows VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       [(plan['source'],plan['resource'],date,zone,currency,'site_daily','{}',key,value,state,run_id) for key,value in rows])

def error_run(db,plan,date,code,is_mock):
    with db:
        db.execute('INSERT INTO collection_runs VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (uuid.uuid4().hex,plan['source'],plan['resource'],'site-daily-v1',dt.datetime.now(dt.timezone.utc).isoformat(),date,None,'failed',code,int(is_mock)))

def snapshot(db,is_mock):
    rows=db.execute('SELECT source,resource_id,source_date,source_timezone,currency,metric_name,metric_value,data_state FROM metric_rows ORDER BY source,resource_id,source_date,metric_name').fetchall()
    runs=db.execute('SELECT source,resource_id,status,error_code,collected_at_utc,verified_through FROM collection_runs ORDER BY rowid').fetchall()
    last={f'{r[0]}:{r[1]}':dict(zip(['source','resource','status','errorCode','collectedAt','verifiedThrough'],r)) for r in runs}
    return {'schemaVersion':1,'isMock':is_mock,'snapshotId':uuid.uuid4().hex,'rows':[dict(zip(['source','resource','sourceDate','sourceTimezone','currency','metric','value','dataState'],r)) for r in rows],
            'lastAttempts':last,'crossSourceRatios':None,'crossSourceRatioReason':'Timezones, currencies and attribution require reconciliation.'}

def write_outputs(output, value):
    output.mkdir(parents=True,exist_ok=True)
    temporary=output/'marketing-data.json.tmp'
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(output/'marketing-data.json')
    label='离线假数据预览' if value['isMock'] else '内部营销数据预览'
    table=''.join('<tr>'+''.join('<td>'+html.escape(str(r[k]))+'</td>' for k in ['source','sourceDate','sourceTimezone','currency','metric','value','dataState'])+'</tr>' for r in value['rows'])
    attempts=''.join('<li>'+html.escape(k)+': '+html.escape(str(v['status']))+'；采集UTC '+html.escape(str(v['collectedAt']))+'；已验证到 '+html.escape(str(v['verifiedThrough']))+'；错误 '+html.escape(str(v['errorCode']))+'</li>' for k,v in value['lastAttempts'].items())
    document='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+label+'</title><style>body{font:16px system-ui;margin:32px;color:#173047}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #dde5ec;text-align:left}small{color:#526477}</style><h1>'+label+'</h1><p>分来源、时区、币种显示；未计算跨来源转化率或 ROAS。失败或空响应时表中可能保留上一有效数据，请先看最后尝试状态。</p><ul>'+attempts+'</ul><table><thead><tr><th>来源</th><th>来源日期</th><th>时区</th><th>币种</th><th>指标</th><th>值</th><th>状态</th></tr></thead><tbody>'+table+'</tbody></table><small>这是独立预览，不是已上线看板。</small></html>'
    (output/'preview.html').write_text(document,encoding='utf-8')

def adc_reader(plan):
    # Reads only an operator-configured existing ADC path. Never creates credentials.
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials,_=google.auth.default(scopes=[SCOPES[plan['source']]])
    session=AuthorizedSession(credentials)
    try:
        response=session.post(plan['url'],json=plan['body'],headers=plan.get('headers',{}),timeout=45)
        if response.status_code!=200: raise RuntimeError('HTTP_'+str(response.status_code))
        return response.json()
    finally:session.close()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['plan','mock','live'],default='mock')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--date',default='2026-09-29')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--schema',type=Path,required=True)
    args=parser.parse_args();config=json.loads(args.config.read_text(encoding='utf-8'))
    request_plans=plans(config,args.date)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'request-plan.json').write_text(json.dumps({'requests':request_plans,'adsBlockedReason':None if config['ads'].get('customer_ids') else 'Advertiser customer IDs required; manager ID is not substituted.'},ensure_ascii=False,indent=2),encoding='utf-8')
    if args.mode=='plan':return
    if args.mode=='live' and not (config.get('network_enabled') and config.get('production_writes_enabled') and os.getenv('MMOEXP_MARKETING_LIVE')=='approved'):
        raise SystemExit('LIVE_DISABLED: operator approval and controlled credential setup required')
    db=sqlite3.connect(':memory:' if args.mode=='mock' else args.output/'marketing.db')
    db.execute('PRAGMA foreign_keys=ON');db.executescript(args.schema.read_text(encoding='utf-8'))
    failures=0
    for plan in request_plans:
        try:
            if args.mode=='live': payload=adc_reader(plan)
            else:
                payload=json.loads((Path(__file__).parent/'fixtures'/f'{plan["source"]}.json').read_text(encoding='utf-8'))
                if plan['source']=='ga4':payload['rows'][0]['dimensionValues'][0]['value']=args.date.replace('-','')
                if plan['source']=='gsc':payload['rows'][0]['keys']=[args.date]
                if plan['source']=='ads':payload['results'][0]['segments']['date']=args.date
            ingest(db,plan,args.date,normalise(plan,payload,args.date,config),is_mock=args.mode=='mock')
        except Exception as exc:
            # Never log response bodies or exception text from authentication libraries.
            code=str(exc) if isinstance(exc,ValueError) and re.fullmatch('[A-Z_]+',str(exc)) else type(exc).__name__
            error_run(db,plan,args.date,code,args.mode=='mock');failures+=1
    write_outputs(args.output,snapshot(db,args.mode=='mock'))
    print(json.dumps({'mode':args.mode,'requests_planned':len(request_plans),'failed_sources':failures,'ads_customer_ids_missing':not bool(config['ads'].get('customer_ids'))}))
    db.close()
    if failures:raise SystemExit(2)

if __name__=='__main__':main()
