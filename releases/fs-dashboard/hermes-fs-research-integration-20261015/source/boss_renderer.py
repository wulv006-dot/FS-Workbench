"""Dependency-free, offline, escaped HTML report renderer. No network or model calls."""
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from contextvars import ContextVar
from decimal import Decimal
from urllib.parse import urlsplit
import argparse, calendar, html, json, math, re

HERE=Path(__file__).resolve().parent
GREEN='#147963'; RED='#b34534'; GREY='#94a3b8'; INK='#182641'; BLUE='#235fe7'
REF_NUMBER=ContextVar('report_references',default={})
def esc(v): return html.escape(str(v),quote=True)
def brief(v):
    """Hide inline evidence codes in the brief; full text remains in details."""
    text=str(v);token=r'ev_[a-f0-9]{24,64}'
    text=re.sub(r'[\[（(]\s*'+token+r'(?:[\s,，、;；]+'+token+r')*\s*[\]）)]','',text)
    text=re.sub(token,'',text)
    return esc(re.sub(r' {2,}',' ',text.replace('[引用]','')).strip())
def safe_url(v):
    p=urlsplit(v)
    if p.scheme!='https' or not p.hostname or p.username or p.password: raise ValueError('Only HTTPS evidence links without credentials are allowed')
    return esc(v)
def number(v,digits=2):
    if v is None: return '缺失'
    return f'{Decimal(str(v)):,.{digits}f}'
def signed(v,digits=2): return '缺失' if v is None else f'{Decimal(str(v)):+,.{digits}f}'

def ratio(amount,orders): return Decimal(str(amount))/Decimal(str(orders)) if amount is not None and orders else None

def delta_color(value): return RED if value>0 else GREEN if value<0 else BLUE

def delta_class(value):
    try:amount=Decimal(str(value).rstrip('%').replace(',',''))
    except Exception:return ''
    return 'up' if amount>0 else 'down' if amount<0 else ''

def series_color(rows,previous='previous',current='current'):
    comparable=[r for r in rows if r.get(previous) is not None and r.get(current) is not None]
    return delta_color(sum(float(r[current])-float(r[previous]) for r in comparable)) if comparable else BLUE
def change(a,b):
    if a is None or b is None or Decimal(str(a))==0:return '不可比'
    return f'{(Decimal(str(b))/Decimal(str(a))-1)*100:+.2f}%'
def refs(ids):
    return ' '.join(f'<a href="#{esc(i)}" title="{esc(i)}">[{REF_NUMBER.get().get(i,"来源")}]</a>' for i in ids)
def table(head,rows):
    return '<div class="table-wrap"><table><thead><tr>'+''.join(f'<th scope="col">{esc(x)}</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td>{esc(x)}</td>' for x in r)+'</tr>' for r in rows)+'</tbody></table></div>'
