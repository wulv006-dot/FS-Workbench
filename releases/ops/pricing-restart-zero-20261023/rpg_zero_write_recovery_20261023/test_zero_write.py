import copy
from contextlib import closing
from datetime import datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


P = module('zero_probe', ROOT/'source/pricing_probe.py')
G = module('zero_prepare', ROOT/'prepare_candidate.py')
JID = 'J20261023163848'


def receipt(jid=JID):
    result = dict(operation_id=jid, original_job_id=jid, write_state='confirmed', write_attempts=0,
                  ok=0, fail=0, mismatch=[], jobs=[dict(ids=['synthetic-id'])], clearcache_wanted=True,
                  clearcache_ok=None)
    return dict(id=jid, kind='write', status='done', result_json=json.dumps(result),
                execution_phase=dict(job_id=jid, finished=True, write_attempts=0))


class Classification(unittest.TestCase):
    def classify(self, row, retained=None):
        return P.classify_jobs([row], [], retained or {})[0]

    def change_result(self, row, **changes):
        result = json.loads(row['result_json']); result.update(changes)
        row['result_json'] = json.dumps(result)

    def test_both_original_ids_resolve_only_their_cache_issue(self):
        for jid in (JID, 'J20261023173949'):
            self.assertEqual(self.classify(receipt(jid), {jid:'cache_unconfirmed', 'other':'unknown'}), {'other':'unknown'})

    def test_new_explicit_noop_keeps_wanted_intent_and_is_not_cache_success(self):
        row = receipt(); self.change_result(row, noop=True, clearcache_required=False,
                                            clearcache_reason='not_required_no_price_change')
        self.assertEqual(self.classify(row), {})
        self.assertIs(json.loads(row['result_json'])['clearcache_wanted'], True)
        self.assertIsNone(json.loads(row['result_json'])['clearcache_ok'])

    def test_unknown_and_partial_are_never_exempted(self):
        for state in ('unknown', 'partial'):
            row = receipt(); self.change_result(row, write_state=state, noop=True, clearcache_required=False)
            self.assertEqual(self.classify(row)[JID], state)
            self.assertEqual(self.classify(receipt(), {JID:state})[JID], state)

    def test_missing_or_unfinished_or_wrong_identity_phase_not_exempted(self):
        for phase in (None, {}, dict(job_id=JID,finished=False,write_attempts=0),
                      dict(job_id='different',finished=True,write_attempts=0)):
            row = receipt(); row['execution_phase'] = phase
            self.assertEqual(self.classify(row)[JID], 'cache_unconfirmed')

    def test_counts_require_actual_integer_zero_and_same_id(self):
        for field in ('write_attempts', 'ok', 'fail'):
            for value in (False, None, '0', 0.0, 1):
                row = receipt(); self.change_result(row, **{field:value})
                self.assertFalse(P.confirmed_no_write(row, json.loads(row['result_json'])))
        for value in (False,None,'0',0.0,1):
            row=receipt(); row['execution_phase']['write_attempts']=value
            self.assertEqual(self.classify(row)[JID], 'cache_unconfirmed')
        for field in ('operation_id','original_job_id'):
            row=receipt(); self.change_result(row, **{field:'different'})
            self.assertEqual(self.classify(row)[JID], 'cache_unconfirmed')

    def test_empty_jobs_mismatch_and_contradictory_noop_not_exempted(self):
        for change in ({'jobs':[]},{'jobs':[{}]},{'mismatch':None},{'mismatch':['synthetic']},
                       {'noop':False},{'clearcache_required':True},{'clearcache_ok':False}):
            row=receipt(); self.change_result(row, **change)
            self.assertEqual(self.classify(row)[JID], 'cache_failed' if change.get('clearcache_ok') is False else 'cache_unconfirmed')

    def test_failed_or_non_item_job_not_exempted(self):
        for change in ({'status':'failed'},{'kind':'writegold'},{'kind':'collect'}):
            row=receipt(); row.update(change)
            self.assertEqual(self.classify(row)[JID], 'cache_unconfirmed')

    def test_actual_write_cache_failure_remains_an_incident(self):
        row=receipt(); row['execution_phase']['write_attempts']=1
        self.change_result(row, ok=1,write_attempts=1,clearcache_ok=False)
        self.assertEqual(self.classify(row)[JID], 'cache_failed')

    def test_readonly_db_attaches_original_phase_without_mutating_db(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); db=root/'jobs.db'; phases=root/'phases'; phases.mkdir()
            row=receipt()
            with closing(sqlite3.connect(db)) as conn:
                conn.execute('create table local_job(id text,kind text,status text,result_json text)')
                conn.execute('insert into local_job values(?,?,?,?)',tuple(row[k] for k in ('id','kind','status','result_json')))
                conn.commit()
            (phases/(JID+'.execution.json')).write_text(json.dumps(row['execution_phase']))
            before=hashlib.sha256(db.read_bytes()).hexdigest()
            result=P.rpg_rows(db,phases)
            self.assertEqual(result,[row]); self.assertEqual(self.classify(result[0]),{})
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(),before)
            (phases/(JID+'.execution.json')).unlink()
            self.assertIsNone(P.rpg_rows(db,phases)[0]['execution_phase'])

    def test_recovery_collect_preserves_unknown_and_all_other_issues(self):
        now=datetime.fromisoformat('2026-10-23T10:30:00+00:00')
        memory=dict(running=True,usage_bytes=100,restart_count=0,started_at='old',oom_killed=False)
        previous=dict(rpg_unresolved={JID:'cache_unconfirmed','other':'unknown'})
        result=P.collect(now,previous,[],{},[receipt()],memory)
        self.assertEqual(result['issues'],['rpg_pricing_unknown:other'])
        self.assertEqual(result['rpg_unresolved'],{'other':'unknown'})


