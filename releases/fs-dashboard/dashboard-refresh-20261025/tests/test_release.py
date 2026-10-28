import importlib.util,sys,types,unittest
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('actual_release',R/'deploy/actual_release.py');release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
class Release(unittest.TestCase):
 def test_filter_release_covers_shared_summary_and_exact_new_assets(self):
  spec=importlib.util.spec_from_file_location('filter_release',R/'deploy/filter_release.py');wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)
  actual=types.SimpleNamespace(load_base=lambda:'original-publisher')
  with patch.dict(sys.modules,{'actual_release':actual}):self.assertEqual(wrapper.load_base(),'original-publisher')
  self.assertEqual(actual.SCOPE,'business-filter-layout-20261025');self.assertEqual(len(actual.TARGETS),11)
  self.assertEqual(actual.NEW,frozenset('source/'+n for n in ('business.js','home-business.js','legacy-business.js','shell.js','site_summary.py')))
  for n in ('live_summary.py','daily_archive.py','summary_bridge.py','site_summary.py'):self.assertEqual(actual.TARGETS['source/'+n],'/opt/fs-exact-range-20261001/'+n)
  self.assertFalse(any('units/' in n or 'auth' in n for n in actual.TARGETS))
 def test_rs_followup_is_exact_existing_backend_and_versioned_ui(self):
  spec=importlib.util.spec_from_file_location('backlog_release',R/'deploy/backlog_release.py');wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)
  actual=types.SimpleNamespace(load_base=lambda:'original-publisher')
  with patch.dict(sys.modules,{'actual_release':actual}):self.assertEqual(wrapper.load_base(),'original-publisher')
  self.assertEqual(actual.TARGETS['source/rs_backlog.py'],'/opt/fs-exact-range-20261001/rs_backlog.py');self.assertEqual(len(actual.TARGETS),6);self.assertEqual(actual.NEW,frozenset('source/'+n for n in ('business.js','home-business.js','legacy-business.js','shell.js')));self.assertEqual(actual.SCOPE,'business-dashboard-backlog-20261025')
 def test_exact_scope_and_targets(self):
  self.assertEqual(release.SCOPE,'business-dashboard-refresh-20261025');self.assertEqual(len(release.TARGETS),11)
  self.assertEqual(release.NEW,frozenset('source/'+n for n in ('business.js','home-business.js','legacy-business.js','shell.js','rs_backlog.py')))
  self.assertEqual(release.TARGETS['source/channel_effects.py'],'/opt/fs-hermes-fc/channel_effects.py')
  self.assertFalse(any('units/' in n or 'auth' in n for n in release.TARGETS))
 def test_original_publisher_and_health_wait_preserved(self):
  base=types.SimpleNamespace(approved_daily_group=lambda *args:False);original=types.SimpleNamespace(load_base=lambda:base);seen=[]
  with patch.dict(sys.modules,{'release':original,'shipping_readiness':types.SimpleNamespace(extend=lambda b,s:seen.append((b,s)))}):self.assertIs(release.load_base(),base)
  self.assertEqual(original.TARGETS,release.TARGETS);self.assertEqual(base.TARGETS_CHANGED_NAV,set(release.TARGETS.values()));self.assertEqual(seen,[(base,release.SCOPE)])
 def test_existing_knowledge_parent_reuses_exact_original_group_boundary(self):
  def group(m,root,item,info):return info.st_gid==0 or (m['scope']=='original-night' and item==root/'var/lib/fs-hermes-fc' and info.st_uid==0 and info.st_gid==9876 and info.st_mode==0o750)
  base=types.SimpleNamespace(approved_daily_group=group,HERMES_NIGHT_SCOPE='original-night',rooted=lambda r,p:r/p.lstrip('/'))
  with patch.dict(sys.modules,{'release':types.SimpleNamespace(load_base=lambda:base),'shipping_readiness':types.SimpleNamespace(extend=lambda *a:None)}):release.load_base()
  for gid,mode,uid,expected in [(9876,0o750,0,True),(9876,0o770,0,False),(9877,0o750,0,False),(9876,0o750,1,False)]:
   self.assertEqual(base.approved_daily_group({'scope':release.SCOPE},Path('/'),Path('/var/lib/fs-hermes-fc'),types.SimpleNamespace(st_uid=uid,st_gid=gid,st_mode=mode)),expected)
  self.assertFalse(base.approved_daily_group({'scope':'other'},Path('/'),Path('/var/lib/fs-hermes-fc'),types.SimpleNamespace(st_uid=0,st_gid=9876,st_mode=0o750)))

