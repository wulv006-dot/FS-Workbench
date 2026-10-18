import ast
import json
import io
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
sys.path.append(str(SOURCE.parents[1]/'admin-data-tools-20261018'/'candidate'/'hermes'))
from workspace_evidence import save, read
from data_workspace_request import checked_request


def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data),'utf-8')


class WorkspaceTests(unittest.TestCase):
    def test_outer_http_dispatch_reaches_cohort_controller(self):
        route_tree=ast.parse((Path(__file__).parent/'fixtures/advisor_dispatch.py').read_text('utf-8'))
        outer=next(n for n in route_tree.body if isinstance(n,ast.FunctionDef) and n.name=='do_POST')
        controller=ast.parse((SOURCE/'controller.py').read_text('utf-8'))
        service_class=next(n for n in controller.body if isinstance(n,ast.ClassDef) and n.name=='HermesService')
        inner=next(n for n in service_class.body if isinstance(n,ast.FunctionDef) and n.name=='_post')
        inner_ns={};exec(compile(ast.Module(body=[inner],type_ignores=[]),'<controller post>','exec'),inner_ns)
        service=SimpleNamespace(authorizer=lambda user:True,detail=object())
        reader=SimpleNamespace(get=lambda args,**kwargs:{'status':'available','monitor':{'state':'active'}})
        ns={'json':json,'re':re,'urlsplit':urlsplit,'HERMES':SimpleNamespace(post=lambda body,user,headers:inner_ns['_post'](service,body,user,headers)),'ADVISOR':SimpleNamespace(post=lambda *args:(410,{'error':'legacy_analysis_retired'}))}
        exec(compile(ast.Module(body=[outer],type_ignores=[]),'<existing outer handler>','exec'),ns)
        headers={'X-Auth-User':'wulv','Content-Type':'application/json','X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'same-origin'}
        for kind,expected in (('hermes_cohort_observation',200),('cohort_observation',410)):
            raw=json.dumps({'kind':kind,'profile':'FC27','start':'2026-10-17','end':'2026-10-17','action':'create'}).encode();responses=[]
            request=SimpleNamespace(path='/advisor',headers=dict(headers,**{'Content-Length':str(len(raw))}),connection=SimpleNamespace(settimeout=lambda seconds:None),rfile=io.BytesIO(raw),reply=lambda code,data:responses.append((code,data)))
            with patch.dict(sys.modules,{'cohort_reader':SimpleNamespace(reader_for=lambda detail:reader)}):ns['do_POST'](request)
            self.assertEqual(responses[0][0],expected)

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
