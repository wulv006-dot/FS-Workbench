"""D1 scope tests: ignored filters and cross-scope caches must not look successful."""
import ast,copy,hashlib,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'tests/fixtures')]
from live_summary import query,key_of,SHANGHAI,SummaryCache
from daily_archive import summary_key
from admin_scope import scope_metadata,repeat_metrics
P={'FC27':('FC27','FC 27',1322,1327,'sports')}
ARGS=dict(mode=['summary'],profile=['FC27'],start=['2026-11-10'],end=['2026-11-11'],profit_site=['main'])
NOW=datetime(2026,11,12,12,tzinfo=SHANGHAI)

def q(**kw):return query({**ARGS,**{k:[v] for k,v in kw.items()}},P,NOW)
def mapped():return {'metrics':{'orders':{'value':49}},'dimensions':{'channels':[{'code':'www.mmoexp.com','name':'www.mmoexp.com'}],'countries':[{'code':'US','name':'US'}],'games':[{'adminGameId':1327}]}}

class FilterContract(unittest.TestCase):
 def test_scope_and_permissions_split_memory_and_archive_keys(self):
  a=q(country_code='US');b=q(country_code='GB');c=q(profit_site='all')
  values=[a,b,c,dict(a,authorization_scope='actor-a'),dict(a,authorization_scope='actor-b')]
  self.assertEqual(len({key_of(x) for x in values}),5)
  self.assertEqual(len({json.dumps(summary_key(x),sort_keys=True) for x in values}),5)
 def test_minute_cross_day_bounds_reach_period_without_hour_rounding(self):
  v=q(grain='minute',start='2026-11-10 23:30',end='2026-11-11 00:30')
  self.assertEqual(v['period'],{'start':'2026-11-10 23:30','end':'2026-11-11 00:30'})
 def test_unsupported_filters_return_no_source_data_or_work(self):
  for k in ('channel','customer_type','payment','device','platform','product'):
   v=q(**{k:'test'});cache=SummaryCache(Mock(),Mock(),P);cache.close()
   with patch('daily_archive.read') as read:
    code,result=cache.get(v)
   self.assertEqual(code,422);self.assertEqual(result['unsupported_filters'],[k]);self.assertIsNone(result['effective_scope']);read.assert_not_called()
   self.assertEqual(cache.entries,{})
 def test_return_ranks_prove_country_site_game_and_empty_is_distinct(self):
  payload=dict(site=266,game='1327',country_code='US',date=['2026-11-11 00:00','2026-11-12 00:00'])
  v=scope_metadata(payload,mapped());self.assertEqual(v['effective_scope']['country_code'],'US')
  self.assertEqual(v['coverage']['scope_status'],'verified_by_returned_ranks')
  self.assertEqual(v['coverage']['time_boundary_status'],'upstream_minute_boundary_unverified')
  empty={'metrics':{'orders':{'value':0}},'dimensions':{}}
  v=scope_metadata(payload,empty);self.assertEqual(v['coverage']['scope_status'],'empty_result_membership_unverified');self.assertIsNone(v['effective_scope']['country_code'])
 def test_ignored_country_or_game_fails_not_widened(self):
  payload=dict(site=266,game='1327',country_code='US',date=['a','b'])
  for field,bad in [('countries',[{'code':'GB'}]),('games',[{'adminGameId':891}]),('channels',[{'code':'www.rsorders.com'}])]:
   m=mapped();m['dimensions'][field]=bad
   with self.assertRaisesRegex(ValueError,'filter_not_applied'):scope_metadata(payload,m)
  m=mapped();m['dimensions']['countries']=None
  with self.assertRaisesRegex(ValueError,'filter_not_applied'):scope_metadata(payload,m)
 def test_country_only_admin_does_not_request_unscreened_order_profit(self):
  v=q(country_code='US');cache=SummaryCache(Mock(),Mock(),P,shipping_read=Mock());cache.close()
  cache.pools={name:Mock() for name in cache.readers}
  cache.get_live(v);entry=cache.entries[key_of(v)]
  self.assertEqual(entry['Order']['state'],'not_requested');self.assertEqual(entry['Shipping']['state'],'not_requested')
  cache.pools['Order'].submit.assert_not_called();cache.pools['Shipping'].submit.assert_not_called()
  record=dict(status='available',period=v['period'],capturedAt='2026-11-12T01:00:00+00:00',metrics={},dimensions={})
  entry['Admin'].update(state='available',at=cache.clock(),valueAt=cache.clock(),value=record)
  code,result=cache.get_live(v)
  self.assertEqual(code,200)
  for name in ('primary','shipping'):
   self.assertEqual(result['profile'][name]['status'],'unsupported');self.assertEqual(result['profile'][name]['metrics'],{})

