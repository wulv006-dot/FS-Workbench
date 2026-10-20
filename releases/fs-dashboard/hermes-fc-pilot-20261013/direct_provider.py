"""Unwired FC-only candidate: original FS process owns the direct API key.

No credential values, response prose, or request body are included in diagnostics.
No redirects or automatic retry, and no API key is exposed to Hermes.
"""
import json
from datetime import datetime, timezone
from http.client import HTTPException
import os
from pathlib import Path
import re
import stat
import time
import socket
import threading
import urllib.error
import urllib.request
import uuid

BASE_URL = 'https://api.deepseek.com'
MODEL = 'deepseek-flash'
POLICY_ID = 'no-pilot-quotas-deepseek-direct-stream-tokens-only-v2'
CONTEXT_TOKENS = 1048576
OUTPUT_TOKENS = 393216
WIRE_BYTES = 10000000
WAIT_SECONDS = 1800
KEY_ENV = 'FS_HERMES_DEEPSEEK_KEY_FILE'
DEFAULT_KEY_FILE = '/var/lib/fs-hermes-fc/fs/secrets/deepseek.key'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _load_key():
    name = os.environ.get(KEY_ENV, DEFAULT_KEY_FILE)
    path = Path(name)
    if not path.exists():
        raise ValueError('configuration_missing')
    info = path.lstat()
    # Production Linux ownership; NTFS tests explicitly inject a POSIX fixture.
    if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or
            info.st_uid != os.geteuid() or not 1 <= info.st_size <= 1024):
        raise ValueError('configuration_invalid')
    key = path.read_text('utf-8-sig').strip()
    if not re.fullmatch(r'sk-[A-Za-z0-9._-]+', key):
        raise ValueError('configuration_invalid')
    return key


def _identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value) else None


def _header_trace(headers):
    out={};headers=headers or {}
    fields={'x-request-id':'provider_http_request_id','x-ds-trace-id':'provider_ds_trace_id'}
    for header,value in headers.items():
        key=fields.get(header.lower())
        if key and isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',value):out[key]=value
    return out


def _safe_http_error(error):
    out = {'status': 'http_rejected', 'http_status': error.code}
    out.update(_header_trace(error.headers))
    identity = _identifier(out.get('provider_http_request_id'))
    if identity:
        out['provider_request_id'] = identity
    try:
        raw = error.read(4097)
        if len(raw) > 4096:
            return out
        body = json.loads(raw)
        nested = body.get('error') if isinstance(body, dict) else None
        if not isinstance(nested, dict):
            return out
        code = nested.get('code')
        if isinstance(code, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,79}', code):
            out['provider_error_code'] = code
        # Save a category only for these exact documented forms, never raw prose.
        message = nested.get('message')
        forms = {'Input data may contain inappropriate content.': 'input',
                 'Output data may contain inappropriate content.': 'output',
                 'Input or output data may contain inappropriate content.': 'unknown'}
        if message in forms:
            out['inspection_direction'] = forms[message]
    except (ValueError, TypeError, OSError, HTTPException):
        pass
    finally:
        error.close()
    return out


def _stream_events(response, trace=None):
    parts = []; size = 0
    for raw in iter(lambda: response.readline(WIRE_BYTES+1), b''):
        if trace is not None:trace['response_bytes_received'] += len(raw)
        if len(raw) > WIRE_BYTES:
            raise ValueError('stream_event_too_large')
        line = raw.rstrip(b'\r\n')
        if not line:
            if parts:
                yield b'\n'.join(parts)
                parts = []; size = 0
        elif line.startswith(b'data:'):
            part = line[5:].lstrip(b' '); size += len(part)
            if size > WIRE_BYTES:
                raise ValueError('stream_event_too_large')
            parts.append(part)
        # SSE comments are vendor keep-alives, not response content.
    if parts:
        yield b'\n'.join(parts)


