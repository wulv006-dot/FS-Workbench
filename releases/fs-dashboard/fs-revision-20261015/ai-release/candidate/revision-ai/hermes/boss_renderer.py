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
    narrative=json.dumps({k:v for k,v in c.items() if k not in ['provenance','corrections']},ensure_ascii=False)
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
    if not 0<=len(c['actions'])<=5:raise ValueError('Use at most 5 concrete actions')
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
            else:segment.append((x(i),y(r[field]),r[field],r['label']))
        if segment:parts.append(segment)
        for segment in parts:
            points=' '.join(f'{a:.1f},{b:.1f}' for a,b,_,_ in segment)
            marks+=f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.5"{dash}/>'
            for xx,yy,v,label in segment:
                marks+=f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="3.5" fill="{color}"><title>{esc(label)}: {number(v)} {esc(ch["unit"] if key=="revenue" else "单" if key=="orders" else "USD/单")}</title></circle>'
            xx,yy,v,_=segment[-1];marks+=txt(xx+9,yy+(13 if field==pk else -7),number(v,0 if key=='orders' else 2),'strong')
    return svg(ch['title'],marks,w,h)
def waterfall(ch):
    if any(row.get('value') is None for row in ch['rows']):return '<p class="empty">缺少完整差额数据，未绘制。</p>'
    totals=[];running=0
    for row in ch['rows']:
        running=float(row['value']) if row.get('role')=='total' else running+float(row['value']);totals.append(running)
    maxv=max(1,max(totals,default=0)*1.15);minv=min(0,min(totals,default=0)*1.15)
    w=max(440,80+len(ch['rows'])*89);h=278;left=40;bottom=225;top=25;bw=46;gap=43
    y=lambda v:bottom-(float(v)-minv)/(maxv-minv)*(bottom-top)
    out='';running=0
    for i in range(5):
        v=minv+(maxv-minv)*i/4;yy=y(v);out+=f'<line class="axis" x1="{left}" y1="{yy:.1f}" x2="{w-30}" y2="{yy:.1f}"/>'+txt(left-6,yy+4,f'{v/1000:.0f}k' if maxv>5000 else f'{v:.0f}',anchor='end')
    for i,row in enumerate(ch['rows']):
        value=float(row['value']);xx=left+12+i*(bw+gap)
        if row.get('role')=='total':a=0;b=value;running=value;color=INK if i==0 else delta_color(value-float(ch['rows'][0]['value']))
        else:a=running;b=running+value;running=b;color=delta_color(value)
        out+=rect(xx,min(y(a),y(b)),bw,abs(y(a)-y(b)),color)+txt(xx+bw/2,min(y(a),y(b))-9,number(value,0) if row.get('role')=='total' else signed(value,0),'strong','middle')+txt(xx+bw/2,bottom+24,row['label'],anchor='middle')
        if i<len(ch['rows'])-1:out+=f'<line x1="{xx+bw}" y1="{y(running):.1f}" x2="{xx+bw+gap}" y2="{y(running):.1f}" stroke="#a1afa4" stroke-dasharray="3 3"/>'
    return svg(ch['title'],out,w,h)
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
    period_label=('当前存量快照 · '+ch['snapshot_at']) if ch.get('period_basis')=='current_snapshot' else ch['period']
    out=f'<figure class="chart" id="chart-{esc(ch["id"])}"><h3>{esc(ch["title"])}</h3><p class="sub">{esc(ch["unit"])} · {esc(period_label)}</p>'
    if not ch['rows']:return out+'<p class="empty">'+esc(ch.get('empty_label','缺失数据，未绘制。'))+'</p><figcaption>'+esc(ch['interpretation'])+'<span class="source">口径：'+esc(ch['scope'])+' · 捕获：'+esc(ch['as_of'])+'</span></figcaption></figure>'
    if ch['kind']=='line_compare':
        labels=ch.get('labels') or ['对照期','本期']
        out+='<div class="legend"><span><i class="key prev"></i>'+esc(labels[0])+'</span><span><i class="key" style="background:'+series_color(ch['rows'])+'"></i>'+esc(labels[1])+'</span></div>'
        if ch['id']=='daily':
            out+='<div class="chart-tabs" role="group" aria-label="趋势指标">'+''.join(f'<button type="button" data-chart-tab="{ch["id"]}-{k}" aria-pressed="{str(i==0).lower()}">{name}</button>' for i,(k,name) in enumerate([('revenue','销售额'),('orders','订单'),('aov','客单价')]))+'</div>'
            for i,k in enumerate(['revenue','orders','aov']):out+=f'<div class="chart-panel" id="{ch["id"]}-{k}"'+(' hidden' if i else '')+'>'+line_chart(ch,k)+'</div>'
        else:out+=line_chart(ch)
    elif ch['kind']=='waterfall':out+=waterfall(ch)
    else:
        if ch['kind']=='bars_compare':out+='<div class="legend"><span><i class="key prev"></i>对照期</span><span>本期：涨红 / 跌绿，持平蓝</span></div>'
        out+=bar_chart(ch)
    out+=f'<figcaption>{esc(ch["interpretation"])}<span class="source">口径：{esc(ch["scope"])} · 捕获：{esc(ch["as_of"])} · 业务水位UNKNOWN<br>{refs(ch["evidence_ids"])}</span></figcaption>'
    if ch['kind']=='line_compare':
        heads=['对齐位置','前期日期','前期值','本期日期','本期值']
        rows=[[r['label'],r.get('previous_date',''),number(r['previous']),r.get('current_date',''),number(r['current'])] for r in ch['rows']]
        if ch['id']=='daily':
            heads+=['前期单数','本期单数','前期客单','本期客单'];rows=[row+[number(r['previous_orders'],0),number(r['current_orders'],0),number(r['previous_aov']),number(r['current_aov'])] for row,r in zip(rows,ch['rows'])]
    elif ch['kind']=='diverging':heads=['平台','前期收入','本期收入','工作日差额','周末差额','前期单数','本期单数'];rows=[[r['label'],number(r['previous']),number(r['current']),signed(r['weekday']),signed(r['weekend']),number(r['previous_orders'],0),number(r['current_orders'],0)] for r in ch['rows']]
    elif ch['kind']=='bars_compare':heads=[ch.get('dimension_label','分组'),'前期收入','本期收入','前期单数','本期单数','前期客单','本期客单'];rows=[[r['label'],number(r.get('previous')),number(r.get('current')),number(r.get('previous_orders'),0),number(r.get('current_orders'),0),number(ratio(r.get('previous'),r.get('previous_orders'))),number(ratio(r.get('current'),r.get('current_orders')))] for r in ch['rows']]
    elif ch['kind']=='bars':heads=['账龄','当前单数','当前金额USD'];rows=[[r['label'],number(r['value'],0),number(r['amount'])] for r in ch['rows']]
    else:heads=['分组','金额USD','类型'];rows=[[r['label'],number(r['value']),r['role']] for r in ch['rows']]
    out+='<details><summary>查看原值表与图表口径</summary>'+table(heads,rows)+f'<p class="sub">{esc(ch["note"])}</p></details></figure>'
    return out
