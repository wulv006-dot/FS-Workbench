"""Patch only the verified live FS HTTP and Nginx bytes into isolated candidates."""

import argparse
import hashlib
from pathlib import Path


RANGE_SHA = "833944f08aa2a9495cf8e0abfbf404ac2366d0eaaf42ee159f3e55ff646609c8"
NGINX_SHA = "43f64da9c7a1cdb04b2bbfa1bffc9eff985dc547df7e5298b77b8c19299130d8"


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("live_anchor_drift")
    return source.replace(old, new)


def build(live, output):
    source = (live / "range_api.py").read_bytes()
    nginx = (live / "formal.conf").read_bytes()
    if hashlib.sha256(source).hexdigest() != RANGE_SHA or hashlib.sha256(nginx).hexdigest() != NGINX_SHA:
        raise ValueError("fresh_live_source_sha_required")
    newline = b"\r\n" if b"\r\n" in source else b"\n"
    source = replace_once(source,
        b"ADVISOR=Advisor(snapshot,get_range,FC_DAILY,CACHE/'advisor',deep=DEEP)",
        b"from conversation_service import ConversationService" + newline +
        b"from conversation_http import handle as conversation_handle, respond as conversation_respond, PREFIX as CONVERSATION_PREFIX" + newline +
        b"CONVERSATION=ConversationService(HERMES,'/var/lib/fs-hermes-fc/fs/conversations','/run/fs-hermes-fc') if HERMES is not None else None" + newline +
        b"ADVISOR=Advisor(snapshot,get_range,FC_DAILY,CACHE/'advisor',deep=DEEP)")
    source = replace_once(source,
        b"  # Only the existing nginx auth_request identity is trusted; public headers are replaced.",
        b"  if uri.path==CONVERSATION_PREFIX or uri.path.startswith(CONVERSATION_PREFIX+'/'):" + newline +
        b"   if CONVERSATION is None:conversation_respond(self,503,{'error':'hermes_not_enabled'})" + newline +
        b"   else:conversation_handle(self,'GET',uri,self.headers.get('X-Auth-User'),CONVERSATION,hermes_authorizer)" + newline +
        b"   return" + newline +
        b"  # Only the existing nginx auth_request identity is trusted; public headers are replaced.")
    source = replace_once(source,
        b" def do_POST(self):" + newline + b"  uri=urlsplit(self.path)" + newline,
        b" def do_POST(self):" + newline + b"  uri=urlsplit(self.path)" + newline +
        b"  if uri.path==CONVERSATION_PREFIX or uri.path.startswith(CONVERSATION_PREFIX+'/'):" + newline +
        b"   if CONVERSATION is None:conversation_respond(self,503,{'error':'hermes_not_enabled'})" + newline +
        b"   else:conversation_handle(self,'POST',uri,self.headers.get('X-Auth-User'),CONVERSATION,hermes_authorizer)" + newline +
        b"   return" + newline)
    nl = b"\r\n" if b"\r\n" in nginx else b"\n"
    routes = """
# Hermes conversation center: same FS identity, admin checked again in the FS handler.
location = /api/hermes/conversations {
    if ($request_method !~ ^(GET|POST)$) { return 405; }
    auth_request /__auth_verify;
    auth_request_set $fs_conversation_user $upstream_http_x_auth_user;
    proxy_set_header X-Auth-User $fs_conversation_user;
    proxy_set_header X-Auth-Role "";
    proxy_set_header Cookie "";
    proxy_set_header Authorization "";
    client_max_body_size 16k;
    proxy_pass http://127.0.0.1:8931;
    proxy_read_timeout 35s;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}
location ^~ /api/hermes/conversations/ {
    if ($request_method !~ ^(GET|POST)$) { return 405; }
    auth_request /__auth_verify;
    auth_request_set $fs_conversation_user $upstream_http_x_auth_user;
    proxy_set_header X-Auth-User $fs_conversation_user;
    proxy_set_header X-Auth-Role "";
    proxy_set_header Cookie "";
    proxy_set_header Authorization "";
    client_max_body_size 16k;
    proxy_pass http://127.0.0.1:8931;
    proxy_read_timeout 35s;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}
location = /dashboard/fs-home/hermes/conversation/ {
    if ($request_method !~ ^(GET|HEAD)$) { return 405; }
    auth_request /__auth_verify;
    error_page 401 = @auth_login;
    alias /var/www/dashboard/fs-home/hermes/conversation/index.html;
    disable_symlinks on;
    add_header Cache-Control "no-store" always;
}
"""
    for name in ("index.html", "conversation.css", "conversation.js"):
        routes += f"""location = /dashboard/fs-home/hermes/conversation/{name} {{
    if ($request_method !~ ^(GET|HEAD)$) {{ return 405; }}
    auth_request /__auth_verify;
    error_page 401 = @auth_login;
    alias /var/www/dashboard/fs-home/hermes/conversation/{name};
    disable_symlinks on;
    add_header Cache-Control "no-store" always;
}}
"""
    nginx += routes.replace("\n", nl.decode()).encode("utf-8")
    output.mkdir(parents=True, exist_ok=False)
    (output / "range_api.py").write_bytes(source)
    (output / "formal.conf").write_bytes(nginx)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--live", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    build(a.live, a.output)
