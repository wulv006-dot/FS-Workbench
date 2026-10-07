"""Bounded daily-native gap queue; no credentials, HTTP, timers or UI operations."""
from pathlib import Path
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib, json, os, re, time
from profit_daily import normalise, merge, stamp
from profit_reader_adapter import adapt_reader, failed_attempt

ACTIVE_EXCLUDED = frozenset({'FC26'})
MAX_REQUESTS = 12
RECENT_DAYS = 7
HISTORY_DAYS = 90
RETRY_SECONDS = 3600
CACHE_SCAN_SECONDS = 3
CACHE_SCAN_FILES = 512
CACHE_TOTAL_BYTES = 32 * 1024 * 1024
CACHE_FILE_BYTES = 1024 * 1024

def mapping(value, code):
    if not isinstance(value,dict):raise ValueError(code)
    return value

def checked_source(source):
    source=mapping(source,'optional_source_structure')
    mapping(source.get('period'),'optional_period_structure')
    mapping(source.get('filters'),'optional_filters_structure')
    metrics=mapping(source.get('metrics'),'optional_metrics_structure')
    mapping(metrics.get('profitMarginPct',{}),'optional_margin_structure')
    stamp(source['capturedAt'])
    return source

def active_keys(expected):
    return [key for key in expected if key not in ACTIVE_EXCLUDED]

def window(today):
    return {'start':str(today-timedelta(days=RECENT_DAYS)),
            'end':str(today-timedelta(days=1)), 'timezone':'Asia/Shanghai',
            'period':{'start':str(today-timedelta(days=RECENT_DAYS))+' 00:00',
                      'end':str(today)+' 00:00'}}

def request(key, day, expected):
    c=expected[key]
    return dict(key='profit-daily:'+key+':'+str(day),profileKey=key,date=str(day),
                gid=c['gid'],tid=c['tid'],status=c['status'],
                start=str(day)+' 00:00',end=str(day+timedelta(days=1))+' 00:00')

def cache_record(data, expected, today):
    """Accept complete native scopes only, never split a multiday percentage."""
    data=mapping(data,'cache_structure')
    q=mapping(data.get('query'),'cache_query_structure');key=q.get('profile')
    if not isinstance(key,str):raise ValueError('cache_profile_key_structure')
    if (data.get('status')!='available' or data.get('schemaVersion')!=1
        or data.get('consistentPeriod') is not True or q.get('analysis')
        or q.get('grain')!='day' or key not in expected):
        raise ValueError('cache_envelope')
    lo=date.fromisoformat(q['start']);hi=date.fromisoformat(q['end'])
    if not lo<=hi<today or (hi-lo).days>=HISTORY_DAYS:raise ValueError('cache_window')
    period=dict(start=str(lo)+' 00:00',end=str(hi+timedelta(days=1))+' 00:00')
    profile=mapping(data.get('profile'),'cache_profile_structure')
    source=checked_source(profile.get('primary'));c=expected[key]
    filters=dict(gid=c['gid'],tid=c['tid'],status=c['status'],
                 start_paytime=period['start'],end_paytime=period['end'])
    if (q.get('period')!=period or source.get('period')!=period
        or source.get('system')!='order.p2pah.cn'
        or source.get('endpoint')!='/stats/admin_order/index.html'
        or source.get('status')!='available' or source.get('labelsVerified') is not True
        or source.get('normalisedScope')!=c['sites'] or source.get('filters')!=filters
        or source.get('timezone')!='Asia/Shanghai' or source.get('currency')!='USD'
        or stamp(source['capturedAt']).astimezone(timezone(timedelta(hours=8))).date()<=hi):
        raise ValueError('cache_source_scope_period')
    selected=dict(profileKey=key,start=str(lo),end=str(hi),capturedAt=source['capturedAt'])
    if lo!=hi:return None,selected
    raw=adapt_reader(source,dict(profileKey=key,date=str(lo)),expected)
    raw['collectionKind']='existing_verified_exact_range_cache'
    if normalise(raw,expected)['status']!='available':raise ValueError('cache_margin_not_provided')
    return raw,selected

