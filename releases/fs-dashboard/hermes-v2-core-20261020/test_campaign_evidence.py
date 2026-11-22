from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parent/'source'))
from campaign_evidence import collect_player_evidence, collect_weekly_evidence
from campaign_public_sources import EA_NEWS_INDEX

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
    def test_weekly_reuses_complete_primary_evidence_without_scrapling(self):
        players=[dict(name='Aleix García Serrano/90/CM/Test',model_id='123')]
        client=Client()
        def read(_):
            self.fail('Complete research must not start a Scrapling request')
        result=collect_weekly_evidence(players,AT,source_limit=20,context_limit=7000,
                                      primary=lambda rows,at:collect_player_evidence(rows,at,client),read=read)
        self.assertEqual(result['status'],'available')
        self.assertNotIn('scrapling',result['coverage'])

    def test_weekly_keeps_original_sources_and_only_passes_matching_card_versions(self):
        players=[dict(name='Aleix García Serrano/90/CM/Test',model_id='123')]
        client=Client()
        bin_url='https://www.futbin.com/27/player/1/test'
        gg_url='https://www.fut.gg/players/123-aleix-garcia-serrano/27-456/'
        news=EA_NEWS_INDEX+'/fc-27-bf-thunderstruck'
        search=client.search
        client.search=lambda query:{'results':search(query)['results']+[dict(url=gg_url)]}
        original_fetch=client.fetch
        client.fetch=lambda url:original_fetch(url) if url==bin_url else dict(content='FC 26')
        data={
            EA_NEWS_INDEX:('ea_news_index',dict(article_url=news)),
            bin_url:('futbin_card',dict(title='Aleix García Serrano Test 91',usage='23%')),
            gg_url:('futgg_card',dict(title='Aleix García Serrano Test 90',games_played='1,234')),
            news:('ea_news',dict(title='Thunderstruck',published_at='2026-11-20',article_summary='Official event article.')),
        }
        calls=[]
        def read(request):
            calls.append(request)
            return dict(sources=[
                dict(url=url,source_kind=data[url][0],status='observed',fetched_at=AT.isoformat(),
                     fields={key:dict(value=value,selector='fixture selector') for key,value in data[url][1].items()})
                for url in request['urls']])
        result=collect_weekly_evidence(players,AT,source_limit=20,context_limit=7000,
                                      primary=lambda rows,at:collect_player_evidence(rows,at,client),read=read)
        self.assertEqual([call['urls'] for call in calls],[[EA_NEWS_INDEX,bin_url,gg_url],[news]])
        self.assertEqual([source['url'] for source in result['sources']],[bin_url,gg_url,news])
        self.assertIn('games_played: 1,234',result['context'])
        self.assertNotIn('23%',result['context'])
        self.assertEqual(result['coverage']['scrapling']['sources'][1]['matched_model_ids'],[])
        self.assertEqual(result['coverage']['scrapling']['sources'][2]['matched_model_ids'],['123'])

    def test_scrapling_unavailable_preserves_original_research_and_records_attempt(self):
        client=Client()
        client.fetch=lambda url:dict(content='FC 26')
        def read(_):
            raise TimeoutError('private request detail')
        result=collect_weekly_evidence([dict(name='Aleix García Serrano/90/CM/Test',model_id='123')],AT,
                                      source_limit=20,context_limit=7000,
                                      primary=lambda rows,at:collect_player_evidence(rows,at,client),read=read)
        self.assertEqual(result['status'],'unavailable')
        self.assertEqual(result['coverage']['scrapling']['error'],'public_source_worker_unavailable')
        self.assertEqual(result['coverage']['scrapling']['sources'][0]['url'],EA_NEWS_INDEX)
        self.assertEqual(result['coverage']['scrapling']['sources'][0]['status'],'worker_unavailable')
        self.assertTrue(result['coverage']['scrapling']['sources'][0]['attempted_at'])
        self.assertNotIn('private request detail',str(result))

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
        self.assertEqual(len(client.queries),12);self.assertTrue(any('market site:' in q for q in client.queries));self.assertTrue(any(' OR ' in q for q in client.queries))
        for player in players:self.assertTrue(any('"'+player['name']+'"' in q for q in client.queries))
        self.assertEqual(result['coverage']['players'],31);self.assertEqual(len(result['documents'][0]['model_ids']),31)
        self.assertIn('外部热度不是我方销量',result['context']);self.assertLessEqual(len(result['sources']),8)

    def test_installed_search_128_character_contract_keeps_full_names_and_pool_coverage(self):
        client=Client();search=client.search
        def bounded_search(query):
            if len(query.strip())>128:raise ValueError('invalid_search_query')
            return search(query)
        client.search=bounded_search
        players=[{'name':'Candidate Full Name '+str(i),'model_id':str(i+1)} for i in range(31)]
        client.fetch=lambda url:{'content':'FC 27 '+', '.join(p['name'] for p in players)+' market discussion.'}
        result=collect_player_evidence(players,AT,client)
        self.assertEqual(len(client.queries),12)
        self.assertTrue(all(len(q.strip())<=128 for q in client.queries))
        self.assertTrue(all(any('"'+p['name']+'"' in q for q in client.queries) for p in players))
        self.assertGreater(result['coverage']['verified_documents'],0)
        self.assertTrue(any('market' in q for q in client.queries));self.assertTrue(any('site:reddit.com' in q or 'site:x.com' in q for q in client.queries))

    def test_name_and_query_budgets_are_explicit_without_silently_truncating_names(self):
        client=Client();players=[{'name':'Very long full player name '+str(i)+'x'*60,'model_id':str(i+1)} for i in range(31)]
        result=collect_player_evidence(players,AT,client)
        self.assertLessEqual(len(client.queries),12);self.assertTrue(all(len(q)<=128 for q in client.queries))
        self.assertIn('research_query_budget',result['coverage']['failures'])
        self.assertIn('coverage_partial:31',result['coverage']['failures'])
        client=Client();result=collect_player_evidence([{'name':'x'*120,'model_id':'1'}],AT,client)
        self.assertEqual(client.queries,[]);self.assertIn('research_query_name_budget',result['coverage']['failures'])

if __name__=='__main__':unittest.main()
