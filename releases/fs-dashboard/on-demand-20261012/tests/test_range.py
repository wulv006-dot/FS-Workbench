import ast, importlib, json, sys, types, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'source'))
sys.path.insert(1,str(ROOT/'tests/helpers'))
if sys.platform=='win32':
    flock=types.ModuleType('fcntl');flock.LOCK_EX=2;flock.LOCK_NB=4;flock.flock=lambda *a:None;sys.modules['fcntl']=flock
collector=types.ModuleType('collector')
metadata=json.loads((ROOT/'tests/catalog.json').read_text(encoding='utf-8'))
collector.PROFILES=[(k,p['name'],int(p['primary']['filters']['gid'] or 0),0,metadata['dashboard']['profiles'][k]['group']) for k,p in metadata['profiles'].items()]
collector.call=lambda *a: (_ for _ in ()).throw(AssertionError('unexpected_real_source_read'))
collector.dimensions=lambda p:p.get('dimensions',{})
collector.profile_record=lambda key,name,primary,supplement:dict(key=key,name=name,period=primary['period'],primary=primary,supplement=supplement,metrics=primary['metrics'])
sys.modules['collector']=collector
import range_api as api

class Range(unittest.TestCase):
    def test_catalog_never_reads_snapshot_and_has_seventeen_profiles(self):
        with patch.object(Path,'read_bytes',side_effect=AssertionError('legacy_snapshot_read')),patch.object(Path,'read_text',side_effect=AssertionError('legacy_snapshot_read')):
            status,catalog=api.get_range({'mode':['catalog']})
        self.assertEqual(status,200);self.assertEqual(len(catalog['profiles']),17)
        self.assertTrue(catalog['catalogId'].startswith('catalog-'))
        self.assertNotIn('timer_seconds',vars(api))

    def test_exact_history_is_independent_of_catalog_initial_window(self):
        d=api.snapshot();params={'profile':['RS'],'start':['2023-07-01'],'end':['2023-07-07'],'grain':['day'],'snapshotId':[d['catalogId']]}
        q=api.query(params,d)
        self.assertEqual(q['period'],{'start':'2023-07-01 00:00','end':'2023-07-08 00:00'})
        params['snapshotId']=['old-version']
        with self.assertRaises(LookupError):api.query(params,d)

    def test_future_reversed_long_and_unknown_inputs_rejected(self):
        d=api.snapshot();p={'profile':['RS'],'start':['2026-10-01'],'end':['2026-10-03'],'grain':['day'],'snapshotId':[d['catalogId']]}
        for changes in [{'end':['2099-01-01']},{'start':['2026-10-04']},{'start':['2022-01-01']},{'profile':['UNAPPROVED']},{'url':['https://example.org']}]:
            with self.subTest(changes=changes),self.assertRaises((ValueError,KeyError)):api.query({**p,**changes},d)

    def test_summary_uses_native_query_without_old_files(self):
        p={'mode':['summary'],'profile':['MAPLESTORY_CLASSIC'],'start':['2026-10-11'],'end':['2026-10-11'],'grain':['day']}
        with patch.object(api.SUMMARY,'get',return_value=(200,{'status':'available'})) as call,patch.object(api,'snapshot',side_effect=AssertionError('snapshot_dependency')):
            self.assertEqual(api.get_range(p)[0],200)
        self.assertEqual(call.call_args[0][0]['profile'],'MAPLESTORY_CLASSIC')
        self.assertEqual(call.call_args[0][0]['cacheSeconds'],7200)

if __name__=='__main__':unittest.main()
