import unittest,re,json,hashlib,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT.parent/'releases/fs-dashboard/menu-cache-20261015/native/assets'
class UIContract(unittest.TestCase):
 def test_no_business_logic_changed(self):
  forbidden=['business.js','google.js','runtime.js','metrics.js','snapshot-client.js','management/management.js','management/targets.json','game-monitor/daily.js']
  for name in forbidden:self.assertFalse((ROOT/'modules/native'/name).exists(),name)
 def test_shell_data_functions_preserved(self):
  old=(OLD/'shell.js').read_text();new=(ROOT/'modules/native/shell.js').read_text()
  self.assertEqual(old[:old.index('const $=')],new[:new.index('const $=')])
 def test_no_unknown_price_rules(self):
  for p in (ROOT/'adapters').glob('*.js'):
   s=p.read_text();self.assertNotIn("method:'POST'",s);self.assertNotIn('Authorization',s)
 def test_shared_nav_security(self):
  s=(ROOT/'adapters/hubnav.js').read_text()
  for value in ["'/__auth/verify'","clearMenuCache()","role==='admin'","requiredGroup!=='deploy'","currentUser=null","identity_changed","redirect:'manual'"]:
   self.assertIn(value,s)
 def test_names_and_single_rpg(self):
  m=json.loads((ROOT/'modules/native/navigation.json').read_text());tools={x['id']:x for x in m['tools']}
  self.assertEqual(tools['gallery']['label'],'FC27 收藏馆调价');self.assertIn('历史',tools['odds']['label'])
  self.assertEqual(sum(t['path']=='/d4/' for t in tools.values()),1)
 def test_theme_complete(self):
  s=(ROOT/'tokens/fs-tokens.css').read_text();blocks=re.findall(r'\{([^{}]*)\}',s,re.S)
  light=set(re.findall(r'(--fs-[\w-]+):',blocks[0]));dark=set(re.findall(r'(--fs-[\w-]+):',blocks[1]))
  self.assertTrue(dark<=light)
  self.assertEqual(light-dark,{'--fs-radius','--fs-input-radius','--fs-modal-radius','--fs-nav-width','--fs-font'})
 def test_contrast(self):
  s=(ROOT/'tokens/fs-tokens.css').read_text()
  def luminance(c):
   rgb=[int(c[i:i+2],16)/255 for i in (1,3,5)];v=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in rgb];return sum(a*b for a,b in zip(v,[.2126,.7152,.0722]))
  for block in re.findall(r'\{([^{}]*)\}',s,re.S):
   d=dict(re.findall(r'--fs-([\w-]+):\s*(#[a-fA-F0-9]{6})',block))
   for fg,bg in [('text','surface'),('muted','surface'),('brand-on','brand'),('ok-on','ok'),('danger-on','danger'),('warn-on','warn'),('info-on','info')]:
    a,b=sorted([luminance(d[fg]),luminance(d[bg])]);self.assertGreaterEqual((b+.05)/(a+.05),4.5,(fg,bg,d))
 def test_shadow_private_definitions_removed(self):
  for n in ['business.css','google.css']:
   s=(ROOT/'modules/native'/n).read_text()
   for v in ['bg','tx','tx2','ac','surface','card']:self.assertNotRegex(s,r'--'+v+r'\s*:')
 def test_syntax_runner_is_wired(self):
  runner=(ROOT/'tests/syntax.cjs').read_text();self.assertIn('--check',runner)
  self.assertIn('ui-system/tests/syntax.cjs',(ROOT.parent/'tools/pr_fast.py').read_text())
 def test_no_auto_switch(self):
  for p in (ROOT/'adapters').glob('*.js'):
   self.assertNotRegex(p.read_text(),r'\.checked\s*=')
 def test_navigation_accessible_subentries(self):
  s=(ROOT/'adapters/hubnav.js').read_text();self.assertIn("section.id==='analytics'",s);self.assertIn("aria-disabled",s);self.assertIn("nav.inert",s)
 def test_layout_contract(self):
  s=(ROOT/'adapters/hubnav.css').read_text();self.assertIn('236px',s);self.assertIn('@media print',s)
  self.assertIn('minmax(0,1fr)',(ROOT/'modules/brain/brain.css').read_text())
if __name__=='__main__':unittest.main()

class LegacyIsolation(unittest.TestCase):
 def test_unreviewed_modules_keep_original_content_palette(self):
  s=(ROOT/'adapters/hubnav.js').read_text()
  self.assertIn("styledModule?['fs-tokens.css','fs-ui.css','legacy.css','hubnav.css']:['fs-tokens.css','hubnav.css']",s)
  self.assertIn("if(styledModule)document.body.classList.add('fs-ui-page')",s)
