"""No live Docker, service, network, role, or model calls in these fixtures."""
import copy,hashlib,importlib.util,json,tempfile,unittest,os
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).parent

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class CapabilityReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.stage=Path(self.temp.name)/'stage';self.stage.mkdir()
        self.pub=load('capability_publisher_fixture',HERE/'shared_candidate/release_navigation.py')
        self.image=load('capability_image_fixture',HERE/'shared_candidate/capability_image_lifecycle.py')
        self.helper=HERE/'shared_candidate/capability_image_lifecycle.py'
        (self.stage/self.helper.name).write_bytes(self.helper.read_bytes())
        package=HERE/'admin_order_capabilities_20261014';files=[]
        for rel,target in self.pub.HERMES_CAPABILITY_TARGETS.items():
            if rel.startswith('hermes/runtime/'):source=HERE/rel.rsplit('/',1)[1]
            elif '/fs-package/' in rel or '/session-package/' in rel:source=package/rel.rsplit('/',1)[1]
            else:source=package/'shared_candidate'/rel.rsplit('/',1)[1]
            raw=source.read_bytes();p=self.stage/'candidate'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            files.append({'candidate':rel,'target':target,'sha256':hashlib.sha256(raw).hexdigest(),'beforeSha256':'b'*64 if rel in self.pub.CAP_EXISTING_TARGETS else None})
        protected=set(self.pub.HERMES_TARGETS.values())-set(self.pub.HERMES_CAPABILITY_TARGETS.values())
        protected|={'/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')}
        protected|={'/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py'}
        protected|=self.pub.CAP_PROTECTED_SESSION
        self.manifest={'schemaVersion':1,'scope':self.pub.HERMES_CAPABILITY_SCOPE,'releaseReady':False,'files':files,
            'unchangedRequired':[{'path':p,'sha256':'c'*64} for p in sorted(protected)],
            'runtimeRequired':{u:{'ActiveState':'active'} for u in ('fs-business-range.service','fs-hermes-fc.service','fc27-p2pah-session.service')},
            'imageId':'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544','sourceCommit':'a'*40,
            'sessionCurrentImage':'sha256:'+'a'*64,'sessionBaseImage':'sha256:'+'b'*64,
            'imageLifecycleSha256':hashlib.sha256(self.helper.read_bytes()).hexdigest(),'businessWrites':False,'timersChanged':False}

    def test_exact14_source_pairs_and50_consumers_required(self):
        self.assertEqual(len(self.pub.validate(self.manifest,self.stage)),14)
        self.assertEqual(len(self.manifest['unchangedRequired']),50)
        for change in ('missing','existing_absent','protected','identity','helper','write'):
            value=copy.deepcopy(self.manifest)
            if change=='missing':value['files'].pop()
            if change=='existing_absent':value['files'][0]['beforeSha256']=None
            if change=='protected':value['unchangedRequired'].pop()
            if change=='identity':value['sessionCurrentImage']='unverified-tag'
            if change=='helper':value['imageLifecycleSha256']='0'*64
            if change=='write':value['businessWrites']=True
            with self.assertRaises(ValueError):self.pub.validate(value,self.stage)

    def test_old_scope_and_extra_file_cannot_publish_capability(self):
        for scope in (self.pub.HERMES_UPDATE_SCOPE,self.pub.HERMES_SCOPE):
            value=copy.deepcopy(self.manifest);value['scope']=scope
            with self.assertRaises(ValueError):self.pub.validate(value,self.stage)
        value=copy.deepcopy(self.manifest);value['files'].append(dict(value['files'][0],candidate='extra.py'))
        with self.assertRaises(ValueError):self.pub.validate(value,self.stage)

    def test_projection_pair_and_wildcard_docker_copy_are_rejected(self):
        path=self.stage/'candidate/capability/session-package/capabilities.py'
        path.write_bytes(path.read_bytes()+b'\n# fixture drift\n')
        value=copy.deepcopy(self.manifest)
        next(r for r in value['files'] if r['candidate']=='capability/session-package/capabilities.py')['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'paired capability'):self.pub.validate(value,self.stage)
        path.write_bytes((self.stage/'candidate/capability/fs-package/capabilities.py').read_bytes())
        path=self.stage/'candidate/capability/session/Dockerfile.session'
        path.write_bytes(path.read_bytes()+b'\nCOPY admin_order_capabilities_20261014 /usr/local/bin/admin_order_capabilities_20261014/\n')
        value=copy.deepcopy(self.manifest)
        next(r for r in value['files'] if r['candidate']=='capability/session/Dockerfile.session')['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'exact three'):self.pub.validate(value,self.stage)

    def test_lifecycle_source_is_frozen_and_image_baseline_checks_running_container(self):
        module=self.pub.capability_lifecycle(self.manifest)
        self.assertEqual(module.TAG,self.pub.CAP_SESSION_TAG)
        wrong=copy.deepcopy(self.manifest);wrong['imageLifecycleSha256']='0'*64
        with self.assertRaises(ValueError):self.pub.capability_lifecycle(wrong)
        with patch.object(self.image,'image_id',side_effect=[self.manifest['sessionCurrentImage'],self.manifest['sessionBaseImage']]),patch.object(self.image.subprocess,'check_output',return_value=json.dumps([{'Image':'sha256:'+'f'*64,'Config':{'Image':self.image.TAG}}])):
            with self.assertRaisesRegex(ValueError,'running session image'):self.image.baseline(self.manifest)

    def test_image_build_uses_only_selected_code_and_journals_before_tag(self):
        root=Path(self.temp.name)/'root';source=root/self.image.ROOT.lstrip('/');source.mkdir(parents=True)
        # Place only approved code in minimal context even with a secret-like unrelated file beside it.
        (source/'not-for-build.env').write_text('fixture-private-not-real')
        for row in self.manifest['files']:
            if row['target'].startswith(self.image.ROOT+'/'):
                p=root/row['target'].lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((self.stage/'candidate'/row['candidate']).read_bytes())
        for name in ('admin_summary.py','supplement_fields.py'):
            p=source/name;p.write_text('fixture code')
            next(r for r in self.manifest['unchangedRequired'] if r['path']==self.image.ROOT+'/'+name)['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
        backup=root/'backup/nav-20261014T000000Z';backup.mkdir(parents=True)
        journal={'sessionImageBefore':self.manifest['sessionCurrentImage'],'manifest':self.manifest};events=[]
        old=journal['sessionImageBefore'];new='sha256:'+'d'*64;tag=[old]
        def image_id(name):return new if ':capability-' in name else tag[0]
        def run(command,**kwargs):
            events.append(('run',command))
            if command[:2]==['docker','tag']:
                self.assertTrue(journal.get('sessionImageIntent'));self.assertEqual(journal['sessionBuiltImage'],new)
                tag[0]=command[2]
        def output(command,**kwargs):
            return '\n'.join(hashlib.sha256((backup/'session-build'/name.removeprefix('/usr/local/bin/')).read_bytes()).hexdigest()+'  '+name for name in command[8:])
        # Python3.9-compatible remove prefix is used by the target runtime.
        with ExitStack() as platform_fixture,patch.object(self.image,'baseline'),patch.object(self.image,'image_id',side_effect=image_id),patch.object(self.image.subprocess,'run',side_effect=run),patch.object(self.image.subprocess,'check_output',side_effect=output),patch.object(self.image,'restart_health') as health:
            if os.name=='nt':platform_fixture.enter_context(patch.object(self.pub,'directory_sync'))
            self.image.apply(self.manifest,backup,journal,root,self.pub.atomic,lambda b,j:events.append(('journal',copy.deepcopy(j))),self.pub.digest,self.pub.no_target_link)
        self.assertEqual(len(list((backup/'session-build').rglob('*.py'))),6)
        self.assertFalse((backup/'session-build/not-for-build.env').exists())
        build=next(c for typ,c in events if typ=='run' and c[:2]==['docker','build'])
        self.assertIn('none',build);self.assertIn('--pull=false',build)
        self.assertTrue(journal['sessionImageWritten']);health.assert_called_once_with(new)

    def test_restore_preserves_unknown_tag_and_failed_restart(self):
        journal={'sessionImageIntent':True,'sessionImageBefore':'sha256:'+'a'*64,'sessionBuiltImage':'sha256:'+'d'*64}
        with patch.object(self.image,'image_id',return_value='sha256:'+'f'*64),patch.object(self.image.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'tag drift'):self.image.restore(self.stage,journal,lambda *args:None)
            run.assert_not_called()
        with patch.object(self.image,'image_id',side_effect=[journal['sessionBuiltImage'],journal['sessionImageBefore']]),patch.object(self.image.subprocess,'run'),patch.object(self.image,'restart_health',side_effect=ValueError('health failed')):
            with self.assertRaisesRegex(ValueError,'health failed'):self.image.restore(self.stage,journal,lambda *args:None)
        self.assertTrue(journal['sessionImageRollbackIntent']);self.assertNotIn('sessionImageRestored',journal)

    def test_restore_no_image_intent_never_changes_existing_tag_or_unit(self):
        with patch.object(self.image,'image_id') as lookup,patch.object(self.image.subprocess,'run') as run,patch.object(self.image,'restart_health') as health:
            self.image.restore(self.stage,{'sessionImageBefore':'sha256:'+'a'*64},lambda *args:None)
            lookup.assert_not_called();run.assert_not_called();health.assert_not_called()

    def test_restore_known_written_image_switches_back_and_confirms_health(self):
        old='sha256:'+'a'*64;new='sha256:'+'d'*64;journal={'sessionImageIntent':True,'sessionImageBefore':old,'sessionBuiltImage':new};writes=[]
        with patch.object(self.image,'image_id',side_effect=[new,old]),patch.object(self.image.subprocess,'run') as run,patch.object(self.image,'restart_health') as health:
            self.image.restore(self.stage,journal,lambda b,j:writes.append(copy.deepcopy(j)))
        run.assert_called_once_with(['docker','tag',old,self.image.TAG],check=True)
        self.assertTrue(writes[0]['sessionImageRollbackIntent']);health.assert_called_once_with(old)
        self.assertTrue(journal['sessionImageRestored']);self.assertFalse(journal['sessionImageWritten'])

    def test_restart_requires_original_admission_fence(self):
        with self.assertRaisesRegex(ValueError,'admission fence'):self.pub.restart_for(self.manifest)
        fence=type('Fence',(),{'root':Path('/'),'stop_then_unlock_database':lambda self:None})()
        # Full service health remains covered by old publisher tests; this scope uses same two consumers.
        with patch.object(self.pub.subprocess,'run') as run,patch.object(self.pub,'rooted') as rooted,patch.object(self.pub,'no_target_link'),patch.object(self.pub.urllib.request,'urlopen') as opened:
            rooted.return_value.read_text.return_value='fixture-control'
            opened.return_value.__enter__.return_value.read.return_value=b'{}'
            opened.return_value.__enter__.return_value.__iter__.return_value=iter(())
            # Range json.load is a distinct health response.
            with patch.object(self.pub.json,'load',return_value={'ok':True}):self.pub.restart_for(self.manifest,fence)
        restarts=[c.args[0] for c in run.call_args_list if c.args[0][:2]==['systemctl','restart']]
        self.assertEqual(restarts,[['systemctl','restart','fs-hermes-fc.service'],['systemctl','restart','fs-business-range.service']])

if __name__=='__main__':unittest.main()
