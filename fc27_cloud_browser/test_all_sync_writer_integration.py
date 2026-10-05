from copy import deepcopy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import price_writer as writer

ID1='00000000-0000-4000-8000-000000000001'
ID2='00000000-0000-4000-8000-000000000002'


class WriterIntegrationTest(unittest.TestCase):
    def execute(self, baseline_error=None, check_only=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'executions').mkdir()
            before={'rows':[{'platform':p,'costPrice':'1','b2c':'0.124'} for p in writer.PLATFORMS]}
            current=deepcopy(before)
            targets=[{'platform':p,'id':str(i),'targetCost':'1.1','quote':'0.1252'}
                     for i,p in enumerate(writer.PLATFORMS)]
            preview={'run_id':ID1,'backend_before':before,'targets':targets}
            policy={'revision':18}
            events=[]
            class Page:
                def goto(self,*args,**kw):pass
                def reload(self,*args,**kw):pass
                def close(self):pass
                def evaluate(self,code,args=None):
                    if 'setCost' in code:
                        next(r for r in current['rows'] if r['platform']==args[0])['costPrice']=args[3]
                    elif 'clickSync' in code:
                        events.append('mmoexp_sync')
                        for row in current['rows']:row['b2c']='0.1252'
                        return {'success':True,'message':'confirmed fixture'}
            page=Page()
            browser=types.SimpleNamespace(contexts=[types.SimpleNamespace(new_page=lambda:page)])
            playwright=types.SimpleNamespace(chromium=types.SimpleNamespace(connect_over_cdp=lambda *a,**k:browser))
            class Context:
                def __enter__(self):return playwright
                def __exit__(self,*args):pass
            def mirror(record,*args):
                events.append('all_sync')
                self.assertEqual(record['status'],'PARTIAL')
                self.assertEqual(record['after']['rows'],current['rows'])
                self.assertEqual(events,['mmoexp_sync','all_sync'])
                if baseline_error:raise ValueError(baseline_error)
                record['all_baseline']={'status':'confirmed'}
                return {'status':'confirmed'}
            with ExitStack() as stack:
                for name,value in {'ROOT':root,'load_authorized':lambda _: (preview,{}),
                    'load_policy':lambda:policy,'check_write':lambda *a,**k:[],
                    'sync_playwright':lambda:Context(),'read_backend':lambda *a,**k:deepcopy(current),
                    'same_backend':lambda *a:True,'revalidate_evidence':lambda *a:None,
                    'expected_state':lambda *a:None,'mirror_confirmed':mirror}.items():
                    stack.enter_context(patch.object(writer,name,value))
                if baseline_error:
                    with self.assertRaisesRegex(ValueError,baseline_error):
                        writer.execute(ID1,ID2,'fixture',list(writer.PLATFORMS),policy_revision=18)
                    audit=json.loads((root/'executions'/(ID2+'.json')).read_text())
                    self.assertEqual(audit['status'],'PARTIAL')
                else:
                    result=writer.execute(ID1,ID2,'fixture',list(writer.PLATFORMS),policy_revision=18,
                                          check_only=check_only)
                    self.assertEqual(result['status'],'CHECK_ONLY' if check_only else 'CONFIRMED')
            return events
    def test_confirmation_waits_for_all_baseline(self):
        self.assertEqual(self.execute(),['mmoexp_sync','all_sync'])
    def test_failed_all_baseline_cannot_confirm_or_release_existing_incomplete_execution_gate(self):
        self.assertEqual(self.execute('coin_all_readback_mismatch'),['mmoexp_sync','all_sync'])
    def test_read_only_check_never_calls_either_sync(self):
        self.assertEqual(self.execute(check_only=True),[])


if __name__=='__main__':unittest.main()
