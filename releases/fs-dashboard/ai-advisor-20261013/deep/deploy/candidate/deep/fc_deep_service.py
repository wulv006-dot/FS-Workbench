"""Integrates evidence, private memory and the one existing model ledger."""
from datetime import date, datetime, timedelta
from pathlib import Path
from advisor_memory import Memory
from fc_deep_analysis import fallback
from fc_deep_model import project, explain
from fc_deep_sources import EvidenceReader


class DeepService:
    def __init__(self, detail, ledger, root, diagnostics=None, model=explain, reader=None):
        self.ledger,self.model=ledger,model
        self.reader=reader or EvidenceReader(detail,diagnostics)
        self.memory=Memory(root)

    def analyse(self, owner, report_id, evidence, at, use_ai=True, question=None, remember=True):
        recalled=self.memory.recall(owner,evidence)
        projected=project(evidence,recalled,question)
        ai=self.ledger.bounded_model(projected,self.model) if use_ai and projected['facts'] else {'status':'not_requested' if not use_ai else 'no_verified_facts'}
        evidence['memory']=recalled
        evidence['decision']=ai if ai.get('status')=='succeeded' else dict(fallback(evidence),model_status=ai['status'])
        evidence['model_result']=ai
        evidence['review']=self.review(evidence,recalled)
        if remember:self.memory.remember(owner,report_id,evidence,evidence['decision'],at)
        return evidence

    @staticmethod
    def review(evidence, recalled):
        """Changes in indicators are observable; effect of a suggestion is not established."""
        target=next((w for w in evidence['windows'] if w['key']=='target' and w['status']=='available'),None)
        if not target:return []
        out=[]
        for old in recalled['observations'][:5]:
            previous_days=(date.fromisoformat(old['end'])-date.fromisoformat(old['start'])).days+1
            for item in old.get('reviews',[]):
                rule=item['verify'];key=rule['metric'];current=before=None
                if key in ('orders','revenue_usd','average_order_usd') and target['complete_days'] and previous_days==target['days']:
                    current=target['main'][key];before=old['main'][key]
                elif evidence.get('backlog') and old.get('backlog'):
                    if key=='backlog_issues':current=evidence['backlog']['main']['issues'];before=old['backlog']['issues']
                    if key=='backlog_over72h':current=evidence['backlog']['age_bands']['72to168h']+evidence['backlog']['age_bands']['over168h'];before=old['backlog']['over72h']
                out.append({'report_id':old['report_id'],'metric':key,'previous':before,'current':current,
                            'review_due':date.fromisoformat(evidence['plan']['end'])>=date.fromisoformat(old['end'])+timedelta(days=rule['window_days']),
                            'implementation_confirmed':False,'conclusion':'仅观察指标变化；原建议未确认执行，不能认定行动有效或无效。'})
        return out[:10]

    def report(self, selected, owner, report_id, at, use_ai=True, progress=None):
        p=selected['period'];evidence=self.reader.collect(p['start'],p['end'],at,progress)
        self.analyse(owner,report_id,evidence,at,use_ai)
        target=next((w for w in evidence['windows'] if w['key']=='target' and w['status']=='available'),None)
        main=target['main'] if target else {}
        names={'orders':'orders','revenueUsd':'revenue_usd','averageOrderUsd':'average_order_usd'}
        metrics={}
        for key in ('orders','revenueUsd','averageOrderUsd','newCustomers','repeatRatePct','fulfillmentRatePct','profitMarginPct'):
            value=main.get(names.get(key))
            metrics[key]={'value':value,'source':'Admin FC支付明细','scope':'MMOEXP主站；支付订单口径',
                          'unit':'USD' if key.endswith('Usd') else '%' if key.endswith('Pct') else 'count',
                          'status':'available' if value is not None else 'not_provided',
                          'captured_at':evidence['evidence'][0]['captured_at'] if evidence['evidence'] else None}
        project_item={'key':'FC27','name':'FC27','status':'available' if target else 'partial','metrics':metrics,
                      'period':{'start':p['start']+' 00:00','end':p['end_exclusive']+' 00:00'},
                      'range_id':evidence['snapshot_id'],'captured_at':metrics['orders']['captured_at'],
                      'warnings':['本报告与FC自动日报采用支付明细口径；不与首页Admin区间原值直接混比。']}
        return {'contractId':'fs-ai-advisor-v1','selection':selected,'period':p,'generated_at':at.isoformat(),
                'report_id':report_id,'currency':'USD','projects':[project_item],
                'totals':{'orders':main.get('orders'),'revenueUsd':main.get('revenue_usd')},
                'coverage':{'available':int(bool(target)),'requested':1,'missing':[] if target else ['FC27']},
                'status':'ready' if target else 'partial','warnings':evidence['gaps'],
                'ai':evidence['model_result'],'deep':evidence}

    def daily_report(self, day, previous, at, report_id):
        from fc_detail_model import aggregate
        from fc_daily import build_report
        evidence,raw,config=self.reader.collect_bundle(day,day,at)
        target=next((w for w in evidence['windows'] if w['key']=='target' and w['status']=='available'),None)
        if not target:raise ValueError('paid_data_incomplete')
        result=[]
        for site in ('all','main'):
            q={'mode':'fc-detail','profile':'FC27','grain':'day','start':day,'end':day,'site_group':site}
            view=aggregate(raw,q,config,now=at)
            # A verified complete subset of the one wide capture, with its original range retained.
            view['coverage']=dict(view['coverage'],source_period=view['coverage']['period'],
                                  period={'start':day+' 00:00','end':(date.fromisoformat(day)+timedelta(days=1)).isoformat()+' 00:00'},
                                  paid_complete=True,missing_days=[])
            result.append(view)
        report=build_report(day,*result,previous)
        self.analyse('__scheduled_fc__',report_id,evidence,at,True)
        report['deep']=evidence
        ai=evidence['model_result']
        if ai['status']=='succeeded':
            report['ai']=dict(ai,analysis='；'.join(f['observation'] for f in ai['findings']),
                              suggestion='；'.join(f['action'] for f in ai['findings']),
                              explanation=ai['findings'][0]['observation'],next_step=ai['findings'][0]['action'],
                              evidence_ref='；'.join(ai['findings'][0]['refs']),focus='deep_analysis',
                              references=sorted({r for f in ai['findings'] for r in f['refs']}))
        else:report['ai']=ai
        report['warnings']=[w for w in report['warnings'] if '未接原始客服备注' not in w and '缺少同口径前一日日报' not in w]
        report['warnings'].extend(evidence['gaps'])
        report['warnings'].append('已按所选日期自动读取近期基线；完整比较、问题单证据和行动复盘见AI运营顾问。')
        return report
