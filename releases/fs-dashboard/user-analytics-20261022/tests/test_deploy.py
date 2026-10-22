"""Release boundary checks do not touch production or relax the frozen publisher."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy'))
from release import checked_manifest, TARGETS, NEW, SCOPE
from patch_navigation import patch


class Deployment(unittest.TestCase):
    def test_manifest_rejects_extra_target_and_existing_source_without_cas(self):
        def manifest():
            return dict(scope=SCOPE,businessWrites=False,timersChanged=True,files=[dict(candidate=k,target=v,beforeSha256=None if k in NEW else 'a'*64,owner='0:0',mode='0o644') for k,v in TARGETS.items()])
        value=manifest();self.assertEqual(checked_manifest(value),value)
        value['files'][0]['target']='/opt/fc27-cloud-browser/price_writer.py'
        with self.assertRaises(ValueError):checked_manifest(value)
        value=manifest();next(r for r in value['files'] if r['candidate'] not in NEW)['beforeSha256']=None
        with self.assertRaises(ValueError):checked_manifest(value)
        value=manifest();value['timersChanged']=False
        with self.assertRaises(ValueError):checked_manifest(value)

    def test_navigation_requires_exact_active_bytes(self):
        with self.assertRaisesRegex(ValueError,'navigation_baseline_drift'):
            patch({'navigation.json':b'{}','hubnav.js':b'','navigation.conf':b''})
