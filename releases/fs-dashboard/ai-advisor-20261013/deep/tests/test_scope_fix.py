import copy,json,unittest
from datetime import timedelta
from test_model_fix import load,ROOT
from test_deep import fixture,AT,model_response
analysis=load('scope_analysis',ROOT/'scope_fix/source/fc_deep_analysis.py')
model=load('scope_model',ROOT/'scope_fix/source/fc_deep_model.py')
publisher=load('scope_publisher',ROOT/'scope_fix/deploy/release_navigation.py')

def build():
    q,d,c=fixture();base=d['orders'][-1]
    d['backlog']=[]
    # Old open orders are NOT issues; the issues here are all young.
    for age,issue,site,terminal in [(200,False,'main',False)]*4+[(2,True,'main',False)]*2+[(300,True,'satellite',False),(300,True,'main',True)]:
        d['backlog'].append(dict(base,paid_at=(AT-timedelta(hours=age)).isoformat(),issue=issue,site_group=site,terminal=terminal))
    return analysis.build_evidence(q,d,c,AT)

class ScopeFix(unittest.TestCase):
    def test_populations_are_counted_independently(self):
        b=build()['backlog']
        self.assertEqual(b['main']['orders'],6);self.assertEqual(b['main']['issues'],2)
        self.assertEqual(b['age_bands']['over168h'],4);self.assertEqual(b['issue_age_bands']['over168h'],0)
        self.assertEqual(b['issue_age_bands']['under24h'],2)
        self.assertEqual(sum(b['issue_age_bands'].values()),b['main']['issues'])
    def test_summary_does_not_transfer_age_to_issues(self):
        s=build()['backlog']['verified_observation']
        self.assertIn('全部当前未结订单中，至少一周组数量最多且超过该群体一半',s)
        self.assertIn('其中的问题单子集中，不足一天组数量最多且超过该群体一半',s)
    def test_boundaries_unknown_and_empty(self):
        rows=[{'paid_at':(AT-timedelta(hours=n)).isoformat()} for n in (0,24,72,168,-1)]+[{'paid_at':None}]
        self.assertEqual(analysis.backlog_age_bands(rows,AT),{'under24h':1,'24to72h':1,'72to168h':1,'over168h':1,'unknown':2})
        self.assertEqual(analysis.age_observation(analysis.backlog_age_bands([],AT),'问题单'),'问题单为空')
    def test_ties_and_no_majority_not_exaggerated(self):
        b={'under24h':2,'24to72h':2,'72to168h':1,'over168h':0,'unknown':0}
        self.assertIn('并列最多',analysis.age_observation(b,'未结池'))
        b['under24h']=3
        self.assertIn('未超过该群体一半',analysis.age_observation(b,'未结池'))
    def test_model_cannot_publish_wrong_scope_or_ranking_as_fact(self):
        e=build();raw=model_response(e);body=json.loads(raw['choices'][0]['message']['content'])
        f=body['findings'][0];f['refs']=['backlog.current'];f['title']='问题单绝大多数超过一周';f['observation']='问题单按不足一天、一至三天、三至七天依次递减。'
        raw['choices'][0]['message']['content']=json.dumps(body)
        out=model.validate(raw,model.project(e))['findings'][0]
        self.assertEqual(out['observation'],e['backlog']['verified_observation'])
        self.assertEqual(out['fact_origin'],'server_verified_backlog_populations')
        self.assertEqual(out['action'],f['action']);self.assertNotIn('绝大多数',out['title'])
    def test_missing_population_cannot_silently_use_old_evidence(self):
        e=build();e['backlog'].pop('verified_observation');raw=model_response(e)
        body=json.loads(raw['choices'][0]['message']['content']);body['findings'][0]['refs']=['backlog.current'];raw['choices'][0]['message']['content']=json.dumps(body)
        with self.assertRaises(model.InvalidStatement):model.validate(raw,model.project(e))
    def test_projection_revision_and_no_private_orders(self):
        p=model.project(build());s=json.dumps(p)
        self.assertEqual(p['contract'],'fc-owner-analysis-v4');self.assertNotIn('PRIVATE_CUSTOMER_KEY',s)
        self.assertIn('issue_age_bands',s);self.assertIn('程序的verified_observation',model.messages(p)[0]['content'])
    def test_publisher_only_two_files_and_protects_peer(self):
        stage=ROOT/'scope_fix/deploy';m=json.loads((stage/'approved-manifest.json').read_text('utf-8'))
        self.assertEqual({r['target'] for r in publisher.validate(m,stage)},{'/opt/fs-exact-range-20261001/fc_deep_model.py','/opt/fs-exact-range-20261001/fc_deep_analysis.py'})
        bad=copy.deepcopy(m);bad['unchangedRequired']=[r for r in bad['unchangedRequired'] if not r['path'].endswith('/boss_insights.py')]
        with self.assertRaises(ValueError):publisher.validate(bad,stage)

if __name__=='__main__':unittest.main()
