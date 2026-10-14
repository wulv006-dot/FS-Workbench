"""Self-contained HTML from validated model text and its same-run evidence.

No remote assets, generated scripts, model HTML, or invented business judgements.
"""
from html import escape
from decimal import Decimal
import json
import re


def text(value):
    return escape(str(value if value is not None else '未提供'), quote=True)


def paragraphs(value):
    return ''.join('<p>'+text(part)+'</p>' for part in str(value).split('\n') if part.strip())


def refs(ids, evidence=None):
    ids=(ref for ref in ids if evidence is None or ref in evidence)
    return '<div class="refs">'+''.join('<a href="#'+text(ref)+'">证据 '+text(ref[-8:])+'</a>' for ref in ids)+'</div>'


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+text(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+text(cell)+'</td>' for cell in row)+'</tr>' for row in rows)+'</tbody></table></div>'


_INLINE = re.compile(
    r'(?P<escaped>\\[\\`*_{}\[\]()#+.!|>~-])'
    r'|(?P<code>(?<!`)(?P<ticks>`{1,64})(?!`)(?P<code_text>.*?)(?<!`)(?P=ticks)(?!`))'
    r'|(?P<link>!?\[[^\]\n]*\]\([^\)\n]*\))'
    r'|(?P<combined>\*\*\*(?=\S).+?(?<=\S)\*\*\*|(?<!\w)___(?=\S).+?(?<=\S)___(?!\w))'
    r'|(?P<strong>\*\*(?=\S).+?(?<=\S)\*\*|(?<!\w)__(?=\S).+?(?<=\S)__(?!\w))'
    r'|(?P<em>(?<!\*)\*(?!\*)(?=\S).+?(?<=\S)\*(?!\*)|(?<!\w)_(?!_)(?=\S).+?(?<=\S)_(?!\w))'
    r'|(?P<ref>\bev_[a-f0-9]{24}\b)', re.S)
_HEADING = re.compile(r'^ {0,3}(#{1,6})[ \t]+(.+?)\s*$')
_FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
_LIST = re.compile(r'^( *)([-+*]|[0-9]{1,9}[.)])[ \t]+(.*)$')
_RULE = re.compile(r'^ {0,3}(?:\*\s*){3,}$|^ {0,3}(?:-\s*){3,}$|^ {0,3}(?:_\s*){3,}$')


def _inline(value, known, depth=0):
    """Only fixed markup and same-run evidence anchors; links stay literal text."""
    if depth >= 12:
        return text(value).replace('\n', '<br>')
    parts=[]; end=0
    for match in _INLINE.finditer(value):
        parts.append(text(value[end:match.start()]).replace('\n', '<br>'))
        token=match.group()
        if match.group('escaped') is not None:
            parts.append(text(token[1:]))
        elif match.group('code') is not None:
            parts.append('<code>'+text(match.group('code_text'))+'</code>')
        elif match.group('link') is not None:
            local=re.fullmatch(r'\[([^\]\n]*)\]\(#?(ev_[a-f0-9]{24})\)',token)
            if local and local[2] in known:
                parts.append('<a href="#'+local[2]+'">'+text(local[1])+'</a>')
            else:
                parts.append(text(token))
        elif match.group('combined') is not None:
            parts.append('<strong><em>'+_inline(token[3:-3],known,depth+1)+'</em></strong>')
        elif match.group('strong') is not None:
            parts.append('<strong>'+_inline(token[2:-2],known,depth+1)+'</strong>')
        elif match.group('em') is not None:
            parts.append('<em>'+_inline(token[1:-1],known,depth+1)+'</em>')
        elif token in known:
            parts.append('<a href="#'+text(token)+'">'+text(token)+'</a>')
        else:
            parts.append(text(token))
        end=match.end()
    parts.append(text(value[end:]).replace('\n', '<br>'))
    return ''.join(parts)


