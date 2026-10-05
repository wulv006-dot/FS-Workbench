import importlib.util,io,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

W=Path(__file__).resolve().parents[2]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,W/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
url=load('url_guard','opt/iggm-web/url_guard.py')
bundle=load('bundle_policy','opt/deploy-hub/bundle_policy.py')
static=load('static_path','opt/mlb-online/static_path.py')

class URLTests(unittest.TestCase):
 def test_domain_and_url_boundaries(self):
  for bad in ['http://127.0.0.1/health?site=iggm.com','https://iggm.com.evil.example/','https://evil.example/?iggm.com','https://user@iggm.com/','file:///iggm.com','https://iggm.com:8443/','https://iggm.com\\@evil.example/','https://iggm.com/#abc','https://iggm.com/\n']:
   with self.subTest(url=bad),self.assertRaises(ValueError):url.parsed_destination(bad)
  self.assertEqual(url.parsed_destination('https://www.iggm.com/items')[1:],('www.iggm.com',443))
 def test_private_and_mixed_dns_rejected(self):
  for ip in ['127.0.0.1','10.0.0.1','169.254.169.254','100.64.0.1','::1','::ffff:127.0.0.1','224.0.0.1']:
   resolver=lambda *a,**k:[(socket.AF_INET6 if ':' in ip else socket.AF_INET,1,6,'',(ip,443))]
   with self.subTest(ip=ip),self.assertRaises(ValueError):url.public_destination('https://iggm.com/',resolver=resolver)
  with self.assertRaises(ValueError):url.public_destination('https://iggm.com/',resolver=lambda *a,**k:[(2,1,6,'',('1.1.1.1',443)),(2,1,6,'',('127.0.0.1',443))])
 def test_public_dns_and_pinned_connection(self):
  resolver=lambda *a,**k:[(socket.AF_INET,1,6,'',('1.1.1.1',80))]
  connection=url.pinned_connection('http://www.iggm.com/',resolver=resolver)
  with patch('socket.create_connection',return_value=object()) as create:
   connection.connect();self.assertEqual(create.call_args.args[0],('1.1.1.1',80))
 def test_redirect_checks_new_hostname_before_any_request(self):
  import urllib.request
  request=urllib.request.Request('https://iggm.com/')
  with self.assertRaises(ValueError):url.SafeRedirect().redirect_request(request,None,302,'',{},'http://127.0.0.1/?iggm.com')

class StaticPathTests(unittest.TestCase):
 def test_real_components_and_encoded_traversal(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'site';root.mkdir();(root/'ok.css').write_text('ok');sibling=Path(tmp)/'site-backup';sibling.mkdir();(sibling/'private.css').write_text('synthetic')
   self.assertEqual(static.safe_static_path(root,'ok.css'),(root/'ok.css').resolve())
   for bad in ['../site-backup/private.css','assets/../../site-backup/private.css','%2e%2e/site-backup/private.css','%252e%252e/site-backup/private.css','/etc/passwd','a\\..\\x','C:/bad','a//b']:
    with self.subTest(path=bad),self.assertRaises((ValueError,FileNotFoundError)):static.safe_static_path(root,bad)
 def test_symlink_refused(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'root';root.mkdir();outside=Path(tmp)/'other';outside.write_text('synthetic')
   try:(root/'link.css').symlink_to(outside)
   except OSError:self.skipTest('Windows user cannot create a symlink; Linux boundary still requires rerun')
   with self.assertRaises(ValueError):static.safe_static_path(root,'link.css')

class BundleTests(unittest.TestCase):
 def test_allowlist_and_runtime_deny(self):
  for name in ['index.html','assets/app.js','assets/style.css','assets/game.png','assets/data.json']:
   bundle.validate_publish_content(name,b'{}')
  for name in ['.env','config.json','deploy_client.json','secret.txt','_token.txt','_ck.txt','apply_log.jsonl','data/raw/a.js','../index.html','/index.html','backend.py','archive.zip','.git/config','nested/.cookies.txt']:
   with self.subTest(name=name),self.assertRaises(ValueError):bundle.validate_publish_content(name,b'{}')
 def test_sensitive_static_content_rejected(self):
  for data in [b'-----BEGIN PRIVATE KEY-----',b'{"password":"synthetic-only"}',b'const access_token = "synthetic-only";']:
   with self.subTest(dataKind=type(data).__name__),self.assertRaises(ValueError):bundle.validate_publish_content('index.html',data)
  bundle.validate_publish_content('index.html',b'const password = "YOUR_PASSWORD";')
 def test_note_escaped_as_text(self):
  self.assertEqual(bundle.escaped_text('<img src=x onerror=alert(1)>'),'&lt;img src=x onerror=alert(1)&gt;')

if __name__=='__main__':
 import sys,json
 sys.dont_write_bytecode=True
 # Only reviewer-authored pure guards. All external network blocked; temporary synthetic files only.
 with patch('socket.socket.connect',side_effect=AssertionError('network disabled')),patch('socket.getaddrinfo',side_effect=AssertionError('real DNS disabled')):
  result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
 print(json.dumps({'scope':'new pure guard logic only; no original app import/entrypoint','run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'passed':result.wasSuccessful()}))
 sys.exit(0 if result.wasSuccessful() else 1)
