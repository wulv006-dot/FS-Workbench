"""Opt-in HTTP boundary for one scoped live page; host owns identity and source."""
from admin_live_page import AdminLivePage,LivePageError

def handle(params,user,*,authorize_for_user,fetch,enabled=False):
 if not user:return 401,{'error':'login_required'}
 if enabled is not True or not callable(authorize_for_user) or not callable(fetch):return 503,{'error':'live_source_not_enabled'}
 required={'site_id','game_id','start','end_exclusive'}
 if not isinstance(params,dict) or set(params)!=required or any(not isinstance(v,list) or len(v)!=1 or not isinstance(v[0],str) or len(v[0])>40 for v in params.values()):return 422,{'error':'invalid_live_query'}
 query={k:v[0] for k,v in params.items()};query['fields']=['order_id','paid_at','status']
 try:
  authorize=authorize_for_user(user)
  if not callable(authorize):return 403,{'error':'scope_or_admin_required'}
  grant=authorize(dict(query))
  if not isinstance(grant,dict):return 403,{'error':'scope_or_admin_required'}
  adapter=AdminLivePage(fetch=fetch,authorize=authorize,expected_grant=grant,page_size=5,max_bytes=262144,timeout_seconds=10)
  result=adapter(query)
  return 206,result
 except LivePageError as error:
  if error.code=='permission_denied':return 403,{'error':'scope_or_admin_required'}
  if error.code=='invalid_request':return 422,{'error':'invalid_live_query'}
  if error.code=='source_busy':return 429,{'error':'source_busy','retryAfter':10}
  return 503,{'error':error.code}
 except Exception:
  return 503,{'error':'live_source_unavailable'}
