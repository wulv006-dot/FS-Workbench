"""Frozen report sources remain usable without a new business read or provider call."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
if sys.platform=='win32':
    import types
    sys.modules.setdefault('fcntl',types.SimpleNamespace())

ROOT=Path(__file__).resolve().parents[4]
SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path[:0]=[str(SOURCE),str(ROOT/'releases/fs-dashboard/hermes-fc-pilot-20261013')]
spec=importlib.util.spec_from_file_location('followup_fixed',SOURCE/'continuation.py')
mod=importlib.util.module_from_spec(spec)
research_spec=importlib.util.spec_from_file_location('followup_current_research',ROOT/'releases/fs-dashboard/fc-coins-workflow-20261022/source/research.py')
research=importlib.util.module_from_spec(research_spec);research_spec.loader.exec_module(research)
with patch.dict(sys.modules,{'research':research}):spec.loader.exec_module(mod)
TASK={'spec':{'snapshot_id':'fc-detail-frozen-report','period':{'start':'2026-10-22'}},'end':'2026-10-22','request_id':'a'*32}

def record(n,source,query=None,project='FC27'):
    return {'evidence_id':'ev_'+format(n,'024x'),'source':source,'project':project,'analysis_anchor_id':'fc-detail-frozen-report',
            'snapshot_id':'original-source','captured_at':'2026-10-23T01:00:00+08:00','query':query or {},'data':{'status':'available','rows':[1,2]}}

class FollowupSources(unittest.TestCase):
    def book(self,*rows):
        return mod.FrozenEvidenceBook(TASK,{r['evidence_id']:r for r in rows},{'version':'fixture'})

    def test_new_sources_restore_exact_cached_evidence(self):
        cases=[('Astra FC金币固定决策流程','fc.run_pricing_workflow'),
               ('FS现有FC金币只读核对','fc.query_pricing_evidence'),
               ('FS现有FC金币执行账本/订单优惠券/发货成本只读核对','fc.query_pricing_evidence'),
               ('FS购买客户事实的冻结聚合','fc.query_user_analytics'),
               ('Admin FC27主站原生统计/商品销量；完整性与定义限制随源保留','fc.query_capability'),
               ('Order当前问题池数量/事件脱敏样本；非总体因果/实际成本','fc.query_capability')]
        for n,(source,tool) in enumerate(cases,1):
            with self.subTest(tool=tool,source=source):
                row=record(n,source,{'action':'review'});before=deepcopy(row);book=self.book(row)
                self.assertEqual(mod.evidence_tool(row),tool)
                self.assertEqual(book.call(tool,row['query']),before)
                self.assertEqual(book.evidence[row['evidence_id']],before)
                self.assertEqual(book.trace[0]['new_source_reads'],0)
                book.call(tool,row['query'])['data']['rows'].append(3)
                self.assertEqual(book.evidence[row['evidence_id']],before)

    def test_management_and_registered_non_fc_native_scopes(self):
        rows=[record(1,'FS 经营管理台已冻结的全项目汇总；Admin 主站 + 显式 Order 参考',project='ALL_MANAGEMENT_PROJECTS'),
              record(2,'Admin原生统计优先、Order补缺；管理台按已登记profile补查',{'profile':'D4'},'ALL_MANAGEMENT_PROJECTS'),
              record(3,'Admin原生订单统计（权威）与显式Order参考；各源范围分别读取',{'profile':'AION2'},'AION2'),
              record(4,'FS购买客户事实的冻结聚合',project='CONNECTED_PURCHASE_CUSTOMERS'),
              record(5,'FS 全项目经营冻结数据',{'operation':'sum'},'ALL_MANAGEMENT_PROJECTS')]
        before=deepcopy(rows);book=self.book(*rows)
        self.assertEqual(list(book.evidence.values()),before)
        self.assertEqual(book.call('fc.query_native_statistics',{'profile':'D4'}),rows[1])
        self.assertEqual(book.call('fc.query_user_analytics',{}),rows[3])

    def test_wrong_scope_anchor_and_unregistered_source_still_fail(self):
        for row,error in [(record(1,'Astra FC金币固定决策流程',project='D4'),'continuation_evidence_invalid'),
                          (record(1,'Admin原生订单统计（权威）与显式Order参考；各源范围分别读取',{'profile':'D4'},'AION2'),'continuation_evidence_invalid'),
                          (record(1,'未知来源'),'continuation_source_unknown')]:
            with self.subTest(row=row),self.assertRaisesRegex(ValueError,error):self.book(row)
        row=record(1,'Astra FC金币固定决策流程');row['analysis_anchor_id']='another-report'
        with self.assertRaisesRegex(ValueError,'continuation_snapshot_mismatch'):self.book(row)

    def test_missing_cached_workflow_keeps_no_new_source_reads(self):
        book=self.book(record(1,'Astra FC金币固定决策流程',{'action':'review'}))
        result=book.call('fc.run_pricing_workflow',{'action':'scenario'})
        self.assertEqual(result['data']['reason'],'not_in_frozen_continuation_evidence')
        self.assertFalse(result['data']['new_source_reads'])

    def test_management_snapshot_uses_its_original_identity(self):
        task=deepcopy(TASK);anchor='management-'+'b'*24;task['spec']['snapshot_id']=anchor
        row=record(1,'FS 经营管理台已冻结的全项目汇总；Admin 主站 + 显式 Order 参考',project='ALL_MANAGEMENT_PROJECTS')
        row['analysis_anchor_id']=anchor
        row['data']={'snapshotId':anchor,'generatedAt':row['captured_at'],'projects':[]}
        book=mod.FrozenEvidenceBook(task,{row['evidence_id']:row},{'version':'fixture'})
        self.assertEqual(book.capture_id,anchor);self.assertEqual(book.evidence[row['evidence_id']],row)
        row['data']['snapshotId']='management-'+'c'*24
        with self.assertRaisesRegex(ValueError,'continuation_management_context_missing'):
            mod.FrozenEvidenceBook(task,{row['evidence_id']:row},{'version':'fixture'})

    def test_legacy_source_loading_guards_are_preserved_with_native_metadata(self):
        import ast
        original=ROOT/'releases/fs-dashboard/hermes-followup-evidence-20261017/source/continuation.py'
        old=ast.parse(original.read_text(encoding='utf-8'));new=ast.parse((SOURCE/'continuation.py').read_text(encoding='utf-8'))
        for name in ('load_report_followup','load_continuation','can_continue','compatible_version'):
            def node(tree,native=False):
                fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
                if native and name in ('load_report_followup','load_continuation'):
                    self.assertEqual([a.arg for a in fn.args.kwonlyargs],['skills'])
                    self.assertEqual([ast.literal_eval(v) for v in fn.args.kw_defaults],[None])
                    fn.args.kwonlyargs=[];fn.args.kw_defaults=[]
                    body=[]
                    for statement in fn.body:
                        if isinstance(statement,ast.If) and ast.dump(statement.test)==ast.dump(ast.parse('skills is None',mode='eval').body):
                            if len(statement.body)==1 and isinstance(statement.body[0],ast.Assign):
                                self.assertEqual(ast.dump(statement.body[0]),ast.dump(ast.parse('skills=load_bundle(root)').body[0]))
                                body.extend(statement.body)
                            else:
                                self.assertTrue(any(isinstance(n,ast.ImportFrom) and n.module=='native_reports' for n in statement.body))
                            continue
                        if isinstance(statement,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='native' for t in statement.targets):
                            self.assertEqual(ast.dump(statement.value),ast.dump(ast.parse('skills is not None',mode='eval').body))
                            continue
                        if isinstance(statement,ast.If) and isinstance(statement.test,ast.BoolOp) and ast.dump(statement.test.values[0])==ast.dump(ast.parse('not native',mode='eval').body):
                            remaining=statement.test.values[1:]
                            statement.test=remaining[0] if len(remaining)==1 else ast.BoolOp(op=statement.test.op,values=remaining)
                        body.append(statement)
                    fn.body=body
                if name=='load_report_followup':
                    end=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='book' for t in n.targets))
                    fn.body=fn.body[:end+1]
                return ast.dump(fn)
            self.assertEqual(node(old),node(new,native=True))

    def test_publisher_changes_one_source_and_reloads_only_reader(self):
        import io,json,tempfile
        deploy=SOURCE.parent/'deploy'
        spec=importlib.util.spec_from_file_location('followup_release',deploy/'release_followup.py')
        release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
        with tempfile.TemporaryDirectory() as directory:
            stage=Path(directory);release.HERE=stage
            # Recreate the released CRLF artifact from Git's normalized text before hash checks.
            raw=(deploy/'release_navigation_base.py').read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            (stage/'release_navigation_base.py').write_bytes(raw)
            manifest={'scope':release.SCOPE,'files':[{'candidate':'source/continuation.py','target':'/opt/fs-hermes-fc/continuation.py','beforeSha256':'a'*64,'mode':'0o644','owner':'0:0'}],'businessWrites':False,'timersChanged':False}
            (stage/'approved-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            base=release.load_base()
            self.assertEqual(base.HERMES_HISTORY_TARGETS,release.TARGETS)
            class Fence:
                def stop_then_unlock_database(self):self.stopped=True
            fence=Fence()
            with patch.object(base.subprocess,'run') as run,patch.object(base.urllib.request,'urlopen',return_value=io.BytesIO(b'{"ok":true}')):
                base.restart_for(manifest,fence)
            self.assertTrue(fence.stopped)
            self.assertEqual(run.call_args_list[0].args[0],['systemctl','restart','fs-business-range.service'])
            self.assertEqual(len(run.call_args_list),2)
            manifest['files'][0]['target']='/opt/fs-hermes-fc/controller.py'
            (stage/'approved-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'exact_followup_target_required'):release.load_base()

if __name__=='__main__':unittest.main()
