"""Append one authenticated POST lookup route; preserve every existing route byte."""
ROUTE = b'''# User analytics email lookup: same IAM, private POST body, no email in URL.
location = /dashboard/users/search.json {
    if ($request_method != POST) { return 405; }
    client_max_body_size 4k;
    auth_request /__auth_verify;
    auth_request_set $fs_users_search_user $upstream_http_x_auth_user;
    proxy_set_header X-Auth-User $fs_users_search_user;
    proxy_set_header X-Auth-Role "";
    proxy_set_header Cookie "";
    proxy_set_header Authorization "";
    proxy_pass http://127.0.0.1:8931/users/private/search;
    proxy_connect_timeout 3s;
    proxy_read_timeout 25s;
    add_header Cache-Control "no-store" always;
}
'''


def patch(current):
    if b'/dashboard/users/search.json' in current or current.count(b'location = /dashboard/users/private.json') != 1:
        raise ValueError('search_route_baseline_changed')
    return current + b'\n' + ROUTE
