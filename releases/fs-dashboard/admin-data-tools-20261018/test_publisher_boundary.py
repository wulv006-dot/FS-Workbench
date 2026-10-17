from copy import deepcopy
import hashlib,json
from pathlib import Path
import sys
import tempfile
import shutil
import unittest

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'publisher'))
import es_v3_patch as bridge


class BoundaryTest(unittest.TestCase):
    def setUp(self):
        self.stage=ROOT/'stage' if (ROOT/'stage/approved-manifest.json').is_file() else ROOT
        self.m=json.loads((self.stage/'approved-manifest.json').read_text('utf-8'))
        self.base=bridge.load_base()
    def test_exact_closed_scope(self):
        files=self.base.validate(self.m,self.stage)
        self.assertEqual(len(files),11)
        self.assertEqual(len(self.m['unchangedRequired']),102)
        self.assertEqual(hashlib.sha256((ROOT/'publisher/release_navigation_base.py').read_bytes()).hexdigest(),bridge.BASE_SHA)
        self.assertFalse(self.m['timersChanged']);self.assertFalse(self.m['businessWrites'])
    def test_rehashed_unreviewed_source_cannot_publish(self):
        with tempfile.TemporaryDirectory() as name:
            stage=Path(name);shutil.copytree(self.stage/'candidate',stage/'candidate')
            m=deepcopy(self.m);r=m['files'][0];p=stage/'candidate'/r['candidate'];p.write_bytes(b'unreviewed')
            r['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):self.base.validate(m,stage)
    def test_new_file_outside_scope_and_schedule_changes_rejected(self):
        for change in ('new','timers','source'):
            m=deepcopy(self.m)
            if change=='new':m['files'].append(dict(m['files'][0],candidate='hermes/arbitrary.py',target='/opt/fs-hermes-fc/arbitrary.py'))
            elif change=='timers':m['timersChanged']=True
            else:m['sourceCommit']='not-a-commit'
            with self.assertRaises(ValueError):self.base.validate(m,self.stage)


if __name__=='__main__':unittest.main()
