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
            (root/(digest+'.xlsx')).write_bytes(raw)
            manifest={'file_sha256':[digest],'query':{'profile':'FC27','start':'2026-10-17','end':'2026-10-17'},
                'file_set':{'declared_files':1,'failed_files':0},'captured_at':'2026-10-18T01:00:00Z',
                'rule_version':'synthetic-rule'}
            manifest['source_version']=hashlib.sha256(json.dumps({'files':[digest],'rule':'synthetic-rule'},sort_keys=True).encode()).hexdigest()
            (root/'manifest.json').write_text(json.dumps(manifest),'utf-8')
            with patch('es_order_structure.parse_files',return_value=([row()],[digest],0)):
                value=private_es_day('2026-10-17',root)
            self.assertEqual(value['status'],'available')
            self.assertEqual(value['rows'][0]['订单号'],'ORDER-1')
            (root/(digest+'.xlsx')).write_bytes(b'tampered')
            with self.assertRaises(ValueError):private_es_day('2026-10-17',root)

    def test_verified_full_day_admin_exact_match_and_uid_zero(self):
        seen=[]
        def request(path,timeout):
            self.assertLessEqual(timeout,10);seen.append(path)
            params=parse_qs(urlsplit(path).query)
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

    def test_identical_raw_source_row_duplicate_is_covered_once(self):
        order={'id':9,'gid':1327,'site_id':266,'pay_status':1,'paytime':'2026-10-17 12:00:00',
            'order_no':'ORDER-1','email':'guest@example.invalid','uid':0,'amount':'501'}
        def request(path,timeout):
            return 200,json.dumps({'code':1,'data':{'total':2,'list':[order,dict(order)]}}).encode()
        result=admin_paid_day(request,'2026-10-17','FC27',{'ORDER-1'})
        self.assertEqual(result['status'],'available')
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


if __name__=='__main__':unittest.main()
