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
        self.assertEqual(len(adapter.CURVE_V6_TARGETS), 45)

    def test_candidate_sources_build_both_copies_with_baseline_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'candidate.tar.gz'
            result = self.build_candidate(archive)
            self.assertEqual(result['targets'], 45)
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
                self.assertFalse(any('collect_competitor' in name for name in bundle.getnames()))
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
                        for name in adapter.CURVE_V6_TARGETS}
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
                                 owner='0:0', mode='0o644')
                            for name, path in adapter.CURVE_V6_TARGETS.items()
                        ])

        value = fixture()
        self.assertIs(adapter.checked_manifest(value), value)
        self.assertEqual(len(target_map.CURVE_V6_NEW), 14)
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
                mapping[name.removeprefix('source/')] = str(live)
            sha = hashlib.sha256(b'# staged bytes\n').hexdigest()
            (stage / 'source-manifest.json').write_text(json.dumps(dict(
                scope=target_map.CURVE_V6_SCOPE, sourceBaseCommit=BASE, sourceCommit='a' * 40,
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
                self.assertEqual(result['files'], 45)
                self.assertEqual(result['existing'], 31)
                self.assertEqual(result['new'], 14)
                self.assertIn('fc-pricing-v3.service', manifest['runtimeRequired'])
                protected = {row['path'] for row in manifest['unchangedRequired']}
                self.assertTrue(set(target_map.COUPON_DISPLAY_PROTECTED).issubset(protected))
                self.assertIn('/opt/fc-ops-readonly-monitor/hooks.py', protected)


if __name__ == '__main__':
    unittest.main()
