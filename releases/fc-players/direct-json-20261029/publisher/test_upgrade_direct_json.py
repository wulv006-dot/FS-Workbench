"""Offline contracts and publisher success/rollback simulation; no host commands."""
import io
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sqlite3
import sys
import tarfile
import tempfile
import types
import unittest
from contextlib import contextmanager, redirect_stdout
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if sys.platform == 'win32':
    sys.modules.setdefault('fcntl', types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=lambda *args: None))
spec = importlib.util.spec_from_file_location('direct_json_publisher', HERE/'upgrade_direct_json.py')
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


def fixture_manifest():
    result = json.loads((HERE/'manifest.fixture.json').read_text(encoding='utf-8'))
    result.pop('_fixture_only')
    result['files']['VERSION'] = 'a'*64
    result['files']['player_web/shared_session.py'] = P.sha(HERE.parent/'source/shared_session.py')
    result['files']['球员维护工具/admin_client.py'] = 'b'*64
    result['archive_sha256'] = 'c'*64
    result['dockerfile_sha256'] = 'd'*64
    return result


def fake_unit():
    mounts = ' '.join('--mount type=bind,src='+str(source)+',dst=/app/'+name+',readonly'
                      for name,(source,_) in P.PATCHES.items())
    return ('[Unit]\nAfter=network-online.target docker.service\n[Service]\n'
            'ExecStart=docker run --user 992:987 --memory 2g '+mounts+
            ' --mount type=bind,src=/var/lib/fc27-cloud/state/price-writer.lock,dst=/var/lib/fc27-cloud/state/price-writer.lock,readonly'
            ' --mount type=bind,src=/run/fs-player-session,dst=/run/fs-player-session,readonly '+P.BASE_IMAGE+'\n')


@contextmanager
def sql(path):
    connection=sqlite3.connect(path)
    try:
        with connection:yield connection
    finally:connection.close()


def database(path):
    with sql(path) as db:
        db.executescript('''
            CREATE TABLE executions(id TEXT,status TEXT,step TEXT);
            CREATE TABLE events(seq INTEGER,execution_id TEXT,detail TEXT);
            CREATE TABLE execution_items(execution_id TEXT,model_id INTEGER,status TEXT);
            CREATE TABLE active_scope(futbin_id TEXT,execution_id TEXT);
            CREATE TABLE legacy_unresolved(futbin_id TEXT,evidence TEXT);
            INSERT INTO executions VALUES('2b24','needs_reconcile','unknown');
            INSERT INTO events VALUES(1878,'2b24','AdminContractError');
            INSERT INTO active_scope VALUES('23691','2b24');
            INSERT INTO legacy_unresolved VALUES('historic','keep');
        ''')


