import contextlib,hashlib,importlib.util,json,os,shutil,tempfile,types,unittest
from unittest.mock import patch
from pathlib import Path
import learning_bridge
from prepare_learning_bridge import verify_receipt

class BridgeTests(unittest.TestCase):
    def test_existing_private_profile_boundary_exact_only(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);b,_=self.load(root);m={'scope':b.HERMES_HISTORY_SCOPE}
            for path,(uid,gid,mode) in learning_bridge.PROFILE_BOUNDARIES.items():
                info=types.SimpleNamespace(st_uid=uid,st_gid=gid,st_mode=mode)
                self.assertTrue(b.learning_boundary_approved(m,root,b.rooted(root,path),info))
                for key,value in [('st_uid',42),('st_gid',42),('st_mode',mode|0o020),('st_mode',mode^0o010)]:
                    bad=types.SimpleNamespace(**vars(info));setattr(bad,key,value)
                    self.assertFalse(b.learning_boundary_approved(m,root,b.rooted(root,path),bad))
                self.assertFalse(b.learning_boundary_approved(m,root,b.rooted(root,path+'/other'),info))
                self.assertFalse(b.learning_boundary_approved({'scope':'other'},root,b.rooted(root,path),info))

    def test_success_receipt_identity_and_complete_readback(self):
        commit='a'*40;operation='nav-20261017T120000Z';es=dict(releaseReady=True,sourceCommit=commit,files=[dict(target='/target',sha256='b'*64)],unchangedRequired=[dict(path='/protected',sha256='c'*64)])
        raw=json.dumps(es).encode();r=dict(sourceCommit=commit,operation=operation,releaseID=operation,releaseId=operation,backup='/var/backups/fs-navigation-20261006/'+operation,executionManifestSha256=hashlib.sha256(raw).hexdigest(),session_ready=True,protected_verified=True,business_health=True,readback=[dict(target='/target',sha256='b'*64)],protected_readback=[dict(target='/protected',sha256='c'*64)],targets=1,protected=1)
        verify_receipt(es,raw,r,commit,operation)
        # Learning may have a new source head while consuming the exact prior ES deployment.
        verify_receipt(es,raw,r,'e'*40,operation)
        for key,value in [('sourceCommit','d'*40),('operation','nav-20261017T120001Z'),('executionManifestSha256','0'*64),('session_ready',False),('protected_readback',[]),('readback',[]),('protected',0)]:
            bad=dict(r);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):verify_receipt(es,raw,bad,commit,operation)

    def test_five_target_apply_and_external_conflicts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);stage=root/'stage';stage.mkdir();here=Path(__file__).parent
            shutil.copyfile(here.parent/'publisher/release_navigation_base.py',stage/'release_navigation_base.py')
            # Synthetic fixture models root-owned targets; real ownership guards run unchanged.
            family='/var/lib/fs-hermes-fc/profile/skills/ops-report-brief/ops-report-family/'
            targets=['/opt/fs-hermes-fc/business_context.py','/opt/fs-hermes-fc/learning-loop.md',family+'SKILL.md',family+'references/ref1.md',family+'references/ref2.md']
            sha=lambda b:hashlib.sha256(b).hexdigest();files=[]
            for i,t in enumerate(targets):
                rel='learning/'+str(i)+'.md';p=stage/'candidate'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'new'+str(i).encode())
                files.append(dict(candidate=rel,target=t,sha256=sha(p.read_bytes()),beforeSha256=sha(b'old') if i<3 else None,mode='0o644' if i<3 else '0o600'))
                if i<3:
                    dest=root/t.lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b'old');dest.chmod(0o644)
            base_raw=(stage/'release_navigation_base.py').read_text(encoding='utf8');ns={};exec(compile(base_raw,str(stage/'release_navigation_base.py'),'exec'),ns)
            required=set(ns['HERMES_TARGETS'].values())|{'/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')}|{'/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py'}
            protected=[]
            for t in sorted(required-set(targets)):
                p=root/t.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'protected');protected.append(dict(path=t,sha256=sha(b'protected')))
            m=dict(schemaVersion=1,scope='hermes-private-learning-20261017-v1',releaseReady=True,files=files,unchangedRequired=protected,runtimeRequired={u:{'ActiveState':'active'} for u in ('fs-business-range.service','fs-hermes-fc.service')},imageId='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544',businessWrites=False,timersChanged=False)
            raw=json.dumps(m).encode();(stage/'approved-manifest.json').write_bytes(raw)
            code=Path(learning_bridge.__file__).read_text(encoding='utf8').replace('PREPARE_REPLACES_THIS',sha(raw));p=stage/'learning_bridge.py';p.write_text(code,encoding='utf8');spec=importlib.util.spec_from_file_location('five_bridge',p);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);b=mod.load_base()
            @contextlib.contextmanager
            def fence(*a):yield types.SimpleNamespace(modified=False,confirmed=False)
            for name in ('locks','live_lock','hermes_admission_fence','model_release_lock'):setattr(b,name,fence)
            b.hermes_quiescent=lambda *a:None;b.retirement=lambda *a:None;b.restart_for=lambda *a:None
            if os.name=='nt':b.directory_sync=lambda *a:None
            b.subprocess=types.SimpleNamespace(PIPE=-1,run=lambda *a,**k:types.SimpleNamespace(stdout='ActiveState=active\n'))
            original=Path.stat
            def root_owner(path,*a,**k):
                st=original(path,*a,**k);v=list(st);v[4]=v[5]=0
                for boundary,(uid,gid,mode) in learning_bridge.PROFILE_BOUNDARIES.items():
                    if path==root/boundary.lstrip('/'):v[4]=uid;v[5]=gid;v[0]=(v[0]&~0o777)|mode
                if os.name=='nt':
                    v[0]&=~0o022
                    for row in files:
                        if path==root/row['target'].lstrip('/'):v[0]=(v[0]&~0o777)|int(row['mode'],8)
                return os.stat_result(v)
            with patch.object(Path,'stat',root_owner):
                external=root/targets[3].lstrip('/');external.parent.mkdir(parents=True,exist_ok=True);external.write_bytes(b'new3');external.chmod(0o600)
                with self.assertRaisesRegex(ValueError,'new_learning_reference_conflict'):b.inspect(m,stage,root)
                external.unlink()
                result=b.apply(m,stage,sha(raw),raw,'nav-20261017T120000Z',root)
                self.assertEqual(result['status'],'applied-awaiting-actual-http-role-acceptance')
                for row in files:self.assertEqual(b.digest(root/row['target'].lstrip('/')),row['sha256'])
                # Outside its apply context even identical new content remains a collision.
                with self.assertRaisesRegex(ValueError,'new_learning_reference_conflict'):b.guards(m,root)
                external.write_bytes(b'foreign')
                with self.assertRaisesRegex(ValueError,'new_learning_reference_conflict'):b.guards(m,root)
                # A different writer after our durable creation must remain UNKNOWN,
                # never be accepted as our reference or deleted by rollback.
                for i,t in enumerate(targets):
                    dest=root/t.lstrip('/')
                    if i<3:dest.write_bytes(b'old')
                    else:dest.unlink()
                durable=b.journal_write;injected=[False]
                def interfere(backup,journal):
                    durable(backup,journal)
                    if not injected[0] and any(x['target']==targets[3] and x.get('written') for x in journal['files']):
                        injected[0]=True;external.write_bytes(b'foreign')
                b.journal_write=interfere
                with self.assertRaisesRegex(ValueError,'preserve all files'):b.apply(m,stage,sha(raw),raw,'nav-20261017T120001Z',root)
                self.assertEqual(external.read_bytes(),b'foreign')

    @unittest.skipUnless(__import__('os').name=='posix','requires POSIX flock')
    def test_release_lock_contention(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);base,_=self.load(root)
            with base.locks(root):
                with self.assertRaises(BlockingIOError):
                    with base.locks(root):pass

    def load(self,root):
        here=Path(__file__).parent;base=here.parent/'publisher/release_navigation_base.py'
        shutil.copyfile(base,root/'release_navigation_base.py')
        m={'files':[{'candidate':'learning/ref.md','target':'/private/ref.md','beforeSha256':None,'mode':'0o600'}]}
        raw=json.dumps(m).encode();(root/'approved-manifest.json').write_bytes(raw)
        code=Path(learning_bridge.__file__).read_text().replace('PREPARE_REPLACES_THIS',hashlib.sha256(raw).hexdigest())
        p=root/'learning_bridge.py';p.write_text(code,encoding='utf8');spec=importlib.util.spec_from_file_location('test_bridge',p);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        return mod.load_base(),m

    def test_inherited_fences_cas_and_new_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);base,m=self.load(root)
            # Keep exact inherited functions for locking/admission/atomic rollback.
            self.assertEqual(base.HERMES_HISTORY_SCOPE,'hermes-private-learning-20261017-v1')
            self.assertIn('hermes_admission_fence',base.apply.__wrapped__.__code__.co_names)
            self.assertIn('locks',base.apply.__wrapped__.__code__.co_names)
            self.assertIn('inspect',base.apply.__wrapped__.__code__.co_names)
            rows=[{'target':'/private/ref.md','candidate':'learning/ref.md','beforeSha256':None,'sha256':hashlib.sha256(b'new').hexdigest()}]
            base.validate=lambda m,s:rows;base.guards=lambda *a,**k:None;base.retirement=lambda *a:None
            base.inspect(m,root,root)
            target=root/'private/ref.md';target.parent.mkdir();target.write_bytes(b'existing')
            with self.assertRaisesRegex(ValueError,'baseline drift'):base.inspect(m,root,root)
            rows[0]['beforeSha256']=hashlib.sha256(b'existing').hexdigest();base.inspect(m,root,root)
            target.write_bytes(b'drift')
            with self.assertRaisesRegex(ValueError,'baseline drift'):base.inspect(m,root,root)

    def test_unknown_preserves_and_new_reference_rolls_back(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);base,m=self.load(root);base.rollback_credentials=lambda *a:None
            if __import__('os').name=='nt':base.directory_sync=lambda *a:None  # POSIX fsync stays inherited on Linux.
            p=root/'private/ref.md';p.parent.mkdir();p.write_bytes(b'UNKNOWN')
            r=dict(target='/private/ref.md',candidate='learning/ref.md',beforeSha256=None,sha256=hashlib.sha256(b'new').hexdigest(),intent=True,written=True,beforeMode=0o600)
            journal=dict(manifest={'scope':base.HERMES_HISTORY_SCOPE},files=[r],approvedManifestSha256='x')
            backup=root/'backup';backup.mkdir()
            with self.assertRaisesRegex(ValueError,'preserve all files'):base.rollback_journal(backup,journal,root)
            self.assertEqual(p.read_bytes(),b'UNKNOWN')
            p.write_bytes(b'new');base.rollback_journal(backup,journal,root)
            self.assertFalse(p.exists());self.assertEqual(journal['status'],'rolled-back')

if __name__=='__main__':unittest.main()
