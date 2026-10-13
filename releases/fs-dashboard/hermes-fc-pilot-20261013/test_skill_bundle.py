import json
from pathlib import Path
import shutil
import tempfile
import unittest
from skill_bundle import load_bundle, prompt


class SkillTests(unittest.TestCase):
    def test_loads_reviewed_procedure_and_no_authority(self):
        bundle = load_bundle(Path(__file__).parent)
        text = prompt(bundle, {'project': 'FC27'})
        self.assertIn('自主按线索下钻', text)
        self.assertIn('KPI', text)
        self.assertNotIn('先核每行代表什么', text)
        self.assertIn('先核每行代表什么', bundle['methods_text'])
        self.assertEqual(bundle['permissions'], [])

    def test_changed_skill_and_permission_metadata_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(Path(__file__).parent/'skills', root/'skills')
            path = root/'skills/fs-fc-operations-analysis/SKILL.md'
            with path.open('a', encoding='utf-8') as f: f.write('changed')
            with self.assertRaisesRegex(ValueError, 'skill_changed'): load_bundle(root)
            manifest = root/'skills/manifest.json'
            item = json.loads(manifest.read_text('utf-8')); item['permissions_added'] = ['shell']
            manifest.write_text(json.dumps(item), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'skill_authority'): load_bundle(root)


if __name__ == '__main__': unittest.main()