def validate(c,e):
    if c.get('schema_version')!='1.0': raise ValueError('Unsupported content schema')
    model=c.get('business_model',{})
    if model.get('fulfillment')!='order_driven' or model.get('holds_inventory') is not False or model.get('supplier_settlement')!='monthly':
        raise ValueError('FC business model must be order-driven, no held inventory, monthly supplier settlement')
    narrative=json.dumps({k:v for k,v in c.items() if k not in ['provenance','corrections','research_text','reviewed_research_text']},ensure_ascii=False)
    if re.search('扩库存|囤货|备库存|补库存|库存/可售|库存日志',narrative):
        raise ValueError('Inventory advice does not match the established FC business model')
    r=c['report'];p=r['period'];a=date.fromisoformat(p['start']);b=date.fromisoformat(p['end'])
    if p['timezone']!='Asia/Shanghai' or b<a:raise ValueError('Invalid period/timezone')
    k=r['kind']
    if k=='daily' and a!=b:raise ValueError('Daily requires one complete natural day')
    if k=='weekly' and (a.weekday()!=0 or b.weekday()!=6 or (b-a).days!=6):raise ValueError('Weekly requires complete Monday–Sunday')
    if k=='monthly' and (a.day!=1 or b.day!=calendar.monthrange(b.year,b.month)[1] or a.month!=b.month or a.year!=b.year):raise ValueError('Monthly requires a complete calendar month')
    if k not in ['daily','weekly','monthly','investigation']:raise ValueError('Unknown report kind')
    generated=datetime.fromisoformat(r['generated_at'].replace('Z','+00:00'))
    if generated.tzinfo is None or b>=generated.astimezone(timezone(timedelta(hours=8))).date():raise ValueError('Report requires closed business dates')
    comparison=[p.get(key) for key in ['comparison_start','comparison_end']]
    if any(comparison) and (not all(comparison) or date.fromisoformat(comparison[1])<date.fromisoformat(comparison[0])):raise ValueError('Invalid comparison period')
    if Path(r['filename']).name!=r['filename'] or any(x in r['filename'] for x in '/\\') or not r['filename'].endswith('.html'):raise ValueError('Output must be an HTML basename')
    if not r.get('source_policy') or not r.get('business_data_captured_at'):raise ValueError('Missing source/capture metadata')
    if not isinstance(c['actions'],list) or len(c['actions'])>1000:raise ValueError('Invalid or oversized action index; original research remains available')
    for action in c['actions']:
        for key in ['priority','title','role','when','trigger','steps','metric','cost','risk','stop']:
            if not action.get(key):raise ValueError('Incomplete action: '+key)
    seen=set()
    for chart in c['charts']:
        if not re.fullmatch(r'[a-z][a-z0-9-]*',chart['id']) or chart['id'] in seen:raise ValueError('Bad/duplicate chart id')
        seen.add(chart['id'])
        if chart.get('period_basis')=='current_snapshot' or chart['id']=='queue':
            if chart.get('period_basis')!='current_snapshot' or not chart.get('snapshot_at'):
                raise ValueError('Current queue needs an actual snapshot timestamp')
            if ' vs ' in chart['period'] or chart.get('labels'):
                raise ValueError('Current snapshot cannot carry a weekly comparison label')
        if chart['kind'] not in ['line_compare','waterfall','diverging','bars_compare','bars']:raise ValueError('Unsupported chart kind')
        for key in ['unit','scope','period','as_of','interpretation']:
            if not chart.get(key):raise ValueError('Chart missing '+key)
        if chart['rows'] and not chart.get('evidence_ids'):raise ValueError('Chart requires evidence')
        for row in chart['rows']:
            for key in ['previous','current','value','amount','weekday','weekend','previous_orders','current_orders','previous_aov','current_aov']:
                if key in row and row[key] is not None:
                    v=Decimal(str(row[key]))
                    if not v.is_finite():raise ValueError('Non-finite chart value')
    def walk(v):
        if isinstance(v,dict):
            for key,x in v.items():
                if key.endswith('evidence_ids'):
                    for i in x:
                        if i not in e:raise ValueError('Unknown evidence '+i)
                else:walk(x)
        elif isinstance(v,list):
            for x in v:walk(x)
    walk(c)
    for item in c['intel']:
        safe_url(item['url'])
        if not item.get('retrieved_at') or not item.get('applies'):raise ValueError('Intel needs retrieval/applicable window')
    if len(e)!=c['provenance']['evidence_count']:raise ValueError('Evidence count differs')
    return {'schema':'passed','period':'passed','evidence_references':'passed','actions':'passed','external_code':'none'}
def svg(title,inner,w=600,h=290):return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}"><title>{esc(title)}</title>{inner}</svg>'
def txt(x,y,label,klass='',anchor='start',color=None):
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" class="{klass}"'+(f' style="fill:{color}"' if color else '')+f'>{esc(label)}</text>'
def rect(x,y,w,h,color):return f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w,0):.1f}" height="{max(h,0):.1f}" rx="2" fill="{color}"/>'
def line_chart(ch,key='revenue'):
    rows=ch['rows'];w=620;h=278;left=45;right=565;top=25;bottom=225
    pk,ck={'revenue':('previous','current'),'orders':('previous_orders','current_orders'),'aov':('previous_aov','current_aov')}[key]
    vals=[float(r[k]) for r in rows for k in [pk,ck] if r.get(k) is not None]
    if not vals:return '<p class="empty">缺少有效数据，图表不绘制。</p>'
    maxv=max(1,math.ceil(max(vals)/5)*5 if max(vals)<100 else math.ceil(max(vals)/100)*100)
    minv=min(0,min(vals))
    y=lambda v:bottom-(float(v)-minv)/(maxv-minv or 1)*(bottom-top)
    x=lambda i:left+i*(right-left)/max(1,len(rows)-1)
    marks=''
    if len(rows)==7:marks+=rect(x(5)-(right-left)/12,top,(right-left)/6*1.5,bottom-top,'#f5eee1')
    for i in range(5):
        v=minv+(maxv-minv)*i/4;yy=y(v);marks+=f'<line class="axis" x1="{left}" y1="{yy:.1f}" x2="{right}" y2="{yy:.1f}"/>'+txt(left-9,yy+4,f'{v/1000:.0f}k' if maxv>5000 else f'{v:.0f}',anchor='end')
    for i,r in enumerate(rows):marks+=txt(x(i),bottom+24,r['label'],anchor='middle')
    for field,color,dash in [(pk,GREY,' stroke-dasharray="5 4"'),(ck,series_color(rows,pk,ck),'')]:
        parts=[];segment=[]
        for i,r in enumerate(rows):
            if r.get(field) is None:
                if segment:parts.append(segment);segment=[]
            else:segment.append((x(i),y(r[field]),r[field],r.get('previous_date' if field==pk else 'current_date',r['label'])))
        if segment:parts.append(segment)
        for segment in parts:
            points=' '.join(f'{a:.1f},{b:.1f}' for a,b,_,_ in segment)
            marks+=f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.5"{dash}/>'
            for xx,yy,v,label in segment:
                marks+=f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="3.5" fill="{color}"><title>{esc(label)}: {number(v)} {esc(ch["unit"] if key=="revenue" else "单" if key=="orders" else "USD/单")}</title></circle>'
            xx,yy,v,_=segment[-1];marks+=txt(xx+9,yy+(13 if field==pk else -7),number(v,0 if key=='orders' else 2),'strong')
    return svg(ch['title'],marks,w,h)
