import importlib.util,json,sys,tempfile,sqlite3,unittest,datetime as dt
from pathlib import Path
R=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(R/'mmoexp_google_data/details'))
sys.path.insert(0,str(R/'releases/fs-dashboard/traffic-hermes-20261017/source'))
import detail_model as model
spec=importlib.util.spec_from_file_location('content_range',Path(__file__).parents[1]/'source/range_api.py');api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
class ContentTests(unittest.TestCase):
 def report(self,name):
  rows=[{'dimensions':{name:('FC27 guide ' if name=='query' else '/news/fc-27-')+str(i)},'metrics':{'clicks':str(30-i),'impressions':'100','ctr':'.1','position':'2'}} for i in range(25)]
  rows += [{'dimensions':{name:'Aion 2 '+str(i)},'metrics':{'clicks':'100','impressions':'100','ctr':'1','position':'1'}} for i in range(22)]
  return {'report':name,'rows':rows,'collected_at':'2026-10-17T12:00:00Z','quality':{'top_rows_not_all_queries':True}}
 def test_both_dimensions_match_before_global_top(self):
  for name in ('query','page'):
   table=model.top_table(self.report(name),'clicks',20,'9999');c=table['fc27_content']
   self.assertTrue(all('Aion' in r['dimensions'][name] for r in table['rows']))
   self.assertEqual(c['returned_matching_rows'],25);self.assertEqual(len(c['rows']),20);self.assertEqual(c['omitted_rows'],5);self.assertTrue(c['display_truncated'])
   self.assertEqual(c['metrics']['clicks'],str(sum(range(6,31))))
 def test_missing_empty_failed(self):
  self.assertIsNone(model.top_table(None,'clicks',20,None)['fc27_content']['rows'])
  empty={'report':'query','rows':[]};self.assertEqual(model.top_table(empty,'clicks',20,None)['fc27_content']['rows'],[])
  failed=self.report('query');failed['last_attempt']={'status':'failed'}
  self.assertTrue(model.top_table(failed,'clicks',20,None)['fc27_content']['status']['retained_previous'])
 def test_cached_same_snapshot_reprojects_without_collection_or_disk_write(self):
  with tempfile.TemporaryDirectory() as td:
   oldcache,olddb=api.CACHE,api.DETAIL_DATABASE;api.CACHE=Path(td)/'cache';api.CACHE.mkdir();api.DETAIL_DATABASE=Path(td)/'raw.db'
   try:
    db=sqlite3.connect(api.DETAIL_DATABASE);db.execute('CREATE TABLE detail_reports(source,resource,report,start_date,end_date,payload_json)')
    parts={}
    for name in ('query','page'):
     raw=self.report(name);parts[name]=model.top_table(raw,'clicks',20,None);parts[name]['fc27_content']={k:v for k,v in parts[name]['fc27_content'].items() if k not in ('rows','displayed_rows','display_truncated','omitted_rows','display_limit','display_basis','status')}
     db.execute('INSERT INTO detail_reports VALUES(?,?,?,?,?,?)',('gsc','sc-domain:mmoexp.com',name,'2026-10-05','2026-10-11',json.dumps(raw)))
    db.commit();db.close()
    value={'start':'2026-10-05','end':'2026-10-11','status':'available','validated_day':dt.datetime.now(api.SHANGHAI).date().isoformat(),'period':{'rule_version':api.RULE_VERSION,'sources':{'gsc':{'breakdowns':parts}}}}
    path=api.cache_path(value['start'],value['end']);path.write_text(json.dumps(value));before=path.read_bytes()
    code,result=api.query(value['start'],value['end'],submit=lambda *a: self.fail('must not collect'))
    self.assertEqual(code,200);self.assertEqual(len(result['period']['sources']['gsc']['breakdowns']['query']['fc27_content']['rows']),20);self.assertEqual(path.read_bytes(),before)
    db=sqlite3.connect(api.DETAIL_DATABASE);raw=self.report('query');raw['collected_at']='2026-10-17T11:00:00Z';db.execute('UPDATE detail_reports SET payload_json=? WHERE report=?',(json.dumps(raw),'query'));db.commit();db.close();result=api.cached(value['start'],value['end']);self.assertNotIn('rows',result['period']['sources']['gsc']['breakdowns']['query']['fc27_content'])
    api.DETAIL_DATABASE.unlink();result=api.cached(value['start'],value['end']);c=result['period']['sources']['gsc']['breakdowns']['query']['fc27_content'];self.assertNotIn('rows',c);self.assertEqual(c['detail_projection'],'legacy_cache_missing_raw')
   finally:api.CACHE,api.DETAIL_DATABASE=oldcache,olddb
if __name__=='__main__':unittest.main()
