import base64
import copy
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import hermes_review_archive as archive
import knowledge_closeout as closeout


def fixture(kind='native', target='memory'):
    record = dict(payload=dict(target=target, content='PRIVATE ORIGINAL NEVER EXPORT'))
    candidate = dict(record=record, sha256=archive.digest(record))
    decision = dict(id=kind + ':' + ('a' * (64 if kind == 'experience' else 8)), decision='approve',
                    expected_sha=candidate['sha256'], target_sha='b' * 64)
    row = dict(request_id=archive.digest(decision), decision=decision, candidate=candidate,
               status='completed', result=dict(success=True, applied=True))
    return row


def snapshot(row):
    raw = json.dumps(row).encode()
    return dict(contract=archive.CONTRACT, receipts=[dict(receipt=row, receipt_sha256=archive.sha(raw),
                receipt_bytes_base64=base64.b64encode(raw).decode())])


def selection(source):
    item = source['receipts'][0]
    return dict(request_id=item['receipt']['request_id'], receipt_sha256=item['receipt_sha256'],
                disposition='summary_only', summary='已审应用；私人正文保留受控原档。',
                evidence='原审批回执与候选哈希已核对。', modules=['FS'], privacy_reviewed=True, rule_change=False)


def skill_source():
    row = fixture('skill')
    raw = b'# Example\nRead only method.\n'
    entries = [dict(path='.', kind='directory', mode=448, uid=0, gid=0),
               dict(path='SKILL.md', kind='file', mode=384, uid=0, gid=0,
                    bytes=len(raw), sha256=archive.sha(raw)),
               dict(path='empty.txt', kind='file', mode=384, uid=0, gid=0, bytes=0, sha256=archive.sha(b'')),
               dict(path='scripts', kind='directory', mode=448, uid=0, gid=0),
               dict(path='scripts/helper.py', kind='file', mode=448, uid=0, gid=0,
                    bytes=5, sha256=archive.sha(b'pass\n'))]
    pkg = dict(path='example', exists=True, entries=entries)
    pkg['sha256'] = archive.digest(pkg)
    row['result']['packages'] = [copy.deepcopy(pkg)]
    source = snapshot(row)
    pkg['entries'][1]['bytes_base64'] = base64.b64encode(raw).decode()
    pkg['entries'][2]['bytes_base64'] = ''
    pkg['entries'][4]['bytes_base64'] = base64.b64encode(b'pass\n').decode()
    source['receipts'][0]['packages'] = [pkg]
    chosen = dict(selection(source), disposition='reusable')
    return source, chosen


