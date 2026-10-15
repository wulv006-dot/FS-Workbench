import ast
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import Mock,patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('report_quality_publisher',HERE/'publisher/release_navigation.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


class ReleaseQuality(unittest.TestCase):
    def stage(self,path):
        baseline={x['name']:x['sha256'] for x in json.loads((HERE/'BASELINE.json').read_text(encoding='utf-8'))['files']}
        rows=[]
        for rel,target in release.HERMES_QUALITY_TARGETS.items():
            name=rel.removeprefix('report-quality/');src=HERE/'candidate'/name;dst=path/'candidate'/rel
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
            rows.append({'candidate':rel,'target':target,'sha256':release.digest(dst),'beforeSha256':baseline.get(name)})
        required={'/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')}
        required|={'/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py'}
        required|=(set(release.HERMES_TARGETS.values())|set(release.HERMES_CAPABILITY_TARGETS.values())|release.CAP_PROTECTED_SESSION|set(release.HERMES_DIRECT_TARGETS.values()))-set(release.HERMES_QUALITY_TARGETS.values())
        return {'schemaVersion':1,'scope':release.HERMES_QUALITY_SCOPE,'files':rows,'businessWrites':False,'timersChanged':False,
                'unchangedRequired':[{'path':p,'sha256':'a'*64} for p in sorted(required)],
                'runtimeRequired':{'fs-business-range.service':{'ActiveState':'active'},'fs-hermes-fc.service':{'ActiveState':'active'}},
                'imageId':'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'}

    def test_exact_report_only_scope(self):
        targets=release.expected_files({'scope':release.HERMES_QUALITY_SCOPE})
        self.assertEqual(len(targets),10)
        self.assertTrue(all(release.target_for(x).startswith('/opt/fs-hermes-fc/') for x in targets))
        self.assertFalse(any('index.html' in x or 'secret' in x or 'runtime-config' in x for x in targets))

    def test_merged_desktop_and_recovery_scopes_remain_available(self):
        for scope,targets in ((release.HERMES_DESKTOP_SCOPE,release.HERMES_DESKTOP_TARGETS),(release.RECOVERY_SCOPE,release.RECOVERY_TARGETS)):
            self.assertEqual(release.expected_files({'scope':scope}),set(targets))
            for name,target in targets.items():self.assertEqual(release.target_for(name),target)
        self.assertIn('HERMES_DESKTOP_SCOPE',(HERE/'publisher/release_navigation.py').read_text(encoding='utf-8'))

    def test_valid_payload_and_existing_new_baselines(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=self.stage(root)
            self.assertEqual(len(release.validate(m,root)),10)
            self.assertEqual({r['candidate'] for r in m['files'] if r['beforeSha256'] is None},release.HERMES_QUALITY_NEW)

    def test_extra_missing_or_redirected_target_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=self.stage(root)
            for mutate in ['missing','extra','redirect']:
                bad=copy.deepcopy(m)
                if mutate=='missing':bad['files'].pop()
                elif mutate=='extra':bad['files'].append(dict(bad['files'][0],candidate='unapproved.py'))
                else:bad['files'][0]['target']='/var/www/dashboard/fs-home/index.html'
                with self.assertRaises(ValueError):release.validate(bad,root)

    def test_existing_target_cannot_be_declared_new(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=self.stage(root);row=next(r for r in m['files'] if r['beforeSha256']);row['beforeSha256']=None
            with self.assertRaisesRegex(ValueError,'baselines'):release.validate(m,root)

    def test_new_target_cannot_overwrite_existing_object(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=self.stage(root);row=next(r for r in m['files'] if r['beforeSha256'] is None);row['beforeSha256']='0'*64
            with self.assertRaisesRegex(ValueError,'baselines'):release.validate(m,root)

    def test_payload_drift_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=self.stage(root);(root/'candidate'/m['files'][0]['candidate']).write_text('changed')
            with self.assertRaisesRegex(ValueError,'SHA'):release.validate(m,root)

    def test_active_or_unreconciled_task_blocks_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'var/lib/fs-hermes-fc/fs/tasks.sqlite3';p.parent.mkdir(parents=True)
            with closing(sqlite3.connect(p)) as db:
                with db:db.execute('CREATE TABLE requests(state TEXT)');db.execute("INSERT INTO requests VALUES('RUNNING')")
            with self.assertRaisesRegex(ValueError,'active or unreconciled'):release.hermes_quiescent(root)
            with closing(sqlite3.connect(p)) as db:
                with db:db.execute("UPDATE requests SET state='NEEDS_RECONCILE'")
            with self.assertRaisesRegex(ValueError,'active or unreconciled'):release.hermes_quiescent(root)
            with closing(sqlite3.connect(p)) as db:
                with db:db.execute("UPDATE requests SET state='COMPLETED'")
            release.hermes_quiescent(root)

    def test_restart_uses_existing_worker_and_range_paths(self):
        original=release.restart_for;fence=Mock()
        with patch.object(release,'restart_for') as nested:
            original({'scope':release.HERMES_QUALITY_SCOPE},fence)
        fence.stop_then_unlock_database.assert_called_once()
        self.assertEqual([x.args[0]['scope'] for x in nested.call_args_list],[release.HERMES_WORKER_SCOPE,release.DEEP_SCOPE])

    def test_no_model_or_schedule_boundary_expansion(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=self.stage(root)
            for key in ['businessWrites','timersChanged']:
                bad=copy.deepcopy(m);bad[key]=True
                with self.assertRaisesRegex(ValueError,'boundary'):release.validate(bad,root)


if __name__=='__main__':unittest.main(verbosity=2)
