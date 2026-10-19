import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import release_source_tabs as release
class ReleaseBoundary(unittest.TestCase):
 def test_frozen_publisher_and_dependency_order(self):
  b=release.publisher();keys=sorted(release.TARGETS)
  self.assertLess(keys.index('data/0_game_mapping_20261019.json'),keys.index('data/1_game_dimensions.py'))
  self.assertLess(keys.index('data/1_game_dimensions.py'),keys.index('data/3_detail_model.py'))
  self.assertLess(keys.index('ui/shell.js'),keys.index('z-index.html'))
  self.assertNotIn('/etc/ssh/sshd_config',release.TARGETS.values())
 def test_exact_scope_and_tamper_rejected(self):
  b=release.publisher()
  with tempfile.TemporaryDirectory() as folder:
   stage=Path(folder);rows=[]
   for rel,target in release.TARGETS.items():
    p=stage/'candidate'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
    rows.append(dict(candidate=rel,target=target,sha256=hashlib.sha256(b'fixture').hexdigest(),beforeSha256=None))
   m=dict(schemaVersion=1,scope=release.SCOPE,businessWrites=False,timersChanged=False,files=rows,unchangedRequired=[dict(path='/var/www/dashboard/index.html',sha256='a'*64)],runtimeRequired={'nginx.service':{'ActiveState':'active'},'fs-marketing-range.service':{'ActiveState':'active'}})
   self.assertEqual(len(b.validate(m,stage)),11)
   with self.assertRaises(ValueError):b.validate(dict(m,scope='other'),stage)
   with self.assertRaises(ValueError):b.validate(dict(m,businessWrites=True),stage)
   (stage/'candidate'/rows[0]['candidate']).write_bytes(b'drift')
   with self.assertRaises(ValueError):b.validate(m,stage)
class UIFinish(unittest.TestCase):
 def test_no_data_targets_or_range_restart(self):
  import release_ui_finish as ui
  from unittest.mock import patch
  self.assertEqual(len(ui.TARGETS),5)
  self.assertTrue(all('/opt/' not in v for v in ui.TARGETS.values()))
  b=ui.publisher();self.assertIs(b.locks,b.ui_only_locks)
  with patch.object(ui.subprocess,'run') as run:b.restart_for({'scope':ui.SCOPE})
  self.assertFalse(any('fs-marketing-range.service' in call.args[0] for call in run.call_args_list))
if __name__=='__main__':unittest.main()
