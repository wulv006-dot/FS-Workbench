import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('daily_publisher', ROOT/'deploy/release_navigation.py')
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)


class PublishTests(unittest.TestCase):
    def test_exact_targets_no_auth_or_orders(self):
        self.assertEqual(p.expected_files({'scope': p.DAILY_SCOPE}), {'daily/range_api.py','daily/fc_daily.py','daily/fc_daily_model.py'})
        for path in ('daily/auth_portal.py','daily/clients.json','daily/fc_detail_reader.py'):
            with self.assertRaises(ValueError): p.target_for(path)
    def test_prior_scopes_preserved(self):
        self.assertEqual(len(p.expected_files({'scope':p.DETAIL_SCOPE})), 5)
        self.assertEqual(p.expected_files({'scope':p.BOUNDARY_SCOPE}), {'live/range_api.py'})
    def test_only_existing_range_service_restarted(self):
        calls=[]
        with patch.object(p.subprocess, 'run', lambda argv,**kw: calls.append(argv)), patch.object(p.urllib.request,'urlopen',lambda *a,**k:io.BytesIO(b'{"ok":true}')):
            p.restart_for({'scope':p.DAILY_SCOPE})
        self.assertEqual([a for a in calls if a[1]=='restart'], [['systemctl','restart','fs-business-range.service']])
    def test_staged_hash_and_extra_scope_guard(self):
        manifest=json.loads((ROOT/'deploy/approved-manifest.json').read_text())
        self.assertEqual(len(p.validate(manifest,ROOT/'deploy')),3)
        wrong=copy.deepcopy(manifest);wrong['files'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'SHA differs'):p.validate(wrong,ROOT/'deploy')
        wrong=copy.deepcopy(manifest);wrong['files'].pop()
        with self.assertRaisesRegex(ValueError,'exact approved scope'):p.validate(wrong,ROOT/'deploy')
    def test_frontend_only_versioned_paths_and_new_module(self):
        manifest=json.loads((ROOT/'frontend/approved-manifest.json').read_text())
        self.assertEqual(len(manifest['immutableAssets']),15);self.assertEqual(len(manifest['targets']),3)
        bundle=(ROOT/'frontend/assets/business.js').read_text('utf-8')
        self.assertIn('function dailyMount()',bundle);self.assertIn('dailyMount();return;',bundle)
        self.assertNotIn('sk-'+'synthetic-secret',bundle)
        self.assertNotIn('FS_DAILY_MODEL_KEY_FILE',bundle)
        nginx=(ROOT/'frontend/candidate/formal.conf').read_text()
        previous=(ROOT.parent/'baseline/frontend/candidate/formal.conf')
        if previous.exists():
            import re
            scrub=lambda text:re.sub(r'workspace-native-20261006-[a-f0-9]{12}','VERSION',text)
            self.assertEqual(scrub(nginx),scrub(previous.read_text()))


if __name__=='__main__':unittest.main(verbosity=2)
