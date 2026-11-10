"""Render the existing card with distinct platform quotes; no browser/network writes."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


HTML = Path(__file__).resolve().parents[1] / 'web/index.html'


class BundleUI(unittest.TestCase):
    def render(self, xbox):
        source = HTML.read_text(encoding='utf-8')
        card = source[source.index('function bundleCard('):source.index('function configPayload(')]
        side = lambda price: dict(orig=price, sale=price*.7, discount_vs_actual_pct=-10,
                                  players_counted=1, players_expected=1)
        bundle = dict(id='b', title='Bundle', products=dict(ps=111,xbox=222,pc=333),
                      warnings=[], players_count=1, players_ok=1, ps=side(10),
                      xbox=side(20) if xbox else None, pc=side(30),
                      players=[dict(status='ok', name='P', futbin_id=1,
                          ps_coins=1000,xbox_coins=1000,pc_coins=2000,
                          ps_actual=1,xbox_actual=2,pc_actual=3,
                          ps_strike=1.1,xbox_strike=2.2,pc_strike=3.3,
                          market_references=dict(XBOX=dict(shared_reference=True, observed_platform='PS')))])
        script = """
const document={createElement:()=>({innerHTML:'',setAttribute(){},querySelector(){return {}}})};
const esc=x=>String(x??''), coinsK=x=>String(x??'—');
const money=x=>x==null?'—':'$'+Number(x).toFixed(2);
""" + card + '\nprocess.stdout.write(bundleCard('+json.dumps(bundle)+').innerHTML);'
        return subprocess.run([shutil.which('node') or 'node', '-e', script],
                              check=True, capture_output=True, text=True, encoding='utf-8').stdout

    def test_card_shows_three_independent_quotes_and_market_reference(self):
        html = self.render(True)
        self.assertIn('Xbox · 页面原价', html)
        xbox_binding = html.split('data-plat="xbox"',1)[1].split('data-plat="pc"',1)[0]
        self.assertIn('原价 $20.00 / 售价 $14.00', xbox_binding)
        self.assertIn('互通市场', html)

    def test_missing_xbox_quote_is_blocked_instead_of_showing_ps_ready(self):
        html = self.render(False)
        self.assertIn('XBOX(本平台报价缺失)', html)
        self.assertNotIn('✅ 写价就绪', html)


if __name__ == '__main__':
    unittest.main()
