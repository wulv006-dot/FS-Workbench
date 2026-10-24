import ast,sys,types,unittest
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
from unittest.mock import patch

node=next(n for n in ast.parse((Path(__file__).parents[1]/'source/price_writer.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='confirm_sync_recipient')

class RecipientTests(unittest.TestCase):
    def check(self,prices=('0.1034','0.1034','0.0868'),identity='chenchao',authenticated=True,unstable=False):
        count=[0];calls=[]
        def read(manager,platform,site):
            self.assertEqual(site,266);count[0]+=1
            return {'unit_price':prices[('PS','XBOX','PC').index(platform)],'more':{'price':[str(count[0]) if unstable else '10.34']}}
        session=types.SimpleNamespace(SessionManager=lambda config:types.SimpleNamespace(ensure=lambda:authenticated),read_private_config=lambda:{},allowed_admin_usernames=lambda:['chenchao'])
        coin=types.SimpleNamespace(api=lambda *args:{'adminInfo':{'username':identity}},read_row=read,PRODUCTS={'PS':1,'XBOX':2,'PC':3})
        env={'sys':sys,'datetime':datetime,'timezone':timezone,'same_money':lambda a,b:Decimal(a)==Decimal(b),'current_cycle_quote':lambda *args:calls.append(args)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'recipient','exec'),env)
        record={'preview_id':'original','selected':['PS','XBOX'],'automation_policy_revision':40,'targets':[{'platform':p,'quote':q} for p,q in zip(('PS','XBOX','PC'),('0.1034','0.1034','0.0868'))]}
        with patch.object(sys,'path',list(sys.path)),patch.dict(sys.modules,{'p2pah_session_service':session,'coin_all_sync_job':coin}),patch('time.sleep'):
            result=env['confirm_sync_recipient'](record)
            self.assertEqual(sys.path[0],'/usr/local/bin')
        self.assertEqual(len(calls),2);self.assertEqual(count[0],6);self.assertIs(result['sync_replayed'],False)
        return result
    def test_two_stable_get_rounds_confirm_without_sync(self):self.check()
    def test_old_recipient_price_cannot_confirm(self):
        with self.assertRaisesRegex(ValueError,'price_unconfirmed'):self.check(prices=('0.0984','0.0984','0.0868'))
    def test_wrong_identity_cannot_confirm(self):
        with self.assertRaisesRegex(ValueError,'identity_invalid'):self.check(identity='other')
    def test_missing_session_cannot_confirm(self):
        with self.assertRaisesRegex(ValueError,'session_unavailable'):self.check(authenticated=False)
    def test_changing_tiers_cannot_confirm(self):
        with self.assertRaisesRegex(ValueError,'unstable'):self.check(unstable=True)

if __name__=='__main__':unittest.main()
