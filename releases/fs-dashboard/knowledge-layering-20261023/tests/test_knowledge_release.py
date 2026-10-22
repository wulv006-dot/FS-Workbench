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
