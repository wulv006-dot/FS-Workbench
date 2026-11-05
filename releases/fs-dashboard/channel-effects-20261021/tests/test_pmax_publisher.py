import importlib.util
import sys
import unittest
from pathlib import Path

DEPLOY=Path(__file__).resolve().parents[1]/'deploy'
sys.path.insert(0,str(DEPLOY))
import pmax_scope
import cards_mapping


class PMaxPublisher(unittest.TestCase):
    def test_cards_mapping_only_updates_four_reading_consumers(self):
        self.assertEqual(set(cards_mapping.TARGETS.values()), {
            '/opt/mmoexp-marketing/details/game_mapping_20261019.json',
            '/opt/mmoexp-marketing/details/game_dimensions.py',
            '/opt/fs-hermes-fc/channel_effects.py',
            '/opt/fs-hermes-fc/es_order_structure.py',
        })

    def test_only_four_current_aliases_change_and_unknown_version_rejects(self):
        original=(b'auth_request /__session;\n'+b'alias /var/lib/fs-navigation-formal-static/channel-effects-a8c5835cbdf9/index.html;\n'+b'alias /var/lib/fs-navigation-formal-static/channel-effects-a8c5835cbdf9/channel.js;\n'+b'alias /var/lib/fs-navigation-formal-static/channel-effects-a8c5835cbdf9/channel.css;\n'+b'alias /var/lib/fs-navigation-formal-static/workspace-native-20261019-traffic-v3/google.js;\n')
        after=pmax_scope.candidate(original)
        self.assertIn(b'auth_request /__session;',after)
        self.assertEqual(after.count(pmax_scope.ASSETS.encode()),4)
        with self.assertRaisesRegex(ValueError,'exact_current'):pmax_scope.candidate(after)

    def test_closed_reading_scope_has_no_credentials_session_or_timer(self):
        targets=pmax_scope.TARGETS
        self.assertEqual(len(targets),13)
        self.assertEqual({k for k in targets if k.startswith('ui/')},{'ui/index.html','ui/channel.js','ui/channel.css','ui/google.js'})
        self.assertTrue(all('session' not in p and not p.endswith(('.service','.timer')) for p in targets.values()))
        self.assertEqual(targets['runtime/traffic_contract.py'],'/opt/fs-hermes-fc/traffic_contract.py')
        self.assertEqual(targets['details/traffic_contract.py'],'/opt/mmoexp-marketing/details/traffic_contract.py')


if __name__=='__main__':unittest.main()
