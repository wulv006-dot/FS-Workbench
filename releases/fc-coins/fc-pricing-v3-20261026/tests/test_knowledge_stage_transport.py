"""The knowledge release stage ships committed bytes, including frozen publisher."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[4]
BUILDER = ROOT / 'releases/fc-coins/fc-pricing-v3-20261026/deploy/knowledge/build_stage.py'
PREFIX = json.loads(subprocess.check_output(['git','show','HEAD:knowledge/index.json'],cwd=ROOT))['release']+'/deploy/'


class KnowledgeStageTransportTest(unittest.TestCase):
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
