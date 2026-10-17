"""Project frozen report evidence into the reviewed executive layout; no queries."""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json


def number(value):
    if isinstance(value, bool) or value is None:raise ValueError('missing_number')
    value = Decimal(str(value))
    if not value.is_finite():raise ValueError('nonfinite_number')
    return value


def periods(period):
    start, end = (date.fromisoformat(period[key]) for key in ('start', 'end'))
    if end < start:raise ValueError('invalid_period')
    if start == end:return 'daily', start-timedelta(days=7), end-timedelta(days=7)
    if start.weekday() == 0 and end-start == timedelta(days=6):return 'weekly', start-timedelta(days=7), end-timedelta(days=7)
    if start.day == 1 and start.year == end.year and start.month == end.month and end.day == monthrange(end.year,end.month)[1]:
        before = start-timedelta(days=1)
        return 'monthly', before.replace(day=1), before
    return 'investigation', start-(end-start)-timedelta(days=1), start-timedelta(days=1)


def stable_generated_at(result, evidence, metadata):
    def parse(value):
        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:raise ValueError('timestamp_requires_timezone')
        return stamp.astimezone(timezone.utc)
    for value in (metadata.get('artifact_written_at'), metadata.get('captured_at'), result.get('generated_at')):
        if value:return parse(value).isoformat()
    stamps=[]
    for row in evidence.values():
        try:stamps.append(parse(row.get('captured_at')))
        except (ValueError,TypeError,AttributeError):continue
    if not stamps:raise ValueError('missing_stable_report_timestamp')
    return max(stamps).isoformat()


