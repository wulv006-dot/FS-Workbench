import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1]
OPS=[ROOT.parent/'hermes-ops-20261020/source',ROOT.parent/'fs_hermes_ops_20261020/source']
sys.path.insert(0,str(next(p for p in OPS if p.is_dir())))
sys.path.insert(0,str(ROOT/'source'))
import controller
from test_contract import fixture,request

def local_atomic(path,raw,profile=False):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)

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
    def test_transient_reads_stay_retryable_and_policy_failures_block(self):
        for status in ('pr_open','merged'):
            record=self.record(status)
            with patch.object(controller,'save'):controller.remember_error(record,TimeoutError())
            self.assertEqual(record['status'],status);self.assertEqual(record['recovery'],'retry_read')
        record=self.record('pr_open')
        with patch.object(controller,'save'):controller.remember_error(record,ValueError('ci failed'))
        self.assertEqual(record['status'],'blocked')
    def test_ambiguous_merge_keeps_original_reconciliation_state(self):
        record=self.record('merging')
        with patch.object(controller,'save'):controller.remember_error(record,controller.URLError('temporary'))
        self.assertEqual(record['status'],'merging');self.assertEqual(record['recovery'],'reconcile_original')
    def test_acceptance_intent_precedes_candidate_files_and_resumes(self):
        raw=json.dumps(request()).encode();before=fixture();page=Mock();page.read_bytes.return_value=before
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)
            def write(path,value,profile=False):local_atomic(path,json.dumps(value).encode())
            with patch.object(controller,'STATE',state),patch.object(controller.publication,'active',return_value=page),patch.object(controller,'write',side_effect=write),patch.object(controller,'atomic',side_effect=local_atomic):
                with patch.object(controller,'save',side_effect=OSError('crash before candidate files')):
                    with self.assertRaises(OSError):controller.accept(raw,{})
                self.assertTrue((state/'acceptance-intent.json').is_file())
                self.assertFalse((state/'runs'/json.loads(raw)['run_id']/'candidate').exists())
                with patch.object(controller,'save'):
                    record=controller.accept(raw,{})
                self.assertEqual(record['status'],'accepted')
                self.assertEqual((state/'runs'/record['run_id']/'candidate/request.json').read_bytes(),raw)
    def test_partial_candidate_files_are_verified_and_completed(self):
        raw=json.dumps(request()).encode();before=fixture();page=Mock();page.read_bytes.return_value=before
        after,proof=controller.build(before,json.loads(raw));record=self.record('accepting');record['proof']=proof
        with tempfile.TemporaryDirectory() as temp,patch.object(controller,'save'):
            state=Path(temp);folder=state/'runs'/record['run_id']/'candidate';folder.mkdir(parents=True);(folder/'before.html').write_bytes(before)
            with patch.object(controller,'STATE',state),patch.object(controller.publication,'active',return_value=page),patch.object(controller,'atomic',side_effect=local_atomic):controller.complete_accept(record,raw)
            self.assertEqual((folder/'index.html').read_bytes(),after);self.assertEqual(record['status'],'accepted')
    def test_terminal_metadata_is_written_before_terminal_status_and_resumes(self):
        record=self.record('publishing');record.update(proof={'after_sha256':'after'},merge_commit='merge')
        result=dict(status='published_file_and_route_readback_verified',release='release',backup='/original/backup')
        saved=[];profile={'raw':b'{"run_id":"previous"}'}
        with tempfile.TemporaryDirectory() as temp,patch.object(controller,'STATE',Path(temp)),patch.object(controller,'atomic',side_effect=local_atomic),patch.object(controller,'profile_read',side_effect=lambda *a:profile['raw']),patch.object(controller,'save',side_effect=lambda r:saved.append(copy.deepcopy(r))):
            with patch.object(controller,'write',side_effect=OSError('crash before metadata')):
                with self.assertRaises(OSError):controller.finish(record,result)
            self.assertEqual(record['status'],'finishing');self.assertFalse(any(r['status'] in controller.TERMINAL for r in saved))
            backup=Path(temp)/'runs'/record['run_id']/'previous-published.json';self.assertEqual(backup.read_bytes(),b'{"run_id":"previous"}')
            def write(path,value,profile=False):profile_data=json.dumps(value).encode();profile_dict['raw']=profile_data
            profile_dict=profile
            with patch.object(controller,'write',side_effect=write):controller.step(record)
            self.assertEqual(record['status'],result['status']);self.assertEqual(json.loads(profile['raw'])['run_id'],record['run_id'])
            self.assertEqual(backup.read_bytes(),b'{"run_id":"previous"}')

if __name__=='__main__':unittest.main()
