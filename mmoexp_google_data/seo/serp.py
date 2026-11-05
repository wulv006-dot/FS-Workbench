"""Independent Bright Data Google observations; no model, SDK or daytime requests."""
import datetime as dt
import calendar as month_calendar
import hashlib
import http.client
import json
import os
import re
from urllib.parse import urlencode, urlsplit

from .contracts import BUSINESS_TZ, game, make_daily_context
from .pages import approved_url
from .sources import SourceError
from .store import encode


def google_redirect(url):
    parts=urlsplit(url)
    return parts.hostname in ('google.com','www.google.com') and parts.path=='/goto'


def condition(value):
    if (not isinstance(value, dict) or set(value)-{'keyword','country','language','device','depth','location'} or
            not isinstance(value.get('keyword'),str) or not 0 < len(value['keyword'].strip()) <= 512 or
            not isinstance(value.get('country'),str) or not re.fullmatch('[A-Z]{2}',value['country']) or
            not isinstance(value.get('language'),str) or not re.fullmatch('[a-z]{2}',value['language']) or
            value.get('device') not in ('desktop','mobile') or type(value.get('depth')) is not int or
            not 1 <= value['depth'] <= 10 or not isinstance(value.get('location',''),str) or len(value.get('location',''))>200):
        raise SourceError('INVALID_SERP_CONDITION')
    return dict(value)


def public_url(url):
    parts=urlsplit(url)
    if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password or parts.port:
        raise SourceError('INVALID_SERP_URL')
    return parts


def matches(url, prefix):
    actual, target=public_url(url),public_url(prefix)
    path=target.path.rstrip('/')
    return (actual.hostname.removeprefix('www.')==target.hostname.removeprefix('www.') and
            (not path or actual.path.lower()==path.lower() or actual.path.lower().startswith(path.lower()+'/')))


def compact(result):
    if not isinstance(result,dict) or not isinstance(result.get('organic'),list):
        raise SourceError('INVALID_SERP_RESPONSE')
    general=result.get('general',{})
    if not isinstance(general,dict):raise SourceError('INVALID_SERP_RESPONSE')
    organic=[]
    for row in result['organic']:
        if not isinstance(row,dict) or not isinstance(row.get('link'),str):raise SourceError('INVALID_SERP_ORGANIC')
        link='https://www.google.com'+row['link'] if row['link'].startswith('/goto?') else row['link']
        public_url(link)
        organic.append(dict(link=link,global_rank=row.get('global_rank'),**{k:row[k] for k in ('original_link','resolution_error') if isinstance(row.get(k),str)}))
    return dict(organic=organic,general={k:general[k] for k in ('query','detected_query','country_code','language','is_mobile') if k in general})


def parse_results(result, query, brands):
    query=condition(query); result=compact(result); general=result['general']
    for field, expected in [('query',query['keyword']),('detected_query',query['keyword']),('country_code',query['country']),('is_mobile',query['device']=='mobile')]:
        actual=general.get(field)
        if field=='country_code' and isinstance(actual,str):actual=actual.upper()
        if field in general and actual!=expected:raise SourceError('SERP_CONDITION_MISMATCH')
    if isinstance(general.get('language'),str) and re.fullmatch('[a-z]{2}',general['language']) and general['language']!=query['language']:raise SourceError('SERP_CONDITION_MISMATCH')
    # global_rank includes other SERP features. Count only top-level organic entries.
    organic=result['organic']
    if any(row['global_rank'] is not None for row in organic):
        if any(type(row['global_rank']) is not int or row['global_rank']<=0 for row in organic) or len({r['global_rank'] for r in organic})!=len(organic):raise SourceError('INVALID_SERP_ORDER')
        organic=sorted(organic,key=lambda row:row['global_rank'])
    depth=len(organic)
    rows=[]
    for brand,prefixes in brands.items():
        found=next(((i+1,row['link']) for i,row in enumerate(organic) if any(matches(row['link'],p) for p in prefixes)),None)
        uncertain=any(google_redirect(row['link']) for row in organic[:found[0] if found else depth])
        rows.append(dict(brand=brand,rank=found[0] if found and not uncertain else None,url=found[1] if found and not uncertain else None,
                         status='unresolved' if uncertain else 'found' if found else 'not_found' if depth else 'no_results',
                         effective_depth=depth,unresolved_links=sum(google_redirect(row['link']) for row in organic),**query))
    return rows


