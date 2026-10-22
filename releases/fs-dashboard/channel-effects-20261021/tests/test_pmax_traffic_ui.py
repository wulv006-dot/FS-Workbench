import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
import pmax_traffic_ui
class ActiveTraffic(unittest.TestCase):
    def test_alias_is_single_static_change(self):
        old=b'auth_request /session;\nalias /var/lib/fs-navigation-formal-static/pmax-fc-scope-20261022-v1/google.js;'
        after=pmax_traffic_ui.candidate(old)
        self.assertIn(b'auth_request /session;',after)
        self.assertIn(b'pmax-fc-traffic-20261022-v2/google.js;',after)
        self.assertEqual(len(pmax_traffic_ui.TARGETS),2)
        with self.assertRaisesRegex(ValueError,'exact_pmax'):pmax_traffic_ui.candidate(after)
    def test_active_renderer_exposes_project_without_merging_platform_cost(self):
        root=Path(__file__).resolve().parents[4]
        source=(root/'ui-system/modules/native/google.js').read_text()
        body=source[source.index('function renderSourceBody'):source.index('function render(container')]
        self.assertIn('PMax-Coins-US归FC项目',body)
        self.assertIn("if(game==='FC27')right.append(fullDetail('PMax-Coins-US",body)
        self.assertIn(".filter(c=>(c.game_mapping?.game||'UNKNOWN')===game)",body)
        self.assertIn('FC项目PMax（跨游戏指标）',source)
if __name__=='__main__':unittest.main()