class ArchiveTests(unittest.TestCase):
    def test_private_memory_never_copies_candidate_or_backup(self):
        source = snapshot(fixture())
        files = archive.render(source, [selection(source)])
        self.assertEqual(len(files), 1)
        self.assertNotIn('PRIVATE ORIGINAL', str(files))
        self.assertNotIn('bytes_base64', str(files))

    def test_revoke_applied_true_is_never_approval(self):
        row = fixture('experience')
        row['decision']['decision'] = 'reject'
        source = snapshot(row)
        with self.assertRaisesRegex(ValueError, 'original_completed_approval'):
            archive.render(source, [selection(source)])

    def test_pending_unknown_blocked_and_not_applied_do_not_export(self):
        for state in ('applying', 'unknown_inspect_before_retry', 'blocked_not_applied'):
            row = fixture()
            row['status'] = state
            source = snapshot(row)
            with self.assertRaises(ValueError): archive.render(source, [selection(source)])
        row = fixture()
        row['result']['applied'] = False
        source = snapshot(row)
        with self.assertRaises(ValueError): archive.render(source, [selection(source)])

    def test_source_decision_and_candidate_tampering_rejected(self):
        source = snapshot(fixture())
        source['receipts'][0]['receipt']['candidate']['record']['payload']['content'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'source_receipt_bytes_changed'):
            archive.render(source, [selection(source)])
        row = fixture()
        row['candidate']['sha256'] = 'c' * 64
        source = snapshot(row)
        with self.assertRaisesRegex(ValueError, 'original_candidate_changed'):
            archive.render(source, [selection(source)])

    def test_private_profile_and_formal_rule_need_separate_scope(self):
        source = snapshot(fixture(target='user'))
        chosen = dict(selection(source), disposition='reusable', content='candidate')
        with self.assertRaisesRegex(PermissionError, 'private_user_profile'):
            archive.render(source, [chosen])
        chosen = dict(selection(source), rule_change=True)
        with self.assertRaises(PermissionError): archive.render(source, [chosen])

    def test_disclosure_filter_and_duplicate_source(self):
        for text in ('email: person@example.com', 'password=secretvalue', '/profile/private', '10.0.0.1'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'possible_private'):
                archive.safe_text(text)
        source = snapshot(fixture())
        source['receipts'] *= 2
        with self.assertRaisesRegex(ValueError, 'duplicate_source'):
            archive.render(source, [selection(source)])

    def test_exact_reviewed_path_reference_preserves_bytes_and_cannot_allow_secrets(self):
        raw = b'# Example\nSource /profile/evidence on 127.0.0.1; read only.\n'
        def source_with(raw):
            source, chosen = skill_source()
            row = source['receipts'][0]['receipt']
            pkg = source['receipts'][0]['packages'][0]
            entry = pkg['entries'][1]
            entry.update(bytes=len(raw), sha256=archive.sha(raw), bytes_base64=base64.b64encode(raw).decode())
            expected = dict(pkg, entries=[{k:v for k,v in e.items() if k != 'bytes_base64'} for e in pkg['entries']])
            expected['sha256'] = archive.digest({k:v for k,v in expected.items() if k != 'sha256'})
            pkg['sha256'] = expected['sha256']
            row['result']['packages'] = [expected]
            original = json.dumps(row).encode()
            source['receipts'][0].update(receipt_sha256=archive.sha(original), receipt_bytes_base64=base64.b64encode(original).decode())
            chosen['receipt_sha256'] = archive.sha(original)
            chosen['reference_exports'] = dict(source='direct_user', message_reference='explicit file/hash/reference export approval', files={
                'example/SKILL.md':dict(sha256=archive.sha(raw), values=['/profile/', '127.0.0.1'])})
            return source, chosen
        source, chosen = source_with(raw)
        files = archive.render(source, [chosen])
        self.assertEqual(next(v for k,v in files.items() if k.endswith('SKILL.md')).encode(), raw)
        metadata = json.loads(next(v for k,v in files.items() if k.endswith('record.json')))
        self.assertEqual(metadata['reference_exports'], chosen['reference_exports'])
        for mutate in ('hash', 'missing', 'authority', 'secret'):
            source, chosen = source_with(raw)
            if mutate == 'hash': chosen['reference_exports']['files']['example/SKILL.md']['sha256'] = '0'*64
            if mutate == 'missing': del chosen['reference_exports']
            if mutate == 'authority': chosen['reference_exports']['source'] = 'model'
            if mutate == 'secret':
                source, chosen = source_with(raw + b'password=secretvalue\n')
                chosen['reference_exports']['files']['example/SKILL.md']['values'].append('password=secretvalue')
            with self.subTest(mutate=mutate), self.assertRaises((ValueError, PermissionError)):
                archive.render(source, [chosen])

    def test_reference_metadata_cannot_smuggle_private_text_or_unused_files(self):
        for mutate in ('message', 'unused_file'):
            source, chosen = skill_source()
            chosen['reference_exports'] = dict(source='direct_user', message_reference='approved', files={})
            if mutate == 'message': chosen['reference_exports']['message_reference'] = 'password=secretvalue'
            else: chosen['reference_exports']['files']['unused.txt'] = dict(sha256='0'*64, values=['/profile/'])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                archive.render(source, [chosen])

    def test_complete_skill_bytes_and_mode_preserved(self):
        source, chosen = skill_source()
        files = archive.render(source, [chosen])
        self.assertEqual(len(files), 4)
        self.assertIn('# Example\n', next(v for k, v in files.items() if k.endswith('SKILL.md')))
        metadata = json.loads(next(v for k, v in files.items() if k.endswith('record.json')))
        self.assertEqual(metadata['packages'][0]['files'][0]['mode'], 384)
        self.assertEqual(metadata['packages'][0]['files'][2]['mode'], 448)
        self.assertEqual(next(v for k, v in files.items() if k.endswith('empty.txt')), '')

    def test_changed_or_missing_package_cannot_be_backfilled(self):
        for change in ('missing', 'bytes', 'manifest', 'path'):
            source, chosen = skill_source()
            pkg = source['receipts'][0]['packages'][0]
            if change == 'missing': source['receipts'][0]['packages'] = []
            if change == 'bytes': pkg['entries'][1]['bytes_base64'] = 'YmFk'
            if change == 'manifest': pkg['sha256'] = 'f' * 64
            if change == 'path': pkg['path'] = '../escape'
            with self.subTest(change=change), self.assertRaises(ValueError):
                archive.render(source, [chosen])

    def test_prepare_reuses_closeout_and_never_creates_publish_step(self):
        source = snapshot(fixture())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'knowledge').mkdir()
            (root / 'knowledge/index.json').write_text('{"entries":[]}', encoding='utf-8')
            with patch.object(closeout.subprocess, 'check_output', return_value='a' * 40):
                first = archive.prepare(root, 'b' * 40, source, [selection(source)])
                second = archive.prepare(root, 'b' * 40, source, [selection(source)])
            self.assertEqual(first['plan'], second['plan'])
            self.assertEqual(second['changed'], [])
            self.assertEqual(first['plan']['steps'], ['git_version', 'notion_sync'])
            self.assertFalse(first['plan']['production_confirmation_required'])
            with closing(closeout.connect(root / 'ledger.sqlite3')) as db:
                key = closeout.register(db, first['plan'])
                closeout.approve(db, key, dict(plan_sha256=first['plan']['plan_sha256'], source='direct_user',
                                 message_reference='offline authorized archival fixture', actions=first['plan']['steps']))
                operation = closeout.begin(db, key, 'git_version')
                closeout.record(db, key, 'git_version', dict(status='unknown', operation_id=operation))
                with self.assertRaises(PermissionError): closeout.begin(db, key, 'git_version')
                closeout.record(db, key, 'git_version', dict(status='completed', operation_id=operation,
                                readback='same original merge', evidence='fixture', scope_verified=True))
                self.assertEqual(closeout.next_step(db, key)['name'], 'notion_sync')

    def test_immutable_archive_conflict_never_overwrites_prior(self):
        source = snapshot(fixture())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'knowledge').mkdir()
            (root / 'knowledge/index.json').write_text('{"entries":[]}', encoding='utf-8')
            with patch.object(closeout.subprocess, 'check_output', return_value='a' * 40):
                archive.prepare(root, 'b' * 40, source, [selection(source)])
                chosen = dict(selection(source), summary='Changed later summary')
                with self.assertRaisesRegex(ValueError, 'immutable_archive_conflict'):
                    archive.prepare(root, 'b' * 40, source, [chosen])

    def test_source_reads_rejected_receipts_without_application_and_keeps_package_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rejected = fixture()
            rejected['decision']['decision'] = 'reject'
            skill = fixture('skill')
            skill['result']['packages'] = [dict(path='example')]
            for i, row in enumerate((rejected, skill)):
                (root / (str(i) * 64 + '.json')).write_text(json.dumps(row), encoding='utf-8')
            (root / 'not-a-receipt.json').write_text('{}', encoding='utf-8')
            queue = SimpleNamespace(ROOT=root, run=lambda *a: (_ for _ in ()).throw(ValueError('unsafe_package')))
            with patch.dict(sys.modules, review_queue=queue):
                result = archive.collect()
            self.assertEqual(len(result['receipts']), 2)
            self.assertNotIn('collection_error', result['receipts'][0])
            self.assertEqual(result['receipts'][1]['collection_error'], 'ValueError')

    def test_same_requests_resume_original_plan_across_workspace_head_changes(self):
        source = snapshot(fixture())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'knowledge').mkdir()
            (root / 'knowledge/index.json').write_text('{"entries":[]}', encoding='utf-8')
            input_path, selection_path = root / 'input.json', root / 'selection.json'
            input_path.write_text(json.dumps(source), encoding='utf-8')
            selection_path.write_text(json.dumps([selection(source)]), encoding='utf-8')
            args = ['archive', 'prepare', '--snapshot', str(input_path), '--selections', str(selection_path),
                    '--base', 'b' * 40, '--ledger', str(root / 'stable.sqlite3')]
            with patch.object(closeout, 'ROOT', root), patch.object(sys, 'argv', args), patch('builtins.print'), \
                    patch.object(closeout.subprocess, 'check_output', side_effect=['a' * 40, 'c' * 40]):
                archive.main()
                archive.main()
            with closing(closeout.connect(root / 'stable.sqlite3')) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
