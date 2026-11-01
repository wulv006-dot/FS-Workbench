"""FS-authenticated HTTP adapter for the separate Hermes conversation service."""

import json
import csv
import re
import time
import zipfile
from xml.etree.ElementTree import ParseError
from urllib.parse import parse_qs, quote, unquote


PREFIX = "/api/hermes/conversations"
IDENT = r"[a-zA-Z0-9_-]{8,80}"
MATERIAL_ADAPTER_VERSION = 'materials_runtime_diagnostics_v1'


def _material_lookup_stage(error, service, stage):
    if stage == 'http_owned':
        return stage
    materials = getattr(service, 'materials', None)
    queue_code = getattr(getattr(materials, '_queue', None), '__code__', None)
    owned_code = getattr(getattr(service.store, '_owned', None), '__code__', None)
    frames = []
    trace = error.__traceback__
    while trace is not None:
        frames.append(trace.tb_frame.f_code)
        trace = trace.tb_next
    if (stage == 'submit' and queue_code is not None and owned_code is not None
            and any(code is queue_code for code in frames) and any(code is owned_code for code in frames)):
        return 'submit_owned'
    return 'lookup'


def respond(handler, status, data, content_type="application/json; charset=utf-8", headers=()):
    body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    for key, value in (("Content-Type", content_type), ("Content-Length", str(len(body))),
                       ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                       ("Connection", "close"), *headers):
        handler.send_header(key, value)
    handler.end_headers()
    handler.close_connection = True
    handler.wfile.write(body)


