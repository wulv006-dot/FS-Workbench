"""Typed, game-scoped operational settings. No file IO or pricing side effects."""
import copy
import math

GAMES = [
    {'id': 'aion2', 'name': 'AION2', 'file': 'config.json'},
    {'id': 'wow', 'name': 'WoW Forever', 'file': 'wow_gold_config.json'},
    {'id': 'd4', 'name': '暗黑破坏神4', 'file': 'config.json'},
    {'id': 'poe2', 'name': '流放之路2', 'file': 'config.json'},
    {'id': 'poe1', 'name': '流放之路1', 'file': 'config.json'},
    {'id': 'arc', 'name': 'ARC Raiders', 'file': 'config.json'},
    {'id': 'msc', 'name': 'MapleStory Classic World', 'file': 'config.json'},
    {'id': 'aa', 'name': '上古世纪编年史', 'file': 'aa_gold_config.json'},
    {'id': 'dad', 'name': 'Dark and Darker', 'file': 'config.json'},
    {'id': 'wardogs', 'name': 'WarDogs', 'file': 'config.json'},
]
SCHEDULE_CHOICES = [.25, .5, 1, 2.5, 3, 6, 12, 24]


def get_path(doc, path, default=None):
    cur = doc
    for part in path:
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_path(doc, path, value):
    cur = doc
    for part in path[:-1]:
        if part not in cur:
            cur[part] = {}
        if not isinstance(cur[part], dict):
            raise ValueError('原配置结构不正确，请先检查：' + '.'.join(path))
        cur = cur[part]
    cur[path[-1]] = value


def game_info(game_id):
    for game in GAMES:
        if game['id'] == game_id:
            return dict(game)
    raise ValueError('未知游戏')


def _field(doc, key, label, path, default, lo, hi, unit='', group='定价',
           help='', kind='number', step=.01, scale=1, options=None):
    result = dict(key=key, label=label, path=path, type=kind, min=lo, max=hi,
                  step=step, unit=unit, group=group, help=help, scale=scale,
                  value=copy.deepcopy(get_path(doc, path, default)))
    if options is not None:
        result['options'] = list(options)
    return result


def _num(doc, key, label, path, default, lo, hi, **kw):
    return _field(doc, key, label, path, default, lo, hi, **kw)