def waterfall(ch):
    rows=ch['rows']
    if len(rows)<2 or rows[0].get('role')!='total' or rows[-1].get('role')!='total':
        return '<p class="empty">缺少两期总额，暂不画变化拆解。</p>'
    if any(row.get('value') is None for row in rows):return '<p class="empty">部分变化金额缺失，暂不画拆解。</p>'
    previous,current=Decimal(str(rows[0]['value'])),Decimal(str(rows[-1]['value']))
    changes=rows[1:-1];labels=ch.get('labels') or [rows[0]['label'],rows[-1]['label']]
    out=table(['对照 '+labels[0]+' · USD','本期 '+labels[-1]+' · USD'],[[number(previous),number(current)]])
    net=current-previous
    out+='<p><b>净变化 <span style="color:'+delta_color(net)+'">'+signed(net)+' USD</span></b></p>'
    if any(row.get('role')!='delta' for row in changes):return out+'<p class="empty">分项类型不完整，暂不画变化拆解。</p>'
    residual=net-sum((Decimal(str(r['value'])) for r in changes),Decimal(0))
    if residual:out+='<p class="missing">还有 '+format(residual,'+,f')+' USD 未解释；下图只展示已列出的变化。</p>'
    if not changes:return out+'<p class="empty">尚无分项变化。</p>'
    maximum=max(Decimal(1),max(abs(Decimal(str(r['value']))) for r in changes))
    zero=340;scale=170/float(maximum);height=64+len(changes)*48;marks=''
    marks+=f'<line x1="{zero}" y1="10" x2="{zero}" y2="{height-25}" stroke="{INK}"/>'+txt(zero,height-6,'0',anchor='middle')
    for i,row in enumerate(changes):
        value=Decimal(str(row['value']));width=abs(float(value))*scale;yy=30+i*48
        xx=zero-width if value<0 else zero
        marks+=txt(8,yy-9,row['label'],'strong')+rect(xx,yy,width,26,delta_color(value))
        marks+=txt(zero+float(value)*scale+(-7 if value<0 else 7),yy+19,signed(value),anchor='end' if value<0 else 'start')
    out+='<div class="legend"><span><i class="key" style="background:'+RED+'"></i>增加</span><span><i class="key" style="background:'+GREEN+'"></i>减少</span><span>变化金额 · USD · 从0起</span></div>'
    return out+svg(ch['title']+'：各项增加或减少的金额',marks.replace('<text ','<text style="font-size:17px" '),620,height)
