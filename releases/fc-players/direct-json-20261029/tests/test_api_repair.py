"""Narrow manual-tag permission and delayed shelves GETs; no real backend writes."""
from dataclasses import replace
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

from test_direct_import import direct
from player_web.settings import Settings
from player_web.repository import Repository, StateError
from player_web.model_service import refresh_models
from player_web.existing_action_service import prepare_existing_action, execute_existing_action
from tests_cloud.test_feature_parity import Backend, configuration


class ApiRepairTests(unittest.TestCase):
    def test_manual_add_tags_does_not_open_other_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings=replace(configuration(Path(tmp)),manual_existing_add_tags_enabled=True)
            self.assertTrue(settings.existing_action_write_enabled('add_tags'))
            for action in ('remove_tags','recommend_disable','recommend_enable','unlist'):
                self.assertFalse(settings.existing_action_write_enabled(action))
            repo=Repository(Path(tmp)/'db/control.sqlite3');repo.initialize();client=Backend(2)
            snapshot=refresh_models(settings,repo,client,'operator')
            plan=prepare_existing_action(settings,repo,client,'operator',snapshot['snapshot_id'],[300000],'add_tags',[9])
            job,created=repo.confirm(plan['plan_id'],'operator',plan['plan_digest'],write_enabled=True)
            self.assertTrue(created)
            execute_existing_action(settings,repo,client,job,repo.get_plan(plan['plan_id'],'operator'))
            self.assertEqual(repo.get_execution(job,'operator')['status'],'completed_readback')
            self.assertEqual(client.writes,[{'tid':[7,9],'id':[300000]}])
            self.assertFalse(settings.write_enabled)

    def test_flag_defaults_closed_and_env_opt_in(self):
        with patch.dict(os.environ,{'MANUAL_EXISTING_ADD_TAGS_ENABLED':'true'},clear=True):
            enabled=Settings.from_env()
            self.assertTrue(enabled.existing_action_write_enabled('add_tags'))
            self.assertFalse(enabled.write_enabled)
        with patch.dict(os.environ,{},clear=True):
            self.assertFalse(Settings.from_env().existing_action_write_enabled('add_tags'))

    def test_browser_status_exposes_only_scoped_tag_permission(self):
        from test_resume import ResumeTests
        fixture=ResumeTests('runTest');fixture.setUp()
        try:
            fixture.app.settings=replace(fixture.settings,manual_existing_add_tags_enabled=True)
            code,body,_=fixture.request('/api/status')
            self.assertEqual(code,200)
            self.assertTrue(body['existing_add_tags_write_enabled'])
            self.assertFalse(body['write_enabled'])
        finally:fixture.tearDown()

    def test_delayed_shelves_get_without_repeated_post(self):
        client=Mock()
        with patch.object(direct,'_products',side_effect=[StateError('DIRECT_SHELVES_MODEL_STATE_INCOMPLETE'),StateError('DIRECT_PRODUCTS_INCOMPLETE'),{'model_id':5}]) as read,patch.object(direct.time,'sleep') as sleep:
            self.assertEqual(direct._shelves_readback(client,5),{'model_id':5})
            self.assertEqual(read.call_count,3);self.assertEqual(sleep.call_count,2)
            self.assertEqual(client.mock_calls,[])

    def test_wait_is_bounded_and_scope_error_is_not_retried(self):
        with patch.object(direct,'_products',side_effect=StateError('DIRECT_SHELVES_MODEL_STATE_INCOMPLETE')) as read,patch.object(direct.time,'sleep'):
            with self.assertRaisesRegex(StateError,'DIRECT_SHELVES_MODEL_STATE_INCOMPLETE'):direct._shelves_readback(Mock(),5)
            self.assertEqual(read.call_count,6)
        with patch.object(direct,'_products',side_effect=StateError('DIRECT_PRODUCT_SCOPE_CHANGED')) as read,patch.object(direct.time,'sleep') as sleep:
            with self.assertRaisesRegex(StateError,'DIRECT_PRODUCT_SCOPE_CHANGED'):direct._shelves_readback(Mock(),5)
            self.assertEqual(read.call_count,1);sleep.assert_not_called()
