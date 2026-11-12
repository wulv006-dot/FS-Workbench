"""Narrow extension of the existing admin-only bot console; no credential output."""
import http.client
import json
import socket
from pathlib import Path

class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/run/mmoexp-lucky-loot/control.sock')

def handle(handler,method,path,query):
    static={'/giveaway.html':'giveaway.html','/giveaway.js':'giveaway.js','/giveaway.css':'giveaway.css'}
    if path in static:
        if handler._require_admin():handler._serve_static(static[path])
        return True
    if path=='/console.css':
        if handler._require_admin():
            source=(Path(__file__).parent/'static/index.html').read_text(encoding='utf8')
            css=source.split('<style>',1)[1].split('</style>',1)[0]
            handler._text(200,css,'text/css; charset=utf-8')
        return True
    if not path.startswith('/api/loot/'):return False
    if not handler._require_admin():return True
    allowed={'GET':{'status','meta','coupon'},'POST':{'connect','save','schedule','cancel','reconcile','manual','recipient','preview','refresh-card'}}
    action=path.removeprefix('/api/loot/')
    if action not in allowed.get(method,set()):
        handler._json(404,{'ok':False,'error':'未知抽奖操作'});return True
    if method=='POST' and not handler._check_csrf():return True
    target='/'+action
    if action=='coupon':
        value=(query.get('id') or [''])[0]
        if not value.isdigit():handler._json(400,{'ok':False,'error':'券编号无效'});return True
        target+='?id='+value
    try:
        body=json.dumps(handler._read_body(),ensure_ascii=False).encode('utf8') if method=='POST' else None
        conn=UnixConnection('localhost',timeout=110)
        try:
            conn.request(method,target,body,{'Content-Type':'application/json'})
            response=conn.getresponse();raw=response.read(2000000)
            handler._json(response.status,json.loads(raw))
        finally:conn.close()
    except Exception:
        handler._json(503,{'ok':False,'error':'抽奖服务暂不可用，请检查独立服务状态'})
    return True
