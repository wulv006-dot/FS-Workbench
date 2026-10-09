"""Direct fault checks; all paths and writers here are isolated."""
import copy, hashlib, importlib, json, os, sys, tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import hooks
from collector import atomic, persist, signature
from hooks_notifier import deliver_bot, load_bot

NOW = datetime.now(timezone.utc)
POLICY = {'system_enabled':True,'mode':'auto','revision':28}


def healthy():
    return {'status':'healthy','captured_at':NOW.isoformat(),'finished_at':NOW.isoformat(),
            'issues':[], 'coin':{'config':POLICY,'job':{'job_id':'old','result':'confirmed'}},
            'publication':{'platforms':[{'platform':p,'status':'matched'} for p in hooks.PLATFORMS]},
            'unknown_operations':[]}


def snapshot(root):
    identity='20261008T000000Z-0123456789abcdef'
    contract='all-websites-order-primary-admin-supplement-v1'
    value={'schemaVersion':2,'snapshotId':identity,'scope':'all-websites','scopeApproved':True,
           'scopeContractId':contract,'currency':'USD','timezone':'Asia/Shanghai','requiredProfiles':['FC'],
           'profiles':{'FC':{'period':{'start':'2026-10-08'},'primary':{'status':'available','system':'order.p2pah.cn',
                                                                  'period':{'start':'2026-10-08'},'capturedAt':NOW.isoformat()}}}}
    body=json.dumps(value).encode(); target=root/'snapshots'/identity/'snapshot.json'
    target.parent.mkdir(parents=True);target.write_bytes(body)
    atomic(root/'current.json',{'schemaVersion':2,'snapshotId':identity,'path':'snapshots/'+identity+'/snapshot.json',
                              'sha256':hashlib.sha256(body).hexdigest(),'scopeContractId':contract,
                              'generatedAt':NOW.isoformat(),'staleAfterSeconds':7200})
    atomic(root/'attempt.json',{'status':'success'})
    return target


