"""All I/O, job storage, Docker, browser and writer effects are memory mocks."""
import pathlib,sys,importlib.util,types,io,json,os,datetime,ast,textwrap,re,unittest,subprocess
OUT=pathlib.Path(__file__).parent;ROOT=OUT.parent
spec=importlib.util.spec_from_file_location('final_review_harness',OUT/'test_isolated.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
EVIDENCE=[]
class MemoryFS:
    def __init__(self):self.files={}
    def open(self,path,mode='r',encoding=None):
        path=str(path).replace('\\','/');fs=self
        class F(io.StringIO):
            def close(self):
                if 'w' in mode:fs.files[path]=self.getvalue()
                super().close()
        return F('' if 'w' in mode else self.files.get(path,'{}'))
def configure_app(cfg,rows,fs):
    queued=[]
    h.app.update({'load_cfg':lambda:cfg,'switch_state':lambda c:{'master':c.get('_master',True)},'open_db':lambda:object(),
                 'core_gold':types.SimpleNamespace(**h.gold),'ROOT':'/synthetic','dt':datetime,
                 'os':types.SimpleNamespace(path=os.path,makedirs=lambda *a,**k:None),'open':fs.open,
                 '_changelog_write':lambda *a,**k:'/synthetic/noop'})
    def add(con,**kw):
        queued.append({'id':'SYNTHJOB'+str(len(queued)), 'kind':kw['kind'],'plan_json':json.dumps(kw['plan'],allow_nan=False)})
        return queued[-1]['id']
    h.app['store']=types.SimpleNamespace(gold_latest=lambda con:(rows,'SYNTH_SNAPSHOT'),local_job_add=add)
    return queued
def config(dec=6):
    return {'金币':{'采购成本小数位':dec,'定价策略':{'模式':'g2g_cheapold','适用游戏':['AION2'],'下浮比例':0},
                    '服务区':[{'key':'SYNTH_A','游戏':'AION2','跟价':True,'利润率':-.2}]},
            '跟价':{'执行方式':'server','系统开关':True,'缓存刷新':{'自动刷新':False}},'商品映射':{}}
def snap(cost=1,**kw):
    return dict({'key':'SYNTH_A','row_id':'SYNTHROW','title':'Synthetic','action':'follow_up','cost_target':cost,'margin_rate':-.2,'our_per_m':1,'iggm_per_m':2},**kw)
def app_dispatch(cfg,rows,confirm='确认改价'):
    fs=MemoryFS();queued=configure_app(cfg,rows,fs)
    result=h.app['task_gold_apply'](types.SimpleNamespace(log=lambda *a:None),{'confirm':confirm})
    return result,queued,fs
def executor(cfg,job,writer=None):
    ns=h.functions('srv_exec.py');fs=MemoryFS();calls=[];finished=[]
    ns.update({'read_cfg':lambda:cfg,'log':lambda *a:None,'flush_state':lambda:None,'dt':datetime,
               'ROOT':'/synthetic','DATA':'/synthetic/data','SRV':'/synthetic/srv','JOBS':'/synthetic/jobs','CFG':'/synthetic/config.json','CFG_SNAP':'/synthetic/cfg.json','OFF_SWITCH':'/synthetic/off',
               'os':types.SimpleNamespace(path=os.path,exists=lambda *a:False,makedirs=lambda *a,**k:None),'open':fs.open,
               'shutil':types.SimpleNamespace(copyfile=lambda *a:None),'_requeue':lambda *a:None,
               'ST':{'state':'idle','job':None,'kind':None,'done':0,'failed':0,'note':'','ts':'SYNTH_TS'},
               'S':types.SimpleNamespace(connect=lambda *a:object(),local_job_claim_srv=lambda con:job,
                                        local_job_finish=lambda *a,**k:finished.append(k),gold_state_upsert=lambda *a,**k:0)})
    def run(cmd,**kwargs):
        calls.append(cmd)
        if cmd[1]=='info':return types.SimpleNamespace(returncode=0)
        plan=json.loads(fs.files['/synthetic/jobs/'+job['id']+'.json'])
        if writer:
            try:writer(plan,fs)
            except BaseException as exc:
                EVIDENCE.append({'mockFailure':repr(exc)})
                raise
        return types.SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
    ns['subprocess']=types.SimpleNamespace(run=run,TimeoutExpired=subprocess.TimeoutExpired)
    ns['_read_result']=lambda *a:{'ok':True,'jobs':[]}
    result=ns['run_once']()
    return result,calls,finished,fs
WRITER_PATH=ROOT/'docs/planning/d4-live-readonly-audit-20261006/sanitized-live/opt/d4follow/_p2pah_srv/p2pah_local.py'
def writer_function(name):
    text=WRITER_PATH.read_text(encoding='utf-8')
    match=re.search(r'^def '+name+r'\(.*?(?=^def |\Z)',text,re.M|re.S)
    return ast.parse(match.group(0)).body[0]
def mock_container_writer(plan,fs):
    # Use the recorded writer function itself, never import browser/CLI modules.
    # Its source is a sanitized audit copy, not a deployable full writer baseline.
    logs=[]
    ns={'json':json,'dt':datetime,'os':types.SimpleNamespace(path=os.path),
        'io':types.SimpleNamespace(open=fs.open),'time':types.SimpleNamespace(sleep=lambda *a:None),
        'HERE':'/synthetic/results','DEFAULT_CFG':'/synthetic/cfg.json',
        'GOLD_GID':{'AION2':'826','暗黑破坏神4':'456','D4':'456'},'log':lambda *a:logs.append(a),
        'cache_wanted':lambda *a:(False,'synthetic cache disabled'),'_fnum':lambda v:float(v) if v is not None else None}
    for name in ['gold_gid_of','cmd_writegold']:
        node=writer_function(name);exec(compile(ast.Module([node],type_ignores=[]),'recorded-writer-'+name,'exec'),ns)
    costs={};wire=[]
    class Session:
        def __init__(self,*a):pass
        def logged_in(self):return True
        def gold_rows(self,gid):
            return {it['后台行ID']:{'costprice':costs.get(it['后台行ID'],.25),'lirunlv':-.2,'b2c':1} for it in plan['items']}
        def set_gold_cost(self,rid,value):
            wire.append(value);costs[rid]=float(value)
            return {'ok':True,'msg':'synthetic'}
        def sync_gold_price(self,**kw):return {'ok':True,'getweb':'1','allserver':False}
        def log_gold_price(self,**kw):return {'ok':True,'getweb':'0','allserver':False}
        def close(self):pass
    ns['Session']=Session
    fs.files['/synthetic/writerplan.json']=json.dumps(plan,allow_nan=False)
    ns['cmd_writegold'](types.SimpleNamespace(plan='/synthetic/writerplan.json',only=None,profile='SYNTH',show=False,confirm=True))
    EVIDENCE.append({'writerWireValues':wire,'game':plan['游戏'],'synthetic':True,'logs':logs})
    return wire
class Closure(unittest.TestCase):
    def test_raw_front_and_quantity_bool_before_legacy_normalization(self):
        for field in ['num','price_discount']:
            for value in [True,False,'NaN','Infinity',0,-1,10**400]:
                with self.subTest(field=field,value=str(value)):
                    tier={'num':100,'price_discount':100};tier[field]=value
                    self.assertEqual(h.gold['per_m']([tier],100),(None,None))
                    self.assertEqual(h.gold['biggest_tier']([tier]),(None,None,None))
        self.assertIsNone(h.gold['_f'](True));self.assertIsNone(h.gold['_f'](10**400))
    def test_real_front_decoder_does_not_erase_bool(self):
        node=next(n for n in ast.parse((h.ROOT/'core_gold.py').read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='fetch_front_gold')
        node.name='real_front_decoder';exec(compile(ast.Module([node],type_ignores=[]),'front-decoder','exec'),h.gold)
        class Response:
            def __init__(self,payload):self.payload=payload
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self):return json.dumps(self.payload).encode()
        for field in ['num','price_discount']:
            with self.subTest(field=field):
                tier={'num':100,'price':100,'price_discount':100};tier[field]=True
                payload={'goods':{'index':{'list':[{'goods_list':{'100':tier}}]}}}
                h.gold['urllib']=types.SimpleNamespace(parse=h.urllib.parse,request=types.SimpleNamespace(Request=lambda *a,**k:object(),urlopen=lambda *a,**k:Response(payload)))
                tiers=h.gold['real_front_decoder'](config(),'FAKE',game='AION2',log=lambda *a:None)
                self.assertEqual(h.gold['per_m'](tiers,100),(None,None))
    def test_raw_declared_cost_fields_invalid_hold_without_exception(self):
        for field in ['成本除数','汇率','前台系数']:
            for value in [True,False,10**400,'NaN','Infinity']:
                with self.subTest(field=field,value=str(value)):
                    row=h.Synthetic().plan(extra={field:value});self.assertEqual(row['动作'],'hold');self.assertIsNone(row['采购成本_新'])
        self.assertTrue(h.gold['raw_cost_inputs_valid'](config(),{'利润率':-.2},'AION2'))
        self.assertFalse(h.gold['raw_cost_inputs_valid'](config(),{'利润率':True},'AION2'))
    def test_precision_exact_existing_round_and_writer_format(self):
        for dec in [2,6,8,0,-1]:
            for cost in [1e-12,.0000004,.0000005,.00000050001,.000001,.004,.01,50,1.23456789]:
                with self.subTest(dec=dec,cost=cost):
                    expected=round(cost,dec or 6)>0 and float('%.6f'%cost)>0
                    self.assertEqual(h.ng['write_cost'](cost,config(dec)) is not None,expected)
        for raw in [True,False,'NaN','Infinity','bad',2.5,10**400]:
            with self.subTest(precision=str(raw)):self.assertIsNone(h.ng['write_cost'](1,config(raw)))
    def test_actual_dispatch_rechecks_old_tiny_and_bool_snapshot(self):
        for cost in [True,False,1e-12,.0000004,'NaN','Infinity','bad',0,-1,10**400]:
            with self.subTest(cost=str(cost)):
                result,queued,fs=app_dispatch(config(8),[snap(cost)])
                self.assertEqual(result['count'],0);self.assertFalse(queued);self.assertFalse(fs.files)
    def test_full_dispatch_serializes_cost_and_keeps_loss(self):
        result,queued,fs=app_dispatch(config(),[snap(15.4812)])
        payload=json.loads(queued[0]['plan_json'])
        self.assertEqual(result['count'],1);self.assertEqual(payload['items'][0]['利润率'],-.2)
        self.assertEqual(payload['items'][0]['采购成本_新'],15.4812)
        self.assertTrue(h.ng['validate_ticket'](payload,config()))
        self.assertTrue(fs.files)
    def test_dispatch_nonfinite_metadata_does_not_emit_partial_ticket(self):
        fs=MemoryFS();queued=configure_app(config(),[snap(1,iggm_per_m=float('nan'))],fs)
        with self.assertRaises(ValueError):h.app['task_gold_apply'](types.SimpleNamespace(log=lambda *a:None),{'confirm':'确认改价'})
        self.assertFalse(queued);self.assertFalse(fs.files)
    def test_existing_confirm_detect_only_and_switch_gates(self):
        for mode in ['no-confirm','only-detect','off']:
            with self.subTest(mode=mode):
                c=config()
                if mode=='only-detect':c['金币']['服务区'][0]['仅检测']=True
                if mode=='off':c['_master']=False
                if mode=='only-detect':
                    result,q,fs=app_dispatch(c,[snap()]);self.assertFalse(q)
                else:
                    with self.assertRaises(RuntimeError):app_dispatch(c,[snap()],confirm='' if mode=='no-confirm' else '确认改价')
    def test_actual_executor_rejects_stale_plan_before_docker(self):
        for cost in [True,False,1e-12,.0000004,'NaN','Infinity',0,-1]:
            with self.subTest(cost=str(cost)):
                plan={'items':[{'采购成本_新':cost}]}
                result,calls,finished,fs=executor(config(8),{'id':'SYNTHJOB','kind':'writegold','plan_json':json.dumps(plan)})
                self.assertFalse(result);self.assertFalse(calls);self.assertFalse(fs.files);self.assertFalse(finished[0]['ok'])
    def test_supported_app_executor_recorded_writer_closure(self):
        result,q,_=app_dispatch(config(),[snap(15.4812)])
        wire=[]
        def writer(plan,fs):wire.extend(mock_container_writer(plan,fs))
        done,calls,finished,fs=executor(config(),q[0],writer)
        self.assertTrue(done);self.assertEqual(wire,['15.481200']);self.assertTrue(finished[-1]['ok'])
        self.assertEqual(calls[0][1],'info');self.assertIn('writegold',calls[1])
        self.assertTrue(h.ng['write_cost'](float(wire[0]),config()))
    def test_legal_zero_discount_and_loss_real_plan_still_passes(self):
        c=config();sv=dict(c['金币']['服务区'][0],中文名='Synthetic',前端aid='FAKE',大区='EU',g2g_dataset='lgc_12_123')
        h.g2g['scrape_offers']=lambda *a,**k:[{'username':'cheapold','converted_unit_price':2}];h.mod.cheapold_base=h.g2g['cheapold_base']
        ig=types.SimpleNamespace(fetch=lambda *a,**k:{'unit_price':2,'tiers':[{'num':100,'all':200}]})
        row=h.gold['build_plan'](c,log=lambda *a:None,iggm_obj=ig,front_fn=lambda *a:[{'num':100,'price_discount':100}],servers=[sv])['items'][0]
        self.assertEqual(row['目标前端每M'],2);self.assertEqual(row['利润率'],-.2);self.assertEqual(row['动作'],'follow_up')
        self.assertLess(h.engine['margin'](2,row['采购成本_新']/h.gold['rate_of'](c)),0)
        result,q,_=app_dispatch(c,[snap(row['采购成本_新'])]);self.assertEqual(result['count'],1)
        done,calls,finished,fs=executor(c,q[0],mock_container_writer);self.assertTrue(done);self.assertTrue(finished[-1]['ok'])
if __name__=='__main__':
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(h.Synthetic),unittest.defaultTestLoader.loadTestsFromTestCase(Closure)])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    doc=ROOT/'docs/planning/d4-final-guard-review-20261006'
    (doc/'closure-synthetic-evidence.json').write_text(json.dumps(EVIDENCE,ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
