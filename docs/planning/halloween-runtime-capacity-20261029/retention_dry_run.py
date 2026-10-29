"""Read-only inventory. No archive, mutation, deletion, scheduling or apply path."""
import collections,datetime,hashlib,json,pathlib,re,stat
from zoneinfo import ZoneInfo

ROOT=pathlib.Path('/var/lib/fs-campaign-runtime/preview/halloween-reveals')
UUID=re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',re.I)

def inventory(root,now=None,limit=10000):
 if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=10000:raise ValueError('invalid scan limit')
 root=pathlib.Path(root)
 if not root.is_dir() or root.is_symlink():raise ValueError('unsafe inventory root')
 tz=ZoneInfo('America/New_York');clock=now or datetime.datetime.now(tz)
 if clock.tzinfo is None:raise ValueError('timezone required')
 clock=clock.astimezone(tz);cutoff=clock.date()-datetime.timedelta(days=2)
 counts=collections.Counter();days=collections.Counter();rows=[];complete=True
 for index,p in enumerate(root.iterdir()):
  if index>=limit:complete=False;break
  s=p.lstat();reason=None;day=None;digest=None
  if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or p.suffix!='.json' or not UUID.fullmatch(p.stem):reason='protected_type_link_or_identity'
  elif s.st_size>16000:reason='protected_size'
  else:
   try:
    with p.open('rb') as file:raw=file.read(16001)
    if len(raw)>16000:raise ValueError('oversized record')
    after=p.lstat()
    if (s.st_ino,s.st_size,s.st_mtime_ns,s.st_nlink)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_nlink):raise ValueError('record changed')
    digest=hashlib.sha256(raw).hexdigest();r=json.loads(raw)
    if r.get('status')!='revealed' or p.stem!=r.get('request_id') or not isinstance(r.get('game_id'),str) or not r.get('release_id') or not all(re.fullmatch('[0-9a-f]{64}',r.get(k,'') or '') for k in ['config_hash','rule_hash']):raise ValueError('unresolved record')
    request=json.dumps({'request_id':r['request_id'],'game_id':r['game_id']},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    if r.get('request_hash')!=hashlib.sha256(request).hexdigest() or [slot['slot'] for slot in r.get('slots',[])]!=['fixed','random-1','random-2'] or any(not re.fullmatch(r'[1-9]\d{0,19}',slot.get('model_id','')) or slot.get('off_percent') not in [8,10,15] for slot in r['slots']):raise ValueError('invalid terminal identity')
    stamp=datetime.datetime.fromisoformat(r['created_at'].replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('missing timezone')
    day=stamp.astimezone(tz).date()
    if stamp>clock:raise ValueError('future record')
    reason='archive_proposal_only' if day<cutoff else 'protected_recent_terminal'
   except Exception:reason='protected_unknown_or_invalid';day=None
  counts[reason]+=1;days[str(day) if day else 'unresolved']+=1
  rows.append({'request_id':p.stem,'bytes':s.st_size,'sha256':digest,'ny_day':str(day) if day else None,'classification':reason})
 return {'read_only':True,'no_mutations':True,'inventory_complete':complete,'scan_limit':limit,'ny_now':clock.isoformat(),'full_payload_keep_from':cutoff.isoformat(),'root':str(root),'counts':dict(counts),'days':dict(days),'total_bytes':sum(x['bytes'] for x in rows),'archive_proposal_bytes':sum(x['bytes'] for x in rows if x['classification']=='archive_proposal_only'),'apply_enabled':False,'precondition':'No archive/deletion until expired UUIDs fail closed via a minimal tombstone; UNKNOWN and purchase/intent journals stay protected.','rows':rows}

if __name__=='__main__':print(json.dumps(inventory(ROOT)))
