"""Validate an existing FS session for one live read; no identity-header trust."""
import re
import socket
import threading
import time

_SLOT=threading.BoundedSemaphore(1)
_NAMES=frozenset(('MMOEXP_AUTH','FS_ACCESS_CANDIDATE','fc27sess'))
_TOKEN=re.compile(r'^[\x21-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]{1,4096}$')
_USER=re.compile(r'^[A-Za-z0-9_.:@-]{1,128}$')
_LIMIT=16384

def session_cookie(header):
 if not isinstance(header,str) or len(header)>8192 or '\r' in header or '\n' in header:return None
 out=[];seen=set()
 for item in header.split(';'):
  name,sep,value=item.strip().partition('=')
  if not sep or name not in _NAMES:continue
  if name in seen:return None
  seen.add(name)
  if not value:continue
  if not _TOKEN.fullmatch(value):return None
  out.append(name+'='+value)
 return '; '.join(out) if out else None

def verify_socket(sock,cookie,deadline=None):
 deadline=deadline if deadline is not None else time.monotonic()+2
 request=('GET /verify?group=dashboard HTTP/1.0\r\nHost: localhost\r\nCookie: '+cookie+'\r\nX-Original-Method: GET\r\nX-Original-URI: /dashboard/users/data.json\r\nConnection: close\r\n\r\n').encode('ascii')
 sock.settimeout(max(0.001,deadline-time.monotonic()));sock.sendall(request)
 raw=bytearray()
 while b'\r\n\r\n' not in raw:
  remaining=deadline-time.monotonic()
  if remaining<=0 or len(raw)>=_LIMIT:return {'status':503}
  sock.settimeout(remaining);part=sock.recv(min(4096,_LIMIT-len(raw)))
  if not part:return {'status':503}
  raw.extend(part)
 head=bytes(raw).split(b'\r\n\r\n',1)[0]
 lines=head.split(b'\r\n')
 if not re.fullmatch(rb'HTTP/1\.[01] [0-9]{3}(?: [\x20-\x7e]*)?',lines[0]):return {'status':503}
 status=int(lines[0].split(b' ')[1])
 if status in (401,403):return {'status':status}
 if status!=200:return {'status':503}
 users=[]
 for line in lines[1:]:
  key,sep,val=line.partition(b':')
  if not sep:return {'status':503}
  if key.lower()==b'x-auth-user':users.append(val.strip())
 if len(users)!=1:return {'status':503}
 try:user=users[0].decode('ascii')
 except UnicodeDecodeError:return {'status':503}
 return {'status':200,'user':user} if _USER.fullmatch(user) else {'status':503}

def verify(header):
 cookie=session_cookie(header)
 if not cookie:return 401,None
 if not _SLOT.acquire(blocking=False):return 429,None
 try:
  deadline=time.monotonic()+2
  with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
   sock.settimeout(max(0.001,deadline-time.monotonic()));sock.connect(('127.0.0.1',8895))
   result=verify_socket(sock,cookie,deadline)
  return result['status'],result.get('user')
 except (OSError,ValueError,UnicodeError):return 503,None
 finally:_SLOT.release()
