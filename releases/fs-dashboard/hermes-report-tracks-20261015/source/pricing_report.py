"""Independent frozen-evidence pricing research. No collection, model or writes.

Deploy beside the existing boss_renderer module; its escaping/link primitives
are shared, while its operating-report projection and six-chart layout are not.
"""
from decimal import Decimal, InvalidOperation
import json
import re
from urllib.parse import urlsplit

from boss_renderer import esc, safe_url, number, table

VERSION='pricing-v1'
SOURCES=('Lootbar','IGGM','U4GM','U7Buy')
PLATFORMS=('PS','XBOX','PC')
PRICE_TERMS=re.compile(r'竞品|定价|报价|跟价|价格|成本护栏|币价|物品行情|市场调研|采价|含赠',re.I)


def _dedicated(result,context):
    return context.get('template_preview') is not True and any(
        obj.get(key)=='pricing' for obj in (result,context) for key in ('report_track','mode','report_kind'))


def _number(value,zero=False):
    if value is None or isinstance(value,bool):raise ValueError('missing_number')
    try:out=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError):raise ValueError('invalid_number') from None
    if not out.is_finite() or out<0 or not zero and out==0:raise ValueError('invalid_number')
    return out


def _offer(row):
    out=dict(row)
    try:
        base=_number(row.get('base_k'));bonus=_number(row.get('bonus_k'),True)
        price=_number(row.get('gross_usd'))
        if base!=100 or row.get('currency')!='USD':raise ValueError('offer_unit')
        out.update(base_k=str(base),bonus_k=str(bonus),gross_usd=str(price),
                   effective_usd_per_k=str(price/(base+bonus)),numeric_available=True)
    except ValueError:out.update(numeric_available=False,reason='缺有效USD金额或100K档位/赠送数量，未参与位置比较')
    return out


def _state(row):
    if row.get('status')=='available' and row.get('freshness')=='fresh':return '采集时可用'
    return '已过观察时效' if row.get('freshness')=='stale' else '资料待核'


def _pricing_text(result,context):
    explicit=result.get('pricing_strategy')
    if isinstance(explicit,str) and explicit.strip():return explicit.strip()
    text=result.get('research_text') or result.get('raw_model_text') or ''
    if not isinstance(text,str):return ''
    if _dedicated(result,context):return text
    # An old mixed investigation contributes only its explicitly priced section.
    headings=list(re.finditer(r'(?m)^\s*(#{1,6})\s+([^\n]+)',text));parts=[]
    for i,heading in enumerate(headings):
        if not PRICE_TERMS.search(heading[2]) and not re.search(r'行情|专题\s*五',heading[2]):continue
        end=next((h.start() for h in headings[i+1:] if len(h[1])<=len(heading[1])),len(text))
        if not any(a<=heading.start()<b for a,b in parts):parts.append((heading.start(),end))
    return '\n\n'.join(text[a:b].strip() for a,b in parts)


def _background(result,evidence,context):
    period=result.get('period',{});totals={}
    for key,row in sorted(evidence.items()):
        data=row.get('data',{});query=row.get('query',{})
        if (row.get('source')!='Admin FC支付明细' or row.get('scope')!='main' or data.get('status')!='available'
                or query.get('group_by')!=[] or query.get('filters')!={} or data.get('filters_applied')!={}
                or query.get('start')!=period.get('start') or query.get('end')!=period.get('end')
                or data.get('coverage',{}).get('paid_complete') is not True
                or data.get('coverage',{}).get('missing_days') or data.get('pagination',{}).get('complete') is not True):continue
        try:
            total=data['total'];amount=_number(total['revenue_usd'],True);orders=_number(total['orders'],True)
            if orders!=orders.to_integral_value() or _number(total['unpriced_orders'],True)!=0:continue
            totals.setdefault((amount,orders),[]).append(key)
        except (KeyError,ValueError):continue
    if len(totals)==1:
        (amount,orders),ids=next(iter(totals.items()))
        return ('经营背景：'+period['start']+' 至 '+period['end']+'主站销售 $'+number(amount)+'、'+number(orders,0)+' 单，仅辅助市场判断。',ids)
    if isinstance(context.get('business_background'),str) and context['business_background'].strip():
        return ('经营补充：'+re.split(r'(?<=[。！？])',context['business_background'].strip())[0],[])
    return ('经营背景：本次未取得唯一可用的同期总量，本报告仍以市场与竞品研究为主。',[])


