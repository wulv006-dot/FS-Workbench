import ast,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
HERE=Path(__file__).resolve().parent
TREE=ast.parse((HERE/'upgrade_api_repair.py').read_text(encoding='utf-8'))

def functions(**values):
    nodes=[n for n in TREE.body if isinstance(n,ast.FunctionDef)]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-publisher-functions','exec'),values)
    return values

class PublisherTests(unittest.TestCase):
    def test_all_51_baselines_are_exact_cloud16_paths_and_hashes(self):
        manifest=json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
        old=json.loads((HERE.parent/'direct-json-20261029/tag-labels/SOURCE-MAP.json').read_text(encoding='utf-8'))
        expected={**old['protected'],**{name:row['candidate_sha256'] for name,row in old['files'].items()}}
        self.assertEqual(len(expected),51)
        self.assertEqual(manifest['baseline'],expected)
        self.assertIn('球员维护工具/admin_client.py',manifest['baseline'])

    def test_exact_runtime_flag_and_other_runtime_text_preserved(self):
        call=functions(original_unit=lambda text:text.replace('cloud.16','cloud.17'))['updated_unit']
        source='ExecStart=docker --env-file /etc/fc27-player-tool/app.env --env IDLE_STOP_SECONDS=600 --read-only cloud.16'
        self.assertEqual(call(source),source.replace('app.env','app.env --env MANUAL_EXISTING_ADD_TAGS_ENABLED=true').replace('cloud.16','cloud.17'))
        for bad in (source.replace('--env-file','--other'),source+' --env MANUAL_EXISTING_ADD_TAGS_ENABLED=false',source+' --env-file /etc/fc27-player-tool/app.env'):
            with self.assertRaises(RuntimeError):call(bad)

    def test_manifest_tamper_rejected(self):
        raw=(HERE/'manifest.json').read_bytes();value=json.loads(raw)
        scope=functions(HERE=HERE,hashlib=hashlib,json=json,MANIFEST_SHA=hashlib.sha256(raw).hexdigest())
        scope['validate_manifest'](value)
        with self.assertRaises(RuntimeError):scope['validate_manifest']({**value,'manual_add_tags':False})
        scope['MANIFEST_SHA']='0'*64
        with self.assertRaises(RuntimeError):scope['validate_manifest'](value)
