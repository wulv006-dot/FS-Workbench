"""Local isolated publisher checks; no service changes, network or live targets."""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('news_cards_release',HERE.parent/'release_backend.py')
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
OWNER_CHECK=publisher.ownership


class ReleaseBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.stage=self.root/'stage'
        # Temporary runners may be non-root or beneath /tmp; production owner checks are tested separately.
        self.owner=patch.object(publisher,'ownership',lambda info:None);self.owner.start();self.addCleanup(self.owner.stop)
        self.unit=patch.object(publisher.subprocess,'run',return_value=SimpleNamespace(stdout='ActiveState=inactive\nMainPID=0\n'))
        self.command=self.unit.start();self.addCleanup(self.unit.stop)
        self.day=patch.object(publisher,'today',return_value='2026-10-16');self.day.start();self.addCleanup(self.day.stop)
        self.baseline=patch.object(publisher,'NEWS_BASELINE',sha256(b'old-news').hexdigest());self.baseline.start();self.addCleanup(self.baseline.stop)
        self.intel_baseline=patch.object(publisher,'INTEL_BASELINE',sha256(b'old-intel').hexdigest());self.intel_baseline.start();self.addCleanup(self.intel_baseline.stop)
        self.manifest={'schemaVersion':1,'scope':publisher.SCOPE,'releaseReady':True,'businessWrites':False,'timersChanged':False,'files':[],'unchangedRequired':[]}
        for name in ('/run/lock','/var/lib/fs-boss-workspaces/locks'):
            publisher.rooted(self.root,name).mkdir(parents=True)
        for rel,target in publisher.TARGETS.items():
            old=b'old-news' if 'mmoexp_news' in rel else b'old-intel'
            live=publisher.rooted(self.root,target);live.parent.mkdir(parents=True,exist_ok=True);live.write_bytes(old)
            source=self.stage/'candidate'/rel;source.parent.mkdir(parents=True,exist_ok=True);source.write_bytes(b'new-'+old)
            self.manifest['files'].append({'candidate':rel,'target':target,'beforeSha256':sha256(old).hexdigest(),'sha256':publisher.digest(source)})
        for name in sorted(publisher.REQUIRED):
            live=publisher.rooted(self.root,name);live.parent.mkdir(parents=True,exist_ok=True)
            if name==publisher.BOSS:
                fixture=Path(publisher.BOSS)
                if not fixture.is_file():fixture=next(p for p in [HERE.parents[1]/'fs_boss_workspaces_20261013/backend/boss_daily.py',HERE.parents[1]/'boss-workspaces-20261013/backend/boss_daily.py'] if p.is_file())
                live.write_bytes(fixture.read_bytes())
            else:live.write_bytes(b'protected')
            self.manifest['unchangedRequired'].append({'path':name,'sha256':publisher.digest(live)})
        self.release='news-cards-20261016T100000Z'

    def execute(self,manifest=None,release=None):
        manifest=manifest or self.manifest;raw=json.dumps(manifest).encode()
        return publisher.apply(manifest,self.stage,sha256(raw).hexdigest(),raw,release or self.release,self.root)

    def backup(self):return publisher.rooted(self.root,publisher.BACKUPS+'/'+self.release)
    def journal(self):return json.loads((self.backup()/'journal.json').read_bytes())

    def assert_original(self):
        for row in self.manifest['files']:self.assertEqual(publisher.digest(publisher.rooted(self.root,row['target'])),row['beforeSha256'])

    def test_inspect_has_no_publication_and_apply_rollback_are_exact(self):
        self.assertFalse(publisher.inspect(self.manifest,self.stage,self.root)['mutations'])
        result=self.execute();self.assertEqual(result['restarts'],0);self.assertEqual(self.journal()['status'],'applied')
        for row in self.manifest['files']:self.assertEqual(publisher.digest(publisher.rooted(self.root,row['target'])),row['sha256'])
        approval=sha256((self.backup()/'approved-manifest.json').read_bytes()).hexdigest()
        publisher.rollback(self.backup(),approval,self.root);self.assert_original()
        self.assertEqual(self.journal()['status'],'rolled-back')
        self.assertTrue(all(call.args[0][:2]==['systemctl','show'] for call in self.command.call_args_list))

    def test_allowlist_baselines_and_scope_are_mandatory(self):
        changes=[lambda m:m.update(scope='other'),lambda m:m['files'].pop(),
                 lambda m:m['files'].append(deepcopy(m['files'][0])),
                 lambda m:m['files'][0].update(target='/opt/other.py'),
                 lambda m:m['files'][1].update(beforeSha256=None),
                 lambda m:m['files'][0].update(beforeSha256='b'*64),
                 lambda m:m.update(businessWrites=True),lambda m:m.update(timersChanged=True)]
        for change in changes:
            manifest=deepcopy(self.manifest);change(manifest)
            with self.subTest(manifest=manifest),self.assertRaises(ValueError):publisher.validate(manifest)

    def test_protection_hashes_paths_and_duplicate_rows_are_checked(self):
        for row in self.manifest['unchangedRequired']:
            manifest=deepcopy(self.manifest);manifest['unchangedRequired'].remove(row)
            with self.assertRaises(ValueError):publisher.validate(manifest)
        for extra in ({'path':self.manifest['files'][0]['target'],'sha256':'a'*64},
                      {'path':'/opt/../etc/secret','sha256':'a'*64},self.manifest['unchangedRequired'][0]):
            manifest=deepcopy(self.manifest);manifest['unchangedRequired'].append(extra)
            with self.assertRaises(ValueError):publisher.validate(manifest)

    def test_target_source_and_protected_drift_stop_before_backup(self):
        paths=[publisher.rooted(self.root,self.manifest['files'][0]['target']),
               self.stage/'candidate'/self.manifest['files'][0]['candidate'],publisher.rooted(self.root,self.manifest['unchangedRequired'][-1]['path'])]
        for path in paths:
            before=path.read_bytes();path.write_bytes(b'drift')
            with self.subTest(path=path),self.assertRaises(ValueError):self.execute()
            self.assertFalse(self.backup().exists());path.write_bytes(before)

    def test_new_target_and_links_are_rejected(self):
        live=publisher.rooted(self.root,self.manifest['files'][0]['target']);payload=live.read_bytes();live.unlink()
        with self.assertRaises(ValueError):self.execute()
        live.write_bytes(payload)
        linked=self.root/'linked-source';linked.write_bytes(payload)
        live.unlink()
        try:live.symlink_to(linked)
        except OSError:
            original=type(live).is_symlink
            with patch.object(type(live),'is_symlink',lambda item:item==live or original(item)),self.assertRaises(ValueError):self.execute()
        else:
            with self.assertRaises(ValueError):self.execute()
            live.unlink()
        os.link(linked,live)
        with self.assertRaises(ValueError):self.execute()

    def test_root_ownership_and_writable_parents_rejected(self):
        with patch.object(publisher.os,'name','posix'):
            for uid,mode in ((1001,0o644),(0,0o666),(0,0o775)):
                with self.assertRaises(ValueError):OWNER_CHECK(SimpleNamespace(st_uid=uid,st_mode=mode))
            OWNER_CHECK(SimpleNamespace(st_uid=0,st_mode=0o644))

    def test_busy_service_and_shared_or_daily_lock_stop_before_writes(self):
        self.command.return_value.stdout='ActiveState=active\nMainPID=123\n'
        with self.assertRaises(ValueError):self.execute()
        self.assertFalse(self.backup().exists())
        self.command.return_value.stdout='ActiveState=inactive\nMainPID=0\n'
        with publisher.locks(self.manifest,self.root):
            with self.assertRaises((BlockingIOError,OSError)):self.execute()
        helper=publisher.rooted(self.root,publisher.BOSS)
        spec=importlib.util.spec_from_file_location('test_boss_daily_lock',helper)
        boss=importlib.util.module_from_spec(spec);spec.loader.exec_module(boss)
        daily=publisher.rooted(self.root,'/var/lib/fs-boss-workspaces/locks/game-monitor-2026-10-16.lock')
        with boss.file_lock(daily):
            with self.assertRaises((BlockingIOError,OSError)):self.execute()
        self.assertFalse(self.backup().exists());self.assert_original()

    def test_lock_is_followed_by_another_busy_state_check(self):
        self.command.side_effect=[SimpleNamespace(stdout='ActiveState=inactive\nMainPID=0\n'),SimpleNamespace(stdout='ActiveState=active\nMainPID=123\n')]
        with self.assertRaises(ValueError):self.execute()
        self.assertFalse(self.backup().exists());self.assert_original()

    def test_partial_failure_rolls_back_first_target(self):
        original=publisher.atomic;second=publisher.rooted(self.root,self.manifest['files'][1]['target']);failed=[]
        def fail(path,payload,mode=0o600):
            if path==second and not failed:failed.append(True);raise OSError('synthetic second replacement failure')
            return original(path,payload,mode)
        with patch.object(publisher,'atomic',side_effect=fail),self.assertRaises(OSError):self.execute()
        self.assert_original();self.assertEqual(self.journal()['status'],'rolled-back')

    def test_backup_failure_records_status_without_touching_targets(self):
        original=publisher.atomic
        def fail(path,payload,mode=0o600):
            if path==self.backup()/'mmoexp_news.py':raise OSError('synthetic backup failure')
            return original(path,payload,mode)
        with patch.object(publisher,'atomic',side_effect=fail),self.assertRaises(OSError):self.execute()
        self.assert_original();self.assertEqual(self.journal()['status'],'backup-failed-no-target-written')

    def test_rollback_rejects_changed_approval_or_journal_target(self):
        self.execute();approval=sha256((self.backup()/'approved-manifest.json').read_bytes()).hexdigest()
        with self.assertRaises(ValueError):publisher.rollback(self.backup(),'a'*64,self.root)
        journal=self.journal();journal['files'][0]['target']='/opt/unapproved.py';publisher.save(self.backup(),journal)
        with self.assertRaises(ValueError):publisher.rollback(self.backup(),approval,self.root)

    def test_failure_after_rename_uses_durable_intent_to_restore(self):
        original=publisher.atomic;first=publisher.rooted(self.root,self.manifest['files'][0]['target']);failed=[]
        def fail(path,payload,mode=0o600):
            original(path,payload,mode)
            if path==first and not failed:failed.append(True);raise OSError('synthetic fsync failure after rename')
        with patch.object(publisher,'atomic',side_effect=fail),self.assertRaises(OSError):self.execute()
        self.assert_original();self.assertEqual(self.journal()['status'],'rolled-back')
        self.assertTrue(self.journal()['files'][0]['intent'])

    def test_third_party_drift_is_preserved_and_not_overwritten_by_rollback(self):
        original=publisher.atomic;first=publisher.rooted(self.root,self.manifest['files'][0]['target'])
        second=publisher.rooted(self.root,self.manifest['files'][1]['target'])
        def fail(path,payload,mode=0o600):
            if path==second:first.write_bytes(b'third-party');raise OSError('synthetic concurrent write')
            return original(path,payload,mode)
        with patch.object(publisher,'atomic',side_effect=fail),self.assertRaises(RuntimeError):self.execute()
        self.assertEqual(first.read_bytes(),b'third-party');self.assertEqual(self.journal()['status'],'rollback-needs-reconciliation')

    def test_release_id_and_manifest_bytes_cannot_be_replayed_or_forged(self):
        with self.assertRaises(ValueError):self.execute(release='../other')
        raw=json.dumps(self.manifest).encode()
        with self.assertRaises(ValueError):publisher.apply(self.manifest,self.stage,'a'*64,raw,self.release,self.root)
        self.execute()
        # Restore baseline bytes to reach the unique-ID check without replaying a publication.
        for row in self.manifest['files']:
            publisher.rooted(self.root,row['target']).write_bytes((self.backup()/Path(row['candidate']).name).read_bytes())
        with self.assertRaises(ValueError):self.execute()

    def test_protection_and_day_change_inside_lock_are_rejected(self):
        original=publisher.locks;protected=publisher.rooted(self.root,self.manifest['unchangedRequired'][-1]['path'])
        @contextmanager
        def drift(manifest,root):
            with original(manifest,root) as day:
                protected.write_bytes(b'changed-under-lock');yield day
        with patch.object(publisher,'locks',drift),self.assertRaises(ValueError):self.execute()
        self.assertFalse(self.backup().exists());self.assert_original()
        protected.write_bytes(b'protected')
        with patch.object(publisher,'today',side_effect=['2026-10-16','2026-10-17']),self.assertRaises(ValueError):self.execute()
        self.assertFalse(self.backup().exists())


if __name__=='__main__':unittest.main()
