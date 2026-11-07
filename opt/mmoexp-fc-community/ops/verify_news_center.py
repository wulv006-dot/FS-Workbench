"""Read-only production news release receipt; no customer or credential output."""
import json
from pathlib import Path
import sqlite3
import subprocess

base = Path('/opt/mmoexp-fc-community')
config = json.loads((base/'content.config.json').read_text())
with sqlite3.connect('file:'+str(base/'var/news.sqlite3')+'?mode=ro', uri=True) as db:
    db.row_factory=sqlite3.Row
    statuses=[dict(r) for r in db.execute('SELECT kind,delivery_mode,status,count(*) AS count FROM news_items GROUP BY kind,delivery_mode,status')]
    batches=[dict(r) for r in db.execute('SELECT * FROM news_batches ORDER BY id DESC LIMIT 2')]
    meta=dict(db.execute("SELECT key,value FROM news_meta WHERE key IN ('last_attempt_at','last_poll_at','last_poll_error','collector_status')"))
    published=[dict(r) for r in db.execute("SELECT id,kind,title,url,channel_id,message_id FROM news_items WHERE status='published' ORDER BY completed_at DESC LIMIT 6")]
print(json.dumps({'news_config':config['news_publish'],'statuses':statuses,'batches':batches,'meta':meta,'published':published,
                  'services':subprocess.check_output(['systemctl','is-active','mmoexp-fc-community','bot-console','mmoexp-fc-quotes'],universal_newlines=True).splitlines()},ensure_ascii=True))
