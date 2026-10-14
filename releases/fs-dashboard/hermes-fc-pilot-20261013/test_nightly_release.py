import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_release


class NightlyReleaseTests(unittest.TestCase):
    def setUp(self):
        fixture=test_release.ReleaseTests('test_exact_scope_keeps_other_publishers_unchanged')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.pub=fixture.publisher;self.stage=fixture.stage;self.root=fixture.root
        here=Path(__file__).parent
        repo=here.parents[2]
        boss=repo/'releases/fs-dashboard/boss-workspaces-20261013'
        marketing=repo/'mmoexp_google_data/deployment'
        if not boss.exists():boss=here.parent/'boss';marketing=here.parent/'marketing/deployment'
        rows=[]
        for rel,target in self.pub.HERMES_NIGHT_TARGETS.items():
            path=self.stage/'candidate'/rel;path.parent.mkdir(parents=True,exist_ok=True)
            if rel=='hermes/nightly/nightly-schedule.json':data=json.dumps({'contract':'fs-hermes-nightly-v1','enabled':True,'owner':'wulv','timezone':'Asia/Shanghai'}).encode()
            elif rel.startswith('hermes/runtime/'):data=(here/rel.removeprefix('hermes/runtime/')).read_bytes()
            elif rel=='hermes/index.html':data=(here/'index.html').read_bytes()
            elif rel.endswith('server_run_integrated.py') or 'marketing-daily.' in rel:data=(marketing/Path(rel).name).read_bytes()
            else:data=(boss/('deploy' if rel.endswith('.timer') else 'backend')/Path(rel).name).read_bytes()
            path.write_bytes(data)
            new=rel in {'hermes/runtime/nightly.py','hermes/runtime/nightly_http.py','hermes/nightly/nightly_http.py','hermes/nightly/nightly-schedule.json'} or '/reviewed/' in rel or 'reviewed-adaptation.md' in rel
            rows.append({'candidate':rel,'target':target,'sha256':hashlib.sha256(data).hexdigest(),'beforeSha256':None if new else 'b'*64})
        targets=set(self.pub.HERMES_NIGHT_TARGETS.values())
        protected=(set(self.pub.HERMES_TARGETS.values())|set(self.pub.HERMES_CAPABILITY_TARGETS.values())|self.pub.CAP_PROTECTED_SESSION|{r['path'] for r in fixture.manifest['unchangedRequired']}|set(self.pub.HERMES_DIRECT_TARGETS.values()))-targets
        self.value=dict(fixture.manifest,scope=self.pub.HERMES_NIGHT_SCOPE,files=rows,unchangedRequired=[{'path':p,'sha256':'c'*64} for p in protected],
            timersChanged=True,timezone='Asia/Shanghai',rollbackSchedulePolicy='pause_three_timers_without_replay',
            runtimeRequired={**{u:{'ActiveState':'active'} for u in ('fs-business-range.service','fs-hermes-fc.service','fc27-p2pah-session.service')},
                **{u:{'ActiveState':'inactive'} for u in ('fs-boss-game-monitor.service','fs-boss-management.service','mmoexp-marketing-daily.service')}})

    def test_exact_scope_idle_cutoff_and_paired_transport(self):
        self.assertEqual(len(self.pub.validate(self.value,self.stage)),39)
        for mutation in ('timer','rollback','idle','baseline','paired'):
            value=json.loads(json.dumps(self.value))
            if mutation=='rollback':value['rollbackSchedulePolicy']='replay'
            elif mutation=='idle':value['runtimeRequired']['mmoexp-marketing-daily.service']['ActiveState']='active'
            elif mutation=='baseline':next(r for r in value['files'] if r['candidate']=='hermes/runtime/controller.py')['beforeSha256']=None
            else:
                rel='hermes/nightly/fs-boss-game-monitor.timer' if mutation=='timer' else 'hermes/nightly/nightly_http.py'
                p=self.stage/'candidate'/rel;data=p.read_bytes();p.write_bytes(data+b'\nPersistent=true\n')
                next(r for r in value['files'] if r['candidate']==rel)['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):self.pub.validate(value,self.stage)
            if mutation in ('timer','paired'):p.write_bytes(data)

    def test_rollback_pauses_three_timers_and_restart_uses_original_fence(self):
        events=[]
        class Fence:
            root=self.root
            def stop_then_unlock_database(self):events.append('fs_stopped')
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'{"ok":true}'
        key=self.root/'run/fs-hermes-fc/api-key';key.parent.mkdir(parents=True);key.write_text('synthetic-control-only')
        original=Path.is_file
        def is_file(p):return False if str(p)=='/var/lib/fs-hermes-fc/fs/nightly-schedule.json' else original(p)
        with patch.object(self.pub.subprocess,'run',side_effect=lambda a,**kw:events.append(a)),patch.object(self.pub.urllib.request,'urlopen',return_value=Response()),patch.object(self.pub.Path,'is_file',is_file):
            self.pub.restart_for(self.value,Fence())
        for u in self.pub.NIGHT_TIMERS:self.assertIn(['systemctl','disable','--now',u],events)
        self.assertIn(['systemctl','restart','fs-hermes-fc.service'],events)
        self.assertIn(['systemctl','restart','fs-business-range.service'],events)
        self.assertNotIn(['systemctl','restart','fc27-p2pah-session.service'],events)


if __name__=='__main__':unittest.main()
