"""Project frozen report evidence into the reviewed executive layout; no queries."""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import re
from report_semantics import index, review_action, declared_comparison, intelligence, resource_cost


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


def order_series(evidence, anchor, old_start, old_end, start, end):
    expected=lambda a,b:[(date.fromisoformat(a)+timedelta(days=i)).isoformat() for i in range((date.fromisoformat(b)-date.fromisoformat(a)).days+1)]
    old_days,new_days=expected(old_start,old_end),expected(start,end)
    if len(old_days)!=len(new_days):return None,'两期天数不同，不强行对齐日率。'
    wanted=set(old_days+new_days);values={};references=[];stamps=[]
    for key,row in sorted(evidence.items()):
        data=row.get('data',{});q=data.get('query',row.get('query',{}));rows=data.get('rows',[])
        if (not row.get('source','').startswith('Order参考利润') or row.get('analysis_anchor_id')!=anchor or
                data.get('status')!='available' or data.get('reference_only') is not True or data.get('missingDays')!=[] or q.get('profile')!='FC27'):continue
        try:
            dates=expected(q['start'],q['end'])
            if not set(dates)<=wanted or len(rows)!=len(dates) or {v['date'] for v in rows}!=set(dates):continue
            checked=[]
            for value in rows:
                if (value.get('status')!='available' or value.get('stale') is not False or value.get('profileKey')!='FC27' or
                        value.get('currency')!='USD' or value.get('timezone')!='Asia/Shanghai' or value.get('source')!='order.p2pah.cn' or value.get('marginUnit')!='percent' or
                        value.get('scope')!={'orderGameId':'1322','orderProductType':'','orderStatus':'','sites':'all-websites'}):raise ValueError('reference_scope')
                margin=number(value['profitMarginPct']);stamp=datetime.fromisoformat(value['capturedAt'].replace('Z','+00:00'))
                if stamp.tzinfo is None:raise ValueError('reference_time')
                checked.append((value['date'],margin,stamp.isoformat()))
            for day,margin,stamp in checked:
                if day in values and values[day]!=(margin,stamp):return None,'完整成功参考结果冲突，须明确版本后再展示。'
                values[day]=(margin,stamp)
            references.append(key);stamps.append(row['captured_at'])
        except (KeyError,TypeError,ValueError,ArithmeticError):continue
    if set(values)!=wanted:return None,'未取得同范围完整双期 Order 日率；缺失不补零。'
    return {'rows':[{'label':b[5:],'previous_date':a,'current_date':b,'previous':str(values[a][0]),'current':str(values[b][0]),
                     'previous_captured_at':values[a][1],'current_captured_at':values[b][1]} for a,b in zip(old_days,new_days)],
            'evidence_ids':references,'as_of':max(stamps),'scope':'Order FC27 / all-websites / USD / Asia/Shanghai；上游日率原值，公式未知',
            'interpretation':'按声明的双期区间逐日配对展示参考日率；未据此认定同星期可比，日均不等于整段利润率。主站预估利润按临时公式另列，不作为实际结算或目标实绩。'},None


