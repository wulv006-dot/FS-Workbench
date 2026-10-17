"""Bounded Admin ES file-set structure. No raw rows or authentication leave this module."""
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import time
import zipfile
from xml.etree import ElementTree as ET

RULE_VERSION='admin-es-structure-v1'
GROUPS=('source_game','product','country','payment','new_customer','status')
COLUMNS={'product':'产品类型','game':'游戏','order':'订单号','usd':'订单金额（美元）','paid':'实付金额','currency':'实付币种','status':'订单状态','payment_type':'支付大类','payment':'支付方式','time':'付款时间','new_customer':'是否新客户','source':'订单来源','country':'国家代码'}
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
MAX_FILE=32*1024*1024
MAX_ROWS=200000
SHANGHAI=timezone(timedelta(hours=8),'Asia/Shanghai')
MAX_ARCHIVE_BYTES=512*1024*1024
MAX_ARCHIVE_FILES=512
ARCHIVE_RESERVE_BYTES=64*1024*1024
ARCHIVE_LOCK=threading.RLock()


def checked_query(args):
    if set(args)-{'profile','start','end','group_by','status'} or not {'profile','start','end'}<=set(args):raise ValueError('es_query_fields')
    if args['profile']!='FC27':raise ValueError('es_profile')
    a,b=(date.fromisoformat(args[k]) for k in ('start','end'))
    if a.isoformat()!=args['start'] or b.isoformat()!=args['end'] or not 0<=(b-a).days<=30 or b>datetime.now(SHANGHAI).date():raise ValueError('es_period')
    group=args.get('group_by','source_game');status=args.get('status','all')
    if group not in GROUPS or not isinstance(status,str) or not status or len(status)>80 or re.search(r'[@<>\r\n]|https?://',status):raise ValueError('es_dimension')
    return dict(args,group_by=group,status=status)


def safe_label(value):
    value=str(value or '').strip()
    return 'unknown' if len(value)>120 or re.search(r'[@<>\r\n]|https?://|Bearer|Cookie|password|\d{10,}',value,re.I) else value or '未知'


