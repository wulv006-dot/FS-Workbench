import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from mmoexp_google_data.seo import prepare,release


class Prepare(unittest.TestCase):
    def test_exact_scope_and_existing_navigation_are_preserved(self):
        repo=Path(__file__).resolve().parents[3]
        nav=dict(schemaVersion=1,sections=[dict(id='analytics',ids=['unified-business'])],tools=[dict(id='unified-business',path='/dashboard/analytics/')])
        raw=(json.dumps(nav)+'\n').encode();formal=b'# Existing unrelated FS routes\n'
        baseline=dict(target_hashes={prepare.NAV:hashlib.sha256(raw).hexdigest(),prepare.FORMAL:hashlib.sha256(formal).hexdigest()},unchangedRequired=[dict(path='/var/www/dashboard/index.html',sha256='0'*64)])
        gb=1024**3
        config=dict(data_root='/var/lib/fs-seo',control_root='/var/lib/fs-seo-control',ai_root='/var/lib/fs-seo-ai',web_port=8957,
                    resource_policy=dict(warning_bytes=4*gb,operating_ceiling_bytes=16*gb,emergency_stop_bytes=24*gb,host_reserve_bytes=40*gb,measured_basis='test fixture'),memory_policy={'measured_basis':'test'},sources={'admin':True})
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'release'
            result=prepare.build(repo,baseline,formal,raw,config,output)
            manifest=json.loads((output/'manifest.json').read_text())
            publisher=release.publisher(output,manifest)
            publisher.validate(manifest,output)
            actual=json.loads((output/'candidate/navigation.json').read_text())
            self.assertEqual(actual['tools'][:-1],nav['tools'])
            self.assertEqual(actual['sections'][0]['ids'][:-1],nav['sections'][0]['ids'])
            self.assertTrue((output/'candidate/routes.conf').read_bytes().startswith(formal))
            self.assertEqual(sum('OnCalendar=' in p.read_text() for p in (output/'candidate/units').iterdir()),1)
            self.assertNotIn('Hermes',(output/'candidate/units/fs-seo-daily.service').read_text())
            self.assertEqual(manifest['package'],result['package'])
            bad=dict(manifest,files=manifest['files']+[dict(candidate='evil',target='/etc/shadow',sha256='0'*64,beforeSha256=None)])
            with self.assertRaises(ValueError):publisher.validate(bad,output)
            with self.assertRaises(FileExistsError):prepare.build(repo,baseline,formal,raw,config,output)
