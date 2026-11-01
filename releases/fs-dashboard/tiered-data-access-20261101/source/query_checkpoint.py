"""Bounded page checkpoints in existing Archive catalog, explicitly initialized."""
from contextlib import closing
import hashlib,json
from range_jobs import encode


class Checkpoints:
    def __init__(self,archive):self.archive=archive

    def initialize(self):
        with closing(self.archive.database(True)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS range_query_jobs(key TEXT PRIMARY KEY,generation TEXT,body TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS range_query_rows(key TEXT,generation TEXT,ordinal INTEGER,body TEXT,PRIMARY KEY(key,generation,ordinal))')
            db.execute('CREATE TABLE IF NOT EXISTS range_query_subscriptions(handle TEXT PRIMARY KEY,key TEXT,body TEXT)')

    def save(self,key,job,subscriptions):
        body={k:v for k,v in job.items() if k not in ('rows','ids')}
        body['row_count']=len(job['rows'])
        if len(encode(body))>65536 or len(subscriptions)>1000 or len(encode(job['rows']))>8*1024*1024:raise ValueError('checkpoint_budget')
        with closing(self.archive.database(True)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT generation,body FROM range_query_jobs WHERE key=?',(key,)).fetchone()
            count=json.loads(old['body'])['row_count'] if old and old['generation']==job['generation'] else 0
            if not old and db.execute('SELECT count(*) FROM range_query_jobs').fetchone()[0]>=32:raise ValueError('checkpoint_capacity')
            if old and old['generation']!=job['generation']:db.execute('DELETE FROM range_query_rows WHERE key=?',(key,))
            if count>len(job['rows']):raise ValueError('checkpoint_rows_rewound')
            # Previously committed rows never get serialized back into the DB.
            for ordinal in range(count,len(job['rows'])):
                db.execute('INSERT INTO range_query_rows VALUES(?,?,?,?)',(key,job['generation'],ordinal,encode(job['rows'][ordinal]).decode()))
            db.execute('INSERT OR REPLACE INTO range_query_jobs VALUES(?,?,?)',(key,job['generation'],encode(body).decode()))
            db.execute('DELETE FROM range_query_subscriptions WHERE key=?',(key,))
            for handle,sub in subscriptions.items():db.execute('INSERT INTO range_query_subscriptions VALUES(?,?,?)',(handle,key,encode(sub).decode()))

    def load(self):
        jobs,subscriptions={},{}
        with closing(self.archive.database()) as db:
            db.execute('BEGIN')
            for row in db.execute('SELECT key,generation,body FROM range_query_jobs LIMIT 33'):
                if len(jobs)>=32 or len(row['body'].encode())>65536:raise ValueError('checkpoint_capacity')
                job=json.loads(row['body']);rows=[];size=0
                for item in db.execute('SELECT ordinal,body FROM range_query_rows WHERE key=? AND generation=? ORDER BY ordinal',(row['key'],row['generation'])):
                    if item['ordinal']!=len(rows):raise ValueError('checkpoint_gap')
                    size+=len(item['body'].encode())
                    if size>8*1024*1024:raise ValueError('checkpoint_budget')
                    rows.append(json.loads(item['body']))
                if len(rows)!=job.pop('row_count'):raise ValueError('checkpoint_gap')
                job['rows']=rows;job['ids']={r['order_id']:hashlib.sha256(encode(r)).hexdigest() for r in rows};jobs[row['key']]=job
            for row in db.execute('SELECT handle,key,body FROM range_query_subscriptions LIMIT 1001'):
                if len(subscriptions)>=1000 or row['key'] not in jobs:raise ValueError('checkpoint_subscription')
                subscriptions[row['handle']]=json.loads(row['body'])
        return jobs,subscriptions
