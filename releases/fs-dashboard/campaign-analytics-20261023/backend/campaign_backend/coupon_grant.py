"""Manual single-recipient CouponGrant/import, behind native host approval.

Wire mapping: verified public Admin index-d2ab3e4b.js. No report URL/token,
invented idempotency field, account/history lookup, or template mutation.
"""
import json
import re

from .benefits import row_hash, safe_response_evidence, scoped_row
from .catalog import positive_id
from .core import ContractError, identity

COUNTERS=('success','not_found','pending_register','skipped_limit','failed')


def validate(request):
    if (type(request) is not dict or set(request)!={'action','site_id','kind','native_id','operation_id',
            'before_hash','grant_batch_no','email'} or request['action']!='coupon_grant' or
            request['site_id']!='266' or request['kind']!='coupon'):
        raise ContractError('GRANT_REQUEST_INVALID')
    positive_id(request['native_id']);identity(request['operation_id'])
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}',request['operation_id']):
        raise ContractError('GRANT_OPERATION_ID_INVALID')
    if (type(request['before_hash']) is not str or not re.fullmatch('[a-f0-9]{64}',request['before_hash']) or
            type(request['grant_batch_no']) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',request['grant_batch_no'])):
        raise ContractError('GRANT_REQUEST_INVALID')
    if type(request['email']) is not str or not re.fullmatch(r'[^@\s,;，；]+@[^@\s,;，；]+',request['email']):
        raise ContractError('GRANT_SINGLE_RECIPIENT_REQUIRED')
    return request


def result(data,payload,*,job_id=None):
    """Counts may be optional, never defaulted. A unique issued row is essential."""
    unknown=dict(state='unknown',reason_code='GRANT_RESULT_UNCONFIRMED')
    if job_id is not None:unknown['upstream_ref']=job_id
    if type(data) is not dict:return unknown
    # The exact approved POST binds site/template; these echoes are not defined
    # by the public contract. A provided mismatching batch/job is contradictory.
    if 'batch_no' in data and data['batch_no']!=payload['grant_batch_no']:return unknown
    if job_id is not None:
        if 'job_id' in data and str(data['job_id'])!=job_id:return unknown
        if data.get('status') in ('pending','running'):
            return dict(unknown,reason_code='GRANT_TASK_PENDING')
        if data.get('status') not in ('done','failed'):return unknown
    for key in (*COUNTERS,'total','processed'):
        if key in data and data[key] is not None and (type(data[key]) is not int or not 0<=data[key]<=1):return unknown
    if any(data.get(key) is not None and data[key]!=1 for key in ('total','processed')):return unknown
    if all(data.get(key) is not None for key in COUNTERS) and sum(data[key] for key in COUNTERS)!=1:return unknown
    rows=data.get('rows')
    if type(rows) is not list or len(rows)!=1 or type(rows[0]) is not dict:return unknown
    row=rows[0]
    if (type(row.get('email')) is not str or row['email'].casefold()!=payload['email'].casefold() or
            type(row.get('status')) not in (str,int) or row['status']==''):return unknown
    issued=row.get('member_coupon_id')
    issued=type(issued) in (str,int) and str(issued).isdigit() and int(issued)>0
    if data.get('success')==1:
        if not issued or data.get('status')=='failed' or any(data.get(k) is not None and data[k]!=0 for k in COUNTERS[1:]):return unknown
        return dict(state='confirmed',upstream_ref='member-coupon:'+str(row['member_coupon_id']))
    failures=[key for key in COUNTERS[1:] if data.get(key)==1]
    if data.get('success')==0 and len(failures)==1 and not issued:
        if failures[0]=='pending_register':
            # A deferred registration outcome is not an issued coupon or a
            # final no-side-effect rejection. Keep the original operation.
            return dict(unknown,reason_code='GRANT_PENDING_REGISTER')
        return dict(state='rejected',reason_code='GRANT_'+failures[0].upper())
    return unknown


class CouponGrant:
    enabled=True
    route='/admin/market.CouponGrant/import'

    def __init__(self,reader,ledger,authorize=None):
        self.reader,self.ledger=reader,ledger
        self.authorize=authorize
        self.audit=None

    def bind_native_response_audit(self,callback):self.audit=callback

    def dispatch_once(self,operation_id,payload):
        validate(payload)
        row=scoped_row(self.reader,'coupon',payload['native_id'],payload['site_id'])
        if row_hash(row)!=payload['before_hash']:
            return dict(state='rejected',reason_code='BEFORE_HASH_CONFLICT',dispatch_state='not_started')
        # fetch_scene=4 is the real template selector condition. The unrelated
        # disabled/unused brief editor proofs must not gate a grant.
        if str(row.get('fetch_scene'))!='4':
            return dict(state='rejected',reason_code='GRANT_TEMPLATE_REQUIRED',dispatch_state='not_started')
        session=self.reader.session;url='https://admin-api.p2pah.cn'+self.route
        retries=session.admin.get_adapter(url).max_retries
        if type(retries.total) is not int or retries.total!=0:
            return dict(state='rejected',reason_code='TRANSPORT_RETRY_NOT_DISABLED',dispatch_state='not_started')
        wire=dict(site_id=payload['site_id'],coupon_id=payload['native_id'],
                  grant_batch_no=payload['grant_batch_no'],emails=payload['email'])
        # Re-read the trusted host approval and actor after the final template
        # GET, immediately before the one outbound POST. Never a body flag.
        try:authorized=callable(self.authorize) and self.authorize(payload) is True
        except PermissionError:authorized=False
        if not authorized:
            return dict(state='rejected',reason_code='BUSINESS_AUTHORIZATION_REQUIRED',dispatch_state='not_started')
        try:
            response=session.admin.post(url,json=wire,headers={'batoken':session.token,'server':'true','think-lang':'zh-cn'},
                                        timeout=30,allow_redirects=False)
        except Exception as error:
            self.audit(operation_id,safe_response_evidence(error=error))
            raise
        self.audit(operation_id,safe_response_evidence(response=response))
        raw=getattr(response,'content',None)
        if response.status_code!=200 or not isinstance(raw,bytes) or len(raw)>2000000:
            return dict(state='unknown',reason_code='GRANT_RESPONSE_UNCONFIRMED')
        reply=json.loads(raw)
        if type(reply) is not dict or type(reply.get('code')) is not int or reply['code']!=1:
            return dict(state='unknown',reason_code='GRANT_RESPONSE_UNCONFIRMED')
        data=reply.get('data')
        if type(data) is dict and data.get('mode')=='sync':return result(data,payload)
        if type(data) is dict and data.get('mode')=='async':
            if 'batch_no' in data and data['batch_no']!=payload['grant_batch_no']:
                return dict(state='unknown',reason_code='GRANT_RESULT_UNCONFIRMED')
            job=data.get('job_id')
            if type(job) in (str,int) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',str(job)):
                # Persist the original native ID before any status read. Original
                # OperationLedger owns dispatch admission and duplicate suppression.
                return dict(state='unknown',upstream_ref=str(job),reason_code='GRANT_TASK_PENDING')
        return dict(state='unknown',reason_code='GRANT_RESULT_UNCONFIRMED')

    def readback(self,operation_id,payload):
        current=self.ledger.lookup(operation_id)
        job=(current.get('result') or {}).get('upstream_ref')
        if not job:return dict(state='unknown',reason_code='GRANT_ORIGINAL_JOB_ID_UNAVAILABLE')
        data=self.reader._get('/admin/market.CouponGrant/jobStatus',job_id=job)
        return result(data,payload,job_id=job)


def execute(reader,ledger,request,*,authorize=None):
    validate(request)
    if not callable(authorize) or authorize(request) is not True:
        raise ContractError('BUSINESS_AUTHORIZATION_REQUIRED')
    old=ledger.lookup(request['operation_id'])
    if old is not None:
        # prepare checks canonical equality even after terminal success.
        return ledger.prepare(request['operation_id'],request)
    row=scoped_row(reader,'coupon',request['native_id'],request['site_id'])
    if row_hash(row)!=request['before_hash']:raise ContractError('BEFORE_HASH_CONFLICT')
    if str(row.get('fetch_scene'))!='4':raise ContractError('GRANT_TEMPLATE_REQUIRED')
    return ledger.execute(request['operation_id'],request,CouponGrant(reader,ledger,authorize))
