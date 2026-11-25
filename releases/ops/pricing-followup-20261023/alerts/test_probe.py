import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

spec=importlib.util.spec_from_file_location('pricing_probe',Path(__file__).parent/'source/pricing_probe.py')
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)

def row(jid='J20261023140000',status='done',**result):
    if result.get('write_state') == 'confirmed':
        result.setdefault('operation_id',jid)
        result.setdefault('original_job_id',jid)
    return dict(id=jid,status=status,result_json=json.dumps(result))

class Receipts(unittest.TestCase):
    def test_unknown_survives_collection_and_disappearance(self):
        prior,_=P.classify_jobs([row(write_state='unknown')],[],{})
        self.assertEqual(P.classify_jobs([],[],prior)[0],prior)
        self.assertEqual(P.classify_jobs([row(jid='J20261023140100',write_state='confirmed')],[],prior)[0],prior)
    def test_same_id_confirmed_resolves(self):
        self.assertEqual(P.classify_jobs([row(write_state='confirmed')],[],{'J20261023140000':'unknown'})[0],{})
    def test_cache_failure_survives_confirmed_without_cache_proof(self):
        result,_=P.classify_jobs([row(write_state='confirmed',clearcache_wanted=True,clearcache_ok=False)],[],{})
        self.assertEqual(result['J20261023140000'],'cache_failed')
        result,_=P.classify_jobs([row(write_state='confirmed',clearcache_wanted=True,clearcache_ok=None)],[],result)
        self.assertEqual(result['J20261023140000'],'cache_unconfirmed')
        self.assertEqual(P.classify_jobs([row(write_state='confirmed',clearcache_wanted=True,clearcache_ok=True)],[],result)[0],{})
    def test_legacy_baseline_not_faked_zero_or_new_incident(self):
        self.assertEqual(P.classify_jobs([row(status='failed')],['J20261023140000'],{}),({},['J20261023140000']))
        self.assertEqual(P.classify_jobs([row(status='failed')],[],{})[0]['J20261023140000'],'execution_unclassified')
    def test_explicit_unknown_not_hidden_by_legacy_baseline(self):
        self.assertEqual(P.classify_jobs([row(status='failed',write_state='partial')],['J20261023140000'],{})[0]['J20261023140000'],'partial')
    def test_prewrite_receipt_detail_does_not_change_original_alert_code(self):
        jid='J20261023140000'
        job=row(status='failed',write_state='prewrite_failed',write_attempts=0,original_job_id=jid)
        memory=dict(running=True,usage_bytes=0,restart_count=0,started_at='old',oom_killed=False)
        snapshot=P.collect(datetime.now(timezone.utc),{},[],{},[job],memory)
        self.assertIn('rpg_pricing_write_failed:'+jid,snapshot['issues'])
        self.assertEqual(snapshot['rpg_receipt_details'][jid],
                         dict(write_state='prewrite_failed',write_attempts=0,status='failed'))
    def test_old_done_cache_missing_is_legacy_not_new_fault(self):
        jid='J20261023140000'
        self.assertEqual(P.classify_jobs([row(clearcache_wanted=True,clearcache_ok=False)], [jid], {jid:'cache_failed'}), ({},[jid]))
        self.assertEqual(P.classify_jobs([row(clearcache_wanted=True,clearcache_ok=False)], [jid], {jid:'unknown'})[0], {jid:'unknown'})
    def test_row_mismatch_even_if_done(self):
        self.assertEqual(P.classify_jobs([row(write_state='confirmed',mismatch=['id'])],[],{})[0]['J20261023140000'],'row_verification_failed')
    def test_wrong_identity_cannot_clear_unknown(self):
        value,_=P.classify_jobs([row(write_state='confirmed',operation_id='different')],[],{'J20261023140000':'unknown'})
        self.assertEqual(value['J20261023140000'],'receipt_identity_mismatch')
    def test_cache_receipt_only_original_cache_issue(self):
        jid='J20261023140000'
        receipt=dict(status='verified',price_requests=0,original_clearcache_ok=False,original_backend_writes=42,
                     original_job_id=jid,response=dict(http=200,code=1,confirmed=True))
        self.assertEqual(P.reconcile_cache({jid:'cache_failed'},receipt),{})
        for state in ('unknown','partial'):
            self.assertEqual(P.reconcile_cache({jid:state},receipt),{jid:state})
        receipt['original_job_id']='J20261023140100'
        self.assertEqual(P.reconcile_cache({jid:'cache_failed'},receipt),{jid:'cache_failed'})
    def test_invalid_id_or_result_rejected(self):
        for value in [dict(id='../x',status='done',result_json='{}'),dict(id='J20261023140000',status='done',result_json='[]')]:
            with self.assertRaises(ValueError):P.classify_jobs([value],[],{})
    def test_restart_is_stable_event_then_recovery(self):
        now=datetime.now(timezone.utc)
        mem=dict(running=True,usage_bytes=500000000,restart_count=2,started_at=now.isoformat(),oom_killed=False)
        old=dict(memory=dict(mem,restart_count=1,started_at='old'))
        first=P.collect(now,old,[],{},[],mem)
        self.assertIn('fc_pricing_browser_restarted:'+mem['started_at'],first['issues'])
        later=P.collect(now+timedelta(seconds=60),first,[],{},[],mem)
        self.assertEqual(later['issues'],first['issues'])
        self.assertEqual(P.collect(now+timedelta(seconds=601),later,[],{},[],mem)['issues'],[])
    def test_memory_threshold_and_unknown_ids(self):
        mem=dict(running=True,usage_bytes=1536*1024*1024,restart_count=0,started_at='old',oom_killed=False)
        jid='9c4fd616-9a97-45d6-990f-e8e8af598d4f'
        raw=dict(issues=[dict(level='warning',code='noncore_source_unavailable:IGGM')],unknown_operations=[dict(operation_id=jid)])
        value=P.collect(datetime.now(timezone.utc),{},[],raw,[],mem)
        self.assertEqual(value['issues'],['fc_pricing_browser_memory_high','fc_pricing_unresolved:'+jid])
    def test_planned_verified_restart_is_sample_not_failure(self):
        now=datetime.now(timezone.utc)
        mem=dict(id='a'*64,running=True,usage_bytes=500000000,restart_count=0,started_at=now.isoformat(),oom_killed=False)
        old=dict(memory=dict(mem,started_at='old'))
        event_id='9c4fd616-9a97-45d6-990f-e8e8af598d4f'
        life=dict(event_id=event_id,action='restart',at=now.timestamp(),state='verified_after_unknown',
                  idle_release=dict(event_id=event_id,container_id=mem['id'],started_at=mem['started_at']),
                  idle_release_verified_at=now.isoformat())
        value=P.collect(now,old,[],{},[],mem,lifecycle=life)
        self.assertEqual(value['issues'],[])
        self.assertTrue(value['browser_restart_event']['planned_startup_acceptance_verified'])
        life.update(state='unknown',event_id='original-recovery')
        self.assertIn('fc_pricing_browser_recovery_unknown:original-recovery',P.collect(now,value,[],{},[],mem,lifecycle=life)['issues'])
    def test_old_report_codes_retained_for_cross_mode_dedup(self):
        now=datetime.now(timezone.utc)
        mem=dict(running=True,usage_bytes=500000000,restart_count=0,started_at='old',oom_killed=False)
        raw=dict(issues=[dict(level='critical',code='latest_coin_job_failed'),dict(level='warning',code='historical_prewrite_failure')])
        value=P.collect(now,{},[],raw,[],mem,extra_issues=['coin_schedule_failed'])
        self.assertEqual(value['legacy_issue_codes'],['coin_schedule_failed','latest_coin_job_failed'])
        self.assertEqual(value['issues'],['fc_pricing_coin_schedule_failed','fc_pricing_latest_coin_job_failed'])
        recovered=P.collect(now,value,[],{},[],mem)
        self.assertEqual(recovered['issues'],[])
        self.assertEqual(recovered['legacy_issue_codes'],value['legacy_issue_codes'])
    def test_actual_connection_failure_not_hidden_by_http_healthy(self):
        now=datetime.now(timezone.utc)
        mem=dict(running=True,usage_bytes=500000000,restart_count=0,started_at='old',oom_killed=False)
        value=P.collect(now,{},[],dict(status='healthy'),[],mem,lifecycle=dict(transport_failed_at=now.timestamp()))
        self.assertEqual(value['issues'],['fc_pricing_actual_browser_connection_failed'])
    def test_main_does_not_probe_retired_order_browser(self):
        source=(Path(__file__).parent/'source/pricing_probe.py').read_text(encoding='utf-8')
        ast.parse(source,feature_version=(3,9))
        self.assertFalse(hasattr(P,'add_order_memory'))
        self.assertNotIn('fs-order-browser',source)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            state=root/'state';profile=root/'profile'
            state.mkdir();profile.mkdir()
            (state/'legacy-baseline.json').write_text(json.dumps({'job_ids':[]}),encoding='utf-8')
            written={}
            collector=types.ModuleType('collector')
            collector.probe=lambda:dict(status='healthy',issues=[])
            def atomic(path,value):
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(value),encoding='utf-8')
                written[str(path)]=value
            collector.atomic=atomic
            common=types.ModuleType('common')
            common.assess=lambda raw,now:[]
            fcntl=types.ModuleType('fcntl')
            fcntl.LOCK_EX,fcntl.LOCK_NB=2,4
            fcntl.flock=lambda *args:None
            inspected=[]
            def fake_memory(container='fc27-cloud-browser'):
                inspected.append(container)
                return dict(id='a'*64,running=True,usage_bytes=500000000,rss_bytes=200000000,
                            cache_bytes=100000000,limit=2*1024*1024*1024,restart_count=0,
                            started_at='2026-11-25T00:00:00+00:00',oom_killed=False)
            done=types.SimpleNamespace(returncode=0,stdout='{"state":"unchanged_quiet"}',stderr='')
            with patch.dict(sys.modules,{'collector':collector,'common':common,'fcntl':fcntl}), \
                 patch.object(P,'STATE',state),patch.object(P,'PROFILE',profile), \
                 patch.object(P,'rpg_rows',return_value=[]), \
                 patch.object(P,'browser_memory',side_effect=fake_memory), \
                 patch.object(P,'owner_price_review',return_value=([],{})), \
                 patch.object(P.subprocess,'run',return_value=done):
                P.main()
            self.assertEqual(inspected,['fc27-cloud-browser'])
            snapshot=written[str(profile/'pricing-snapshot.json')]
            self.assertEqual(snapshot['issues'],[])
            self.assertNotIn('order_memory',snapshot)

if __name__=='__main__':unittest.main()
