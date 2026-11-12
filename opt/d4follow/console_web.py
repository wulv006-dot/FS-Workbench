"""Read-only RPG console and compatibility routes. No collector or writer calls."""
import datetime as dt
import functools
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import jsonify, render_template, request

VERSION = 'rpg-console-v2-20261112'
GAME_LIST = [
    ('aion2', 'AION2', 'AION2', 'config.json'),
    ('wow', '魔兽无限', 'WoW Forever', 'wow_gold_config.json'),
    ('d4', '暗黑破坏神4', '暗黑破坏神4', 'config.json'),
    ('poe2', '流放之路2', '流放之路2', 'config.json'),
    ('arc', 'ARC Raiders', 'ARC Raiders', 'config.json'),
    ('msc', '冒险岛怀旧服', 'MapleStory Classic World', 'config.json'),
    ('aa', '上古世纪编年史', 'ArcheAge Chronicles', 'aa_gold_config.json'),
    ('dad', 'Dark and Darker', 'Dark and Darker', 'config.json'),
    ('wardogs', 'WarDogs', 'WarDogs', 'config.json'),
]
GAME_MAP = {r[0]:r for r in GAME_LIST}


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def age_minutes(stamp):
    try:
        return max(0, (dt.datetime.now() - dt.datetime.fromisoformat(stamp)).total_seconds()/60)
    except (TypeError, ValueError):
        return None


def latest_ledger(root, game):
    pattern = {'wow':'魔兽金币台账_*.json', 'aa':'上古金币台账_*.json'}.get(game)
    if not pattern:
        return None
    files = sorted((Path(root)/'output').glob(pattern), reverse=True)
    # A partial newest write is shown as unavailable, never silently replaced by an old round.
    return read_json(files[0]) if files else None


def database(root):
    p = Path(root)/'data'/'iggm_follow.db'
    con = sqlite3.connect(p.resolve().as_uri()+'?mode=ro', uri=True, timeout=3)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    return con


def jobs_summary(root):
    with closing(database(root)) as con:
        rows = [dict(r) for r in con.execute(
            'SELECT id,title,status,created_at,finished_at,result_json,plan_json FROM local_job '
            'ORDER BY created_at DESC LIMIT 12')]
        pending = con.execute("SELECT COUNT(*) FROM local_job WHERE status IN ('pending','dispatched')").fetchone()[0]
    out=[]
    labels={'pending':'等待执行','dispatched':'执行中','done':'已完成','failed':'执行异常','canceled':'已取消'}
    for row in rows:
        result=read_doc(row.get('result_json'))
        plan=read_doc(row.get('plan_json'))
        ws=result.get('write_state')
        status=row['status']
        if ws in ('unknown','partial','partially_written'):
            label='结果待核实'
        elif status=='done' and ws=='confirmed':
            label='已核实完成'
        elif status=='done':
            label='已回报完成'
        else:
            label=labels.get(status, '待核实')
        games=plan.get('游戏') or []
        if isinstance(games,str): games=[games]
        out.append({'id':row['id'],'game':'、'.join(str(g) for g in games),
                    'created_at':row['created_at'],'status':status,'status_label':label,
                    'success':number(result.get('ok_count',result.get('ok',result.get('success')))),
                    'failed':number(result.get('fail_count',result.get('fail',result.get('failed')))),
                    'unknown':1 if ws in ('unknown','partial','partially_written') else (0 if ws=='confirmed' else None)})
    return out,pending


def read_doc(raw):
    try:
        d=json.loads(raw or '{}')
        return d if isinstance(d,dict) else {}
    except (TypeError,ValueError):
        return {}


def game_rows(cfg, api, name):
    items=[x for x in (cfg.get('商品映射',{}).get('对照项') or []) if x.get('游戏')==name]
    gold=[x for x in (cfg.get('金币',{}).get('服务区') or []) if api['engine'].game_of(cfg,x.get('key'))==name]
    return items,gold


