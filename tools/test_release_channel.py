import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import release_channel as channel

SHA = 'a' * 40


class ChannelTests(unittest.TestCase):
    def test_workflow_supports_exact_main_and_pr_without_weakening_isolation(self):
        text = (channel.ROOT / '.github/workflows/pr-fast.yml').read_text(encoding='utf8')
        self.assertIn('  push:\n    branches: [main]', text)
        self.assertIn('  pull_request:\n    branches: [main]', text)
        self.assertEqual(text.count('PR_BASE: ${{ github.event.pull_request.base.sha || github.event.before }}'), 7)
        self.assertEqual(text.count('PR_HEAD: ${{ github.event.pull_request.head.sha || github.sha }}'), 7)
        self.assertIn('sudo unshare --net', text)
        self.assertIn('contents: read', text)

    def test_paths_fail_closed(self):
        for path in ('/tmp/a', '../a', 'releases/../a', 'releases//a', 'releases/a;id', 'releases/./a'):
            with self.subTest(path=path), self.assertRaises(channel.Refused):
                channel.checked_path(path)
        self.assertEqual(channel.checked_path('releases/a/manifest.json'), 'releases/a/manifest.json')

    def test_checks_exact_complete_green(self):
        good = {'total_count': 1, 'check_runs': [{'name': 'pr-fast', 'app': {'slug': 'github-actions'}, 'id': 123, 'head_sha': SHA,
                 'status': 'completed', 'conclusion': 'success'}]}
        channel.validate_checks(good, SHA)
        for value in ({}, dict(good, total_count=2), {'total_count': 0, 'check_runs': []}):
            with self.assertRaises(channel.Refused):
                channel.validate_checks(value, SHA)
        for key, value in (('head_sha', 'b' * 40), ('status', 'queued'),
                           ('conclusion', 'failure'), ('name', 'other')):
            bad = json.loads(json.dumps(good))
            bad['check_runs'][0][key] = value
            with self.assertRaises(channel.Refused):
                channel.validate_checks(bad, SHA)

    def test_no_process_for_invalid_request(self):
        for module, sha, manifest in (('arbitrary-shell', SHA, 'releases/m.json'),
                                     ('business-html', 'main', 'releases/m.json'),
                                     ('business-html', SHA, '../manifest')):
            with patch.object(channel, 'command') as run, self.assertRaises(channel.Refused):
                channel.prepare(module, sha, manifest)
            run.assert_not_called()

    def test_origin_sha_and_dirty_refused_before_ci(self):
        for outputs in ([b'https://other/repo'],
                        [b'https://github.com/' + channel.REPOSITORY.encode(), b'', b'b' * 40],
                        [b'https://github.com/' + channel.REPOSITORY.encode(), b'', SHA.encode(), b'b' * 40],
                        [b'https://github.com/' + channel.REPOSITORY.encode(), b'', SHA.encode(), SHA.encode(), b' M changed']):
            with patch.object(channel, 'command', side_effect=outputs) as run:
                with self.assertRaises(channel.Refused):
                    channel.prepare('business-html', SHA, 'releases/m.json')
                self.assertFalse(any(call.args[0][0] == 'gh' for call in run.call_args_list))

    def test_prepare_checks_tracked_payload_and_modified_bytes(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = 'releases/fixture/manifest.json'
            payload = b'<html>fixture</html>'
            raw = json.dumps({'source': 'dashboard.html', 'releaseId': 'fixture',
                              'sha256': hashlib.sha256(payload).hexdigest()}).encode()
            files = {manifest: raw, 'releases/fixture/dashboard.html': payload,
                     channel.GATEWAY: b'# fixture gateway'}
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            checks = json.dumps({'total_count': 1, 'check_runs': [{'name': 'pr-fast', 'id': 123, 'app': {'slug': 'github-actions'},
                     'head_sha': SHA, 'status': 'completed', 'conclusion': 'success'}]}).encode()
            def run(args):
                if args[:2] == ['git', 'show']:
                    return files[args[2].split(':', 1)[1]]
                if args[0] == 'gh':
                    return checks
                if args[:3] == ['git', 'remote', 'get-url']:
                    return ('https://github.com/' + channel.REPOSITORY).encode()
                if args[:2] == ['git', 'rev-parse']:
                    return SHA.encode()
                return b''
            with patch.object(channel, 'ROOT', root), patch.object(channel, 'command', side_effect=run), patch.object(channel, 'verify_workflow'):
                path, spec = channel.prepare('business-html', SHA, manifest)
                self.assertEqual(path, root / manifest)
                self.assertEqual(spec['releaseId'], 'fixture')
                (root / 'releases/fixture/dashboard.html').write_bytes(b'changed')
                with self.assertRaisesRegex(channel.Refused, 'differs from main SHA'):
                    channel.prepare('business-html', SHA, manifest)

    def test_wrong_ci_issuer_rejected(self):
        checks = {'total_count': 1, 'check_runs': [{'id': 123, 'name': 'pr-fast', 'head_sha': SHA,
                  'status': 'completed', 'conclusion': 'success', 'app': {'slug': 'unrelated-app'}}]}
        with self.assertRaises(channel.Refused):
            channel.validate_checks(checks, SHA)

    def test_workflow_job_must_match_check(self):
        checks = {'check_runs': [{'id': 123, 'name': 'pr-fast', 'conclusion': 'success',
                                 'app': {'slug': 'github-actions'}}]}
        run = {'id': 1, 'run_number': 1, 'path': '.github/workflows/pr-fast.yml', 'head_sha': SHA,
               'event': 'push', 'head_branch': 'main', 'head_repository': {'full_name': channel.REPOSITORY},
               'status': 'completed', 'conclusion': 'success'}
        job = {'name': 'pr-fast', 'conclusion': 'success',
               'check_run_url': 'https://api.github.com/repos/' + channel.REPOSITORY + '/check-runs/123'}
        def verify(r, j):
            with patch.object(channel, 'command', side_effect=[json.dumps({'total_count': 1, 'workflow_runs': [r]}).encode(),
                       json.dumps({'total_count': 1, 'jobs': [j]}).encode()]):
                channel.verify_workflow(checks, SHA)
        verify(run, job)
        for field, bad in (('path', '.github/workflows/other.yml'), ('head_sha', 'b' * 40), ('event', 'pull_request')):
            with self.assertRaises(channel.Refused):
                verify(dict(run, **{field: bad}), job)
        with self.assertRaises(channel.Refused):
            verify(run, dict(job, check_run_url='unrelated'))

    def test_verified_source_ignores_cache_and_pending_blocks_under_lock(self):
        import importlib.util
        import py_compile
        source = (channel.ROOT / channel.GATEWAY).read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / channel.GATEWAY
            path.parent.mkdir(parents=True)
            path.write_bytes(source)
            malicious = root / 'malicious.py'
            malicious.write_text("raise RuntimeError('cached_code_executed')", encoding='utf8')
            cache = Path(importlib.util.cache_from_source(str(path)))
            cache.parent.mkdir(parents=True, exist_ok=True)
            py_compile.compile(str(malicious), cfile=str(cache))
            with patch.object(channel, 'ROOT', root):
                gateway = channel.load_gateway(source)
                pending = root / 'var/lib/fs-dashboard-release/pending.json'
                pending.parent.mkdir(parents=True)
                pending.write_text('{"original":"intent"}', encoding='utf8')
                with self.assertRaisesRegex(channel.Refused, 'unresolved publication intent'):
                    gateway.publish(root, root / 'missing-manifest.json')
                self.assertEqual(pending.read_text(), '{"original":"intent"}')
                # The refusal releases the original gateway lock rather than leaking it.
                pending.unlink()
                with gateway.Lock(root / 'var/lock/fs-dashboard-release.lock'):
                    pass

    def test_plan_never_loads_writer(self):
        with patch.object(channel, 'prepare', return_value=(Path('m'), {'releaseId': 'r'})), \
             patch.object(channel, 'load_gateway') as load:
            result = channel.execute('business-html', SHA, 'releases/m.json')
        load.assert_not_called()
        self.assertFalse(result['production_changed'])
        self.assertEqual(result['status'], 'planned')

    def test_apply_delegates_once_no_alternate_writer(self):
        with patch.object(channel, 'prepare', return_value=(Path('m'), {'releaseId': 'r'})), \
             patch.object(channel, 'tracked_bytes', return_value=b'# verified'), \
             patch.object(channel, 'load_gateway') as load:
            gateway = load.return_value
            gateway.publish.return_value = {'releaseId': 'r'}
            result = channel.execute('business-html', SHA, 'releases/m.json', True)
            gateway.publish.assert_called_once_with('/', Path('m'))
            self.assertEqual(result['business_acceptance'], 'pending')
            self.assertEqual(result['status'], 'published_readback_pending')
            gateway.publish.side_effect = RuntimeError('unknown_after_write')
            with self.assertRaisesRegex(RuntimeError, 'unknown_after_write'):
                channel.execute('business-html', SHA, 'releases/m.json', True)
            self.assertEqual(gateway.publish.call_count, 2)


if __name__ == '__main__':
    unittest.main()
