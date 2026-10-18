from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from cohort_es_source import project_dataset,join_paid,archive_for


def digest(value):return hashlib.sha256(value.encode()).hexdigest()


class ESJoinTests(unittest.TestCase):
    q={'start':'2026-10-01','end':'2026-10-01'}

    def dataset(self):
        return {'status':'available','hashes':['a'*64],'parse_failures':0,'declared_files':1,'failed_files':0,'rows':[
            {'订单号':digest('new-id'),'游戏':'FC 27','付款时间':'2026/10/01 12:00:00','是否新客户':'是'},
            {'订单号':digest('no-uid-id'),'游戏':'FC 27','付款时间':'2026/10/01 12:30:00','是否新客户':'是'},
            {'订单号':digest('old-id'),'游戏':'FC 27','付款时间':'2026/10/01 13:00:00','是否新客户':'否'}]}

    def rows(self):
        return [{'id':ident,'customer_key':key,'customer':'unknown','paid_at':when} for ident,key,when in (
            ('new-id','site:one','2026-10-01T12:00:00+08:00'),('no-uid-id',None,'2026-10-01T12:30:00+08:00'),('old-id','site:two','2026-10-01T13:00:00+08:00'),
            ('repeat-id','site:one','2026-10-03T12:00:00+08:00'))]

    def test_flags_join_stable_subset_and_all_later_payments(self):
        es=project_dataset(self.dataset(),self.q)
        rows,quality=join_paid(self.rows(),es,self.q)
        self.assertTrue(quality['link_complete'])
        self.assertEqual(quality['acquisition_paid_orders'],3)
        self.assertEqual(quality['es_new_marked_paid_orders'],2)
        self.assertEqual(quality['stable_es_new_marked_paid_orders'],1)
        self.assertEqual(quality['excluded_es_new_identity_orders'],1)
        self.assertEqual([r['id'] for r in rows if r['customer']=='new'],['new-id'])
        self.assertIn('repeat-id',[r['id'] for r in rows])
        self.assertNotIn('new-id',str(es))

    def test_conflict_missing_match_and_unknown_do_not_establish_group(self):
        data=self.dataset();data['rows'].append(dict(data['rows'][0],是否新客户='否'))
        es=project_dataset(data,self.q)
        self.assertEqual(es['status'],'partial')
        self.assertFalse(join_paid(self.rows(),es,self.q)[1]['link_complete'])
        data=self.dataset();data['rows'][0]['是否新客户']=''
        self.assertFalse(join_paid(self.rows(),project_dataset(data,self.q),self.q)[1]['link_complete'])

    def test_incomplete_file_set_not_complete(self):
        data=self.dataset();data['declared_files']=2
        self.assertEqual(project_dataset(data,self.q)['status'],'partial')

    def test_payment_day_mismatch_blocks_link(self):
        es=project_dataset(self.dataset(),self.q)
        es['rows'][0]['payment_day']='2026-09-30'
        quality=join_paid(self.rows(),es,self.q)[1]
        self.assertEqual(quality['payment_day_mismatches'],1)
        self.assertFalse(quality['link_complete'])

    def test_missing_archive_uses_existing_reader_only(self):
        calls=[]
        reader=SimpleNamespace(get=lambda q:calls.append(q) or {'status':'pending','retryAfter':3})
        with patch('cohort_es_source.read_archive',return_value={'status':'missing'}),patch.dict(sys.modules,{'es_order_structure':SimpleNamespace(reader_for=lambda detail:reader)}):
            value=archive_for(object(),self.q)
        self.assertEqual(value['status'],'pending');self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
