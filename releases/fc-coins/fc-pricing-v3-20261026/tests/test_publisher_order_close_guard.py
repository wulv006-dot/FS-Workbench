"""Exercise the original publisher guard functions against a real read-only ledger."""
import ast,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
from fc_pricing_v3.order_close import TERMINAL_LEDGER_STATUS

def function(path,name,scope):
    node=next(n for n in ast.parse(path.read_text('utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),scope)
    return scope[name]

class PublisherOrderCloseGuard(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'v3').mkdir()
        self.db=sqlite3.connect(self.root/'v3/control.sqlite3');self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE operations(id TEXT PRIMARY KEY, body TEXT)')
        self.execution='5cf3f55c-0305-4c1d-a169-a6e259a83536'
        self.read=function(SOURCE/'price_writer.py','ledger_operation_status',dict(ROOT=self.root,json=json))
        self.resolved=function(SOURCE/'automation_tick.py','resolved_execution',{})
        self.module=patch.dict(sys.modules,price_writer=SimpleNamespace(ledger_operation_status=self.read));self.module.start();self.addCleanup(self.module.stop)
    def ledger(self,status):
        self.db.execute('INSERT OR REPLACE INTO operations VALUES(?,?)',(self.execution,json.dumps({'status':status})));self.db.commit()
    def audit(self,**changes):
        return dict(dict(status='ORDER_ADMIN_CONFIRMED',ledger_status='COMPLETED',execution_id=self.execution),**changes)
    def test_only_matching_terminal_ledger_readback_resolves_order_admin_receipt(self):
        for status in TERMINAL_LEDGER_STATUS:
            with self.subTest(status=status):
                self.ledger(status);self.assertTrue(self.resolved(self.audit(ledger_status=status)))
    def test_missing_or_conflicting_ledger_and_unknown_audit_still_block(self):
        self.assertFalse(self.resolved(self.audit()))
        for status in ('UNKNOWN','RUNNING','NO_CHANGE'):
            self.ledger(status);self.assertFalse(self.resolved(self.audit()))
        self.ledger('COMPLETED')
        for changes in ({'execution_id':None},{'execution_id':'different-operation'},{'ledger_status':None},{'ledger_status':'UNKNOWN'},{'status':'PARTIAL'}):
            with self.subTest(changes=changes):self.assertFalse(self.resolved(self.audit(**changes)))
    def test_existing_receipts_and_prewrite_rejection_keep_original_behavior(self):
        for status in ('CONFIRMED','RESTORED','CHECK_ONLY'):
            self.assertTrue(self.resolved({'status':status}))
        self.assertTrue(self.resolved({'status':'FAILED_BEFORE_WRITE','changed':False}))
        self.assertFalse(self.resolved({'status':'FAILED_BEFORE_WRITE','changed':True}))

if __name__=='__main__':unittest.main()