def console_snapshot(root, api):
    cfg=api['load_cfg']()
    schedule={x['游戏']:x for x in api['schedule_snapshot'](cfg)['列表']}
    games=[]
    notices=[]
    for game_id,name,source_name,filename in GAME_LIST:
        items,gold=game_rows(cfg,api,source_name)
        source='IGGM'
        rule='按当前游戏规则运行'
        attention=0
        last=None
        if game_id in ('wow','aa'):
            doc=read_json(Path(root)/filename)
            ledger=latest_ledger(root,game_id)
            enabled=bool(doc and doc.get('启用'))
            last=(ledger or {}).get('ts')
            p=(doc or {}).get('参数') or {}
            source='DD373 / 比价器' if game_id=='wow' else 'DD373'
            interval=10 if game_id=='wow' else 15
            schedule_label='约 %d 分钟'%interval
            region_count=len((doc or {}).get('区服') or []) or len((ledger or {}).get('plan') or [])
            if game_id=='wow':
                rule='充足 %.0f%% · 偏少 %.0f%% · 稀缺 %.0f%%'%(
                    float(p.get('常规利润率',.25))*100,float(p.get('薄区利润率',.30))*100,float(p.get('稀缺利润率',.35))*100)
            else:
                rule='常规 %.0f%% · 薄区 %.0f%%'%(float(p.get('常规利润率',.30))*100,float(p.get('薄区利润率',.50))*100)
            if not doc: attention+=1
        else:
            sch=schedule.get(source_name,{})
            interval=float(sch.get('周期小时') or 6)*60
            schedule_label=('%g 分钟'%interval) if interval<60 else ('%g 小时'%(interval/60))
            last=sch.get('上次')
            enabled=any(x.get('跟价',True) for x in items+gold)
            region_count=len(gold)
            pol=api['core_gold'].pricing_policy(cfg,source_name) or {}
            if pol.get('模式')=='dd373_only':
                source='DD373'
                rule='目标毛利 %.0f%% · 下限 %.0f%%'%(float(pol.get('利润率',0))*100,float(pol.get('利润率下限',0))*100)
            elif items:
                over=((cfg.get('跟价',{}).get('按游戏') or {}).get(source_name) or {}).get('跟随策略') or {}
                discount=over.get('让价百分比',(cfg.get('跟价',{}).get('跟随策略') or {}).get('让价百分比',0))
                rule='道具跟随让价 %g%%'%float(discount)
            if game_id=='dad':
                p=(cfg.get('金币固定跟价') or {}).get(source_name) or {}
                enabled=bool(p.get('启用',True))
                rule='金币跟随让价 %g%%；装备按原开关运行'%float(p.get('让价百分比',0))
                schedule_label='定价约 30 分钟 / 采集 %g 小时'%(interval/60)
                interval=30
                try:
                    with closing(database(root)) as con:
                        row=con.execute('SELECT ts FROM dnd_gold_follow ORDER BY rowid DESC LIMIT 1').fetchone()
                        last=row[0] if row else None
                except sqlite3.Error:
                    last=None
        age=age_minutes(last)
        stale=enabled and (age is None or age>max(interval*2,40))
        status='paused' if not enabled else ('attention' if stale or attention else 'active')
        label='已暂停' if not enabled else ('需关注' if status=='attention' else '运行中')
        if game_id not in ('aa','dad') and enabled and not cfg.get('跟价',{}).get('系统开关',False):
            status,label='paused','执行已暂停'
        elif game_id not in ('wow','aa','dad') and enabled and not cfg.get('跟价',{}).get('自动跟价',False):
            status,label='monitoring','仅采集，待手动派单'
        if stale: attention+=1
        games.append({'id':game_id,'name':name,'subtitle':source_name if source_name!=name else '',
            'status':status,'status_label':label,'enabled':enabled,'schedule_label':schedule_label,'last_run':last,
            'items_count':len(items),'regions_count':region_count,'attention_count':attention,
            'source_label':source,'rule_summary':rule})
    try:
        jobs,pending=jobs_summary(root)
    except sqlite3.Error:
        jobs,pending=[],None
        notices.append({'level':'warning','title':'执行记录暂不可用','detail':'请稍后刷新。当前页面不会补报改价成功。'})
    executor=api['_srv_exec_state']()
    if not executor.get('alive'):
        notices.append({'level':'warning','title':'执行器状态待核实','detail':'暂未读到新鲜的运行状态。'})
    return {'updated_at':dt.datetime.now().isoformat(timespec='seconds'),'version':VERSION,
        'summary':{'games':len(games),'enabled':sum(x['enabled'] for x in games),
                   'attention':sum(x['status']=='attention' for x in games),
                   'pending':pending,'executor_label':'在线' if executor.get('alive') else '待核实'},
        'games':games,'recent_jobs':jobs,'notices':notices}


