import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from _paths import ROOT, RELEASE
from customer_tracking import DEFAULT_CONFIG
from tracking_source import admin_paid_day, admin_email_history, private_es_day, scan_day


def row(order='ORDER-1'):
    return {'游戏':'FC 27','产品类型':'货币(Gold)','订单号':order,
        '订单金额（美元）':'500.01','实付金额':'440','实付币种':'EUR',
        '折扣金额':'24.99','是否新客户':'是','付款时间':'2026-10-17 12:00:00'}


class SourceTests(unittest.TestCase):
    def test_fuzzy_search_is_narrowed_to_exact_customer_email_and_site(self):
        calls=[]
        def request(path,timeout):
            self.assertLessEqual(timeout,10);calls.append(path)
            self.assertEqual(parse_qs(urlsplit(path).query)['quick_search'],['guest@example.invalid'])
            rows=[{'id':12,'order_no':'A','email':'guest@example.invalid','payer_email':'different@example.invalid',
                   'uid':0,'site_id':266,'gid':1327,'pay_status':1,'paytime':'2026-10-17 09:00:00','amount':'501'},
                  {'id':11,'order_no':'B','email':'other@example.invalid','payer_email':'guest@example.invalid',
                   'uid':5,'site_id':266,'gid':1327,'pay_status':1,'paytime':'2026-10-17 10:00:00','amount':'40'},
                  {'id':10,'order_no':'C','email':'guest@example.invalid','uid':99,'site_id':266,'gid':891,
                   'pay_status':1,'paytime':'2026-10-18 10:00:00','amount':'28'}]
            return 200,json.dumps({'code':1,'data':{'total':3,'list':rows}}).encode()
        value=admin_email_history(request,'guest@example.invalid','FC27')
        self.assertEqual(len(calls),1)
        self.assertEqual(value['status'],'available')
        self.assertEqual({item['order_no'] for item in value['orders']},{'A','C'})
        self.assertEqual(value['coverage']['other_game_orders'],1)
        self.assertEqual(value['coverage']['excluded_nonmatching_email'],1)
        self.assertNotIn('payer_email',json.dumps(value))

    def test_archive_sha_and_original_order_no_private(self):
        with tempfile.TemporaryDirectory() as dirname:
            root=Path(dirname);raw=b'synthetic-xlsx';digest=hashlib.sha256(raw).hexdigest()
            root.chmod(0o700)
            archive=root/(digest+'.xlsx');archive.write_bytes(raw);archive.chmod(0o600)
            manifest={'file_sha256':[digest],'query':{'profile':'FC27','start':'2026-10-17','end':'2026-10-17'},
                'file_set':{'declared_files':1,'failed_files':0},'captured_at':'2026-10-18T01:00:00Z',
                'rule_version':'synthetic-rule'}
            manifest['source_version']=hashlib.sha256(json.dumps({'files':[digest],'rule':'synthetic-rule'},sort_keys=True).encode()).hexdigest()
            saved=root/'manifest.json';saved.write_text(json.dumps(manifest),'utf-8');saved.chmod(0o600)
            with patch('es_order_structure.parse_files',return_value=([row()],[digest],0)):
                value=private_es_day('2026-10-17',root)
            self.assertEqual(value['status'],'available')
            self.assertEqual(value['rows'][0]['订单号'],'ORDER-1')
            archive.write_bytes(b'tampered')
            with self.assertRaises(ValueError):private_es_day('2026-10-17',root)

    def test_verified_full_day_admin_exact_match_and_uid_zero(self):
        seen=[]
        def request(path,timeout):
            self.assertEqual(timeout,10);seen.append(path)
            params=parse_qs(urlsplit(path).query)
            self.assertEqual(params['limit'],['20'])
            self.assertEqual(params['order'],['id,desc'])
            self.assertEqual(params['search[0][val]'],['1327'])
            self.assertEqual(params['search[1][val]'],['266'])
            rows=[{'id':9,'gid':1327,'site_id':266,'pay_status':1,'paytime':'2026-10-17 12:00:00',
                'order_no':'ORDER-1','email':'guest@example.invalid','uid':0,'amount':'501'},
                {'id':8,'gid':1327,'site_id':266,'pay_status':1,'paytime':'2026-10-17 13:00:00',
                'order_no':'OTHER','email':'another@example.invalid','uid':4,'amount':'10'}]
            return 200,json.dumps({'code':1,'data':{'total':2,'list':rows}}).encode()
        value=admin_paid_day(request,'2026-10-17','FC27',{'ORDER-1'})
        self.assertEqual(value['status'],'available');self.assertEqual(len(seen),1)
        self.assertEqual(value['orders']['ORDER-1']['uid'],0)
        self.assertNotIn('OTHER',json.dumps(value))

    def test_targeted_order_batches_preserve_missing_order_coverage(self):
        wanted={'ORDER-'+str(n) for n in range(1,22)};calls=[]
        def request(path,timeout):
            query=parse_qs(urlsplit(path).query);calls.append(query)
            self.assertEqual(query['search[4][field]'],['order_no'])
            self.assertEqual(query['search[4][operator]'],['IN'])
            numbers=query['search[4][val]'][0].split(',')
            self.assertLessEqual(len(numbers),20)
            rows=[{'id':int(number.split('-')[1]),'gid':1327,'site_id':266,'pay_status':1,
                   'paytime':'2026-10-17 12:00:00','order_no':number,'email':'guest@example.invalid',
                   'uid':0,'amount':'501'} for number in numbers if number!='ORDER-21']
            rows.sort(key=lambda row:row['id'],reverse=True)
            return 200,json.dumps({'code':1,'data':{'total':len(rows),'list':rows}}).encode()
        value=admin_paid_day(request,'2026-10-17','FC27',wanted,targeted=True)
        self.assertEqual(value['status'],'available')
        self.assertEqual(len(calls),2)
        self.assertEqual(value['coverage']['candidate_orders_requested'],21)
        self.assertEqual(value['coverage']['missing_candidate_orders'],1)
        self.assertEqual(value['coverage']['received'],20)

    def test_identical_raw_source_row_duplicate_is_covered_once(self):
        order={'id':9,'gid':1327,'site_id':266,'pay_status':1,'paytime':'2026-10-17 12:00:00',
            'order_no':'ORDER-1','email':'guest@example.invalid','uid':0,'amount':'501'}
        def request(path,timeout):
            return 200,json.dumps({'code':1,'data':{'total':2,'list':[order,dict(order)]}}).encode()
        result=admin_paid_day(request,'2026-10-17','FC27',{'ORDER-1'})
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['coverage']['received'],2)
        self.assertEqual(result['coverage']['unique_source_ids'],1)
        self.assertEqual(len(result['orders']),1)
        with self.assertRaisesRegex(ValueError,'duplicate_conflict'):
            admin_paid_day(lambda *a:(200,json.dumps({'code':1,'data':{'total':2,'list':[order,dict(order,amount='502')]}}).encode()),
                '2026-10-17','FC27',{'ORDER-1'})

    def test_incomplete_admin_source_never_publishes_candidate_scan(self):
        source={'status':'available','rows':[row()],'captured_at':'time','source_version':'synthetic',
            'coverage':{'file_set_complete':True}}
        with patch('tracking_source.private_es_day',return_value=source),patch('tracking_source.admin_paid_day',return_value={'status':'partial','orders':{},'coverage':{'complete':False}}):
            value=scan_day(lambda *_:None,'2026-10-17',DEFAULT_CONFIG)
        self.assertEqual(value['status'],'partial')
        self.assertNotIn('items',value)

    def test_es_amount_selects_buyer_before_targeted_admin_and_groups_candidates(self):
        rows=[dict(row('ORDER-1'),**{'Buyer ID':'buyer-a'}),
              dict(row('ORDER-2'),**{'Buyer ID':'buyer-a','订单金额（美元）':'520'}),
              dict(row('ORDER-3'),**{'Buyer ID':'buyer-b','订单金额（美元）':'500'})]
        source={'status':'available','rows':rows,'captured_at':'time','source_version':'synthetic',
                'coverage':{'file_set_complete':True,'rows':3}}
        calls=[]
        def request(path,timeout):
            query=parse_qs(urlsplit(path).query);calls.append(query)
            self.assertEqual(query['search[4][field]'],['order_no'])
            self.assertEqual(query['search[4][operator]'],['IN'])
            self.assertEqual(query['search[4][val]'],['ORDER-1'])
            admin_rows=[{'id':1,'gid':1327,'site_id':266,'pay_status':1,'paytime':'2026-10-17 12:00:00',
                         'order_no':'ORDER-1','email':'guest@example.invalid','uid':0,'amount':'400'}]
            return 200,json.dumps({'code':1,'data':{'total':1,'list':admin_rows}}).encode()
        with patch('tracking_source.private_es_day',return_value=source):
            value=scan_day(request,'2026-10-17',DEFAULT_CONFIG)
        self.assertEqual(value['status'],'available')
        self.assertEqual(len(calls),1)
        self.assertEqual(len(value['items']),1)
        self.assertEqual(value['items'][0]['order_usd'],'500.01')
        self.assertEqual(value['items'][0]['buyer_group_order_count'],2)
        self.assertTrue(value['items'][0]['amount_conflict'])
        self.assertEqual(value['coverage']['es_eligible_orders'],2)
        self.assertEqual(value['coverage']['es_eligible_buyers'],1)
        self.assertEqual(value['coverage']['admin_orders_requested'],1)
        self.assertEqual(value['coverage']['buyer_orders_collapsed'],1)

    def test_unverified_representative_tries_next_order_of_same_buyer(self):
        source={'status':'available','rows':[dict(row('ORDER-1'),buyer_id='buyer-a'),
            dict(row('ORDER-2'),buyer_id='buyer-a')],'captured_at':'time',
            'source_version':'synthetic','coverage':{'file_set_complete':True}}
        calls=[]
        def request(path,timeout):
            number=parse_qs(urlsplit(path).query)['search[4][val]'][0];calls.append(number)
            rows=[{'id':1 if number=='ORDER-1' else 2,'gid':1327,'site_id':266,'pay_status':1,
                'paytime':'2026-10-17 12:00:00','order_no':number,'email':'guest@example.invalid',
                'uid':0,'amount':'500.01'}]
            if number=='ORDER-1':rows[0]['email']='invalid'
            return 200,json.dumps({'code':1,'data':{'total':len(rows),'list':rows}}).encode()
        with patch('tracking_source.private_es_day',return_value=source):
            value=scan_day(request,'2026-10-17',DEFAULT_CONFIG)
        self.assertEqual(calls,['ORDER-1','ORDER-2'])
        self.assertEqual(value['items'][0]['order_no'],'ORDER-2')
        self.assertEqual(value['items'][0]['buyer_group_order_count'],2)
        self.assertEqual(value['coverage']['admin_orders_requested'],2)

    def test_no_es_eligible_order_skips_admin_read(self):
        source={'status':'available','rows':[dict(row(),**{'订单金额（美元）':'500'})],
                'captured_at':'time','source_version':'synthetic','coverage':{'file_set_complete':True}}
        with patch('tracking_source.private_es_day',return_value=source):
            value=scan_day(lambda *_:self.fail('Admin must not be called'),'2026-10-17',DEFAULT_CONFIG)
        self.assertEqual(value['status'],'available')
        self.assertEqual(value['items'],[])
        self.assertEqual(value['coverage']['es_eligible_orders'],0)

    def test_ignored_target_filter_falls_back_to_complete_day(self):
        source={'status':'available','rows':[row()],'captured_at':'time',
                'source_version':'synthetic','coverage':{'file_set_complete':True}}
        calls=[]
        def request(path,timeout):
            query=parse_qs(urlsplit(path).query);calls.append(query)
            order='OTHER' if 'search[4][field]' in query else 'ORDER-1'
            admin_row={'id':1,'gid':1327,'site_id':266,'pay_status':1,'paytime':'2026-10-17 12:00:00',
                       'order_no':order,'email':'guest@example.invalid','uid':0,'amount':'500.01'}
            return 200,json.dumps({'code':1,'data':{'total':1,'list':[admin_row]}}).encode()
        with patch('tracking_source.private_es_day',return_value=source):
            value=scan_day(request,'2026-10-17',DEFAULT_CONFIG)
        self.assertEqual(value['status'],'available')
        self.assertEqual(len(value['items']),1)
        self.assertEqual(len(calls),2)


if __name__=='__main__':unittest.main()
