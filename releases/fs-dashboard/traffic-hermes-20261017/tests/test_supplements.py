import ast
from datetime import date,timedelta
import json
from pathlib import Path
import time
import unittest


class ExactSupplements(unittest.TestCase):
    def test_daily_preparation_uses_daily_marketing_and_keeps_unavailable_local(self):
        source=Path(__file__).resolve().parents[1]/'source/source_snapshots.py'
        tree=ast.parse(source.read_text('utf8'))
        names={'prepare_supplements','native_pending','report_queries'}
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        scope={'date':date,'timedelta':timedelta,'json':json,'time':time}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-source-preparation','exec'),scope)
        calls=[]
        class Book:
            def research(self,name,args):
                calls.append((name,args))
                return {'evidence_id':'ev_'+'a'*24,'data':{'status':'not_available' if name=='fc.query_game_news' else 'available'}}
        result=scope['prepare_supplements'](Book(),'2026-10-16','2026-10-16')
        marketing=[q for name,q in calls if name=='fc.query_marketing_snapshot']
        self.assertEqual(marketing,[{'profile':'FC27','start':'2026-10-16','end':'2026-10-16'}, {'profile':'FC27','start':'2026-10-09','end':'2026-10-09'}])
        self.assertEqual(next(r for r in result if r['tool']=='fc.query_game_news')['status'],'not_available')
        self.assertTrue(all(r['status']=='available' for r in result if r['tool']=='fc.query_marketing_snapshot'))


if __name__=='__main__':unittest.main()
