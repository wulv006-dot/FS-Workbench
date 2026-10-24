"""Existing admin session; supplements only missing customer fields."""
from datetime import datetime,timezone
from decimal import Decimal
import json,sys
import urllib.request
from supplement_fields import extract
sys.path.insert(0,'/usr/local/bin')
from p2pah_session_service import SessionManager,read_private_config
manager=SessionManager(read_private_config());requests=json.loads(sys.argv[1]);results={}
def existing_admin_token():
    with urllib.request.urlopen('http://127.0.0.1:8767/session/admin-token',timeout=5) as response:
        raw=response.read(16385)
    if len(raw)>16384:raise ValueError('supplement_shared_session_size')
    value=json.loads(raw);token=value.get('token')
    if value.get('ready') is not True or not isinstance(token,str) or not 0<len(token)<=8192 or any(ord(c)<33 or ord(c)>126 for c in token):
        raise ValueError('supplement_shared_session_unavailable')
    return token
for item in requests:
    data={'order_status':item.get('status',''),'pay_status':1,'game':item.get('game',''),'site':'',
          'country_code':'','client':'','date':[item['start'],item['end']],'pay_type':'','time_unit':1,
          'cid':'','discount_code':'','product_type':item.get('product_type','')}
    try:
        status,raw=manager.request('/admin/order.Order/orderStaticsDetailByEs',data=data,token=existing_admin_token())
        value=json.loads(raw)
        if status!=200 or value.get('code')!=1:raise ValueError('supplement_failed')
        value=value.get('data')
        if isinstance(value,dict) and isinstance(value.get('data'),dict):value=value['data']
        extended=extract(value)
        n=extended['metrics']['newCustomers']['value']
        results[item['key']]={'system':'admin.p2pah.cn','endpoint':'/admin/order.Order/orderStaticsDetailByEs','status':'available',
            'normalisedScope':'all-websites','period':{'start':item['start'],'end':item['end']},'filters':data,
            'capturedAt':datetime.now(timezone.utc).isoformat(),'newCustomers':n,
            'metrics':extended['metrics'],'dimensions':extended['dimensions'],'definitionVersion':extended['definitionVersion'],
            'comparisonOnly':{'orders':value.get('total'),'revenueUsd':value.get('amount')}}
    except Exception:
        results[item['key']]={'system':'admin.p2pah.cn','status':'unavailable','normalisedScope':'all-websites',
                            'period':{'start':item['start'],'end':item['end']},'capturedAt':datetime.now(timezone.utc).isoformat(),'newCustomers':None}
print(json.dumps(results,ensure_ascii=False))