def monitor_snapshot(root, api, game_id):
    _,name,source_name,_=GAME_MAP[game_id]
    cfg=api['load_cfg']()
    notes=[]
    rows=[]
    if game_id in ('wow','aa'):
        led=latest_ledger(root,game_id)
        if not led:
            return {'id':game_id,'name':name,'updated_at':None,'unit':'','columns':[], 'rows':[], 'notes':['暂未读到采集记录。']}
        wow=game_id=='wow'
        unit='USD/G' if wow else 'USD/K'
        for r in led.get('plan') or []:
            rows.append({'title':r.get('后台名'),'current':number(r.get('现b2c' if wow else '现b2c$每币')),
                'target':number(r.get('目标b2c' if wow else '目标b2c$每币')),
                'margin':number(r.get('利润率')),
                'source':r.get('成本来源') if wow else 'DD373',
                'inventory':number(r.get('可买金' if wow else '可买万金')),
                'action':r.get('动作'),'note':r.get('备注') or r.get('规则') or ''})
        notes=['现价是本轮采集时读取的后台价格；目标价是本轮计划，不代表已执行。',
               '采集时间与其他游戏分别记录。']
        if not wow: notes.append('上古当前缺少自动写后核验，执行完成需单独核实。')
        columns=[{'key':'title','label':'区服'},{'key':'current','label':'采集时现价 ('+unit+')','type':'number'},
            {'key':'target','label':'计划目标 ('+unit+')','type':'number'},
            {'key':'margin','label':'测算毛利','type':'percent'},{'key':'source','label':'成本来源'},
            {'key':'inventory','label':'库存 ('+('G' if wow else '万金')+')','type':'number'},
            {'key':'action','label':'本轮动作'},{'key':'note','label':'说明'}]
        return {'id':game_id,'name':name,'updated_at':led.get('ts'),'unit':unit,'columns':columns,'rows':rows,'notes':notes}
    items,gold=game_rows(cfg,api,source_name)
    keymap={str(x.get('key')):x for x in items+gold}
    with closing(database(root)) as con:
        if gold:
            records=con.execute('SELECT * FROM gold_price WHERE ts=(SELECT MAX(ts) FROM gold_price)').fetchall()
            mult=api['core_gold'].display_mult_of(cfg,source_name)
            unit=api['core_gold'].unit_label(mult,(api['core_gold'].game_param(cfg,source_name) or {}).get('展示单位名'))
            for raw in records:
                r=dict(raw)
                if r['key'] not in keymap: continue
                current=number(r.get('our_per_m'))
                cost=number(r.get('cost_target'))
                divisor=number(r.get('divisor'))
                target=cost/divisor if cost is not None and divisor else None
                rows.append({'title':r.get('title') or r['key'],'category':'金币 / '+str(unit),
                    'current':current*mult if current is not None else None,
                    'target':target*mult if target is not None else None,'source':r.get('price_mode') or 'IGGM',
                    'action':r.get('action'),'note':r.get('reason'),'observed_at':r.get('ts')})
        if items:
            for raw in con.execute('SELECT d.* FROM decisions d JOIN (SELECT key,MAX(ts) ts FROM decisions GROUP BY key) latest ON latest.key=d.key AND latest.ts=d.ts'):
                r=dict(raw)
                if r['key'] not in keymap: continue
                rows.append({'title':r.get('title') or r['key'],'category':'道具 / USD',
                    'current':number(r.get('ours_old')),'target':number(r.get('target_usd')),
                    'source':'IGGM','action':r.get('action'),'note':r.get('reason'),'observed_at':r.get('ts')})
    columns=[{'key':'title','label':'商品 / 区服'},{'key':'category','label':'类型与单位'},
        {'key':'current','label':'采集时现价 (USD)','type':'number'},
        {'key':'target','label':'计划目标 (USD)','type':'number'},
        {'key':'action','label':'本轮动作'},{'key':'note','label':'定价说明'}]
    schedule={x['游戏']:x for x in api['schedule_snapshot'](cfg)['列表']}
    return {'id':game_id,'name':name,'updated_at':schedule.get(source_name,{}).get('上次'),
        'unit':'按行展示','columns':columns,'rows':rows,'notes':['表内是采集与计划快照；实际执行结果以工单记录为准。']}


