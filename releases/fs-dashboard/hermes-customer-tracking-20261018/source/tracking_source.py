"""Session-side private ES archive and exact Admin paid-order join.

This module only accepts injected authenticated read callbacks. It never logs
raw rows or exposes a generic URL, SQL, or browser credential interface.
"""
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import urlencode

from customer_tracking import EMAIL, candidate_rows, checked_config, game_scope, money

MAX_FILE = 32*1024*1024
MAX_ROWS = 200000
MAX_PAGES = 300
ARCHIVE = Path('/var/lib/fc27-es-exports')


def private_es_day(day, root=ARCHIVE):
    """Read original XLSX only after the existing archive's private-file checks."""
    from es_order_structure import parse_files
    if date.fromisoformat(day).isoformat()!=day:raise ValueError('tracking_day')
    root=Path(root)
    if any(path.is_symlink() for path in (root,*root.parents)):raise ValueError('archive_link')
    if not root.is_dir():return {'status':'unavailable','reason':'es_archive_missing'}
    if os.name=='posix' and (root.stat().st_uid!=os.geteuid() or root.stat().st_mode&0o077):raise ValueError('archive_permissions')
    manifests=[]
    for path in root.glob('*.json'):
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>1024*1024 or os.name=='posix' and (info.st_uid!=os.geteuid() or info.st_mode&0o077):
            raise ValueError('archive_manifest_integrity')
        value=json.loads(path.read_text('utf-8'))
        q=value.get('query') or {}
        if (q.get('start'),q.get('end'))==(day,day):manifests.append(value)
    if not manifests:return {'status':'unavailable','reason':'es_archive_day_missing'}
    manifest=max(manifests,key=lambda item:item.get('captured_at',''))
    files=[];digests=manifest.get('file_sha256')
    if not isinstance(digests,list) or not 1<=len(digests)<=20:raise ValueError('archive_file_set')
    expected_version=hashlib.sha256(json.dumps({'files':digests,'rule':manifest.get('rule_version')},sort_keys=True).encode()).hexdigest()
    if manifest.get('source_version')!=expected_version:raise ValueError('archive_source_version')
    for digest in digests:
        if not isinstance(digest,str) or not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('archive_digest')
        path=root/(digest+'.xlsx');info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>MAX_FILE or os.name=='posix' and (info.st_uid!=os.geteuid() or info.st_mode&0o077):
            raise ValueError('archive_file_integrity')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('archive_hash_mismatch')
        files.append(raw)
    rows,hashes,failures=parse_files(files)
    coverage=manifest.get('file_set') or {}
    complete=failures==0 and coverage.get('failed_files')==0 and coverage.get('declared_files')==len(files)
    return {'status':'available' if complete else 'partial','rows':rows,
        'captured_at':manifest.get('captured_at'),'source_version':manifest.get('source_version'),
        'coverage':{'file_set_complete':complete,'declared_files':coverage.get('declared_files'),
            'read_files':len(files),'parse_failures':failures,'rows':len(rows)}}


