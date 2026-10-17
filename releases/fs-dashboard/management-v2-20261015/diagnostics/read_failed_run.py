"""Read the latest management acceptance run through the existing service reader.
No raw prompt, credential, model reasoning or report data is printed.
"""
import json,re,sqlite3,sys
from pathlib import Path
from types import SimpleNamespace
sys.path[:0]=['/opt/fs-hermes-fc','/opt/fs-exact-range-20261001']
from controller import HermesService
with sqlite3.connect('file:/var/lib/fs-hermes-fc/fs/tasks.sqlite3?mode=ro',uri=True) as db:
 row=db.execute("SELECT r.id,r.state,t.run_id FROM requests r JOIN tasks t ON t.id=r.task_id WHERE r.body LIKE ? ORDER BY r.rowid DESC LIMIT 1",('%经营管理台日更%',)).fetchone()
if not row or not re.fullmatch(r'run_[a-f0-9]{32}',row[2] or ''):raise SystemExit('no_bound_management_run')
status,value=HermesService.remote(SimpleNamespace(run_root=Path('/run/fs-hermes-fc')),'GET','/v1/runs/'+row[2])
error=str(value.get('error') or '')
known=('task_context_identity_changed','admission_handshake_timeout','context_window_configuration_mismatch','unexpected_context_compressor','admission_report_mode','admission_invalid','session_not_admitted','skill_changed','skill_authority','runtime_tool_contract_mismatch')
print(json.dumps({'request_id':row[0],'request_state':row[1],'run_id':row[2],'http_status':status,'runtime_status':value.get('status'),'known_error_codes':[x for x in known if x in error],'error_classes':re.findall(r'\b[A-Za-z]+Error\b',error),'error_length':len(error)},ensure_ascii=False))
