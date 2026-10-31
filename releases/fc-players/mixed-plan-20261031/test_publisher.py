import ast,hashlib,json,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
TREE=ast.parse((HERE/'upgrade_mixed_plan.py').read_text(encoding='utf-8'))
def functions(**scope):
    exec(compile(ast.Module(body=[n for n in TREE.body if isinstance(n,ast.FunctionDef)],type_ignores=[]),'actual-wrapper','exec'),scope)
    return scope
class PublisherTests(unittest.TestCase):
    def test_exact_current_51_source_baseline_and_three_targets(self):
        new=json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
        old=json.loads((HERE.parent/'admin-api-repair-20261031/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(new['baseline'],{**old['baseline'],**old['files']});self.assertEqual(len(new['baseline']),51)
        self.assertEqual(set(new['files']),{'VERSION','player_web/new_card_service.py','player_web/static/app.js'})
    def test_original_dockerfile_validator(self):
        path=HERE.parent/'direct-json-20261029/publisher/upgrade_direct_json.py'
        tree=ast.parse(path.read_text(encoding='utf-8'));node=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='validate_dockerfile')
        scope={'BASE_IMAGE':'fc27-player-tool:2026.10.31-cloud.17'}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'original-validator','exec'),scope)
        scope['validate_dockerfile']((HERE/'Dockerfile').read_text(encoding='utf-8'))
    def test_manual_flag_preserved_and_no_policy_injection(self):
        call=functions(original_unit=lambda text:text.replace('cloud.17','cloud.18'))['updated_unit']
        text='docker --env MANUAL_EXISTING_ADD_TAGS_ENABLED=true --read-only cloud.17'
        self.assertEqual(call(text),text.replace('cloud.17','cloud.18'))
        with self.assertRaises(RuntimeError):call(text.replace('true','false'))
    def test_manifest_must_match_pinned_bytes(self):
        raw=(HERE/'manifest.json').read_bytes();value=json.loads(raw)
        scope=functions(HERE=HERE,hashlib=hashlib,json=json,MANIFEST_SHA=hashlib.sha256(raw).hexdigest())
        scope['validate_manifest'](value)
        with self.assertRaises(RuntimeError):scope['validate_manifest']({**value,'base_version':'old'})