class Faults(unittest.TestCase):
    def test_bot_readiness_requires_bound_received_receipt(self):
        from types import SimpleNamespace
        import stat
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);cfg=root/'bot.json';proof=root/'receipt.json';cfg.write_bytes(b'isolated-credential')
            record={'provider_accepted':True,'group_receipt':'awaiting_user',
                    'config_sha256':hashlib.sha256(cfg.read_bytes()).hexdigest()}
            meta=SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=0,st_nlink=1,st_size=100)
            with patch('hooks_notifier.load_bot',return_value={}),patch('pathlib.Path.lstat',return_value=meta):
                proof.write_text(json.dumps(record));self.assertFalse(hooks.bot_ready(cfg,proof))
                record['group_receipt']='both_received';proof.write_text(json.dumps(record));self.assertTrue(hooks.bot_ready(cfg,proof))
                record['provider_accepted']=False;proof.write_text(json.dumps(record));self.assertFalse(hooks.bot_ready(cfg,proof))
                record['provider_accepted']=True;proof.write_text(json.dumps(record));cfg.write_bytes(b'rotated-credential')
                self.assertFalse(hooks.bot_ready(cfg,proof))
                record['config_sha256']=hashlib.sha256(cfg.read_bytes()).hexdigest();proof.write_text(json.dumps(record))
                meta.st_uid=1;self.assertFalse(hooks.bot_ready(cfg,proof))

    def test_shared_resume_interface_fails_closed(self):
        kwargs={'user_intent':'ENABLED','pause_source':'system_fault','revision_current':True,
                'dependencies_verified':True,'unknown_operations':[],'business_safe':True,'authorized':True}
        self.assertTrue(hooks.can_resume(**kwargs))
        for key,value in [('user_intent','DISABLED'),('pause_source','user_intent'),('revision_current',False),
                          ('dependencies_verified',False),('unknown_operations',['original-id']),('business_safe',None),('authorized',False)]:
            self.assertFalse(hooks.can_resume(**(kwargs|{key:value})))

    def test_hung_live_process_detected_without_killing_or_replay(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);snapshot(root);value=healthy()
            value['coin']['job']={'job_id':'original','status':'running','started_at':(NOW-timedelta(seconds=1100)).isoformat()}
            class Response:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,_):return b'{"ok":true,"service":"fs-business-range","readonly":true}'
            with patch('hooks.urlopen',return_value=Response()):
                hooks.extend_report(value,snapshot_root=root,business_root=root/'business')
            self.assertIn('coin_job_deadline_exceeded',[x['code'] for x in value['issues']])
            self.assertEqual(value['coin']['job']['job_id'],'original')
            self.assertTrue(hooks.controls(value,at=NOW)['platforms']['PS']['reasons'])

    def test_platform_pause_not_other_platform_or_dashboard(self):
        value=healthy();value['issues']=[{'level':'critical','code':'business_snapshot_build_failed'}]
        value['publication']['platforms'][0]['status']='unverified'
        c=hooks.controls(value,at=NOW)
        self.assertTrue(c['platforms']['PS']['reasons'])
        self.assertEqual(c['platforms']['PS']['phase'],'ESCALATED')
        self.assertEqual(c['platforms']['PS']['sales_protection_status'],'UNAVAILABLE')
        self.assertEqual(c['platforms']['PC']['reasons'],[])
        self.assertEqual(c['platforms']['XBOX']['reasons'],[])

    def test_fault_resume_requires_two_clean_and_next_natural_cycle(self):
        value=healthy();value['issues']=[{'level':'critical','code':'worker_unhealthy_or_unknown'}]
        paused=hooks.controls(value,at=NOW);value['issues']=[]
        first=hooks.controls(value,paused,at=NOW);self.assertTrue(first['platforms']['PS']['reasons'])
        second=hooks.controls(value,first,at=NOW);self.assertEqual(second['platforms']['PS']['phase'],'AWAITING_CYCLE')
        same=hooks.controls(value,second,at=NOW);self.assertEqual(same['platforms']['PS']['phase'],'AWAITING_CYCLE')
        value['coin']['job']['job_id']='new'
        final=hooks.controls(value,same,at=NOW);self.assertEqual(final['platforms']['PS']['phase'],'RECOVERED')

    def test_user_disabled_during_repair_never_reenabled(self):
        value=healthy();value['issues']=[{'level':'critical','code':'source_coverage_unverified'}]
        c=hooks.controls(value,at=NOW);value['issues']=[];value['coin']['config']=dict(POLICY,system_enabled=False)
        for _ in range(4):c=hooks.controls(value,c,at=NOW)
        self.assertEqual(c['user_intent'],'DISABLED');self.assertTrue(c['platforms']['PC']['reasons'])
        self.assertFalse(value['coin']['config']['system_enabled'])

    def test_original_id_retained_legitimate_inflight_not_unknown(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);op='11111111-1111-4111-8111-111111111111'
            atomic(root/'jobs'/('job.json'),{'job_id':op,'status':'running'})
            target=root/'executions'/(op+'.json')
            atomic(target,{'execution_id':op,'run_id':'collection-is-not-operation','status':'PARTIAL','selected':['PS']})
            self.assertEqual(hooks.unknown_operations(root),[])
            atomic(root/'jobs'/'job.json',{'job_id':op,'status':'ready'})
            self.assertEqual(hooks.unknown_operations(root)[0]['operation_id'],op)
            atomic(root/'jobs'/'job.json',{'job_id':'manual-job','status':'running','request':{'execution_id':op}})
            self.assertEqual(hooks.unknown_operations(root),[])
            atomic(target,{'execution_id':op,'run_id':'collection-is-not-operation','status':'UNCERTAIN','selected':['PS']})
            before=target.read_bytes();rows=hooks.unknown_operations(root)
            self.assertEqual(rows[0]['operation_id'],op);self.assertEqual(target.read_bytes(),before)
            c=hooks.controls(healthy()|{'unknown_operations':rows},at=NOW)
            self.assertTrue(c['platforms']['PS']['reasons']);self.assertFalse(c['platforms']['PC']['reasons'])
            value=healthy()|{'unknown_operations':rows,'status':'critical','issues':[{'level':'critical','code':'coin_execution_needs_reconcile'}]}
            persist(root,value)
            event=json.loads(next((root/'outbox').glob('*.json')).read_text())
            self.assertEqual(event['operation_ids'],[op])

    def test_bad_snapshot_retains_original_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);target=snapshot(root);before=target.read_bytes()
            self.assertEqual(hooks.snapshot_probe(root,NOW)['status'],'live')
            atomic(root/'attempt.json',{'status':'failed'})
            self.assertEqual(hooks.snapshot_probe(root,NOW)['status'],'stale')
            self.assertEqual(target.read_bytes(),before)
            self.assertTrue(hooks.snapshot_probe(root,NOW)['legal_snapshot_retained'])
            target.write_text('{}');self.assertEqual(hooks.snapshot_probe(root,NOW)['status'],'unavailable')

    def test_clock_stale_and_cross_scope_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);snapshot(root)
            self.assertEqual(hooks.snapshot_probe(root,NOW+timedelta(seconds=7201))['status'],'stale')
            self.assertEqual(hooks.snapshot_probe(root,NOW-timedelta(seconds=61))['status'],'unavailable')
            m=json.loads((root/'current.json').read_text());m['path']='../foreign-snapshot.json';atomic(root/'current.json',m)
            self.assertEqual(hooks.snapshot_probe(root,NOW)['status'],'unavailable')

    def test_dedupe_keeps_different_operations_and_severity_upgrade(self):
        first=healthy()|{'unknown_operations':[{'operation_id':'one'}]}
        second=healthy()|{'unknown_operations':[{'operation_id':'two'}]}
        self.assertNotEqual(signature(first),signature(second))
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);v=healthy();persist(root,v);persist(root,v)
            self.assertEqual(len(list((root/'outbox').glob('*.json'))),0)
            v=healthy()|{'status':'warning','issues':[{'level':'warning','code':'fault'}]}
            persist(root,v);persist(root,v);self.assertEqual(len(list((root/'outbox').glob('*.json'))),1)
            v=healthy()|{'status':'critical','issues':[{'level':'critical','code':'fault'}]}
            persist(root,v);self.assertEqual(len(list((root/'outbox').glob('*.json'))),2)

    def test_pause_survives_restart_and_corrupt_state_not_reset(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'gates').mkdir()
            value=healthy();value['issues']=[{'level':'critical','code':'worker_unhealthy_or_unknown'}]
            before=hooks.persist_controls(root,value);after=hooks.persist_controls(root,value)
            self.assertEqual(before['platforms'],after['platforms'])
            (root/'gates/control.json').write_text('{')
            with self.assertRaises(ValueError):hooks.persist_controls(root,healthy())
            self.assertEqual((root/'gates/control.json').read_text(),'{')

    def test_http_error_detector_controller_and_notification_outbox(self):
        # Same collector/controls/outbox/notifier path, with a real isolated HTTP 503.
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        import threading
        from urllib.request import urlopen
        class Bad(BaseHTTPRequestHandler):
            def do_GET(self):self.send_response(503);self.end_headers();self.wfile.write(b'{"error":"fault"}')
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Bad);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            value=healthy()
            with tempfile.TemporaryDirectory() as name:
                root=Path(name);(root/'gates').mkdir();snapshot(root)
                value=hooks.extend_report(value,'http://127.0.0.1:'+str(server.server_port),root,root/'business')
                self.assertEqual(value['exact_range']['status'],'unavailable')
                self.assertIn('exact_range_health_unavailable',[x['code'] for x in value['issues']])
                c=hooks.persist_controls(root,value);persist(root,value)
                self.assertFalse(c['platforms']['PS']['reasons'])
                marker=root/'bot';marker.touch();calls=[]
                cfg={'activated_at':'2020-01-01T00:00:00+00:00'}
                r=deliver_bot(root,marker,lambda config,event:calls.append(event),lambda _:cfg)
                self.assertEqual(r['state'],'accepted');self.assertEqual(len(calls),1)
                r=deliver_bot(root,marker,lambda config,event:calls.append(event),lambda _:cfg)
                self.assertEqual(len(calls),1);self.assertFalse(r['delivered'])
        finally:server.shutdown();server.server_close();thread.join()

    def test_notification_failure_keeps_pending(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);marker=root/'bot';marker.touch();v=healthy()|{'status':'critical','issues':[{'level':'critical','code':'fault'}]};persist(root,v)
            def fail(*args):raise OSError('private upstream text must not leak')
            r=deliver_bot(root,marker,fail,lambda _:{'activated_at':'2020-01-01T00:00:00+00:00'})
            self.assertEqual(r['state'],'unconfirmed');self.assertNotIn('private',str(r))
            event=json.loads(next((root/'outbox').glob('*.json')).read_text());self.assertEqual(event['delivery_state'],'pending')

    def test_gate_fails_closed_before_fake_writer_and_manual_unchanged(self):
        # Load only the added function so tests don't depend on pricing algorithms/imports.
        text=Path(__file__).with_name('automation_policy.py').read_text();ns={'Path':Path,'json':json,'os':os,'datetime':datetime,'timezone':timezone}
        exec(text[text.index('\ndef hooks_before_write('):],ns)
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);target=root/'control.json'
            # CI cannot chown root fixtures. Model trusted/untrusted ownership here;
            # actual UID 11027 + root-owned readonly bind is verified on production.
            from types import SimpleNamespace
            class GuardPath:
                owner=0
                def __init__(self,path):self.path=path
                @property
                def parent(self):return GuardPath(self.path.parent)
                def lstat(self):
                    m=self.path.lstat();return SimpleNamespace(st_mode=m.st_mode,st_uid=self.owner,
                                                              st_size=m.st_size,st_nlink=m.st_nlink)
                def read_text(self,**kwargs):return self.path.read_text(**kwargs)
            ns['Path']=lambda _:GuardPath(target)
            ns['hooks_before_write'](POLICY,['PS'],False)
            writes=[]
            with self.assertRaises(ValueError):ns['hooks_before_write'](POLICY,['PS'],True);writes.append('POST')
            self.assertEqual(writes,[])
            c=hooks.controls(healthy(),at=NOW);atomic(target,c);target.chmod(0o640)
            ns['hooks_before_write'](POLICY,['PS'],True)
            # Trace service probe -> report -> controls -> actual automatic guard.
            from report import report
            required=('fc27-cloud-api.service','fc27-cloud-worker.service','fc27-gate.service',
                      'coin_api_http_gate')
            for unit in required:
                for state in ('inactive','failed','unknown','unexpected_http_status','unexpected_anonymous_success'):
                    with self.subTest(unit=unit,state=state):
                        snapshot={'captured_at':NOW.isoformat(),'health':{'api':'ok'},
                                  'automation':POLICY,'publication':healthy()['publication']}
                        observed=report(snapshot,{'issues':[]},{unit:state},{})
                        code='service_unavailable:'+unit
                        self.assertEqual(observed['issues'][0]['code'],code)
                        control=hooks.controls(observed,at=NOW);atomic(target,control);target.chmod(0o640)
                        for platform in hooks.PLATFORMS:
                            self.assertIn(code,control['platforms'][platform]['reasons'])
                            with self.assertRaisesRegex(ValueError,'hook_scope_paused'):
                                ns['hooks_before_write'](POLICY,[platform],True);writes.append('POST')
                        self.assertEqual(writes,[])
            for unit in ('fc27-gallery.service','gallery_api_http_gate','fs-business-range.service','unrelated-service'):
                snapshot={'captured_at':NOW.isoformat(),'automation':POLICY,
                          'publication':healthy()['publication']}
                control=hooks.controls(report(snapshot,{'issues':[]},{unit:'failed'},{}),at=NOW)
                atomic(target,control);target.chmod(0o640)
                for platform in hooks.PLATFORMS:
                    self.assertEqual(control['platforms'][platform]['reasons'],[])
                    ns['hooks_before_write'](POLICY,[platform],True)
            atomic(target,c);target.chmod(0o640)
            if os.name=='posix':
                GuardPath.owner=1
                with self.assertRaises(ValueError):ns['hooks_before_write'](POLICY,['PS'],True)
                GuardPath.owner=0
            c['platforms']['PS']['reasons']=['unknown_operation:original'];atomic(target,c);target.chmod(0o640)
            with self.assertRaises(ValueError):ns['hooks_before_write'](POLICY,['PS'],True)
            ns['hooks_before_write'](POLICY,['PC'],True)
            with self.assertRaises(ValueError):ns['hooks_before_write'](dict(POLICY,revision=29),['PC'],True)
            c['valid_until']=(NOW-timedelta(seconds=1)).isoformat();atomic(target,c);target.chmod(0o640)
            with self.assertRaises(ValueError):ns['hooks_before_write'](POLICY,['PC'],True)

    def test_all_actual_send_sites_guarded_and_existing_lock_retained(self):
        root=Path(__file__).parent
        writer=(root/'price_writer.py').read_text()
        self.assertIn('hooks_before_write(load_policy(), [platform], automatic)\n                stage(record, "saving_"',writer)
        self.assertIn('hooks_before_write(load_policy(), selected, automatic)\n            stage(record, "syncing")',writer)
        mirror=(root/'coin_all_sync_job.py').read_text()
        self.assertIn("hooks_before_write(read_policy(), [step['platform']], audit.get('automatic') is True)",mirror)
        wrapper=(root/'execute_price.sh').read_text();self.assertIn('flock -n 9',wrapper);self.assertIn('gates,readonly',wrapper)

    def test_monitor_upgrade_rollback_removes_only_this_attempt_files(self):
        from types import SimpleNamespace
        import importlib.util
        publisher_path=Path(__file__).parent/'publishers/monitor-publisher.py'
        spec=importlib.util.spec_from_file_location('isolated_monitor_publisher',publisher_path)
        publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
        with patch.object(sys,'argv',['publisher','--repair-runtime']),patch.object(publisher,'repair_runtime',return_value='checked') as repair:
            self.assertEqual(publisher.main(),'checked');repair.assert_called_once_with(False)
        with patch.object(sys,'argv',['publisher']),patch('sys.stderr'),self.assertRaises(SystemExit) as rejected:
            publisher.main()
        self.assertEqual(rejected.exception.code,2)
        names=('collector.py','hooks.py','probe_worker.py','hooks_notifier.py','delivery.py')
        for fail_at in range(1,7):
            with self.subTest(fail_at=fail_at),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);app=root/'app';data=root/'data';stage=root/'stage'
                app.mkdir();data.mkdir();(stage/'source').mkdir(parents=True)
                original={};rows=[]
                for name in names:
                    before=None
                    if name not in {'hooks.py','hooks_notifier.py'}:
                        body=('# old '+name+'\n').encode();(app/name).write_bytes(body)
                        original[name]=body;before=hashlib.sha256(body).hexdigest()
                    body=('# new '+name+'\n').encode();(stage/'source'/name).write_bytes(body)
                    rows.append({'name':name,'before':before,'after':hashlib.sha256(body).hexdigest()})
                original['.hooks-unrelated']=b'preserve existing evidence'
                (app/'.hooks-unrelated').write_bytes(original['.hooks-unrelated'])
                (stage/'hooks-monitor-manifest.json').write_text(json.dumps({'files':rows}))
                snapshot={'synthetic_protected':'unchanged'}
                after=snapshot if fail_at<6 else {'synthetic_protected':'changed'}
                replace=os.replace;calls=[]
                def interrupted(source,target):
                    calls.append(Path(target).name)
                    if fail_at==len(calls):raise OSError('isolated mid-upgrade failure')
                    replace(source,target)
                lock_modules={}
                if os.name!='posix':
                    lock_modules['fcntl']=SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *_:None)
                with patch.dict(sys.modules,lock_modules),patch.object(publisher,'APP',app),patch.object(publisher,'DATA',data), \
                     patch.object(publisher,'baseline',side_effect=[snapshot,after]), \
                     patch.object(publisher.os,'geteuid',return_value=0,create=True), \
                     patch.object(publisher.os,'chown',create=True), \
                     patch.object(publisher.os,'replace',side_effect=interrupted), \
                     patch.object(publisher.subprocess,'run',return_value=SimpleNamespace(returncode=0,stderr='Ran 35 tests\n\nOK\n')):
                    with self.assertRaises((OSError,RuntimeError)):
                        publisher.upgrade(stage,True)
                self.assertEqual({p.name:p.read_bytes() for p in app.iterdir()},original)

if __name__=='__main__':unittest.main()
