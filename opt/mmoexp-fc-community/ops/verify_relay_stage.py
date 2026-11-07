import sys
import unittest

stage = '/opt/mmoexp-fc-relay-fix-20261108'
sys.path[:0] = [stage, '/opt/mmoexp-fc-community']
suite = unittest.defaultTestLoader.discover(stage + '/tests', pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(not result.wasSuccessful())
