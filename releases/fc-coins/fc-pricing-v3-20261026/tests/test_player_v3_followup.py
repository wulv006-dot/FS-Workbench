from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType,SimpleNamespace
from unittest.mock import Mock,patch
from contextlib import redirect_stdout
import importlib.util,io,json,sys,unittest

RELEASE=Path(__file__).resolve().parents[1]
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
            post.assert_called_once_with(manager)

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


if __name__=='__main__':unittest.main()
