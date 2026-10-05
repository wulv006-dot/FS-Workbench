"""Consume the existing loopback range service; never read source credentials or collect orders."""
import copy,datetime as dt,hashlib,json,os,tempfile,time,urllib.request,urllib.parse,urllib.error
from decimal import Decimal
from pathlib import Path
import weekly_report as w

ENDPOINT='http://127.0.0.1:8931/range'
BASE=Path('/var/www/dashboard/fs-home/transactions/current.json')
INPUTS=Path('/opt/mmoexp-weekly-report/input-ranges')

def validate(value,key,p,base):
    if value.get('isMock') or value.get('schemaVersion')!=1 or value.get('status')!='available' or value.get('consistentPeriod') is not True:raise ValueError('EXACT_RANGE_NOT_AVAILABLE')
    clean=copy.deepcopy(value);digest=clean.pop('resultSha256',None)
    if w.sha(w.encoded(clean))!=digest:raise ValueError('EXACT_RANGE_SHA_MISMATCH')
    query=value['query']
    if value.get('baseSnapshotId')!=base or query.get('baseSnapshotId')!=base:raise ValueError('EXACT_RANGE_BASE_CHANGED')
    if query.get('profile')!=key or query.get('grain')!='day' or query.get('start')!=p['start'] or query.get('end')!=p['end'] or value.get('rangeId')!=w.sha(w.encoded(query)):raise ValueError('EXACT_RANGE_QUERY_MISMATCH')
    if value.get('scopeContractId')!=w.CONTRACT or value.get('currency')!='USD' or value.get('timezone')!='Asia/Shanghai':raise ValueError('EXACT_RANGE_SCOPE_MISMATCH')
    profile=value['profile']
    if profile.get('key')!=key or not w.exact(profile,p) or not w.exact(profile['primary'],p) or not w.exact(profile['supplement'],p):raise ValueError('EXACT_RANGE_PERIOD_MISMATCH')
    if profile['primary'].get('system')!='order.p2pah.cn' or profile['primary'].get('status')!='available' or profile['supplement'].get('system')!='admin.p2pah.cn' or profile['supplement'].get('status')!='available':raise ValueError('EXACT_RANGE_SOURCE_UNAVAILABLE')
    return value

def daily_rows(rows,p):
    days={}
    for row in rows:
        stamp=row.get('date','')[:10]
        # Upstream chart includes an empty tick at the excluded end midnight.
        # Drop only that proved zero endpoint; reject other out-of-range values.
        if row.get('date')==p['endExclusive']+' 00:00' and row.get('orders')==0 and row.get('amount')==0:continue
        if len(stamp)!=10 or not p['start']<=stamp<=p['end']:raise ValueError('EXACT_RANGE_ROW_OUTSIDE_WEEK')
        for key in ['orders','amount']:
            if not w.finite(row.get(key)):raise ValueError('EXACT_RANGE_ROW_INVALID')
        total=days.setdefault(stamp,{'date':stamp,'orders':0,'amount':Decimal(0)})
        total['orders']+=row['orders'];total['amount']+=Decimal(str(row['amount']))
    return [{**item,'amount':float(item['amount'])} for item in sorted(days.values(),key=lambda x:x['date'])]

def adapt(results,p,base):
    if set(results)!=set(w.PROFILES):raise ValueError('EXACT_RANGE_NINE_PROFILES_REQUIRED')
    refs={key:{'rangeId':value['rangeId'],'resultSha256':value['resultSha256'],'generatedAt':value['generatedAt']} for key,value in results.items()}
    identifier='week-'+p['id']+'-'+w.sha(w.encoded(refs))[:16]
    generated=max(value['generatedAt'] for value in results.values())
    value={'schemaVersion':2,'supplementContractVersion':1,'isMock':False,'snapshotId':identifier,'scope': 'all-websites','scopeContractId':w.CONTRACT,'currency':'USD','timezone':'Asia/Shanghai','generatedAt':generated,'generatedAtShanghai':w.parse_time(generated).isoformat(),'profiles':{},'dashboard':{'profiles':{}},'reportRange':{'start':p['startAt'],'endExclusive':p['endExclusiveAt'],'boundary':'[start,end)','complete':True,'coreAggregation':'order-native','provider':'fs-business-range.service','baseSnapshotId':base,'rangeReferences':refs}}
    for key,result in results.items():
        validate(result,key,p,base)
        profile=copy.deepcopy(result['profile']);value['profiles'][key]=profile
        value['dashboard']['profiles'][key]={'series':daily_rows(profile['primary'].get('rows',[]),p),'hourly':[]}
    w.business(value,p) # enforce all four native core values before certification/write
    return value

def private_write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);path.parent.chmod(0o700)
    fd,name=tempfile.mkstemp(prefix='.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.chmod(name,0o600);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def read_request(params):
    # Root-only server consumer of the existing loopback read service. This marker
    # is not a user/account/credential and is never accepted on the public route.
    request=urllib.request.Request(ENDPOINT+'?'+urllib.parse.urlencode(params),headers={'X-Auth-User':'server-weekly-readonly'})
    try:
        with urllib.request.urlopen(request,timeout=15) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as error:return error.code,json.load(error)
    except (urllib.error.URLError,TimeoutError):raise ValueError('EXACT_RANGE_SERVICE_UNAVAILABLE')

def fetch_week(p,base,inputs=INPUTS,event=None):
    results={};started=0
    for key in w.PROFILES:
        params={'profile':key,'start':p['start'],'end':p['end'],'grain':'day','snapshotId':base};deadline=time.monotonic()+330
        pause=max(0,11-(time.monotonic()-started))
        if pause:time.sleep(pause)
        started=time.monotonic()
        while True:
            status,value=read_request(params)
            if status==200:
                results[key]=validate(value,key,p,base)
                if event:event({'weekStart':p['start'],'profile':key,'status':'verified','rangeId':value['rangeId'],'sourceGeneratedAt':value['generatedAt']})
                break
            if status==409:raise ValueError('EXACT_RANGE_BASE_CHANGED')
            if status not in [202,429,503] or time.monotonic()>=deadline:raise ValueError('EXACT_RANGE_REQUEST_NOT_READY')
            wait=max(2,min(30,value.get('retryAfter',30 if status==503 else 3)))
            if event:event({'weekStart':p['start'],'profile':key,'status':'waiting','httpStatus':status,'retryAfter':wait})
            time.sleep(wait)
    value=adapt(results,p,base);folder=inputs/p['id'];relative='snapshots/'+value['snapshotId']+'/snapshot.json';raw=w.encoded(value)
    target=folder/relative
    if target.exists() and target.read_bytes()!=raw:raise ValueError('EXACT_RANGE_IMMUTABLE_CONFLICT')
    if not target.exists():private_write(target,raw)
    manifest={'schemaVersion':2,'snapshotId':value['snapshotId'],'path':relative,'sha256':w.sha(raw),'scopeContractId':w.CONTRACT,'generatedAt':value['generatedAt'],'baseSnapshotId':base}
    private_write(folder/'current.json',w.encoded(manifest))
    return folder/'current.json',refs_summary(value)

def refs_summary(value):return {'snapshotId':value['snapshotId'],'baseSnapshotId':value['reportRange']['baseSnapshotId'],'profilesVerified':len(value['profiles']),'rangeReferences':value['reportRange']['rangeReferences']}
