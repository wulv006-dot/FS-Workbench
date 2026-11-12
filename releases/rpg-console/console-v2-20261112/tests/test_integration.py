import copy
import datetime as dt
import importlib.util
import json
import pathlib
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from support import APP, MAIN, SEP
from flask import Flask,jsonify
import console_web as web
import game_parameters as gp
import engine
from console_config import ConfigStore,ConfigError



class IntegratedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='rpg08_')
        self.root=pathlib.Path(self.temp.name)
        self.cfg=copy.deepcopy(MAIN)
        self.cfg['商品映射']={'对照项':[]}
        self.cfg['金币']['服务区']=[]
        for name,doc in [('config.json',self.cfg),('wow_gold_config.json',SEP['wow_gold_config.json']),('aa_gold_config.json',SEP['aa_gold_config.json'])]:
            (self.root/name).write_text(json.dumps(doc,ensure_ascii=False),encoding='utf-8')
        (self.root/'data').mkdir()
        con=sqlite3.connect(self.root/'data'/'iggm_follow.db')
        con.execute('CREATE TABLE local_job(id,title,status,created_at,finished_at,result_json,plan_json)')
        con.commit();con.close()
        self.calls=[]
        self.api={'CFG_LOCK':threading.RLock(),'load_cfg':lambda:copy.deepcopy(self.cfg),
          'save_cfg':lambda c:self.calls.append(('save',c)), 'sync_mode':lambda c:None,
          'engine':engine, 'schedule_snapshot':lambda c:{'列表':[]},
          '_srv_exec_state':lambda:{'alive':True},
          'core_gold':types.SimpleNamespace(pricing_policy=lambda c,g:None)}
        self.app=Flask('test08',template_folder=str(APP/'templates'))
        self.app.add_url_rule('/','index',lambda:'old')
        for endpoint in ['api_follow','api_schedule','api_config','api_switch','api_mode','api_iggm_source_set','api_exec_mode']:
            def old(ep=endpoint):self.calls.append(ep);return jsonify(ok=True)
            self.app.add_url_rule('/old/'+endpoint,endpoint,old,methods=['POST'])
        web.register_console(self.app,str(self.root),self.api)
        self.client=self.app.test_client()
    def tearDown(self):self.temp.cleanup()
    def test_nine_schemas_routes_and_secret_exclusion(self):
        for g in gp.GAMES:
            response=self.client.get('/api/games/'+g['id']+'/config')
            self.assertEqual(response.status_code,200,g['id'])
            data=response.json['data']
            self.assertEqual(data['id'],g['id'])
            self.assertEqual(len(data['version']),64)
            self.assertTrue(data['fields'])
            for f in data['fields']:
                self.assertIn(f['type'],('boolean','number','integer','select'))
                self.assertNotIn('password','.'.join(f['path']))
                self.assertNotIn('token','.'.join(f['path']))
    def test_all_page_routes_render_and_alias_prefix(self):
        for path in ['/','/changes','/games/wow/','/games/wow/settings','/maintenance/']:
            response=self.client.get(path,headers={'X-Forwarded-Prefix':'/repricing/'})
            self.assertEqual(response.status_code,200,path)
            self.assertIn(b'/repricing/',response.data)
        self.assertEqual(self.client.get('/games/not-game/settings').status_code,404)
    def test_legacy_cannot_revive_wow_or_global_follow(self):
        for body in ({'all':True},{'all':False},{'game':'WoW Forever','on':True},{'key':'WOWF_X','on':True}):
            self.assertEqual(self.client.post('/old/api_follow',json=body).status_code,400)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.client.post('/old/api_follow',json={'game':'AION2','on':False}).status_code,200)
        self.assertEqual(self.calls,['api_follow'])
    def test_legacy_rejects_wow_old_schedule(self):
        self.assertEqual(self.client.post('/old/api_schedule',json={'周期':{'WoW Forever':6}}).status_code,400)
        self.assertEqual(self.calls,[])
    def test_current_and_target_prices_are_separate(self):
        (self.root/'output').mkdir()
        (self.root/'output'/'魔兽金币台账_20261112_100000.json').write_text(json.dumps({'ts':'2026-11-12T10:00:00','plan':[{'后台名':'example','现b2c':1.2,'目标b2c':1.6,'利润率':-.1,'可买金':25,'动作':'up'}]}),encoding='utf-8')
        response=self.client.get('/api/games/wow/monitor')
        self.assertEqual(response.status_code,200)
        row=response.json['data']['rows'][0]
        self.assertEqual(row['current'],1.2);self.assertEqual(row['target'],1.6)
        self.assertEqual(row['margin'],-.1)
    def test_jobs_unknown_not_claimed_confirmed_and_real_pending(self):
        con=sqlite3.connect(self.root/'data'/'iggm_follow.db')
        for key,status,state in [('a','failed','unknown'),('b','done','confirmed'),('c','pending',None)]:
            con.execute('INSERT INTO local_job VALUES(?,?,?,?,?,?,?)',(key,'test',status,'2026-11-12T10:00:00',None,json.dumps({'write_state':state}),json.dumps({'游戏':['AION2']})))
        con.commit();con.close()
        jobs,pending=web.jobs_summary(self.root)
        self.assertEqual(pending,1)
        jobs={j['id']:j for j in jobs}
        self.assertEqual(jobs['a']['status_label'],'结果待核实')
        self.assertEqual(jobs['b']['status_label'],'已核实完成')
    def test_storage_api_actual_edited_consumer_and_restore(self):
        headers={'Origin':'http://localhost','X-Authenticated-User':'test08'}
        route='/api/games/d4/config'
        original=self.client.get(route).json['data']
        res=self.client.post(route,json={'version':original['version'],'patch':{'item_discount':7}},headers=headers)
        self.assertEqual(res.status_code,200,res.json)
        doc=json.loads((self.root/'config.json').read_text(encoding='utf-8'))
        self.assertEqual(engine.strategy_of(doc,'暗黑破坏神4')['让价百分比'],7)
        self.assertEqual(engine.strategy_of(doc,'流放之路2')['让价百分比'],2)
        hist=self.client.get('/api/config/history').json['items']
        self.assertEqual(len(hist),1);self.assertEqual(hist[0]['actor'],'test08')
        restored=self.client.post('/api/config/restore',json={'id':hist[0]['id'],'version':res.json['data']['version']},headers=headers)
        self.assertEqual(restored.status_code,200,restored.json)
        doc=json.loads((self.root/'config.json').read_text(encoding='utf-8'))
        self.assertEqual(engine.strategy_of(doc,'暗黑破坏神4')['让价百分比'],2)
    def test_schema_consumers_for_quick_gold(self):
        for game_id,game_name in [('poe2','流放之路2'),('wardogs','WarDogs')]:
            fields={f['key']:f for f in gp.get_game_schema(game_id,MAIN)['fields']}
            self.assertNotIn('gold_discount',fields,'Quick Gold is an ordinary engine item')
            new,_=gp.apply_fields(game_id,MAIN,{'item_discount':6})
            self.assertEqual(engine.strategy_of(new,game_name)['让价百分比'],6)
    def test_dad_independent_flag_and_real_history(self):
        now=dt.datetime.now().isoformat(timespec='seconds')
        self.cfg['商品映射']['对照项']=[{'游戏':'Dark and Darker','key':'DND_GOLD','跟价':False}]
        self.cfg['金币固定跟价']={'Dark and Darker':{'启用':True}}
        self.cfg['跟价']['系统开关']=False
        con=sqlite3.connect(self.root/'data'/'iggm_follow.db')
        con.execute('CREATE TABLE dnd_gold_follow(ts)')
        con.execute('INSERT INTO dnd_gold_follow VALUES(?)',(now,))
        con.commit();con.close()
        self.api['schedule_snapshot']=lambda c:{'列表':[{'游戏':'Dark and Darker','周期小时':12,'上次':'2001-01-01T00:00:00'}]}
        games={g['id']:g for g in web.console_snapshot(self.root,self.api)['games']}
        self.assertEqual(games['dad']['status'],'active')
        self.assertEqual(games['dad']['last_run'],now)
        self.assertEqual(games['dad']['schedule_label'],'定价约 30 分钟 / 采集 12 小时')
        self.cfg['金币固定跟价']['Dark and Darker']['启用']=False
        games={g['id']:g for g in web.console_snapshot(self.root,self.api)['games']}
        self.assertEqual(games['dad']['status'],'paused')
    def test_common_monitoring_does_not_pause_independent_games(self):
        self.cfg['跟价']['系统开关']=True
        self.cfg['跟价']['自动跟价']=False
        self.cfg['商品映射']['对照项']=[{'游戏':'暗黑破坏神4','key':'D4_TEST','跟价':True}]
        games={g['id']:g for g in web.console_snapshot(self.root,self.api)['games']}
        self.assertEqual(games['d4']['status'],'monitoring')
        self.assertEqual(games['d4']['status_label'],'仅采集，待手动派单')
        for key in ('wow','aa','dad'):
            self.assertNotEqual(games[key]['status'],'monitoring')
    def test_dad_schema_controls_real_independent_path_only(self):
        new,_=gp.apply_fields('dad',MAIN,{'enabled':False})
        self.assertIs(new['金币固定跟价']['Dark and Darker']['启用'],False)
        self.assertEqual(new['跟价'],MAIN['跟价'])
        self.assertEqual(new.get('商品映射'),MAIN.get('商品映射'))

if __name__=='__main__':unittest.main(verbosity=2)