class BrightDataTransport:
    def __init__(self, core, config, limits, *, key_loader=lambda name:os.environ.get(name), post=None,
                 clock=lambda:dt.datetime.now(dt.timezone.utc),finish_margin_seconds=0,redirect=None):
        self.core,self.config,self.limits,self.key_loader=core,config,limits,key_loader
        self.clock,self.post,self.calls=clock,post or self._post,0
        self.margin=finish_margin_seconds
        self.redirect,self.resolution_calls=redirect or self._redirect,0

    def remaining(self):
        local=self.clock().astimezone(BUSINESS_TZ)
        return (local.replace(hour=6,minute=30,second=0,microsecond=0)-local).total_seconds()-self.margin

    def _post(self, url, token):
        remaining=self.remaining()
        if remaining<=0:raise SourceError('NIGHT_DEADLINE')
        connection=http.client.HTTPSConnection('api.brightdata.com',timeout=min(remaining,self.limits['connect_seconds']))
        try:
            connection.connect(); connection.sock.settimeout(min(remaining,self.limits['idle_seconds']))
            connection.request('POST','/request',body=encode(dict(zone=self.config['zone'],url=url,format='raw')),
                               headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            response=connection.getresponse()
            if response.status!=200:raise SourceError('HTTP_'+str(response.status))
            content=bytearray()
            while True:
                if self.remaining()<=0:raise SourceError('SUBMISSION_UNKNOWN')
                chunk=response.read(65536)
                if not chunk:break
                if len(content)+len(chunk)>self.limits['response_emergency_bytes']:raise SourceError('SERP_RESPONSE_EMERGENCY_SIZE')
                content.extend(chunk)
            return compact(json.loads(content)), response.getheader('x-brd-request-id')
        finally:connection.close()

    def _redirect(self,url):
        parts=public_url(url)
        if not google_redirect(url) or self.remaining()<=0:raise SourceError('GOOGLE_REDIRECT_NOT_ALLOWED')
        connection=http.client.HTTPSConnection(parts.hostname,timeout=min(self.remaining(),self.limits['connect_seconds']))
        try:
            connection.connect();connection.sock.settimeout(min(self.remaining(),self.limits['idle_seconds']))
            connection.request('GET',parts.path+'?'+parts.query,headers={'User-Agent':'Mozilla/5.0','Accept':'text/html','Accept-Encoding':'identity'})
            response=connection.getresponse();location=response.getheader('Location')
            if response.status not in (301,302,303,307,308) or not location:raise SourceError('GOOGLE_REDIRECT_UNRESOLVED')
            public_url(location)
            if google_redirect(location):raise SourceError('GOOGLE_REDIRECT_UNRESOLVED')
            return location  # Do not follow to the destination website.
        finally:connection.close()

    def resolve_result(self,result,ident):
        result=compact(result);changed=False
        for row in result['organic']:
            if not google_redirect(row['link']) or row.get('resolution_error'):continue
            changed=True
            try:
                if self.remaining()<=0:raise SourceError('NIGHT_DEADLINE')
                self.resolution_calls+=1
                target=self.redirect(row['link']);public_url(target)
                if google_redirect(target):raise SourceError('GOOGLE_REDIRECT_UNRESOLVED')
                row['original_link'],row['link']=row['link'],target
            except (OSError,http.client.HTTPException,ValueError) as error:
                row['resolution_error']=getattr(error,'code','GOOGLE_REDIRECT_UNRESOLVED')
        if changed:
            with self.core.db() as db:db.execute("UPDATE provider_requests SET response=? WHERE request_key=? AND state='completed'",(encode(result),ident))
        return result

    def __call__(self, query, scope, day):
        context=make_daily_context(self.clock())
        if not context.publication_allowed or self.remaining()<=0 or day!=context.publication_date:raise SourceError('SERP_OBSERVATION_TIME_REQUIRED')
        condition(query);game(scope)
        auth=dict(self.config.get('authorization',{}))
        if not isinstance(auth.get('reference'),str) or not auth['reference'].strip():raise SourceError('SERP_CONSUMPTION_AUTHORIZATION_REQUIRED')
        if auth.get('renewal')=='monthly_free_credits':
            today=dt.date.fromisoformat(context.publication_date)
            auth['reference']=str(auth.get('reference',''))+':'+today.strftime('%Y-%m')
            auth['valid_until']=today.replace(day=month_calendar.monthrange(today.year,today.month)[1]).isoformat()
        if (not auth.get('reference') or not isinstance(auth.get('valid_until'),str) or
                dt.date.fromisoformat(context.publication_date)>dt.date.fromisoformat(auth['valid_until']) or type(auth.get('request_allowance')) is not int or auth['request_allowance']<=0):
            raise SourceError('SERP_CONSUMPTION_AUTHORIZATION_REQUIRED')
        token=self.key_loader(self.config.get('api_key_env',''))
        if not self.config.get('zone') or not isinstance(token,str) or not token.strip() or '\n' in token or '\r' in token:
            raise SourceError('BRIGHT_DATA_CREDENTIAL_REFERENCE_REQUIRED')
        ident=hashlib.sha256(encode([auth['reference'],day,query]).encode()).hexdigest()
        with self.core.db() as db:
            old=db.execute('SELECT state,response FROM provider_requests WHERE request_key=?',(ident,)).fetchone()
            if not old:
                used=db.execute('SELECT COUNT(*) FROM provider_requests WHERE authorization=?',(auth['reference'],)).fetchone()[0]
                if used>=auth['request_allowance']:raise SourceError('SERP_AUTHORIZED_ALLOWANCE_EXHAUSTED')
                db.execute('INSERT INTO provider_requests VALUES (?,?,?,?,?,?,?,?,?)',(ident,auth['reference'],day,'pending',None,None,None,auth['valid_until'],self.clock().isoformat()))
        if old:
            if old[0]=='completed':return self.resolve_result(json.loads(old[1]),ident)
            raise SourceError('SUBMISSION_UNKNOWN' if old[0] in ('pending','unknown') else 'SERP_PREVIOUS_REQUEST_FAILED')
        params=dict(q=query['keyword'],gl=query['country'].lower(),hl=query['language'],brd_mobile='0' if query['device']=='desktop' else '1',brd_json='1')
        if query.get('location'):params['uule']=query['location']
        self.calls+=1
        try:
            result,request_id=self.post('https://www.google.com/search?'+urlencode(params),token)
            result=compact(result)
        except (OSError,http.client.HTTPException,ValueError) as error:
            code=getattr(error,'code','SUBMISSION_UNKNOWN')
            state='failed' if code.startswith('HTTP_') else 'unknown'
            with self.core.db() as db:db.execute('UPDATE provider_requests SET state=?,error=? WHERE request_key=?',(state,code,ident))
            failure=SourceError(code)
            failure.stop_source=code in ('HTTP_400','HTTP_401','HTTP_402','HTTP_403','HTTP_410','HTTP_422','HTTP_429')
            raise failure from None
        with self.core.db() as db:db.execute('UPDATE provider_requests SET state=?,request_id=?,response=? WHERE request_key=?',('completed',request_id,encode(result),ident))
        return self.resolve_result(result,ident)


class SerpSource:
    name='serp'
    timezone='Asia/Shanghai'
    is_observation=True

    def __init__(self, config, request, *, clock=lambda:dt.datetime.now(dt.timezone.utc)):
        self.config,self.request,self.clock=config,request,clock

    def pages(self, scope, day, cursor=0):
        context=make_daily_context(self.clock())
        if not context.publication_allowed or day!=context.publication_date:raise SourceError('SERP_OBSERVATION_TIME_REQUIRED')
        if not isinstance(self.config,dict):raise SourceError('INVALID_SERP_CONFIG')
        project=self.config.get('projects',{}).get(game(scope),{})
        if not isinstance(project,dict):raise SourceError('INVALID_SERP_PROJECT')
        queries=project.get('conditions',[]) if self.config.get('enabled') is True else []
        brands=project.get('brands',{})
        if not queries or not brands:
            yield dict(rows=[],next_cursor=None,source_timezone=self.timezone,status='not_configured',quality={});return
        if not isinstance(queries,list) or not isinstance(brands,dict):raise SourceError('INVALID_SERP_PROJECT')
        for brand,prefixes in brands.items():
            if not isinstance(brand,str) or not isinstance(prefixes,list) or not prefixes:raise SourceError('INVALID_SERP_BRAND')
            for prefix in prefixes:
                public_url(prefix)
                if brand=='MMOEXP':approved_url(scope,prefix)
        seen=set();failed=False
        for index,query in enumerate(queries):
            condition(query);key=encode(query)
            if key in seen:raise SourceError('DUPLICATE_SERP_CONDITION')
            seen.add(key)
            if index<cursor:continue
            if not make_daily_context(self.clock()).publication_allowed:raise SourceError('NIGHT_DEADLINE')
            observed=self.clock().isoformat()
            try:
                rows=parse_results(self.request(query,scope,day),query,brands)
                failed=failed or any(row['status']=='unresolved' for row in rows)
            except (OSError,ValueError,RuntimeError,TypeError,KeyError) as error:
                if getattr(error,'stop_source',False):raise
                failed=True
                rows=[dict(brand=brand,rank=None,url=None,status='failed',effective_depth=None,error=getattr(error,'code',type(error).__name__),**query) for brand in brands]
            for row in rows:
                row.update(engine='google',provider='brightdata',observed_at=observed,
                           key=hashlib.sha256(encode([query,row['brand']]).encode()).hexdigest())
            yield dict(rows=rows,next_cursor=index+1 if index+1<len(queries) else None,source_timezone=self.timezone,
                       status='partial' if failed else 'available',quality=dict(sample_kind='point_observation',requested_conditions=len(queries)))
