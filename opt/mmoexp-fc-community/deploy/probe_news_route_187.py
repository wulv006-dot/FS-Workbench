import json
import subprocess
import sys
sys.path.insert(0, '/tmp/fc27-news-route-20261108')
from collector_router import fetch_remote_html
for source in ('mmoexp', 'ea'):
    try:
        html = fetch_remote_html(source, key_path='/etc/mmoexp-fc-news/collector_ed25519',
                                 known_hosts='/etc/mmoexp-fc-news/known_hosts')
        print(json.dumps({'source': source, 'ok': True, 'html_bytes': len(html.encode('utf-8'))}))
    except Exception as exc:
        print(json.dumps({'source': source, 'ok': False, 'error': str(exc)}))
cmd = ['ssh','-T','-i','/etc/mmoexp-fc-news/collector_ed25519','-o','BatchMode=yes',
       '-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
       '-o','UserKnownHostsFile=/etc/mmoexp-fc-news/known_hosts','-o','ConnectTimeout=8',
       '-o','HostKeyAlias=47.85.170.62','fc27-news-fetch@172.18.108.183','id']
result = subprocess.run(cmd, input='{"source":"http://127.0.0.1"}\n', text=True,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
print(json.dumps({'forced_command_invalid_source_rejected': result.returncode != 0,
                  'shell_not_run': 'uid=' not in result.stdout,
                  'stderr': result.stderr.strip()[:160]}))
