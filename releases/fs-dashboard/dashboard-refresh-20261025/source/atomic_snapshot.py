"""Publish a validated, complete transaction snapshot; never fall back across sources.

Preparation only. The production collector and website-scope contract are not switched.
"""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import hashlib,json,os,tempfile
import math
from copy import deepcopy
from profit_daily import validate_history
from profit_reader_adapter import contracts_from_snapshot

class OrderSourceBusy(BlockingIOError):
    """The shared Order browser mutex was not acquired; no reader was started."""


SHANGHAI=timezone(timedelta(hours=8))

def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')

def atomic_write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o644);os.replace(tmp,path)
        if hasattr(os,'O_DIRECTORY'):
            directory=os.open(str(path.parent),os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def validate(value):
    if value.get('timezone')!='Asia/Shanghai' or value.get('currency')!='USD':
        raise ValueError('timezone_or_currency_unverified')
    if not value.get('scopeApproved') or not value.get('scopeContractId'):
        raise ValueError('website_scope_approval_pending')
    profiles=value.get('profiles')
    if not isinstance(profiles,dict) or set(profiles)!=set(value.get('requiredProfiles',[])) or not profiles:
        raise ValueError('incomplete_profiles')
    for profile in profiles.values():
        source=profile.get('primary',{})
        if source.get('system')!='order.p2pah.cn' or source.get('status')!='available':
            raise ValueError('primary_failed_no_admin_fallback')
        if not source.get('period') or not source.get('filters') or not source.get('capturedAt'):
            raise ValueError('primary_contract_incomplete')
        if source['period']!=profile.get('period'):
            raise ValueError('primary_period_mismatch')
        metrics=profile.get('metrics',{})
        for field in ['orders','revenueUsd']:
            item=metrics.get(field,{})
            number=item.get('value')
            if type(number) not in (int,float) or number<0 or item.get('source')!='primary':
                raise ValueError('invalid_primary_metric')
        if type(metrics['orders']['value']) is not int:
            raise ValueError('invalid_order_count')
        for field in ['averageOrderUsd','profitMarginPct','fulfillmentRatePct','minOrderAmountUsd','maxOrderAmountUsd','receiptsCny','goodsPaymentCny']:
            if field in metrics:
                item=metrics[field];n=item.get('value')
                if item.get('source')!='primary' or (n is not None and (type(n) not in (int,float) or not math.isfinite(n))):
                    raise ValueError('primary_optional_metric_source_invalid')
        supplemental=profile.get('supplement',{})
        extra=supplemental.get('metrics',{})
        if extra:
            if (supplemental.get('system')!='admin.p2pah.cn' or supplemental.get('status')!='available'
                or supplemental.get('period')!=source['period'] or not supplemental.get('capturedAt')
                or supplemental.get('normalisedScope')!=source.get('normalisedScope')):
                raise ValueError('supplement_fields_scope_or_period_mismatch')
            for item in extra.values():
                number=item.get('value')
                if item.get('source')!='supplement' or (number is not None and (type(number) not in (int,float) or not math.isfinite(number))):
                    raise ValueError('invalid_supplemental_field')
            share=extra.get('newCustomerSharePct',{}).get('value')
            numerator=extra.get('newCustomers',{}).get('value');denominator=extra.get('orders',{}).get('value')
            expected=100*numerator/denominator if numerator is not None and denominator else None
            if (expected is None and share is not None) or (expected is not None and (share is None or abs(share-expected)>1e-9)):
                raise ValueError('supplement_share_denominator_mismatch')
        new=metrics.get('newCustomers',{})
        if new.get('value') is not None:
            supplement=profile.get('supplement',{})
            if new.get('source')!='supplement' or type(new['value']) is not int or new['value']<0:
                raise ValueError('invalid_supplement_metric')
            if (supplement.get('system')!='admin.p2pah.cn' or supplement.get('status')!='available'
                or supplement.get('period')!=source['period'] or not supplement.get('capturedAt')
                or supplement.get('normalisedScope')!=source.get('normalisedScope')):
                raise ValueError('supplement_scope_or_period_mismatch')
    if 'profitHistory' in value:validate_history(value['profitHistory'],contracts_from_snapshot(value))
    encoded(value)  # Reject NaN/Infinity before creating any public file.

def publish(root,value,now=None):
    validate(value)
    root=Path(root)
    now=now or datetime.now(timezone.utc)
    payload=dict(value,generatedAt=now.isoformat(),generatedAtShanghai=now.astimezone(SHANGHAI).isoformat(),schemaVersion=2)
    digest=hashlib.sha256(encoded(payload)).hexdigest()
    version=now.strftime('%Y%m%dT%H%M%SZ')+'-'+digest[:16]
    payload['snapshotId']=version
    if 'profitHistory' in payload:
        payload['profitHistory']=deepcopy(payload['profitHistory'])
        payload['profitHistory']['snapshotId']=version
    if 'dashboard' in payload:
        payload['dashboard'].update(snapshotId=version,generatedAt=payload['generatedAtShanghai'],snapshotContract=payload['scopeContractId'])
    if 'fcOps' in payload:
        payload['fcOps'].update(snapshotId=version,generatedAt=payload['generatedAtShanghai'])
    body=encoded(payload)
    # Every reader pins this immutable path, so a new manifest cannot mix files.
    atomic_write(root/'snapshots'/version/'snapshot.json',body)
    if 'dashboard' in payload:
        atomic_write(root/'snapshots'/version/'dashboard.json',encoded(payload['dashboard']))
    if 'fcOps' in payload:
        atomic_write(root/'snapshots'/version/'daily.json',encoded(payload['fcOps']))
    # Legacy read endpoints share this single symlink. New clients always pin manifest ID.
    if os.name!='nt':
        link=root/'.current-files-stage'
        if link.is_symlink():link.unlink()
        link.symlink_to('snapshots/'+version,target_is_directory=True)
        os.replace(link,root/'current-files')
    manifest={'schemaVersion':2,'snapshotId':version,'path':'snapshots/'+version+'/snapshot.json',
              'sha256':hashlib.sha256(body).hexdigest(),'generatedAt':payload['generatedAt'],
              'generatedAtShanghai':payload['generatedAtShanghai'],'timezone':'Asia/Shanghai',
              'serverIntervalSeconds':7200,'clientCheckSeconds':60,'staleAfterSeconds':7200,
              'scopeContractId':payload['scopeContractId']}
    atomic_write(root/'current.json',encoded(manifest))
    return manifest

def run_once(root,collect,*,lock_name="collector.lock"):
    """Cloud collector owns a nonblocking lock. Failed attempts retain current.json."""
    import fcntl  # Linux production only; fail explicitly on unsupported environments.
    if lock_name not in ('collector.lock','transaction-snapshot.lock'):
        raise ValueError('unknown_snapshot_lock')
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    with (root/lock_name).open('a+b') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'skipped','reason':'already_running'}
        try:
            manifest=publish(root,collect())
            atomic_write(root/'attempt.json',encoded({'status':'success','snapshotId':manifest['snapshotId'],'at':datetime.now(timezone.utc).isoformat()}))
            return manifest
        except Exception as exc:
            if lock_name=='transaction-snapshot.lock' and isinstance(exc,OrderSourceBusy):
                atomic_write(root/'attempt.json',encoded({'status':'deferred','reason':'collector_busy','at':datetime.now(timezone.utc).isoformat()}))
                return {'status':'skipped','reason':'collector_busy'}
            # Do not archive exception strings: upstream clients could include credentials.
            atomic_write(root/'attempt.json',encoded({'status':'failed','reason':'collection_or_validation_failed','type':type(exc).__name__,'at':datetime.now(timezone.utc).isoformat()}))
            raise
