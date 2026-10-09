"""Sanitize verified Admin read endpoints; no member identities are exported."""
from datetime import date,datetime,timezone
from decimal import Decimal,InvalidOperation
from urllib.parse import urlencode
import json

MEMBER_FIELDS={
 'register_total':('注册会员数','所选期间内在MMOEXP主站注册的会员数。','people'),
 'new_member_order_count':('新会员订单数','在所选期间注册、且在同一期间付款的新会员订单数。','orders'),
 'new_member_order_amount':('新会员订单金额','上述新会员在同一期间付款的订单金额，美元。','USD'),
 'member_order_count':('会员订单数','不限注册时间，所选期间内付款的会员订单数。','orders'),
 'member_order_amount':('会员订单金额','不限注册时间，所选期间内付款的会员订单金额，美元。','USD'),
 'coupon_grant_users':('新会员发券人数','仅所选期间新注册的会员中，获得优惠券的人数。','people'),
 'coupon_use_users':('新会员用券人数','所选期间新注册、且用券订单在同一期间付款的人数；不含老会员。','people'),
 'coupon_use_orders':('新会员用券订单数','上述新会员在同一期间付款的用券订单数；不是全站用券总数。','orders'),
 'coupon_discount_total':('新会员用券总额','会员统计返回的上述新会员用券金额，美元；按后台此项原值展示，不与订单销售额合并。','USD'),
}
def number(value,integer=False):
 if value is None or isinstance(value,bool):return None
 try:
  n=Decimal(str(value).replace(',',''))
  if not n.is_finite() or n<0 or integer and n!=n.to_integral_value():return None
  return int(n) if integer else float(n)
 except (InvalidOperation,ValueError,TypeError):return None
def unwrap(status,raw):
 value=json.loads(raw)
 if not isinstance(value,dict):raise ValueError('admin_shape_invalid')
 if status!=200 or value.get('code')!=1:raise ValueError('admin_read_failed')
 data=value.get('data')
 if isinstance(data,dict) and isinstance(data.get('data'),dict):data=data['data']
 if not isinstance(data,dict):raise ValueError('admin_shape_invalid')
 return data
def membership(request,start,end):
 for v in (start,end):
  if date.fromisoformat(v).isoformat()!=v:raise ValueError('invalid_date')
 if end<start:raise ValueError('invalid_date_order')
 data=unwrap(*request('/admin/stats.MemberStats/summary',data={'site':266,'date':[start+' 00:00:00',end+' 23:59:59'],'time_unit':3}))
 return {'status':'available','source':'Admin 会员统计','endpoint':'/admin/stats.MemberStats/summary','site':'www.mmoexp.com','start':start,'end':end,'timezone':'Asia/Shanghai','currency':'USD',
  'metrics':[{ 'field':key,'label':label,'explanation':help,'unit':unit,'value':number(data.get(key),unit!='USD')} for key,(label,help,unit) in MEMBER_FIELDS.items()]}
def inventory(request,kind,page=1):
 endpoints={'discount':'/admin/market.Discount/index','coupon':'/admin/market.Coupon/index','usage':'/admin/user.MemberCouponLog/index'}
 endpoint=endpoints[kind]
 data=unwrap(*request(endpoint+('?' + urlencode({'page':page}) if page!=1 else '')))
 if not isinstance(data.get('list'),list):raise ValueError('admin_list_invalid')
 output=[]
 for row in data['list']:
  if not isinstance(row,dict):raise ValueError('admin_row_invalid')
  site=row.get('site');site=site.get('full_title') if isinstance(site,dict) else None
  if site!='www.mmoexp.com':continue
  if kind=='discount':
   item={'id':row.get('id'),'name':row.get('code'),'site':site,'game':row.get('game_title'),'uses':number(row.get('count'),True),'enabled':row.get('status')==1}
  elif kind=='coupon':
   game=row.get('game')
   item={'id':row.get('id'),'name':row.get('title'),'site':site,'game':game.get('title') if isinstance(game,dict) else None,'claimed':number(row.get('fetch_qty'),True),'uses':number(row.get('used_qty'),True),'enabled':row.get('status')==1}
  else:
   item={'couponId':row.get('coupon_id'),'name':row.get('title'),'site':site,'usedAt':row.get('use_time'),'batch':row.get('memberCoupon',{}).get('grant_batch_no') if isinstance(row.get('memberCoupon'),dict) else None,'repeatOrders90d':number(row.get('repurchase_count'),True)}
  output.append(item)
 return {'status':'partial','source':'Admin','endpoint':endpoint,'site':'www.mmoexp.com','kind':kind,'page':page,'returnedRows':len(data['list']),'returnedMainSiteRows':len(output),'totalAllSites':number(data.get('total'),True),'rows':output,
  'basis':'最新返回的一页记录；总项数为全部站点，不代表MMOEXP总量。配置使用次数为后台累计原值，不受Google日期筛选影响。' if kind!='usage' else '最新返回的一页用券记录，不限注册时间；不是所选期间完整订单统计。'}
def collect(request,start,end):
 result={'schemaVersion':1,'capturedAt':datetime.now(timezone.utc).isoformat(),'site':'www.mmoexp.com','start':start,'end':end}
 for name in ('membership','discount','coupon','usage'):
  try:result[name]=membership(request,start,end) if name=='membership' else inventory(request,name)
  except (OSError,ValueError,TypeError,KeyError):result[name]={'status':'unavailable','source':'Admin','reason':'本次读取未成功，未填零。'}
 return result
