"""Exercise exact repair manifest selection while preserving unselected targets."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

DEPLOY=Path(__file__).resolve().parents[1]/'deploy'
sys.path.insert(0,str(DEPLOY))
import fc_v3_release_adapter as adapter
import prepare_manifest as prepare
import target_map


class RepairManifest(unittest.TestCase):
    def test_repair_selects_four_existing_files_protects_others_and_freezes_both_manifests(self):
        with tempfile.TemporaryDirectory() as folder:
            stage=Path(folder);deploy=stage/'deploy';deploy.mkdir()
            names=list(target_map.REPAIR_NAMES)+['source/fc-pricing-v3.js']
            mapping={}
            for index,name in enumerate(names):
                candidate=stage/'candidate'/name;candidate.parent.mkdir(parents=True,exist_ok=True)
                candidate.write_bytes(('new-'+name).encode())
                target=stage/'live'/str(index);target.parent.mkdir(exist_ok=True);target.write_bytes(('old-'+name).encode())
                mapping[name.removeprefix('source/')]=str(target)
            sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'a'*64
            provenance=dict(sourceCommit='a'*40,files={name:sha(stage/'candidate'/name) for name in names})
            (stage/'source-manifest.json').write_text(json.dumps(provenance))
            original=SimpleNamespace(HERMES_TARGETS={},HERMES_CAPABILITY_TARGETS={},CAP_PROTECTED_SESSION=set(),HERMES_DIRECT_TARGETS={})
            inspect=Mock(return_value={'ok':True})
            with patch.object(prepare,'STAGE',stage),patch.object(prepare,'HERE',deploy), \
                 patch.object(prepare,'targets',return_value=mapping),patch.object(prepare,'TARGET_COUNT',5), \
                 patch.object(prepare,'regular'),patch.object(prepare,'sha',side_effect=sha), \
                 patch.object(prepare,'load_base',return_value=original), \
                 patch.object(adapter,'load_base',return_value=SimpleNamespace(inspect=inspect)), \
                 patch.object(prepare.subprocess,'check_output',return_value='ActiveState=active'):
                result=prepare.prepare(repair=True)
                manifest=json.loads((stage/'approved-manifest.json').read_text())
                self.assertEqual(result['files'],4);self.assertEqual(result['new'],0)
                self.assertEqual(manifest['scope'],target_map.REPAIR_SCOPE)
                self.assertEqual({r['candidate'] for r in manifest['files']},set(target_map.REPAIR_NAMES))
                self.assertEqual({r['target'] for r in manifest['files']},{mapping[n.removeprefix('source/')] for n in target_map.REPAIR_NAMES})
                self.assertTrue(all(r['beforeSha256']==sha(Path(r['target'])) for r in manifest['files']))
                untouched=mapping['fc-pricing-v3.js']
                self.assertIn(dict(path=untouched,sha256=sha(Path(untouched))),manifest['unchangedRequired'])
                self.assertEqual((stage/'approved-manifest.json').read_bytes(),(deploy/'approved-manifest.json').read_bytes())
                inspect.assert_called_once_with(manifest,stage)
                with self.assertRaisesRegex(ValueError,'existing_manifest_must_be_reconciled'):prepare.prepare(repair=True)
                (stage/'candidate/source/fc-pricing-v3.js').write_bytes(b'changed outside repair')
                with self.assertRaisesRegex(ValueError,'staged_payload_differs_from_git_source_manifest'):prepare.prepare(repair=True)


if __name__=='__main__':unittest.main()
