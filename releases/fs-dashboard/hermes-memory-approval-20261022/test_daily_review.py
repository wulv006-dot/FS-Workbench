"""Focused boundary checks: scope, evidence fidelity, and unsafe report text."""
import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
try:
    ZoneInfo('Asia/Shanghai')
except ZoneInfoNotFoundError:
    # This offline suite uses 2026 Shanghai fixtures, which have fixed UTC+08.
    # Production still requires actual tzdata; Linux CI exercises its real ZoneInfo.
    with patch('zoneinfo.ZoneInfo',return_value=timezone(timedelta(hours=8))):
        import daily_review
    print('Daily review fixture: tzdata absent; explicit 2026 UTC+08 test clock')
else:
    import daily_review
from daily_review import selected_native, normalized_content, validate, render, CATEGORIES


class ReviewBoundaryTests(unittest.TestCase):
    def test_native_pending_projection_requires_original_record_and_owner(self):
        import hashlib
        self.assertTrue(callable(getattr(daily_review,'collect_native_pending',None)), 'native daily consumer is missing')
        owner='wulv';key=hashlib.sha256(owner.encode()).hexdigest()
        record=dict(id='ab1234cd',subsystem='memory',action='add',summary='preference',origin='tool',created_at=1,
                    payload=dict(action='add',target='user',content='Prefer Chinese'))
        sha=hashlib.sha256(json.dumps(record,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        source=dict(owner=owner,cid='cid',turn_id='turn',session_id='session',run_id='run',lease='lease',profile_key=key,
                    subsystem='memory',pending_id='ab1234cd',record_sha256=sha)
        item=dict(id='native:ab1234cd',record=record,sha256=sha,native_source=source)
        snapshot=dict(owner=owner,profile_root='/var/lib/fs-hermes-fc/native/profiles/'+key,native=[item],skills=[],
                      unmapped=[dict(id='skill:deadbeef',status='unmapped_pending')])
        sources=[];coverage={}
        daily_review.collect_native_pending(snapshot,sources,coverage)
        self.assertEqual(len(sources),1)
        self.assertEqual(coverage['native_unmapped_pending'],1)
        self.assertEqual(sources[0]['kind'],'pending_memory')
        self.assertIn('Prefer Chinese',sources[0]['content'])
        self.assertNotIn('approved',coverage)
        for changed in (dict(snapshot,owner='bob'),dict(snapshot,native=[dict(item,sha256='0'*64)])):
            with self.assertRaises(ValueError):daily_review.collect_native_pending(changed,[],{})

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
