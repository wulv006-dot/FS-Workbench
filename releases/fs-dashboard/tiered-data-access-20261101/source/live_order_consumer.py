"""Consume scoped live pages without claiming snapshot or customer history."""
from datetime import date,timedelta

def iter_pages(fetch,*,site_id,game_id,start,end_exclusive,max_pages):
 if not callable(fetch) or type(max_pages) is not int or not 1<=max_pages<=2000:raise ValueError('invalid_page_budget')
 if any(not isinstance(x,str) or not x.isascii() or not x.isdigit() or len(x)>20 for x in (site_id,game_id)):raise ValueError('invalid_scope')
 try:
  begin=date.fromisoformat(start);end=date.fromisoformat(end_exclusive)
  if begin.isoformat()!=start or end.isoformat()!=end_exclusive or not 0<(end-begin).days<=366:raise ValueError()
 except (ValueError,TypeError):raise ValueError('invalid_range') from None
 remaining=max_pages
 while begin<end:
  stop=min(begin+timedelta(days=28),end);seen=set();cursor=None
  while True:
   if remaining==0:raise ValueError('page_budget_exhausted')
   query={'site_id':site_id,'game_id':game_id,'start':begin.isoformat(),'end_exclusive':stop.isoformat()}
   if cursor is not None:query['cursor']=cursor
   result=fetch(query);remaining-=1
   if not isinstance(result,dict) or result.get('status')!='partial' or result.get('complete') is not False or result.get('semantics')!='live_non_snapshot' or not isinstance(result.get('data'),list):raise ValueError('unexpected_live_response')
   if result.get('limitation')=='page_limit_reached':raise ValueError('page_limit_reached')
   following=result.get('next_cursor')
   if following is not None and (not isinstance(following,str) or not following or len(following)>1024):raise ValueError('invalid_cursor')
   if following is not None and following in seen:raise ValueError('repeated_cursor')
   yield result
   if following is None:break
   seen.add(following);cursor=following
  begin=stop
