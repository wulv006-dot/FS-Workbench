"""Exact three-target publisher contracts; all host commands are offline substitutes."""
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import types
import unittest
from contextlib import closing, redirect_stdout
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if sys.platform == 'win32':
    sys.modules.setdefault('fcntl', types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=lambda *args: None))
spec = importlib.util.spec_from_file_location('tag_labels_publisher', HERE/'upgrade_tag_labels.py')
A = importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
P = A.P
prepare_spec = importlib.util.spec_from_file_location('tag_labels_prepare', HERE/'prepare_tag_labels.py')
S = importlib.util.module_from_spec(prepare_spec); prepare_spec.loader.exec_module(S)


def manifest():
    return {'version': P.VERSION, 'base_version': P.BASE_VERSION, 'base_image_id': P.BASE_IMAGE_ID,
            'manual_flag': P.MANUAL_FLAG, 'baseline': dict(A.BASELINE), 'files': dict(A.FILES),
            **A.CONFIG_SHA, 'archive_sha256': 'a'*64, 'dockerfile_sha256': 'b'*64}


def unit():
    mounts = ' '.join('--mount type=bind,src='+str(source)+',dst=/app/'+name+',readonly'
                      for name,(source,_) in P.PATCHES.items())
    return ('ExecStart=docker run --user 992:987 --memory 2g '+mounts+
            ' --mount type=bind,src=/var/lib/fc27-cloud/state/price-writer.lock,dst=/var/lib/fc27-cloud/state/price-writer.lock,readonly '+P.BASE_IMAGE+'\n')


def database(path):
    with closing(sqlite3.connect(path)) as db:
        db.executescript('''CREATE TABLE executions(id TEXT,status TEXT,step TEXT);
          CREATE TABLE events(seq INTEGER,execution_id TEXT,detail TEXT);
          CREATE TABLE execution_items(execution_id TEXT,model_id INTEGER,status TEXT);
          CREATE TABLE active_scope(futbin_id TEXT,execution_id TEXT);
          CREATE TABLE legacy_unresolved(futbin_id TEXT,evidence TEXT);
          CREATE TABLE plans(id TEXT,payload TEXT);
          CREATE TABLE model_snapshot_rows(id INTEGER,payload TEXT);
          INSERT INTO executions VALUES('original','needs_reconcile','unknown');
          INSERT INTO events VALUES(1,'original','UNKNOWN keep');
          INSERT INTO active_scope VALUES('23691','original');
          INSERT INTO legacy_unresolved VALUES('old','keep');
          INSERT INTO plans VALUES('single-image','saved plan');
          INSERT INTO model_snapshot_rows VALUES(45274659,'original tags');''')


