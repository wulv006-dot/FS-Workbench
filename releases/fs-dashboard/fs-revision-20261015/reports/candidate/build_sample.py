"""Build a reviewed weekly boss-report input from the frozen public evidence only."""
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime, timezone, timedelta
import json

HERE=Path(__file__).resolve().parent
E=json.loads((HERE.parent/'fixtures/evidence-public.json').read_text(encoding='utf-8'))
def money(x): return f'{D(x):,.2f}'
def num(x): return f'{int(x):,}'
def pct(a,b): return f'{(D(b)/D(a)-1)*100:+.2f}%'
def read(i): return E[i]['data']
def chart(cid,kind,title,unit,rows,ids,interpretation,note='',scope='Admin / MMOEXP主站 / 去重支付订单',as_of='2026-10-14 19:44–19:52 +08:00'):
    return dict(id=cid,kind=kind,title=title,unit=unit,rows=rows,evidence_ids=ids,interpretation=interpretation,note=note,scope=scope,as_of=as_of,period='2026-10-05—10-11 vs 09-28—10-04',labels=['前周 09-28—10-04','本周 10-05—10-11'])
old=read('ev_b8dde747e9e3145ded94b1c4')['total']; new=read('ev_fd8914720a8382f5766ebf0e')['total']
daily=sorted(read('ev_6129f30ebfe61433a3df819c')['groups'],key=lambda x:x['group']['day'])
previous=daily[:7];current=daily[7:]
trend=[dict(label=['周一','周二','周三','周四','周五','周六','周日'][i],previous_date=a['group']['day'],current_date=b['group']['day'],previous=a['revenue_usd'],current=b['revenue_usd'],previous_orders=a['orders'],current_orders=b['orders'],previous_aov=str(D(a['revenue_usd'])/a['orders']),current_aov=str(D(b['revenue_usd'])/b['orders'])) for i,(a,b) in enumerate(zip(previous,current))]
weekday_old=sum(D(x['revenue_usd']) for x in previous[:5]); weekday_new=sum(D(x['revenue_usd']) for x in current[:5])
weekend_old=sum(D(x['revenue_usd']) for x in previous[5:]); weekend_new=sum(D(x['revenue_usd']) for x in current[5:])
po={g['group']['platform']:g for g in read('ev_7c90764e9ce30474e18f6d36')['groups']};pn={g['group']['platform']:g for g in read('ev_2aaf1b192ad96386898ce623')['groups']}
platform=[]
platform_day=read('ev_c377a6c0295696a4dd3dba83')['groups']
assert E['ev_c377a6c0295696a4dd3dba83']['query']['filters']=={}, 'Use all products for platform/weekend attribution'
for name in ['PS','XBOX','PC']:
    a=po[name];b=pn[name]
    weekend_delta=sum(D(x['revenue_usd']) for x in platform_day if x['group']['platform']==name and x['group']['day'] in ['2026-10-10','2026-10-11'])-sum(D(x['revenue_usd']) for x in platform_day if x['group']['platform']==name and x['group']['day'] in ['2026-10-03','2026-10-04'])
    delta=D(b['revenue_usd'])-D(a['revenue_usd'])
    platform.append(dict(label=name,value=str(delta),previous=a['revenue_usd'],current=b['revenue_usd'],weekday=str(delta-weekend_delta),weekend=str(weekend_delta),previous_orders=a['orders'],current_orders=b['orders']))
