"""Read native pending provenance; reuse the original Codex review/apply ledger."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import textwrap


DB_PATH = Path('/var/lib/fs-hermes-fc/fs/conversations/conversations.db')
PROFILE_BASE = PurePosixPath('/var/lib/fs-hermes-fc/native/profiles')
BINDING_FIELDS = {'owner', 'conversation_id', 'turn_id', 'request_id', 'session_id', 'lease', 'run_id'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def identifier(value):
    return type(value) is str and 1 <= len(value) <= 256 and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def load_scope(path, owner, session_id=None):
    if not identifier(owner) or (session_id is not None and not identifier(session_id)):
        raise ValueError('native_review_identity')
    key = hashlib.sha256(owner.encode('utf-8')).hexdigest()
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise OSError('native_review_database_unavailable')
    try:
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON')
            rows = db.execute('SELECT p.*,n.binding FROM native_pending_sources p '
                              'LEFT JOIN native_conversation_runs n ON n.turn_id=p.turn_id WHERE p.owner=?', (owner,)).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        raise OSError('native_review_database_unavailable') from None
    sources = []
    for row in rows:
        item = dict(row)
        try:
            binding = json.loads(item.pop('binding'))
            if (type(binding) is not dict or set(binding) != BINDING_FIELDS or
                    not all(identifier(v) for v in binding.values()) or
                    tuple(binding[k] for k in ('owner', 'conversation_id', 'turn_id', 'session_id', 'run_id', 'lease')) !=
                    tuple(item[k] for k in ('owner', 'cid', 'turn_id', 'session_id', 'run_id', 'lease')) or
                    item['profile_key'] != key or item['subsystem'] not in ('memory', 'skills') or
                    not re.fullmatch(r'[a-f0-9]{8}', item['pending_id']) or
                    not re.fullmatch(r'[a-f0-9]{64}', item['record_sha256'])):
                raise ValueError('native_review_source_binding')
        except (TypeError, KeyError, ValueError):
            raise ValueError('native_review_source_binding') from None
        if session_id is None or item['session_id'] == session_id:
            sources.append(item)
    return dict(owner=owner, profile_key=key, profile_root=str(PROFILE_BASE / key),
                session_id=session_id, sources=sources)


def bind_source(scope, source, record):
    if (type(source) is not dict or source not in scope['sources'] or
            source.get('owner') != scope['owner'] or source.get('profile_key') != scope['profile_key'] or
            type(record) is not dict or record.get('id') != source['pending_id'] or
            record.get('subsystem') != source['subsystem'] or digest(record) != source['record_sha256']):
        raise ValueError('native_review_candidate_changed_or_unmapped')
    return source


LIST = '''
native=[];skills=[];unmapped=[]
for subsystem,kind in ((wa.MEMORY,'native'),(wa.SKILLS,'skill')):
 for record in wa.list_pending(subsystem):
  source=next((s for s in NATIVE_SCOPE['sources'] if s['subsystem']==subsystem and s['pending_id']==record['id'] and s['record_sha256']==digest(record)),None)
  if source is None:
   unmapped.append(dict(id=kind+':'+record['id'],subsystem=subsystem,status='unmapped_pending'))
   continue
  if kind=='native':
   candidate=dict(id='native:'+record['id'],record=record,sha256=digest(record),native_source=source)
   try:candidate['target_sha256']=filesha(memory_target(record['payload']))
   except ValueError:
    candidate.update(validation_error='native_review_memory_target',target_sha256=digest(dict(blocked='native_review_memory_target')))
   native.append(candidate)
  else:
   candidate=skill_candidate(record,sm);candidate['native_source']=source;skills.append(candidate)
print(json.dumps(dict(native=native,skills=skills,experiences=[],unmapped=unmapped,
 owner=NATIVE_SCOPE['owner'],profile_root=NATIVE_SCOPE['profile_root'],
 memory_gate_enabled=wa.write_approval_enabled(wa.MEMORY),skills_gate_enabled=wa.write_approval_enabled(wa.SKILLS)),ensure_ascii=True))
'''

MEMORY = '''
record=wa.get_pending(wa.MEMORY,DATA['id'].split(':')[1])
assert record is not None and digest(record)==DATA['expected_sha'],'candidate_changed'
payload=record['payload']
if DATA['decision']=='reject':
 assert wa.discard_pending(wa.MEMORY,record['id']),'pending_discard_failed'
 result=dict(success=True,applied=False,rejected=True)
else:
 assert wa.write_approval_enabled(wa.MEMORY) is True,'native_memory_gate_not_enabled'
 target=memory_target(payload);assert filesha(target)==DATA['target_sha'],'target_changed'
if DATA['decision']!='reject' and payload.get('action')=='core_compaction':
 from tools.memory_tool import _scan_memory_content
 from utils import atomic_write_text
 store=load_on_disk_store();new=payload['content'];limit=store._char_limit(payload['target'])
 assert payload['base_sha256']==DATA['target_sha'],'core_base_changed'
 assert 0<len(new)<=limit and not _scan_memory_content(new),'core_limit_or_content_scan'
 assert filesha(target)==DATA['target_sha'],'core_base_changed'
 atomic_write_text(Path(target),new,tmp_prefix='.codex_curate_')
 assert wa.discard_pending(wa.MEMORY,record['id']),'applied_pending_cleanup_failed_inspect_receipt'
 result=dict(success=True,applied=True,after_sha256=filesha(target),characters=len(new),limit=limit)
elif DATA['decision']!='reject':
 assert payload.get('action') in ('add','replace','remove','batch'),'unsupported_native_payload'
 result=apply_memory_pending(payload,load_on_disk_store())
 result['applied']=result.get('success') is True;result['after_sha256']=filesha(target)
 if result.get('success'):assert wa.discard_pending(wa.MEMORY,record['id']),'applied_pending_cleanup_failed_inspect_receipt'
print(json.dumps(result,ensure_ascii=True))
'''

SNAPSHOT = '''
import base64
record=wa.get_pending(wa.MEMORY,DATA['id'].split(':')[1])
assert record is not None and digest(record)==DATA['expected_sha'],'candidate_changed'
try:target=memory_target(record['payload'])
except ValueError:
 assert DATA['decision']=='reject' and DATA['target_sha']==digest(dict(blocked='native_review_memory_target')),'unsafe_memory_approval'
 print(json.dumps(dict(validation_error='native_review_memory_target'),ensure_ascii=True))
else:
 assert filesha(target)==DATA['target_sha'],'target_changed'
 print(json.dumps(dict(path=str(target),exists=Path(target).is_file(),sha256=filesha(target),
  bytes_base64=base64.b64encode(Path(target).read_bytes() if Path(target).is_file() else b'').decode()),ensure_ascii=True))
'''


def worker_script(code, data, scope, header, helpers):
    expected = str(PROFILE_BASE / hashlib.sha256(scope['owner'].encode()).hexdigest())
    if scope['profile_root'] != expected:
        raise ValueError('native_review_profile_path')
    prelude = ('from pathlib import Path\nfrom hermes_constants import set_hermes_home_override, reset_hermes_home_override\n'
               'NATIVE_SCOPE=' + repr(scope) + '\n'
               '_native_home_token=set_hermes_home_override(Path(NATIVE_SCOPE["profile_root"]))\n')
    native_helpers = '''
from tools import skill_manager_tool as sm
def memory_target(payload):
 if payload.get('target','memory') not in ('memory','user'):raise ValueError('native_review_memory_target')
 target=Path(NATIVE_SCOPE['profile_root'])/'memories'/('USER.md' if payload.get('target')=='user' else 'MEMORY.md')
 for directory in (Path(NATIVE_SCOPE['profile_root']),target.parent,target):
  if directory.is_symlink():raise ValueError('native_review_memory_symlink')
 return target
def filesha(path):
 path=Path(path)
 if path.is_symlink() or (path.exists() and not path.is_file()):raise ValueError('native_review_nonregular_target')
 return hashlib.sha256(path.read_bytes() if path.is_file() else b'').hexdigest()
'''
    body = header + '\n' + helpers + '\n' + native_helpers + '\nDATA=' + repr(data or {}) + '\n' + code
    return prelude + 'try:\n' + textwrap.indent(body, ' ') + '\nfinally:\n reset_hermes_home_override(_native_home_token)\n'
