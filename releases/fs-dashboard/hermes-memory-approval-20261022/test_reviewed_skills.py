"""Offline boundary fixtures; native application is called, never reimplemented by the adapter."""
import base64
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import reviewed_skills as skills


class IsolationReleaseTests(unittest.TestCase):
    def test_release_accepts_only_existing_identical_helper_copies(self):
        import reviewed_skill_isolation_release as release
        manifest = dict(businessWrites=False, timersChanged=False,
                        files=[dict(candidate=name, target=target, beforeSha256='a' * 64, sha256='b' * 64)
                               for name, target in release.TARGETS.items()])
        self.assertEqual(release.targets(manifest), release.TARGETS)
        for changed in (dict(beforeSha256=None), dict(sha256='c' * 64),
                        dict(target='/var/lib/fs-hermes-fc/profile/skills/SKILL.md')):
            wrong = copy.deepcopy(manifest)
            wrong['files'][0].update(changed)
            with self.assertRaisesRegex(ValueError, 'exact_reviewed_skill_isolation_targets'):
                release.targets(wrong)


class SkillReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root/'alpha'
        self.path.mkdir()
        (self.path/'SKILL.md').write_text('method v1',encoding='utf-8')
        (self.path/'scripts').mkdir()
        (self.path/'scripts/tool.py').write_bytes(b'print(1)\n')
        (self.path/'assets').mkdir()
        (self.path/'assets/icon.bin').write_bytes(b'\x00\xff\x01')
        self.locked = False
        self.calls = []
        @contextmanager
        def locks(names):
            self.locked = True
            try: yield
            finally: self.locked = False
        self.manager = SimpleNamespace(
            _skills_dir=lambda:self.root,
            _resolve_skill_dir=lambda name,category=None:self.root/(category or '')/name,
            _find_skill=lambda name:dict(path=self.root/name) if (self.root/name/'SKILL.md').exists() else None,
            _skill_mutation_locks=locks,apply_skill_pending=self.native)
        self.record = dict(id='ab1234cd',subsystem='skills',payload=dict(action='edit',name='alpha',content='method v2'))
        self.pending = copy.deepcopy(self.record)
        def discard(subsystem,key):
            self.assertEqual((subsystem,key),('skills','ab1234cd'))
            self.pending = None
            return True
        self.approval=SimpleNamespace(SKILLS='skills',get_pending=lambda subsystem,key:self.pending,discard_pending=discard)
        self.checked = patch.object(skills,'checked_native')
        self.checked.start()
        self.addCleanup(self.checked.stop)

    def native(self,payload):
        self.assertTrue(self.locked)
        self.calls.append(copy.deepcopy(payload))
        for op in payload.get('operations') or [payload]:
            target=self.root/(op.get('category') or '')/op['name']
            if op['action']=='create':
                target.mkdir(parents=True)
                (target/'SKILL.md').write_text(op['content'],encoding='utf-8')
            elif op['action']=='edit':
                (target/'SKILL.md').write_text(op['content'],encoding='utf-8')
            elif op['action']=='write_file':
                file=target/op['file_path'];file.parent.mkdir(parents=True,exist_ok=True)
                file.write_text(op['file_content'],encoding='utf-8')
            elif op['action']=='remove_file':
                (target/op['file_path']).unlink()
            elif op['action']=='delete':
                shutil.rmtree(target)
        return json.dumps(dict(success=True))

    def decision(self,payload=None,decision='approve'):
        if payload is not None:
            self.record['payload']=payload
            self.pending=copy.deepcopy(self.record)
        candidate=skills.skill_candidate(self.record,self.manager)
        data=dict(id=candidate['id'],expected_sha=candidate['sha256'],target_sha=candidate['target_sha256'],decision=decision)
        if decision=='approve' and 'target' in candidate:
            deleted={candidate['target']['targets'][op['name']] for op in skills.operations(self.record['payload']) if op['action']=='delete'}
            data['reviewed_skills']={p:dict(modules=['fc27'],description='Use for verified reporting.')
                                     for p in set(candidate['target']['targets'].values())-deleted}
        return data

    def receipt(self,result):
        return dict(request_id='1'*64,decision=dict(id='skill:ab1234cd',decision='approve'),
                    status='completed',created_at=1,completed_at=2,result=result)

    def test_complete_backup_covers_binary_support_files_and_modes(self):
        before=skills.target_snapshot(self.record['payload'],self.manager,backup=True)
        rows=before['snapshots'][0]['entries']
        binary=next(r for r in rows if r['path']=='assets/icon.bin')
        self.assertEqual(base64.b64decode(binary['bytes_base64']),b'\x00\xff\x01')
        self.assertIn('mode',binary);self.assertIn('uid',binary);self.assertIn('gid',binary)
        self.assertEqual(before['sha256'],skills.target_snapshot(self.record['payload'],self.manager)['sha256'])

    def test_create_and_multifile_batch_uses_exact_native_payload(self):
        payload=dict(action='batch',operations=[dict(action='create',name='beta',content='new method'),
                    dict(action='write_file',name='beta',file_path='scripts/check.py',file_content='assert 1'),
                    dict(action='write_file',name='beta',file_path='references/source.md',file_content='proof')])
        result=skills.apply_review(self.decision(payload),self.manager,self.approval)
        self.assertTrue(result['applied']);self.assertEqual(self.calls,[payload]);self.assertIsNone(self.pending)
        self.assertTrue((self.root/'beta/scripts/check.py').exists())
        self.assertEqual(set(result['reviewed_skills']),{'beta'})

    def test_edit_approve_preserves_unmodified_files_and_indexes_exact_package(self):
        result=skills.apply_review(self.decision(),self.manager,self.approval)
        self.assertEqual((self.path/'SKILL.md').read_text(),'method v2')
        self.assertEqual((self.path/'assets/icon.bin').read_bytes(),b'\x00\xff\x01')
        index=skills.approved_index([self.receipt(result)])
        self.assertEqual(index['items'][0]['package_sha256'],skills.package(self.root,'alpha')['sha256'])
        self.assertEqual(index['items'][0]['candidate_id'],'skill:ab1234cd')

    def test_hermes_managed_skill_is_outside_fs_projection_and_package_checks(self):
        managed = 'fs-operations/fs-business-context-rulings'
        active = self.root / managed
        active.mkdir(parents=True)
        (active / 'SKILL.md').write_text('Hermes-owned method', encoding='utf-8')
        other = skills.apply_review(self.decision(), self.manager, self.approval)
        managed_package = skills.package(self.root, managed)
        receipt = self.receipt(other)
        prior = skills.approved_index([receipt])
        prior['items'].append(dict(id=managed, sha256=managed_package['sha256'],
            package_sha256=managed_package['sha256'], files=managed_package['entries'],
            modules=['FS', 'FC', 'RPG'], review_request_id='old-review'))
        prior['sha256'] = skills.digest({k: v for k, v in prior.items() if k != 'sha256'})
        index_path = self.root / 'index.json'
        index_path.write_text(json.dumps(prior), encoding='utf-8')
        archive = self.root / '.archive' / active.name
        archive.parent.mkdir()
        active.rename(archive)

        listing = skills.list_reviewed(self.root, index_path, ['FC27', 'FS'],
                                       expected_index_sha=prior['sha256'])
        self.assertEqual([row['id'] for row in listing['items']], ['alpha'])
        self.assertEqual(skills.read_reviewed_skill(self.root, index_path, ['FC27', 'FS'],
            'alpha', prior['items'][0]['sha256'], expected_index_sha=prior['sha256'])['content'], 'method v2')
        self.assertEqual((archive / 'SKILL.md').read_text(encoding='utf-8'), 'Hermes-owned method')

        previous = dict(receipt, result=dict(other, packages=[*other['packages'], managed_package],
            reviewed_skills={**other['reviewed_skills'], managed: dict(modules=['FS'], description='Hermes')}))
        self.assertEqual(skills.approved_index([previous])['items'], prior['items'][:1])
        (self.path / 'SKILL.md').write_text('unaudited edit', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'reviewed_skill_package_changed'):
            skills.list_reviewed(self.root, index_path, ['FC27', 'FS'], expected_index_sha=prior['sha256'])

    def test_delete_full_package_is_backed_up_and_removes_only_approved_index_item(self):
        edit=skills.apply_review(self.decision(),self.manager,self.approval)
        old=self.receipt(edit)
        payload=dict(action='delete',name='alpha')
        data=self.decision(payload)
        backup=skills.target_snapshot(payload,self.manager,backup=True)
        deleted=skills.apply_review(data,self.manager,self.approval)
        current=self.receipt(deleted);current.update(request_id='2'*64,completed_at=3)
        self.assertFalse(self.path.exists())
        self.assertEqual(len([r for r in backup['snapshots'][0]['entries'] if r['kind']=='file']),3)
        self.assertEqual(skills.approved_index([old,current])['items'],[])

    def test_remove_support_file_routes_native_without_narrowing_other_files(self):
        data=self.decision(dict(action='remove_file',name='alpha',file_path='scripts/tool.py'))
        result=skills.apply_review(data,self.manager,self.approval)
        self.assertTrue(result['success']);self.assertFalse((self.path/'scripts/tool.py').exists())
        self.assertTrue((self.path/'assets/icon.bin').exists())

    def test_path_traversal_absolute_and_unsafe_category_never_apply(self):
        for path in ('../escape','/etc/passwd','scripts/../../x','scripts\\x','a//b'):
            candidate=skills.skill_candidate(dict(self.record,payload=dict(action='write_file',name='alpha',file_path=path)),self.manager)
            self.assertIn('validation_error',candidate)
        for name in ('../alpha','/alpha','a/b/c','Alpha'):
            candidate=skills.skill_candidate(dict(self.record,payload=dict(action='delete',name=name)),self.manager)
            self.assertIn('validation_error',candidate)
        self.assertEqual(self.calls,[])

    def test_symlink_anywhere_in_complete_package_is_refused(self):
        link=self.path/'assets/redirect'
        try: link.symlink_to(self.root/'other')
        except OSError as error: self.skipTest('host cannot create symlinks: '+str(error))
        with self.assertRaisesRegex(ValueError,'skill_nonregular_entry'):
            skills.package(self.root,'alpha')

    def test_nonregular_entry_branch_is_checked_without_host_symlink_privilege(self):
        original=Path.lstat
        def lstat(path,*args,**kwargs):
            if path == self.path/'assets/icon.bin':
                info=original(path,*args,**kwargs)
                return type(info)((stat.S_IFLNK | 0o777,*tuple(info)[1:]))
            return original(path,*args,**kwargs)
        with patch.object(Path,'lstat',lstat):
            with self.assertRaisesRegex(ValueError,'skill_nonregular_entry'):
                skills.package(self.root,'alpha')

    def test_changed_candidate_or_support_file_blocks_cas(self):
        data=self.decision()
        self.pending['payload']['content']='unreviewed'
        with self.assertRaisesRegex(ValueError,'candidate_changed'):
            skills.apply_review(data,self.manager,self.approval)
        self.pending=copy.deepcopy(self.record)
        (self.path/'assets/icon.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'skill_target_changed'):
            skills.apply_review(data,self.manager,self.approval)
        self.assertEqual(self.calls,[])

    def test_candidate_changed_while_waiting_for_native_locks_is_rechecked(self):
        data=self.decision()
        @contextmanager
        def locks(names):
            self.pending['payload']['content']='arrived while waiting'
            yield
        self.manager._skill_mutation_locks=locks
        with self.assertRaisesRegex(ValueError,'candidate_changed'):
            skills.apply_review(data,self.manager,self.approval)
        self.assertEqual(self.calls,[])

    def test_reject_keeps_original_package_and_uses_no_native_write(self):
        data=self.decision(decision='reject');before=skills.package(self.root,'alpha')
        result=skills.apply_review(data,self.manager,self.approval)
        self.assertTrue(result['rejected']);self.assertIsNone(self.pending);self.assertEqual(self.calls,[])
        self.assertEqual(before,skills.package(self.root,'alpha'))

    def test_invalid_candidate_can_be_rejected_without_following_unsafe_target(self):
        data=self.decision(dict(action='delete',name='../outside'),decision='reject')
        self.assertTrue(skills.apply_review(data,self.manager,self.approval)['rejected'])
        self.assertEqual(self.calls,[])

    def test_native_failure_retains_pending_and_does_not_publish(self):
        self.manager.apply_skill_pending=lambda payload:json.dumps(dict(success=False,error='native guard failed'))
        result=skills.apply_review(self.decision(),self.manager,self.approval)
        self.assertFalse(result['applied']);self.assertIsNotNone(self.pending)
        row=self.receipt(result);row['status']='blocked_not_applied'
        self.assertEqual(skills.approved_index([row])['items'],[])

    def test_partial_write_or_cleanup_failure_is_unknown_not_replayed(self):
        original=self.manager.apply_skill_pending
        def broken(payload):
            original(payload)
            return json.dumps(dict(success=False,error='failed after mutation'))
        self.manager.apply_skill_pending=broken
        with self.assertRaisesRegex(RuntimeError,'failure_with_changes'):
            skills.apply_review(self.decision(),self.manager,self.approval)
        self.assertIsNotNone(self.pending)

    def test_cleanup_failure_preserves_pending_and_never_exports_approval(self):
        data=self.decision()
        self.approval.discard_pending=lambda subsystem,key:False
        with self.assertRaisesRegex(RuntimeError,'cleanup_failed'):
            skills.apply_review(data,self.manager,self.approval)
        self.assertEqual((self.path/'SKILL.md').read_text(),'method v2')
        self.assertIsNotNone(self.pending)

    def test_index_requires_external_hash_and_module_then_verifies_entire_package(self):
        result=skills.apply_review(self.decision(),self.manager,self.approval)
        index=skills.approved_index([self.receipt(result)]);path=self.root/'reviewed.json'
        path.write_text(json.dumps(index),encoding='utf-8')
        listing=skills.list_reviewed(self.root,path,['FC27'],expected_index_sha=index['sha256'])
        item=listing['items'][0]
        read=skills.read_reviewed_skill(self.root,path,['fc27'],'alpha',item['sha256'],expected_index_sha=index['sha256'])
        self.assertEqual(read['content'],'method v2')
        self.assertEqual(skills.list_reviewed(self.root,path,['rpg'],expected_index_sha=index['sha256'])['items'],[])
        with self.assertRaisesRegex(ValueError,'index_changed'):
            skills.list_reviewed(self.root,path,['fc27'],expected_index_sha='0'*64)
        (self.path/'scripts/tool.py').write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'package_changed'):
            skills.list_reviewed(self.root,path,['fc27'],expected_index_sha=index['sha256'])

    def test_unknown_or_rejected_receipt_never_becomes_reviewed(self):
        result=skills.apply_review(self.decision(),self.manager,self.approval)
        row=self.receipt(result);row['status']='unknown_inspect_before_retry'
        self.assertEqual(skills.approved_index([row])['items'],[])
        self.assertTrue(skills.list_reviewed(self.root,self.root/'missing.json',['fc27'],expected_index_sha=None)['missing'])

    def test_current_catalog_uses_trusted_current_and_preserves_prior_task_snapshot(self):
        result=skills.apply_review(self.decision(),self.manager,self.approval)
        first=skills.approved_index([self.receipt(result)])
        published=self.root/'published';published.mkdir()
        path=published/'index.json';path.write_text(json.dumps(first),encoding='utf-8')
        original_lstat=Path.lstat;original_fstat=os.fstat
        trusted={published,*published.parents,path}
        def trusted_stat(info):
            mode=(stat.S_IFDIR | 0o700) if stat.S_ISDIR(info.st_mode) else (stat.S_IFREG | 0o600)
            values=list(info);values[0]=mode;values[4]=0;values[5]=0
            return type(info)(values)
        def lstat(value,*args,**kwargs):
            info=original_lstat(value,*args,**kwargs)
            return trusted_stat(info) if value in trusted else info
        with patch.object(skills,'PUBLISHED_ROOTS',(str(published),)),patch.object(Path,'lstat',lstat),\
             patch.object(os,'fstat',lambda fd:trusted_stat(original_fstat(fd))):
            frozen=skills.current_catalog(self.root,published,['FC27'])
            self.assertEqual(frozen['sha256'],first['sha256'])
            updated=copy.deepcopy(first);updated['items'][0]['description']='reviewed next revision'
            updated['sha256']=skills.digest({k:v for k,v in updated.items() if k!='sha256'})
            path.write_text(json.dumps(updated),encoding='utf-8')
            following=skills.current_catalog(self.root,published,['fc27'])
            self.assertNotEqual(following['sha256'],frozen['sha256'])
            self.assertEqual(frozen['items'][0]['description'],'Use for verified reporting.')
        with self.assertRaisesRegex(ValueError,'untrusted_reviewed_skill_root'):
            skills.current_catalog(self.root,self.root,['fc27'])

    def test_current_catalog_refuses_writable_or_unowned_root_before_read(self):
        published=self.root/'published';published.mkdir()
        original=Path.lstat
        def writable(path,*args,**kwargs):
            info=original(path,*args,**kwargs)
            if path==published:
                values=list(info);values[0]=stat.S_IFDIR|0o777
                return type(info)(values)
            return info
        with patch.object(skills,'PUBLISHED_ROOTS',(str(published),)),patch.object(Path,'lstat',writable):
            with self.assertRaisesRegex(ValueError,'untrusted_reviewed_skill_directory'):
                skills.current_catalog(self.root,published,['fc27'])


if __name__=='__main__': unittest.main()