co={g['group']['product']:g for g in read('ev_091ca3d51433f6376c8c27ab')['groups']};cn={g['group']['product']:g for g in read('ev_0756d1969293e88666a00125')['groups']}
category=[dict(label=n,previous=co[n]['revenue_usd'],current=cn[n]['revenue_usd'],previous_orders=co[n]['orders'],current_orders=cn[n]['orders']) for n in ['Coins','Items','待分类']]
queue=read('ev_6f7affd9a1e539b019e5dbf0')
age_names={'under1d':'<1天','1to3d':'1–3天','3to7d':'3–7天','7to14d':'7–14天','over14d':'>14天'}
age_map={g['group']['age_band']:g for g in queue['groups']}
age=[dict(label=age_names[k],value=age_map[k]['orders'],amount=age_map[k]['revenue_usd']) for k in age_names]
reference=read('ev_d276e25ce48dc00a63131228')['rows'];ro=reference[:7];rn=reference[7:]
refchart=[dict(label=['周一','周二','周三','周四','周五','周六','周日'][i],previous=a['profitMarginPct'],current=b['profitMarginPct'],previous_date=a['date'],current_date=b['date']) for i,(a,b) in enumerate(zip(ro,rn))]
meanold=sum(D(str(x['profitMarginPct'])) for x in ro)/7; meannew=sum(D(str(x['profitMarginPct'])) for x in rn)/7
payold=read('ev_46b27ee0e4f8e428ff979e12')['groups'];paynew=read('ev_177bf3e2732992fbbbed3eb2')['groups'];pmo={g['group']['payment']:g for g in payold};pmn={g['group']['payment']:g for g in paynew}
payment=[dict(label=k,previous=pmo[k]['revenue_usd'],current=pmn[k]['revenue_usd'],delta=str(D(pmn[k]['revenue_usd'])-D(pmo[k]['revenue_usd']))) for k in ['applepay','paypal','awgooglepay','klarna']]
charts=[
 chart('daily','line_compare','同星期对照：低谷出现在周末','USD / 日',trend,['ev_6129f30ebfe61433a3df819c'],'周一至周五销售整体高于前周，周六/周日分别下降22.71% / 27.22%。先排查周末平台订单与成交时段。','按周一—周日对齐；订单及客单价可切换。曲线只连接已取得的完整日。'),
 chart('bridge','waterfall','净降幅从哪里来','USD / 周',[dict(label='前周',value=old['revenue_usd'],role='total'),dict(label='工作日',value=str(weekday_new-weekday_old),role='delta'),dict(label='周末',value=str(weekend_new-weekend_old),role='delta'),dict(label='本周',value=new['revenue_usd'],role='total')],['ev_6129f30ebfe61433a3df819c','ev_b8dde747e9e3145ded94b1c4','ev_fd8914720a8382f5766ebf0e'],'周末减少$19,496.85，被工作日增长$6,309.39部分抵消。周末负贡献约为净降额的148%，这是差额拆解，不是原因归因。','全轴从零起；两个时间分组互斥且覆盖全周。'),
 chart('platform','diverging','PS降幅最大，PC提供增长抵消','USD / 周差额',platform,['ev_7c90764e9ce30474e18f6d36','ev_2aaf1b192ad96386898ce623'],'PS净减$16,098，XBOX净减$7,060；PC增长$9,971。PS的下滑约95%集中在周末，XBOX在工作日也走弱。','平台互斥；下表同时拆到工作日与周末。'),
 chart('category','bars_compare','金币仍是基本盘；Items值得深挖','USD / 周',category,['ev_091ca3d51433f6376c8c27ab','ev_0756d1969293e88666a00125'],'Coins占本周销售额90.53%，净减$16,706；Items仅6.96%，但净增$4,107。Items订单282→232，客单价$41.52→$68.17，需要先看高额订单结构。','待分类保留，不填入Coins或Items。单量/客单见展开表。'),
 chart('queue','bars','当前未结池：高龄队列需要推进','单 / 当前存量',age,['ev_6f7affd9a1e539b019e5dbf0','ev_0fe775ae86f1b5b5b83ff5b3'],'当前1,143单 / $49,061.62；>14天543单，其中PS365单。先核固定分层样本的阻塞节点与剩余交付量。','跨支付日存量，读取时状态；没有历史同口径快照，不能画积压增长趋势或清出率。',scope='Admin / MMOEXP主站 / 当前去重未结订单',as_of=E['ev_6f7affd9a1e539b019e5dbf0']['captured_at']),
 chart('margin','line_compare','参考利润率：周中偏低，周日回升','% / 日',refchart,['ev_d276e25ce48dc00a63131228'],f'Order日利润率简单均值{meanold:.2f}%→{meannew:.2f}%（{meannew-meanold:+.2f}个百分点）。它是全部网站估算参考，不能视作主站周毛利率。','未提供成本/毛净定义与同口径利润金额；不乘主站销售额，不据此推断成本改善。',scope='Order / 全部网站 / 原生日利润率参考',as_of='2026-10-14 19:45–19:46 +08:00')
]
content=dict(schema_version='1.0',business_model=dict(fulfillment='order_driven',holds_inventory=False,supplier_settlement='monthly'),report=dict(id='FC27-boss-weekly-20261005-11-v1',title='FC27 经营周报',subtitle='周末成交回落，是下一步最值得追的经营线索',kind='weekly',period=dict(start='2026-10-05',end='2026-10-11',comparison_start='2026-09-28',comparison_end='2026-10-04',timezone='Asia/Shanghai'),generated_at=datetime.now(timezone.utc).isoformat(),business_data_captured_at='2026-10-14 19:44–19:52 +08:00',source_data_as_of=None,snapshot_id='fc-detail-ce9093f37832f24b5bc0',source_policy='Admin主站支付明细为事实；Order全部网站仅作参考；准确支付日期与去重口径',status='本地真实数据样板 / 未集成生产',filename='FC27_老板经营周报_20261005-11.html'),
 executive=dict(headline='销售下降5.48%，排查重点在PS/XBOX周末。',summary='工作日增加$6,309，周末减少$19,497。全周单量下降12.45%，客单价上升7.95%只抵消了部分压力。排查窗口与平台已经明确，需求、供给或支付中的具体原因仍待直接证据。',confidence_fact='销售方向与时间/平台差额：已复算。',confidence_unknown='根因：未证实；利润金额、目标、新老客与FC专属流量归因未闭合。',now=[dict(title='抓住周末窗口',text='10-17/18跟PS/XBOX；平台×小时与支付尝试日志先补齐。'),dict(title='推进PS老龄队列',text='从>14天365单中分层抽≤50单，跟固定队列的推进与重开。'),dict(title='备好活动承接',text='10-17官方玩法升级前先做内容与可售检查，再看实际成交。')],decision='请决定：周五前是否给跨部门排查一个小窗口，以及10-17活动内容是否先走低成本测试。'),
 metrics=[dict(label='主站销售额',value='$'+money(new['revenue_usd']),previous='$'+money(old['revenue_usd']),delta=pct(old['revenue_usd'],new['revenue_usd']),status='fact',evidence_ids=['ev_b8dde747e9e3145ded94b1c4','ev_fd8914720a8382f5766ebf0e']),dict(label='支付订单',value=num(new['orders'])+' 单',previous=num(old['orders'])+' 单',delta=pct(old['orders'],new['orders']),status='fact',evidence_ids=['ev_b8dde747e9e3145ded94b1c4','ev_fd8914720a8382f5766ebf0e']),dict(label='客单价',value='$'+money(D(new['revenue_usd'])/new['orders']),previous='$'+money(D(old['revenue_usd'])/old['orders']),delta=pct(D(old['revenue_usd'])/old['orders'],D(new['revenue_usd'])/new['orders']),status='derived',evidence_ids=['ev_b8dde747e9e3145ded94b1c4','ev_fd8914720a8382f5766ebf0e']),dict(label='利润金额 / 目标',value='未提供',previous='同口径成本与目标版本缺失',delta='不计算达成率',status='missing',evidence_ids=[])],
 charts=charts,payment=payment,
 hypotheses=[dict(title='客单价上涨 ≠ 已证明提价',text='Items的平台结构反事实客单价约$40.52，无法解释实际$68.17；PS Items贡献约70.18%的Items金额增量。优先核PS高额订单、同商品ID数量与优惠。该描述性拆解由独立QA补充，不是价格因果。',evidence_ids=['ev_0756d1969293e88666a00125','ev_091ca3d51433f6376c8c27ab','ev_095457a296bc32beef07a7fe','ev_9ec892fa922b7af5be0af224']),dict(title='支付金额下降 ≠ 已证明通道故障',text='Apple Pay / PayPal是成功成交的边际分布；英国和美国也是同批订单的另一种切法，不能把各维度缺口相加。没有支付尝试与失败分母，先核平台×日期×支付，再查错误记录。',evidence_ids=['ev_46b27ee0e4f8e428ff979e12','ev_177bf3e2732992fbbbed3eb2'])],
 context=[dict(label='地域线索',text='GB净减$4,662.69，US净减$8,408.72；两国合计$13,071.41。国家仅取得前50行，两行本身可比；其余净额可由总量求残差，不能声称各国明细完整。',evidence_ids=['ev_b50b8ffb2f4eb613d3064f81','ev_2108fe962993972c6d585112']),dict(label='设备线索',text='移动端销售$181,558.60→$167,804.11（-7.58%），桌面端$58,888.63→$59,455.66（+0.96%）。这是成交结构，无会话/曝光分母，不能据此判断移动转化率变差。',evidence_ids=['ev_d22e87b058ef0d034de2d0d4','ev_8d7bf8aa975078ada62717f4']),dict(label='原生消损线索',text='Admin原生分类合计$8,564.87→$12,602.79（+47.15%）。分类定义、重叠及归属支付日待核；dc/tkwtg可先人工核案例，不把该额计为退款、净损失或财务利润。',evidence_ids=['ev_73634d3508b40746fccfe9f2','ev_f5b4ad9267ce9c116aa39e16'])],
 intel=[
 dict(id='web-ea-future-stars',window='分析周内',published_at='2026-10-09',event_at='2026-10-09起',applies='2026-10-09—10-11历史分析',title='Future Stars启动，新增SBC与Academy进化',fact='EA确认10-09启动追踪，活动包含球员SBC、Puzzle SBC与Academy进化。',hypothesis='新内容可能改变阵容、金币与球员需求结构；它与周末下滑重叠，但尚未证明刺激或抑制我方销售。',action='按现有商品ID与平台检查活动相关成交、咨询及可售日志；将活动标记放入周末对照，保留PC参照。',url='https://www.ea.com/games/ea-sports-fc/fc-27/news/fc-27-future-stars',source='EA官方',retrieved_at='2026-10-14',verified=True),
 dict(id='web-ea-patch',window='分析周内',published_at='2026-10-07',event_at='2026-10-07已上线',applies='2026-10-07—10-11历史分析',title='v1.0.4修复FUT赛后Service Unavailable',fact='EA补丁说明列出特定情境的赛后Service Unavailable修复，并注明没有玩法平衡调整。',hypothesis='游戏端可用性是需求体验线索；这不是商城支付错误，更不能据此确认我方履约根因。',action='若客户记录确有同类游戏错误，按平台/发生时间比对已有案例，不用新闻代替订单日志。',url='https://www.ea.com/games/ea-sports-fc/fc-27/news/fc27-title-update-v1-0-4',source='EA官方',retrieved_at='2026-10-14',verified=True),
 dict(id='web-ea-feedback',window='期后披露 / 回溯线索',published_at='2026-10-13',event_at='2026-10-09修复',applies='回溯10-09，不能作为当时已知信息',title='EA期后披露Champions匹配于10-09修复',fact='10-13反馈更新回溯称，Champions匹配范围异常已在10-09部署修复。',hypothesis='周末玩法体验可能改变，但与我方周末订单下降仍无因果连接。',action='将发布时间和事件日期分开标记；复核客户反馈是否涉及该玩法，不能把10-13公告写成分析周内发布。',url='https://www.ea.com/games/ea-sports-fc/fc-27/news/fc-27-launch-feedback-update',source='EA官方',retrieved_at='2026-10-14',verified=True),
 dict(id='web-ea-next-window',window='截至10-14的新机会',published_at='2026-10-09',event_at='2026-10-17起',applies='2026-10-17—10-18下个周末',title='10-17起PlayStyle+ Lab与UEFA Star Performers',fact='EA计划Future Stars第二周引入PlayStyle+ Lab，首批UEFA Star Performers从10-17起具备PlayStyle+升级资格。',hypothesis='内容可能带来相关阵容需求；与PS Items高额结构线索结合，值得低成本验证，而非直接扩大供应商承接规模。',action='先准备一页活动解读与相关在售品内容；统计活动窗口咨询/点击/成交，只有可售与履约能力确认才提交投放方案。',url='https://www.ea.com/games/ea-sports-fc/fc-27/news/fc-27-future-stars',source='EA官方',retrieved_at='2026-10-14',verified=True),
 dict(id='web-futbin',window='截至10-14的市场观察',published_at=None,event_at='抓取时当前列表',applies='当前观察；不可回填为10-05—11价格',title='Future Stars已进入市场列表，平台价格应分开观察',fact='FUTBIN的FC27 Future Stars列表提供Console / PC分列市场报价。当前读取未闭合10-05—11历史序列，也没有我方同规格竞品成交价。',hypothesis='平台差异提示活动承接需要分别看PC与主机，不能据单点报价推断涨跌或利润空间。',action='先用官方名单筛选活动主题；价格方向与竞品差价保持待核，后续由既有市场监测负责人提供同时间/数量/赠送口径数据。',url='https://www.futbin.com/27/totw/FutureStars',source='FUTBIN市场列表 / 非官方统计',retrieved_at='2026-10-14',verified=True)
 ],
 actions=[
 dict(id='A1',priority='P1',title='周末平台排查：把PS/XBOX的少单落到具体时段',role='FC运营负责人 + 数据/支付负责人',when='10-15—16取证；10-17/18观察；10-19复盘',trigger='本期周末销售-24.88%，PS/XBOX贡献主要负差额。现在就准备双基线。',steps='先补平台×日期×小时、支付×日期/平台及已有供应商供给/可售能力/投放日志；10-17/18同时对照10-10/11与10-03/04，PC作参照。',metric='产出平台/时段缺口与直接日志对应表；跟收入、订单和支付失败率（有分母才算）。恢复百分比只决定排查优先级。',cost='拟议小窗口：运营4小时+数据/支付2小时，属排查工时估计，不是预算承诺。',risk='活动与基数不同；别把平台/国家/支付三个维度的缺口相加。',stop='若来源/日期/交叉字段不一致，停止因果归因并保留缺项；连续两个可比窗口恢复后可降级监控。',evidence_ids=['ev_6129f30ebfe61433a3df819c','ev_7c90764e9ce30474e18f6d36','ev_2aaf1b192ad96386898ce623']),
 dict(id='A2',priority='P1',title='PS高龄队列：先闭环≤50单固定分层样本',role='客服/履约负责人',when='10-15建样本；10-22与10-29复查',trigger='当前PS>14天365单，7–14天173单，老龄样本有明确对象。',steps='按商品/金额/最新事件分层，核剩余交付量与阻塞节点；记录同一批订单推进、结案和重开，同时记录新增跨龄进入。',metric='固定样本已确认阻塞节点率、推进/结案/重开数；处理工时/单。先建基线，不虚设改善目标。',cost='最多50单人工核查；低金额订单控制处理工时，实际耗时待记录。',risk='当前池不是本周新增；事件样本不等于完整支付历史，不能统一称零进度。',stop='发现身份、订单状态或证据冲突就停止该个案；退款/关单/派单按原权限另审。总池不降不能单独判无效。',evidence_ids=['ev_6f7affd9a1e539b019e5dbf0','ev_0fe775ae86f1b5b5b83ff5b3']),
 dict(id='A3',priority='P2',title='PS Items高额结构：把增长机会先验成可复用组合',role='商品运营 + 数据负责人',when='10-16完成首轮；10-19复盘',trigger='Items金额+35.08%、订单-17.73%；PS贡献约70.18%的金额增量。',steps='核PS Items高额订单与同商品ID的购买数量、成交额、优惠/赠送，区分大单、数量组合和价格因素；在售承接页面仅出内容草案。',metric='按金额档/商品ID定位增量集中度；记录相关咨询与成交，核实可售和履约能力后再评估扩量。',cost='拟议10–20个高额样本，属取证范围；不预付采购，不承诺新增供应商额度或投放金额。',risk='标题变化不能推断换SKU；全周商品1922单不能证明周末供给正常。',stop='同SKU数量/优惠证据缺失时不作定价归因；毛利与供给未核实前停止扩量提案。',evidence_ids=['ev_095457a296bc32beef07a7fe','ev_9ec892fa922b7af5be0af224']),
 dict(id='A4',priority='P2',title='Apple Pay / PayPal：查尝试与失败，别只看成功金额',role='支付负责人',when='10-15—16首轮，只读核查',trigger='两通道全周成功金额合计净减$17,072.78，值得核查，但还不是故障。',steps='读已有支付尝试/错误/拒绝与风控变更记录，按平台、日期、金额档核分母；若没有失败异常，再比对流量与订单组合。',metric='有可信分母后计算失败率及错误集中时段；缺分母直接标未验证。',cost='现有日志排查；新增采集接口或权限由主任务另核。',risk='恢复、统计异常或国家/支付的边际相似不能单独证明原因。',stop='无直接异常则停止故障定性；不按成功金额下降直接切支付通道。',evidence_ids=['ev_46b27ee0e4f8e428ff979e12','ev_177bf3e2732992fbbbed3eb2']),
 dict(id='A5',priority='P2',title='10-17活动承接：先做内容验证，再谈投放与供应商承接扩量',role='FC内容/商品运营',when='10-16草案；10-17/18观察；10-19决定下一轮',trigger='EA已公布10-17起的PlayStyle+升级窗口，和下个周末重叠。',steps='按官方资格写一页内容与常见问答，核现有可售品/供给/履约；标记活动咨询与点击，比较PC与主机。实际发布/投放由原owner审批。',metric='活动相关有效咨询、内容点击及同窗口成交；利润数据补齐后才评估投入产出。',cost='建议先用现有内容与商品资源，投放预算未申请；不承诺收入增量。',risk='活动资格/日期会更新；无营销归因时只能描述同步变化。',stop='官方窗口变更或可售/履约不确定就暂停承接；无直接需求信号不扩大供应商承接规模、不加预算。',evidence_ids=[])
 ],
 decisions=[dict(topic='跨部门排查资源',recommended='A｜周五前给运营4h + 数据/支付2h的拟议取证窗口',alternative='B｜等待下个完整周末再分配资源',tradeoff='A更早定位时段与阻塞点，需借调工时；B短期投入少，但周末可能重复低谷。无现成金额预算。',status='待老板选择 / 工时建议未执行'),dict(topic='10-17活动承接方式',recommended='A｜先审核内容草案与现有可售能力，做低成本验证',alternative='B｜暂缓承接；先把PS履约队列推进',tradeoff='A可捕捉咨询和结构信号；B降低履约压力。付费投放/供应商承接扩量缺利润与需求依据，本轮不提交金额。',status='待老板选择 / 非上线或业务写入授权')],
 timeline=[dict(date='10-15—16',text='补交叉数据 / PS固定样本 / 活动草案'),dict(date='10-17—18',text='双基线观察周末 / 记录活动需求'),dict(date='10-19',text='复盘差额 / 用日志区分机制'),dict(date='10-22 / 29',text='固定队列推进、结案、重开复查')],
 gaps=['目标版本与同口径实际利润金额未提供；无达成率。','源业务水位UNKNOWN；捕获时间不是上游最新订单水位。','无FC专属会话/广告归因、新老客口径；不搬用全站GA4指标。','国家前50行、商品Top10截断；不可冒充全量。','支付×日期、平台×小时及尝试/失败分母尚缺。','未结池无同口径历史快照；不能比较积压增长或清出率。','Admin消损定义/重叠/归属日期待核；不能当净损失。','市场历史价格与同规格竞品价格缺失；不制造价格趋势。'],
 corrections=['客单价用原销售额÷订单重算，环比+7.95%；原稿用两位展示均价计算为+7.94%，是四舍五入差异。','2026-10-14读取：10-11为T+3、10-04为T+10、09-28为T+16；不沿用原稿日龄笔误。','PS头部商品1922单为整周TopN线索，不是周末供给反证。','恢复到85%只能是建议管理阈值，不能确认基数正常化。','周末聚合客单价涨幅小不足以排除提价，需同SKU数量/优惠可比。','队列复查跟固定cohort与流入/流出，避免自然跨龄误判。'],
    finance=dict(title='目前无法给出主站实际利润与达标判断',basis='Order全部网站利润率和Admin主站销售范围不同；这份报告保留日度估算参考，不计算主站周利润金额。旧参考案例的25%目标没有当前周目标版本，不能移植。',next='下一步先确认消损分类与案例，补同口径成本、优惠及费用定义，再评估动作收益。没有这些输入，就没有可信的扩量回报预测。'),
    research_url='https://chatgpt.com/space/page_d5724fd6d3708191aa107b50c5051874',
 provenance=dict(package_sha256='5790ba9e85f874ed3f9b96973c8ec3af79f2833f528c0f66958d3ab123188e95',research_html_sha256='bcf98fbdedd9646354501541942dc47d57f902df5a678e90c9bea6464f2bb1df',evidence_file='evidence-public.json',evidence_count=154,scope='冻结公开证据；新增网页情报独立编号，不改原154；没有重新采集或模型调用'))
content['payment_evidence_ids']=['ev_46b27ee0e4f8e428ff979e12','ev_177bf3e2732992fbbbed3eb2']
queue_chart=next(x for x in content['charts'] if x['id']=='queue')
queue_chart['period_basis']='current_snapshot'
queue_chart['snapshot_at']=datetime.fromisoformat(E['ev_6f7affd9a1e539b019e5dbf0']['captured_at']).astimezone(timezone(timedelta(hours=8))).isoformat()
queue_chart['period']='当前存量快照 · 2026-10-14 19:44:41 +08:00'
queue_chart['labels']=[]
(HERE.parent/'fixtures/rebuilt.sample.content.json').write_text(json.dumps(content,ensure_ascii=False,indent=2),encoding='utf-8')
print('Built',len(charts),'charts and',len(content['actions']),'actions')
