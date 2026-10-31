import sys,json,unittest,types,contextlib,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'opt/fs-access-policy'),str(ROOT/'releases/registration/iam-modules-20261031/candidate'),str(ROOT/'releases/registration/iam-modules-20261031'),str(ROOT/'releases/fs-dashboard/fs-revision-20261015/accounts/candidate/runtime/vendor')]
import rbac, module_permissions as m, auth_candidate as core, iam_console
from unittest.mock import patch
from roles import migrate
USER='reg:11111111-1111-4111-8111-111111111111'
P=rbac.default_policy()
P['roles']['FCObserver']={'label':'FC观察','rules':[{'resources':['coins'],'actions':['view']}]}
P['bindings'][USER]={'roles':['SportsOps','Viewer','ArpgOps','Analyst','CollabEditor','Deployer','PricingOps']}
P['bindings']['dot_fc_observer']={'roles':['FCObserver'],'deny':[{'resources':['*'],'actions':['edit','execute','deploy','manage']}]}
class Policy:
    def __init__(self,p):self.p=p
    def status(self):return {'degraded':''}
    def authorize(self,*args):return rbac.authorize(self.p,*args)
    def matrix(self,s):return rbac.grant_matrix(self.p,s)
class Store:
    def __init__(self,p):
        self.policy=Policy(p);self.namespace=types.SimpleNamespace(fence=contextlib.nullcontext)
        self.live={'user_id':USER[4:],'live_state':'readonly','live_name':'liushengjie'}
        self.enabled=True;self.collisions=set();self.accounts=types.SimpleNamespace(row=lambda s:{'enabled':self.enabled,'modules':dict(m.DEFAULT)})
    def session(self,token):return self.live if token=='test' else None
    def permission_state(self,uid):return {'modules':dict(m.DEFAULT)}
    def reserved(self):return self.collisions
class Fix(unittest.TestCase):
    def setUp(self):
        self.p=migrate(P,rbac);self.store=Store(self.p)
        self.adapter=types.SimpleNamespace(store=self.store,legacy=lambda cookies:None)
    def verify(self,path,method='GET'):
        return m.verify(self.adapter,{core.COOKIE:'test'},method,path,'dashboard')[0]
    def test_reported_reads(self):
        for path in ['/dashboard/fs-home/navigation.json','/dashboard/channel-effects/',
            '/dashboard/fs-home/advisor.json?mode=hermes&structure=customer_tracking&view=config',
            '/dashboard/fs-home/range.json?start=2026-10-01&end=2026-10-30&profit_site=all&profit_category=-1&mode=profit-history',
            '/dashboard/analytics/?mode=business&b_site=all&b_group=mmoexp&b_grain=day',
            '/api/hermes/conversations','/d4/api/local/jobs?limit=10','/s/',
            '/dashboard/analytics/campaigns/analytics/api/statistics-snapshot?kind=today',
            '/dashboard/modules/marketing/','/api/fc27/cloud/automation']:
            with self.subTest(path=path): self.assertEqual(self.verify(path),200)
    def test_business_writes_and_admin_denial(self):
        self.assertEqual(self.verify('/d4/api/prices','POST'),200)
        self.assertEqual(self.verify('/__auth/iam/api/member/roles','POST'),403)
        self.assertEqual(self.verify('/dashboard/modules/marketing/api/settings','POST'),403)
        self.assertEqual(self.verify('/unknown-api'),403)
    def test_revoked_disabled_collision_expired(self):
        self.store.live['live_state']='revoked'; self.assertEqual(self.verify('/d4/'),403)
        self.store.live['live_state']='readonly';self.store.enabled=False;self.assertEqual(self.verify('/d4/'),403)
        self.store.enabled=True;self.store.collisions={'liushengjie'};self.assertEqual(self.verify('/d4/'),403)
        self.store.collisions=set();self.store.live=None;self.assertEqual(self.verify('/d4/'),401)
    def test_deny_and_policy_failure(self):
        self.p['bindings'][USER]['deny']=[{'resources':['d4'],'actions':['view']}]
        self.assertEqual(self.verify('/d4/'),403)
        self.store.policy.status=lambda:{'degraded':'bad'};self.assertEqual(self.verify('/s/'),403)
    def test_scoped_roles(self):
        for role,own,other in [('SportsOps','/dashboard/fc27-coins.html','/d4/'),('ArpgOps','/d4/','/dashboard/fc27-coins.html'),('MarketingOps','/dashboard/modules/marketing/','/d4/')]:
            self.p['bindings'][USER]={'roles':[role]}
            self.assertEqual(self.verify(own,'POST'),200);self.assertEqual(self.verify(other,'POST'),403)
            self.assertEqual(self.verify('/__auth/iam/'),403)
    def test_default_viewer_and_observer(self):
        self.p['bindings'][USER]={'roles':['Viewer']}
        self.assertEqual(self.verify('/d4/'),200);self.assertEqual(self.verify('/d4/api/update','POST'),403)
        self.assertEqual(self.verify('/api/unknown'),403)
        for verb,path,code in [('GET','/api/fc27/cloud/automation',200),('GET','/d4/',403),('POST','/api/fc27/cloud/automation',403)]:
            self.assertEqual(rbac.authorize(self.p,'dot_fc_observer',verb,path),code)
    def test_role_migration_preserves_existing(self):
        for user in P['bindings']:
            if user=='dot_fc_observer':continue
            old=rbac.grant_matrix(P,user);new=rbac.grant_matrix(self.p,user)
            self.assertTrue(all(set(a)<=set(new.get(r,[])) for r,a in old.items()),user)
    def test_remove_roles_preserves_denies_and_clears_extra(self):
        self.p['bindings'][USER]['deny']=[{'resources':['d4'],'actions':['view']}]
        def mutate(portal,actor,note,fn,revision):
            fn(self.p);return 200,{}
        with patch.object(rbac,'load_policy',return_value=self.p),patch.object(iam_console,'_mutate',side_effect=mutate):
            self.assertEqual(iam_console._api_member_roles(None,'chenchao',{'subject':USER,'roles':[],'keep_extra_grants':False})[0],200)
        self.assertIn('deny',self.p['bindings'][USER]);self.assertNotIn('grants',self.p['bindings'][USER])
        self.assertEqual(self.verify('/dashboard/analytics/'),403)
if __name__=='__main__':unittest.main(verbosity=2)
