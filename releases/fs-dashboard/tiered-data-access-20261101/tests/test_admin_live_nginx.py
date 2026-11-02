import unittest
from pathlib import Path

class NginxLiveRoute(unittest.TestCase):
 def test_exact_location_passes_only_known_session_names(self):
  path=Path(__file__).resolve().parents[1]/'deploy'/'live_orders.location.conf'
  self.assertTrue(path.is_file(),'dedicated live route missing')
  text=path.read_text(encoding='utf8')
  self.assertIn('location = /dashboard/users/live-orders.json {',text)
  self.assertIn('auth_request /__auth_verify;',text)
  self.assertIn('if ($request_method !~ "^(GET|POST)$") { return 405; }',text)
  self.assertIn('proxy_set_header X-Auth-User "";',text)
  self.assertIn('MMOEXP_AUTH=$cookie_MMOEXP_AUTH',text)
  self.assertIn('FS_ACCESS_CANDIDATE=$cookie_FS_ACCESS_CANDIDATE',text)
  self.assertIn('fc27sess=$cookie_fc27sess',text)
  self.assertNotIn('$http_cookie',text)
  self.assertIn('proxy_pass http://127.0.0.1:8931/users/live-orders$is_args$args;',text)

if __name__=='__main__':unittest.main(verbosity=2)