def project(result, evidence, metadata, research_sha):
    from report_constraints import complete_projection,apply_constraints,estimated_profit
    period = result['period'];start, end = period['start'], period['end']
    kind, old_start, old_end = periods(period);old_start, old_end = old_start.isoformat(), old_end.isoformat()
    explicit,comparison_basis,comparison_ambiguous=declared_comparison(result)
    if explicit:old_start,old_end=explicit
    anchor = result['snapshot_id']
    def eligible(row):
        data = row.get('data', {})
        return (row.get('source') == 'Admin FC支付明细' and row.get('scope') == 'main' and row.get('project') == 'FC27'
                and row.get('snapshot_id') == anchor and row.get('timezone') == 'Asia/Shanghai'
                and data.get('status') == 'available' and data.get('coverage', {}).get('paid_complete') is True
                and not data.get('coverage', {}).get('missing_days') and row.get('query', {}).get('filters') == {})
    def total(lo,hi):
        candidates = []
        standalone=any(eligible(row) and row.get('query',{}).get('start')==lo and row.get('query',{}).get('end')==hi
                       and row.get('query',{}).get('group_by') in ([],['day']) and row.get('data',{}).get('filters_applied')=={}
                       for row in evidence.values())
        for key,row in sorted(evidence.items()):
            q=row.get('query', {});data=row.get('data', {})
            if not eligible(row) or q.get('start') != lo or q.get('end') != hi or not isinstance(q.get('group_by'),list) or data.get('pagination',{}).get('complete') is not True or data.get('filters_applied')!={}:continue
            try:
                value=data['total'];revenue=number(value['revenue_usd']);orders=number(value['orders'])
                if orders < 0 or orders != orders.to_integral_value() or number(value.get('unpriced_orders')) != 0:continue
                if q.get('group_by')==['day']:
                    days={(date.fromisoformat(lo)+timedelta(days=i)).isoformat() for i in range((date.fromisoformat(hi)-date.fromisoformat(lo)).days+1)}
                    groups=data['groups'];keys=[g['group']['day'] for g in groups]
                    if len(keys)!=len(set(keys)) or set(keys)!=days or any(set(g['group'])!={'day'} for g in groups):continue
                    if any(number(g['unpriced_orders'])!=0 or number(g['orders'])<0 or number(g['orders'])!=number(g['orders']).to_integral_value() or number(g['revenue_usd'])<0 for g in groups):continue
                    if (sum(number(g['revenue_usd']) for g in groups),sum(number(g['orders']) for g in groups))!=(revenue,orders):continue
                elif q['group_by']:
                    if standalone:continue
                    if not complete_projection(evidence,q['group_by'][0],lo,hi,row['captured_at'],eligible,(revenue,orders)):continue
                candidates.append((key,revenue,orders,row))
            except (KeyError,ValueError,TypeError,ArithmeticError):continue
        if len({(v[1],v[2],v[3].get('captured_at')) for v in candidates}) != 1:return None
        return candidates[0]
    current, previous = total(start,end), None if comparison_ambiguous else total(old_start,old_end)
    if current and previous and current[3].get('captured_at')!=previous[3].get('captured_at'):previous=None
    captured = current[3]['captured_at'] if current else '未取得完整同口径汇总'
    ids = [v[0] for v in (current,previous) if v]
    def facts(value):
        revenue,orders=number(value['revenue_usd']),number(value['orders'])
        if revenue<0 or orders<0 or orders!=orders.to_integral_value() or number(value['unpriced_orders'])!=0:raise ValueError('invalid_group_facts')
        return revenue,orders
    def grouped(dimension,lo,hi,item,pool=False):
        if not current:return None
        return complete_projection(evidence,dimension,lo,hi,current[3]['captured_at'],eligible,
                                   (item[1],item[2]) if item else None,pool)
    def comparison_rows(old,new):
        # A group absent from a fully reconciled complete population has zero orders/amount.
        rows=[]
        for label in sorted(set(old[0])|set(new[0])):
            a=old[0].get(label);b=new[0].get(label)
            av,ao=facts(a) if a else (Decimal(0),Decimal(0));bv,bo=facts(b) if b else (Decimal(0),Decimal(0))
            rows.append({'label':label,'previous':str(av),'current':str(bv),'previous_orders':int(ao),'current_orders':int(bo),
                         'previous_aov':str(av/ao) if ao else None,'current_aov':str(bv/bo) if bo else None})
        return rows
    def covered(dimension,lo,hi):
        values={};source_ids=[]
        for key,row in sorted(evidence.items()):
            q=row.get('query',{});data=row.get('data',{})
            if (not eligible(row) or not current or row.get('captured_at')!=current[3].get('captured_at') or
                    q.get('start')!=lo or q.get('end')!=hi or q.get('group_by')!=[dimension] or data.get('filters_applied')!={}):continue
            try:
                for value in data['groups']:
                    label=value['group'][dimension];facts(value)
                    if not isinstance(label,str) or set(value['group'])!={dimension}:raise ValueError('group_label')
                    if label in values and facts(values[label])!=facts(value):return None
                    values[label]=value
                source_ids.append(key)
            except (KeyError,TypeError,ValueError,ArithmeticError):return None
        return (values,source_ids) if values else None
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
    observations={};observation_conflict=False
    # Combine complete date queries; reconcile both windows to independent totals.
    if current and previous:
        days=lambda lo,hi:[(date.fromisoformat(lo)+timedelta(days=i)).isoformat() for i in range((date.fromisoformat(hi)-date.fromisoformat(lo)).days+1)]
        old_days,new_days=days(old_start,old_end),days(start,end)
        wanted=set(old_days+new_days);values={};daily_ids=[];conflict=False
        for key,row in sorted(evidence.items()):
            q=row.get('query',{});data=row.get('data',{})
            if (not eligible(row) or row.get('captured_at')!=current[3].get('captured_at') or q.get('group_by')!=['day'] or
                    data.get('pagination',{}).get('complete') is not True or data.get('filters_applied')!={}):continue
            try:
                incoming={g['group']['day']:g for g in data['groups']}
                if len(incoming)!=len(data['groups']) or set(incoming)!=set(days(q['start'],q['end'])):continue
                if any(facts(g)[0]<0 for g in incoming.values()):continue
                if (sum((facts(g)[0] for g in incoming.values()),Decimal(0)),sum((facts(g)[1] for g in incoming.values()),Decimal(0)))!=facts(data['total']):continue
                for day in incoming:
                    if old_start<=day<=end:
                        if day in observations and facts(observations[day])!=facts(incoming[day]):observation_conflict=True
                        observations[day]=incoming[day]
                for day in wanted&set(incoming):
                    if day in values and facts(values[day])!=facts(incoming[day]):conflict=True
                    values[day]=incoming[day]
                if wanted&set(incoming):daily_ids.append(key)
            except (ValueError,KeyError,TypeError,ArithmeticError):continue
        if not conflict and len(old_days)==len(new_days) and set(values)==wanted:
            if all(sum(number(values[d]['revenue_usd']) for d in group)==item[1] and sum(number(values[d]['orders']) for d in group)==item[2] for group,item in ((old_days,previous),(new_days,current))):
                rows=[]
                for a,b in zip(old_days,new_days):
                    av,bv=values[a],values[b];ao,bo=number(av['orders']),number(bv['orders'])
                    rows.append({'label':b[5:],'previous_date':a,'current_date':b,'previous':av['revenue_usd'],'current':bv['revenue_usd'],
                                 'previous_orders':av['orders'],'current_orders':bv['orders'],'previous_aov':str(number(av['revenue_usd'])/ao) if ao else None,'current_aov':str(number(bv['revenue_usd'])/bo) if bo else None})
                charts[0].update(rows=rows,evidence_ids=daily_ids+ids,interpretation='按明确对照区间的完整日序列展示；金额与订单已与同批汇总核平，变化本身不等于原因。')
    payment=[];payment_ids=[]
    if current and previous:
        for dimension,chart_index,title in [('platform',2,'平台销售与订单'),('product',3,'品类销售与订单'),('amount_band',6,'支付金额档结构')]:
            a,b=grouped(dimension,old_start,old_end,previous),grouped(dimension,start,end,current)
            if not a or not b:continue
            rows=comparison_rows(a,b);source_ids=a[1]+b[1]+ids
            if chart_index==6:charts.append(dict(charts[5],id='amount-band'))
            charts[chart_index].update(kind='bars_compare',title=title,unit='USD',scope='Admin 主站完整支付明细',rows=rows,evidence_ids=list(dict.fromkeys(source_ids)),
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
                age_order={v:i for i,v in enumerate(['under1d','1to3d','3to7d','7to14d','over14d'])}
                charts[4].update(rows=[{'label':label,'value':int(facts(v)[1]),'amount':str(facts(v)[0])} for label,v in sorted(queue[0].items(),key=lambda item:(age_order.get(item[0],99),item[0]))],evidence_ids=queue[1],
                                 snapshot_at=captured_time.isoformat(),as_of=captured_time.isoformat(),period='当前存量快照 · '+captured_time.isoformat(),
                                 interpretation='采集时点的当前未结存量；不能当作报告期末或本期新增队列。',note='完整无过滤当前池按账龄分组并与该池总量核平，不能推造历史趋势。')
        except (KeyError,ValueError):pass
    title='FC27 '+{'daily':'经营日报','weekly':'运营周报','monthly':'经营月报','investigation':'经营调查'}[kind]
    gaps=list(result.get('limitations',[]))+['目标基准沿用DY原版，未与本报告精确期间及字段闭合前不计算达成。','Order参考利润不是主站结算利润；当前未结池不是报告期末历史存量。','原始研究判断由Hermes产生，本版仅从同批证据排版，尚需业务复核。']
    if not current:gaps.append('本次证据没有可核平的同快照、同区间、主站完整支付汇总，指标保持缺失。')
    if not previous:gaps.append('未取得同口径对照期汇总，未计算涨跌。')
    if comparison_ambiguous:gaps.append(comparison_basis)
    semantic=index(result,evidence)
    corrections=['本版独立保存；原始研究、原始老板版及冻结证据保持原字节。','索引提取不代表业务验证，建议均待复核、未下发或执行。']
    reference,reference_gap=(None,comparison_basis) if comparison_ambiguous else order_series(evidence,anchor,old_start,old_end,start,end)
    if reference:charts[5].update(reference,note='全站上游参考日率，非主站结算利润；可按用户临时口径乘对应日期主站金额估算，不当作采购成本或整周利润率。')
    else:gaps.append(reference_gap)
    estimates={'current':estimated_profit(evidence,anchor,start,end,current,eligible),
               'previous':estimated_profit(evidence,anchor,old_start,old_end,previous,eligible)}
    corrections.append('2026-10-15临时利润口径优先：主站预估利润=主站订单金额×对应参考利润率÷100；允许Order参考范围与主站不同并披露。旧研究中禁止据参考率估算的限制不再适用；仍非实际结算、核实成本或目标实绩。')
    for item in estimates.values():
        if item['status']=='missing':gaps.append(item['period']['start']+' — '+item['period']['end']+'：'+item['reason'])
    context=[]
    for dimension,label in [('country','地域覆盖行'),('device','设备结构')]:
        a=(None if comparison_ambiguous else grouped(dimension,old_start,old_end,previous) or covered(dimension,old_start,old_end))
        b=grouped(dimension,start,end,current) or covered(dimension,start,end)
        if not a or not b:
            context.append({'label':label,'text':'未取得同口径可比覆盖行；与客户身份/复购缺口分开。','evidence_ids':[]});continue
        labels=set(a[0])&set(b[0])
        selected=sorted(labels,key=lambda name:abs(facts(b[0][name])[0]-facts(a[0][name])[0]),reverse=True)[:5]
        text='；'.join(name+' $'+format(facts(a[0][name])[0],',.2f')+' → $'+format(facts(b[0][name])[0],',.2f') for name in selected)
        context.append({'label':label,'text':text+'。仅列已知两期行；有分页/Top 截断时不代表全体，不把未出现的组补零。客户身份与复购仍未验证。',
                        'evidence_ids':list(dict.fromkeys(a[1]+b[1]))})
    context.append({'label':'履约与成本','text':'当前未结池为跨支付日存量，未提供同口径历史队列流入/退出；成本、利润定义未闭合，不能推算结算利润。','evidence_ids':queue[1] if queue else []})
    context.extend(dict(row,label='研究补充（待复核）：'+row.get('label','背景')) for row in result.get('context',[]) if isinstance(row,dict) and isinstance(row.get('text'),str))
    daily=charts[0]['rows'];raw=semantic['research_text']
    if kind=='weekly' and len(daily)==7 and current and previous:
        weekday=sum((number(r['current'])-number(r['previous']) for r in daily if date.fromisoformat(r['current_date']).weekday()<5),Decimal(0))
        weekend=sum((number(r['current'])-number(r['previous']) for r in daily if date.fromisoformat(r['current_date']).weekday()>=5),Decimal(0))
        if weekday+weekend==current[1]-previous[1]:
            charts[1].update(rows=[{'label':'对照期','role':'total','value':str(previous[1])},{'label':'工作日净变化','role':'delta','value':str(weekday)},
                                   {'label':'周末净变化','role':'delta','value':str(weekend)},{'label':'本期','role':'total','value':str(current[1])}],
                             evidence_ids=charts[0]['evidence_ids'],interpretation='按完整同星期日序列定位变化；工作日与周末差额闭合，变化位置不证明原因。')
            if current[1]<previous[1] and weekend<0 and weekday>0:
                corrections.append('周末负差额占净下降 '+format(-weekend/(previous[1]-current[1])*100,'.2f')+'%，工作日抵消 '+format(weekday/(previous[1]-current[1])*100,'.2f')+'%；原文若写数值100%应以此校正。')
    rebound=False
    if observations and not observation_conflict and re.search('连续回落|持续走低|连续下降',raw):
        ordered=sorted(observations);peak=max(ordered,key=lambda day:number(observations[day]['orders']))
        after=[d for d in ordered if d>=peak]
        rebounds=[(a,b) for a,b in zip(after,after[1:]) if (date.fromisoformat(b)-date.fromisoformat(a)).days==1 and number(observations[b]['orders'])>number(observations[a]['orders'])]
        if rebounds:
            rebound=True
            corrections.append('逐日证据存在反弹：'+'；'.join(a+' '+str(observations[a]['orders'])+' 单 → '+b+' '+str(observations[b]['orders'])+' 单' for a,b in rebounds)+'；撤回逐日连续下降的表述，整体变化不能证明节奏或需求机制。')
    if re.search('sale_total|捆绑|数量堆叠',raw):corrections.append('商品 sale_total 与 order_count 接近并不能证明件数或排除多件/捆绑；字段定义、订单行、SKU规格及数量/优惠未闭合，相关原因保持未证。')
    replacements=[]
    if current and previous and current[2] and previous[2]:
        before,after=previous[1]/previous[2],current[1]/current[2]
        exact=format((after/before-1)*100,'+.2f')+'%' if before else '不可比'
        if before and before.quantize(Decimal('.01')):
            rounded=format((after.quantize(Decimal('.01'))/before.quantize(Decimal('.01'))-1)*100,'+.2f')+'%'
            if rounded!=exact:replacements.append((rounded,exact))
        volume=((current[2]-previous[2])*before).quantize(Decimal('.01'))
        basket=(current[1]-previous[1]).quantize(Decimal('.01'))-volume
        corrections.append('客单价按原金额/订单精算：'+exact+'；量效应 $'+format(volume,',.2f')+' + 客单效应 $'+format(basket,',.2f')+' = 净变化 $'+format(current[1]-previous[1],',.2f')+'。用未舍入值计算，显示值按分闭合。')
    try:
        capture_day=datetime.fromisoformat(captured.replace('Z','+00:00')).astimezone(timezone(timedelta(hours=8))).date()
        for match in re.finditer(r'对\s*(\d{2}-\d{2})\s*为\s*T\+(\d+)',raw):
            day=date.fromisoformat(start[:4]+'-'+match[1]);age=(capture_day-day).days
            if age!=int(match[2]):corrections.append(match[1]+' 在 '+capture_day.isoformat()+' 采集时为 T+'+str(age)+'，原文 T+'+match[2]+' 有误；各业务日成熟度仍不同。')
    except (ValueError,TypeError):pass
    if '周末仍有' in raw:corrections.append('原文把整周头部商品单量用于证明周末供给，期间不匹配，撤回该反证。')
    if '库存' in raw:corrections.append('本业务按订单驱动、无持货库存；只核供应商接单/履约与页面可用性，不作备货或库存推断。')
    if '若为纯提价' in raw:corrections.append('周末客单增幅不能排除纯提价；同 SKU 数量、优惠与组合未控制，客单不是单位售价。')
    if re.search(r'不是.{0,4}提价|提价导致失单.{0,120}不成立',raw,re.S):corrections.append('总客单或订单方向不能排除局部提价、折扣、规格与组合变化；原文“不是/不成立”应降为未证实，也不能据此认定反向因果。')
    def reviewed_text(text):
        for a,b in replacements:
            # Bind correction to an explicit global AOV label, never a bare
            # percentage also used by another metric or a named subgroup.
            pattern=r'(?<![\w])((?:主站|总体|整体)?(?:客单价|客单|单均价)\s*(?:增幅|环比|变化)?\s*[:：]?\s*)'+re.escape(a)
            text=re.sub(pattern,lambda m:m[1]+b,text)
        if rebound and re.search('峰值|见顶',text):
            text='\n\n'.join(re.sub('连续回落|持续走低|连续下降','整体回落、期间有反弹',block) if re.search('峰值|见顶',block) else block for block in text.split('\n\n'))
            text+='（走势描述不能证明节奏或需求机制，仍待验证。）'
        if re.search('单件高价|数量堆叠|未观察到多商品捆绑',text):
            text+='（商品字段定义及订单行数量未闭合，不能据此排除多件或捆绑。）'
            text=text.replace('（件数与订单数接近 1:1）','（字段原值接近；单位与粒度待核）')
            text=text.replace('主要来自**单件高价商品**而非数量堆叠','可见高价商品行，但尚不能确认订单内件数或排除数量/组合影响')
            text=text.replace('未观察到多商品捆绑痕迹','已见样本不足以排除多商品捆绑').replace('可见的是"单商品"购买','只观察到商品分组行，订单内商品构成未验证')
        text=text.replace('量降价升','单量下降、客单上升').replace('量缩价平','单量减少、客单基本持平').replace('量崩、价平','单量下降、客单略升')
        text=re.sub(r'不是["“]?提价失单["”]?，也不是["“]?降价换量["”]?','提价失单、降价换量均未获证实，也不能排除局部价格、规格或组合影响',text)
        text=re.sub(r'PS\s*头部商品当周末仍有\s*[\d,]+\s*单','PS 头部商品仅有整周销量，不能据此排除周末供给限制',text)
        return text.replace('供给/库存限制','供应商接单/履约能力限制（待证，无持货库存）')
    actions=[]
    for i,original in enumerate(semantic['actions']):
        item=review_action(original);corrections.extend(item['review_notes'])
        actions.append({'id':'action-'+str(i+1),'priority':'待复核建议','title':item.get('target','待明确对象'),'role':item.get('role','责任人待明确'),'when':item.get('review_at','复查时间待明确'),
                        'trigger':item.get('condition','触发条件待明确'),'steps':item.get('action','行动待明确'),'metric':item.get('success_check','验收指标待明确'),
                        'cost':resource_cost(item),'risk':item.get('cost_risk','需复核数据和业务约束')+'；提取不代表通过业务验证。',
                        'stop':item.get('stop_condition','未给出停止条件；执行前需补齐'),'source_section':item.get('source_section','结构化行动字段'),
                        'evidence_ids':[x for x in item.get('evidence_ids',[]) if x in evidence]})
    intel,intel_pending,intel_note=intelligence(result,evidence)
    blob=json.dumps(evidence,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    content={'schema_version':'1.0','business_model':{'fulfillment':'order_driven','holds_inventory':False,'supplier_settlement':'monthly'},
            'report':{'id':anchor+'-boss-semantic-v2-'+start+'-'+end,'title':title,'subtitle':'同一研究任务 · 冻结证据 · 阅读校正版 v2','kind':kind,'filename':'FC27_boss_reviewed_v2_'+start+'_'+end+'.html',
                      'period':dict(period,comparison_start=old_start if previous else None,comparison_end=old_end if previous else None,comparison_basis=comparison_basis,timezone='Asia/Shanghai'),
                      'generated_at':stable_generated_at(result,evidence,metadata),'business_data_captured_at':captured,'source_data_as_of':None,
                      'snapshot_id':anchor,'source_policy':'Admin主站去重支付明细；Order补缺与全站参考分开；缺失不补零','status':'研究已成稿 · 待业务复核',
                      'target_basis':metadata.get('target_basis') or 'DY原版目标；版本、周期、站点和指标含义闭合后才能计算达成'},
            'executive':{'headline':'；'.join(m['label']+' '+m['delta'] for m in metrics[:3]) if current and previous else '经营调查：先复核可比事实与缺口',
                         'summary':reviewed_text(semantic['summary']),'confidence_fact':'可展示指标来自同批完整证据；未取得的字段保持缺失。',
                         'confidence_unknown':'下列原研究判断与提取建议仍待业务复核；可见勘误优先于历史原文。',
                         'now':[{'title':a['title'],'text':'待复核：'+a['steps']} for a in actions[:3]],'decision':'先完成列明的补证与复查，再由负责人决定是否执行建议。'},
            'key_findings':[dict(row,statement=reviewed_text(row['statement'])) for row in semantic['findings']],
            'metrics':metrics,'charts':charts,'payment':payment,'payment_evidence_ids':payment_ids,
            'hypotheses':[dict(row,text=reviewed_text(row['text'])) for row in semantic['hypotheses']],'context':context,
            'finance':{'title':'主站预估利润（临时参考口径）','estimates':estimates,
                       'basis':'按2026-10-15用户临时口径，主站预估利润=主站订单金额×对应参考利润率÷100。优先同区间原生参考率；缺区间率时逐日匹配金额和参考率求和，不平均日率。允许来源范围不同并列明，缺值不补零。',
                       'next':'用于经营参考，非实际结算利润；不改变采购成本、结算账本或打款。取得准确利润渠道后按用户指令更新；目标须另核版本与口径。'},
            'intel':intel,'intel_pending':intel_pending,'intel_note':intel_note,
            'actions':actions,'timeline':[dict(row) for row in result.get('timeline',[]) if isinstance(row,dict) and all(isinstance(row.get(k),str) for k in ('date','text'))],
            'decisions':[dict(row,**{k:row.get(k) or '待补：'+k for k in ('topic','status','recommended','alternative','tradeoff')}) for row in result.get('decisions',[]) if isinstance(row,dict)],
            'gaps':gaps,'corrections':list(dict.fromkeys(corrections)),
            'research_text':result.get('raw_model_text') or semantic['research_text'],'reviewed_research_text':reviewed_text(semantic['research_text']),'research_url':'https://47.85.224.112/dashboard/fs-home/brain/index.html#reports',
            'provenance':{'evidence_count':len(evidence),'scope':'本任务冻结公开证据；原研究文件保持原字节','research_html_sha256':research_sha,'package_sha256':hashlib.sha256(blob).hexdigest()}}
    return apply_constraints(content,evidence)
