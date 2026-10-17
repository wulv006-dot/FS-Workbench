"""Synthetic emergency monitor checks; no production writes or outbound requests."""
import ast
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TASK = Path(__file__).resolve().parents[1]
WORKSPACE = TASK.parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(TASK/'source'/'monitor'), str(TASK/'source'),
               str(TASK/'tests'/'monitor_dependencies'), '/opt/fc-ops-readonly-monitor', '/opt/fc27-cloud-browser']
import collector
import hooks
import hooks_notifier
import read_only_status

PLATFORMS = ('PS','XBOX','PC')
SITES = ('Lootbar','IGGM','U4GM','U7Buy')

def snapshot(missing=()):
    keys = [[s,p] for s in SITES if s not in missing for p in PLATFORMS]
    return {
        'captured_at':'2026-10-09T02:00:00+00:00',
        'gateway':{'certificate_valid':True,'http_status':'401'},
        'health':{**{k:'ok' for k in ('api','worker','browser','p2pah_session')},
                  'automation_timer':'active','https_certificate':{'status':'ok'},
                  'incomplete_executions':0,'sources':{**{s.lower():'missing' if s in missing else 'ok' for s in SITES},
                                                      'p2pah_cost':'ok','fx':'ok'}},
        'automation':{'interval_minutes':120,'system_enabled':True,'mode':'auto','revision':29},
        'monitor':{'latest_collection':{'run_id':'run-new','created_at':'2026-10-09T01:55:00+00:00',
                                       'competitor_count':len(keys),'competitor_keys':keys,
                                       'cost_count':3,'cost_platforms':list(PLATFORMS),'storefront_run_id':'run-new'},
                   'latest_attempt':{'status':'ready_for_quote','run_id':'run-new'}},
        'publication':{'status':'matched','platforms':[{'platform':p,'status':'matched'} for p in PLATFORMS]},
        'player_sync':{'enabled':True},'gallery':{'settings':{'enabled':False}}
    }

def codes(value):
    return {i['code'] for i in read_only_status.assess(value)['issues']}

def observation(missing=(), extra=(), status='warning', second=0):
    return {'status':status,'captured_at':'2026-10-09T02:00:00+00:00',
            'finished_at':f'2026-10-09T02:00:{second:02d}+00:00',
            'issues':[{'level':'warning','code':'gallery_automation_disabled'}] +
                     [{'level':'warning','code':'noncore_source_unavailable:'+s} for s in missing] +
                     [{'level':'critical','code':s} for s in extra],
            'coin':{'collection':{'reference_sources':{p:['U4GM'] for p in PLATFORMS}}}}

