"""Complete native daily rates, fetched only for explicitly requested dates."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
import fcntl, hashlib, json, os, time
import re
from profit_daily import normalise, validate_row
from fs_cleanup import cache_guard

TTL = 7200
FAILURE_COOLDOWN = 30
CHUNK = 4

class ProfitQueries:
    def __init__(self, profiles, call, pool, web, cache, clock=time.monotonic):
        self.profiles, self.call, self.pool, self.web, self.cache, self.clock = profiles, call, pool, web, cache, clock
        self.expected = {k:dict(sites='all-websites',gid=str(v[2]),tid='',status='3' if v[4]=='rpg' else '') for k,v in profiles.items()}
        self.lock, self.jobs, self.starts = RLock(), {}, []
        self.rs_filters = {}

    def key(self, key, day):
        raw = json.dumps([key, day, self.expected[key]], sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()

    def load(self, key, day):
        if not self.cache.exists():return None
        with cache_guard(self.cache):
            target = self.cache/(self.key(key,day)+'.json')
            if not target.is_file() or target.is_symlink():return None
            try:
                row=json.loads(target.read_text());validate_row(row,self.expected)
                if row['profileKey']!=key or row['date']!=day:return None
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(row['capturedAt'])).total_seconds()
                from daily_archive import closed, cutoff
                if not closed({'start':day,'end':day}) or date.fromisoformat(day)<cutoff() or age<0:return None
                return row
            except (OSError,ValueError,KeyError,TypeError):return None

    def save(self,row):
        if any(p.is_symlink() for p in (self.cache,*self.cache.parents)):raise ValueError('linked_profit_cache')
        self.cache.mkdir(parents=True,exist_ok=True,mode=0o700)
        os.chmod(self.cache,0o700)
        with cache_guard(self.cache):
            target=self.cache/(self.key(row['profileKey'],row['date'])+'.json')
            if target.is_symlink():raise ValueError('linked_profit_cache')
            tmp=target.with_suffix('.tmp')
            with tmp.open('wb') as out:
                out.write(json.dumps(row,sort_keys=True,allow_nan=False).encode());out.flush();os.fsync(out.fileno())
            os.chmod(tmp,0o600);os.replace(tmp,target)
            files=sorted(self.cache.glob('*.json'),key=lambda p:p.stat().st_mtime)
            for old in files[:-8192]:
                if re.fullmatch(r'[a-f0-9]{64}\.json',old.name) and not old.is_symlink():old.unlink()

    def chunk(self, key, job):
        with self.lock:
            if job.get('failed'):return
            days=job['remaining'][:CHUNK]
            job['reading']=days
        try:
            row=self.profiles[key]
            requests=[{'key':day,'gid':row[2],'tid':'','status':'3' if row[4]=='rpg' else '',
                       **self.rs_filters, 'start':day+' 00:00','end':(date.fromisoformat(day)+timedelta(days=1)).isoformat()+' 00:00'} for day in days]
            with (self.web/'collector.lock').open('a+b') as source_lock:
                fcntl.flock(source_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                values=self.call('fc27-cloud-browser','rs_shipping' if self.expected[key].get('delivery') else 'primary_reader.py',requests,210)
            for day in days:
                source=values[day]
                raw={**source,'profileKey':key,'date':day,'profitMarginPct':source.get('metrics',{}).get('profitMarginPct',{}),
                     'collectionKind':'on-demand-native-day'}
                self.save(normalise(raw,self.expected))
            with self.lock:
                job['remaining']=job['remaining'][len(days):]
                job['reading']=[]
                if job['remaining']:
                    # Yield between small batches to the same Order worker used by summaries.
                    self.pool.submit(self.chunk,key,job)
                else:job['finished']=self.clock()
        except Exception as error:
            with self.lock:job.update(failed=True,denied=isinstance(error,PermissionError),reading=[],finished=self.clock())

    def get(self,q,catalog_id,today):
        key=q['profile'];lo=date.fromisoformat(q['start']);hi=min(date.fromisoformat(q['end']),today-timedelta(days=1))
        days=[(lo+timedelta(days=i)).isoformat() for i in range(max(0,(hi-lo).days+1))]
        identity=(key,q['start'],q['end'],catalog_id)
        with self.lock:
            rows={day:None if q.get('refresh') else self.load(key,day) for day in days}
            missing=[day for day in days if rows[day] is None]
            now=self.clock();job=self.jobs.get(identity)
            if job and job.get('denied') and now-job['finished']<FAILURE_COOLDOWN:
                return 403,{'status':'denied','error':'source_permission_denied'}
            self.starts[:]=[t for t in self.starts if now-t<60]
            if missing and (not job or job.get('finished') is not None and now-job['finished']>=FAILURE_COOLDOWN):
                active=sum(not j.get('failed') and j.get('finished') is None for j in self.jobs.values())
                if active>=4 or len(self.starts)>=6:return 429,{'status':'busy','retryAfter':10}
                if len(self.jobs)>=256:
                    victim=next((k for k,j in self.jobs.items() if j.get('finished') is not None),None)
                    if victim is None:return 429,{'status':'busy','retryAfter':10}
                    self.jobs.pop(victim)
                self.starts.append(now);job={'remaining':missing,'reading':[],'finished':None};self.jobs[identity]=job
                self.pool.submit(self.chunk,key,job)
            pending=bool(job and job.get('finished') is None)
            return 200,{'schemaVersion':1,'status':'pending' if pending else 'partial' if missing else 'available',
                        'query':{k:q[k] for k in ['profile','start','end','grain','rs_site','rs_server','rs_category'] if k in q},'catalogId':catalog_id,'retryAfter':2,
                        'history':{'schemaVersion':2,'contractId':'order-native-daily-margin-v2','snapshotId':catalog_id,
                                   'daily':[rows[day] for day in days if rows[day] is not None]},
                        'requestedDays':len(days),'cachedDays':len(days)-len(missing),'missingDays':missing,
                        'completeDayOnly':True,'cacheSeconds':TTL,'lastError':'source_read_failed' if job and job.get('failed') else None}
