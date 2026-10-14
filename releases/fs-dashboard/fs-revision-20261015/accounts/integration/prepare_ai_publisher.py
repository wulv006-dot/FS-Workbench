"""Add the coordinated 20-target AI scope to the derived account publisher.

Produces inert code and a patch; no Git or production operations.
"""
import difflib
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / 'deploy/release_navigation.py'
original = BASE.read_text(encoding='utf-8')
text = original


def replace(old, new, count=1):
    global text
    if text.count(old) != count:
        raise ValueError('publisher context changed: ' + old[:80])
    text = text.replace(old, new)


def edit_function(name, old, new, count=1):
    global text
    found = re.search(r'(?ms)^def ' + re.escape(name) + r'\(.*?(?=^def |^class |^@contextlib.contextmanager|\Z)', text)
    if not found or found.group().count(old) != count:
        raise ValueError('publisher function changed: ' + name)
    text = text[:found.start()] + found.group().replace(old, new) + text[found.end():]


definition = """AI_REVISION_SCOPE='fs-revision-ai-20261015'
AI_REVISION_TARGETS={
 **{'revision-ai/range/'+name:'/opt/fs-exact-range-20261001/'+name for name in ('fc_daily.py','fc_daily_model.py','ai_advisor_model.py','ai_advisor.py','fc_detail.py','range_api.py','profit_queries.py','fs_cleanup.py')},
 **{'revision-ai/boss/'+name:'/opt/fs-boss-workspaces/backend/'+name for name in ('boss_daily.py','game_intelligence.py','management_daily.py','workspace_official_model.py')},
 **{'revision-ai/hermes/'+name:'/opt/fs-hermes-fc/'+name for name in ('report_artifacts.py','boss_projection.py','boss_renderer.py','report.template.html')},
 **{'revision-ai/knowledge/'+name:'/opt/fs-hermes-fc/assets/'+name for name in ('knowledge-derived.md','knowledge-derived.json')},
 **{'revision-ai/units/'+name:'/etc/systemd/system/'+name for name in ('fs-maintenance-cleanup.service','fs-maintenance-cleanup.timer')},
}
AI_REVISION_NEW={'revision-ai/range/fs_cleanup.py','revision-ai/boss/workspace_official_model.py','revision-ai/hermes/boss_projection.py','revision-ai/hermes/boss_renderer.py','revision-ai/hermes/report.template.html','revision-ai/units/fs-maintenance-cleanup.service','revision-ai/units/fs-maintenance-cleanup.timer'}
AI_REVISION_BOSS_UNITS=('fs-boss-game-monitor.service','fs-boss-management.service')
AI_REVISION_CLEAN_UNITS=('fs-maintenance-cleanup.service','fs-maintenance-cleanup.timer')
"""
replace("QUERY_SCOPE='fs-internal-query-api-20261009'", definition + "QUERY_SCOPE='fs-internal-query-api-20261009'")
replace('def expected_files(manifest):', "def expected_files(manifest):\n if manifest.get('scope')==AI_REVISION_SCOPE:return set(AI_REVISION_TARGETS)")
replace('def target_for(rel):', 'def target_for(rel):\n if rel in AI_REVISION_TARGETS:return AI_REVISION_TARGETS[rel]')
replace("  if manifest.get('scope')==ACCOUNT_SCOPE and rel!=", "  if manifest.get('scope')==AI_REVISION_SCOPE and rel not in AI_REVISION_NEW and row.get('beforeSha256') is None:raise ValueError('existing AI revision baseline required')\n  if manifest.get('scope')==ACCOUNT_SCOPE and rel!=")
replace(" if manifest.get('scope')==ACCOUNT_SCOPE and manifest.get('runtimeRequired',{}).get('auth-portal.service')", " if manifest.get('scope')==AI_REVISION_SCOPE:\n  if manifest.get('runtimeRequired',{}).get('fs-business-range.service')!={'ActiveState':'active'} or manifest.get('cleanupActivationDuringRelease') is not False:raise ValueError('active range and deferred cleanup activation required')\n  service=(stage/'candidate/revision-ai/units/fs-maintenance-cleanup.service').read_text()\n  timer=(stage/'candidate/revision-ai/units/fs-maintenance-cleanup.timer').read_text()\n  if [line for line in service.splitlines() if line.startswith('ExecStart=')]!=['ExecStart=/opt/python39/bin/python3 -B /opt/fs-exact-range-20261001/fs_cleanup.py --apply']:raise ValueError('exact deferred cleanup service required')\n  if not all(line in timer.splitlines() for line in ('OnCalendar=*-*-* 06:30:00','Persistent=false','Unit=fs-maintenance-cleanup.service')):raise ValueError('exact nonpersistent cleanup timer required')\n if manifest.get('scope')==ACCOUNT_SCOPE and manifest.get('runtimeRequired',{}).get('auth-portal.service')")
replace("OnCalendar=*-*-* 06:30:00'", "OnCalendar=*-*-* 06:30:00 Asia/Shanghai'")
helper = """def revision_units_inactive(units):
 for unit in units:
  result=subprocess.run(['systemctl','show',unit,'--no-pager','-p','ActiveState','-p','UnitFileState','-p','LoadState','-p','MainPID'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
  props=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
  allowed=props.get('ActiveState') in ('inactive','failed') if unit in AI_REVISION_BOSS_UNITS else props.get('ActiveState')=='inactive'
  if not allowed or (unit.endswith('.service') and props.get('MainPID')!='0') or (unit in AI_REVISION_CLEAN_UNITS and props.get('UnitFileState') in ('enabled','enabled-runtime')) or (result.returncode and props.get('LoadState')!='not-found'):raise ValueError('active/enabled revision consumer; defer update: '+unit)

def revision_ai_quiescent(root):
 revision_units_inactive(AI_REVISION_BOSS_UNITS+AI_REVISION_CLEAN_UNITS)
 hermes_quiescent(root)
 for name in ('advisor/advisor.sqlite3','fc-daily/daily.sqlite3'):
  database=rooted(root,'/var/lib/fs-business-ranges/'+name);no_target_link(database)
  if not database.is_file():raise ValueError('existing AI job database missing')
  with contextlib.closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
   if db.execute("SELECT count(*) FROM jobs WHERE state IN ('pending','running')").fetchone()[0]:raise ValueError('active/unknown old AI report; preserve history and reconcile original ID before update')

"""
replace('def guards(manifest,root):', helper + "def guards(manifest,root):\n if manifest.get('scope')==AI_REVISION_SCOPE:revision_ai_quiescent(root)")
edit_function('guards', 'HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE)', 'HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE)', count=2)
edit_function('guards', "for target in (HERMES_NIGHT_TARGETS if", "for target in (AI_REVISION_TARGETS if manifest.get('scope')==AI_REVISION_SCOPE else HERMES_NIGHT_TARGETS if")
edit_function('live_lock', 'HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE)', 'HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE)')
edit_function('hermes_admission_fence', 'HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE)', 'HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE)')
edit_function('model_release_lock', 'HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE)', 'HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE)', count=2)
replace('def restart_for(manifest,admission_fence=None):', "def restart_for(manifest,admission_fence=None):\n if manifest.get('scope')==AI_REVISION_SCOPE:\n  if admission_fence is None:raise ValueError('AI revision requires Hermes admission fence')\n  revision_ai_quiescent(admission_fence.root)\n  subprocess.run(['systemctl','daemon-reload'],check=True)\n  revision_units_inactive(AI_REVISION_CLEAN_UNITS)\n  admission_fence.stop_then_unlock_database()\n  restart_for(dict(manifest,scope=DEEP_SCOPE))\n  return")
edit_function('apply', 'HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE)', 'HERMES_NIGHT_SCOPE,HERMES_CAPABILITY_SCOPE,AI_REVISION_SCOPE)', count=2)
output = HERE / 'release_navigation.py'
with output.open('w', encoding='utf-8', newline='\n') as stream:
    stream.write(text)
(HERE / 'ai-publisher.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True), text.splitlines(True), fromfile='account-derived/release_navigation.py', tofile='combined/release_navigation.py')), encoding='utf-8')
(HERE / 'derivation.json').write_text(json.dumps({'base': '../deploy/release_navigation.py', 'base_sha256': hashlib.sha256(BASE.read_bytes()).hexdigest(), 'original_active_publisher_sha256': 'e0c8db6ad0e4b732593f72494980e62f55adee88c8ae5c446a9f76c8c834dc95', 'candidate_sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'scope': 'fs-revision-ai-20261015', 'targets':20, 'new_targets':7, 'cleanup_activation':'deferred; never enabled or started by publisher', 'worker_restart':False, 'status':'inert-candidate-needs-final-main-source-map-and-Linux-QA'}, indent=2), encoding='utf-8')
print(json.dumps({'targets':20,'new_targets':7,'cleanupActivationDuringRelease':False,'business_mutations':0}))