def _cells(line):
    """Split table pipes except escaped pipes and pipes inside inline code."""
    cells=[]; current=[]; ticks=0; i=0
    while i<len(line):
        char=line[i]
        if char=='\\' and i+1<len(line):
            current.append(line[i:i+2]); i+=2; continue
        if char=='`':
            end=i+1
            while end<len(line) and line[end]=='`': end+=1
            size=end-i
            if not ticks: ticks=size
            elif ticks==size: ticks=0
            current.append(line[i:end]); i=end; continue
        if char=='|' and not ticks:
            cells.append(''.join(current).strip()); current=[]
        else:
            current.append(char)
        i+=1
    cells.append(''.join(current).strip())
    if cells and not cells[0] and line.lstrip().startswith('|'): cells.pop(0)
    if cells and not cells[-1] and line.rstrip().endswith('|'): cells.pop()
    return cells


def _table_start(rows, index):
    if index+1>=len(rows) or '|' not in rows[index]: return False
    header=_cells(rows[index]); separator=_cells(rows[index+1])
    return bool(header) and len(header)==len(separator) and all(re.fullmatch(r':?-{3,}:?',cell) for cell in separator)


def _blocks(rows, known, depth=0):
    if depth>=32:
        return '<p>'+text('\n'.join(rows)).replace('\n','<br>')+'</p>'
    parts=[]; i=0
    while i<len(rows):
        row=rows[i]
        if not row.strip(): i+=1; continue
        fence=_FENCE.match(row)
        heading=_HEADING.match(row)
        item=_LIST.match(row)
        if fence:
            marker=fence[1]; i+=1; code=[]
            close=re.compile(r'^ {0,3}'+re.escape(marker[0])+'{'+str(len(marker))+r',}\s*$')
            while i<len(rows) and not close.fullmatch(rows[i]):
                code.append(rows[i]); i+=1
            if i<len(rows): i+=1
            parts.append('<pre><code>'+text('\n'.join(code))+'</code></pre>')
        elif heading:
            level=str(len(heading[1])); label=re.sub(r'\s+#+\s*$','',heading[2])
            parts.append('<h'+level+'>'+_inline(label,known)+'</h'+level+'>'); i+=1
        elif _table_start(rows,i):
            headers=_cells(row); i+=2; values=[]
            while i<len(rows) and rows[i].strip() and '|' in rows[i]:
                values.append(_cells(rows[i])); i+=1
            parts.append('<div class="scroll"><table><thead><tr>'+''.join('<th>'+_inline(cell,known)+'</th>' for cell in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+_inline(cell,known)+'</td>' for cell in cells)+'</tr>' for cells in values)+'</tbody></table></div>')
        elif item:
            indent=len(item[1]); ordered=item[2][0].isdigit(); tag='ol' if ordered else 'ul'; items=[]
            while i<len(rows):
                match=_LIST.match(rows[i])
                if not match or len(match[1])!=indent or match[2][0].isdigit()!=ordered: break
                content=[match[3]]; number=match[2][:-1] if ordered else None; i+=1
                while i<len(rows):
                    if not rows[i].strip():
                        next_line=i+1
                        while next_line<len(rows) and not rows[next_line].strip(): next_line+=1
                        if next_line==len(rows) or len(rows[next_line])-len(rows[next_line].lstrip(' '))<=indent: break
                        content.extend(rows[i:next_line]); i=next_line
                    leading=len(rows[i])-len(rows[i].lstrip(' '))
                    if leading<=indent: break
                    content.append(rows[i][min(leading,indent+2):]); i+=1
                items.append('<li'+(' value="'+str(int(number))+'"' if ordered else '')+'>'+_blocks(content,known,depth+1)+'</li>')
            parts.append('<'+tag+'>'+''.join(items)+'</'+tag+'>')
        elif _RULE.fullmatch(row):
            parts.append('<hr>'); i+=1
        else:
            paragraph=[row]; i+=1
            while i<len(rows) and rows[i].strip() and not (_FENCE.match(rows[i]) or _HEADING.match(rows[i]) or _LIST.match(rows[i]) or _RULE.fullmatch(rows[i]) or _table_start(rows,i)):
                paragraph.append(rows[i]); i+=1
            parts.append('<p>'+_inline('\n'.join(paragraph),known)+'</p>')
    return ''.join(parts)


