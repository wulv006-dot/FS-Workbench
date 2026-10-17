import contextlib, copy, hashlib, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
import release_navigation as r
from grant_dy import grant_all

class Release(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);self.stage=self.root/'stage'
  self.registry={'clients':[{'id':'dy-all-projects','owner':'DY','enabled':True,'includeProfit':True,'expiresAtEpoch':4102444800,'tokenSha256':'a'*64,'projects':['FC27']}]}
  self.m={'schemaVersion':1,'scope':r.DEMAND_SCOPE,'releaseReady':False,'unchangedRequired':[{'path':'/var/www/dashboard/index.html','sha256':'a'*64}],'files':[]}
  for rel,target in r.DEMAND_TARGETS.items():
   old=None if rel in ('live/catalog.py','live/profit_queries.py') else b'old'
   new=json.dumps(grant_all(self.registry)).encode() if rel=='machine/clients.json' else b'new'
   if rel=='machine/clients.json':old=json.dumps(self.registry).encode()
   p=r.rooted(self.root,target);p.parent.mkdir(parents=True,exist_ok=True)
   if old:p.write_bytes(old)
   q=self.stage/'candidate'/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(new)
   self.m['files'].append({'candidate':rel,'target':target,'sha256':hashlib.sha256(new).hexdigest(),'beforeSha256':hashlib.sha256(old).hexdigest() if old else None})
 def test_exact_scope_and_private_registry_only(self):
  with patch.object(r,'guards'),patch.object(r,'retirement'):
   self.assertEqual(r.inspect(self.m,self.stage,self.root)['staticFiles'],9)
   p=self.stage/'candidate/machine/clients.json';bad=grant_all(self.registry);bad['clients'][0]['expiresAtEpoch']+=1;p.write_text(json.dumps(bad))
   self.m['files'][6]['sha256']=r.digest(p)
   with self.assertRaises(ValueError):r.inspect(self.m,self.stage,self.root)
 def test_baseline_and_approval_are_required(self):
  m=copy.deepcopy(self.m);m['files'][0]['beforeSha256']=None
  with self.assertRaises(ValueError):r.validate(m,self.stage)
  with self.assertRaises(ValueError):r.apply(self.m,self.stage,'0'*64,b'{}','nav-20261012T000000Z',self.root)
 def retirement(self):
  paths=list(r.DEMAND_TARGETS.values())+['/var/www/dashboard/fs-home/index.html','/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf','/etc/systemd/system/fs-transaction-collect.timer']
  return {'schemaVersion':1,'scope':'fs-on-demand-retire-20261012','releaseReady':True,'unchangedRequired':[{'path':p,'sha256':'a'*64} for p in paths],'runtimeRequired':{'fs-transaction-collect.service':{'ActiveState':'inactive'}},'acceptance':dict.fromkeys(['catalogue','frontend','dailyProfit','weeklyCurrent','weeklyPrevious','machine17','sevenGames','anonymousDenied'],True)}
 def test_retirement_stops_only_original_timer_and_preserves_journal(self):
  m=self.retirement();raw=json.dumps(m).encode();sha=hashlib.sha256(raw).hexdigest()
  with patch.object(r,'locks',lambda *a:contextlib.nullcontext()),patch.object(r,'live_lock',lambda *a:contextlib.nullcontext()),patch.object(r,'guards'),patch.object(r,'retirement'),patch.object(r,'directory_sync'),patch.object(r.subprocess,'check_output',side_effect=['UnitFileState=enabled\nActiveState=active\n','UnitFileState=disabled\nActiveState=inactive\n']),patch.object(r.subprocess,'run') as run:
   result=r.retire_collection(m,raw,sha,'nav-20261012T000001Z',self.root)
   self.assertEqual(result['status'],'retired');run.assert_called_once_with(['systemctl','disable','--now','fs-transaction-collect.timer'],check=True)
   self.assertEqual(json.loads((Path(result['backup'])/'journal.json').read_text())['status'],'retired')
   with self.assertRaises(ValueError):r.retire_collection(m,raw,sha,'nav-20261012T000001Z',self.root)
 def test_missing_acceptance_blocks_retirement_before_any_command(self):
  m=self.retirement();m['acceptance']['weeklyPrevious']=False;raw=json.dumps(m).encode()
  with patch.object(r.subprocess,'run') as run:
   with self.assertRaises(ValueError):r.retire_collection(m,raw,hashlib.sha256(raw).hexdigest(),'nav-20261012T000001Z',self.root)
   run.assert_not_called()

if __name__=='__main__':unittest.main()