class ItemProducer(unittest.TestCase):
    def execute(self, initial=3, after=3, write_ok=True, cache_ok=True, wanted=True):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); plan=root/'plan.json'
            plan.write_text(json.dumps(dict(items=[dict(key='synthetic',new=3)])))
            session=SimpleNamespace(logged_in=lambda:True,write_rows=Mock(return_value=dict(ok=write_ok,msg='synthetic')),
                                    clear_cache=Mock(return_value=(True,'synthetic')),close=Mock())
            main_cache=Mock(return_value=(cache_ok,'synthetic'))
            source=(ROOT/'tests/fixtures/item_write_baseline.py').read_text(encoding='utf-8')
            candidate=G.transform(source)
            handles=[]
            def tracked_open(*args, **kwargs):
                handle=io.open(*args, **kwargs); handles.append(handle); return handle
            scope=dict(json=json,io=SimpleNamespace(open=tracked_open),os=os,HERE=str(root),dt=SimpleNamespace(datetime=datetime),
                       load_cfg=lambda path:{},ids_of=lambda cfg,key:['1'],log=lambda *args:None,
                       Session=lambda *args:session,game_gid_of=lambda *args:'1',time=SimpleNamespace(sleep=lambda s:None),
                       fetch_all_needed=Mock(side_effect=[{'1':dict(unit_price=initial)},{'1':dict(unit_price=after)}]),
                       cache_wanted=lambda *args:(wanted,'synthetic'),clear_main_cache=main_cache)
            exec(compile(candidate,'safe-item-fixture','exec'),scope)
            args=SimpleNamespace(config='synthetic',plan=str(plan),confirm=True,profile='unused',show=False)
            try:
                with patch.dict(os.environ,{'FS_RPG_JOB_ID':JID}):code=scope['cmd_write'](args)
            finally:
                for handle in handles:handle.close()
            files=list(root.glob('p2pah_write_result_*.json')); self.assertEqual(len(files),1)
            result=json.loads(files[0].read_text(encoding='utf-8'))
            return code,result,session,main_cache

    def test_unchanged_targets_preserve_intent_without_writes_or_cache(self):
        code,result,session,cache=self.execute()
        self.assertEqual(code,0); self.assertTrue(result['noop']); self.assertFalse(result['clearcache_required'])
        self.assertEqual(result['clearcache_reason'],'not_required_no_price_change')
        self.assertTrue(result['clearcache_wanted']); self.assertIsNone(result['clearcache_ok'])
        session.write_rows.assert_not_called(); session.clear_cache.assert_not_called(); cache.assert_not_called()

    def test_changed_target_still_writes_and_clears_both_original_caches(self):
        code,result,session,cache=self.execute(initial=2)
        self.assertEqual(code,0); self.assertFalse(result['noop']); self.assertTrue(result['clearcache_required'])
        self.assertTrue(result['clearcache_ok']); session.write_rows.assert_called_once()
        cache.assert_called_once(); session.clear_cache.assert_called_once()

    def test_postread_mismatch_is_not_noop_or_cache_success(self):
        code,result,session,cache=self.execute(after=4)
        self.assertEqual(code,1); self.assertFalse(result['noop']); self.assertTrue(result['mismatch'])
        self.assertTrue(result['clearcache_required']); cache.assert_not_called()

    def test_failed_write_not_noop(self):
        code,result,session,cache=self.execute(initial=2,after=2,write_ok=False)
        self.assertEqual(code,1); self.assertFalse(result['noop']); self.assertEqual(result['fail'],1)
        cache.assert_not_called()

    def test_cache_failed_after_write_retains_real_write_and_failure(self):
        code,result,session,cache=self.execute(initial=2,cache_ok=False)
        self.assertEqual(code,0); self.assertEqual(result['ok'],1); self.assertFalse(result['clearcache_ok'])
        self.assertTrue(result['clearcache_required']); self.assertFalse(result['noop'])

    def test_explicit_no_cache_request_not_overridden(self):
        code,result,session,cache=self.execute(initial=2,wanted=False)
        self.assertEqual(code,0); self.assertFalse(result['clearcache_required']); self.assertFalse(result['clearcache_wanted'])
        self.assertEqual(result['clearcache_reason'],'not_requested'); cache.assert_not_called()

    def test_transform_and_prepare_reject_drift_without_output(self):
        source=(ROOT/'tests/fixtures/item_write_baseline.py').read_text(encoding='utf-8')
        with self.assertRaises(ValueError):G.transform(source.replace('ok = fail = 0','ok = fail = 1'))
        with tempfile.TemporaryDirectory() as name:
            baseline=Path(name)/'baseline.py'; target=Path(name)/'candidate.py';baseline.write_text(source,encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'baseline'):G.prepare(baseline,target)
            self.assertFalse(target.exists())


