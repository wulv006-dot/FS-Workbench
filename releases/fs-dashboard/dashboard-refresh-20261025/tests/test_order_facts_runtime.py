"""Read-only source and HTTP dispatch seams, with synthetic source records."""
import ast
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT.parent/'cache-archive-retention-20261025/source')]
from order_facts_runtime import admin_orders, collect, publication, existing_costs

SCOPE=dict(start='2026-11-10',end='2026-11-10',site_id='266',gid='1327')
def row(i=2,site=266,**kw):
    return dict(id=i,site_id=site,site={'full_title':'www.mmoexp.com' if site==266 else 'www.rsorders.com'},
        order_no='O'+str(i),paytime='2026-11-10 10:00:00',pay_status='1',gid=1327,
        amount_usd_format='50',amount_rmb_format='350',status_format='已完成',**kw)
def response(rows,total=None):
    return 200,json.dumps({'code':1,'data':{'list':rows,'total':len(rows) if total is None else total}}).encode()

class Runtime(unittest.TestCase):
    def test_all_site_pagination_keeps_identity_catalog(self):
        request=Mock(side_effect=[response([row()],2),response([row(1,320)],2)])
        result=admin_orders(SCOPE,request)
        self.assertEqual(len(result),2)
        self.assertNotIn('email',result[0])
        qs=parse_qs(urlsplit(request.call_args_list[0].args[0]).query)
        self.assertEqual(qs['search[0][field]'],['pay_status'])
        self.assertEqual(qs['search[0][val]'],['1'])
        self.assertEqual(qs['search[1][field]'],['paytime'])
        self.assertEqual(qs['search[1][val]'],['2026-11-10 00:00:00,2026-11-10 23:59:59'])
        self.assertNotIn('site_id',qs)
    def test_pagination_scope_conflicts_and_denial_fail(self):
        bad=row();bad['paytime']='2026-11-11 00:00:00'
        for replies in ([response([bad])],[response([row()],2),response([row()],2)],
                        [response([row()],2),response([row(1)],3)],[(403,b'{}')]):
            with self.subTest(replies=len(replies)),self.assertRaises((ValueError,PermissionError)):
                admin_orders(SCOPE,Mock(side_effect=replies))
    def test_database_read_does_not_initialize_or_write(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/'existing.db'
            self.assertIsNone(publication(db));self.assertFalse(db.exists())
            with closing(sqlite3.connect(db)) as connection:
                connection.execute('CREATE TABLE meta(key TEXT,value TEXT)')
                connection.execute('INSERT INTO meta VALUES (?,?)',('weekly_publication',json.dumps({'cutoff':'x'})))
                connection.commit()
            before=db.read_bytes()
            self.assertEqual(publication(db),{'cutoff':'x'})
            self.assertEqual(db.read_bytes(),before)
    def test_cost_cache_retains_observed_only(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'cost.json'
            self.assertEqual(existing_costs(p)[0],[])
            p.write_text(json.dumps(dict(contract='channel-order-deliveries-v1',complete=True,rows=[],period={})))
            _,proof=existing_costs(p)
            self.assertTrue(proof['shipment_window_complete']);self.assertFalse(proof['order_cost_complete'])
    def test_collect_filters_local_membership_and_keeps_cost_missing(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/'absent.db';cost=Path(root)/'cost.json'
            cost.write_text(json.dumps(dict(contract='channel-order-deliveries-v1',complete=True,rows=[
                dict(source='www.mmoexp.com',sn='O2',delivery_id='D',genre=1,cost_total='100'),
                dict(source='www.rsorders.com',sn='O1',delivery_id='D-other',genre=1,cost_total='500') ])))
            reader=Mock()
            data=collect(SCOPE,request=Mock(return_value=response([row(),row(1,320)])),
                db=db,costs=cost,dataset_reader=reader)
            self.assertEqual(data['totals']['orders'],1)
            self.assertEqual(data['totals']['observed_cost_cny'],'100')
            self.assertEqual(data['totals']['missing_cost_orders'],1)
            self.assertEqual(data['totals']['unknown_channel_orders'],1)
            self.assertEqual(data['coverage']['unlinked_cost_records'],0)
            reader.assert_not_called()
    def test_existing_http_route_dispatches_facts_without_changing_old_modes(self):
        tree=ast.parse((ROOT/'source/range_api.py').read_text(encoding='utf-8'))
        handler=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
        method=next(n for n in handler.body if isinstance(n,ast.FunctionDef) and n.name=='do_GET')
        env=dict(urlsplit=urlsplit,parse_qs=parse_qs,CONVERSATION_PREFIX='/conversations',
                 CHANNELS=Mock(),ACTUAL_PROFITS=Mock(),ORDER_FACTS=Mock())
        exec(compile(ast.Module(body=[method],type_ignores=[]),'handler','exec'),env)
        for mode,name in [('order-facts','ORDER_FACTS'),('actual-profit','ACTUAL_PROFITS'),('profit','CHANNELS')]:
            service=env[name];service.get.return_value=(200,{'ok':name})
            h=Mock(path='/channels?mode='+mode,headers={'X-Auth-User':'actor'})
            env['do_GET'](h);service.get.assert_called_once_with({'mode':[mode]},'actor')
            h.reply.assert_called_with(200,{'ok':name})
        h=Mock(path='/channels?mode=order-facts',headers={})
        env['do_GET'](h);h.reply.assert_called_once_with(401,{'error':'login_required'})

if __name__=='__main__':unittest.main()
