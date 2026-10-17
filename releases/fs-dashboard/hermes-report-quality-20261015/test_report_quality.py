import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest

HERE=Path(__file__).resolve().parent
from test_support import SOURCE_ROOT
sys.path.insert(0,str(SOURCE_ROOT))
from boss_projection import project,order_series
from boss_renderer import render,validate
from report_delivery import deliver_output
from report_semantics import index,structured,declared_comparison
from report_artifacts import save_boss,read_file,digest_bytes
from skill_bundle import load_bundle

TOTAL='ev_fd8914720a8382f5766ebf0e'
REFERENCE='ev_d276e25ce48dc00a63131228'
TASK='a2dd842057e94629bb943066d6aaadff'
CAPTURE='2026-10-14T14:29:09.672503+00:00'


class ReportQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        full=HERE.parent/'fs-revision-acceptance-20261015/weekly-content-diagnosis'
        if (full/'actual-result.json').exists():
            cls.result=json.loads((full/'actual-result.json').read_text(encoding='utf-8'))
            cls.ev=json.loads((full/'actual-evidence.json').read_text(encoding='utf-8'))
            cls.fixture_scope='actual_full_154'
        else:
            reduced=json.loads((HERE/'inputs/projection-fixture.json').read_text(encoding='utf-8'))
            cls.result=reduced['result'];cls.ev=reduced['evidence'];cls.fixture_scope='reduced_projection_fields'
        cls.raw=cls.result['raw_model_text']
        cls.book=SimpleNamespace(evidence=cls.ev,capture_id=cls.result['snapshot_id'])

    def content(self,result=None,ev=None):
        return project(result or self.result,ev or self.ev,{'artifact_written_at':CAPTURE},'f'*64)

    def reference(self,ev):
        return order_series(ev,self.result['snapshot_id'],'2026-09-28','2026-10-04','2026-10-05','2026-10-11')

    def envelope(self):
        return {'report_contract':'fs-report-v2','summary':'支付规模变化待复核，先核平台与组合。',
                'research_text':'## 关键判断\n\n观察性差异不能识别因果。\n\n## 建议与复查\n\n详见结构化行动。',
                'findings':[{'statement':'支付规模发生变化，原因仍待验证。','claim_type':'fact','evidence_ids':[TOTAL]}],
                'actions':[{'target':'平台与品类','action':'只读核对平台与品类交叉结构。','evidence_ids':[TOTAL]}],
                'limitations':['暂无官方网页读取工具，情报未开展。']}

    def test_original_markdown_semantics_and_six_actions(self):
        s=index(self.result,self.ev)
        self.assertEqual((len(s['findings']),len(s['actions'])),(9,6))
        self.assertNotIn('**快照**',s['summary'])
        self.assertTrue(all(a['source_section'] for a in s['actions']))

    def test_delivery_with_real_modules_keeps_native_text(self):
        d=deliver_output(self.raw,self.book)
        self.assertEqual(d['raw_model_text'],self.raw)
        self.assertEqual(len(d['actions']),6)
        self.assertEqual(d['semantic_index']['contract'],'fs-report-semantic-index-v2')

    def test_structured_v2_preserves_incomplete_action(self):
        d=deliver_output(json.dumps(self.envelope(),ensure_ascii=False),self.book)
        self.assertEqual(d['report_format'],'structured_v2')
        self.assertEqual(len(d['actions']),1)
        self.assertEqual(d['actions'][0]['role'],'待补：role')
        self.assertIn('待补',d['actions'][0]['stop_condition'])
        self.assertEqual(d['business_acceptance'],'user_review_required')
        c=self.content(dict(self.result,**d));self.assertIn('结构化行动',c['research_text'])
        self.assertEqual(c['executive']['summary'],self.envelope()['summary'])

    def test_legacy_structured_stays_compatible(self):
        d={'summary':'销售变化待复核','findings':[{'statement':'销售结构存在变化','claim_type':'fact','evidence_ids':[TOTAL],'alternative':'','missing':''}],
           'actions':[],'reviews':[],'limitations':[],'number_claims':[]}
        result=deliver_output(json.dumps(d,ensure_ascii=False),self.book)
        self.assertEqual(result['report_format'],'structured')
        self.assertEqual(result['semantic_index']['summary'],d['summary'])

    def test_incomplete_legacy_json_keeps_action_and_warning(self):
        d={'summary':'需补证','findings':[{'statement':'尚未核准的判断','claim_type':'fact','evidence_ids':[TOTAL]}],'actions':[{'target':'品类','action':'核查品类结构。','evidence_ids':[TOTAL]}]}
        result=deliver_output(json.dumps(d,ensure_ascii=False),self.book)
        self.assertEqual(result['delivery_status'],'raw_saved')
        self.assertEqual(len(result['actions']),1)
        self.assertIn('待补',result['actions'][0]['condition'])
        c=self.content(dict(self.result,**result));self.assertEqual(c['key_findings'][0]['statement'],'尚未核准的判断')
        self.assertEqual(c['key_findings'][0]['claim_type'],'unreviewed')

    def test_v2_rejects_unknown_evidence(self):
        d=self.envelope();d['actions'][0]['evidence_ids']=['ev_'+'f'*24]
        with self.assertRaisesRegex(ValueError,'unknown_evidence'):structured(d,self.ev)

    def test_unbound_v2_finding_is_not_promoted_to_fact(self):
        d=self.envelope();d['findings'][0]['evidence_ids']=[]
        v=structured(d,self.ev)
        self.assertEqual(v['findings'][0]['claim_type'],'unreviewed')
        self.assertTrue(any('未逐项绑定' in x for x in v['limitations']))

    def test_missing_auxiliary_refs_remain_explicit_not_crash(self):
        d=self.envelope();d['hypotheses']=[{'title':'待证解释','text':'缺引用，等待补证。'}]
        result=deliver_output(json.dumps(d,ensure_ascii=False),self.book)
        self.assertEqual(result['hypotheses'][0]['evidence_ids'],[])
        render(self.content(dict(self.result,**result)),self.ev)

    def test_actions_not_truncated_to_five(self):
        d=self.envelope();d['actions']*=7
        result=deliver_output(json.dumps(d,ensure_ascii=False),self.book)
        c=self.content(dict(self.result,**result))
        self.assertEqual(len(c['actions']),7);validate(c,self.ev)

    def test_structured_context_hypotheses_decisions_visible(self):
        d=self.envelope();d.update(context=[{'label':'结构核查','text':'保留同口径已知行。','evidence_ids':[TOTAL]}],
            hypotheses=[{'title':'组合假设','text':'需要同 SKU 证据验证。','evidence_ids':[TOTAL]}],
            decisions=[{'topic':'是否先补证','recommended':'先补证','evidence_ids':[TOTAL]}])
        result=deliver_output(json.dumps(d,ensure_ascii=False),self.book);c=self.content(dict(self.result,**result));h=render(c,self.ev)
        self.assertIn('结构核查',h);self.assertIn('组合假设',h);self.assertIn('是否先补证',h);self.assertIn('待补：alternative',h)

    def test_complete_reference_is_seven_pairs_with_actual_dates(self):
        value,gap=self.reference(self.ev);self.assertIsNone(gap);self.assertEqual(len(value['rows']),7)
        self.assertEqual(value['rows'][0]['previous_date'],'2026-09-28')
        self.assertEqual(value['rows'][0]['previous'],'25.0')

    def test_pending_does_not_hide_success(self):
        ev={k:self.ev[k] for k in sorted(self.ev)}
        self.assertIn('ev_00c0ba60f603ea4a0ef1ce9c',ev)
        self.assertEqual(len(self.reference(ev)[0]['rows']),7)

    def test_two_complete_seven_day_queries_cover_reference(self):
        ev=copy.deepcopy(self.ev);ev.pop(REFERENCE)
        self.assertEqual(len(self.reference(ev)[0]['rows']),7)

    def test_complete_wider_query_is_sliced_to_two_declared_windows(self):
        value,gap=order_series({REFERENCE:self.ev[REFERENCE]},self.result['snapshot_id'],'2026-10-01','2026-10-02','2026-10-08','2026-10-09')
        self.assertIsNone(gap)
        self.assertEqual([(r['previous_date'],r['current_date']) for r in value['rows']],[('2026-10-01','2026-10-08'),('2026-10-02','2026-10-09')])

    def test_wider_query_still_requires_every_declared_source_day(self):
        row=copy.deepcopy(self.ev[REFERENCE]);row['data']['rows']=[r for r in row['data']['rows'] if r['date']!='2026-10-05']
        self.assertIsNone(order_series({REFERENCE:row},self.result['snapshot_id'],'2026-10-01','2026-10-02','2026-10-08','2026-10-09')[0])

    def test_missing_reference_day_not_filled_zero(self):
        ev=copy.deepcopy(self.ev)
        for v in ev.values():
            if v.get('source','').startswith('Order参考利润'):
                d=v['data'];d['rows']=[r for r in d.get('rows',[]) if r['date']!='2026-10-07']
        self.assertIsNone(self.reference(ev)[0])

    def test_conflicting_success_rejected(self):
        ev=copy.deepcopy(self.ev);row=copy.deepcopy(ev[REFERENCE]);row['data']['rows'][0]['profitMarginPct']=99
        ev['ev_'+'f'*24]=row
        value,gap=self.reference(ev);self.assertIsNone(value);self.assertIn('冲突',gap)

    def test_wrong_reference_scope_rejected(self):
        ev=copy.deepcopy(self.ev)
        for v in ev.values():
            if v.get('source','').startswith('Order参考利润'):
                for row in v['data'].get('rows',[]):row['scope']['sites']='main'
        self.assertIsNone(self.reference(ev)[0])

    def test_missing_reference_rate_rejected(self):
        ev=copy.deepcopy(self.ev)
        for v in ev.values():
            if v.get('source','').startswith('Order参考利润'):
                for row in v['data'].get('rows',[]):row['profitMarginPct']=None
        self.assertIsNone(self.reference(ev)[0])

    def test_known_country_survives_partial_paging(self):
        ev=copy.deepcopy(self.ev)
        for v in ev.values():
            if v.get('query',{}).get('group_by')==['country']:
                v['data']['pagination']['complete']=False
                v['data']['groups']=[r for r in v['data']['groups'] if r['group']['country'] in ['GB','US']]
        c=self.content(ev=ev);self.assertIn('GB',c['context'][0]['text']);self.assertIn('US',c['context'][0]['text'])
        self.assertIn('截断',c['context'][0]['text'])

    def test_admin_filters_do_not_become_main_site_total(self):
        ev=copy.deepcopy(self.ev)
        for row in ev.values():
            if row.get('source')=='Admin FC支付明细':row['query']['filters']={'platform':'PS'}
        c=self.content(ev=ev)
        self.assertEqual(c['metrics'][0]['status'],'missing');self.assertEqual(c['charts'][0]['rows'],[])

    def test_conflicting_admin_total_not_selected_by_hash(self):
        ev=copy.deepcopy(self.ev);row=copy.deepcopy(ev[TOTAL]);row['captured_at']='2026-10-14T11:44:42+00:00';ev['ev_'+'f'*24]=row
        self.assertEqual(self.content(ev=ev)['metrics'][0]['status'],'missing')

    def test_true_tooltip_dates_and_age_order(self):
        c=self.content();h=render(c,self.ev)
        self.assertIn('<title>2026-09-28: 28,366.50',h);self.assertNotIn('<title>10-05: 28,366.50',h)
        self.assertEqual([r['label'] for r in c['charts'][4]['rows']],['under1d','1to3d','3to7d','7to14d','over14d'])

    def test_arithmetic_and_causal_corrections_visible(self):
        c=self.content();h=render(c,self.ev)
        for token in ['147.84%','47.84%','T+16','+7.95%','29,925.33','16,737.87']:
            self.assertIn(token,' '.join(c['corrections']))
        self.assertIn('review-corrections',h)
        self.assertNotIn('判定“基数+正常化”',c['actions'][0]['trigger'])
        self.assertIn('固定观察队列',c['actions'][1]['trigger'])
        self.assertIn('无持货库存',c['actions'][2]['steps'])

    def test_no_fake_official_intelligence_and_profit_is_labelled_estimate(self):
        c=self.content();self.assertEqual(c['intel'],[]);self.assertIn('未开展',c['intel_note'])
        self.assertIn('临时公式',c['charts'][5]['interpretation']);self.assertIn('非实际结算',c['finance']['estimates']['current']['label'])

    def test_closed_daily_monthly_contracts_do_not_reuse_week_numbers(self):
        for period,kind in [({'start':'2026-10-13','end':'2026-10-13'},'daily'),({'start':'2026-09-01','end':'2026-09-30'},'monthly')]:
            d=copy.deepcopy(self.result);d['period']=period;c=self.content(result=d)
            self.assertEqual(c['report']['kind'],kind);self.assertEqual(c['metrics'][0]['status'],'missing');render(c,self.ev)

    def test_raw_text_and_evidence_not_mutated_by_projection(self):
        before=json.dumps(self.ev,sort_keys=True);c=self.content()
        self.assertEqual(c['research_text'],self.raw);self.assertEqual(json.dumps(self.ev,sort_keys=True),before)

    def test_versioned_artifact_preserves_original_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'reports'/TASK;p.mkdir(parents=True)
            raw=self.raw.encode();ev=json.dumps(self.ev,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
            result=json.dumps(self.result,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
            native=(HERE/'inputs/report.html').read_bytes() if (HERE/'inputs/report.html').exists() else b'<html><body>Inert native report fixture for CI</body></html>'
            values={'model.txt':raw,'evidence.json':ev,'result.json':result,'report.html':native,
                    'boss-report.html':b'original boss bytes','boss.content.json':b'original content','boss-ready.json':b'original receipt'}
            metadata={'raw_sha256':digest_bytes(raw),'evidence_sha256':digest_bytes(ev)}
            values['metadata.json']=json.dumps(metadata).encode();values['ready.json']=json.dumps({'html_sha256':digest_bytes(native),'result_sha256':digest_bytes(result)}).encode()
            for name,value in values.items():(p/name).write_bytes(value)
            from datetime import datetime
            stamp=datetime.fromisoformat(CAPTURE).timestamp();os.utime(p/'model.txt',(stamp,stamp))
            proof=save_boss(temp,TASK);again=save_boss(temp,TASK)
            self.assertEqual(proof,again);self.assertTrue(proof['html_file'].startswith('boss-semantic-v2-'))
            for name,value in values.items():self.assertEqual((p/name).read_bytes(),value,name)
            self.assertEqual(read_file(temp,TASK,'boss')['sha256'],proof['html_sha256'])

    def test_original_artifact_tamper_still_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'reports'/TASK;p.mkdir(parents=True)
            for name in ['model.txt','evidence.json','result.json','report.html']:(p/name).write_bytes(b'changed')
            (p/'metadata.json').write_text(json.dumps({'raw_sha256':'0'*64,'evidence_sha256':'0'*64}))
            (p/'ready.json').write_text(json.dumps({'html_sha256':'0'*64,'result_sha256':'0'*64}))
            with self.assertRaisesRegex(ValueError,'artifact_changed'):save_boss(temp,TASK)

    def test_skill_loaded_contract_and_permissions_unchanged(self):
        bundle=load_bundle(SOURCE_ROOT);self.assertEqual(bundle['version'],'0.8.0-proof-constraints')
        self.assertIn('经营调查生成与审核合同 v2',bundle['methods_text']);self.assertEqual(bundle['permissions'],[])
        self.assertTrue(any(x['name']=='humanizer-zh' for x in bundle['reviewed_skills']))

    def test_sensitive_output_still_blocked(self):
        with self.assertRaisesRegex(ValueError,'sensitive_analysis'):deliver_output('密码：very-secret-value',self.book)

    def test_real_cross_period_comparison_and_all_six_actions(self):
        fixture=json.loads((HERE/'inputs/cross-period-fixture.json').read_text(encoding='utf-8'))
        c=project(fixture['result'],fixture['evidence'],{},'f'*64);h=render(c,fixture['evidence'])
        self.assertEqual(c['report']['period']['comparison_start'],'2026-10-05')
        self.assertEqual(c['report']['period']['comparison_end'],'2026-10-07')
        self.assertEqual(c['metrics'][0]['value'],'$85,326.05');self.assertEqual(c['metrics'][0]['previous'],'$93,139.27')
        self.assertEqual((len(c['key_findings']),len(c['actions'])),(5,6))
        self.assertEqual([v['role'] for v in c['actions']][:2],['商品/定价运营','类目运营'])
        self.assertIn('待补',c['actions'][3]['trigger'])
        self.assertIn('阈值', ' '.join(c['corrections']))
        self.assertIn('未证实', ' '.join(c['corrections']))
        self.assertEqual(len(c['charts'][0]['rows']),3);self.assertEqual(len(c['charts'][5]['rows']),3)
        self.assertIn('2026-10-05:',h)

    def test_daily_aggregate_must_reconcile_before_becoming_total(self):
        fixture=json.loads((HERE/'inputs/cross-period-fixture.json').read_text(encoding='utf-8'))
        for row in fixture['evidence'].values():
            if row.get('query',{}).get('start')=='2026-10-05' and row.get('query',{}).get('end')=='2026-10-07' and row.get('query',{}).get('group_by')==['day']:
                row['data']['groups'][0]['orders']+=1
        c=self.content(fixture['result'],fixture['evidence'])
        self.assertEqual(c['metrics'][0]['previous'],'未提供');self.assertEqual(c['charts'][0]['rows'],[])

    def test_explicit_structured_comparison_controls_period(self):
        result=copy.deepcopy(self.result);result['comparison_period']={'start':'2026-09-21','end':'2026-09-27'}
        self.assertEqual(self.content(result)['metrics'][0]['previous'],'未提供')
        d=self.envelope();d['comparison_period']={'start':'2026-10-06','end':'2026-10-05'}
        with self.assertRaisesRegex(ValueError,'comparison_period'):structured(d,self.ev)

    def test_comparison_aliases_at_different_heading_levels(self):
        f=json.loads((HERE/'inputs/cross-period-fixture.json').read_text(encoding='utf-8'))
        for declaration in ['# 调查（环比 10-05 至 10-07）','## 对照窗口：2026-10-05～2026-10-07','对比期：2026-10-05—2026-10-07']:
            result=dict(f['result'],raw_model_text=declaration)
            c=project(result,f['evidence'],{},'f'*64)
            self.assertEqual(c['metrics'][0]['previous'],'$93,139.27',declaration)

    def declared_probe_content(self,declaration):
        full=HERE/'model-probe'
        if (full/'evidence.json').exists():
            result=json.loads((full/'result.json').read_text(encoding='utf-8'));ev=json.loads((full/'evidence.json').read_text(encoding='utf-8'))
            self.assertEqual(len(ev),79)
        else:
            fixture=json.loads((HERE/'inputs/cross-period-fixture.json').read_text(encoding='utf-8'));result,ev=fixture['result'],fixture['evidence']
        return project(dict(result,raw_model_text=declaration),ev,{},'f'*64)

    def test_bold_comparison_label_keeps_declared_period(self):
        c=self.declared_probe_content('**对照期**：2026-10-05～2026-10-07')
        self.assertEqual((c['report']['period']['comparison_start'],c['report']['period']['comparison_end']),('2026-10-05','2026-10-07'))
        self.assertEqual(c['metrics'][0]['previous'],'$93,139.27')
        self.assertIn('声明的双期区间',c['charts'][5]['interpretation'])

    def test_list_comparison_label_keeps_declared_period(self):
        c=self.declared_probe_content('- 对照期：2026-10-05～2026-10-07')
        self.assertEqual((c['report']['period']['comparison_start'],c['report']['period']['comparison_end']),('2026-10-05','2026-10-07'))
        self.assertEqual(c['metrics'][0]['previous'],'$93,139.27')

    def test_ambiguous_or_incomplete_comparison_never_uses_default(self):
        f=json.loads((HERE/'inputs/cross-period-fixture.json').read_text(encoding='utf-8'))
        for declaration in ['# 对比10-05至10-07\n## 环比10-09至10-11','## 对照期：2026-10-05','## 对照窗口待定']:
            c=project(dict(f['result'],raw_model_text=declaration),f['evidence'],{},'f'*64)
            self.assertEqual(c['metrics'][0]['previous'],'未提供');self.assertEqual(c['charts'][5]['rows'],[])
            self.assertIn('未擅自',c['report']['period']['comparison_basis'])

    def test_structured_comparison_overrides_legacy_title(self):
        d=dict(self.result,comparison_period={'start':'2026-09-21','end':'2026-09-27'},raw_model_text='# 环比09-28至10-04')
        self.assertEqual(declared_comparison(d)[0],('2026-09-21','2026-09-27'))

    def test_standalone_and_unnumbered_action_headings(self):
        for raw in ['## R1 建议核查PS\n- 动作：核查最新事件\n- 负责人：履约运营',
                    '## 建议与复查\n### PS履约核对\n- 动作：核对来源字段\n- 条件：只读来源可用',
                    '## 建议：核查PS样本\n责任角色：履约运营']:
            s=index({'raw_model_text':raw},self.ev);self.assertEqual(len(s['actions']),1,raw)
            self.assertTrue(s['actions'][0]['source_section'])

    def test_unnumbered_action_list_preserves_proposals_only(self):
        raw='## 建议与复查\n- 核查支付失败样本\n- 销售下降属于观察事实\n- 验证商品规格与优惠\n'
        actions=index({'raw_model_text':raw},self.ev)['actions']
        self.assertEqual(len(actions),2);self.assertEqual(actions[0]['action'],'核查支付失败样本')

    def test_descriptive_text_is_not_invented_as_action(self):
        for raw in ['## 建议与复查\n当前销售下降，原因尚不明确。','## R1 现状\n订单下降，暂无行动。','## 数据概览\n动作：该字段未定义','## 建议与复查\n- 核查结果显示数量下降\n- 对支付进行核对后未发现异常']:
            self.assertEqual(index({'raw_model_text':raw},self.ev)['actions'],[])

    def intel_envelope(self):
        d=self.envelope();url='https://www.ea.com/games/ea-sports-fc/news/fixture';stamp='2026-10-15T04:00:00+00:00';ref='ev_'+'e'*24
        ev=copy.deepcopy(self.ev);ev[ref]={'source':'explicit synthetic official-page read fixture','captured_at':stamp,'data':{'url':url,'published_at':'2026-10-15','event_at':'2026-10-07'}}
        d['intel']=[{'title':'合成事件','url':url,'retrieved_at':stamp,'published_at':'2026-10-15','event_at':'2026-10-07','applies':'合成期内范围','fact':'来源所述事件','hypothesis':'机制待证','action':'先验证内部信号','source':'EA 合成夹具','evidence_ids':[ref]}]
        return d,ev

    def test_actual_bound_intel_survives_v2_projection(self):
        d,ev=self.intel_envelope();delivered=deliver_output(json.dumps(d,ensure_ascii=False),SimpleNamespace(evidence=ev,capture_id=self.result['snapshot_id']))
        c=self.content(dict(self.result,**delivered),ev);h=render(c,ev)
        self.assertEqual(len(c['intel']),1);self.assertIn(d['intel'][0]['url'],h);self.assertNotIn('未开展',c['intel_note'])
        self.assertNotIn('期后事件',c['intel'][0]['window'])

    def test_intel_event_after_period_differs_from_late_publication(self):
        d,ev=self.intel_envelope();r=d['intel'][0];r['event_at']='2026-10-16';ev[r['evidence_ids'][0]]['data']['event_at']=r['event_at']
        c=self.content(dict(self.result,intel=d['intel']),ev)
        self.assertIn('期后事件',c['intel'][0]['window'])

    def test_unverified_or_unsafe_intel_is_visible_pending(self):
        for change in ('unbound','unsafe'):
            d,ev=self.intel_envelope();d['intel'][0]['url']='https://example.com/not-read' if change=='unbound' else 'javascript:alert(1)'
            c=self.content(dict(self.result,intel=d['intel']),ev);h=render(c,ev)
            self.assertEqual(c['intel'],[]);self.assertEqual(len(c['intel_pending']),1)
            self.assertIn('来源所述事件',h);self.assertNotIn('href="javascript:',h)

    def test_aov_correction_does_not_change_other_equal_percentages(self):
        result=dict(self.result,report_format='structured_v2',summary='客单+7.94%、某渠道+7.94%、某渠道客单+7.94%',findings=[],actions=[])
        summary=self.content(result)['executive']['summary']
        self.assertEqual(summary,'客单+7.95%、某渠道+7.94%、某渠道客单+7.94%')

    def test_full_real_probe_checks_rebound_items_limits_and_cost(self):
        full=HERE/'model-probe'
        if (full/'evidence.json').exists():
            result=json.loads((full/'result.json').read_text(encoding='utf-8'));ev=json.loads((full/'evidence.json').read_text(encoding='utf-8'))
            self.assertEqual(len(ev),79)
        else:
            f=json.loads((HERE/'inputs/cross-period-fixture.json').read_text(encoding='utf-8'));result,ev=f['result'],f['evidence']
        c=project(result,ev,{},'f'*64)
        self.assertIn('433 单 → 2026-10-12 457 单',' '.join(c['corrections']))
        self.assertNotIn('连续回落',c['reviewed_research_text']);self.assertIn('不足以排除多商品捆绑',c['reviewed_research_text'])
        self.assertIn('0.5 人日',c['actions'][0]['cost'])
        h=render(c,ev);self.assertIn('完整研究阅读校正版',h);self.assertIn('历史原文',h)
        self.assertEqual(c['research_text'],result['raw_model_text'])


if __name__=='__main__':unittest.main(verbosity=2)