class SummaryArchiveBoundary(unittest.TestCase):
 def exercise_get(self, selection, should_archive):
  cache=SummaryCache(Mock(),Mock(),P,shipping_read=Mock(),clock=lambda:100)
  cache.close();cache.pools={name:Mock() for name in cache.readers}
  with patch('daily_archive.read',return_value=None),patch('daily_archive.save') as save:
   self.assertEqual(cache.get(selection)[0],202)
   entry=cache.entries[key_of(selection)]
   for name,slot in entry.items():
    if slot['state']=='pending':
     slot.update(state='available',at=100,valueAt=100,phase='available',value=dict(
      status='available',period=copy.deepcopy(selection['period']),
      capturedAt='2026-11-12T01:00:00+00:00',metrics={},dimensions={}))
   calls={name:pool.submit.call_count for name,pool in cache.pools.items()}
   for _ in range(2):
    code,result=cache.get(selection)
    self.assertEqual(code,200)
    self.assertEqual(result['profile']['supplement']['period'],selection['period'])
   self.assertEqual(save.call_count,2 if should_archive else 0)
   self.assertEqual(calls,{name:pool.submit.call_count for name,pool in cache.pools.items()})
   if selection.get('admin_only'):
    for name in ('Order','Shipping'):
     cache.pools[name].submit.assert_not_called()
     self.assertEqual(entry[name]['state'],'not_requested')
    self.assertEqual(result['profile']['primary']['status'],'unsupported')
    self.assertEqual(result['profile']['shipping']['status'],'unsupported')
 def test_cross_day_minute_and_hour_get_return_200_without_day_archive(self):
  for grain,start,end in [('minute','2026-11-10 23:30','2026-11-11 00:30'),
                          ('hour','2026-11-10 23:00','2026-11-11 00:00')]:
   for country in ('','US'):
    with self.subTest(grain=grain,country=country):
     self.exercise_get(q(grain=grain,start=start,end=end,**({'country_code':country} if country else {})),False)
 def test_complete_day_get_still_archives_with_and_without_country(self):
  for country in ('','US'):
   with self.subTest(country=country):
    self.exercise_get(q(**({'country_code':country} if country else {})),True)
 def test_partial_today_get_does_not_archive_as_complete_day(self):
  self.exercise_get(q(start='2026-11-12',end='2026-11-12',country_code='US'),False)

class Repurchase(unittest.TestCase):
 def test_native_and_local_repeat_not_silently_replaced(self):
  local={'repeat_rate':{'numerator':13,'denominator':280,'rate':13/280,'status':'available','basis':'at_least_two_distinct_valid_orders_within_selected_period'},'coverage':{'period_complete':True,'identity_deduplication_complete':True,'missing_identity_orders':0,'state_basis':'period_cohort'},'scope':{'site':'unverified-es-sample'}}
  original=copy.deepcopy(local);v=repeat_metrics({'repeat_rete':'4.33%','paid_payments':280},{'site':266},local)
  self.assertEqual(v['admin_repeat_rate_raw'],'4.33%');self.assertEqual(v['native_repeat_rate']['value'],4.33)
  self.assertIsNone(v['native_repeat_rate']['denominator']);self.assertIsNone(v['native_repeat_rate']['numerator'])
  self.assertAlmostEqual(v['local_repeat_rate']['value'],100*13/280);self.assertEqual(v['reconciliation_status'],'not_aligned');self.assertEqual(local,original)
 def test_native_zero_buyer_raw_preserved(self):
  v=repeat_metrics({'repeat_rete':'0%','paid_payments':0},{})
  self.assertEqual(v['admin_repeat_rate_raw'],'0%');self.assertEqual(v['native_repeat_rate']['raw_value'],0)
  self.assertIsNone(v['native_repeat_rate']['value']);self.assertEqual(v['native_repeat_rate']['status'],'not_applicable')
 def test_native_valid_whitespace_and_zero_decimal_remain_compatible(self):
  v=repeat_metrics({'repeat_rete':' 0% ','paid_payments':'0.00'}, {})
  self.assertEqual(v['admin_repeat_rate_raw'],' 0% ');self.assertEqual(v['native_repeat_rate']['status'],'not_applicable')
 def test_complete_replay_zero_denominator_is_not_applicable_only_for_known_empty(self):
  local={'repeat_rate':{'numerator':0,'denominator':0,'rate':None,'status':'not_mature',
         'basis':'at_least_two_distinct_valid_orders_within_selected_period'},
         'coverage':{'period_complete':True,'identity_deduplication_complete':True,'missing_identity_orders':0,'state_basis':'period_cohort'}}
  value=repeat_metrics({'repeat_rete':'0%','paid_payments':0},{},local)
  self.assertEqual(value['admin_repeat_rate_raw'],'0%')
  self.assertEqual(value['native_repeat_rate']['status'],'not_applicable')
  self.assertEqual((value['local_repeat_rate']['numerator'],value['local_repeat_rate']['denominator']),(0,0))
  self.assertIsNone(value['local_repeat_rate']['value'])
  self.assertEqual(value['local_repeat_rate']['status'],'not_applicable')
  for field in ('period_complete','identity_deduplication_complete'):
   incomplete=copy.deepcopy(local);incomplete['coverage'][field]=False
   self.assertEqual(repeat_metrics({}, {},incomplete)['local_repeat_rate']['status'],'unavailable')
  for changes in ({'status':'pending'},{'status':'unavailable'},{'denominator':1},
                  {'rate':0},{'basis':'unverified_formula'}):
   unknown=copy.deepcopy(local);unknown['repeat_rate'].update(changes)
   result=repeat_metrics({}, {},unknown)['local_repeat_rate']
   self.assertEqual(result['status'],'unavailable');self.assertIsNone(result['denominator'])
 def test_missing_identity_or_partial_source_not_complete_local_rate(self):
  for coverage in ({'period_complete':False,'identity_deduplication_complete':True},{'period_complete':True,'identity_deduplication_complete':False}):
   v=repeat_metrics({'repeat_rete':'4.33%'},{},{'repeat_rate':{'numerator':13,'denominator':280,'rate':13/280,'status':'partial'},'coverage':coverage,'scope':{}})
   self.assertIsNone(v['local_repeat_rate']['value']);self.assertEqual(v['local_repeat_rate']['status'],'unavailable')

