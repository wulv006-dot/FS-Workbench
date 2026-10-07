"""Exact label and unit mapping from the Order statistics summary cards."""
from decimal import Decimal,InvalidOperation
FIELDS={
 'averageOrderUsd':('单均价','USD'),
 'profitMarginPct':('利润率','percent'),
 'fulfillmentRatePct':('发货完成率','percent'),
 'minOrderAmountUsd':('最小订单金额','USD'),
 'maxOrderAmountUsd':('最大订单金额','USD'),
 'receiptsCny':('收款总额','CNY'),
 'goodsPaymentCny':('货款总额','CNY')}
def parse(text,unit):
 try:
  raw=str(text).strip().replace(',','')
  if unit=='percent':
   if not raw.endswith('%'):return None
   raw=raw[:-1]
  elif unit=='USD':
   if not raw.startswith('$'):return None
   raw=raw[1:]
  elif unit=='CNY':
   if raw[:1] not in ('¥','￥'):return None
   raw=raw[1:]
  n=Decimal(raw)
  return float(n) if n.is_finite() else None
 except (InvalidOperation,ValueError,TypeError):return None
def extract(names,values):
 labelled={}
 for name,value in zip(names,values):
  label=str(name).replace(str(value),'',1).strip()
  labelled[label]=str(value)
 result={}
 for field,(label,unit) in FIELDS.items():
  v=parse(labelled.get(label),unit)
  definition='Order订单统计“'+label+'”原值'
  if field=='profitMarginPct':definition+='；上游未公开毛/净、成本及汇率公式，不推算利润金额'
  result[field]={'value':v,'source':'primary','field':label,'unit':unit,'raw':labelled.get(label),
   'status':'available' if v is not None else 'not_provided','definition':definition}
 return result
