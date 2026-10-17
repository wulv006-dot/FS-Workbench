import ast,copy,hashlib,importlib.util,json,shutil,tempfile,unittest,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('learning_publisher',ROOT/'release_navigation.py');pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub)

class ExactRelease(unittest.TestCase):
 def test_constraints_only_release_reloads_reader_without_worker_restart(self):
  from unittest.mock import patch
  original=pub.restart_for;calls=[];fence=types.SimpleNamespace(stop_then_unlock_database=lambda:calls.append('stop'))
  rows=[dict(target='/opt/fs-hermes-fc/report_constraints.py',beforeSha256='a'*64,sha256='b'*64),dict(target='/opt/fs-hermes-fc/controller.py',beforeSha256='c'*64,sha256='c'*64)]
  with patch.object(pub,'restart_for',lambda m,f=None:calls.append(m['scope'])):
   original(dict(scope=pub.TITLE_GOAL_SCOPE,files=rows),fence)
   self.assertEqual(calls,[pub.LEARNING_RENDER_SCOPE]);calls.clear()
   rows[1]['sha256']='d'*64;original(dict(scope=pub.TITLE_GOAL_SCOPE,files=rows),fence)
   self.assertEqual(calls,['stop',pub.HERMES_WORKER_SCOPE,pub.DEEP_SCOPE])
 def test_runtime_guard_requires_the_controlled_reader_state(self):
  tree=ast.parse((ROOT/'release_navigation.py').read_text('utf8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='guards')
  loop=next(n for n in fn.body if isinstance(n,ast.For) and isinstance(n.target,ast.Tuple))
  code=compile(ast.Module(body=[loop],type_ignores=[]),'runtime-guard','exec')
  def check(scope,stopped,reader='active',other='active'):
   def run(args,**kwargs):return types.SimpleNamespace(stdout='ActiveState='+ (reader if args[2]=='fs-business-range.service' else other)+'\n')
   state=dict(manifest={'scope':scope,'runtimeRequired':{'fs-business-range.service':{'ActiveState':'active'},'fs-hermes-fc.service':{'ActiveState':'active'}}},reader_stopped=stopped,TITLE_GOAL_SCOPE=pub.TITLE_GOAL_SCOPE,re=pub.re,subprocess=types.SimpleNamespace(run=run,PIPE=None))
   exec(code,state)
  check(pub.TITLE_GOAL_SCOPE,False);check(pub.TITLE_GOAL_SCOPE,True,'inactive')
  for scope,stopped,reader,other in ((pub.TITLE_GOAL_SCOPE,False,'inactive','active'),(pub.TITLE_GOAL_SCOPE,True,'active','active'),(pub.TITLE_GOAL_SCOPE,True,'inactive','inactive'),(pub.LEARNING_SCOPE,True,'inactive','active')):
   with self.assertRaises(ValueError):check(scope,stopped,reader,other)
 def test_report_release_stops_old_reader_before_replacing_sources(self):
  tree=ast.parse((ROOT/'release_navigation.py').read_text('utf8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='apply')
  loop=next(n for n in ast.walk(fn) if isinstance(n,ast.For) and isinstance(n.iter,ast.Name) and n.iter.id=='ordered')
  guard=next(n for n in ast.walk(fn) if isinstance(n,ast.If) and n.lineno<loop.lineno and any(isinstance(x,ast.Attribute) and x.attr=='stop_then_unlock_database' for x in ast.walk(n)))
  calls=[];scope=dict(TITLE_GOAL_SCOPE=pub.TITLE_GOAL_SCOPE,admission_fence=types.SimpleNamespace(stop_then_unlock_database=lambda:calls.append('stopped')))
  code=compile(ast.Module(body=[guard],type_ignores=[]),'report-release-fence','exec')
  for name,want in ((pub.LEARNING_SCOPE,[]),(pub.TITLE_GOAL_SCOPE,['stopped'])):
   calls.clear();scope['manifest']={'scope':name};exec(code,scope);self.assertEqual(calls,want)
 def test_exact_files_and_new_method_only(self):
  with tempfile.TemporaryDirectory() as tmp:
   stage=Path(tmp);rows=[]
   for relative,target in pub.LEARNING_TARGETS.items():
    dest=stage/'candidate'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,dest)
    rows.append(dict(candidate=relative,target=target,sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),beforeSha256=None if relative.endswith('.md') else 'a'*64))
   protected=set(pub.HERMES_TARGETS.values())|{'/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')}
   protected|={'/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py'}
   protected-=set(pub.LEARNING_TARGETS.values())
   manifest={'schemaVersion':1,'scope':pub.LEARNING_SCOPE,'files':rows,'businessWrites':False,'timersChanged':False,
             'unchangedRequired':[{'path':p,'sha256':'b'*64} for p in protected],
             'runtimeRequired':{'fs-business-range.service':{'ActiveState':'active'},'fs-hermes-fc.service':{'ActiveState':'active'}},
             'imageId':'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'}
   pub.validate(manifest,stage)
   render=copy.deepcopy(manifest);render['scope']=pub.LEARNING_RENDER_SCOPE
   render['files']=[r for r in rows if r['candidate'] in pub.LEARNING_RENDER_TARGETS]
   render['unchangedRequired'] += [{'path':r['target'],'sha256':'b'*64} for r in rows if r['candidate'] not in pub.LEARNING_RENDER_TARGETS]
   pub.validate(render,stage)
   acceptance=copy.deepcopy(manifest);acceptance['scope']=pub.LEARNING_ACCEPTANCE_SCOPE
   acceptance['files']=[r for r in acceptance['files'] if r['candidate'] in pub.LEARNING_ACCEPTANCE_TARGETS]
   extra='source/report_constraints.py';dest=stage/'candidate'/extra;shutil.copyfile(ROOT/extra,dest)
   acceptance['files'].append(dict(candidate=extra,target=pub.LEARNING_ACCEPTANCE_TARGETS[extra],sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),beforeSha256='a'*64))
   acceptance['unchangedRequired']=[r for r in acceptance['unchangedRequired'] if r['path']!=pub.LEARNING_ACCEPTANCE_TARGETS[extra]]
   for r in acceptance['files']:r['beforeSha256']='a'*64
   acceptance['unchangedRequired'] += [{'path':r['target'],'sha256':'b'*64} for r in rows if r['candidate'] not in pub.LEARNING_ACCEPTANCE_TARGETS]
   pub.validate(acceptance,stage)
   bad=copy.deepcopy(manifest);bad['files'][0]['target']='/opt/fc27-cloud/price_writer.py'
   with self.assertRaises(ValueError):pub.validate(bad,stage)
   bad=copy.deepcopy(manifest);bad['files'].pop()
   with self.assertRaises(ValueError):pub.validate(bad,stage)
   bad=copy.deepcopy(manifest);bad['files'][0]['beforeSha256']=None
   with self.assertRaises(ValueError):pub.validate(bad,stage)

 def test_title_goal_release_is_exact_and_rejects_unrelated_target(self):
  with tempfile.TemporaryDirectory() as tmp:
   stage=Path(tmp);rows=[]
   for relative,target in pub.TITLE_GOAL_TARGETS.items():
    dest=stage/'candidate'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,dest)
    rows.append(dict(candidate=relative,target=target,sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),beforeSha256='a'*64))
   protected=set(pub.HERMES_TARGETS.values())|{'/opt/fs-exact-range-20261001/'+n for n in ('boss_insights.py','fc_deep_model.py','fc_daily.py','fc_daily_model.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json','fc_deep_sources.py','summary_bridge.py')}
   protected|={'/var/www/dashboard/index.html','/var/www/dashboard/fs-home/index.html','/var/www/dashboard/fs-home/navigation.js','/opt/fs-access-policy/access_policy.py'}
   protected-=set(pub.TITLE_GOAL_TARGETS.values())
   m={'schemaVersion':1,'scope':pub.TITLE_GOAL_SCOPE,'files':rows,'businessWrites':False,'timersChanged':False,
      'unchangedRequired':[{'path':p,'sha256':'b'*64} for p in protected],
      'runtimeRequired':{'fs-business-range.service':{'ActiveState':'active'},'fs-hermes-fc.service':{'ActiveState':'active'}},
      'imageId':'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'}
   pub.validate(m,stage);bad=copy.deepcopy(m);bad['files'][0]['target']='/opt/fc27-cloud/price_writer.py'
   with self.assertRaises(ValueError):pub.validate(bad,stage)

if __name__=='__main__':unittest.main()