class LocalRepeatBinding(unittest.TestCase):
 def setUp(self):
  self.scope={'site':'266','game':'1327','country_code':'all','period':{'start':'2026-11-10 00:00','end':'2026-11-12 00:00'}}
  self.supplement={'status':'available','requested_scope':self.scope,'effective_scope':self.scope,
   'admin_repeat_rate_raw':'4.33%','local_repeat_rate':{'status':'unavailable'},'metrics':{'repeatRatePct':{'value':4.33}}}
  self.service=Mock();self.service.store=Mock()
  self.store=Mock()
  self.publication={'cutoff':'2026-11-13T00:00:00+08:00','publication_id':'uw_revision1','data_version':'4',
   'config':{'sites':{'266':{}},'projects':{'1327':{}},'policies':{'fc-v1':[14,30,90],'common-v1':[30,60,90]}},
   'jobs':[{'site':'266','start':'2026-11-10T00:00:00+08:00','end':'2026-11-12T00:00:00+08:00','state':'complete'}]}
  self.store.read_at.return_value=[self.order('a','c1'),self.order('b','c1','2026-11-11'),self.order('c','c2'),
   self.order('d','c2',gid='456'),self.order('e','c2',site='277'),self.order('f','c2',valid=False)]
  self.cache={}

 @staticmethod
 def order(order_key,customer_id,day='2026-11-10',gid='1327',site='266',valid=True):
  return dict(order_key=order_key,customer_id=customer_id,paid_at=day+'T10:00:00+08:00',source_id='',body='{}',gid=gid,site=site,valid=valid)

 def run_binding(self, selection=None, actor='alice'):
  from local_repeat_source import attach
  from threading import RLock
  value={'profile':{'supplement':self.supplement}}
  with patch('local_repeat_source.copy',return_value=self.store), patch('user_weekly.stored_publication',return_value=self.publication) as reader:
   result=attach(value,selection or q(),actor,self.service,self.cache,RLock())
  return result['profile']['supplement']['local_repeat_rate'],reader

 def test_same_site_game_and_window_uses_read_only_published_revision(self):
  local,reader=self.run_binding()
  self.assertEqual((local['status'],local['numerator'],local['denominator'],local['value']),('available',1,2,50))
  self.assertEqual(local['scope']['game'],'1327')
  self.assertEqual(local['data_revision'],'4');self.assertEqual(local['publication_id'],'uw_revision1')
  self.assertEqual(self.supplement['metrics']['repeatRatePct']['value'],4.33)
  self.assertEqual(self.supplement['local_repeat_rate']['status'],'unavailable')
  self.assertTrue(self.store.read_only)
  reader.assert_called_once_with(self.store)
  self.store.read_at.assert_called_once_with('4','2026-11-10T00:00:00+08:00','2026-11-12T00:00:00+08:00',bounded_only=True)
  self.service.query.assert_not_called();self.store.save_snapshot.assert_not_called()

 def test_permission_is_rechecked_before_cached_revision_and_reads(self):
  self.assertEqual(self.run_binding()[0]['value'],50)
  self.assertEqual(self.run_binding()[0]['value'],50)
  self.assertEqual(self.service.permit.call_count,4)
  self.assertEqual(self.store.read_at.call_count,1)
  self.assertEqual(self.run_binding(actor='bob')[0]['value'],50)
  self.service.permit.side_effect=PermissionError('private source detail')
  local,reader=self.run_binding()
  self.assertIsNone(local['value']);self.assertEqual(local['reason'],'user_scope_denied')
  reader.assert_not_called();self.assertEqual(self.store.read_at.call_count,2)
  self.assertNotIn('private source detail',str(local))

 def test_unproven_scope_or_dates_never_read_local_facts(self):
  for selection in (q(country_code='US'),q(profit_site='all'),q(grain='hour',start='2026-11-10 00:00',end='2026-11-11 23:00')):
   with self.subTest(selection=selection):
    local,reader=self.run_binding(selection)
    self.assertIsNone(local['value']);reader.assert_not_called()
  self.store.read_at.assert_not_called()

 def test_missing_window_identity_and_revision_never_publish_zero(self):
  jobs=self.publication['jobs'];self.publication['jobs']=[]
  local,_=self.run_binding();self.assertIsNone(local['value']);self.store.read_at.assert_not_called()
  self.publication['jobs']=jobs
  self.store.read_at.return_value=None
  local,_=self.run_binding();self.assertIsNone(local['value']);self.assertEqual(local['reason'],'bounded_revision_unavailable')
  self.store.read_at.return_value=[self.order('a',None)]
  local,_=self.run_binding();self.assertIsNone(local['value']);self.assertEqual(local['coverage']['missing_identity_orders'],1)
  self.assertEqual(local['status'],'unavailable');self.assertIsNone(local['denominator'])
  self.publication.update(publication_id='uw_revision2',data_version='5')
  self.store.read_at.return_value=[]
  local,_=self.run_binding()
  self.assertEqual((local['status'],local['numerator'],local['denominator']),('not_applicable',0,0))

