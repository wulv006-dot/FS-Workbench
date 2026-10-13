from concurrent.futures import Future
from contextlib import contextmanager
from types import SimpleNamespace
from pathlib import Path
import sqlite3,tempfile,unittest
from unittest.mock import patch
from fs_evidence import build_book
from research import ResearchBook,RESEARCH_NAMES,tool_schemas
from runs_contract import WIRE_TOOLS
from test_research import dataset
from admin_order_capabilities_20261014.capabilities import checked_query,result

CONFIG={'enabled':True,'game_id':1327,'main_site_id':266}
QUERY={'kind':'native_loss','profile':'FC27','start':'2026-10-05','end':'2026-10-11'}

class InlinePool:
    def submit(self,fn,*args):
        future=Future();future.set_result(fn(*args));return future

class CapabilityWiringTests(unittest.TestCase):
    def test_closed_tool_registered_and_data_catalog_separates_capture_gaps(self):
        self.assertIn('fc.query_capability',RESEARCH_NAMES)
        self.assertIn('mcp__fcro__fc_query_capability',WIRE_TOOLS)
        schema=next(s['function'] for s in tool_schemas() if s['function']['name']=='mcp__fcro__fc_query_capability')
        self.assertFalse(schema['parameters']['additionalProperties'])
        book=ResearchBook(dataset(),CONFIG,{'start':'2026-10-05','end':'2026-10-11'},capability=lambda q:result(checked_query(q,CONFIG),'available',source_orders=10))
        catalog=book.call('fc.get_data_catalog',{})['data']
        self.assertTrue(catalog['capabilities']['unprojected_is_not_backend_missing'])
        self.assertIn('capture only',catalog['unavailable_field_scope'])
        self.assertEqual(book.call('fc.query_capability',QUERY)['data']['source_orders'],10)
        with self.assertRaises(ValueError):book.call('fc.query_capability',dict(QUERY,url='https://fixture.invalid'))

    def test_user_off_blocks_already_pinned_success_before_source_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'daily.db'
            class Daily:
                @contextmanager
                def db(self):
                    conn=sqlite3.connect(path)
                    try:
                        with conn:yield conn
                    finally:conn.close()
            daily=Daily()
            with daily.db() as db:db.execute('CREATE TABLE reports(job_id INTEGER PRIMARY KEY,day TEXT,content TEXT)')
            detail=SimpleNamespace(config=dict(CONFIG),pool=InlinePool())
            bundle={'version':'fixture','sha256':'a'*64,'methods_text':'methods','governance_text':'governance'}
            source=lambda q:result(checked_query(q,CONFIG),'available',source_orders=10)
            with patch('fs_evidence.source_capture',return_value=(dataset(),dict(CONFIG))),patch('fs_evidence.load_bundle',return_value=bundle),patch('admin_order_capabilities_20261014.fs_reader.admin_read',side_effect=source) as reader:
                book=build_book(detail,daily,None,None,'2026-10-05','2026-10-11',Path(temp),'owner')
                self.assertEqual(book.call('fc.query_capability',QUERY)['data']['status'],'pending')
                success=book.call('fc.query_capability',QUERY)
                self.assertEqual(success['data']['source_orders'],10)
                detail.config['enabled']=False
                denied=book.call('fc.query_capability',QUERY)
                self.assertEqual(denied['data']['reason'],'fc_detail_disabled')
                self.assertNotIn('source_orders',denied['data']);self.assertEqual(reader.call_count,1)

if __name__=='__main__':unittest.main()
