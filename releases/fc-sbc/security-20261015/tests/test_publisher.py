import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sbc_publisher', ROOT/'publisher/release_navigation.py')
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)


class Publisher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory()
        cls.stage=Path(cls.directory.name)
        for key in pub.SBC_TARGETS:
            name=Path(key).name
            source=ROOT/('source' if name.endswith('.py') else 'config')/name
            target=cls.stage/'candidate'/key
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def manifest(self):
        protected = {'/opt/fc27-sbc-tool/'+name for name in ('admin_client.py','fetch_sbc.py','fetch_futgg.py','workbook.py','uploader.py','pricing.py','repricer.py','watermark.py','iconfix.py')}
        protected |= {'/opt/fc27-sbc-tool/output/auto_settings.json','/opt/fs-access-policy/access_policy.py','/opt/auth-portal/auth_portal.py','/etc/nginx/conf.d/iggm-web.conf','/var/www/dashboard/fs-home/navigation.js','/var/www/dashboard/modules/sports/index.html','/var/www/dashboard/index.html'}
        stage = self.stage
        return dict(scope=pub.SBC_SCOPE,schemaVersion=1,releaseReady=True,businessWrites=False,automaticWritesEnabled=False,
            files=[dict(candidate=key,target=target,beforeSha256='0'*64,sha256=pub.digest(stage/'candidate'/key)) for key,target in pub.SBC_TARGETS.items()],
            unchangedRequired=[dict(path=path,sha256='0'*64) for path in protected],runtimeRequired={})

    def test_exact_scope_validates(self):
        self.assertEqual(len(pub.validate(self.manifest(),self.stage)), 5)

    def test_other_tool_target_rejected(self):
        manifest=self.manifest()
        manifest['files'][0]['target']='/opt/fc27-cloud-browser/fc27_cloud_api.py'
        with self.assertRaises(ValueError):pub.validate(manifest,self.stage)

    def test_missing_target_rejected(self):
        manifest=self.manifest();manifest['files'].pop()
        with self.assertRaises(ValueError):pub.validate(manifest,self.stage)

    def test_every_dependency_is_required(self):
        for index in range(len(self.manifest()['unchangedRequired'])):
            manifest=self.manifest();manifest['unchangedRequired'].pop(index)
            with self.subTest(index=index),self.assertRaises(ValueError):pub.validate(manifest,self.stage)

    def test_automatic_write_enable_rejected(self):
        manifest=self.manifest();manifest['automaticWritesEnabled']=True
        with self.assertRaises(ValueError):pub.validate(manifest,self.stage)

    def test_payload_hash_drift_rejected(self):
        manifest=self.manifest();manifest['files'][0]['sha256']='f'*64
        with self.assertRaises(ValueError):pub.validate(manifest,self.stage)

    def test_restart_touches_only_sbc_and_nginx(self):
        commands=[]
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch.object(pub.subprocess,'run',side_effect=lambda cmd,**kw:commands.append(cmd)),patch.object(pub,'digest',return_value='0'*64),patch.object(pub.urllib.request,'urlopen',return_value=Response()):
            pub.restart_for(self.manifest())
        self.assertEqual([c for c in commands if c[:2]==['systemctl','restart']], [['systemctl','restart','fc27-sbc-tool.service']])
        self.assertEqual([c for c in commands if c[:2]==['systemctl','reload']], [['systemctl','reload','nginx']])

    def test_only_navigation_addition(self):
        before=json.loads((ROOT/'baseline/navigation.json').read_text(encoding='utf-8'))
        after=json.loads((ROOT/'config/navigation.json').read_text(encoding='utf-8'))
        tool=next(t for t in after['tools'] if t['id']=='fc27-sbc')
        self.assertEqual((tool['section'],tool['category'],tool['path']),('sports','FC','/dashboard/fc27-sbc/'))
        after['tools'].remove(tool)
        next(s for s in after['sections'] if s['id']=='sports')['ids'].remove('fc27-sbc')
        self.assertEqual(after,before)


if __name__=='__main__':unittest.main()