class Integration(unittest.TestCase):
 def test_real_extractor_adapter_and_bridge_preserve_native_filters(self):
  # This is the existing supplement_fields source, not a replacement mapping.
  path=ROOT.parent/'order-latency-20261010/source/supplement_fields.py'
  spec=importlib.util.spec_from_file_location('d1_existing_fields',path);fields=importlib.util.module_from_spec(spec);spec.loader.exec_module(fields)
  import summary_bridge,site_summary
  raw=dict(total=49,amount=4830.30,paid_payments=47,repeat_rete='2.22%',
           site_rank={'www.mmoexp.com':{'site_name':'www.mmoexp.com','num':49}},
           game_rank={'FC 27':{'gname':'FC 27','gid':1327,'num':49}},country_rank={'US':{'name':'US','num':49}},
           chart_sales_arr={'date':['2026-11-11'],'n':[49],'amount':[4830.30]})
  upstream=Mock(return_value=(200,json.dumps({'code':1,'data':raw})))
  v=q(country_code='US');factory=Mock()
  with patch.object(summary_bridge,'SummaryCache',factory):summary_bridge.build(P,Mock(),Mock(),Path('/unused'))
  with patch.dict(sys.modules,{'supplement_fields':fields}),patch.object(summary_bridge,'dc_request',upstream):
   value=factory.call_args.args[0](v)
  self.assertEqual(upstream.call_args.kwargs['data']['country_code'],'US')
  self.assertEqual(value['requested_scope']['game'],'1327');self.assertEqual(value['effective_scope']['country_code'],'US')
  self.assertEqual(value['admin_repeat_rate_raw'],'2.22%');self.assertEqual(value['metrics']['repeatRatePct']['value'],2.22)
  self.assertIsNone(value['local_repeat_rate']['value'])
  raw.update(total=0,amount=0,paid_payments=0,repeat_rete='0%',site_rank={},game_rank={},country_rank={},chart_sales_arr={'date':[],'n':[],'amount':[]})
  upstream.return_value=(200,json.dumps({'code':1,'data':raw}))
  with patch.dict(sys.modules,{'supplement_fields':fields}),patch.object(summary_bridge,'dc_request',upstream):value=factory.call_args.args[0](v)
  self.assertEqual(value['metrics']['repeatRatePct']['status'],'not_applicable');self.assertIsNone(value['metrics']['repeatRatePct']['value'])
  self.assertEqual(value['admin_repeat_rate_raw'],'0%')
 def test_route_actor_scope_cannot_come_from_query_and_does_not_mix_users(self):
  tree=ast.parse((ROOT/'source/range_api.py').read_text(encoding='utf-8'));node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='get_range')
  cache=Mock();cache.get.side_effect=lambda v:(200,v)
  env=dict(hashlib=hashlib,SUMMARY=cache,summary_query=query,PROFILE_MAP=P,USERS=None)
  exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-get-range','exec'),env)
  a=env['get_range'](ARGS,summary_actor='reader-a')[1];b=env['get_range'](ARGS,summary_actor='reader-b')[1]
  self.assertNotEqual(key_of(a),key_of(b));self.assertNotEqual(summary_key(a),summary_key(b))
  with self.assertRaises(ValueError):env['get_range']({**ARGS,'authorization_scope':['reader-a']},summary_actor='reader-b')
  handler=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
  body=ast.unparse(handler);self.assertIn("self.headers.get('X-Auth-User')",body);self.assertIn("'summary_actor'",body)
 def test_route_attaches_local_repeat_after_shared_cache_only_for_authenticated_actor(self):
  from threading import RLock
  tree=ast.parse((ROOT/'source/range_api.py').read_text(encoding='utf-8'));node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='get_range')
  cache=Mock();user_service=Mock();payload={'profile':{}};cache.get.return_value=(200,payload)
  env=dict(hashlib=hashlib,SUMMARY=cache,summary_query=query,PROFILE_MAP=P,USERS=user_service,
           LOCAL_REPEAT_CACHE={},LOCAL_REPEAT_LOCK=RLock())
  exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-get-range','exec'),env)
  with patch('local_repeat_source.attach',return_value={'attached':True}) as attach:
   self.assertEqual(env['get_range'](ARGS,summary_actor='alice'),(200,{'attached':True}))
   saved=cache.get.call_args.args[0]
   self.assertEqual(saved['authorization_scope'],'actor:'+hashlib.sha256(b'alice').hexdigest())
   attach.assert_called_once_with(payload,saved,'alice',user_service,env['LOCAL_REPEAT_CACHE'],env['LOCAL_REPEAT_LOCK'])
   self.assertEqual(env['get_range'](ARGS),(200,payload))
   cache.get.return_value=(202,{'status':'pending'})
   self.assertEqual(env['get_range'](ARGS,summary_actor='alice'),(202,{'status':'pending'}))
   self.assertEqual(attach.call_count,1)
 def test_existing_period_replay_cross_day_uid_zero_and_order_flags(self):
  sys.path.insert(0,str(ROOT.parent/'user-analytics-20261022/source'))
  from user_store import Store
  from user_query import Service
  from user_contract import stamp
  cfg=json.loads((ROOT.parent/'user-analytics-20261022/source/user_config.json').read_text(encoding='utf-8'))
  with tempfile.TemporaryDirectory() as folder:
   store=Store(Path(folder)/'private',b'x'*32,cfg)
   rows=[dict(id=i,order_no='d1-'+str(i),paytime=paid,email=email,gid='1327',uid=0,site_id='266',pay_status=1,status='11')
         for i,paid,email in [(1,'2026-11-10 10:00:00','a@example.test'),(2,'2026-11-11 10:00:00','a@example.test'),(3,'2026-11-10 12:00:00','b@example.test'),(4,'2026-11-11 12:00:00','c@example.test')]]
   now=stamp('2026-11-12T12:00:00+08:00');store.replace_window('266','2026-11-10','2026-11-12',rows,now.isoformat())
   flags={hashlib.sha256(('d1-'+str(i)).encode()).hexdigest():('new' if i in (1,3) else 'old') for i in range(1,5)}
   service=Service(store,lambda u,q,p:True,clock=lambda:now,customer_type_reader=lambda q:(flags,dict(status='complete',source='synthetic flags',sourceVersion='d1')))
   local=service.query(dict(start='2026-11-10',scope='site',scope_id='266',state_basis='period_cohort'),'test-user')
   local['scope']=local['query'];v=repeat_metrics({'repeat_rete':'4.33%'},{'site':'266'},local)
   self.assertEqual((v['local_repeat_rate']['numerator'],v['local_repeat_rate']['denominator']),(1,3))
   self.assertAlmostEqual(v['local_repeat_rate']['value'],100/3);self.assertEqual(v['reconciliation_status'],'not_aligned')
if __name__=='__main__':unittest.main()

