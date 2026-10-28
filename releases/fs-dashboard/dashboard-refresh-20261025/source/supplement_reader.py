"""Admin aggregate reads through the existing direct API session."""
from datetime import datetime,timezone
import json,sys
from supplement_fields import extract
sys.path.insert(0,'/opt/sales-dashboard/collector')
import p2pah_auth as auth

session=auth.Session();requests=json.loads(sys.argv[1]);results={}
try:
    token,error=auth.admin_token_from_service()
    if token:session.bind_admin_token(token)
    for item in requests:
        data={'order_status':item.get('status',''),'pay_status':1,'game':item.get('game',''),'site':'',
              'country_code':'','client':'','date':[item['start'],item['end']],'pay_type':'','time_unit':1,
              'cid':'','discount_code':'','product_type':item.get('product_type','')}
        try:
            if error or not token:raise OSError('admin_api_unavailable')
            status,value=session.post_admin('/admin/order.Order/orderStaticsDetailByEs',payload=data)
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
finally:session.close()
print(json.dumps(results,ensure_ascii=False))
