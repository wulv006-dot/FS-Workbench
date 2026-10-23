import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('madden_publish',Path(__file__).with_name('publish.py'))
publish=importlib.util.module_from_spec(spec);spec.loader.exec_module(publish)


class PublishTests(unittest.TestCase):
    def test_drift_and_non_allowlisted_files_fail_before_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'live';stage=Path(folder)/'stage'
            root.mkdir();(stage/'source').mkdir(parents=True)
            (root/'browser_runtime.py').write_text('before')
            (stage/'source/browser_runtime.py').write_text('after')
            manifest={'browser_runtime.py':{'before':publish.sha(root/'browser_runtime.py'),
                                            'after':publish.sha(stage/'source/browser_runtime.py')}}
            publish.verify(root,stage,manifest)
            (root/'browser_runtime.py').write_text('changed elsewhere')
            with self.assertRaisesRegex(RuntimeError,'runtime_changed'):publish.verify(root,stage,manifest)
            with self.assertRaisesRegex(ValueError,'allowlisted'):publish.verify(root,stage,{'evidence/automation.json':{}})

    def test_manifest_exactly_covers_payload_and_has_no_sensitive_runtime(self):
        stage=Path(__file__).parent
        manifest=json.loads((stage/'manifest.json').read_text())
        self.assertEqual(set(manifest),{'dashboard/server.py','madden_nfl_27/browser.py','browser_runtime.py','run_in_container.sh'})
        for name,item in manifest.items():self.assertEqual(publish.sha(stage/'source'/name),item['after'])


if __name__=='__main__':unittest.main(verbosity=2)
