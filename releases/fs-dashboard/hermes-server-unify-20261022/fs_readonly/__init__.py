"""Native Hermes tools for the existing FS loopback read interfaces."""
import json
import sys
sys.path.insert(0, '/fs-source')
from user_tools import DESCRIPTION as USER_DESCRIPTION, PROPERTIES as USER_PROPERTIES
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

BASE = 'http://127.0.0.1:8931'
OWNER = 'wulv'
MAX_RESPONSE = 10_000_000
PERIOD = {'profile': {'type':'string'}, 'start': {'type':'string'}, 'end': {'type':'string'}}
TOOLS = {
    'fs_query_user_analytics': (USER_DESCRIPTION, USER_PROPERTIES, []),
    'fs_get_data_catalog': ('Read the current FS project catalog, timezone and source policy. No source collection or model call.', {}, []),
    'fs_query_native_statistics': ('Read a fresh or valid cached exact inclusive-day FS business range through its existing Admin-first/Order-reference service. Covers approved catalog projects. Keep source, currency, capture time, estimated-profit labels and missing fields. For pending/unknown, poll identical repeat_arguments after retryAfter; do not change catalog_id or fabricate zeros.',
        {**PERIOD,'catalog_id':{'type':'string','description':'Reuse this exact catalog version when polling repeat_arguments.'}}, list(PERIOD)),
    'fs_query_es_order_structure': ('Read Admin ES aggregate structure through the existing FS query, including fresh reads when needed. This scope differs from Admin native totals. Preserve original statuses and USD/order versus original-paid currencies. No PII or order changes. Pending: poll identical arguments.',
        {**PERIOD,'group_by':{'type':'string','enum':['game','source_game','product','country','payment','new_customer','status']},'status':{'type':'string'}},list(PERIOD)),
    'fs_query_discount_analysis': ('Read actual ES discount amounts in USD through the existing FS query and reuse its same period export. Preserve scope, status, new/old/unknown flags and missing coverage. No coupon creation or campaign changes. Pending: poll identical arguments.',
        {**PERIOD,'group_by':{'type':'string','enum':['new_customer','type','day']},'status':{'type':'string'}},list(PERIOD)),
    'fs_query_product_orders': ('Read aggregate orders for one verified Admin game and product ID through FS, MMOEXP site266. Dates retain the source time field; preserve completeness. Whole-order USD is not SKU revenue. No customer identifiers or order changes. Pending: poll identical arguments.',
        {**PERIOD,'product_id':{'type':'integer','minimum':1,'maximum':999999999}},[*PERIOD,'product_id']),
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read(path, params):
    # This root server profile is the existing trusted local caller for owner wulv.
    # Callers cannot supply an owner, URL, headers, credentials or a write method.
    assert path in ('/range','/advisor','/users')
    req=Request(BASE+path+'?'+urlencode(params),headers={'X-Auth-User':OWNER,'Accept':'application/json'},method='GET')
    try:
        response=build_opener(ProxyHandler({}),NoRedirect).open(req,timeout=30)
    except HTTPError as error:
        response=error
    except (URLError,TimeoutError):
        return {'status':'unknown','error':'fs_transport_outcome_unknown','query_identity_retained':True}
    with response:
        if 'application/json' not in response.headers.get('Content-Type',''):
            return {'status':'unavailable','http_status':response.code,'error':'fs_response_not_json'}
        raw=response.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE:
            return {'status':'unavailable','http_status':response.code,'error':'fs_response_too_large'}
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError('fs_response_shape')
        return value if response.code<400 else {**value,'http_status':response.code}


def call(name,args):
    if name not in TOOLS or not isinstance(args,dict):raise ValueError('fs_tool_denied')
    _,properties,required=TOOLS[name]
    if set(args)-set(properties) or not set(required)<=set(args):raise ValueError('fs_tool_fields')
    if any(type(v) not in (str,int) for v in args.values()):raise ValueError('fs_tool_value')
    if any('enum' in properties[k] and v not in properties[k]['enum'] for k,v in args.items()):raise ValueError('fs_tool_enum')
    if name=='fs_get_data_catalog':
        return {**read('/range',{'mode':'catalog'}),'user_analytics':read('/users',{'action':'catalog'})}
    if name=='fs_query_user_analytics':
        query=dict(args)
        if 'evidence_id' in query:
            evidence=query.pop('evidence_id')
            if not isinstance(evidence,str) or len(evidence)!=35 or not evidence.startswith('ua_'):raise ValueError('user_evidence_id')
            snapshot='us_'+evidence[3:]
            if query.get('snapshot_id',snapshot)!=snapshot:raise ValueError('user_evidence_snapshot_mismatch')
            query['snapshot_id']=snapshot
        return read('/users',query)
    if name=='fs_query_native_statistics':
        catalog=args.get('catalog_id')
        if not catalog:
            current=read('/range',{'mode':'catalog'})
            catalog=current.get('catalogId')
            if not isinstance(catalog,str):return current
        query={k:args[k] for k in PERIOD}
        result=read('/range',{**query,'grain':'day','snapshotId':catalog})
        return {**result,'repeat_arguments':{**query,'catalog_id':catalog}}
    query={k:v for k,v in args.items()}
    structure='product_orders' if name=='fs_query_product_orders' else 'es'
    if name=='fs_query_discount_analysis':
        group=query.get('group_by','new_customer')
        if group not in ('new_customer','type','day'):raise ValueError('fs_discount_group')
        query['group_by']='discount_'+group
    return read('/advisor',{'mode':'hermes','structure':structure,**query})


def register(ctx):
    for name,(description,properties,required) in TOOLS.items():
        schema={'name':name,'description':description,'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}
        def handler(args,_name=name,**context):
            return json.dumps(call(_name,args),ensure_ascii=False,allow_nan=False)
        ctx.register_tool(name=name,toolset='fs_readonly',schema=schema,handler=handler)
