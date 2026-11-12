import copy,json,unittest
from prepare_weekly import ENTRY,add_entry,patch_script

class WeeklyNavigation(unittest.TestCase):
 def setUp(self):self.registry={'schemaVersion':1,'sections':[{'id':'activities','ids':['campaign-products']}],'tools':[{'id':'campaign-products','path':'/products.html'}]}
 def test_adds_once_and_preserves_every_existing_field(self):
  before=copy.deepcopy(self.registry);result=add_entry(before)
  self.assertEqual(before,self.registry);self.assertEqual(result['tools'][:-1],before['tools']);self.assertEqual(result['tools'][-1],ENTRY)
  self.assertEqual(result['sections'][0]['ids'],['campaign-products','campaign-weekly']);self.assertEqual(add_entry(result),result)
 def test_module_registry_without_sections(self):self.assertEqual(add_entry({'tools':[]}),{'tools':[ENTRY]})
 def test_conflicting_identity_is_not_overwritten(self):
  self.registry['tools'].append(dict(ENTRY,path='/different.html'))
  with self.assertRaisesRegex(ValueError,'conflict'):add_entry(self.registry)
 def test_replaces_only_compiled_registry_and_rejects_drift(self):
  source='keep();\r\nconst registry='+json.dumps(self.registry)+';\r\nafter();'
  result=patch_script(source,self.registry,add_entry(self.registry));self.assertTrue(result.startswith('keep();\r\n'));self.assertTrue(result.endswith(';\r\nafter();'))
  with self.assertRaisesRegex(ValueError,'drift'):patch_script(source,{'tools':[]},self.registry)

if __name__=='__main__':unittest.main()
