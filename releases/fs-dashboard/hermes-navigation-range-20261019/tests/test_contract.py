import unittest,json,re,ast
from pathlib import Path
R=Path(__file__).resolve().parents[1]
class HermesNavigation(unittest.TestCase):
 def test_three_entries_and_existing_routes(self):
  reg=json.loads((R/'candidate/navigation.json').read_text());s=next(x for x in reg['sections'] if x['id']=='brain')
  self.assertEqual(s['path'],'/dashboard/modules/hermes/');self.assertEqual(s['ids'],['brain','hermes-conversation','customer-tracking'])
  self.assertEqual(len(re.findall('class="tool-card"',(R/'candidate/hermes-index.html').read_text())),3)
 def test_strict_pages_static_without_policy_relaxation(self):
  for n in ['conversation','customer']:
   s=(R/('candidate/'+n+'-index.html')).read_text();self.assertEqual(s.count('id="hubNav"'),1);self.assertIn("style-src 'self'",s);self.assertNotIn('unsafe-inline',s);self.assertIn('/__hub/hermes-nav.css?',s);self.assertIn('/__hub/nav.js?',s)
 def test_native_lifecycle_and_motion(self):
  s=(R/'candidate/hermes-nav.css').read_text();self.assertIn('@view-transition',s);self.assertIn('prefers-reduced-motion',s)
  s=(R/'candidate/nav.js').read_text();self.assertNotIn('history.pushState',s);self.assertNotIn('iframe',s)
 def test_range_keeps_existing_contract_and_unknown_guard(self):
  s=(R/'candidate/page.js').read_text();self.assertIn("get('candidates',{day}",s);self.assertIn('candidateEpoch',s);self.assertIn("write('scan',{day}",s);self.assertIn('pendingWrite',s);self.assertIn('config_version!==version',s)
  self.assertNotIn("localStorage.setItem",s);self.assertNotIn("sessionStorage.setItem",s)
 def test_bridge_and_exact_preparation(self):
  p=(R/'prepare_release.py').read_text();ast.parse(p);self.assertIn('baseline drift',p);self.assertIn("'/var/www/dashboard/index.html'",p)
  s=(R/'release_ui.py').read_text();ast.parse(s);self.assertIn('b=ui.publisher()',s);self.assertIn('b.apply(',s);self.assertIn('b.rollback(',s);self.assertNotIn('b.locks=',s)
if __name__=='__main__':unittest.main()
