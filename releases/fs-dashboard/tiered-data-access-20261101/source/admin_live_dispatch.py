"""Opt-in HTTP boundary for one scoped live page; host owns identity and source."""
import json
from admin_live_page import AdminLivePage,LivePageError,valid_customer_email

def private_body_params(raw):
 if not isinstance(raw,bytes) or not 1<=len(raw)<=4096:raise ValueError('invalid_body')
 def unique(pairs):
  result={}
  for key,value in pairs:
   if key in result:raise ValueError('duplicate_field')
   result[key]=value
  return result
 try:value=json.loads(raw.decode('utf8'),object_pairs_hook=unique)
 except (UnicodeError,ValueError,TypeError):raise ValueError('invalid_body') from None
 required={'site_id','game_id','start','end_exclusive','customer_email'}
 if not isinstance(value,dict) or not required<=set(value) or set(value)-required-{'cursor'} or not valid_customer_email(value.get('customer_email')) or any(not isinstance(v,str) for v in value.values()):raise ValueError('invalid_body')
 return {k:[v] for k,v in value.items()}

def handle(params,user,*,authorize_for_user,fetch,enabled=False,observed_at=None,select_fields=None):
 if not user:return 401,{'error':'login_required'}
 if enabled is not True or not callable(authorize_for_user) or not callable(fetch):return 503,{'error':'live_source_not_enabled'}
 required={'site_id','game_id','start','end_exclusive'}
 if not isinstance(params,dict) or not required<=set(params) or set(params)-required-{'cursor','customer_email'} or any(not isinstance(v,list) or len(v)!=1 or not isinstance(v[0],str) or len(v[0])>(1024 if k=='cursor' else 320 if k=='customer_email' else 40) for k,v in params.items()):return 422,{'error':'invalid_live_query'}
 query={k:v[0] for k,v in params.items()}
 try:
  query['fields']=select_fields(dict(query)) if callable(select_fields) else ['order_id','paid_at','status']
  if 'customer_email' in query and 'customer_email' not in query['fields']:return 403,{'error':'scope_denied'}
  authorize=authorize_for_user(user)
  if not callable(authorize):return 403,{'error':'scope_denied'}
  grant=authorize(dict(query))
  if not isinstance(grant,dict):return 403,{'error':'scope_denied'}
  options={} if observed_at is None else {'observed_at':observed_at}
  adapter=AdminLivePage(fetch=fetch,authorize=authorize,expected_grant=grant,page_size=20,max_bytes=262144,timeout_seconds=10,**options)
  result=adapter(query)
  return 206,result
 except LivePageError as error:
  if error.code=='permission_denied':return 403,{'error':'scope_denied'}
  if error.code=='invalid_request':return 422,{'error':'invalid_live_query'}
  if error.code=='source_changed':return 409,{'error':'source_changed_restart_required'}
  if error.code=='source_busy':return 429,{'error':'source_busy','retryAfter':10}
  return 503,{'error':error.code}
 except Exception:
  return 503,{'error':'live_source_unavailable'}
