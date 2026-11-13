import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[4]
spec=importlib.util.spec_from_file_location('prepare_release',ROOT/'tools/prepare_knowledge_release.py')
prepare=importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
spec=importlib.util.spec_from_file_location('release_scope',Path(__file__).resolve().parents[1]/'deploy/release.py')
scope=importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class Release(unittest.TestCase):
    def test_knowledge_only_scope_admits_policy_and_new_immutable_documents_only(self):
        release='fc-reporting-knowledge-20261105-'+('a'*8)
        prefix='/var/lib/fs-hermes-fc/fs/knowledge-releases/'+release+'/'
        value=dict(scope=scope.SCOPE,knowledgeOnly=True,knowledgeRelease=release,sourceCommit='a'*40,
            businessWrites=False,timersChanged=False,files=[
                dict(candidate='runtime/knowledge-load-policy.json',target='/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json'),
                dict(candidate='artifact/index.json',target=prefix+'index.json'),
                dict(candidate='artifact/sources/knowledge/reporting/fc27-monthly/DATA.md',target=prefix+'sources/knowledge/reporting/fc27-monthly/DATA.md')])
        self.assertEqual(len(scope.targets(value)),3)
        for name,target in [('runtime/controller.py','/opt/fs-hermes-fc/controller.py'),
                            ('runtime/business-baseline.md','/opt/fs-hermes-fc/business-baseline.md'),
                            ('artifact/../escape',prefix+'../escape'),
                            ('artifact/other','/etc/systemd/system/fs-hermes-desktop.service')]:
            bad=copy.deepcopy(value);bad['files'].append(dict(candidate=name,target=target))
            with self.assertRaises(ValueError):scope.targets(bad)
        for key,wrong in [('sourceCommit','b'*40),('businessWrites',True),('timersChanged',True)]:
            bad=copy.deepcopy(value);bad[key]=wrong
            with self.assertRaises(ValueError):scope.targets(bad)

    def test_knowledge_only_scope_has_no_service_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage=Path(tmp)/'stage'
            with patch.object(prepare,'git_bytes',side_effect=lambda root,name:(root/name).read_bytes()):
                value=prepare.prepare(ROOT,stage,'a'*40)
            manifest=value['manifest'];release='fc-reporting-knowledge-20261105-'+('a'*8)
            manifest.update(knowledgeOnly=True,knowledgeRelease=release)
            manifest['files']=[r for r in manifest['files'] if r['candidate'].startswith('artifact/')]
            for row in manifest['files']:row['target']=row['target'].replace(scope.RELEASE,release)
            manifest['files'].append(dict(candidate='runtime/knowledge-load-policy.json',target='/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json',sha256='c'*64,beforeSha256='b'*64,owner='0:0',mode='0o644'))
            (stage/'approved-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            with patch.object(scope,'HERE',stage):publisher=scope.load_base()
            with patch('subprocess.run',side_effect=AssertionError('service operation forbidden')):
                publisher.restart_for(manifest)

    def test_shared_admin_es_identity_binds_full_commit_and_cannot_write_baseline(self):
        commit = 'a' * 40
        release = scope.SHARED_ADMIN_ES + '-' + commit
        prefix = '/var/lib/fs-hermes-fc/fs/knowledge-releases/' + release + '/'
        value = dict(scope=scope.SCOPE, knowledgeOnly=True, knowledgeRelease=release, sourceCommit=commit,
                     businessWrites=False, timersChanged=False, files=[
                         dict(candidate='runtime/knowledge-load-policy.json',
                              target='/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json'),
                         dict(candidate='artifact/index.json', target=prefix + 'index.json')])
        self.assertEqual(len(scope.targets(value)), 2)
        for wrong in (release[:-1], scope.SHARED_ADMIN_ES + '-' + 'b' * 40):
            with self.assertRaisesRegex(ValueError, 'knowledge_only_identity_or_authority'):
                scope.targets(dict(value, knowledgeRelease=wrong))
        with self.assertRaisesRegex(ValueError, 'knowledge_immutable_release_boundary'):
            scope.targets(dict(value, files=value['files'] + [
                dict(candidate='runtime/business-baseline.md', target='/opt/fs-hermes-fc/business-baseline.md')]))

    def test_fc_v61_baseline_patch_is_bound_to_existing_target_and_both_hashes(self):
        commit = 'a' * 40
        release = scope.FC_V61 + '-' + commit
        prefix = '/var/lib/fs-hermes-fc/fs/knowledge-releases/' + release + '/'
        row = dict(candidate=scope.BASELINE_CANDIDATE, target=scope.BASELINE_TARGET,
                   beforeSha256='b' * 64, sha256='c' * 64)
        marker = dict(contract=scope.BASELINE_PATCH_CONTRACT, before_sha256='b' * 64, after_sha256='c' * 64)
        value = dict(scope=scope.SCOPE, knowledgeOnly=True, knowledgeRelease=release, sourceCommit=commit,
                     businessWrites=False, timersChanged=False, baselinePatch=marker, files=[
                         dict(candidate='runtime/knowledge-load-policy.json',
                              target='/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json'),
                         dict(candidate='artifact/index.json', target=prefix + 'index.json'), row])
        self.assertEqual(scope.targets(value)[scope.BASELINE_CANDIDATE], scope.BASELINE_TARGET)
        without_marker = dict(value)
        del without_marker['baselinePatch']
        with self.assertRaisesRegex(ValueError, 'knowledge_immutable_release_boundary'):
            scope.targets(without_marker)
        self.assertEqual(len(scope.targets(dict(without_marker, files=value['files'][:2]))), 2)
        for variant, reason in (
            (dict(value, knowledgeOnly=False), 'scope'),
            (dict(value, knowledgeRelease=scope.SHARED_ADMIN_ES + '-' + commit), 'scope'),
            (dict(value, baselinePatch=None), 'contract'),
            (dict(value, baselinePatch=dict(marker, extra=True)), 'contract'),
            (dict(value, baselinePatch=dict(marker, before_sha256='c' * 64)), 'hash'),
            (dict(value, baselinePatch=dict(marker, before_sha256=42)), 'hash'),
            (dict(value, files=value['files'][:2]), 'binding'),
            (dict(value, files=value['files'] + [row]), 'binding'),
            (dict(value, files=value['files'][:2] + [dict(row, target='/opt/fs-hermes-fc/controller.py')]), 'binding'),
            (dict(value, files=value['files'][:2] + [dict(row, beforeSha256=None)]), 'binding'),
            (dict(value, files=value['files'][:2] + [dict(row, sha256='d' * 64)]), 'binding'),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, 'knowledge_baseline_patch_' + reason):
                scope.targets(variant)

    def test_existing_publisher_used_and_immutable_package_can_be_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage=Path(tmp)/'stage'
            with patch.object(prepare,'git_bytes',side_effect=lambda root,name:(root/name).read_bytes()):
                value=prepare.prepare(ROOT,stage,'a'*40)
            self.assertFalse(value['manifest']['releaseReady'])
            manifest=value['manifest']
            self.assertFalse(manifest['businessWrites'])
            self.assertFalse(manifest['timersChanged'])
            adapter=(stage/'release_adapter_base.py').read_bytes()
            self.assertEqual(hashlib.sha256(adapter).hexdigest(),'65794d515f78826e5a23c4c88966c603e1a46dd3c977c3dd0956bc770a581344')
            self.assertEqual(hashlib.sha256((stage/'release_navigation_base.py').read_bytes()).hexdigest(),'1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de')
            import types
            original=types.ModuleType('offline_original_publisher')
            exec(compile((stage/'release_navigation_base.py').read_text(),str(stage/'release_navigation_base.py'),'exec'),original.__dict__)
            protected=set(original.HERMES_TARGETS.values()) | {'/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')}
            protected.update(['/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py'])
            protected-=set(scope.targets(manifest).values())
            manifest['unchangedRequired']=[dict(path=p,sha256='f'*64) for p in sorted(protected)]
            manifest['runtimeRequired']={n:{'ActiveState':'active'} for n in ('fs-hermes-fc.service','fs-business-range.service')}
            manifest['imageId']='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'
            for row in manifest['files']:
                if row['candidate'] in ('runtime/controller.py','runtime/business_context.py'):
                    row['beforeSha256']='a'*64
            (stage/'approved-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            with patch.object(scope,'HERE',stage):
                publisher=scope.load_base()
            self.assertEqual(len(publisher.validate(manifest,stage)),len(manifest['files']))
            from types import SimpleNamespace
            parent=Path('/var/lib/fs-hermes-fc')
            info=SimpleNamespace(st_uid=0,st_gid=9876,st_mode=0o40750)
            self.assertTrue(publisher.approved_daily_group(manifest,Path('/'),parent,info))
            self.assertFalse(publisher.approved_daily_group(manifest,Path('/'),parent/'profile',info))
            self.assertFalse(publisher.approved_daily_group(dict(manifest,scope='other'),Path('/'),parent,info))
            for wrong in (dict(st_uid=9876),dict(st_gid=9875),dict(st_mode=0o40775),dict(st_mode=0o42750)):
                values=vars(info).copy();values.update(wrong)
                self.assertFalse(publisher.approved_daily_group(manifest,Path('/'),parent,SimpleNamespace(**values)))
            docs_only=copy.deepcopy(manifest)
            for row in docs_only['files']:
                if row['candidate'] in scope.RUNTIME:
                    row['beforeSha256']=row['sha256']
            (stage/'approved-manifest.json').write_text(json.dumps(docs_only),encoding='utf-8')
            with patch.object(scope,'HERE',stage):
                existing=scope.load_base()
            self.assertEqual(len(existing.validate(docs_only,stage)),len(docs_only['files']))
            with patch('subprocess.run') as service:
                publisher.restart_for(docs_only)
                service.assert_not_called()
            fs=Path(tmp)/'fs'
            import shutil
            shutil.copytree(stage/'candidate/artifact',fs/'knowledge-releases'/scope.RELEASE)
            from knowledge_catalog import select
            p=fs/'knowledge-releases'/scope.RELEASE/'index.json'
            value=select(fs,'knowledge-releases/'+scope.RELEASE+'/index.json',hashlib.sha256(p.read_bytes()).hexdigest(),['FC27'],['fc.marketing.attribution'])
            self.assertIn('归FC项目',value['entries'][0]['content'])
            with self.assertRaisesRegex(ValueError,'already_exists'):
                prepare.prepare(ROOT,stage,'a'*40)

    def test_scope_cannot_touch_pricing_teaching_policy_or_schedule(self):
        rows=[dict(candidate=n,target=p) for n,p in scope.RUNTIME.items()]
        rows.append(dict(candidate='artifact/index.json',target=scope.PREFIX+'index.json'))
        value={'files':rows}
        scope.targets(value)
        for target in ('/opt/fs-hermes-fc/business-baseline.md','/var/lib/fs-hermes-fc/fs/nightly-schedule.json','/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json','/etc/systemd/system/anything.timer'):
            bad=copy.deepcopy(value)
            bad['files'].append(dict(candidate='artifact/escape',target=target))
            with self.assertRaisesRegex(ValueError,'boundary'):
                scope.targets(bad)
