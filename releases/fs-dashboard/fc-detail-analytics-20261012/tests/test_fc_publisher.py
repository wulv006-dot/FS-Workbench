import importlib.util, unittest, io
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fc_publisher',ROOT/'deploy/release_navigation.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class PublisherTest(unittest.TestCase):
    def test_exact_fc_files_only(self):
        self.assertEqual(len(p.expected_files({'scope':p.DETAIL_SCOPE})),5)
        self.assertEqual(p.target_for('fc/range_api.py'),'/opt/fs-exact-range-20261001/range_api.py')
        with self.assertRaises(ValueError):p.target_for('fc/fc27_cloud_worker.py')
    def test_existing_scopes_preserved(self):
        self.assertEqual(p.expected_files({'scope':p.BOUNDARY_SCOPE}),{'live/range_api.py'})
        self.assertEqual(p.expected_files({'scope':p.CACHE_FIX_SCOPE}),{'live/live_summary.py'})
    def test_range_only_restart(self):
        calls=[]
        original=p.subprocess.run
        original_url=p.urllib.request.urlopen
        class Result:
            returncode=0
            stdout='{"ok":true}'
        try:
            p.subprocess.run=lambda argv,**kw:(calls.append(argv) or Result())
            p.urllib.request.urlopen=lambda *a,**k:io.BytesIO(b'{"ok":true}')
            p.restart_for({'scope':p.DETAIL_SCOPE})
        finally:p.subprocess.run=original;p.urllib.request.urlopen=original_url
        self.assertEqual([a for a in calls if len(a)>1 and a[1]=='restart'],[['systemctl','restart','fs-business-range.service']])
if __name__=='__main__':unittest.main()
