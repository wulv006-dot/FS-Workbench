from pathlib import Path
import importlib.util,hashlib,unittest
HERE=Path(__file__).resolve().parent


class Scope(unittest.TestCase):
    def test_existing_page_styles_and_exact_single_target_are_preserved(self):
        raw=(HERE/'source/brain.css').read_bytes();before,delta=raw.split(b'\n/* Hermes V2 views',1)
        self.assertEqual(hashlib.sha256(before).hexdigest(),'ac8d2ceb9bd758c64d3c0a286fefac253d18851b8314dbf9c7969ee6ba567ec0')
        self.assertIn(b'min-inline-size:0',delta);self.assertIn(b'overflow-wrap:anywhere',delta)
        spec=importlib.util.spec_from_file_location('publisher',HERE/'deploy/release.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
        self.assertEqual(p.TARGETS,{'source/brain.css':'/var/www/dashboard/fs-home/brain/brain.css'});self.assertEqual(p.NEW,frozenset())


if __name__=='__main__':unittest.main()
