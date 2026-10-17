"""Approved background is explicit context; target values and permissions stay separate."""
import hashlib,json,re
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parent

class BackgroundContract(unittest.TestCase):
    def test_reviewed_bytes_fit_existing_runtime_and_sections(self):
        assets=HERE/'candidate/assets'
        raw=(assets/'knowledge-derived.md').read_bytes()
        meta=json.loads((assets/'knowledge-derived.json').read_text('utf-8'))
        self.assertEqual(hashlib.sha256(raw).hexdigest(),meta['sha256'])
        self.assertLessEqual(len(raw),32768)
        self.assertLessEqual(len(meta['source_reference']),240)
        self.assertEqual(meta['version'],'derived-1.2-20261015')
        content=raw.decode('utf-8')
        for section in re.split(r'(?m)^## ',content):self.assertLessEqual(len(section.encode('utf-8')),8000)
        for required in ('LV决策大脑','DY','Humanizer','00:00','06:59','Admin','Order','绿茵'):
            self.assertIn(required,content)
        self.assertNotRegex(content,r'-----BEGIN .*PRIVATE KEY|Bearer\s|Cookie\s*[:=]|password\s*[:=]')

if __name__=='__main__':unittest.main()
