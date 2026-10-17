"""Offline regressions: no upstream login, writes, credentials or subprocesses."""
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import mlb_writeback as wb
import mlb_server as server


class ApprovalGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('writer.py', 'synthetic.json'):
            (self.root / name).write_text('{}')
        self.config = {'writeback': {'enabled': True, 'dry_run': True,
                       'script': str(self.root / 'writer.py'),
                       'cred': str(self.root / 'synthetic.json')}}
        self.cards = [{'product_name': 'SYNTHETIC', 'include': True}]
        self.state = wb.freeze(tid='test', cards=self.cards, wb=wb.cfg(self.config),
                               workdir=str(self.root), log=lambda _: None)

    def approve(self):
        def update(tid, value):
            self.state = value
        return wb.approve(tid='test', names=None, config=self.config,
                          read=lambda _: self.state, update=update,
                          workdir=str(self.root), log=lambda _: None)

    def test_unchanged_mode_starts_once(self):
        with patch.object(wb, '_start_worker') as start:
            self.assertEqual(self.approve()['status'], 'running')
            self.assertEqual(self.approve()['status'], 'noop')
            start.assert_called_once()
            self.assertTrue(start.call_args.kwargs['wb']['dry_run'])

    def test_disabled_service_blocks_pending(self):
        self.config['writeback']['enabled'] = False
        with patch.object(wb, '_start_worker') as start:
            self.assertEqual(self.approve()['status'], 'noop')
            self.assertEqual(self.state['status'], wb.AWAITING)
            start.assert_not_called()

    def test_dry_to_live_and_confirm_change_blocked(self):
        for changes in ({'dry_run': False}, {'confirm': 'changed'}):
            with self.subTest(changes=changes), patch.object(wb, '_start_worker') as start:
                original = dict(self.config['writeback'])
                self.config['writeback'].update(changes)
                self.assertEqual(self.approve()['status'], 'noop')
                start.assert_not_called()
                self.config['writeback'] = original

    def test_live_to_dry_also_requires_new_review(self):
        self.config['writeback']['dry_run'] = False
        self.state = wb.freeze(tid='test', cards=self.cards, wb=wb.cfg(self.config),
                               workdir=str(self.root), log=lambda _: None)
        self.config['writeback']['dry_run'] = True
        with patch.object(wb, '_start_worker') as start:
            self.assertEqual(self.approve()['status'], 'noop')
            start.assert_not_called()

    def test_missing_environment_blocks(self):
        (self.root / 'synthetic.json').unlink()
        with patch.object(wb, '_start_worker') as start:
            self.assertEqual(self.approve()['status'], 'noop')
            start.assert_not_called()

    def test_bad_snapshot_and_changed_cards_block(self):
        path = Path(wb.pending_path(str(self.root), 'test'))
        original = json.loads(path.read_text())
        for key, value in [('dry_run', None), ('cards', [{'product_name': 'OTHER'}]),
                           ('sha256', 'wrong')]:
            with self.subTest(key=key), patch.object(wb, '_start_worker') as start:
                path.write_text(json.dumps(dict(original, **{key: value})))
                self.assertEqual(self.approve()['status'], 'noop')
                start.assert_not_called()


class ReportGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = wb.cfg({'writeback': {'script': 'synthetic.py'}})
        self.cards = [{'product_name': 'SYNTHETIC'}]

    def run_once(self):
        return wb.run_once(tid='same', cards=self.cards, wb=self.cfg,
                           workdir=str(self.root), log=lambda _: None)

    def test_stale_success_never_reused_on_spawn_failure(self):
        stale = self.root / 'same.writeback.json'
        stale.write_text('[{"verdict":"ok"}]')
        with patch.object(wb.subprocess, 'run', side_effect=OSError('synthetic failure')):
            result = self.run_once()
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['report'])
        self.assertTrue(stale.exists())

    def test_each_invocation_has_distinct_output(self):
        seen = []
        def fake(cmd, **kwargs):
            out = cmd[cmd.index('--out') + 1]
            seen.append(out)
            Path(out).write_text('[{"verdict":"dry-run"}]')
            return types.SimpleNamespace(stdout=b'', returncode=0)
        with patch.object(wb.subprocess, 'run', side_effect=fake):
            self.assertEqual(self.run_once()['status'], 'dry_run')
            self.assertEqual(self.run_once()['status'], 'dry_run')
        self.assertEqual(len(set(seen)), 2)

    def test_nonzero_or_malformed_report_not_success(self):
        for rc, report in [(1, [{'verdict': 'ok'}]), (0, {}), (0, []), (0, ['bad'])]:
            with self.subTest(rc=rc, report=report):
                def fake(cmd, **kwargs):
                    Path(cmd[cmd.index('--out') + 1]).write_text(json.dumps(report))
                    return types.SimpleNamespace(stdout=b'', returncode=rc)
                with patch.object(wb.subprocess, 'run', side_effect=fake):
                    self.assertEqual(self.run_once()['status'], 'needs_review')

    def test_timeout_not_success_even_with_report(self):
        def fake(cmd, **kwargs):
            Path(cmd[cmd.index('--out') + 1]).write_text('[{"verdict":"ok"}]')
            raise wb.subprocess.TimeoutExpired(cmd, 1)
        with patch.object(wb.subprocess, 'run', side_effect=fake):
            self.assertEqual(self.run_once()['status'], 'timeout')


class StaticGuards(unittest.TestCase):
    def test_actual_handler_containment_and_valid_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'mlb-online'
            sibling = Path(tmp) / 'mlb-online-old'
            root.mkdir(); sibling.mkdir(); (root / 'assets').mkdir()
            (root / 'assets' / 'ok.css').write_text('safe')
            (sibling / 'private.css').write_text('private synthetic')
            (root / 'assets' / 'link.css').symlink_to(sibling / 'private.css')
            obj = types.SimpleNamespace(_send=lambda code, body, headers=None: (code, body))
            with patch.object(server, 'ARGS', types.SimpleNamespace(root=str(root))):
                self.assertEqual(server.Handler._static(obj, 'assets/ok.css'), (200, b'safe'))
                for rel in ('../mlb-online-old/private.css', 'assets/../../mlb-online-old/private.css',
                            'assets/link.css', 'assets/%2e%2e/%2e%2e/mlb-online-old/private.css'):
                    with self.subTest(rel=rel):
                        self.assertEqual(server.Handler._static(obj, rel)[0], 403)
                self.assertEqual(server.Handler._static(obj, 'assets/missing.css')[0], 404)


if __name__ == '__main__':
    unittest.main()
