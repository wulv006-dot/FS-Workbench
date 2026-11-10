"""Prepare the existing shared sidebar release on the host; export metadata only."""
from pathlib import Path
import copy,hashlib,json,re,sys

ENTRY=dict(id='campaign-weekly',label='FC27 周更运营台',path='/dashboard/analytics/campaigns/analytics/weekly.html',icon='◷',short='自动取品、草稿预览、人工确认与周更记录',requiredGroup='dashboard',section='activities')
TARGETS={
 'hubnav.js':'/var/www/hub/hubnav.js','nav.js':'/var/www/hub/nav.js',
 'z-main.conf':'/etc/nginx/conf.d/iggm-web.conf','zz-formal.conf':'/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf',
 'home.html':'/var/www/dashboard/fs-home/index.html','analytics.html':'/var/www/dashboard/modules/analytics/index.html',
 'hermes.html':'/var/www/dashboard/modules/hermes/index.html','sports.html':'/var/www/dashboard/modules/sports/index.html',
 'arpg.html':'/var/www/dashboard/modules/arpg/index.html','bots.html':'/var/www/dashboard/modules/bots/index.html',
 'collaboration.html':'/var/www/dashboard/modules/collaboration/index.html','about.html':'/var/www/dashboard/modules/about/index.html',
 'report.html':'/var/www/dashboard/fs-home/brain/index.html','conversation.html':'/var/www/dashboard/fs-home/hermes/conversation/index.html',
 'tasks.html':'/var/www/dashboard/tasks/index.html','fc-coins.html':'/var/www/dashboard/fc27-coins.html',
 'navigation.json':'/var/www/dashboard/fs-home/navigation.json','module-registry.json':'/var/www/dashboard/fs-home/module-registry.json'}
sha=lambda raw:hashlib.sha256(raw).hexdigest()
encode=lambda value:(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()

def add_entry(registry):
 result=copy.deepcopy(registry)
 existing=[t for t in result['tools'] if t['id']==ENTRY['id'] or t['path']==ENTRY['path']]
 if existing:
  if existing!=[ENTRY]:raise ValueError('weekly_entry_conflict')
 else:result['tools'].append(copy.deepcopy(ENTRY))
 if 'sections' in result:
  section=next(s for s in result['sections'] if s['id']=='activities')
  if section['ids'].count(ENTRY['id'])>1:raise ValueError('duplicate_weekly_entry')
  if ENTRY['id'] not in section['ids']:section['ids'].append(ENTRY['id'])
 return result

def patch_script(text,old,new):
 matches=list(re.finditer(r'const registry=(.*);\r?\n',text))
 if len(matches)!=1 or json.loads(matches[0][1])!=old:raise ValueError('live_navigation_registry_drift')
 m=matches[0];value=json.dumps(new,ensure_ascii=False,separators=(',',':'))
 return text[:m.start(1)]+value+text[m.end(1):]

def prepare(stage):
 stage=Path(stage);candidate=stage/'candidate'
 if candidate.exists():raise ValueError('new_candidate_directory_required')
 candidate.mkdir(parents=True,mode=0o700)
 old=json.loads(Path(TARGETS['navigation.json']).read_bytes());new=add_entry(old)
 if old==new:raise ValueError('weekly_entry_already_installed')
 version='fc27-weekly-nav-20261109-'+sha(encode(new))[:12]
 rows=[];references={}
 for name,target in TARGETS.items():
  path=Path(target)
  if not path.is_file() or path.is_symlink():raise ValueError('invalid_navigation_source:'+name)
  raw=path.read_bytes()
  if name in ('hubnav.js','nav.js'):result=patch_script(raw.decode(),old,new).encode()
  elif name in ('navigation.json','module-registry.json'):result=encode(add_entry(json.loads(raw)))
  else:
   text,count=re.subn(r'((?:hubnav|nav)\.js\?v=)[A-Za-z0-9_-]+',lambda m:m[1]+version,raw.decode())
   if not count:raise ValueError('navigation_reference_missing:'+name)
   references[name]=count;result=text.encode()
  if result==raw:raise ValueError('unchanged_navigation_target:'+name)
  (candidate/name).write_bytes(result)
  rows.append(dict(candidate=name,target=target,beforeSha256=sha(raw),sha256=sha(result)))
 protected='/var/www/dashboard/index.html'
 manifest=dict(schemaVersion=1,scope='traffic-source-tabs-ui-finish-20261019',releaseReady=True,businessWrites=False,timersChanged=False,runtimeRequired={'nginx.service':{'ActiveState':'active'},'fs-marketing-range.service':{'ActiveState':'active'}},unchangedRequired=[dict(path=protected,sha256=sha(Path(protected).read_bytes()))],files=rows)
 (stage/'manifest.json').write_bytes(encode(manifest));(stage/'targets.json').write_bytes(encode(TARGETS))
 return dict(version=version,files=len(rows),manifest_sha=sha((stage/'manifest.json').read_bytes()),references=references,entry=ENTRY,source_hashes={r['candidate']:r['beforeSha256'] for r in rows})

if __name__=='__main__':print(json.dumps(prepare(sys.argv[1]),ensure_ascii=False,indent=2))
