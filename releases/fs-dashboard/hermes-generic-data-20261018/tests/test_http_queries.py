"""Exercise production request parsing without starting services."""
import ast
from concurrent.futures import Future, ThreadPoolExecutor
import json
from pathlib import Path
import re
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
PACKAGE=Path(__file__).resolve().parents[1]
SIBLINGS=PACKAGE.parent
sys.path.insert(0,str(SIBLINGS/'admin-data-tools-20261018/candidate/hermes'))
sys.path.insert(0,str(PACKAGE/'source'))

def method(file,cls,name,scope):
    tree=ast.parse(file.read_text('utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
    fn=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(file),'exec'),scope)
    return scope[name]

class Queries(unittest.TestCase):
    def test_session_health_exposes_only_active_model_count(self):
        health=method(PACKAGE/'source/p2pah_session_service.py','SessionManager','health',{})
        pending=Future();completed=Future();completed.set_result({'status':'available'})
        obj=SimpleNamespace(lock=threading.RLock(),model_lock=threading.RLock(),
            model_jobs={'private-query':{'future':pending},'finished':{'future':completed}},
            status='ready',last_ok='synthetic-time')
        value=health(obj)
        self.assertEqual(value['active_model_reads'],1)
        self.assertNotIn('private-query',json.dumps(value))
        pending.set_result({})
        self.assertEqual(health(obj)['active_model_reads'],0)

    def test_model_read_single_worker_reuses_pending_and_bounds_each_request(self):
        import admin_product_orders as product
        source=PACKAGE/'source/p2pah_session_service.py'
        model_product=method(source,'SessionManager','model_product',
                             {'json':json,'time':time})
        entered=threading.Event();release=threading.Event();calls=[];timeouts=[]
        q=product.checked_query({'profile':'AION2','model_id':17815737,
            'start':'2026-10-17','end':'2026-10-17'})
        obj=SimpleNamespace(model_lock=threading.RLock(),model_pool=ThreadPoolExecutor(max_workers=1),
            model_jobs={},request=lambda path,**kwargs:(timeouts.append(kwargs['timeout']) or (200,b'{}')))
        def collect(request,query,model_seconds):
            calls.append((query,model_seconds));request('/synthetic',17)
            entered.set();self.assertTrue(release.wait(2))
            return {'kind':'admin_product_orders','query':query,'status':'available','products':[]}
        try:
            with patch.object(product,'collect',side_effect=collect):
                first=model_product(obj,q,'synthetic-token')
                self.assertEqual(first['status'],'pending');self.assertTrue(entered.wait(2))
                self.assertEqual(model_product(obj,q,'synthetic-token')['status'],'pending')
                other=dict(q,model_id=17815738)
                self.assertEqual(model_product(obj,other,'synthetic-token')['reason'],'model_read_busy')
                self.assertEqual(len(calls),1);self.assertEqual(calls[0][1],540)
                self.assertEqual(timeouts,[10])
                release.set();self.assertEqual(obj.model_jobs[json.dumps(q,sort_keys=True)]['future'].result(2)['status'],'available')
                self.assertEqual(model_product(obj,q,'synthetic-token')['status'],'available')
                self.assertEqual(len(calls),1)
        finally:
            release.set();obj.model_pool.shutdown(wait=True)

    def test_session_model_dispatch_releases_manager_lock_before_background(self):
        import admin_product_orders as product
        capability=method(PACKAGE/'source/p2pah_session_service.py','SessionManager','fc_capability',{'json':json})
        lock=threading.RLock();seen=[]
        def identity(token,timeout):
            self.assertEqual(timeout,10)
            return token=='synthetic-token'
        def background(query,token):
            seen.append((query,token,lock._is_owned()))
            return {'kind':'admin_product_orders','query':query,'status':'pending'}
        obj=SimpleNamespace(lock=lock,token='synthetic-token',identity_ok=identity,model_product=background)
        q={'kind':'product_orders','profile':'AION2','model_id':17815737,'start':'2026-10-17','end':'2026-10-17'}
        self.assertEqual(capability(obj,q)['status'],'pending')
        self.assertEqual(seen[0][0],product.checked_query({k:v for k,v in q.items() if k!='kind'}))
        self.assertFalse(seen[0][2])

    def test_http_accepts_full_cohort_query_and_rejects_overflow(self):
        replies=[];calls=[]
        ns={'urlsplit':urlsplit,'parse_qs':parse_qs,'CONVERSATION_PREFIX':'/conversation',
            'HERMES':SimpleNamespace(get=lambda q,u:(calls.append((q,u)) or (200,{'ok':True})))}
        get=method(PACKAGE/'source/range_api.py','Handler','do_GET',ns)
        query='mode=hermes&structure=cohort&profile=D4&start=2026-10-17&end=2026-10-17&platform=all&site_group=main&window_days=30'
        obj=SimpleNamespace(path='/advisor?'+query,headers={'X-Auth-User':'admin'},reply=lambda s,d:replies.append((s,d)))
        get(obj);self.assertEqual(replies[-1][0],200);self.assertEqual(calls[-1][0]['profile'],['D4'])
        obj.path+='&extra=1';get(obj);self.assertEqual(replies[-1][0],422);self.assertEqual(len(calls),1)
        obj.headers={};get(obj);self.assertEqual(replies[-1][0],401)

    def test_product_id_conversion_and_boundary(self):
        import admin_product_orders as product
        get=method(PACKAGE/'source/controller.py','HermesService','get',{'re':re})
        obj=SimpleNamespace(detail=SimpleNamespace(config={'enabled':True}))
        q=parse_qs('mode=hermes&structure=product_orders&profile=D4&product_id=1365865&start=2026-10-17&end=2026-10-17')
        with patch.object(product,'read',return_value={'status':'available'}) as read, patch.dict(sys.modules,{'workspace_evidence':SimpleNamespace(save=lambda *args:args[-1])}):
            self.assertEqual(get(obj,q,'admin')[0],200)
            self.assertEqual(read.call_args.args[0]['product_id'],1365865)
            self.assertNotIn('platform',read.call_args.args[0])
            for bad in ('0','-1','1.0','abc','9999999999'):
                self.assertEqual(get(obj,dict(q,product_id=[bad]),'admin')[0],422)
            self.assertEqual(get(obj,dict(q,product_id=['1','2']),'admin')[0],422)
            self.assertEqual(get(obj,dict(q,unknown=['1']),'admin')[0],422)
            self.assertEqual(get(obj,dict(q,model_id=['1']),'admin')[0],422)
            self.assertEqual(read.call_count,1)

if __name__=='__main__':unittest.main()