def handle(handler, method, uri, user, service, authorized):
    """Return True only for this exact path family; never trust client role headers."""
    path = uri.path
    if path != PREFIX and not path.startswith(PREFIX + "/"):
        return False
    if not user:
        respond(handler, 401, {"error": "login_required"})
        return True
    permission = authorized(user)
    if not permission:
        respond(handler, 403, {"error": "admin_required"})
        return True
    parts = path[len(PREFIX):].strip("/").split("/") if path != PREFIX else []
    material_route = len(parts) >= 2 and parts[1] == 'materials'
    diagnostic_route = len(parts) >= 2 and parts[1] == 'runtime-diagnostics'
    if diagnostic_route and permission is not True:
        respond(handler, 403, {'error': 'admin_required'})
        return True
    material_stage = 'route'
    def reply(status, data, *args, **kwargs):
        if material_route or diagnostic_route:
            kwargs['headers'] = [*kwargs.get('headers', ()), ('X-FS-Material-Adapter', MATERIAL_ADAPTER_VERSION)]
        if material_route and status == 404:
            data = dict(data, stage=material_stage, source='material_http')
        return respond(handler, status, data, *args, **kwargs)
    ids = ([parts[1]] if len(parts)>1 else []) if parts and parts[0]=='pricing-reviews' else (([parts[0]] if parts else []) + ([parts[2]] if len(parts)>2 else []))
    if any(not re.fullmatch(IDENT, part) for part in ids):
        reply(404, {"error": "not_found"})
        return True
    if method == "POST" and (handler.headers.get("X-FS-Advisor-Action") != "submit" or
                             handler.headers.get("Sec-Fetch-Site") != "same-origin"):
        reply(403, {"error": "same_origin_required"})
        return True
    try:
        params = parse_qs(uri.query, keep_blank_values=True, max_num_fields=2)
        if parts and parts[0] == 'pricing-reviews':
            # This route has a separate store and one-slot model lane. It never
            # creates a turn in the ordinary investigation/report conversation.
            if method == 'POST' and len(parts) == 1 and not params:
                body = read_json(handler)
                if body: raise ValueError('pricing_review_create_body')
                respond(handler, 201,service.pricing.create(user))
            elif method == 'POST' and len(parts) == 3 and parts[2] == 'turns' and not params and re.fullmatch(IDENT,parts[1]):
                body = read_json(handler, {'text','client_request_id','run_id'})
                respond(handler, 202,service.pricing.submit_pricing(user,parts[1],body['text'],body['client_request_id'],body['run_id']))
            elif method == 'GET' and len(parts) == 2 and not params and re.fullmatch(IDENT,parts[1]):
                respond(handler, 200,service.pricing.detail(user,parts[1]))
            else:
                respond(handler, 404,{'error':'not_found'})
            return True
        if diagnostic_route:
            if method == 'GET' and len(parts) == 2 and not uri.query:
                diagnostics = getattr(service, 'runtime_diagnostics', None)
                if diagnostics is None:
                    reply(503, {'error': 'runtime_diagnostics_unavailable'})
                else:
                    reply(200, diagnostics(user, parts[0]))
            else:
                reply(404, {'error': 'not_found'})
            return True
        if len(parts) >= 2 and parts[1] == 'materials' and not params:
            material_stage = 'http_owned'
            with service.store.db() as db:
                service.store._owned(db,user,parts[0])
            material_stage = 'route'
            materials=getattr(service,'materials',None)
            if materials is None:
                reply(503,{'error':'material_execution_unavailable'})
            elif method=='POST' and len(parts)==2:
                material_stage = 'submit'
                reply(202,materials.submit(user,parts[0],read_json(handler)))
            elif method=='GET' and len(parts)==3:
                reply(200,materials.detail(user,parts[0],parts[2]))
            elif method=='GET' and len(parts)==4 and parts[3]=='result':
                reply(200,materials.result(user,parts[0],parts[2]))
            elif method=='POST' and len(parts)==4 and parts[3]=='stop':
                if read_json(handler):raise ValueError('material_stop_fields')
                reply(200,materials.stop(user,parts[0],parts[2]))
            else:
                reply(404,{'error':'not_found'})
            return True
        if method == "GET" and not parts and not params:
            respond(handler, 200, service.listed(user))
        elif method == "POST" and not parts and not params:
            body = read_json(handler)
            if body: raise ValueError("create_body")
            respond(handler, 201, service.create(user))
        elif method == "GET" and len(parts) == 1 and not params:
            respond(handler, 200, service.detail(user, parts[0]))
        elif len(parts) >= 2 and parts[1] == "files" and (not params or
                (method == 'GET' and len(parts) == 2 and set(params) == {'request_id'} and len(params['request_id']) == 1)):
            from conversation_files import ConversationFiles
            # Existing service gate and owner checks also apply after revocation.
            service.detail(user, parts[0])
            files = ConversationFiles(service.store)
            if method == "GET" and len(parts) == 2:
                if params:
                    respond(handler, 200, files.lookup(user, parts[0], params['request_id'][0]))
                else:
                    listed = files.listed(user, parts[0])
                    respond(handler, 200, {'items': [files.describe(user, parts[0], item['file_id']) for item in listed['items']]})
            elif method == "POST" and len(parts) == 2:
                raw = read_file(handler)
                name = handler.headers.get('X-FS-Filename')
                item = files.save(user, parts[0], unquote(name, errors='strict') if name else name, raw,
                                  handler.headers.get('X-FS-Request-ID'))
                respond(handler, 201, item)
            elif method == "GET" and len(parts) == 4 and parts[3] == "table":
                respond(handler, 200, files.parsed(user, parts[0], parts[2]))
            elif method == "POST" and len(parts) == 4 and parts[3] == "revisions":
                body = read_json(handler, {'edits', 'format', 'client_request_id'})
                respond(handler, 201, files.revise(user, parts[0], parts[2], body['edits'],
                                                 body['format'], body['client_request_id']))
            elif method == "GET" and len(parts) == 3:
                item = files.read(user, parts[0], parts[2])
                respond(handler, 200, item['content'], item['mime'],
                        [('Content-Disposition', "attachment; filename*=UTF-8''" + quote(item['filename']))])
            else:
                respond(handler, 404, {'error': 'not_found'})
        elif method == "POST" and len(parts) == 2 and parts[1] == "turns" and not params:
            body = read_json(handler)
            if set(body) not in ({'text', 'client_request_id'}, {'text', 'client_request_id', 'file_ids'}):
                raise ValueError('turn_fields')
            extra = {'file_ids': body['file_ids']} if 'file_ids' in body else {}
            respond(handler, 202, service.submit(user, parts[0], body["text"], body["client_request_id"], **extra))
        elif method == "GET" and len(parts) == 2 and parts[1] == "events" and set(params) == {"after"} and len(params["after"]) == 1:
            stream_events(handler, service, user, parts[0], params["after"][0])
        elif method == "POST" and len(parts) == 4 and parts[1] == "runs" and parts[3] in {"steer", "stop"} and not params:
            names = {"text", "client_request_id"} if parts[3] == "steer" else {"client_request_id"}
            body = read_json(handler, names)
            result = (service.steer(user, parts[0], parts[2], body["text"], body["client_request_id"])
                      if parts[3] == "steer" else service.stop(user, parts[0], parts[2], body["client_request_id"]))
            respond(handler, 202, result)
        elif method == "GET" and len(parts) == 3 and parts[1] == "artifacts" and set(params) in (set(), {"view"}):
            if params and params != {"view": ["1"]}: raise ValueError("view")
            artifact = service.artifact(user, parts[0], parts[2])
            data = artifact["content"]
            if not isinstance(data, bytes): raise ValueError("artifact_bytes")
            filename = artifact["filename"].replace("/", "_").replace("\\", "_").replace("\r", "_").replace("\n", "_")
            preview = bool(params) and artifact["mime"] in {"text/html", "text/plain", "text/csv"}
            disposition = "inline" if preview else "attachment"
            extra = [("Content-Disposition", disposition + "; filename*=UTF-8''" + quote(filename))]
            if preview:
                script = " allow-scripts" if artifact["mime"] == "text/html" else ""
                extra.append(("Content-Security-Policy", "sandbox" + script + "; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'"))
            respond(handler, 200, data, artifact["mime"] + "; charset=utf-8", extra)
        else:
            reply(404, {"error": "not_found"})
    except PermissionError:
        reply(403, {"error": "forbidden"})
    except LookupError as error:
        if material_route:
            material_stage = _material_lookup_stage(error, service, material_stage)
        reply(404, {"error": "not_found"})
    except (ValueError, KeyError, TypeError, csv.Error, zipfile.BadZipFile, ParseError):
        reply(422, {"error": "invalid_request"})
    except Exception:
        reply(503, {"error": "conversation_unavailable"})
    return True