def markdown(value, evidence=None):
    """Render a bounded Markdown subset without executing HTML, links or code."""
    return _blocks(str(value).splitlines(),set(evidence or {}))


def money(value):
    return '$'+format(Decimal(str(value)),',.2f') if value is not None else '未提供'


def lines(series, title):
    """Each series is (label, [(label, Decimal amount)]); absence is never zero."""
    if not series or not any(points for _,points in series):return ''
    largest=max(v for _,points in series for _,v in points)
    ceiling=largest*Decimal('1.12') or Decimal(1)
    colors=('#2563eb','#94a3b8','#0d9488'); parts=[]
    for index,(label,points) in enumerate(series):
        xy=[]
        for i,(day,value) in enumerate(points):
            x=55+i*690/max(len(points)-1,1);y=210-float(value/ceiling)*165
            xy.append('%.2f,%.2f'%(x,y))
            parts.append('<circle cx="%.2f" cy="%.2f" r="4" fill="%s"><title>%s · %s</title></circle>'%(x,y,colors[index%3],text(day),text(money(value))))
            if index==0:parts.append('<text x="%.2f" y="233" text-anchor="middle">%s</text>'%(x,text(day[-5:])))
        parts.append('<polyline fill="none" stroke="%s" stroke-width="3" points="%s"/>'%(colors[index%3],' '.join(xy)))
    ticks=[]
    for i in range(4):
        y=210-i*55; val=ceiling*Decimal(i)/3
        ticks.append('<line x1="55" y1="%s" x2="750" y2="%s" stroke="#e2e8f0"/><text x="49" y="%s" text-anchor="end">%s</text>'%(y,y,y+4,text(format(val/1000,'.1f')+'k')))
    legend=' · '.join('<span style="color:'+colors[i%3]+'">● '+text(label)+'</span>' for i,(label,_) in enumerate(series))
    return '<div class="chart"><h3>'+text(title)+'</h3><p class="muted">'+legend+' · USD · 纵轴从零起；横向为各期间内顺序</p><svg viewBox="0 0 800 250" role="img" aria-label="'+text(title)+'">'+''.join(ticks+parts)+'</svg></div>'


