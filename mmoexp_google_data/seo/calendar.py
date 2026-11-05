"""Read existing published game-monitor material without its model or collector."""
import datetime as dt
import hashlib
import http.client
import importlib.util
import json
import re
from pathlib import Path
from urllib.parse import urlsplit,urljoin

from .contracts import BUSINESS_TZ,game,make_daily_context
from .sources import SourceError

PUBLISHED=Path('/var/lib/fs-boss-workspaces/public/game-monitor.json')


class CalendarSource:
    name='calendar'
    timezone='Asia/Shanghai'
    is_observation=True

    def __init__(self,config,*,read=None,official=None,http=None,clock=lambda:dt.datetime.now(dt.timezone.utc),finish_margin_seconds=0):
        self.config,self.clock=config,clock
        self.read=read or (lambda:self.read_json(PUBLISHED))
        self.official,self.http,self.calls=official or self.read_official,http,0
        self.reader=None
        self.margin=finish_margin_seconds

    def collection_open(self):
        local=self.clock().astimezone(BUSINESS_TZ)
        return make_daily_context(self.clock()).publication_allowed and (local.replace(hour=6,minute=30,second=0,microsecond=0)-local).total_seconds()>self.margin

    def read_official(self,source_id):
        if self.reader is None:
            spec=importlib.util.spec_from_file_location('fs_seo_official_reader','/opt/fs-boss-workspaces/backend/game_intelligence.py')
            self.reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.reader)
        sources=[s for s in self.reader.SOURCES if s['source_id']==source_id]
        if len(sources)!=1:raise SourceError('UNKNOWN_OFFICIAL_SOURCE')
        spec=sources[0];url=spec['url']
        if not self.http:raise SourceError('CALENDAR_HTTP_CONFIG_REQUIRED')
        for redirect in range(4):
            if not self.collection_open():raise SourceError('NIGHT_DEADLINE')
            self.reader.safe_url(url,spec['hosts']);parts=urlsplit(url)
            connection=http.client.HTTPSConnection(parts.hostname,timeout=self.http['connect_seconds'])
            try:
                connection.connect();connection.sock.settimeout(self.http['idle_seconds'])
                self.calls+=1
                connection.request('GET',parts.path+('?' + parts.query if parts.query else ''),headers={'User-Agent':'FS-SEO-Daily/1.0','Accept':'application/json,application/rss+xml,text/html','Accept-Encoding':'identity'})
                response=connection.getresponse()
                if response.status in (301,302,303,307,308):
                    url=urljoin(url,response.getheader('Location',''));continue
                if response.status!=200:raise SourceError('HTTP_'+str(response.status))
                raw=bytearray()
                while True:
                    if not self.collection_open():raise SourceError('NIGHT_DEADLINE')
                    chunk=response.read(65536)
                    if not chunk:break
                    if len(raw)+len(chunk)>self.http['response_emergency_bytes']:raise SourceError('CALENDAR_SOURCE_EMERGENCY_SIZE')
                    raw.extend(chunk)
                return [d for d in self.reader.parse(spec,bytes(raw),url) if d]
            finally:connection.close()
        raise SourceError('CALENDAR_REDIRECT_LIMIT')

    def read_json(self,path):
        ceiling=self.config.get('source_emergency_bytes',16*1024**2)
        if type(ceiling) is not int or ceiling<=0:raise SourceError('CALENDAR_RESOURCE_CONFIG_REQUIRED')
        with path.open('rb') as stream:raw=stream.read(ceiling+1)
        if len(raw)>ceiling:raise SourceError('CALENDAR_SOURCE_EMERGENCY_SIZE')
        return json.loads(raw)

    def user_plan(self,now):
        document=self.read_json(Path(__file__).with_name('calendar.fc27.user-provided.json'))
        rows=[]
        for entry in document['events']:
            title,english,start,end,kind,original,summary,_=entry
            if dt.date.fromisoformat(start)>dt.date.fromisoformat(end):raise SourceError('INVALID_USER_CALENDAR_DATE')
            key='fc27-plan-'+hashlib.sha256((english+'|'+start).encode()).hexdigest()[:24]
            rows.append(dict(key=key,title=title+' / '+english,event_date=start,event_end_date=end,kind=kind,summary=summary,
                             verification='user_provided',source_status='unverified',source_url=None,
                             evidence=document['source']+'；原表日期来源标注：'+original+'。'+document['source_note'],
                             upstream_observed_at=None,upstream_source_date='2026-11-03',observed_at=now.isoformat()))
        return rows

    def pages(self,scope,day,cursor=0):
        now=self.clock();context=make_daily_context(now)
        if not context.publication_allowed or day!=context.publication_date:raise SourceError('CALENDAR_OBSERVATION_TIME_REQUIRED')
        if not isinstance(self.config,dict):raise SourceError('INVALID_CALENDAR_CONFIG')
        binding=self.config.get('bindings',{}).get(game(scope))
        manual=scope=='FC27' and self.config.get('include_fc27_user_plan') is True
        if not binding and not manual:
            yield dict(rows=[],next_cursor=None,source_timezone=self.timezone,status='not_configured',quality={});return
        rows=self.user_plan(now) if manual else []
        if not binding:
            yield dict(rows=rows,next_cursor=None,source_timezone=self.timezone,status='available',quality=dict(user_plan=True,sample_kind='point_observation'));return
        quality=dict(upstream_stale=False,sample_kind='point_observation');errors={}
        try:
            published,extra=self.published(binding,scope,now)
            rows.extend(published);quality.update(extra)
        except (OSError,ValueError,KeyError,TypeError) as error:
            errors['published']=getattr(error,'code','CALENDAR_PUBLISHED_SOURCE_UNAVAILABLE')
        for source_id in binding.get('official_feeds',[]):
            try:
                for doc in self.official(source_id):
                    if binding['game_key'] not in doc['game_keys']:continue
                    if binding.get('required_pattern') and not re.search(binding['required_pattern'],doc['title']+' '+doc['text']):continue
                    if scope=='WOW_FOREVER' and binding.get('scope_confirmed') is not True:raise SourceError('WOW_FOREVER_SCOPE_CONFIRMATION_REQUIRED')
                    url=doc['source_url'];parts=urlsplit(url)
                    if parts.scheme!='https' or parts.hostname not in binding['hosts']:raise SourceError('CALENDAR_EVIDENCE_REQUIRED')
                    if any(row.get('source_url')==url for row in rows):continue
                    rows.append(dict(key='official-'+doc['document_id'],title=doc['title'],event_date=None,
                                     published_at=doc.get('published_at'),source_url=url,evidence=doc['text'],
                                     source_status='published',verification='official_source',upstream_observed_at=now.isoformat(),observed_at=now.isoformat()))
            except (OSError,ValueError,KeyError,TypeError,ImportError,http.client.HTTPException) as error:
                errors[source_id]=getattr(error,'code',type(error).__name__)
        quality.update(user_plan=manual,dated_events=sum(bool(r['event_date']) for r in rows))
        if errors:quality['source_errors']=errors
        yield dict(rows=rows,next_cursor=None,source_timezone=self.timezone,status=('partial' if rows else 'failed') if errors else 'stale' if quality['upstream_stale'] else 'available',quality=quality)

    def published(self,binding,scope,now):
        document=self.read()
        if document.get('schema_version')!=1 or document.get('status')!='succeeded' or not isinstance(document.get('events'),list):raise SourceError('CALENDAR_PUBLISHED_SOURCE_UNAVAILABLE')
        upstream=dt.datetime.fromisoformat(document['collected_at'])
        if upstream.tzinfo is None or upstream>now:raise SourceError('INVALID_CALENDAR_SOURCE_TIME')
        stale=now>=dt.datetime.fromisoformat(document['stale_after'])
        rows=[]
        for event in document['events']:
            if not isinstance(event,dict):raise SourceError('INVALID_CALENDAR_EVENT')
            if event.get('game_key')!=binding['game_key']:continue
            if binding.get('required_pattern') and not re.search(binding['required_pattern'],' '.join(str(event.get(k) or '') for k in ('title','summary','evidence'))):continue
            if scope=='WOW_FOREVER' and binding.get('scope_confirmed') is not True:raise SourceError('WOW_FOREVER_SCOPE_CONFIRMATION_REQUIRED')
            url=event.get('source_url','');parts=urlsplit(url)
            if parts.scheme!='https' or parts.username or parts.password or parts.hostname not in binding['hosts'] or not event.get('evidence') or not event.get('event_id') or not event.get('title'):raise SourceError('CALENDAR_EVIDENCE_REQUIRED')
            date=event.get('event_date')
            if date:
                dt.date.fromisoformat(date)
                if not event.get('date_evidence'):raise SourceError('CALENDAR_DATE_EVIDENCE_REQUIRED')
            rows.append(dict(key=event['event_id'],title=event['title'],summary=event.get('summary'),kind=event.get('kind'),
                             event_date=date,event_time=event.get('event_time') if date else None,timezone=event.get('timezone') if date else None,
                             published_at=event.get('published_at'),source_url=url,evidence=event['evidence'],date_evidence=event.get('date_evidence'),
                             upstream_observed_at=document['collected_at'],source_version=document.get('version'),
                             source_status='stale' if stale else 'published',observed_at=now.isoformat()))
        return rows,dict(source='existing_game_monitor',upstream_observed_at=document['collected_at'],upstream_stale=stale)
