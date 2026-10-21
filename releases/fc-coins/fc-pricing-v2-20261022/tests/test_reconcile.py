from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('empty_recovery',Path(__file__).parents[1]/'deploy/reconcile_empty_all.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


class EmptyRecovery(unittest.TestCase):
    def setUp(self):
        self.audit=dict(execution_id=r.EXECUTION,status='PARTIAL',stage='stopped',error='coin_backend_request_rejected',sync_confirmed=True,changed=['PS','XBOX','PC'],after={'rows':[dict(platform=p,b2c='.12',costPrice='.6') for p in ('PS','XBOX','PC')]},targets=[dict(platform=p,quote='.12',targetCost='.6') for p in ('PS','XBOX','PC')])
        self.record=dict(execution_id=r.EXECUTION,status='needs_reconcile',steps=[],source_confirmation=dict(status='stopped',reason='coin_backend_request_rejected',rounds=[dict(observations=[dict(path='/admin/goods.Goods/edit?id=163329311',response_code=302,http_status=200)])]))

    def test_only_exact_empty_read_rejection_can_continue(self):
        r.empty_auth_failure(self.audit,self.record)
        for change in ('dispatch','other_failure','wrong_identity','unconfirmed_order','unknown_response'):
            a,b=deepcopy(self.audit),deepcopy(self.record)
            if change=='dispatch':b['steps']=[{'status':'dispatching'}]
            elif change=='other_failure':a['error']='TimeoutError'
            elif change=='wrong_identity':b['execution_id']='another'
            elif change=='unconfirmed_order':a['after']['rows'][0]['b2c']='.13'
            else:b['source_confirmation']['rounds'][0]['observations'][0]['response_code']=None
            with self.subTest(change=change),self.assertRaises(ValueError):r.empty_auth_failure(a,b)