def bar_chart(ch):
    rows=[r for r in ch['rows'] if any(r.get(k) is not None for k in (['previous','current'] if ch['kind']=='bars_compare' else ['value']))];w=500;left=80;right=425;h=48+len(rows)*49;out=''
    if not rows:return '<p class="empty">缺少有效数据，未绘制。</p>'
    if ch['kind']=='diverging':
        mx=max(1,max(abs(float(r['value'])) for r in rows)*1.3);zero=285;scale=190/mx
        out=f'<line x1="{zero}" y1="10" x2="{zero}" y2="{h-26}" stroke="#c5d2c9"/>'
        for i,r in enumerate(rows):
            yy=20+i*49;v=float(r['value']);xx=zero+min(v,0)*scale
            out+=txt(0,yy+18,r['label'],'strong')+rect(xx,yy+2,abs(v)*scale,25,delta_color(v))+txt(zero+v*scale+(-7 if v<0 else 7),yy+19,signed(v,0),anchor='end' if v<0 else 'start')
        out+=txt(zero,h-6,'0',anchor='middle')
    elif ch['kind']=='bars_compare':
        mx=max(1,max((float(r[k]) for r in rows for k in ['previous','current'] if r.get(k) is not None),default=0)*1.23)
        for i,r in enumerate(rows):
            yy=15+i*62
            out+=txt(0,yy+23,r['label'],'strong')
            color=delta_color(float(r['current'])-float(r['previous'])) if r.get('current') is not None and r.get('previous') is not None else BLUE
            for k,color,dy in [('previous',GREY,0),('current',color,22)]:
                if r.get(k) is None:continue
                width=float(r[k])/mx*(right-left);out+=rect(left,yy+dy,width,16,color)+txt(left+width+6,yy+dy+13,number(r[k],0))
        h=48+len(rows)*62
        out+=txt(left,h-8,'金额轴从0起；USD')
    else:
        mx=max(1,max(float(r['value']) for r in rows)*1.18)
        for i,r in enumerate(rows):
            yy=14+i*49;width=float(r['value'])/mx*(right-left)
            out+=txt(0,yy+20,r['label'],'strong')+rect(left,yy+2,width,26,BLUE)+txt(left+width+7,yy+21,number(r['value'],0))
        out+=txt(left,h-8,'数量轴从0起；单')
    return svg(ch['title'],out,w,h)
def chart_figure(ch):
    period_label=('当前订单 · '+ch['snapshot_at'][:10]) if ch.get('period_basis')=='current_snapshot' else ch['period']
    out=f'<figure class="chart" id="chart-{esc(ch["id"])}"><h3>{esc(ch["title"])}</h3><p class="sub">{esc(ch["unit"])} · {esc(period_label)}</p>'
    if not ch['rows']:
        out+='<p class="empty">'+brief(ch.get('empty_label','暂无足够数据，暂不绘图。'))+'</p>'
        return out+'<details><summary>查看数据说明</summary><p>'+esc(ch['interpretation'])+'</p><p>'+esc(ch.get('note',''))+'</p><p>'+esc(ch['scope'])+' · 采集时间 '+esc(ch['as_of'])+'</p>'+refs(ch['evidence_ids'])+'</details></figure>'
    if ch['kind']=='line_compare':
        labels=ch.get('labels') or ['对照期','本期']
        out+='<div class="legend"><span><i class="key prev"></i>'+esc(labels[0])+'</span><span><i class="key" style="background:'+series_color(ch['rows'])+'"></i>'+esc(labels[1])+'</span></div>'
        if ch['id']=='daily':
            out+='<div class="chart-tabs" role="group" aria-label="趋势指标">'+''.join(f'<button type="button" data-chart-tab="{ch["id"]}-{k}" aria-pressed="{str(i==0).lower()}">{name}</button>' for i,(k,name) in enumerate([('revenue','销售额'),('orders','订单'),('aov','客单价')]))+'</div>'
            for i,k in enumerate(['revenue','orders','aov']):out+=f'<div class="chart-panel" id="{ch["id"]}-{k}"'+(' hidden' if i else '')+'>'+line_chart(ch,k)+'</div>'
        else:out+=line_chart(ch)
    elif ch['kind']=='waterfall':out+=waterfall(ch)
    else:
        if ch['kind']=='bars_compare':
            labels=ch.get('labels') or ['对照期','本期']
            out+='<div class="legend"><span><i class="key prev"></i>'+esc(labels[0])+'</span><span>'+esc(labels[-1])+'：涨红 / 跌绿，持平蓝</span></div>'
        out+=bar_chart(ch)
    caption={'daily':'两期销售额、订单和客单价，按日期顺序对比。','bridge':'条形表示各项带来的增加或减少，不是各项销售总额。',
             'platform':'比较两期销售额，增加为红色，减少为绿色。','category':'比较两期销售额，增加为红色，减少为绿色。',
             'queue':'这是当前未完成订单，跨多个支付日，并非报告期末数量。','margin':'参考利润率可用于预估，不等于实际结算利润。'}
    out+='<figcaption>'+esc(caption.get(ch['id'],'展开下方可查看各项金额和数据说明。'))+'</figcaption>'
    if ch['kind']=='line_compare':
        heads=['对齐位置','前期日期','前期值','本期日期','本期值']
        rows=[[r['label'],r.get('previous_date',''),number(r['previous']),r.get('current_date',''),number(r['current'])] for r in ch['rows']]
        if ch['id']=='daily':
            heads+=['前期单数','本期单数','前期客单','本期客单'];rows=[row+[number(r['previous_orders'],0),number(r['current_orders'],0),number(r['previous_aov']),number(r['current_aov'])] for row,r in zip(rows,ch['rows'])]
    elif ch['kind']=='diverging':heads=['平台','前期收入','本期收入','工作日差额','周末差额','前期单数','本期单数'];rows=[[r['label'],number(r['previous']),number(r['current']),signed(r['weekday']),signed(r['weekend']),number(r['previous_orders'],0),number(r['current_orders'],0)] for r in ch['rows']]
    elif ch['kind']=='bars_compare':heads=[ch.get('dimension_label','分组'),'前期收入','本期收入','前期单数','本期单数','前期客单','本期客单'];rows=[[r['label'],number(r.get('previous')),number(r.get('current')),number(r.get('previous_orders'),0),number(r.get('current_orders'),0),number(ratio(r.get('previous'),r.get('previous_orders'))),number(ratio(r.get('current'),r.get('current_orders')))] for r in ch['rows']]
    elif ch['kind']=='bars':heads=['账龄','当前单数','当前金额USD'];rows=[[r['label'],number(r['value'],0),number(r['amount'])] for r in ch['rows']]
    else:heads=['分组','金额USD','类型'];rows=[[r['label'],number(r['value']),r['role']] for r in ch['rows']]
    out+='<details><summary>查看金额明细与数据说明</summary>'+table(heads,rows)+f'<p>{esc(ch["interpretation"])}</p><p class="sub">{esc(ch["note"])}</p><p class="source">范围：{esc(ch["scope"])} · 采集时间：{esc(ch["as_of"])}</p>'+refs(ch['evidence_ids'])+'</details></figure>'
    return out
