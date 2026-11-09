from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parent/'source'))
from campaign_evidence import collect_player_evidence

AT=datetime(2026,11,9,5,tzinfo=timezone.utc)

class Client:
    def __init__(self):self.fetched=[];self.queries=[]
    def search(self,query):
        self.queries.append(query)
        return {'results':[
            {'url':'https://www.futbin.com/27/player/1/test','title':'FC 27 Player guide'},
            {'url':'https://www.reddit.com/r/EASportsFC/comments/abc/test/','title':'Player discussion'},
            {'url':'https://127.0.0.1/private','title':'Untrusted'},
            {'url':'https://www.futbin.com@evil.example/player','title':'Untrusted'}]}
    def fetch(self,url):
        self.fetched.append(url)
        return {'content':'FC 27 Aleix García Serrano has useful midfield links. Community opinion, not a verified chemistry calculation.'}

class EvidenceTests(unittest.TestCase):
    def test_fetches_only_allowed_sources_and_freezes_real_text_and_hash(self):
        client=Client();result=collect_player_evidence([{'name':'Aleix García Serrano','model_id':'123'}],AT,client)
        self.assertEqual(result['status'],'available');self.assertEqual(len(client.fetched),2)
        self.assertEqual(result['coverage']['categories'],['social','vertical'])
        self.assertEqual(len(result['sources']),2);self.assertIn('发布时间未核实',result['context'])
        self.assertTrue(all(len(row['content_sha256'])==64 for row in result['documents']))
        self.assertTrue(all(row['observed_at']==AT.isoformat() for row in result['sources']))

    def test_search_snippets_and_unrelated_body_do_not_become_evidence(self):
        client=Client();client.fetch=lambda url:{'content':'An unrelated FC 26 player.'}
        result=collect_player_evidence([{'name':'Aleix García Serrano','model_id':'123'}],AT,client)
        self.assertEqual(result['status'],'unavailable');self.assertEqual(result['sources'],[])
        self.assertTrue(result['coverage']['failures'])

    def test_failed_source_keeps_success_and_never_exports_exception_secrets(self):
        client=Client();old=client.fetch
        def fetch(url):
            if 'reddit.com' in url:raise RuntimeError('Bearer secret-value')
            return old(url)
        client.fetch=fetch
        result=collect_player_evidence([{'name':'Aleix García Serrano','model_id':'123'}],AT,client)
        self.assertEqual(result['status'],'partial');self.assertEqual(len(result['sources']),1)
        self.assertNotIn('secret-value',str(result));self.assertNotIn('Bearer',str(result))

    def test_evidence_keeps_player_association_and_no_duplicate_fetches(self):
        client=Client();result=collect_player_evidence([{'name':'Aleix García Serrano','model_id':'123'},{'name':'Other Player','model_id':'124'}],AT,client)
        self.assertEqual(result['status'],'partial');self.assertEqual(len(client.fetched),2)
        self.assertEqual(result['documents'][0]['model_ids'],['123'])

    def test_invalid_scope_is_rejected_before_network(self):
        client=Client()
        for players in ([],[{'name':'x','model_id':'../bad'}],[{'name':'x','model_id':'1'}]*301):
            with self.assertRaises(ValueError):collect_player_evidence(players,AT,client)
        self.assertEqual(client.fetched,[])

    def test_full_newest_pool_uses_grouped_market_queries_with_original_total_budget(self):
        client=Client();players=[{'name':'Candidate '+str(i),'model_id':str(i+1)} for i in range(31)]
        client.fetch=lambda url:{'content':'FC 27 '+', '.join(p['name'] for p in players)+' market discussion, not seller sales.'}
        result=collect_player_evidence(players,AT,client)
        self.assertEqual(len(client.queries),12);self.assertTrue(any('market price popularity' in q for q in client.queries));self.assertTrue(all(' OR ' in q for q in client.queries))
        for player in players:self.assertTrue(any('"'+player['name']+'"' in q for q in client.queries))
        self.assertEqual(result['coverage']['players'],31);self.assertEqual(len(result['documents'][0]['model_ids']),31)
        self.assertIn('外部热度不是我方销量',result['context']);self.assertLessEqual(len(result['sources']),8)

if __name__=='__main__':unittest.main()
