"""Offline tests of the exact current shared source plus the minimal timer patch."""
import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_range_api as fixture

api=fixture.api
ROOT=Path(__file__).resolve().parent.parent

class TimerParserTests(unittest.TestCase):
 def setUp(self):api.JOBS.clear();api.STARTS.clear()

 def test_each_supported_unit(self):
  for unit,seconds in [('w',604800),('d',86400),('h',3600),('min',60),('m',60),('s',1)]:
   with self.subTest(unit=unit):self.assertEqual(api.monotonic_schedule_seconds('1'+unit),seconds)

 def test_mixed_week_day_hour_minute_second(self):
  self.assertEqual(api.monotonic_schedule_seconds('1w 2d 3h 4m 5.125s'),788645.125)

 def test_compact_and_unit_whitespace(self):
  self.assertEqual(api.monotonic_schedule_seconds(' 1w2d3h4min5.125s '),788645.125)
  self.assertEqual(api.monotonic_schedule_seconds('1 w 2 d 3 h 4 min 5.125 s'),788645.125)

 def test_fractional_units_and_zero(self):
  self.assertEqual(api.monotonic_schedule_seconds('0.5min 0.25s'),30.25)
  self.assertEqual(api.monotonic_schedule_seconds('0s'),0)

 def test_unknown_units_are_not_partially_accepted(self):
  for value in ['1month 2h','1y 1w','1ms','1us','1fortnight 2s','garbage 3h','3h garbage','1week','1msec','1s infinity']:
   with self.subTest(value=value),self.assertRaisesRegex(RuntimeError,'^timer_schedule_unavailable$'):api.monotonic_schedule_seconds(value)

 def test_unknown_numeric_or_empty_values_fail_closed(self):
  for value in ['', ' ', 'n/a','infinity','NaNs','-1s','+1s','1e3s','1..2s','1.s','123','1h,2s','1h;2s','.'+'s']:
   with self.subTest(value=value),self.assertRaisesRegex(RuntimeError,'^timer_schedule_unavailable$'):api.monotonic_schedule_seconds(value)

 def test_numeric_overflow_fails_closed(self):
  with self.assertRaisesRegex(RuntimeError,'^timer_schedule_unavailable$'):api.monotonic_schedule_seconds('9'*1000+'w')

 def test_exact_systemctl_command_and_monotonic_clock(self):
  with patch.object(api.subprocess,'check_output',return_value=b'NextElapseUSecMonotonic=1w 3h 31min 5.055657s\n') as run,patch.object(api.time,'monotonic',return_value=613708.066789414):
   self.assertAlmostEqual(api.timer_seconds(),3756.988867586013)
   run.assert_called_once_with(['systemctl','show','fs-transaction-collect.timer','-p','NextElapseUSecMonotonic'],timeout=4)

 def test_original_failure_replay_differs_by_exactly_one_week(self):
  source=(ROOT/'baseline/range_api.py').read_text(encoding='utf-8')
  node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='timer_seconds')
  context={'subprocess':api.subprocess,'re':api.re,'time':api.time}
  exec(compile(ast.Module(body=[node],type_ignores=[]),'exact-baseline','exec'),context)
  with patch.object(api.subprocess,'check_output',return_value=b'NextElapseUSecMonotonic=1w 3h 31min 5.055657s\n'),patch.object(api.time,'monotonic',return_value=613708.066789414):
   old=context['timer_seconds']();new=api.timer_seconds()
  self.assertLess(old,270);self.assertGreater(new,270);self.assertAlmostEqual(new-old,604800)

 def test_old_valid_day_format_is_equivalent(self):
  with patch.object(api.subprocess,'check_output',return_value=b'NextElapseUSecMonotonic=6d 2h 31min 0.5s\n'),patch.object(api.time,'monotonic',return_value=100):
   self.assertEqual(api.timer_seconds(),527360.5)

 def test_wrong_or_missing_property_is_rejected(self):
  for raw in [b'NextElapseUSecRealtime=1w',b'1w',b'',b'NextElapseUSecMonotonic=',b'NextElapseUSecMonotonic=1s\nExtra=2s']:
   with self.subTest(raw=raw),patch.object(api.subprocess,'check_output',return_value=raw),self.assertRaisesRegex(RuntimeError,'^timer_schedule_unavailable$'):api.timer_seconds()

 def test_real_near_and_past_due_guard_still_prevents_all_source_reads(self):
  q=api.query(fixture.params(),fixture.data)
  for delta in [269.999,0,-1]:
   with self.subTest(delta=delta),patch.object(api.subprocess,'check_output',return_value=('NextElapseUSecMonotonic='+str(1000+delta)+'s').encode()),patch.object(api.time,'monotonic',return_value=1000),patch.object(api,'call') as call,patch.object(api,'existing_call') as existing,patch.object(api.fcntl,'flock') as flock:
    api.capture(q,'guard');self.assertEqual(api.JOBS['guard']['error'],'scheduled_collection_due');call.assert_not_called();existing.assert_not_called();flock.assert_not_called()

 def test_exact_270_boundary_preserves_original_comparison(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(api,'WEB',Path(tmp)),patch.object(api,'timer_seconds',return_value=270),patch.object(api,'call',side_effect=RuntimeError('fixture-no-native-read')) as call:
   api.capture(api.query(fixture.params(),fixture.data),'boundary');self.assertGreater(call.call_count,0)

 def test_unknown_schedule_never_takes_lock_or_calls_source_or_publishes(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(api,'CACHE',Path(tmp)),patch.object(api.subprocess,'check_output',return_value=b'NextElapseUSecMonotonic=1month 2h'),patch.object(api,'call') as call,patch.object(api,'existing_call') as existing,patch.object(api.fcntl,'flock') as flock:
   api.capture(api.query(fixture.params(),fixture.data),'unknown');self.assertEqual(api.JOBS['unknown']['error'],'timer_schedule_unavailable');call.assert_not_called();existing.assert_not_called();flock.assert_not_called();self.assertEqual(list(Path(tmp).iterdir()),[])

 def test_running_collector_lock_remains_busy_even_with_valid_week(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(api,'WEB',Path(tmp)),patch.object(api,'CACHE',Path(tmp)),patch.object(api.subprocess,'check_output',return_value=b'NextElapseUSecMonotonic=1w 3h 31min 5.055657s'),patch.object(api.time,'monotonic',return_value=613708.066789414),patch.object(api.fcntl,'flock',side_effect=BlockingIOError()) as flock,patch.object(api,'call') as call,patch.object(api,'existing_call') as existing:
   api.capture(api.query(fixture.params(),fixture.data),'busy');self.assertEqual(api.JOBS['busy']['error'],'collector_busy');call.assert_not_called();existing.assert_not_called();self.assertEqual(flock.call_args.args[1],api.fcntl.LOCK_EX|api.fcntl.LOCK_NB);self.assertFalse((Path(tmp)/'busy.json').exists())

 def test_all_other_top_level_nodes_are_unchanged(self):
  baseline=ast.parse((ROOT/'baseline/range_api.py').read_bytes());candidate=ast.parse((ROOT/'candidate/range_api.py').read_bytes())
  def original(nodes):return [ast.dump(n,include_attributes=False) for n in nodes if not isinstance(n,ast.FunctionDef) or n.name not in {'timer_seconds','monotonic_schedule_seconds'}]
  self.assertEqual(original(baseline.body),original(candidate.body))

 def test_current_baseline_hash_is_not_old_shared_source(self):
  self.assertEqual(hashlib.sha256((ROOT/'baseline/range_api.py').read_bytes()).hexdigest(),'be8ff8342fc5229cf73934f0bb0dfbe05aff707b443b7b9fbb2d1ccac646ddc2')

 def test_all_ten_profiles_preserved_including_aion2(self):
  self.assertEqual(len(api.PROFILE_MAP),10);self.assertEqual(api.PROFILE_MAP['AION2'][2:],[826,891,'rpg'])
  self.assertEqual(api.query(fixture.params(profile='AION2'),fixture.data)['profile'],'AION2')

 def test_aion2_native_ids_and_finished_status_preserved(self):
  q=api.query(fixture.params(profile='AION2'),fixture.data)
  primary={'period':q['period'],'orders':3,'revenueUsd':40};supplement={'period':q['period'],'status':'available'}
  def native(container,script,requests,timeout):
   req=requests[0]
   if script=='primary_reader.py':self.assertEqual(req['gid'],826);self.assertEqual(req['status'],'3');return {'range':primary}
   self.assertEqual(req['game'],891);self.assertEqual(req['status'],'101');return {'range':supplement}
  with tempfile.TemporaryDirectory() as tmp,patch.object(api,'WEB',Path(tmp)),patch.object(api,'CACHE',Path(tmp)),patch.object(api,'timer_seconds',return_value=1000),patch.object(api,'call',side_effect=native):
   api.capture(q,'aion2');self.assertEqual(api.JOBS['aion2']['status'],'available');self.assertEqual(json.loads((Path(tmp)/'aion2.json').read_text())['profile']['key'],'AION2')

 def test_authenticated_read_and_write_methods_unchanged(self):
  handler=object.__new__(api.Handler);handler.path='/range?example=yes';handler.headers={'X-Auth-User':'offline-fixture'};out=[];handler.reply=lambda status,data:out.append(status)
  with patch.object(api,'get_range',return_value=(200,{'fixture':True})) as read:handler.do_GET();read.assert_called_once();self.assertEqual(out[-1],200)
  for method in ['do_POST','do_PUT','do_PATCH','do_DELETE']:getattr(handler,method)();self.assertEqual(out[-1],405)

if __name__=='__main__':unittest.main()
