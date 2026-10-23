"""Read-only Hermes profile inventory; never read auth.json or .env."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3

PROFILE = Path('/profile')


def redact(text):
    text = re.sub(r'(?im)^.*(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|authorization)\s*[:=].*$', '[credential field omitted]', text)
    text = re.sub(r'\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{15,})\b', '[token omitted]', text)
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', '[email omitted]', text)
    text = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----', '[private key omitted]', text)
    return text


def file_info(path, content=False):
    b = path.read_bytes()
    result = {'path': str(path), 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
    if content:
        result['content'] = redact(b.decode('utf-8', errors='replace'))
    return result


def main():
    assert redact('api_key: secret\na@b.com\nsk-abcdefghijklmnop') == '[credential field omitted]\n[email omitted]\n[token omitted]'
    result = {'profile': str(PROFILE), 'memory_files': [], 'skills': [], 'database_schema': {}, 'jobs': []}
    for name in ('MEMORY.md', 'USER.md', 'AGENTS.md', 'SOUL.md'):
        p = PROFILE / name
        if p.is_file():
            result['memory_files'].append(file_info(p, True))
    for p in sorted((PROFILE / 'memories').rglob('*.md')):
        result['memory_files'].append(file_info(p, True))
    for p in sorted((PROFILE / 'skills').rglob('SKILL.md')):
        result['skills'].append(file_info(p))
    for name in ('config.yaml',):
        result[name] = file_info(PROFILE / name, True)
    jobs = json.loads((PROFILE / 'cron/jobs.json').read_text())
    result['cron_shape'] = list(jobs) if isinstance(jobs, dict) else 'list'
    values = jobs.get('jobs', []) if isinstance(jobs, dict) else jobs
    for j in values:
        result['jobs'].append({k: redact(v) if isinstance(v, str) else v for k, v in j.items() if k not in ('delivery', 'last_output', 'last_result')})
    for name in ('state.db', 'cron/executions.db'):
        db = sqlite3.connect('file:' + str(PROFILE / name) + '?mode=ro', uri=True, timeout=5)
        db.execute('PRAGMA query_only=ON')
        result['database_schema'][name] = [{'name': r[0], 'sql': r[1]} for r in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE '%fts%' ORDER BY name")]
        db.close()
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
