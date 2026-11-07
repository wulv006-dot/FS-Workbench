import json
import subprocess
from pathlib import Path

ROOT = Path('/tmp/fc27-news-router-20261108')
for source in ('mmoexp', 'ea'):
    try:
        result = subprocess.run(['runuser', '-u', 'nobody', '--', '/usr/bin/python3', '-I',
                                 str(ROOT/'worker.py')], input=json.dumps({'source': source}),
                                text=True, capture_output=True, timeout=40)
        (ROOT/(source+'.json')).write_text(result.stdout, encoding='utf-8')
        print(json.dumps({'source': source, 'code': result.returncode,
                          'bytes': len(result.stdout), 'error': result.stderr.strip()[:80]}))
    except subprocess.TimeoutExpired:
        print(json.dumps({'source': source, 'error': 'timeout'}))
