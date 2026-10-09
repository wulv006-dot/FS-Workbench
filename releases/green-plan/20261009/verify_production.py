"""Read-only production checks; never supplies a cookie or backend identity."""
import argparse,contextlib,json,sqlite3,ssl,urllib.request,urllib.error,urllib.parse
from pathlib import Path
import release_navigation as r
p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--backup',type=Path,required=True);a=p.parse_args()
m=json.loads(a.manifest.read_text());j=json.loads((a.backup/'journal.json').read_text());r.guards(m,Path('/'));r.retirement(Path('/'))
assert all(r.digest(Path(row['target']))==row['sha256'] for row in m['files'])
assert r.db_state(Path('/'))==j['databaseBefore'],'Existing database state differs'
with contextlib.closing(sqlite3.connect('file:/opt/mmoexp-taskboard/data/taskboard.db?mode=ro',uri=True)) as conn:
 rows=[json.loads(row[0]) for row in conn.execute('SELECT data FROM green_plan_tasks')]
 events=conn.execute('SELECT count(*) FROM green_plan_events').fetchone()[0]
 assert len(rows)==50 and events==0
 assert all(x['status']=='todo' and x['progress']==0 and not x['assignee'] and not x.get('acceptedAt') for x in rows)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
checks=[]
for path in ('/dashboard/tasks/green-plan/','/dashboard/tasks/api/green-plan'):
 for spoof in (False,True):
  req=urllib.request.Request('https://127.0.0.1'+path,headers={'X-Auth-User':'wulv','X-Auth-Role':'admin','X-Auth-Groups':'dashboard'} if spoof else {})
  try:response=opener.open(req,timeout=10);status=response.status;location=response.headers.get("Location","");response.close()
  except urllib.error.HTTPError as error:status=error.code;location=error.headers.get("Location","");error.close()
  assert status in (301,302,303,307,308,401,403),(path,spoof,status)
  if status<400:assert urllib.parse.urlsplit(location).path.startswith('/__auth/'),('Unexpected redirect',path,location)
  checks.append(dict(path=path,forgedHeader=spoof,status=status,denied=True))
print(json.dumps(dict(targetSHA='10/10',protectedSHA=len(m['unchangedRequired']),oldDatabase='unchanged',greenTasks=50,initialTodo=50,unassigned=50,accepted=0,events=events,http=checks,realRoleBrowser='not tested'),ensure_ascii=False,indent=2))
