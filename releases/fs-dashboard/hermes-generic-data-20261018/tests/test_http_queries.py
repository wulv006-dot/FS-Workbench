"""Exercise production request parsing without starting services."""
import ast
from pathlib import Path
import re
import sys
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