def xlsx_rows(raw):
    if len(raw)>MAX_FILE:raise ValueError('es_file_size')
    with zipfile.ZipFile(io.BytesIO(raw)) as book:
        if len(book.infolist())>1000 or sum(v.file_size for v in book.infolist())>128*1024*1024:raise ValueError('es_expanded_size')
        def xml(name):
            data=book.read(name)
            if b'<!DOCTYPE' in data or b'<!ENTITY' in data:raise ValueError('es_xml_entities')
            return ET.fromstring(data)
        shared=[]
        if 'xl/sharedStrings.xml' in book.namelist():
            shared=[''.join(node.itertext()) for node in xml('xl/sharedStrings.xml').findall('m:si',NS)]
        sheets=sorted(n for n in book.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',n))
        if not sheets:raise ValueError('es_no_sheet')
        output=[]
        for sheet in sheets:
            header=None
            for row in xml(sheet).findall('m:sheetData/m:row',NS):
                values={}
                for cell in row.findall('m:c',NS):
                    ident=re.match(r'[A-Z]+',cell.get('r',''))
                    if not ident:raise ValueError('es_cell_reference')
                    if cell.find('m:f',NS) is not None:raise ValueError('es_formula_cell')
                    value=cell.findtext('m:v','',NS)
                    if cell.get('t')=='s':value=shared[int(value)]
                    elif cell.get('t')=='inlineStr':value=''.join(cell.find('m:is',NS).itertext())
                    values[ident[0]]=value
                if not any(values.values()):continue
                if header is None:
                    header=values
                    if len(set(header.values()))!=len(header) or not set(COLUMNS.values())<=set(header.values()):raise ValueError('es_missing_columns')
                    continue
                output.append({name:values.get(col,'') for col,name in header.items()})
                if len(output)>MAX_ROWS:raise ValueError('es_row_limit')
            if header is None:raise ValueError('es_missing_columns')
        return output


def amount(value):
    try:
        parsed=Decimal(str(value).strip())
        return parsed if parsed.is_finite() and abs(parsed)<Decimal('1e15') else None
    except (InvalidOperation,ValueError,TypeError):return None


def unavailable(args,reason='es_source_unavailable'):
    return {'schemaVersion':1,'kind':'es_order_structure','http_status':200,'status':'unavailable','period':{'start':args['start'],'end':args['end'],'timezone':'unverified'},'captured_at':None,'source_version':None,'scope':{'label':'Admin ES导出原范围','site_verified':False,'distribution_exclusion_verified':False},'structure_totals':None,'groups':[],'quality':{'reason':reason,'upstream_completeness':'unknown'},'missing_dimensions':['site','distribution_group','platform','cost','profit','customer_identity']}


def parse_files(files):
    allrows=[];hashes=[];parse_failures=0
    for raw in files:
        hashes.append(hashlib.sha256(raw).hexdigest())
        try:allrows.extend(xlsx_rows(raw))
        except (ValueError,KeyError,IndexError,zipfile.BadZipFile,ET.ParseError):parse_failures+=1
        if len(allrows)>MAX_ROWS:raise ValueError('es_row_limit')
    return allrows,hashes,parse_failures


def aggregate(files,args,declared_files=None,failed_files=0):
    return aggregate_rows(*parse_files(files),args,declared_files,failed_files)


def aggregate_rows(allrows,hashes,parse_failures,args,declared_files=None,failed_files=0):
    args=checked_query(args);result=unavailable(args)
    if not hashes or parse_failures==len(hashes):return dict(result,quality={'reason':'es_files_unreadable','declared_files':declared_files,'read_files':len(hashes),'parse_failures':parse_failures,'failed_files':failed_files,'upstream_completeness':'unknown'})
    by_order=defaultdict(dict);unkeyed=0
    for row in allrows:
        ident=row.get(COLUMNS['order'],'').strip()
        if not ident:unkeyed+=1;continue
        signature=hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        entry=by_order[ident].setdefault(signature,{'row':row,'records':0});entry['records']+=1
    ambiguous=sum(len(variants)>1 for variants in by_order.values());duplicates=sum(item['records']-1 for variants in by_order.values() for item in variants.values())
    selected=[];outside=0;unknown_time=0
    for variants in by_order.values():
        if len(variants)!=1:continue
        row=next(iter(variants.values()))['row']
        if row[COLUMNS['game']].strip()!='FC 27':continue
        if args['status']!='all' and row[COLUMNS['status']]!=args['status']:continue
        try:when=datetime.strptime(row[COLUMNS['time']],'%Y/%m/%d %H:%M:%S')
        except ValueError:unknown_time+=1;continue
        if not args['start']<=when.date().isoformat()<=args['end']:outside+=1;continue
        selected.append(row)
    from traffic_contract import campaign_scope
    grouped={};priced=0;usd=Decimal(0);original_paid={};statuses=defaultdict(int)
    for row in selected:
        source=row[COLUMNS['source']].strip();game=safe_label(row[COLUMNS['game']]);kind='natural' if not source else campaign_scope(source)['campaign_scope']
        group=args['group_by']
        parts=([kind,safe_label(source) if source else '业务自然',game] if group=='source_game' else [safe_label(row[COLUMNS['payment_type']]),safe_label(row[COLUMNS['payment']])] if group=='payment' else [safe_label(row[COLUMNS[group]])])
        key=json.dumps(parts,ensure_ascii=False,separators=(',',':'));bucket=grouped.setdefault(key,{'key':key,'label':' / '.join(parts),'records':0,'orders':0,'order_amount_usd':Decimal(0),'priced_orders':0})
        bucket['records']+=1;bucket['orders']+=1;statuses[safe_label(row[COLUMNS['status']])]+=1
        value=amount(row[COLUMNS['usd']])
        if value is not None:bucket['order_amount_usd']+=value;bucket['priced_orders']+=1;priced+=1;usd+=value
        currency=row[COLUMNS['currency']].strip();paid=amount(row[COLUMNS['paid']])
        if re.fullmatch('[A-Z]{3}',currency) and paid is not None:original_paid[currency]=original_paid.get(currency,Decimal(0))+paid
    groups=sorted(grouped.values(),key=lambda row:row['order_amount_usd'],reverse=True)
    for row in groups:row['order_amount_usd']=str(row['order_amount_usd']) if row['priced_orders'] else None
    if len(groups)>20:
        rest=groups[20:];groups=groups[:20]+[{'key':'__other__','label':'其他（全部已读集合残差）','records':sum(r['records'] for r in rest),'orders':sum(r['orders'] for r in rest),'priced_orders':sum(r['priced_orders'] for r in rest),'order_amount_usd':str(sum((Decimal(r['order_amount_usd'] or '0') for r in rest),Decimal(0))) if any(r['priced_orders'] for r in rest) else None}]
    partial=bool(failed_files or parse_failures or ambiguous or unkeyed or outside or unknown_time or priced<len(selected) or declared_files is None or declared_files!=len(hashes))
    result.update(status='partial' if partial else 'available',captured_at=datetime.now(timezone.utc).isoformat(),source_version=hashlib.sha256(json.dumps({'files':hashes,'rule':RULE_VERSION},sort_keys=True).encode()).hexdigest(),structure_totals={'records':len(selected),'orders':len(selected),'order_amount_usd':str(usd) if priced else None,'priced_orders':priced},groups=groups,
        quality={'declared_files':declared_files,'read_files':len(hashes),'parse_failures':parse_failures,'failed_files':failed_files,'parsed_records':len(allrows),'duplicate_records':duplicates,'ambiguous_orders':ambiguous,'missing_order_keys':unkeyed,'outside_period_records':outside,'unknown_payment_time_records':unknown_time,'unknown_amount_orders':len(selected)-priced,'upstream_completeness':'unknown','file_set_complete':not failed_files and not parse_failures and declared_files==len(hashes),'order_identity':'deduplicated_within_this_file_set; global_uniqueness_unverified','time_boundary':'local payment-time strings filtered to requested inclusive days; source timezone and export bounds unverified','status_composition':dict(statuses),'original_paid_by_currency':{k:str(v) for k,v in original_paid.items()},'financial_definition':'订单金额（美元）结构金额；不是Admin原生总盘、财务实收或净额','profile_basis':'exact export game label FC 27','rule_version':RULE_VERSION,'top_limit':20,'total_group_count':len(grouped)})
    return result

class ESReader:
    """One bounded export per period; grouping never launches a second export."""
    def __init__(self,config,pool,reader=None):
        self.config=config;self.pool=pool;self.reader=reader or server_bundle;self.jobs={};self.created={};self.lock=threading.RLock()

    def get(self,args):
        q=checked_query(args)
        if self.config.get('enabled') is not True:return unavailable(q,'fc_detail_disabled')
        key=(q['profile'],q['start'],q['end'])
        with self.lock:
            now=time.monotonic()
            for old in list(self.jobs):
                if self.jobs[old].done() and now-self.created[old]>=cache_seconds(old[2]):
                    self.jobs.pop(old);self.created.pop(old)
            if key not in self.jobs:
                if len(self.jobs)>=16:return unavailable(q,'es_cache_capacity')
                self.created[key]=now
                self.jobs[key]=self.pool.submit(self.reader,{k:q[k] for k in ('profile','start','end')})
            future=self.jobs[key];started=self.created[key]
        if not future.done():return dict(unavailable(q),status='pending',retryAfter=3)
        if self.config.get('enabled') is not True:return unavailable(q,'fc_detail_disabled')
        try:
            bundle=future.result()
            if bundle.get('status')=='pending' or bundle.get('refresh_pending'):
                if time.monotonic()-started>=bundle.get('retryAfter',3):
                    with self.lock:
                        if self.jobs.get(key) is future:self.jobs.pop(key);self.created.pop(key)
                if bundle.get('status')=='pending':return dict(unavailable(q,bundle.get('reason','es_source_running')),status='pending',retryAfter=3)
            if bundle.get('status')!='available':
                if bundle.get('retryable') is True and time.monotonic()-started>=30:
                    with self.lock:
                        if self.jobs.get(key) is future:self.jobs.pop(key);self.created.pop(key)
                return unavailable(q,bundle.get('reason','es_source_unavailable'))
            found=[r for r in bundle['snapshots'] if r['query']==q]
            if len(found)==1:return deepcopy(found[0]['value'])
            return unavailable(q,'es_status_not_in_file_set')
        except Exception:return unavailable(q,'es_source_unavailable')


def export_bundle(manager,args,headers,download,archive=None,deadline=None):
    """Use an injected existing identity. Export generation is never retried here."""
    from urllib.parse import urlencode,urlsplit
    query=checked_query(args)
    deadline=deadline or time.monotonic()+150
    with manager.lock:
        try:identity_ok=manager.identity_ok(manager.token)
        except Exception:identity_ok=False
        if not identity_ok:return {'status':'unavailable','reason':'existing_auth_unavailable','retryable':True,'stage':'not_generated'}
        token=manager.token
    path='/admin/order.OrderExcelByEs/downloadsMake?'+urlencode({'startTime':query['start']+' 00:00:00','endTime':query['end']+' 23:59:59'})
    remaining=deadline-time.monotonic()
    if remaining<=0:return {'status':'unavailable','reason':'es_deadline_before_generation','retryable':True,'stage':'not_generated'}
    status,raw=manager.request(path,token=token,timeout=min(90,remaining))
    if status!=200 or len(raw)>1024*1024:return {'status':'unavailable','reason':'es_export_request_failed_or_unknown','retryable':False,'stage':'export_sent'}
    payload=json.loads(raw)
    urls=(payload.get('data') or {}).get('urls')
    if payload.get('code')!=1 or not isinstance(urls,list) or not 1<=len(urls)<=20 or len(set(urls))!=len(urls):return {'status':'unavailable','reason':'es_export_manifest_invalid','retryable':False,'stage':'export_sent'}
    files=[];failed=0
    for url in urls:
        if time.monotonic()>=deadline:failed+=len(urls)-len(files)-failed;break
        parts=urlsplit(url)
        if parts.scheme!='https' or parts.hostname!='admin-api.p2pah.cn' or parts.port not in (None,443) or parts.username or parts.password or parts.fragment or not parts.path.lower().endswith('.xlsx'):
            failed+=1;continue
        try:
            raw=download(url,{**headers,'batoken':token})
            if len(raw)>MAX_FILE or not raw.startswith(b'PK') or sum(len(v) for v in files)+len(raw)>128*1024*1024:raise ValueError('es_download_format')
            files.append(raw)
        except Exception:failed+=1
    if archive:
        try:archive(files,args)
        except (ValueError,OSError):return {'status':'unavailable','reason':'es_archive_not_saved_capacity_or_io','retryable':False,'stage':'export_sent'}
    parsed,hashes,parse_failures=parse_files(files)
    statuses={'all'}|{row.get(COLUMNS['status'],'') for row in parsed}
    statuses={s for s in statuses if isinstance(s,str) and s and len(s)<=80 and not re.search(r'[@<>\r\n]|https?://',s)}
    if len(statuses)>50:return {'status':'unavailable','reason':'es_status_limit'}
    snapshots=[]
    for status in sorted(statuses):
        for group in GROUPS:
            if time.monotonic()>=deadline:return {'status':'unavailable','reason':'es_projection_deadline','retryable':False,'stage':'export_sent'}
            q=dict(args,group_by=group,status=status)
            snapshots.append({'query':q,'value':aggregate_rows(parsed,hashes,parse_failures,q,len(urls),failed)})
    return {'kind':'es_order_structure_bundle','status':'available','snapshots':snapshots}


def archive_files(files,args,root=Path('/var/lib/fc27-es-exports')):
    import os,stat,shutil
    root=Path(root)
    with ARCHIVE_LOCK:
        if any(p.is_symlink() for p in (root,*root.parents)):raise ValueError('es_archive_symlink')
        root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if os.name=='posix' and (root.stat().st_uid!=os.geteuid() or root.stat().st_mode&0o077):raise ValueError('es_archive_permissions')
        existing={}
        for path in root.iterdir():
            info=path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or os.name=='posix' and (info.st_uid!=os.geteuid() or info.st_mode&0o077):raise ValueError('es_archive_integrity')
            existing[path.name]=info.st_size
        hashes=[hashlib.sha256(raw).hexdigest() for raw in files]
        additions={}
        for raw,digest in zip(files,hashes):
            name=digest+'.xlsx'
            if name in existing:
                if existing[name]>MAX_FILE or (root/name).read_bytes()!=raw:raise ValueError('es_archive_integrity')
            else:additions[name]=raw
        version=hashlib.sha256(json.dumps({'files':hashes,'rule':RULE_VERSION},sort_keys=True).encode()).hexdigest()
        if files and version+'.json' not in existing:
            additions[version+'.json']=json.dumps({'source_version':version,'file_sha256':hashes,'query':args,'captured_at':datetime.now(timezone.utc).isoformat(),'rule_version':RULE_VERSION},ensure_ascii=False).encode()
        extra=sum(map(len,additions.values()));used=sum(existing.values())
        if used+extra>MAX_ARCHIVE_BYTES or len(existing)+len(additions)>MAX_ARCHIVE_FILES or not files and (used>=MAX_ARCHIVE_BYTES or len(existing)>=MAX_ARCHIVE_FILES):raise ValueError('es_archive_capacity')
        if shutil.disk_usage(root).free<extra+ARCHIVE_RESERVE_BYTES:raise ValueError('es_archive_disk_reserve')
        for name,raw in additions.items():
            fd=os.open(str(root/name),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())


def cache_seconds(end):
    return 900 if end>=datetime.now(SHANGHAI).date().isoformat() else 21600


def trusted_download(url,headers,deadline=None):
    from urllib.request import Request,build_opener,HTTPRedirectHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    remaining=min(45,deadline-time.monotonic()) if deadline is not None else 45
    if remaining<=0:raise TimeoutError('es_deadline')
    with build_opener(NoRedirect).open(Request(url,headers=headers),timeout=remaining) as response:
        if response.status!=200:raise ValueError('es_download_http')
        content_type=response.headers.get_content_type()
        if content_type not in ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/octet-stream','application/zip'):raise ValueError('es_download_type')
        raw=response.read(MAX_FILE+1)
        if len(raw)>MAX_FILE:raise ValueError('es_file_size')
        return raw


SESSION_LOCK=threading.RLock()
SESSION_JOBS={}
SESSION_POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='admin-es-export')


