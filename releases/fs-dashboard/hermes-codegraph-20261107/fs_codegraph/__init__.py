"""Native Hermes access to CodeGraph; production directories are never query targets."""
import json
import os
from pathlib import Path
import subprocess
import threading

ROOT = Path('/profile/cache/fs-codegraph')
REPOSITORY = Path('/profile/cache/workspaces/FS-Workbench')
MANIFEST = ROOT / 'projects.json'
BINARY = Path('/profile/tools/codegraph/1.6.2/codegraph-linux-x64/bin/codegraph')
LOCK = threading.Lock()


def projects():
    with MANIFEST.open(encoding='utf-8') as stream:
        return json.load(stream)


def project_path(entry):
    path = Path(entry['path']).resolve()
    allowed = [(ROOT / 'sources').resolve(), REPOSITORY.resolve()]
    if not any(base == path or base in path.parents for base in allowed):
        raise ValueError('codegraph_workspace_outside_analysis_roots')
    if not path.is_dir():
        raise ValueError('codegraph_workspace_missing')
    return path


def run(arguments, path):
    env = {key: value for key, value in os.environ.items() if key in
           {'PATH', 'LANG', 'LC_ALL', 'TZ', 'HOME', 'USER', 'LOGNAME', 'TMPDIR', 'XDG_CACHE_HOME'}}
    env['CODEGRAPH_TELEMETRY'] = '0'
    return subprocess.run([str(BINARY), *arguments], cwd=str(path), env=env,
                          capture_output=True, text=True, timeout=90)


def call(name, args):
    if not isinstance(args, dict):
        raise ValueError('codegraph_arguments_must_be_object')
    if name == 'codegraph_projects':
        if args:
            raise ValueError('codegraph_projects_takes_no_arguments')
        return projects()
    if name != 'codegraph_explore' or set(args) - {'workspace', 'query', 'maxFiles'}:
        raise ValueError('codegraph_tool_or_arguments_denied')
    workspace, query, maximum = args.get('workspace'), args.get('query'), args.get('maxFiles', 12)
    if not isinstance(workspace, str) or not isinstance(query, str) or not query.strip() or len(query) > 4096:
        raise ValueError('codegraph_workspace_and_query_required')
    if type(maximum) is not int or not 1 <= maximum <= 12:
        raise ValueError('codegraph_maxFiles_must_be_1_to_12')
    manifest = projects()
    entry = manifest['projects'].get(workspace)
    if not isinstance(entry, dict):
        raise ValueError('codegraph_unknown_workspace')
    path = project_path(entry)
    if not (path / '.codegraph/codegraph.db').is_file():
        return {'status': 'not_indexed', 'workspace': workspace, 'error': 'approved_workspace_needs_initial_index'}
    with LOCK:
        try:
            synced = run(['sync', '--quiet', str(path)], path)
            if synced.returncode:
                return {'status': 'error', 'step': 'sync', 'workspace': workspace,
                        'exit_code': synced.returncode, 'error': synced.stderr or synced.stdout}
            result = run(['explore', '--path', str(path), '--max-files', str(maximum), '--', query], path)
        except subprocess.TimeoutExpired:
            return {'status': 'error', 'workspace': workspace, 'error': 'codegraph_timeout'}
        except OSError as error:
            return {'status': 'error', 'workspace': workspace, 'error': str(error)}
    return {'status': 'ok' if result.returncode == 0 else 'error', 'workspace': workspace,
            'source_kind': entry['source_kind'], 'captured_at': manifest['captured_at'],
            'exit_code': result.returncode, 'warnings': synced.stderr + result.stderr, 'content': result.stdout}


def register(ctx):
    schemas = {
        'codegraph_projects': {
            'name': 'codegraph_projects',
            'description': 'List approved indexed FS code workspaces and their source provenance. Production snapshots describe their capture time, not current deployment state.',
            'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
        'codegraph_explore': {
            'name': 'codegraph_explore',
            'description': 'Read relevant source and call paths from an approved workspace. List codegraph_projects first to select its workspace ID. Automatically syncs the local index before each query. Missing graph edges do not prove production files unused.',
            'parameters': {'type': 'object', 'properties': {
                'workspace': {'type': 'string'}, 'query': {'type': 'string'},
                'maxFiles': {'type': 'integer', 'minimum': 1, 'maximum': 12}},
                'required': ['workspace', 'query'], 'additionalProperties': False}},
    }
    for name, schema in schemas.items():
        def handler(args, _name=name, **context):
            try:
                result = call(_name, args)
            except (ValueError, KeyError, OSError) as error:
                result = {'status': 'blocked', 'error': str(error)}
            return json.dumps(result, ensure_ascii=False, allow_nan=False)
        ctx.register_tool(name=name, toolset='fs_codegraph', schema=schema, handler=handler)