def evidence_overview(evidence, period):
    selected=[];used=set()
    for ref,e in evidence.items():
        q=e.get('query',{});d=e.get('data',{})
        if e.get('source')=='Admin FC支付明细' and q.get('start') and q.get('end') and not q.get('filters') and d.get('status')=='available':
            selected.append((q.get('start'),q.get('end'),q.get('group_by',[]),ref,d))
    totals={}
    for start,end,group,ref,d in selected:
        # All dimensions share one total; keep one per exact period, never sum them.
        totals.setdefault((start,end),(ref,d))
    ordered=sorted(totals)
    rows=[];cards=[]
    for start,end in ordered:
        ref,d=totals[(start,end)];t=d['total']
        used.add(ref)
        rows.append([start+' 至 '+end,t.get('orders'),money(t.get('revenue_usd')),money(t.get('average_order_usd')),t.get('unpriced_orders'),ref])
        if start==period.get('start') and end==period.get('end'):
            for label,value in [('销售额',money(t.get('revenue_usd'))),('订单数',str(t.get('orders'))+' 单'),('单均价',money(t.get('average_order_usd')))]:
                cards.append('<div class="metric"><span>'+label+'</span><strong>'+text(value)+'</strong><small>Admin 主站 · 目标完整期间</small></div>')
    html='<div class="metrics">'+''.join(cards)+'</div>'
    if rows:html+='<section id="metrics"><h2>核心指标与趋势</h2><p class="muted">同一次调查保存的 Admin 主站支付订单证据。不同切面的总量只展示一次，不跨来源相加。</p>'+table(['期间','订单数','销售额 USD','单均价 USD','缺金额单','证据'],rows)
    day_series=[]
    for start,end,group,ref,d in sorted(selected):
        if group==['day'] and d.get('pagination',{}).get('complete'):
            used.add(ref)
            points=sorted((r['group']['day'],Decimal(r['revenue_usd'])) for r in d.get('groups',[]) if r.get('revenue_usd') is not None)
            day_series.append((start+' 至 '+end,points))
    if len(day_series)>3:day_series=day_series[-3:]
    html+=lines(day_series,'每日销售曲线 · 保留两期各自日期')
    for dimension,title in [('platform','平台量价结构'),('product','品类量价结构')]:
        groups=[]
        for start,end,group,ref,d in sorted(selected):
            if group==[dimension]:
                used.add(ref)
                complete=d.get('pagination',{}).get('complete')
                for row in d.get('groups',[]):groups.append([start+' 至 '+end,row.get('group',{}).get(dimension),row.get('orders'),money(row.get('revenue_usd')),money(row.get('average_order_usd')),'完整' if complete else '部分页',ref])
        if groups:html+='<h3>'+title+'</h3>'+table(['期间','分类','订单数','金额 USD','单均价 USD','覆盖','证据'],groups)
    return html+('</section>' if rows else ''),used


