"""Offline Linux regression entrypoint; never starts the bot or reads live configuration."""
import os
from pathlib import Path
import socket
import sys
import unittest


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))


REAL_CONNECT = socket.socket.connect


def local_connect(sock, address):
    if isinstance(address, tuple) and address[0] in ('127.0.0.1', 'localhost', '::1'):
        return REAL_CONNECT(sock, address)
    raise AssertionError('FC community tests must not connect to external services')


if __name__ == '__main__':
    for name in ('quote_bridge.py', 'quote_catalog.py', 'player_service.py', 'player_catalog.py', 'player_config.py', 'player_matching.py'):
        if (ROOT/name).read_bytes() != (ROOT.parent/'mmoexp-fc-quotes'/name).read_bytes():
            raise RuntimeError('Quote service mirror differs: '+name)
    if (ROOT/'deploy/news_collector_worker.py').read_bytes() != (ROOT.parent/'fc27-news-fetch/worker.py').read_bytes():
        raise RuntimeError('183 news worker mirror differs')
    socket.socket.connect = local_connect
    modules = [path.stem for path in sorted((ROOT / 'tests').glob('test_*.py'))
               if path.stem != 'test_token_save' or os.name == 'nt']
    if not modules:
        raise RuntimeError('FC community tests missing')
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in modules)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.testsRun or not result.wasSuccessful() or result.skipped:
        raise SystemExit(1)
