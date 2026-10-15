from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import importlib.util
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('market_publisher',HERE/'release_navigation.py')
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.stage=Path(self.temp.name)
        self.manifest={'schemaVersion':1,'scope':publisher.HERMES_RESEARCH_SCOPE,'sourceCommit':'a'*40,
            'imageId':'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544',
            'businessWrites':False,'timersChanged':False,'files':[],
            'runtimeRequired':{u:{'ActiveState':'active'} for u in ('fs-business-range.service','fs-hermes-fc.service')}}
        for rel,target in publisher.HERMES_RESEARCH_TARGETS.items():
            p=self.stage/'candidate'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'candidate')
            self.manifest['files'].append({'candidate':rel,'target':target,'sha256':hashlib.sha256(b'candidate').hexdigest(),
                'beforeSha256':None if rel in publisher.HERMES_RESEARCH_NEW else 'b'*64})
        protected=set(publisher.HERMES_TARGETS.values())-set(publisher.HERMES_RESEARCH_TARGETS.values())
        protected|={'/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')}
        protected|={'/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py'}
        protected|={'/opt/fs-boss-workspaces/backend/game_intelligence.py','/opt/fs-hermes-fc/nightly_http.py','/opt/fs-hermes-fc/market_snapshot.py','/opt/fs-hermes-fc/market_snapshot_client.py','/etc/systemd/system/fs-hermes-fc.service.d/install-state-isolation.conf'}
        self.manifest['unchangedRequired']=[{'path':p,'sha256':'c'*64} for p in sorted(protected)]

    def test_exact_scope_valid(self):publisher.validate(self.manifest,self.stage)

    def test_no_extra_or_price_target(self):
        for target in ['/etc/fc27-cloud/fc27.env','/opt/fc27-cloud-browser/price_writer.py']:
            m=deepcopy(self.manifest);m['files'][0]['target']=target
            with self.assertRaises(ValueError):publisher.validate(m,self.stage)

    def test_business_write_or_new_timer_rejected(self):
        for key in ['businessWrites','timersChanged']:
            m=deepcopy(self.manifest);m[key]=True
            with self.assertRaises(ValueError):publisher.validate(m,self.stage)

    def test_old_baseline_or_missing_protection_rejected(self):
        m=deepcopy(self.manifest);m['files'][0]['beforeSha256']=None
        with self.assertRaises(ValueError):publisher.validate(m,self.stage)
        m=deepcopy(self.manifest);m['unchangedRequired']=[]
        with self.assertRaises(ValueError):publisher.validate(m,self.stage)

    def test_changed_candidate_is_rejected(self):
        row=self.manifest['files'][0]
        (self.stage/'candidate'/row['candidate']).write_bytes(b'changed')
        with self.assertRaises(ValueError):publisher.validate(self.manifest,self.stage)

    def test_release_stops_old_admission_holder_before_new_processes(self):
        events=[]
        class Fence:
            def stop_then_unlock_database(self):events.append('old_process_stopped_database_unlocked')
        restart=publisher.restart_for
        with patch.object(publisher,'restart_for',side_effect=lambda m,*a:events.append(m['scope'])):
            restart(self.manifest,Fence())
        self.assertEqual(events,['old_process_stopped_database_unlocked',publisher.HERMES_WORKER_SCOPE,publisher.DEEP_SCOPE])
        m=deepcopy(self.manifest);m.pop('sourceCommit')
        with self.assertRaises(ValueError):publisher.validate(m,self.stage)


if __name__=='__main__':unittest.main()
