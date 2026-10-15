import unittest,sys,json,hashlib,importlib.util,re,tempfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];D=ROOT/'releases/fs-dashboard/ui-system-20261015';OLD=ROOT/'releases/fs-dashboard/menu-cache-20261015/native'
def mod(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
sys.path.insert(0,str(D/'native'));import release_workspace as native
shared=mod('shared_ui_publisher',D/'shared/release_navigation.py')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
class ReleaseContract(unittest.TestCase):
 def test_payload_hashes(self):
  p=D/'native';m=json.loads((p/'release-manifest.json').read_text());rows=native.validate(m,None)
  self.assertEqual(len(rows),17)
  for r in rows:self.assertEqual(sha(p/r['candidate']),r['sha256'])
 def test_changed_manifest_rejected(self):
  m=json.loads((D/'native/release-manifest.json').read_text());m['targets'][0]['target']='/etc/passwd'
  with self.assertRaises(ValueError):native.validate(m,None)
 def test_shared_scope(self):
  p=D/'shared';m=json.loads((p/'approved-manifest.json').read_text());self.assertEqual(len(shared.validate(m,p)),4)
  self.assertFalse(m['runtimeRequired']);self.assertFalse(m['businessWrites']);self.assertFalse(m['timersChanged'])
 def test_shared_extra_rejected(self):
  p=D/'shared';m=json.loads((p/'approved-manifest.json').read_text());m['files'].append(m['files'][0])
  with self.assertRaises(ValueError):shared.validate(m,p)
 def test_html_dependency_closure(self):
  from html.parser import HTMLParser
  m=json.loads((D/'native/release-manifest.json').read_text());urls={r['url'] for r in m['immutableAssets']};prefix='/dashboard/workspace-assets/'+m['releaseId']+'/'
  class Parser(HTMLParser):
   def handle_starttag(self,tag,attrs):
    for k,v in attrs:
     if k in ('src','href') and v and v.startswith(prefix):assert v.split('?')[0] in urls,v
  for n in ['assets/home.html','assets/index.html','candidate/fs-home/index.html']:Parser().feed((D/'native'/n).read_text())
 def test_old_immutable_routes_unchanged(self):
  pattern=r'location = (/dashboard/workspace-assets/[^\s{]+) \{.*?\n\}'
  old=(OLD/'candidate/formal.conf').read_text();new=(D/'native/candidate/formal.conf').read_text()
  for match in re.finditer(pattern,old,re.S):self.assertIn(match.group(0),new)
 def test_new_exact_routes_keep_auth(self):
  m=json.loads((D/'native/release-manifest.json').read_text());s=(D/'native/candidate/formal.conf').read_text()
  for r in m['immutableAssets']:
   block=re.search(r'location = '+re.escape(r['url'])+r' \{.*?\n\}',s,re.S).group(0)
   self.assertIn('auth_request /__nav_formal_native_session;',block);self.assertIn('disable_symlinks on;',block);self.assertIn('GET|HEAD',block);self.assertIn(r['target'],block)
 def test_rollback_shared_then_native_compatible(self):
  m=json.loads((D/'native/release-manifest.json').read_text());s=json.loads((D/'shared/approved-manifest.json').read_text())
  self.assertFalse({x['path'] for x in m['unchangedRequired']}&{x['target'] for x in s['files']})
 def test_live_baseline_before_hash(self):
  old=json.loads((OLD/'release-contract.json').read_text());new=json.loads((D/'native/release-manifest.json').read_text())
  self.assertEqual({r['target']:r['sha256'] for r in old['targets']},{r['target']:r['beforeSha256'] for r in new['targets']})
 def test_ui_no_backend_or_secret_target(self):
  m=json.loads((D/'shared/approved-manifest.json').read_text());self.assertTrue(all(r['target'].startswith('/var/www/') for r in m['files']))
  self.assertTrue(all(r['target'].endswith(('.css','.js','.json')) for r in m['files']))
 def test_module_polish_scope_and_payload(self):
  p=D/'module-polish';pub=mod('module_polish',p/'release_navigation.py');m=json.loads((p/'approved-manifest.json').read_text())
  self.assertEqual(len(pub.validate(m,p)),5)
  self.assertTrue(all(r['target'].endswith(('.css','.html','.js')) for r in m['files']))
 def test_login_handlers_unchanged(self):
  old=(ROOT/'opt/auth-portal/login.html').read_text();new=(D/'module-polish/candidate/ui/login.html').read_text()
  strip=lambda s:re.sub(r'<style>.*?</style>','<style></style>',s,flags=re.S)
  self.assertEqual(strip(old),strip(new))
 def test_task_script_retained(self):
  old=(ROOT/'opt/mmoexp-taskboard/web/index.html').read_text();new=(D/'module-polish/candidate/ui/tasks.html').read_text()
  self.assertEqual(old,new.replace('<script defer src="/__hub/hubnav.js?v=ui-polish-20261015"></script>','').replace('styles.css?v=ui-20261015','styles.css?v=20261001-1'))
 def test_task_navigation_moved_not_cloned(self):
  s=(D/'module-polish/candidate/ui/hubnav.js').read_text();self.assertIn('main.prepend(local)',s);self.assertNotIn('cloneNode',s)
 def test_private_theme_no_invalid_shadow_selector(self):
  self.assertNotIn(':host[data-theme', (D/'native/assets/business.css').read_text())
if __name__=='__main__':unittest.main()

class FollowupReleaseContract(unittest.TestCase):
 def test_followup_manifests(self):
  for name,count in [('navfix',1),('module-polish',5),('contrastfix',1)]:
   p=D/name;m=json.loads((p/'approved-manifest.json').read_text());pub=mod('publisher_'+name.replace('-','_'),p/'release_navigation.py')
   self.assertEqual(len(pub.validate(m,p)),count)
   for row in m['files']:self.assertEqual(sha(p/'candidate'/row['candidate']),row['sha256'])
 def test_pricing_labels_and_final_source(self):
  s=(ROOT/'ui-system/adapters/hubnav.js').read_text();self.assertIn('.automation-grid>label',s)
  self.assertEqual(s.replace('__FS_UI_ROOT__','/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/'),(D/'contrastfix/candidate/ui/hubnav.js').read_text())
