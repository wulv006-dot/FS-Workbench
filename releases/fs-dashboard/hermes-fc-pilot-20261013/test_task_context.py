from pathlib import Path
import hashlib
import unittest
import json
import tempfile
from unittest.mock import patch
from background import task_context
from fs_inprocess import approved_background
from skill_bundle import load_bundle


class TaskContextTests(unittest.TestCase):
    def test_real_admission_accepts_paired_context_and_rejects_partial_context(self):
        import hermes_worker
        root=Path(__file__).parent
        background=approved_background(root)
        _,receipt=task_context(background,load_bundle(root))
        session='fc_'+'a'*64
        item={'session_id':session,'token':'a'*64,'model':'deepseek-flash','prompt':'Synthetic only',
              'background':background,'context_receipt':receipt}
        with tempfile.TemporaryDirectory() as tmp,patch.object(hermes_worker,'ADMISSIONS',Path(tmp)):
            path=Path(tmp)/(session+'.json')
            path.write_text(json.dumps(item),encoding='utf-8')
            self.assertEqual(hermes_worker.admission(session),item)
            del item['context_receipt']
            path.write_text(json.dumps(item),encoding='utf-8')
            with self.assertRaisesRegex(PermissionError,'admission_context_invalid'):hermes_worker.admission(session)

    def test_verified_business_preferences_and_methods_are_injected_and_fingerprinted(self):
        root=Path(__file__).parent
        background=approved_background(root)
        bundle=load_bundle(root)
        text,receipt=task_context(background,bundle)
        self.assertIn('主站及NBA2KING',text)
        self.assertIn('结论价值',text)
        self.assertIn('1048576',text)
        self.assertIn('393216',text)
        self.assertIn(bundle['methods_text'],text)
        self.assertIn(bundle['governance_text'],text)
        self.assertEqual(receipt['background_version'],'derived-1.1-20261014')
        self.assertEqual(receipt['context_sha256'],hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(receipt['permissions_added'],[])
        self.assertFalse(receipt['external_skill_scripts_executed'])
        self.assertEqual(len(receipt['reviewed_skills']),5)
        self.assertIn('final_expression_preserve_facts_evidence_confidence',text)
        self.assertIn('existing_sanitized_feedback_only_when_available',text)
        self.assertNotIn('- 95% confidence = p-value < 0.05',text)
        self.assertIn('It is not the probability that the null is true',text)

    def test_changed_background_is_rejected_before_runner(self):
        root=Path(__file__).parent
        background=approved_background(root)
        background['content']+='tampered'
        with self.assertRaises(PermissionError):task_context(background,load_bundle(root))

    def test_failed_runtime_still_preserves_prepared_context_not_false_confirmation(self):
        from test_controller import ControllerTests
        fixture=ControllerTests('test_end_to_end_handshake_model_receipt_and_owner_idempotency')
        fixture.setUp()
        try:
            service=fixture.service
            def remote(*args,**kwargs):
                if args[1]=='/v1/runs':return 202,{'run_id':'run_'+'a'*32,'status':'queued'}
                return 200,{'status':'failed','error':'synthetic'}
            with patch('controller.build_book',return_value=fixture.book),patch('controller.gateway',side_effect=fixture.build_gateway),patch.object(service,'remote',side_effect=remote):
                _,job=service.post(fixture.body,'owner',fixture.headers)
            self.assertEqual(job['state'],'FAILED')
            self.assertEqual(job['context_loading']['status'],'prepared_for_runner')
            self.assertEqual(job['context_loading']['background_version'],'derived-1.1-20261014')
            self.assertEqual(job['model_usage']['calls'],0)
        finally:fixture.doCleanups()


if __name__=='__main__':unittest.main()