class SourceCoverageTests(unittest.TestCase):
    def test_each_noncore_site_and_u7_sole(self):
        for missing in ((),('IGGM',),('U4GM',),('U7Buy',),('IGGM','U4GM')):
            with self.subTest(missing=missing):
                result = codes(snapshot(missing))
                self.assertNotIn('source_coverage_unverified',result)
                self.assertEqual(result, {'gallery_automation_disabled'} |
                                 {'noncore_source_unavailable:'+s for s in missing})

    def test_core_or_all_references_mandatory(self):
        for missing in (('Lootbar',),('IGGM','U4GM','U7Buy')):
            self.assertIn('source_coverage_unverified',codes(snapshot(missing)))

    def test_cost_fx_and_core_health_still_mandatory(self):
        for key in ('lootbar','p2pah_cost','fx'):
            value=snapshot(('IGGM',));value['health']['sources'][key]='missing'
            self.assertIn('source_coverage_unverified',codes(value))
        value=snapshot();value['monitor']['latest_collection']['cost_platforms']=['PS','XBOX','XBOX']
        self.assertIn('source_coverage_unverified',codes(value))

    def test_duplicates_malformed_unknown_and_count_mismatch(self):
        for row in (['Lootbar','PS'],['IGGM'],['Other','PC'],['IGGM',{}]):
            value=snapshot();value['monitor']['latest_collection']['competitor_keys'].append(row)
            value['monitor']['latest_collection']['competitor_count'] += 1
            self.assertIn('source_coverage_unverified',codes(value))
        value=snapshot();value['monitor']['latest_collection']['competitor_count']=9
        self.assertIn('source_coverage_unverified',codes(value))
        value=snapshot();value['monitor']['latest_collection']['competitor_records_invalid']=True
        self.assertIn('source_coverage_unverified',codes(value))

    def test_age_run_id_storefront_unknown_and_publication_retained(self):
        value=snapshot(('IGGM',));value['monitor']['latest_collection']['created_at']='2026-10-08T00:00:00+00:00'
        self.assertIn('collection_stale_or_clock_invalid',codes(value))
        value=snapshot(('IGGM',));value['monitor']['latest_collection']['storefront_run_id']='old-run'
        self.assertIn('latest_attempt_or_monitor_run_unverified',codes(value))
        value=snapshot(('IGGM',));value['health']['incomplete_executions']=1
        self.assertIn('coin_execution_needs_reconcile',codes(value))
        value=snapshot(('IGGM',));value['publication']['platforms'][1]['status']='unconfirmed'
        self.assertIn('three_platform_publication_unverified',codes(value))

    def test_degraded_warning_does_not_contain_writer_but_core_loss_does(self):
        for missing, contained in [(('IGGM',),False),(('IGGM','U4GM'),False),(('Lootbar',),True)]:
            value=snapshot(missing)
            report={'issues':read_only_status.assess(value)['issues'],
                    'coin':{'config':value['automation'],'job':{}},'publication':value['publication']}
            result=hooks.controls(report)
            for state in result['platforms'].values():
                self.assertEqual('source_coverage_unverified' in state['reasons'],contained)

    def test_collect_metadata_rejects_present_bad_and_duplicate_records(self):
        for mutation in ('none','invalid_status','incomparable','duplicate','unknown','u7_incomparable',
                         'default_lootbar','conditional_lootbar','invalid_comparable'):
            value=snapshot(('IGGM','U4GM') if mutation=='u7_incomparable' else ('IGGM',))
            summary=value['monitor']['latest_collection']
            collection={'run_id':'run-new','created_at':summary['created_at'],
                        'competitors':[{'source':s,'platform':p,'status':'valid','comparable':True}
                                       for s,p in summary['competitor_keys']],
                        'costs':[{'platform':p} for p in PLATFORMS]}
            if mutation=='invalid_status':collection['competitors'][0]['status']='invalid'
            if mutation=='incomparable':collection['competitors'][0]['comparable']=False
            if mutation=='duplicate':collection['competitors'].append(copy.deepcopy(collection['competitors'][0]))
            if mutation=='unknown':collection['competitors'][0]['source']='unknown'
            if mutation=='u7_incomparable':collection['competitors'][-1]['comparable']=False
            if mutation=='default_lootbar':collection['competitors'][0].update(comparable=None,conditional=None)
            if mutation=='conditional_lootbar':collection['competitors'][0].update(comparable=None,conditional=True)
            if mutation=='invalid_comparable':collection['competitors'][0]['comparable']='true'
            monitor={'health':value['health'],'automation':value['automation'],'player_sync':value['player_sync'],
                     'latest_collection':collection,'latest_attempt':value['monitor']['latest_attempt'],
                     'page_readback':{},'cache_refresh':{},'storefront':{'collection_run_id':'run-new'},
                     'publication':value['publication']}
            with tempfile.TemporaryDirectory() as name, patch.dict(sys.modules,{'fc27_cloud_api':SimpleNamespace(monitor_view=lambda:monitor)}), \
                    patch.object(read_only_status,'APP',Path(name)), patch.object(read_only_status,'ROOT',Path(name)), \
                    patch.object(read_only_status,'Path',side_effect=lambda path:Path(name)/str(path).lstrip('/')), \
                    patch.object(read_only_status,'read',lambda path,default=None:default), \
                    patch.object(read_only_status,'summary_jobs',lambda *args:[]), \
                    patch.object(read_only_status.subprocess,'run',return_value=SimpleNamespace(stdout='401 0',returncode=0)):
                result=read_only_status.collect()['monitor']['latest_collection']
            self.assertEqual(result['competitor_records_invalid'],mutation not in ('none','default_lootbar'))
            if mutation=='none':
                self.assertEqual(result['unavailable_sources'],['IGGM'])
                self.assertEqual(result['reference_sources'],{p:['U4GM'] for p in PLATFORMS})

