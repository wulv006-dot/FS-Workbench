"""Exact two-file single-card release and reuse of the reviewed publisher; no host calls."""
import ast
import hashlib
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


class SingleCardRelease(unittest.TestCase):
    def test_manifest_preserves_51_sources_and_exact_rule_version_delta(self):
        manifest = json.loads((HERE/'manifest.json').read_bytes())
        sources = json.loads((HERE/'SOURCE-MAP.json').read_bytes())
        self.assertEqual(len(manifest['baseline']), 51)
        self.assertEqual(set(manifest['files']), {'VERSION','player_web/direct_model_payload.py'})
        self.assertEqual(sources['manifest_sha256'], hashlib.sha256((HERE/'manifest.json').read_bytes()).hexdigest())
        self.assertEqual(sources['base_version'], manifest['base_version'])
        self.assertEqual(sources['version'], manifest['version'])
        for name, row in sources['runtime_files'].items():
            self.assertEqual(row['before_sha256'], manifest['baseline'][name])
            self.assertEqual(row['sha256'], manifest['files'][name])
            self.assertEqual(row['sha256'], hashlib.sha256((ROOT/row['source']).read_bytes()).hexdigest())
        self.assertEqual(manifest['dockerfile_sha256'], hashlib.sha256((HERE/'Dockerfile').read_bytes()).hexdigest())
        self.assertEqual((HERE/'VERSION').read_text().strip(), manifest['version'])
        self.assertTrue(sources['policy_changes'])

    def test_wrapper_only_changes_manifest_pin_and_keeps_original_guards(self):
        def shape(path):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            tree.body.pop(0)  # Reviewed wrapper's module docstring.
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(isinstance(n,ast.Name) and n.id=='MANIFEST_SHA' for n in node.targets):
                    node.value = ast.Constant('release-specific-pin')
            return ast.dump(tree,include_attributes=False)
        previous = ROOT/'releases/fc-players/empty-market-recovery-20261031/upgrade_empty_market.py'
        self.assertEqual(shape(HERE/'upgrade_single_card.py'),shape(previous))
        tree = ast.parse((HERE/'upgrade_single_card.py').read_text(encoding='utf-8'))
        pin = next(n.value.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MANIFEST_SHA' for t in n.targets))
        self.assertEqual(pin,hashlib.sha256((HERE/'manifest.json').read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
