import importlib.util,json,os,tempfile,unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

SOURCE=Path(__file__).parents[2]/'app/analytics/weekly-commerce-install.py'
spec=importlib.util.spec_from_file_location('weekly_install',SOURCE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Publisher:
    def __init__(self):self.locked=False;self.writes=[];self.fail_final=False
    @contextmanager
    def locks(self,root):
        self.locked=True
        try:yield
        finally:self.locked=False
    def atomic(self,file,raw,mode):
        assert self.locked
        if self.fail_final and file.name=='receipt.json' and json.loads(raw).get('state')=='installed':raise OSError('interrupted after policy installation')
        file.parent.mkdir(parents=True,exist_ok=True);temp=file.with_suffix('.tmp');temp.write_bytes(raw);os.chmod(temp,mode);temp.replace(file);self.writes.append(file)

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.pub=Publisher();self.op=str(uuid4());self.proposal=str(uuid4())
        price=lambda mid:dict(model_ref={'site_id':'266','game_id':'1327','model_id':mid},quantity_value='1',quantity_unit='item')
        product=lambda mid:dict(key='p'+mid,product_ref={'game_id':'1327','model_id':mid},platform={'code':'ps'})
        self.old=dict(other_game={'unchanged':True},admin_reference_prices={'entries':[price('99')]},native_catalog={'products':[product('99')],'model_contracts':{'99':{}}},native_checkout={'bindings':[]})
        self.new=json.loads(json.dumps(self.old));self.new['admin_reference_prices']['entries'].append(price('22'));self.new['native_catalog']['products'].append(product('22'));self.new['native_catalog']['model_contracts']['22']={}
        self.write(m.TARGET,m.encoded(self.old));self.write(m.CENTER,m.encoded({'revision':7}))
        candidate=m.encoded(self.new);self.write(m.PROPOSALS+'/'+self.proposal+'.policy.json',candidate)
        p=dict(proposal_id=self.proposal,owner='alice',can_publish=True,candidate_sha=m.sha(candidate),policy_before_sha=m.sha(m.encoded(self.old)),revision=7,draft_hash='a'*64,expires_at='2026-11-09T10:05:00Z',resolved_models=[{'model_id':'22'}])
        raw=m.encoded(p);self.write(m.PROPOSALS+'/'+self.proposal+'.json',raw)
        self.request=dict(action='inspect',confirm=False,operation_id=self.op,proposal_id=self.proposal,proposal_sha=m.sha(raw),owner='alice')
    def write(self,relative,raw):
        file=self.root/relative.lstrip('/');file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(raw);os.chmod(file,0o600);return file
    def run_install(self,**changes):return m.install(dict(self.request,**changes),root=self.root,publisher=self.pub,now=lambda:0)
    def test_default_inspect_is_read_only_and_confirmation_installs_once_with_original_backup(self):
        before=(self.root/m.TARGET.lstrip('/')).read_bytes();self.assertEqual(self.run_install()['state'],'validated_not_installed');self.assertEqual(self.pub.writes,[])
        self.assertEqual(self.run_install(action='install',confirm=True)['state'],'installed')
        backup=self.root/m.RECEIPTS.lstrip('/')/self.op/'policy.before.json';self.assertEqual(backup.read_bytes(),before)
        count=len(self.pub.writes);self.assertEqual(self.run_install(action='install',confirm=True)['state'],'already_installed');self.assertEqual(len(self.pub.writes),count)
    def test_interrupted_receipt_recovers_same_id_without_reinstall_even_after_expiry(self):
        self.pub.fail_final=True
        with self.assertRaises(OSError):self.run_install(action='install',confirm=True)
        target=self.root/m.TARGET.lstrip('/');self.assertEqual(sum(p==target for p in self.pub.writes),1)
        self.pub.fail_final=False
        value=m.install(dict(self.request,action='install',confirm=True),root=self.root,publisher=self.pub,now=lambda:9999999999)
        self.assertEqual(value['state'],'already_installed');self.assertEqual(sum(p==target for p in self.pub.writes),1)
    def test_revision_and_policy_conflicts_never_install_or_backup(self):
        self.write(m.CENTER,m.encoded({'revision':8}))
        with self.assertRaisesRegex(ValueError,'draft_revision_conflict'):self.run_install(action='install',confirm=True)
        self.assertEqual(self.pub.writes,[])
        self.write(m.CENTER,m.encoded({'revision':7}));self.write(m.TARGET,b'{}')
        with self.assertRaisesRegex(ValueError,'policy_revision_conflict'):self.run_install(action='install',confirm=True)
    def test_unrelated_policy_or_retained_halloween_price_removal_is_rejected(self):
        p={'resolved_models':[{'model_id':'22'}]};bad=json.loads(json.dumps(self.new));bad['admin_reference_prices']['entries'].pop(0)
        with self.assertRaisesRegex(ValueError,'unrelated_policy_changed'):m.preserve(self.old,bad,p)
        bad=json.loads(json.dumps(self.new));bad['other_game']={}
        with self.assertRaisesRegex(ValueError,'unrelated_policy_changed'):m.preserve(self.old,bad,p)
    def test_missing_confirmation_never_installs(self):
        with self.assertRaisesRegex(ValueError,'explicit_confirmation_required'):self.run_install(action='install',confirm=False)
        self.assertEqual(self.pub.writes,[])

if __name__=='__main__':unittest.main()
