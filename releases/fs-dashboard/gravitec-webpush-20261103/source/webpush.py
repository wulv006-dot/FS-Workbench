"""Gravitec V3 adapter. Credentials stay server-side; uncertain writes never retry."""
import base64
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid

LOCK = threading.RLock()
VERSION = 'gravitec-20261103-v1'

class Invalid(ValueError):
    pass

def text(value, limit=1000, required=True):
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        raise Invalid('字段为空或超出长度限制')
    return value.strip()

def url(value):
    value = text(value)
    u = urllib.parse.urlsplit(value)
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or any(c.isspace() for c in value):
        raise Invalid('请使用有效的网页或图片链接')
    return value

def campaign(body):
    mode = body.get('audience_mode')
    if mode not in ('tokens', 'aliases', 'tags', 'segment', 'all'):
        raise Invalid('请选择发送对象')
    payload = {k:text(body.get(k, ''), required=k == 'message') for k in ('title','message')}
    payload['redirect_url'] = url(body.get('redirect_url'))
    for k in ('icon','image'):
        if body.get(k):
            payload[k] = url(body[k])
            if not urllib.parse.urlsplit(payload[k]).path.lower().endswith(('.jpg','.jpeg','.png')):
                raise Invalid('图片链接须以 jpg、jpeg 或 png 结尾')
    buttons = body.get('buttons', [])
    if not isinstance(buttons,list) or len(buttons)>2:
        raise Invalid('最多设置两个按钮')
    if buttons:
        payload['buttons'] = [{'title':text(x.get('title'),48), 'url':url(x.get('url'))} for x in buttons if isinstance(x,dict)]
        if len(payload['buttons']) != len(buttons):
            raise Invalid('按钮格式不正确')
    out = {'payload':payload}
    if mode != 'all':
        values = body.get('audience_values')
        if not isinstance(values,list) or not 1 <= len(values) <= (1 if mode=='segment' else 100):
            raise Invalid('发送对象不能为空；分群限一个，其余最多100项')
        values = list(dict.fromkeys(text(x,255) for x in values))
        out.update({'segments':values} if mode=='segment' else {'audience':{mode:values}})
    for key,default in [('ttl',28800),('display_time',60)]:
        val = body.get(key,default)
        if type(val) is not int or not 0 <= val <= 2419200:
            raise Invalid('有效期或展示时间不正确')
        out[key] = val
    when = body.get('send_date')
    if when not in (None,'','now'):
        if type(when) is not int or when <= int(time.time()*1000):
            raise Invalid('定时发送必须为未来时间')
        out['send_date'] = when
    if body.get('push_tag'):
        out['push_tag'] = text(body['push_tag'],100)
    return out

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def transport(config, method, path, data=None):
    auth = base64.b64encode((config['app_key']+':'+config['app_secret']).encode()).decode()
    request=urllib.request.Request('https://uapi.gravitec.net/api/v3/'+path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'},method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(request,timeout=25) as r:
            return r.status,json.loads(r.read(1048576) or b'{}')
    except urllib.error.HTTPError as e:
        # Do not expose provider errors: these can echo credentials.
        return e.code,{}

class Service:
    def __init__(self,directory,sender=transport):
        self.root=Path(directory); self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.sender=sender; self.file=self.root/'config.json'; self.db=self.root/'push.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,body TEXT,updated REAL,actor TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS sends(id TEXT PRIMARY KEY,fingerprint TEXT,body TEXT,state TEXT,provider_id TEXT,created REAL,actor TEXT,http_status INTEGER)')
        os.chmod(self.db,0o600)

    @contextmanager
    def connect(self):
        db=sqlite3.connect(str(self.db),timeout=10)
        try:
            with db: yield db
        finally: db.close()

    def config(self):
        return json.loads(self.file.read_text()) if self.file.exists() else {}

    def public(self):
        c=self.config()
        return {'ok':True,'version':VERSION,'site_name':c.get('site_name',''),
            'configured':bool(c.get('app_key') and c.get('app_secret')),
            'verified_at':c.get('verified_at'), 'capabilities':['push','schedule','audience','stats','alias','tag']}

    def save(self,body):
        with LOCK:
            c=self.config(); c['site_name']=text(body.get('site_name','Gravitec'),100)
            for k in ('app_key','app_secret'):
                if body.get(k):
                    c[k]=text(body[k],255)
                    if ':' in c[k] or any(x.isspace() for x in c[k]):
                        raise Invalid('密钥格式不正确')
                    c.pop('verified_at',None)
            if not c.get('app_key') or not c.get('app_secret'):
                raise Invalid('首次配置需要两项密钥')
            self._save(c)
        return self.public()

    def _save(self,c):
        tmp=self.root/('config-'+uuid.uuid4().hex+'.tmp')
        fd=os.open(str(tmp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f: json.dump(c,f)
        os.replace(str(tmp),str(self.file))

    def request(self,method,path,body=None):
        c=self.config()
        if not c.get('app_key') or not c.get('app_secret'): raise Invalid('请先保存平台配置')
        return self.sender(c,method,path,body)

    def verify(self):
        with LOCK:
            status,result=self.request('GET','alias?regId=fs_connection_probe_'+uuid.uuid4().hex)
            good=status==200 and isinstance(result,dict) and 'regIdExists' in result
            c=self.config(); c['verified_at']=time.time() if good else None; self._save(c)
        return {'ok':True,'verified':good,'http_status':status}

    def draft(self,body,actor):
        campaign(body)
        ident=body.get('draft_id') or uuid.uuid4().hex
        if not re.fullmatch('[a-f0-9]{32}',ident): raise Invalid('草稿编号不正确')
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO drafts VALUES(?,?,?,?)',(ident,json.dumps(body),time.time(),actor))
        return {'ok':True,'draft_id':ident}

    def records(self):
        with self.connect() as db:
            drafts=[{'id':r[0],'body':json.loads(r[1]),'updated':r[2]} for r in db.execute('SELECT id,body,updated FROM drafts ORDER BY updated DESC LIMIT 50')]
            sends=[dict(zip(('id','state','provider_id','created','actor','http_status','body'),r)) for r in db.execute('SELECT id,state,provider_id,created,actor,http_status,body FROM sends ORDER BY created DESC LIMIT 50')]
        for r in sends: r['body']=json.loads(r['body'])
        return {'ok':True,'drafts':drafts,'sends':sends}

    def send(self,body,actor):
        if body.get('confirm') is not True: raise Invalid('请先预览并确认发送')
        payload=campaign(body)
        if body['audience_mode']=='all' and body.get('all_confirmation')!='发送给全部订阅者':
            raise Invalid('全部发送需要明确确认')
        ident=body.get('request_id','')
        if not re.fullmatch('[a-f0-9]{32}',ident): raise Invalid('请求编号不正确')
        c=self.config()
        if not c.get('app_key') or not c.get('app_secret'): raise Invalid('请先保存平台配置')
        fingerprint=hashlib.sha256(json.dumps([payload,c['app_key']],sort_keys=True).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT fingerprint,state,provider_id FROM sends WHERE id=?',(ident,)).fetchone()
            if old:
                if old[0]!=fingerprint: raise Invalid('原请求内容已改变，请新建推送')
                return {'ok':True,'state':old[1],'provider_id':old[2],'replayed':True}
            db.execute('INSERT INTO sends VALUES(?,?,?,?,?,?,?,?)',(ident,fingerprint,json.dumps(payload),'unknown',None,time.time(),actor,None))
        state,pid,status='unknown',None,None
        try:
            status,result=self.sender(c,'POST','push',payload)
            if status==200 and isinstance(result,dict) and re.fullmatch('[0-9]{1,40}',str(result.get('id',''))):
                state,pid='accepted',str(result['id'])
            elif status in (400,401,403,422,429): state='rejected'
        except Exception:
            pass
        with self.connect() as db:
            db.execute('UPDATE sends SET state=?,provider_id=?,http_status=? WHERE id=?',(state,pid,status,ident))
        return {'ok':True,'state':state,'provider_id':pid,'request_id':ident}

    def stats(self,body):
        ident=body.get('campaign_id','')
        if not isinstance(ident,str) or not re.fullmatch('[0-9]{1,40}',ident): raise Invalid('请输入平台推送编号')
        status,result=self.request('GET','messages/'+ident)
        safe={k:result[k] for k in ('status','send','received','clicked','closed') if k in result} if isinstance(result,dict) else {}
        return {'ok':True,'http_status':status,'campaign_id':ident,'stats':safe}

    def subscriber(self,body):
        action=body.get('action')
        mapping={'get_alias':('GET','alias'),'set_alias':('POST','alias'),'add_tag':('POST','tag'),'delete_tag':('DELETE','tag')}
        if action not in mapping: raise Invalid('未知订阅者操作')
        method,path=mapping[action]; query={'regId':text(body.get('regId'),255)}
        if action!='get_alias':
            if body.get('confirm') is not True: raise Invalid('请确认订阅者变更')
            query['name']=text(body.get('name'),255)
        status,result=self.request(method,path+'?'+urllib.parse.urlencode(query))
        safe={k:result[k] for k in ('regIdExists','aliasExists','isActiveFollower','alias') if k in result} if isinstance(result,dict) else {}
        return {'ok':True,'http_status':status,'result':safe}

def authorize(headers,method,path):
    conn=http.client.HTTPConnection('127.0.0.1',8895,timeout=4)
    try:
        conn.request('GET','/verify?group=dashboard',headers={'Cookie':headers.get('Cookie',''),'X-Original-Method':method,'X-Original-URI':'/dashboard/modules/marketing'+path})
        r=conn.getresponse(); actor=r.getheader('X-Auth-User'); role=r.getheader('X-Auth-Role'); r.read()
        if r.status!=200 or role!='admin' or not actor: return None
        if method=='POST':
            if headers.get('X-FS-WebPush-Request')!='1' or headers.get('Sec-Fetch-Site')=='cross-site': return None
            origin=headers.get('Origin')
            if origin and urllib.parse.urlparse(origin).netloc!=headers.get('Host'): return None
        return actor
    except (OSError,http.client.HTTPException): return None
    finally: conn.close()

def handle(handler):
    path=urllib.parse.urlparse(handler.path).path
    def reply(value,status=200):
        data=json.dumps(value,ensure_ascii=False).encode(); handler.send_response(status)
        for k,v in {'Content-Type':'application/json; charset=utf-8','Content-Length':str(len(data)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}.items(): handler.send_header(k,v)
        handler.end_headers(); handler.wfile.write(data)
    actor=authorize(handler.headers,handler.command,path)
    if not actor:
        reply({'ok':False,'error':'请使用后台管理员账号登录'},403); return True
    try:
        service=Service(Path(__file__).parent/'_webpush_private')
        if handler.command=='GET' and path=='/api/webpush/config': reply(service.public())
        elif handler.command=='GET' and path=='/api/webpush/records': reply(service.records())
        elif handler.command=='POST':
            size=int(handler.headers.get('Content-Length','0'))
            if not 0<size<=65536 or not handler.headers.get('Content-Type','').startswith('application/json'): raise Invalid('请求格式不正确')
            body=json.loads(handler.rfile.read(size))
            if not isinstance(body,dict): raise Invalid('请求格式不正确')
            action=path.removeprefix('/api/webpush/')
            funcs={'config':lambda:service.save(body),'verify':service.verify,'preview':lambda:{'ok':True,'payload':campaign(body)},'draft':lambda:service.draft(body,actor),'send':lambda:service.send(body,actor),'stats':lambda:service.stats(body),'subscriber':lambda:service.subscriber(body)}
            if action not in funcs: reply({'ok':False,'error':'接口不存在'},404)
            else: reply(funcs[action]())
        else: reply({'ok':False,'error':'接口不存在'},404)
    except Invalid as e: reply({'ok':False,'error':str(e)},400)
    except (ValueError,TypeError,KeyError): reply({'ok':False,'error':'请求内容不正确'},400)
    except Exception: reply({'ok':False,'error':'平台连接或服务异常，请稍后查询原操作结果'},502)
    return True
