import datetime as dt
import tempfile
import unittest
from pathlib import Path
from mmoexp_google_data.seo import ai_policy, ai_bridge, daily, store
from test_daily_snapshot import NIGHT, Source


class AiPolicy(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.policy=ai_policy.PolicyStore(self.root/'seo-control')
        self.actor=ai_policy.Actor('fixture-admin',('FC27','D4','AION2','WOW_FOREVER'),True,True)

    def enable(self):
        return self.policy.update({'ai_enabled':True,'projects':{'FC27':True,'D4':True}},0,self.actor)

    def test_defaults_off_and_cas_permission(self):
        self.assertFalse(self.policy.allowed('FC27',self.actor))
        self.enable()
        with self.assertRaises(ValueError):self.policy.update({'ai_enabled':False},0,self.actor)
        with self.assertRaises(PermissionError):self.policy.update({'ai_enabled':False},1,ai_policy.Actor('member',('FC27',),False,True))
        self.assertFalse(self.policy.allowed('AION2',self.actor))

    def test_off_on_does_not_revive_old_generation(self):
        self.enable();token=self.policy.token('FC27')
        self.policy.update({'projects':{'FC27':False}},1,self.actor)
        self.policy.update({'projects':{'FC27':True}},2,self.actor)
        self.assertFalse(self.policy.allowed('FC27',self.actor,token))
        self.assertTrue(self.policy.allowed('D4',self.actor))

    def test_other_game_toggle_does_not_cancel_current_game(self):
        self.enable();token=self.policy.token('FC27')
        self.policy.update({'projects':{'D4':False}},1,self.actor)
        self.assertTrue(self.policy.allowed('FC27',self.actor,token))

    def test_disabled_games_never_enter_provider_scope_or_change_base(self):
        self.enable()
        core=store.Store(self.root/'core')
        receipt=daily.run_daily(core,[Source()],clock=lambda:NIGHT)
        calls=[]
        def provider(payload,gate):
            gate();calls.append(payload)
            return dict(text='fixture analysis',receipt='fixture-receipt',usage=dict(tokens=10),provider_ref='fixture')
        bridge=ai_bridge.Bridge(core.root,self.root/'seo-ai',self.policy,self.actor,provider,clock=lambda:NIGHT)
        result=bridge.run(receipt['snapshot_id'])
        self.assertEqual([p['game'] for p in calls],['FC27','D4'])
        self.assertTrue(all(set(p['facts'])=={'game','history'} for p in calls))
        self.assertEqual(result['ready'],2)
        self.assertEqual(bridge.run(receipt['snapshot_id'])['ready'],0)

    def test_inflight_disable_discards_result_but_retains_receipt(self):
        self.enable()
        core=store.Store(self.root/'core');receipt=daily.run_daily(core,[Source()],clock=lambda:NIGHT)
        def provider(payload,gate):
            gate()
            policy=self.policy.read()
            self.policy.update({'projects':{'FC27':False}},policy['revision'],self.actor)
            return dict(text='late',receipt='already-submitted',usage={'tokens':10},provider_ref='fixture')
        bridge=ai_bridge.Bridge(core.root,self.root/'seo-ai',self.policy,self.actor,provider,clock=lambda:NIGHT)
        bridge.run(receipt['snapshot_id'])
        status=bridge.status(receipt['snapshot_id'],'FC27')
        self.assertEqual(status['status'],'cancelled')
        self.assertEqual(status['provider_receipt'],'already-submitted')
        self.assertIsNone(status['text'])

    def test_daytime_recovery_has_zero_provider_calls(self):
        self.enable()
        def provider(*a):raise AssertionError('daytime paid call')
        bridge=ai_bridge.Bridge(self.root,self.root/'seo-ai',self.policy,self.actor,provider,clock=lambda:NIGHT+dt.timedelta(hours=8))
        self.assertEqual(bridge.run('seo-2026-11-05')['status'],'outside_night_window')


if __name__=='__main__':unittest.main()
