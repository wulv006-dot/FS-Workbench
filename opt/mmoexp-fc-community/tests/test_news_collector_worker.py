import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('news_worker', Path(__file__).resolve().parents[1]/'deploy/news_collector_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class WorkerTests(unittest.TestCase):
    def test_rejects_arbitrary_urls_and_extra_fields_before_network(self):
        with patch.object(worker.urllib.request, 'build_opener') as opener:
            for request in ({'source': 'http://127.0.0.1'}, {'source':'mmoexp','url':'http://localhost'}, {}):
                with self.assertRaises(ValueError):
                    worker.fetch(request)
            opener.assert_not_called()

    def test_redirect_denied(self):
        with self.assertRaises(ValueError):
            worker.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://localhost')

    def test_response_size_limited(self):
        response = Mock()
        response.geturl.return_value = worker.SOURCES['mmoexp']
        response.read.return_value = b'x'*(worker.MAX_BYTES+1)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(worker.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(ValueError):
                worker.fetch({'source':'mmoexp'})
        response.read.assert_called_once_with(worker.MAX_BYTES+1)

    def test_source_set_is_fixed(self):
        self.assertEqual(set(worker.SOURCES), {'mmoexp','ea'})
        self.assertTrue(all(url.startswith('https://') for url in worker.SOURCES.values()))


if __name__ == '__main__':
    unittest.main()