def section(no,title,body,sid='',aside=''):
    return f'<section class="section"'+(f' id="{sid}"' if sid else '')+f'><div class="section-head"><span class="section-no">{no}</span><h2>{esc(title)}</h2>'+ (f'<span class="aside">{esc(aside)}</span>' if aside else '')+'</div>'+body+'</section>'
def render(c,e):
    validate(c,e);REF_NUMBER.set({i:n+1 for n,i in enumerate(sorted(e))});r=c['report'];p=r['period'];ex=c['executive'];charts={x['id']:dict(x) for x in c['charts']}
    period_name={'daily':'上周同日','weekly':'前周','monthly':'前月','investigation':'对照期'}[r['kind']]
    comparable=bool(p.get('comparison_start') and p.get('comparison_end'))
    if comparable:
        for chart in charts.values():
            if chart.get('period_basis')!='current_snapshot':chart['labels']=[p['comparison_start']+' — '+p['comparison_end'],p['start']+' — '+p['end']]
    comparison=('对照 '+esc(p['comparison_start'])+' — '+esc(p['comparison_end'])) if comparable else '暂无可比数据'
    comparison_note={'daily':'与上周同一天比较','weekly':'与前一周比较','monthly':'与前一个月比较','investigation':'按两期日期比较'}[r['kind']] if comparable else '暂无可比数据'
    body=f'<header id="executive"><div class="mast"><div><div class="eyebrow">经营结果 · 关键变化 · 下一步</div><h1>{esc(r["title"])}</h1><p class="meta">经营参考 · 金额为 USD · 建议尚未执行</p></div><div class="issue"><strong>{esc(p["start"])} — {esc(p["end"])}</strong>{comparison}<br>北京时间</div></div>'
    body+=f'<div class="headline"><div><h2>{brief(ex["headline"])}</h2><p>{brief(ex["summary"])}</p></div><aside class="confidence"><details><summary>判断依据与限制</summary><p>{esc(ex["confidence_fact"])}</p><p>{esc(ex["confidence_unknown"])}</p><p>摘要原文：{esc(ex["summary"])}</p></details></aside></div>'
    body+='<div class="metrics">'
    for m in c['metrics']:
        body+=f'<div class="metric"><span class="label">{esc(m["label"])}</span><span class="value'+(' missing' if m['status']=='missing' else '')+f'">{esc(m["value"])}</span><span class="delta '+(delta_class(m['delta']) if comparable else '')+f'">{esc(m["delta"] if comparable else "不可比")}'+(' · 较'+period_name if m['status']!='missing' and comparable else '')+f'</span><small>{period_name+" " if m["status"]!="missing" and comparable else ""}{esc(m["previous"] if comparable else "未获取同口径对照")}</small></div>'
    body+=f'</div><details class="targets"><summary>查看统计说明与来源</summary><p>{esc(r["subtitle"])}。{esc(r["source_policy"])}；{esc(r.get("metric_basis","客单价=销售额÷订单"))}。数据捕获 {esc(r["business_data_captured_at"])}；上游业务水位{esc(r.get("source_data_as_of") or "UNKNOWN")}。{esc(r.get("target_basis") or "目标口径未提供。")}{refs(c["metrics"][0]["evidence_ids"] if c["metrics"] else [])}</p></details>'
    body+='<div class="now">'+''.join(f'<div class="now-item"><span class="now-num">0{i+1}</span><div><h3>{brief(x["title"])}</h3><p>{brief(x["text"])}</p></div></div>' for i,x in enumerate(ex['now']))+'</div>'
    if ex.get('decision'):body+=f'<div class="decision-strip"><strong>建议怎么做</strong><span>{brief(ex["decision"])}</span></div>'
    body+='</header>'
    if c.get('corrections'):
        body+='<section class="note" id="review-corrections"><details><summary>查看本报告的校正说明</summary><p>原研究保持原文；以下校正适用于本阅读版。提取出的结论和建议仍须业务复核。</p><ul>'+''.join('<li>'+esc(x)+'</li>' for x in c['corrections'])+'</ul></details></section>'
    if c.get('quality_review'):
        review=c['quality_review']
        if any(i.get('severity')=='error' for i in review['issues']):body+='<p class="missing">个别判断与依据有冲突，已在相关句标出；请展开下方说明核对。</p>'
        body+='<details><summary>查看局部待核项</summary>'
        body+='<section class="note" id="evidence-review"><h2>依据与局部待核项</h2><p>'+esc(review['scope'])+'</p><p>轻微缺口保留参考判断；硬冲突只标记相关句，原始研究与证据保留。把握程度、优先动作与反转条件结合正文阅读；建议尚未执行。</p><ul>'
        for issue in review['issues']:
            body+='<li><strong>'+('相关判断需核：' if issue.get('severity')=='error' else '局部提示：')+esc(issue['location'])+'</strong>：'+esc('；'.join(issue['reasons']))+' '+refs(issue.get('evidence_ids',[]))+'</li>'
        if not review['issues']:body+='<li>本次有限规则未发现上述类型的冲突；仍须业务复核。</li>'
        body+='</ul></section></details>'
    if c.get('key_findings'):
        body+='<section class="note"><details><summary>更多研究判断（'+str(len(c['key_findings']))+'项）</summary>'
        for finding in c['key_findings']:
            body+='<p>'+esc(finding['statement'])+'</p><span class="source">'+esc(finding.get('source_section','结构化发现字段'))+' '+refs(finding.get('evidence_ids',[]))+'</span>'
        body+='</details></section>'
    body+=section('01','销售与订单变化','<div class="two">'+chart_figure(charts['daily'])+chart_figure(charts['bridge'])+'</div>',sid='analysis',aside=comparison_note)
    if c.get('research_text'):
        try:
            from report_html import markdown
        except ImportError:
            research='<pre>'+esc(c.get('reviewed_research_text',c['research_text']))+'</pre>'
        else:
            research=markdown(c.get('reviewed_research_text',c['research_text']),e)
        body+='<details class="research-body"><summary>完整研究阅读校正版</summary>'+research+'</details>'
        if c.get('reviewed_research_text',c['research_text'])!=c['research_text']:
            body+='<details class="research-body"><summary>历史原文（未改写；请先看勘误）</summary><pre>'+esc(c['research_text'])+'</pre></details>'
    body+=section('02','哪些平台和商品在变化','<div class="two equal">'+chart_figure(charts['platform'])+chart_figure(charts['category'])+'</div><details><summary>查看原因解释与待验证假设</summary><div class="hypothesis">'+''.join(f'<div><h3>{esc(h["title"])}</h3><p>{esc(h["text"])}</p><span class="source">{refs(h["evidence_ids"])}</span></div>' for h in c['hypotheses'])+'</div></details>')
    pay=table(['支付通道','对照期USD','本期USD','净变化USD'],[[x['label'],number(x['previous']),number(x['current']),signed(x['delta'])] for x in c['payment']])
    pay+='<details><summary>查看支付数据说明</summary><p>'+esc(c.get('payment_note','成功交易金额不是支付成功率；缺少尝试与失败分母时不能判断通道故障。'))+'</p><span class="source">'+esc(r['source_policy'])+'。'+refs(c.get('payment_evidence_ids',[]))+'</span></details>'
    body+=section('03','客户、支付与未完成订单','<div class="two equal"><div>'+pay+'<details><summary>查看地区与设备变化</summary>'+''.join(f'<div class="compact"><h3 style="font-size:14px;margin:0 0 5px">{esc(x["label"])}</h3><p style="font-size:12px;margin:0;color:var(--muted)">{esc(x["text"])}</p><span class="source">{refs(x["evidence_ids"])}</span></div>' for x in c['context'][:2])+'</details></div>'+chart_figure(charts['queue'])+'</div>')
    for x in c['context'][3:]:body+='<div class="note"><strong>'+esc(x['label'])+'</strong><p>'+esc(x['text'])+'</p>'+refs(x.get('evidence_ids',[]))+'</div>'
    estimate_html=''
    for key,label in [('current','本期'),('previous','对照期')]:
        item=c['finance'].get('estimates',{}).get(key)
        if not item:continue
        estimate_period=item['period'];estimate_html+='<h4>'+esc(label+' '+estimate_period['start']+' — '+estimate_period['end'])+'</h4>'
        if item['status']!='estimated':
            estimate_html+='<p class="missing">'+esc(item['reason'])+'</p>';continue
        rate=item.get('reference_margin_percent')
        estimate_html+=table(['主站金额 USD','参考率','预估利润 USD（非实际结算）'],
                             [[number(item['main_revenue_usd']),number(rate)+'%' if rate is not None else '按同日率逐日计算',number(item['amount_usd'])]])
        estimate_html+='<details><summary>查看计算方法与来源</summary><p class="source">'+esc(item['formula'])+' '+refs(item['evidence_ids'])+'</p>'
        for source in item['sources']:
            scope=source['scope'];period=source['period']
            scope_text=('FC27 / Order全站参考' if scope.get('sites')=='all-websites' else
                        'FC27 / Order原生查询；已报告渠道 '+('、'.join(scope.get('reported_channels',[])) or '未提供')+'；渠道完整性未知')
            estimate_html+='<p class="source">'+esc(source['system']+'；参考范围 '+scope_text
                +'；区间 '+period['start']+' 至 '+period['end']+'（截止不含）'+'；参考率 '+source['reference_margin_percent']+'%'
                +'；捕获 '+source['captured_at']+'；上游业务水位 '+str(source['source_data_as_of'] or 'UNKNOWN'))+'</p>'
        estimate_html+='</details>'
    body+=section('04','利润与成本','<div class="two equal">'+chart_figure(charts['margin'])+'<div><h3 style="margin:0;font-size:17px">预估利润（非实际结算）</h3><p style="font-size:13px;color:var(--muted)">按参考利润率估算，供经营判断。</p>'+estimate_html+'<details><summary>查看估算限制与成本说明</summary><p>'+esc(c['finance']['title'])+'。'+esc(c['finance']['basis'])+'</p><div class="note">'+esc(c['context'][2]['text'] if len(c['context'])>2 else '未提供补充风险数据。')+'<span class="source">'+refs(c['context'][2]['evidence_ids'] if len(c['context'])>2 else [])+'</span></div><p>'+esc(c['finance']['next'])+'</p></details></div></div>')
    if 'amount-band' in charts:body+=chart_figure(charts['amount-band'])
    intel=''
    for x in c['intel']:
        intel+=f'<article class="signal"><div class="when"><span class="tag'+(' amber' if '机会' in x['window'] or '期后' in x['window'] else '')+f'">{esc(x["window"])}</span><strong>发布：{esc(x["published_at"] or "未标注")}</strong>事件：{esc(x["event_at"])}<br>适用：{esc(x["applies"])}</div><div><h3>{brief(x["title"])}</h3><p><b>来源内容：</b>{brief(x["fact"])}</p><p><b>可能影响（待验证）：</b>{brief(x["hypothesis"])}</p><p><b>建议行动：</b>{brief(x["action"])}</p><details><summary>查看情报来源</summary><span class="source"><a href="{safe_url(x["url"])}" target="_blank" rel="noopener noreferrer">{esc(x["source"])} · 查看来源</a> · 读取 {esc(x["retrieved_at"])} {refs(x.get("evidence_ids",[]))}</span><p>{esc(x["fact"])}</p><p>{esc(x["hypothesis"])}</p><p>{esc(x["action"])}</p></details></div></article>'
    for x in c.get('intel_pending',[]):
        intel+='<article class="note"><strong>'+esc(x['title'])+'</strong><p>'+esc(x['fact'])+'</p><p>'+esc(x['reason'])+'</p>'+refs(x['evidence_ids'])+'</article>'
    body+=section('05','游戏与市场情报',intel+'<div class="note">'+esc(c.get('intel_note','情报按原来源、事件日期和适用窗口使用；缺少历史市场或同规格竞品数据时，不推断价格趋势。'))+'</div>')
    actions='' if c['actions'] else '<p class="empty">未识别独立行动条目；请复核完整原文，不将索引缺口当作没有建议。</p>'
    for a in c['actions']:
        actions+=f'<article class="action" id="{esc(a["id"])}"><span class="priority">{esc(a["priority"])}</span><div><h3>{brief(a["title"])}</h3><p>{brief(a["steps"])}</p><p><b>看什么：</b>{brief(a["metric"])}</p><details><summary>何时开始、风险与停止条件</summary><p><b>原建议：</b>{esc(a["steps"])}</p><p><b>触发：</b>{esc(a["trigger"])}</p><p><b>成本：</b>{esc(a["cost"])}</p><p><b>风险：</b>{esc(a["risk"])}</p><p><b>停止：</b>{esc(a["stop"])}</p><span class="source">{esc(a.get("source_section","原研究行动字段"))} · {refs(a["evidence_ids"]) or "原文未逐项绑定证据，待核对"}</span></details></div><div class="owner"><strong>{esc(a["role"])}</strong>{esc(a["when"])}</div></article>'
    actions+='<div class="timeline">'+''.join(f'<div class="timepoint"><strong>{esc(t["date"])}</strong><span>{brief(t["text"])}</span></div>' for t in c['timeline'])+'</div><p class="source">以上为建议，尚未执行；实际改价、退款、发布或变更权限，仍须负责人按现行规则批准。</p>'
    body+=section('06','行动与复查',actions,sid='actions',aside=str(len(c['actions']))+'项行动建议')
    decisions='<div class="table-wrap"><table class="choice"><thead><tr><th>决策主题</th><th>建议选项</th><th>另一真实选项</th><th>代价与取舍</th></tr></thead><tbody>'
    for x in c['decisions']:decisions+=f'<tr><td>{esc(x["topic"])}<br><small>{esc(x["status"])}</small></td><td><strong>{esc(x["recommended"])}</strong></td><td>{esc(x["alternative"])}</td><td>{esc(x["tradeoff"])}</td></tr>'
    decisions+='</tbody></table></div>'
    if c['decisions']:body+=section('07','需决策事项',decisions)
    body+='<section class="appendix"><details id="appendix-root"><summary>口径、缺口与'+str(len(e))+'份原始证据（折叠附录）</summary><h3 style="font-size:15px">数据来自哪里，哪些判断还不能下</h3><p class="meta">'+esc(r['source_policy'])+'；快照 '+esc(r['snapshot_id'])+'。'+esc(c['provenance']['scope'])+'</p><ul class="gaps">'+''.join('<li>'+esc(g)+'</li>' for g in c['gaps'])+'</ul><h3 style="font-size:14px">已应用的阅读校正</h3><ul style="font-size:12px;color:var(--muted)">'+''.join('<li>'+esc(g)+'</li>' for g in c['corrections'])+'</ul><p class="meta">完整研究版：<a href="'+(safe_url(c['research_url']) if c.get('research_url') else '#analysis')+'">持久阅读页与原报告</a>。研究HTML SHA256：'+esc(c['provenance']['research_html_sha256'])+'<br>公开证据包 SHA256：'+esc(c['provenance']['package_sha256'])+'</p><h3 style="font-size:14px">原始'+str(len(e))+'份公开证据 / 保持原值</h3><div class="evidence">'
    for i,v in sorted(e.items()):body+=f'<details id="{esc(i)}"><summary>[{REF_NUMBER.get()[i]}] {esc(i)} · {esc(v.get("source",""))}</summary><pre>{esc(json.dumps(v,ensure_ascii=False,indent=2))}</pre></details>'
    body+='</div><p class="meta">'+esc(r.get('method_note','同批证据渲染；行动建议未执行。'))+'</p></details></section>'
    body+='<footer class="foot"><span>MMOEXP / '+esc(r.get('project_label','FC27'))+' · '+esc(r['status'])+'<br>研究供参考，建议尚未执行。</span><span>生成：'+esc(r['generated_at'])+'</span></footer>'
    template=(HERE/'report.template.html').read_text(encoding='utf-8')
    return template.replace('@@TITLE@@',esc(r['title']+' | '+p['start']+'—'+p['end'])).replace('@@BODY@@',body).replace('@@FILENAME_JSON@@',json.dumps(r['filename'],ensure_ascii=False).replace('<','\\u003c'))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--content',type=Path,default=HERE/'sample.content.json');ap.add_argument('--evidence',type=Path,default=HERE/'evidence-public.json');ap.add_argument('--output',type=Path);args=ap.parse_args()
    c=json.loads(args.content.read_text(encoding='utf-8'));e=json.loads(args.evidence.read_text(encoding='utf-8'));result=validate(c,e)
    output=args.output or HERE/c['report']['filename'];output.write_text(render(c,e),encoding='utf-8');print(json.dumps({'output':str(output),'bytes':output.stat().st_size,'validation':result},ensure_ascii=True))
if __name__=='__main__':main()
