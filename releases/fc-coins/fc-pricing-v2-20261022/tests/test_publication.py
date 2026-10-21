import ast
from datetime import datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
import json
from pathlib import Path
import re
import tempfile
import unittest


class Publication(unittest.TestCase):
    def test_matching_later_preview_retains_write_identity_but_changed_one_does_not(self):
        source=Path(__file__).parents[1]/'source/fc27_cloud_api.py'
        tree=ast.parse(source.read_text(encoding='utf-8'));node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='publication_view')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'executions').mkdir();(root/'previews').mkdir()
            namespace=dict(ROOT=root,read_json=lambda p:json.loads(p.read_text()),valid_id=lambda v:isinstance(v,str) and re.fullmatch('[a-f0-9-]{36}',v),datetime=datetime,timezone=timezone,Decimal=Decimal,InvalidOperation=InvalidOperation,ROUND_HALF_UP=ROUND_HALF_UP)
            exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
            now=datetime.now(timezone.utc);eid='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';pid='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
            rows=[dict(platform=p,id=str(i),costPrice='.6',lirunlv='.2',b2c='.12') for i,p in enumerate(('PS','XBOX','PC'))]
            backend=dict(rows=rows,exchangeRate='6.65',gameId='1322',isRoute=True,login=False,allServerChecked=False,selectedWebsites=0,b2cSelected=True,origin='https://order.p2pah.cn')
            written=(now-timedelta(seconds=120)).isoformat();observed=(now-timedelta(seconds=60)).isoformat()
            (root/'executions'/(eid+'.json')).write_text(json.dumps(dict(status='CONFIRMED',sync_confirmed=True,execution_id=eid,created_at=written,after=backend,automatic=False)))
            path=root/'previews'/(pid+'.json');preview=dict(preview_id=pid,run_id=eid,created_at=observed,status='review_only',backend_before=backend);path.write_text(json.dumps(preview))
            public={'rows':{p:dict(status='ok',checked_at=now.isoformat(),package_usd='12.00') for p in ('PS','XBOX','PC')}}
            value=namespace['publication_view'](public)
            self.assertEqual(value['execution_id'],eid);self.assertEqual(value['backend_written_at'],written);self.assertEqual(value['backend_checked_at'],observed);self.assertEqual(value['status'],'matched')
            preview['backend_before']['rows'][0]['b2c']='.13';path.write_text(json.dumps(preview))
            value=namespace['publication_view'](public)
            self.assertIsNone(value['execution_id']);self.assertEqual(value['basis'],'backend_preview');self.assertEqual(value['status'],'mismatch')
