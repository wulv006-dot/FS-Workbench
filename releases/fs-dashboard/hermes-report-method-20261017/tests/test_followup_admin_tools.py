import ast, json, re, threading, unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/'source/continuation.py'

class Base:
 def __init__(self,*args,**kwargs):self._lock=threading.RLock();self.capture_id=args[0]['snapshot_id']
 def register(self,name,args,data,*unused):return {'data':data,'query':args}

class AdminFrozenTools(unittest.TestCase):
 def setUp(self):
  nodes=[n for n in ast.parse(SOURCE.read_text('utf-8')).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))]
  self.ns=dict(ResearchBook=Base,RESEARCH_NAMES={'fc.query_product_orders','fc.query_discount_analysis','fc.query_es_order_structure'},TOOLS=(),deepcopy=deepcopy,datetime=datetime,timezone=timezone,json=json,re=re,encoded=lambda x:json.dumps(x,sort_keys=True,separators=(',',':')))
  exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),self.ns)
 def evidence(self,source,query,ref='a',state='available'):
  return dict(evidence_id='ev_'+ref*24,project='FC27',analysis_anchor_id='synthetic-snapshot',snapshot_id='synthetic-snapshot',captured_at='2026-10-18T00:00:00+00:00',source=source,query=query,data={'status':state,'sentinel':'original-public-aggregate'})
 def book(self,values):
  task={'spec':{'snapshot_id':'synthetic-snapshot','period':{'start':'2026-10-01'}},'end':'2026-10-17','request_id':'synthetic-parent'}
  return self.ns['FrozenEvidenceBook'](task,{v['evidence_id']:v for v in values},{})
 def test_product_default_parameters_reuse_original_without_read(self):
  q=dict(profile='FC27',model_id=123,start='2026-10-17',end='2026-10-17',platform='ALL',max_pages=20)
  e=self.evidence('Admin verified site/model products → order.Order/index',q);b=self.book([e])
  args={k:v for k,v in q.items() if k not in ('platform','max_pages')}
  self.assertEqual(b.call('fc.query_product_orders',args),e)
  self.assertNotIn('platform',args)
  self.assertEqual(b.trace[-1]['basis'],'cached_original_source_evidence')
 def test_discount_public_arguments_match_normalized_archive_query(self):
  q=dict(profile='FC27',start='2026-10-01',end='2026-10-16',group_by='discount_new_customer',status='all')
  e=self.evidence('Admin ES订单导出：原范围文件集合结构；非原生主盘',q);b=self.book([e])
  args={k:v for k,v in q.items() if k not in ('group_by','status')}
  self.assertEqual(b.call('fc.query_discount_analysis',args),e)
  self.assertEqual(b.call('fc.query_es_order_structure',q),e)
 def test_missing_product_stays_unavailable_and_no_new_capture(self):
  q=dict(profile='FC27',model_id=123,start='2026-10-17',end='2026-10-17',platform='ALL',max_pages=20)
  b=self.book([self.evidence('Admin verified site/model products → order.Order/index',q)])
  r=b.call('fc.query_product_orders',dict(q,model_id=456))
  self.assertEqual(r['data']['reason'],'not_in_frozen_continuation_evidence')
  self.assertFalse(r['data']['new_source_reads'])
 def test_terminal_product_beats_pending_and_unknown_source_rejected(self):
  q=dict(profile='FC27',model_id=123,start='2026-10-17',end='2026-10-17',platform='ALL',max_pages=20)
  ready=self.evidence('Admin verified site/model products → order.Order/index',q)
  pending=self.evidence(ready['source'],q,'b','pending')
  self.assertEqual(self.book([ready,pending]).call('fc.query_product_orders',q),ready)
  with self.assertRaises(ValueError):self.ns['evidence_tool'](self.evidence('unregistered-source',{}))

if __name__=='__main__':unittest.main()
