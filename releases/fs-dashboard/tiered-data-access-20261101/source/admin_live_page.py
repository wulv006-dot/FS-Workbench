"""Explicit non-snapshot first page over an injected, authorized bounded transport.

Not registered with any host. No source access occurs without injected fetch and
real authorization. Results are intentionally partial and must never be cached
or fed to range_jobs as a complete snapshot.
"""
import base64,datetime,hashlib,hmac,json,secrets,time
from admin_live_admission import LiveBusy
from admin_supervised_transport import SourceResponseTooLarge

_CURSOR_KEY=secrets.token_bytes(32)
_MAX_PAGES=100000

class LivePageError(Exception):
 def __init__(self,code):super().__init__(code);self.code=code

def utc_now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def valid_customer_email(value):
 return isinstance(value,str) and 3<=len(value)<=320 and value.count('@')==1 and all(part for part in value.split('@')) and not any(c.isspace() or ord(c)<32 or ord(c)==127 for c in value)

def validate_period(request,observed_at):
 try:
  start=datetime.date.fromisoformat(request['start']);end=datetime.date.fromisoformat(request['end_exclusive'])
  if start.isoformat()!=request['start'] or end.isoformat()!=request['end_exclusive'] or not 0<(end-start).days<=28:raise ValueError()
  now=datetime.datetime.fromisoformat(observed_at().replace('Z','+00:00'))
  if now.utcoffset() is None:raise ValueError()
  today=now.astimezone(datetime.timezone(datetime.timedelta(hours=8))).date()
  if start<today-datetime.timedelta(days=365) or end>today+datetime.timedelta(days=1):raise ValueError()
  return start,end
 except (KeyError,ValueError,TypeError,AttributeError):raise LivePageError('invalid_request') from None

