import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'source'), str(ROOT.parent/'hermes-ops-20261020/source')]
import controller
import publication


class Recovery(unittest.TestCase):
    def fixture(self, root, activated=False):
        stage=root/'stage';stage.mkdir()
        raw=json.dumps({'releaseId':'release'}).encode()
        (stage/'release-manifest.json').write_bytes(raw)
        backup=root/'backups/release';backup.mkdir(parents=True)
        (backup/'approved-manifest.json').write_bytes(raw)
        (backup/'journal.json').write_text(json.dumps(dict(
            status='rolled-back-immutable-history-retained', activationAttempted=activated,
            approvedManifestSha256=publication.sha(raw), failure='read-only nginx')))
        page=root/'live.html';page.write_bytes(b'original')
        return stage,backup,page

    def test_verified_rollback_is_terminal_without_replay(self):
        record=dict(status='publishing_unknown',run_id='old',publication={'stage':'/old/stage'},proof={'before_sha256':'before'})
        result=dict(status='rolled_back_verified',failure='read-only nginx')
        with patch.object(publication,'verify',side_effect=ValueError('not published')), patch.object(publication,'verify_rollback',return_value=result,create=True), patch.object(controller,'save'), patch.object(controller.subprocess,'run') as run:
            controller.step(record)
        self.assertEqual(record['status'],'rolled_back_verified')
        self.assertIn('rolled_back_verified',controller.TERMINAL)
        self.assertEqual(record['rollback_readback'],result)
        run.assert_not_called()

    def test_original_journal_and_live_bytes_prove_no_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stage,backup,page=self.fixture(root)
            with patch.object(publication,'BACKUPS',root/'backups',create=True), patch.object(publication,'active',return_value=page):
                result=publication.verify_rollback(stage,publication.sha(b'original'))
            self.assertEqual(result['status'],'rolled_back_verified')
            self.assertEqual(result['backup'],str(backup))

    def test_attempted_activation_cannot_be_reclassified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stage,_,page=self.fixture(root,True)
            with patch.object(publication,'BACKUPS',root/'backups',create=True), patch.object(publication,'active',return_value=page), self.assertRaisesRegex(ValueError,'rollback_not_proven'):
                publication.verify_rollback(stage,publication.sha(b'original'))

    def test_changed_live_page_keeps_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stage,_,page=self.fixture(root)
            page.write_bytes(b'changed')
            with patch.object(publication,'BACKUPS',root/'backups',create=True), patch.object(publication,'active',return_value=page), self.assertRaisesRegex(ValueError,'rollback_live_drift'):
                publication.verify_rollback(stage,publication.sha(b'original'))

    def test_changed_approved_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stage,backup,page=self.fixture(root)
            (backup/'approved-manifest.json').write_bytes(b'changed')
            with patch.object(publication,'BACKUPS',root/'backups',create=True), patch.object(publication,'active',return_value=page), self.assertRaisesRegex(ValueError,'backup_manifest_drift'):
                publication.verify_rollback(stage,publication.sha(b'original'))


if __name__=='__main__':unittest.main()
