import tempfile
import unittest
from mmoexp_google_data.seo import web,ai_policy


class Web(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.calls=[]
        def verify(cookie,method,path):
            self.calls.append((cookie,method,path))
            return (200,'fixture') if cookie=='session=valid' else (401,None)
        self.app=web.Application(self.temp.name,self.temp.name+'/control',verify)
        self.path='/dashboard/analytics/seo/api/v1/ai-policy'

    def test_identity_headers_do_not_authenticate(self):
        self.assertEqual(self.app.handle('GET',self.path,{'X-Auth-User':'fixture'},b'')[0],401)

    def test_same_site_cookie_and_existing_edit_permission_control_switches(self):
        headers={'Cookie':'session=valid','Host':'fs.example','Origin':'https://fs.example','Content-Type':'application/json'}
        body=b'{"expected_revision":0,"patch":{"ai_enabled":true}}'
        self.assertEqual(self.app.handle('PATCH',self.path,dict(headers,Origin='https://evil.example'),body)[0],403)
        self.assertEqual(self.app.handle('PATCH',self.path,headers,body)[0],200)
        self.assertEqual(self.calls[-1][1:],('PATCH',self.path))

    def test_duplicate_query_and_unscoped_route_rejected(self):
        self.assertEqual(self.app.handle('GET',self.path+'?game=FC27&game=D4',{'Cookie':'session=valid'},b'')[0],422)
        self.assertEqual(self.app.handle('GET','/api/seo/v1/snapshots/current',{'Cookie':'session=valid'},b'')[0],404)

    def test_broken_control_store_does_not_block_base_endpoint(self):
        from unittest.mock import patch
        with patch.object(ai_policy.PolicyStore,'__init__',side_effect=OSError('unavailable')):
            self.assertEqual(self.app.handle('GET',self.path,{'Cookie':'session=valid'},b'')[0],503)
            self.assertEqual(self.app.handle('GET',self.path.replace('ai-policy','snapshots/current'),{'Cookie':'session=valid'},b'')[0],404)

    def test_authenticated_export_reads_one_fixed_snapshot_with_source_status(self):
        import csv,io
        from mmoexp_google_data.seo import store,daily
        from test_daily_snapshot import NIGHT,Source
        work=store.Store(self.temp.name)
        manifest=daily.run_daily(work,[Source()],clock=lambda:NIGHT)
        path=self.path.replace('ai-policy','snapshots/'+manifest['snapshot_id']+'/export.csv')+'?game=FC27'
        self.assertEqual(self.app.handle('GET',path,{},b'')[0],401)
        status,body=self.app.handle('GET',path,{'Cookie':'session=valid'},b'')
        self.assertEqual(status,200)
        rows=list(csv.DictReader(io.StringIO(body.text)))
        self.assertEqual(len(rows),30)
        self.assertEqual({r['facts_hash'] for r in rows},{manifest['facts_hash']})
        self.assertIn('ga4_data_status',rows[0])
        self.assertEqual(rows[0]['gsc_timezone'],'America/Los_Angeles')
