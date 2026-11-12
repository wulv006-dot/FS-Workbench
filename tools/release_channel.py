#!/usr/bin/env python3
"""Server-local restricted entry to the existing business HTML publisher.

No SSH, shell command passthrough, service, credentials or alternate writer.
This is a workflow guard, not an OS security boundary for a root caller.
"""
import argparse
import hashlib
import types
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = 'fs_dashboard_overwrite_20261003/release_gateway.py'
REPOSITORY = 'wulv006-dot/FS-Workbench'


class Refused(RuntimeError):
    pass


def command(args):
    result = subprocess.run(args, cwd=ROOT, check=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=60)
    return result.stdout


def tracked_bytes(sha, path):
    return command(['git', 'show', sha + ':' + path])


def checked_path(value):
    if not isinstance(value, str) or not re.fullmatch(r'releases/[A-Za-z0-9_./-]+', value):
        raise Refused('manifest must be a repository-relative releases/ path')
    if any(part in ('', '.', '..') for part in value.split('/')):
        raise Refused('unsafe manifest path')
    return value


def validate_checks(value, sha):
    runs = value.get('check_runs', [])
    if value.get('total_count') != len(runs):
        raise Refused('incomplete CI check response')
    if not runs or any(run.get('head_sha') != sha or run.get('status') != 'completed'
                       or run.get('conclusion') not in ('success', 'neutral', 'skipped') for run in runs):
        raise Refused('CI is incomplete or failed for this exact SHA')
    if not any(run.get('name') == 'pr-fast' and run.get('conclusion') == 'success'
               and run.get('app', {}).get('slug') == 'github-actions' for run in runs):
        raise Refused('successful GitHub Actions pr-fast for this exact SHA required')


def verify_workflow(checks, sha):
    prefix = 'repos/' + REPOSITORY + '/actions/'
    runs = json.loads(command(['gh', 'api', prefix + 'workflows/pr-fast.yml/runs?event=push&head_sha=' + sha + '&per_page=100']))
    items = runs.get('workflow_runs', [])
    if runs.get('total_count') != len(items) or not items:
        raise Refused('complete exact-main workflow evidence required')
    run = max(items, key=lambda item: (item['run_number'], item.get('run_attempt', 1)))
    if (run.get('path') != '.github/workflows/pr-fast.yml' or run.get('head_sha') != sha
            or run.get('event') != 'push' or run.get('head_branch') != 'main'
            or run.get('head_repository', {}).get('full_name') != REPOSITORY
            or run.get('status') != 'completed' or run.get('conclusion') != 'success'):
        raise Refused('trusted main workflow is not successful')
    jobs = json.loads(command(['gh', 'api', prefix + 'runs/' + str(int(run['id'])) + '/jobs?filter=latest&per_page=100']))
    items = jobs.get('jobs', [])
    if jobs.get('total_count') != len(items):
        raise Refused('incomplete workflow job evidence')
    trusted = {'https://api.github.com/repos/' + REPOSITORY + '/check-runs/' + str(int(check['id']))
               for check in checks['check_runs'] if check.get('name') == 'pr-fast'
               and check.get('app', {}).get('slug') == 'github-actions' and check.get('conclusion') == 'success'}
    if not any(job.get('name') == 'pr-fast' and job.get('conclusion') == 'success'
               and job.get('check_run_url') in trusted for job in items):
        raise Refused('check is not from the expected workflow')


def load_gateway(source):
    gateway = types.ModuleType('fs_business_release_gateway')
    gateway.__file__ = str(ROOT / GATEWAY)
    exec(compile(source, gateway.__file__, 'exec'), gateway.__dict__)
    original_lock = gateway.Lock

    class ReconciledLock(original_lock):
        def __enter__(self):
            result = super().__enter__()
            try:
                if (self.path.parent.parent / 'lib/fs-dashboard-release/pending.json').exists():
                    raise Refused('unresolved publication intent; reconcile before retry')
            except BaseException:
                self.__exit__(None, None, None)
                raise
            return result
    gateway.Lock = ReconciledLock
    return gateway


def prepare(module, sha, manifest):
    if module != 'business-html':
        raise Refused('unsupported module; no publisher mapping')
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise Refused('full lowercase main SHA required')
    manifest = checked_path(manifest)
    remote = command(['git', 'remote', 'get-url', 'origin']).decode().strip()
    if remote not in ('https://github.com/' + REPOSITORY, 'https://github.com/' + REPOSITORY + '.git'):
        raise Refused('unexpected origin')
    command(['git', 'fetch', 'origin', 'main'])
    if command(['git', 'rev-parse', 'origin/main']).decode().strip() != sha:
        raise Refused('requested SHA is not current origin/main')
    if command(['git', 'rev-parse', 'HEAD']).decode().strip() != sha:
        raise Refused('run from a checkout of the requested main SHA')
    if command(['git', 'status', '--porcelain', '--untracked-files=all']).strip():
        raise Refused('clean release checkout required')
    checks = json.loads(command(['gh', 'api', 'repos/' + REPOSITORY + '/commits/' + sha + '/check-runs?per_page=100']))
    validate_checks(checks, sha)
    verify_workflow(checks, sha)
    # Read only tracked bytes at the specified commit; no historical CAS reuse.
    raw = tracked_bytes(sha, manifest)
    spec = json.loads(raw)
    source = spec.get('source', 'dashboard.html')
    if not isinstance(source, str) or not re.fullmatch('[A-Za-z0-9_-]+\\.html', source):
        raise Refused('flat HTML source required')
    stage = (ROOT / manifest).parent
    paths = {manifest: raw, GATEWAY: tracked_bytes(sha, GATEWAY)}
    payload_path = str(Path(manifest).parent / source).replace('\\', '/')
    paths[payload_path] = tracked_bytes(sha, payload_path)
    for relative, expected in paths.items():
        file = ROOT / relative
        if file.is_symlink() or any(p.is_symlink() for p in file.parents if p != ROOT.parent):
            raise Refused('symlink release input refused')
        if file.read_bytes() != expected:
            raise Refused('release input differs from main SHA')
    if hashlib.sha256(paths[payload_path]).hexdigest() != spec.get('sha256'):
        raise Refused('payload digest differs from manifest')
    return stage / Path(manifest).name, spec


def execute(module, sha, manifest, apply=False):
    path, spec = prepare(module, sha, manifest)
    result = {'status': 'planned', 'module': module, 'commit': sha,
              'releaseId': spec.get('releaseId'), 'production_changed': False}
    if not apply:
        return result
    # Existing gateway owns locks, current-baseline CAS, seven dependency checks,
    # backups, pending-intent ledger and post-write digest. No new rollback path.
    gateway = load_gateway(tracked_bytes(sha, GATEWAY))
    receipt = gateway.publish('/', path)
    return dict(result, status='published_readback_pending', production_changed=True,
                receipt=receipt, business_acceptance='pending')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', choices=['business-html'], required=True)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args.module, args.sha, args.manifest, args.apply)))
    except Exception:
        # Subprocess stderr may contain authenticated URLs; do not echo it.
        # An apply failure can occur after rename: never claim no side effects.
        print(json.dumps({'status': 'stopped_reconcile_before_retry',
                          'production_changed': 'unknown' if args.apply else False}))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
