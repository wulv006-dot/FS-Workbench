import unittest
import resource_boundaries as boundaries


class BoundaryTests(unittest.TestCase):
    def test_units_preserve_all_existing_arguments(self):
        source='[Service]\nExecStart=/usr/bin/docker run --rm --network host --env-file /private.env fixture\n'
        result=boundaries.unit(source,7)
        self.assertIn('--memory=7g --memory-swap=7g',result)
        self.assertEqual(result.replace(' --memory=7g --memory-swap=7g',''),source)
        with self.assertRaises(ValueError):boundaries.unit(result,7)
        with self.assertRaises(ValueError):boundaries.unit(source+source,7)

    def test_both_rpg_paths_bounded_without_changing_original_arguments(self):
        source='def one():\n    cmd = [DOCKER, "run", "--rm", "original-id"]\ndef two():\n    cmd = [DOCKER, "run", "--rm", "other-original-id"]\n'
        result=boundaries.rpg(source)
        self.assertEqual(result.count('"--memory", "2g"'),2)
        self.assertEqual(result.count('"--init"'),2)
        self.assertEqual(result.replace(' "--init", "--memory", "2g", "--memory-swap", "2g",',''),source)
        with self.assertRaises(ValueError):boundaries.rpg(result)
        with self.assertRaises(ValueError):boundaries.rpg(source.split('def two():')[0])
