"""Verified orderEs aggregates only; missing optional fields remain unavailable."""
from decimal import Decimal,InvalidOperation

FIELDS={
 'orders':('total','orders','补源订单统计原值'),
 'revenueUsd':('amount','USD','补源订单金额'),
 'payingCustomers':('paid_payments','people','付款总人数，按补源原字段'),
 'newCustomers':('new_people','people','补源新客户人数'),
 'newCustomerRevenueUsd':('new_amount','USD','补源新客户总额'),
 'repeatRatePct':('repeat_rete','percent','后台复购率原值；上游未公开分子分母，不在本系统推算'),
 'pureSalesUsd':('pure_amount','USD','纯销售额；不是利润'),
 'refundOrders':('refund_order_num','orders','补源退款订单数'),
 'refundAmountUsd':('refund_amount','USD','补源退款金额'),
 'deductedAmountUsd':('deducted_amount','USD','补源扣除金额'),
 'fulfillmentRatePct':('shipped_rate','percent','补源发货完成率原值'),
 'paymentSuccessRatePct':('payment_rate','percent','补源支付成功率原值'),
 'averageCustomerUsd':('customer_price','USD','补源客单价原值'),
 'minOrderAmountUsd':('min_order_amount','USD','补源最小订单金额'),
 'maxOrderAmountUsd':('max_order_amount','USD','补源最大订单金额')}

def numeric(raw,integer=False,percent=False,allow_negative=False):
 if raw is None or isinstance(raw,bool):return None
 try:
  text=str(raw).strip().replace(',','')
  if percent:
   if not text.endswith('%'):return None # Never guess fraction versus percentage points.
   text=text[:-1]
  n=Decimal(text)
  if not n.is_finite() or (not allow_negative and n<0):return None
  if integer and n!=n.to_integral_value():return None
  return int(n) if integer else float(n)
 except (InvalidOperation,ValueError,TypeError):return None

def metric(value,field,unit,definition,status=None):
 return {'value':value,'source':'supplement','field':field,'unit':unit,'definition':definition,
         'status':status or ('available' if value is not None else 'not_provided')}

def dimensions(data):
 result={}
 for target,key,label in [('channels','site_rank','site_name'),('countries','country_rank','name'),('games','game_rank','gname')]:
  raw=data.get(key)
  result[target]=None if not isinstance(raw,dict) else []
  if isinstance(raw,dict):
   for code,item in raw.items():
    if not isinstance(item,dict):continue
    row={'code':str(code),'name':str(item.get(label) or code),'orders':numeric(item.get('num'),integer=True),
         'revenueUsd':numeric(item.get('amount'))}
    if target=='games':row.update(adminGameId=item.get('gid'),cnName=item.get('gcnname'))
    result[target].append(row)
 raw=data.get('chart_pay_device')
 result['devices']=None if not isinstance(raw,list) else [
  {'name':str(i.get('name') or '未命名'),'orders':numeric(i.get('value'),integer=True),'revenueUsd':None}
  for i in raw if isinstance(i,dict)]
 raw=data.get('chart_pay_style')
 result['payments']=None
 if isinstance(raw,dict) and isinstance(raw.get('paytype_name'),list):
  names=raw['paytype_name'];counts=raw.get('paytype_order_num') or [];amounts=raw.get('paytype_amount') or []
  result['payments']=[{'name':str(name),'orders':numeric(counts[i],integer=True) if i<len(counts) else None,
   'revenueUsd':numeric(amounts[i]) if i<len(amounts) else None} for i,name in enumerate(names)]
 result['coupon']=None
 return result

def extract(data):
 fields={name:metric(numeric(data.get(key),integer=unit in ('people','orders'),percent=unit=='percent',allow_negative=unit=='USD'),key,unit,definition)
         for name,(key,unit,definition) in FIELDS.items()}
 new=fields['newCustomers']['value'];orders=fields['orders']['value']
 share=100*new/orders if new is not None and orders else None
 fields['newCustomerSharePct']=metric(share,'new_people / total','percent','补源新客人数 ÷ 补源订单数 × 100',
  'available' if share is not None else 'not_computable' if orders==0 else 'not_provided')
 fields['profitMarginPct']=metric(None,None,'percent','订单统计响应未提供利润/成本及可验证利润率口径','not_provided')
 fields['profitUsd']=metric(None,None,'USD','未提供可验证毛利润/净利润金额','not_provided')
 fields['costUsd']=metric(None,None,'USD','未提供可验证成本定义及总额','not_provided')
 return {'metrics':fields,'dimensions':dimensions(data),'definitionVersion':'admin-orderEs-verified-v1'}
