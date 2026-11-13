from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType,SimpleNamespace
from unittest.mock import ANY,Mock,patch
from contextlib import redirect_stdout
import ast,importlib.util,io,json,os,sys,unittest,uuid

RELEASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RELEASE/'source'))
sys.path.insert(0,str(RELEASE/'tests'))
stub=ModuleType('p2pah_session_service')
stub.allowed_admin_usernames=lambda:{'wulv'};stub.HEADERS={};stub.SessionManager=Mock;stub.read_private_config=lambda:{}
spec=importlib.util.spec_from_file_location('v3_player_followup',RELEASE/'source/player_sync_job.py');players=importlib.util.module_from_spec(spec)
with patch.dict(sys.modules,{'p2pah_session_service':stub}):spec.loader.exec_module(players)
spec=importlib.util.spec_from_file_location('v3_release_readiness',RELEASE/'deploy/release_readiness.py');readiness=importlib.util.module_from_spec(spec);spec.loader.exec_module(readiness)

JOB='00000000-0000-4000-8000-000000000091';COIN='00000000-0000-4000-8000-000000000092'


def execution():
    return dict(execution_id=COIN,status='CONFIRMED',automatic=False,sync_confirmed=True,
        after=dict(rows=[dict(platform=p,b2c='.1' if p!='PC' else '.2') for p in ('PS','XBOX','PC')]),
        pricing_decision_receipt=dict(schema_version='fc-pricing-v3-20261026',decision_bundle_id=COIN,
            review_contract='program_pricing_with_daily_hermes_review_v3',decision_source='program_current_strategy',execution_authorized=True,
            financial_contract_version='fc27_dual20_v1',financial_proof=dict(pass_all=True,execution_eligible=True),
            action=dict(base_prices=dict(console='10',pc='20'))))


