import ast
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
sys.path.append(str(SOURCE.parents[1]/'admin-data-tools-20261018'/'candidate'/'hermes'))
from workspace_evidence import save, read
from data_workspace_request import checked_request


def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data),'utf-8')


class WorkspaceTests(unittest.TestCase):
    def test_archive_scope_and_no_second_read(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(sys.modules,{'fc_detail':SimpleNamespace(atomic=atomic)}):
            detail=SimpleNamespace(cache=tmp)
            q={'profile':'FC27','model_id':123,'start':'2026-10-01','end':'2026-10-01','platform':'ALL','max_pages':20}
            value=save(detail,'product_orders',q,{'status':'available','totals':{'distinct_orders':0}})
            self.assertEqual(read(detail,'product_orders',q,value['evidence_id']),value)
            with self.assertRaises(ValueError):read(detail,'product_orders',dict(q,model_id=124),value['evidence_id'])
            request=checked_request({'kind':'product_orders','query':dict(q,evidence_id=value['evidence_id'])})
            self.assertEqual(request['query']['evidence_id'],value['evidence_id'])
            with self.assertRaises(ValueError):checked_request({'kind':'product_orders','query':dict(q,url='https://example.com')})

    def test_http_product_and_duplicate_validation(self):
        tree=ast.parse((SOURCE/'controller.py').read_text('utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='HermesService')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='get')
        namespace={'re':re};exec(compile(ast.Module(body=[method],type_ignores=[]),'<controller get>','exec'),namespace)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(sys.modules,{'fc_detail':SimpleNamespace(atomic=atomic)}):
            detail=SimpleNamespace(config={'enabled':True},cache=tmp)
            service=SimpleNamespace(detail=detail)
            params={k:[v] for k,v in {'mode':'hermes','structure':'product_orders','profile':'FC27','model_id':'123','start':'2026-10-01','end':'2026-10-01'}.items()}
            import admin_product_orders
            with patch.object(admin_product_orders,'read',return_value={'status':'available','totals':{'distinct_orders':0}}):
                status,result=namespace['get'](service,params,'admin')
            self.assertEqual(status,200);self.assertTrue(result['evidence_id'].startswith('ws_'))
            params['model_id']=['123','124']
            self.assertEqual(namespace['get'](service,params,'admin')[0],422)
            self.assertEqual(namespace['get'](service,params,None)[0],401)


if __name__=='__main__':unittest.main()