def admin_paid_day(request,day,profile,wanted):
    """Use the verified full-day Admin contract, then exact-match order_no locally."""
    gid,_=game_scope(profile)
    if date.fromisoformat(day).isoformat()!=day or not isinstance(wanted,set) or len(wanted)>MAX_ROWS:
        raise ValueError('admin_day_query')
    if not wanted:
        return {'status':'available','orders':{},'coverage':{'source_total':None,
            'received':0,'pages':[],'complete':True,'matched_candidate_orders':0,
            'candidate_orders_requested':0,'missing_candidate_orders':0,
            'admin_read_skipped':'no ES rows pass product, discount and customer-flag prefilter'}}
    found={};seen_ids={};previous_id=None;expected=None;raw_count=0;pages=[];deadline=time.monotonic()+850
    for page in range(1,MAX_PAGES+1):
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        filters=[('gid',gid,'='),('site_id',266,'='),('pay_status',1,'='),
                 ('paytime',day+' 00:00:00,'+day+' 23:59:59','RANGE')]
        params={'page':page,'limit':100,'order':'id,desc'}
        for index,(field,value,operator) in enumerate(filters):
            params.update({f'search[{index}][field]':field,f'search[{index}][val]':value,
                f'search[{index}][operator]':operator})
            if operator=='RANGE':params[f'search[{index}][render]']='datetime'
        code,raw=request('/admin/order.Order/index?'+urlencode(params),min(10,remaining))
        if code in (401,403):raise PermissionError('admin_identity_unavailable')
        if code!=200 or len(raw)>8*1024*1024:raise ValueError('admin_day_response')
        value=json.loads(raw);data=value.get('data') if value.get('code')==1 else None
        if not isinstance(data,dict) or type(data.get('total')) is not int or not isinstance(data.get('list'),list):
            raise ValueError('admin_day_contract')
        total=data['total'];batch=data['list']
        if total<0 or len(batch)>100 or expected is not None and total!=expected:raise ValueError('admin_day_pagination')
        if expected is None:expected=total
        ids=[]
        for row in batch:
            if str(row.get('gid'))!=str(gid) or str(row.get('site_id'))!='266' or str(row.get('pay_status'))!='1':
                raise ValueError('admin_day_scope')
            ident=row.get('id');order=row.get('order_no')
            if not str(ident).isdigit() or not isinstance(order,str):raise ValueError('admin_day_identity')
            when=row.get('paytime')
            if not isinstance(when,str) or not when.startswith(day+' '):raise ValueError('admin_day_time')
            ident=int(ident);ids.append(ident)
            row_sha=hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if ident in seen_ids and seen_ids[ident]!=row_sha:raise ValueError('admin_day_duplicate_conflict')
            seen_ids[ident]=row_sha
            if order not in wanted:continue
            projection={key:row.get(key) for key in ('order_no','gid','site_id','pay_status','email','uid','amount')}
            if order in found and found[order]!=projection:raise ValueError('admin_order_conflict')
            found[order]=projection
        if ids!=sorted(ids,reverse=True) or ids and previous_id is not None and ids[0]>previous_id:
            raise ValueError('admin_day_sort_or_duplicate')
        if ids:previous_id=ids[-1]
        raw_count+=len(batch);pages.append({'page':page,'rows':len(batch),'source_total':total})
        if raw_count>=total:break
        if not batch:raise ValueError('admin_day_empty_page')
    complete=expected is not None and raw_count==expected
    return {'status':'available' if complete else 'partial','orders':found,
        'coverage':{'source_total':expected,'received':raw_count,'unique_source_ids':len(seen_ids),'pages':pages,
            'complete':complete,'matched_candidate_orders':len(found),
            'candidate_orders_requested':len(wanted),
            'missing_candidate_orders':len(wanted-set(found))}}


def scan_day(request,day,config,root=ARCHIVE):
    """Private session call. The caller may publish only Admin-gated results."""
    config=checked_config(config)
    archive=private_es_day(day,root)
    if archive['status']=='unavailable':return archive
    if archive['status']!='available':return {'status':'partial','reason':'es_archive_incomplete',
        'coverage':archive['coverage'],'captured_at':archive['captured_at']}
    # Filter product, discount and customer flag before the full-day Admin join.
    from customer_tracking import classify
    prelim=[item for row in archive['rows'] if (item:=classify(row,config)[0]) is not None]
    admin=admin_paid_day(request,day,config['profile'],{item['order_no'] for item in prelim})
    if admin['status']!='available':return {'status':'partial','reason':'admin_paid_day_incomplete',
        'coverage':{'es':archive['coverage'],'admin':admin['coverage']},'captured_at':archive['captured_at']}
    items,criteria=candidate_rows(archive['rows'],admin['orders'],config)
    return {'status':'available','date':day,'captured_at':datetime.now(timezone.utc).isoformat(),
        'source_version':archive['source_version'],'items':items,
        'coverage':{'es':archive['coverage'],'admin':admin['coverage'],'criteria':criteria},
        'private':True}