def section(no,title,body,sid='',aside=''):
    return f'<section class="section"'+(f' id="{sid}"' if sid else '')+f'><div class="section-head"><span class="section-no">{no}</span><h2>{esc(title)}</h2>'+ (f'<span class="aside">{esc(aside)}</span>' if aside else '')+'</div>'+body+'</section>'
def render(c,e):
    validate(c,e);REF_NUMBER.set({i:n+1 for n,i in enumerate(sorted(e))});r=c['report'];p=r['period'];ex=c['executive'];charts={x['id']:x for x in c['charts']}
    period_name={'daily':'上周同日','weekly':'前周','monthly':'前月','investigation':'对照期'}[r['kind']]
    comparable=bool(p.get('comparison_start') and p.get('comparison_end'))
    comparison=('对照 '+esc(p['comparison_start'])+' — '+esc(p['comparison_end'])) if comparable else '未获取同口径对照'
    comparison_note={'daily':'完整自然日 · 同星期参考','weekly':'同批冻结数据 · 相邻完整周','monthly':'完整自然月 · 前月参考','investigation':'已闭合日期 · 专题调查'}[r['kind']] if comparable else '未获取同口径对照'
    body=f'<header id="executive"><div class="mast"><div><div class="eyebrow">经营结果 · 关键变化 · 下一步</div><h1>{esc(r["title"])}</h1><p class="meta">{esc(r["subtitle"])}</p></div><div class="issue"><strong>{esc(p["start"])} — {esc(p["end"])}</strong>{comparison}<br>Asia/Shanghai · {esc({"daily":"完整自然日","weekly":"完整自然周","monthly":"完整自然月","investigation":"已闭合日期调查"}[r["kind"]])}</div></div>'
    body+=f'<div class="headline"><div><h2>{esc(ex["headline"])}</h2><p>{esc(ex["summary"])}</p></div><aside class="confidence"><span class="tag">事实与口径</span><p>{esc(ex["confidence_fact"])}</p><span class="tag amber">解释仍待验证</span><p>{esc(ex["confidence_unknown"])}</p></aside></div>'
    body+='<div class="metrics">'
    for m in c['metrics']:
        body+=f'<div class="metric"><span class="label">{esc(m["label"])}</span><span class="value'+(' missing' if m['status']=='missing' else '')+f'">{esc(m["value"])}</span><span class="delta '+(delta_class(m['delta']) if comparable else '')+f'">{esc(m["delta"] if comparable else "不可比")}'+(' · 较'+period_name if m['status']!='missing' and comparable else '')+f'</span><small>{period_name+" " if m["status"]!="missing" and comparable else ""}{esc(m["previous"] if comparable else "未获取同口径对照")}</small></div>'
    body+=f'</div><p class="targets">{esc(r["source_policy"])}；{esc(r.get("metric_basis","客单价=销售额÷订单"))}。数据捕获 {esc(r["business_data_captured_at"])}；上游业务水位{esc(r.get("source_data_as_of") or "UNKNOWN")}。{esc(r.get("target_basis") or "目标口径未提供。")}{refs(c["metrics"][0]["evidence_ids"] if c["metrics"] else [])}</p>'
    body+='<div class="now">'+''.join(f'<div class="now-item"><span class="now-num">0{i+1}</span><div><h3>{esc(x["title"])}</h3><p>{esc(x["text"])}</p></div></div>' for i,x in enumerate(ex['now']))+'</div>'
    if ex.get('decision'):body+=f'<div class="decision-strip"><strong>需决策事项</strong><span>{esc(ex["decision"])}</span></div>'
    body+='</header>'
    body+=section('01','销售与订单变化','<div class="two">'+chart_figure(charts['daily'])+chart_figure(charts['bridge'])+'</div>',sid='analysis',aside=comparison_note)
    if c.get('research_text'):
        try:
            from report_html import markdown
        except ImportError:
            research='<pre>'+esc(c['research_text'])+'</pre>'
        else:
            research=markdown(c['research_text'],e)
        body+='<details class="research-body"><summary>完整研究正文</summary>'+research+'</details>'
    body+=section('02','平台与品类结构','<div class="two equal">'+chart_figure(charts['platform'])+chart_figure(charts['category'])+'</div><div class="hypothesis">'+''.join(f'<div><h3>{esc(h["title"])}</h3><p>{esc(h["text"])}</p><span class="source">{refs(h["evidence_ids"])}</span></div>' for h in c['hypotheses'])+'</div>')
    pay=table(['支付通道','对照期USD','本期USD','净变化USD'],[[x['label'],number(x['previous']),number(x['current']),signed(x['delta'])] for x in c['payment']])
    pay+='<p class="sub">'+esc(c.get('payment_note','成功交易金额不是支付成功率；缺少尝试与失败分母时不能判断通道故障。'))+'</p><span class="source">'+esc(r['source_policy'])+'。'+refs(c.get('payment_evidence_ids',[]))+'</span>'
    body+=section('03','客户、支付与当前存量','<div class="two equal"><div>'+pay+''.join(f'<div class="compact"><h3 style="font-size:14px;margin:0 0 5px">{esc(x["label"])}</h3><p style="font-size:12px;margin:0;color:var(--muted)">{esc(x["text"])}</p><span class="source">{refs(x["evidence_ids"])}</span></div>' for x in c['context'][:2])+'</div>'+chart_figure(charts['queue'])+'</div>')
    body+=section('04','利润、成本与目标口径','<div class="two equal">'+chart_figure(charts['margin'])+'<div><h3 style="margin:0;font-size:17px">'+esc(c['finance']['title'])+'</h3><p style="font-size:13px;color:var(--muted)">'+esc(c['finance']['basis'])+'</p><div class="note">'+esc(c['context'][2]['text'] if len(c['context'])>2 else '未提供补充风险数据。')+'<span class="source">'+refs(c['context'][2]['evidence_ids'] if len(c['context'])>2 else [])+'</span></div><p style="font-size:13px;color:var(--muted)">'+esc(c['finance']['next'])+'</p></div></div>')
    intel=''
    for x in c['intel']:
        intel+=f'<article class="signal"><div class="when"><span class="tag'+(' amber' if '机会' in x['window'] or '期后' in x['window'] else '')+f'">{esc(x["window"])}</span><strong>发布：{esc(x["published_at"] or "未标注")}</strong>事件：{esc(x["event_at"])}<br>适用：{esc(x["applies"])}</div><div><h3>{esc(x["title"])}</h3><p><b>已核实：</b>{esc(x["fact"])}</p><p><b>需求假设：</b>{esc(x["hypothesis"])}</p><p><b>可落地动作：</b>{esc(x["action"])}</p><span class="source"><a href="{safe_url(x["url"])}" target="_blank" rel="noopener noreferrer">{esc(x["source"])} · 查看来源</a> · 读取 {esc(x["retrieved_at"])}</span></div></article>'
    body+=section('05','游戏与市场情报',intel+'<div class="note">'+esc(c.get('intel_note','情报按原来源、事件日期和适用窗口使用；缺少历史市场或同规格竞品数据时，不推断价格趋势。'))+'</div>')
    actions='' if c['actions'] else '<p class="empty">未提供行动建议。</p>'
    for a in c['actions']:
        actions+=f'<article class="action" id="{esc(a["id"])}"><span class="priority">{esc(a["priority"])}</span><div><h3>{esc(a["title"])}</h3><p>{esc(a["steps"])}</p><p><b>观察指标：</b>{esc(a["metric"])}</p><details><summary>触发条件 · 成本/风险 · 停止条件</summary><p><b>触发：</b>{esc(a["trigger"])}</p><p><b>成本：</b>{esc(a["cost"])}</p><p><b>风险：</b>{esc(a["risk"])}</p><p><b>停止：</b>{esc(a["stop"])}</p><span class="source">{refs(a["evidence_ids"])}</span></details></div><div class="owner"><strong>{esc(a["role"])}</strong>{esc(a["when"])}</div></article>'
    actions+='<div class="timeline">'+''.join(f'<div class="timepoint"><strong>{esc(t["date"])}</strong><span>{esc(t["text"])}</span></div>' for t in c['timeline'])+'</div><p class="source">以上均为拟议运营动作与角色分工，未自动下发、未执行。新增接口/权限、业务改价/退款、内容发布/投放仍按各自owner与原合同处理。</p>'
    body+=section('06','行动与复查',actions,sid='actions',aside=str(len(c['actions']))+'项行动建议')
    decisions='<div class="table-wrap"><table class="choice"><thead><tr><th>决策主题</th><th>建议选项</th><th>另一真实选项</th><th>代价与取舍</th></tr></thead><tbody>'
    for x in c['decisions']:decisions+=f'<tr><td>{esc(x["topic"])}<br><small>{esc(x["status"])}</small></td><td><strong>{esc(x["recommended"])}</strong></td><td>{esc(x["alternative"])}</td><td>{esc(x["tradeoff"])}</td></tr>'
    decisions+='</tbody></table></div>'
    if c['decisions']:body+=section('07','需决策事项',decisions)
    body+='<section class="appendix"><details id="appendix-root"><summary>口径、缺口与'+str(len(e))+'份原始证据（折叠附录）</summary><h3 style="font-size:15px">数据来自哪里，哪些判断还不能下</h3><p class="meta">'+esc(r['source_policy'])+'；快照 '+esc(r['snapshot_id'])+'。'+esc(c['provenance']['scope'])+'</p><ul class="gaps">'+''.join('<li>'+esc(g)+'</li>' for g in c['gaps'])+'</ul><h3 style="font-size:14px">已应用的阅读校正</h3><ul style="font-size:12px;color:var(--muted)">'+''.join('<li>'+esc(g)+'</li>' for g in c['corrections'])+'</ul><p class="meta">完整研究版：<a href="'+(safe_url(c['research_url']) if c.get('research_url') else '#analysis')+'">持久阅读页与原报告</a>。研究HTML SHA256：'+esc(c['provenance']['research_html_sha256'])+'<br>公开证据包 SHA256：'+esc(c['provenance']['package_sha256'])+'</p><h3 style="font-size:14px">原始'+str(len(e))+'份公开证据 / 保持原值</h3><div class="evidence">'
    for i,v in sorted(e.items()):body+=f'<details id="{esc(i)}"><summary>[{REF_NUMBER.get()[i]}] {esc(i)} · {esc(v.get("source",""))}</summary><pre>{esc(json.dumps(v,ensure_ascii=False,indent=2))}</pre></details>'
    body+='</div></details></section>'
    body+='<footer class="foot"><span>MMOEXP / '+esc(r.get('project_label','FC27'))+' · '+esc(r['status'])+'<br>研究结论与行动状态分开。</span><span>生成：'+esc(r['generated_at'])+'<br>'+esc(r.get('method_note','同批证据渲染；行动建议未执行。'))+'</span></footer>'
    template=(HERE/'report.template.html').read_text(encoding='utf-8')
    return template.replace('@@TITLE@@',esc(r['title']+' | '+p['start']+'—'+p['end'])).replace('@@BODY@@',body).replace('@@FILENAME_JSON@@',json.dumps(r['filename'],ensure_ascii=False).replace('<','\\u003c'))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--content',type=Path,default=HERE/'sample.content.json');ap.add_argument('--evidence',type=Path,default=HERE/'evidence-public.json');ap.add_argument('--output',type=Path);args=ap.parse_args()
    c=json.loads(args.content.read_text(encoding='utf-8'));e=json.loads(args.evidence.read_text(encoding='utf-8'));result=validate(c,e)
    output=args.output or HERE/c['report']['filename'];output.write_text(render(c,e),encoding='utf-8');print(json.dumps({'output':str(output),'bytes':output.stat().st_size,'validation':result},ensure_ascii=True))
if __name__=='__main__':main()