class RestartProof(unittest.TestCase):
    def setUp(self):
        self.now=datetime.fromisoformat('2026-10-23T09:16:00+00:00')
        self.memory=dict(id='a'*64,running=True,usage_bytes=100,restart_count=0,
                         started_at='2026-10-23T09:15:43.77241584Z',oom_killed=False)
        self.life=dict(action='restart',event_id='0e74258c-4d9e-405d-b543-5fcf24fcdb84',
                       state='verified_after_unknown',at=self.now.timestamp()-22,
                       reconciled_container=dict(id=self.memory['id'],running=True,started_at=self.memory['started_at']))

    def idle(self):
        self.life.update(idle_release=dict(container_id=self.memory['id'],started_at=self.memory['started_at'],
                                          event_id=self.life['event_id']),idle_release_verified_at=self.now.isoformat())

    def test_same_event_and_container_idle_release_is_valid(self):
        self.idle();self.assertTrue(P.restart_acceptance_verified(self.life,self.memory,self.now))

    def test_new_idle_release_does_not_require_prior_startup_fields(self):
        self.idle();self.life.pop('reconciled_container')
        self.assertTrue(P.restart_acceptance_verified(self.life,self.memory,self.now))

    def test_idle_proof_rejects_wrong_event_container_start_or_future_time(self):
        self.idle()
        for key in ('event_id','container_id','started_at'):
            value=copy.deepcopy(self.life);value['idle_release'][key]='different'
            self.assertFalse(P.restart_acceptance_verified(value,self.memory,self.now))
        for time in ('2026-10-23T06:30:24+00:00','2026-10-23T09:17:00+00:00','invalid'):
            value=dict(self.life,idle_release_verified_at=time)
            self.assertFalse(P.restart_acceptance_verified(value,self.memory,self.now))

    def test_old_startup_fields_cannot_validate_new_restart(self):
        self.life.update(startup_source_sha256='b'*64,reconciled_at='2026-10-23T06:30:24+00:00',
                         readback=dict(startup_sha256='b'*64,owned_idle=True,global_workers=0))
        self.assertFalse(P.restart_acceptance_verified(self.life,self.memory,self.now))

    def test_current_original_startup_readback_is_valid(self):
        self.life.update(startup_source_sha256='b'*64,reconciled_at=self.now.isoformat(),
                         readback=dict(startup_sha256='b'*64,owned_idle=True,global_workers=0))
        self.assertTrue(P.restart_acceptance_verified(self.life,self.memory,self.now))
        self.life['readback']['global_workers']=1
        self.assertFalse(P.restart_acceptance_verified(self.life,self.memory,self.now))
        self.life['readback']['global_workers']=0
        self.life['reconciled_container']['id']='different'
        self.assertFalse(P.restart_acceptance_verified(self.life,self.memory,self.now))

    def test_current_direct_startup_cookie_readback_is_valid(self):
        self.life.update(startup_source_sha256='b'*64,verified_at=self.now.isoformat(),
                         after_cookies=dict(logged_in=True,lootbar_blob_workers=0,cookie_count=13))
        self.assertTrue(P.restart_acceptance_verified(self.life,self.memory,self.now))

    def test_unknown_and_incomplete_or_nonfinite_event_is_unverified(self):
        self.idle()
        for change in ({'state':'unknown'},{'at':float('nan')},{'at':False},{'event_id':'different'},
                       {'action':'reload'}):
            self.assertFalse(P.restart_acceptance_verified(dict(self.life,**change),self.memory,self.now))

    def test_inherited_previous_planned_flag_is_recomputed(self):
        event=dict(started_at=self.memory['started_at'],restart_count=0,oom_killed=False,
                   observed_at=self.now.isoformat(),planned_startup_acceptance_verified=True)
        previous=dict(memory=self.memory,browser_restart_event=event)
        value=P.collect(self.now,previous,[],{},[],self.memory,lifecycle=self.life)
        self.assertFalse(value['browser_restart_event']['planned_startup_acceptance_verified'])
        self.assertIn('fc_pricing_browser_restarted:'+self.memory['started_at'],value['issues'])
        self.idle()
        value=P.collect(self.now,value,[],{},[],self.memory,lifecycle=self.life)
        self.assertTrue(value['browser_restart_event']['planned_startup_acceptance_verified'])
        self.assertNotIn('fc_pricing_browser_restarted:'+self.memory['started_at'],value['issues'])


if __name__=='__main__':unittest.main()
