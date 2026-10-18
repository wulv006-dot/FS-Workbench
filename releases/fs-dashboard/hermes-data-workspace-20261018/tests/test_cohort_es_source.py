from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'admin-data-tools-20261018'/'candidate/hermes'))
from cohort_es_source import project_dataset,join_paid,archive_for,read_archive


def digest(value):return hashlib.sha256(value.encode()).hexdigest()


class ESJoinTests(unittest.TestCase):
    q={'profile':'FC27','start':'2026-10-01','end':'2026-10-01'}

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

    def test_exclusion_scope_distinguishes_all_paid_from_es_new_orders(self):
        data=self.dataset()
        data['rows'].append({'订单号':digest('old-no-uid'),'游戏':'FC 27','付款时间':'2026/10/01 14:00:00','是否新客户':'否'})
        rows=self.rows()+[
            {'id':'old-no-uid','customer_key':None,'paid_at':'2026-10-01T14:00:00+08:00'},
            {'id':'later-no-uid','customer_key':None,'paid_at':'2026-10-03T14:00:00+08:00'}]
        _,quality=join_paid(rows,project_dataset(data,self.q),self.q)
        self.assertTrue(quality['link_complete'])
        self.assertEqual(quality['acquisition_paid_orders'],4)
        self.assertEqual(quality['es_new_marked_paid_orders'],2)
        self.assertEqual(quality['excluded_identity_orders'],3)
        self.assertEqual(quality['excluded_es_new_identity_orders'],1)
        self.assertIn('全部已付订单',quality['excluded_identity_orders_scope'])
        self.assertIn('complete_through',quality['excluded_identity_orders_scope'])
        self.assertTrue(quality['excluded_es_new_identity_orders_scope'].startswith('分母：es_new_marked_paid_orders'))
        self.assertIn('获取窗内',quality['excluded_es_new_identity_orders_scope'])
        for key in ('excluded_identity_orders_unit','excluded_es_new_identity_orders_unit'):
            self.assertEqual(quality[key],'订单，非去重客户人数')

    def test_payment_day_mismatch_blocks_link(self):
        es=project_dataset(self.dataset(),self.q)
        es['rows'][0]['payment_day']='2026-09-30'
        quality=join_paid(self.rows(),es,self.q)[1]
        self.assertEqual(quality['payment_day_mismatches'],1)
        self.assertFalse(quality['link_complete'])

    def test_aion2_excel_flag_matches_hashed_admin_order_only_same_game(self):
        query=dict(self.q,profile='AION2')
        data=self.dataset()
        data['rows']=[dict(data['rows'][0],游戏='Aion 2'),dict(data['rows'][1],游戏='Diablo 4')]
        es=project_dataset(data,query)
        self.assertEqual(len(es['rows']),1)
        rows=[{'id':digest('new-id'),'id_is_hashed':True,'customer_key':'site-local-anon',
            'paid_at':'2026-10-01T12:00:00+08:00'}]
        selected,quality=join_paid(rows,es,query)
        self.assertTrue(quality['link_complete'])
        self.assertEqual(selected[0]['customer'],'new')

    def test_missing_archive_uses_existing_reader_only(self):
        calls=[]
        reader=SimpleNamespace(get=lambda q:calls.append(q) or {'status':'pending','retryAfter':3})
        with patch('cohort_es_source.read_archive',return_value={'status':'missing'}),patch.dict(sys.modules,{'es_order_structure':SimpleNamespace(reader_for=lambda detail:reader)}):
            value=archive_for(object(),self.q)
        self.assertEqual(value['status'],'pending');self.assertEqual(len(calls),1)

    def test_archive_read_passes_selected_game_without_new_export(self):
        calls=[]
        def run(argv,**kwargs):
            calls.append((argv,kwargs))
            return SimpleNamespace(returncode=0,stdout=b'{"status":"available","rows":[]}')
        q=dict(self.q,profile='D4')
        with patch('cohort_es_source.subprocess.run',side_effect=run):
            self.assertEqual(read_archive(q)['status'],'available')
        self.assertEqual(__import__('json').loads(calls[0][0][-1])['profile'],'D4')
        self.assertIn(b'GAME_LABELS',calls[0][1]['input'])


if __name__=='__main__':unittest.main()
