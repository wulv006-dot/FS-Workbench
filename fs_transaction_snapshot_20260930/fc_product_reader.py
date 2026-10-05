"""Read the official Admin aggregate within a hard Linux deadline; never export secrets."""
import sys,json,time,signal
from datetime import datetime,timezone
from urllib.parse import urlencode
from fc_product_contract import native_query,normalise
sys.path.insert(0,'/usr/local/bin')
from p2pah_session_service import SessionManager,read_private_config

def alarm(*args):raise TimeoutError('native_product_deadline')
signal.signal(signal.SIGALRM,alarm);signal.alarm(65)
out={}
try:
 wanted=json.loads(sys.argv[1]);m=SessionManager(read_private_config())
 if len(wanted)>3:raise ValueError('product_batch_limit')
 if not m.ensure():raise ValueError('product_session_unavailable')
 status,raw=m.request('/admin/goods.GoodsCategory/categorySelect?'+urlencode({'gid':1327}),token=m.token)
 value=json.loads(raw)
 if status!=200 or value.get('code')!=1:raise ValueError('product_taxonomy_unavailable')
 tree=(value.get('data') or {}).get('list') or []
 if not tree:raise ValueError('product_taxonomy_unavailable')
 for q in wanted:
  key=q['key'];period={k:q[k] for k in ['start','end']};pages=[];total=None
  try:
   # Native offset pages have unstable ties and ignore pid sorting (live verified).
   # Read the whole bounded result in one batch, retrying with the actual total.
   for attempt in range(2):
    params=native_query(period,1,1000 if total is None else max(1000,total))
    status,raw=m.request('/admin/stats.productSalesByEs/index?'+urlencode(params),token=m.token);value=json.loads(raw);data=value.get('data') or {}
    if status!=200 or value.get('code')!=1:raise ValueError('product_native_request_failed')
    count=data.get('total')
    if type(count) is not int or count<0 or count>10000 or (total is not None and count!=total):raise ValueError('product_total_changed_or_invalid')
    total=count;rows=[]
    for x in data.get('list') or []:
     row={k:x.get(k) for k in ['pid','gid','cid','title','sale_total','order_count','paytime']}
     row['goods']={k:(x.get('goods') or {}).get(k) for k in ['id','cid']};rows.append(row)
    pages=[{'page':1,'http':status,'code':value['code'],'total':total,'rows':rows}]
    if len(rows)>=total:break
   out[key]=normalise(period,pages,tree,datetime.now(timezone.utc).isoformat())
   out[key]['coverage']['retrievalStrategy']='complete-native-batch-with-total-check'
   out[key]['coverage']['readAttempts']=attempt+1
  except (ValueError,KeyError,TypeError):out[key]={'status':'unavailable','error':'native_product_contract_failed','period':period}
except Exception:
 # No arbitrary upstream error text, payload or identity escapes to collector output.
 pass
finally:signal.alarm(0)
print(json.dumps(out,ensure_ascii=True))
