"""Legacy protected today endpoint: reads pinned cloud snapshot, never recollects."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib
ROOT=Path('/var/www/dashboard/fs-home/transactions')
def today():
    try:
        m=json.loads((ROOT/'current.json').read_text());path=m['path']
        if path!='snapshots/'+m['snapshotId']+'/snapshot.json':raise ValueError('bad_path')
        raw=(ROOT/path).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=m['sha256']:raise ValueError('hash_mismatch')
        d=json.loads(raw);p=d['profiles']['MMOEXP'];attempt=json.loads((ROOT/'attempt.json').read_text())
        stale=(datetime.now(timezone.utc)-datetime.fromisoformat(d['generatedAt'])).total_seconds()>7200 or attempt.get('status')!='success'
        return {'schemaVersion':2,'status':'available','stale':stale,'snapshotId':d['snapshotId'],'date':d['date'],
                'metricScope':'ALL_WEBSITES','timezone':d['timezone'],'currency':d['currency'],'period':p['period'],
                'generatedAt':d['generatedAt'],'source':p['primary'],'supplement':p['supplement'],
                'metrics':{k:v['value'] for k,v in p['metrics'].items()},'refreshSeconds':7200,'clientCheckSeconds':60}
    except Exception:return {'schemaVersion':2,'status':'unavailable','metrics':{'orders':None,'revenueUsd':None,'newCustomers':None}}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/health':self.reply(200,{'ok':True,'service':'fs-home-readonly','mode':'shared-snapshot'})
        elif self.path=='/today':
            d=today();self.reply(200 if d['status']=='available' else 503,d)
        else:self.reply(404,{'error':'not_found'})
    def do_POST(self):self.reply(405,{'error':'read_only'})
    def reply(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False).encode();self.send_response(status)
        for name,value in [('Content-Type','application/json; charset=utf-8'),('Cache-Control','no-store'),('Content-Length',str(len(body))),('X-Content-Type-Options','nosniff')]:self.send_header(name,value)
        self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass
if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',8930),Handler).serve_forever()
