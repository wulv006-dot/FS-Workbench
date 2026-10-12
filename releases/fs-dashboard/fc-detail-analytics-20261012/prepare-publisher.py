"""Extend the existing publisher's exact allowlist with this five-file FC scope."""
from pathlib import Path
ROOT=Path(__file__).resolve().parent
base=ROOT.parent/('fs_on_demand_20261012' if (ROOT.parent/'fs_on_demand_20261012').exists() else 'on-demand-20261012')/'native-boundary/release_navigation.py'
text=base.read_text('utf-8')
point="BOUNDARY_SCOPE='fs-on-demand-boundary-20261012'"
assert text.count(point)==1
text=text.replace(point,point+"\nDETAIL_SCOPE='fc-detail-analytics-20261012'\nDETAIL_TARGETS={'fc/'+name:'/opt/fs-exact-range-20261001/'+name for name in ('range_api.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json')}\n",1)
text=text.replace('def expected_files(manifest):','def expected_files(manifest):\n if manifest.get("scope")==DETAIL_SCOPE:return set(DETAIL_TARGETS)',1)
text=text.replace('def target_for(rel):','def target_for(rel):\n if rel in DETAIL_TARGETS:return DETAIL_TARGETS[rel]',1)
point=" protected={x['path']:x['sha256'] for x in manifest['unchangedRequired']}"
assert text.count(point)==1
text=text.replace(point," if manifest.get('scope')==DETAIL_SCOPE:\n  if next(r for r in files if r['candidate']=='fc/range_api.py')['beforeSha256'] is None:raise ValueError('active range baseline required')\n  c=json.loads((stage/'candidate/fc/fc_detail_config.json').read_text())\n  if c['game_id']!=1327 or c['main_site_id']!=266 or c['ai_enabled'] is not False:raise ValueError('FC-only no-AI config required')\n"+point+"\n if manifest.get('scope')==DETAIL_SCOPE and set(protected)&set(DETAIL_TARGETS.values()):raise ValueError('FC target cannot also be unchanged')",1)
text=text.replace('def guards(manifest,root):','def guards(manifest,root):\n if manifest.get("scope")==DETAIL_SCOPE:\n  for target in DETAIL_TARGETS.values():\n   path=rooted(root,target);no_target_link(path)\n   for item in (path,*path.parents):\n    if item.exists():\n     info=item.stat()\n     if info.st_uid!=0 or info.st_gid!=0 or info.st_mode&0o022:raise ValueError("unsafe FC target boundary")\n    if item==root:break',1)
text=text.replace('(CACHE_FIX_SCOPE,BOUNDARY_SCOPE)', '(CACHE_FIX_SCOPE,BOUNDARY_SCOPE,DETAIL_SCOPE)')
text=text.replace('(LIVE_SCOPE,CACHE_FIX_SCOPE,GAMES_SCOPE,DEMAND_SCOPE,BOUNDARY_SCOPE)', '(LIVE_SCOPE,CACHE_FIX_SCOPE,GAMES_SCOPE,DEMAND_SCOPE,BOUNDARY_SCOPE,DETAIL_SCOPE)')
text=text.replace('(QUERY_SCOPE,TRAFFIC_SCOPE,LIVE_SCOPE,CACHE_FIX_SCOPE,GAMES_SCOPE,DEMAND_SCOPE,BOUNDARY_SCOPE)', '(QUERY_SCOPE,TRAFFIC_SCOPE,LIVE_SCOPE,CACHE_FIX_SCOPE,GAMES_SCOPE,DEMAND_SCOPE,BOUNDARY_SCOPE,DETAIL_SCOPE)')
out=ROOT/'deploy/release_navigation.py';out.write_text(text,'utf-8',newline='\n')
candidate=ROOT/'deploy/candidate/fc';candidate.mkdir(parents=True,exist_ok=True)
for name in ('range_api.py','fc_detail.py','fc_detail_model.py','fc_detail_reader.py','fc_detail_config.json'):
 (candidate/name).write_bytes((ROOT/'source'/name).read_bytes())
print('Existing publisher extended for 5 FC files; restart remains range service only.')
