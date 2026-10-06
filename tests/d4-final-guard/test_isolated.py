import ast, pathlib, re, json, html, sys, types, socket, unittest, io, contextlib, urllib.parse, math
ROOT=pathlib.Path(__file__).parent/'candidate/opt/d4follow'
def deny(*a,**kw):raise AssertionError('External I/O forbidden in isolated tests')
socket.socket=deny
def functions(file):
    tree=ast.parse((ROOT/file).read_text(encoding='utf-8'))
    ns={'re':re,'json':json,'html':html,'sys':sys,'math':math,'time':types.SimpleNamespace(sleep=lambda *a:None,time=lambda:0),'urllib':types.SimpleNamespace(parse=urllib.parse),'__name__':'isolated'}
    # Execute reviewed function definitions, literal constants and regex constants only.
    # No package imports, module startup, CLI, decorators, clients or storage executed.
    for n in tree.body:
        if isinstance(n,ast.Assign):
            try:v=ast.literal_eval(n.value)
            except (ValueError,TypeError):
                if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and isinstance(n.value.func.value,ast.Name) and n.value.func.value.id=='re' and n.value.func.attr=='compile':
                    v=eval(compile(ast.Expression(n.value),file,'eval'),ns)
                elif all(isinstance(x,(ast.Dict,ast.Subscript,ast.Name,ast.Load,ast.Constant)) for x in ast.walk(n.value)):
                    v=eval(compile(ast.Expression(n.value),file,'eval'),ns)
                else:continue
            for t in n.targets:
                if isinstance(t,ast.Name):ns[t.id]=v
    for n in tree.body:
        if isinstance(n,ast.FunctionDef):
            n.decorator_list=[]
            exec(compile(ast.Module([n],type_ignores=[]),file,'exec'),ns)
    ns['_get']=deny;ns['post_form']=deny;ns['fetch_front_gold']=deny
    return ns
