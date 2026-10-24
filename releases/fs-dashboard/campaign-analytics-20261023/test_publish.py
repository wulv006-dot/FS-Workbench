import hashlib, json, tempfile, unittest
from pathlib import Path
import publish as p
import importlib.util
from unittest.mock import patch

class Release(unittest.TestCase):
 def test_navigation_registry_and_static_submenus_share_order(self):
  path=Path(__file__).parent/'navigation/prepare_release.py';spec=importlib.util.spec_from_file_location('activity_navigation',path);nav=importlib.util.module_from_spec(spec);spec.loader.exec_module(nav)
  original={'sections':[{'id':'analytics','ids':['data','campaign-analytics']},{'id':'sports','ids':['coins']}],'tools':[{'id':'campaign-analytics','section':'analytics'}]}
  updated=nav.update_registry(original)
  self.assertEqual([s['id'] for s in updated['sections']],['analytics','activities','sports'])
  self.assertEqual(updated['sections'][0]['ids'],['data'])
  self.assertEqual(original['sections'][0]['ids'],['data','campaign-analytics'])
  section=updated['sections'][1];tools={t['id']:dict(t,path=t.get('path','/dashboard/analytics/'),label=t.get('label','活动转化分析')) for t in updated['tools']}
  text=nav.group(section,tools)
  self.assertLess(text.index('活动转化分析'),text.index('商品编辑与预览'))
  self.assertEqual(text.count('class="hn-tool"'),2)
 def test_frozen_navigation_sources_share_registry(self):
  import re
  root=Path(__file__).parent/'navigation/source';registry=json.loads((root/'navigation.json').read_text(encoding='utf-8'))
  sections={s['id']:s for s in registry['sections']};tools={t['id']:t for t in registry['tools']}
  expected=[tools[k]['label'] for k in sections['analytics']['ids']]
  pages=list(root.glob('page-*.html'));self.assertEqual(len(pages),10)
  for page in pages:
   nav=re.search(r'<nav id="hubNav".*?</nav>',page.read_text(encoding='utf-8'),re.S)[0]
   self.assertLess(nav.index('主站活动区'),nav.index('球类工作区'))
   group=re.search(r'<section class="hn-group"><a class="hn-heading" href="/dashboard/modules/analytics/".*?</section>',nav,re.S)[0]
   self.assertEqual(re.findall(r'class="hn-tool"[^>]*>(.*?)</a>',group),expected,page.name)
 def test_runtime_unit_uses_observed_legacy_systemd_and_existing_identity(self):
  text=(Path(__file__).parent/'fs-campaign-runtime.service').read_text(encoding='utf-8')
  for required in ['User=nobody','Group=nobody','PermissionsStartOnly=true','ExecStart=/usr/local/bin/node ', 'ExecStartPre=/usr/bin/install -d -m0700 -o nobody -g nobody /var/lib/fs-campaign-runtime','ProtectSystem=full','ReadWriteDirectories=/var/lib/fs-campaign-runtime']:
   self.assertIn(required,text)
  for unsupported in ['StateDirectory=','ReadWritePaths=','ProtectSystem=strict','www-data']:
   self.assertNotIn(unsupported,text)
 def test_target_boundary(self):
  self.assertEqual(p.target('app/analytics/production-server.mjs'),'/opt/fs-campaign-dashboard/analytics/production-server.mjs')
  self.assertEqual(p.target('fs-campaign-runtime.service'),'/etc/systemd/system/fs-campaign-runtime.service')
  self.assertEqual(p.target('runtime.env'),'/etc/fs-campaign-runtime.env')
  self.assertEqual(p.target('backend/campaign_backend/coupon_draft.py'),'/opt/fs-campaign-dashboard/backend/campaign_backend/coupon_draft.py')
  self.assertEqual(p.target('app/seasonal/assets/hero.jpg'),'/opt/fs-campaign-dashboard/seasonal/assets/hero.jpg')
  for path in ['app/../../etc/passwd','app/..\\etc/file.json','app//index.html','app/./index.html','secret.pem','app/data.db','other/index.html','other.service','etc/runtime.env','backend/secret.py','backend/campaign_backend/../../etc/passwd','backend/tests/test_ledger.py']:
   with self.assertRaises(ValueError):p.target(path)
 def test_payload_change_and_rollback_binding(self):
  with tempfile.TemporaryDirectory() as tmp:
   stage=Path(tmp);rows=[]
   for name in list(p.REQUIRED_SPECIAL)+['app/index.html']:
    file=stage/'candidate'/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('fixture')
    rows.append(dict(candidate=name,target=p.target(name),sha256=hashlib.sha256(file.read_bytes()).hexdigest(),beforeSha256=None))
   manifest=dict(schemaVersion=1,scope=p.SCOPE,targets={r['candidate']:r['target'] for r in rows},files=rows)
   self.assertEqual(len(p.validate(manifest,stage)),5)
   raw=json.dumps(manifest).encode();(stage/'approved-manifest.json').write_bytes(raw);sha=hashlib.sha256(raw).hexdigest()
   p.m.rollback_credentials(stage,dict(manifest=manifest,files=rows,approvedManifestSha256=sha),sha)
   (stage/'candidate/app/index.html').write_text('changed')
   with self.assertRaises(ValueError):p.validate(manifest,stage)
 def test_pinned_base_and_optional_runtime_pair(self):
  self.assertEqual(hashlib.sha256(p.base.read_bytes()).hexdigest(),p.BASE_SHA)
  with tempfile.TemporaryDirectory() as tmp:
   stage=Path(tmp);rows=[]
   for name in list(p.REQUIRED_SPECIAL)+['fs-campaign-runtime.service','runtime.env']:
    file=stage/'candidate'/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('fixture')
    rows.append(dict(candidate=name,target=p.target(name),sha256=hashlib.sha256(file.read_bytes()).hexdigest(),beforeSha256=None))
   manifest=dict(schemaVersion=1,scope=p.SCOPE,targets={r['candidate']:r['target'] for r in rows},files=rows)
   self.assertEqual(len(p.validate(manifest,stage)),6)
   manifest['files']=rows[:-1];manifest['targets'].pop('runtime.env')
   with self.assertRaisesRegex(ValueError,'staged together'):p.validate(manifest,stage)
 def test_restart_remains_project_scoped(self):
  with patch.object(p.subprocess,'run') as run,patch.object(p.Path,'exists',return_value=True):
   p.restart({'files':[]})
  commands=[call.args[0] for call in run.call_args_list]
  units={arg for command in commands for arg in command if arg.endswith('.service')}
  self.assertEqual(units,{'fs-campaign-dashboard.service','fs-campaign-runtime.service'})
if __name__=='__main__':unittest.main()
