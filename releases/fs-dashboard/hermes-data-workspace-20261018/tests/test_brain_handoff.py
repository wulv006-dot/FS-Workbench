"""Execute the real form handoff block and validate its typed request with the backend."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.parse import urlencode
SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
sys.path.append(str(SOURCE.parents[1]/'admin-data-tools-20261018/candidate/hermes'))
from data_workspace_request import checked_request

class BrainHandoffTests(unittest.TestCase):
 def handoff(self,kind,**params):
  code="""const fs=require('node:fs');const source=fs.readFileSync(process.argv[1],'utf8');const begin=source.indexOf('  const dataKind=initial.get');const end=source.indexOf('  refresh().then',begin);if(begin<0||end<0)throw Error('handoff block missing');const fields={};const result=new Function('initial','$','message','let dataRequest=null;'+source.slice(begin,end)+';return dataRequest;')(new URLSearchParams(process.argv[2]),id=>fields[id]||(fields[id]={}),()=>{});process.stdout.write(JSON.stringify(result));"""
  query=dict(data_kind=kind,data_evidence=('cohort_' if kind=='cohort' else 'ws_')+'a'*24,start='2026-10-01',end='2026-10-01',profile='FC27',**params)
  raw=subprocess.check_output(['node','-e',code,str(SOURCE/'brain.js'),urlencode(query)],text=True)
  return json.loads(raw)
 def test_three_forms_match_real_backend_request(self):
  product=self.handoff('product_orders',model_id='123',platform='ALL')
  self.assertEqual(checked_request(product)['query']['model_id'],123)
  for group in ('discount_new_customer','discount_type','discount_day'):
   discount=self.handoff('discount',group_by=group)
   self.assertEqual(checked_request(discount)['query']['group_by'],group.removeprefix('discount_'))
  for days in (7,14,30):
   cohort=self.handoff('cohort',platform='all',site_group='satellite',window_days=str(days))
   self.assertEqual(checked_request(cohort)['query']['window_days'],days)
 def test_archive_identity_and_window_remain_rejected_by_backend(self):
  cohort=self.handoff('cohort',window_days='999')
  with self.assertRaises(ValueError):checked_request(cohort)
  self.assertIsNone(self.handoff('unknown'))

if __name__=='__main__':unittest.main()
