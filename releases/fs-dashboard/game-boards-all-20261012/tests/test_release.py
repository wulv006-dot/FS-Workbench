"""Game-only release admission and image/restart wiring; no production mutations."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('game_release',ROOT/'deploy/release_navigation.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


class Release(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.stage=Path(self.temp.name)
        self.manifest={'schemaVersion':1,'scope':release.GAMES_SCOPE,'releaseReady':False,
            'files':[],'unchangedRequired':[{'path':'/var/www/dashboard/index.html','sha256':'a'*64}]}
        for rel,target in release.GAMES_TARGETS.items():
            path=self.stage/'candidate'/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'candidate')
            self.manifest['files'].append({'candidate':rel,'target':target,'beforeSha256':'b'*64,'sha256':hashlib.sha256(b'candidate').hexdigest()})

    def tearDown(self):self.temp.cleanup()

    def test_exact_existing_two_file_scope(self):
        self.assertEqual(len(release.validate(self.manifest,self.stage)),2)
        for change in ('extra','missing','wrong-target','missing-baseline','self-protection'):
            with self.subTest(change=change):
                m=copy.deepcopy(self.manifest)
                if change=='extra':m['files'].append(copy.deepcopy(m['files'][0]))
                elif change=='missing':m['files'].pop()
                elif change=='wrong-target':m['files'][0]['target']='/etc/fc27-cloud/fc27.env'
                elif change=='missing-baseline':m['files'][0]['beforeSha256']=None
                else:m['unchangedRequired'].append({'path':m['files'][0]['target'],'sha256':'b'*64})
                with self.assertRaises(ValueError):release.validate(m,self.stage)

    def test_changed_staging_and_unapproved_apply_are_rejected(self):
        (self.stage/'candidate'/self.manifest['files'][0]['candidate']).write_bytes(b'drift')
        with self.assertRaises(ValueError):release.validate(self.manifest,self.stage)
        raw=json.dumps(self.manifest).encode()
        with patch.object(release,'locks',side_effect=AssertionError('must reject before writes')):
            with self.assertRaises(ValueError):release.apply(self.manifest,self.stage,hashlib.sha256(raw).hexdigest(),raw,'nav-20261012T000000Z')

    def test_rebuild_is_offline_and_restarts_only_existing_summary_consumers(self):
        self.manifest['files'][1]['sha256']='c'*64
        self.manifest['unchangedRequired'] += [{'path':'/opt/fc27-cloud/marketing-session-20261009/'+n,'sha256':'c'*64} for n in ('p2pah_session_service.py','supplement_fields.py')]
        images='\n'.join('c'*64+'  /usr/local/bin/'+n for n in ('p2pah_session_service.py','admin_summary.py','supplement_fields.py'))
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'{"ready":true,"ok":true}'
        with patch.object(release,'digest',return_value='c'*64),patch.object(release.subprocess,'run') as run,patch.object(release.subprocess,'check_output',return_value=images),patch.object(release.urllib.request,'urlopen',return_value=Response()):
            release.restart_for(self.manifest)
        commands=[c.args[0] for c in run.call_args_list]
        self.assertIn(['systemctl','restart','fc27-p2pah-session.service'],commands)
        self.assertIn(['systemctl','restart','fs-business-range.service'],commands)
        self.assertEqual([c for c in commands if c[:2]==['systemctl','restart']],[['systemctl','restart','fc27-p2pah-session.service'],['systemctl','restart','fs-business-range.service']])
        self.assertIn('--pull=false',commands[0]);self.assertIn('none',commands[0])

    def test_image_readback_failure_stops_before_restart(self):
        self.manifest['files'][1]['sha256']='c'*64
        self.manifest['unchangedRequired'] += [{'path':'/opt/fc27-cloud/marketing-session-20261009/'+n,'sha256':'c'*64} for n in ('p2pah_session_service.py','supplement_fields.py')]
        with patch.object(release,'digest',return_value='c'*64),patch.object(release.subprocess,'run') as run,patch.object(release.subprocess,'check_output',return_value='d'*64+' /usr/local/bin/admin_summary.py'):
            with self.assertRaises(ValueError):release.restart_for(self.manifest)
        self.assertEqual(len(run.call_args_list),1)


if __name__=='__main__':unittest.main()
