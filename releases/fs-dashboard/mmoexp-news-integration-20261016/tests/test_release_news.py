from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import importlib.util
import io
import sqlite3
import unittest
from unittest.mock import patch


spec=importlib.util.spec_from_file_location('news_publisher',Path(__file__).resolve().parents[1]/'release_navigation.py')
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)


class ReleaseNewsTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.stage=Path(self.temp.name)
        self.manifest={'schemaVersion':1,'scope':publisher.NEWS_SCOPE,'sourceCommit':'a'*40,
            'imageId':'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544',
            'businessWrites':False,'timersChanged':False,'files':[],
            'runtimeRequired':{u:{'ActiveState':'active'} for u in ('fs-business-range.service','fs-hermes-fc.service')}}
        self.manifest['runtimeRequired']['fs-boss-game-monitor.service']={'ActiveState':'inactive'}
        for rel,target in publisher.NEWS_TARGETS.items():
            path=self.stage/'candidate'/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'candidate')
            self.manifest['files'].append({'candidate':rel,'target':target,'sha256':hashlib.sha256(b'candidate').hexdigest(),
                'beforeSha256':publisher.NEWS_BASELINES[rel]})
        protected=set(publisher.HERMES_TARGETS.values())-set(publisher.NEWS_TARGETS.values())
        protected|={'/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')}
        protected|={'/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py'}
        protected|={'/etc/systemd/system/fs-boss-game-monitor.service','/etc/systemd/system/fs-boss-game-monitor.timer','/opt/fs-hermes-fc/nightly_http.py','/opt/fs-hermes-fc/market_snapshot.py','/opt/fs-hermes-fc/market_snapshot_client.py','/etc/systemd/system/fs-hermes-fc.service.d/install-state-isolation.conf'}
        self.manifest['unchangedRequired']=[{'path':p,'sha256':'c'*64} for p in sorted(protected)]

    def test_exact_allowlist_and_new_file(self):
        self.assertEqual(len(publisher.validate(self.manifest,self.stage)),4)
        self.assertEqual(publisher.NEWS_NEW,{'source/mmoexp_news.py'})
        self.assertNotIn(publisher.NEWS_TARGETS['source/game_intelligence.py'],{r['path'] for r in self.manifest['unchangedRequired']})

    def test_existing_baselines_pinned_and_new_target_absent(self):
        for row in self.manifest['files']:
            for baseline in (None,'b'*64):
                if baseline==row['beforeSha256']:continue
                manifest=deepcopy(self.manifest)
                next(r for r in manifest['files'] if r['candidate']==row['candidate'])['beforeSha256']=baseline
                with self.subTest(candidate=row['candidate'],baseline=baseline),self.assertRaises(ValueError):
                    publisher.validate(manifest,self.stage)

    def test_extra_missing_duplicate_and_unapproved_target_rejected(self):
        for mode in ('extra','missing','duplicate','target','escape'):
            manifest=deepcopy(self.manifest)
            if mode=='extra':manifest['files'].append(dict(manifest['files'][0],candidate='source/extra.py'))
            if mode=='missing':manifest['files'].pop()
            if mode=='duplicate':manifest['files'].append(manifest['files'][0])
            if mode=='target':manifest['files'][0]['target']='/opt/fc27-cloud-browser/price_writer.py'
            if mode=='escape':manifest['files'][0]['candidate']='../game_intelligence.py'
            with self.subTest(mode=mode),self.assertRaises(ValueError):publisher.validate(manifest,self.stage)

    def test_only_news_scope_supported(self):
        for scope in (None,'mmoexp-news-integration-20261017','hermes-fc-report-import-20261015',publisher.DEEP_SCOPE):
            manifest=dict(self.manifest,scope=scope)
            with self.subTest(scope=scope),self.assertRaises(ValueError):publisher.validate(manifest,self.stage)

    def test_protection_cannot_omit_dependency_or_include_target(self):
        for row in self.manifest['unchangedRequired']:
            manifest=deepcopy(self.manifest);manifest['unchangedRequired'].remove(row)
            with self.subTest(path=row['path']),self.assertRaises(ValueError):publisher.validate(manifest,self.stage)
        manifest=deepcopy(self.manifest)
        manifest['unchangedRequired'].append({'path':publisher.NEWS_TARGETS['source/game_intelligence.py'],'sha256':'c'*64})
        with self.assertRaises(ValueError):publisher.validate(manifest,self.stage)

    def test_write_schedule_runtime_and_source_boundaries(self):
        for key,value in [('businessWrites',True),('timersChanged',True),('sourceCommit',''),('imageId','sha256:'+'b'*64)]:
            manifest=deepcopy(self.manifest);manifest[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):publisher.validate(manifest,self.stage)
        for unit in self.manifest['runtimeRequired']:
            manifest=deepcopy(self.manifest);manifest['runtimeRequired'].pop(unit)
            with self.subTest(unit=unit),self.assertRaises(ValueError):publisher.validate(manifest,self.stage)

    def test_staged_source_drift_rejected(self):
        (self.stage/'candidate/source/mmoexp_news.py').write_bytes(b'changed')
        with self.assertRaises(ValueError):publisher.validate(self.manifest,self.stage)

    def test_restart_uses_admission_fence_then_only_original_services(self):
        events=[]
        class Fence:
            def stop_then_unlock_database(self):events.append('old_process_stopped_database_unlocked')
        restart=publisher.restart_for
        with patch.object(publisher,'restart_for',side_effect=lambda m,*a:events.append(m['scope'])):
            restart(self.manifest,Fence())
        self.assertEqual(events,['old_process_stopped_database_unlocked',publisher.HERMES_WORKER_SCOPE,publisher.DEEP_SCOPE])
        with self.assertRaises(ValueError):restart(self.manifest)

    def test_restart_actual_service_allowlist(self):
        key=self.stage/'run/fs-hermes-fc/api-key';key.parent.mkdir(parents=True);key.write_text('test-only')
        class Fence:
            root=self.stage
            def stop_then_unlock_database(self):pass
        with patch.object(publisher.subprocess,'run') as command,patch.object(publisher.urllib.request,'urlopen',side_effect=lambda *a,**k:io.BytesIO(b'{"ok":true}')):
            publisher.restart_for(self.manifest,Fence())
        self.assertEqual([call.args[0] for call in command.call_args_list],[
            ['systemctl','restart','fs-hermes-fc.service'],['systemctl','is-active','--quiet','fs-hermes-fc.service'],
            ['systemctl','restart','fs-business-range.service'],['systemctl','is-active','--quiet','fs-business-range.service']])

    def test_active_or_unknown_hermes_task_blocks_release(self):
        database=self.stage/'var/lib/fs-hermes-fc/fs/tasks.sqlite3';database.parent.mkdir(parents=True)
        with sqlite3.connect(database) as db:db.execute('CREATE TABLE requests(state TEXT)')
        db.close()
        publisher.hermes_quiescent(self.stage)
        for state in ('PREPARING','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','NEEDS_RECONCILE'):
            with sqlite3.connect(database) as db:
                db.execute('DELETE FROM requests');db.execute('INSERT INTO requests VALUES (?)',(state,))
            db.close()
            with self.subTest(state=state),self.assertRaises(ValueError):publisher.hermes_quiescent(self.stage)


if __name__=='__main__':unittest.main()