def render_report(report, evidence, period=None, provenance='Hermes 原始模型正文 · 自动排版'):
    period=period or {}; title='FC27 经营调查'
    span=period.get('start','')+' 至 '+period.get('end','')
    natural=report.get('report_format') in ('markdown','raw_json') or any(f.get('claim_type')=='report' for f in report.get('findings',[]))
    raw=report.get('raw_model_text')
    if raw is None: raw='\n\n'.join(f.get('statement','') for f in report.get('findings',[])) or report.get('summary','')
    used=set()
    for kind in ('findings','actions','reviews'):
        for row in report.get(kind,[]):used.update(row.get('evidence_ids',[]))
    used.update(c['evidence_id'] for c in report.get('number_claims',[]))
    used.update(report.get('report_evidence_ids',[]))
    if natural: used.update(re.findall(r'\bev_[a-f0-9]{24}\b',raw))
    nav='<a href="#decision">'+('完整报告' if natural else '经营结论')+'</a><a href="#metrics">指标趋势</a>'
    if not natural: nav+='<a href="#investigation">深入调查</a>'
    if report.get('actions') or not natural: nav+='<a href="#actions">行动建议</a>'
    if report.get('reviews') or not natural: nav+='<a href="#history">历史复查</a>'
    nav+='<a href="#sources">证据口径</a>'
    body='<header><span class="eyebrow">MMOEXP · FC OPERATIONS</span><h1>'+title+'</h1><p>'+text(span)+' · Asia/Shanghai</p><p class="muted">'+text(provenance)+'。经营验收待负责人审核，所有建议尚未执行。</p></header><nav>'+nav+'</nav>'
    if natural:
        content='<pre><code>'+text(raw)+'</code></pre>' if report.get('report_format')=='raw_json' else markdown(raw,evidence)
        if report.get('report_format')=='raw_json': content+=refs(sorted(used.intersection(evidence)),evidence)
        body+='<section id="decision" class="report">'+content+'</section>'
    else:
        body+='<section id="decision" class="lead"><h2>这次经营变化说明什么</h2>'+paragraphs(report['summary'])+refs(sorted({c['evidence_id'] for c in report.get('number_claims',[]) if c['report_field']=='/summary'}),evidence)+'</section>'
    overview,overview_refs=evidence_overview(evidence,period);body+=overview;used.update(overview_refs)
    if not natural:
        body+='<section id="investigation"><h2>深入调查与竞争解释</h2>'
        for i,f in enumerate(report['findings']):
            finding_title=f['statement'].replace('：',':').split(':',1)[0].strip()
            heading=finding_title if 2<=len(finding_title)<=45 and finding_title!=f['statement'].strip() else '专题 '+str(i+1)
            body+='<article class="finding"><div class="badge '+('hypothesis' if f['claim_type']=='hypothesis' else '')+'">'+('待证解释' if f['claim_type']=='hypothesis' else '证据判断')+'</div><h3>'+text(heading)+'</h3>'+paragraphs(f['statement'])
            if f['alternative']:body+='<div class="note"><b>替代解释与反证</b>'+paragraphs(f['alternative'])+'</div>'
            if f['missing']:body+='<div class="note"><b>尚未闭合的证据</b>'+paragraphs(f['missing'])+'</div>'
            body+=refs(f['evidence_ids'],evidence)+'</article>'
        body+='</section>'
    if report.get('actions') or not natural:
        body+='<section id="actions"><h2>下一步行动 · 建议未执行</h2><div class="actions">'
        for a in report['actions']:
            body+='<article class="action"><h3>'+text(a['target'])+'</h3>'+paragraphs(a['action'])+'<dl>'
            for label,key in [('触发前提','condition'),('投入与风险','cost_risk'),('复查时点','review_at'),('成功与失败标准','success_check')]:body+='<dt>'+label+'</dt><dd>'+text(a[key])+'</dd>'
            body+='</dl>'+refs(a['evidence_ids'],evidence)+'</article>'
        body+='</div></section>'
    if report.get('reviews') or not natural:
        body+='<section id="history"><h2>历史判断复查</h2>'
        for old in report['reviews']:
            body+='<article class="review"><h3>'+text(old['old_report_id'])+' · '+text({'improved':'改善','worse':'恶化','pending':'待核实','retracted':'撤回'}.get(old['status'],old['status']))+'</h3>'+paragraphs(old['reason'])+refs(old['evidence_ids'],evidence)+'</article>'
        if not report['reviews']:body+='<p>本次没有足够证据形成旧判断修正，不能声称已完成跨期复盘验收。</p>'
        body+='</section>'
    body+='<section id="sources"><h2>限制、估算与数据口径</h2><ul>'+''.join('<li>'+text(l)+'</li>' for l in report['limitations'])+'</ul><p class="muted">Admin 经营主源；Order 利润为参考口径，不等于已核实改价成本。证据编号为同次调查版本，当前状态不等于历史日终状态。下面保留原始聚合工具返回，方便复核。</p>'
    for ref in sorted(used.intersection(evidence)):
        e=evidence[ref];body+='<details id="'+text(ref)+'"><summary>'+text(ref)+' · '+text(e.get('source'))+'</summary><pre>'+text(json.dumps(e,ensure_ascii=False,indent=2))+'</pre></details>'
    body+='</section><footer>独立 HTML · 无外部字体、脚本、图片或 CDN · 可离线打开及打印。<br>'+text(report.get('run_id',''))+' · 技能 '+text(report.get('skills_version','未提供'))+'</footer>'
    css='''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f1f5f9;color:#172033;font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}main{max-width:1160px;padding:32px;margin:auto}header{padding:48px 44px;background:#102a43;color:white;border-radius:18px}h1{font-size:38px;margin:8px 0}h2{font-size:26px;letter-spacing:-.4px;margin:0 0 20px}h3{font-size:19px;margin:16px 0 10px}p{margin:12px 0}a{color:#1d4ed8;text-decoration:none;overflow-wrap:anywhere}.eyebrow{font-size:13px;letter-spacing:3px;color:#7dd3fc}.muted,small{color:#64748b;font-size:14px}header .muted{color:#cbd5e1}nav{position:sticky;top:0;z-index:1;background:#fffffff2;backdrop-filter:blur(8px);display:flex;gap:22px;padding:16px 22px;border-radius:12px;margin:20px 0;flex-wrap:wrap;box-shadow:0 3px 15px #0f172a0a}section{background:white;padding:32px 36px;border-radius:16px;margin:24px 0;border:1px solid #dfe7f0;scroll-margin-top:86px}.lead{border-top:4px solid #2563eb;font-size:18px}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:24px 0}.metric{border:1px solid #e2e8f0;background:white;border-radius:14px;padding:24px}.metric span,.metric small{display:block}.metric strong{display:block;font-size:32px;font-variant-numeric:tabular-nums;color:#0f3b72;margin:7px 0}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}th{text-align:left;background:#f1f5f9;color:#334155}td,th{padding:12px 13px;border-bottom:1px solid #e2e8f0;vertical-align:top;min-width:90px}td:last-child{font-size:11px;overflow-wrap:anywhere}tr:hover{background:#f8fafc}.chart{margin:26px 0;padding:20px;background:#f8fafc;border-radius:12px}.chart svg{display:block;width:100%;font:12px sans-serif;overflow:visible}.finding{padding:24px 0;border-bottom:1px solid #e2e8f0}.finding:last-child{border-bottom:0}.badge{display:inline-block;font-size:12px;padding:3px 10px;background:#dbeafe;color:#1e40af;border-radius:6px}.hypothesis{background:#fef3c7;color:#92400e}.note{padding:10px 18px;background:#f8fafc;border-left:3px solid #cbd5e1;margin:14px 0;font-size:15px}.note b{font-size:13px;color:#64748b}.refs{display:flex;gap:7px;flex-wrap:wrap;margin:14px 0}.refs a{font-size:12px;background:#eff6ff;padding:3px 8px;border-radius:5px}.actions{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}.action{padding:22px;border:1px solid #d7e3f0;border-top:3px solid #0d9488;border-radius:10px}dl{font-size:14px}dt{color:#64748b;margin-top:12px;font-weight:600}dd{margin:4px 0}.review{padding:16px 0;border-bottom:1px solid #e2e8f0}details{border:1px solid #e2e8f0;border-radius:8px;margin:12px 0;padding:10px 14px;scroll-margin-top:90px}summary{cursor:pointer;font-size:13px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.6 Consolas,monospace;color:#334155;background:#f8fafc;padding:16px;max-height:560px;overflow:auto}li{margin:12px 0}footer{padding:24px;text-align:center;font-size:13px;color:#64748b}@media(max-width:720px){main{padding:14px}header{padding:28px 24px}h1{font-size:30px}section{padding:24px 20px}.metrics,.actions{grid-template-columns:1fr}.metric strong{font-size:30px}nav{position:static;gap:12px;padding:12px;font-size:14px}.chart{padding:12px}h2{font-size:23px}}@media print{body{background:white}main{max-width:none;padding:0}header{background:#eef4fa;color:#172033;padding:25px}header .muted{color:#64748b}nav{position:static;display:none}section{border:0;padding:12px 0;break-inside:auto}.metric,.action{break-inside:avoid}.metrics{gap:10px}details{display:none}a{color:inherit}.chart{break-inside:avoid}footer{border-top:1px solid #ccc}}'''
    css+='''.report h1{font-size:30px;color:#0f3b72}.report h2{margin-top:30px}.report h4,.report h5,.report h6{font-size:17px;margin:18px 0 8px}.report code{font:14px/1.7 Consolas,monospace;background:#f1f5f9;padding:2px 4px;border-radius:4px}.report pre code{padding:0;background:none}.report td:last-child{font-size:14px}.report li p{margin:4px 0}.report pre{max-height:none}.report hr{border:0;border-top:1px solid #e2e8f0;margin:28px 0}'''
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+' · '+text(span)+'</title><style>'+css+'</style></head><body><main>'+body+'</main></body></html>'
