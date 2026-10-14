from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from continuation import FrozenEvidenceBook,load_continuation,can_continue
from pilot import encoded
import test_controller


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_controller.ControllerTests('test_end_to_end_handshake_model_receipt_and_owner_idempotency')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.service=self.fixture.service;self.book=self.fixture.book
        self.catalog=self.book.call('fc.get_data_catalog',{})
        self.query={'start':'2026-10-05','end':'2026-10-11','group_by':['platform'],'filters':{},'page':1}
        self.original=self.book.call('fc.query_business',self.query)
        self.parent='a'*32
        spec={'period':{'start':'2026-10-05','end_exclusive':'2026-10-12','timezone':'Asia/Shanghai'},
              'snapshot_id':self.book.capture_id,'template_version':'interrupted-fixture',
              'knowledge_version':self.book.skills['version'],'budget_policy_id':'fixture'}
        task=self.service.tasks.create('owner',spec)
        self.service.tasks.reserve_dispatch(task['id'],'owner','fixture_parent_lease')
        self.service.tasks.bind_run(task['id'],'owner','fixture_parent_lease','run_'+'b'*32)
        self.service.tasks.observe(task['id'],'owner','fixture_parent_lease','failed',worker_stopped=True)
        self.parent_task=self.service.tasks.get(task['id'],'owner')
        with self.service.tasks.db() as db:
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,?)',(self.parent,'owner','parent_fixture',encoded(self.fixture.body),'FAILED',task['id'],'provider_outcome_unknown',None))
            for ref,ev in self.book.evidence.items():db.execute('INSERT INTO evidence VALUES(?,?,?)',(task['id'],ref,encoded(ev)))

    def load(self,**changes):
        args={'tasks':self.service.tasks,'parent':self.parent,'owner':'owner','start':'2026-10-05','end':'2026-10-11','root':Path(__file__).parent}
        args.update(changes);return load_continuation(**args)

    def test_cached_evidence_keeps_exact_ids_capture_times_and_deepcopy(self):
        book=self.load();value=book.call('fc.query_business',deepcopy(self.query))
        self.assertEqual(value,self.original)
        self.assertEqual(book.at.isoformat(),self.catalog['captured_at'])
        value['data']['total']['orders']=999
        self.assertEqual(book.evidence[self.original['evidence_id']],self.original)
        self.assertNotIn('NEVER-SEND',book.continuation_context)
        self.assertNotIn('user@example.com',book.continuation_context)

    def test_uncaptured_question_returns_gap_without_live_capture_or_fake_zero(self):
        value=self.load().call('fc.query_business',dict(self.query,filters={'platform':'PC'}))
        self.assertEqual(value['data']['reason'],'not_in_frozen_continuation_evidence')
        self.assertFalse(value['data']['new_source_reads'])
        self.assertNotIn('total',value['data'])

    def test_owner_period_terminal_state_and_skill_boundary(self):
        with self.assertRaises(PermissionError):self.load(owner='other')
        with self.assertRaises(ValueError):self.load(end='2026-10-10')
        with self.service.tasks.db() as db:db.execute("UPDATE tasks SET state='NEEDS_RECONCILE' WHERE id=?",(self.parent_task['id'],))
        with self.assertRaises(ValueError):self.load()
        with self.service.tasks.db() as db:
            spec=deepcopy(self.parent_task['spec']);spec['knowledge_version']='older-skill'
            db.execute("UPDATE tasks SET state='FAILED',spec=? WHERE id=?",(encoded(spec),self.parent_task['id']))
        with self.assertRaises(ValueError):self.load()

    def test_foreign_snapshot_is_not_silently_combined(self):
        evidence=deepcopy(self.book.evidence)
        evidence[self.original['evidence_id']]['analysis_anchor_id']='fc-detail-another'
        task=dict(self.parent_task,request_id=self.parent,end='2026-10-11')
        with self.assertRaises(ValueError):FrozenEvidenceBook(task,evidence,self.book.skills)

    def test_new_controller_run_stores_html_original_json_and_keeps_parent_failed(self):
        body=dict(self.fixture.body,request_id='continue_fixture',continuation_from=self.parent)
        original_parent=self.service.get_job('owner',self.parent)
        with patch('controller.build_book',side_effect=AssertionError('new capture forbidden')),patch('controller.attach_owner_history',side_effect=AssertionError('new history read forbidden')),patch('controller.gateway',side_effect=self.fixture.build_gateway),patch.object(self.service,'remote',side_effect=self.fixture.remote):
            code,job=self.service.post(body,'owner',self.fixture.headers)
            self.assertEqual(code,202)
            self.assertEqual(job['state'],'COMPLETED',job)
            self.assertNotEqual(job['task_id'],self.parent_task['id'])
            self.assertEqual(job['result']['continuation_from'],self.parent)
            self.assertFalse(job['result']['source_capture_repeated'])
            html=self.service.get({'mode':['hermes'],'id':[job['id']],'artifact':['html']},'owner')
            self.assertEqual(html[0],200);self.assertIn('<!doctype html>',html[1]['content'].lower())
            raw=self.service.get({'mode':['hermes'],'id':[job['id']],'artifact':['raw']},'owner')
            self.assertEqual(raw[0],200);self.assertIn('summary',json.loads(raw[1]['content']))
            self.assertEqual(self.service.post(body,'owner',self.fixture.headers)[0],200)
            with patch('controller.load_continuation',side_effect=ValueError('continuation_skill_mismatch')):
                self.assertEqual(self.service.post(body,'owner',self.fixture.headers)[0],200)
                self.assertEqual(self.service.post(dict(body,request_id='another_fresh_request'),'owner',self.fixture.headers)[0],422)
        current_parent=self.service.get_job('owner',self.parent)
        # The first new run initializes the shared ledger; it does not change the old row/task.
        current_parent.pop('model_usage',None);original_parent.pop('model_usage',None)
        self.assertEqual(current_parent,original_parent)
        self.assertEqual(self.service.tasks.get(self.parent_task['id'],'owner'),self.parent_task)
        with self.service.tasks.db() as db:
            inherited={r['evidence_id'] for r in db.execute('SELECT evidence_id FROM evidence WHERE task_id=?',(job['task_id'],))}
        self.assertTrue(set(self.book.evidence)<=inherited)
        self.assertEqual(list((self.fixture.run_root/'admissions').glob('*.json')),[])

    def test_foreign_parent_rejected_before_dispatch(self):
        with patch.object(self.service,'remote',side_effect=AssertionError('not dispatched')):
            body=dict(self.fixture.body,continuation_from='c'*32)
            self.assertEqual(self.service.post(body,'owner',self.fixture.headers)[0],403)
        with self.service.tasks.db() as db:row=db.execute('SELECT * FROM requests WHERE id=?',(self.parent,)).fetchone()
        self.assertTrue(can_continue(self.service.tasks,row,'owner',self.book.skills['version']))
        self.assertFalse(can_continue(self.service.tasks,row,'other',self.book.skills['version']))

    def test_new_bound_calculation_uses_frozen_fact_without_a_reader(self):
        book=self.load();ref=self.original['evidence_id']
        value=book.call('fc.calculate',{'operation':'sum','values':['10.00'],'evidence_ids':[ref],
                'value_paths':[{'evidence_id':ref,'path':'/data/total/known_revenue_usd'}],'assumptions':['']})
        self.assertEqual(value['data']['result']['sum'],'10.00')
        self.assertEqual(value['data']['basis'],'evidence_bound_calculation')

    def test_pending_cannot_replace_completed_result_and_later_denial_remains_visible(self):
        completed=deepcopy(self.original);completed['data']['status']='available'
        completed['captured_at']='2026-10-13T16:00:00+00:00'
        pending=deepcopy(self.original);pending['data']={'status':'pending'}
        pending['evidence_id']='ev_'+'f'*24;pending['captured_at']='2026-10-13T17:00:00+00:00'
        task=dict(self.parent_task,request_id=self.parent,end='2026-10-11')
        evidence={completed['evidence_id']:completed,pending['evidence_id']:pending}
        book=FrozenEvidenceBook(task,evidence,self.book.skills)
        self.assertEqual(book.call('fc.query_business',self.query)['data']['status'],'available')
        denied=deepcopy(pending);denied['evidence_id']='ev_'+'e'*24;denied['data']={'status':'permission_denied'}
        evidence[denied['evidence_id']]=denied
        book=FrozenEvidenceBook(task,evidence,self.book.skills)
        self.assertEqual(book.call('fc.query_business',self.query)['data']['status'],'permission_denied')

    def test_gap_can_be_loaded_again_after_another_interruption(self):
        book=self.load();args=dict(self.query,filters={'platform':'PC'})
        first=book.call('fc.query_business',args)
        task=dict(self.parent_task,request_id=self.parent,end='2026-10-11')
        resumed=FrozenEvidenceBook(task,book.evidence,self.book.skills)
        self.assertEqual(resumed.call('fc.query_business',args),first)


if __name__=='__main__':unittest.main()
