"""Offline range configuration contracts; roots and HTTP server are isolated."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
from http.server import ThreadingHTTPServer
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

import automation_policy as policy
import fc27_quote_engine as engine
import fc27_cloud_api as api
import server_quote_job as quotes

HERE=Path(__file__).resolve().parent
FIXTURES=json.loads((HERE/'audit-vectors.json').read_text())['cases']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def rules(tier='at_least_40', low='2', high='4'):
    value=engine.default_discount_rules()
    value['bands'][tier]={'min_discount_pct':low,'max_discount_pct':high}
    return value

def settings(value):
    return {key:value[key] for key in ('system_enabled','mode','interval_minutes','platforms','minimum_gross_margin_pct')}

class RangeValidationTests(unittest.TestCase):
    def test_default_full_results_match_old_engine(self):
        spec=importlib.util.spec_from_file_location('before_engine',HERE/'before_engine.py')
        before=importlib.util.module_from_spec(spec);spec.loader.exec_module(before)
        for case in FIXTURES:
            with self.subTest(case=case['name']):
                self.assertEqual(engine.calculate(case['evidence']),before.calculate(case['evidence']))
                self.assertEqual(engine.calculate(case['evidence'],{'pricing_rules':engine.default_discount_rules()}),case['expected'])

    def test_schema_exact_bands_and_fixed_thresholds(self):
        for mutation in [lambda x:x.update(schema_version=True),lambda x:x.update(schema_version=2),
                         lambda x:x.update(thresholds=[20,30,40]),lambda x:x['bands'].pop('below_20'),
                         lambda x:x['bands'].update(extra={'min_discount_pct':'0','max_discount_pct':'1'}),
                         lambda x:x['bands']['30_to_40'].update(margin_lower='30')]:
            value=rules();mutation(value)
            with self.assertRaises(ValueError):engine.normalize_discount_rules(value)

    def test_strict_percentage_limits_precision_and_min_max(self):
        for bad in ['',None,True,1,1.5,'NaN','Infinity','1e0','-1','10.01','1.001',' 1','1%','.5']:
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                engine.normalize_discount_rules(rules(low=bad))
        with self.assertRaisesRegex(ValueError,'range_invalid'):
            engine.normalize_discount_rules(rules(low='5',high='4'))
        self.assertEqual(engine.normalize_discount_rules(rules(low='01',high='4'))['bands']['at_least_40']['min_discount_pct'],'1.00')

    def test_deterministic_clip_and_both_exact_bounds(self):
        for name,low,high,requested in [('average3','4','6','4.00'),('average3','1','2','2.00'),
                                        ('average3','2','4','3.00'),('exact30','1','6','6.00'),
                                        ('exact20','6','8','6.00'),('just_below20','1','2','1.00')]:
            case=next(x for x in FIXTURES if x['name']==name);tier=case['expected']['rows'][0]['pricing_tier']
            edits={'pricing_rules':rules(tier,low,high)}
            result=engine.calculate(case['evidence'],edits)
            self.assertEqual(result['rows'][0]['requested_discount_pct'],requested)
            self.assertEqual(result,engine.calculate(case['evidence'],edits))

    def test_cost_floor_overrides_requested_minimum_without_faking_success(self):
        case=next(x for x in FIXTURES if x['name']=='floor_overrides_target')
        row=engine.calculate(case['evidence'],{'pricing_rules':rules(low='8',high='9')})['rows'][0]
        self.assertEqual(row['requested_discount_pct'],'9.00')
        self.assertTrue(row['profit_floor_applied'])
        self.assertLess(float(row['lootbar_reduction_pct']),8)
        self.assertGreaterEqual(float(row['gross_margin_pct']),10)

    def test_missing_competitor_and_cost_are_fail_closed(self):
        for field in ('cost','offer'):
            e=copy.deepcopy(FIXTURES[0]['evidence'])
            if field=='cost':del e['costs']['PS']
            else:del e['offers']['PS']['IGGM']
            result=engine.calculate(e,{'pricing_rules':rules()})
            self.assertIsNone(result['rows'][0]['proposal'])
            self.assertIsNone(result['rows'][1]['auto_proposal'])

    def test_write_gate_recomputes_non_default_rules_and_rejects_tampering(self):
        e=FIXTURES[0]['evidence'];r=engine.normalize_discount_rules(rules())
        p={**policy.initial_policy(),'revision':1,'system_enabled':True,'mode':'auto','pricing_rules':r}
        edits={'minimum_gross_margin_pct':'10','pricing_rules':r}
        q={'automation_policy_revision':1,'pricing_rules_schema_version':1,'pricing_rules':r,
           'pricing_rules_sha256':engine.discount_rules_sha256(r),'evidence':e,'edits':edits,
           'result':engine.calculate(e,edits)}
        self.assertEqual(policy.check_write(p,q,['PS','XBOX','PC'],automatic=True),[])
        bad=copy.deepcopy(q);bad['result']['rows'][0].update(proposal='0.9500',target_page_usd='95.00')
        with self.assertRaisesRegex(ValueError,'automatic_tier_rule:PS'):policy.check_write(p,bad,['PS'],automatic=True)
        for key,value in [('pricing_rules_sha256','bad'),('pricing_rules_schema_version',2),
                           ('pricing_rules',engine.default_discount_rules())]:
            bad=copy.deepcopy(q);bad[key]=value
            with self.assertRaisesRegex(ValueError,'changed_since_quote'):policy.check_write(p,bad,['PS'],automatic=True)
        bad=copy.deepcopy(q);bad['edits']['pricing_rules']=engine.default_discount_rules()
        with self.assertRaisesRegex(ValueError,'changed_since_quote'):policy.check_write(p,bad,['PS'],automatic=True)
        bad=copy.deepcopy(q);del bad['pricing_rules']
        with self.assertRaisesRegex(ValueError,'changed_since_quote'):policy.check_write(p,bad,['PS'],automatic=True)

    def test_xbox_uses_ps_range_and_retains_independent_floor_block(self):
        case=next(x for x in FIXTURES if x['name']=='xbox_floor_blocks_follow')
        r=engine.calculate(case['evidence'],{'pricing_rules':rules()})['rows']
        self.assertEqual(r[1]['proposal'],r[0]['proposal']);self.assertTrue(r[1]['margin_below_minimum'])
        self.assertEqual(r[1]['auto_price_source'],'PS')

class IsolatedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.file=self.root/'config'/'automation.json';self.file.parent.mkdir()
        self.value={**policy.initial_policy(),'revision':23,'system_enabled':False,'mode':'manual',
                    'interval_minutes':91,'platforms':['PS','PC']}
        self.file.write_text(json.dumps(self.value));self.before=self.file.read_bytes()
        change=patch.object(policy,'POLICY_FILE',self.file);change.start();self.addCleanup(change.stop)
        change=patch.object(policy,'ROOT',self.root);change.start();self.addCleanup(change.stop)
        self.audit=self.file.parent/'automation-events.jsonl'

    def test_legacy_read_virtual_defaults_without_writing_or_revision_change(self):
        legacy=copy.deepcopy(self.value);del legacy['pricing_rules'];self.file.write_text(json.dumps(legacy))
        before=self.file.read_bytes();p=policy.load_policy()
        self.assertEqual(p['pricing_rules'],engine.default_discount_rules());self.assertEqual(p['revision'],23)
        self.assertEqual(self.file.read_bytes(),before);self.assertFalse(self.audit.exists())
        self.assertEqual(policy.save_discount_rules(engine.default_discount_rules(),'wulv',23),p)
        self.assertEqual(self.file.read_bytes(),before)

    def test_save_changes_only_rules_and_metadata_preserves_off_and_audits_actor(self):
        p=policy.save_discount_rules(rules(),'wulv',23)
        self.assertEqual(settings(p),settings(self.value));self.assertFalse(p['system_enabled']);self.assertEqual(p['revision'],24)
        event=json.loads(self.audit.read_text())
        self.assertEqual(event['actor'],'wulv');self.assertEqual(event['before'],self.value)
        self.assertEqual(event['after'],p)

    def test_duplicate_noop_and_stale_revision_conflict(self):
        first=policy.save_discount_rules(rules(),'wulv',23);stored=self.file.read_bytes();history=self.audit.read_bytes()
        self.assertEqual(policy.save_discount_rules(rules(),'DY',24),first)
        self.assertEqual(self.file.read_bytes(),stored);self.assertEqual(self.audit.read_bytes(),history)
        with self.assertRaisesRegex(ValueError,'revision_changed'):policy.save_discount_rules(rules(high='5'),'DY',23)
        self.assertEqual(self.file.read_bytes(),stored)

    def test_two_concurrent_admins_only_one_revision_commits(self):
        outcomes=[];barrier=threading.Barrier(2)
        def save(actor,high):
            barrier.wait()
            try:outcomes.append(policy.save_discount_rules(rules(high=high),actor,23)['revision'])
            except ValueError as exc:outcomes.append(str(exc))
        threads=[threading.Thread(target=save,args=('wulv','4')),threading.Thread(target=save,args=('DY','5'))]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertCountEqual(outcomes,[24,'automation_revision_changed'])
        self.assertEqual(len(self.audit.read_text().splitlines()),1)

    def test_invalid_save_and_lower_margin_never_change_runtime(self):
        for bad in [None,rules(low='5',high='4'),rules(low='10.01')]:
            with self.assertRaises(ValueError):policy.save_discount_rules(bad,'wulv',23)
            self.assertEqual(self.file.read_bytes(),self.before)
        low={**self.value,'minimum_gross_margin_pct':'9'};self.file.write_text(json.dumps(low));before=self.file.read_bytes()
        with self.assertRaisesRegex(ValueError,'margin_floor_invalid'):policy.save_discount_rules(rules(),'wulv',23)
        self.assertEqual(self.file.read_bytes(),before)

    def test_existing_general_save_preserves_ranges_without_changing_old_margin_policy(self):
        first=policy.save_discount_rules(rules(),'wulv',23)
        old_settings=settings(first);old_settings['minimum_gross_margin_pct']='9'
        p=policy.save_policy(old_settings,'wulv',24)
        self.assertEqual(p['pricing_rules'],first['pricing_rules']);self.assertEqual(p['minimum_gross_margin_pct'],'9')

    def test_atomic_publish_failure_preserves_policy(self):
        with patch.object(policy.os,'replace',side_effect=OSError('isolated atomic replacement failure')):
            with self.assertRaises(OSError):policy.save_discount_rules(rules(),'wulv',23)
        self.assertEqual(self.file.read_bytes(),self.before)

    def test_range_save_preserves_original_natural_due_and_failed_pause(self):
        from automation_tick import due
        current={**self.value,'system_enabled':True,'mode':'auto'}
        self.file.write_text(json.dumps(current))
        saved=policy.save_discount_rules(rules(),'wulv',23)
        now=datetime.now(timezone.utc)
        last={'request':{'policy_revision':23},'status':'ready','created_at':now.isoformat(),
              'completed_at':now.isoformat(),'result':{'status':'no_price_change'}}
        self.assertEqual(saved['schedule_revision'],23)
        self.assertEqual(due(saved,last,now+timedelta(minutes=90)),'waiting')
        self.assertEqual(due(saved,last,now+timedelta(minutes=91)),'due')
        last['request']['policy_revision']=24
        self.assertEqual(due(saved,last,now+timedelta(minutes=90)),'waiting')
        last['request']['policy_revision']=23;last['status']='failed'
        self.assertEqual(due(saved,last,now),'paused_after_failure')
        general=policy.save_policy(settings(saved),'wulv',24)
        self.assertEqual(general['schedule_revision'],25)
        self.assertEqual(due(general,last,now),'due')

    def test_active_job_rejects_changed_ranges_without_invalidation(self):
        (self.root/'jobs').mkdir()
        (self.root/'jobs'/'active.json').write_text(json.dumps({'kind':'auto_cycle','status':'running'}))
        with self.assertRaisesRegex(ValueError,'cycle_in_progress'):policy.save_discount_rules(rules(),'wulv',23)
        self.assertEqual(self.file.read_bytes(),self.before)
        self.assertFalse(self.audit.exists())

    def test_audit_fsync_failure_rolls_back_running_config(self):
        real=policy.os.fsync;calls=0
        def fail_once(fd):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('isolated audit fsync failure')
            return real(fd)
        with patch.object(policy.os,'fsync',side_effect=fail_once):
            with self.assertRaises(OSError):policy.save_discount_rules(rules(),'wulv',23)
        self.assertEqual(self.file.read_bytes(),self.before)
        self.assertEqual(self.audit.read_bytes(),b'')

class IsolatedHttpTests(unittest.TestCase):
    # Only HTTP tests, do not count inherited storage tests twice.
    def setUp(self):
        IsolatedPolicyTests.setUp(self)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),api.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.thread.join);self.addCleanup(self.server.shutdown)
        roles=patch.object(api,'WRITERS',{'wulv','chenchao','DY'});roles.start();self.addCleanup(roles.stop)
        view=patch.object(api,'automation_view',side_effect=lambda p,actor=None:{**p,'can_edit_discount_rules':actor in api.WRITERS})
        view.start();self.addCleanup(view.stop)

    def request(self,path='/automation/discount-rules',body=None,actor='wulv',https=True):
        headers={'Content-Type':'application/json','X-Authenticated-User':actor}
        if https:headers['X-Forwarded-Proto']='https'
        encoded=json.dumps(body).encode() if body is not None else None
        request=urllib.request.Request(f'http://127.0.0.1:{self.server.server_port}'+path,encoded,headers)
        try:
            with urllib.request.urlopen(request,timeout=3) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:
            with e:return e.code,json.load(e)

    def test_http_readonly_and_https_gate_no_writes(self):
        body={'rules':rules(),'expected_revision':23}
        self.assertEqual(self.request(body=body,actor='viewer')[0],403)
        self.assertEqual(self.request(body=body,https=False)[0],503)
        self.assertEqual(self.request(body=body,actor='')[0],401)
        self.assertEqual(self.file.read_bytes(),self.before)
        status,payload=self.request('/automation',actor='viewer')
        self.assertEqual(status,200);self.assertFalse(payload['can_edit_discount_rules'])

    def test_http_save_duplicate_conflict_and_no_queue(self):
        with patch.object(api.Handler,'enqueue',side_effect=AssertionError('new save must never enqueue')):
            self.assertEqual(self.request(body={'rules':rules(),'expected_revision':23})[0],200)
            stored=self.file.read_bytes()
            self.assertEqual(self.request(body={'rules':rules(),'expected_revision':24})[0],200)
            self.assertEqual(self.request(body={'rules':rules(high='6'),'expected_revision':23})[0],409)
            self.assertEqual(self.file.read_bytes(),stored)

    def test_http_cannot_smuggle_other_settings_or_rules_via_general_route(self):
        body={'rules':rules(),'expected_revision':23,'minimum_gross_margin_pct':'0'}
        self.assertEqual(self.request(body=body)[0],400)
        raw={**settings(self.value),'pricing_rules':rules()}
        self.assertEqual(self.request('/automation',{'settings':raw,'expected_revision':23})[0],400)
        self.assertEqual(self.file.read_bytes(),self.before)

    def test_http_preview_readonly_rejected_before_calculation(self):
        with patch.object(api,'preview_discount_rules') as calc:
            self.assertEqual(self.request('/automation/discount-preview',{'rules':rules(),'expected_revision':23},actor='viewer')[0],403)
            calc.assert_not_called()

class PurePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for name in ('runs','quotes','jobs','queue','config'):(self.root/name).mkdir()
        self.value={**policy.initial_policy(),'revision':23,'system_enabled':True,'mode':'auto'}
        self.file=self.root/'config'/'automation.json';self.file.write_text(json.dumps(self.value))
        for obj,name,value in [(policy,'POLICY_FILE',self.file),(quotes,'ROOT',self.root)]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        self.run_id='00000000-0000-4000-8000-000000000001'
        now=datetime.now(timezone.utc).isoformat();e=copy.deepcopy(FIXTURES[0]['evidence'])
        snapshot={'run_id':self.run_id,'status':'ready_for_quote','created_at':now,'costs':[], 'competitors':[],
                  'fx':{'status':'valid','checked_at':now,'cny_per_usd':'1'},'storefront':{
                   'source':'https://www.mmoexp.com/Fc-27/Coins.html','currency':'USD','collection_run_id':self.run_id,
                   'status':'ok','package_k':100,'rows':{}}}
        for i,p in enumerate(('PS','XBOX','PC'),1):
            snapshot['costs'].append({'platform':p,'status':'valid','run_id':self.run_id,'checked_at':now,
               'game':'FC27','product':'Game Coins','unit':'CNY/K','record_id':str(i),'trade_at':now,'cny_per_1k':'0.6'})
            for site,offer in e['offers'][p].items():
                snapshot['competitors'].append({'platform':p,'source':site,'status':'valid','run_id':self.run_id,
                  'currency':'USD','captured_at':now,'gross_usd':offer['usd_price'],'purchase_k':'100','bonus_k':'0','url':'https://example.test'})
            snapshot['storefront']['rows'][p]={'platform':p,'status':'ok','base_k':'100','checked_at':now,
                 'sku_id':str(i),'package_usd':'100.00','bonus_k':'0','usd_per_k':'1.000000'}
        self.snapshot=snapshot;self.path=self.root/'runs'/(self.run_id+'.json');self.path.write_text(json.dumps(snapshot))

    def files(self):return {str(p.relative_to(self.root)):sha(p) for p in self.root.rglob('*') if p.is_file()}

    def test_preview_pure_same_snapshot_no_files_changed(self):
        before=self.files();r=quotes.preview_discount_rules(rules(),23)
        self.assertTrue(r['draft_only']);self.assertEqual(r['run_id'],self.run_id)
        self.assertEqual(r['draft']['rows'][0]['requested_discount_pct'],'4.00')
        self.assertEqual(r['original']['rows'][0]['requested_discount_pct'],'10.00')
        self.assertEqual(before,self.files())

    def test_preview_missing_stale_or_invalid_source_fails_without_writes(self):
        old=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
        for mutate in [lambda s:s.update(created_at=old),lambda s:s['competitors'].pop(),lambda s:s['costs'].pop()]:
            s=copy.deepcopy(self.snapshot);mutate(s);self.path.write_text(json.dumps(s));before=self.files()
            with self.assertRaisesRegex(ValueError,'snapshot_unavailable'):quotes.preview_discount_rules(rules(),23)
            self.assertEqual(before,self.files())

    def test_preview_stale_revision_and_user_supplied_rules_recalculation_rejected(self):
        with self.assertRaisesRegex(ValueError,'revision_changed'):quotes.preview_discount_rules(rules(),22)
        with self.assertRaisesRegex(ValueError,'edits_invalid'):quotes.validate_edits({'pricing_rules':rules()})

    def test_real_quote_owns_rules_snapshot_and_hash(self):
        with patch.object(quotes.os,'chown'),patch.object(quotes.os,'chmod'):
            quotes.quote_for_run(self.run_id)
        q=json.loads((self.root/'quotes'/(self.run_id+'.json')).read_text())
        self.assertEqual(q['automation_policy_revision'],23);self.assertEqual(q['pricing_rules'],self.value['pricing_rules'])
        self.assertEqual(q['pricing_rules_sha256'],engine.discount_rules_sha256(q['pricing_rules']))
        self.assertEqual(q['result'],engine.calculate(q['evidence'],q['edits']))

if __name__=='__main__':unittest.main()
