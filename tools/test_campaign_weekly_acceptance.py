"""Isolated acceptance-helper tests. Run: python -m unittest discover -s tools -p test_campaign_weekly_acceptance.py"""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent
OP='8dd85cc4-32c3-4cb7-9af1-ae46dea6aa7a'
def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def write(path,value):
    path.write_text(json.dumps(value),encoding='utf-8')

class AcceptanceHelpers(unittest.TestCase):
    def test_model_receipt_is_operation_scoped_redacted_and_readonly(self):
        with tempfile.TemporaryDirectory(prefix='campaign-receipt-test-') as temp:
            root=Path(temp);tasks=root/'tasks.sqlite3';daily=root/'daily.sqlite3'
            conn=sqlite3.connect(tasks)
            try:
                conn.execute('CREATE TABLE campaign_recommendations(owner,operation_id,state,task_id,run_id,network_started,result)')
                conn.execute('INSERT INTO campaign_recommendations VALUES(?,?,?,?,?,?,?)',('PRIVATE_OWNER',OP,'completed','task-1','run-1',1,json.dumps({'receipt':{'model':'gpt-6.1-sol','usage':{'input_tokens':12,'output_tokens':5,'total_tokens':17}},'prompt':'SECRET_PROMPT','session':'SECRET_SESSION'})))
                conn.commit()
            finally:conn.close()
            conn=sqlite3.connect(daily)
            try:
                conn.execute('CREATE TABLE model_calls(fingerprint,state,content)')
                conn.execute('CREATE TABLE hermes_reservations(fingerprint,owner,task,turn,policy)')
                for fp,owner,task in [('f1','PRIVATE_OWNER','task-1'),('f2','OTHER_OWNER','other-task')]:
                    conn.execute('INSERT INTO model_calls VALUES(?,?,?)',(fp,'succeeded',json.dumps({'model':'gpt-6.1-sol','usage':{'prompt_tokens':12,'completion_tokens':5,'total_tokens':17},'message':'SECRET_MODEL_OUTPUT','model_validation':{'status':'provider_metadata_confirmed','forwarded_verified':True,'response_model':'gpt-6.1-sol'}})))
                    conn.execute('INSERT INTO hermes_reservations VALUES(?,?,?,?,?)',(fp,owner,task,0,json.dumps({'model':'gpt-6.1-sol'})))
                conn.commit()
            finally:conn.close()
            before={p.name:p.read_bytes() for p in root.iterdir()}
            cmd=[sys.executable,str(ROOT/'campaign_weekly_model_receipt_readonly.py'),'--operation-id',OP,'--tasks-db',str(tasks),'--daily-db',str(daily)]
            result=subprocess.run(cmd,capture_output=True,text=True,check=True);value=json.loads(result.stdout)
            self.assertEqual(value['ledger_call_count'],1);self.assertEqual(value['receipt_usage']['total_tokens'],17)
            self.assertEqual(value['ledger_calls'][0]['usage']['total_tokens'],17);self.assertTrue(value['ledger_calls'][0]['forwarded_verified'])
            for secret in ('SECRET','PRIVATE_OWNER','OTHER_OWNER','other-task'):self.assertNotIn(secret,result.stdout+result.stderr)
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
            absent=cmd.copy();absent[absent.index(OP)]='12345678-1234-4234-8234-123456789abc'
            missing=subprocess.run(absent,capture_output=True,text=True)
            self.assertEqual(missing.returncode,2);self.assertEqual(json.loads(missing.stdout)['reason'],'operation_missing_or_ambiguous')
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})

    def test_center_readback_and_publication_change_detection(self):
        with tempfile.TemporaryDirectory(prefix='campaign-center-test-') as temp:
            root=Path(temp);center=root/'data'/'center';pub=root/'public'
            center.mkdir(parents=True);pub.mkdir();(center/'weekly-plans').mkdir();(center/'operations').mkdir()
            key=lambda i:'model-266-1327-'+str(i)
            models={key(i):dict(key=key(i),model_id=str(i),kind='sbc' if i==7 else 'player',title='Fixture '+str(i),platforms={code:dict(state='verified',product_ref=dict(site_id='266',game_id='1327',model_id=str(i),goods_id=str(100*i+n))) for n,code in enumerate(['ps','xbox','pc'])}) for i in range(1,8)}
            layout=dict(weekly=[key(i) for i in [1,2,3]],trio=[key(i) for i in [4,5,6]],sbc=[key(7)],defaultCore=key(7),routes={key(7):dict(picks=[key(1),key(2)],alternatives=[key(3)])})
            draft=dict(pages=[dict(page_id=x,title=x) for x in ['fc27-trio','fc27-weekly','fc27-sbc','seasonal-vault']],fc_layout=layout,fc_models=models)
            original=dict(revision=1,draft=draft,published=None,updated_by='PRIVATE_OWNER')
            write(center/'state.json',original);write(pub/'current.json',{'fixture':'unchanged'})
            command=['node',str(ROOT/'campaign_weekly_readonly_acceptance.mjs')]
            opts=['--data-dir',str(root/'data'),'--public-dir',str(pub)]
            captured=subprocess.run(command+['snapshot']+opts,capture_output=True,text=True,check=True)
            self.assertNotIn('PRIVATE_OWNER',captured.stdout);(root/'before.json').write_text(captured.stdout,encoding='utf-8')
            request=dict(revision=1,draft=draft,model_imports=[]);signature=digest(dict(kind='save',**request))
            current=dict(revision=2,draft=draft,published=None,updated_by='PRIVATE_OWNER',last_operation=dict(kind='save',operation_id=OP,hash=signature))
            write(center/'state.json',current)
            source=dict(scout_model_ids=['1','2','3'],trio_player_ids=['4','5','6'],sbc_model_ids=['7'],observations=[dict(goods_complete=True)],evidence={})
            write(center/'weekly-plans'/(OP+'.json'),dict(base_revision=1,save_request=request,source=source,owner='PRIVATE_OWNER'))
            write(center/'operations'/(OP+'.json'),dict(hash=signature,result=current))
            verify=command+['verify','--operation-id',OP,'--before',str(root/'before.json')]+opts
            baseline={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            checked=subprocess.run(verify,capture_output=True,text=True,check=True);value=json.loads(checked.stdout)
            self.assertEqual(value['status'],'checks_passed');self.assertTrue(value['checks']['three_platform_identities']);self.assertTrue(value['checks']['sbc_has_multiple_choices'])
            self.assertNotIn('PRIVATE_OWNER',checked.stdout);self.assertEqual(baseline,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})
            write(pub/'current.json',{'fixture':'changed'})
            changed=subprocess.run(verify,capture_output=True,text=True);self.assertEqual(changed.returncode,2);self.assertFalse(json.loads(changed.stdout)['checks']['published_hash_unchanged'])
            write(pub/'current.json',{'fixture':'unchanged'});current['draft']['pages'][-1]['title']='Changed unrelated page';write(center/'state.json',current)
            changed=subprocess.run(verify,capture_output=True,text=True);self.assertEqual(changed.returncode,2);self.assertFalse(json.loads(changed.stdout)['checks']['other_pages_hash_unchanged'])

if __name__=='__main__':unittest.main()