class Contracts(unittest.TestCase):
    def test_stage_uses_committed_bytes_exact_three_members_and_refuses_overwrite(self):
        repo=next(parent for parent in HERE.parents if (parent/'fc27_players_cloud').is_dir())
        calls=[]
        def git(args):
            calls.append(args)
            if args[-2]=='rev-parse':return b'1'*40+b'\n'
            self.assertEqual(args[-2],'show')
            return (repo/args[-1].split(':',1)[1]).read_text(encoding='utf-8').encode('utf-8')
        with tempfile.TemporaryDirectory() as temporary,patch.object(S.subprocess,'check_output',side_effect=git):
            stage=Path(temporary)/'stage';receipt=S.prepare(repo,'HEAD',stage)
            self.assertTrue(receipt['prepared_only']);self.assertFalse(receipt['applied'])
            A.validate_manifest(json.loads((stage/'manifest.json').read_text(encoding='utf-8')))
            with tarfile.open(stage/'delta.tar.gz') as archive:
                self.assertEqual({item.name for item in archive.getmembers()},set(A.FILES))
                for name,value in A.FILES.items():self.assertEqual(S.digest(archive.extractfile(name).read()),value)
            with self.assertRaisesRegex(RuntimeError,'already exists'):S.prepare(repo,'HEAD',stage)
            self.assertEqual(receipt,json.loads((stage/'stage-receipt.json').read_text(encoding='utf-8')))
            self.assertTrue(all(call[-2] in ('rev-parse','show') for call in calls))

    def test_exact_three_targets_and_all_51_baselines_are_required(self):
        self.assertEqual(len(A.BASELINE), 51)
        self.assertEqual(set(A.FILES), {'VERSION','player_web/model_service.py','player_web/static/app.js'})
        A.validate_manifest(manifest())
        for name in ('player_web/shared_session.py','球员维护工具/admin_client.py','player_web/static/images.js'):
            bad = manifest(); bad['files'][name] = 'c'*64
            with self.assertRaises(RuntimeError): A.validate_manifest(bad)
        for key in ('baseline', 'files'):
            bad = manifest(); bad[key].pop(next(iter(bad[key])))
            with self.assertRaises(RuntimeError): A.validate_manifest(bad)

    def test_wrong_base_config_candidates_or_fixture_are_rejected(self):
        for key in ('version','base_version','base_image_id','manual_flag',*A.CONFIG_SHA):
            bad=manifest();bad[key]='stale'
            with self.subTest(key=key),self.assertRaises(RuntimeError):A.validate_manifest(bad)
        bad=manifest();bad['files']['player_web/model_service.py']='c'*64
        with self.assertRaises(RuntimeError):A.validate_manifest(bad)
        bad=manifest();bad['_fixture_only']=True
        with self.assertRaises(RuntimeError):A.validate_manifest(bad)
        bad=manifest();bad['archive_sha256']='TBD'
        with self.assertRaises(RuntimeError):A.validate_manifest(bad)

    def test_original_publisher_and_mapping_are_pinned_without_changing_history(self):
        self.assertEqual(A.original.read_text(encoding='utf-8').count("VERSION = '2026.10.29-cloud.15'"),1)
        with tempfile.TemporaryDirectory() as temporary:
            p=Path(temporary)/'changed';p.write_text('changed',encoding='utf-8')
            with self.assertRaises(RuntimeError):A.pinned_text(p,A.ORIGINAL_SHA)
        P.validate_transport(P.HMAC_TRANSPORT)
        self.assertEqual(A.BASELINE['player_web/shared_session.py'],P.PATCHES['player_web/shared_session.py'][1])

    def test_unit_moves_only_image_and_two_readonly_binds(self):
        before=unit();after=P.updated_unit(before)
        expected=before.replace(P.BASE_IMAGE,P.IMAGE)
        for name,(source,_) in P.PATCHES.items():expected=expected.replace('src='+str(source)+',','src='+str(P.RELEASE/name)+',')
        self.assertEqual(after,expected)
        self.assertIn('price-writer.lock,readonly',after)
        for wrong in (before.replace(',readonly',',rw',1),before+P.BASE_IMAGE):
            with self.assertRaises(RuntimeError):P.updated_unit(wrong)
        P.validate_dockerfile((HERE/'Dockerfile').read_text(encoding='utf-8'))

    def test_complete_store_detects_saved_image_plan_snapshot_and_schema_changes(self):
        for statement in ("UPDATE plans SET payload='lost'", "UPDATE model_snapshot_rows SET payload='wrong'", 'CREATE TABLE extra(value TEXT)'):
            with self.subTest(statement=statement),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);db=root/'db';tasks=root/'tasks';database(db);tasks.write_text('original')
                with patch.object(P,'DB',db),patch.object(P,'ADMIN_TASKS',tasks):
                    before=P.db_state()
                    with closing(sqlite3.connect(db)) as conn:conn.execute(statement);conn.commit()
                    self.assertNotEqual(before,P.db_state())
                    self.assertEqual(before['ledger']['legacy_unresolved'],P.db_state()['ledger']['legacy_unresolved'])

    def test_entry_uses_original_deployment_lock(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(P,'ROOT',Path(temporary)),patch.object(P,'main') as execute,patch.object(P.fcntl,'flock') as lock:
            A.main();execute.assert_called_once();lock.assert_called_once()
            self.assertTrue((Path(temporary)/'deployment.lock').is_file())
        with tempfile.TemporaryDirectory() as temporary,patch.object(P,'ROOT',Path(temporary)),patch.object(P,'main') as execute,patch.object(P.fcntl,'flock',side_effect=BlockingIOError):
            with self.assertRaises(BlockingIOError):A.main()
            execute.assert_not_called()

    def simulate(self, rollback=False, active=False):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);current=root/'releases'/P.BASE_VERSION;current.mkdir(parents=True)
            stage=root/'staging'/'tag-labels-20261029';stage.mkdir(parents=True)
            env=root/'app.env';svc=root/'service';demand=root/'dropins/on-demand.conf';demand.parent.mkdir()
            db=root/'control.sqlite3';tasks=root/'admin_tasks.json';price_lock=root/'price-writer.lock'
            database(db);tasks.write_text('original UNKNOWN');price_lock.write_text('keep inode')
            if active:
                with closing(sqlite3.connect(db)) as conn:conn.execute("INSERT INTO executions VALUES('wait','waiting_price_lock','pending')");conn.commit()
            baseline={}
            for name in A.BASELINE:
                path=current/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(P.HMAC_TRANSPORT if name=='player_web/shared_session.py' else 'base '+name,encoding='utf-8')
                baseline[name]=P.sha(path)
            (current/'source_manifest.json').write_text(json.dumps({'version':P.BASE_VERSION,'files':baseline}),encoding='utf-8')
            patches={name:(current/name,baseline[name]) for name in P.PATCHES}
            values={'VERSION':(P.VERSION+'\n').encode(),'player_web/model_service.py':b'new model service','player_web/static/app.js':b'new renderer'}
            with tarfile.open(stage/'delta.tar.gz','w:gz') as archive:
                for name,data in values.items():
                    info=tarfile.TarInfo(name);info.size=len(data);archive.addfile(info,io.BytesIO(data))
            (stage/'Dockerfile').write_text((HERE/'Dockerfile').read_text(encoding='utf-8'),encoding='utf-8')
            env.write_text('WRITE_ENABLED=false\nAUTO_WRITE_ENABLED=false\nMANUAL_NEW_CARDS_ENABLED=true\nMANUAL_MODEL_IMAGES_ENABLED=true\nMANUAL_EXISTING_RECOMMEND_ENABLED=true\nFS_SHARED_BACKEND_SESSION=true\nAPPROVED_PUBLIC_HTTP_SOURCE=http://139.28.18.234:8001\n',encoding='utf-8')
            args={'ROOT':root,'CURRENT':current,'RELEASE':root/'releases'/P.VERSION,'STAGE':stage,'ENV':env,'UNIT':svc,'ON_DEMAND':demand,'DB':db,'ADMIN_TASKS':tasks,'PRICE_LOCK':price_lock,'PATCHES':patches}
            calls=[];activity={'fc27-player-tool.service':True,'fc27-player-demand.socket':True,'fc27-player-collect.timer':False,'fc27-player-collect.service':False}
            target=[current];mutated=[False];real_replace=P.os.replace
            def link(path,value,*a,**k):path.write_text(str(value),encoding='utf-8')
            def replace(source,dest):
                if Path(dest)==current:target[0]=Path(Path(source).read_text(encoding='utf-8'));Path(source).unlink()
                else:real_replace(source,dest)
            def run(*cmd):
                calls.append(cmd)
                if cmd[0]=='systemctl':
                    if cmd[1]=='show':
                        if cmd[-1]=='--property=ActiveState':out='ActiveState='+('active' if activity.get(cmd[2],False) else 'inactive')
                        else:
                            pid={'fc-pricing-v3.service':5004,'fc27-cloud-api.service':699,'fc27-p2pah-session.service':0}[cmd[2]]
                            out='ActiveState='+('active' if pid else 'failed')+'\nMainPID='+str(pid)+'\nUnitFileState=disabled'
                        return types.SimpleNamespace(stdout=out)
                    if cmd[1] in ('start','stop'):
                        self.assertIn(cmd[2],activity,'unrelated service mutation');activity[cmd[2]]=cmd[1]=='start'
                        if rollback and cmd[1:]==('start','fc27-player-demand.socket') and target[0]==P.RELEASE and not mutated[0]:
                            with closing(sqlite3.connect(db)) as conn:conn.execute("UPDATE plans SET payload='concurrent plan preserved'");conn.commit()
                            mutated[0]=True
                    return types.SimpleNamespace(stdout='')
                self.assertEqual(cmd[0],'docker')
                if cmd[1:3]==('inspect','--format'):
                    if cmd[3]=='{{.Image}}':return types.SimpleNamespace(stdout=P.BASE_IMAGE_ID)
                    deployed=P.IMAGE in svc.read_text(encoding='utf-8')
                    return types.SimpleNamespace(stdout=json.dumps([{'Destination':'/app/'+name,'Source':str(P.RELEASE/name if deployed else source),'RW':False} for name,(source,_) in patches.items()]))
                if cmd[1:3]==('image','inspect'):return types.SimpleNamespace(stdout=P.BASE_IMAGE_ID)
                return types.SimpleNamespace(stdout='offline')
            with patch.multiple(P,**args),patch.object(P,'run',side_effect=run),patch.object(P,'healthy',return_value=True),patch.object(P,'verify_image_sources',return_value='offline'),patch.object(P,'validate_manifest'),patch.object(sys,'argv',['publisher']),patch.object(Path,'symlink_to',new=link),patch.object(P.os,'replace',side_effect=replace):
                svc.write_text(unit(),encoding='utf-8');demand.write_text(unit(),encoding='utf-8')
                prior=[p.read_bytes() for p in (env,svc,demand)];lock_inode=price_lock.stat().st_ino
                m={**manifest(),'baseline':baseline,'files':{name:__import__('hashlib').sha256(data).hexdigest() for name,data in values.items()},'base_env_sha256':P.sha(env),'base_unit_sha256':P.sha(svc),'base_on_demand_sha256':P.sha(demand),'base_source_manifest_sha256':P.sha(current/'source_manifest.json'),'archive_sha256':P.sha(stage/'delta.tar.gz'),'dockerfile_sha256':P.sha(stage/'Dockerfile')}
                (stage/'manifest.json').write_text(json.dumps(m),encoding='utf-8');before=P.db_state()
                if active:
                    with self.assertRaisesRegex(RuntimeError,'Active job'):P.main()
                    self.assertFalse(any(cmd[:2]==('systemctl','stop') for cmd in calls));self.assertFalse(P.RELEASE.exists())
                elif rollback:
                    with self.assertRaisesRegex(RuntimeError,'Execution or legacy state changed'):P.main()
                    self.assertEqual(target[0],current);self.assertEqual([p.read_bytes() for p in (env,svc,demand)],prior)
                    with closing(sqlite3.connect(db)) as conn:self.assertEqual(conn.execute('SELECT payload FROM plans').fetchone()[0],'concurrent plan preserved')
                else:
                    with redirect_stdout(io.StringIO()):P.main()
                    self.assertEqual(target[0],P.RELEASE);self.assertEqual(before,P.db_state())
                    result=json.loads((P.RELEASE/'source_manifest.json').read_text(encoding='utf-8'))
                    self.assertEqual(result,{'version':P.VERSION,'files':{**baseline,**m['files']}})
                    self.assertEqual(len(result['files']),51)
                    for name,value in baseline.items():
                        if name not in values:self.assertEqual(P.sha(P.RELEASE/name),value)
                self.assertEqual(env.read_bytes(),prior[0]);self.assertEqual(price_lock.stat().st_ino,lock_inode)
                self.assertFalse(activity['fc27-player-collect.timer']);self.assertTrue(activity['fc27-player-demand.socket'])
                self.assertTrue(activity['fc27-player-tool.service']);self.assertEqual(P.db_state()['ledger']['legacy_unresolved'],before['ledger']['legacy_unresolved'])
                if not active:self.assertTrue(list((root/'backups').glob('*/control.sqlite3')))

    def test_full_success_preserves_48_files_and_complete_store(self):self.simulate()
    def test_full_rollback_preserves_concurrent_plan_and_original_unknown(self):self.simulate(rollback=True)
    def test_active_job_refuses_before_any_stop_or_stage_write(self):self.simulate(active=True)


if __name__ == '__main__':unittest.main(verbosity=2)
