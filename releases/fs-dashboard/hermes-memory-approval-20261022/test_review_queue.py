import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import review_queue
from review_queue import validate_decision, decision_projection, prior_unknown, HEADER, SKILL_HELPERS, LIST, NATIVE, EXPERIENCE, MANIFEST, SNAPSHOT, SKILL, SKILL_SNAPSHOT, SKILL_INSPECT


class DecisionTests(unittest.TestCase):
    def test_remote_programs_parse_before_any_write(self):
        for code in (LIST,NATIVE,EXPERIENCE,MANIFEST,SNAPSHOT,SKILL,SKILL_SNAPSHOT,SKILL_INSPECT):
            compile(HEADER+'\n'+SKILL_HELPERS+'\nDATA={}\n'+code,'review-operation','exec')

    def test_daily_projection_preserves_receipt_without_repeating_memory(self):
        row=dict(request_id='r',decision={'id':'experience:'+'a'*64,'decision':'approve'},status='completed',created_at=1,result=dict(success=True,applied=True,result=dict(sha256='s',experiences=[{'content':'private old memory'}])))
        compact=decision_projection(row)
        self.assertEqual(compact['result']['knowledge_sha256'],'s')
        self.assertNotIn('experiences',str(compact))
        self.assertNotIn('private old memory',str(compact))

    def test_exact_candidate_and_evidence_are_required(self):
        valid=dict(id='native:ab1234cd',decision='approve',expected_sha='a'*64,target_sha='b'*64,reason='可核对的明确用户偏好',evidence='用户原话及当前合同')
        self.assertIs(validate_decision(valid),valid)
        for field,value in [('id','../../MEMORY'),('decision','auto'),('expected_sha','old'),('target_sha',''),('evidence',''),('reason','ok')]:
            d=copy.deepcopy(valid);d[field]=value
            with self.assertRaises(ValueError):validate_decision(d)

    def test_skill_id_compatible_and_unknown_cannot_change_reason_to_replay(self):
        row=dict(id='skill:ab1234cd',decision='approve',expected_sha='a'*64,target_sha='b'*64,reason='已检查来源与全部技能文件',evidence='fixture')
        self.assertIs(validate_decision(row),row)
        for status in ('applying','unknown_inspect_before_retry'):
            self.assertTrue(prior_unknown([dict(decision=row,status=status)],row['id']))
        self.assertFalse(prior_unknown([dict(decision=row,status='blocked_not_applied')],row['id']))

    def run_decision(self,root,decision,run,export_error=None):
        path=root/'decision.input';path.write_text(json.dumps(decision),encoding='utf-8')
        fake_fcntl=SimpleNamespace(flock=lambda *a:None,LOCK_EX=1)
        with patch.object(review_queue,'ROOT',root),patch.object(review_queue,'run',run),\
             patch.object(review_queue,'export_reviews',side_effect=export_error),patch.dict(sys.modules,{'fcntl':fake_fcntl}),\
             patch.object(sys,'argv',['review_queue.py','decide','--decision-file',str(path)]):
            review_queue.main()

    def test_durable_backup_precedes_apply_and_same_decision_never_applies_twice(self):
        decision=dict(id='skill:ab1234cd',decision='reject',expected_sha='a'*64,target_sha='b'*64,
                      reason='拒绝缺少证据的技能候选',evidence='review fixture')
        request_id=hashlib.sha256(review_queue.canonical(decision)).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);calls=[]
            def run(code,data=None):
                calls.append(code)
                if code==LIST:return dict(skills=[dict(id=decision['id'],sha256='a'*64,target_sha256='b'*64)],native=[],experiences=[])
                if code==SKILL_SNAPSHOT:return dict(snapshots=[dict(path='alpha',entries=[dict(path='SKILL.md',bytes_base64='cHJvb2Y=')])])
                self.assertEqual(code,SKILL)
                durable=json.loads((root/(request_id+'.json')).read_text(encoding='utf-8'))
                self.assertEqual(durable['backup']['snapshots'][0]['entries'][0]['bytes_base64'],'cHJvb2Y=')
                self.assertEqual(durable['status'],'applying')
                return dict(success=True,applied=False,rejected=True)
            self.run_decision(root,decision,run)
            self.assertEqual(calls.count(SKILL),1)
            before=len(calls)
            self.run_decision(root,decision,run)
            self.assertEqual(len(calls),before)

    def test_unknown_is_durable_and_new_reason_cannot_replay_candidate(self):
        decision=dict(id='skill:ab1234cd',decision='reject',expected_sha='a'*64,target_sha='b'*64,
                      reason='拒绝缺少证据的技能候选',evidence='review fixture')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);calls=[]
            def run(code,data=None):
                calls.append(code)
                if code==LIST:return dict(skills=[dict(id=decision['id'],sha256='a'*64,target_sha256='b'*64)],native=[],experiences=[])
                if code==SKILL_SNAPSHOT:return dict(snapshots=[])
                raise TimeoutError('fixture unknown transport')
            with self.assertRaises(TimeoutError):self.run_decision(root,decision,run)
            receipt=json.loads(next(root.glob('*.json')).read_text(encoding='utf-8'))
            self.assertEqual(receipt['status'],'unknown_inspect_before_retry')
            changed=dict(decision,reason='另一段理由也不构成重放授权')
            with self.assertRaisesRegex(RuntimeError,'prior_unknown'):self.run_decision(root,changed,run)
            self.assertEqual(calls.count(SKILL),1)

    def test_projection_failure_keeps_known_completed_application(self):
        decision=dict(id='skill:ab1234cd',decision='reject',expected_sha='a'*64,target_sha='b'*64,
                      reason='拒绝缺少证据的技能候选',evidence='review fixture')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def run(code,data=None):
                if code==LIST:return dict(skills=[dict(id=decision['id'],sha256='a'*64,target_sha256='b'*64)],native=[],experiences=[])
                if code==SKILL_SNAPSHOT:return dict(snapshots=[])
                return dict(success=True,applied=False,rejected=True)
            with self.assertRaisesRegex(OSError,'fixture projection'):
                self.run_decision(root,decision,run,OSError('fixture projection'))
            receipt=json.loads(next(root.glob('*.json')).read_text(encoding='utf-8'))
            self.assertEqual(receipt['status'],'completed')

    def test_inspect_draft_exposes_complete_prevalue_without_applying_or_saving_receipt(self):
        draft=dict(id='skill:ab1234cd',decision='approve',expected_sha='a'*64,target_sha='b'*64,
                   reason='审核前检查完整包及引用依赖',evidence='draft fixture')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'draft.input';source.write_text(json.dumps(draft),encoding='utf-8')
            native_lock=SimpleNamespace(flock=lambda *args:None,LOCK_EX=1)
            with patch.object(review_queue,'ROOT',root),patch.dict(sys.modules,{'fcntl':native_lock}),\
                 patch.object(review_queue,'run',return_value={'snapshots':[{'entries':[{'bytes_base64':'cHJvb2Y='}]}]}) as run,\
                 patch.object(sys,'argv',['review_queue.py','inspect','--decision-file',str(source)]):
                review_queue.main()
            run.assert_called_once_with(SKILL_SNAPSHOT,draft)
            self.assertEqual(list(root.glob('*.json')),[])

    def test_published_current_has_only_index_and_retains_two_approved_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            original_save=review_queue.save
            def save(path,value):
                if not path.is_relative_to(root):path=root/'receipt-projection.json'
                original_save(path,value)
            result=dict(success=True,applied=True,packages=[dict(path='alpha',exists=True,sha256='a'*64,entries=[])],
                        reviewed_skills={'alpha':dict(modules=['FS'],description='approved first')})
            row=dict(request_id='1'*64,decision=dict(id='skill:ab1234cd',decision='approve'),status='completed',created_at=1,completed_at=2,result=result)
            with patch.object(review_queue,'ROOT',root),patch.object(review_queue,'save',save):
                original_save(root/('1'*64+'.json'),row);review_queue.export_reviews()
                first=json.loads((root/'published-skills/index.json').read_text(encoding='utf-8'))
                row=copy.deepcopy(row);row.update(request_id='2'*64,completed_at=3)
                row['result']['reviewed_skills']['alpha']['description']='approved second'
                original_save(root/('2'*64+'.json'),row);review_queue.export_reviews()
                current=json.loads((root/'published-skills/index.json').read_text(encoding='utf-8'))
                self.assertNotEqual(first['sha256'],current['sha256'])
                self.assertEqual(len(list((root/'published-skills/versions').glob('*.json'))),2)
                self.assertEqual((root/'approved-skills.json').read_bytes(),(root/'published-skills/index.json').read_bytes())
                self.assertEqual(len(review_queue.receipts()),2)
                self.assertNotIn('backup',str(current));self.assertNotIn('decision',str(current))


if __name__=='__main__':unittest.main()