def project(result,evidence,context=None):
    context=context or {};gaps=[];snapshots={};anchor=result.get('snapshot_id')
    for key,row in sorted(evidence.items()):
        data=row.get('data',{})
        if data.get('contract')!='fc27-existing-market-readonly-v1' or data.get('profile')!='FC27':continue
        if anchor and row.get('analysis_anchor_id') and row['analysis_anchor_id']!=anchor:
            gaps.append('一份市场证据属于其他研究任务，未混入比较。');continue
        comparable=dict(data);comparable.pop('captured_at',None)
        signature=json.dumps(comparable,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        if signature in snapshots:snapshots[signature]['evidence_ids'].append(key)
        else:snapshots[signature]={'data':data,'evidence_ids':[key]}
    markets=[]
    if len(snapshots)>1:gaps.append('存在不同市场快照，已分别展示；没有自动选为最新，也不跨快照拼接成本与报价。')
    for snapshot in snapshots.values():
        data=snapshot['data'];competitors=data.get('competitors') or [];own=(data.get('storefront') or {}).get('rows') or []
        market={'evidence_ids':snapshot['evidence_ids'],'observed_at':data.get('captured_at'),'run_id':data.get('collection_run_id'),
                'quotes':[],'own':[],'positions':[],'costs':[],'fx':data.get('fx',{}),'fee_scenario':data.get('fee_scenario',{}),
                'limitations':data.get('limitations',[])}
        for platform in PLATFORMS:
            rows=[r for r in own if isinstance(r,dict) and r.get('platform')==platform]
            current=_offer(rows[0]) if len(rows)==1 else {'platform':platform,'numeric_available':False}
            market['own'].append(current);less=more=equal=0;compared=0
            for source in SOURCES:
                rows=[r for r in competitors if isinstance(r,dict) and r.get('source')==source and r.get('platform')==platform]
                offer=_offer(rows[0]) if len(rows)==1 else {'source':source,'platform':platform,'numeric_available':False,'reason':'缺报价或同平台重复报价'}
                offer['relative']=None
                if (current['numeric_available'] and offer['numeric_available']
                        and _state(current)=='采集时可用' and _state(offer)=='采集时可用'):
                    difference=Decimal(current['effective_usd_per_k'])/Decimal(offer['effective_usd_per_k'])-1
                    offer['relative']=str(difference*100);compared+=1
                    less+=difference<0;more+=difference>0;equal+=difference==0
                market['quotes'].append(offer)
            market['positions'].append({'platform':platform,'lower_than':less,'higher_than':more,'equal_to':equal,'compared':compared})
            rows=[r for r in (data.get('costs') or []) if isinstance(r,dict) and r.get('platform')==platform]
            cost=dict(rows[0]) if len(rows)==1 else {'platform':platform,'status':'missing'}
            cost['usd_per_k']=None;cost['spread_usd_per_k']=None;cost['cny_display']=None
            try:
                if cost.get('unit')=='CNY/K':cost['cny_display']=str(_number(cost.get('cny_per_1k')))
            except ValueError:pass
            try:
                fx=data.get('fx') or {}
                if (cost.get('status')!='available' or cost.get('freshness')!='fresh' or cost.get('unit')!='CNY/K'
                        or fx.get('status')!='available' or fx.get('freshness')!='fresh' or fx.get('direction')!='CNY per USD'):raise ValueError('cost_or_fx_unavailable')
                converted=_number(cost['cny_per_1k'])/_number(fx['cny_per_usd']);cost['usd_per_k']=str(converted)
                if current['numeric_available'] and _state(current)=='采集时可用':cost['spread_usd_per_k']=str(Decimal(current['effective_usd_per_k'])-converted)
            except (KeyError,ValueError):pass
            market['costs'].append(cost)
        markets.append(market)
    if not markets:gaps.append('本次没有可用市场快照；这不等于服务器没有金币行情。')
    gaps+=['现有金币观察覆盖四家网站、PS/XBOX/PC、100K档；不是全市场或历史趋势。',
           '物品竞品价格与可比SKU/规格数据尚未接入；不能用金币行情代替物品结论。',
           '配送、优惠券资格、必付费用和有效期尚未全部核齐；采集时可用不等于现在仍新鲜。',
           '成本差额未扣费用，非实际利润；新售价仍需当前有效成本、可比报价及原业务护栏。']
    text=_pricing_text(result,context);dedicated=_dedicated(result,context)
    summary=result.get('pricing_summary') or (result.get('summary') if dedicated else None)
    if not isinstance(summary,str) or not summary.strip():
        summary=next((p.strip() for p in re.split(r'\n\s*\n',text) if p.strip() and not p.lstrip().startswith('#')),'未识别独立定价判断；先看市场观察与缺口，不以经营动作补位。')
    actions=[]
    for row in result.get('actions',[]):
        if not isinstance(row,dict):continue
        fields=' '.join(str(row.get(k,'')) for k in ('target','action','condition','steps','title'))
        if not PRICE_TERMS.search(fields):continue
        actions.append({'target':row.get('target') or row.get('title') or '原研究未明确对象',
                        'action':row.get('action') or row.get('steps') or '原研究未给出动作',
                        'condition':row.get('condition') or row.get('trigger') or '原研究未给出条件',
                        'reversal':row.get('stop_condition') or row.get('stop') or '原研究未给出反转/停止条件',
                        'evidence_ids':[x for x in row.get('evidence_ids',[]) if x in evidence]})
    events=[];official_ids=[]
    for key,row in sorted(evidence.items()):
        data=row.get('data',{})
        if not row.get('source','').startswith('EA官网FC27官方情报') or not isinstance(data.get('documents'),list):continue
        for item in data['documents']:
            if not isinstance(item,dict):continue
            events.append({k:item.get(k) for k in ('title','source_url','published_at','event_date','publication_in_window','text')})
        official_ids.append(key)
    background,background_ids=_background(result,evidence,context)
    used=set(background_ids+official_ids+[key for m in markets for key in m['evidence_ids']]+[key for a in actions for key in a['evidence_ids']])
    preview=context.get('template_preview') is True
    return {'report':{'kind':'pricing','version':VERSION,'template_preview':preview,
                      'title':'FC27 定价报告 · 模板接线预览' if preview else 'FC27 市场与定价研究'},'summary':summary,'business_background':background,
            'markets':markets,'events':events,'strategy_text':text,'actions':actions,'gaps':list(dict.fromkeys(gaps)),
            'evidence':{k:evidence[k] for k in sorted(used)},'actions_executed':False,'new_price_recommended':False}


def _link(label,url):
    try:target=safe_url(url)
    except (ValueError,TypeError,AttributeError):return esc(label)+'（无有效HTTPS链接）'
    return '<a href="'+target+'" target="_blank" rel="noopener noreferrer">'+esc(label)+'</a>'


def render(result,evidence,context=None):
    c=project(result,evidence,context);body='<header><p class="eyebrow">MARKET RESEARCH / '+VERSION+'</p><h1>'+esc(c['report']['title'])+'</h1><p>金币与物品市场 · 竞品比较 · 策略取舍</p><h2>'+esc(c['summary'])+'</h2><p class="background">'+esc(c['business_background'])+'</p><p class="notice">研究建议尚未执行；不自动生成新售价。下列报价是冻结观察，采用前须复核时效与可比条件。</p></header>'
    body+='<section><h2>01 金币市场位置</h2><p>四家网站、三平台的100K档观察；含赠单价统一为 USD/K。</p>'
    for i,market in enumerate(c['markets'],1):
        body+='<article><h3>市场观察 '+str(i)+' · '+esc(market['observed_at'] or '时间未提供')+'</h3>'
        body+=table(['平台','本店基础K','赠送K','本店金额 USD','本店含赠 USD/K','观察状态'],[[r['platform'],r.get('base_k','缺失'),r.get('bonus_k','缺失'),number(r.get('gross_usd')) if r['numeric_available'] else '缺失',number(r.get('effective_usd_per_k'),4) if r['numeric_available'] else '缺失',_state(r)] for r in market['own']])
        quote_rows=[]
        for row in market['quotes']:
            relative=row['relative'];position='不可比' if relative is None else '持平' if Decimal(relative)==0 else ('本店高 ' if Decimal(relative)>0 else '本店低 ')+number(abs(Decimal(relative)))+'%'
            quote_rows.append([row['platform'],row['source'],row.get('base_k','缺失'),row.get('bonus_k','缺失'),number(row.get('gross_usd')) if row['numeric_available'] else '缺失',number(row.get('effective_usd_per_k'),4) if row['numeric_available'] else '缺失',position,_state(row)])
        body+=table(['平台','竞品','购买K','赠送K','金额 USD','含赠 USD/K','表内相对位置','观察状态'],quote_rows)
        body+='<p>表内单价只比较所列金额与数量；配送、优惠和费用条件仍待核，不据此证明价格导致失单。</p><details><summary>报价来源与完整条件</summary>'
        for row in market['quotes']+market['own']:
            body+='<p>'+_link(str(row.get('source','MMOEXP'))+' / '+str(row.get('platform','')),row.get('url'))+' · '+esc(row.get('captured_at','时间缺失'))+' · '+esc(row.get('auth_state','登录状态未知'))+'</p>'
        body+='<pre>'+esc(json.dumps(market['limitations'],ensure_ascii=False,indent=2))+'</pre></details></article>'
    if not c['markets']:body+='<p class="missing">暂无本任务的金币市场观察。</p>'
    body+='</section><section><h2>02 成本空间</h2><p>只计算本店观察单价与可用采购成本的差额，未扣费用，非实际利润和新售价。</p>'
    for market in c['markets']:
        body+=table(['平台','采购成本 ¥/K','折合成本 USD/K','本店含赠单价减成本 USD/K'],[[r['platform'],number(r['cny_display'],4),number(r['usd_per_k'],4),number(r['spread_usd_per_k'],4)] for r in market['costs']])
        body+='<details><summary>汇率、成本时间与费用情景</summary><pre>'+esc(json.dumps({'fx':market['fx'],'costs':market['costs'],'fee_scenario':market['fee_scenario']},ensure_ascii=False,indent=2))+'</pre></details>'
    body+='</section><section><h2>03 物品市场</h2><p class="missing">物品竞品数据尚未接入。需要同SKU、规格、数量、优惠与履约条件的报价，不能从金币市场推断。</p></section>'
    body+='<section><h2>04 官方事件与需求线索</h2><p>发文日期与事件日期分开；官方信息本身不证明本站销量或价格变化原因。</p>'
    for event in c['events']:
        url=event['source_url']
        try:official=isinstance(url,str) and urlsplit(url).hostname=='www.ea.com'
        except ValueError:official=False
        body+='<article><h3>'+(_link(event['title'] or '官方文章',url) if official else esc(event['title'] or '待核文章'))+'</h3><p>发文：'+esc(event['published_at'] or '未提供')+' · 事件日期：'+esc(event['event_date'] or '未独立核实')+'</p><details><summary>查看原文片段</summary><pre>'+esc(event['text'] or '')+'</pre></details></article>'
    if not c['events']:body+='<p>本任务没有可展示的官方事件证据；不等于市场没有活动。</p>'
    body+='</section><section><h2>05 策略情景与反转条件</h2>'
    if c['strategy_text']:body+='<div class="research">'+esc(c['strategy_text'])+'</div>'
    else:body+='<p>尚未识别定价专属研究段落，不用经营报告动作填充。</p>'
    if c['actions']:body+=table(['对象','原研究建议','成立条件','反转/停止条件'],[[a['target'],a['action'],a['condition'],a['reversal']] for a in c['actions']])
    else:body+='<p>原研究没有单独列出可提取的定价动作；不补造调价建议。</p>'
    body+='</section><section><h2>06 缺口与下一步研究</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in c['gaps'])+'</ul></section>'
    body+='<details class="appendix"><summary>冻结证据与核算依据</summary><p>仅使用传入的本任务冻结资料；未重新采集、调用模型或执行业务操作。</p><pre>'+esc(json.dumps(c['evidence'],ensure_ascii=False,indent=2))+'</pre></details>'
    style='body{margin:0;background:#f4f6fb;color:#182641;font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1100px;margin:24px auto;padding:36px;background:white}header{border-top:5px solid #235fe7;padding-top:20px}h1{font-size:32px}h2{font-size:22px;line-height:1.5}section{padding:24px 0;border-top:1px solid #dfe5ef}article{margin:20px 0}.eyebrow{color:#235fe7;font-size:12px}.background,details{color:#64748b;font-size:13px}.notice,.missing{background:#fff5df;padding:12px}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:9px;border-bottom:1px solid #dfe5ef;vertical-align:top}th{background:#f4f6fb}pre,.research{white-space:pre-wrap;overflow-wrap:anywhere}details{margin:15px 0}a{color:#235fe7}summary{cursor:pointer}a:focus-visible,summary:focus-visible{outline:3px solid #95671f;outline-offset:3px}@media(max-width:600px){main{margin:0;padding:20px}h1{font-size:26px}}'
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="report-kind" content="pricing"><meta name="report-version" content="'+VERSION+'"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>'+esc(c['report']['title'])+'</title><style>'+style+'</style></head><body><main>'+body+'</main></body></html>'
