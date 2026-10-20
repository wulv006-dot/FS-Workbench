"""Real failure shape: a settled model response used an array for a text field."""
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
CORE=next(p for p in (HERE.parent/'hermes-v2-core-20261020',HERE.parent/'hermes_v2_core_20261020') if p.exists())
spec=importlib.util.spec_from_file_location('core_support',CORE/'test_core.py')
support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
spec=importlib.util.spec_from_file_location('review_repair',HERE/'source/learning_service.py')
service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)
lr=support.lr;NOW=support.NOW


class ReviewRepair(unittest.TestCase):
    def test_publisher_is_one_existing_target_with_original_frozen_base(self):
        spec=importlib.util.spec_from_file_location('repair_release',HERE/'deploy/release.py')
        release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
        self.assertEqual(release.TARGETS,{'source/learning_service.py':'/opt/fs-hermes-fc/learning_service.py'})
        self.assertEqual(release.NEW,frozenset())
        self.assertEqual(release.BASE_SHA,'1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de')
        manifest=dict(scope=release.SCOPE,files=[dict(candidate='source/learning_service.py',target='/opt/fs-hermes-fc/learning_service.py',beforeSha256='a'*64,owner='0:0',mode='0o644')],businessWrites=False,timersChanged=False)
        self.assertEqual(release.checked_manifest(manifest),manifest)
        manifest['files'][0]['beforeSha256']=None
        with self.assertRaises(ValueError):release.checked_manifest(manifest)

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        from pilot import TaskStore
        self.tasks=TaskStore(Path(self.folder.name)/'tasks.sqlite3')
        with self.tasks.db() as db:
            baseline=lr.manifest(db,'wulv','FS',NOW)
            self.event=lr.enqueue(db,'wulv','FS','a'*32,baseline['sha256'],'completed_report',{'evidence_refs':['real']})
            self.attempt=lr.claim(db,'wulv','FS',self.event['id'])
        self.controller=types.SimpleNamespace(tasks=self.tasks,daily=None,clock=lambda:NOW,authorizer=lambda u:u=='wulv')
        self.candidate=dict(kind='experience',lesson='比较前核对同一字段。',applies_to='经营比较',evidence_refs=['real'],counterexample='不同分母分别说明。',expires_at=(NOW+support.timedelta(days=30)).isoformat())

    def fail_model(self):
        sent=[];candidate=dict(self.candidate,applies_to=['经营比较'])
        class Gateway:
            def call(inner,owner,key,attempt,turn,body):
                inner.scope.context(owner,key,attempt);sent.append(body)
                return {'message':{'content':json.dumps(candidate),'reasoning_content':'MUST_NOT_COPY'},'provider_request_id':'settled-original','model_validation':{'status':'accepted_no_effort_echo'}}
        factory=types.ModuleType('fs_inprocess');factory.gateway=lambda *a:Gateway();factory.spending_hold=lambda *a:None
        with patch.dict(sys.modules,{'fs_inprocess':factory}):service.review_model(self.controller,'wulv',self.event['id'],self.attempt)
        return sent

    def review(self,candidate):
        return service.handle(self.controller,'wulv',{'kind':'hermes_learning','action':'review','event':self.event['id'],'candidate':candidate})

    def test_settled_invalid_candidate_retains_receipt_without_private_protocol(self):
        sent=self.fail_model()
        self.assertIn('均为单个字符串',sent[0]['messages'][0]['content'])
        with self.tasks.db() as db:
            row=lr.event(db,'wulv','FS',self.event['id']);result=json.loads(row['result'])
            self.assertEqual(row['state'],'failed');self.assertEqual(result['validation_error'],'experience_text')
            self.assertEqual(result['model_receipt']['provider_request_id'],'settled-original')
            self.assertNotIn('MUST_NOT_COPY',row['result'])

    def test_authenticated_correction_keeps_original_attempt_failure_and_no_release(self):
        self.fail_model();status,result=self.review(self.candidate)
        self.assertEqual(status,200);self.assertFalse(result['model_replayed'])
        self.assertEqual(result['previous_review']['model_receipt']['provider_request_id'],'settled-original')
        with self.tasks.db() as db:
            self.assertEqual(lr.event(db,'wulv','FS',self.event['id'])['attempt'],self.attempt)
            self.assertEqual(lr.manifest(db,'wulv','FS',NOW)['experiences'],[])

    def test_invalid_correction_rolls_back_failed_state(self):
        self.fail_model();self.assertEqual(self.review(dict(self.candidate,evidence_refs=['forged']))[0],422)
        with self.tasks.db() as db:self.assertEqual(lr.event(db,'wulv','FS',self.event['id'])['state'],'failed')

    def test_unknown_attempt_requires_reconciliation_and_other_owner_denied(self):
        with self.tasks.db() as db:db.execute("UPDATE learning_events SET state='unknown' WHERE id=?",(self.event['id'],))
        self.assertEqual(self.review(self.candidate)[0],409)
        self.assertEqual(service.handle(self.controller,'reader',{'kind':'hermes_learning','action':'review'})[0],403)


if __name__=='__main__':unittest.main()
