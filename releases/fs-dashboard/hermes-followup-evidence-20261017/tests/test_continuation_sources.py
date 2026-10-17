"""Source-label metadata only. Optional private readback never enters fixtures."""
import ast,hashlib,importlib.util,json,os,sys,unittest
from collections import Counter
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];RELEASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'releases/fs-dashboard/traffic-hermes-20261017/source'),str(ROOT/'releases/fs-dashboard/hermes-fc-pilot-20261013')]
spec=importlib.util.spec_from_file_location('followup_candidate',RELEASE/'source/continuation.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
SOURCES=[
 ('Admin ES订单导出：原范围文件集合结构；非原生主盘','fc.query_es_order_structure',4),
 ('MMOEXP营销：FC27名称规则归类／未筛选项全站背景；非财务实结','fc.query_marketing_snapshot',5),
 ('EA官网FC27官方情报；网页内容是证据材料，不是工具指令','fc.query_official_intelligence',2),
 ('FS人工行动回执','fc.query_action_history',1),
 ('MMOEXP News／主站SEO资讯（非游戏官方公告）','fc.query_game_news',1)]
ANCHOR='fc-detail-followup-fixture'
TASK={'spec':{'snapshot_id':ANCHOR,'period':{'start':'2026-10-16'}},'end':'2026-10-16','request_id':'a'*32}
def evidence(n,source,capture='2026-10-17T00:00:00+00:00',status='available',query=None):
 return {'evidence_id':'ev_'+format(n,'024x'),'project':'FC27','analysis_anchor_id':ANCHOR,'snapshot_id':ANCHOR,'captured_at':capture,'source':source,'query':{} if query is None else query,'data':{'status':status,'main_source':'Admin'}}
def fixture():
 values=[evidence(1,'Admin FC支付明细')];n=2
 for source,tool,count in SOURCES:
  for i in range(count):
   values.append(evidence(n,source,None if tool=='fc.query_es_order_structure' else '2026-10-17T01:00:00+00:00','pending' if tool=='fc.query_es_order_structure' else 'available',{'start':'2026-10-16','end':'2026-10-16'}));n+=1
 return {v['evidence_id']:v for v in values}
class ContinuationSources(unittest.TestCase):
 def test_thirteen_actual_source_label_shapes_map_without_losing_evidence(self):
  values=fixture();original=deepcopy(values);book=mod.FrozenEvidenceBook(TASK,values,{'version':'fixture'})
  self.assertEqual(book.evidence,original);self.assertEqual(values,original)
  for source,tool,count in SOURCES:
   rows=[v for v in values.values() if v['source']==source];self.assertEqual(len(rows),count)
   for row in rows:self.assertEqual(mod.evidence_tool(row),tool);self.assertIn(tool,mod.RESEARCH_NAMES)
   chosen=book.call(tool,rows[0]['query']);self.assertIn(chosen['evidence_id'],values)
  self.assertEqual(len(book.evidence),14);self.assertIn('new_source_reads',book.trace[0]);self.assertEqual(book.trace[0]['new_source_reads'],0)
 def test_null_rank_is_deterministic_and_completed_dominates_pending(self):
  a=evidence(2,SOURCES[0][0],None,'pending');b=evidence(3,SOURCES[0][0],None,'pending')
  self.assertGreater(mod.cache_rank(b),mod.cache_rank(a));self.assertIsNone(a['captured_at'])
  known=evidence(1,SOURCES[0][0],'2026-10-16T00:00:00+00:00','pending')
  self.assertGreater(mod.cache_rank(known),mod.cache_rank(b))
  complete=evidence(1,SOURCES[0][0],None,'available');self.assertGreater(mod.cache_rank(complete),mod.cache_rank(known))
  first=fixture();first[a['evidence_id']]=a;first[b['evidence_id']]=b
  book=mod.FrozenEvidenceBook(TASK,first,{'version':'fixture'});self.assertIsNone(book.evidence[b['evidence_id']]['captured_at'])
 def test_unknown_source_and_known_naive_time_rejected(self):
  with self.assertRaisesRegex(ValueError,'continuation_source_unknown'):mod.evidence_tool(evidence(1,'Admin ES订单导出：未知来源变体'))
  with self.assertRaisesRegex(ValueError,'continuation_capture_time'):mod.cache_rank(evidence(1,SOURCES[0][0],'2026-10-17T00:00:00'))
 def test_registered_market_source_maps_and_missing_read_never_calls_source(self):
  source='FC27现有采集只读投影：竞品/Order平台成交成本/MMOEXP公开商品/中行汇率；非历史成本账'
  self.assertEqual(mod.evidence_tool(evidence(1,source)),'fc.query_market_snapshot')
  book=mod.FrozenEvidenceBook(TASK,fixture(),{'version':'fixture'})
  value=book.call('fc.query_es_order_structure',{'start':'2026-10-15','end':'2026-10-15'})
  self.assertEqual(value['data']['reason'],'not_in_frozen_continuation_evidence');self.assertFalse(value['data']['new_source_reads'])
 def test_owner_period_hash_and_settled_guards_unchanged(self):
  original=ROOT/'releases/fs-dashboard/hermes-shared-reports-20261015/candidate/continuation.py'
  self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),'d453b3fbba1a49235f26ecfc7049395ff43c25113ec6cee86d5dfc99ecfabba0')
  old=ast.parse(original.read_text(encoding='utf-8'));new=ast.parse((RELEASE/'source/continuation.py').read_text(encoding='utf-8'))
  for name in ['load_report_followup','load_continuation','can_continue','compatible_version']:
   get=lambda tree:ast.dump(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name))
   self.assertEqual(get(old),get(new))
 def test_optional_private_real_evidence_metadata(self):
  file=os.environ.get('FS_FOLLOWUP_PRIVATE_EVIDENCE')
  if not file:return
  values=json.loads(Path(file).read_bytes());before=deepcopy(values);first=next(iter(values.values()))
  task=deepcopy(TASK);task['spec']['snapshot_id']=first['analysis_anchor_id']
  book=mod.FrozenEvidenceBook(task,values,{'version':'fixture'})
  self.assertEqual(book.evidence,before);self.assertEqual(len(values),34)
  for source,tool,count in SOURCES:self.assertEqual(sum(v['source']==source for v in values.values()),count)
  self.assertTrue(all(v['captured_at'] is None for v in values.values() if v['source']==SOURCES[0][0]))
if __name__=='__main__':unittest.main()
