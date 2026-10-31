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
