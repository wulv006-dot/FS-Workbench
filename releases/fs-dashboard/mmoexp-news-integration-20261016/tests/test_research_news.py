"""Synthetic shared-news wiring; no network, server, model or production writes."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def sibling(name):
    path=ROOT/name.replace('_','-')
    return path if path.exists() else ROOT/name

MARKET=sibling('hermes_market_sources_20261015')
INTEGRATION=sibling('hermes_fs_research_integration_20261015')
WEEKLY=sibling('hermes_weekly_upgrade_20261015')
BASE=MARKET/'deps' if (MARKET/'deps').exists() else sibling('hermes_fc_pilot_20261013')
sys.path[:0]=[str(HERE.parent/'source'),str(WEEKLY/'data'),str(INTEGRATION/'source'),str(MARKET/'source'),str(BASE)]
import fs_evidence
from research import ResearchBook, RESEARCH_NAMES, tool_schemas

QUERY={'profile':'FC27','start':'2026-10-05','end':'2026-10-11'}
STAMP='2026-10-16T00:05:00+08:00'
SOURCE='MMOEXP News／主站SEO资讯（非游戏官方公告）'
DATA={'snapshot_id':'fc-detail-news-test','as_of':STAMP,'coverage':{'period':QUERY},'orders':[],'backlog':[]}

def reply(status='available'):
    return {'http_status':200,'status':status,'captured_at':STAMP,'source_type':'mmoexp_seo',
            'documents':[{'source_url':'https://www.mmoexp.com/News/synthetic-fc27.html',
                          'observed_at':STAMP,'published_at':'2026-10-10','event_date':None,
                          'source_type':'mmoexp_seo','text':'Synthetic SEO game news; not an official announcement.'}]}


class ResearchNewsTests(unittest.TestCase):
    def test_schema_is_distinct_and_accepts_only_fixed_query_fields(self):
        schemas=tool_schemas()
        names=[item['function']['name'] for item in schemas]
        self.assertEqual(len(names),len(set(names)))
        self.assertEqual(len(names),len(RESEARCH_NAMES))
        schema=next(item['function'] for item in schemas if item['function']['name']=='mcp__fcro__fc_query_game_news')
        self.assertEqual(set(schema['parameters']['properties']),{'profile','start','end'})
        self.assertEqual(schema['parameters']['properties']['profile']['enum'],['FC27'])
        self.assertFalse(schema['parameters']['additionalProperties'])
        self.assertIn('not official',schema['description'])
        self.assertIn('mcp__fcro__fc_query_official_intelligence',names)

    def test_catalog_labels_seo_independently_of_official(self):
        book=ResearchBook(DATA,{},QUERY,news=lambda q:reply())
        catalog=book.call('fc.get_data_catalog',{})['data']
        self.assertEqual(catalog['game_news']['tool'],'fc.query_game_news')
        self.assertEqual(catalog['game_news']['scope'],SOURCE)
        self.assertEqual(catalog['game_news']['status'],'shared_snapshot_readonly')
        self.assertTrue(catalog['game_news']['no_new_collection'])
        self.assertTrue(catalog['game_news']['no_network'])
        self.assertEqual(catalog['external_intelligence']['status'],'not_wired')

    def test_evidence_is_seo_and_does_not_call_official(self):
        calls=[]
        def official(q):
            self.fail('SEO query must never call the official collector')
        def news(q):calls.append(deepcopy(q));return reply()
        book=ResearchBook(DATA,{},QUERY,news=news,official=official)
        result=book.call('fc.query_game_news',QUERY)
        self.assertEqual(calls,[QUERY])
        self.assertEqual(result['source'],SOURCE)
        self.assertEqual(result['captured_at'],STAMP)
        self.assertIsNone(result['data']['documents'][0]['event_date'])
        self.assertEqual(result['data']['source_type'],'mmoexp_seo')
        self.assertEqual(book.trace[-1]['tool'],'fc.query_game_news')

    def test_default_callback_is_unavailable_not_official_fallback(self):
        book=ResearchBook(DATA,{},QUERY,official=lambda q:self.fail('unexpected official read'))
        self.assertEqual(book.call('fc.get_data_catalog',{})['data']['game_news']['status'],'not_wired')
        result=book.call('fc.query_game_news',QUERY)
        self.assertEqual(result['data'],{'status':'not_available','reason':'game_news_adapter_missing'})
        self.assertEqual(result['source'],SOURCE)

    def test_invalid_dates_profiles_and_arbitrary_source_fields_are_rejected(self):
        calls=[];book=ResearchBook(DATA,{},QUERY,news=lambda q:calls.append(q))
        for extra in ({'profile':'FC26'},{'start':'2026-02-30'},{'end':'2026-01-01'},
                      {'url':'https://other.test/'},{'path':'/etc/passwd'},{'end':'2027-10-11'}):
            with self.subTest(extra=extra),self.assertRaises((ValueError,TypeError)):
                book.call('fc.query_game_news',{**QUERY,**extra})
        self.assertEqual(calls,[])

    def test_first_shared_reply_is_frozen_without_recollection(self):
        calls=[]
        def reader(q):calls.append(q);return reply()
        book=ResearchBook(DATA,{},QUERY,news=fs_evidence.SourcePins().wrap(reader,'MMOEXP-SEO-shared-news'))
        first=book.call('fc.query_game_news',QUERY)
        first['data']['documents'][0]['text']='changed by caller'
        second=book.call('fc.query_game_news',QUERY)
        self.assertEqual(len(calls),1)
        self.assertNotEqual(second['data']['documents'][0]['text'],'changed by caller')
        self.assertEqual(first['evidence_id'],second['evidence_id'])

    def test_stale_reply_is_labelled_and_not_replaced_by_official(self):
        book=ResearchBook(DATA,{},QUERY,news=lambda q:reply('stale'),official=lambda q:self.fail('unexpected fallback'))
        self.assertEqual(book.call('fc.query_game_news',QUERY)['data']['status'],'stale')

    def test_factory_preserves_live_off_barrier_before_pinned_reply(self):
        detail=SimpleNamespace(config={'enabled':True},pool=None)
        history=SimpleNamespace(index={},read=lambda q:{})
        readers=SimpleNamespace(admin_read=lambda q:None,order_read=lambda *a:None)
        calls=[]
        def news(q):calls.append(q);return reply()
        with patch('fs_evidence.source_capture',return_value=(DATA,{})),patch('fs_evidence.load_bundle',return_value={}),\
             patch('fs_evidence.ReportHistory',return_value=history),patch('fs_evidence.shared_news',side_effect=news),\
             patch.dict(sys.modules,{'admin_order_capabilities_20261014.fs_reader':readers}),\
             patch('admin_order_capabilities_20261014.provider.CapabilityProvider'):
            book=fs_evidence.build_book(detail,None,lambda q:(200,{}),lambda:{},QUERY['start'],QUERY['end'],'.','owner')
            first=book.call('fc.query_game_news',QUERY)
            self.assertEqual(first['data']['status'],'available')
            self.assertEqual(book.call('fc.query_game_news',QUERY)['evidence_id'],first['evidence_id'])
            self.assertEqual(len(calls),1)
            detail.config['enabled']=False
            self.assertEqual(book.call('fc.query_game_news',QUERY)['data']['reason'],'fc_detail_disabled')
            self.assertEqual(len(calls),1)

    def test_fixed_lazy_adapter_loads_only_operator_path(self):
        before=list(sys.path)
        module=SimpleNamespace()
        def execute(target):target.read_shared=lambda q:reply()
        spec=SimpleNamespace(loader=SimpleNamespace(exec_module=execute))
        with patch('importlib.util.spec_from_file_location',return_value=spec) as factory,\
             patch('importlib.util.module_from_spec',return_value=module):
            self.assertEqual(fs_evidence.shared_news(QUERY)['status'],'available')
        factory.assert_called_once_with('fs_mmoexp_shared_news','/opt/fs-boss-workspaces/backend/mmoexp_news.py')
        self.assertEqual(sys.path,before)

    def test_missing_operator_adapter_fails_closed(self):
        with patch('importlib.util.spec_from_file_location',side_effect=FileNotFoundError):
            self.assertEqual(fs_evidence.shared_news(QUERY),{'http_status':503,'status':'not_available','reason':'shared_news_unavailable'})

    def test_dynamic_wire_registry_and_proxy_reach_new_tool(self):
        from runs_contract import SEMANTIC_TOOLS, WIRE_TOOLS
        from proxy_gateway import ScopedTools, schemas
        name='mcp__fcro__fc_query_game_news'
        self.assertIn(name,WIRE_TOOLS)
        self.assertEqual(SEMANTIC_TOOLS[WIRE_TOOLS.index(name)],'fc.query_game_news')
        self.assertEqual({schema['function']['name'] for schema in schemas()},set(WIRE_TOOLS))
        book=ResearchBook(DATA,{},QUERY,news=lambda q:reply(),official=lambda q:self.fail('No official fallback'))
        tasks=SimpleNamespace(get=lambda *a:{'state':'RUNNING','lease':'synthetic','spec':{'snapshot_id':book.capture_id}})
        result=ScopedTools(tasks,book,lambda:0).call('owner','task','synthetic',name,QUERY)
        self.assertEqual(result['data']['source'],SOURCE)
        self.assertEqual(result['data']['data']['source_type'],'mmoexp_seo')


if __name__=='__main__':unittest.main()
