import json,hashlib,sys,unittest
from pathlib import Path
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT/'source'
sys.path.insert(0,str(SOURCE))
from channel_effects import Attribution
from channel_source import apply_current_mapping as apply
COUPON=SOURCE/'coupon_channels.json'
if not COUPON.is_file():COUPON=ROOT.parent/'fs-business-baseline-20261021/source/coupon_channels.json'

class MappingCorrection(unittest.TestCase):
 def test_only_named_mapping_entries_change(self):
  v=json.loads((SOURCE/'channel_mapping.json').read_text(encoding='utf-8'))
  rows=[r for r in v['entries'] if r['code'].strip().casefold()=='aion2']
  self.assertEqual(len(rows),2);self.assertTrue(all(r['channel']=='分销' for r in rows))
  for r in rows:r['channel']='Tiktok'
  self.assertEqual(hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'b556f057bc2793fcdb04d9b579afd95690f15c135ac37030cea21b62ff815d67')
  v=json.loads(COUPON.read_text(encoding='utf-8'))
  keys=[k for k in v['codes'] if k.strip().casefold()=='aion2'];self.assertEqual(set(keys),{'Aion2','aion2'})
  for k in keys:self.assertEqual(v['codes'][k],'分销');v['codes'][k]='TT'
  self.assertEqual(hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'688ed7370a2e9f30134ed9a4d78a97a52648c58e75530f90449d58d8c7c9cfb4')

 def data(self):
  return {'generatedAt':'2026-10-20T01:00:00+08:00','period':{'start':'2026-10-19','end':'2026-10-19'},'sources':{'attribution':{'historical':'original'}},'codeCatalog':[{'key':'aion2','label':'Aion2','project':'TikTok'}], 'orders':[{'codeKey':c,'code':c,'project':p,'conflict':conflict,'salesUsd':1.25,'costCny':3.2,'promoterUid':'42','attribution':'折扣码'} for c,p,conflict in [('AION2','TikTok',False),('aion2','待核：映射冲突',True),('','TikTok',False),('not_in_map','未归类',False)]]}

 def test_closed_archive_projection_updates_code_and_catalog_without_mutating_money_or_source_time(self):
  data=self.data();before=deepcopy(data);result=apply(data)
  self.assertEqual(result['orders'][0]['project'],'分销');self.assertEqual(result['codeCatalog'][0]['project'],'分销')
  self.assertEqual(result['generatedAt'],before['generatedAt']);self.assertEqual(result['period'],before['period'])
  for old,new in zip(before['orders'],result['orders']):self.assertEqual({k:v for k,v in old.items() if k!='project'},{k:v for k,v in new.items() if k!='project'})
  self.assertEqual(result['orders'][1:],before['orders'][1:]);self.assertEqual(apply(deepcopy(result)),result)
  self.assertEqual(result['sources']['attribution']['mappingVersion'],hashlib.sha256((SOURCE/'channel_mapping.json').read_bytes()).hexdigest())

 def test_new_collection_uses_same_casefold_attribution(self):
  a=Attribution(json.loads((SOURCE/'channel_mapping.json').read_text(encoding='utf-8')),[],{})
  for code in ('Aion2','aion2',' AION2 '):self.assertEqual(a.resolve({'discount_code':code,'gid':'example'})['project'],'分销')

if __name__=='__main__':unittest.main()
