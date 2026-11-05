"""Original installed seven-column writer; exact functions from Git7f2f110, full source SHA 5386eb529a21382438f4d48392946a5450e520452eb963d74bdd25f8ae28441e."""
import re,json,uuid

def tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS pricing_grants(conversation TEXT PRIMARY KEY,owner TEXT NOT NULL,mode TEXT NOT NULL,runs TEXT NOT NULL,expires_at TEXT NOT NULL,source TEXT NOT NULL,restore_sources TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS pricing_operations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,task TEXT NOT NULL,action TEXT NOT NULL,payload_hash TEXT NOT NULL,request_id TEXT NOT NULL,state TEXT NOT NULL,result TEXT,created_at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS pricing_recommendations(id TEXT PRIMARY KEY,owner TEXT NOT NULL,task TEXT NOT NULL,conversation TEXT NOT NULL,run_id TEXT NOT NULL,quote_sha256 TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL)')

def grant(db,owner,conversation,run,mode,expires,source,restore_sources=()):
    if mode!='daily_review' or not re.fullmatch('[a-f0-9]{32}',conversation):
        raise ValueError('pricing_grant_scope')
    uuid.UUID(run)
    if len(restore_sources)>1 or restore_sources and mode!='operator_workflow':raise ValueError('pricing_restore_grant_scope')
    sources=json.dumps([str(uuid.UUID(value)) for value in restore_sources]);tables(db)
    raw=json.dumps([run])
    old=db.execute('SELECT owner,mode,runs,expires_at,source,restore_sources FROM pricing_grants WHERE conversation=?',(conversation,)).fetchone()
    values=(owner,mode,raw,expires,source,sources)
    if old is not None and tuple(old)!=values:raise ValueError('pricing_grant_conflict')
    db.execute('INSERT OR IGNORE INTO pricing_grants VALUES(?,?,?,?,?,?,?)',(conversation,*values))
