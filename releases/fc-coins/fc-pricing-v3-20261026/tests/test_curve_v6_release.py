import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'
ROOT = DEPLOY.parents[3]
sys.path.insert(0, str(DEPLOY))
import build_stage
import fc_v3_release_adapter as adapter
import prepare_manifest as prepare
import target_map

RELEASE = DEPLOY.parent.relative_to(ROOT).as_posix()
SOURCE = DEPLOY.parent / 'source'
BASE = target_map.CURVE_V6_BASE


class CurveV6Release(unittest.TestCase):
    def test_observer_cache_stage_has_only_the_live_controller_delta(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'cache.tar.gz'
            with patch.object(build_stage.subprocess, 'check_output', side_effect=['a' * 40, '']), \
                 patch.object(build_stage, 'git_blob', side_effect=lambda _, path, rev: path.read_bytes().replace(b'\r\n', b'\n')):
                built = build_stage.build(ROOT, output, curve_recovery='observer-cache')
            self.assertEqual(built['targets'], 3)
            with tarfile.open(output) as bundle:
                manifest = json.load(bundle.extractfile('fc-pricing-v3-20261026/source-manifest.json'))
            self.assertEqual(set(manifest['files']), {'source/control-role/manifest.json',
                'source/control-role/fc_collection/package_routes.py', 'source/control-role/fc_collection/package_relay.py'})

    def test_observer_status_stage_binds_bounded_control_files_to_role_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'observer.tar.gz'
            with patch.object(build_stage.subprocess, 'check_output', side_effect=['a' * 40, '']), \
                 patch.object(build_stage, 'git_blob', side_effect=lambda _, path, rev: path.read_bytes().replace(b'\r\n', b'\n')):
                build_stage.build(ROOT, output, curve_recovery='observer-status')
            with tarfile.open(output) as bundle:
                prefix = 'fc-pricing-v3-20261026/candidate/source/control-role/'
                manifest = json.load(bundle.extractfile(prefix + 'manifest.json'))
                names = {member.name.removeprefix(prefix) for member in bundle.getmembers()
                         if member.isfile() and member.name.startswith(prefix)}
                self.assertEqual(names, {'manifest.json', 'fc_collection/client.py',
                                         'fc_collection/package_routes.py', 'fc_collection/package_relay.py'})
                for name in names - {'manifest.json'}:
                    self.assertEqual(hashlib.sha256(bundle.extractfile(prefix + name).read()).hexdigest(),
                                     manifest['sha256'][name])

    def test_market_packages_stage_binds_both_hermes_market_readers_to_the_same_commit(self):
        origin = 'releases/fs-dashboard/fc-coins-workflow-20261022/source/'
        commit = 'a' * 40
        names = ('research.py', 'fs_evidence.py')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'market.tar.gz'
            with patch.object(build_stage.subprocess, 'check_output', side_effect=[commit, '']) as git, \
                 patch.object(build_stage, 'git_blob', side_effect=lambda _, path, rev: path.read_bytes().replace(b'\r\n', b'\n')) as blob:
                build_stage.build(ROOT, output, curve_recovery='market-packages')
            with tarfile.open(output) as bundle:
                prefix = 'fc-pricing-v3-20261026/'
                provenance = json.load(bundle.extractfile(prefix + 'source-manifest.json'))
                for name in names:
                    candidate = 'source/' + name
                    self.assertEqual(adapter.SCOPED_TARGETS[provenance['scope']].get(candidate), '/opt/fs-hermes-fc/' + name)
                    self.assertEqual(provenance['repositorySources'][candidate], origin + name)
                    self.assertIn(origin + name, git.call_args.args[0])
                    blob.assert_any_call(ROOT, ROOT / (origin + name), commit)
                    self.assertEqual(bundle.extractfile(prefix + 'candidate/' + candidate).read(),
                                     (ROOT / (origin + name)).read_bytes().replace(b'\r\n', b'\n'))

    def test_recovery_scope_only_packages_each_fix_and_rejects_mirror_drift(self):
        modules_by_fix = {
            'live-order-cost': (),
            'shared-order': ('business_source.py', 'runtime.py', 'average_discount_v6.py'),
            'round-latency': ('business_source.py', 'runtime.py', 'planning_baskets_v6.py'),
            'recent-orders': ('business_source.py', 'planning_baskets_v6.py', 'runtime.py'),
            'catalogue-inputs': ('runtime.py',),
            'cycle-recovery': ('scheduler.py',),
            'targeted-price-reads': ('business_source.py', 'daily.py'),
            'unit-price-sync': ('curve_strategy_v6.py', 'price_curve.py', 'runtime.py'),
            'bf-cost-guard': ('api.py', 'average_discount_v6.py', 'cost_inputs_v6.py', 'curve_strategy_v6.py',
                              'runtime.py'),
            'bf-fixes': ('api.py', 'average_discount_v6.py', 'curve_strategy_v6.py', 'price_curve.py', 'runtime.py'),
            'outcomes': ('business_source.py', 'daily.py'),
            'cost-incidents': ('cost_inputs_v6.py', 'ledger.py', 'runtime.py', 'scheduler.py'),
            'shared-evidence': ('api.py', 'pricing_proof_v6.py', 'runtime.py'),
        }
        for fix, modules in modules_by_fix.items():
            with self.subTest(fix=fix), tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / 'recovery.tar.gz'
                with patch.object(build_stage.subprocess, 'check_output', side_effect=['a' * 40, '']), \
                     patch.object(build_stage, 'git_blob', side_effect=lambda _, path, commit: path.read_bytes()):
                    built = build_stage.build(ROOT, output, curve_recovery=fix)
                with tarfile.open(output) as bundle:
                    provenance = json.load(bundle.extractfile('fc-pricing-v3-20261026/source-manifest.json'))
                expected = {}
                for name in modules:
                    expected['source/fc_pricing_v3/' + name] = '/opt/fc27-cloud-browser/fc_pricing_v3/' + name
                    expected['source/hermes-copy/fc_pricing_v3/' + name] = '/opt/fs-hermes-fc/fc_pricing_v3/' + name
                if fix in ('shared-order', 'live-order-cost', 'round-latency'):
                    expected['source/collect_p2pah_cost.py'] = '/opt/fc27-cloud-browser/collect_p2pah_cost.py'
                    expected['source/snapshot_layer.py'] = '/opt/fc27-cloud-browser/snapshot_layer.py'
                if fix == 'round-latency':
                    expected['source/fc27_cloud_worker.py'] = '/opt/fc27-cloud-browser/fc27_cloud_worker.py'
                if fix in ('targeted-price-reads', 'unit-price-sync', 'bf-fixes'):
                    expected['source/coin_all_sync_job.py'] = '/opt/fc27-cloud-browser/coin_all_sync_job.py'
                if fix == 'bf-cost-guard':
                    self.assertEqual(provenance['scope'], 'fc-pricing-v6-bf-cost-guard-20261127')
                    expected['source/collect_p2pah_cost.py'] = '/opt/fc27-cloud-browser/collect_p2pah_cost.py'
                if fix == 'bf-fixes':
                    self.assertEqual(provenance['scope'], 'fc-pricing-v6-bf-fixes-20261128')
                if fix in ('bf-cost-guard', 'bf-fixes'):
                    for name in ('fc-pricing-v3.js', 'fc27-coins.html'):
                        expected['source/' + name] = '/var/www/dashboard/' + name
                if fix == 'cycle-recovery':
                    expected['source/snapshot_layer.py'] = '/opt/fc27-cloud-browser/snapshot_layer.py'
                if fix == 'shared-evidence':
                    expected['source/fc_pricing_v3/business_source.py'] = '/opt/fc27-cloud-browser/fc_pricing_v3/business_source.py'
                    self.assertEqual(provenance['scope'], 'fc-pricing-v6-recovery-shared-evidence-20261120')
                self.assertEqual(built['targets'], len(expected))
                self.assertEqual(set(provenance['files']), set(expected))
                self.assertEqual(adapter.SCOPED_TARGETS[provenance['scope']], expected)
                files = [dict(candidate=name, target=path, sha256=provenance['files'][name],
                              beforeSha256='b' * 64, owner='0:0', mode='0o644')
                         for name, path in expected.items()]
                manifest = dict(scope=provenance['scope'], releaseReady=True, businessWrites=False,
                                timersChanged=False, files=files)
                self.assertIs(adapter.checked_manifest(manifest), manifest)
                if fix == 'shared-evidence':
                    extra = dict(files[-1], candidate='source/hermes-copy/fc_pricing_v3/business_source.py',
                                 target='/opt/fs-hermes-fc/fc_pricing_v3/business_source.py')
                    with self.assertRaisesRegex(ValueError, 'exact_fc_v3_targets_required'):
                        adapter.checked_manifest(dict(manifest, files=files + [extra]))
                    for field in ('businessWrites', 'timersChanged'):
                        with self.assertRaisesRegex(ValueError, 'code_release_does_not_change_business_or_timer_state'):
                            adapter.checked_manifest(dict(manifest, **{field: True}))
                if modules:
                    files[1]['sha256'] = 'c' * 64
                    with self.assertRaisesRegex(ValueError, 'module_copy_sha_mismatch'):
                        adapter.checked_manifest(manifest)
                else:
                    files.pop()
                    with self.assertRaises(ValueError):
                        adapter.checked_manifest(manifest)


    def test_order_cost_scope_pairs_fc_modules_and_only_overlays_the_pinned_live_channel_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            live = root/'active-channel-source.py'
            active = (b"def enrich(data):\n    if data:\n        cost_info = {}\n"
                      b"        data['sources']['cost'] = cost_info\n    return data\n")
            live.write_bytes(active)
            before = hashlib.sha256(active).hexdigest()
            output = root/'order-cost.tar.gz'
            with patch.dict(target_map.ORDER_COST_CHANNEL_OVERLAY, beforeSha256=before), \
                 patch.object(build_stage.subprocess, 'check_output', side_effect=['a'*40, '']), \
                 patch.object(build_stage, 'git_blob', side_effect=lambda _, path, commit:
                              path.read_bytes().replace(b'\r\n', b'\n')):
                built = build_stage.build(ROOT, output, curve_recovery='order-cost', order_cost_channel_baseline=live)
                with tarfile.open(output) as bundle:
                    prefix = 'fc-pricing-v3-20261026/'
                    provenance = json.load(bundle.extractfile(prefix+'source-manifest.json'))
                    candidate = bundle.extractfile(prefix+'candidate/source/channel_source.py').read()
                self.assertEqual(candidate.replace(target_map.ORDER_COST_CHANNEL_INSERT, b'', 1), active)
                self.assertEqual(provenance['liveSourceOverlays'], [target_map.ORDER_COST_CHANNEL_OVERLAY])
                expected = {
                    'source/collect_p2pah_cost.py': '/opt/fc27-cloud-browser/collect_p2pah_cost.py',
                    'source/channel_source.py': '/opt/fs-hermes-fc/channel_source.py',
                    'source/fc_pricing_v3/business_source.py': '/opt/fc27-cloud-browser/fc_pricing_v3/business_source.py',
                    'source/hermes-copy/fc_pricing_v3/business_source.py': '/opt/fs-hermes-fc/fc_pricing_v3/business_source.py',
                }
                self.assertEqual(built['targets'], 4)
                self.assertEqual(adapter.SCOPED_TARGETS[provenance['scope']], expected)
                self.assertEqual(target_map.ORDER_COST_FC_BASELINES['source/collect_p2pah_cost.py'],
                                 '7c60ad5d4dc517b7e6c6b9a93cf6e8fba2f5ef0f2df9fed96411b94335ae351e')
                files = [dict(candidate=name, target=path, sha256=provenance['files'][name],
                              beforeSha256=target_map.ORDER_COST_FC_BASELINES.get(name, before),
                              owner='0:0', mode='0o644') for name, path in expected.items()]
                manifest = dict(scope=provenance['scope'], releaseReady=True, businessWrites=False,
                                timersChanged=False, files=files)
                self.assertIs(adapter.checked_manifest(manifest), manifest)
                for index, component in ((0, 'fc'), (1, 'channel')):
                    with self.subTest(component=component):
                        original = files[index]['beforeSha256']
                        files[index]['beforeSha256'] = 'b'*64
                        with self.assertRaisesRegex(ValueError, 'order_cost_'+component+'_baseline_drift'):
                            adapter.checked_manifest(manifest)
                        files[index]['beforeSha256'] = original
                live.write_bytes(active+b'# drift\n')
                with self.assertRaisesRegex(ValueError, 'order_cost_channel_baseline_drift'):
                    build_stage.build(ROOT, output, curve_recovery='order-cost', order_cost_channel_baseline=live)

    def test_order_http_cost_prepares_shared_reader_and_collectors_from_the_live_baseline(self):
        key = 'order-http-cost'
        expected_sources = {
            'source/order_http.py': 'order_global_session_20261021/order_http.py',
            'source/collect_p2pah_cost.py': RELEASE + '/source/collect_p2pah_cost.py',
            'source/collect_p2pah_cost.sh':
                'releases/fc-coins/cost-timeout-20261025/source/collect_p2pah_cost.sh',
        }
        before = {
            'source/order_http.py': '4bc456a1146df3934b071c694607f2692424fb9ff8c2724cf5912247ab564256',
            'source/collect_p2pah_cost.py': 'ffff1ea5ee7e5218c47f9a91b451c8f47862bb02c029ed4c8f732e18aae810f8',
            'source/collect_p2pah_cost.sh': '3ed23e6e88b27247164559e06d5884fd3fda57aeb086e9442970ff9da04e65cd',
        }
        expected_targets = {
            'source/order_http.py': '/opt/fs-order-session/order_http.py',
            'source/collect_p2pah_cost.py': '/opt/fc27-cloud-browser/collect_p2pah_cost.py',
            'source/collect_p2pah_cost.sh': '/opt/fc27-cloud-browser/collect_p2pah_cost.sh',
        }
        # Replay the immutable historical release, including its original collector.
        commit = '48b7c3f77529399e2452e7987d14a9d982c27991'
        payloads = {source: build_stage.git_blob(ROOT, ROOT / source, commit) for source in expected_sources.values()}
        check_output = build_stage.subprocess.check_output

        def historical_git(args, **kwargs):
            if args[1] == 'rev-parse':
                return commit
            if args[1] == 'status':
                return ''
            return check_output(args, **kwargs)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / 'cost.tar.gz'
            with patch.object(build_stage.subprocess, 'check_output', side_effect=historical_git) as git:
                built = build_stage.build(ROOT, output, curve_recovery=key)
            self.assertEqual(built['targets'], 3)
            status = next(call.args[0] for call in git.call_args_list if call.args[0][1] == 'status')
            self.assertTrue(set(expected_sources.values()) <= set(status))
            with tarfile.open(output) as bundle:
                bundle.extractall(root, filter='data')
            stage = root / 'fc-pricing-v3-20261026'
            source_manifest = stage / 'source-manifest.json'
            provenance = json.loads(source_manifest.read_bytes())
            self.assertEqual(provenance['repositorySources'], expected_sources)
            after = {}
            for name, source in expected_sources.items():
                payload = payloads[source]
                self.assertEqual((stage / 'candidate' / name).read_bytes(), payload)
                after[name] = hashlib.sha256(payload).hexdigest()
            self.assertEqual(provenance['files'], after)
            candidate_release = json.loads(
                (ROOT / 'docs/planning/order-http-access-20261125/fc-cost-list-release-manifest.json').read_bytes())
            self.assertEqual(candidate_release['scope'], provenance['scope'])
            self.assertEqual({row['candidate']: row['source'] for row in candidate_release['files']},
                             expected_sources)
            self.assertEqual({row['candidate']: row['target'] for row in candidate_release['files']},
                             expected_targets)
            self.assertEqual({row['candidate']: row['beforeSha256'] for row in candidate_release['files']}, before)
            self.assertEqual({row['candidate']: row['sha256'] for row in candidate_release['files']}, after)
            self.assertEqual([name for name in after if before[name] != after[name]],
                             ['source/collect_p2pah_cost.py'])

            live_hashes = {Path(target): before[name] for name, target in expected_targets.items()}

            publisher = root / 'original_fc_publisher.py'
            publisher.write_bytes(b'# FC publisher fixture; inspect checks are supplied below\n')
            load_adapter = adapter.load_base

            def load_with_live_checks_stubbed():
                base = load_adapter()
                base.guards = Mock()
                base.retirement = Mock()
                real_digest = base.digest
                base.digest = lambda path: live_hashes[path] if path in live_hashes else real_digest(path)
                return base

            def live_path(value):
                path = Path(value)
                if path in live_hashes:
                    return SimpleNamespace(exists=lambda: True, parents=path.parents, digest=live_hashes[path],
                                           stat=lambda: SimpleNamespace(st_uid=0, st_gid=0, st_mode=0o644 if path.name == 'order_http.py' else 0o755))
                return path

            real_sha = prepare.sha
            with patch.object(prepare, 'STAGE', stage), patch.object(prepare, 'HERE', stage / 'deploy'), \
                 patch.object(prepare, 'regular'), \
                 patch.object(prepare, 'sha', side_effect=lambda path:
                              real_sha(path) if stage in path.parents else getattr(path, 'digest', 'e' * 64)), \
                 patch.object(prepare, 'Path', side_effect=live_path), \
                 patch.object(prepare.subprocess, 'check_output', return_value='ActiveState=active'), \
                 patch.object(adapter, 'HERE', stage / 'deploy'), \
                 patch.object(adapter, 'FC_PUBLISHER', publisher), \
                 patch.object(adapter, 'FC_SHA', hashlib.sha256(publisher.read_bytes()).hexdigest()), \
                 patch.object(adapter, 'load_base', side_effect=load_with_live_checks_stubbed):
                source_manifest.write_text(json.dumps(dict(provenance, repositorySources={})), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'order_http_cost_source_provenance_changed'):
                    prepare.prepare(curve_recovery=key)
                source_manifest.write_text(json.dumps(provenance), encoding='utf-8')
                result = prepare.prepare(curve_recovery=key)
            self.assertEqual((result['files'], result['existing'], result['new']), (3, 3, 0))
            self.assertEqual(result['inspect']['sourceCAS'], 'passed')
            self.assertFalse(result['inspect']['mutations'])
            manifest = json.loads((stage / 'approved-manifest.json').read_bytes())
            rows = manifest['files']
            self.assertEqual({row['candidate']: row['target'] for row in rows}, expected_targets)
            self.assertEqual({row['candidate']: row['beforeSha256'] for row in rows}, before)
            self.assertEqual({row['candidate']: row['sha256'] for row in rows}, after)
            for row in rows:
                changed = [dict(item, beforeSha256='f' * 64) if item is row else item for item in rows]
                with self.assertRaisesRegex(ValueError, 'order_http_cost_baseline_drift'):
                    adapter.checked_manifest(dict(manifest, files=changed))

    def test_hourly_cost_stage_and_original_adapter_require_the_exact_seven_targets(self):
        key = 'hourly-order-cost'
        updated_refresh = b"\ndef enrich(data):\n    return 'new refresh'\n"
        previous_refresh = b"\ndef enrich(data):\n    return 'old refresh'\n"
        live = b'# live-only integration\n' + previous_refresh + b"\ndef shared_view():\n    return 'live'\n"
        original = b'# canonical prefix\n' + previous_refresh + b"\ndef shared_view():\n    return 'canonical'\n"
        updated = original.replace(previous_refresh, updated_refresh)
        expected_content = live.replace(previous_refresh, updated_refresh)
        commit = 'a' * 40
        expected = {
            'source/channel_source.py': '/opt/fs-hermes-fc/channel_source.py',
            'source/fc_pricing_v3/business_source.py': '/opt/fc27-cloud-browser/fc_pricing_v3/business_source.py',
            'source/hermes-copy/fc_pricing_v3/business_source.py': '/opt/fs-hermes-fc/fc_pricing_v3/business_source.py',
            'source/fc_pricing_v3/ledger.py': '/opt/fc27-cloud-browser/fc_pricing_v3/ledger.py',
            'source/hermes-copy/fc_pricing_v3/ledger.py': '/opt/fs-hermes-fc/fc_pricing_v3/ledger.py',
            'source/fc_pricing_v3/scheduler.py': '/opt/fc27-cloud-browser/fc_pricing_v3/scheduler.py',
            'source/hermes-copy/fc_pricing_v3/scheduler.py': '/opt/fs-hermes-fc/fc_pricing_v3/scheduler.py',
        }
        self.assertNotIn('hourly-quarter-past', target_map.CURVE_RECOVERY_SCOPES)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline = root / 'live-channel.py'
            baseline.write_bytes(live)
            output = root / 'hourly.tar.gz'

            def git_blob(_, path, rev):
                if path == ROOT / target_map.ORDER_COST_CHANNEL_REPOSITORY:
                    self.assertIn(rev, (target_map.HOURLY_COST_CHANNEL_BASE, commit))
                    return original if rev == target_map.HOURLY_COST_CHANNEL_BASE else updated
                self.assertEqual(rev, commit)
                return path.read_bytes()

            with patch.dict(target_map.HOURLY_COST_CHANNEL_OVERLAY, beforeSha256=hashlib.sha256(live).hexdigest()), \
                 patch.object(build_stage.subprocess, 'check_output', side_effect=lambda cmd, **kwargs:
                              commit if cmd[1:2] == ['rev-parse'] else ''), \
                 patch.object(build_stage, 'git_blob', side_effect=git_blob):
                built = build_stage.build(ROOT, output, curve_recovery=key, order_cost_channel_baseline=baseline)
                self.assertEqual(built['targets'], 7)
                with tarfile.open(output) as bundle:
                    prefix = 'fc-pricing-v3-20261026/'
                    provenance = json.load(bundle.extractfile(prefix + 'source-manifest.json'))
                    files = {name: bundle.extractfile(prefix + 'candidate/' + name).read() for name in expected}
                self.assertEqual(provenance['sourceBaseCommit'], target_map.HOURLY_COST_CHANNEL_BASE)
                self.assertEqual(provenance['repositorySources'], {
                    'source/channel_source.py': target_map.ORDER_COST_CHANNEL_REPOSITORY})
                self.assertEqual(provenance['liveSourceOverlays'], [target_map.HOURLY_COST_CHANNEL_OVERLAY])
                self.assertEqual(provenance['files'], {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()})
                self.assertEqual(files['source/channel_source.py'], expected_content)
                self.assertEqual(adapter.SCOPED_TARGETS[provenance['scope']], expected)
                for name in ('scheduler.py', 'business_source.py', 'ledger.py'):
                    self.assertEqual(files['source/fc_pricing_v3/' + name],
                                     files['source/hermes-copy/fc_pricing_v3/' + name])

                for changed, error in ((original, 'refresh_change_missing'),
                                       (updated + b'# unrelated repository change\n', 'change_outside_refresh')):
                    updated = changed
                    with self.assertRaisesRegex(ValueError, 'hourly_cost_' + error):
                        build_stage.build(ROOT, output, curve_recovery=key, order_cost_channel_baseline=baseline)
                updated = original.replace(previous_refresh, updated_refresh)
                baseline.write_bytes(live + b'# concurrent live edit\n')
                with self.assertRaisesRegex(ValueError, 'hourly_cost_channel_baseline_changed'):
                    build_stage.build(ROOT, output, curve_recovery=key, order_cost_channel_baseline=baseline)
                baseline.write_bytes(live)
                with self.assertRaisesRegex(ValueError, 'order_cost_channel_baseline_required_for_scope'):
                    build_stage.build(ROOT, output, curve_recovery='outcomes', order_cost_channel_baseline=baseline)

                stage = root / 'stage'
                deployment = stage / 'deploy'
                deployment.mkdir(parents=True)
                for name, content in files.items():
                    path = stage / 'candidate' / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                manifest_source = stage / 'source-manifest.json'
                manifest_source.write_text(json.dumps(provenance))
                live_paths = {}
                for name in files:
                    current = root / 'targets' / name
                    current.parent.mkdir(parents=True, exist_ok=True)
                    current.write_bytes(live if name == 'source/channel_source.py' else b'old module')
                    live_paths[name.removeprefix('source/')] = str(current)

                def inspect(manifest, candidate_stage):
                    self.assertEqual(candidate_stage, stage)
                    rows = [dict(row, target=expected[row['candidate']]) for row in manifest['files']]
                    channel = next(row for row in rows if row['candidate'] == 'source/channel_source.py')
                    self.assertEqual(channel['beforeSha256'], target_map.HOURLY_COST_CHANNEL_OVERLAY['beforeSha256'])
                    value = dict(manifest, files=rows)
                    self.assertIs(adapter.checked_manifest(value), value)
                    with self.assertRaisesRegex(ValueError, 'exact_fc_v3_targets_required'):
                        adapter.checked_manifest(dict(value, files=rows[:-1]))
                    for row in rows:
                        if row['candidate'].startswith('source/hermes-copy/'):
                            changed = [dict(item, sha256='c' * 64) if item is row else item for item in rows]
                            with self.assertRaisesRegex(ValueError, 'module_copy_sha_mismatch'):
                                adapter.checked_manifest(dict(value, files=changed))
                    return {'verified': True}

                frozen = SimpleNamespace(HERMES_TARGETS={}, HERMES_CAPABILITY_TARGETS={},
                                         CAP_PROTECTED_SESSION=set(), HERMES_DIRECT_TARGETS={})
                regular, sha = prepare.regular, prepare.sha
                with patch.object(prepare, 'STAGE', stage), patch.object(prepare, 'HERE', deployment), \
                     patch.dict(prepare.CURVE_RECOVERY_TARGETS, {key: live_paths}), \
                     patch.object(prepare, 'regular', side_effect=lambda path, **kw:
                                  regular(path, **kw) if root in path.parents else None), \
                     patch.object(prepare, 'sha', side_effect=lambda path:
                                  sha(path) if root in path.parents else 'e' * 64), \
                     patch.object(prepare, 'stat', SimpleNamespace(S_IMODE=lambda _: 0o644)), \
                     patch.object(prepare, 'load_base', return_value=frozen), \
                     patch.object(prepare.subprocess, 'check_output', return_value='ActiveState=active'), \
                     patch.object(adapter, 'load_base', return_value=SimpleNamespace(inspect=inspect)):
                    channel = stage / 'candidate' / 'source/channel_source.py'
                    tampered = expected_content + b'# unexpected staged edit\n'
                    channel.write_bytes(tampered)
                    provenance['files']['source/channel_source.py'] = hashlib.sha256(tampered).hexdigest()
                    manifest_source.write_text(json.dumps(provenance))
                    with self.assertRaisesRegex(ValueError, 'order_cost_channel_overlay_changed'):
                        prepare.prepare(curve_recovery=key)
                    channel.write_bytes(expected_content)
                    provenance['files']['source/channel_source.py'] = hashlib.sha256(expected_content).hexdigest()
                    manifest_source.write_text(json.dumps(provenance))
                    result = prepare.prepare(curve_recovery=key)
                self.assertEqual((result['files'], result['existing'], result['new']), (7, 7, 0))

    def test_arab_quote_scope_uses_only_identical_existing_market_registry_copies(self):
        scope = 'fc-pricing-v6-arab-quote-20261119'
        expected = {
            'source/fc_pricing_v3/market_registry.py': '/opt/fc27-cloud-browser/fc_pricing_v3/market_registry.py',
            'source/hermes-copy/fc_pricing_v3/market_registry.py': '/opt/fs-hermes-fc/fc_pricing_v3/market_registry.py',
        }
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'arab-quote.tar.gz'
            with patch.object(build_stage.subprocess, 'check_output', side_effect=['a' * 40, '']), \
                 patch.object(build_stage, 'git_blob', side_effect=lambda _, path, commit: path.read_bytes()):
                result = build_stage.build(ROOT, output, curve_arab_quote=True)
            with tarfile.open(output) as bundle:
                prefix = 'fc-pricing-v3-20261026/'
                provenance = json.load(bundle.extractfile(prefix + 'source-manifest.json'))
                self.assertEqual(provenance['scope'], scope)
                self.assertEqual(set(provenance['files']), set(expected))
                self.assertEqual(len(set(provenance['files'].values())), 1)
        self.assertEqual(result['targets'], 2)
        self.assertEqual(adapter.SCOPED_TARGETS[scope], expected)

    def test_review_scope_only_releases_identical_monitor_and_week_source_pairs(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'monitor.tar.gz'
            with patch.object(build_stage.subprocess,'check_output',side_effect=['a'*40,'']), \
                 patch.object(build_stage,'git_blob',side_effect=lambda _,path,commit:path.read_bytes()):
                result=build_stage.build(ROOT,output,curve_review=True)
            with tarfile.open(output) as bundle:
                prefix='fc-pricing-v3-20261026/'
                provenance=json.load(bundle.extractfile(prefix+'source-manifest.json'))
                expected={prefix+'fc_pricing_v3/'+name for prefix in ('source/','source/hermes-copy/') for name in ('monitoring.py','weekly_ladder.py')}
                self.assertEqual(set(provenance['files']),expected)
                self.assertEqual(provenance['scope'],target_map.CURVE_REVIEW_SCOPE)
                self.assertEqual(len(adapter.SCOPED_TARGETS[target_map.CURVE_REVIEW_SCOPE]),4)
                self.assertEqual(bundle.extractfile(prefix+'candidate/source/fc_pricing_v3/monitoring.py').read(),
                                 bundle.extractfile(prefix+'candidate/source/hermes-copy/fc_pricing_v3/monitoring.py').read())
        self.assertEqual(result['targets'],4)

    def test_weekly_scope_pairs_modules_and_keeps_exactly_two_new_targets(self):
        mapping = target_map.curve_weekly_targets(SOURCE)
        self.assertEqual(len(mapping),12)
        self.assertEqual(adapter.SCOPED_NEW[target_map.CURVE_WEEKLY_SCOPE],target_map.CURVE_WEEKLY_NEW)
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'weekly.tar.gz'
            with patch.object(build_stage.subprocess,'check_output',side_effect=['a'*40,'']), \
                 patch.object(build_stage,'git_blob',side_effect=lambda _,path,commit:path.read_bytes()):
                result=build_stage.build(ROOT,output,curve_weekly=True)
            with tarfile.open(output) as bundle:
                prefix='fc-pricing-v3-20261026/'
                provenance=json.load(bundle.extractfile(prefix+'source-manifest.json'))
                self.assertEqual(provenance['scope'],target_map.CURVE_WEEKLY_SCOPE)
                self.assertEqual(set(provenance['files']),set(adapter.SCOPED_TARGETS[target_map.CURVE_WEEKLY_SCOPE]))
                for name in ('api.py','ledger.py','runtime.py','scheduler.py','weekly_ladder.py'):
                    self.assertEqual(bundle.extractfile(prefix+'candidate/source/fc_pricing_v3/'+name).read(),
                                     bundle.extractfile(prefix+'candidate/source/hermes-copy/fc_pricing_v3/'+name).read())
        self.assertEqual(result['targets'],12)
        self.assertNotIn('coin_all_sync_job.py',mapping)
        with self.assertRaisesRegex(ValueError,'curve_v6_scope_required'):
            target_map.require_curve_scope_for_imports('fc_pricing_v3/api.py',b'from .weekly_ladder import state')

    def test_market_scope_builds_identical_strategy_and_revision_modules_for_both_roles(self):
        mapping = target_map.curve_market_targets(SOURCE)
        self.assertEqual(len(mapping), 10)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'market.tar.gz'
            with patch.object(build_stage.subprocess, 'check_output', side_effect=['a' * 40, '']), \
                 patch.object(build_stage, 'git_blob', side_effect=lambda _, path, commit: path.read_bytes()):
                result = build_stage.build(ROOT, output, curve_market=True)
            with tarfile.open(output) as bundle:
                prefix = 'fc-pricing-v3-20261026/'
                provenance = json.load(bundle.extractfile(prefix + 'source-manifest.json'))
                self.assertEqual(provenance['scope'], target_map.CURVE_MARKET_SCOPE)
                self.assertEqual(set(provenance['files']), set(adapter.SCOPED_TARGETS[target_map.CURVE_MARKET_SCOPE]))
                for name in ('api.py', 'curve_strategy_v6.py', 'ledger.py', 'platforms.py', 'runtime.py'):
                    original = bundle.extractfile(prefix + 'candidate/source/fc_pricing_v3/' + name).read()
                    copy = bundle.extractfile(prefix + 'candidate/source/hermes-copy/fc_pricing_v3/' + name).read()
                    self.assertEqual(original, copy)
        self.assertEqual(result['targets'], 10)
        self.assertNotIn('coin_all_sync_job.py', mapping)
        self.assertNotIn('fc_pricing_v3/scheduler.py', mapping)

    def test_margin_band_stage_updates_the_exact_existing_targets_with_paired_hashes(self):
        modules = ('api.py', 'average_discount_v6.py', 'curve_strategy_v6.py', 'ledger.py',
                   'runtime.py', 'weekly_ladder.py')
        expected = {'source/fc-pricing-v3.js': '/var/www/dashboard/fc-pricing-v3.js'}
        for name in modules:
            expected['source/fc_pricing_v3/' + name] = '/opt/fc27-cloud-browser/fc_pricing_v3/' + name
            expected['source/hermes-copy/fc_pricing_v3/' + name] = '/opt/fs-hermes-fc/fc_pricing_v3/' + name
        scope = target_map.CURVE_MARGIN_BAND_SCOPE
        self.assertEqual(adapter.SCOPED_TARGETS[scope], expected)
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder) / 'stage'
            deploy = stage / 'deploy'
            deploy.mkdir(parents=True)
            output = Path(folder) / 'margin-band.tar.gz'
            with patch.object(build_stage.subprocess, 'check_output', side_effect=['a' * 40, '']), \
                 patch.object(build_stage, 'git_blob', side_effect=lambda _, path, commit: path.read_bytes()):
                result = build_stage.build(ROOT, output, curve_margin_band=True)
            self.assertEqual(result['targets'], 13)

            prefix = 'fc-pricing-v3-20261026/'
            live_mapping = {}
            live_sha = hashlib.sha256(b'existing stage 4 bytes').hexdigest()
            with tarfile.open(output) as bundle:
                raw_provenance = bundle.extractfile(prefix + 'source-manifest.json').read()
                provenance = json.loads(raw_provenance)
                self.assertEqual(provenance['scope'], scope)
                self.assertEqual(set(provenance['files']), set(expected))
                (stage / 'source-manifest.json').write_bytes(raw_provenance)
                for index, name in enumerate(expected):
                    payload = bundle.extractfile(prefix + 'candidate/' + name).read()
                    candidate = stage / 'candidate' / name
                    candidate.parent.mkdir(parents=True, exist_ok=True)
                    candidate.write_bytes(payload)
                    live = stage / 'live' / str(index)
                    live.parent.mkdir(exist_ok=True)
                    live.write_bytes(b'existing stage 4 bytes')
                    live_mapping[name.removeprefix('source/')] = str(live)

            def inspect(manifest, candidate_stage):
                self.assertEqual(candidate_stage, stage)
                self.assertEqual({row['beforeSha256'] for row in manifest['files']}, {live_sha})
                rows = [dict(row, target=expected[row['candidate']]) for row in manifest['files']]
                value = dict(manifest, files=rows)
                self.assertIs(adapter.checked_manifest(value), value)
                runtime_mirror = next(row for row in rows if row['candidate'].endswith('hermes-copy/fc_pricing_v3/runtime.py'))
                runtime_mirror['sha256'] = 'c' * 64
                with self.assertRaisesRegex(ValueError, 'module_copy_sha_mismatch'):
                    adapter.checked_manifest(value)
                runtime_mirror['sha256'] = provenance['files'][runtime_mirror['candidate']]
                runtime_mirror['beforeSha256'] = None
                with self.assertRaisesRegex(ValueError, 'new_existing_target_boundary_changed'):
                    adapter.checked_manifest(value)
                return {'verified': True}

            frozen = SimpleNamespace(HERMES_TARGETS={}, HERMES_CAPABILITY_TARGETS={},
                                     CAP_PROTECTED_SESSION=set(), HERMES_DIRECT_TARGETS={})
            regular, sha = prepare.regular, prepare.sha
            with patch.object(prepare, 'STAGE', stage), patch.object(prepare, 'HERE', deploy), \
                 patch.object(prepare, 'curve_margin_band_targets', return_value=live_mapping), \
                 patch.object(prepare, 'regular', side_effect=lambda path, **kw: regular(path, **kw) if stage in path.parents else None), \
                 patch.object(prepare, 'sha', side_effect=lambda path: sha(path) if stage in path.parents else 'e' * 64), \
                 patch.object(prepare, 'stat', SimpleNamespace(S_IMODE=lambda _: 0o644)), \
                 patch.object(prepare, 'load_base', return_value=frozen), \
                 patch.object(prepare.subprocess, 'check_output', return_value='ActiveState=active'), \
                 patch.object(adapter, 'load_base', return_value=SimpleNamespace(inspect=inspect)):
                result = prepare.prepare(curve_margin_band=True)
            self.assertEqual((result['files'], result['existing'], result['new']), (13, 13, 0))

    def test_stability_release_contains_only_cost_pipeline_and_two_paired_modules(self):
        mapping = target_map.curve_stability_targets(SOURCE)
        self.assertEqual(len(mapping), 8)
        self.assertEqual(mapping['collect_p2pah_cost.py'], '/opt/fc27-cloud-browser/collect_p2pah_cost.py')
        self.assertEqual(adapter.SCOPED_TARGETS[target_map.CURVE_STABILITY_SCOPE],
                         {'source/' + name: path for name, path in mapping.items()})
        self.assertNotIn('coin_all_sync_job.py', mapping)
        self.assertNotIn('fc_pricing_v3/scheduler.py', mapping)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'stability.tar.gz'
            with patch.object(build_stage.subprocess, 'check_output', side_effect=['a' * 40, '']), \
                 patch.object(build_stage, 'git_blob', side_effect=lambda _, path, commit:
                              path.read_bytes().replace(b'\r\n', b'\n')):
                result = build_stage.build(ROOT, output, curve_stability=True)
            with tarfile.open(output) as bundle:
                provenance = json.load(bundle.extractfile('fc-pricing-v3-20261026/source-manifest.json'))
                shell = bundle.extractfile('fc-pricing-v3-20261026/candidate/source/collect_p2pah_cost.sh').read()
        self.assertEqual(result['targets'], 8)
        self.assertEqual(provenance['repositorySources'], target_map.CURVE_STABILITY_REPOSITORY_SOURCES)
        self.assertEqual(set(provenance['files']), set(adapter.SCOPED_TARGETS[target_map.CURVE_STABILITY_SCOPE]))
        self.assertIn(b'--env PYTHONPATH=/opt:/opt/fs-order-session', shell)
        self.assertIn(b'-e FC_V6_COST_REFERENCES', shell)
        self.assertIn(b'timeout 180s docker run', shell)
        self.assertIn(b'src=/opt/fs-order-session,dst=/opt/fs-order-session,readonly', shell)
        self.assertIn(b'src=/run/fs-order-session,dst=/run/fs-order-session,readonly', shell)
        self.assertNotIn(b'FC27_CDP_ENDPOINT', shell)
        self.assertNotIn(b'isolated_backend.py', shell)
        self.assertNotIn(b'/etc/fc27-cloud/fc27.env', shell)

    def test_insurance_release_contains_only_nine_price_guard_targets(self):
        mapping = target_map.curve_insurance_targets(SOURCE)
        self.assertEqual(len(mapping), 9)
        self.assertEqual(mapping['coin_all_sync_job.py'], '/opt/fc27-cloud-browser/coin_all_sync_job.py')
        for name in ('average_discount_v6.py', 'cost_inputs_v6.py', 'pricing_proof_v6.py', 'runtime.py'):
            self.assertEqual(mapping['fc_pricing_v3/' + name], '/opt/fc27-cloud-browser/fc_pricing_v3/' + name)
            self.assertEqual(mapping['hermes-copy/fc_pricing_v3/' + name], '/opt/fs-hermes-fc/fc_pricing_v3/' + name)
        self.assertEqual(adapter.SCOPED_TARGETS[target_map.CURVE_INSURANCE_SCOPE],
                         {'source/' + name: path for name, path in mapping.items()})

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=ROOT)

    def test_historical_targets_match_original_source_inventory(self):
        original = self.git('ls-tree', '-r', '--name-only', BASE, '--',
                            RELEASE + '/source/fc_pricing_v3').decode().splitlines()
        original = {p.split('/source/', 1)[1] for p in original}
        base = set(target_map.targets(SOURCE))
        three = set(target_map.three_platform_targets(SOURCE))
        package = {name for name in three if name.startswith('fc_pricing_v3/')}
        self.assertEqual(package, original)
        self.assertEqual(len(base), 101)
        self.assertEqual(len(three), 107)
        self.assertEqual(len(adapter.THREE_PLATFORM_TARGETS), 56)
        self.assertEqual(len(adapter.CURVE_V6_TARGETS), 60)

    def test_candidate_sources_build_both_copies_with_baseline_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'candidate.tar.gz'
            result = self.build_candidate(archive)
            self.assertEqual(result['targets'], 60)
            browser = root / 'browser'
            hermes = root / 'hermes'
            baseline = self.git('ls-tree', '-r', '--name-only', BASE, '--',
                                RELEASE + '/source/fc_pricing_v3').decode().splitlines()
            for name in baseline:
                relative = name.split('/source/', 1)[1]
                if 'source/' + relative in adapter.CURVE_V6_TARGETS:
                    continue
                original = self.git('show', BASE + ':' + name)
                for destination in (browser, hermes):
                    path = destination / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(original)
            (hermes / 'pricing_operations.py').write_bytes(self.git(
                'show', BASE + ':' + RELEASE + '/source/pricing_operations.py'))
            with tarfile.open(archive) as bundle:
                prefix = 'fc-pricing-v3-20261026/'
                provenance = json.load(bundle.extractfile(prefix + 'source-manifest.json'))
                self.assertEqual(provenance['scope'], target_map.CURVE_V6_SCOPE)
                self.assertEqual(provenance['sourceBaseCommit'], BASE)
                self.assertEqual(provenance['repositorySources'], target_map.CURVE_V6_REPOSITORY_SOURCES)
                self.assertEqual(set(provenance['files']), set(adapter.CURVE_V6_TARGETS))
                for name, sha in provenance['files'].items():
                    payload = bundle.extractfile(prefix + 'candidate/' + name).read()
                    self.assertEqual(sha, hashlib.sha256(payload).hexdigest())
                    if name.startswith('source/hermes-copy/'):
                        primary = name.replace('source/hermes-copy/', 'source/', 1)
                        self.assertEqual(sha, provenance['files'][primary])
                        destination = hermes / name.removeprefix('source/hermes-copy/')
                    elif adapter.CURVE_V6_TARGETS[name].startswith('/opt/fs-hermes-fc/'):
                        destination = hermes / name.removeprefix('source/')
                    else:
                        destination = browser / name.removeprefix('source/')
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(payload)
                self.assertTrue(set(target_map.CURVE_V6_COLLECTION_TARGETS) <= set(provenance['files']))
                self.assertFalse(any(name.startswith('source/fc_collection/') for name in provenance['files']))
                self.assertFalse(any('monitor-' in name for name in provenance['files']))
            for destination in (browser, hermes):
                subprocess.run([sys.executable, '-I', '-B', '-c',
                    'import importlib, sys\nsys.path.insert(0, sys.argv[1])\n'
                    'for name in sys.argv[2:]:\n    importlib.import_module("fc_pricing_v3." + name)\n',
                    str(destination), *(name.removesuffix('.py') for name in
                        target_map.CURVE_V6_CHANGED_MODULES + target_map.CURVE_V6_MODULES)],
                    check=True, cwd=destination)
            self.check_simulation_pin(browser, hermes)

    def check_simulation_pin(self, browser, hermes):
        subprocess.run([sys.executable, '-I', '-B', '-c', '''
import hashlib, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from fc_pricing_v3.legacy_simulation import SOURCES
from pricing_simulation import SimulationBridge, V3_VERSION
remote = Path(sys.argv[2]) / 'fc_pricing_v3'
version = dict(version=V3_VERSION, legacy_sources={key: sha for key, (_, sha) in SOURCES.items()})
for name in ('engine', 'financial'):
    version[name + '_sha256'] = hashlib.sha256((remote / (name + '.py')).read_bytes()).hexdigest()
SimulationBridge(request=lambda *args: version).versions()
''', str(hermes), str(browser)], check=True, cwd=hermes)

    def build_candidate(self, output, extra=None):
        def command(args, **kwargs):
            if args[1] == 'rev-parse':
                return 'a' * 40
            if args[1] == 'status':
                return ''
            self.assertEqual(args[1:6], ['diff', '--name-only', '--no-renames', '-z', BASE])
            self.assertEqual(args[6], 'a' * 40)
            selected = {name.removeprefix('source/').removeprefix('hermes-copy/')
                        for name in adapter.CURVE_V6_TARGETS if name not in target_map.CURVE_V6_REPOSITORY_SOURCES}
            selected.update(target_map.CURVE_V6_SEPARATE_ROLE_SOURCES)
            if extra is not None:
                selected.add(extra)
            return ''.join(RELEASE + '/source/' + name + '\0' for name in sorted(selected))

        def payload(checkout, path, commit):
            self.assertEqual(commit, 'a' * 40)
            return path.read_bytes().replace(b'\r\n', b'\n')

        with patch.object(build_stage, 'git_blob', side_effect=payload), \
             patch.object(build_stage.subprocess, 'check_output', side_effect=command):
            return build_stage.build(ROOT, output, curve_v6=True)

    def test_reject_unlisted_source_before_archive_is_created(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'forbidden.tar.gz'
            with self.assertRaisesRegex(ValueError, r'extra=fc_pricing_v3/experimental\.py'):
                self.build_candidate(output, extra='fc_pricing_v3/experimental.py')
            self.assertFalse(output.exists())

    def test_old_stage_rejects_current_selected_dependencies_and_replays_old_source(self):
        check_output = subprocess.check_output
        read = build_stage.git_blob

        def git(args, **kwargs):
            return '' if args[1] == 'status' else check_output(args, **kwargs)

        with tempfile.TemporaryDirectory() as folder, patch.object(build_stage.subprocess, 'check_output', side_effect=git):
            failed = Path(folder) / 'broken.tar.gz'
            for kwargs in ({}, {'lootbar': True}):
                with self.subTest(**kwargs), self.assertRaisesRegex(ValueError, 'curve_v6_scope_required:'):
                    build_stage.build(ROOT, failed, **kwargs)
                self.assertFalse(failed.exists())
            def runtime_with_missing_symbol(checkout, path):
                if path.name == 'runtime.py':
                    return (b'from .dispatch import CURVE_WRITE_PROTOCOL, proven_not_sent, write_protocol\n'
                            b'from .ledger import Ledger, confirmed_curve_window\n')
                return read(checkout, path, BASE)
            with patch.object(build_stage, 'git_blob', side_effect=runtime_with_missing_symbol):
                with self.assertRaisesRegex(ValueError, 'curve_v6_scope_required:.*runtime.py:CURVE_WRITE_PROTOCOL'):
                    build_stage.build(ROOT, failed, coupon_display=True)
                self.assertFalse(failed.exists())
            with patch.object(build_stage, 'git_blob', side_effect=lambda checkout, path: read(checkout, path, BASE)):
                result = build_stage.build(ROOT, Path(folder) / 'historical.tar.gz')
                self.assertEqual(result['targets'], 101)
                result = build_stage.build(ROOT, Path(folder) / 'historical-coupon.tar.gz', coupon_display=True)
                self.assertEqual(result['targets'], 102)

    def test_manifest_rejects_wrong_new_file_mismatched_copy_and_extra_target(self):
        def fixture():
            return dict(scope=target_map.CURVE_V6_SCOPE, businessWrites=False, timersChanged=False,
                        releaseReady=True, files=[
                            dict(candidate=name, target=path, sha256='b' * 64,
                                 beforeSha256=None if name in target_map.CURVE_V6_NEW else 'a' * 64,
                                 owner='0:0', mode='0o755' if name in target_map.CURVE_V6_EXECUTABLES else '0o644')
                            for name, path in adapter.CURVE_V6_TARGETS.items()
                        ])

        value = fixture()
        self.assertIs(adapter.checked_manifest(value), value)
        self.assertEqual(len(target_map.CURVE_V6_NEW), 18)
        for missing in ('source/collect_competitor.sh', 'source/hermes-copy/fc_pricing_v3/native_checkout_evidence.py'):
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'exact_fc_v3_targets_required'):
                value = fixture()
                value['files'] = [r for r in value['files'] if r['candidate'] != missing]
                adapter.checked_manifest(value)
        value = fixture()
        value['files'].append(dict(value['files'][0], candidate='source/fc_pricing_v3/extra.py'))
        with self.assertRaisesRegex(ValueError, 'exact_fc_v3_targets_required'):
            adapter.checked_manifest(value)
        value = fixture()
        new = next(row for row in value['files'] if row['beforeSha256'] is None)
        old = next(row for row in value['files'] if row['beforeSha256'] is not None)
        new['beforeSha256'], old['beforeSha256'] = old['beforeSha256'], None
        with self.assertRaisesRegex(ValueError, 'new_target_identity_changed'):
            adapter.checked_manifest(value)
        value = fixture()
        mirror = next(row for row in value['files'] if row['candidate'].startswith('source/hermes-copy/'))
        mirror['sha256'] = 'c' * 64
        with self.assertRaisesRegex(ValueError, 'module_copy_sha_mismatch'):
            adapter.checked_manifest(value)

    def test_average_stage_has_exact_changed_targets_and_two_new_matching_copies(self):
        scope = target_map.CURVE_AVERAGE_SCOPE
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'average.tar.gz'
            commands = patch.object(build_stage.subprocess, 'check_output', side_effect=['a' * 40, ''])
            blobs = patch.object(build_stage, 'git_blob', side_effect=lambda _, path, commit: path.read_bytes())
            with commands, blobs as read:
                result = build_stage.build(ROOT, output, curve_average=True)
            self.assertEqual(result['targets'], 24)
            self.assertTrue(all(call.args[2]=='a' * 40 for call in read.call_args_list))
            with tarfile.open(output) as bundle:
                provenance = json.load(bundle.extractfile('fc-pricing-v3-20261026/source-manifest.json'))
        self.assertEqual(provenance['scope'], scope)
        self.assertEqual(set(provenance['files']), set(adapter.SCOPED_TARGETS[scope]))
        manifest = dict(scope=scope, releaseReady=True, businessWrites=False, timersChanged=False, files=[
            dict(candidate=name,target=path,sha256=provenance['files'][name],owner='0:0',mode='0o644',
                 beforeSha256=None if name in target_map.CURVE_AVERAGE_NEW else 'b' * 64)
            for name,path in adapter.SCOPED_TARGETS[scope].items()])
        self.assertIs(adapter.checked_manifest(manifest),manifest)
        new = next(row for row in manifest['files'] if row['candidate'] in target_map.CURVE_AVERAGE_NEW)
        new['sha256'] = 'c' * 64
        with self.assertRaisesRegex(ValueError,'module_copy_sha_mismatch'):
            adapter.checked_manifest(manifest)

    def test_prepare_requires_exact_archive_and_uses_original_inspection(self):
        with tempfile.TemporaryDirectory() as folder:
            stage = Path(folder)
            deploy = stage / 'deploy'
            deploy.mkdir()
            mapping = {}
            for index, name in enumerate(adapter.CURVE_V6_TARGETS):
                candidate = stage / 'candidate' / name
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_bytes(b'# staged bytes\n')
                live = stage / 'live' / str(index)
                live.parent.mkdir(exist_ok=True)
                if name not in target_map.CURVE_V6_NEW:
                    live.write_bytes(b'# live bytes\n')
                    if name in target_map.CURVE_V6_EXECUTABLES:
                        live.chmod(0o755)
                mapping[name.removeprefix('source/')] = str(live)
            sha = hashlib.sha256(b'# staged bytes\n').hexdigest()
            (stage / 'source-manifest.json').write_text(json.dumps(dict(
                scope=target_map.CURVE_V6_SCOPE, sourceBaseCommit=BASE, sourceCommit='a' * 40,
                repositorySources=target_map.CURVE_V6_REPOSITORY_SOURCES,
                files={name: sha for name in adapter.CURVE_V6_TARGETS}
            )), encoding='utf-8')
            frozen = SimpleNamespace(HERMES_TARGETS={}, HERMES_CAPABILITY_TARGETS={},
                                     CAP_PROTECTED_SESSION=set(), HERMES_DIRECT_TARGETS={})
            inspect = Mock(return_value={'verified': True})
            original_sha = prepare.sha
            real_regular = prepare.regular

            def regular(path, existing=True):
                if stage in path.parents:
                    real_regular(path, existing=existing)

            with patch.object(prepare, 'STAGE', stage), patch.object(prepare, 'HERE', deploy), \
                 patch.object(prepare, 'curve_v6_targets', return_value=mapping), \
                 patch.object(prepare, 'regular', side_effect=regular), \
                 patch.object(prepare, 'sha', side_effect=lambda p: original_sha(p) if p.is_file() else 'e' * 64), \
                 patch.object(prepare, 'load_base', return_value=frozen), \
                 patch.object(prepare.subprocess, 'check_output', return_value='ActiveState=active'), \
                 patch.object(adapter, 'load_base', return_value=SimpleNamespace(inspect=inspect)):
                extra = stage / 'candidate/source/experimental.py'
                extra.touch()
                with self.assertRaisesRegex(ValueError, 'staged_payload_differs'):
                    prepare.prepare(curve_v6=True)
                self.assertFalse((deploy / 'approved-manifest.json').exists())
                extra.unlink()
                result = prepare.prepare(curve_v6=True)
                raw = (stage / 'approved-manifest.json').read_bytes()
                self.assertEqual(raw, (deploy / 'approved-manifest.json').read_bytes())
                manifest = json.loads(raw)
                inspect.assert_called_once_with(manifest, stage)
                self.assertEqual(result['files'], 60)
                self.assertEqual(result['existing'], 42)
                self.assertEqual(result['new'], 18)
                self.assertIn('fc-pricing-v3.service', manifest['runtimeRequired'])
                protected = {row['path'] for row in manifest['unchangedRequired']}
                self.assertTrue(set(target_map.COUPON_DISPLAY_PROTECTED).issubset(protected))
                self.assertTrue(set(target_map.CURVE_V6_PROTECTED).issubset(protected))
                self.assertIn('/opt/fc-ops-readonly-monitor/hooks.py', protected)


if __name__ == '__main__':
    unittest.main()
