"""Pure native daily margin history; explicit scope and monotonic attempt times."""
from copy import deepcopy
from datetime import date,datetime,timedelta,timezone
from math import isfinite
CONTRACT='order-native-daily-margin-v2'
def stamp(value):
 d=datetime.fromisoformat(value)
 if d.tzinfo is None:raise ValueError('capture timestamp requires timezone')
 return d
def utc(value):return stamp(value).astimezone(timezone.utc).isoformat()
def number(value,integer=False):
 if isinstance(value,bool) or not isinstance(value,(int,float)) or not isfinite(value):raise ValueError('invalid number')
 if integer and (value<0 or int(value)!=value):raise ValueError('invalid order count')
 return value
def check_scope(key,scope,expected):
 want=expected.get(key)
 if not want or scope!={'sites':want['sites'],'orderGameId':want['gid'],'orderProductType':want['tid'],'orderStatus':want['status']}:raise ValueError('profile/site/game/status contract differs')
def normalise(record,expected):
 day=date.fromisoformat(record['date']);period={'start':day.isoformat()+' 00:00','end':(day+timedelta(days=1)).isoformat()+' 00:00'}
 if record.get('system')!='order.p2pah.cn' or record.get('endpoint')!='/stats/admin_order/index.html' or record.get('timezone')!='Asia/Shanghai' or record.get('currency')!='USD':raise ValueError('source/unit differs')
 if record.get('period')!=period:raise ValueError('complete daily period differs')
 filters=record['filters']
 if filters.get('start_paytime')!=period['start'] or filters.get('end_paytime')!=period['end']:raise ValueError('date filters differ')
 scope={'sites':record.get('normalisedScope'),'orderGameId':str(filters['gid']),'orderProductType':str(filters['tid']),'orderStatus':str(filters['status'])}
 check_scope(record['profileKey'],scope,expected)
 captured=utc(record['capturedAt']);margin=record.get('profitMarginPct',{});valid=record.get('status')=='available' and margin.get('status')=='available'
 if valid:
  if stamp(captured).astimezone(timezone(timedelta(hours=8))).date()<=day:raise ValueError('daily value captured before complete-day boundary')
  if record.get('labelsVerified') is not True or margin.get('unit')!='percent' or margin.get('source')!='primary' or margin.get('field')!='利润率':raise ValueError('native rate contract differs')
  value=number(margin['value']);orders=number(record['orders'],True);revenue=number(record['revenueUsd'])
 else:value=orders=revenue=None
 return dict(profileKey=record['profileKey'],date=day.isoformat(),period=period,timezone='Asia/Shanghai',currency='USD',scope=scope,profitMarginPct=value,orders=orders,revenueUsd=revenue,profitUsd=None,costUsd=None,status='available' if valid else 'not_provided',source='order.p2pah.cn',endpoint='/stats/admin_order/index.html',capturedAt=captured,latestAttemptAt=captured,latestAttemptStatus='available' if valid else 'not_provided',collectionKind=record.get('collectionKind'),definition=margin.get('definition'),marginUnit='percent',profitCostStatus='not_provided',stale=False)
def identity(row):
 s=row['scope'];return row['profileKey'],row['date'],s['sites'],s['orderGameId'],s['orderProductType'],s['orderStatus']
def validate_row(row,expected):
 check_scope(row['profileKey'],row['scope'],expected);day=date.fromisoformat(row['date'])
 if row['period']!={'start':str(day)+' 00:00','end':str(day+timedelta(days=1))+' 00:00'} or row['source']!='order.p2pah.cn' or row['marginUnit']!='percent' or row['timezone']!='Asia/Shanghai' or row['currency']!='USD':raise ValueError('history provenance differs')
 stamp(row['capturedAt']);stamp(row.get('latestAttemptAt',row['capturedAt']))
 if row['profitUsd'] is not None or row['costUsd'] is not None:raise ValueError('derived profit forbidden')
 if row['status']=='available':number(row['profitMarginPct']);number(row['orders'],True);number(row['revenueUsd'])
 elif row['status']!='not_provided' or any(row[x] is not None for x in ('profitMarginPct','orders','revenueUsd')):raise ValueError('invalid missing day')
def merge(existing,records,expected):
 rows={}
 for row in existing:
  validate_row(row,expected);key=identity(row)
  if key in rows:raise ValueError('duplicate persisted day')
  rows[key]=deepcopy(row)
 for raw in records:
  new=normalise(raw,expected);key=identity(new);old=rows.get(key)
  if not old:rows[key]=new;continue
  observed=stamp(old.get('latestAttemptAt',old['capturedAt']));incoming=stamp(new['capturedAt']);valid_at=stamp(old['capturedAt'])
  if new['status']!='available' and old['status']=='available':
   if incoming>observed:
    old.update(stale=True,latestAttemptAt=new['capturedAt'],latestAttemptStatus=new['status'])
   continue
  if new['status']=='available' and old['status']=='available':
   if incoming<valid_at:continue
   if incoming==valid_at and any(new[k]!=old[k] for k in ('profitMarginPct','orders','revenueUsd')):raise ValueError('conflicting same-time native values')
   if incoming<observed:
    new.update(stale=old['stale'],latestAttemptAt=old['latestAttemptAt'],latestAttemptStatus=old['latestAttemptStatus'])
  elif incoming<observed:
   if new['status']!='available':continue
   new.update(stale=True,latestAttemptAt=old.get('latestAttemptAt',old['capturedAt']),latestAttemptStatus=old.get('latestAttemptStatus',old['status']))
  rows[key]=new
 return sorted(rows.values(),key=identity)
def build_history(existing,records,expected):
 daily=merge(existing,records,expected)
 return dict(schemaVersion=2,contractId=CONTRACT,daily=daily,historyGeneratedAt=max((utc(r.get('latestAttemptAt',r['capturedAt'])) for r in daily),default=None),snapshotId=None,refreshContract=dict(serverIntervalSeconds=7200,clientCheckSeconds=60),note='Complete daily native rates. Missing days are null, no average or inferred USD profit; failed newer attempts retain native values with stale metadata.')
def validate_history(history,expected):
 if history.get('contractId')!=CONTRACT or history.get('schemaVersion')!=2 or history.get('refreshContract')!={'serverIntervalSeconds':7200,'clientCheckSeconds':60}:raise ValueError('profit history contract differs')
 seen=set()
 for row in history['daily']:
  validate_row(row,expected);key=identity(row)
  if key in seen:raise ValueError('duplicate history day')
  seen.add(key)
