import copy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'baseline')]
from source_snapshots import SnapshotStore,report_queries
from report_constraints import native_total
from boss_projection import project
import test_projection as projection_fixtures
import test_titles_goals as title_fixtures


class SourceSnapshots(unittest.TestCase):
 def test_official_index_shared_across_windows_but_not_after_expiry(self):
  from source_snapshots import official_snapshot
  with tempfile.TemporaryDirectory() as tmp:
   now=[datetime(2026,10,17,2,tzinfo=timezone.utc)];store=SnapshotStore(Path(tmp)/'private',lambda:now[0]);calls=[]
   def reader(q):
    calls.append(q);return {'http_status':200,'status':'partial','captured_at':now[0].isoformat(),'coverage':{'index_read':True,'exhaustive':False},'failures':[],
     'documents':[{'published_at':'2026-10-09','text':'bounded article','publication_in_window':False}]}
   one=official_snapshot(reader,{'profile':'FC27','start':'2026-10-05','end':'2026-10-11'},{'enabled':True},store)
   two=official_snapshot(reader,{'profile':'FC27','start':'2026-10-16','end':'2026-10-16'},{'enabled':True},store)
   self.assertEqual(len(calls),1);self.assertTrue(one['documents'][0]['publication_in_window']);self.assertFalse(two['documents'][0]['publication_in_window'])
   self.assertEqual(one['source_cache']['version'],two['source_cache']['version']);self.assertTrue(two['source_cache']['reused'])
   self.assertEqual(two['status'],'partial');self.assertFalse(two['coverage']['exhaustive'])
   now[0]+=timedelta(hours=6)
   official_snapshot(reader,{'profile':'FC27','start':'2026-10-16','end':'2026-10-16'},{'enabled':True},store)
   self.assertEqual(len(calls),2)
 def test_native_loss_preserves_two_hour_limit_and_publication_checks_new_version(self):
  from source_snapshots import archived_publication
  with tempfile.TemporaryDirectory() as tmp:
   now=[datetime(2026,10,17,2,tzinfo=timezone.utc)];store=SnapshotStore(Path(tmp)/'private',lambda:now[0]);q={'start':'2026-10-16','end':'2026-10-16'};calls=[]
   def reader():calls.append(1);return {'status':'available'}
   a=store.get('native-loss',q,reader,lambda v:True);store.get('native-loss',q,reader,lambda v:True)
   self.assertEqual(len(calls),1);now[0]+=timedelta(hours=2);store.get('native-loss',q,reader,lambda v:True);self.assertEqual(len(calls),2)
   first=archived_publication('marketing',q,{'http_status':200,'status':'partial','source_sha256':'old','captured_at':'original'},store)
   new=archived_publication('marketing',q,{'http_status':200,'status':'partial','source_sha256':'new','captured_at':'new-source-time'},store)
   self.assertNotEqual(first['source_cache']['version'],new['source_cache']['version'])
   stale=archived_publication('marketing',q,{'http_status':200,'status':'partial','source_sha256':'new','stale':True},store)
   self.assertTrue(stale['stale'])
   news=archived_publication('news',q,{'http_status':200,'status':'stale','shared_snapshot_id':'news-v1','stale_after':'original-expiry'},store)
   self.assertIn('source_cache',news);self.assertEqual(news['status'],'stale');self.assertEqual(news['stale_after'],'original-expiry')
 def test_supplement_plan_reuses_published_weeks_and_keeps_failure_local(self):
  from source_snapshots import prepare_supplements
  from types import SimpleNamespace
  calls=[]
  def research(name,q):
   calls.append((name,q))
   if name=='fc.query_game_news':raise ValueError('missing')
   return {'evidence_id':'ev_fixture','data':{'status':'available'}}
  rows=prepare_supplements(SimpleNamespace(research=research),'2026-10-16','2026-10-16')
  marketing=[q for name,q in calls if name=='fc.query_marketing_snapshot']
  self.assertEqual(marketing[0],{'profile':'FC27','start':'2026-10-05','end':'2026-10-11'})
  self.assertEqual(len(rows),6);self.assertEqual(rows[-1]['status'],'not_available')
 def test_prepared_input_registers_daily_trend_without_model_queries(self):
  from types import SimpleNamespace
  from source_snapshots import prepared_brief
  queries=[];daily={'evidence_id':'ev_trend','data':{'groups':[{'group':{'day':'2026-10-16'},'revenue_usd':'123'}]}}
  book=SimpleNamespace(native=None,query=lambda q:(queries.append(q) or daily),research=lambda n,q:{'evidence_id':'ev_native','data':{'status':'unavailable'}})
  brief=prepared_brief(book,'2026-10-16','2026-10-16')
  self.assertEqual(queries[0]['start'],'2026-10-03');self.assertEqual(queries[0]['end'],'2026-10-16')
  self.assertEqual(brief['daily_detail_trend'],daily)
  prepared_brief(book,'2026-10-05','2026-10-11',True)
  self.assertEqual(queries[1]['start'],'2026-09-12');self.assertEqual(queries[1]['group_by'],['day'])
 def test_admin_ready_does_not_freeze_pending_order_supplement(self):
  from source_snapshots import native_cacheable,native_pending
  partial={'status':'available','authoritative_fields':{k:{'status':'available'} for k in ('orders','revenueUsd')},
   'source_status':{'Admin':{'status':'available','stale':False},'Order':{'status':'pending','stale':True}}}
  self.assertTrue(native_pending(partial));self.assertFalse(native_cacheable(partial))
  full=copy.deepcopy(partial);full['source_status']['Order']={'status':'available','stale':False}
  self.assertFalse(native_pending(full));self.assertTrue(native_cacheable(full))
  import ast,threading,hashlib
  tree=ast.parse((ROOT/'source/fs_evidence.py').read_text('utf8'))
  node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SourcePins')
  scope=dict(threading=threading,deepcopy=copy.deepcopy,digest=lambda v:hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest())
  exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-source-pins','exec'),scope)
  replies=iter([dict(partial,http_status=200),dict(full,http_status=200)])
  pinned=scope['SourcePins']().wrap(lambda q:next(replies),'native-test',ready=native_cacheable)
  self.assertTrue(native_pending(pinned({})));self.assertTrue(native_cacheable(pinned({})))
  self.assertTrue(native_cacheable(pinned({})))
  with tempfile.TemporaryDirectory() as tmp:
   store=SnapshotStore(Path(tmp)/'private',lambda:datetime(2026,10,17,2,tzinfo=timezone.utc));q={'start':'2026-10-16','end':'2026-10-16'}
   old=store.get('native-statistics',q,lambda:partial,lambda v:True)
   updated=store.get('native-statistics',q,lambda:full,native_cacheable)
   self.assertNotEqual(old['source_cache']['version'],updated['source_cache']['version'])
   self.assertFalse(updated['source_cache']['reused']);self.assertTrue(native_cacheable(updated))
 def test_weekly_news_readiness_uses_frozen_hash_and_expiry(self):
  import hashlib
  import ast
  tree=ast.parse((ROOT/'source/nightly.py').read_text('utf8'))
  nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('civil','preparation_status')]
  scope=dict(datetime=datetime,Path=Path,json=json,hashlib=hashlib,SHANGHAI=timezone(timedelta(hours=8)))
  exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-nightly-readiness','exec'),scope)
  preparation_status=scope['preparation_status']
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);public=root/'public';public.mkdir()
   now=datetime(2026,10,18,0,40,tzinfo=timezone(timedelta(hours=8)))
   news={'status':'succeeded','collected_at':'2026-10-17T00:06:00+08:00','stale_after':'2026-10-24T07:00:00+08:00'}
   raw=json.dumps(news).encode();(public/'game-monitor.json').write_bytes(raw)
   (public/'game-monitor.status.json').write_text(json.dumps({'day':'2026-10-17','phase':'completed','status':'succeeded','public_sha256':hashlib.sha256(raw).hexdigest()}),'utf8')
   (public/'management.status.json').write_text(json.dumps({'day':'2026-10-18','phase':'completed','status':'facts_ready','fact_status':'available'}),'utf8')
   record=root/'marketing.json';record.write_text(json.dumps({'completed_at_utc':'2026-10-17T16:20:00+00:00','steps':{'collect':0},'publication_performed':True}),'utf8')
   self.assertEqual(preparation_status(now,boss_root=root,marketing_record=record),(True,[]))
   (public/'game-monitor.json').write_text('{}','utf8')
   self.assertFalse(preparation_status(now,boss_root=root,marketing_record=record)[0])
 def test_preparation_is_once_per_day_and_outside_model_path(self):
  from types import SimpleNamespace
  from unittest.mock import patch
  import source_snapshots as snapshots
  with tempfile.TemporaryDirectory() as tmp:
   store=snapshots.SnapshotStore(Path(tmp)/'private')
   service=SimpleNamespace(nightly=SimpleNamespace(config=lambda:{'enabled':True}),detail=SimpleNamespace(config={'enabled':True}))
   prep=snapshots.Preparation(service);calls=[]
   thread=SimpleNamespace(start=lambda:calls.append('started'),is_alive=lambda:False)
   with patch.object(snapshots,'SnapshotStore',return_value=store),patch.object(snapshots.threading,'Thread',return_value=thread):
    prep.tick(datetime(2026,10,17,0,24,tzinfo=snapshots.SHANGHAI));self.assertEqual(calls,[])
    prep.tick(datetime(2026,10,17,0,25,tzinfo=snapshots.SHANGHAI));prep.tick(datetime(2026,10,17,0,26,tzinfo=snapshots.SHANGHAI))
    self.assertEqual(calls,['started'])
    prep.tick(datetime(2026,10,18,8,0,tzinfo=snapshots.SHANGHAI));self.assertEqual(calls,['started'])
 def test_reuse_versions_day_rollover_and_failed_refresh(self):
  with tempfile.TemporaryDirectory() as tmp:
   now=[datetime(2026,10,17,2,tzinfo=timezone.utc)];calls=[]
   store=SnapshotStore(Path(tmp)/'private',lambda:now[0]);query={'start':'2026-10-16','end':'2026-10-16'}
   def reader():calls.append(1);return {'status':'available','captured_at':'source-original'}
   valid=lambda v:v['status']=='available'
   a=store.get('native-statistics',query,reader,valid)
   b=SnapshotStore(store.root,store.clock).get('native-statistics',query,reader,valid)
   self.assertEqual(len(calls),1);self.assertEqual(a['source_cache']['version'],b['source_cache']['version'])
   self.assertTrue(b['source_cache']['reused']);self.assertEqual(b['captured_at'],'source-original')
   with self.assertRaises(PermissionError):store.get('native-statistics',query,reader,valid,enabled=False)
   now[0]+=timedelta(days=1)
   failed=store.get('native-statistics',query,lambda:{'status':'unavailable'},valid)
   self.assertEqual(failed['status'],'unavailable');self.assertNotIn('source_cache',failed)
   c=store.get('native-statistics',query,reader,valid)
   self.assertEqual(len(calls),2);self.assertNotEqual(c['source_cache']['version'],a['source_cache']['version'])
   self.assertEqual(len(list(store.root.glob('*.data.json'))),2)
 def test_save_time_is_after_source_fetch(self):
  with tempfile.TemporaryDirectory() as tmp:
   now=[datetime(2026,10,17,15,59,tzinfo=timezone.utc)];store=SnapshotStore(Path(tmp)/'private',lambda:now[0])
   def reader():now[0]+=timedelta(minutes=2);return {'status':'available'}
   q={'start':'2026-10-16','end':'2026-10-16'}
   first=store.get('native-statistics',q,reader,lambda v:True)
   second=store.get('native-statistics',q,lambda:self.fail('already saved today'),lambda v:True)
   self.assertEqual(first['source_cache']['saved_at'],now[0].isoformat());self.assertTrue(second['source_cache']['reused'])
 def test_corruption_and_future_clock_do_not_become_cache_hits(self):
  with tempfile.TemporaryDirectory() as tmp:
   now=[datetime(2026,10,17,2,tzinfo=timezone.utc)];store=SnapshotStore(Path(tmp)/'private',lambda:now[0]);calls=[]
   def reader():calls.append(1);return {'status':'available'}
   q={'start':'2026-10-15','end':'2026-10-15'};valid=lambda v:True
   a=store.get('native-statistics',q,reader,valid);now[0]-=timedelta(hours=1)
   store.get('native-statistics',q,reader,valid);self.assertEqual(len(calls),2)
   for p in store.root.glob('*.data.json'):
    v=json.loads(p.read_text('utf8'));v['value']['status']='tampered';p.write_text(json.dumps(v),'utf8')
   with self.assertRaises(ValueError):store.get('native-statistics',q,reader,valid)
 def test_open_day_not_persisted_and_query_plan_keeps_games_and_dates(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=SnapshotStore(Path(tmp)/'private',lambda:datetime(2026,10,17,2,tzinfo=timezone.utc))
   self.assertEqual(store.get('native-statistics',{'end':'2026-10-17'},lambda:{'live':True},lambda v:True),{'live':True})
   self.assertFalse(store.root.exists())
  rows=report_queries('2026-10-05','2026-10-11',True)
  self.assertIn({'profile':'FC26','start':'2025-10-05','end':'2025-10-11'},rows)
  self.assertIn({'profile':'FC27','start':'2026-09-12','end':'2026-10-11'},rows)


class NativeTotalAcceptance(unittest.TestCase):
 def test_original_statistics_drive_metrics_profit_and_target_detail_stays_separate(self):
  r,e=title_fixtures.TitlesAndGoals().facts();e['ev_native']=projection_fixtures.PartialProjection().native(revenue='130',orders=5)
  e['ev_native']['data']['authoritative_fields']['orders']['unit']='orders'
  e['ev_detail_platform']=projection_fixtures.PartialProjection().evidence(group='platform')
  c=project(r,e,{'profit_target_snapshot':{'period':'2026-10','monthly_profit_usd':3100}},'f'*64)
  self.assertEqual([m['value'] for m in c['metrics']],['$130.00','5','$26.00','26.0%'])
  self.assertEqual(c['finance']['estimates']['current']['amount_usd'],'26.00')
  chart=next(x for x in c['charts'] if x['id']=='platform')
  self.assertEqual(chart['rows'][0]['current'],'100');self.assertIn('不作为原生总盘',chart['scope'])
  del e['ev_native'];c=project(r,e,{'profit_target_snapshot':{'period':'2026-10','monthly_profit_usd':3100}},'f'*64)
  self.assertEqual(c['metrics'][0]['value'],'未提供');self.assertEqual(c['metrics'][3]['value'],'未提供')
 def test_native_authority_zero_latest_and_scope_validation(self):
  row=projection_fixtures.PartialProjection().native(revenue='0',orders=0);other=copy.deepcopy(row)
  for field in other['data']['authoritative_fields'].values():field.update(system='order.p2pah.cn',value=999,capturedAt='2026-10-16T02:00:00Z')
  evidence={'admin':row,'order':other};get=lambda:native_total(evidence,'fixture','2026-10-15','2026-10-15')
  self.assertEqual(get()[1:3],(0,0))
  del row['data']['authoritative_fields']['revenueUsd'];self.assertEqual(get()[1],999)
  other['query']['profile']='FC26';self.assertIsNone(get())
  other['query']['profile']='FC27';other['data']['authoritative_fields']['revenueUsd']['unit']='CNY';self.assertIsNone(get())

if __name__=='__main__':unittest.main()
