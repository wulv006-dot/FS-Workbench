import copy,json,sys,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'source'))
import contract

def fixture():
    paths=[ROOT.parent/'evidence/live-index.html',ROOT.parent/'game-monitor-sop-20261022/source/index.html',ROOT.parent/'docs/planning/game-monitor-sop-20261022/evidence/repo/releases/fs-dashboard/game-monitor-sop-20261022/source/index.html']
    return next(p for p in paths if p.is_file()).read_bytes()

def request(before=None):
    before=before or fixture();data=contract.snapshot(before)['maplestory']['game']
    data['platform_pricing']['note']+=' Classic Windows/macOS 支持信息待当前官方版本复核（离线测试文本）。'
    return dict(schema=1,run_id='20261022T060000Z-1234abcd',base_sha256=contract.sha(before),summary='Offline test of a scoped platform note',updates={'maplestory':{'game':data}},
        sources=[dict(game='maplestory',url='https://www.nexon.com/maplestory/news/general/46506/grand-launch-release-notes',retrieved_at=datetime.now(timezone.utc).isoformat(),version='Classic test fixture',claim='Offline fixture: validate the data-only delivery mechanism.',kind='official')])

class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.before=fixture()
    def test_scoped_change_preserves_other_games_and_executable_page(self):
        r=request(self.before);after,proof=contract.build(self.before,r)
        old=contract.snapshot(self.before);new=contract.snapshot(after)
        self.assertEqual(proof['changed'],['maplestory:game'])
        for key in old:
            if key!='maplestory':self.assertEqual(old[key],new[key])
        self.assertIn('Classic Windows/macOS',after.decode())
        self.assertEqual(self.before.count(b'<script'),after.count(b'<script'))
    def test_noop_is_identified_without_a_publication(self):
        r=request(self.before);r['updates']['maplestory']['game']=contract.snapshot(self.before)['maplestory']['game']
        after,proof=contract.build(self.before,r);self.assertEqual(after,self.before);self.assertEqual(proof['changed'],[])
    def test_wrong_live_baseline_is_refused(self):
        r=request(self.before);r['base_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'baseline'):contract.build(self.before,r)
    def test_identity_and_events_cannot_change(self):
        for field,value in [('owner','new'),('events',[]),('key','new-game')]:
            r=request(self.before);r['updates']['maplestory']['game'][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'identity_or_events'):contract.build(self.before,r)
    def test_html_and_template_execution_are_refused(self):
        for value in ['<img src=x onerror=alert(1)>','${process.env.TOKEN}','javascript:alert(1)']:
            r=request(self.before);r['updates']['maplestory']['game']['intro']=value
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'executable_content'):contract.build(self.before,r)
    def test_prototype_keys_are_refused(self):
        r=request(self.before);r['updates']['maplestory']['game']['platform_pricing']['__proto__']={'x':'y'}
        with self.assertRaisesRegex(ValueError,'unsafe_property'):contract.build(self.before,r)
    def test_sources_must_be_https_versioned_and_current(self):
        mutations=[('url','http://nexon.com/'),('version',''),('retrieved_at',datetime.now(timezone.utc).replace(year=2020).isoformat()),('retrieved_at',(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())]
        for field,value in mutations:
            r=request(self.before);r['sources'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):contract.build(self.before,r)
    def test_every_updated_game_needs_source_coverage(self):
        r=request(self.before);r['sources'][0]['game']='poe2'
        with self.assertRaisesRegex(ValueError,'source_scope'):contract.build(self.before,r)
    def test_visible_draft_and_full_columns_are_required(self):
        data=contract.snapshot(self.before)['maplestory'];data['playbook']['tips'][0]='unapproved recommendation'
        r=request(self.before);r['updates']['maplestory']['playbook']=data['playbook']
        with self.assertRaisesRegex(ValueError,'draft_contract'):contract.build(self.before,r)
    def test_missing_columns_are_refused(self):
        data=contract.snapshot(self.before)['maplestory'];data['guide']['ops']=[]
        r=request(self.before);r['updates']['maplestory']['guide']=data['guide']
        with self.assertRaisesRegex(ValueError,'guide_counts'):contract.build(self.before,r)
    def test_duplicate_json_request_keys_are_refused(self):
        with self.assertRaisesRegex(ValueError,'duplicate_json'):contract.strict_json('{"schema":1,"schema":2}')
    def test_submitted_candidate_is_rebuilt_and_bound_to_proof(self):
        folder=ROOT/'candidate'
        if folder.exists():
            fixture_request=contract.strict_json((folder/'request.json').read_bytes())
            fixture_time=max(datetime.fromisoformat(s['retrieved_at'].replace('Z','+00:00')) for s in fixture_request['sources'])+timedelta(seconds=1)
            class FixtureClock(datetime):
                @classmethod
                def now(cls,tz=None):return fixture_time
            with patch.object(contract,'datetime',FixtureClock):
                proof=contract.verify_candidate(folder)
            self.assertTrue(proof['games'])
        else:self.assertEqual(len(contract.snapshot(self.before)),30)


class StaticFill(unittest.TestCase):
    def test_github_large_file_reads_the_same_verified_blob(self):
        import importlib.util,base64
        from unittest.mock import Mock
        files=[ROOT.parent/'hermes-ops-20261020/source/github_api.py',ROOT/'source/github_api.py']
        path=next(p for p in files if p.is_file())
        spec=importlib.util.spec_from_file_location('large_file_github',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        client=object.__new__(module.GitHub)
        raw=b'large fixture content';identity='a'*40
        client.request=Mock(side_effect=[{'encoding':'none','sha':identity,'size':2000000},{'encoding':'base64','content':base64.b64encode(raw).decode()}])
        self.assertEqual(client.file('candidate/index.html','fixed-ref'),raw)
        self.assertEqual(client.request.call_args_list[1].args,('GET','/git/blobs/'+identity))
        client.request=Mock(return_value={'content':base64.b64encode(raw).decode()+'\n'})
        self.assertEqual(client.file('candidate/index.html','fixed-ref'),raw)
        client.request=Mock(return_value={'encoding':'none','sha':'../../outside'})
        with self.assertRaisesRegex(ValueError,'blob_identity'):client.file('candidate/index.html','fixed-ref')
    def test_fc_aion_intelligence_uses_actual_rendered_literals(self):
        rows=contract.slots(fixture().decode())
        self.assertIn('cats',rows['ea-sports-fc']['intel'][2])
        self.assertIn('cats',rows['aion2']['intel'][2])
    def test_legacy_intelligence_rejects_string_items(self):
        data=contract.snapshot(fixture())['maplestory']
        data['intel']={'items':{key:['one','two'] for key in contract.DIMS}}
        contract.sop(data)
        data['intel']['items']['version']='wrong shape'
        with self.assertRaisesRegex(ValueError,'intelligence_items'):contract.sop(data)
    def test_all_29_static_edits_rebuild_with_exact_two_renderer_fixes(self):
        folder=ROOT/'static-fill-20261022'
        if not folder.exists():folder=ROOT.parent/'static-fill'
        self.assertTrue(folder.is_dir(),'static fill fixture missing')
        before=(folder/'before.html').read_bytes();current=before.decode()
        patches=json.loads((folder/'renderer-patch.json').read_text(encoding='utf-8'))
        self.assertEqual(len(patches),2)
        self.assertEqual(patches[0],['  if(!isSA)return null;','  if(!isSA && !SA_INTEL[g.key])return null;'])
        self.assertEqual(patches[1],['items:pts.slice(),times:hasReal?realTimes:[]','items:Array.isArray(pts)?pts.slice():String(pts).split(" · "),times:hasReal?realTimes:[]'])
        for old,new in patches:self.assertEqual(current.count(old),1);current=current.replace(old,new,1)
        current=current.encode();games=[]
        requests=json.loads((folder/'requests.json').read_text(encoding='utf-8'))
        fixture_time=max(datetime.fromisoformat(s['retrieved_at'].replace('Z','+00:00')) for r in requests for s in r['sources'])+timedelta(seconds=1)
        for request in requests:
            current,proof=contract.build(current,request,now=fixture_time);games.extend(proof['games'])
        self.assertEqual(len(games),29);self.assertEqual(len(set(games)),29)
        self.assertNotIn('maplestory',games)
        self.assertEqual(current,(folder/'index.html').read_bytes())
        old,new=contract.snapshot(before),contract.snapshot(current)
        self.assertEqual(old['maplestory'],new['maplestory'])
        for key in old:
            for field in set(old[key]['game'])-{'intro','official_site'}:self.assertEqual(old[key]['game'][field],new[key]['game'][field])

if __name__=='__main__':unittest.main()
