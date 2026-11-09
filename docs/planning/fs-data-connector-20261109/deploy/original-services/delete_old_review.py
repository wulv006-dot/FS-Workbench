"""User-authorized deletion of one old pricing-review residue; no replay or price write."""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys

CID='2e78ccd96e234b6e8573df4d97d5b11e'
TID='25e40b0a9864443f8ecf72fa65f66753'
RUN='run_07185f69c3b7408cb3bbefe476f82898'
REQUEST='fc_pricing_37615cc51ff65ad1903629740ac5fcd9'
EXPECTED='5caddf5eeeeb327d7621cf849be97ab7e3807e6f4e265f0605b5c682ee4e671c'
OWNER_SHA='8786268024326948bef96466ae9950ffa1e8a8fcb449cb23e679e54a129d1661'
DATABASE=Path('/var/lib/fs-hermes-fc/fs/pricing-reviews/conversations.db')
BACKUP=Path('/var/backups/fs-pricing-review-delete-20261109-'+TID)
RELATIONS={'conversations':'id','turns':'id','events':'turn_id','artifacts':'turn_id',
           'actions':'turn_id','synthetic_turn_archives':'turn_id','native_workspace_files':'cid',
           'native_file_exports':'cid','native_collected_runs':'cid','native_conversation_runs':'turn_id',
           'native_pending_sources':'turn_id'}
EXPECTED_COUNTS={name:(74 if name=='events' else 1 if name in ('conversations','turns','native_conversation_runs') else 0) for name in RELATIONS}


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()


def selected(db):
    rows={}
    for table,key in RELATIONS.items():
        ident=CID if table=='conversations' or key in ('cid','conversation_id') else TID
        rows[table]=[dict(r) for r in db.execute('SELECT * FROM '+table+' WHERE '+key+'=?',(ident,))]
    return rows


def verify(db,expected=EXPECTED):
    rows=selected(db)
    if {name:len(value) for name,value in rows.items()}!=EXPECTED_COUNTS:raise ValueError('exact_old_review_counts_changed')
    turn=rows['turns'][0];conversation=rows['conversations'][0];native=rows['native_conversation_runs'][0]
    if (turn['id'],turn['conversation_id'],turn['run_id'],turn['request_id'],turn['state'])!=(TID,CID,RUN,REQUEST,'dispatch_unknown'):
        raise ValueError('original_review_identity_or_state_changed')
    if hashlib.sha256(conversation['owner'].encode()).hexdigest()!=OWNER_SHA:raise ValueError('original_owner_changed')
    if db.execute('SELECT count(*) FROM turns WHERE conversation_id=?',(CID,)).fetchone()[0]!=1:raise ValueError('other_conversation_turns_present')
    binding=json.loads(native['binding'])
    target={'owner':conversation['owner'],'conversation_id':CID,'turn_id':TID,'request_id':REQUEST,
            'run_id':RUN,'session_id':conversation['session_id'],'lease':turn['lease']}
    if native['stopped']!=1 or any(binding.get(k)!=v for k,v in target.items()):raise ValueError('stopped_original_binding_changed')
    if digest(rows)!=expected:raise ValueError('approved_record_CAS_changed')
    return rows