class AdminLivePage:
 def __init__(self,*,fetch,authorize,expected_grant,page_size,max_bytes,timeout_seconds,observed_at=utc_now,clock=time.monotonic,cursor_key=None):
  if not all(callable(x) for x in (fetch,authorize,observed_at,clock)):raise ValueError('host_dependencies_required')
  if not isinstance(expected_grant,dict) or set(expected_grant)!={'scope_hash','permission_epoch','policy_version'} or any(not isinstance(v,str) or not v for v in expected_grant.values()):raise ValueError('trusted_grant_required')
  if any(type(x) is not int for x in (page_size,max_bytes,timeout_seconds)) or not (1<=page_size<=20 and 1<=max_bytes<=1048576 and 1<=timeout_seconds<=10):raise ValueError('invalid_budget')
  self.fetch,self.authorize,self.expected_grant=fetch,authorize,dict(expected_grant)
  self.page_size,self.max_bytes,self.timeout_seconds,self.observed_at,self.clock=page_size,max_bytes,timeout_seconds,observed_at,clock
  self.cursor_key=_CURSOR_KEY if cursor_key is None else cursor_key
  if not isinstance(self.cursor_key,bytes) or len(self.cursor_key)<32:raise ValueError('cursor_key_required')
 def grant(self,request):
  try:value=self.authorize(dict(request))
  except Exception:raise LivePageError('permission_denied') from None
  if value!=self.expected_grant:raise LivePageError('permission_denied')
 def matches_game(self,row_gid,requested_gid):
  return row_gid==requested_gid
 def __call__(self,request):
  if not isinstance(request,dict) or set(request)-{'site_id','game_id','start','end_exclusive','fields','cursor','customer_email'} or not {'site_id','game_id','start','end_exclusive','fields'}<=set(request):raise LivePageError('invalid_request')
  if any(not isinstance(request[k],str) or not request[k].isascii() or not request[k].isdigit() or len(request[k])>20 for k in ('site_id','game_id')):raise LivePageError('invalid_request')
  fields=request['fields']
  if not isinstance(fields,list) or any(type(x) is not str for x in fields) or (fields and 'order_id' not in fields) or len(fields)!=len(set(fields)) or set(fields)-{'order_id','paid_at','status','pay_status','customer_email'}:raise LivePageError('invalid_request')
  if 'customer_email' in request and (not valid_customer_email(request['customer_email']) or 'customer_email' not in fields):raise LivePageError('invalid_request')
  start,end=validate_period(request,self.observed_at)
  self.grant(request)
  bound=hashlib.sha256(json.dumps([self.expected_grant,{k:v for k,v in request.items() if k!='cursor'},self.page_size],sort_keys=True,separators=(',',':')).encode()).hexdigest()
  page=1;last_digests=set();expected_total=None
  if 'cursor' in request:
   try:
    token=request['cursor']
    if not isinstance(token,str) or not 1<=len(token)<=1024:raise ValueError()
    body,signature=token.split('.')
    if not hmac.compare_digest(signature,hmac.new(self.cursor_key,body.encode('ascii'),hashlib.sha256).hexdigest()):raise ValueError()
    value=json.loads(base64.urlsafe_b64decode(body+'='*((-len(body))%4)))
    if not isinstance(value,list) or len(value)!=4 or value[0]!=bound:raise ValueError()
    page,packed,expected_total=value[1:]
    if type(page) is not int or type(expected_total) is not int or not 2<=page<=_MAX_PAGES or expected_total<0 or not isinstance(packed,str) or len(packed)>432:raise ValueError()
    digests=base64.b64decode(packed+'='*((-len(packed))%4),altchars=b'-_',validate=True)
    if not 16<=len(digests)<=16*self.page_size or len(digests)%16:raise ValueError()
    last_digests={digests[i:i+16] for i in range(0,len(digests),16)}
    if len(last_digests)!=len(digests)//16:raise ValueError()
   except (ValueError,TypeError,UnicodeError,OverflowError):raise LivePageError('invalid_request') from None
  filters=[('site_id','=',request['site_id']),('gid','=',request['game_id']),('paytime','RANGE',start.isoformat()+' 00:00:00,'+(end-datetime.timedelta(days=1)).isoformat()+' 23:59:59')]
  if 'customer_email' in request:filters.append(('email','=',request['customer_email']))
  params={'page':page,'limit':self.page_size,'order':'id,desc'}
  for i,(field,operator,value) in enumerate(filters):
   for key,val in (('field',field),('operator',operator),('val',value)):params['search[%d][%s]'%(i,key)]=val
   if operator=='RANGE':params['search[%d][render]'%i]='datetime'
  started=self.clock()
  try:status,raw=self.fetch('/admin/order.Order/index',params,self.timeout_seconds,self.max_bytes)
  except LivePageError:raise
  except LiveBusy:raise LivePageError('source_busy') from None
  except SourceResponseTooLarge:raise LivePageError('source_response_too_large') from None
  except PermissionError:raise LivePageError('permission_denied') from None
  except TimeoutError:raise LivePageError('source_timeout') from None
  except Exception:raise LivePageError('source_unavailable') from None
  if self.clock()-started>self.timeout_seconds:raise LivePageError('source_timeout')
  if type(status) is not int:raise LivePageError('source_schema_changed')
  if status in (401,403):raise LivePageError('source_auth')
  if status==429:raise LivePageError('source_rate_limited')
  if status!=200:raise LivePageError('source_unavailable')
  if not isinstance(raw,bytes) or len(raw)>self.max_bytes:raise LivePageError('source_schema_changed')
  try:
   data=json.loads(raw);payload=data['data'];rows=payload['list'];total=payload['total']
   if type(data['code']) is not int or data['code']!=1 or type(total) is not int or total<0 or not isinstance(rows,list) or len(rows)>self.page_size or len(rows)>total or page==1 and not rows and total!=0:raise ValueError()
   if expected_total is not None and total!=expected_total:raise LivePageError('source_changed')
   if rows and (page-1)*self.page_size+len(rows)>total:raise LivePageError('source_changed')
   if len(rows)<self.page_size and (page-1)*self.page_size+len(rows)<total:raise LivePageError('source_changed')
   output=[];previous=None;current_digests=[]
   for row in rows:
    if not isinstance(row,dict) or str(row['site_id'])!=request['site_id'] or not self.matches_game(str(row['gid']),request['game_id']):raise ValueError()
    ident=str(row['id']);paid=row['paytime'];state=str(row['status'])
    if not ident.isascii() or not ident.isdigit() or len(ident)>20 or int(ident)<=0 or not isinstance(paid,str) or not state.isascii() or not state.isdigit() or not 1<=len(state)<=4:raise ValueError()
    digest=hmac.new(self.cursor_key,('order:'+ident).encode('ascii'),hashlib.sha256).digest()[:16]
    if digest in last_digests:raise LivePageError('source_changed')
    current_digests.append(digest)
    if previous is not None and int(ident)>=previous:raise LivePageError('source_changed')
    when=datetime.datetime.strptime(paid,'%Y-%m-%d %H:%M:%S')
    if not start<=when.date()<end:raise ValueError()
    projection={'order_id':ident,'paid_at':paid,'status':state}
    if 'pay_status' in fields:
     paid_status=str(row['pay_status'])
     if paid_status not in ('0','1','2'):raise ValueError()
     projection['pay_status']=paid_status
    if 'customer_email' in fields:
     email=row['email']
     if email is not None and (not isinstance(email,str) or len(email)>320):raise ValueError()
     if 'customer_email' in request and email!=request['customer_email']:raise LivePageError('source_filter_mismatch')
     projection['customer_email']=email.strip() if email else None
    if fields:output.append({k:projection[k] for k in fields})
    previous=int(ident)
   at=self.observed_at()
   if not isinstance(at,str) or datetime.datetime.fromisoformat(at.replace('Z','+00:00')).utcoffset() is None:raise ValueError()
  except (ValueError,TypeError,KeyError,OverflowError):raise LivePageError('source_schema_changed') from None
  self.grant(request)
  next_cursor=None;limitation='live_pagination_not_snapshot'
  if page*self.page_size<total:
   if not rows:raise LivePageError('source_changed')
   if page>=_MAX_PAGES:limitation='page_limit_reached'
   else:
    packed=base64.urlsafe_b64encode(b''.join(current_digests)).decode().rstrip('=')
    body=base64.urlsafe_b64encode(json.dumps([bound,page+1,packed,total],separators=(',',':')).encode()).decode().rstrip('=')
    next_cursor=body+'.'+hmac.new(self.cursor_key,body.encode('ascii'),hashlib.sha256).hexdigest()
  return dict(status='partial',complete=False,semantics='live_non_snapshot',observed_at=at,timezone='Asia/Shanghai',scope=dict(site_id=request['site_id'],game_id=request['game_id']),period=dict(start=request['start'],end_exclusive=request['end_exclusive']),data=output,next_cursor=next_cursor,
              source_reported_total=total,observed_page_rows=len(rows),limitation=limitation)
