import copy,importlib.util,io,json,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];STAGE=ROOT/'deploy/backend'
spec=importlib.util.spec_from_file_location('cache_patch_publish',STAGE/'release_navigation.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class PatchTests(unittest.TestCase):
 def test_exact_one_existing_target(self):
  m=json.loads((STAGE/'approved-manifest.json').read_text());self.assertEqual(1,len(r.validate(m,STAGE)))
  m['files'][0]['beforeSha256']=None
  with self.assertRaises(ValueError):r.validate(m,STAGE)
 def test_restart_only_range(self):
  calls=[]
  with patch.object(r.subprocess,'run',lambda args,**kw:calls.append(args)),patch.object(r.urllib.request,'urlopen',lambda *a,**kw:io.BytesIO(b'{"ok":true}')):
   r.restart_for({'scope':r.CACHE_FIX_SCOPE})
  self.assertEqual([['systemctl','restart','fs-business-range.service'],['systemctl','is-active','--quiet','fs-business-range.service']],calls)
if __name__=='__main__':unittest.main()
