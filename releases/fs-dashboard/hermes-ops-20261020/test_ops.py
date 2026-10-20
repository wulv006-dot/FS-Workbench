import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'source'))
import common
import watch
import host
from github_api import GitHub

NOW = datetime(2026, 10, 20, 10, tzinfo=timezone.utc)
PAGE = b'<!doctype html><html><head><link rel="stylesheet" href="brain.css"></head><body>unchanged</body></html>'

class Checks(unittest.TestCase):
    def snapshot(self):
        return {'captured_at': NOW.isoformat(), 'status': 'healthy', 'coin': {'config': {'system_enabled': True, 'mode': 'auto'}, 'schedule': {'next_at': (NOW+timedelta(hours=1)).isoformat()}}}

    def test_theme_only_adds_existing_dependencies(self):
        after = common.repair_html(PAGE)
        self.assertEqual(after.replace(''.join(common.UI_TAGS).encode(), b''), PAGE)
        self.assertEqual(common.repair_html(after), after)

    def test_partial_theme_no_duplicate(self):
        before = PAGE.replace(b'<head>', b'<head>'+common.UI_TAGS[0].encode())
        after = common.repair_html(before)
        self.assertEqual(after.count(common.UI_TAGS[0].encode()), 1)
        self.assertEqual(after.count(b'fs-theme.js'), 1)

    def test_different_asset_version_refused(self):
        with self.assertRaises(ValueError): common.repair_html(PAGE.replace(b'<head>', b'<head><link href="/new/fs-tokens.css">'))

    def test_unrecognized_html_refused(self):
        with self.assertRaises(ValueError): common.repair_html(b'<head></head>')

    def test_disabled_is_observed_not_repaired(self):
        value = self.snapshot(); value['issues'] = [{'code': 'gallery_automation_disabled'}]
        value['coin']['config']['system_enabled'] = False
        value['coin']['schedule']['next_at'] = (NOW-timedelta(days=1)).isoformat()
        self.assertEqual(common.assess(value, NOW), [])

    def test_approved_noncore_degradation_does_not_dispatch_repair(self):
        value = self.snapshot(); value['issues'] = [{'level': 'warning', 'code': 'noncore_source_unavailable:IGGM'}]
        self.assertEqual(common.assess(value, NOW), [])

    def test_monitor_recipe_is_exact_and_fail_closed(self):
        after = (ROOT/'source/recipes/monitor-health/hooks.py').read_bytes()
        self.assertEqual(common.sha(after), common.MONITOR_AFTER)
        self.assertEqual(common.repair_content('monitor-health', after), after)
        with self.assertRaises(ValueError): common.repair_content('monitor-health', after+b'\n')
        with self.assertRaises(ValueError): common.repair_content('unknown', after)

    def test_overdue_is_business_issue(self):
        value = self.snapshot(); value['coin']['schedule']['next_at'] = (NOW-timedelta(minutes=16)).isoformat()
        self.assertIn('coin_schedule_overdue', common.assess(value, NOW))

    def test_unresolved_and_deferred_not_healthy(self):
        value = self.snapshot(); value['health'] = {'incomplete_executions': 1}; value['coin']['job'] = {'result': 'deferred_player_sync'}
        self.assertIn('business_write_unresolved', common.assess(value, NOW))
        self.assertIn('coin_result_deferred_player_sync', common.assess(value, NOW))

    def test_stale_future_missing_refused(self):
        for stamp in ((NOW-timedelta(minutes=16)).isoformat(), (NOW+timedelta(minutes=2)).isoformat(), 'bad', '2026-10-20T10:00:00'):
            value = self.snapshot(); value['captured_at'] = stamp
            self.assertTrue(common.assess(value, NOW), stamp)

    def test_no_player_price_sampling(self):
        value = self.snapshot(); value['player'] = {'price_mismatch': True}
        self.assertEqual(common.assess(value, NOW), [])

    def test_symlink_parent_refused(self):
        with patch.object(Path, 'is_symlink', lambda self: self.name == 'linked'):
            with self.assertRaises(ValueError): host.safe(Path('/root/linked/child.json'))

    def test_claim_exact_incident_and_expiry(self):
        request = {'incident': 'a'*16}
        claim = {'active': True, 'owner': 'codex', 'incident': 'a'*16, 'claimed_at': NOW.isoformat()}
        with patch.object(host, 'read', return_value=claim):
            self.assertTrue(host.claim_active(request, NOW))
            self.assertFalse(host.claim_active(request, NOW+timedelta(minutes=61)))
            self.assertFalse(host.claim_active({'incident': 'b'*16}, NOW))

    def test_unsupported_root_request_refused(self):
        for action in ('shell', 'fc-reset', 'clear-unknown'):
            with patch.object(host, 'read', return_value={'action': action, 'incident': 'a'*16, 'created_at': NOW.isoformat()}):
                with self.assertRaises(ValueError): host.process(NOW)

    def test_generated_recipe_bundles(self):
        for path in (ROOT/'repairs').glob('*/proof.json'):
            proof = json.loads(path.read_text())
            name = 'brain-index.html' if proof['recipe'] == 'brain-theme' else 'hooks.py'
            before = (path.parent/'before'/name).read_bytes()
            after = (path.parent/'source'/name).read_bytes()
            self.assertEqual(proof, {'recipe': proof['recipe'], 'before': common.sha(before), 'after': common.sha(after)})
            self.assertEqual(common.repair_content(proof['recipe'], before), after)

class PipelineChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root/'state'; self.state.mkdir()
        self.profile = self.root/'profile'; self.profile.mkdir()
        self.brain = self.root/'brain.html'; self.brain.write_bytes(PAGE)
        self.stack = __import__('contextlib').ExitStack(); self.addCleanup(self.stack.close)
        for key,value in (('STATE',self.state),('PROFILE',self.profile),('BRAIN',self.brain),('write',watch.write)):
            self.stack.enter_context(patch.object(host,key,value))
        watch.write(self.profile/'request.json', {'incident':'a'*16,'action':'brain-theme','created_at':NOW.isoformat()})

    def test_wait_claim_then_ci_merge_publish_exactly_once(self):
        events=[]
        class FakeGit:
            def __init__(self, path): pass
            def create_pr(self, branch, title, body, files):
                events.append('pr'); self_files=list(files)
                assert len(self_files)==3 and all(p.startswith(host.PREFIX+'a'*16+'/') for p in self_files)
                return {'number':1,'url':'https://github.com/test/pull/1','head':'h','base':'b'}
            def ready(self, pr): events.append('ci'); return True
            def request(self,*args): events.append('merge'); return {'merged':True,'sha':'m'}
        def published(record, github, now): events.append('publish'); return dict(record,status='published_file_readback_verified')
        with patch.object(host,'GitHub',FakeGit),patch.object(host,'publish_repair',published):
            host.process(NOW)
            self.assertEqual(events,[])
            watch.write(self.profile/'claim-codex.json',{'active':True,'owner':'codex','incident':'a'*16,'claimed_at':NOW.isoformat()})
            host.process(NOW+timedelta(minutes=11)); self.assertEqual(events,[])
            watch.write(self.profile/'claim-codex.json',{'active':False})
            host.process(NOW+timedelta(minutes=12))
            self.assertEqual(events,['pr','ci','merge','publish'])
            host.process(NOW+timedelta(minutes=13))
            self.assertEqual(events,['pr','ci','merge','publish'])

    def test_unknown_pr_write_is_not_repeated(self):
        host.process(NOW)
        fake = unittest.mock.Mock()
        fake.create_pr.side_effect = TimeoutError()
        with patch.object(host,'GitHub',return_value=fake):
            with self.assertRaises(TimeoutError): host.process(NOW+timedelta(minutes=11))
            host.process(NOW+timedelta(minutes=12))
            self.assertEqual(fake.create_pr.call_count,1)

class WatchChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        watch.write(self.home/'private-target.json', {'target':'feishu:private-test'})
        self.calls = []

    def snapshot(self, issues=None, **extra):
        watch.write(self.home/'snapshot.json', dict(exported_at=NOW.isoformat(), issues=issues or [], **extra))

    def transport(self, text, target):
        self.calls.append((text, target)); return {'success':True, 'message_id':'test-id'}

    def test_healthy_no_notification(self):
        self.snapshot()
        self.assertEqual(watch.run(self.home, self.transport, NOW)['state'], 'healthy_quiet')
        self.assertEqual(self.calls, [])

    def test_incident_change_only_and_recovery(self):
        self.snapshot(['latest_coin_job_failed'])
        self.assertEqual(watch.run(self.home, self.transport, NOW)['state'], 'sent')
        self.assertEqual(watch.run(self.home, self.transport, NOW)['state'], 'unchanged_quiet')
        self.snapshot()
        self.assertEqual(watch.run(self.home, self.transport, NOW)['state'], 'sent')
        self.assertEqual(len(self.calls), 2)
        self.snapshot(['latest_coin_job_failed'])
        self.assertEqual(watch.run(self.home, self.transport, NOW+timedelta(seconds=1))['state'], 'sent')
        self.assertEqual(len(self.calls), 3)

    def test_group_routes_both_owners(self):
        config = {'owners': {'codex': 'ou_codex', 'workbuddy': 'ou_buddy'}}
        text = watch.task_text(['latest_coin_job_failed', 'rpg_task_failed:poe2:collect:abc'], config, 'a'*16)
        self.assertIn('<at user_id="ou_codex"></at> FC / FS', text)
        self.assertIn('<at user_id="ou_buddy"></at> RPG', text)

    def test_unknown_notification_does_not_request_repair(self):
        self.snapshot(['brain_ui_dependencies_missing'], brain={'repairable':True})
        watch.run(self.home, lambda *args: {'success':True}, NOW)
        self.assertFalse((self.home/'request.json').exists())

    def test_unknown_send_never_retried(self):
        self.snapshot(['coin_schedule_overdue'])
        def uncertain(text, target): self.calls.append(1); raise TimeoutError()
        self.assertEqual(watch.run(self.home, uncertain, NOW)['state'], 'notification_unknown_no_retry')
        self.assertEqual(watch.run(self.home, uncertain, NOW)['state'], 'notification_unknown_no_retry')
        self.assertEqual(len(self.calls), 1)

    def test_accepted_without_message_id_is_unknown(self):
        self.snapshot(['failed'])
        self.assertEqual(watch.run(self.home, lambda *args: {'success':True}, NOW)['state'], 'notification_unknown_no_retry')

    def test_fresh_export_required(self):
        self.snapshot()
        watch.run(self.home, self.transport, NOW+timedelta(minutes=16))
        self.assertIn('watchdog_export_stale', self.calls[0][0])

    def test_only_known_recipe_is_requested(self):
        self.snapshot(['brain_ui_dependencies_missing'], brain={'repairable':True})
        watch.run(self.home, self.transport, NOW)
        self.assertEqual(watch.read(self.home/'request.json')['action'], 'brain-theme')
        self.assertFalse((self.home/'claim.json').exists())

    def test_install_scope_is_bounded(self):
        spec = importlib.util.spec_from_file_location('ops_install', ROOT/'deploy/install.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertEqual(len(module.MAP), 14)
        self.assertFalse(any('/opt/fc27-cloud-browser/' in str(p) for p in module.MAP.values()))
        timer = (ROOT/'deploy/fs-hermes-ops-bridge.timer').read_text()
        self.assertIn('Persistent=false', timer)
        self.assertIn('OnUnitActiveSec=5min', timer)

class GitChecks(unittest.TestCase):
    def client(self, changed=None, conclusion='success'):
        github = object.__new__(GitHub)
        def request(method, path, body=None):
            if path.startswith('/pulls/'): return {'head':{'sha': 'h' if changed != 'head' else 'new'}, 'base':{'sha':'b'}, 'mergeable_state':'clean'}
            if path == '/git/ref/heads/main': return {'object':{'sha':'b' if changed != 'base' else 'new'}}
            return {'check_runs':[{'name':'pr-fast','status':'completed','conclusion':conclusion}]}
        github.request = request
        return github

    def test_exact_head_base_ci_required(self):
        pr={'number':1,'head':'h','base':'b'}
        self.assertTrue(self.client().ready(pr))
        for field in ('head','base'):
            with self.assertRaises(ValueError): self.client(changed=field).ready(pr)
        for conclusion in ('failure', 'skipped', 'cancelled'):
            with self.assertRaises(ValueError): self.client(conclusion=conclusion).ready(pr)

if __name__ == '__main__': unittest.main(verbosity=2)
