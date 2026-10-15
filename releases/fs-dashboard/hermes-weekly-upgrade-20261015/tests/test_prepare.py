from pathlib import Path
import importlib.util,json,tempfile,unittest,zipfile
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('weekly_prepare',HERE.parent/'publisher/prepare_release.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class PreparationTests(unittest.TestCase):
 def test_traversal_archive_stops_before_database_or_live_write(self):
  with tempfile.TemporaryDirectory() as temp:
   stage=Path(temp);bundle=stage/'candidate.zip'
   with zipfile.ZipFile(bundle,'w') as z:z.writestr('../outside.txt','bad')
   (stage/'release-input.json').write_text(json.dumps({'zip_sha256':m.digest(bundle)}))
   with patch.object(m,'__file__',str(stage/'prepare_release.py')),patch.object(m,'snapshot',side_effect=AssertionError('must not inspect database')):
    with self.assertRaisesRegex(ValueError,'invalid candidate path'):m.main()
   self.assertFalse((stage.parent/'outside.txt').exists())
 def test_changed_archive_stops_before_extract(self):
  with tempfile.TemporaryDirectory() as temp:
   stage=Path(temp);(stage/'candidate.zip').write_bytes(b'changed');(stage/'release-input.json').write_text(json.dumps({'zip_sha256':'a'*64}))
   with patch.object(m,'__file__',str(stage/'prepare_release.py')):
    with self.assertRaisesRegex(ValueError,'archive changed'):m.main()
if __name__=='__main__':unittest.main()
