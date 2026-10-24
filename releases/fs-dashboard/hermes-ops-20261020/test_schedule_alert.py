import copy,importlib.util,unittest
from pathlib import Path
from datetime import datetime,timezone
spec=importlib.util.spec_from_file_location('incident_common',Path(__file__).parent/'source/common.py')
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
class ScheduleTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime.now(timezone.utc)
  self.snapshot={'captured_at':self.now.isoformat(),'status':'healthy','coin':{'config':{'system_enabled':True,'mode':'auto'},'schedule':{'status':'paused_after_failure','next_at':None}}}
 def test_paused_without_next_at_is_visible(self):
  self.assertEqual(common.assess(self.snapshot,self.now),['coin_schedule_paused_after_failure'])
 def test_player_gate_does_not_hide_collection_pause(self):
  self.snapshot['coin']['schedule'].update(status='player_sync_blocked',collection_status='paused_after_failure')
  self.assertIn('coin_schedule_paused_after_failure',common.assess(self.snapshot,self.now))
 def test_running_without_deadline_is_normal(self):
  self.snapshot['coin']['schedule']['status']='in_progress'
  self.assertEqual(common.assess(self.snapshot,self.now),[])
 def test_user_disabled_does_not_alert_pause(self):
  self.snapshot['coin']['config']['system_enabled']=False
  self.assertEqual(common.assess(self.snapshot,self.now),[])
 def test_unresolved_write_stays_visible(self):
  self.snapshot['health']={'incomplete_executions':1}
  self.assertEqual(common.assess(self.snapshot,self.now),['business_write_unresolved','coin_schedule_paused_after_failure'])
if __name__=='__main__':unittest.main()
