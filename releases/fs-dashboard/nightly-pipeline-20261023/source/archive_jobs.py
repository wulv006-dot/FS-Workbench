"""Bounded low-priority reads through existing routes, with durable read receipts."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError
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


def read_route(params,port=8931,path='/range'):
    request=Request('http://127.0.0.1:'+str(port)+path+'?'+urlencode(params),headers={'X-Auth-User':'wulv'})
    try:
        with build_opener(ProxyHandler({})).open(request,timeout=10) as response:
            raw=response.read(16*1024*1024+1)
            if len(raw)>16*1024*1024:raise ValueError('archive_route_size')
            return response.status,json.loads(raw)
    except HTTPError as error:
        if error.code not in (403,409,429,500,502,503,504):raise
        return error.code,{'status':'denied' if error.code==403 else 'busy' if error.code==429 else 'unavailable'}
    except (URLError,TimeoutError,ConnectionError):
        return 503,{'status':'unavailable','reason':'local_route_temporarily_unavailable'}


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
    if not daily and not 1<=now.hour<7:return {'status':'outside_idle_window'}
    state_path=ROOT/'scheduler-state.json'
    state=json.loads(state_path.read_text()) if state_path.is_file() else {}
    completed=0;begin=time.monotonic();definition=profiles();blocked={}
    for args in candidates(now.date(),definition,daily):
        if time.monotonic()-begin>=budget or not daily and datetime.now(TZ).hour>=7:break
        marketing=args['profile']=='marketing';key=hashlib.sha256(encoded({'cadence':'daily' if daily else 'history','query':args})).hexdigest()
        port=8935 if marketing else 8931
        if port in blocked:continue
        prior=state.get(key,{})
        if prior.get('retryAfter',0)>time.time():continue
        if daily and prior.get('status')=='complete' and prior.get('at','')[:10]==now.date().isoformat():continue
        native=args.get('archiveFamily')=='native'
        if not marketing:
            from live_summary import query
            selector=native_key(dict(args,grain='day'),definition[args['profile']]) if native else summary_key(query({k:[v] for k,v in args.items()},definition))
            if store.get('native' if native else 'summary',selector) is not None:continue
        params={k:v for k,v in args.items() if k!='archiveFamily' and (not marketing or k!='profile')}
        if native:
            code,catalog=read_route({'mode':'catalog'})
            if code!=200:return {'status':'deferred','reason':'catalog_unavailable','completed':completed}
            params['snapshotId']=catalog['catalogId']
        requested=prior.get('requestedAt') or datetime.now(timezone.utc).isoformat()
        attempt_at=prior.get('attemptStartedAt',requested) if prior.get('status')=='pending' else datetime.now(timezone.utc).isoformat()
        if daily and marketing and prior.get('status')!='pending':params['refresh']='true'
        state[key]=dict(query=args,status='pending',requestedAt=requested,attemptStartedAt=attempt_at,failures=prior.get('failures',0));atomic(state_path,state)
        deadline=min(begin+budget,time.monotonic()+90);outcome='pending'
        while time.monotonic()<deadline:
            code,value=read_route(params,port)
            params.pop('refresh',None)
            if code in (403,429):outcome=value['status'];break
            if (value.get('archive') or {}).get('refreshDeferred'):
                outcome='busy';break
            valid=(value.get('status')=='available') if marketing else code==200 and (complete_native(value) if native else complete_summary(value))
            capture=(value.get('archive') or {}).get('sourceCapturedAt') or value.get('generatedAt') or ''
            fresh=False
            try:fresh=datetime.fromisoformat(capture.replace('Z','+00:00'))>=datetime.fromisoformat(attempt_at)-timedelta(seconds=60)
            except (ValueError,TypeError):pass
            if valid and (not (daily and marketing) or fresh):outcome='complete';break
            if code in (500,502,503,504):outcome='unavailable';break
            time.sleep(2)
        failures=0 if outcome=='complete' else prior.get('failures',0)+1
        state[key].update(status=outcome,failures=failures,at=datetime.now(TZ).isoformat(),retryAfter=time.time()+(0 if not failures else min(14400,300*2**min(failures-1,6))))
        atomic(state_path,state)
        if outcome=='complete':completed+=1
        if outcome in ('busy','denied'):blocked[port]=outcome
    if blocked:return {'status':'deferred','reason':next(iter(blocked.values())),'completed':completed,'deferredSources':blocked}
    return {'status':'budget_finished','completed':completed,'seconds':round(time.monotonic()-begin,3)}


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
            elif 1<=now.hour<7:result={'daily':run_once(True,120),'history':run_once(False,360)}
            else:result={'status':'outside_idle_window'}
            result['cleanup']=store.prune(False)
        else:result=run_once(args.daily)
        atomic(ROOT/'job-status.json',dict(result,at=datetime.now(TZ).isoformat()))
        print(json.dumps(result))


if __name__=='__main__':main()
