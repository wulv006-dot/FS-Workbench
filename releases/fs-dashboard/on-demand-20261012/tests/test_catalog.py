from datetime import datetime, timezone, timedelta
import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
import catalog

class Catalog(unittest.TestCase):
    def test_identity_is_stable_without_data_or_clock_cutoff(self):
        rows=[('MMOEXP','所有网站',0,'','mmoexp'),('RS','RS',506,506,'general')]
        now=datetime(2026,10,12,10,tzinfo=timezone(timedelta(hours=8)))
        a,b=catalog.build(rows,now),catalog.build(rows,now+timedelta(days=1))
        self.assertEqual(a['catalogId'],b['catalogId'])
        self.assertNotEqual(a['catalogId'],catalog.identifier(rows[:-1]))
        self.assertEqual(a['profiles']['RS']['metrics'],{})
        self.assertEqual(a['dashboard']['profiles']['RS']['series'],[])
        self.assertEqual(a['profiles']['RS']['primary']['filters']['gid'],'506')
        self.assertEqual(a['dashboard']['groups'][-1]['key'],'general')

if __name__=='__main__':unittest.main()
