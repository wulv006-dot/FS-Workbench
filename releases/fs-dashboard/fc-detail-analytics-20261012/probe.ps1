$ErrorActionPreference = 'Stop'
$fcProbe = @'
import sys,json
sys.path.insert(0,'/usr/local/bin')
from p2pah_session_service import SessionManager,read_private_config
m=SessionManager(read_private_config())
if not m.ensure(): raise RuntimeError('existing_auth_unavailable')
p='/admin/order.Order/index?limit=100&page=1&search[0][field]=gid&search[0][val]=1327&search[0][operator]=%3D&search[1][field]=paytime&search[1][val]=2026-10-11%2000:00:00,2026-10-12%2000:00:00&search[1][operator]=RANGE&search[1][render]=datetime'
status,raw=m.request(p+'&order=id,asc',token=m.token)
d=json.loads(raw);rows=d.get('data',{}).get('list',[])
assert status==200 and d.get('code')==1,'orders_read_unavailable'
ids=[int(r['id']) for r in rows]
status2,raw2=m.request(p.replace('page=1','page=2')+'&order=id,asc',token=m.token)
page2=json.loads(raw2)['data']['list'];ids2=[int(r['id']) for r in page2]
print(json.dumps({'http':status,'code':d['code'],'total':d['data']['total'],'returned':len(rows),'order_id_ascending':ids==sorted(ids),'next_page_ordered':bool(ids2) and max(ids)<min(ids2),'site_counts':{str(s):sum(r['site_id']==s for r in rows) for s in set(r['site_id'] for r in rows)},'customer_flag_counts':{str(s):sum(r.get('isNew')==s for r in rows) for s in set(r.get('isNew') for r in rows)},'numeric_usd_matches':all(abs(float(r['amount'])-float(r['amount_usd_format'].replace('$','').replace(',','').strip()))<0.005 for r in rows)},ensure_ascii=False))
'@
$fcRemote = "docker exec -i fc27-p2pah-session python3 - <<'FC_READ_PROBE'`n$fcProbe`nFC_READ_PROBE"
& "$PSScriptRoot/../server_187/access/Invoke-Server187.ps1" -Action Run -RemoteCommand $fcRemote
