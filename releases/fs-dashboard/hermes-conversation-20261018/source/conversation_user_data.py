"""Trusted native run -> existing FS users/live consumers. No caller identities in tools."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from b2_customer_followup import describe_customer, observe_live_orders, observation_from_a2

TEXT={'type':'string'}
REFERENCE={'snapshot_id':TEXT,'customer_id':TEXT}
CUSTOMER_SCOPE_HELP=('Global, series and default queries remain available for aggregates. Customer investigation requires an explicit site or project snapshot. '
    'Choose scope and scope_id from customer_investigation.scope_choices in fs_get_data_catalog, call fs_query_user_analytics with both fields, '
    'then use its new snapshot_id for fs_customer_candidates and fs_describe_customer. Never reuse or silently narrow a global/series snapshot.')


class _CustomerScopeRequired(ValueError):
    pass


TOOLS={
    'fs_track_customer':(
        'Only for an explicit user request to persist customer follow-up. create requires explicit_goal=true, objective and recheck_at. step requires expected_revision and authorized site/project frozen snapshot/customer. '+CUSTOMER_SCOPE_HELP+' Ordinary questions use fs_describe_customer. This reserves the original follow-up ID through the existing goal CAS; it never authorizes outreach, pricing or other business actions.',
        {'operation':{'type':'string','enum':['create','step','status','pause','stop']},
         **REFERENCE,'goal_id':TEXT,'objective':TEXT,'recheck_at':TEXT,
         'explicit_goal':{'type':'boolean'},'expected_revision':{'type':'integer','minimum':0}},['operation']),
    'fs_customer_candidates':(
        'Read private customer candidates from an explicit site/project frozen snapshot. Global/series snapshots return scope-selection guidance, not customer rows. '+CUSTOMER_SCOPE_HELP+' Keep coverage, cursor and policy. Opaque IDs are not access grants.',
        {'snapshot_id':TEXT,'group':{'type':'string','enum':['known_pool','entered_silent','high_value_entered_silent']},
         'cursor':TEXT,'limit':{'type':'integer','minimum':1,'maximum':200}},['snapshot_id']),
    'fs_describe_customer':(
        'Explain one authorized opaque customer from an explicit site/project snapshot using FS frozen lifecycle facts, policy, coverage and evidence. '+CUSTOMER_SCOPE_HELP+' No goal or business action is created; period-first is not lifetime Day0.',
        dict(REFERENCE),list(REFERENCE)),
    'fs_observe_customer_orders':(
        'Observe bounded recent orders for the same authorized customer. Host resolves the private email; never supply one. Serial 20-row pages, 28-day windows, 365-day boundary. Partial live observations are not a frozen history or valid-purchase count.',
        dict(REFERENCE,site_id=TEXT,game_id=TEXT,start=TEXT,end_exclusive=TEXT,
             max_pages={'type':'integer','minimum':1,'maximum':2000}),
        [*REFERENCE,'site_id','game_id','start','end_exclusive','max_pages']),
}

COUPON_TOOLS={
    'fs_coupon_candidates':('Read exactly one original coupon page for project site266. Returns IDs/status/counters only, partial single-page coverage and next_page; no implicit next page or discount query.',
        {'page':{'type':'integer','minimum':1,'maximum':500},'limit':{'type':'integer','minimum':1,'maximum':200}},[]),
    'fs_coupon_detail':('Read one project coupon metadata/hash and original brief-edit eligibility. No coupon code or brief body; no business write.',{'native_id':TEXT},['native_id']),
    'fs_edit_coupon_brief':('Change only an existing disabled, unused project coupon brief through the original executor. Requires exact external business approval bound by the host to this run, operation ID, object, before hash, text and time. Model approval or admin access is insufficient. Preserve original ID on unknown; tool/Goal completion is not business confirmation.',
        {key:TEXT for key in ('native_id','operation_id','before_hash','brief')},['native_id','operation_id','before_hash','brief']),
    'fs_grant_coupon':('Send at most one reviewed template coupon to the one privately approved recipient. Host approval fixes this run, site/template, original batch and operation ID, recipient and expiry; none come from model identity claims. Pending/unknown: use fs_coupon_operation with the same operation_id, never send again or create a replacement ID. Business success requires the original single-recipient result, not tool/Goal completion.',
        {'operation_id':TEXT},['operation_id']),
    'fs_coupon_operation':('Look up the same externally approved original coupon operation. reconcile uses only the original executor readback/fence, never another mutation POST.',
        {'operation_id':TEXT,'reconcile':{'type':'boolean'}},['operation_id']),
}
TOOLS.update(COUPON_TOOLS)


def authorize_campaign(owner,mutation):
    from user_runtime import authorize
    if authorize(owner,{'scope':'site','scope_id':'266'},True,resource='/dashboard/analytics/') is not True:return False
    import rbac
    endpoint='/dashboard/analytics/campaigns/analytics/api/center/backend-'+('mutate' if mutation else 'read')
    return rbac.authorize(rbac.load_policy(),owner,'POST',endpoint)==200


CAMPAIGN_APPROVAL_FILE=Path('/var/lib/fs-campaign-dashboard/backend/native-coupon-approval.json')


def _read_campaign_approval():
    """The one root-controlled file; shared by consumption and pre-ready binding."""
    path=CAMPAIGN_APPROVAL_FILE
    if not path.exists():return None,None
    parents=[]
    for parent in path.parents:
        info=parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or (info.st_uid,info.st_gid)!=(0,0) or info.st_mode&0o022):
            raise PermissionError('business_authorization_file_boundary')
        parents.append((parent,info.st_dev,info.st_ino,info.st_uid,info.st_gid,info.st_mode))
    fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink','st_uid','st_gid','st_mode')
    before=path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>16384 or
            (before.st_uid,before.st_gid,stat.S_IMODE(before.st_mode))!=(0,0,0o600)):
        raise PermissionError('business_authorization_file_boundary')
    with os.fdopen(os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)),'rb') as source:
        opened=os.fstat(source.fileno())
        if any(getattr(before,k)!=getattr(opened,k) for k in fields):raise PermissionError('business_authorization_file_changed')
        raw=source.read(16385)
        if any(getattr(before,k)!=getattr(os.fstat(source.fileno()),k) for k in fields):raise PermissionError('business_authorization_file_changed')
    after=path.lstat()
    if len(raw)!=before.st_size or any(getattr(before,k)!=getattr(after,k) for k in fields):
        raise PermissionError('business_authorization_file_changed')
    for parent,*identity in parents:
        now=parent.lstat()
        if [now.st_dev,now.st_ino,now.st_uid,now.st_gid,now.st_mode]!=identity:
            raise PermissionError('business_authorization_file_changed')
    return json.loads(raw),(tuple(getattr(before,k) for k in fields),tuple(tuple(r) for r in parents))


def campaign_approval(binding,operation_id):
    """Consume a finalized user approval, never model-supplied authority."""
    value,_=_read_campaign_approval()
    if value is None:return None
    if (type(value) is not dict or type(value.get('binding')) is not dict or set(value['binding'])!=set(binding) or
            any(value['binding'].get(k)!=binding[k] for k in ('owner','conversation_id','session_id')) or
            type(value.get('request')) is not dict or value['request'].get('operation_id')!=operation_id):
        raise PermissionError('business_authorization_mismatch')
    # approval() requires all seven fields for writes; a later authorized turn
    # in this same session may only look up/reconcile the original operation.
    return value


@contextmanager
def _campaign_approval_lock(expected):
    """Lock the existing approval inode, never create another lock or queue."""
    import fcntl
    path=CAMPAIGN_APPROVAL_FILE
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise PermissionError('business_authorization_file_locked') from None
        info=os.fstat(fd)
        fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink','st_uid','st_gid','st_mode')
        if tuple(getattr(info,k) for k in fields)!=expected[0]:
            raise PermissionError('business_authorization_file_changed')
        yield
    finally:os.close(fd)


def prepare_campaign_approval(native,binding):
    """Bind one trusted intent after real run persistence, before worker ready.

    Intent matching is not authorization: only the secure root file supplies
    the exact request/source/time, and the original consumer checks IAM again.
    Unrelated or unreadable records never become an ordinary-chat prerequisite.
    """
    try:value,expected=_read_campaign_approval()
    except (OSError,ValueError,PermissionError):return False
    if type(value) is not dict:return False
    if 'intent' in value:
        intent=value['intent']
        if type(intent) is not dict:return False
        with native.store.db() as db:
            native.store._owned(db,binding['owner'],binding['conversation_id'])
            turn=db.execute('SELECT input_sha256 FROM turns WHERE id=? AND conversation_id=?',
                (binding['turn_id'],binding['conversation_id'])).fetchone()
        if turn is None:raise PermissionError('business_authorization_binding')
        actual={k:binding[k] for k in ('owner','conversation_id','session_id')}
        actual['input_sha256']=turn['input_sha256']  # Original stored request normalization; never caller hash.
        if any(intent.get(k)!=v for k,v in actual.items()):return False
        if set(intent)!=set(actual):raise PermissionError('business_authorization_invalid')
        final={k:v for k,v in value.items() if k!='intent'};final['binding']=deepcopy(binding)
        if type(final.get('request')) is not dict or final['request'].get('action')!='coupon_grant':
            raise PermissionError('business_authorization_mismatch')
    elif value.get('binding')==binding:final=value
    else:return False  # A finalized record must never be reassigned to another run.
    sys.path.insert(0,'/opt/fs-campaign-dashboard/backend')
    actions=NativeCouponActions(native,None,None,authorize=authorize_campaign,approval_source=lambda *args:final)
    if type(final.get('request')) is not dict:raise PermissionError('business_authorization_invalid')
    operation_id=final['request'].get('operation_id')
    actions.approval(binding,operation_id,write=True)
    with native.service.lock,_campaign_approval_lock(expected):
        current,identity=_read_campaign_approval()
        if identity!=expected or current!=value:raise PermissionError('business_authorization_file_changed')
        actions.approval(binding,operation_id,write=True)
        if 'intent' in value:
            from controller import atomic
            atomic(CAMPAIGN_APPROVAL_FILE,final,mode=0o600)
            saved,_=_read_campaign_approval()
            if saved!=final:raise PermissionError('business_authorization_file_changed')
        actions.guard(binding,True)
    return True


class NativeCouponActions:
    """Original writer/ledger, with the existing private host approval source."""
    def __init__(self,native,backend,reader_factory,*,authorize,approval_source=None,clock=None):
        self.native,self.backend,self.reader_factory=native,backend,reader_factory
        self.authorize,self.approval_source=authorize,approval_source
        self.clock=clock or (lambda:datetime.now(timezone.utc))

    @classmethod
    def runtime(cls,native,binding):
        if native.authorized(binding) is not True or authorize_campaign(binding['owner'],False) is not True:
            raise PermissionError('native_campaign_access_denied')
        sys.path.insert(0,'/opt/fs-campaign-dashboard/backend')
        from campaign_backend.services import BackendServices
        from campaign_backend.adapters import AdminRead
        # An explicitly composed host callback or the one root-controlled user
        # approval file is trusted. Missing records still deny every mutation.
        return cls(native,BackendServices.from_environment(),AdminRead.from_shared_session,
            authorize=authorize_campaign,approval_source=getattr(native.service,'campaign_approval',None) or campaign_approval)

    def guard(self,binding,mutation=False):
        if self.native.authorized(binding) is not True or self.authorize(binding['owner'],mutation) is not True:
            raise PermissionError('native_campaign_access_denied')

    def handle(self,binding,request):
        mutation=request['action'] in ('benefit_edit','coupon_grant','operation_reconcile')
        self.guard(binding,mutation)
        def reader():
            self.guard(binding,mutation)
            return self.reader_factory()
        trusted={}
        if request['action']=='coupon_grant':
            trusted['grant_authorize']=lambda payload:self.approval(binding,request['operation_id'],write=True)==payload
        result=self.backend.handle(request,reader,**trusted)
        self.guard(binding,mutation)
        return result

    def approval(self,binding,operation_id,*,write):
        self.guard(binding,write)
        record=self.approval_source(binding,operation_id) if callable(self.approval_source) else None
        if type(record) is not dict:raise PermissionError('business_authorization_required')
        record=deepcopy(record)
        if set(record)!={'binding','request','valid_from','valid_until','authority_ref'}:
            raise PermissionError('business_authorization_invalid')
        old=record['binding'];request=record['request']
        if (type(old) is not dict or (old!=binding if write else any(old.get(k)!=binding[k] for k in ('owner','conversation_id','session_id')))
                or type(request) is not dict or request.get('operation_id')!=operation_id
                or type(record['authority_ref']) is not str or not record['authority_ref']):
            raise PermissionError('business_authorization_mismatch')
        if request.get('action')=='coupon_grant':
            from campaign_backend.coupon_grant import validate
            try:validate(request)
            except ValueError:raise PermissionError('business_authorization_mismatch') from None
        elif (set(request)!={'action','site_id','kind','native_id','operation_id','before_hash','changes'} or
                request['action']!='benefit_edit' or request['site_id']!='266' or request['kind']!='coupon' or
                type(request['changes']) is not dict or set(request['changes'])!={'brief'}):
            raise PermissionError('business_authorization_mismatch')
        try:
            start=datetime.fromisoformat(record['valid_from'].replace('Z','+00:00'))
            end=datetime.fromisoformat(record['valid_until'].replace('Z','+00:00'));now=self.clock()
            valid=start.tzinfo is not None and end.tzinfo is not None and start<end and start<=now and (not write or now<end)
        except (ValueError,TypeError,AttributeError):valid=False
        if not valid:raise PermissionError('business_authorization_expired')
        return request

    @staticmethod
    def receipt(value,*,grant=False):
        # The original ledger/coupon adapter owns success audit and full native
        # readback. Keep its operation identity; no synthetic Goal success receipt.
        out={k:value[k] for k in ('operation_id','state','dispatched','payload_hash','dispatch_state','created_at','updated_at',
            'object_busy','requested_operation_id','recovery_operation_id','recovery_operation_ids') if k in value}
        result=value.get('result') or {}
        out['result']={k:result[k] for k in ('state','reason_code','upstream_ref','dispatch_state') if k in result}
        if grant:
            # Native job/member-coupon IDs stay in the private original ledger.
            # The operation ID suffices for every authorized status/reconcile call.
            out['result'].pop('upstream_ref',None)
            out['business_progress']='pending' if result.get('reason_code') in ('GRANT_TASK_PENDING','GRANT_PENDING_REGISTER') else value['state']
        out['business_confirmed']=value['state']=='confirmed'
        return out

    def call(self,binding,name,args):
        self.guard(binding)
        if type(args) is not dict or name not in COUPON_TOOLS:raise ValueError('native_coupon_fields')
        _,properties,required=COUPON_TOOLS[name]
        if set(args)-set(properties) or not set(required)<=set(args):raise ValueError('native_coupon_fields')
        for key,value in args.items():
            if type(value) is not {'integer':int,'boolean':bool,'string':str}[properties[key]['type']]:
                raise ValueError('native_coupon_value')
        fixed={'site_id':'266','kind':'coupon'}
        if name=='fs_coupon_candidates':return self.handle(binding,dict(action='coupon_candidates',site_id='266',**args))
        if name=='fs_coupon_detail':
            view=self.handle(binding,dict(fixed,action='benefit_detail',**args));fields=view['fields']
            if str(fields.get('site_id'))!='266':raise PermissionError('native_coupon_scope')
            brief=fields.get('brief')
            if type(brief) is not str:raise ValueError('native_coupon_detail')
            return dict(native_id=view['native_id'],before_hash=view['before_hash'],
                fields={k:fields[k] for k in ('site_id','game_id','goods_id','status','fetch_qty','used_qty')},
                brief_sha256=hashlib.sha256(brief.encode()).hexdigest(),brief_chars=len(brief),editability=view['editability'])
        request=self.approval(binding,args['operation_id'],write=name in ('fs_edit_coupon_brief','fs_grant_coupon'))
        if name=='fs_coupon_operation':
            return self.receipt(self.handle(binding,dict(action='operation_reconcile' if args.get('reconcile') else 'operation_lookup',site_id='266',operation_id=args['operation_id'])),grant=request['action']=='coupon_grant')
        if name=='fs_grant_coupon':
            if request['action']!='coupon_grant' or self.approval(binding,args['operation_id'],write=True)!=request:
                raise PermissionError('business_authorization_mismatch')
            return self.receipt(self.handle(binding,request),grant=True)
        actual=dict(fixed,action='benefit_edit',native_id=args['native_id'],operation_id=args['operation_id'],
                    before_hash=args['before_hash'],changes={'brief':args['brief']})
        if actual!=request:raise PermissionError('business_authorization_mismatch')
        from campaign_backend.core import ContractError
        try:existing=self.handle(binding,dict(action='operation_lookup',site_id='266',operation_id=args['operation_id']))
        except ContractError as error:
            if str(error)!='OPERATION_NOT_FOUND':raise
            existing=None
        if existing is None:
            view=self.handle(binding,dict(fixed,action='benefit_detail',native_id=args['native_id']))
            if (any(str(view['fields'].get(k))!='0' for k in ('status','fetch_qty','used_qty'))
                    or 'brief' not in view['editability']['allowed_changes'] or str(view['fields'].get('site_id'))!='266'):
                raise PermissionError('native_coupon_not_disabled_unused')
        if self.approval(binding,args['operation_id'],write=True)!=actual:
            raise PermissionError('business_authorization_mismatch')
        return self.receipt(self.handle(binding,actual))


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def fact_version(receipt,now):
    """Scope + identity + policy + data + effective cutoff, never capture time."""
    observation=observation_from_a2(receipt,now=now)
    source=receipt['source'];query=source['query']
    version={key:source.get(key) for key in ('scope_version','identity_version','policy_version','data_version')}
    if any(v is None or v=='' for v in version.values()):raise ValueError('customer_fact_version_missing')
    version.update(scope={key:query[key] for key in ('scope','scope_id')},
                   query={key:query[key] for key in ('start','end_exclusive','as_of','state_basis') if key in query},
                   effective_cutoff=observation.as_of.isoformat())
    return hashlib.sha256(canonical(version).encode()).hexdigest()


class NativeUserData:
    def __init__(self,native,service,*,live_get=None,run_source=None,clock=None):
        self.native,self.service=native,service
        self.live_get,self.run_source=live_get,run_source
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.pending={}

    @classmethod
    def runtime(cls,native):
        from user_runtime import build
        # Reuse the already constructed HTTP host and its single Admin slot.
        # Importing range_api again would create another service/pool.
        host=sys.modules.get('__main__')
        live=getattr(host,'get_live_orders',None)
        admission=getattr(host,'LIVE_ADMIN',None)
        return cls(native,build(),live_get=live,run_source=getattr(admission,'run',None))

    def guard(self,binding,scope,private=False):
        if (self.native.authorized(binding) is not True or
                self.service.authorizer(binding['owner'],scope,private) is not True):
            raise PermissionError('native_user_scope_unavailable')
        return True

    def context(self,binding,snapshot_id):
        from a2_query_context import QueryContext
        self.guard(binding,{'scope':'global','scope_id':''})
        # Read the authoritative frozen query; a model's scope cannot override it.
        public=self.service.query({'snapshot_id':snapshot_id},binding['owner'])
        scope={key:public['query'][key] for key in ('scope','scope_id')}
        context=QueryContext(self.service,binding['owner'],scope,
            lambda owner,selected: owner==binding['owner'] and selected==scope and self.guard(binding,scope))
        if not context.configured():
            self.guard(binding,scope,True)  # A scope mismatch must not hide an actual private-access denial.
            raise _CustomerScopeRequired('customer_snapshot_scope_required')
        context.guard()
        return context

    def customer_path(self,binding,scope=None):
        choices=[]
        for kind,key in (('site','sites'),('project','projects')):
            for identity in self.service.store.config[key]:
                selected={'scope':kind,'scope_id':identity}
                if (self.service.authorizer(binding['owner'],selected,False) is True and
                        self.service.authorizer(binding['owner'],selected,True) is True):choices.append(selected)
        return dict(snapshot_usable=scope in choices,scope_choices=choices,
                    query_required_fields=['scope','scope_id'],instruction=CUSTOMER_SCOPE_HELP)

    def call(self,binding,name,args):
        if name in COUPON_TOOLS:
            if getattr(self,'campaign',None) is None:self.campaign=NativeCouponActions.runtime(self.native,binding)
            return self.campaign.call(binding,name,args)
        self.guard(binding,{'scope':'global','scope_id':''})
        if not isinstance(args,dict):raise ValueError('native_user_tool_fields')
        if name=='fs_query_user_analytics':
            # The pre-ready approval hook must not initialize analytics on
            # ordinary native turns; load these original consumers on use.
            from a2_query_context import QueryContext
            from user_tools import invoke
            # A narrow frozen snapshot must be created with the same narrow
            # authorizer that will read it later; no global matrices are hidden
            # after having created a global-dependent recipe.
            scope={key:args.get(key) for key in ('scope','scope_id')}
            if scope['scope'] in ('site','project') and not args.get('snapshot_id') and not args.get('evidence_id'):
                context=QueryContext(self.service,binding['owner'],scope,
                    lambda owner,selected:owner==binding['owner'] and selected==scope and self.guard(binding,scope))
                section=args.get('section','summary')
                query={k:v for k,v in args.items() if k not in ('scope','scope_id','section','view')}
                receipt=context.aggregate(query,section)
                value=dict(receipt.get('data',{}),source=receipt.get('source'),
                           evidence_ref=receipt.get('evidence_ref'),status=receipt['status'])
            else:value=invoke(self.service,binding['owner'],args)
            query=value.get('query') or (value.get('source') or {}).get('query') or {}
            value['customer_investigation']=self.customer_path(binding,{k:query.get(k) for k in ('scope','scope_id')})
        elif name=='fs_get_data_catalog':
            if args:raise ValueError('native_user_tool_fields')
            catalog=self.service.catalog(binding['owner'])
            value={'user_analytics':dict(catalog,customer_investigation=self.customer_path(binding))}
        else:
            if name not in TOOLS:raise PermissionError('native_user_tool_unavailable')
            _,properties,required=TOOLS[name]
            if set(args)-set(properties) or not set(required)<=set(args):raise ValueError('native_user_tool_fields')
            for key,part in args.items():
                expected={'integer':int,'boolean':bool,'string':str}[properties[key]['type']]
                if type(part) is not expected:raise ValueError('native_user_tool_value')
            if name=='fs_track_customer':
                value=self.track(binding,args)
                self.guard(binding,{'scope':'global','scope_id':''})
                return value
            try:context=self.context(binding,args['snapshot_id'])
            except _CustomerScopeRequired:
                value=dict(status='unavailable',reason='customer_snapshot_scope_required',snapshot_id=args['snapshot_id'],
                           customer_investigation=self.customer_path(binding))
                self.guard(binding,{'scope':'global','scope_id':''})
                return value
            if name=='fs_customer_candidates':value=context.candidates(**args)
            elif name=='fs_describe_customer':value=describe_customer(context,**args,now=self.clock())
            else:
                selected={key:args[key] for key in ('snapshot_id','customer_id','site_id','game_id','start','end_exclusive')}
                fetch=self.customer_fetch(binding,**selected)
                value=observe_live_orders(fetch,**{k:v for k,v in args.items() if k!='snapshot_id'},now=self.clock())
        self.guard(binding,{'scope':'global','scope_id':''})
        return value

    def read(self,binding,path,params):
        self.guard(binding,{'scope':'global','scope_id':''})
        fields={'/range':{'mode','profile','start','end','grain','snapshotId'},
                '/advisor':{'mode','structure','profile','start','end','group_by','status','product_id'}}
        if (path not in fields or type(params) is not dict or set(params)-fields[path] or
                any(type(v) not in (str,int) for v in params.values())):
            raise ValueError('native_fs_read_fields')
        from user_runtime import authorize
        resource='/dashboard/analytics/' if path=='/range' else '/dashboard/data-tools/'
        if authorize(binding['owner'],{'scope':'global','scope_id':''},resource=resource) is not True:
            raise PermissionError('native_fs_resource_denied')
        host=sys.modules.get('__main__')
        if path=='/range':
            read=getattr(host,'get_range',None)
            if not callable(read):raise RuntimeError('native_fs_source_unavailable')
            status,value=read({k:[str(v)] for k,v in params.items()})
        else:
            read=getattr(getattr(host,'ADVISOR',None),'get',None)
            if not callable(read):raise RuntimeError('native_fs_source_unavailable')
            status,value=read({k:[str(v)] for k,v in params.items()},binding['owner'])
        self.guard(binding,{'scope':'global','scope_id':''})
        if authorize(binding['owner'],{'scope':'global','scope_id':''},resource=resource) is not True:
            raise PermissionError('native_fs_resource_denied')
        if status>=400:raise RuntimeError('native_fs_http_'+str(status))
        return value

    def customer_fetch(self,binding,snapshot_id,customer_id,site_id,game_id,start,end_exclusive):
        context=self.context(binding,snapshot_id);scope=deepcopy(context.scope)
        if (site_id not in self.service.store.config['sites'] or game_id not in self.service.store.config['projects'] or
                scope['scope']=='site' and scope['scope_id']!=site_id or
                scope['scope']=='project' and scope['scope_id']!=game_id):
            raise PermissionError('native_live_scope_mismatch')
        def identity():
            self.guard(binding,scope,True)
            detail=self.service.detail({'snapshot_id':snapshot_id,'customer_id':customer_id},binding['owner'])
            if not any(str(row['site'])==site_id and str(row['project_id'])==game_id for row in detail['orders']):
                raise PermissionError('native_live_customer_scope_mismatch')
            return detail['email']
        email=identity()
        begin,end=date.fromisoformat(start),date.fromisoformat(end_exclusive)
        def fetch(query):
            expected={'site_id','game_id','start','end_exclusive'}
            if (type(query) is not dict or not expected<=set(query) or set(query)-expected-{'cursor'} or
                    query['site_id']!=site_id or query['game_id']!=game_id or
                    not begin<=date.fromisoformat(query['start'])<date.fromisoformat(query['end_exclusive'])<=end):
                raise PermissionError('native_live_query_mismatch')
            if identity()!=email:raise PermissionError('native_live_customer_changed')
            if not callable(self.live_get) or not callable(self.run_source):raise RuntimeError('native_live_admission_unavailable')
            from admin_live_dispatch import private_body_params
            # Exact existing private POST body validator. Email never enters a URL,
            # model arguments, handoff, evidence reference or returned page.
            params=private_body_params(canonical(dict(query,customer_email=email)).encode())
            def admitted(operation,timeout):
                def checked():
                    if identity()!=email:raise PermissionError('native_live_customer_changed')
                    return operation()
                return self.run_source(checked,timeout)
            status,page=self.live_get(params,binding['owner'],run_source=admitted)
            if status!=206:raise RuntimeError('native_live_http_'+str(status))
            if identity()!=email:raise PermissionError('native_live_customer_changed')
            rows=page.get('data')
            if (not isinstance(rows,list) or len(rows)>20 or page.get('observed_page_rows')!=len(rows) or
                    any(not isinstance(row,dict) or row.get('customer_email')!=email for row in rows)):
                raise PermissionError('native_live_customer_projection')
            return {key:deepcopy(page[key]) for key in ('status','semantics','complete','next_cursor','limitation','observed_page_rows') if key in page} | {
                'data':[{key:row.get(key) for key in ('status','pay_status')} for row in rows]}
        return fetch

    def version(self,binding,snapshot_id,customer_id):
        receipt=self.context(binding,snapshot_id).timeline(snapshot_id,customer_id,limit=1)
        return fact_version(receipt,self.clock())

    def goal_authorized(self,owner,scope_ref):
        if self.native.hermes.authorizer(owner) is not True:return False
        ref=json.loads(scope_ref)
        if type(ref) is not dict or set(ref)!={'scope','snapshot_id','customer_id'}:return False
        if self.service.authorizer(owner,ref['scope'],True) is not True:return False
        public=self.service.query({'snapshot_id':ref['snapshot_id']},owner)
        if {k:public['query'][k] for k in ('scope','scope_id')}!=ref['scope']:return False
        self.service.detail({k:ref[k] for k in ('snapshot_id','customer_id')},owner)
        return True

    def _goals(self,owner,cid):
        from conversation_goals import ConversationGoals
        from conversation_goal_tasks import ConversationGoalTasks
        from b2_goal_host import GoalHost
        goals=ConversationGoals(self.native.store,owner,cid,self.goal_authorized)
        queue=ConversationGoalTasks(self.native.hermes.tasks,owner,cid,self.goal_authorized,
                                    expected_path=self.native.hermes.root/'tasks.sqlite3')
        data=self;queued=[]
        class Dispatcher:
            def lookup(_,*,binding):
                receipt=queue.lookup(binding=binding)
                if receipt['status']=='not_found':return receipt
                with queue._db() as db:
                    _,row=queue._lookup(db,binding)
                    text=row['handoff_json']
                with data.native.store.db() as db:
                    data.native.store._owned(db,owner,cid)
                    turn=db.execute('SELECT id,state,input_sha256 FROM turns WHERE conversation_id=? AND request_id=?',
                                    (cid,binding['request_id'])).fetchone()
                if turn is None:return receipt
                if turn['input_sha256']!=hashlib.sha256(text.encode()).hexdigest():raise ValueError('customer_goal_turn_conflict')
                state={'preparing':'queued','dispatch_unknown':'unknown','stopping':'running'}.get(turn['state'],turn['state'])
                return dict(binding=binding,status=state,receipt_ref='native-turn:'+turn['id']+':'+turn['state'])
            def submit(_,*,binding,handoff):
                receipt=queue.submit(binding=binding,handoff=handoff)
                queued.append((deepcopy(binding),deepcopy(handoff)))
                return receipt
        dispatcher=Dispatcher()
        host=GoalHost(goals,owner=owner,cid=cid,authorize=self.goal_authorized,dispatcher=dispatcher,
                      verify_receipt=lambda receipt,bound:receipt==dispatcher.lookup(binding=bound))
        return goals,host,dispatcher,queued

    def track(self,binding,args):
        self.guard(binding,{'scope':'global','scope_id':''},True)
        owner,cid=binding['owner'],binding['conversation_id']
        operation=args['operation']
        if operation not in ('create','step','status','pause','stop'):raise ValueError('customer_goal_operation')
        if operation=='create' and args.get('explicit_goal') is not True:raise ValueError('explicit_goal_required')
        goal_id=args.get('goal_id')
        goals,host,dispatcher,queued=self._goals(owner,cid)
        if operation=='create':
            context=self.context(binding,args['snapshot_id'])
            context.timeline(args['snapshot_id'],args['customer_id'],limit=1)
            scope_ref=canonical({'scope':context.scope,'snapshot_id':args['snapshot_id'],'customer_id':args['customer_id']})
            goal_id='customer-'+hashlib.sha256(canonical([owner,cid,binding['request_id'],args['customer_id']]).encode()).hexdigest()
            return host.create(goal_id,mutation_id='create-'+hashlib.sha256(canonical([binding,goal_id]).encode()).hexdigest(),
                scope_ref=scope_ref,objective=args['objective'],constraints=['Read authorized FS facts only; no business writes or outreach.'],
                recheck_at=args['recheck_at'],now=self.clock(),explicit_goal=True)
        state=host._load(goal_id)
        if operation in ('pause','stop'):
            return host.configure(goal_id,mutation_id=operation+'-'+hashlib.sha256(canonical([binding,goal_id,state['revision']]).encode()).hexdigest(),
                                  now=self.clock(),status='paused' if operation=='pause' else 'stopped')
        if operation=='status':
            if state['work']:
                bound=host._binding(state)
                found=dispatcher.lookup(binding=bound)
                if found['status']!='not_found':return host.observe(goal_id,receipt=found,now=self.clock())
            return {'goal_id':goal_id,'state':state,'action':'read_only','request_id':None}
        context=self.context(binding,args['snapshot_id']);ref=json.loads(state['scope_ref'])
        if context.scope!=ref['scope'] or args['customer_id']!=ref['customer_id']:
            raise PermissionError('customer_goal_scope_mismatch')
        receipt=context.timeline(args['snapshot_id'],args['customer_id'],limit=1)
        version=fact_version(receipt,self.clock());observation=observation_from_a2(receipt,now=self.clock())
        revision=args['expected_revision']
        request='followup_'+hashlib.sha256(canonical([owner,cid,goal_id,revision,version]).encode()).hexdigest()
        evidence=[dict(ref=canonical(receipt['evidence_ref']),source='FS/users',as_of=observation.as_of.isoformat(),
                       coverage='complete' if observation.complete else 'partial',missing=list(observation.missing),version=version)]
        result=host.step(goal_id,mutation_id='step-'+hashlib.sha256(canonical([binding,goal_id,revision]).encode()).hexdigest(),
                         request_id=request,fact_version=version,now=self.clock(),expected_revision=revision,evidence=evidence)
        # Original GoalHost already committed its CAS/outbox before this point.
        # Never submit another turn while the current conversation is busy.
        # Only this fresh CAS winner has this continuation; restarts/replays
        # reconcile the durable original ID and do not recreate dispatch rights.
        for bound,handoff in queued:
            def continue_original(bound=bound,handoff=handoff):
                current=host._load(goal_id)
                if current['status']!='active' or current['work']['request_id']!=bound['request_id']:
                    return {'request_id':bound['request_id'],'action':'reconcile_original'}
                try:
                    self.native.service.submit(owner,cid,canonical(handoff),bound['request_id'])
                    actual=dispatcher.lookup(binding=bound)
                    return host.observe(goal_id,receipt=actual,now=self.clock())
                except (OSError,RuntimeError,PermissionError,ValueError,LookupError):
                    return {'request_id':bound['request_id'],'action':'reconcile_original'}
            with self.native.service.lock:self.pending.setdefault(binding['turn_id'],[]).append(continue_original)
        return result

    def finish(self,turn_id,state):
        with self.native.service.lock:callbacks=self.pending.pop(turn_id,[])
        # Existing ledger truth, including after a process restart. Never use a
        # response string as a receipt, or turn a missing row into dispatch rights.
        with self.native.store.db() as db:
            turn=db.execute('SELECT t.request_id,t.conversation_id,t.state,c.owner FROM turns t '
                            'JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?',(turn_id,)).fetchone()
        if turn is None:return []
        if state=='completed' and turn['state']!='completed':
            raise ValueError('customer_goal_receipt_state_mismatch')
        results=[callback() for callback in callbacks] if state=='completed' else []
        if not turn['request_id'].startswith('followup_'):return results
        from contextlib import closing
        from pathlib import Path
        import sqlite3
        path=Path(self.native.hermes.tasks.path)
        if path.is_symlink() or path.resolve(strict=True)!=(self.native.hermes.root/'tasks.sqlite3').resolve(strict=True):
            raise PermissionError('customer_goal_receipt_store')
        with closing(sqlite3.connect(path.resolve(strict=True).as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='conversation_goal_outbox_v1'").fetchone():return results
            row=db.execute('SELECT binding_json FROM conversation_goal_outbox_v1 WHERE owner=? AND request_id=?',
                           (turn['owner'],turn['request_id'])).fetchone()
        if row is None:return results
        bound=json.loads(row[0])
        if (bound['owner'],bound['cid'],bound['request_id'])!=(turn['owner'],turn['conversation_id'],turn['request_id']):
            raise PermissionError('customer_goal_receipt_binding')
        if self.goal_authorized(bound['owner'],bound['scope_ref']) is not True:
            raise PermissionError('customer_goal_receipt_revoked')
        _,host,dispatcher,_=self._goals(bound['owner'],bound['cid'])
        actual=dispatcher.lookup(binding=bound)
        results.append(host.observe(bound['goal_id'],receipt=actual,now=self.clock()))
        return results
