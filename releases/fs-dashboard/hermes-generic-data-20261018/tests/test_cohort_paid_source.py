from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

PACKAGE=Path(__file__).resolve().parents[1]
SIBLINGS=PACKAGE.parent
sys.path.insert(0,str(PACKAGE/'source'))
from cohort_paid_source import checked_query,collect
sys.path.insert(0,str(SIBLINGS/'admin-data-tools-20261018'/'candidate/hermes'))
sys.path.insert(0,str(PACKAGE/'source'))
from es_order_structure import GAME_LABELS
from admin_product_orders import GAME_IDS as PRODUCT_GAME_IDS
from cohort_paid_source import GAME_IDS as PAID_GAME_IDS


class PaidSourceTests(unittest.TestCase):
    def test_exact_same_game_set_across_es_product_and_cohort(self):
        self.assertEqual(set(GAME_LABELS),set(PRODUCT_GAME_IDS))
        self.assertEqual(PRODUCT_GAME_IDS,PAID_GAME_IDS)

    def test_d4_aion2_main_site_only_and_private_pseudonyms(self):
        yesterday=(datetime.now(timezone(timedelta(hours=8))).date()-timedelta(days=1)).isoformat()
        for profile,gid in (('D4',456),('AION2',891)):
            query={'profile':profile,'start':yesterday,'end':yesterday}
            def request(path,timeout):
                params=parse_qs(urlsplit(path).query)
                self.assertEqual(params['search[0][val]'],[str(gid)])
                self.assertEqual(params['search[1][val]'],['266'])
                self.assertEqual(params['search[2][val]'],['1'])
                self.assertEqual(params['order'],['id,desc'])
                data={'code':1,'data':{'total':1,'list':[{'id':42,'gid':gid,'site_id':266,
                    'pay_status':1,'order_no':'PRIVATE-ORDER','uid':123456,
                    'paytime':yesterday+' 12:00:00','email':'private@example.invalid'}]}}
                return 200,json.dumps(data).encode()
            result=collect(request,query)
            self.assertEqual(result['status'],'available')
            self.assertTrue(result['coverage']['paid_complete'])
            self.assertEqual(result['orders'][0]['id'],hashlib.sha256(b'PRIVATE-ORDER').hexdigest())
            self.assertTrue(result['orders'][0]['customer_key'])
            self.assertNotIn('PRIVATE-ORDER',json.dumps(result))
            self.assertNotIn('123456',json.dumps(result))
            self.assertNotIn('private@example',json.dumps(result))

    def test_cross_game_response_rejected_and_scope_strict(self):
        yesterday=(datetime.now(timezone(timedelta(hours=8))).date()-timedelta(days=1)).isoformat()
        query={'profile':'D4','start':yesterday,'end':yesterday}
        def wrong(path,timeout):
            return 200,json.dumps({'code':1,'data':{'total':1,'list':[{'id':42,'gid':891,
                'site_id':266,'pay_status':1,'order_no':'PRIVATE-ORDER','uid':123,
                'paytime':yesterday+' 12:00:00'}]}}).encode()
        with self.assertRaises(ValueError):collect(wrong,query)
        with self.assertRaises(ValueError):checked_query(dict(query,site_id=0))

    def test_active_service_candidate_dispatches_private_generic_read(self):
        path=PACKAGE/'source'/'p2pah_session_service.py'
        spec=importlib.util.spec_from_file_location('generic_session_candidate',path)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'ddddocr':SimpleNamespace()}):spec.loader.exec_module(module)
        yesterday=(datetime.now(timezone(timedelta(hours=8))).date()-timedelta(days=1)).isoformat()
        q={'kind':'cohort_paid_orders','profile':'D4','start':yesterday,'end':yesterday}
        def request(path,*,token,timeout):
            return 200,json.dumps({'code':1,'data':{'total':0,'list':[]}}).encode()
        fake=SimpleNamespace(lock=threading.RLock(),token='test-only',identity_ok=lambda token:True,
            request=request)
        result=module.SessionManager.fc_capability(fake,q)
        self.assertEqual(result['status'],'available')
        self.assertEqual(result['orders'],[])
        fake.identity_ok=lambda token:False
        denied=module.SessionManager.fc_capability(fake,q)
        self.assertEqual(denied['reason'],'existing_auth_unavailable')


if __name__=='__main__':unittest.main()
