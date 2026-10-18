import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest

from _paths import ROOT, RELEASE
from customer_tracking import DEFAULT_CONFIG, candidate_rows
from tracking_controller import TrackingController
from tracking_tool import anonymous_snapshot
from research import RESEARCH_NAMES,tool_schemas
from runs_contract import WIRE_TOOLS
from proxy_gateway import schemas

def attach_customer_tracking(book,controller,user):
    import re
    source=(RELEASE/'source'/'conversation_service.py').read_text('utf-8')
    function=next(item for item in ast.parse(source).body if isinstance(item,ast.FunctionDef) and item.name=='attach_customer_tracking')
    module=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
    namespace={'re':re}
    exec(compile(module,'conversation_service.py','exec'),namespace)
    return namespace['attach_customer_tracking'](book,controller,user)


class ToolTests(unittest.TestCase):
    def test_exact_tool_schema_matches_worker_allowlist(self):
        wire='mcp__fcro__fc_query_customer_tracking'
        self.assertIn('fc.query_customer_tracking',RESEARCH_NAMES)
        self.assertEqual(set(WIRE_TOOLS),{item['function']['name'] for item in schemas()})
        schema=next(item['function'] for item in tool_schemas() if item['function']['name']==wire)
        self.assertEqual(schema['parameters']['required'],['tracking_id'])
        self.assertFalse(schema['parameters']['additionalProperties'])

    def test_anonymous_tool_owner_guard_and_no_private_identifiers(self):
        class Client:
            def read(self,body):
                return {'status':'available','orders':[],
                    'coverage':{'complete':True,'source_total':0,'received':0}}
        with tempfile.TemporaryDirectory() as dirname:
            service=TrackingController(dirname,lambda user:user in ('admin','otheradmin'),Client(),auto_start=False)
            es={'游戏':'FC 27','产品类型':'货币(Gold)','订单号':'SECRET-ORDER',
                '订单金额（美元）':'501','实付金额':'401','实付币种':'EUR',
                '折扣金额':'10','是否新客户':'是','付款时间':'2026-10-17 10:00:00'}
            admin={'order_no':'SECRET-ORDER','gid':1327,'site_id':266,'pay_status':1,
                'email':'secret@example.invalid','uid':0,'amount':'501'}
            item=candidate_rows([es],{'SECRET-ORDER':admin},DEFAULT_CONFIG)[0][0]
            candidate=service.store.save_candidates('2026-10-17',[item])['items'][0]
            tracking=service.store.track(candidate['candidate_id'],'a'*32,owner='admin')['tracking_id']
            with self.assertRaises(PermissionError):service.tool_read('ordinary',tracking)
            with self.assertRaises(PermissionError):service.tool_read('otheradmin',tracking)
            value=service.tool_read('admin',tracking)
            encoded=json.dumps(value)
            self.assertNotIn('secret@example.invalid',encoded)
            self.assertNotIn('SECRET-ORDER',encoded)
            self.assertNotIn('uid',encoded.lower())
            self.assertEqual(value['groups'][0]['order_usd'],'501')
            service.client.read=lambda body:{'status':'unavailable','reason':'upstream_offline'}
            stale=service.tool_read('admin',tracking)
            self.assertEqual(stale['status'],'available')
            self.assertEqual(stale['refresh_status'],'available')  # 15-minute captured snapshot remains current
            with service.store.db() as db:
                db.execute("UPDATE history_coverage SET observed_at='2026-10-01T00:00:00+00:00' WHERE track_id=?",(tracking,))
            stale=service.tool_read('admin',tracking)
            self.assertEqual(stale['status'],'available')
            self.assertEqual(stale['refresh_status'],'unavailable')
            self.assertTrue(stale['stale'])

    def test_conversation_wrapper_only_one_opaque_argument(self):
        class Book:
            def call(self,name,args):raise AssertionError('should intercept')
            def register(self,name,args,value,source,captured_at):return value
        class Controller:
            def tool_read(self,user,tracking_id):
                self.args=(user,tracking_id)
                return {'status':'available','tracking_id':tracking_id,'groups':[]}
        book=Book();controller=Controller()
        attach_customer_tracking(book,controller,'admin')
        ident='f'*32
        self.assertEqual(book.call('fc.query_customer_tracking',{'tracking_id':ident})['tracking_id'],ident)
        self.assertEqual(controller.args,('admin',ident))
        with self.assertRaises(ValueError):book.call('fc.query_customer_tracking',{'tracking_id':ident,'email':'secret@example.invalid'})

if __name__=='__main__':unittest.main()
