"""Export code only, including the exact existing Lootbar reader; never a server tree."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOOTBAR = {
    'lootbar_server_collector.py': '4d19dcf18bf6705bbf6aa6590ca660a974f8e1d006b7b9bbd4bb0673f4f52103',
    'background.js': '4f36ad8a9723039912727f64bb6a3f20da0c657dc2a57105c4fb4d8faa6cf67b'}
LOOTBAR_SOURCE = 'releases/ops/pricing-recovery-20261023/fc_residency/source/'


def build(output):
    files = {}
    for name in ('__init__.py', 'contracts.py', 'worker.py', 'adapters.py'):
        files['fc_collection/' + name] = (ROOT / 'source/fc_collection' / name).read_bytes().replace(b'\r\n', b'\n')
    for name, expected in LOOTBAR.items():
        body = subprocess.check_output(['git', '-C', str(ROOT), 'show', 'HEAD:' + LOOTBAR_SOURCE + name])
        if hashlib.sha256(body).hexdigest() != expected:
            raise ValueError('lootbar_activity_source_changed')
        files['lootbar/' + name] = body
    script = files['lootbar/background.js'].decode('utf-8')
    start = script.index('function readVisibleOffer() {')
    end = script.index('\n\nasync function collectOne(target)', start)
    # Export only the self-contained parser, not the extension's preview/storage handlers.
    files['lootbar/background.js'] = (script[start:end] + '\n// FC_PARSER_END\n').encode('utf-8')
    collector = files['lootbar/lootbar_server_collector.py'].decode('utf-8')
    replacements = {
        'CDP_ENDPOINT = os.environ.get("FC27_CDP_ENDPOINT", "http://127.0.0.1:9223")':
            'CDP_ENDPOINT = os.environ.get("FC27_CDP_ENDPOINT")',
        'end_marker = "\\n\\nasync function collectOne(target)"':
            'end_marker = "\\n// FC_PARSER_END"',
        '    reader_source = load_reader()':
            '    parsed_endpoint = urlsplit(CDP_ENDPOINT or "")\n'
            '    if (parsed_endpoint.scheme != "http" or parsed_endpoint.hostname != "127.0.0.1"\n'
            '            or parsed_endpoint.port in (None, 9223, 9225) or parsed_endpoint.path\n'
            '            or parsed_endpoint.query or parsed_endpoint.fragment or parsed_endpoint.username):\n'
            '        raise CollectionError("owned_browser_endpoint_required")\n'
            '    reader_source = load_reader()'}
    for before, after in replacements.items():
        if collector.count(before) != 1:
            raise ValueError('lootbar_export_boundary_changed')
        collector = collector.replace(before, after)
    files['lootbar/lootbar_server_collector.py'] = collector.encode('utf-8')
    manifest = dict(schema_version=1, production_ready=False, credentials=[],
        scope='FC worker and current Lootbar reader only; no coordinator or business runtime',
        lootbar=LOOTBAR, lootbar_source=LOOTBAR_SOURCE,
        export_changes=['standalone parser only', 'explicit owned loopback CDP required; shared ports rejected'],
        pending=['authenticated restricted endpoint', 'per-source request groups and total budget',
                 '183 owned browser and independent Lootbar login', 'shadow and business-entry acceptance'],
        sha256={name: hashlib.sha256(body).hexdigest() for name, body in files.items()})
    files['manifest.json'] = json.dumps(manifest, indent=2, ensure_ascii=False).encode('utf-8')
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            archive.writestr(name, body)
    return manifest


if __name__ == '__main__':
    build(Path(sys.argv[1]))
