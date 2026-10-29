import datetime,hashlib,importlib.util,json,os,tempfile,unittest,uuid
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[3]/'docs/planning/halloween-runtime-capacity-20261029/retention_dry_run.py'
spec=importlib.util.spec_from_file_location('halloween_readonly_retention',SOURCE);plan=importlib.util.module_from_spec(spec);spec.loader.exec_module(plan)
UTC=datetime.timezone.utc

class RetentionPlanTests(unittest.TestCase):
 def receipt(self,root,stamp,status='revealed'):
  identity=str(uuid.uuid4());request={'request_id':identity,'game_id':'diablo'}
  value={**request,'status':status,'request_hash':hashlib.sha256(json.dumps(request,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'created_at':stamp,'release_id':'campaign-preview-15','config_hash':'a'*64,'rule_hash':'b'*64,'slots':[{'slot':s,'model_id':'123','off_percent':10} for s in ['fixed','random-1','random-2']]}
  p=root/(identity+'.json');p.write_text(json.dumps(value),encoding='utf-8');return p

 def test_ny_calendar_cutoff_and_dst_remain_readonly(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);old=self.receipt(root,'2026-10-27T03:59:59Z');edge=self.receipt(root,'2026-10-27T04:00:00Z')
   before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
   r=plan.inventory(root,datetime.datetime(2026,10,29,4,tzinfo=UTC));rows={x['request_id']:x for x in r['rows']}
   self.assertEqual(r['full_payload_keep_from'],'2026-10-27');self.assertEqual(rows[old.stem]['classification'],'archive_proposal_only');self.assertEqual(rows[edge.stem]['classification'],'protected_recent_terminal')
   self.assertTrue(r['no_mutations']);self.assertFalse(r['apply_enabled']);self.assertEqual(before,{p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()})
   dst=plan.inventory(root,datetime.datetime(2026,11,2,4,30,tzinfo=UTC));self.assertEqual(dst['full_payload_keep_from'],'2026-10-30');self.assertIn('-05:00',dst['ny_now'])

 def test_unknown_corrupt_future_bad_hash_and_hardlinks_are_protected(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);unknown=self.receipt(root,'2020-01-01T00:00:00Z','unknown');corrupt=root/(str(uuid.uuid4())+'.json');corrupt.write_text('{broken')
   future=self.receipt(root,'2026-10-29T05:00:00Z');bad=self.receipt(root,'2020-01-01T00:00:00Z');data=json.loads(bad.read_text());data['request_hash']='c'*64;bad.write_text(json.dumps(data))
   linked=self.receipt(root,'2020-01-01T00:00:00Z');os.link(linked,root/(str(uuid.uuid4())+'.json'))
   r=plan.inventory(root,datetime.datetime(2026,10,29,4,tzinfo=UTC));rows={x['request_id']:x for x in r['rows']}
   for p in [unknown,corrupt,future,bad]:self.assertEqual(rows[p.stem]['classification'],'protected_unknown_or_invalid')
   self.assertEqual(rows[linked.stem]['classification'],'protected_type_link_or_identity');self.assertNotIn('archive_proposal_only',r['counts'])

 def test_scan_cap_invalid_inputs_and_oversized_record(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);oversized=root/(str(uuid.uuid4())+'.json');oversized.write_text('x'*16001)
   self.receipt(root,'2020-01-01T00:00:00Z');r=plan.inventory(root,datetime.datetime(2026,10,29,4,tzinfo=UTC));self.assertEqual(r['counts']['protected_size'],1)
   limited=plan.inventory(root,datetime.datetime(2026,10,29,4,tzinfo=UTC),limit=1);self.assertFalse(limited['inventory_complete']);self.assertEqual(len(limited['rows']),1)
   for limit in [0,10001,True]:
    with self.assertRaises(ValueError):plan.inventory(root,limit=limit)
   with self.assertRaises(ValueError):plan.inventory(root,datetime.datetime(2026,10,29))
   with self.assertRaises(ValueError):plan.inventory(root/'missing')

if __name__=='__main__':unittest.main()