def register_console(app, root, api):
    from console_config import register_config, config_transaction_lock
    register_config(app, root, api['CFG_LOCK'])

    def base_path():
        prefix=request.headers.get('X-Forwarded-Prefix','/d4/').rstrip('/')+'/'
        return prefix if prefix in ('/d4/','/repricing/') else '/d4/'

    def page(page='home',game_id=None):
        if game_id is not None and game_id not in GAME_MAP:
            return '游戏不存在',404
        return render_template('console.html',base_path=base_path(),page=page,game_id=game_id,version=VERSION)

    app.view_functions['index']=lambda:page()
    app.add_url_rule('/games/<game_id>/','console_monitor_page',lambda game_id:page('monitor',game_id))
    app.add_url_rule('/games/<game_id>/settings','console_settings_page',lambda game_id:page('settings',game_id))
    app.add_url_rule('/changes','console_history_page',lambda:page('history'))
    app.add_url_rule('/maintenance/','console_maintenance',lambda:render_template('index.html',version=VERSION,console_base=base_path()))

    @app.route('/api/console')
    def console_overview():
        try:
            return jsonify(ok=True,data=console_snapshot(root,api))
        except Exception:
            app.logger.exception('console read failed')
            return jsonify(ok=False,error='概览读取失败，请稍后刷新'),503

    @app.route('/api/games/<game_id>/monitor')
    def console_monitor(game_id):
        if game_id not in GAME_MAP: return jsonify(ok=False,error='未知游戏'),404
        try:
            return jsonify(ok=True,data=monitor_snapshot(root,api,game_id))
        except Exception:
            app.logger.exception('monitor read failed')
            return jsonify(ok=False,error='监控数据暂不可用，请稍后刷新'),503

    # Keep old automation URLs working. Serialize every existing config writer with the new editor.
    endpoints=('api_config','api_schedule','api_follow','api_mode','api_switch','api_iggm_source_set','api_exec_mode')
    for endpoint in endpoints:
        original=app.view_functions.get(endpoint)
        if original is None: continue
        def guarded(fn=original, name=endpoint):
            @functools.wraps(fn)
            def run(*args,**kwargs):
                body=request.get_json(silent=True) or {}
                if name=='api_follow':
                    if 'all' in body:
                        return jsonify(ok=False,error='请按游戏管理跟价范围，全局批量开关已停用'),400
                    if body.get('game')=='WoW Forever' or str(body.get('key','')).startswith('WOWF_'):
                        return jsonify(ok=False,error='魔兽使用独立配置，请从魔兽配置页修改'),400
                if name=='api_schedule' and 'WoW Forever' in (body.get('周期') or {}):
                    return jsonify(ok=False,error='魔兽使用独立运行周期，不能保存旧采集周期'),400
                with config_transaction_lock(root,api['CFG_LOCK']):
                    result=fn(*args,**kwargs)
                    if name=='api_config':
                        status=result[1] if isinstance(result,tuple) else getattr(result,'status_code',200)
                        if status<400 and any(str(k).startswith('跟价.') for k in (body.get('patch') or {})):
                            cfg=api['load_cfg']()
                            api['sync_mode'](cfg)
                            api['save_cfg'](cfg)
                    return result
            return run
        app.view_functions[endpoint]=guarded()