def _read_stream(response, trace=None):
    identity = model = finish = usage = None
    text = []; reasoning = []; calls = {}; size = 0; done = False; terminal_usage = False
    for payload in _stream_events(response, trace):
        if trace is not None:trace['stream_events_received'] += 1
        if payload == b'[DONE]':
            done = True; break
        chunk = json.loads(payload)
        if not isinstance(chunk, dict) or chunk.get('error'):
            raise ValueError('invalid_stream_chunk')
        for key, old in (('id', identity), ('model', model)):
            value = chunk.get(key)
            if value is not None and (not isinstance(value, str) or old is not None and value != old):
                raise ValueError('stream_identity_changed')
        if chunk.get('id') is not None:identity = chunk['id']
        if trace is not None and _identifier(identity):trace['provider_response_id'] = identity
        if chunk.get('model') is not None:model = chunk['model']
        usage = chunk.get('usage'); terminal_usage = False
        choices = chunk.get('choices')
        if choices == [] and isinstance(usage,dict) and finish is not None:
            terminal_usage = True
            continue
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0],dict) or choices[0].get('index') != 0:
            raise ValueError('stream_choices')
        choice = choices[0]; delta = choice.get('delta', {})
        if not isinstance(delta, dict) or delta.get('role') not in (None, 'assistant'):
            raise ValueError('stream_delta')
        if finish is not None and any(delta.get(k) for k in ('content','reasoning_content','tool_calls')):
            raise ValueError('content_after_stream_finish')
        for key, parts in (('content', text), ('reasoning_content', reasoning)):
            value = delta.get(key)
            if value is not None:
                if not isinstance(value, str):raise ValueError('stream_text')
                size += len(value.encode('utf-8')); parts.append(value)
        items = delta.get('tool_calls') or []
        if not isinstance(items,list):raise ValueError('stream_tools')
        for item in items:
            if not isinstance(item,dict):raise ValueError('stream_tool')
            index = item.get('index')
            if type(index) is not int or index < 0:raise ValueError('stream_tool_index')
            tool = calls.setdefault(index, {'id':None,'type':None,'name':[],'arguments':[]})
            for key in ('id','type'):
                value = item.get(key)
                if value is not None:
                    if not isinstance(value,str) or tool[key] is not None and value != tool[key]:raise ValueError('stream_tool_identity')
                    if tool[key] is None:size += len(value.encode('utf-8'))
                    tool[key] = value
            function = item.get('function', {})
            if not isinstance(function, dict):raise ValueError('stream_function')
            for key in ('name','arguments'):
                value = function.get(key)
                if value is not None:
                    if not isinstance(value,str):raise ValueError('stream_tool_text')
                    size += len(value.encode('utf-8')); tool[key].append(value)
        if size > WIRE_BYTES:raise ValueError('stream_response_too_large')
        value = choice.get('finish_reason')
        if value is not None:
            if not isinstance(value,str) or finish is not None and finish != value:raise ValueError('stream_finish_changed')
            finish = value
            terminal_usage = isinstance(usage,dict)
    if not done or finish is None or not terminal_usage or not identity or model != MODEL:
        raise ValueError('stream_incomplete')
    message = {'role':'assistant','content':''.join(text) if text else None}
    if reasoning:message['reasoning_content'] = ''.join(reasoning)
    if calls:
        message['tool_calls'] = [{'index':index,'id':tool['id'],'type':tool['type'],
            'function':{'name':''.join(tool['name']),'arguments':''.join(tool['arguments'])}}
            for index,tool in sorted(calls.items())]
    result = {'id':identity,'model':model,'object':'chat.completion','usage':usage,
              'choices':[{'index':0,'finish_reason':finish,'message':message}]}
    if len(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode('utf-8')) > WIRE_BYTES:
        raise ValueError('stream_response_too_large')
    return result


def _open(path, payload=None, deadline=None):
    if deadline is None:return _open_sync(path,payload)
    if deadline<=datetime.now(timezone.utc):return {'status':'scheduled_deadline','network_started':False}
    from nightly_http import Deadline
    trace={'local_trace_id':uuid.uuid4().hex,'request_started_at':datetime.now(timezone.utc).isoformat(),
           'response_headers_received':False,'transport_phase':'opening','response_bytes_received':0,'stream_events_received':0}
    try:
        with Deadline(deadline) as control:
            return control.run(lambda:_open_sync(path,payload,control,trace))
    except TimeoutError:
        return dict(trace,status='scheduled_deadline')


