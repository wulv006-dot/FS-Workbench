import importlib.util
from pathlib import Path
import unittest
import sys

path=Path(__file__).resolve().parents[1]/'prepare_ui.py'
spec=importlib.util.spec_from_file_location('prepare_game_monitor',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class PrepareTests(unittest.TestCase):
    def test_new_route_inherits_auth_instead_of_opening_public_access(self):
        old='location = /dashboard/game-monitor/index.html {\n auth_request /__auth;\n alias /old/index.html;\n add_header X-Frame-Options SAMEORIGIN;\n}'
        result=module.route(old,'/dashboard/game-monitor/index.html','/dashboard/game-monitor/operations.html','/new/operations.html')
        self.assertIn('auth_request /__auth;',result)
        self.assertIn('X-Frame-Options SAMEORIGIN',result)
        self.assertIn('alias /new/operations.html;',result)
        self.assertNotIn('alias /old/index.html;',result)

    def test_ambiguous_route_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'ambiguous_existing_route'):
            module.route('location = /x {\n alias /a;\n alias /b;\n}','/x','/new','/c')

    def test_legacy_data_and_scripts_are_preserved(self):
        original=b'<html><body><script>window.GAME_TIMELINE_DATA = {"games":[]};</script></body></html>'
        result=module.legacy_entry(original,'a'*64)
        self.assertIn(b'window.GAME_TIMELINE_DATA = {"games":[]};',result)
        self.assertEqual(result.count(b'id="fs-operations-entry"'),1)
        revised=module.legacy_entry(result,'b'*64)
        self.assertEqual(revised.count(b'id="fs-operations-entry"'),1)
        self.assertNotIn(b'asset: '+b'a'*64,revised)

    def test_rebuilt_manifest_has_one_latest_row_for_existing_operations_asset(self):
        rows=module.asset_rows({'game-monitor/index.html':'a'*64,'game-monitor/operations.html':'b'*64},Path('/static'),'version-new')
        self.assertEqual(len(rows),2)
        operations=[r for r in rows if r['candidate']=='assets/game-monitor/operations.html']
        self.assertEqual(len(operations),1)
        self.assertEqual(operations[0]['sha256'],'b'*64)

    def test_existing_route_parser_preserves_crlf_blocks(self):
        source=Path(__file__).resolve().parents[4]/'releases/fs-dashboard/game-monitor-autopublish-20261022/source'
        sys.path.insert(0,str(source))
        spec=importlib.util.spec_from_file_location('existing_publication',source/'publication.py')
        publication=importlib.util.module_from_spec(spec);spec.loader.exec_module(publication)
        block='location = /dashboard/game-monitor/index.html {\r\n    alias /static/index.html;\r\n}'
        self.assertEqual(publication.blocks(block)['/dashboard/game-monitor/index.html'],block)


if __name__=='__main__':unittest.main()
