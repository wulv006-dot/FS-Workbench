"""Sol Responses transport for admitted FS reports and pricing reviews."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import re
import stat
import subprocess
import tempfile
import uuid

MODEL = 'gpt-6.2-sol'
POLICY_ID = 'openai-sol-responses-tokens-only-v1'
PRICE_VERSION = 'openai-sol-no-cny-invoice-or-fx-v1'
OUTPUT_TOKENS = 128000
WIRE_BYTES = 10000000
REASONING_PREFIX = 'fs-openai-encrypted-reasoning-v1:'


def prepare_request(request, approved_tools, *, native_chat=False,campaign=False):
    from proxy_gateway import native_tool_choice, native_response_format
    if ((not native_chat and not campaign) or campaign and native_chat or request.get('model') != MODEL or
            set(request)-{'model','messages','max_tokens','tools','tool_choice','stream','enable_thinking','reasoning_effort','response_format'} or
            request.get('tools') not in (approved_tools, []) or not approved_tools and not campaign or campaign and (approved_tools or request.get('tools')!=[]) or
            request.get('stream') is not False or type(request.get('max_tokens')) is not int or
            not 1 <= request['max_tokens'] <= OUTPUT_TOKENS or
            request.get('reasoning_effort') not in (None,'low','medium','high','xhigh','max')):
        raise ValueError('configuration_invalid')
    inputs=[]
    for message in request['messages']:
        role=message['role']; content=message.get('content')
        reasoning=message.get('reasoning_content','')
        if reasoning.startswith(REASONING_PREFIX):
            items=json.loads(reasoning[len(REASONING_PREFIX):])
            if not isinstance(items,list) or any(i.get('type')!='reasoning' for i in items):
                raise ValueError('configuration_invalid')
            inputs.extend(items)
        if role=='tool':
            inputs.append(dict(type='function_call_output',call_id=message['tool_call_id'],output=content))
            continue
        if content:
            if isinstance(content,list):
                parts=[]
                for part in content:
                    if part['type']=='text':parts.append(dict(type='input_text',text=part['text']))
                    elif part['type']=='image_url':
                        image=part['image_url']
                        parts.append(dict(type='input_image',image_url=image['url'],detail=image.get('detail','auto')))
                    else:raise ValueError('configuration_invalid')
                content=parts
            inputs.append(dict(role=role,content=content))
        for call in message.get('tool_calls',[]):
            inputs.append(dict(type='function_call',call_id=call['id'],name=call['function']['name'],arguments=call['function']['arguments']))
    body=dict(model=MODEL,input=inputs,store=False,include=['reasoning.encrypted_content'],
              max_output_tokens=request['max_tokens'],reasoning={'effort':request.get('reasoning_effort') or 'low'})
    if request['tools']:
        body['tools']=[dict(type='function',**tool['function'],strict=tool['function'].get('strict',False))
                       if 'strict' not in tool['function'] else dict(type='function',**tool['function']) for tool in approved_tools]
        choice=native_tool_choice(request.get('tool_choice','auto'),request['tools'])
        body['tool_choice']=dict(type='function',name=choice['function']['name']) if isinstance(choice,dict) else choice
    if 'response_format' in request:
        fmt=native_response_format(request['response_format'])
        body['text']={'format':dict(type='json_schema',**fmt['json_schema']) if fmt['type']=='json_schema' else fmt}
    payload=json.dumps(body,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    if len(payload)>WIRE_BYTES:raise ValueError('provider_payload_too_large')
    return payload


def _key():
    path=Path('/var/lib/fs-hermes-fc/profile/.env');info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:raise ValueError('configuration_invalid')
    matches=re.findall(r'(?m)^OPENAI_API_KEY\s*=\s*(.+)$',path.read_text())
    if len(matches)!=1:raise ValueError('configuration_missing')
    key=matches[0].strip().strip('\"\'')
    if not re.fullmatch(r'sk-[A-Za-z0-9_.-]+',key):raise ValueError('configuration_invalid')
    return key


def _open(payload,deadline=None,on_dispatch=None,on_not_dispatched=None):
    remaining=1800 if deadline is None else min(1800,(deadline-datetime.now(timezone.utc)).total_seconds())
    if remaining<=0:return dict(status='scheduled_deadline',network_started=False)
    # curl 7.29 rejects even an integral float such as "1799.0" before any HTTP.
    # Round up the remaining second, preserving the original 1800-second ceiling.
    timeout=min(1800,math.ceil(remaining))
    trace=dict(local_trace_id=uuid.uuid4().hex,request_started_at=datetime.now(timezone.utc).isoformat(),transport_phase='opening')
    # The deployed host Python lacks SSL; curl supplies verified TLS, without shell, redirects or retries.
    config='url = "https://api.openai.com/v1/responses"\nheader = "Authorization: Bearer '+_key()+'"\nheader = "Content-Type: application/json"\ndata = '+json.dumps(payload.decode())+'\n'
    with tempfile.TemporaryFile() as output:
        try:
            if on_dispatch is not None:on_dispatch()
            result=subprocess.run(['curl','--silent','--show-error','--include','--proto','=https','--max-time',str(timeout),
                '--max-filesize',str(WIRE_BYTES),'--config','-'],input=config.encode(),stdout=output,stderr=subprocess.PIPE,timeout=timeout+1)
        except subprocess.TimeoutExpired:return dict(trace,status='unknown_transport')
        output.seek(0);raw=output.read(WIRE_BYTES+1)
    trace.update(curl_exit_code=result.returncode,network_started=True)
    if (result.returncode==2 and not raw and
            b'curl: option --max-time: expected a proper numerical parameter' in result.stderr):
        proof=dict(network_started=False,curl_exit_code=2,provider_error_code='curl_option_invalid',transport_phase='local_validation')
        if on_not_dispatched is not None:on_not_dispatched(proof)
        return dict(trace,**proof,status='local_rejected')
    # Response headers are parsed locally and discarded; only fixed metadata survives.
    while raw.startswith(b'HTTP/'):
        header,separator,body=raw.partition(b'\r\n\r\n')
        if not separator:break
        status=re.match(br'HTTP/[0-9.]+ ([0-9]{3})(?: |\r|$)',header)
        if status:trace.update(http_status=int(status[1]),response_headers_received=True,transport_phase='reading_body')
        for line in header.split(b'\r\n')[1:]:
            name,_,value=line.partition(b':')
            if name.lower()==b'x-request-id':
                identity=value.strip().decode('ascii','replace')
                if re.fullmatch('[A-Za-z0-9_.:-]{1,160}',identity):trace['provider_http_request_id']=identity
        raw=body
    if result.returncode:return dict(trace,status='unknown_transport')
    if len(raw)>WIRE_BYTES:return dict(trace,status='invalid_response')
    try:value=json.loads(raw)
    except ValueError:return dict(trace,status='invalid_response')
    if not isinstance(value,dict):return dict(trace,status='invalid_response')
    if value.get('error'):
        error=value['error'];known={'invalid_api_key','invalid_json_schema','invalid_request_error','model_not_found','insufficient_quota','rate_limit_exceeded','unsupported_parameter','unsupported_value','context_length_exceeded','invalid_value','invalid_parameter','permission_denied','server_error'}
        code=error.get('code') if isinstance(error,dict) else None
        return dict(trace,status='http_rejected',provider_error_code=code if isinstance(code,str) and code in known else 'provider_http_rejected',transport_phase='http_rejected')
    reserved={'network_started','curl_exit_code','http_status','response_headers_received','local_trace_id','request_started_at','transport_phase','provider_http_request_id','provider_error_code'}
    return dict({key:item for key,item in value.items() if key not in reserved},**trace)


def request_model(request, approved_tools, deadline=None, *, native_chat=False,campaign=False,on_dispatch=None,on_not_dispatched=None):
    if (on_dispatch is not None or on_not_dispatched is not None) and not campaign:raise ValueError('configuration_invalid')
    payload=prepare_request(request,approved_tools,native_chat=native_chat,campaign=campaign)
    value=_open(payload,deadline,on_dispatch,on_not_dispatched) if campaign else _open(payload,deadline)
    if value.get('status') not in ('completed','incomplete'):return value
    if value.get('model')!=MODEL:return dict(status='invalid_response')
    text=[];calls=[];reasoning=[]
    for item in value['output']:
        if item['type']=='reasoning':reasoning.append(item)
        elif item['type']=='function_call':
            calls.append(dict(id=item['call_id'],type='function',function=dict(name=item['name'],arguments=item['arguments'])))
        elif item['type']=='message':
            for part in item['content']:
                if part['type']=='output_text':text.append(part['text'])
                elif part['type']=='refusal':return dict(status='invalid_response')
                else:raise ValueError('response_content_invalid')
        else:raise ValueError('response_item_invalid')
    message=dict(role='assistant',content=''.join(text) or None)
    if calls:message['tool_calls']=calls
    if reasoning and request['enable_thinking']:
        message['reasoning_content']=REASONING_PREFIX+json.dumps(reasoning,separators=(',',':'))
    usage=value['usage']
    finish='length' if value['status']=='incomplete' else 'tool_calls' if calls else 'stop'
    result=dict(id=value['id'],model=MODEL,choices=[dict(index=0,message=message,finish_reason=finish)],
        usage=dict(prompt_tokens=usage['input_tokens'],completion_tokens=usage['output_tokens'],total_tokens=usage['total_tokens'],
                   completion_tokens_details=usage.get('output_tokens_details',{})),
        model_validation=dict(status='provider_metadata_confirmed',forwarded_verified=True,endpoint_type='responses',
            requested_model=MODEL,response_model=value['model'],actual_backend_version='unknown',
            requested_effort=request.get('reasoning_effort'),provider_effort_echo=value.get('reasoning',{}).get('effort'),
            payload_sha256=hashlib.sha256(payload).hexdigest(),provider_response_id=value['id'],thinking_enabled=request['enable_thinking']))
    for key in ('local_trace_id','request_started_at','transport_phase','curl_exit_code','http_status','response_headers_received','provider_http_request_id'):
        if key in value:result[key]=value[key]
    return result
