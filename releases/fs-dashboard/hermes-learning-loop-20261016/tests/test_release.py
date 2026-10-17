import copy,hashlib,importlib.util,json,shutil,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('learning_publisher',ROOT/'release_navigation.py');pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub)

class ExactRelease(unittest.TestCase):
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

if __name__=='__main__':unittest.main()