def session_bundle(manager,args,headers,poll_only=False):
    """Only this source process owns export futures. Poll never recreates a lost job."""
    q=checked_query(args);args={k:q[k] for k in ('profile','start','end')};key=(args['profile'],args['start'],args['end'])
    with SESSION_LOCK:
        for old,(job,started) in list(SESSION_JOBS.items()):
            if old==key or not job.done():continue
            try:prior=job.result()
            except Exception:continue
            ttl=30 if prior.get('retryable') else cache_seconds(old[2]) if prior.get('status')=='available' else None
            if ttl is not None and time.monotonic()-started>=ttl:SESSION_JOBS.pop(old)
        item=SESSION_JOBS.get(key)
        if item and item[0].done() and not poll_only:
            try:previous=item[0].result()
            except Exception:previous={'status':'unavailable','retryable':False}
            ttl=30 if previous.get('retryable') else cache_seconds(args['end']) if previous.get('status')=='available' else None
            if ttl is not None and time.monotonic()-item[1]>=ttl:SESSION_JOBS.pop(key);item=None
        if item is None:
            if poll_only:return {'kind':'es_order_structure_bundle','status':'unavailable','reason':'es_export_previous_attempt_unknown_requires_reconcile','retryable':False}
            if len(SESSION_JOBS)>=16:return {'kind':'es_order_structure_bundle','status':'unavailable','reason':'es_source_capacity','retryable':True,'stage':'not_generated'}
            try:archive_files([],args)
            except (ValueError,OSError):return {'kind':'es_order_structure_bundle','status':'unavailable','reason':'es_archive_capacity_or_mount_unavailable','retryable':True,'stage':'not_generated'}
            deadline=time.monotonic()+150
            future=SESSION_POOL.submit(export_bundle,manager,args,headers,lambda u,h:trusted_download(u,h,deadline),archive_files,deadline)
            item=(future,time.monotonic());SESSION_JOBS[key]=item
        future=item[0]
    if not future.done():return {'kind':'es_order_structure_bundle','status':'pending','reason':'es_source_running','retryAfter':3}
    try:return dict(future.result(),kind='es_order_structure_bundle')
    except Exception:return {'kind':'es_order_structure_bundle','status':'unavailable','reason':'es_export_result_unknown_requires_reconcile','retryable':False}