class ConcurrentPublisher(unittest.TestCase):
 def manifest(self,module,states):
  return dict(scope=module.SCOPE,runtimeRequired={module.RANGE:{'ActiveState':'active'},'fs-hermes-fc.service':{'ActiveState':'active'}},
   maintenanceBefore={u:{k:states[u][k] for k in ('ActiveState','UnitFileState')} for u in (*module.TIMERS,module.RANGE)})
 def module(self):
  spec=importlib.util.spec_from_file_location('p4_release_contract',R/'deploy/concurrent_release.py')
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
 def setup(self):
  from contextlib import contextmanager
  import copy
  module=self.module();actions=[];states={}
  def value(active='inactive',enabled='static',pid='0'):
   return dict(LoadState='loaded',ActiveState=active,SubState='running' if active=='active' else 'dead',MainPID=pid,ControlPID='0',UnitFileState=enabled)
  for unit in module.SOURCES:states[unit]=value()
  for unit in module.TIMERS:states[unit]=value(enabled='disabled')
  states[module.TIMERS[0]]=value('active','enabled');states[module.RANGE]=value('active','enabled','101')
  states['fs-hermes-fc.service']=value('active','disabled','499')
  outer=self
  class Control(module.SystemControl):
   def __init__(self,root):self.before={};self.paused=[]
   def state(self,unit):return dict(states[unit])
   def idle(self):
    if any(states[u]['MainPID']!='0' or states[u]['ActiveState'] not in ('inactive','failed') for u in module.SOURCES):raise ValueError('p4_source_still_running')
  control=Control(Path('/'))
  def command(args,**kwargs):
   actions.append(tuple(args));verb,unit=args[1:3]
   if verb=='stop':states[unit].update(ActiveState='inactive',MainPID='0',ControlPID='0')
   elif verb=='start':states[unit].update(ActiveState='active',MainPID='202' if unit==module.RANGE else '0')
   else:outer.fail('unexpected system action')
   return types.SimpleNamespace(returncode=0)
  self.addCleanup(patch.stopall);patch.object(module.subprocess,'run',side_effect=command).start()
  @contextmanager
  def file_lease(base,root,path):actions.append(('lease',path));yield
  patch.object(module,'lease',file_lease).start()
  class Fence:
   modified=False;confirmed=False
   def unlock_database(self):actions.append(('original-database-unlock',))
  # Execute the existing publisher's actual stop method, rather than handwave a stopped flag.
  raw=R.parents[0]/'channel-effects-20261021/deploy/release_navigation_base.py'
  import ast
  cls=next(n for n in ast.parse(raw.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='HermesAdmissionFence')
  node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='stop_then_unlock_database')
  namespace=dict(subprocess=module.subprocess);exec(compile(ast.Module(body=[node],type_ignores=[]),'original-stop-method','exec'),namespace)
  Fence.stop_then_unlock_database=namespace['stop_then_unlock_database'];fence=Fence()
  @contextmanager
  def admission(m,root):actions.append(('admission-enter',));yield fence;actions.append(('admission-exit',))
  @contextmanager
  def web(m,root):actions.append(('snapshot-then-web',));yield
  seen=[]
  def guards(m,root,stopped=False):
   if stopped:raise ValueError('invalid controlled reader stop')
   seen.append(copy.deepcopy(m))
   for unit,expected in m['runtimeRequired'].items():
    if any(states[unit][k]!=v for k,v in expected.items()):raise ValueError('protected unit changed')
  base=types.SimpleNamespace(HERMES_HISTORY_SCOPE=module.SCOPE,live_lock=web,hermes_admission_fence=admission,
   guards=guards,inspect=lambda m,s,r:guards(m,r),rollback_journal=lambda b,j,r:actions.append(('original-rollback',)),
   rooted=lambda root,path:Path(root)/path.lstrip('/'),no_target_link=lambda p:None,apply=object())
  original_apply=base.apply;base=module.extend(base,lambda root:control)
  return module,base,control,fence,states,actions,seen,original_apply
 def test_exact_existing_targets_and_original_apply_unchanged(self):
  module,base,*rest=self.setup();self.assertEqual(len(module.TARGETS),7);self.assertFalse(module.NEW)
  self.assertIs(base.apply,rest[-1]);self.assertFalse(any('user_' in path or path.endswith('.db') for path in module.TARGETS.values()))
  self.assertEqual(module.TARGETS['source/cache_retention.py'],'/opt/fs-hermes-fc/cache_retention.py')
 def test_legacy_centos_timer_show_projects_full_metadata_without_requesting_pid_properties(self):
  module=self.module();control=module.SystemControl.__new__(module.SystemControl)
  import subprocess
  def legacy(args,**kwargs):
   if '-p' in args:raise subprocess.CalledProcessError(1,args)
   self.assertEqual(args,['systemctl','show',module.TIMERS[0],'--no-pager'])
   return 'LoadState=loaded\nActiveState=active\nSubState=waiting\nUnitFileState=enabled\nEnvironment=synthetic_not_for_output\nExecStart=synthetic_not_for_output\n'
  with patch.object(module.subprocess,'check_output',side_effect=legacy) as show:
   value=control.state(module.TIMERS[0]);show.assert_called_once()
  self.assertEqual(value,dict(LoadState='loaded',ActiveState='active',SubState='waiting',UnitFileState='enabled'))
  self.assertNotIn('MainPID',value);self.assertNotIn('ControlPID',value)

 def test_full_service_metadata_keeps_real_pids_and_rejects_missing_or_unknown_state(self):
  module=self.module();control=module.SystemControl.__new__(module.SystemControl)
  raw='LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\nControlPID=0\nUnitFileState=static\nExecStart=synthetic_not_for_output\n'
  with patch.object(module.subprocess,'check_output',return_value=raw) as show:
   value=control.state(module.SOURCES[0])
  self.assertEqual(show.call_args.args[0],['systemctl','show',module.SOURCES[0],'--no-pager'])
  self.assertEqual((value['MainPID'],value['ControlPID']),('0','0'));self.assertNotIn('ExecStart',value)
  for bad in (raw.replace('MainPID=0\n',''),raw.replace('ControlPID=0\n',''),raw.replace('MainPID=0','MainPID=unknown'),raw.replace('LoadState=loaded','LoadState=not-found'),raw.replace('ActiveState=inactive\n','')):
   with self.subTest(metadata=bad.splitlines()[:1]),patch.object(module.subprocess,'check_output',return_value=bad):
    with self.assertRaisesRegex(ValueError,'p4_source_unit_unavailable'):control.state(module.SOURCES[0])

 def idle_with_jobs(self,raw):
  module=self.module();control=module.SystemControl.__new__(module.SystemControl)
  control.state=lambda unit:dict(ActiveState='inactive',MainPID='0',ControlPID='0')
  command=['busctl','call','org.freedesktop.systemd1','/org/freedesktop/systemd1','org.freedesktop.systemd1.Manager','ListJobs']
  def read(args,**kwargs):
   if args!=command:
    raise module.subprocess.CalledProcessError(1,args,output='legacy systemctl list-jobs fails even with real rows')
   return raw
  with patch.object(module.subprocess,'check_output',side_effect=read) as jobs,patch.object(module.Path,'iterdir',return_value=[]):
   result=control.idle();jobs.assert_called_once_with(command,text=True)
  return result

 def test_real_systemd219_typed_six_jobs_cannot_be_misclassified_as_empty(self):
  rows=[(21384922,'fs-pricing-alerts.service','fs_2dpricing_2dalerts_2eservice'),
   (21377981,'sales-dashboard-sync.service','sales_2ddashboard_2dsync_2eservice'),
   (21384829,'fs-channel-backfill.service','fs_2dchannel_2dbackfill_2eservice'),
   (21383621,'fs-transaction-collect.service','fs_2dtransaction_2dcollect_2eservice'),
   (21384458,'aion2-watch.service','aion2_2dwatch_2eservice'),
   (21384736,'fs-data-archive.service','fs_2ddata_2darchive_2eservice')]
  raw='a(usssoo) 6 '+ ' '.join(f'{ident} "{unit}" "start" "running" "/org/freedesktop/systemd1/job/{ident}" "/org/freedesktop/systemd1/unit/{path}"' for ident,unit,path in rows)
  with self.assertRaisesRegex(ValueError,'p4_source_job_pending'):self.idle_with_jobs(raw)

 def test_typed_empty_or_unrelated_jobs_continue_but_invalid_or_failed_transport_never_does(self):
  self.assertIsNone(self.idle_with_jobs('a(usssoo) 0\n'))
  row='1 "unrelated.service" "start" "running" "/org/freedesktop/systemd1/job/1" "/org/freedesktop/systemd1/unit/unrelated_2eservice"'
  self.assertIsNone(self.idle_with_jobs('a(usssoo) 1 '+row))
  for raw in (None,'','a(ssssoo) 0','a(usssoo) -1','a(usssoo) one','a(usssoo) 2 '+row,'a(usssoo) 0 extra',
   'a(usssoo) 1 '+row.rsplit(' ',1)[0],'a(usssoo) 1 '+row.replace('1 ', 'bad ',1),
   'a(usssoo) 1 '+row.replace('/job/1','/job/2'),'a(usssoo) 1 '+row.replace('/unit/unrelated_2eservice','/unit/not-valid'),
   'a(usssoo) 1 '+row.replace('"unrelated.service"','""'),'a(usssoo) 1 '+row.replace('"start"','""'),
   'a(usssoo) 1 '+row.replace('"running"','""'),'a(usssoo) 1 '+row[:-1]):
   with self.subTest(typed=str(raw)[:24]),self.assertRaisesRegex(ValueError,'p4_source_jobs_invalid'):self.idle_with_jobs(raw)
  module=self.module();control=module.SystemControl.__new__(module.SystemControl)
  control.state=lambda unit:dict(ActiveState='inactive',MainPID='0',ControlPID='0')
  with patch.object(module.subprocess,'check_output',side_effect=module.subprocess.CalledProcessError(1,['busctl'],output='a(usssoo) 0')):
   with self.assertRaises(module.subprocess.CalledProcessError):control.idle()
  control.state=lambda unit:dict(ActiveState='active',MainPID='99',ControlPID='0')
  with patch.object(module.subprocess,'check_output') as jobs:
   with self.assertRaisesRegex(ValueError,'p4_source_still_running'):control.idle()
   jobs.assert_not_called()
 def test_idle_reads_real_cmdline_bytes_and_rejects_legacy_source_scripts(self):
  import tempfile
  module=self.module();control=module.SystemControl.__new__(module.SystemControl)
  control.state=lambda unit:dict(ActiveState='inactive',MainPID='0',ControlPID='0')
  command=['busctl','call','org.freedesktop.systemd1','/org/freedesktop/systemd1','org.freedesktop.systemd1.Manager','ListJobs']
  scripts=('/opt/fs-hermes-fc/channel_cache.py','/opt/fs-exact-range-20261001/archive_jobs.py',
   '/opt/fs-transaction-snapshot/collector.py','/opt/fs-hermes-fc/user_jobs.py')
  with tempfile.TemporaryDirectory() as directory:
   process=Path(directory)/'123';process.mkdir()
   original_iterdir=module.Path.iterdir
   def processes(path):return iter((process,)) if path==Path('/proc') else original_iterdir(path)
   cases=[(b'/opt/python39/bin/python3\0-B\0/opt/unrelated.py\0',False),
    (b'/usr/bin/unrelated\0',False)]+[(b'/opt/python39/bin/python3\0-B\0'+script.encode()+b'\0',True) for script in scripts]
   for raw,blocked in cases:
    with self.subTest(cmdline=raw),patch.object(module.Path,'iterdir',processes),patch.object(module.subprocess,'check_output',return_value='a(usssoo) 0') as jobs:
     (process/'cmdline').write_bytes(raw)
     if blocked:
      with self.assertRaisesRegex(ValueError,'p4_legacy_source_process_running'):control.idle()
     else:self.assertIsNone(control.idle())
     jobs.assert_called_once_with(command,text=True)

 def test_real_frozen_validate_keeps_exact_runtime_fields_and_accepts_separate_maintenance_record(self):
  import copy,hashlib,tempfile
  module,_,_,_,states,*_=self.setup()
  path=R.parent/'channel-effects-20261021/deploy/release_navigation_base.py';raw=path.read_bytes()
  self.assertEqual(hashlib.sha256(raw).hexdigest(),'1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de')
  base=types.ModuleType('original_frozen_validate_contract');base.__file__=str(path)
  exec(compile(raw,str(path),'exec'),base.__dict__)
  base.HERMES_HISTORY_SCOPE,base.HERMES_HISTORY_TARGETS=module.SCOPE,module.TARGETS
  base.expected_files=lambda manifest:set(module.TARGETS);base.target_for=lambda relative:module.TARGETS[relative]
  protected={*base.HERMES_TARGETS.values(),*('/opt/fs-exact-range-20261001/'+name for name in
   ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')),
   '/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py'}-set(module.TARGETS.values())
  with tempfile.TemporaryDirectory() as folder:
   stage=Path(folder);rows=[]
   for relative,target in module.TARGETS.items():
    candidate=stage/'candidate'/relative;candidate.parent.mkdir(parents=True,exist_ok=True);candidate.write_bytes(b'# synthetic publisher fixture\n')
    rows.append(dict(candidate=relative,target=target,sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),beforeSha256='a'*64,owner='0:0',mode='0o644'))
   manifest=dict(self.manifest(module,states),schemaVersion=1,files=rows,businessWrites=False,timersChanged=False,
    imageId='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544',
    unchangedRequired=[dict(path=name,sha256='b'*64) for name in protected])
   self.assertEqual(len(base.validate(manifest,stage)),7)
   bad=copy.deepcopy(manifest);bad['runtimeRequired'][module.RANGE]['UnitFileState']='enabled'
   with self.assertRaisesRegex(ValueError,'active Hermes update services required'):base.validate(bad,stage)
   self.assertEqual(len(base.validate(manifest,stage)),7)
 def test_inspect_is_readonly_and_external_stopped_flag_cannot_bypass_guard(self):
  module,base,control,fence,states,actions,seen,_=self.setup()
  manifest=self.manifest(module,states)
  base.inspect(manifest,Path('/fixture'),Path('/fixture'))
  self.assertFalse(any(action[0]=='systemctl' for action in actions))
  self.assertEqual(actions[0],('lease',module.ADMISSION));self.assertFalse(fence.modified)
  with self.assertRaisesRegex(ValueError,'invalid controlled reader stop'):base.guards(manifest,Path('/fixture'),True)
 def test_apply_real_stop_precedes_controlled_guards_restore_only_original_active_state(self):
  module,base,control,fence,states,actions,seen,_=self.setup()
  manifest=self.manifest(module,states)
  with base.live_lock(manifest,Path('/fixture')):
   self.assertEqual(states[module.RANGE]['MainPID'],'0')
   with base.hermes_admission_fence(manifest,Path('/fixture')) as reused:self.assertIs(reused,fence)
   base.guards(manifest,Path('/fixture'))
   self.assertEqual(seen[-1]['runtimeRequired'][module.RANGE],{'ActiveState':'inactive'})
   self.assertEqual(manifest['runtimeRequired'][module.RANGE],{'ActiveState':'active'})
   self.assertEqual(manifest['maintenanceBefore'][module.RANGE]['UnitFileState'],'enabled')
   states[module.RANGE].update(ActiveState='inactive',MainPID='999')
   with self.assertRaisesRegex(ValueError,'stop_not_confirmed'):base.guards(manifest,Path('/fixture'))
   states[module.RANGE]['MainPID']='0'
  self.assertEqual(states[module.RANGE]['ActiveState'],'active')
  self.assertEqual(states[module.TIMERS[0]]['ActiveState'],'active')
  self.assertTrue(all(states[u]['ActiveState']=='inactive' for u in module.TIMERS[1:]))
  commands=[a for a in actions if a[0]=='systemctl']
  self.assertEqual(commands,[('systemctl','stop',module.TIMERS[0]),('systemctl','stop',module.RANGE),('systemctl','start',module.RANGE),('systemctl','start',module.TIMERS[0])])
  self.assertLess(actions.index(('admission-enter',)),actions.index(('systemctl','stop',module.TIMERS[0])))
  self.assertLess(actions.index(('snapshot-then-web',)),actions.index(('systemctl','stop',module.RANGE)))
 def test_old_source_busy_defers_before_reader_stop_and_restores_timer(self):
  module,base,control,fence,states,actions,*_=self.setup()
  states[module.SOURCES[0]].update(ActiveState='active',MainPID='303')
  with self.assertRaisesRegex(ValueError,'source_still_running'):
   with base.live_lock(self.manifest(module,states),Path('/fixture')):self.fail('writer reached')
  self.assertNotIn(('systemctl','stop',module.RANGE),actions)
  self.assertEqual(states[module.TIMERS[0]]['ActiveState'],'active')
 def test_rollback_stops_reader_before_original_restore_and_unconfirmed_never_auto_starts_bad_code(self):
  module,base,control,fence,states,actions,*_=self.setup();manifest=self.manifest(module,states)
  with base.live_lock(manifest,Path('/fixture')):
   states[module.RANGE].update(ActiveState='active',MainPID='202')
   base.rollback_journal(Path('/backup'),dict(manifest=manifest),Path('/fixture'))
   self.assertEqual(states[module.RANGE]['MainPID'],'0');self.assertEqual(actions[-1],('original-rollback',))
   fence.modified=True
  self.assertEqual(states[module.RANGE]['ActiveState'],'inactive')
  self.assertNotIn(('systemctl','start',module.RANGE),actions)
  self.assertEqual(states[module.TIMERS[0]]['ActiveState'],'inactive')
 def test_restore_failure_does_not_skip_api_or_other_original_active_timers(self):
  module,base,control,fence,states,actions,*_=self.setup()
  states[module.TIMERS[1]].update(ActiveState='active',UnitFileState='enabled')
  control.pause(self.manifest(module,states));states[module.RANGE].update(ActiveState='inactive',MainPID='0')
  run=module.subprocess.run.side_effect
  def fail_first_timer(args,**kwargs):
   if args==['systemctl','start',module.TIMERS[0]]:actions.append(tuple(args));raise OSError('fixture timer start failure')
   return run(args,**kwargs)
  module.subprocess.run.side_effect=fail_first_timer
  with self.assertRaisesRegex(ValueError,'restore_incomplete'):control.restore(True)
  self.assertEqual(states[module.RANGE]['ActiveState'],'active')
  self.assertEqual(states[module.TIMERS[1]]['ActiveState'],'active')
  starts=[a for a in actions if a[:2]==('systemctl','start')]
  self.assertEqual(starts,[('systemctl','start',module.RANGE),('systemctl','start',module.TIMERS[0]),('systemctl','start',module.TIMERS[1])])


