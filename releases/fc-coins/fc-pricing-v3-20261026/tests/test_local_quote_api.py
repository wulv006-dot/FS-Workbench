from datetime import datetime, timezone
import json
import unittest
from unittest.mock import MagicMock, patch

from fc_collection import local_quote_api, package_relay, u4gm_browser

RUN_ID = '00000000-0000-4000-8000-000000010003'


def request(source='U4GM', wanted=None):
    return dict(source=source, run_id=RUN_ID, wanted=[['PS', '100']] if wanted is None else wanted)


class LocalQuoteAPI(unittest.TestCase):
    def test_offer_binds_visible_platform_quantity_price_and_gift(self):
        stamp = '2026-11-24T14:15:00+00:00'
        row = u4gm_browser.preview_offer('XBOX', '1000', 'Xbox One/Series', '1000 K\n+50K Free', '$ 65.00', stamp)
        self.assertEqual((row['platform'], row['purchase_k'], row['regular_price'], row['bonus_k']),
                         ('XBOX', '1000', '65.00', '50'))
        with self.assertRaisesRegex(ValueError, 'browser_platform_mismatch'):
            u4gm_browser.preview_offer('XBOX', '1000', 'PC', '1000 K', '$ 65.00', stamp)
        with self.assertRaisesRegex(ValueError, 'browser_package_mismatch'):
            u4gm_browser.preview_offer('XBOX', '1000', 'Xbox One/Series', '100 K', '$ 6.50', stamp)

    def test_pc_unavailable_and_iggm_outside_scope(self):
        self.assertEqual(u4gm_browser.run_request(request(wanted=[['PC', '1000']]))['offers'], [])
        with self.assertRaisesRegex(ValueError, 'browser_observation_scope'):
            u4gm_browser.run_request(request('IGGM'))

    def test_provider_stops_later_requests_after_access_refusal(self):
        with patch.object(u4gm_browser, '_blocked', False), patch.object(u4gm_browser, 'collect',
                return_value=([], ['http_403'])) as collect:
            self.assertEqual(u4gm_browser.run_request(request())['errors'], ['http_403'])
            self.assertEqual(u4gm_browser.run_request(request())['errors'], ['source_blocked'])
        collect.assert_called_once()

    def test_server_request_only_reads_fresh_local_data_and_binds_round(self):
        stamp = datetime(2026, 11, 24, 14, 16, tzinfo=timezone.utc)
        latest = dict(sampled_at=stamp.isoformat(), offers=[
            u4gm_browser.preview_offer('PS', '100', 'PS 4/5', '100 K', '$ 6.50', stamp.isoformat()),
            u4gm_browser.preview_offer('PS', '1000', 'PS 4/5', '1000 K', '$ 65.00', '2026-11-24T13:16:00+00:00')],
                      errors=[])
        with patch.object(local_quote_api, 'run_request') as fetch:
            receipt = local_quote_api.read_snapshot(request(wanted=[['PS','100'],['PS','1000'],['PC','100']]),
                                                   latest, stamp)
            self.assertEqual(receipt['errors'], ['browser_platform_unavailable'])
            self.assertEqual([(o['run_id'], o['purchase_k']) for o in receipt['offers']], [(RUN_ID, '100')])
        fetch.assert_not_called()

    def test_ssh_worker_accepts_only_matching_loopback_receipt(self):
        payload = dict(request(), offers=[], errors=['browser_platform_unavailable'])
        response = MagicMock()
        with patch.object(package_relay, 'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value = response
            response.read.return_value = json.dumps(payload).encode()
            self.assertEqual(package_relay.local_quote_api(request()), payload)
            sent = opener.return_value.open.call_args.args[0]
            self.assertEqual(sent.full_url, 'http://127.0.0.1:8790' + local_quote_api.OBSERVATION_PATH)
            self.assertEqual(sent.get_method(), 'POST')
            response.read.return_value = b'{"source":"U4GM","run_id":"other"}'
            self.assertEqual(package_relay.local_quote_api(request())['errors'], ['local_quote_api_unavailable'])
