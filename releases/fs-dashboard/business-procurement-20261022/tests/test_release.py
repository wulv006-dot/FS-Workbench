import hashlib
import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('procurement_ui',ROOT/'deploy/procurement_ui.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)

class ReleaseTest(unittest.TestCase):
    def test_four_static_targets_only(self):
        self.assertEqual(len(release.TARGETS),4)
        self.assertEqual(set(release.TARGETS),set(release.SOURCES)|{'generated/navigation.conf'})
        self.assertTrue(all(p.startswith('/var/lib/fs-navigation-formal-static/') or p=='/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf' for p in release.TARGETS.values()))

    def test_asset_version_pins_all_three_variants(self):
        raw=b''.join((ROOT/'source'/name).read_bytes() for name in ('business.js','home-business.js','legacy-business.js'))
        self.assertTrue(release.VERSION.endswith(hashlib.sha256(raw).hexdigest()[:12]))

    def test_only_the_three_aliases_change(self):
        before=b'# unrelated exact routes and permissions remain\n'+b'\n'.join(('location /variant { auth_request /existing; alias '+path+'; }').encode() for path in release.ALIASES)
        changed=release.candidate(before)
        for original,name in release.ALIASES.items():
            changed=changed.replace(('/var/lib/fs-navigation-formal-static/'+release.VERSION+'/'+name).encode(),original.encode())
        self.assertEqual(changed,before)

    def test_missing_or_duplicated_active_alias_is_rejected(self):
        before=b'\n'.join(('alias '+path+';').encode() for path in release.ALIASES)
        with self.assertRaises(ValueError):release.candidate(b'')
        with self.assertRaises(ValueError):release.candidate(before+before)

if __name__=='__main__':unittest.main()
