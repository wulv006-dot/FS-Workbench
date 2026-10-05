import copy,importlib.util,json,sys,unittest
from pathlib import Path
p=Path(__file__).resolve().parents[2]/'tools/fc_migration_contract.py'
spec=importlib.util.spec_from_file_location('migration',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class MigrationTests(unittest.TestCase):
 def setUp(self):
  self.policy={'revision':25,'schedule_revision':23,'interval_minutes':60,'minimum_gross_margin_pct':'10','platforms':['PS','XBOX','PC'],'mode':'auto','system_enabled':True,'pricing_rules':{'schema_version':1,'bands':{k:dict(zip(('min_discount_pct','max_discount_pct'),v)) for k,v in m.APPROVED_BANDS.items()}}}
  # Synthetic quantities test shape/preservation only; not actual production whitelist.
  self.vectors={p:list(range(50,200,10)) for p in m.PLATFORMS}
  self.rows={(p,s):{**m.row_identity(p,s),'more':{'gold':copy.deepcopy(self.vectors[p]),'price':['1.00']*15,'discount':[100]*15,'give':[0]*15,'delivery_time':['test']*15,'hot':[False]*15}} for p in m.PLATFORMS for s in (0,266)}
 def test_rev25_ranges_schedule_preserved(self):self.assertTrue(m.validate_policy_migration(self.policy))
 def test_missing_conflicting_and_old_default_state_rejected(self):
  for key,value in [('revision',0),('schedule_revision',25),('system_enabled',False),('interval_minutes',8)]:
   policy=copy.deepcopy(self.policy);policy[key]=value
   with self.assertRaises(ValueError):m.validate_policy_migration(policy)
  with self.assertRaises(ValueError):m.validate_policy_migration(None)
 def test_fifteen_tiers_are_readonly_preserved(self):
  before=copy.deepcopy(self.rows);self.assertTrue(m.validate_six_tier_rows(self.rows,self.vectors));self.assertEqual(self.rows,before)
 def test_dated_approved_quantity_vectors_are_preserved(self):
  root=Path(__file__).resolve().parents[2]
  reference=json.loads((root/'config/examples/fc-approved-tier-quantities.reference.json').read_text(encoding='utf-8'))
  vectors=reference['quantitiesByPlatform']
  rows=copy.deepcopy(self.rows)
  for (platform,site),row in rows.items():row['more']['gold']=copy.deepcopy(vectors[platform])
  self.assertTrue(m.validate_six_tier_rows(rows,vectors))
  self.assertFalse(reference['pricesIncluded'])
 def test_missing_basis_or_removed_tiers_rejected(self):
  bad=copy.deepcopy(self.rows);bad[('PS',0)]['more']['give'][0]=1
  with self.assertRaises(ValueError):m.validate_six_tier_rows(bad,self.vectors)
  vectors=copy.deepcopy(self.vectors);vectors['PS'][0]=20
  with self.assertRaises(ValueError):m.validate_six_tier_rows(self.rows,vectors)
  with self.assertRaises(ValueError):m.validate_six_tier_rows({},self.vectors)
  with self.assertRaises(ValueError):m.validate_six_tier_rows(self.rows,None)
 def test_all_six_row_identity_fields_required(self):
  for key,row in self.rows.items():
   for field in m.row_identity(*key):
    for wrong in (None,'WRONG_PRODUCT'):
     bad=copy.deepcopy(self.rows);bad[key][field]=wrong
     with self.subTest(key=key,field=field),self.assertRaisesRegex(ValueError,'SCOPE_CHANGED'):
      m.validate_six_tier_rows(bad,self.vectors)
  bad=copy.deepcopy(self.rows);bad[('PS',0)]=copy.deepcopy(bad[('PC',0)])
  with self.assertRaisesRegex(ValueError,'SCOPE_CHANGED'):m.validate_six_tier_rows(bad,self.vectors)
 def test_quantities_finite_positive_and_numerically_unique(self):
  for bad in (True,False,0,-1,'NaN','Infinity','-Infinity','bad','60.0'):
   vectors=copy.deepcopy(self.vectors);vectors['PS'][0]=bad
   rows=copy.deepcopy(self.rows)
   for site in (0,266):rows[('PS',site)]['more']['gold']=copy.deepcopy(vectors['PS'])
   with self.subTest(bad=bad),self.assertRaises(ValueError):m.validate_six_tier_rows(rows,vectors)
 def test_row_gold_validation_and_order_not_normalized(self):
  for value in (0,'NaN',True,'60.0'):
   bad=copy.deepcopy(self.rows);bad[('PS',0)]['more']['gold'][0]=value
   with self.assertRaises(ValueError):m.validate_six_tier_rows(bad,self.vectors)
  bad=copy.deepcopy(self.rows);bad[('PS',0)]['more']['gold'].reverse()
  with self.assertRaises(ValueError):m.validate_six_tier_rows(bad,self.vectors)
if __name__=='__main__':unittest.main()