def load_caches(root, expected, today, clock=time.monotonic, scan_seconds=CACHE_SCAN_SECONDS):
    """Read only the existing private cache, with file/time/byte limits and inner SHA."""
    started=clock();audit=dict(scanned=0,acceptedSingleDayFiles=0,ignored=0,
                             bytesRead=0,stopReason='complete',imported=[])
    records=[];selected=[]
    root=Path(root)
    if not root.is_dir():return records,selected,audit
    files=[]
    # Existing cache has its own 2048-file bound; do not scan unrelated directories.
    for p in root.iterdir():
        if clock()-started>=scan_seconds:audit['stopReason']='scan_deadline';break
        try:
            if re.fullmatch(r'[a-f0-9]{64}\.json',p.name) and not p.is_symlink() and p.is_file():
                files.append((p.stat().st_mtime,p))
        except OSError:audit['ignored']+=1
    files.sort(key=lambda pair:pair[0],reverse=True)
    for _,p in files[:CACHE_SCAN_FILES]:
        if clock()-started>=scan_seconds:audit['stopReason']='scan_deadline';break
        try:size=p.stat().st_size
        except OSError:audit['ignored']+=1;continue
        if size>CACHE_FILE_BYTES:audit['ignored']+=1;continue
        if audit['bytesRead']+size>CACHE_TOTAL_BYTES:audit['stopReason']='byte_budget';break
        audit['scanned']+=1
        try:
            fd=os.open(str(p),os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
            with os.fdopen(fd,'rb') as f:body=f.read(CACHE_FILE_BYTES+1)
            if len(body)>CACHE_FILE_BYTES:raise ValueError('cache_too_large')
            audit['bytesRead']+=len(body)
            data=mapping(json.loads(body),'cache_structure');given=data.pop('resultSha256',None)
            canonical=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
            if given!=hashlib.sha256(canonical).hexdigest():raise ValueError('cache_inner_sha')
            raw,chosen=cache_record(data,expected,today);selected.append(chosen)
            if raw:
                records.append(raw);audit['acceptedSingleDayFiles']+=1
                audit['imported'].append(dict(name=p.name,sha256=hashlib.sha256(body).hexdigest(),
                    profileKey=raw['profileKey'],date=raw['date'],capturedAt=raw['capturedAt'],
                    sourceBaseSnapshotId=data.get('baseSnapshotId')))
        except (OSError,ValueError,KeyError,TypeError,AttributeError,OverflowError):audit['ignored']+=1
    if len(files)>CACHE_SCAN_FILES and audit['stopReason']=='complete':audit['stopReason']='file_budget'
    audit['elapsedSeconds']=max(0,clock()-started)
    return records,selected,audit

def merge_cached(previous, records, expected):
    # Persisted history validation is deliberately outside optional-record isolation.
    # Corrupt authoritative history must fail explicitly, not be masked by a seed fallback.
    rows=merge(previous,[],expected);ignored=0
    if not isinstance(records,(list,tuple)):return rows,1
    valid=[]
    for raw in records:
        try:
            raw=mapping(raw,'optional_record_structure')
            mapping(raw.get('period'),'optional_period_structure')
            mapping(raw.get('filters'),'optional_filters_structure')
            mapping(raw.get('profitMarginPct',{}),'optional_margin_structure')
            normalise(raw,expected)
            valid.append(raw)
        except (ValueError,KeyError,TypeError,AttributeError,OverflowError):ignored+=1
    for raw in sorted(valid,key=lambda r:stamp(r['capturedAt'])):
        try:rows=merge(rows,[raw],expected)
        except (ValueError,KeyError,TypeError,AttributeError,OverflowError):ignored+=1
    return rows,ignored

def plan_requests(today, previous, expected, selected=(), now=None, limit=MAX_REQUESTS):
    """Recent gaps first, then selected complete windows, then a rolling 90-day backlog."""
    if not isinstance(today,date) or isinstance(today,datetime):raise ValueError('today_date_required')
    if type(limit) is not int or not 0<=limit<=MAX_REQUESTS:raise ValueError('request_limit')
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('now_timezone_required')
    previous=merge(previous,[],expected);by={(r['profileKey'],r['date']):r for r in previous}
    active=active_keys(expected);rank={key:i for i,key in enumerate(active)}
    floor=today-timedelta(days=HISTORY_DAYS);recent=today-timedelta(days=RECENT_DAYS)
    chosen=set()
    for item in selected:
        try:
            key=item['profileKey'];lo=max(floor,date.fromisoformat(item['start']));hi=min(today-timedelta(days=1),date.fromisoformat(item['end']))
            if key not in rank or hi<lo or (hi-lo).days>=HISTORY_DAYS:continue
            for n in range((hi-lo).days+1):chosen.add((key,str(lo+timedelta(days=n))))
        except (ValueError,KeyError,TypeError):continue
    queue=[];missing_recent=0;cooldown=0
    for key in active:
        for n in range(1,HISTORY_DAYS+1):
            day=today-timedelta(days=n);old=by.get((key,str(day)))
            if old and old['status']=='available' and not old.get('stale'):continue
            is_recent=day>=recent
            if is_recent:missing_recent+=1
            attempt=stamp(old.get('latestAttemptAt',old['capturedAt'])) if old else None
            if attempt and (now-attempt).total_seconds()<RETRY_SECONDS:
                cooldown+=1;continue
            tier=0 if is_recent else 1 if (key,str(day)) in chosen else 2
            # Unattempted gaps progress before repeatedly failing entries in the same tier.
            # New gaps: newest complete day first. Retried gaps: oldest attempt first.
            # Date cannot permanently starve an older failed day inside its priority tier.
            order=(tier,1 if attempt else 0,attempt.timestamp() if attempt else -day.toordinal(),-day.toordinal(),rank[key])
            queue.append((order,request(key,day,expected)))
    queue.sort(key=lambda row:row[0])
    return [item for _,item in queue[:limit]],dict(
        contractId='order-native-daily-backfill-v1',window=window(today),
        activeProfiles=active,excludedActiveProfiles=sorted(ACTIVE_EXCLUDED.intersection(expected)),
        missingRecentProfileDays=missing_recent,totalEligibleGapDays=len(queue),
        plannedRequests=min(len(queue),limit),deferredEligibleGapDays=max(0,len(queue)-limit),
        retryCooldownSeconds=RETRY_SECONDS,cooldownGapDays=cooldown,
        historyLookbackDays=HISTORY_DAYS,maxRequestsPerCycle=MAX_REQUESTS,
        note='Existing FC26 history retained. No interval percent copied into daily points.')

SAFE_FAILURE_CODES=frozenset({
    'invalid_metric','primary_login_or_page_unavailable','primary_filter_mismatch',
    'primary_metric_labels_mismatch','primary_average_mismatch','primary_series_unavailable',
    'primary_series_dates_unavailable','primary_series_length_mismatch','primary_series_schema_unverified',
    'primary_hour_outside_period','primary_day_outside_period','primary_date_label_ambiguous',
    'primary_date_label_unverified','primary_duplicate_date_label','primary_mixed_date_granularity',
    'primary_series_totals_mismatch','primary_zero_sentinel_scope_unverified',
    'primary_zero_sentinel_nonzero','primary_zero_sentinel_position_unverified',
    'native_daily_read_timeout','native_daily_read_failed'})

def safe_result_reason(value):
    return value if isinstance(value,str) and value in SAFE_FAILURE_CODES else 'native_daily_read_failed'

def add_reason(audit,field,code):
    counts=audit.setdefault(field,{})
    counts[code]=counts.get(code,0)+1

def apply_results(wanted, results, expected):
    records=[];audit=dict(attempted=0,available=0,failed=0,deferred=0,rejected=0,failureReasonCounts={},rejectionReasonCounts={},zeroEndpointExclusions=0)
    if not isinstance(results,dict):
        audit.update(deferred=len(wanted),batchProgressUnknown=True,batchRejected=True)
        return records,audit
    for item in wanted:
        source=results.get(item['key'])
        if source is None:
            audit['deferred']+=1;continue
        if not isinstance(source,dict):
            audit['rejected']+=1;add_reason(audit,'rejectionReasonCounts','native_daily_result_shape_invalid');continue
        if source.get('status')=='not_started_budget':audit['deferred']+=1;continue
        known_at=source.get('attemptedAt') if source.get('status')!='available' else source.get('capturedAt')
        try:
            # Reject bad/naive source times now; never invent an unknown day's attempt time.
            stamp(known_at)
        except (ValueError,KeyError,TypeError,AttributeError,OverflowError):
            audit['rejected']+=1;add_reason(audit,'rejectionReasonCounts','native_daily_timestamp_unverified');continue
        audit['attempted']+=1
        failure_code=safe_result_reason(source.get('errorCode')) if source.get('status')!='available' else 'native_daily_contract_invalid'
        try:
            if source.get('status')!='available':raise ValueError('native_unavailable')
            checked_source(source)
            raw=adapt_reader(source,item,expected)
            if normalise(raw,expected)['status']!='available':
                failure_code='native_daily_margin_not_provided';raise ValueError('margin_not_provided')
            records.append(raw);audit['available']+=1
            boundary=source.get('seriesBoundaryAudit')
            if isinstance(boundary,dict) and boundary.get('schemaVersion')==1 and boundary.get('contractId')=='order-hour-zero-exclusive-end-sentinel-v1' and boundary.get('exclusiveEndPreserved') is True and type(boundary.get('excludedZeroEndpointCount')) is int and boundary['excludedZeroEndpointCount'] in (0,1):
                audit['zeroEndpointExclusions']+=boundary['excludedZeroEndpointCount']
        except (KeyError,ValueError,TypeError,AttributeError,OverflowError):
            failed=failed_attempt(item,expected)
            failed['capturedAt']=known_at
            records.append(failed);audit['failed']+=1;add_reason(audit,'failureReasonCounts',failure_code)
    return records,audit

def coverage(today, daily, expected):
    chosen=window(today);rows=[]
    by={(r['profileKey'],r['date']):r for r in daily}
    for key in active_keys(expected):
        present=[];missing=[];stale=[]
        for n in range(RECENT_DAYS,0,-1):
            day=str(today-timedelta(days=n));r=by.get((key,day))
            if r and r['status']=='available':
                present.append(day)
                if r.get('stale'):stale.append(day)
            else:missing.append(day)
        rows.append(dict(profileKey=key,providedDates=present,missingDates=missing,
                         staleDates=stale,status='complete' if not missing and not stale else 'partial'))
    return dict(contractId='order-native-daily-coverage-v1',window=chosen,profiles=rows,
                excludedActiveProfiles=sorted(ACTIVE_EXCLUDED.intersection(expected)))