def retained_bundle(previous,reason,pending=False):
    if previous and previous.get('status')=='available':
        value=deepcopy(previous)
        for item in value.get('snapshots',[]):
            projection=item['value'];projection['status']='partial'
            projection['quality'].update(retained_previous=True,last_attempt_reason=reason,refresh_pending=pending)
        if pending:value.update(refresh_pending=True,retryAfter=3)
        return value
    return {'kind':'es_order_structure_bundle','status':'pending' if pending else 'unavailable','reason':reason,'retryAfter':3}


def server_bundle(args,root=Path('/var/lib/fs-hermes-fc/fs/es-structures'),opener=None):
    """Existing session endpoint; persistent attempt switches all later reads to poll-only."""
    import os,stat,tempfile
    from urllib.request import Request,build_opener,HTTPRedirectHandler
    checked_query(args);root=Path(root)
    if any(p.is_symlink() for p in (root,*root.parents)):raise ValueError('es_cache_symlink')
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if os.name=='posix' and (root.stat().st_uid!=os.geteuid() or root.stat().st_mode&0o077):raise ValueError('es_cache_permissions')
    key=hashlib.sha256(json.dumps(args,sort_keys=True).encode()).hexdigest();index=root/(key+'.json');attempt=root/(key+'.attempt')
    def read(path):
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>8*1024*1024:raise ValueError('es_cache_file')
        if os.name=='posix' and (info.st_uid!=os.geteuid() or info.st_mode&0o077):raise ValueError('es_cache_file_permissions')
        return json.loads(path.read_text('utf-8'))
    def save(value):
        fd,name=tempfile.mkstemp(prefix='.es-',dir=root)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
            os.replace(name,index)
        finally:
            if os.path.exists(name):os.unlink(name)
    saved=read(index) if index.exists() or index.is_symlink() else None
    previous=saved.get('value') if saved else None;now=time.time()
    if saved:
        if saved.get('next_retry_at',0)>now:
            out=retained_bundle(previous,saved['last_attempt']) if previous and previous.get('status')=='available' else dict(previous or {},retryable=saved.get('retryable',False))
            if saved.get('retryable'):out.update(refresh_pending=True,retryAfter=max(3,saved['next_retry_at']-now))
            return out
        if previous and previous.get('status')=='available' and 0<=now-saved['saved_at']<cache_seconds(args['end']) and not saved.get('last_attempt'):return previous
        if previous and previous.get('status')!='available' and not saved.get('retryable'):return previous
    poll_only=attempt.exists() or attempt.is_symlink()
    if poll_only:read(attempt)
    else:
        if not index.exists() and len(list(root.glob('*.json')))+len(list(root.glob('*.attempt')))>=128:return {'status':'unavailable','reason':'es_durable_cache_capacity_requires_review'}
        try:fd=os.open(str(attempt),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        except FileExistsError:poll_only=True
        else:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump({'query':args,'started_at':datetime.now(timezone.utc).isoformat()},stream);stream.flush();os.fsync(stream.fileno())
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=opener or build_opener(NoRedirect);body=json.dumps(dict(args,kind='es_structure',poll_only=poll_only),separators=(',',':')).encode()
    try:
        with opener.open(Request('http://127.0.0.1:8767/business/fc-capability',data=body,headers={'Content-Type':'application/json'},method='POST'),timeout=30) as response:raw=response.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise ValueError('es_response_size')
        value=json.loads(raw)
        if not isinstance(value,dict) or value.get('kind')!='es_order_structure_bundle' or value.get('status') not in ('available','pending','unavailable'):raise ValueError('es_response_contract')
        if value['status']=='pending':return retained_bundle(previous,value.get('reason','es_source_running'),True)
        if value['status']=='available':
            if not isinstance(value.get('snapshots'),list) or len(value['snapshots'])>300:raise ValueError('es_response_contract')
            for item in value['snapshots']:
                q=checked_query(item['query']);projection=item['value']
                if any(q[k]!=args[k] for k in ('profile','start','end')) or projection.get('kind')!='es_order_structure' or projection.get('source_version') is not None and not re.fullmatch('[a-f0-9]{64}',projection['source_version']):raise ValueError('es_response_contract')
            save({'saved_at':now,'value':value});attempt.unlink();return value
        retry=value.get('retryable') is True and value.get('stage')=='not_generated'
        reason=value.get('reason','es_source_unavailable')
        save({'saved_at':saved['saved_at'] if saved and previous and previous.get('status')=='available' else now,'value':previous if previous and previous.get('status')=='available' else value,'last_attempt':reason,'next_retry_at':now+(30 if retry else 21600),'retryable':retry})
        if retry:attempt.unlink()
        out=retained_bundle(previous,reason)
        if retry:out.update(retryable=True,refresh_pending=True,retryAfter=30)
        return out
    except Exception:return retained_bundle(previous,'es_export_result_unknown_poll_only',True)


READER_LOCK=threading.RLock()

def reader_for(detail):
    with READER_LOCK:
        if not hasattr(detail,'es_structure_reader'):detail.es_structure_reader=ESReader(detail.config,detail.pool)
        detail.es_structure_reader.config=detail.config
        return detail.es_structure_reader