def get_game_schema(game_id, doc, common_cfg=None):
    """Return only explicitly supported fields; never serialize credentials/maps."""
    game = game_info(game_id)
    name = game['name']
    cfg = doc if game['file'] == 'config.json' else (common_cfg or {})
    fields, readonly = [], []
    readonly.append({'label': '共享汇率 CNY/USD',
                     'value': get_path(cfg, ['汇率', 'USDCNY'], 6.65)})
    if game_id in ('wow', 'aa'):
        fields.append(_field(doc, 'enabled', '启用此游戏自动改价', ['启用'], True,
                             None, None, kind='boolean', group='运行',
                             help='下一轮读取。在途工单仍按已生成内容执行。'))
        p = ['参数']
        if game_id == 'wow':
            fields.extend([
                _num(doc, 'sample_gold', '成本采样金币量', p+['成本采样金'],150,1,1000000,
                     unit='G', group='采集', step=1,
                     help='库存足量时从低价开始采样；整件起购可略超。不等于接口挂单条数。'),
                _num(doc, 'scarce_boundary', '稀缺库存分界', p+['薄区阈值金'],50,1,1000000,
                     unit='G', group='采集', step=1,
                     help='低于此量采用稀缺利润率；此量至采样量之间采用薄区利润率。'),
                _num(doc, 'margin_full', '常规利润率', p+['常规利润率'],.25,0,.95,
                     unit='%',scale=100,step=.1,help='库存达到成本采样量时使用。'),
                _num(doc, 'margin_thin', '薄区利润率', p+['薄区利润率'],.30,0,.95,
                     unit='%',scale=100,step=.1),
                _num(doc, 'margin_scarce', '稀缺利润率', p+['稀缺利润率'],.35,0,.95,
                     unit='%',scale=100,step=.1),
                _num(doc, 'price_cap', '有货售价上限', p+['最高售价USD每G'],1.6,.000001,10000,
                     unit='USD/G',step=.01,help='优先于目标利润率；双源确认无货价为独立例外。'),
                _num(doc, 'quote_ttl', '报价最长时效', p+['报价最长时效秒'],1200,60,86400,
                     unit='秒',group='采集',kind='integer',step=60),
                _num(doc, 'change_threshold', '最小改价幅度', p+['变动闸百分比'],.5,0,50,
                     unit='%',step=.1,help='低于此幅度通常保持；售价超限仍按原规则纠正。'),
            ])
            readonly += [{'label':'货源','value':'DD373 与比价器，分别算价后取低价'},
                         {'label':'双源确认无货售价','value':'2.99 USD/G；仅双方确认空挂单时使用，采集未知保持现价'},
                         {'label':'运行周期','value':'约 10 分钟；由独立定时任务控制'},
                         {'label':'成本单位','value':'人民币/G；售价单位 USD/G'}]
        else:
            fields.extend([
                _num(doc,'stock_target','常规利润库存门槛',p+['目标万金'],2000,1,100000000,
                     unit='万金',group='采集',step=1,
                     help='当前最低有效单价口径下，用于区分常规/薄区利润档，不是均价采样量。'),
                _num(doc,'skip_lowest','跳过最低挂单数',p+['跳过最低条数'],1,0,20,
                     unit='条',group='采集',kind='integer',step=1),
                _num(doc,'margin_full','常规利润率',p+['常规利润率'],.30,0,.95,
                     unit='%',scale=100,step=.1),
                _num(doc,'margin_thin','薄区利润率',p+['薄区利润率'],.50,0,.95,
                     unit='%',scale=100,step=.1),
                _num(doc,'outlier_ratio','离群价格倍数',p+['离群倍数'],8,0,100,
                     unit='倍',group='采集',step=.1,help='0 表示关闭此过滤。'),
                _num(doc,'change_threshold','最小改价幅度',p+['变动闸百分比'],.5,0,50,
                     unit='%',step=.1),
                _num(doc,'request_gap','请求间隔',p+['请求延迟秒'],1.2,.25,60,
                     unit='秒',group='采集',step=.1),
            ])
            readonly += [{'label':'成本口径','value':get_path(doc,p+['成本口径'],'low')},
                         {'label':'单价计价单位','value':get_path(doc,p+['单价计价单位'],1000)},
                         {'label':'运行周期','value':'约 15 分钟；由独立定时任务控制'}]
    else:
        schedule_default = {'d4':3,'poe2':3,'poe1':.25,'arc':3,'aion2':.25,'msc':3,'dad':12,'wardogs':6}[game_id]
        fields.append(_num(doc,'interval_hours','采集周期',['运行','采集周期小时',name],
                           schedule_default,.25,24,unit='小时',group='运行',step=.25,
                           kind='select',options=SCHEDULE_CHOICES,
                           help='按现有采集心跳判断是否到期；不会立即触发采集或补发工单。'))
        if game_id in ('aion2','msc'):
            has_override=isinstance(get_path(doc,['金币','定价策略','按游戏',name]),dict)
            policy = ['金币','定价策略'] + (['按游戏',name] if has_override or game_id=='msc' else [])
            cost = ['金币','进货成本','按游戏',name]
            margin, floor, target, gate, count = ((.29,.25,80000,20000,5) if game_id=='aion2'
                                                 else (.30,.30,500,500,10))
            fields += [
                _num(doc,'target_margin','目标利润率',policy+['利润率'],margin,0,.95,
                     unit='%',scale=100,step=.1),
                _num(doc,'margin_floor','利润率下限',policy+['利润率下限'],floor,0,.95,
                     unit='%',scale=100,step=.1),
                _num(doc,'sample_quantity','成本采样量',cost+['目标万量'],target,1,100000000,
                     unit='万基纳' if game_id=='aion2' else '万金',group='采集',step=1,
                     help='数量加权成本目标；不足量时沿用该游戏现行处理规则。'),
                _num(doc,'stock_gate','最低可买库存',policy+['无货最小可买万基纳'],gate,0,100000000,
                     unit='万基纳' if game_id=='aion2' else '万金',group='采集',step=1),
                _num(doc,'min_quotes','最低挂单数',policy+['条数下限'],count,1,1000,
                     unit='条',group='采集',kind='integer',step=1),
            ]
            if game_id=='aion2':
                fields.append(_num(doc,'empty_price','无货保护售价',policy+['无货兜底售价_USD每M'],12.99,
                                   .000001,10000,unit='USD/M',step=.01,
                                   help='无货或库存不足时使用，来源与兜底顺序保持原规则。'))
                fields.append(_num(doc,'short_quotes_price','挂单不足售价',policy+['条数不足售价_USD每M'],12.99,
                                   .000001,10000,unit='USD/M',step=.01))
            readonly += [{'label':'定价方式','value':get_path(doc,policy+['模式'],'dd373_only')},
                         {'label':'货源不足处理','value':'保持当前价格' if game_id=='msc' else '现行无货保护价'},
                         {'label':'跳过最低挂单','value':'1 条（沿用现行规则）'}]
        elif game_id=='poe1':
            # 2026-11-16：PoE1 神圣石专线。定价口径 = DD373 挂单均价 ÷ (1−利润率) ÷ 汇率，
            # 与 IGGM 跟价、千岛成本无关；后台两个商品强制 20 倍关系。
            p=['POE1定价']
            fields += [
                _field(doc,'enabled','启用此游戏自动改价',p+['启用'],True,None,None,
                       kind='boolean',group='运行',
                       help='下一轮读取。在途工单仍按已生成内容执行。'),
                _num(doc,'margin','目标利润率',p+['利润率'],.30,0,.95,
                     unit='%',scale=100,step=.1,
                     help='售价 = DD373 成本 ÷（1−利润率）÷ 汇率。'),
                _num(doc,'sample_rows','成本采样条数',p+['采样条数'],20,2,30,
                     unit='条',group='采集',kind='integer',step=1,
                     help='固定条数模式使用；按数量采样的币种按各自目标累计。接口最多返回30条。'),
                _num(doc,'skip_lowest','跳过最低挂单数',p+['跳过最低条数'],1,0,10,
                     unit='条',group='采集',kind='integer',step=1,
                     help='先整条剔除最便宜的 N 条，再在剩余挂单上算加权均价。'),
                _num(doc,'max_step','单轮最大成本变动',p+['最大单轮变动'],.35,.01,.95,
                     unit='%',scale=100,step=.1,
                     help='超过则本轮不改价；连续 4 轮仍在闸门外会自动放行。'),
                _num(doc,'min_change','最小改价幅度',p+['最小改价幅度'],.002,0,.5,
                     unit='%',scale=100,step=.1,
                     help='目标价与现行价差异小于此值不发写请求；组合包数量倍数被改坏时强制纠正。'),
            ]
            readonly += [
                {'label':'成本来源','value':'DD373 流放之路（国际服）· POE1 · 巫影(标准)；各启用币种分别采价'},
                {'label':'后台位置','value':'gid=157 · 服务区 18858 · 类目 76 Currency'},
                {'label':'写入商品','value':'38588451 Divine Orb = P；71488529 Divine Orb(20+1 Free) = 20 × P'},
                {'label':'附加币种','value':'；'.join('%s：%s'%(x.get('币种名称',x.get('key')),
                    '，'.join('%s ×%s'%(it.get('名称'),it.get('倍数',1)) for it in x.get('商品',[])))
                    for x in get_path(doc,['POE1定价','附加币种'],[]) if x.get('启用',True)) or '无'},
                {'label':'数量采样','value':'；'.join('%s：低价整条累计至少%g个，达到即停'%(x.get('币种名称',x.get('key')),x['采样目标数量'])
                    for x in get_path(doc,['POE1定价','附加币种'],[]) if x.get('启用',True) and x.get('采样目标数量')) or '未启用'},
                {'label':'换算汇率','value':get_path(doc,['POE1定价','汇率USDCNY'],6.65)},
                {'label':'未接入项','value':'IGGM 竞品跟价 / 千岛进货成本 / 前端折扣换算（本条专线都不使用）'},
            ]
        elif game_id=='dad':
            p=['金币固定跟价',name]
            fields += [
                _field(doc,'enabled','启用金币独立跟价',p+['启用'],True,None,None,
                       kind='boolean',group='运行',help='仅控制独立金币链路，装备原有开关保持。'),
                _num(doc,'gold_discount','金币跟随让价',p+['让价百分比'],0,0,90,unit='%',step=.1),
                _num(doc,'gold_deviation','允许偏离目标',p+['最大偏离百分比'],.5,.001,50,unit='%',step=.1),
                _num(doc,'gold_step','单轮最大变动',p+['单轮最大变动'],.30,.001,.95,
                     unit='%',scale=100,step=.1),
                _num(doc,'quote_ttl_hours','报价最长时效',p+['数据最长时效小时'],12,.25,168,
                     unit='小时',group='采集',step=.25),
            ]
            readonly.append({'label':'金币定价方式','value':'IGGM 真价跟随；独立定价约 30 分钟检查一次，采集周期只控制行情更新'})
        else:
            if game_id in ('d4','poe2','arc','wardogs'):
                p=['跟价','按游戏',name,'跟随策略']
                common=['跟价','跟随策略']
                fields += [
                    _num(doc,'item_discount','商品跟随让价（含金币）' if game_id in ('poe2','wardogs') else '道具跟随让价',p+['让价百分比'],
                         get_path(doc,common+['让价百分比'],0),0,90,unit='%',step=.1,
                         help='只改变本游戏商品跟随比例。'),
                    _num(doc,'item_cost_markup','商品成本加价保护',p+['最低毛利率'],
                         get_path(doc,common+['最低毛利率'],.15),0,5,unit='%',scale=100,step=.1,
                         help='保留现行公式：成本 ×（1＋比例），并沿用现行竞品封顶规则；不是按收入计算的毛利率。'),
                ]
            p=['金币','游戏参数',name]
            if game_id not in ('poe2','wardogs'):
                fields.append(_num(doc,'gold_discount','金币跟随让价',p+['让价百分比'],
                                   get_path(doc,['金币','让价百分比'],0),0,90,unit='%',step=.1,
                                   help='只影响本游戏普通金币跟随比例。'))
    return dict(game, fields=fields, readonly=readonly,
                effect='保存后在下一次新轮次读取；已经采集或生成的工单仍使用原快照。')


