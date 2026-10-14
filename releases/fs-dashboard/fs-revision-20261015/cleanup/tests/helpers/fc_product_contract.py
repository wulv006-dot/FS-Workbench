"""Official Admin product groups: counts only, with exactly one native hierarchy bucket."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
import copy
SH=timezone(timedelta(hours=8));CONTRACT='fc27-admin-native-product-ranking-v1'
BUCKETS=('coins','players','packs','sbc','items-other','boosting','other','unknown')
# Source product type codes and catalogue roots have different namespaces.
TYPE_PARENT={'1':'coins','0':'items','2':'boosting','3':'other','5':'other','7':'other','8':'other','9':'other'}
ROOT_TYPE={'1':'1','2':'0','4':'2','3':'3','5':'5','7':'7','8':'8','9':'9'}

def timepoint(s):return datetime.strptime(s,'%Y-%m-%d %H:%M').replace(tzinfo=SH)
def native_query(period,page=1,limit=1000):
 begin=timepoint(period['start']);end=timepoint(period['end'])
 if end<=begin or end-begin>timedelta(days=366):raise ValueError('product_period_invalid')
 if type(page) is not int or page<1 or type(limit) is not int or not 1<=limit<=10000:raise ValueError('product_pagination_invalid')
 q={'page':page,'limit':limit,'order':'order_count,descending'}
 for i,(field,op,val) in enumerate([('gid','=','1327'),('paytime','RANGE',begin.strftime('%Y-%m-%d %H:%M:%S')+','+(end-timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S'))]):
  q.update({f'search[{i}][field]':field,f'search[{i}][operator]':op,f'search[{i}][val]':val})
 q['search[1][render]']='datetime';return q

def number(v,integer=False):
 if isinstance(v,bool) or v is None:raise ValueError('product_metric_missing')
 try:d=Decimal(str(v))
 except InvalidOperation:raise ValueError('product_metric_invalid')
 if not d.is_finite() or abs(d)>Decimal('9007199254740991'):raise ValueError('product_metric_invalid')
 if integer and (d<0 or d!=d.to_integral_value()):raise ValueError('product_order_count_invalid')
 return int(d) if integer else str(d)

def taxonomy(tree):
 paths={};ambiguous=set()
 def walk(nodes,path):
  for node in nodes:
   ident=str(node.get('id',''))
   if not ident.isdigit():continue
   current=path+[ident]
   if ident in paths and paths[ident]!=current:ambiguous.add(ident)
   else:paths[ident]=current
   walk(node.get('children') or [],current)
 walk(tree,[])
 # A conflicting ancestor also makes its descendants' ancestry untrustworthy.
 paths={ident:path for ident,path in paths.items() if not any(x in ambiguous for x in path)}
 return paths

def classify(row,paths):
 path=paths.get(str(row['catalogueCategoryId']),[]);raw=row['nativeTypeId'];parent=TYPE_PARENT.get(raw)
 if not parent or not path or ROOT_TYPE.get(path[0])!=raw:return 'unknown','unknown','unverified_or_conflicting_native_hierarchy'
 if parent=='items':
  if '9627' in path:bucket='players'
  elif '9629' in path:bucket='packs'
  elif '9625' in path:bucket='sbc'
  else:bucket='items-other'
 else:bucket=parent
 return parent,bucket,None

def normalise(period,pages,tree,captured_at):
 begin=timepoint(period['start']);end=timepoint(period['end']);native_query(period)
 if not pages:raise ValueError('product_pages_missing')
 total=pages[0].get('total');unique={};page_numbers=set();read_rows=0
 if type(total) is not int or total<0 or total>10000:raise ValueError('product_total_invalid')
 for page in pages:
  if page.get('http')!=200 or page.get('code')!=1 or page.get('total')!=total:raise ValueError('product_paging_changed_or_failed')
  if page.get('page') in page_numbers:raise ValueError('product_repeated_page')
  page_numbers.add(page.get('page'))
  for x in page.get('rows') or []:
   read_rows+=1;pid=str(x.get('pid',''));goods=x.get('goods') or {}
   if not pid.isdigit() or int(pid)==0:raise ValueError('product_catalogue_relation_invalid')
   goods_id=str(goods.get('id') or '')
   if goods_id and goods_id!=pid:raise ValueError('product_catalogue_relation_invalid')
   linked=goods_id==pid
   if str(x.get('gid'))!='1327':raise ValueError('product_game_scope_mismatch')
   try:paid=datetime.fromtimestamp(int(x['paytime']),SH)
   except (ValueError,TypeError,KeyError,OverflowError):raise ValueError('product_payment_time_invalid')
   if not begin<=paid<end:raise ValueError('product_payment_outside_period')
   row={'productId':pid,'catalogueCategoryId':str(goods.get('cid','')) if linked else None,'catalogueIdVerified':linked,'nativeTypeId':str(x.get('cid','')),
    'representativeDescription':str(x.get('title') or '')[:220],'nativeSales':number(x.get('sale_total')),
    'nativeGroupOrderCount':number(x.get('order_count'),True),'salesUnit':None,'representativePaidAt':paid.isoformat()}
   if pid in unique and unique[pid]!=row:raise ValueError('product_conflicting_duplicate')
   unique[pid]=row
 if len(unique)!=total:raise ValueError('product_paging_incomplete')
 if page_numbers!=set(range(1,len(pages)+1)):raise ValueError('product_page_sequence_invalid')
 paths=taxonomy(tree);rows=list(unique.values())
 for row in rows:
  parent,bucket,issue=classify(row,paths);row.update(primaryParent=parent,bucket=bucket)
  if not row['catalogueIdVerified']:issue='catalogue_relation_missing'
  if issue:row['classificationIssue']=issue
 return {'schemaVersion':1,'contractId':CONTRACT,'status':'available' if rows else 'empty','source':'admin.p2pah.cn',
  'nativePage':'#/admin/stats/productSalesByEs','nativeEndpoint':'/admin/stats.productSalesByEs/index',
  'scope':'all-websites','platformScope':'all-platforms','gameAdminId':1327,'timezone':'Asia/Shanghai',
  'period':copy.deepcopy(period),'capturedAt':captured_at,'rows':rows,'sourceProductGroups':total,
  'categoryGroupCounts':{bucket:sum(r['bucket']==bucket for r in rows) for bucket in BUCKETS},
  'coverage':{'complete':True,'nativePageCount':len(pages),'rowsRead':read_rows,'distinctProductGroups':len(unique),'identicalDuplicatesDropped':read_rows-len(unique),'unlinkedCatalogueGroups':sum(not r['catalogueIdVerified'] for r in rows)},
  'nativeFilters':{'paymentStatus':'source-default-not-independently-defined','siteId':None,'platformId':None,'gid':1327,'timeField':'paytime','timeLabel':'source payment time','operator':'RANGE','render':'datetime'},
  'metricDefinitions':{'nativeSales':'source sale_total; raw units, not standard item units or coin balance',
   'nativeGroupOrderCount':'source order_count per product group; not overall distinct orders',
   'productId':'native pid equals goods.id; aggregate catalogue product, not fixed platform/quantity SKU'},
  'taxonomy':{'source':'/admin/goods.GoodsCategory/categorySelect?gid=1327','paths':paths},
  'noMoneyOrMargin':True,'noRepresentativePlatformGrouping':True,'noNameBasedClassification':True,'noCrossCategoryDoubleCount':True}

def requests(today,history_start,cutoff):
 start=today.isoformat()+' 00:00'
 return [{'key':'today','start':start,'end':cutoff},{'key':'history','start':history_start,'end':start},
  {'key':'yesterday','start':(today-timedelta(days=1)).isoformat()+' 00:00','end':start}]

def cycle(results,wanted,previous=None,previous_snapshot=None):
 old={'today':previous or {},'history':(previous or {}).get('history',{}),'yesterday':(previous or {}).get('yesterday',{})};out={}
 for q in wanted:
  key=q['key'];candidate=results.get(key) or {};period={k:q[k] for k in ['start','end']}
  if candidate.get('contractId')==CONTRACT and candidate.get('status') in ['available','empty'] and candidate.get('period')==period and candidate.get('coverage',{}).get('complete'):
   out[key]=copy.deepcopy(candidate)
  else:
   prior=old.get(key) or {}
   if prior.get('contractId')==CONTRACT and prior.get('status') in ['available','empty','stale'] and prior.get('coverage',{}).get('complete'):
    out[key]={k:copy.deepcopy(v) for k,v in prior.items() if k not in ['history','yesterday']}
    out[key].update(status='stale',requestedPeriod=period,carriedFromSnapshotId=previous_snapshot,failedAt=datetime.now(timezone.utc).isoformat())
   else:out[key]={'contractId':CONTRACT,'status':'unavailable','period':period,'rows':[],'source':'admin.p2pah.cn','error':'native_product_read_failed'}
 current=out.get('today') or {'status':'unavailable','contractId':CONTRACT,'rows':[]}
 current['history']=out.get('history');current['yesterday']=out.get('yesterday');return current
