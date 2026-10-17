import sys

P = '/etc/nginx/conf.d/iggm-web.conf'
MARKER = '    # <<< unified-dashboard (auto) <<<'
BLOCK = '''    # >>> fc27-bundles-api (auto) >>>
    location /dashboard/fc27-bundles-api/ {
        auth_request /__auth_verify;
        error_page 401 = @auth_login;
        proxy_pass http://127.0.0.1:8904/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        add_header Cache-Control "no-store" always;
    }
    # <<< fc27-bundles-api (auto) <<<

'''

src = open(P, encoding='utf-8').read()
if 'fc27-bundles-api' in src:
    print('ALREADY_INJECTED')
    sys.exit(0)
if src.count(MARKER) != 1:
    print('MARKER_NOT_UNIQUE:%d' % src.count(MARKER))
    sys.exit(2)
open(P, 'w', encoding='utf-8').write(src.replace(MARKER, BLOCK + MARKER))
print('INJECTED')
