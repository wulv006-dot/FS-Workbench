# Reviewed request dispatcher excerpt. Source: releases/fs-dashboard/traffic-hermes-20261017/source/shared_range_es_v3.py
# Source SHA256: 833944f08aa2a9495cf8e0abfbf404ac2366d0eaaf42ee159f3e55ff646609c8
def do_POST(self):
 uri=urlsplit(self.path)
 if uri.path not in ('/advisor','/boss-insight') or uri.query:self.reply(405,{'error':'read_only'});return
 user=self.headers.get('X-Auth-User')
 if not user:self.reply(401,{'error':'login_required'});return
 if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':self.reply(415,{'error':'json_required'});return
 length=self.headers.get('Content-Length','')
 if not re.fullmatch(r'[0-9]{1,5}',length) or not 1<=int(length)<=16384:self.reply(413,{'error':'body_too_large'});return
 try:
  self.connection.settimeout(15)
  body=json.loads(self.rfile.read(int(length)))
  if uri.path=='/advisor' and isinstance(body,dict) and str(body.get('kind','')).startswith('hermes_'):
   if HERMES is None:self.reply(503,{'error':'hermes_not_enabled'});return
   status,data=HERMES.post(body,user,self.headers)
  else:status,data=(ADVISOR.post if uri.path=='/advisor' else ADVISOR.post_boss)(body,user,self.headers)
  self.reply(status,data)
 except (ValueError,TypeError,UnicodeError):self.reply(422,{'error':'invalid_request'})
 except Exception:self.reply(503,{'error':'advisor_unavailable'})
