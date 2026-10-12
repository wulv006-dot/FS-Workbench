"""Adapter for the existing verified Order reader, never synthesizes available data."""
from copy import deepcopy
from datetime import date,datetime,timedelta,timezone
def expected_contracts(profiles):return {key:dict(sites='all-websites',gid=str(gid),tid='',status='3' if group=='rpg' else '') for key,name,gid,game,group in profiles}
def contracts_from_snapshot(snapshot):
 result={}
 for key,profile in snapshot['profiles'].items():
  source=profile['primary'];f=source['filters']
  result[key]=dict(sites=source['normalisedScope'],gid=str(f['gid']),tid=str(f['tid']),status=str(f['status']))
 return result
def daily_requests(today,previous,expected):
 day=today-timedelta(days=1);want=expected['MMOEXP']
 if any(r['profileKey']=='MMOEXP' and r['date']==str(day) and r['status']=='available' and r['scope']==dict(sites=want['sites'],orderGameId=want['gid'],orderProductType=want['tid'],orderStatus=want['status']) for r in previous):return []
 return [dict(key='profit-daily:MMOEXP:'+str(day),profileKey='MMOEXP',date=str(day),gid=want['gid'],tid=want['tid'],status=want['status'],start=str(day)+' 00:00',end=str(day+timedelta(days=1))+' 00:00')]
def adapt_reader(source,item,expected):
 from profit_daily import normalise
 raw={k:deepcopy(source.get(k)) for k in ('system','endpoint','normalisedScope','timezone','currency','period','filters','capturedAt','status','orders','revenueUsd','labelsVerified')}
 raw.update(date=item['date'],profileKey=item['profileKey'],collectionKind='existing-120min-native-day',profitMarginPct=deepcopy(source.get('metrics',{}).get('profitMarginPct',{})))
 normalise(raw,expected);return raw
def failed_attempt(item,expected):
 c=expected[item['profileKey']]
 return dict(date=item['date'],profileKey=item['profileKey'],system='order.p2pah.cn',endpoint='/stats/admin_order/index.html',normalisedScope=c['sites'],timezone='Asia/Shanghai',currency='USD',period=dict(start=item['start'],end=item['end']),filters=dict(gid=c['gid'],tid=c['tid'],status=c['status'],start_paytime=item['start'],end_paytime=item['end']),capturedAt=datetime.now(timezone.utc).isoformat(),status='unavailable',profitMarginPct={},collectionKind='failed-120min-native-day')
