"""Synthetic wiring checks: registered source, task freeze and useful review output."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import json
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
MARKET=ROOT.parent/'hermes-market-sources-20261015'
if not MARKET.exists():MARKET=ROOT.parent/'hermes_market_sources_20261015'
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'baseline'),str(MARKET/'source'),str(MARKET/'deps')]
from research import ResearchBook,RESEARCH_NAMES,tool_schemas
from fs_evidence import SourcePins,build_book
from report_semantics import intelligence
from report_delivery import attach_review

STAMP='2026-01-15T12:00:00+00:00'
QUERY={'profile':'FC27','start':'2026-01-08','end':'2026-01-14'}
DATA={'snapshot_id':'fc-detail-synthetic','as_of':STAMP,'coverage':{'period':QUERY},'orders':[],'backlog':[]}
URL='https://www.ea.com/games/ea-sports-fc/fc-27/news/example'

class IntegrationTests(unittest.TestCase):
    def test_discovery_schema_and_frozen_official_evidence(self):
        calls=[]
        def read(q):
            calls.append(q)
            return {'http_status':200,'status':'partial','captured_at':STAMP,
                    'documents':[{'source_url':URL,'observed_at':STAMP,'text':'Official update content.'}],
                    'source_snapshot_id':'official_synthetic'}
        book=ResearchBook(DATA,{},QUERY,official=SourcePins().wrap(read,'official'))
        schemas=tool_schemas();names=[s['function']['name'] for s in schemas]
        self.assertEqual(len(names),len(set(names)))
        self.assertEqual(len(names),len(RESEARCH_NAMES))
        schema=next(s['function']['parameters'] for s in schemas if s['function']['name'].endswith('fc_query_official_intelligence'))
        self.assertFalse(schema['additionalProperties']);self.assertNotIn('url',schema['properties'])
        a=book.call('fc.query_official_intelligence',QUERY);b=book.call('fc.query_official_intelligence',QUERY)
        self.assertEqual(a['evidence_id'],b['evidence_id']);self.assertEqual(len(calls),1)
        catalog=book.call('fc.get_data_catalog',{})['data']
        self.assertEqual(catalog['external_intelligence']['status'],'on_demand')
        self.assertIn('quality target',catalog['report_constraints']['review_standard'])
        result={'period':QUERY,'intel':[{'title':'Update','url':URL,'retrieved_at':STAMP,
                'fact':'Observed announcement','evidence_ids':[a['evidence_id']]}]}
        accepted,pending,_=intelligence(result,book.evidence)
        self.assertEqual(len(accepted),1);self.assertEqual(pending,[])

    def test_book_factory_pending_then_frozen_and_live_off_switch(self):
        calls=[]
        def reader(q):calls.append(q);return {'http_status':200,'status':'available','captured_at':STAMP,'documents':[]}
        history=SimpleNamespace(index={},read=lambda q:{})
        detail=SimpleNamespace(config={'enabled':True},pool=None)
        source_readers=SimpleNamespace(admin_read=lambda q:None,order_read=lambda *a:None)
        with patch('fs_evidence.source_capture',return_value=(DATA,{})),patch('fs_evidence.load_bundle',return_value={}),\
             patch('fs_evidence.ReportHistory',return_value=history),\
             patch.dict(sys.modules,{'admin_order_capabilities_20261014.fs_reader':source_readers}),\
             patch('admin_order_capabilities_20261014.provider.CapabilityProvider'),\
             patch('official_intelligence.OfficialReader',return_value=reader):
            book=build_book(detail,None,lambda q:(200,{}),lambda:{},QUERY['start'],QUERY['end'],'.','owner')
            for _ in range(100):
                result=book.call('fc.query_official_intelligence',QUERY)
                if result['data'].get('status')=='available':break
                time.sleep(.005)
            self.assertEqual(result['data']['status'],'available')
            self.assertEqual(len(calls),1)
            self.assertEqual(book.call('fc.query_official_intelligence',QUERY)['evidence_id'],result['evidence_id'])
            detail.config['enabled']=False
            self.assertEqual(book.call('fc.query_official_intelligence',QUERY)['data']['reason'],'fc_detail_disabled')

    def test_warning_does_not_prefix_or_suppress_practical_summary(self):
        book=SimpleNamespace(target=QUERY,capture_id=DATA['snapshot_id'],evidence={})
        content={'quality_review':{'status':'warnings_visible','issues':[{'severity':'warning'}]},
                 'evidence_constraints':{},'payment':[],'executive':{'summary':'优先核查重点平台，局部缺口保留。'}}
        with patch('boss_projection.project',return_value=content):
            result=attach_review({'summary':'original','limitations':[]},book)
        self.assertEqual(result['summary'],content['executive']['summary'])
        self.assertEqual(result['business_review_status'],'warnings_visible')
        self.assertNotIn('业务未放行',''.join(result['limitations']))

    def test_skill_integrity_and_user_review_target(self):
        source=ROOT/'source';manifest=json.loads((source/'skills/manifest.json').read_text('utf-8'))
        self.assertEqual(manifest['permissions_added'],[])
        self.assertEqual(manifest['version'],'0.9.0-practical-research')
        for row in manifest['files']:
            p=source/row['path']
            if p.exists():self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),row['sha256'])
        text=(source/'skills/fs-fc-operations-analysis/SKILL.md').read_text('utf-8')
        for term in ('反转条件','合理推断','fc.query_market_snapshot','fc.query_official_intelligence'):
            self.assertIn(term,text)
        from skill_bundle import prompt
        rendered=prompt({'version':'test','sha256':'0'*64,'text':'method'}, {'question':'example'})
        for term in ('通俗中文','90%以上','局部未核平','反转条件'):
            self.assertIn(term,rendered[:400])

if __name__=='__main__':unittest.main()
