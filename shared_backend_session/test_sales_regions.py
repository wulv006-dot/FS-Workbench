import json, sqlite3, unittest
from unittest.mock import patch
import sales_regions as R


def page(no='DTEST123', game='▶美东-魔族-Siel', site='www.mmoexp.com', gid='826'):
    return '<table class="table-list"><tr data-gid="%s"><td></td><td>1</td><td>%s<br>%s</td><td>Aion 2 %s</td></tr></table>' % (gid,site,no,game)


class Session:
    def __init__(self, body):self.body,self.calls=body,[]
    def get_order(self,path,**kw):self.calls.append((path,kw));return 200,self.body


class RegionTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row
        self.orders=[dict(order_no='DTEST123',content='Siel - Elyos')]
    def tearDown(self):self.conn.close()
    def resolve(self,s,deliveries=()):
        return R.resolve_regions(s,self.conn,self.orders,deliveries,lambda x:(x,''))
    def test_exact_identity(self):
        self.assertEqual(R.parse_order_region(page(),'DTEST123'),'NA East')
        for kw in [dict(no='DTEST1234'),dict(site='www.other.com'),dict(gid='123')]:
            self.assertEqual(R.parse_order_region(page(**kw),'DTEST123'),'')
    def test_all_regions_and_ambiguous(self):
        for cn,en in R.CN.items():self.assertEqual(R.region_in('Aion 2 ▶'+cn+'-Siel'),en)
        self.assertEqual(R.region_in('[NA East] and [EU]'),'')
    def test_conflict_rejected(self):
        body=page()+page(game='▶欧服-魔族-Siel')
        # One table with two conflicting exact matches.
        body=body.replace('</table><table class="table-list">','')
        with self.assertRaises(RuntimeError):R.parse_order_region(body,'DTEST123')
    def test_session_or_layout_failure(self):
        for text in ['<input name="password">','<h1>error</h1>']:
            with self.assertRaises(RuntimeError):R.parse_order_region(text,'DTEST123')
    def test_native_area_id_distinguishes_taiwan_and_korea(self):
        for aid,expected in [('19910','TW'),('19972','Korea'),('0','')]:
            body=page(game='▶克羅梅德 - 魔族').replace('data-gid="826"','data-gid="826" data-aid="%s"' % aid)
            self.assertEqual(R.parse_order_region(body,'DTEST123'),expected)
    def test_native_mapping_complete_and_unambiguous(self):
        self.assertEqual(len(R.AREA_REGIONS),182)
        self.assertEqual(R.AREA_REGIONS[('826','19910')],'TW')
        self.assertEqual(R.AREA_REGIONS[('826','19972')],'Korea')
    def test_persisted_and_no_repeated_lookup(self):
        s=Session(page());self.assertEqual(self.resolve(s)['lookups'],1)
        self.assertEqual(self.resolve(s)['cached'],1);self.assertEqual(len(s.calls),1)
        self.assertEqual(s.calls[0][1],dict(sn='DTEST123',status='all'))
        self.assertEqual(R.load_verified(self.conn)['DTEST123']['region'],'NA East')
    def test_missing_retry_and_update(self):
        s=Session(page(no='OTHER'))
        with patch.object(R.time,'time',return_value=100):self.resolve(s)
        with patch.object(R.time,'time',return_value=200):self.assertEqual(self.resolve(s)['lookups'],0)
        with patch.object(R.time,'time',return_value=30000):self.resolve(s)
        self.assertGreater(R.load_verified(self.conn)['DTEST123']['retry_at'],30000)
    def test_local_evidence_no_network_and_change_invalidates(self):
        s=Session(page());self.resolve(s)
        self.orders[0]['content']='Other - Elyos [EU]'
        self.resolve(s);self.assertEqual(len(s.calls),1)
        self.assertEqual(R.load_verified(self.conn)['DTEST123']['region'],'EU')
    def test_delivery_conflict_uses_exact_lookup(self):
        s=Session(page(game='▶亚服-天族-Siel'))
        ds=[dict(order_no='DTEST123',game='▶美东-魔族-Siel'),dict(order_no='DTEST123',game='▶欧服-魔族-Siel')]
        self.resolve(s,ds)
        self.assertEqual(R.load_verified(self.conn)['DTEST123']['region'],'Asia')


if __name__=='__main__':unittest.main()