def read_json(handler, fields=None):
    if handler.headers.get("Transfer-Encoding") or handler.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
        raise ValueError("json_required")
    lengths = handler.headers.get_all("Content-Length", [])
    if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,5}", lengths[0]) or not 1 <= int(lengths[0]) <= 16384:
        raise ValueError("body_size")
    handler.connection.settimeout(15)
    raw = handler.rfile.read(int(lengths[0]))
    if len(raw) != int(lengths[0]): raise ValueError("body_incomplete")
    body = json.loads(raw)
    if not isinstance(body, dict) or (fields is not None and set(body) != fields): raise ValueError("body_fields")
    return body


def read_file(handler):
    from conversation_files import MAX_BYTES
    if handler.headers.get('Transfer-Encoding') or handler.headers.get('Content-Type') != 'application/octet-stream':
        raise ValueError('binary_required')
    lengths = handler.headers.get_all('Content-Length', [])
    if len(lengths) != 1 or not re.fullmatch('[0-9]{1,8}', lengths[0]) or not 0 < int(lengths[0]) <= MAX_BYTES:
        raise ValueError('file_size')
    handler.connection.settimeout(30)
    raw = handler.rfile.read(int(lengths[0]))
    if len(raw) != int(lengths[0]):
        raise ValueError('file_incomplete')
    return raw


def stream_events(handler, service, user, conversation_id, after):
    if not re.fullmatch(r"[0-9]{1,12}", after): raise ValueError("after")
    # Authorize ownership before writing headers, including an empty event stream.
    service.detail(user, conversation_id)
    handler.send_response(200)
    for key, value in (("Content-Type", "text/event-stream; charset=utf-8"), ("Cache-Control", "no-store"),
                       ("X-Accel-Buffering", "no"), ("X-Content-Type-Options", "nosniff"),
                       ("Connection", "close")):
        handler.send_header(key, value)
    handler.end_headers()
    handler.close_connection = True
    cursor = int(after)
    end = time.monotonic() + 20
    try:
        while time.monotonic() < end:
            rows = service.events(user, conversation_id, cursor)
            for row in rows:
                cursor = max(cursor, row["seq"])
                handler.wfile.write(b"data: " + json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n\n")
            handler.wfile.flush()
            if rows: break
            time.sleep(1)
    except Exception:
        # The stream already has 200 headers; the browser reconnects and rechecks the cursor.
        return
