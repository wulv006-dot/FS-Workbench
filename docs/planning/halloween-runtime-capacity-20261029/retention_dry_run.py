"""Read-only inventory; proposes reversible archival, never changes a receipt."""
import pathlib,json,hashlib,datetime,stat,collections,re
from zoneinfo import ZoneInfo
root=pathlib.Path('/var/lib/fs-campaign-runtime/preview/halloween-reveals')
tz=ZoneInfo('America/New_York');clock=datetime.datetime.now(tz);cutoff=clock.date()-datetime.timedelta(days=2)
counts=collections.Counter();days=collections.Counter();rows=[];complete=True
assert root.is_dir() and not root.is_symlink()
for index,p in enumerate(root.iterdir()):
 if index>=10000:complete=False;break
 s=p.lstat();reason=None;day=None;digest=None
 if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or p.suffix!='.json' or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',p.stem,re.I):reason='protected_type_link_or_identity'
 elif s.st_size>16000:reason='protected_size'
 else:
  try:
   raw=p.read_bytes();digest=hashlib.sha256(raw).hexdigest();r=json.loads(raw)
   assert r['status']=='revealed' and p.stem==r['request_id']
   assert len(r['slots'])==3 and r.get('request_hash') and r.get('release_id') and r.get('config_hash') and r.get('rule_hash')
   stamp=datetime.datetime.fromisoformat(r['created_at'].replace('Z','+00:00'));assert stamp.tzinfo
   day=stamp.astimezone(tz).date();assert day<=clock.date()
   reason='archive_proposal_only' if day<cutoff else 'protected_recent_terminal'
  except Exception:reason='protected_unknown_or_invalid'
 counts[reason]+=1;days[str(day) if day else 'unresolved']+=1
 rows.append({'request_id':p.stem,'bytes':s.st_size,'sha256':digest,'ny_day':str(day) if day else None,'classification':reason})
print(json.dumps({'read_only':True,'no_mutations':True,'inventory_complete':complete,'scan_limit':10000,'ny_now':clock.isoformat(),'full_payload_keep_from':cutoff.isoformat(),'root':str(root),'counts':dict(counts),'days':dict(days),'total_bytes':sum(x['bytes'] for x in rows),'archive_proposal_bytes':sum(x['bytes'] for x in rows if x['classification']=='archive_proposal_only'),'apply_enabled':False,'precondition':'No archive/deletion until expired UUIDs fail closed via a minimal tombstone; UNKNOWN and purchase/intent journals stay protected.','rows':rows}))