ng=functions('gold_numeric_guard.py');ngmod=types.ModuleType('gold_numeric_guard');ngmod.__dict__.update(ng);sys.modules['gold_numeric_guard']=ngmod
g2g=functions('core_g2g.py');gold=functions('core_gold.py');front=functions('core_front.py');gates=functions('gates.py');engine=functions('engine.py')
mod=types.ModuleType('core_g2g');mod.__dict__.update(g2g);sys.modules['core_g2g']=mod
gold['multisrc']=lambda *a,**k:None
app=functions('app.py')
class Synthetic(unittest.TestCase):
    def test_cheapold_and_fallback(self):
        cases=[([{'username':'other','converted_unit_price':2},{'username':'cheapold','converted_unit_price':9,'min_qty':5}],9,'cheapold'),([{'username':'a','converted_unit_price':4},{'username':'b','converted_unit_price':3},{'username':'c','converted_unit_price':1}],3,'推荐前二'),([],None,None),([{'username':' CHEAPOLD ','converted_unit_price':7}],7,'cheapold'),([{'username':'a','converted_unit_price':None},{'username':'b','converted_unit_price':3}],3,'推荐前二')]
        for offers,price,src in cases:
            with self.subTest(offers=offers):
                g2g['scrape_offers']=lambda *a,**k:offers
                rec=g2g['cheapold_base']('lgc_12_123','EU')
                self.assertEqual((rec['base'],rec['src']),(price,src))
        self.assertEqual(g2g['dataset_collection']('lgc_12_123'),'lgc_12')
    def test_scrape_query_is_synthetic(self):
        seen=[]
        g2g['_get']=lambda url,**kw:(seen.append(url) or {'code':2000,'payload':{'results':[]}})
        for area in ['EU','NA West','NA East','Asia','South America']:
            with self.subTest(area=area):
                g2g['scrape_offers']=functions('core_g2g.py')['scrape_offers']
                g2g['scrape_offers'].__globals__['_get']=g2g['_get']
                g2g['scrape_offers']('lgc_12_123',area)
                q=urllib.parse.parse_qs(urllib.parse.urlparse(seen[-1]).query)
                self.assertEqual(q['filter_attr'],['lgc_12:lgc_12_123']);self.assertEqual(q['sort'],['recommended_v4'])
        with self.assertRaises(KeyError):g2g['scrape_offers']('bad','UNKNOWN')
    def policycfg(self):return {'金币':{'启用':True,'定价策略':{'模式':'g2g_cheapold','适用游戏':['AION2'],'下浮比例':0.03},'机房系数':1},'商品映射':{}}
    def test_game_policy_isolation(self):
        cfg=self.policycfg()
        for game in ['暗黑破坏神4','POE2']:
            with self.subTest(game=game):self.assertIsNone(gold['pricing_policy'](cfg,game))
        self.assertEqual(gold['pricing_policy'](cfg,'AION2')['乘数'],.97)
        cfg['金币']['定价策略']['下浮比例']=0
        self.assertEqual(gold['pricing_policy'](cfg,'AION2')['乘数'],1)
        cfg['金币']['定价策略']['模式']='multisrc';self.assertEqual(gold['pricing_policy'](cfg,'AION2')['模式'],'multisrc')
    def plan(self,game='AION2',quote=10,dataset='lgc_12_123',empty_front=False,fail=False,discount=.03,extra=None,offers=None):
        cfg=self.policycfg()
        cfg['金币']['定价策略']['下浮比例']=discount
        cfg['金币'].update(extra or {})
        sv={'key':'SYNTHETIC_A' if game=='AION2' else 'SYNTHETIC_D','中文名':'Synthetic','游戏':game,'跟价':True,'前端aid':'FAKE','大区':'EU','g2g_dataset':dataset,'利润率':.2}
        if offers is not None:
            g2g['scrape_offers']=lambda *a,**k:offers
            mod.cheapold_base=g2g['cheapold_base']
        elif fail:mod.cheapold_base=deny
        else:mod.cheapold_base=lambda *a,**k:{'base':quote,'src':'cheapold' if quote is not None else None,'cheapold':quote,'who':'cheapold','n':1}
        ig=types.SimpleNamespace(fetch=lambda *a,**kw:{'unit_price':2,'tiers':[{'num':100,'all':200}]})
        return gold['build_plan'](cfg,log=lambda *a:None,iggm_obj=ig,front_fn=lambda aid:[] if empty_front else [{'num':100,'price_discount':100,'discount':100}],servers=[sv])['items'][0]
    def test_real_plan_cheapold_hold_and_no_cross_game(self):
        r=self.plan();self.assertAlmostEqual(r['目标前端每M'],9.7);self.assertEqual(r['定价模式'],'g2g_cheapold')
        for kw in [{'quote':None},{'dataset':''},{'fail':True}]:
            with self.subTest(kw=kw):
                r=self.plan(**kw);self.assertIsNone(r['目标前端每M']);self.assertEqual(r['动作'],'hold');self.assertIsNone(r['采购成本_新'])
        r=self.plan(game='暗黑破坏神4');self.assertNotEqual(r.get('定价模式'),'g2g_cheapold');self.assertLess(r['目标前端每M'],3)
        r=self.plan(empty_front=True);self.assertEqual(r['动作'],'hold');self.assertIsNone(r['采购成本_新'])
    def test_pack_precision_and_missing(self):
        for name,n in [('(10) Lair Key',10),('Lair Key*100',100),('Lair Key✕1000',1000)]:
            with self.subTest(name=name):self.assertEqual(front['split_pack'](name)[1],n)
        for raw,expect in [('&#039;',"'"),('&amp;','&')]:self.assertEqual(front['_clean'](raw),expect)
        payload='<div class="goods-title">(10) Lair Key</div><span id="s123" data-price="$ 0.09"></span><span data-id="123" data-discount="90" data-price="0.089"></span>'
        front['_get']=lambda *a,**kw:payload
        row=front['scrape_page']('synthetic-items',log=lambda *a:None)[0]
        self.assertAlmostEqual(row['price_usd'],.0801);self.assertAlmostEqual(row['unit_price_usd'],.00801);self.assertEqual(row['pack_size'],10)
        front['_get']=lambda *a,**kw:'';self.assertEqual(front['scrape_page']('synthetic-items',log=lambda *a:None),[])
        self.assertEqual(gold['biggest_tier']([]),(None,None,None))
    def test_pack_audit_and_preserved_safety(self):
        cfg={'商品映射':{'对照项':[{'key':'LAIR_X10','数量':1000,'装量':1000},{'key':'LAIR_X1000','数量':1000,'装量':1000}]}}
        with contextlib.redirect_stdout(io.StringIO()):bad,dup=front['_audit_pack_conflicts'](cfg)
        self.assertTrue(bad);self.assertTrue(dup);self.assertTrue(gates['audit_qty_collisions'](cfg,log=lambda *a:None))
        self.assertTrue(gates['clamp_round_step']({},1,9)[1]);self.assertFalse(gates['clamp_round_step']({},1,1.1)[1])
        cfg={'前端':{'后台折扣':90},'商品映射':{'游戏字典':{'POE2':{'后台折扣':100}}}}
        self.assertEqual(engine['disc_of'](cfg,{'游戏':'POE2'}),1);self.assertEqual(engine['disc_of'](cfg,{'游戏':'D4'}),.9)
        self.assertEqual(engine['units_of']({'iggm':{'计数':1000}}),1000)
        self.assertEqual(engine['front_disc_of']({'_前台折扣':80}),80)
    def test_actual_summary_endpoint_without_db(self):
        cfg=self.policycfg();cfg['金币']['服务区']=[{'key':'SYNTH_A','g2g_服务区':'Siel - Elyos','中文名':'Siel（天族）','大区':'EU'}]
        app['load_cfg']=lambda:cfg;app['open_db']=lambda:object();app['jsonify']=lambda v:v
        app['core_gold']=types.SimpleNamespace(**gold);app['engine']=types.SimpleNamespace(game_of=lambda *a:'AION2')
        app['store']=types.SimpleNamespace(gold_latest=lambda con:([{'key':'SYNTH_A','tgt_big':970,'big_tier':100}],None),gold_cost_latest=lambda con,game:[{'key':'SYNTH_A','ok':True,'usd_per_m':2,'dd_zone':'oldname','dd_area':'oldregion','dd_race':'oldrace'}],gold_ticket_map=lambda *a:{})
        res=app['api_gold_cost']();row=res['items'][0]
        self.assertEqual((row['服务器名'],row['大区中文'],row['种族']),('Siel','欧服','天族'))
        self.assertAlmostEqual(row['售价_USD每M'],9.7)
        cfg['金币']['服务区']=[];row=app['api_gold_cost']()['items'][0];self.assertEqual(row['服务器名'],'oldname')
    def test_helper_static_only_and_sha_boundaries(self):
        tree=ast.parse((ROOT/'switch_pricing_mode.py').read_text(encoding='utf-8'))
        valid=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VALID' for t in n.targets))
        self.assertIn('g2g_cheapold',valid)
        self.assertTrue(any(isinstance(n,ast.Import) and any(a.name=='sys' for a in n.names) for n in ast.parse((ROOT/'core_front.py').read_text(encoding='utf-8')).body))
        # Helper main intentionally never runs; no config reads/writes in tests.
    def test_binding_missing_qty_and_amount_isolation(self):
        cfg={'p2pah':{'商品ID映射':{'LAIR_X10':'SYNTH1'}},'商品映射':{'对照项':[{'key':'LAIR_X10','装量':10,'中文名':'Lair Key'}]}}
        drift,checked=gates['detect_binding_drift'](cfg,[],log=lambda *a:None)
        self.assertEqual((checked,drift[0]['level']),(1,'id_gone'))
        drift,_=gates['detect_binding_drift'](cfg,[{'id':'SYNTH1','title':'(1000) Lair Key'}],log=lambda *a:None)
        self.assertIn('qty_changed',[r['level'] for r in drift])
        cfg['商品映射']['对照项'][0].update({'装量':1,'中文名':'10,000 Gold'})
        drift,_=gates['detect_binding_drift'](cfg,[{'id':'SYNTH1','title':'10,000 Gold'}],log=lambda *a:None)
        self.assertFalse(drift)
    def test_matching_pack_not_unit_and_conflicts(self):
        cfg={'商品映射':{'对照项':[{'key':'LAIR_X10','数量':10,'中文名':'Lair Key'},{'key':'LAIR_X1000','数量':1000,'中文名':'Lair Key'}]}}
        self.assertEqual(front['match_key'](cfg,'Lair Key',1000),('LAIR_X1000',True))
        self.assertEqual(front['match_key'](cfg,'Unknown',10),(None,False))
        cfg['商品映射']['对照项'][0]['数量']=1000
        conflicts=[];front['match_key'](cfg,'Lair Key',1000,_conflicts=conflicts);self.assertTrue(conflicts)
    def test_poe2_d4_item_targets_and_no_missing_as_zero(self):
        strategy={'让价百分比':5}
        self.assertAlmostEqual(engine['compute_target']({},strategy,.0159,front_disc=1),.015105)
        self.assertAlmostEqual(engine['compute_target']({},strategy,.0159,front_disc=.9),.016783333333333333)
        self.assertIsNone(engine['compute_target']({},strategy,None))
        self.assertIsNone(engine['margin'](2,None))
    def assert_hold(self,row):
        self.assertIsNone(row['目标前端每M']);self.assertIsNone(row['采购成本_新']);self.assertEqual(row['动作'],'hold')
    def test_invalid_preferred_quote_real_function_composition(self):
        invalid=[None,'not-number','NaN','Infinity','-Infinity',float('nan'),float('inf'),0,-1,True,10**400]
        for value in invalid:
            with self.subTest(value=str(value)):
                offers=[{'username':'a','converted_unit_price':2},{'username':'cheapold','converted_unit_price':value}]
                self.assert_hold(self.plan(offers=offers))
        row=self.plan(offers=[{'username':'a','converted_unit_price':2},{'username':'cheapold','converted_unit_price':'9','min_qty':100}])
        self.assertAlmostEqual(row['目标前端每M'],8.73)
    def test_invalid_base_policy_threshold_cost_fail_closed(self):
        for value in [None,'bad','NaN','Infinity','-Infinity',0,-1,True,10**400]:
            with self.subTest(base=str(value)):self.assert_hold(self.plan(quote=value))
        for value in [None,'bad','NaN','Infinity','-Infinity',True,10**400,1,1.01]:
            with self.subTest(discount=str(value)):self.assert_hold(self.plan(discount=value))
        for extra in [{'成本除数':float('inf')},{'持平阈值':'NaN'},{'持平阈值':'bad'}]:
            with self.subTest(extra=extra):self.assert_hold(self.plan(extra=extra))
        self.assert_hold(self.plan(quote=1e308)) # finite factors overflow when multiplied
        self.assert_hold(self.plan(quote=1e-12)) # rounded procurement cost becomes zero
        self.assertEqual(self.plan(quote='10')['目标前端每M'],9.7)
    def test_zero_discount_whole_plan_and_summary_display(self):
        row=self.plan(discount=0)
        self.assertEqual(row['目标前端每M'],10);self.assertEqual(row['下浮比例'],0)
        self.assertIn('0.0%',row['目标前端每M_口径']);self.assertNotIn('3.0%',row['说明'])
        self.assertEqual(gold['discount_display'](0),0)
        # Existing negative-clamping contract retained; no new finite percentage cap.
        self.assertEqual(self.plan(discount=-.1)['目标前端每M'],10)
        cfg=self.policycfg();cfg['金币']['定价策略']['下浮比例']=0
        app['load_cfg']=lambda:cfg;app['open_db']=lambda:object();app['jsonify']=lambda v:v
        app['core_gold']=types.SimpleNamespace(**gold);app['engine']=types.SimpleNamespace(game_of=lambda *a:'AION2')
        app['store']=types.SimpleNamespace(gold_latest=lambda con:([],None),gold_cost_latest=lambda *a,**k:[],gold_ticket_map=lambda *a:{})
        self.assertIn('0.0%',app['api_gold_cost']()['口径'])
    def test_dispatch_rejects_snapshot_invalid_cost_without_ticket_io(self):
        cfg=self.policycfg();cfg['金币']['服务区']=[{'key':'SYNTH_A','游戏':'AION2','跟价':True}]
        app['load_cfg']=lambda:cfg;app['switch_state']=lambda cfg:{'master':True};app['open_db']=lambda:object();app['core_gold']=types.SimpleNamespace(**gold)
        for value in [None,'bad','NaN','Infinity','-Infinity',0,-1,True,10**400]:
            with self.subTest(value=str(value)):
                app['store']=types.SimpleNamespace(gold_latest=lambda con:([{'key':'SYNTH_A','action':'follow_up','cost_target':value}],None))
                result=app['task_gold_apply'](types.SimpleNamespace(log=lambda *a:None),{'confirm':'确认改价'})
                self.assertEqual(result,{'count':0,'ticket':None})
if __name__=='__main__':unittest.main(verbosity=2)