class Contracts(unittest.TestCase):
    def test_current_49_file_fixture_and_manifest_acceptance(self):
        manifest = fixture_manifest()
        self.assertEqual(len(manifest['baseline']), 49)
        P.validate_manifest(manifest)

    def test_undeployable_placeholder_fixture_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Invalid SHA256'):
            P.validate_manifest(json.loads((HERE/'manifest.fixture.json').read_text(encoding='utf-8')))

    def test_stale_cloud_and_policy_rejected(self):
        for key in ('version','base_version','base_image_id','manual_flag','base_env_sha256','base_unit_sha256','base_on_demand_sha256','base_source_manifest_sha256'):
            with self.subTest(key=key):
                candidate = fixture_manifest(); candidate[key] = 'stale'
                with self.assertRaises(RuntimeError): P.validate_manifest(candidate)

    def test_no_hmac_patch_rejected_but_candidate_sha_can_change(self):
        candidate = fixture_manifest(); del candidate['files']['球员维护工具/admin_client.py']
        with self.assertRaises(RuntimeError): P.validate_manifest(candidate)
        candidate = fixture_manifest(); candidate['files']['player_web/shared_session.py']='0'*64
        P.validate_manifest(candidate)

    def test_actual_sharedgit_transport_is_primary_hmac_and_old_session_rejected(self):
        actual = (HERE.parent/'source/shared_session.py').read_text(encoding='utf-8')
        P.validate_transport(actual)
        for invalid in (actual.replace('127.0.0.1:8912','127.0.0.1:8911'),actual.replace("raise AdminAuthError('FS_SHARED_SESSION_RETIRED')","return 'old-token'"),actual+'\nimport socket\n',actual+'\nimport subprocess;subprocess.run(["systemctl","start","fc27-p2pah-session.service"])\n'):
            with self.assertRaises(RuntimeError):P.validate_transport(invalid)

    def test_unsafe_archive_target_rejected(self):
        for name in ('../other.py','/etc/passwd','folder\\escape.py'):
            candidate = fixture_manifest(); candidate['files'][name] = 'e'*64
            with self.assertRaises(RuntimeError): P.validate_manifest(candidate)

    def test_dockerfile_copies_both_trees_without_dependency_changes(self):
        dockerfile = (HERE/'Dockerfile').read_text(encoding='utf-8')
        P.validate_dockerfile(dockerfile)
        for invalid in (dockerfile.replace('COPY ["球员维护工具", "/app/球员维护工具"]\n',''), dockerfile+'RUN pip install something\n'):
            with self.assertRaises(RuntimeError): P.validate_dockerfile(invalid)

    def test_unit_changes_only_image_and_effective_bind_sources(self):
        patches = {name:(PurePosixPath('/opt/fc27-player-tool/patches/20261028')/source.name,value) for name,(source,value) in P.PATCHES.items()}
        with patch.object(P,'PATCHES',patches), patch.object(P,'RELEASE',PurePosixPath('/opt/fc27-player-tool/releases')/P.VERSION):
            original = fake_unit(); result = P.updated_unit(original)
            expected = original.replace(P.BASE_IMAGE,P.IMAGE)
            for name,(source,_) in patches.items(): expected=expected.replace('src='+str(source)+',','src='+str(P.RELEASE/name)+',')
            self.assertEqual(result,expected)
            self.assertIn('src=/run/fs-player-session,dst=/run/fs-player-session,readonly',result)
            self.assertNotIn('fc27-p2pah-session.service',result)
            self.assertIn('--memory 2g',result)
            for invalid in (original.replace(',readonly',',rw',1),original.replace('--memory 2g','--memory 4g'),original+P.BASE_IMAGE):
                with self.assertRaises(RuntimeError): P.updated_unit(invalid)

    def test_waiting_lock_active_but_unknown_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/'control.sqlite3'; tasks=Path(root)/'admin_tasks.json'
            database(db);tasks.write_text('[{"operation_id":"original","status":"uploading"}]')
            with patch.object(P,'DB',db),patch.object(P,'ADMIN_TASKS',tasks):
                before=P.db_state();self.assertEqual(before['active'],0)
                with sql(db) as connection: connection.execute("INSERT INTO executions VALUES('wait','waiting_price_lock','sync_pending')")
                self.assertEqual(P.db_state()['active'],1)

    def test_same_row_count_unknown_scope_event_edits_are_detected(self):
        for mutation in ("UPDATE executions SET step='done'", "UPDATE active_scope SET futbin_id='different'", "UPDATE events SET detail='erased'", "UPDATE legacy_unresolved SET evidence='lost'"):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as root:
                db=Path(root)/'control.sqlite3'; tasks=Path(root)/'admin_tasks.json'
                database(db);tasks.write_text('original-uploading')
                with patch.object(P,'DB',db),patch.object(P,'ADMIN_TASKS',tasks):
                    before=P.db_state()
                    with sql(db) as connection: connection.execute(mutation)
                    after=P.db_state()
                    self.assertEqual(before['executions'],after['executions'])
                    self.assertNotEqual(before,after)

    def test_admin_tasks_change_detected(self):
        with tempfile.TemporaryDirectory() as root:
            db=Path(root)/'control.sqlite3'; tasks=Path(root)/'admin_tasks.json'
            database(db);tasks.write_text('uploading')
            with patch.object(P,'DB',db),patch.object(P,'ADMIN_TASKS',tasks):
                before=P.db_state();tasks.write_text('erased');self.assertNotEqual(before,P.db_state())

    def test_atomic_config_preserves_mode_and_rejects_stale_pending(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'unit';path.write_text('old');mode=path.stat().st_mode
            P.atomic_text(path,'new');self.assertEqual(path.read_text(),'new');self.assertEqual(path.stat().st_mode,mode)
            pending=path.with_name(path.name+'.direct-json.pending');pending.write_text('someone-else')
            with self.assertRaises(RuntimeError):P.atomic_text(path,'overwrite')
            self.assertEqual(pending.read_text(),'someone-else')

    def test_actual_bind_contract_rejects_wrong_source_or_writable(self):
        for deployed in (False,True):
            mounts=[{'Destination':'/app/'+name,'Source':str(P.RELEASE/name if deployed else source),'RW':False} for name,(source,_) in P.PATCHES.items()]
            with patch.object(P,'run',return_value=types.SimpleNamespace(stdout=json.dumps(mounts))):
                P.verify_bind_sources(deployed=deployed)
            for field,value in (('Source','wrong-source'),('RW',True)):
                wrong=[dict(item) for item in mounts];wrong[0][field]=value
                with patch.object(P,'run',return_value=types.SimpleNamespace(stdout=json.dumps(wrong))):
                    with self.assertRaises(RuntimeError):P.verify_bind_sources(deployed=deployed)

    def test_retired_session_pid_or_active_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            lock=Path(root)/'lock';lock.write_text('preserve')
            for retired in ('ActiveState=active\nMainPID=99','ActiveState=active\nMainPID=0','ActiveState=failed\nMainPID=99'):
                def run(*args):return types.SimpleNamespace(stdout=retired if args[2]=='fc27-p2pah-session.service' else 'ActiveState=active\nMainPID=5004')
                with patch.object(P,'PRICE_LOCK',lock),patch.object(P,'run',side_effect=run):
                    with self.assertRaises(RuntimeError):P.protected_state()

    def simulate(self, fail_after_current=False):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);current=root/'releases'/P.BASE_VERSION;current.mkdir(parents=True)
            stage=root/'staging'/'direct-json-20261029';stage.mkdir(parents=True)
            unit=root/'unit';demand=root/'dropins'/'on-demand.conf';demand.parent.mkdir()
            env=root/'app.env';db=root/'control.sqlite3';tasks=root/'admin_tasks.json';lock=root/'price-writer.lock'
            database(db);tasks.write_text('original uploading UNKNOWN');lock.write_text('do not change')
            baseline={}
            for name in fixture_manifest()['baseline']:
                target=current/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('base '+name,encoding='utf-8');baseline[name]=P.sha(target)
            (current/'source_manifest.json').write_text(json.dumps({'version':P.BASE_VERSION,'files':baseline}))
            patches={}
            for name,(source,_) in P.PATCHES.items():
                source=root/'patches'/source.name;source.parent.mkdir(exist_ok=True);source.write_text('active HMAC '+name,encoding='utf-8');patches[name]=(source,P.sha(source))
            env.write_text('WRITE_ENABLED=false\nAUTO_WRITE_ENABLED=false\nMANUAL_NEW_CARDS_ENABLED=true\nMANUAL_MODEL_IMAGES_ENABLED=true\nMANUAL_EXISTING_RECOMMEND_ENABLED=true\nFS_SHARED_BACKEND_SESSION=true\nAPPROVED_PUBLIC_HTTP_SOURCE=http://139.28.18.234:8001\n')
            changes={name:source.read_bytes() for name,(source,_) in patches.items()};changes['VERSION']=(P.VERSION+'\n').encode()
            changes['player_web/shared_session.py']=P.HMAC_TRANSPORT.encode('utf-8')
            delta=root/'delta';delta.mkdir()
            with tarfile.open(stage/'delta.tar.gz','w:gz') as archive:
                for name,value in changes.items():
                    target=delta/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value);archive.add(target,arcname=name)
            (stage/'Dockerfile').write_bytes((HERE/'Dockerfile').read_bytes())
            globals_to_patch={'ROOT':root,'CURRENT':current,'RELEASE':root/'releases'/P.VERSION,'STAGE':stage,'ENV':env,'UNIT':unit,'ON_DEMAND':demand,'DB':db,'ADMIN_TASKS':tasks,'PRICE_LOCK':lock,'PATCHES':patches}
            calls=[];activity={'fc27-player-tool.service':True,'fc27-player-demand.socket':True,'fc27-player-collect.timer':False,'fc27-player-collect.service':False}
            current_target=[current];mutated=[False];real_replace=P.os.replace
            def fake_link(path,target,*args,**kwargs):path.write_text(str(target))
            def fake_replace(source,target):
                if Path(target)==current:
                    current_target[0]=Path(Path(source).read_text());Path(source).unlink()
                else:real_replace(source,target)
            def fake_run(*args):
                calls.append(args)
                if args[0]=='systemctl':
                    if args[1]=='show':
                        if args[-1]=='--property=ActiveState':out='ActiveState='+('active' if activity.get(args[2],False) else 'inactive')
                        else:
                            pid={'fc-pricing-v3.service':5004,'fc27-cloud-api.service':699,'fc27-p2pah-session.service':0}[args[2]]
                            out='ActiveState='+('active' if pid else 'failed')+'\nMainPID='+str(pid)+'\nUnitFileState=disabled'
                        return types.SimpleNamespace(stdout=out)
                    if args[1] in ('start','stop'):
                        self.assertIn(args[2],activity,'Unrelated service mutation')
                        activity[args[2]]=args[1]=='start'
                        if fail_after_current and args[1:]==('start','fc27-player-demand.socket') and current_target[0]==P.RELEASE and not mutated[0]:
                            with sql(db) as connection:connection.execute("INSERT INTO events VALUES(9999,'later','do not roll back DB')")
                            mutated[0]=True
                    return types.SimpleNamespace(stdout='')
                if args[0]=='docker':
                    if args[1:3]==('inspect','--format'):
                        if args[3]=='{{.Image}}':return types.SimpleNamespace(stdout=P.BASE_IMAGE_ID)
                        new_unit = unit.read_text(encoding='utf-8').count(P.IMAGE)==1
                        return types.SimpleNamespace(stdout=json.dumps([{'Destination':'/app/'+name,'Source':str(P.RELEASE/name if new_unit else source),'RW':False} for name,(source,_) in patches.items()]))
                    if args[1:3]==('image','inspect'):return types.SimpleNamespace(stdout=P.BASE_IMAGE_ID)
                    return types.SimpleNamespace(stdout='offline stub')
                raise AssertionError('Unexpected command '+str(args))
            with patch.multiple(P,**globals_to_patch),patch.object(P,'run',side_effect=fake_run),patch.object(P,'healthy',return_value=True),patch.object(P,'verify_image_sources',return_value='offline'),patch.object(P,'validate_manifest'),patch.object(sys,'argv',['publisher']),patch.object(Path,'symlink_to',new=fake_link),patch.object(P.os,'replace',side_effect=fake_replace):
                unit.write_text(fake_unit(),encoding='utf-8');demand.write_text(fake_unit(),encoding='utf-8')
                original_unit=unit.read_bytes();original_dropin=demand.read_bytes();original_env=env.read_bytes()
                manifest={**fixture_manifest(),'baseline':baseline,'files':{name:P.sha(delta/name) for name in changes},'base_env_sha256':P.sha(env),'base_unit_sha256':P.sha(unit),'base_on_demand_sha256':P.sha(demand),'base_source_manifest_sha256':P.sha(current/'source_manifest.json'),'archive_sha256':P.sha(stage/'delta.tar.gz'),'dockerfile_sha256':P.sha(stage/'Dockerfile')}
                (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
                before=P.db_state()
                if fail_after_current:
                    with self.assertRaisesRegex(RuntimeError,'Execution or legacy state changed'):P.main()
                    self.assertEqual(current_target[0],current)
                    self.assertEqual(unit.read_bytes(),original_unit);self.assertEqual(demand.read_bytes(),original_dropin)
                    with sql(db) as connection:self.assertEqual(connection.execute('SELECT COUNT(*) FROM events WHERE seq=9999').fetchone()[0],1)
                    self.assertEqual(before['ledger']['active_scope'],P.db_state()['ledger']['active_scope'])
                else:
                    with redirect_stdout(io.StringIO()):P.main()
                    self.assertEqual(current_target[0],P.RELEASE);self.assertEqual(before,P.db_state())
                    for name in patches:self.assertIn('src='+str(P.RELEASE/name)+',',unit.read_text(encoding='utf-8'))
                self.assertEqual(env.read_bytes(),original_env)
                self.assertTrue(activity['fc27-player-tool.service']);self.assertTrue(activity['fc27-player-demand.socket']);self.assertFalse(activity['fc27-player-collect.timer'])
                self.assertFalse(any(cmd[:2]==('systemctl','start') and cmd[-1]=='fc27-p2pah-session.service' for cmd in calls))
                self.assertTrue(list((root/'backups').glob('*/control.sqlite3')))

    def test_full_success_offline(self):self.simulate()
    def test_full_failure_rolls_back_units_current_but_never_db(self):self.simulate(fail_after_current=True)


if __name__=='__main__': unittest.main(verbosity=2)
