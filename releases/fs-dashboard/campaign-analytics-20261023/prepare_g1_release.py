"""Prepare an unapproved G1 package for the existing publisher. Never connects or installs.

Inputs must be an exact Git module export, a controller-captured remote baseline and
an accepted-base mapping {candidate-relative path: exact accepted Git blob SHA256}.
Optional accepted-export and deployed-source evidence must be supplied together;
only exact raw-hash-verified CRLF/LF divergence can reconcile a deployed base.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path, PurePosixPath

PUBLIC_NAMES = set('''index.html Weekly-Scout.html Sbc-Companions.html Player-Trio.html
activity.css activity.js activity-core.js activity-content.js host-adapter.js standalone-adapter.js
activity-analytics.js analytics-config.js catalog.js sitemap.xml robots.txt
seasonal/index.html seasonal/creative-kit.html seasonal/event.js seasonal/event.css seasonal/vault-core.js
seasonal/campaign-data.js seasonal/kit.js seasonal/kit.css seasonal/vault-analytics.js
seasonal/activity-analytics.js seasonal/analytics-config.js seasonal/runtime-bridge.js'''.split())
PUBLIC_REQUIRED = {'index.html', 'Weekly-Scout.html', 'Sbc-Companions.html', 'Player-Trio.html', 'seasonal/index.html'}
PUBLIC_ASSET = re.compile(r'^(?:seasonal/)?assets/[A-Za-z0-9_.-]+\.(?:webp|png|svg|jpg|jpeg|gif|woff2)$')
HASH = re.compile(r'^[a-f0-9]{64}$')
COMMIT = re.compile(r'^[a-f0-9]{40}$')
TEXT_SUFFIXES = {'.js', '.mjs', '.cjs', '.html', '.css', '.json', '.xml', '.svg', '.txt', '.md', '.py'}
GUARDS = {'/opt/auth-portal/auth_portal.py', '/opt/fs-access-policy/rbac.py'}
NGINX_APPEND = b'''\n# FS campaign G1 customer runtime: management locations above are unchanged.
location ^~ /events/ {
    auth_request off;
    sub_filter "</body>" "</body>";
    proxy_pass http://127.0.0.1:8949;
    proxy_set_header Host $host;
    proxy_set_header Cookie "";
    proxy_set_header Authorization "";
    proxy_hide_header Set-Cookie;
    proxy_cache off;
}
'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + '\n').encode('utf-8')


def safe_relative(value):
    if not isinstance(value, str):
        raise ValueError('unsafe candidate path')
    path = PurePosixPath(value)
    if ('\\' in value or path.is_absolute()
            or path.as_posix() != value or any(part in ('', '.', '..') for part in value.split('/'))):
        raise ValueError('unsafe candidate path: ' + str(value))
    return value


def read_source(root, relative):
    path = root / safe_relative(relative)
    for component in (path, *path.parents):
        if component == root.parent:
            break
        if component.is_symlink():
            raise ValueError('source symlink refused: ' + relative)
    if not path.is_file() or root.resolve() not in path.resolve().parents:
        raise ValueError('source file missing: ' + relative)
    return path.read_bytes()


def load_publisher(export):
    path = export / 'publish.py'
    read_source(export, 'publish.py')
    native = read_source(export, 'native/release_navigation_base.py')
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('campaign_g1_export_publisher', path)
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)
    finally:
        sys.dont_write_bytecode = previous
    if sha(native) != publisher.BASE_SHA:
        raise ValueError('frozen publisher native hash mismatch')
    if not hasattr(publisher, 'BACKEND_FILES') or not hasattr(publisher, 'RUNTIME_SPECIAL'):
        raise ValueError('export lacks current campaign publisher allowlist')
    return publisher


def service_revision(original, commit):
    lines = original.splitlines(keepends=True)
    sections = [n for n, line in enumerate(lines) if line.strip() == b'[Service]']
    if len(sections) != 1 or b'CAMPAIGN_SOURCE_REVISION=' in original:
        raise ValueError('unit Service section or revision environment is ambiguous')
    if b'ExecStart=/usr/local/bin/node ' not in original:
        raise ValueError('unit must retain actual /usr/local/bin/node executable')
    start = sections[0]
    stop = next((n for n in range(start + 1, len(lines)) if lines[n].lstrip().startswith(b'[')), len(lines))
    newline = b'\r\n' if lines[start].endswith(b'\r\n') else b'\n'
    prefix = b''.join(lines[:stop])
    if prefix and not prefix.endswith(b'\n'):
        prefix += newline
    return prefix + b'Environment=CAMPAIGN_SOURCE_REVISION=' + commit.encode('ascii') + newline + b''.join(lines[stop:])


def public_name(relative):
    return relative in PUBLIC_NAMES or bool(PUBLIC_ASSET.fullmatch(relative))


def line_ending_proof(relative, target, accepted_hash, remote_hash, accepted_export, deployed_source):
    if PurePosixPath(relative).suffix not in TEXT_SUFFIXES:
        raise ValueError('line-ending reconciliation requires text source: ' + relative)
    accepted = read_source(accepted_export, relative)
    deployed_relative = PurePosixPath(target).relative_to('/opt/fs-campaign-dashboard').as_posix()
    deployed = read_source(deployed_source, deployed_relative)
    if sha(accepted) != accepted_hash:
        raise ValueError('accepted export raw SHA differs from accepted-base map: ' + relative)
    if sha(deployed) != remote_hash:
        raise ValueError('deployed readback raw SHA differs from baseline: ' + relative)
    normalized = accepted.replace(b'\r\n', b'\n')
    if normalized != deployed.replace(b'\r\n', b'\n'):
        raise ValueError('content differs beyond CRLF/LF: ' + relative)
    return dict(candidate=relative, target=target, acceptedSha256=accepted_hash,
                deployedSha256=remote_hash, normalizedSha256=sha(normalized),
                normalization='replace_CRLF_with_LF_only')


def prepare(export, baseline, commit, output, accepted_base, accepted_export=None, deployed_source=None):
    export, output = Path(export).resolve(), Path(output).resolve()
    if (accepted_export is None) != (deployed_source is None):
        raise ValueError('accepted-export and deployed-source evidence must be supplied together')
    if accepted_export is not None:
        accepted_export, deployed_source = Path(accepted_export).resolve(), Path(deployed_source).resolve()
        if any(output == root or root in output.parents for root in (accepted_export, deployed_source)):
            raise ValueError('output must be outside reconciliation evidence directories')
    if not COMMIT.fullmatch(commit):
        raise ValueError('full source Git commit required')
    if output.exists() or output == export or export in output.parents:
        raise ValueError('output must be a new directory outside source export')
    if set(baseline.get('guards', {})) != GUARDS:
        raise ValueError('exact existing authentication guards required')
    if baseline.get('node_executable') != '/usr/local/bin/node':
        raise ValueError('actual Node executable baseline required')
    for value in list(baseline['files'].values()) + list(baseline['guards'].values()):
        if not isinstance(value, str) or not HASH.fullmatch(value):
            raise ValueError('invalid baseline SHA256')
    for relative, digest in accepted_base.items():
        safe_relative(relative)
        if not relative.startswith(('app/', 'backend/')) or not isinstance(digest, str) or not HASH.fullmatch(digest):
            raise ValueError('invalid accepted-base entry: ' + relative)
    tools = {name: read_source(export, name) for name in ('publish.py', 'native/release_navigation_base.py')}
    publisher = load_publisher(export)
    if any(read_source(export, name) != raw for name, raw in tools.items()):
        raise ValueError('export publisher changed during preparation')
    candidates, before, skipped, source_hashes = {}, {}, [], {}

    def stage(relative, content, old):
        safe_relative(relative)
        target = publisher.target(relative)
        if old is not None and not HASH.fullmatch(old):
            raise ValueError('invalid target baseline hash: ' + target)
        candidates[relative], before[relative] = content, old

    def special_bytes(name):
        target = publisher.SPECIAL[name]
        item = baseline['specials'].get(target)
        if not isinstance(item, dict):
            raise ValueError('exact existing special bytes required: ' + target)
        raw = base64.b64decode(item['content_base64'], validate=True)
        if sha(raw) != item['sha256']:
            raise ValueError('special baseline bytes/hash conflict: ' + target)
        return raw, item['sha256']

    for name in ('navigation.json', 'module-registry.json'):
        raw, old = special_bytes(name)
        stage(name, raw, old)
    nginx, old = special_bytes('navigation.conf')
    if re.search(rb'\blocation\s+[^\r\n{]*?/events(?:/|\s|\{)', nginx):
        raise ValueError('existing events location requires explicit reconciliation')
    stage('navigation.conf', nginx + NGINX_APPEND, old)
    unit, old = special_bytes('fs-campaign-dashboard.service')
    stage('fs-campaign-dashboard.service', service_revision(unit, commit), old)

    runtime_target = publisher.SPECIAL['fs-campaign-runtime.service']
    if runtime_target in baseline['specials']:
        runtime_unit, old = special_bytes('fs-campaign-runtime.service')
    else:
        if baseline.get('runtime_unit_exists') is not False:
            raise ValueError('runtime unit absence or exact existing bytes required')
        runtime_unit, old = read_source(export, 'fs-campaign-runtime.service'), None
    stage('fs-campaign-runtime.service', service_revision(runtime_unit, commit), old)
    environment = dict(CAMPAIGN_PUBLIC_MODE='preview', CAMPAIGN_PUBLIC_PORT='8949',
        CAMPAIGN_PUBLIC_ROOT='/opt/fs-campaign-dashboard',
        CAMPAIGN_PUBLIC_RELEASE='/var/lib/fs-campaign-public/current.json',
        CAMPAIGN_PUBLIC_MANIFEST='/opt/fs-campaign-dashboard/runtime/static-manifest.json',
        CAMPAIGN_PUBLIC_ORIGIN='https://47.85.224.112', CAMPAIGN_PUBLIC_PREFIX='/events/',
        CAMPAIGN_RUNTIME_DATA='/var/lib/fs-campaign-runtime', CAMPAIGN_SOURCE_REVISION=commit)
    runtime_env = ''.join(key + '=' + value + '\n' for key, value in sorted(environment.items())).encode('ascii')
    if publisher.SPECIAL['runtime.env'] in baseline['specials']:
        raw, old = special_bytes('runtime.env')
        if raw != runtime_env:
            raise ValueError('existing runtime environment requires explicit reconciliation')
    else:
        old = None  # Publisher inspect requires absence and refuses any unexpectedly existing file.
    stage('runtime.env', runtime_env, old)

    source_paths = []
    for path in sorted((export / 'app').rglob('*')):
        if path.is_symlink():
            raise ValueError('source symlink refused: ' + str(path.relative_to(export)))
        if not path.is_file():
            continue
        relative = path.relative_to(export).as_posix()
        parts = PurePosixPath(relative).parts
        if (any(part in ('tests', 'validation', 'docs', '__pycache__') for part in parts[1:-1]) or path.suffix == '.md'
                or relative == 'app/runtime/static-manifest.json'):
            continue
        publisher.target(relative)
        source_paths.append(relative)
    source_paths += ['backend/' + name for name in sorted(publisher.BACKEND_FILES)]
    public, reconciliations = {}, []
    for relative in source_paths:
        raw = read_source(export, relative)
        digest, target = sha(raw), publisher.target(relative)
        source_hashes[relative] = digest
        remote, accepted = baseline['files'].get(target), accepted_base.get(relative)
        is_public = relative.startswith('app/') and public_name(relative[4:])
        public_digest = digest
        proof = None
        if (accepted_export is not None and remote is not None and accepted is not None
                and remote != accepted and remote != digest):
            proof = line_ending_proof(relative, target, accepted, remote, accepted_export, deployed_source)
            reconciliations.append(proof)
        if remote == digest:
            skipped.append(relative)
        elif remote is None and is_public:
            stage(relative, raw, None)  # An allowlisted public file never installed is an absent-CAS addition.
        elif accepted is not None and digest == accepted:
            if is_public:
                if proof is None:
                    raise ValueError('public customization requires reviewed bytes: ' + target + ' remote=' + str(remote) + ' export=' + digest)
                public_digest = remote  # Keep exact deployed bytes, verified by the raw readback hash.
            skipped.append(relative)  # Unchanged Git management bytes must not overwrite deployed customization.
        elif remote is None and accepted is None:
            stage(relative, raw, None)
        elif remote == accepted or proof is not None:
            stage(relative, raw, remote)
        else:
            raise ValueError('deployed customization or missing accepted base: ' + target + ' remote=' + str(remote)
                             + ' accepted=' + str(accepted) + ' export=' + digest)
        if is_public:
            public[relative[4:]] = public_digest
    if not PUBLIC_REQUIRED.issubset(public):
        raise ValueError('required FC/seasonal public pages missing')
    static_relative = 'app/runtime/static-manifest.json'
    static_target = publisher.target(static_relative)
    stage(static_relative, encoded(public), baseline['files'].get(static_target))

    rows = [dict(candidate=name, target=publisher.target(name), sha256=sha(raw), beforeSha256=before[name])
            for name, raw in sorted(candidates.items())]
    manifest = dict(schemaVersion=1, scope=publisher.SCOPE, sourceRevision=commit,
        releaseReady=False, targets={row['candidate']: row['target'] for row in rows}, files=rows,
        unchangedRequired=[dict(path=path, sha256=baseline['guards'][path]) for path in sorted(GUARDS)],
        publicSnapshotRequiredAtPackageTime=False,
        baselineCapture=baseline.get('utc'), sourceFilesSha256=source_hashes,
        packagingToolsSha256={name: sha(raw) for name, raw in tools.items()},
        acceptedBaseRevision='2c976e7f849b3b7916e006dd6907e633051cb3fb',
        acceptedBaseMapSha256=sha(encoded(accepted_base)),
        lineEndingReconciliations=reconciliations,
        lineEndingReconciliationSha256=sha(encoded(reconciliations)),
        skippedUnchangedFiles=sorted(skipped), publicStaticFiles=sorted(public))
    output.mkdir(parents=True)
    for name, raw in candidates.items():
        path = output / 'candidate' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    publisher.validate(manifest, output)
    for relative, tool_bytes in tools.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(tool_bytes)
    raw = encoded(manifest)
    (output / 'approved-manifest.json').write_bytes(raw)
    (output / 'approved-manifest.sha256').write_text(sha(raw) + '\n', encoding='ascii')
    return dict(stage=str(output), sourceRevision=commit, releaseReady=False,
                approvedManifestSha256=sha(raw), stagedFiles=len(rows), publicStaticFiles=len(public))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', required=True, type=Path)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--accepted-base', required=True, type=Path)
    parser.add_argument('--accepted-export', type=Path,
                        help='exact accepted module export; requires --deployed-source')
    parser.add_argument('--deployed-source', type=Path,
                        help='exact readback root under /opt/fs-campaign-dashboard, without app/ prefix')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.export, json.loads(args.baseline.read_text('utf-8')), args.source_commit,
                     args.output, json.loads(args.accepted_base.read_text('utf-8')),
                     accepted_export=args.accepted_export, deployed_source=args.deployed_source)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
