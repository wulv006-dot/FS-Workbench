"""Focused boundary checks: scope, evidence fidelity, and unsafe report text."""
import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import daily_review
from daily_review import selected_native, normalized_content, validate, render, CATEGORIES


class ReviewBoundaryTests(unittest.TestCase):
    def test_pending_skills_are_input_data_and_index_only_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);profile=root/'profile';fs=root/'fs'
            for subsystem in ('memory','skills'):
                directory=profile/'pending'/subsystem;directory.mkdir(parents=True)
                record=dict(id='abc12345',payload=dict(action='batch',operations=[dict(action='write_file',name='method',file_path='scripts/check.py',file_content='proof')]))
                (directory/'abc12345.json').write_text(json.dumps(record),encoding='utf-8')
            directory=fs/'knowledge';directory.mkdir(parents=True)
            index=dict(contract='fs-hermes-reviewed-skills-v1',sha256='not-an-authority',items=[])
            (directory/'reviewed-skills.json').write_text(json.dumps(index),encoding='utf-8')
            sources=[];coverage={}
            original=daily_review.Path
            def redirected_path(value):
                return directory/'reviewed-skills.json' if str(value)=='/approved-skills/index.json' else original(value)
            with patch.object(daily_review,'PROFILE',profile),patch.object(daily_review,'FS',fs),\
                 patch.object(daily_review,'Path',redirected_path):
                daily_review.collect_pending_and_index(sources,coverage)
            self.assertEqual(coverage['memory_pending_count'],1)
            self.assertEqual(coverage['skills_pending_count'],1)
            self.assertEqual({s['kind'] for s in sources},{'pending_memory','pending_skill','reviewed_skill_index'})
            self.assertIn('scripts/check.py',next(s['content'] for s in sources if s['kind']=='pending_skill'))
            self.assertNotIn('approved',coverage)
            self.assertIn('观察值',daily_review.POLICY)

    def test_unauthorized_sessions_do_not_enter_review(self):
        self.assertTrue(selected_native('api_server', 'mine', {'mine': 'c1'}, {'f1'}))
        self.assertTrue(selected_native('feishu', 'f1', {'mine': 'c1'}, {'f1'}))
        for source, session in [('api_server','another_admin'), ('feishu','another_group'), ('desktop','mine')]:
            self.assertFalse(selected_native(source, session, {'mine':'c1'}, {'f1'}))

    def test_quotes_must_exist_in_actual_input(self):
        bundle = {'sources':[{'source_id':'message:7','content':'原答需要保留历史身份。'}]}
        row = dict(category=CATEGORIES[0], title='t', observation='o', proposal='p', scope='s', replaces='r', validation='v', quotes=[{'source_id':'message:7','quote':'保留历史身份'}])
        review = {'summary':'s','findings':[row]}
        self.assertIs(validate(review,bundle),review)
        for source, quote in [('message:8','保留历史身份'), ('message:7','已经写入永久记忆')]:
            row['quotes'] = [{'source_id':source,'quote':quote}]
            with self.assertRaises(ValueError):
                validate(review,bundle)

    def test_report_escapes_instructions_and_html(self):
        row = dict(category=CATEGORIES[0], title='<script>alert(1)</script>', observation='o', proposal='p', scope='s', replaces='r', validation='v', quotes=[{'source_id':'message:7','quote':'<img src=x onerror=1>'}])
        bundle = {'coverage':{'window_start':'2026-10-21T06:00:00+08:00','window_end_exclusive':'2026-10-22T06:00:00+08:00','messages':{'feishu:user':1},'skills_on_disk':77,'gaps':[]}, 'inventory':[]}
        md, page = render({'summary':'待审核','findings':[row]},bundle)
        self.assertIn('&lt;script&gt;',page)
        self.assertNotIn('<script>',page)
        self.assertNotIn('<img ',page)
        self.assertIn('default-src',page)
        self.assertIn('待审',md)
        self.assertEqual(normalized_content('[{"type":"text","text":"abc"},{"type":"image","text":"secret"}]'),'abc')


if __name__ == '__main__':
    unittest.main()