class PlayerV3Followup(unittest.TestCase):
    def test_confirmed_v6_queues_once_and_category_sync_uses_original_admin_receipt(self):
        from fc_pricing_v3 import runtime
        from fc_pricing_v3.dispatch import CURVE_WRITE_PROTOCOL
        from fc_pricing_v3.financial import fingerprint
        from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT
        from test_curve_writer_v6 import PLATFORM, Transport, saved, setup_bundle, writer
        from fc_pricing_v3.price_curve import curve_key

        bundle, capability, before, recipient = setup_bundle()
        target = deepcopy(bundle['action']['curves'][PLATFORM]['native_payload'])
        target['more']['price'][0] = '10.20'
        bundle['action']['curves'][PLATFORM] = saved(target, 'editor_candidate')
        for action in ('before_action', 'action'):
            bundle[action]['curves'][PLATFORM]['native_contract']['price_edit_policy'] = TWO_BAND_PRICE_EDIT
        curve_proof = bundle['curve_proofs'][PLATFORM]
        curve_proof['curve_key'] = curve_key(bundle['action']['curves'][PLATFORM])
        curve_proof['proof_hash'] = fingerprint({k: v for k, v in curve_proof.items() if k != 'proof_hash'})
        bundle.update(decision_bundle_id=COIN, snapshot_id=JOB, execution_authorized=True)
        bundle['sha256'] = fingerprint({k: v for k, v in bundle.items() if k != 'sha256'})
        item = dict(writer.curve_catalog_plan(bundle, PLATFORM, capability), operation_id=COIN)
        audit = dict(execution_id=COIN, write_protocol=CURVE_WRITE_PROTOCOL, selected=[PLATFORM],
                     status='RUNNING', sync_confirmed=False, curve_results={PLATFORM: item}, run_id=JOB,
                     pricing_decision_receipt=bundle)
        transport = Transport(before, recipient)
        writer.drive_curve_catalog(transport, audit, lambda _: None, lambda _: None, {PLATFORM: capability})
        self.assertEqual(audit['status'], 'CONFIRMED')
        self.assertFalse(audit['sync_confirmed'])
        self.assertEqual(transport.projection_writes, [])
        operation = dict(operation_id=COIN, status='COMPLETED', bundle=bundle,
                         readback=dict(status='CONFIRMED', write_protocol=CURVE_WRITE_PROTOCOL,
                                       execution_id=COIN, curve_results=deepcopy(audit['curve_results'])))
        config = dict(enabled=True, revision=10)
        parent = dict(job_id=JOB, kind='v3_cycle', request=dict(v3_operation_id=COIN),
                      result=dict(status='confirmed'), v3_outcome=operation)
        tree = ast.parse((RELEASE/'source/fc27_cloud_worker.py').read_text(encoding='utf-8'))
        names = {'_enqueue_player_sync_locked', 'v3_player_completion', 'handle'}
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        manager = Mock()
        manager.ensure.return_value = True
        category = Mock()
        with TemporaryDirectory() as folder, patch.object(runtime, 'ledger', return_value=Mock(
                get=lambda *args: operation)):
            root = Path(folder)
            for name in ('jobs', 'executions', 'queue', 'player-sync'):
                (root/name).mkdir()
            (root/'executions'/(COIN+'.json')).write_text(json.dumps(audit), encoding='utf-8')
            host_os = SimpleNamespace(open=os.open, fdopen=os.fdopen, fsync=os.fsync, O_WRONLY=os.O_WRONLY,
                                      O_CREAT=os.O_CREAT, O_EXCL=os.O_EXCL, chown=lambda *args: None)
            namespace = dict(ROOT=root, JOBS=root/'jobs', QUEUE=root/'queue', json=json, uuid=uuid, os=host_os,
                             datetime=runtime.datetime, timezone=runtime.timezone,
                             sync_directory=lambda *args: None, load_player_sync_policy=lambda: config)
            exec(compile(ast.Module(body=functions, type_ignores=[]), 'curve-worker-followup', 'exec'), namespace)
            queued = namespace['_enqueue_player_sync_locked'](parent)
            self.assertEqual(queued['status'], 'queued')
            self.assertEqual(namespace['_enqueue_player_sync_locked'](parent),
                             dict(status='already_queued', job_id=queued['job_id']))
            job = json.loads((root/'queue'/(queued['job_id']+'.json')).read_text(encoding='utf-8'))
            request_proof = namespace['v3_player_completion'](COIN, JOB)
            self.assertEqual(players.confirmed_curve_basis(audit, request_proof, COIN), {'PS': '0.102'})
            for mutate in (lambda r: r.update(status='PARTIAL'),
                           lambda r: r['pricing_decision_receipt']['action'].update(extra_price='9'),
                           lambda r: r['curve_results'][PLATFORM]['actual_site266_curve']['tiers'][1].update(
                               native_price_usd='99')):
                tampered = deepcopy(audit)
                mutate(tampered)
                with self.assertRaisesRegex(ValueError, 'player_sync_curve_'):
                    players.confirmed_curve_basis(tampered, request_proof, COIN)
            with self.assertRaisesRegex(ValueError, 'player_sync_curve_rate_changed'):
                players.confirmed_curve_basis(audit, dict(request_proof, confirmed_100k_rates={'PS': '0.2'}), COIN)

            def dispatch(job, script, request, timeout):
                self.assertEqual(request['v3_completion'], request_proof)
                records = {players.REQUEST: request, players.EXECUTION: audit, players.POLICY: config}
                output = io.StringIO()
                with patch.object(players, 'ROOT', root/'player-sync'), patch.object(players, 'read',
                        side_effect=lambda p: deepcopy(records[p])), patch.object(players, 'SessionManager',
                        return_value=manager), patch.object(players, 'api',
                        return_value=dict(adminInfo=dict(username='wulv'))), patch.object(players, 'list_models',
                        return_value=[dict(id=1)]), patch.object(players, 'recalculate_category', category), redirect_stdout(output):
                    try:
                        players.bulk_main()
                    except ValueError as exc:
                        return 1, dict(status='blocked_before_write', reason=str(exc))
                return 0, json.loads(output.getvalue())

            namespace['run_writer_request'] = dispatch
            with self.assertRaisesRegex(ValueError, 'player_sync_original_job_mismatch'):
                namespace['handle'](dict(job, job_id=JOB))
            result = namespace['handle'](job)
            self.assertEqual((result['status'], result['sample_count']), ('confirmed', 0))
            written = json.loads((root/'player-sync'/(queued['job_id']+'.json')).read_text(encoding='utf-8'))
            self.assertEqual(written['confirmed_coin_100k_rates_usd_per_k'], {'PS': '0.102'})
            self.assertEqual(written['price_verification'], 'disabled')
            with self.assertRaisesRegex(ValueError, 'player_sync_not_confirmed'):
                namespace['handle'](job)
            operation['status'] = 'UNKNOWN'
            with self.assertRaisesRegex(ValueError, 'player_sync_coin_not_confirmed'):
                namespace['handle'](job)
            category.assert_called_once_with(manager, observer=ANY)

    def test_three_platform_execution_requires_each_native_amount_and_contract(self):
        audit = execution()
        receipt = audit['pricing_decision_receipt']
        receipt.update(price_scope_contract='fc27_three_platform_v1',
                       financial_contract_version='fc27_dual20_d9_d2_platform_100k_v4')
        receipt['action']['base_prices'] = dict(PS='10', XBOX='13', PC='20')
        audit['after']['rows'][1]['b2c'] = '.13'
        self.assertTrue(players.verified_v3_coin_execution(audit))
        for mutate in (
            lambda x: x['after']['rows'][1].update(b2c='.1'),
            lambda x: x['pricing_decision_receipt']['action']['base_prices'].update(console='10'),
            lambda x: x['pricing_decision_receipt'].pop('price_scope_contract'),
            lambda x: x['pricing_decision_receipt'].update(financial_contract_version='fc27_dual20_v1'),
            lambda x: x['pricing_decision_receipt'].update(financial_contract_version='fc27_dual20_d9_d2_platform_v3'),
        ):
            invalid = deepcopy(audit); mutate(invalid)
            self.assertFalse(players.verified_v3_coin_execution(invalid))

    def test_native_closed_operation_binds_each_admin_and_target_amount_to_original_receipt(self):
        audit = execution(); receipt = audit['pricing_decision_receipt']
        receipt.update(price_scope_contract='fc27_three_platform_v1',
                       financial_contract_version='fc27_dual20_d9_d2_platform_100k_v4',
                       sha256='a'*64, snapshot_id=JOB)
        receipt['action']['base_prices'] = dict(PS='10', XBOX='13', PC='20')
        audit['after']['rows'][1]['b2c'] = '.13'
        prices = dict(PS='.1', XBOX='.13', PC='.2')
        audit.update(status='ORDER_ADMIN_CONFIRMED', ledger_status='COMPLETED',
                     operation_id=COIN, confirmation_scope='Order_Admin', sync_message='saved')
        audit['close_receipt'] = dict(status=audit['status'], admin_unit_prices=prices)
        completion = dict(operation_id=COIN, status='COMPLETED', bundle_sha256='a'*64,
                          snapshot_id=JOB, base_prices=deepcopy(receipt['action']['base_prices']),
                          readback=dict(operation_id=COIN, confirmation_scope='Order_Admin',
                              status=audit['status'], admin_unit_prices=deepcopy(prices),
                              order_feedback=dict(sync_message='saved'),
                              targets=[dict(platform=p, quote=v) for p,v in receipt['action']['base_prices'].items()]))
        self.assertTrue(players.verified_v3_coin_execution(audit, completion))
        for mutate in (
            lambda c: c['base_prices'].update(XBOX='10'),
            lambda c: c['base_prices'].update(console='10'),
            lambda c: c.update(operation_id=JOB),
            lambda c: c['readback']['admin_unit_prices'].update(XBOX='.1'),
        ):
            invalid = deepcopy(completion); mutate(invalid)
            self.assertFalse(players.verified_v3_coin_execution(audit, invalid))

    def test_original_reconcile_retains_parent_and_dispatches_category_only_once(self):
        from fc_pricing_v3 import runtime,adapters
        from fc_pricing_v3.ledger import Ledger
        from test_order_close_runtime import _operation,ADMIN_OK
        coin='3678aed7-4e88-5b23-8299-65db214b10b4';parent='4fac1668-33ec-5a2e-b997-68b3d297b94b'
        follow='808f6dad-1d63-5175-bc46-a0a51f538478';config=dict(enabled=True,revision=10)
        operation=_operation();operation.update(operation_id=coin)
        operation['bundle']=deepcopy(operation['bundle']);operation['bundle'].update(schema_version='fc-pricing-v3-20261026',snapshot_id=parent,sha256='a'*64)
        audit=execution();audit.update(execution_id=coin,status='PARTIAL',automatic=True,created_at='2026-10-28T04:04:54+00:00',sync_message='修改价格已推送')
        audit['after']['rows']=[dict(platform=p,b2c=str(ADMIN_OK[p])) for p in ('PS','XBOX','PC')]
        audit['pricing_decision_receipt'].update(decision_bundle_id=coin,snapshot_id=parent,sha256='a'*64,action=deepcopy(operation['bundle']['action']))
        tree=ast.parse((RELEASE/'source/fc27_cloud_worker.py').read_text(encoding='utf-8'))
        names={'_enqueue_player_sync_locked','v3_player_completion','_retry_player_followups_locked','handle'}
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        with TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('jobs','executions','queue','player-sync'):(root/name).mkdir()
            db=Ledger(root/'v3/control.sqlite3');db.put('operations',coin,operation)
            (root/'executions'/(coin+'.json')).write_text(json.dumps(audit),encoding='utf-8')
            original_parent=dict(job_id=parent,kind='v3_cycle',status='ready',request=dict(v3_operation_id=coin),result=dict(status='UNKNOWN'))
            (root/'jobs'/(parent+'.json')).write_text(json.dumps(original_parent),encoding='utf-8')
            def save(job):(root/'jobs'/(job['job_id']+'.json')).write_text(json.dumps(job),encoding='utf-8')
            host_os=SimpleNamespace(open=os.open,fdopen=os.fdopen,fsync=os.fsync,O_WRONLY=os.O_WRONLY,O_CREAT=os.O_CREAT,O_EXCL=os.O_EXCL,chown=lambda *a:None)
            namespace=dict(ROOT=root,JOBS=root/'jobs',QUEUE=root/'queue',json=json,uuid=uuid,os=host_os,datetime=runtime.datetime,timezone=runtime.timezone,
                sync_directory=lambda *a:None,save_job=save,load_player_sync_policy=lambda:config)
            exec(compile(ast.Module(body=functions,type_ignores=[]),'original-worker-followup','exec'),namespace)
            enqueue=Mock(side_effect=OSError('queue busy'))
            worker=SimpleNamespace(load_player_sync_policy=lambda:config,save_job=save,enqueue_player_sync=enqueue)
            with patch.object(runtime,'ROOT',root),patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'_admin_observed_prices',return_value=ADMIN_OK) as admin_read,patch.object(runtime,'write_json',side_effect=lambda p,v:p.write_text(json.dumps(v),encoding='utf-8')),patch.object(adapters,'reconcile_postwrite',return_value=dict(status='unavailable')) as public_read,patch.dict(sys.modules,{'fc27_cloud_worker':worker}):
                closed=runtime.close_on_order_admin(operation,audit)
                self.assertEqual(closed['status'],'COMPLETED');self.assertTrue(closed['target_not_completed'])
                self.assertTrue(all(s['state']=='CANCELLED_NOT_SENT' for s in closed['steps'] if s['kind']=='region'))
                saved=json.loads((root/'jobs'/(parent+'.json')).read_text(encoding='utf-8'))
                self.assertEqual(saved['v3_outcome']['operation_id'],coin);self.assertEqual(saved['player_sync_intent'],config)
                self.assertEqual(saved['player_sync']['status'],'pending');self.assertFalse(list((root/'queue').glob('*.json')))
                namespace['_retry_player_followups_locked']()
                saved=json.loads((root/'jobs'/(parent+'.json')).read_text(encoding='utf-8'))
                self.assertEqual(saved['player_sync']['job_id'],follow)
                enqueue.side_effect=namespace['_enqueue_player_sync_locked']
                runtime.reconcile(coin);self.assertEqual(len(list((root/'queue').glob('*.json'))),1)
                admin_read.assert_called_once_with();public_read.assert_called_once()
                current=json.loads((root/'executions'/(coin+'.json')).read_text(encoding='utf-8'))
                self.assertEqual(current['created_at'],audit['created_at'])
                proof=namespace['v3_player_completion'](coin,parent)
                self.assertTrue(players.verified_v3_coin_execution(current,proof))
                for mutate in (lambda p:p.update(operation_id=parent),lambda p:p.update(status='UNKNOWN'),lambda p:p.update(bundle_sha256='wrong'),lambda p:p['readback'].update(confirmation_scope='other'),lambda p:p['readback']['admin_unit_prices'].update(PC='0.01')):
                    invalid=deepcopy(proof);mutate(invalid);self.assertFalse(players.verified_v3_coin_execution(current,invalid))
                no_feedback=deepcopy(current);no_feedback.pop('sync_message');self.assertFalse(players.verified_v3_coin_execution(no_feedback,proof))
                unknown=deepcopy(current);unknown['status']='UNKNOWN';self.assertFalse(players.verified_v3_coin_execution(unknown,proof))
                public=deepcopy(current);public['status']=public['close_receipt']['status']='PUBLIC_CONFIRMED'
                public_proof=deepcopy(proof);public_proof['readback']['status']='PUBLIC_CONFIRMED'
                self.assertTrue(players.verified_v3_coin_execution(public,public_proof))
                receipt={'path':'/admin/goods.GoodsMould/recalcFc27Price','http_status':200,'response_code':1,'response_sha256':'a'*64}
                category=Mock(side_effect=lambda manager,observer:observer(deepcopy(receipt)));manager=Mock();manager.ensure.return_value=True;requests=[]
                def dispatch(job,script,request,timeout):
                    requests.append(deepcopy(request));records={players.REQUEST:request,players.EXECUTION:json.loads((root/'executions'/(coin+'.json')).read_text(encoding='utf-8')),players.POLICY:config}
                    output=io.StringIO()
                    with patch.object(players,'ROOT',root/'player-sync'),patch.object(players,'read',side_effect=lambda p:deepcopy(records[p])),patch.object(players,'SessionManager',return_value=manager),patch.object(players,'api',return_value=dict(adminInfo=dict(username='wulv'))),patch.object(players,'list_models',return_value=[dict(id=1)]),patch.object(players,'recalculate_category',category),redirect_stdout(output):
                        try:players.bulk_main()
                        except ValueError as exc:return 1,dict(status='blocked_before_write',reason=str(exc))
                    return 0,json.loads(output.getvalue())
                namespace['run_writer_request']=dispatch
                job=json.loads((root/'queue'/(follow+'.json')).read_text(encoding='utf-8'))
                job['request']['v3_completion']={'status':'forged-client-proof'}
                with self.assertRaisesRegex(ValueError,'player_sync_original_job_mismatch'):namespace['handle'](dict(job,job_id=parent))
                result=namespace['handle'](job);self.assertEqual(result['status'],'confirmed');self.assertEqual(result['post_response'],receipt)
                self.assertEqual(requests[0]['v3_completion']['operation_id'],coin)
                with self.assertRaisesRegex(ValueError,'player_sync_not_confirmed'):namespace['handle'](job)
                category.assert_called_once_with(manager,observer=ANY)
                written=json.loads((root/'player-sync'/(follow+'.json')).read_text(encoding='utf-8'))
                self.assertEqual(written['price_verification'],'disabled');self.assertEqual(written['sample_count'],0)
                db.put('operations',coin,dict(closed,status='UNKNOWN'))
                with self.assertRaisesRegex(ValueError,'player_sync_coin_not_confirmed'):namespace['handle'](job)
                self.assertEqual(len(requests),2)
                queued=enqueue.call_count
                self.assertEqual(runtime.complete_player_followup(dict(closed,status='NO_CHANGE'))['status'],'NO_CHANGE')
                self.assertEqual(enqueue.call_count,queued)
                db.put('operations',coin,closed)
                with patch.object(worker,'save_job',side_effect=OSError('disk_full')):
                    kept=runtime.complete_player_followup(closed)
                self.assertEqual(kept['status'],'COMPLETED')
                self.assertEqual(kept['player_sync_followup'],dict(status='pending',reason='OSError'))

    def test_operator_triggered_program_has_bound_proof_but_legacy_manual_and_changed_amounts_do_not(self):
        audit=execution();self.assertTrue(players.verified_v3_coin_execution(audit))
        for mutate in (
            lambda r:r.pop('pricing_decision_receipt'),
            lambda r:r.update(status='UNCERTAIN'),
            lambda r:r['pricing_decision_receipt'].update(decision_bundle_id=JOB),
            lambda r:r['pricing_decision_receipt'].update(financial_contract_version='fc27_dual10_v15'),
            lambda r:r['pricing_decision_receipt']['financial_proof'].update(pass_all=False),
            lambda r:r['after']['rows'][0].update(b2c='.11')):
            changed=deepcopy(audit);mutate(changed);self.assertFalse(players.verified_v3_coin_execution(changed))

    def test_category_runs_once_for_V3_with_no_player_price_sample_and_second_attempt_is_refused(self):
        audit=execution();request=dict(job_id=JOB,coin_execution_id=COIN,config_revision=10);policy=dict(enabled=True,revision=10)
        records={players.REQUEST:request,players.EXECUTION:audit,players.POLICY:policy};manager=Mock();manager.ensure.return_value=True
        with TemporaryDirectory() as folder,patch.object(players,'ROOT',Path(folder)),patch.object(players,'read',side_effect=lambda p:deepcopy(records[p])),patch.object(players,'SessionManager',return_value=manager),patch.object(players,'api',return_value=dict(adminInfo=dict(username='wulv'))),patch.object(players,'list_models',return_value=[dict(id=1),dict(id=2)]),patch.object(players,'recalculate_category') as post,redirect_stdout(io.StringIO()):
            players.bulk_main()
            ledger=json.loads((Path(folder)/(JOB+'.json')).read_text())
            self.assertEqual(ledger['status'],'confirmed');self.assertEqual(ledger['sample_count'],0);self.assertEqual(ledger['price_verification'],'disabled')
            with self.assertRaisesRegex(ValueError,'already_started'):players.bulk_main()
            post.assert_called_once_with(manager,observer=ANY)

    def test_missing_program_proof_is_rejected_before_session_or_category_request(self):
        audit=execution();audit.pop('pricing_decision_receipt')
        records={players.REQUEST:dict(job_id=JOB,coin_execution_id=COIN,config_revision=10),players.EXECUTION:audit,players.POLICY:dict(enabled=True,revision=10)}
        with patch.object(players,'read',side_effect=lambda p:records[p]),patch.object(players,'SessionManager') as session,patch.object(players,'recalculate_category') as post:
            with self.assertRaisesRegex(ValueError,'preflight_changed'):players.bulk_main()
            session.assert_not_called();post.assert_not_called()

    def test_release_only_accepts_proven_zero_dispatch_not_unknown_or_any_existing_ledger(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);(root/'jobs').mkdir();(root/'player-sync').mkdir()
            record=dict(job_id=JOB,kind='player_sync',created_at='2026-10-27T00:00:00+00:00',request=dict(config_revision=10),status='failed',error='player_sync_not_confirmed',sync_result=dict(status='blocked_before_write',reason='player_sync_preflight_changed'))
            path=root/'jobs'/(JOB+'.json');path.write_text(json.dumps(record))
            tick=SimpleNamespace(ROOT=root,retry_guard=Mock(return_value='player_sync_unconfirmed'),load_player_sync_policy=lambda:dict(revision=10),read_record=lambda p:json.loads(p.read_text()))
            api=SimpleNamespace(health=Mock(return_value=dict(incomplete_executions=0)))
            self.assertTrue(readiness.fc_release_quiescent(tick,api))
            for status,result in [('failed',dict(status='UNKNOWN')),('running',record['sync_result'])]:
                path.write_text(json.dumps(dict(record,status=status,sync_result=result)));self.assertFalse(readiness.fc_release_quiescent(tick,api))
            path.write_text(json.dumps(record));(root/'player-sync'/(JOB+'.json')).write_text('{}')
            self.assertFalse(readiness.fc_release_quiescent(tick,api))
            tick.retry_guard.return_value='queue_busy';self.assertFalse(readiness.fc_release_quiescent(tick,api))
            tick.retry_guard.return_value='ready';api.health.return_value=dict(incomplete_executions=1);self.assertFalse(readiness.fc_release_quiescent(tick,api))


    def test_category_receipt_preserves_http_parse_business_and_transport_boundaries(self):
        import hashlib
        manager=SimpleNamespace(token='private-token',config={'P2PAH_API_BASE':'http://127.0.0.1:8912'})
        cases=[
            (502,b'<html>private body</html>',None,'backend_response_invalid'),
            (200,b'not JSON private body',None,'backend_response_invalid'),
            (200,b'{"code":401,"msg":"private message"}',401,'backend_request_rejected'),
            (200,b'{"code":"1","msg":"private message"}',None,'backend_request_rejected'),
            (502,b'{"code":0,"msg":"private message"}',0,'backend_request_rejected'),
            (200,b'{"code":1,"data":{"accepted":true}}',1,None),
        ]
        for status,raw,code,error in cases:
            with self.subTest(status=status,code=code,error=error):
                response=Mock();response.status=status;response.read.return_value=raw
                response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
                outcome=players.urllib.error.HTTPError('http://private-url',status,'private message',{},io.BytesIO(raw)) if status!=200 else response
                receipts=[]
                with patch.object(players.urllib.request,'urlopen',side_effect=[outcome]) as post:
                    if error:
                        with self.assertRaisesRegex(ValueError,error):players.recalculate_category(manager,observer=receipts.append)
                    else:self.assertEqual(players.recalculate_category(manager,observer=receipts.append),{'accepted':True})
                if status!=200:outcome.close()
                self.assertEqual(post.call_count,1);self.assertEqual(post.call_args.kwargs,{'timeout':300})
                request=post.call_args.args[0]
                self.assertEqual(request.method,'POST');self.assertEqual(json.loads(request.data),{'gid':1327,'cid':9627,'id':[]})
                self.assertEqual(len(receipts),1);receipt=receipts[0]
                self.assertEqual(set(receipt),{'path','started_at','received_at','http_status','response_code','response_sha256'})
                self.assertEqual(receipt['http_status'],status);self.assertEqual(receipt['response_code'],code)
                self.assertEqual(receipt['response_sha256'],hashlib.sha256(raw).hexdigest())
                self.assertNotIn('private',json.dumps(receipt));self.assertEqual(receipt['path'],'/admin/goods.GoodsMould/recalcFc27Price')
        receipts=[]
        with patch.object(players.urllib.request,'urlopen',side_effect=players.urllib.error.URLError('private error')) as post:
            with self.assertRaises(players.urllib.error.URLError):players.recalculate_category(manager,observer=receipts.append)
        self.assertEqual(post.call_count,1);self.assertEqual(receipts[0]['transport_error'],'URLError')
        self.assertEqual(set(receipts[0]),{'path','started_at','received_at','transport_error'})
        self.assertNotIn('private',json.dumps(receipts))

    def test_bulk_persists_same_receipt_in_ledger_and_worker_result_without_replay(self):
        for status,raw in [(502,b'private non JSON'),(200,b'{"code":401}'),(200,b'{"code":1,"data":{}}'),(None,b'')]:
            with self.subTest(status=status,raw=raw),TemporaryDirectory() as folder:
                records={players.REQUEST:dict(job_id=JOB,coin_execution_id=COIN,config_revision=10),players.EXECUTION:execution(),players.POLICY:dict(enabled=True,revision=10)}
                manager=Mock();manager.ensure.return_value=True;manager.token='private-token';manager.config={'P2PAH_API_BASE':'http://127.0.0.1:8912'}
                response=Mock();response.status=status;response.read.return_value=raw;response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
                outcome=players.urllib.error.URLError('private transport') if status is None else players.urllib.error.HTTPError('private-url',status,'private',{},io.BytesIO(raw)) if status!=200 else response
                output=io.StringIO();path=Path(folder)/(JOB+'.json')
                with patch.object(players,'ROOT',Path(folder)),patch.object(players,'read',side_effect=lambda p:deepcopy(records[p])),patch.object(players,'SessionManager',return_value=manager),patch.object(players,'api',return_value={'adminInfo':{'username':'wulv'}}),patch.object(players,'list_models',return_value=[{'id':1}]),patch.object(players.urllib.request,'urlopen',side_effect=[outcome]) as post,redirect_stdout(output):
                    if status==200 and b'"code":1,' in raw:players.bulk_main()
                    else:
                        with self.assertRaises(SystemExit) as stopped:players.bulk_main()
                        self.assertEqual(stopped.exception.code,2)
                    if status!=200 and status is not None:outcome.close()
                    ledger=json.loads(path.read_text());result=json.loads(output.getvalue())
                    self.assertEqual(ledger['post_response'],result['post_response'])
                    if status is None:self.assertEqual(result['post_response']['transport_error'],'URLError')
                    self.assertEqual(ledger['status'],result['status']);self.assertEqual(ledger['job_id'],JOB)
                    self.assertEqual(ledger['status'],'confirmed' if b'"code":1,' in raw else 'needs_reconcile')
                    self.assertNotIn('private',json.dumps(ledger));self.assertNotIn('private',output.getvalue())
                    before=path.read_bytes()
                    with self.assertRaisesRegex(ValueError,'already_started'):players.bulk_main()
                    self.assertEqual(path.read_bytes(),before);self.assertEqual(post.call_count,1)

    def test_category_body_read_error_keeps_received_http_status_and_still_sends_once(self):
        manager=SimpleNamespace(token='private-token',config={'P2PAH_API_BASE':'http://127.0.0.1:8912'})
        response=Mock();response.status=200;response.read.side_effect=OSError('private body error')
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        receipts=[]
        with patch.object(players.urllib.request,'urlopen',return_value=response) as post:
            with self.assertRaises(OSError):players.recalculate_category(manager,observer=receipts.append)
        self.assertEqual(post.call_count,1);self.assertEqual(receipts[0]['http_status'],200)
        self.assertEqual(receipts[0]['transport_error'],'OSError');self.assertNotIn('private',json.dumps(receipts))
        self.assertNotIn('response_sha256',receipts[0])

    def test_receipt_persistence_failure_does_not_send_category_again(self):
        manager=SimpleNamespace(token='private-token',config={'P2PAH_API_BASE':'http://127.0.0.1:8912'})
        response=Mock();response.status=200;response.read.return_value=b'{"code":1}'
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        observer=Mock(side_effect=OSError('ledger unavailable'))
        with patch.object(players.urllib.request,'urlopen',return_value=response) as post:
            with self.assertRaises(OSError):players.recalculate_category(manager,observer=observer)
        self.assertEqual(post.call_count,1);self.assertEqual(observer.call_count,1)


if __name__=='__main__':unittest.main()