def cost_parameters(cfg, game):
    """Explicit per-round DD373 settings; no mutable module globals."""
    result=copy.deepcopy(get_path(cfg,['金币','进货成本','按游戏',game],{}) or {})
    policy=get_path(cfg,['金币','定价策略','按游戏',game])
    if not isinstance(policy,dict) and game=='AION2':
        policy=get_path(cfg,['金币','定价策略'],{})
    policy=policy or {}
    if game=='MapleStory Classic World':
        result['最低条数']=policy.get('条数下限',10)
    if game=='AION2':
        result['薄区万量']=policy.get('无货最小可买万基纳',20000)
    return result


def apply_fields(game_id, doc, patch, common_cfg=None):
    if not isinstance(doc, dict):
        raise ValueError('配置结构不正确')
    if not isinstance(patch, dict) or not patch:
        raise ValueError('没有要保存的字段')
    schema = get_game_schema(game_id, doc, common_cfg)
    allowed = {f['key']:f for f in schema['fields']}
    unknown = set(patch)-set(allowed)
    if unknown:
        raise ValueError('字段不允许修改：'+', '.join(sorted(map(str,unknown))))
    new_doc, changes = copy.deepcopy(doc), []
    for key, raw in patch.items():
        spec=allowed[key]
        if spec['type']=='boolean':
            if not isinstance(raw,bool):
                raise ValueError(spec['label']+'需要布尔值')
            value=raw
        else:
            if isinstance(raw,bool) or not isinstance(raw,(int,float)) or not math.isfinite(raw):
                raise ValueError(spec['label']+'需要有限数字')
            if not spec['min'] <= raw <= spec['max']:
                raise ValueError(spec['label']+'超出允许范围')
            if spec['type']=='integer' and int(raw)!=raw:
                raise ValueError(spec['label']+'需要整数')
            if 'options' in spec and raw not in spec['options']:
                raise ValueError(spec['label']+'不在可选范围')
            value=int(raw) if spec['type']=='integer' else float(raw)
        before=spec['value']
        if value != before:
            set_path(new_doc,spec['path'],value)
            sentinel=object()
            changes.append(dict(key=key,label=spec['label'],path=spec['path'],before=before,after=value,
                                unit=spec['unit'],scale=spec['scale'],
                                before_exists=get_path(doc,spec['path'],sentinel) is not sentinel))
    values={f['key']:f['value'] for f in get_game_schema(game_id,new_doc,common_cfg)['fields']}
    if game_id=='wow' and values['scarce_boundary']>=values['sample_gold']:
        raise ValueError('稀缺库存分界必须低于成本采样金币量')
    if game_id in ('aion2','msc') and values['margin_floor']>values['target_margin']:
        raise ValueError('利润率下限不能高于目标利润率')
    return new_doc, changes