def admin_email_history(request,email,selected_profile,start=None,end=None):
    """Search broadly upstream, then require exact customer email locally.

    Only a private, server-resolved tracked email may reach this function.
    No payment-email fallback, no arbitrary search-term API, no fabricated full
    coverage after pagination or date ambiguity.
    """
    if not isinstance(email,str) or not EMAIL.fullmatch(email) or len(email)>254:
        raise ValueError('tracked_email')
    if (start is None)!=(end is None):raise ValueError('history_period')
    if start is not None and (date.fromisoformat(start).isoformat()!=start or date.fromisoformat(end).isoformat()!=end or start>end):
        raise ValueError('history_period')
    selected_gid,_=game_scope(selected_profile)
    deadline=time.monotonic()+850;expected=None;seen_ids={};previous_id=None;raw_count=0;orders_by_no={};conflicts=set()
    pages=[];excluded_email=excluded_site=unknown_time=0
    for page in range(1,MAX_PAGES+1):
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        path='/admin/order.Order/index?'+urlencode({'limit':100,'page':page,'order':'id,desc','quick_search':email})
        code,raw=request(path,min(10,remaining))
        if code in (401,403):raise PermissionError('admin_identity_unavailable')
        if code!=200 or len(raw)>8*1024*1024:raise ValueError('history_response')
        value=json.loads(raw);data=value.get('data') if value.get('code')==1 else None
        if not isinstance(data,dict) or type(data.get('total')) is not int or not isinstance(data.get('list'),list):
            raise ValueError('history_contract')
        total=data['total'];batch=data['list']
        if total<0 or len(batch)>100 or expected is not None and expected!=total:raise ValueError('history_pagination')
        if expected is None:expected=total
        ids=[]
        for row in batch:
            ident=row.get('id');order=row.get('order_no')
            if not str(ident).isdigit() or not isinstance(order,str):raise ValueError('history_identity')
            ident=int(ident);ids.append(ident)
            row_sha=hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if ident in seen_ids and seen_ids[ident]!=row_sha:raise ValueError('history_duplicate_conflict')
            seen_ids[ident]=row_sha
            if row.get('email')!=email:excluded_email+=1;continue
            if str(row.get('site_id'))!='266':excluded_site+=1;continue
            when=row.get('paytime')
            if start is not None:
                if not isinstance(when,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} .*',when):
                    unknown_time+=1;continue
                if not start<=when[:10]<=end:continue
            usd=money(row.get('amount'))
            projection={'order_no':order,'email':email,'uid':int(row['uid']) if str(row.get('uid')).isdigit() else None,
                'gid':row.get('gid'),'site_id':266,'pay_status':row.get('pay_status'),
                'order_usd':str(usd) if usd is not None else None,'order_usd_source':'Admin',
                'paid_at':when if isinstance(when,str) and when else None,
                'current_status':str(row.get('status_format') or row.get('status') or 'unknown')[:80],
                'selected_game':str(row.get('gid'))==str(selected_gid),
                'discount_usd':None,'discount_source':'ES not joined for this history order',
                'payment':{'amount':None,'currency':None}}
            if order in conflicts:continue
            if order in orders_by_no and orders_by_no[order]!=projection:
                conflicts.add(order);orders_by_no.pop(order)
            else:orders_by_no[order]=projection
        if ids!=sorted(ids,reverse=True) or ids and previous_id is not None and ids[0]>previous_id:
            raise ValueError('history_sort_or_duplicate')
        if ids:previous_id=ids[-1]
        raw_count+=len(batch);pages.append({'page':page,'rows':len(batch),'source_total':total})
        if raw_count>=total:break
        if not batch:raise ValueError('history_empty_page')
    orders=list(orders_by_no.values())
    complete=expected is not None and raw_count==expected and not unknown_time and not conflicts
    return {'status':'available' if complete else 'partial','orders':orders,
        'coverage':{'quick_search_is_broad':True,'customer_email_exact':True,'site_id':266,
            'source_total':expected,'received':raw_count,'unique_source_ids':len(seen_ids),'complete':complete,'pages':pages,
            'excluded_nonmatching_email':excluded_email,'excluded_other_site':excluded_site,
            'unknown_date_excluded':unknown_time,'conflicting_order_numbers':len(conflicts),
            'selected_game_orders':sum(item['selected_game'] for item in orders),
            'other_game_orders':sum(not item['selected_game'] for item in orders),
            'currency_and_discount_not_inferred':True}}
