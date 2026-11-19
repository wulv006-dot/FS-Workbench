"""Real WSGI/Repository resume contracts; deferred fake pool and fake backend only."""
from dataclasses import replace
import hashlib
import io
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_direct_import as fixtures
from test_direct_import import direct, load
from player_web.repository import digest
from player_web.settings import Settings

service = load('new_card_service')
load('shared_session')
web = load('main')


class DeferredPool:
    def __init__(self):self.pending=[];self.submissions=[]
    def submit(self, function, *args):
        self.submissions.append((function,args));self.pending.append((function,args))
        return SimpleNamespace()
    def drain(self):
        while self.pending:
            function,args=self.pending.pop(0);function(*args)


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.flow=fixtures.DirectImportTests('runTest');self.flow.setUp();self.flow.plan()
        self.repo=self.flow.repo;self.execution=self.flow.execution;self.backend=self.flow.backend
        self.repo.set_execution(self.execution,'needs_reconcile','unknown',{'original_error':'preserve'})
        self.settings=Settings(self.flow.root,'https://source.invalid','https://admin-api.p2pah.cn',
            'https://fs.invalid','/tools/fc27-players',False,False,3,5000,1.0,
            manual_new_cards_enabled=True,shared_backend_session=True)
        self.pool=DeferredPool()
        with patch.object(web,'ThreadPoolExecutor',return_value=self.pool):self.app=web.App(self.settings)
        self.sid,self.csrf=self.bootstrap('operator')
        self.key='operator:'+self.sid
        self.app._sessions[self.key]=(self.backend,time.time(),time.time())
        # Any accidental network call is a test failure, including hidden fallback login.
        self.network=patch('socket.create_connection',side_effect=AssertionError('No network permitted'))
        self.network.start()

    def tearDown(self):
        self.network.stop();self.flow.tearDown()

    def request(self,path,method='GET',body=None,*,owner='operator',role='admin',sid=None,csrf=None,origin=None):
        raw=json.dumps(body).encode() if body is not None else b''
        env={'PATH_INFO':path,'REQUEST_METHOD':method,'REMOTE_ADDR':'127.0.0.1',
             'HTTP_X_FC27_USER':owner,'HTTP_X_FC27_ROLE':role,'wsgi.input':io.BytesIO(raw),
             'CONTENT_LENGTH':str(len(raw)),'HTTP_ORIGIN':self.settings.public_origin if origin is None else origin,
             'HTTP_X_CSRF_TOKEN':getattr(self,'csrf','') if csrf is None else csrf,
             'HTTP_COOKIE':'FC27PLAYER_SID='+(getattr(self,'sid','') if sid is None else sid)}
        response={}
        def start(status,headers):response.update(status=int(status.split()[0]),headers=headers)
        payload=b''.join(self.app(env,start));return response['status'],json.loads(payload),response['headers']

    def bootstrap(self,owner,role='admin'):
        status,result,headers=self.request('/api/bootstrap',owner=owner,role=role,sid='',csrf='')
        self.assertEqual(status,200)
        cookie=next(value for key,value in headers if key=='Set-Cookie')
        return cookie.split('=',1)[1].split(';',1)[0],result['csrf']

    def resume(self,**kwargs):
        return self.request('/api/jobs/'+self.execution+'/resume','POST',{'confirmed':True},**kwargs)

    def row_counts(self):
        with self.repo.connection() as db:
            return {table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('executions','plans','active_scope')}

    def legacy(self,*,proof):
        # Build an immutable legacy plan; migrate with an append-only controlled event.
        original=self.repo.get_plan(self.flow.frozen['plan_id'],'operator')
        payload={key:value for key,value in original.items() if key not in ('plan_id','plan_digest','status','execution_id','created_at','expires_at')}
        payload.pop('import_mode',None);payload.pop('direct_items',None)
        with self.repo.connection() as db:
            db.execute('DELETE FROM active_scope WHERE execution_id=?',(self.execution,))
        old=self.repo.save_plan('operator',payload)
        execution,_=self.repo.confirm(old['plan_id'],'operator',old['plan_digest'],write_enabled=True)
        self.execution=execution;self.flow.execution=execution
        derived={**original,'plan_id':old['plan_id'],'origin_plan_digest':old['plan_digest'],
                 'execution_id':execution,'status':'consumed'}
        details={'root_controlled':True,'direct_plan':derived,'direct_plan_sha256':digest(derived),
                 'authorization_summary':{'tag_ids':[12307,12411]}}
        if proof:details['original_request_no_enqueue_evidence']={'original_request':'fixture','rejected_before_enqueue':True}
        self.repo.set_execution(execution,'needs_reconcile','direct_plan_migration',details)
        return derived

    def test_resume_queues_same_id_runs_real_direct_flow_and_never_changes_plan(self):
        before=self.row_counts();frozen=self.repo.get_plan(self.flow.frozen['plan_id'],'operator')
        status,result,_=self.resume()
        self.assertEqual((status,result['execution_id']),(202,self.execution))
        self.assertEqual(self.row_counts(),before)
        self.assertEqual(self.pool.submissions[0][1][1],self.execution)
        self.assertEqual(self.backend.calls,[],'HTTP only queues; no write in request thread')
        self.pool.drain()
        self.assertEqual(self.repo.get_execution(self.execution,'operator')['status'],'completed_readback')
        self.assertEqual(self.repo.get_plan(frozen['plan_id'],'operator'),frozen)
        self.assertEqual(self.backend.calls.count(('add','23700')),1)
        self.assertEqual(self.row_counts()['executions'],before['executions'])

    def test_image_resume_reuses_attachment_skips_verified_and_continues_same_id(self):
        from player_web.model_image_service import create_batch, stage_png, prepare_image_plan, execute_image_plan
        from player_web.model_service import refresh_models
        from tests_cloud.test_model_images import png
        from tests_cloud.test_feature_parity import Backend
        from player_web.model_image_service import AdminHttpError, ImageUploadNotStarted

        self.app.settings = replace(self.settings, manual_model_images_enabled=True, manual_new_cards_enabled=False)
        self.settings = self.app.settings
        backend = Backend(3)
        for row in backend.rows.values():
            row["icon"] = 0
        content = png()
        image_hash = hashlib.sha256(content).hexdigest()
        snapshot = refresh_models(self.settings, self.repo, backend, "operator")
        names = ["400000.png", "400001.png", "400002.png"]
        batch = create_batch(self.settings, self.repo, backend, "operator", snapshot["snapshot_id"],
                             [{"name": name, "size": len(content), "sha256": image_hash} for name in names])
        for name in names:
            stage_png(self.settings, "operator", batch["batch_id"], name, content)
        plan = prepare_image_plan(self.settings, self.repo, backend, "operator", batch["batch_id"])
        execution, created = self.repo.confirm(plan["plan_id"], "operator", plan["plan_digest"], write_enabled=True)
        self.assertTrue(created)
        self.execution = execution
        self.app._sessions[self.key] = (backend, time.time(), time.time())
        get_model = backend.get_model
        uploads = Mock(side_effect=[{"attachment_id": 777, "url": ""}, {"attachment_id": 778, "url": ""},
                                    ImageUploadNotStarted("IMAGE_UPLOAD_PRECHECK_FAILED"),
                                    {"attachment_id": 779, "url": ""}])

        def read_model(model_id):
            if uploads.call_count == 2 and model_id == 300001:
                raise AdminHttpError("read timed out")
            return get_model(model_id)

        def bind(client, model_id, attachment_id):
            client.rows[model_id]["icon"] = attachment_id

        image_module = web.execute_image_plan.__module__
        with patch(image_module + ".upload_png", uploads), patch(image_module + ".edit_model_icon", side_effect=bind) as edit:
            with patch.object(backend, "get_model", side_effect=read_model):
                with self.assertRaises(AdminHttpError):
                    execute_image_plan(self.settings, self.repo, backend, execution, plan)
            job_path = "/api/jobs/" + execution
            before = self.request(job_path)[1]
            self.assertTrue(before["can_resume"])
            self.assertTrue(before["image_resume"])
            self.assertEqual([item["status"] for item in before["items"]], ["verified", "unknown", "planned"])
            self.assertEqual([call.args[1] for call in edit.call_args_list], [300000])
            self.assertEqual(self.request(job_path + "/resume", "POST", {})[1]["error"], "EXPLICIT_CONFIRMATION_REQUIRED")
            self.assertEqual(self.resume(csrf="wrong")[0], 403)
            self.assertEqual(self.resume()[1], {"execution_id": execution, "status": "queued"})
            self.assertEqual(self.resume()[1], {"execution_id": execution, "status": "existing"})
            self.assertEqual(len(self.pool.submissions), 1)
            self.pool.drain()
            blocked = self.request(job_path)[1]
            self.assertTrue(blocked["can_resume"])
            self.assertEqual([item["status"] for item in blocked["items"]], ["verified", "verified", "not_started"])
            self.assertEqual(self.resume()[1], {"execution_id": execution, "status": "queued"})
            self.pool.drain()
        self.assertEqual([call.args[1].name for call in uploads.call_args_list], names + [names[-1]])
        self.assertEqual([(call.args[1], call.args[2]) for call in edit.call_args_list],
                         [(300000, 777), (300001, 778), (300002, 779)])
        after = self.repo.get_execution(execution, "operator")
        self.assertEqual(after["status"], "completed_readback")
        self.assertEqual([item["after"]["icon"] for item in after["items"]], [777, 778, 779])
        self.assertEqual(after["events"][:len(before["events"])], before["events"])
        self.assertEqual(after["events"][-1]["detail"]["images_verified"], 3)

    def test_repeat_resume_has_no_second_submission_or_new_execution(self):
        self.assertEqual(self.resume()[0],202)
        status,result,_=self.resume()
        self.assertEqual(status,202)
        self.assertEqual(result,{'execution_id':self.execution,'status':'existing'})
        self.assertEqual(len(self.pool.submissions),1)
        self.assertEqual(self.row_counts()['executions'],1)

    def test_pool_rejection_clears_placeholder_preserves_scope_and_can_resume_same_id(self):
        counts=self.row_counts()
        with patch.object(self.pool,'submit',side_effect=RuntimeError('executor refused before dispatch')):
            status,_,_=self.resume()
        self.assertEqual(status,502)
        self.assertNotIn(self.execution,self.app._stops)
        job=self.repo.get_execution(self.execution,'operator')
        self.assertEqual((job['status'],job['step']),('needs_reconcile','direct_resume_not_started'))
        self.assertEqual(self.row_counts(),counts);self.assertEqual(self.backend.calls,[])
        self.assertEqual(self.resume()[1]['execution_id'],self.execution)
        self.assertEqual(len(self.pool.submissions),1)

    def test_queued_ledger_failure_clears_placeholder_without_dispatch(self):
        counts=self.row_counts()
        with patch.object(self.app.repository,'set_execution',side_effect=RuntimeError('ledger unavailable before queued')):
            self.assertEqual(self.resume()[0],502)
        self.assertNotIn(self.execution,self.app._stops)
        self.assertEqual(self.pool.submissions,[]);self.assertEqual(self.backend.calls,[])
        self.assertEqual(self.row_counts(),counts)
        self.assertEqual(self.resume()[1]['execution_id'],self.execution)

    def test_role_origin_csrf_browser_session_and_backend_auth_are_required(self):
        cases=({'role':'readonly'},{'origin':'https://other.invalid'},{'csrf':'wrong'},{'sid':'unknown_browser_session'})
        for overrides in cases:
            status,_,_=self.resume(**overrides);self.assertEqual(status,403)
        self.app._sessions.clear()
        status,result,_=self.resume();self.assertEqual((status,result['error']),(409,'AUTH_REQUIRED'))
        self.assertEqual(self.pool.submissions,[])

    def test_other_owner_cannot_resume_or_view_execution(self):
        sid,csrf=self.bootstrap('different')
        self.app._sessions['different:'+sid]=(self.backend,time.time(),time.time())
        self.assertEqual(self.resume(owner='different',sid=sid,csrf=csrf)[0],409)
        self.assertEqual(self.request('/api/jobs/'+self.execution,owner='different',sid=sid,csrf=csrf)[0],409)
        self.assertEqual(self.pool.submissions,[])

    def test_resume_rejects_any_caller_supplied_plan_or_scope(self):
        for body in ({},{'confirmed':False},{'confirmed':1},{'confirmed':1.0},{'confirmed':'true'},
                     {'confirmed':True,'plan':self.flow.frozen},
                     {'confirmed':True,'only_futbin_ids':['99999']},{'confirmed':True,'tag_ids':[1]}):
            status,result,_=self.request('/api/jobs/'+self.execution+'/resume','POST',body)
            self.assertEqual((status,result['error']),(409,'EXPLICIT_CONFIRMATION_REQUIRED'))
        self.assertEqual(self.pool.submissions,[])

    def test_stop_writes_and_manual_switch_are_enforced(self):
        marker=self.flow.root/'STOP_WRITES';marker.touch()
        self.assertEqual(self.resume()[1]['error'],'WRITE_DISABLED');marker.unlink()
        self.app.settings=replace(self.settings,manual_new_cards_enabled=False)
        self.assertEqual(self.resume()[1]['error'],'WRITE_DISABLED')
        self.assertEqual(self.pool.submissions,[])

    def test_current_source_policy_revalidated_before_queue(self):
        self.app.settings=replace(self.settings,player_db_base_url='http://139.28.18.234:8001',
                                  approved_public_http_source='http://139.28.18.234:8001')
        status,result,_=self.resume()
        self.assertEqual((status,result['error']),(409,'SOURCE_TRANSPORT_UNVERIFIED'))
        self.assertEqual(self.pool.submissions,[])

    def test_frozen_artifact_change_blocks_queue_and_keeps_unknown_scope(self):
        before=self.row_counts();artifact=self.flow.frozen['artifact_path']
        with open(artifact,'ab') as handle:handle.write(b'changed')
        self.assertEqual(self.resume()[0],409)
        self.assertEqual(self.pool.submissions,[]);self.assertEqual(self.row_counts(),before)
        self.assertEqual(self.repo.get_execution(self.execution,'operator')['status'],'needs_reconcile')

    def test_missing_artifact_keeps_historical_job_readable_but_not_resumable(self):
        from pathlib import Path
        Path(self.flow.frozen['artifact_path']).unlink()
        status,result,_=self.request('/api/jobs/'+self.execution)
        self.assertEqual(status,200,result)
        self.assertEqual(result['id'],self.execution)
        self.assertFalse(result['can_resume'])
        self.assertTrue(result['events'])

    def test_get_job_exposes_resume_summary_but_not_migrated_direct_plan(self):
        self.legacy(proof=True)
        status,result,_=self.request('/api/jobs/'+self.execution)
        self.assertEqual(status,200);self.assertTrue(result['can_resume'])
        event=next(event for event in result['events'] if event['step']=='direct_plan_migration')
        self.assertNotIn('direct_plan',event['detail'])
        self.assertIn('direct_plan_sha256',event['detail'])
        self.assertIn('authorization_summary',event['detail'])
        self.assertEqual(self.pool.submissions,[])

    def test_proved_migration_executes_under_original_id_and_preserves_legacy_plan(self):
        derived=self.legacy(proof=True)
        original=self.repo.get_plan(derived['plan_id'],'operator');counts=self.row_counts()
        self.assertNotEqual(original.get('import_mode'),'direct_json_v1')
        self.assertEqual(self.resume()[1]['execution_id'],self.execution)
        self.pool.drain()
        job=self.repo.get_execution(self.execution,'operator')
        self.assertEqual(job['status'],'completed_readback')
        self.assertTrue(any(event['step']=='direct_plan_migration' for event in job['events']))
        self.assertEqual(self.repo.get_plan(derived['plan_id'],'operator'),original)
        self.assertEqual(self.row_counts()['executions'],counts['executions'])
        self.assertEqual(self.backend.calls.count(('add','23700')),1)
        self.assertEqual(set(next(iter(self.backend.rows.values()))['tid']),{12307,12411})

    def test_unproved_old_multipart_migration_never_resumes(self):
        self.legacy(proof=False)
        self.assertFalse(self.request('/api/jobs/'+self.execution)[1]['can_resume'])
        status,result,_=self.resume()
        self.assertEqual((status,result['error']),(409,'DIRECT_MIGRATION_PROOF_REQUIRED'))
        self.assertEqual(self.pool.submissions,[]);self.assertEqual(self.backend.calls,[])

    def test_old_multipart_without_migration_is_not_resumable(self):
        self.legacy(proof=False)
        with self.repo.connection() as db:db.execute("DELETE FROM events WHERE execution_id=? AND step='direct_plan_migration'",(self.execution,))
        status,result,_=self.resume();self.assertEqual((status,result['error']),(409,'DIRECT_PLAN_REQUIRED'))
        self.assertFalse(self.request('/api/jobs/'+self.execution)[1]['can_resume'])

    def test_terminal_execution_is_not_resumable(self):
        self.repo.set_execution(self.execution,'completed_readback','done',release_scope=True)
        self.assertFalse(self.request('/api/jobs/'+self.execution)[1]['can_resume'])
        self.assertEqual(self.resume()[1]['error'],'DIRECT_JOB_NOT_RESUMABLE')
        self.assertEqual(self.pool.submissions,[])

    def test_stop_direct_job_preserves_scope_and_same_id_can_resume(self):
        self.assertEqual(self.resume()[0],202)
        before=self.row_counts()
        self.assertEqual(self.request('/api/jobs/'+self.execution+'/stop','POST',{})[0],200)
        self.pool.drain()
        self.assertEqual(self.backend.calls,[])
        self.assertEqual(self.row_counts(),before)
        self.assertIn(self.repo.get_execution(self.execution,'operator')['status'],('needs_reconcile','partial_readback'))
        self.assertEqual(self.resume()[0],202)

    def test_existing_plan_confirmation_remains_functional(self):
        # Synthetic earlier job is finished, so a fresh valid plan can own its scope.
        self.repo.set_execution(self.execution,'completed_readback','done',release_scope=True)
        plan=self.repo.save_plan('operator',self.flow.frozen)
        status,result,_=self.request('/api/plans/'+plan['plan_id']+'/confirm','POST',
                                   {'confirmed':True,'plan_digest':plan['plan_digest']})
        self.assertEqual(status,202,result)
        self.assertEqual(len(self.pool.submissions),1)


if __name__=='__main__':unittest.main(verbosity=2)
