import json,unittest
from pathlib import Path
from unittest.mock import patch
import test_controller
from controller import HermesService
from report_delivery import deliver_output
from report_artifacts import read_file


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.f=test_controller.ControllerTests('test_end_to_end_handshake_model_receipt_and_owner_idempotency')
        self.f.setUp();self.addCleanup(self.f.doCleanups)

    def run_native(self,raw=None):
        f=self.f
        def remote(*args,**kwargs):
            code,result=f.remote(*args,**kwargs)
            if result.get('output') and raw is not None:result['output']=raw
            return code,result
        with patch('controller.build_book',return_value=f.book),patch('controller.gateway',side_effect=f.build_gateway),patch.object(f.service,'remote',side_effect=remote):
            return f.service.post(f.body,'owner',f.headers)[1]

    def test_result_submission_failure_recovers_only_receipt_and_is_idempotent(self):
        f=self.f;real=f.service.update;failed=[]
        def update(key,**values):
            if values.get('state')=='COMPLETED' and not failed:failed.append(True);raise OSError('synthetic write failure')
            return real(key,**values)
        with patch.object(f.service,'update',side_effect=update):job=self.run_native('# Decision\n\nComplete native analysis.\n')
        self.assertEqual(job['state'],'REPORT_PENDING');self.assertEqual(job['model_usage']['calls'],1)
        self.assertEqual(f.service.get({'mode':['hermes'],'id':[job['id']],'artifact':['raw']},'owner')[0],200)
        with patch('controller.build_book',side_effect=AssertionError('no new capture')),patch('controller.gateway',side_effect=AssertionError('no model')),patch.object(f.service,'remote',side_effect=AssertionError('no runtime')):
            f.service.recover_reports();f.service.recover_reports()
        result=f.service.get_job('owner',job['id'])
        self.assertEqual(result['state'],'COMPLETED');self.assertEqual(result['model_usage']['calls'],1)
        self.assertEqual(result['result']['delivery_status'],'ready')
        with f.service.tasks.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0],1)

    def test_process_restart_recovers_saved_report_without_model_or_chat(self):
        f=self.f
        with patch('controller.save_result',side_effect=OSError('synthetic renderer store failure')):job=self.run_native('# Native output\n\nSaved before delivery.\n')
        self.assertEqual(job['state'],'REPORT_PENDING');self.assertEqual(job['task_state'],'VALIDATING')
        service=HermesService(None,f.daily,None,None,f.root/'state',f.run_root,Path(__file__).parent,lambda u:u=='owner',clock=lambda:f.at)
        self.addCleanup(service.pool.shutdown)
        with patch.object(service,'remote',side_effect=AssertionError('no new run')),patch('controller.gateway',side_effect=AssertionError('no model')):service.recover_reports()
        recovered=service.get_job('owner',job['id']);self.assertEqual(recovered['state'],'COMPLETED')
        self.assertEqual(recovered['model_usage']['calls'],1)
        self.assertEqual(service.get({'mode':['hermes'],'id':[job['id']],'artifact':['html']},'owner')[0],200)

    def test_private_text_rejected_before_original_saved_sk_business_text_allowed(self):
        for raw in ['密码：SYNTHETIC_ONLY','user@example.com','password=SYNTHETIC_ONLY','Bearer SYNTHETIC_ONLY',json.dumps({'note':'密码：SYNTHETIC_ONLY'},ensure_ascii=True),json.dumps({'note':'Bearer\nSYNTHETIC_ONLY'}),json.dumps({'note':'Bearer\tSYNTHETIC_ONLY'})]:
            with self.subTest(raw=raw),self.assertRaisesRegex(ValueError,'sensitive_analysis'):deliver_output(raw,self.f.book)
        self.assertEqual(deliver_output('sk 用于业务标签。',self.f.book)['delivery_status'],'ready')
        job=self.run_native('# report\n\n密码：SYNTHETIC_ONLY')
        self.assertEqual(job['state'],'FAILED');self.assertFalse((self.f.service.root/'reports'/job['task_id']/'model.txt').exists())

    def test_changed_artifact_and_read_missing_path_are_not_silent_or_mutating(self):
        f=self.f
        with self.assertRaises(FileNotFoundError):read_file(f.service.root,'f'*32,'raw')
        self.assertFalse((f.service.root/'reports'/('f'*32)).exists())
        job=self.run_native('# Complete\n\nOriginal.');path=f.service.root/'reports'/job['task_id']/'report.html'
        path.write_text('changed',encoding='utf-8')
        self.assertEqual(f.service.get({'mode':['hermes'],'id':[job['id']],'artifact':['html']},'owner')[0],404)
        self.assertEqual(f.service.get({'mode':['hermes'],'id':[job['id']],'artifact':['raw'],'evidence':['ev_'+'a'*24]},'owner')[0],422)

    def test_cancel_after_native_completed_during_delivery_cannot_orphan_saved_report(self):
        f=self.f
        with patch('controller.save_result',side_effect=OSError('synthetic store failure')):job=self.run_native('# Complete\n\nOriginal.\n')
        self.assertEqual(job['state'],'REPORT_PENDING');self.assertEqual(job['task_state'],'VALIDATING')
        code,result=f.service.post({'kind':'hermes_cancel','id':job['id']},'owner',f.headers)
        self.assertEqual(code,409);self.assertEqual(result['error'],'analysis_finished_report_delivery_pending')
        self.assertEqual(f.service.get_job('owner',job['id'])['state'],'REPORT_PENDING')
        f.service.recover_reports();self.assertEqual(f.service.get_job('owner',job['id'])['state'],'COMPLETED')

    def test_gap_report_without_evidence_recovers_without_faking_sources(self):
        f=self.f
        def remote(method,path,*args,**kwargs):
            return (202,{'run_id':'run_'+'a'*32,'status':'queued'}) if method=='POST' else (200,{'status':'completed','output':'# Evidence gap\n\nNo readable sources available; no business attribution.'})
        with patch('controller.build_book',return_value=f.book),patch('controller.gateway',side_effect=f.build_gateway),patch.object(f.service,'remote',side_effect=remote),patch('controller.save_result',side_effect=OSError('temporary disk failure')):
            job=f.service.post(f.body,'owner',f.headers)[1]
        self.assertEqual(job['state'],'REPORT_PENDING');self.assertEqual(job['evidence_count'],0)
        with patch.object(f.service,'remote',side_effect=AssertionError('no new run')):f.service.recover_reports()
        job=f.service.get_job('owner',job['id']);self.assertEqual(job['state'],'COMPLETED');self.assertEqual(job['evidence_count'],0)

    def test_cancel_between_task_completion_and_receipt_retry_is_not_falsely_accepted(self):
        f=self.f;real=f.service.update;codes=[]
        def update(key,**values):
            if values.get('state')=='COMPLETED' and not codes:
                codes.append(f.service.post({'kind':'hermes_cancel','id':key},'owner',f.headers))
                raise OSError('synthetic receipt failure')
            return real(key,**values)
        with patch.object(f.service,'update',side_effect=update):job=self.run_native('# Completed\n\nOriginal.\n')
        self.assertEqual(codes[0][0],409);self.assertEqual(job['state'],'REPORT_PENDING')
        f.service.recover_reports();self.assertEqual(f.service.get_job('owner',job['id'])['state'],'COMPLETED')

    def test_unexpected_json_index_type_failure_preserves_original_and_html(self):
        f=self.f
        def invalid(raw,book):raise TypeError('unhashable claim type')
        raw=json.dumps({'summary':'Original completed investigation','findings':[{'claim_type':['fact']}]})
        result=deliver_output(raw,f.book,validator=invalid)
        self.assertEqual(result['delivery_status'],'raw_saved');self.assertEqual(result['raw_model_text'],raw)
        with patch('controller.validate_output',side_effect=invalid):job=self.run_native(raw)
        self.assertEqual(job['state'],'COMPLETED');self.assertEqual(job['task_state'],'PARTIAL')
        self.assertEqual(f.service.get({'mode':['hermes'],'id':[job['id']],'artifact':['html']},'owner')[0],200)


if __name__=='__main__':unittest.main()