def _open_sync(path,payload=None,control=None,trace=None):
    if control is not None:control.remaining()
    key=_load_key()
    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
    req=urllib.request.Request(BASE_URL+path,payload,headers)
    started=time.monotonic()
    trace=trace if trace is not None else {'local_trace_id':uuid.uuid4().hex,
          'request_started_at':datetime.now(timezone.utc).isoformat(),'response_headers_received':False,
          'transport_phase':'opening','response_bytes_received':0,'stream_events_received':0}
    handlers=(NoRedirect(),*control.handlers()) if control is not None else (NoRedirect(),)
    try:
        with urllib.request.build_opener(*handlers).open(req,timeout=min(WAIT_SECONDS,control.remaining()) if control is not None else WAIT_SECONDS) as response:
            trace['response_headers_received']=True
            trace.update(_header_trace(getattr(response,'headers',None) or {}))
            if payload is not None and json.loads(payload).get('stream') is True:
                trace['transport_phase']='reading_stream'
                result=_read_stream(response,trace)
                return dict(result,**trace,elapsed_seconds=round(time.monotonic()-started,3))
            trace['transport_phase']='reading_body'
            raw=response.read(WIRE_BYTES+1)
            trace['response_bytes_received']=len(raw)
        if len(raw)>WIRE_BYTES:return dict(trace,status='invalid_response')
        result=json.loads(raw)
        if not isinstance(result,dict):return dict(trace,status='invalid_response')
        return dict(result,**trace,elapsed_seconds=round(time.monotonic()-started,3))
    except urllib.error.HTTPError as error:
        trace['response_headers_received']=True;trace['transport_phase']='http_rejected'
        result=_safe_http_error(error)
        trace.update({k:result[k] for k in ('provider_http_request_id','provider_ds_trace_id') if k in result})
        return dict(result,**trace,elapsed_seconds=round(time.monotonic()-started,3))
    except (OSError,TimeoutError,HTTPException) as error:
        result=dict(trace,status='unknown_transport',transport_error_type=type(error).__name__,
                    elapsed_seconds=round(time.monotonic()-started,3),timeout_seconds=WAIT_SECONDS)
        reason=getattr(error,'reason',None)
        if isinstance(reason,BaseException):result['transport_reason_type']=type(reason).__name__
        return result
    except (ValueError,TypeError):return dict(trace,status='invalid_response',elapsed_seconds=round(time.monotonic()-started,3))


def discover_models():
    """Harmless GET only; no balance query or completion, no secret in receipt."""
    try:
        result = _open('/models')
    except (ValueError, OSError) as error:
        code = str(error) if isinstance(error, ValueError) and str(error) in ('configuration_missing', 'configuration_invalid') else 'configuration_invalid'
        return {'status': code}
    if result.get('object') != 'list' or not isinstance(result.get('data'), list):
        return result if result.get('status') else {'status': 'invalid_response'}
    entries = []
    for item in result['data']:
        if not isinstance(item, dict) or item.get('id') != MODEL:
            continue
        context, output = item.get('context_window'), item.get('max_output_tokens')
        levels = item.get('effort', {}).get('supported_levels') if isinstance(item.get('effort'), dict) else None
        if (type(context) is not int or type(output) is not int or
                context != CONTEXT_TOKENS or output != OUTPUT_TOKENS or
                not isinstance(levels, list) or not {'high', 'max'}.issubset(levels)):
            return {'status': 'model_capability_changed'}
        entries.append({'id': MODEL, 'context_window': context, 'max_output_tokens': output,
                        'effort_levels': [v for v in levels if v in ('low', 'high', 'max')]})
    return {'status': 'verified' if len(entries) == 1 else 'model_unavailable', 'models': entries}


def prepare_request(request, approved_tools):
    """Pure native wire builder, shared by pre-reservation validation and send."""
    if (not isinstance(request, dict) or request.get('model') != MODEL or
            set(request)-{'model', 'messages', 'max_tokens', 'tools', 'tool_choice', 'stream', 'enable_thinking', 'reasoning_effort'} or
            request.get('reasoning_effort') not in ('high', 'max') or
            request.get('enable_thinking') is not True or request.get('stream') is not False or
            type(request.get('max_tokens')) is not int or request['max_tokens'] != OUTPUT_TOKENS or
            not isinstance(request.get('messages'), list) or not request['messages'] or
            request.get('tools') not in (approved_tools, []) or not approved_tools):
        raise ValueError('configuration_invalid')
    body = {'model': MODEL, 'messages': request['messages'], 'max_tokens': OUTPUT_TOKENS,
            'thinking': {'type': 'enabled'}, 'reasoning_effort': request['reasoning_effort'],
            'stream': True, 'stream_options': {'include_usage': True}}
    if request['tools']:
        body.update(tools=approved_tools, tool_choice='auto')
    payload = json.dumps(body, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(payload) > WIRE_BYTES:
        raise ValueError('provider_payload_too_large')
    return payload


def request_model(request, approved_tools, deadline=None):
    """Only a trusted ModelGateway request; not an arbitrary endpoint proxy."""
    try:
        payload = prepare_request(request, approved_tools)
        result = _open('/chat/completions', payload,deadline=deadline) if deadline is not None else _open('/chat/completions', payload)
    except (ValueError, OSError, TypeError) as error:
        code = ('input_too_large' if str(error)=='provider_payload_too_large' else str(error)) if isinstance(error, ValueError) and str(error) in ('configuration_missing', 'configuration_invalid', 'provider_payload_too_large') else 'configuration_invalid'
        return {'status': code}
    if result.get('status'):
        return result
    if result.get('model') != MODEL:
        return {'status': 'invalid_response'}
    return result
