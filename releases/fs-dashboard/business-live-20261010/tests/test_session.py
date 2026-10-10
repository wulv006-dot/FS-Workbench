import sys,threading,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
sys.modules.setdefault('ddddocr',types.ModuleType('ddddocr'))
import p2pah_session_service as s
class SessionTests(unittest.TestCase):
 def manager(self,ready):
  m=object.__new__(s.SessionManager);m.lock=threading.RLock();m.status='ready' if ready else 'offline';m.token='SYNTHETIC' if ready else None
  m.ensure=lambda: self.fail('summary must not ensure/login');m.login=m.ensure;m.refresh=m.ensure
  return m
 def test_ready_reuses_existing_request(self):
  m=self.manager(True);seen=[]
  m.request=lambda path,**kw:seen.append((path,kw)) or (200,'{"code":1,"data":{}}')
  with patch('admin_summary.extract',lambda d:{'metrics':{'newCustomers':{'value':None}},'dimensions':{}}):
   value=m.business_summary('1327','2026-10-09 00:00','2026-10-10 00:00')
  self.assertEqual('available',value['status']);self.assertEqual('SYNTHETIC',seen[0][1]['token'])
 def test_unready_does_not_renew(self):
  m=self.manager(False);m.request=lambda *a,**k:self.fail('no ready session')
  with self.assertRaises(OSError):m.business_summary('1327','2026-10-09 00:00','2026-10-10 00:00')
if __name__=='__main__':unittest.main(verbosity=2)
