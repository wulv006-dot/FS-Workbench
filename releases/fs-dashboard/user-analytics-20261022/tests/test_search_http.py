"""Exercise the actual host POST method without importing production services."""
import ast
import io
import json
from pathlib import Path
import re
import sys
import unittest
from urllib.parse import urlsplit
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))


class SearchHTTP(unittest.TestCase):
    def test_actual_post_dispatch_and_body_guards(self):
        path=ROOT/'releases/fs-dashboard/daily-archive-20261021/source/range_api.py'
        tree=ast.parse(path.read_text('utf-8'))
        handler=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
        method=next(n for n in handler.body if isinstance(n,ast.FunctionDef) and n.name=='do_POST')
        service=Mock();service.search.return_value={'found':False}
        ns=dict(urlsplit=urlsplit,re=re,json=json,USERS=service)
        exec(compile(ast.Module(body=[method],type_ignores=[]),str(path),'exec'),ns)
        def call(headers,body=b'{}',path='/users/private/search'):
            request=Mock(path=path,headers=headers,rfile=io.BytesIO(body))
            ns['do_POST'](request)
            return request.reply.call_args.args
        headers={'X-Auth-User':'admin','Sec-Fetch-Site':'same-origin','Content-Type':'application/json','Content-Length':'2'}
        self.assertEqual(call(headers)[0],200)
        service.search.assert_called_once_with({},'admin')
        for remove,status in [('X-Auth-User',401),('Sec-Fetch-Site',403),('Content-Type',415),('Content-Length',413)]:
            self.assertEqual(call({k:v for k,v in headers.items() if k!=remove})[0],status)
        self.assertEqual(call(dict(headers,**{'Content-Length':'4097'}))[0],413)
        self.assertEqual(call(dict(headers,**{'Transfer-Encoding':'chunked'}))[0],415)
        self.assertEqual(call(headers,path='/users/private/search?email=bad')[0],403)
        self.assertEqual(call(headers,b'xx')[0],422)
        service.search.assert_called_once()

    def test_search_route_preserves_existing_routes_and_is_not_get(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
        from patch_search import patch,ROUTE
        before=b'location = /dashboard/users/private.json { original; }\n'
        self.assertEqual(patch(before),before+b'\n'+ROUTE)
        self.assertIn(b'if ($request_method != POST)',ROUTE)
        self.assertIn(b'auth_request /__auth_verify',ROUTE)
        with self.assertRaises(ValueError):patch(patch(before))
