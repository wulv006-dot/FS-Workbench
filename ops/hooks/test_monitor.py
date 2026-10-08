"""Isolated synthetic checks: no production services or real notifications."""
import ast, json, os, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from collector import atomic, collect_bounded, persist
from delivery import deliver, load_config, send
from report import report, reader_health, unverified

def value(status='healthy'):
    return {'captured_at':datetime.now(timezone.utc).isoformat(), 'status':status,
            'issues':[] if status=='healthy' else [{'level':'critical','code':'synthetic_fault'}]}
def save(root,status):persist(root,collect_bounded(lambda:value(status),lambda _:None))
def config():
    return {'approved':True,'activated_at':'2020-01-01T00:00:00+00:00',
            'heartbeat_url':'https://hc-ping.com/00000000-0000-0000-0000-000000000001',
            'business_url':'https://hc-ping.com/00000000-0000-0000-0000-000000000002'}

class MonitorTests(unittest.TestCase):
    def test_bounded_confirmation_and_transient(self):
        sleeps=[]; result=collect_bounded(lambda:value('critical'),sleeps.append)
        self.assertEqual((len(result['observations']),sleeps),(3,[10,10]))
        values=iter([value('critical'),value()]); result=collect_bounded(lambda:next(values),lambda _:None)
        self.assertEqual(result['status'],'healthy'); self.assertEqual(result['observations'][0]['status'],'critical')

    def test_failure_overrides_old_healthy(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); save(root,'healthy')
            persist(root,collect_bounded(lambda:unverified('TimeoutExpired'),lambda _:None))
            self.assertEqual(json.loads((root/'latest.json').read_text())['status'],'unverified')

    def test_dedupe_recovery_recurrence(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            for status in ['critical','critical','healthy','healthy','critical']:save(root,status)
            events=[json.loads(p.read_text()) for p in (root/'outbox').glob('*.json')]
            self.assertEqual(len(events),3); self.assertEqual(sum(e['kind']=='recovery' for e in events),1)
            self.assertTrue(all(e['delivery_state']=='pending' for e in events))

    def test_crash_before_latest_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); save(root,'healthy'); original=atomic
            def crash(path,data):
                if path.name=='latest.json':raise OSError('synthetic_disk_failure')
                original(path,data)
            with patch('collector.atomic',crash):
                with self.assertRaises(OSError):save(root,'critical')
            save(root,'critical'); self.assertEqual(len(list((root/'outbox').glob('*.json'))),1)

    def test_heartbeat_stale_future_missing_invalid(self):
        now=datetime.now(timezone.utc)
        for age in [901,-61]:
            self.assertEqual(reader_health({'status':'healthy','finished_at':(now-timedelta(seconds=age)).isoformat()},now),
                             'monitor_stale_or_clock_invalid')
        self.assertEqual(reader_health({},now),'monitor_unavailable')
        self.assertEqual(reader_health({'status':'bogus','finished_at':now.isoformat()},now),'monitor_unavailable')

    def test_service_failure(self):
        self.assertEqual(report(value(),{'issues':[]},{'api':'inactive'},{})['status'],'critical')

    def test_player_request_acceptance_without_samples(self):
        evidence={'coin':{'result':'confirmed','player_expected':True,'player_job_id':'p'},
                  'all':{'status':'confirmed','execution_id':'c','steps':[
                      {'platform':p,'status':'confirmed'} for p in ['PS','XBOX','PC']]},
                  'player':{'status':'confirmed','coin_execution_id':'c','category_response':'accepted',
                            'price_verification':'disabled'}}
        self.assertEqual(report(value(),{'issues':[]},{},evidence)['status'],'healthy')
        evidence['player']['category_response']='unknown'
        self.assertEqual(report(value(),{'issues':[]},{},evidence)['status'],'critical')
        evidence['player']['request_price_check_waived']=True
        self.assertEqual(report(value(),{'issues':[]},{},evidence)['status'],'healthy')

    def test_missing_all_and_player_still_fail_nochange_passes(self):
        result=report(value(),{'issues':[]},{},{'coin':{'result':'confirmed','player_expected':True}})
        self.assertEqual({i['code'] for i in result['issues']},
                         {'latest_coin_all_proof_unverified','player_dispatch_unverified'})
        self.assertEqual(report(value(),{'issues':[]},{},
                                {'coin':{'result':'no_price_change','player_expected':False}})['status'],'healthy')

    def test_no_player_price_readback_and_python39_syntax(self):
        for name in ['probe_worker.py','read_only_status.py','report.py']:
            text=(Path(__file__).parent/name).read_text(encoding='utf-8')
            self.assertNotIn('sample_readback',text); self.assertNotIn('sample_verified_count',text)
            ast.parse(text,feature_version=(3,9))

    def test_no_config_zero_outbound(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); save(root,'healthy'); calls=[]
            self.assertEqual(deliver(root,root/'absent',calls.append)['state'],'not_configured')
            self.assertEqual(calls,[])

    def test_ordered_delivery_dedupe_and_recovery(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); marker=root/'marker'; marker.touch(); calls=[]
            save(root,'critical'); save(root,'critical'); save(root,'healthy')
            result=deliver(root,marker,calls.append,lambda _:config())
            self.assertEqual(len(result['accepted_event_ids']),2)
            self.assertEqual(calls,[config()['heartbeat_url'],config()['business_url']+'/fail',
                                    config()['business_url'],config()['business_url']])
            again=deliver(root,marker,calls.append,lambda _:config())
            self.assertEqual(again['accepted_event_ids'],[]); self.assertFalse(again['delivered'])

    def test_delivery_failure_pending_retry_recovers(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); marker=root/'marker'; marker.touch(); save(root,'critical')
            def fail(url):
                if url.endswith('/fail'):raise TimeoutError('secret_endpoint_must_not_be_logged')
            result=deliver(root,marker,fail,lambda _:config()); self.assertEqual(result['state'],'unconfirmed')
            self.assertNotIn('secret_endpoint',json.dumps(result))
            event=json.loads(next((root/'outbox').glob('*.json')).read_text())
            self.assertEqual((event['delivery_state'],event['attempt_count']),('pending',1))
            self.assertEqual(deliver(root,marker,lambda _:None,lambda _:config())['state'],'accepted')

    def test_old_history_retained_not_replayed(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); marker=root/'marker'; marker.touch(); save(root,'critical'); save(root,'healthy')
            cfg=config(); cfg['activated_at']=datetime.now(timezone.utc).isoformat(); calls=[]
            result=deliver(root,marker,calls.append,lambda _:cfg)
            self.assertEqual(len(calls),2); self.assertEqual(result['accepted_event_ids'],[])
            self.assertTrue(all(json.loads(p.read_text())['delivery_state']=='retained_pre_activation'
                                for p in (root/'outbox').glob('*.json')))

    def test_stale_snapshot_cannot_ping_healthy(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); marker=root/'marker'; marker.touch(); save(root,'healthy'); calls=[]
            saved=json.loads((root/'latest.json').read_text()); saved['finished_at']='2020-01-01T00:00:00+00:00'
            atomic(root/'latest.json',saved)
            self.assertEqual((deliver(root,marker,calls.append,lambda _:config())['state'],calls),('unconfirmed',[]))

    @unittest.skipUnless(os.name=='posix','Linux owner/mode check, verified on target Linux')
    def test_private_config_approval_endpoint_validation(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'private'; atomic(path,config()); path.chmod(0o600)
            self.assertEqual(load_config(path),config())
            for delta in [{'approved':False},{'business_url':config()['heartbeat_url']},
                          {'heartbeat_url':'https://example.com/token'}, {'activated_at':'2020-01-01T00:00:00'}]:
                atomic(path,config()|delta); path.chmod(0o600)
                with self.assertRaises(ValueError):load_config(path)

    def test_http200_without_exact_ok_rejected_empty_body(self):
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,_):return b'OK (not found)'
        class Opener:
            def open(inner,req,timeout):
                self.assertEqual(req.data,b''); self.assertEqual(timeout,8); return Response()
        with patch('delivery.build_opener',return_value=Opener()):
            with self.assertRaises(ValueError):send(config()['heartbeat_url'])

if __name__=='__main__':unittest.main()
