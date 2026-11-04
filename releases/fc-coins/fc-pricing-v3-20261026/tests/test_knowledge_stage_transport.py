"""The knowledge release stage ships committed bytes, including frozen publisher."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[4]
BUILDER = ROOT / 'releases/fc-coins/fc-pricing-v3-20261026/deploy/knowledge/build_stage.py'
PREFIX = json.loads(subprocess.check_output(['git','show','HEAD:knowledge/index.json'],cwd=ROOT))['release']+'/deploy/'


class KnowledgeStageTransportTest(unittest.TestCase):
    def test_candidate_requires_exact_current_ids(self):
        sys.path.insert(0, str(BUILDER.parent))
        spec=importlib.util.spec_from_file_location('knowledge_stage_validation',BUILDER)
        build_stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(build_stage)
        index=json.loads(subprocess.check_output(['git','show','HEAD:knowledge/index.json'],cwd=ROOT))
        entry=next(row for row in index['entries'] if row['id']=='fc.reporting.methods')
        entry['id']='unexpected.reporting.methods'
        with patch.object(build_stage.subprocess,'check_output',return_value='a'*40), \
             patch.object(build_stage,'blob',return_value=json.dumps(index).encode()):
            with self.assertRaisesRegex(ValueError,'v3_current_knowledge_selection_invalid'):
                build_stage.build(ROOT,'a'*40,ROOT/'unused.tar.gz')

    def test_stage_publisher_equals_committed_blob(self):
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'knowledge.tar.gz'
            result = subprocess.run([sys.executable, str(BUILDER), str(ROOT), commit, str(archive)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['sourceCommit'], commit)
            with tarfile.open(archive, 'r:gz') as bundle:
                release = PREFIX.removesuffix('deploy/')
                catalog = json.load(bundle.extractfile(release + 'candidate/artifact/index.json'))
                baseline = bundle.extractfile(release + 'candidate/runtime/business-baseline.md').read()
                expected = {row['source']['sha256'] for row in catalog['entries']
                            if row['source']['path'] == 'docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md'}
                self.assertEqual(expected, {hashlib.sha256(baseline).hexdigest()})
                for name in ('release.py', 'prepare_manifest.py', 'release_navigation_base.py'):
                    relative = 'releases/fc-coins/fc-pricing-v3-20261026/deploy/knowledge/' + name
                    committed = subprocess.check_output(['git', 'show', 'HEAD:' + relative], cwd=ROOT)
                    staged = bundle.extractfile(PREFIX + name).read()
                    self.assertEqual(staged, committed, name)
                helper='releases/fc-coins/fc-pricing-v3-20261026/deploy/release_readiness.py'
                self.assertEqual(bundle.extractfile(PREFIX+'release_readiness.py').read(),subprocess.check_output(['git','show','HEAD:'+helper],cwd=ROOT))
                frozen = bundle.extractfile(PREFIX + 'release_navigation_base.py').read()
                self.assertEqual(hashlib.sha256(frozen).hexdigest(),
                                 '57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840')


if __name__ == '__main__':
    unittest.main()
