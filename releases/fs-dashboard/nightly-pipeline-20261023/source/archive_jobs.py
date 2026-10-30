"""Bounded low-priority reads through existing routes, with durable read receipts."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError
from http.client import IncompleteRead, BadStatusLine
import argparse
import ast
import hashlib
import json
import os
import sys
import time

sys.path.append('/opt/fs-hermes-fc')

from daily_archive import Archive, ROOT, TZ, cutoff, encoded, complete_native, complete_summary, native_key, summary_key


def profiles():
    tree=ast.parse(Path('/opt/fs-transaction-snapshot/collector.py').read_text())
    return {row[0]:row for node in tree.body if isinstance(node,ast.Assign)
        and any(isinstance(n,ast.Name) and n.id=='PROFILES' for n in node.targets) for row in ast.literal_eval(node.value)}


def import_existing(store):
    definitions=profiles();counts={'native':0,'native-statistics':0,'marketing':0,'references':0,'rejected':0}
    for path in Path('/var/lib/fs-business-ranges').glob('*.json'):
        try:
            value=json.loads(path.read_text());q=value['query'];profile=definitions[q['profile']]
            source=value.get('profile',{}).get('primary',{})
            if not complete_native(value) or str(source.get('filters',{}).get('gid'))!=str(profile[2]):continue
            if store.put('native',native_key(q,profile),value):counts['native']+=1
        except (ValueError,KeyError,TypeError,OSError):counts['rejected']+=1
    for path in Path('/var/lib/fs-hermes-fc/fs/source-snapshots').glob('*.data.json'):
        try:
            value=json.loads(path.read_text())
            if value.get('family')!='native-statistics':continue
            if hashlib.sha256(encoded(value)).hexdigest()!=path.name.split('.')[0]:raise ValueError('snapshot_checksum')
            from source_snapshots import native_cacheable
            if native_cacheable(value['value']) and store.put('native-statistics',value['query'],value['value'],value['saved_at']):counts['native-statistics']+=1
        except (ValueError,KeyError,TypeError,OSError):counts['rejected']+=1
    for path in Path('/opt/mmoexp-marketing/data/verified-readonly/traffic-ranges').glob('*.json'):
        try:
            value=json.loads(path.read_text());period=value['period']
            if value.get('status')!='available' or not period.get('game_projection_version'):continue
            q=dict(profile='MMOEXP',start=value['start'],end=value['end'],rule=period['rule_version'],projection=period['game_projection_version'])
            if store.put('marketing',q,value):counts['marketing']+=1
        except (ValueError,KeyError,TypeError,OSError):counts['rejected']+=1
    for folder,family in [('days','channel-orders'),('delivery-days','channel-deliveries')]:
        for path in (Path('/var/lib/fs-channel-effects')/folder).glob('*.json'):
            value=json.loads(path.read_text());p=value['period']
            complete=value.get('complete') is True if folder=='delivery-days' else all(value['sources'][k]['status']=='complete' for k in ('orders','coupons'))
            store.reference(family,'MMOEXP',p['start'],p['end'],path,complete);counts['references']+=1
    for path in Path('/var/lib/fc27-es-exports').glob('*.json'):
        try:
            value=json.loads(path.read_text());q=value['query']
            if not all(q.get(k) for k in ('start','end')):continue
            # Metadata reference only; the existing ES reader validates file sets on use.
            store.reference('es-export',q.get('profile','ALL'),q['start'],q['end'],path,False);counts['references']+=1
        except (ValueError,KeyError,TypeError,OSError):counts['rejected']+=1
    return counts


def atomic(path,value):
    from source_snapshots import atomic as publish
    publish(path,value)


def read_route(params,port=8931,path='/range',timeout=10):
    request=Request('http://127.0.0.1:'+str(port)+path+'?'+urlencode(params),headers={'X-Auth-User':'wulv'})
    try:
        try:response=build_opener(ProxyHandler({})).open(request,timeout=timeout)
        except HTTPError as error:response=error
        with response:
            raw=response.read(16*1024*1024+1) or b''
            code=response.status
        if len(raw)>16*1024*1024:return code,dict(status='unavailable',reason='archive_route_size',retryable=False)
        try:value=json.loads(raw)
        except (ValueError,UnicodeError):value=None
        if not isinstance(value,dict):
            return code,dict(status='unavailable',reason='archive_response_schema_invalid',retryable=code>=500)
        return code,value
    except (URLError,TimeoutError,ConnectionError,IncompleteRead,BadStatusLine):
        return 503,{'status':'unavailable','reason':'local_route_temporarily_unavailable'}


def unavailable(code,value):
    reasons=[value.get(k) for k in ('reason','error','lastError')]
    sources=value.get('sources') or {}
    reasons += [s.get('error') for s in sources.values() if isinstance(s,dict)] if isinstance(sources,dict) else []
    if code in (401,403) or value.get('status')=='denied' or any(r in ('permission_denied','source_permission_denied') for r in reasons):
        return 'failed','permission_denied',False
    if code in (400,405,413,415,422):return 'failed','invalid_archive_arguments',False
    schema=('archive_route_size','archive_response_schema_invalid','source_period_or_status','source_period_mismatch','native_source_contract')
    if value.get('retryable') is False or any(isinstance(r,str) and (r.startswith(('invalid_','schema_')) or r in schema and not (r=='archive_response_schema_invalid' and value.get('retryable') is True)) for r in reasons):
        return 'failed',next((r for r in reasons if r in schema),'source_schema_invalid'),False
    if code==429 or (value.get('archive') or {}).get('refreshDeferred') or 'collector_busy' in reasons or value.get('status')=='busy':
        return 'busy','collector_busy' if 'collector_busy' in reasons else 'source_busy',True
    if code==409:return 'unavailable','catalog_changed',True
    if code in (500,502,503,504):
        return 'unavailable','local_route_temporarily_unavailable' if 'local_route_temporarily_unavailable' in reasons else 'source_http_'+str(code),True
    records=list(sources.values()) if isinstance(sources,dict) else []
    records += list((value.get('profile') or {}).get(k,{}) for k in ('primary','supplement'))
    if code==202 or value.get('status')=='pending' or any(isinstance(s,dict) and s.get('status') in ('pending','new') for s in records):
        return 'pending','source_pending',True
    if value.get('status') in ('unavailable','stale') or any(isinstance(s,dict) and s.get('status')=='unavailable' for s in records):
        return 'unavailable','source_read_failed',True
    return 'failed','source_schema_invalid',False


def retry_at(prior):
    due=prior.get('retryAfter',0)
    if prior.get('status')=='busy':
        try:observed=datetime.fromisoformat(prior.get('lastObservedAt') or prior.get('at') or '').timestamp()
        except (ValueError,TypeError):return 0
        # Old admission failures must not keep an otherwise ready query asleep for four hours.
        due=min(due,observed+300)
    return due


def candidates(today,definitions,daily):
    end=(today-timedelta(days=1)).isoformat()
    if daily:
        for offset in range(1,7):
            day=(today-timedelta(days=offset)).isoformat()
            yield dict(profile='marketing',start=day,end=day)
        for length in (7,30):
            yield dict(profile='marketing',start=(today-timedelta(days=length)).isoformat(),end=end)
        ordered=sorted(definitions,key=lambda key:(key not in ('MMOEXP','FC27'),list(definitions).index(key)))
        for profile in ordered:
            spans=[((today-timedelta(days=length)).isoformat(),end) for length in (1,7,30)]
            from nightly import closed_period
            spans += [closed_period(today,kind) for kind in ('management','weekly','monthly') if kind!='monthly' or today.day==1]
            for start,range_end in dict.fromkeys(spans):
                yield dict(mode='summary',profile=profile,start=start,end=range_end)
                yield dict(archiveFamily='native',profile=profile,start=start,end=range_end)
        return
    lo=max(date(2026,9,1),cutoff(today));day=today-timedelta(days=1)
    while day>=lo:
        for profile in definitions:
            yield dict(mode='summary',profile=profile,start=day.isoformat(),end=day.isoformat())
            yield dict(archiveFamily='native',profile=profile,start=day.isoformat(),end=day.isoformat())
        yield dict(profile='marketing',start=day.isoformat(),end=day.isoformat())
        day-=timedelta(days=1)


def run_once(daily=False,budget=480):
    now=datetime.now(TZ);store=Archive();store.safe(True)
    state_path=ROOT/'scheduler-state.json'
    state=json.loads(state_path.read_text()) if state_path.is_file() else {}
    completed=0;reused=0;begin=time.monotonic();definition=profiles();deferred={};catalog_reply=None;limited_ports=set()
    cadence='daily' if daily else 'history'
    work=[(hashlib.sha256(encoded({'cadence':cadence,'query':args})).hexdigest(),args) for args in candidates(now.date(),definition,daily)]
    def oldest(item):
        prior=state.get(item[0],{})
        try:stamp=datetime.fromisoformat(prior.get('lastObservedAt') or prior.get('at') or '').timestamp()
        except (ValueError,TypeError):stamp=0
        rank=0 if not prior else 3 if prior.get('status')=='complete' else 2 if retry_at(prior)>time.time() or prior.get('retryable') is False else 1
        return rank,stamp
    # The same state rotates due work; a slow first marketing item cannot starve business profiles.
    work.sort(key=oldest)
    for key,args in work:
        if time.monotonic()-begin>=budget:break
        marketing=args['profile']=='marketing';native=args.get('archiveFamily')=='native'
        family='marketing' if marketing else 'native' if native else 'summary'
        port=8935 if marketing else 8931
        if port in limited_ports:continue
        prior=state.get(key,{})
        correction_day=prior.get('correctionDay') or prior.get('at','')[:10]
        if daily and prior.get('status')=='complete' and correction_day==now.date().isoformat():continue
        if prior.get('status')=='failed' and prior.get('retryable') is False and prior.get('reason')=='invalid_archive_arguments':continue
        requested=prior.get('requestedAt') or datetime.now(timezone.utc).isoformat()
        base=dict(prior,query=args,cadence=cadence,family=family,requestedAt=requested)
        if not marketing:
            from live_summary import query
            try:selector=native_key(dict(args,grain='day'),definition[args['profile']]) if native else summary_key(query({k:[v] for k,v in args.items()},definition))
            except (ValueError,KeyError,TypeError):
                state[key]=dict(base,status='failed',reason='invalid_archive_arguments',retryable=False,failures=prior.get('failures',0)+1,retryAfter=0,at=now.isoformat(),lastObservedAt=datetime.now(timezone.utc).isoformat())
                atomic(state_path,state);deferred[port]='failed';continue
            try:
                cached=store.get(family,selector)
                cached_complete=cached is not None and (complete_native(cached) if native else complete_summary(cached))
            except (ValueError,KeyError,TypeError):
                if prior.get('status')=='failed' and prior.get('retryable') is False:continue
                state[key]=dict(base,status='failed',reason='invalid_archived_source',retryable=False,failures=prior.get('failures',0)+1,retryAfter=0,at=now.isoformat(),lastObservedAt=datetime.now(timezone.utc).isoformat())
                atomic(state_path,state);deferred[port]='failed';continue
            if cached_complete:
                if prior.get('status')!='complete':
                    state[key]=dict(base,status='complete',reason='existing_complete_archive',retryable=False,failures=0,retryAfter=0,at=now.isoformat(),lastObservedAt=datetime.now(timezone.utc).isoformat())
                    atomic(state_path,state)
                reused+=1;continue
        if prior.get('retryable') is False and prior.get('status')=='failed':continue
        if retry_at(prior)>time.time():continue
        params={k:v for k,v in args.items() if k!='archiveFamily' and (not marketing or k!='profile')}
        catalog_failed=None
        if native:
            if catalog_reply is None:catalog_reply=read_route({'mode':'catalog'},timeout=min(10,max(.01,begin+budget-time.monotonic())))
            code,catalog=catalog_reply
            if code!=200:catalog_failed=(code,catalog)
            elif not isinstance(catalog.get('catalogId'),str):catalog_failed=(200,dict(status='unavailable',retryable=False))
            else:params['snapshotId']=catalog['catalogId']
        continuation=prior.get('status') in ('pending','busy') or daily and marketing and correction_day==now.date().isoformat()
        attempt_at=prior.get('attemptStartedAt',requested) if continuation else datetime.now(timezone.utc).isoformat()
        # One refresh per daily correction; a lost reply still resumes the existing job/cache.
        if daily and marketing and prior.get('status')!='pending' and correction_day!=now.date().isoformat():
            params['refresh']='true';correction_day=now.date().isoformat();attempt_at=datetime.now(timezone.utc).isoformat()
        elif daily and marketing and prior.get('refreshPending') is True:params['refresh']='true'
        if time.monotonic()-begin>=budget:break
        state[key]=dict(base,status='pending',reason='source_pending',retryable=True,retryAfter=0,correctionDay=correction_day,refreshPending=False,attemptStartedAt=attempt_at,failures=prior.get('failures',0));atomic(state_path,state)
        code,value=catalog_failed if catalog_failed is not None else read_route(params,port,timeout=min(10,begin+budget-time.monotonic()))
        if code==429:limited_ports.add(port)
        try:
            valid=code==200 and value.get('status')=='available' if marketing else code==200 and (complete_native(value) if native else complete_summary(value))
            deferred_refresh=(value.get('archive') or {}).get('refreshDeferred') is True
            if daily and marketing and (deferred_refresh or code==429):state[key]['refreshPending']=True
            if deferred_refresh:valid=False
            capture=(value.get('archive') or {}).get('sourceCapturedAt') or value.get('generatedAt') or ''
            fresh=False
            try:fresh=datetime.fromisoformat(capture.replace('Z','+00:00'))>=datetime.fromisoformat(attempt_at)-timedelta(seconds=60)
            except (ValueError,TypeError):pass
            outcome,reason,retryable=('complete','complete',False) if valid and (not (daily and marketing) or fresh) else ('pending','correction_pending',True) if valid else unavailable(code,value)
        except (ValueError,KeyError,TypeError):outcome,reason,retryable='failed','source_schema_invalid',False
        failures=0 if outcome=='complete' else prior.get('failures',0)+(outcome not in ('pending','busy'))
        retry=0 if not retryable else 2 if outcome=='pending' else 300 if outcome=='busy' else min(14400,300*2**min(failures-1,6))
        state[key].update(status=outcome,reason=reason,retryable=retryable,httpStatus=code,failures=failures,at=datetime.now(TZ).isoformat(),lastObservedAt=datetime.now(timezone.utc).isoformat(),retryAfter=time.time()+retry if retry else 0)
        atomic(state_path,state)
        if outcome=='complete':completed+=1
        else:deferred[port]=outcome
    missing=[{k:state[key].get(k) for k in ('query','family','status','reason','retryable','failures','retryAfter')} for key,args in work if key in state and state[key].get('status')!='complete']
    unobserved=sum(key not in state for key,args in work)
    result=dict(status='deferred' if missing or unobserved else 'budget_finished',completed=completed,reused=reused,seconds=round(time.monotonic()-begin,3),missingCount=len(missing),unobservedCount=unobserved,terminalCount=sum(v.get('retryable') is False for v in missing),repeatedFailureCount=sum(v.get('failures',0)>=3 for v in missing),missing=missing[:64],stateFile=str(state_path))
    if deferred:result.update(reason=next(iter(deferred.values())),deferredSources=deferred)
    return result


def main():
    import fcntl
    parser=argparse.ArgumentParser();parser.add_argument('--seed',action='store_true');parser.add_argument('--daily',action='store_true');parser.add_argument('--scheduled',action='store_true');args=parser.parse_args()
    store=Archive();store.safe(True)
    with (ROOT/'scheduler.lock').open('a+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:print('{"status":"deferred","reason":"archive_job_running"}');return
        if args.seed:result=import_existing(store)
        elif args.scheduled:
            now=datetime.now(TZ)
            if now.hour==0:result={'daily':run_once(True,480)}
            else:result={'daily':run_once(True,120),'history':run_once(False,360)}
            result['cleanup']=store.prune(False)
        else:result=run_once(args.daily)
        atomic(ROOT/'job-status.json',dict(result,at=datetime.now(TZ).isoformat()))
        print(json.dumps(result))


if __name__=='__main__':main()
