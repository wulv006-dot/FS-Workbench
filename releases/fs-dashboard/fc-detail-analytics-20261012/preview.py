"""Local isolated UI verification. Auth is a fixture, never production role evidence."""
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import csv, io, json, mimetypes, sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'source'))
sys.path.insert(0,str(ROOT.parent/('fs_on_demand_20261012' if (ROOT.parent/'fs_on_demand_20261012').exists() else 'on-demand-20261012')/'source'))
from catalog import build as catalog
from fc_detail import query
from fc_detail_model import aggregate
CONFIG=json.loads((ROOT/'source/fc_detail_config.json').read_text())
PROFILES=[('FC27','FC27',1322,1327,'sports'),('NBA2K27','NBA2K27',1306,1329,'sports')]

def dataset():
    files=sorted((ROOT.parent/'.agent_runtime/fc27-detail-analytics-20261012').glob('*-snapshot.json'))
    for file in reversed(files):
        if file.stat().st_size:
            try:return json.loads(file.read_text('utf-8-sig'))
            except ValueError:pass
    sys.path.insert(0,str(ROOT/'tests'))
    from test_fc_detail import row,data
    return data([row(n,str(n*10)) for n in range(1,25)]+[row(30,site_id=141)], [row(40,paytime='2026-08-01 12:00:00')])

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u=urlsplit(self.path);q=parse_qs(u.query)
        now=datetime.now(timezone(timedelta(hours=8)))
        cat=catalog(PROFILES,now)
        if u.path.startswith('/__auth/'):
            self.send_response(200)
            for k,v in [('X-Auth-User','isolated-ui-fixture'),('X-Auth-Groups','dashboard,marketing,tasks'),('X-Auth-Role','admin'),('Content-Type','application/json')]:self.send_header(k,v)
            self.end_headers();self.wfile.write(b'{}');return
        if u.path=='/dashboard/fs-home/range.json':
            mode=q.get('mode',[''])[0]
            if mode=='catalog':return self.reply(cat)
            if mode in ('fc-detail','fc-report'):
                value=aggregate(dataset(),query(q),CONFIG)
                if mode=='fc-report':value['report']={**value,'report_id':'isolated-preview','generated_at':now.isoformat()}
                if q.get('format')==['csv']:
                    out=io.StringIO();writer=csv.writer(out);writer.writerow(['订单号','USD'])
                    for row in value['orders']:writer.writerow([row['id'],row['amount_usd']])
                    value['csv']=out.getvalue();value['orders']=value['orders'][:10]
                return self.reply(value)
            if mode=='profit-history':return self.reply({'schemaVersion':1,'catalogId':cat['catalogId'],'query':{k:v[0]for k,v in q.items()},'status':'available','history':{'contractId':'order-native-daily-margin-v2','daily':[]}})
            if mode=='summary':
                period={'start':q['start'][0]+' 00:00','end':(datetime.fromisoformat(q['end'][0])+timedelta(days=1)).strftime('%Y-%m-%d 00:00')}
                source={'status':'not_provided','currency':'USD','period':period,'metrics':{},'dimensions':{}}
                return self.reply({'schemaVersion':1,'status':'available','scopeContractId':'admin-main-order-labelled-supplement-v1','query':{k:v[0]for k,v in q.items()},'profile':{'key':q['profile'][0],'period':period,'primary':source,'supplement':source,'metrics':{},'dimensions':{}},'sources':{'Admin':{'status':'available'},'Order':{'status':'unavailable'}},'expiresInSeconds':900})
            return self.reply({'error':'unavailable'},503)
        name=u.path.rsplit('/',1)[-1]
        if u.path in ('/','/dashboard/analytics/'):name='index.html'
        path=ROOT/'frontend/assets'/name
        if path.is_file() and name in {p.name for p in (ROOT/'frontend/assets').iterdir()}:
            kind={'.js':'text/javascript','.html':'text/html','.css':'text/css','.json':'application/json'}.get(path.suffix,'application/octet-stream')
            self.send_response(200);self.send_header('Content-Type',kind+'; charset=utf-8');self.end_headers();self.wfile.write(path.read_bytes());return
        self.reply({'error':'not_found'},404)
    def reply(self,data,status=200):
        self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(data,ensure_ascii=False).encode())
    def log_message(self,*args):pass

if __name__=='__main__':
    print('Isolated preview http://127.0.0.1:8841/dashboard/analytics/?mode=business&b_profile=FC27&b_group=sports&b_range=30',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8841),Handler).serve_forever()
