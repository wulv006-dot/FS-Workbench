import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mmoexp_google_data.seo import api, ai_policy, daily, snapshot, store
from test_daily_snapshot import NIGHT, Source


class Api(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=store.Store(self.root/'core')
        self.receipt=daily.run_daily(self.store,[Source()],clock=lambda:NIGHT)
        self.policy=ai_policy.PolicyStore(self.root/'control')
        self.service=api.Service(self.store.root,self.policy)
        self.actor=ai_policy.Actor('fixture-viewer',('FC27',),False,False)
        self.path='/api/seo/v1/snapshots/'+self.receipt['snapshot_id']+'/history'

    def test_anonymous_and_cross_game_denied(self):
        self.assertEqual(self.service.handle('GET',self.path,{'game':'FC27'},None)[0],401)
        self.assertEqual(self.service.handle('GET',self.path,{'game':'D4'},self.actor)[0],403)

    def test_read_is_snapshot_bound_without_work_db_or_model(self):
        with patch.object(store.Store,'db',side_effect=AssertionError('query must not read work DB')):
            status,body=self.service.handle('GET',self.path,{'game':'FC27'},self.actor)
        self.assertEqual(status,200)
        self.assertEqual(body['facts_hash'],self.receipt['facts_hash'])
        self.assertEqual(len(body['rows']),30)

    def test_refresh_and_invalid_pagination_rejected(self):
        self.assertEqual(self.service.handle('GET',self.path,{'game':'FC27','refresh':'1'},self.actor)[0],422)
        self.assertEqual(self.service.handle('GET',self.path,{'game':'FC27','limit':'101'},self.actor)[0],422)

    def test_settings_need_existing_manage_permission_and_csrf(self):
        path='/api/seo/v1/ai-policy'
        admin=ai_policy.Actor('fixture-admin',('FC27','D4','AION2','WOW_FOREVER'),True,False)
        body=dict(expected_revision=0,patch=dict(ai_enabled=True))
        self.assertEqual(self.service.handle('PATCH',path,{},admin,body=body)[0],403)
        self.assertEqual(self.service.handle('PATCH',path,{},admin,body=body,mutation_authorized=True)[0],200)
        self.assertEqual(self.service.handle('PATCH',path,{},admin,body=body,mutation_authorized=True)[0],409)

    def test_export_pages_keep_same_hash(self):
        rows=list(self.service.export(self.receipt['snapshot_id'],'FC27',self.actor))
        self.assertIn(self.receipt['snapshot_id'],rows[1])
        self.assertIn(self.receipt['facts_hash'],rows[1])
        self.assertEqual(len(rows),31)


if __name__=='__main__':unittest.main()