class TransitionTests(unittest.TestCase):
    def events(self, root):
        return sorted([json.loads(p.read_text(encoding='utf-8')) for p in (root/'outbox').glob('*.json')],
                      key=lambda event:event['created_at'])

    def test_same_event_dedup_partial_and_full_source_recovery_with_gallery_warning(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            for second,missing in enumerate([('IGGM','U4GM'),('IGGM','U4GM'),('IGGM',),(),()]):
                collector.persist(root,observation(missing,second=second))
            events=self.events(root)
            self.assertEqual([e['kind'] for e in events],['incident','recovery','recovery'])
            self.assertEqual([e['recovered_sources'] for e in events],[[],['U4GM'],['IGGM']])
            self.assertTrue(all(e['status']=='warning' and e['delivery_state']=='pending' for e in events))
            self.assertIn('IGGM 已在新一轮采集恢复有效数据',hooks_notifier.format_message(events[-1]))
            self.assertIn('不代表自动改价或售卖保护已恢复',hooks_notifier.format_message(events[-1]))

    def test_changed_site_alerts_but_new_critical_not_called_source_recovery(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            collector.persist(root,observation(('IGGM',),second=0))
            collector.persist(root,observation(('U4GM',),second=1))
            collector.persist(root,observation((),('api_unhealthy_or_unknown',),'critical',2))
            events=self.events(root)
            self.assertEqual(len(events),3)
            self.assertEqual([e['kind'] for e in events],['incident']*3)
            self.assertEqual(events[-1]['recovered_sources'],[])

    def test_crash_before_latest_keeps_one_outbox_event(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);collector.persist(root,observation(second=0));original=collector.atomic
            def crash(path,data):
                if path.name=='latest.json':raise OSError('synthetic_crash')
                original(path,data)
            with patch.object(collector,'atomic',crash):
                with self.assertRaises(OSError):collector.persist(root,observation(('IGGM',),second=1))
            collector.persist(root,observation(('IGGM',),second=2))
            self.assertEqual(len(self.events(root)),2)

    def test_notifier_primary_fallback_and_rpg_preserved(self):
        event={'kind':'incident','status':'warning','created_at':'2026-10-09T02:00:00+00:00',
               'event_id':'a'*64,'issues':[{'level':'warning','code':'noncore_source_unavailable:IGGM'},
                                        {'level':'critical','code':'rpg_task_failed:d4:collect:0123456789ab'}],
               'reference_sources':{p:['U7Buy'] for p in PLATFORMS}}
        text=hooks_notifier.format_message(event)
        for expected in ('IGGM 本轮采集异常','PC 当前参考：U7Buy','核心 Lootbar 保留','D4的采集与改价任务失败','RPG 处理建议'):
            self.assertIn(expected,text)
        self.assertNotIn('未识别的巡检异常',text)

    def test_python39_syntax(self):
        for path in (TASK/'source'/'monitor').glob('*.py'):
            ast.parse(path.read_text(encoding='utf-8'),feature_version=(3,9))

class PrewriteRecoveryTests(unittest.TestCase):
    def report(self):
        value=observation(('IGGM',),('latest_coin_job_failed',),'critical')
        collection=snapshot(('IGGM',))['monitor']['latest_collection']
        job_id='11111111-1111-4111-8111-111111111111'
        collection['prewrite_failure_recovery']={
            'verified_prewrite':True,'failed_job_id':job_id,'failed_completed_at':'2026-10-09T01:50:00+00:00',
            'policy_revision':29,'new_collection_run_id':'run-new','new_collection_created_at':collection['created_at']}
        value['coin']={'config':snapshot()['automation'],'collection':collection,
                       'latest_attempt':{'run_id':'run-new','status':'ready_for_quote'},
                       'job':{'job_id':job_id,'status':'failed','completed_at':'2026-10-09T01:50:00+00:00'}}
        value['publication']=snapshot()['publication']
        value['unknown_operations']=[]
        return value

    def test_historical_prewrite_deadlock_two_clean_then_real_new_cycle(self):
        value=self.report();paused=hooks.controls(value)
        self.assertTrue(paused['platforms']['PS']['reasons'])
        collector.apply_prewrite_recovery(value)
        self.assertEqual(value['coin']['job']['status'],'failed')
        self.assertEqual({i['code'] for i in value['issues']},
                         {'gallery_automation_disabled','noncore_source_unavailable:IGGM','historical_prewrite_failure'})
        first=hooks.controls(value,paused)
        self.assertEqual(first['platforms']['PS']['reasons'],['recovery_confirmation_pending'])
        second=hooks.controls(value,first)
        self.assertEqual(second['platforms']['PS']['phase'],'AWAITING_CYCLE')
        same=hooks.controls(value,second)
        self.assertEqual(same['platforms']['PS']['phase'],'AWAITING_CYCLE')
        value['coin']['job']={'job_id':'22222222-2222-4222-8222-222222222222','status':'completed','result':'confirmed'}
        recovered=hooks.controls(value,same)
        self.assertEqual(recovered['platforms']['PS']['phase'],'RECOVERED')

    def test_unknown_revision_age_identity_and_other_critical_never_downgrade(self):
        for mutation in ('unverified','unknown','revision','job','run','older','stale','core','different_completion'):
            value=self.report();proof=value['coin']['collection']['prewrite_failure_recovery']
            if mutation=='unverified':proof['verified_prewrite']=False
            if mutation=='unknown':value['unknown_operations']=[{'operation_id':'unknown'}]
            if mutation=='revision':proof['policy_revision']=28
            if mutation=='job':proof['failed_job_id']='other'
            if mutation=='run':proof['new_collection_run_id']='other'
            if mutation=='older':
                proof['new_collection_created_at']='2026-10-09T01:40:00+00:00'
                value['coin']['collection']['created_at']=proof['new_collection_created_at']
            if mutation=='stale':value['captured_at']='2026-10-10T02:00:00+00:00'
            if mutation=='core':value['issues'].append({'level':'critical','code':'source_coverage_unverified'})
            if mutation=='different_completion':proof['failed_completed_at']='2026-10-09T01:49:00+00:00'
            collector.apply_prewrite_recovery(value)
            self.assertEqual(value['status'],'critical',mutation)
            self.assertIn('latest_coin_job_failed',{i['code'] for i in value['issues']},mutation)

    def test_bounded_probe_preserves_proof_recovery_without_retries(self):
        calls=[]
        result=collector.collect_bounded(self.report,calls.append)
        self.assertEqual(result['status'],'warning')
        self.assertEqual(len(result['observations']),1)
        self.assertEqual(calls,[])

    def same_job_report(self):
        value=self.report();coin=value['coin'];collection=coin['collection'];job=coin['job']
        job.update(created_at='2026-10-09T01:53:00+00:00',completed_at='2026-10-09T01:58:00+00:00')
        collection.update(run_id=job['job_id'],storefront_run_id=job['job_id'],quote_created_at='2026-10-09T01:57:00+00:00')
        coin['latest_attempt']['run_id']=job['job_id']
        collection['prewrite_failure_recovery'].update(new_collection_run_id=job['job_id'],
            failed_completed_at=job['completed_at'],same_failed_job_collection=True)
        return value

    def test_same_no_write_job_collection_needs_two_observations_and_preserves_failed_record(self):
        value=self.same_job_report();job=copy.deepcopy(value['coin']['job']);paused=hooks.controls(value)
        collector.apply_prewrite_recovery(value)
        self.assertNotIn('latest_coin_job_failed',{i['code'] for i in value['issues']})
        first=hooks.controls(value,paused)
        self.assertEqual(first['platforms']['PC']['reasons'],['recovery_confirmation_pending'])
        second=hooks.controls(value,first)
        self.assertEqual(second['platforms']['PC']['phase'],'AWAITING_CYCLE')
        self.assertEqual(value['coin']['job'],job)

    def test_same_job_proof_rejects_bad_timeline_identity_staleness_unknown_and_other_faults(self):
        for mutation in ('flag','identity','no_created','naive','before_job','quote_before','quote_after',
                         'no_quote','stale','unknown','revision','attempt','core','off'):
            value=self.same_job_report();coin=value['coin'];collection=coin['collection'];proof=collection['prewrite_failure_recovery']
            if mutation=='flag':proof.pop('same_failed_job_collection')
            if mutation=='identity':coin['job']['job_id']='other';proof['failed_job_id']='other'
            if mutation=='no_created':coin['job'].pop('created_at')
            if mutation=='naive':coin['job']['created_at']='2026-10-09T01:53:00'
            if mutation=='before_job':coin['job']['created_at']='2026-10-09T01:56:00+00:00'
            if mutation=='quote_before':collection['quote_created_at']='2026-10-09T01:54:00+00:00'
            if mutation=='quote_after':collection['quote_created_at']='2026-10-09T01:59:00+00:00'
            if mutation=='no_quote':collection.pop('quote_created_at')
            if mutation=='stale':value['captured_at']='2026-10-10T02:00:00+00:00'
            if mutation=='unknown':value['unknown_operations']=[{'operation_id':'unknown'}]
            if mutation=='revision':proof['policy_revision']=28
            if mutation=='attempt':coin['latest_attempt']['status']='incomplete'
            if mutation=='core':value['issues'].append({'level':'critical','code':'source_coverage_unverified'})
            if mutation=='off':coin['config']['system_enabled']=False
            collector.apply_prewrite_recovery(value)
            self.assertIn('latest_coin_job_failed',{i['code'] for i in value['issues']},mutation)

    def test_readonly_producer_only_proves_same_complete_job_after_exact_no_dispatch_check(self):
        at=datetime.now(timezone.utc);jid='11111111-1111-4111-8111-111111111111'
        for mutation in ('none','helper_false','quote_after','before_job','different_run','storefront','core'):
            value=snapshot();job={'job_id':jid,'status':'failed','created_at':(at-timedelta(minutes=5)).isoformat(),
                                 'completed_at':(at-timedelta(minutes=2)).isoformat()}
            collection={'run_id':jid,'created_at':(at-timedelta(minutes=4)).isoformat(),
                        'quote_created_at':(at-timedelta(minutes=3)).isoformat(),
                        'competitors':[{'source':s,'platform':p,'status':'valid','comparable':True}
                                       for s,p in value['monitor']['latest_collection']['competitor_keys']],
                        'costs':[{'platform':p} for p in PLATFORMS]}
            if mutation=='quote_after':collection['quote_created_at']=at.isoformat()
            if mutation=='before_job':job['created_at']=(at-timedelta(minutes=3)).isoformat()
            if mutation=='different_run':collection['run_id']='other'
            if mutation=='core':value['health']['sources']['lootbar']='missing'
            monitor={'health':value['health'],'automation':value['automation'],'player_sync':value['player_sync'],
                     'latest_collection':collection,'latest_attempt':{'run_id':collection['run_id'],'status':'ready_for_quote'},
                     'page_readback':{},'cache_refresh':{},'storefront':{'collection_run_id':jid},'publication':value['publication']}
            if mutation=='storefront':monitor['storefront']['collection_run_id']='other'
            def read(path,default=None):return job if path.name==jid+'.json' else {}
            fake_api=SimpleNamespace(monitor_view=lambda:monitor)
            fake_tick=SimpleNamespace(proven_prewrite_rejection=lambda j,r:mutation!='helper_false')
            with patch.dict(sys.modules,{'fc27_cloud_api':fake_api,'automation_tick':fake_tick}), \
                 patch.object(read_only_status,'read',side_effect=read), \
                 patch.object(read_only_status,'summary_jobs',return_value=[job]), \
                 patch.object(read_only_status.subprocess,'run',return_value=SimpleNamespace(stdout='401 0',returncode=0)):
                result=read_only_status.collect()['monitor']['latest_collection'].get('prewrite_failure_recovery')
            self.assertEqual(bool(result),mutation=='none',mutation)
            if result:self.assertTrue(result['same_failed_job_collection'])

    def test_independent_rpg_business_gallery_critical_stays_visible_without_containing_fc(self):
        for code in ('rpg_state_unavailable','business_snapshot_unverified','gallery_task_unconfirmed'):
            value=self.report();value['issues'].append({'level':'critical','code':code})
            collector.apply_prewrite_recovery(value)
            self.assertEqual(value['status'],'critical')
            self.assertIn({'level':'critical','code':code},value['issues'])
            self.assertNotIn('latest_coin_job_failed',{i['code'] for i in value['issues']})
            self.assertTrue(all(not row['reasons'] for row in hooks.controls(value)['platforms'].values()))

    def test_other_fc_critical_or_user_disabled_never_downgrade(self):
        for code in ('worker_unhealthy_or_unknown','source_coverage_unverified','coin_execution_needs_reconcile'):
            value=self.report();value['issues'].append({'level':'critical','code':code})
            if code=='coin_execution_needs_reconcile':value['unknown_operations']=[{'operation_id':'unknown','platforms':['PS']}]
            collector.apply_prewrite_recovery(value)
            self.assertIn('latest_coin_job_failed',{i['code'] for i in value['issues']})
        value=self.report();value['coin']['config']['system_enabled']=False
        collector.apply_prewrite_recovery(value)
        self.assertIn('latest_coin_job_failed',{i['code'] for i in value['issues']})

    def test_collect_only_proves_new_usable_current_run_with_helper(self):
        for mutation in ('none','helper_false','older','core','run','revision_helper_false'):
            at=datetime.now(timezone.utc)
            value=snapshot(('IGGM',))
            job_id='11111111-1111-4111-8111-111111111111'
            collection={'run_id':'run-new','created_at':(at-timedelta(minutes=5)).isoformat(),
                        'competitors':[{'source':s,'platform':p,'status':'valid','comparable':True}
                                       for s,p in value['monitor']['latest_collection']['competitor_keys']],
                        'costs':[{'platform':p} for p in PLATFORMS]}
            job={'job_id':job_id,'completed_at':(at-timedelta(minutes=10)).isoformat(),'status':'failed'}
            if mutation=='older':collection['created_at']=(at-timedelta(minutes=11)).isoformat()
            if mutation=='core':value['health']['sources']['lootbar']='missing'
            if mutation=='run':value['monitor']['latest_attempt']['run_id']='old'
            monitor={'health':value['health'],'automation':value['automation'],'player_sync':value['player_sync'],
                     'latest_collection':collection,'latest_attempt':value['monitor']['latest_attempt'],
                     'page_readback':{},'cache_refresh':{},'storefront':{'collection_run_id':'run-new'},
                     'publication':value['publication']}
            def read(path,default=None):
                if path.name==job_id+'.json':return job
                if path.name=='settings.json':return {'settings':{'enabled':False}}
                return default
            helper_calls=[]
            def proof(actual,revision):
                helper_calls.append((actual,revision));return mutation not in ('helper_false','revision_helper_false')
            with tempfile.TemporaryDirectory() as name, patch.dict(sys.modules,{
                    'fc27_cloud_api':SimpleNamespace(monitor_view=lambda:monitor),
                    'automation_tick':SimpleNamespace(proven_prewrite_rejection=proof)}), \
                    patch.object(read_only_status,'APP',Path(name)),patch.object(read_only_status,'ROOT',Path(name)), \
                    patch.object(read_only_status,'Path',side_effect=lambda path:Path(name)/str(path).lstrip('/')), \
                    patch.object(read_only_status,'read',read), \
                    patch.object(read_only_status,'summary_jobs',lambda *args:[{'job_id':job_id}]), \
                    patch.object(read_only_status.subprocess,'run',return_value=SimpleNamespace(stdout='401 0',returncode=0)):
                result=read_only_status.collect()['monitor']['latest_collection']
            self.assertEqual('prewrite_failure_recovery' in result,mutation=='none',mutation)
            if mutation=='none':self.assertEqual(helper_calls,[(job,29)])

class CycleRecoveryTests(unittest.TestCase):
    def transition(self, result='confirmed'):
        value=PrewriteRecoveryTests().report()
        previous=hooks.controls(value)
        collector.apply_prewrite_recovery(value)
        previous=hooks.controls(value,hooks.controls(value,previous))
        value['coin']['job']={'job_id':'22222222-2222-4222-8222-222222222222','status':'ready','result':result}
        value['issues']=[i for i in value['issues'] if i['code']!='historical_prewrite_failure']
        value['finished_at']='2026-10-09T02:00:01+00:00'
        return value,previous,hooks.controls(value,previous)

    def test_one_cycle_recovery_then_same_job_no_event_or_fingerprint_pollution(self):
        value,previous,current=self.transition()
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            collector.persist(root,value)
            fingerprint=collector.signature(value)
            event_id=collector.persist_cycle_recovery(root,value,previous,current)
            self.assertIsNotNone(event_id)
            self.assertEqual(collector.signature(value),fingerprint)
            self.assertEqual(collector.persist_cycle_recovery(root,value,previous,current),event_id)
            self.assertIsNone(collector.persist_cycle_recovery(root,value,current,hooks.controls(value,current)))
            value['finished_at']='2026-10-09T02:00:02+00:00'
            collector.persist(root,value)
            events=[json.loads(p.read_text(encoding='utf-8')) for p in (root/'outbox').glob('*.json')]
            self.assertEqual(len(events),2)
            event=next(e for e in events if e.get('cycle_recovery'))
            self.assertEqual(event['cycle_recovery']['platforms'],['PC','PS','XBOX'])
            self.assertEqual(event['status'],'warning')
            self.assertIn({'level':'warning','code':'noncore_source_unavailable:IGGM'},event['issues'])
            text=hooks_notifier.format_message(event)
            self.assertIn('恢复后的新自然周期',text)
            self.assertIn('不代表所有来源或其他模块已恢复',text)
            self.assertIn('IGGM 本轮采集异常',text)
            self.assertNotIn('本次巡检恢复正常',text)

    def test_nochange_and_partial_platforms_are_explicit(self):
        value,previous,current=self.transition('no_price_change')
        current['platforms']['PC']['phase']='AWAITING_CYCLE'
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);event_id=collector.persist_cycle_recovery(root,value,previous,current)
            event=json.loads((root/'outbox'/(event_id+'.json')).read_text(encoding='utf-8'))
            self.assertEqual(event['cycle_recovery']['platforms'],['PS','XBOX'])
            self.assertIn('PS、XBOX 已完成恢复后的新自然周期，本轮无需改价',hooks_notifier.format_message(event))

    def test_unknown_unconfirmed_same_original_job_or_not_ready_never_alert(self):
        for mutation in ('unknown','missing_unknown','result','same','running','revision','user_disabled'):
            value,previous,current=self.transition()
            if mutation=='unknown':value['unknown_operations']=[{'operation_id':'unknown','platforms':['PS']}]
            if mutation=='missing_unknown':value.pop('unknown_operations')
            if mutation=='result':value['coin']['job']['result']='unknown'
            if mutation=='same':
                for row in previous['platforms'].values():row['resume_after_job_id']=value['coin']['job']['job_id']
            if mutation=='running':value['coin']['job']['status']='running'
            if mutation=='revision':current['policy_revision']=28
            if mutation=='user_disabled':value['coin']['config']['system_enabled']=False
            with tempfile.TemporaryDirectory() as name:
                root=Path(name)
                self.assertIsNone(collector.persist_cycle_recovery(root,value,previous,current),mutation)
                self.assertFalse((root/'outbox').exists())

if __name__=='__main__':
    unittest.main()