def delete_rows(db,expected=EXPECTED):
    verify(db,expected)
    if db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('events','native_conversation_runs','turns','conversations')").fetchone()[0]:
        raise ValueError('unexpected_delete_trigger_requires_review')
    schema=[tuple(r) for r in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
    sequence=[tuple(r) for r in db.execute('SELECT * FROM sqlite_sequence ORDER BY name')]
    counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in RELATIONS}
    # The approved dependency rows are zero; only these four nonempty exact sets change.
    deleted={}
    for table,key,ident in (('events','turn_id',TID),('native_conversation_runs','turn_id',TID),
                            ('turns','id',TID),('conversations','id',CID)):
        cursor=db.execute('DELETE FROM '+table+' WHERE '+key+'=?',(ident,))
        if cursor.rowcount!=EXPECTED_COUNTS[table]:raise ValueError('exact_deleted_count_mismatch')
        deleted[table]=cursor.rowcount
    if any(selected(db).values()):raise ValueError('target_residue_remains')
    if any(db.execute('SELECT count(*) FROM '+table).fetchone()[0]!=before-deleted.get(table,0) for table,before in counts.items()):
        raise ValueError('unrelated_row_count_changed')
    if schema!=[tuple(r) for r in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')] or sequence!=[tuple(r) for r in db.execute('SELECT * FROM sqlite_sequence ORDER BY name')]:
        raise ValueError('schema_index_or_sequence_changed')
    return deleted


def summary(rows):
    return {'cid':CID,'turn_id':TID,'run_id':RUN,'state':'dispatch_unknown',
            'rows':{k:len(v) for k,v in rows.items()},'selected_record_sha256':digest(rows),'production_writes':0}


def write_receipt(path,value):
    raw=canonical(value)
    with path.open('wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.chmod(path,0o600)


def store_boundary(path=DATABASE):
    # SQLite's existing 0644 file is protected by both 0700 ancestor directories.
    expected=((path,(0,0,0o644,stat.S_IFREG)),
              (path.parent,(0,0,0o700,stat.S_IFDIR)),
              (path.parent.parent,(0,0,0o700,stat.S_IFDIR)),
              (path.parent.parent.parent,(0,9876,0o750,stat.S_IFDIR)))
    for target,(uid,gid,mode,kind) in expected:
        info=target.lstat()
        if (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode),stat.S_IFMT(info.st_mode))!=(uid,gid,mode,kind):
            raise ValueError('existing_private_review_boundary_changed:'+str(target))
        if kind==stat.S_IFREG and info.st_nlink!=1:raise ValueError('review_store_hardlink')


def delete(approved):
    if os.name!='posix' or os.geteuid()!=0 or approved!=EXPECTED:raise ValueError('root_and_exact_user_approved_record_required')
    if BACKUP.exists():raise ValueError('backup_exists_inspect_original_result_do_not_replay')
    for p in (DATABASE,*DATABASE.parents,BACKUP,*BACKUP.parents):
        if p.is_symlink():raise ValueError('linked_backup_or_store_path')
    store_boundary()
    import release
    base=release.frozen();root=Path('/');scope={'scope':base.HERMES_HISTORY_SCOPE}
    # Use original publisher/provider/admission locks; do not use its all-UNKNOWN idle gate to erase this one explicitly approved residue.
    with base.locks(root),base.live_lock(scope,root),base.hermes_admission_fence(scope,root),base.model_release_lock(scope,root):
        with closing(sqlite3.connect(DATABASE.as_uri()+'?mode=rw',uri=True,timeout=3)) as db:
            db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE')
            rows=verify(db)
            BACKUP.mkdir(mode=0o700,parents=False,exist_ok=False)
            # A separate read connection sees the consistent pre-delete database while the reserved write transaction excludes other writers.
            with closing(sqlite3.connect(DATABASE.as_uri()+'?mode=ro',uri=True,timeout=3)) as source,closing(sqlite3.connect(str(BACKUP/'pricing-reviews.sqlite3'))) as saved:
                source.backup(saved)
            os.chmod(BACKUP/'pricing-reviews.sqlite3',0o600)
            receipt=dict(summary(rows),status='backed_up_before_delete',backup=str(BACKUP),
                         backup_sha256=hashlib.sha256((BACKUP/'pricing-reviews.sqlite3').read_bytes()).hexdigest(),
                         at=datetime.now(timezone.utc).isoformat(),reason='direct_user_delete_single_old_pricing_review_residue',
                         restored_output=False,model_requests=0,price_writes=0)
            write_receipt(BACKUP/'receipt.json',receipt)
            try:deleted=delete_rows(db);db.commit()
            except Exception:db.rollback();raise
            receipt.update(status='deleted_single_old_review',deleted_rows=deleted,production_writes=sum(deleted.values()))
            write_receipt(BACKUP/'receipt.json',receipt)
            return {k:v for k,v in receipt.items() if k!='rows'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('preview','delete'))
    parser.add_argument('--approved-record-sha');args=parser.parse_args()
    if args.action=='delete':result=delete(args.approved_record_sha)
    else:
        store_boundary()
        with closing(sqlite3.connect(DATABASE.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.row_factory=sqlite3.Row;result=summary(verify(db))
    print(json.dumps(result,indent=2))