def project(result, evidence, metadata, research_sha):
    period = result['period'];start, end = period['start'], period['end']
    kind, old_start, old_end = periods(period);old_start, old_end = old_start.isoformat(), old_end.isoformat()
    anchor = result['snapshot_id']
    def eligible(row):
        data = row.get('data', {})
        return (row.get('source') == 'Admin FC支付明细' and row.get('scope') == 'main' and row.get('project') == 'FC27'
                and row.get('snapshot_id') == anchor and row.get('timezone') == 'Asia/Shanghai'
                and data.get('status') == 'available' and data.get('coverage', {}).get('paid_complete') is True
                and not data.get('coverage', {}).get('missing_days') and row.get('query', {}).get('filters') == {})
    def total(lo,hi):
        candidates = []
        for key,row in sorted(evidence.items()):
            q=row.get('query', {});data=row.get('data', {})
            if not eligible(row) or q.get('start') != lo or q.get('end') != hi or q.get('group_by') != [] or data.get('pagination',{}).get('complete') is not True or data.get('filters_applied')!={}:continue
            try:
                value=data['total'];revenue=number(value['revenue_usd']);orders=number(value['orders'])
                if orders < 0 or orders != orders.to_integral_value() or number(value.get('unpriced_orders')) != 0:continue
                candidates.append((key,revenue,orders,row))
            except (KeyError,ValueError,ArithmeticError):continue
        if len({(v[1],v[2],v[3].get('captured_at')) for v in candidates}) != 1:return None
        return candidates[0]
    current, previous = total(start,end), total(old_start,old_end)
    if current and previous and current[3].get('captured_at')!=previous[3].get('captured_at'):previous=None
    captured = current[3]['captured_at'] if current else '未取得完整同口径汇总'
    ids = [v[0] for v in (current,previous) if v]
    def facts(value):
        revenue,orders=number(value['revenue_usd']),number(value['orders'])
        if revenue<0 or orders<0 or orders!=orders.to_integral_value() or number(value['unpriced_orders'])!=0:raise ValueError('invalid_group_facts')
        return revenue,orders
    def grouped(dimension,lo,hi,item,pool=False):
        if not current:return None
        pages={};expected_groups=None;page_size=None;grand=None
        for key,row in sorted(evidence.items()):
            q=row.get('query',{});data=row.get('data',{})
            if not eligible(row) or row.get('captured_at')!=current[3].get('captured_at') or q.get('group_by')!=[dimension]:continue
            if q.get('start')!=lo or q.get('end')!=hi or data.get('filters_applied')!={}:continue
            if pool and (data.get('coverage',{}).get('backlog_status')!='available' or data.get('state_basis')!='current_at_capture_not_historical_day_end'):continue
            try:
                pagination=data['pagination'];page=pagination['page'];size=pagination['page_size'];count=pagination['total_groups']
                if any(type(v) is not int for v in (page,size,count)) or page<1 or size<1 or not 0<=count<=10000 or page!=q.get('page') or type(pagination['complete']) is not bool:continue
                total_value=facts(data['total'])
                if item and total_value!=(item[1],item[2]):continue
                groups=data['groups']
                if not isinstance(groups,list) or len(groups)>size or any(set(g.get('group',{}))!={dimension} for g in groups):continue
                if expected_groups is not None and (expected_groups,page_size,grand)!=(count,size,total_value):return None
                expected_groups,page_size,grand=count,size,total_value
                signature=json.dumps(groups,sort_keys=True,separators=(',',':'))
                if page in pages and pages[page][1]!=signature:return None
                pages[page]=(key,signature,groups,pagination['complete'])
            except (KeyError,TypeError,ValueError,ArithmeticError):continue
        if expected_groups is None:return None
        last=max(1,(expected_groups+page_size-1)//page_size)
        if set(pages)!=set(range(1,last+1)) or any(pages[p][3]!=(p==last) for p in pages):return None
        values={};references=[]
        try:
            for page in range(1,last+1):
                key,_,groups,_=pages[page];references.append(key)
                for group in groups:
                    label=group['group'][dimension]
                    if not isinstance(label,str) or label in values:return None
                    facts(group);values[label]=group
            if len(values)!=expected_groups or (sum((facts(v)[0] for v in values.values()),Decimal(0)),sum((facts(v)[1] for v in values.values()),Decimal(0)))!=grand:return None
        except (KeyError,TypeError,ValueError,ArithmeticError):return None
        return values,references
    def comparison_rows(old,new):
        # A group absent from a fully reconciled complete population has zero orders/amount.
        rows=[]
        for label in sorted(set(old[0])|set(new[0])):
            a=old[0].get(label);b=new[0].get(label)
            av,ao=facts(a) if a else (Decimal(0),Decimal(0));bv,bo=facts(b) if b else (Decimal(0),Decimal(0))
            rows.append({'label':label,'previous':str(av),'current':str(bv),'previous_orders':int(ao),'current_orders':int(bo),
                         'previous_aov':str(av/ao) if ao else None,'current_aov':str(bv/bo) if bo else None})
        return rows
    def metric(label,index,currency=False):
        a = current[index] if current else None;b = previous[index] if previous else None
        if index == 3:
            a=current[1]/current[2] if current and current[2] else None
            b=previous[1]/previous[2] if previous and previous[2] else None
        fmt=lambda v:('未提供' if v is None else ('$' if currency else '')+format(v,',.2f' if currency else ',.0f'))
        return {'label':label,'value':fmt(a),'previous':fmt(b),'delta':format((a/b-1)*100,'+.2f')+'%' if a is not None and b else '无可比基准',
                'status':'fact' if a is not None else 'missing','evidence_ids':ids}
    metrics=[metric('主站销售额',1,True),metric('支付订单',2),metric('客单价',3,True),
             {'label':'目标达成','value':'待核对','previous':'须同周期、同范围目标','delta':'不以估算利润评目标','status':'missing','evidence_ids':[]}]
    charts=[]
    for key,title,chart_kind,unit in [('daily','每日销售与订单','line_compare','USD / 日'),('bridge','变化拆解','waterfall','USD'),('platform','平台变化','diverging','USD'),('category','品类变化','bars_compare','USD'),('queue','当前未结池','bars','单'),('margin','参考利润率','line_compare','%')]:
        charts.append({'id':key,'title':title,'kind':chart_kind,'unit':unit,'scope':'Admin 主站支付明细' if key!='margin' else 'Order全站参考，不能评主站利润目标',
                       'period':start+' — '+end,'as_of':captured,'interpretation':'本次冻结证据未形成完整可比系列，保留缺口。','note':'缺失不补零；原始证据可在附录查看。',
                       'rows':[],'evidence_ids':[],'labels':[old_start+' — '+old_end,start+' — '+end]})
    charts[4].update(period_basis='current_snapshot',snapshot_at='未取得当前存量证据',period='当前存量，未取得快照',labels=[])
    # Only plot a complete daily series when it reconciles to the independently queried total.
    if current and previous:
        for key,row in sorted(evidence.items()):
            q=row.get('query',{});data=row.get('data',{})
            if not eligible(row) or row.get('captured_at')!=current[3].get('captured_at') or q.get('start')!=old_start or q.get('end')!=end or q.get('group_by') != ['day'] or not data.get('pagination',{}).get('complete'):continue
            values={g['group'].get('day'):g for g in data.get('groups',[]) if isinstance(g.get('group'),dict)}
            days=lambda lo,hi:[(date.fromisoformat(lo)+timedelta(days=i)).isoformat() for i in range((date.fromisoformat(hi)-date.fromisoformat(lo)).days+1)]
            old_days,new_days=days(old_start,old_end),days(start,end)
            if len(old_days)!=len(new_days) or len(values)!=len(data.get('groups',[])) or set(values)!=set(old_days+new_days):continue
            try:
                if any(number(values[d]['unpriced_orders']) != 0 for d in old_days+new_days):continue
                if any(sum(number(values[d]['revenue_usd']) for d in group)!=item[1] or sum(number(values[d]['orders']) for d in group)!=item[2] for group,item in ((old_days,previous),(new_days,current))):continue
                rows=[]
                for a,b in zip(old_days,new_days):
                    av,bv=values[a],values[b];ao,bo=number(av['orders']),number(bv['orders'])
                    rows.append({'label':b[5:],'previous_date':a,'current_date':b,'previous':av['revenue_usd'],'current':bv['revenue_usd'],
                                 'previous_orders':av['orders'],'current_orders':bv['orders'],'previous_aov':str(number(av['revenue_usd'])/ao) if ao else None,'current_aov':str(number(bv['revenue_usd'])/bo) if bo else None})
                charts[0].update(rows=rows,evidence_ids=[key]+ids,interpretation='按完整日对照；销售额与订单已与同批汇总核平，变化本身不等于原因。')
                break
            except (ValueError,KeyError,ArithmeticError):continue
    payment=[];payment_ids=[]
    if current and previous:
        for dimension,index,title in [('platform',2,'平台销售与订单'),('product',3,'品类销售与订单'),('amount_band',5,'支付金额档结构')]:
            a,b=grouped(dimension,old_start,old_end,previous),grouped(dimension,start,end,current)
            if not a or not b:continue
            rows=comparison_rows(a,b);source_ids=a[1]+b[1]+ids
            charts[index].update(kind='bars_compare',title=title,unit='USD',scope='Admin 主站完整支付明细',rows=rows,evidence_ids=list(dict.fromkeys(source_ids)),
                                 dimension_label={'platform':'平台','product':'品类','amount_band':'金额档'}[dimension],
                                 interpretation='两期分组均与同批汇总核平；差额描述变化位置，不证明原因。',
                                 empty_label='两期汇总均为零，没有分组数据。' if current[2]==previous[2]==0 else '缺失数据，未绘制。',
                                 note='两期完整分页；该期未出现的分组按零单/零额表示，不把未知值补零。')
            if dimension=='product':
                charts[1].update(rows=[{'label':'对照期','role':'total','value':str(previous[1])}]+[{'label':r['label'],'role':'delta','value':str(number(r['current'])-number(r['previous']))} for r in rows]+[{'label':'本期','role':'total','value':str(current[1])}],
                                 evidence_ids=list(dict.fromkeys(source_ids)),interpretation='按互斥品类拆解销售净变化，差额与两期汇总核平。',note='品类完整分组，没有把平台、支付等不同边际相加。')
        a,b=grouped('payment',old_start,old_end,previous),grouped('payment',start,end,current)
        if a and b:
            payment=[dict(row,delta=str(number(row['current'])-number(row['previous']))) for row in comparison_rows(a,b)]
            payment_ids=list(dict.fromkeys(a[1]+b[1]+ids))
    queue=grouped('age_band',None,None,None,True) if current else None
    if queue:
        try:
            captured_time=datetime.fromisoformat(current[3]['captured_at'].replace('Z','+00:00'))
            if captured_time.tzinfo is not None:
                charts[4].update(rows=[{'label':label,'value':int(facts(v)[1]),'amount':str(facts(v)[0])} for label,v in sorted(queue[0].items())],evidence_ids=queue[1],
                                 snapshot_at=captured_time.isoformat(),as_of=captured_time.isoformat(),period='当前存量快照 · '+captured_time.isoformat(),
                                 interpretation='采集时点的当前未结存量；不能当作报告期末或本期新增队列。',note='完整无过滤当前池按账龄分组并与该池总量核平，不能推造历史趋势。')
        except (KeyError,ValueError):pass
    title='FC27 '+{'daily':'经营日报','weekly':'运营周报','monthly':'经营月报','investigation':'经营调查'}[kind]
    gaps=list(result.get('limitations',[]))+['目标基准沿用DY原版，未与本报告精确期间及字段闭合前不计算达成。','Order参考利润不是主站结算利润；当前未结池不是报告期末历史存量。','原始研究判断由Hermes产生，本版仅从同批证据排版，尚需业务复核。']
    if not current:gaps.append('本次证据没有可核平的同快照、同区间、主站完整支付汇总，指标保持缺失。')
    if not previous:gaps.append('未取得同口径对照期汇总，未计算涨跌。')
    actions=[]
    for i,item in enumerate(result.get('actions',[])[:5]):
        actions.append({'id':'action-'+str(i+1),'priority':'建议','title':item.get('target','待明确对象'),'role':'责任人待明确','when':item.get('review_at','复查时间待明确'),
                        'trigger':item.get('condition','触发条件待明确'),'steps':item.get('action','行动待明确'),'metric':item.get('success_check','验收指标待明确'),
                        'cost':'资源投入待评估','risk':'需复核数据和业务约束','stop':item.get('stop_condition','未给出停止条件；执行前需补齐'),'evidence_ids':[x for x in item.get('evidence_ids',[]) if x in evidence]})
    blob=json.dumps(evidence,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    return {'schema_version':'1.0','business_model':{'fulfillment':'order_driven','holds_inventory':False,'supplier_settlement':'monthly'},
            'report':{'id':anchor+'-boss-'+start+'-'+end,'title':title,'subtitle':'同一研究任务 · 冻结证据 · 老板阅读版','kind':kind,'filename':'FC27_boss_'+start+'_'+end+'.html',
                      'period':dict(period,comparison_start=old_start if previous else None,comparison_end=old_end if previous else None,timezone='Asia/Shanghai'),
                      'generated_at':stable_generated_at(result,evidence,metadata),'business_data_captured_at':captured,'source_data_as_of':None,
                      'snapshot_id':anchor,'source_policy':'Admin主站去重支付明细；Order补缺与全站参考分开；缺失不补零','status':'研究已成稿 · 待业务复核',
                      'target_basis':metadata.get('target_basis') or 'DY原版目标；版本、周期、站点和指标含义闭合后才能计算达成'},
            'executive':{'headline':'先看事实，再决定下一步','summary':result.get('summary','原研究正文见下方。'),'confidence_fact':'可展示指标来自同批完整证据；未取得的字段保持缺失。','confidence_unknown':'解释与建议需结合原始证据复核，未自动执行。','now':[],'decision':'请依据正文与证据确认下一步；本版不新增或替你批准行动。'},
            'metrics':metrics,'charts':charts,'payment':payment,'payment_evidence_ids':payment_ids,'hypotheses':[],'context':[{'label':label,'text':'本次未形成可直接展示的完整口径，请核对原报告与证据。','evidence_ids':[]} for label in ['客户与地域','设备与支付','履约与成本']],
            'finance':{'title':'利润与目标保持范围一致','basis':'不把全站参考利润乘主站销售额当作已结算利润或目标实绩。','next':'先补同范围成本、利润定义和目标版本，再判断达成。'},
            'intel':[],'actions':actions,'timeline':[],'decisions':[],'gaps':gaps,'corrections':['同批证据展示，不复用样板数字。','涨跌为描述性比较，不直接推断归因。','建议数量按实际结果，缺少停止条件时明确提示。'],
            'research_text':result.get('raw_model_text',''),'research_url':'https://47.85.224.112/dashboard/fs-home/brain/index.html#reports',
            'provenance':{'evidence_count':len(evidence),'scope':'本任务冻结公开证据；原研究文件保持原字节','research_html_sha256':research_sha,'package_sha256':hashlib.sha256(blob).hexdigest()}}