class TransactionPublisher(unittest.TestCase):
 def module(self):
  spec=importlib.util.spec_from_file_location('transaction_release_contract',R/'deploy/transaction_release.py')
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
 def base(self,root):
  import hashlib,os
  from contextlib import contextmanager
  self.original_calls=[]
  @contextmanager
  def web(manifest,base_root):
   import fcntl
   path=base_root/'var/www/dashboard/fs-home/transactions/collector.lock';path.parent.mkdir(parents=True,exist_ok=True)
   fd=os.open(path,os.O_RDWR|os.O_CREAT,0o600)
   try:
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);self.original_calls.append('web-enter');yield
   finally:self.original_calls.append('web-exit');os.close(fd)
  return types.SimpleNamespace(HERMES_HISTORY_SCOPE=self.module().SCOPE,live_lock=web,
   inspect=lambda m,s,r:dict(original=True),rooted=lambda r,p:Path(r)/p.lstrip('/'),
   no_target_link=lambda p:None,digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
 def legacy(self,root):
  import base64,hashlib
  path=root/'opt/fs-transaction-snapshot/atomic_snapshot.py';path.parent.mkdir(parents=True)
  raw=base64.b64decode((R/'tests/fixtures/atomic_snapshot_live_20261028.b64').read_bytes())
  self.assertEqual(hashlib.sha256(raw).hexdigest(),self.module().LEGACY_ATOMIC_SHA);path.write_bytes(raw)
  (root/'var/www/dashboard/fs-home/transactions').mkdir(parents=True)
 def test_scope_is_only_two_existing_targets_through_original_actual_adapter(self):
  module=self.module();base=self.base(Path('/'));actual=types.SimpleNamespace(load_base=lambda:base)
  with patch.dict(sys.modules,actual_release=actual):self.assertIs(module.load_base(),base)
  self.assertEqual(actual.SCOPE,module.SCOPE);self.assertEqual(actual.NEW,frozenset())
  self.assertEqual(actual.TARGETS,{'source/atomic_snapshot.py':'/opt/fs-transaction-snapshot/atomic_snapshot.py','source/collector.py':'/opt/fs-transaction-snapshot/collector.py'})
  base.HERMES_HISTORY_SCOPE='unbound'
  with self.assertRaisesRegex(ValueError,'web_fence_not_bound'):module.extend(base)
 @unittest.skipUnless(__import__('os').name=='posix','real Linux publication locks')
 def test_legacy_bootstrap_is_readonly_until_apply_and_unknown_missing_inode_is_rejected(self):
  import os,tempfile
  module=self.module();manifest=dict(scope=module.SCOPE)
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.legacy(root);base=module.extend(self.base(root));lock=base.rooted(root,module.SNAPSHOT_LOCK)
   self.assertTrue(base.inspect(manifest,root,root)['original']);self.assertFalse(lock.exists())
   with base.live_lock(manifest,root):self.assertTrue(lock.exists());self.assertEqual(lock.stat().st_mode&0o777,0o600)
   self.assertTrue(lock.exists())
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.legacy(root);base=module.extend(self.base(root));base.rooted(root,module.ATOMIC_TARGET).write_bytes(b'new or unknown collector')
   with self.assertRaisesRegex(ValueError,'snapshot_lock_missing'):base.inspect(manifest,root,root)
   with self.assertRaisesRegex(ValueError,'snapshot_lock_missing'):
    with base.live_lock(manifest,root):pass
   self.assertFalse(base.rooted(root,module.SNAPSHOT_LOCK).exists())
 @unittest.skipUnless(__import__('os').name=='posix','real Linux publication locks')
 def test_running_collection_blocks_publish_but_not_unrelated_knowledge(self):
  import fcntl,os,tempfile
  module=self.module();manifest=dict(scope=module.SCOPE)
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.legacy(root);base=module.extend(self.base(root));lock=base.rooted(root,module.SNAPSHOT_LOCK)
   fd=os.open(lock,os.O_RDWR|os.O_CREAT,0o600)
   try:
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    with self.assertRaisesRegex(ValueError,'transaction_snapshot_busy'):base.inspect(manifest,root,root)
    with self.assertRaisesRegex(ValueError,'transaction_snapshot_busy'):
     with base.live_lock(manifest,root):pass
    other=dict(scope='knowledge-only')
    with base.live_lock(other,root):self.assertTrue(base.inspect(other,root,root)['original'])
   finally:os.close(fd)
 @unittest.skipUnless(__import__('os').name=='posix','real Linux publication locks')
 def test_legacy_browser_owner_also_blocks_both_publication_entries(self):
  import fcntl,tempfile
  module=self.module();manifest=dict(scope=module.SCOPE)
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.legacy(root);base=module.extend(self.base(root))
   with (root/'var/www/dashboard/fs-home/transactions/collector.lock').open('a+b') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    with self.assertRaises(BlockingIOError):base.inspect(manifest,root,root)
    with self.assertRaises(BlockingIOError):
     with base.live_lock(manifest,root):pass
   with base.live_lock(manifest,root):self.assertTrue(base.inspect(manifest,root,root)['original'])
 @unittest.skipUnless(__import__('os').name=='posix','real Linux publication locks')
 def test_actual_context_holds_both_locks_allows_inner_inspect_and_releases_on_failure(self):
  import fcntl,tempfile
  from concurrent.futures import ThreadPoolExecutor
  module=self.module();manifest=dict(scope=module.SCOPE)
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);self.legacy(root);base=module.extend(self.base(root))
   with self.assertRaisesRegex(RuntimeError,'fixture_failure'):
    with base.live_lock(manifest,root):
     self.assertTrue(base.inspect(manifest,root,root)['original'])
     for name in ('transaction-snapshot.lock','collector.lock'):
      with (root/'var/www/dashboard/fs-home/transactions'/name).open('a+b') as lock:
       with self.assertRaises(BlockingIOError):fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
     with ThreadPoolExecutor(max_workers=1) as pool:
      with self.assertRaisesRegex(ValueError,'transaction_snapshot_busy'):pool.submit(base.inspect,manifest,root,root).result(timeout=1)
     raise RuntimeError('fixture_failure')
   for name in ('transaction-snapshot.lock','collector.lock'):
    with (root/'var/www/dashboard/fs-home/transactions'/name).open('a+b') as lock:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)

if __name__=='__main__':unittest.main()
