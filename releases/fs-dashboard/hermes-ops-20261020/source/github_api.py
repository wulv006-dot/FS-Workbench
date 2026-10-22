"""Use the existing Hermes GitHub identity; never print or copy its token."""
import base64
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

REPO = 'wulv006-dot/FS-Workbench'

class GitHub:
    def __init__(self, token_file):
        value = Path(token_file).read_text('utf-8')
        match = re.search(r'(?m)^\s*oauth_token:\s*(\S+)', value)
        if not match:
            raise ValueError('existing_github_identity_missing')
        self.token = match.group(1).strip('"\'')

    def request(self, method, path, body=None):
        if not path.startswith('/') or '..' in path:
            raise ValueError('repository_relative_api_required')
        request = Request('https://api.github.com/repos/' + REPO + path,
                          data=None if body is None else json.dumps(body).encode(), method=method,
                          headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json', 'User-Agent': 'FS-Hermes-Ops'})
        with urlopen(request, timeout=20) as response:
            return json.load(response)

    def file(self, path, ref):
        from urllib.parse import quote
        result = self.request('GET', '/contents/' + quote(path, safe='/') + '?ref=' + quote(ref, safe=''))
        if result.get('encoding') == 'none':
            if not re.fullmatch(r'[a-f0-9]{40}',result.get('sha','')):raise ValueError('invalid_github_blob_identity')
            result = self.request('GET','/git/blobs/' + result['sha'])
        return base64.b64decode(''.join(result['content'].split()),validate=True)

    def create_pr(self, branch, title, body, files, expected_base=None):
        # A failed/unknown write is reconciled by its fixed branch/PR, never repeated here.
        head = self.request('GET', '/git/ref/heads/main')['object']['sha']
        if expected_base is not None and head != expected_base: raise ValueError('bootstrap_base_changed')
        commit = self.request('GET', '/git/commits/' + head)
        tree = self.request('POST', '/git/trees', {'base_tree': commit['tree']['sha'], 'tree': [dict(path=p, mode='100644', type='blob', content=b.decode('utf-8')) for p, b in files.items()]})
        new = self.request('POST', '/git/commits', {'message': title, 'tree': tree['sha'], 'parents': [head]})
        self.request('POST', '/git/refs', {'ref': 'refs/heads/' + branch, 'sha': new['sha']})
        pr = self.request('POST', '/pulls', {'head': branch, 'base': 'main', 'title': title, 'body': body, 'draft': False})
        return {'number': pr['number'], 'url': pr['html_url'], 'head': new['sha'], 'base': head, 'branch': branch}

    def ready(self, pr):
        current = self.request('GET', '/pulls/' + str(pr['number']))
        if current['head']['sha'] != pr['head'] or current['base']['sha'] != pr['base']:
            raise ValueError('pr_head_or_base_changed')
        if self.request('GET', '/git/ref/heads/main')['object']['sha'] != pr['base']:
            raise ValueError('main_changed_retest_required')
        checks = self.request('GET', '/commits/' + pr['head'] + '/check-runs?per_page=100')['check_runs']
        required = [c for c in checks if c['name'] == 'pr-fast']
        if not required or any(c['status'] != 'completed' for c in required):
            return False
        if any(c['conclusion'] != 'success' for c in required) or current.get('mergeable_state') != 'clean':
            raise ValueError('ci_or_mergeability_failed')
        return True
