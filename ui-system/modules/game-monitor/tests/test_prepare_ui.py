import importlib.util
from pathlib import Path
import unittest
import sys

path=Path(__file__).resolve().parents[1]/'prepare_ui.py'
spec=importlib.util.spec_from_file_location('prepare_game_monitor',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class PrepareTests(unittest.TestCase):
    def test_default_entry_targets_new_ui_without_replacing_legacy_data_route(self):
        old='location = /dashboard/game-monitor/ { rewrite ^ /dashboard/game-monitor/index.html last; }'
        result=module.default_entry(old)
        self.assertIn('/dashboard/game-monitor/operations.html last;',result)
        self.assertEqual(module.default_entry(result),result)
        with self.assertRaisesRegex(ValueError,'default_entry_route_drift'):
            module.default_entry(old+'\n'+old)

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

    def test_legacy_assets_are_not_in_new_release_inventory(self):
        rows=module.current_assets({'game-monitor/index.html':'a','game-monitor/daily.js':'b','game-monitor/assets/tool.jpg':'c','management/index.html':'d'})
        self.assertEqual(rows,{'game-monitor/index.html':'a','management/index.html':'d'})

    def test_retired_routes_removed_without_touching_new_or_shared_routes(self):
        block=lambda path:'location = '+path+' {\n alias /a;\n}'
        paths=['/dashboard/game-monitor/daily.json','/dashboard/game-monitor/fs-integration.js','/dashboard/game-monitor/assets/tool.jpg','/dashboard/game-monitor/intelligence.json','/dashboard/management/index.html']
        result=module.retire_routes('\n'.join(map(block,paths)),'new')
        self.assertNotIn('daily.json',result)
        self.assertNotIn('fs-integration.js',result)
        self.assertNotIn('assets/tool.jpg',result)
        self.assertIn('intelligence.json',result)
        self.assertIn('management/index.html',result)
        old=block('/dashboard/workspace-assets/old/game-monitor/daily.js')
        current=block('/dashboard/workspace-assets/new/game-monitor/assets/index.html')
        self.assertEqual(module.retire_routes(old+'\n'+current,'new'),old+'\n')

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

    def test_only_authorized_retired_units_leave_protection(self):
        source=Path(__file__).resolve().parents[4]/'releases/fs-dashboard/game-monitor-autopublish-20261022/source'
        sys.path.insert(0,str(source))
        spec=importlib.util.spec_from_file_location('publication_retirement',source/'publication.py')
        publication=importlib.util.module_from_spec(spec);spec.loader.exec_module(publication)
        paths=['/etc/systemd/system/fs-boss-game-monitor.timer','/etc/systemd/system/fs-boss-game-monitor.service','/etc/systemd/system/fs-game-intelligence.timer','/etc/systemd/system/fs-hermes-ops-bridge.service']
        self.assertEqual(publication.retained_protection([{'path':p} for p in paths]),set(paths[2:]))


if __name__=='__main__':unittest.main()
