"""Opt-in frozen masked projections and signed ordinal keyset pages.

Build from the already-computed private result, never from a page/cache MISS.
All rows remain derived; original facts, revisions, recipes and algorithms survive.
"""
import hashlib,hmac,json
from user_contract import canonical,digest


class IndexUnavailable(RuntimeError):pass


def mac(store,value):return hmac.new(store.key,canonical(value).encode(),'sha256').hexdigest()


def initialize(store):
    with store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS member_projection_bodies(ref TEXT PRIMARY KEY,body TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS member_projection_groups(snapshot TEXT,grp TEXT,body TEXT,signature TEXT,PRIMARY KEY(snapshot,grp))')
        db.execute('CREATE TABLE IF NOT EXISTS member_projection_rows(snapshot TEXT,grp TEXT,ordinal INTEGER,cid TEXT,ref TEXT,repeated INTEGER,kind TEXT,signature TEXT,PRIMARY KEY(snapshot,grp,ordinal))')
        db.execute('CREATE INDEX IF NOT EXISTS member_projection_repeat ON member_projection_rows(snapshot,grp,repeated,ordinal)')
        db.execute('CREATE INDEX IF NOT EXISTS member_projection_kind ON member_projection_rows(snapshot,grp,kind,ordinal)')
        db.execute('CREATE INDEX IF NOT EXISTS member_projection_both ON member_projection_rows(snapshot,grp,repeated,kind,ordinal)')


def classification(record):
    repeated=record.get('period_repeated')
    repeated=1 if repeated is True else 0 if repeated is False else -1
    kind=record.get('period_entry_customer_type')
    kind='unknown' if kind in ('unknown','conflict') else kind if kind in ('new','old') else 'other'
    return repeated,kind


def build(store,public,private):
    sid=public['snapshot_id'];query,_=store.snapshot_public(sid);token=store.snapshot_token(sid)
    private_hash=digest({k:v for k,v in private.items() if k!='events'});query_hash=digest(query)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        saved=db.execute('SELECT members FROM snapshots WHERE id=?',(sid,)).fetchone()
        if saved is None:raise IndexUnavailable('snapshot_missing')
        reference=json.loads(saved[0])
        if reference.get('member_kind')=='recipe-v1':
            recipe=store._snapshot_members(db,saved[0])
            if recipe.get('private_sha256')!=private_hash:raise ValueError('member_projection_recipe_mismatch')
        elif set(reference)=={'member_ref'}:
            if reference['member_ref']!=digest(private):raise ValueError('member_projection_recipe_mismatch')
        elif digest(reference)!=digest(private):raise ValueError('member_projection_recipe_mismatch')
        for group,ids in private['members'].items():
            if len(ids)!=len(set(ids)):raise ValueError('member_index_duplicate_identity')
            totals={r+':'+k:0 for r in ('all','repeated','not_repeated') for k in ('all','new','old','unknown')}
            for ordinal,cid in enumerate(ids):
                record=private['records'][cid];body=canonical(record)
                if len(body.encode())>16384:raise ValueError('member_projection_size')
                ref=hashlib.sha256(body.encode()).hexdigest();repeated,kind=classification(record)
                for r in ('all',)+(('repeated',) if repeated==1 else ('not_repeated',) if repeated==0 else ()):
                    for k in ('all',)+((kind,) if kind in ('new','old','unknown') else ()):totals[r+':'+k]+=1
                db.execute('INSERT OR IGNORE INTO member_projection_bodies VALUES(?,?)',(ref,body))
            header=dict(contract='fs-frozen-member-keyset-v1',snapshot_id=sid,group=group,data_version=public['data_version'],query_hash=query_hash,private_sha256=private_hash,snapshot_token=token,totals=totals)
            encoded=canonical(header);signature=mac(store,header)
            old=db.execute('SELECT body,signature FROM member_projection_groups WHERE snapshot=? AND grp=?',(sid,group)).fetchone()
            if old:
                if tuple(old)!=(encoded,signature):raise ValueError('member_projection_immutable')
                continue
            def rows():
                for ordinal,cid in enumerate(ids):
                    record=private['records'][cid];ref=hashlib.sha256(canonical(record).encode()).hexdigest();repeated,kind=classification(record)
                    yield (sid,group,ordinal,cid,ref,repeated,kind,mac(store,[sid,group,ordinal,cid,ref,repeated,kind]))
            db.executemany('INSERT INTO member_projection_rows VALUES(?,?,?,?,?,?,?,?)',rows())
            db.execute('INSERT INTO member_projection_groups VALUES(?,?,?,?)',(sid,group,encoded,signature))


def filters(query,args):
    repeat,kind=args.get('repeat_status','all'),args.get('customer_type','all')
    if repeat not in ('all','repeated','not_repeated') or kind not in ('all','new','old','unknown'):raise ValueError('private_period_filter')
    if query.get('state_basis')!='period_cohort' and (repeat!='all' or kind!='all'):raise ValueError('period_cohort_filter_required')
    return repeat,kind


def page(store,query,public,args,user,epoch):
    repeat,kind=filters(query,args);sid=public['snapshot_id'];group=args['group'];limit=args.get('limit',50)
    if type(limit) is not int or not 1<=limit<=200:raise ValueError('private_group_or_limit')
    if not isinstance(epoch,str) or not epoch:raise IndexUnavailable('permission_epoch_required')
    with store.db() as db:
        db.execute('BEGIN')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='member_projection_groups'").fetchone():raise IndexUnavailable('snapshot_member_index_unavailable')
        row=db.execute('SELECT body,signature FROM member_projection_groups WHERE snapshot=? AND grp=?',(sid,group)).fetchone()
        if row is None:raise IndexUnavailable('snapshot_member_index_unavailable')
        header=json.loads(row['body'])
        if not hmac.compare_digest(row['signature'],mac(store,header)) or header['query_hash']!=digest(query) or header['data_version']!=public['data_version']:raise ValueError('member_projection_integrity')
        if header['snapshot_token']!=store.snapshot_token(sid):raise ValueError('member_projection_recipe_changed')
        context=[sid,group,repeat,kind,mac(store,['owner',user]),epoch,header['data_version'],header['private_sha256']]
        after=-1;seen=0;cursor=args.get('cursor')
        if cursor is not None:
            if type(cursor) is not str or not cursor or len(cursor)>128:raise ValueError('private_cursor_mismatch')
            try:
                numbers,signature=cursor.split('.');ordinal,count=numbers.split('_')
                if any(not n.isascii() or not n.isdecimal() or str(int(n))!=n or not 0<=int(n)<2**63 for n in (ordinal,count)):raise ValueError()
                after,seen=int(ordinal),int(count)
                if not hmac.compare_digest(signature,mac(store,context+[after,seen])):raise ValueError()
            except (ValueError,AttributeError):raise ValueError('private_cursor_mismatch') from None
        where='snapshot=? AND grp=? AND ordinal>?';params=[sid,group,after]
        if repeat!='all':where+=' AND repeated=?';params.append(1 if repeat=='repeated' else 0)
        if kind!='all':where+=' AND kind=?';params.append(kind)
        rows=list(db.execute('SELECT ordinal,cid,ref,repeated,kind,signature FROM member_projection_rows WHERE '+where+' ORDER BY ordinal LIMIT ?',params+[limit+1]))
        result=[]
        for row in rows[:limit]:
            if not hmac.compare_digest(row['signature'],mac(store,[sid,group,row['ordinal'],row['cid'],row['ref'],row['repeated'],row['kind']])):raise ValueError('member_projection_integrity')
            body=db.execute('SELECT body FROM member_projection_bodies WHERE ref=?',(row['ref'],)).fetchone()
            if body is None or hashlib.sha256(body[0].encode()).hexdigest()!=row['ref']:raise ValueError('member_projection_integrity')
            result.append(json.loads(body[0]))
        next_cursor=None
        total=header['totals'][repeat+':'+kind];consumed=seen+len(result)
        if len(rows)<=limit and consumed!=total or len(rows)>limit and consumed>=total:raise ValueError('member_projection_incomplete')
        if len(rows)>limit:
            ordinal=rows[limit-1]['ordinal'];next_cursor=str(ordinal)+'_'+str(consumed)+'.'+mac(store,context+[ordinal,consumed])
        return dict(snapshot_id=sid,data_version=header['data_version'],total=total,group=group,rows=result,next_cursor=next_cursor)
