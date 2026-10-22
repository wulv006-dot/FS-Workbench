import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1]
OPS=[ROOT.parent/'hermes-ops-20261020/source',ROOT.parent/'fs_hermes_ops_20261020/source']
sys.path.insert(0,str(next(p for p in OPS if p.is_dir())))
sys.path.insert(0,str(ROOT/'source'))
import controller
from test_contract import fixture,request

class Controller(unittest.TestCase):
    def record(self,status='accepted'):
        return dict(run_id='20261022T060000Z-1234abcd',status=status,branch='codex/game-monitor-content-test',request_summary='A content update',pr=dict(number=123,head='head',base='base',branch='codex/game-monitor-content-test'))
    def test_unknown_create_without_branch_is_not_replayed(self):
        record=self.record('creating_pr');github=Mock();github.request.side_effect=controller.HTTPError('x',404,'missing',{},None)
        with patch.object(controller,'save'),self.assertRaisesRegex(ValueError,'unknown_pr_creation'):controller.open_pr(github,record)
        github.create_pr.assert_not_called()
    def test_pending_ci_never_merges(self):
        record=self.record('pr_open');github=Mock();github.ready.return_value=False
        github.request.side_effect=[dict(head=dict(ref=record['branch'],sha='head',repo=dict(full_name='wulv006-dot/FS-Workbench')),base=dict(ref='main'),merged=False),dict(object=dict(sha='base'))]
        with patch.object(controller,'GitHub',return_value=github),patch.object(controller,'save'):controller.step(record)
        self.assertEqual(record['status'],'pr_open');self.assertFalse(any(c.args[0]=='PUT' for c in github.request.call_args_list))
    def test_unknown_merge_is_reconciled_before_any_write(self):
        record=self.record('merging');github=Mock()
        github.request.return_value=dict(head=dict(ref=record['branch'],sha='head',repo=dict(full_name='wulv006-dot/FS-Workbench')),base=dict(ref='main'),merged=True,merge_commit_sha='merged')
        with patch.object(controller,'GitHub',return_value=github),patch.object(controller,'save'):controller.step(record)
        self.assertEqual(record['merge_commit'],'merged');self.assertEqual(record['status'],'merged')
        self.assertEqual(github.request.call_args.args[0],'GET')
    def test_changed_pr_head_is_refused(self):
        record=self.record()
        pr=dict(head=dict(ref=record['branch'],sha='peer',repo=dict(full_name='wulv006-dot/FS-Workbench')),base=dict(ref='main'))
        with self.assertRaisesRegex(ValueError,'head_drift'):controller.check_pr(pr,record)
    def test_unknown_publish_only_reads_original_stage(self):
        record=self.record('publishing_unknown');record['publication']={'stage':'/original/stage'}
        with patch.object(controller.publication,'verify',side_effect=ValueError('incomplete')) as verify,patch.object(controller.subprocess,'run') as run:controller.step(record)
        verify.assert_called_once_with(Path('/original/stage'));run.assert_not_called()
    def test_existing_request_hash_cannot_change(self):
        record=self.record();record['request_sha256']='0'*64
        raw=json.dumps(request()).encode()
        with self.assertRaisesRegex(ValueError,'request_changed'):controller.accept(raw,record)
    def test_rebase_refuses_other_maintenance_changes(self):
        record=self.record('pr_open');github=Mock()
        github.request.side_effect=[dict(head=dict(ref=record['branch'],sha='head',repo=dict(full_name='wulv006-dot/FS-Workbench')),base=dict(ref='main')),dict(files=[dict(filename=controller.PREFIX+'source/contract.py')])]
        with self.assertRaisesRegex(ValueError,'base_conflict'):controller.refresh_base(github,record,'new-base')
        self.assertTrue(all(c.args[0]=='GET' for c in github.request.call_args_list))
    def test_original_bridge_logic_is_preserved_before_fixed_hook(self):
        source=ROOT/'source/host.py'
        if not source.is_file():source=next(p for p in OPS if p.is_dir())/'host.py'
        text=source.read_text(encoding='utf8')
        self.assertEqual(text.count("str(HERE/'game_monitor/controller.py')"),1)
        self.assertLess(text.index("write(PROFILE/'snapshot.json', collect(now))"),text.index("str(HERE/'game_monitor/controller.py')"))

if __name__=='__main__':unittest.main()
