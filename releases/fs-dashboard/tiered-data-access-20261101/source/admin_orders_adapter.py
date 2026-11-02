"""Opt-in one-page Admin adapter; host must supply real grant, proof and bounded transport.

No credentials, network client, database writes, timer, or production registry are
created here. Missing strong source watermark is an explicit failure, not an empty
result. The host is responsible for enforcing response size and socket deadline.
"""
import datetime,hashlib,hmac,json,time

class SourceError(Exception):
 def __init__(self,code):super().__init__(code);self.code=code

def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')

class AdminOrdersAdapter:
 def __init__(self,*,fetch,authorize,expected_grant,source_proof,secret,page_size,max_pages,max_response_bytes,timeout_seconds,clock=time.monotonic):
  if not all(callable(x) for x in (fetch,authorize,source_proof,clock)) or not isinstance(secret,bytes) or len(secret)<32:raise ValueError('trusted_dependencies_required')
  if not isinstance(expected_grant,dict) or set(expected_grant)!={'scope_hash','permission_epoch','policy_version'} or any(not isinstance(v,str) or not v for v in expected_grant.values()):raise ValueError('trusted_grant_required')
  if any(type(v) is not int for v in (page_size,max_pages,max_response_bytes,timeout_seconds)) or not (1<=page_size<=1000 and 1<=max_pages<=100 and 1<=max_response_bytes<=10000000 and 1<=timeout_seconds<=30):raise ValueError('invalid_budget')
  self.fetch,self.authorize,self.expected_grant,self.source_proof=fetch,authorize,dict(expected_grant),source_proof
  self.secret,self.page_size,self.max_pages,self.max_response_bytes,self.timeout_seconds,self.clock=secret,page_size,max_pages,max_response_bytes,timeout_seconds,clock

 def trust(self,request):
  try:grant=self.authorize(dict(request))
  except Exception:raise SourceError('source_auth') from None
  if grant!=self.expected_grant:raise SourceError('source_auth')
  try:proof=self.source_proof(dict(request))
  except Exception:raise SourceError('source_unstable') from None
  if not isinstance(proof,dict) or proof.get('stable') is not True or proof.get('watermark')!=request['watermark']:raise SourceError('source_unstable')

 def __call__(self,request):
  required={'source','site_id','game_id','start','end_exclusive','fields','filters','date_semantics','cursor','watermark'}
  if not isinstance(request,dict) or set(request)!=required:raise SourceError('source_schema_changed')
  if request['source']!='Admin' or request['date_semantics']!='paid_at' or request['filters']!={}:raise SourceError('source_schema_changed')
  if any(not isinstance(request[k],str) or not request[k].isdigit() or len(request[k])>20 for k in ('site_id','game_id')):raise SourceError('source_schema_changed')
  fields=request['fields'];watermark=request['watermark']
  if not isinstance(fields,list) or any(type(v) is not str for v in fields) or 'order_id' not in fields or len(fields)!=len(set(fields)) or set(fields)-{'order_id','paid_at','status'} or not isinstance(watermark,str) or not 1<=len(watermark)<=256:raise SourceError('source_schema_changed')
  try:
   start=datetime.date.fromisoformat(request['start']);end=datetime.date.fromisoformat(request['end_exclusive'])
   if start.isoformat()!=request['start'] or end.isoformat()!=request['end_exclusive'] or not 0<(end-start).days<=28:raise ValueError()
  except (TypeError,ValueError):raise SourceError('source_schema_changed') from None
  self.trust(request)
  bound=hashlib.sha256(encoded({'request':{k:v for k,v in request.items() if k!='cursor'},'grant':self.expected_grant,'page_size':self.page_size})).hexdigest()
  page,total_so_far,last_id,expected_total=1,0,None,None
  cursor=request['cursor']
  if cursor is not None:
   if not isinstance(cursor,str) or not 1<=len(cursor)<=2048:raise SourceError('source_schema_changed')
   try:
    body,signature=cursor.rsplit('.',1)
    if not hmac.compare_digest(signature,hmac.new(self.secret,body.encode(),hashlib.sha256).hexdigest()):raise ValueError()
    value=json.loads(body)
    if not isinstance(value,list) or len(value)!=5 or value[0]!=bound:raise ValueError()
    page,total_so_far,last_id,expected_total=value[1:]
    if any(type(x) is not int for x in (page,total_so_far,last_id,expected_total)) or not (2<=page<=self.max_pages and 0<total_so_far<expected_total<=100000 and last_id>0):raise ValueError()
   except (ValueError,TypeError):raise SourceError('source_schema_changed') from None
  filters=[('site_id','=',request['site_id']),('gid','=',request['game_id']),('paytime','RANGE',start.isoformat()+' 00:00:00,'+(end-datetime.timedelta(days=1)).isoformat()+' 23:59:59')]
  params={'page':page,'limit':self.page_size,'order':'id,desc'}
  for i,(field,operator,value) in enumerate(filters):
   for key,val in (('field',field),('operator',operator),('val',value)):params['search[%d][%s]'%(i,key)]=val
   if operator=='RANGE':params['search[%d][render]'%i]='datetime'
  started=self.clock()
  try:status,raw=self.fetch('/admin/order.Order/index',params,self.timeout_seconds,self.max_response_bytes)
  except TimeoutError:raise SourceError('source_timeout') from None
  except Exception:raise SourceError('source_error') from None
  if self.clock()-started>self.timeout_seconds:raise SourceError('source_timeout')
  if type(status) is not int:raise SourceError('source_schema_changed')
  if status in (401,403):raise SourceError('source_auth')
  if status==429:raise SourceError('source_rate_limited')
  if status!=200:raise SourceError('source_error')
  if not isinstance(raw,bytes) or len(raw)>self.max_response_bytes:raise SourceError('source_schema_changed')
  try:
   data=json.loads(raw);payload=data['data'];rows=payload['list'];total=payload['total']
   if type(data['code']) is not int or data['code']!=1 or type(total) is not int or not 0<=total<=100000 or not isinstance(rows,list) or len(rows)>self.page_size or expected_total is not None and total!=expected_total:raise ValueError()
   if total_so_far+len(rows)>total or (not rows and total_so_far!=total):raise ValueError()
   output=[];previous=last_id
   for row in rows:
    if not isinstance(row,dict) or str(row['site_id'])!=request['site_id'] or str(row['gid'])!=request['game_id']:raise ValueError()
    ident=str(row['id']);paid=row['paytime'];status_value=str(row['status'])
    if not ident.isascii() or not ident.isdigit() or len(ident)>20 or int(ident)<=0 or previous is not None and int(ident)>=previous or not isinstance(paid,str) or not status_value.isascii() or not status_value.isdigit() or not 1<=len(status_value)<=4:raise ValueError()
    when=datetime.datetime.strptime(paid,'%Y-%m-%d %H:%M:%S')
    if not start<=when.date()<end:raise ValueError()
    projected={'order_id':ident,'paid_at':paid,'status':status_value};output.append({k:projected[k] for k in fields});previous=int(ident)
   count=total_so_far+len(rows);complete=count==total
   if not complete and page>=self.max_pages:raise SourceError('source_unstable')
  except SourceError:raise
  except (ValueError,TypeError,KeyError,OverflowError):raise SourceError('source_schema_changed') from None
  self.trust(request)
  next_cursor=None
  if not complete:
   body=encoded([bound,page+1,count,previous,total]).decode('utf-8');next_cursor=body+'.'+hmac.new(self.secret,body.encode(),hashlib.sha256).hexdigest()
  return dict(rows=output,complete=complete,next_cursor=next_cursor,watermark=watermark,confirmed_empty=complete and total==0)
