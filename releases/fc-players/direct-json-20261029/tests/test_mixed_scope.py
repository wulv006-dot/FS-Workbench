from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile,unittest
from unittest.mock import Mock
from test_direct_import import load
service=load("new_card_service")
prepare_plan=service.prepare_plan
verify_manual_new_card_scope=service.verify_manual_new_card_scope
execute_confirmed_plan=service.execute_confirmed_plan
from player_web.settings import Settings
from player_web.repository import Repository,StateError

class Backend:
    authenticated=True
    def __init__(self):
        self.rows={100+i:{'id':100+i,'gid':1327,'cid':9627,'futbin_id':str(i),'tid':[],
                    'is_rec':0,'status':1,'title':'Existing '+str(i)} for i in range(9,35)}
        self.writes=[]
    def list_models(self,**kwargs):return SimpleNamespace(total=len(self.rows),rows=tuple(self.rows.values()))
    def get_model(self,mid):return self.rows[mid]
    def list_tags(self,**kwargs):return ({'id':12307,'name':'Newest'},)
    def single_edit(self,payload):
        self.writes.append(payload)
        self.rows[payload['id'][0]]['tid']=payload['tid']
        return {'code':1}

class MixedScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.settings=Settings(Path(self.temp.name),'https://source.invalid','https://admin-api.p2pah.cn','https://fs.invalid',
           '/tools/fc27-players',False,True,3,5000,3,manual_new_cards_enabled=True,manual_existing_add_tags_enabled=True)
        self.repo=Repository(self.settings.data_root/'db/control.sqlite3');self.repo.initialize();self.client=Backend()
        self.collection=self.repo.save_collection('source',{'days_new':'3'},[{'futbin_id':str(i),'rating':90,'name':'P'+str(i)} for i in range(1,35)])
    def scope(self):
        return {'upload_futbin_ids':[str(i) for i in range(1,9)],'tag_futbin_ids':[str(i) for i in range(1,35)],
          'recommend_futbin_ids':[],'scope_ids':[str(i) for i in range(1,35)],'existing_model_map':{str(i):100+i for i in range(9,35)}}
    def test_exact_screenshot_eight_new_and_34_tags_allowed_by_two_separate_flags(self):
        verify_manual_new_card_scope(self.settings,self.scope())
        with self.assertRaisesRegex(StateError,'NEW_CARD_SCOPE_REQUIRED'):
            verify_manual_new_card_scope(replace(self.settings,manual_existing_add_tags_enabled=False),self.scope())
    def test_foreign_scope_missing_binding_and_existing_recommend_still_rejected(self):
        for plan in ({**self.scope(),'scope_ids':['999',*self.scope()['scope_ids']]},
                     {**self.scope(),'existing_model_map':{}},
                     {**self.scope(),'recommend_futbin_ids':['9']}):
            with self.assertRaisesRegex(StateError,'NEW_CARD_SCOPE_REQUIRED'):verify_manual_new_card_scope(self.settings,plan)
    def test_original_eight_unknowns_show_preview_conflicts_without_export_or_new_execution(self):
        old=self.repo.save_plan('operator',{'scope_ids':[str(i) for i in range(1,9)]})
        original,_=self.repo.confirm(old['plan_id'],'operator',old['plan_digest'],write_enabled=True)
        self.repo.set_execution(original,'needs_reconcile','unknown',{'original_error':'HTTP500'})
        source=Mock()
        plan=prepare_plan(self.settings,self.repo,self.client,'operator',self.collection,
             [str(i) for i in range(1,9)],[str(i) for i in range(1,35)],[],[12307],source_client=source)
        self.assertEqual(len(plan['scope_ids']),34);self.assertEqual(len(plan['existing_model_map']),26)
        self.assertEqual(plan['blockers'],['UNRESOLVED_IMPORT'])
        self.assertEqual({row['execution_id'] for row in plan['active_conflicts']},{original})
        self.assertEqual(len(plan['active_conflicts']),8)
        source.export_players.assert_not_called()
        with self.assertRaisesRegex(StateError,'PLAN_BLOCKED'):self.repo.confirm(plan['plan_id'],'operator',plan['plan_digest'],write_enabled=True)
        self.assertEqual(self.repo.get_execution(original,'operator')['status'],'needs_reconcile')
        self.assertEqual(self.client.writes,[])
    def test_existing_tags_only_can_prepare_confirm_and_execute_without_new_or_price_writes(self):
        plan=prepare_plan(self.settings,self.repo,self.client,'operator',self.collection,[],['9','10'],[],[12307])
        self.assertEqual(plan['import_mode'],'existing_actions_only');self.assertEqual(plan['blockers'],[])
        execution,_=self.repo.confirm(plan['plan_id'],'operator',plan['plan_digest'],write_enabled=True)
        execute_confirmed_plan(self.settings,self.repo,self.client,execution,self.repo.get_plan(plan['plan_id'],'operator'))
        self.assertEqual(self.repo.get_execution(execution,'operator')['status'],'completed_readback')
        self.assertEqual(self.client.writes,[{'tid':[12307],'id':[109]},{'tid':[12307],'id':[110]}])
        self.assertFalse(self.settings.write_enabled)
