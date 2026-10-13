import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.stage=Path(self.tmp.name)/'stage';self.root=Path(self.tmp.name)/'root';self.stage.mkdir();self.root.mkdir()
        path=Path(__file__).parent/'shared_candidate/release_navigation.py'
        spec=importlib.util.spec_from_file_location('hermes_publisher',path);self.publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.publisher)
        files=[]
        for rel,target in self.publisher.HERMES_TARGETS.items():
            p=self.stage/'candidate'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'reviewed fixture')
            before=None
            if rel.startswith('hermes/shared/'):
                old=self.root/target.lstrip('/');old.parent.mkdir(parents=True,exist_ok=True);old.write_bytes(b'old fixture');before=hashlib.sha256(b'old fixture').hexdigest()
            files.append({'candidate':rel,'target':target,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'beforeSha256':before})
        protected=['/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')]
        protected+=['/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py']
        self.manifest={'schemaVersion':1,'scope':self.publisher.HERMES_SCOPE,'releaseReady':True,'files':files,
            'unchangedRequired':[{'path':p,'sha256':'a'*64} for p in protected],'runtimeRequired':{'fs-business-range.service':{'ActiveState':'active'}},
            'imageId':'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544','businessWrites':False,'timersChanged':False}

    def test_exact_scope_keeps_other_publishers_unchanged(self):
        self.assertEqual(len(self.publisher.validate(self.manifest,self.stage)),34)
        self.assertEqual(self.publisher.expected_files({'scope':self.publisher.DEEP_SCOPE}),set(self.publisher.DEEP_TARGETS))
        with self.assertRaises(ValueError):self.publisher.target_for('hermes/shared/boss_insights.py')

    def test_hash_target_baseline_and_consumer_omissions_refused(self):
        for change in ('hash','target','baseline','protected','scope'):
            value=json.loads(json.dumps(self.manifest))
            if change=='hash':value['files'][0]['sha256']='b'*64
            if change=='target':value['files'][0]['target']='/etc/passwd'
            if change=='baseline':value['files'][0]['beforeSha256']=None
            if change=='protected':value['unchangedRequired']=[r for r in value['unchangedRequired'] if not r['path'].endswith('boss_insights.py')]
            if change=='scope':value['files'].pop()
            with self.assertRaises(ValueError):self.publisher.validate(value,self.stage)

    def test_uses_original_locks_and_active_report_guard(self):
        import inspect
        source=inspect.getsource(self.publisher.apply)
        self.assertIn('with locks(root),live_lock(manifest,root),model_release_lock(manifest,root)',source)
        self.assertIn('target drift before replacement',source)
        self.assertIn('rollback_journal(backup,journal,root)',source)

    def test_uid_firewall_policy_never_exposes_other_service_or_key(self):
        import network_guard
        self.assertEqual(network_guard.UID,9876)
        self.assertEqual([r[r.index('--dport')+1] for r in network_guard.rules('iptables') if '--dport' in r],['8940','8941'])
        self.assertEqual(network_guard.rules('ip6tables'),[['-j','REJECT']])
        unit=(Path(__file__).parent/'fs-hermes-fc.service').read_text('utf-8')
        self.assertIn('--user 9876:9876',unit);self.assertIn('--read-only',unit)
        for denied in ('FS_DAILY_MODEL_KEY_FILE','docker.sock','/var/lib/fs-business-ranges','DEEPSEEK_API_KEY'):self.assertNotIn(denied,unit)


if __name__=='__main__':unittest.main()
