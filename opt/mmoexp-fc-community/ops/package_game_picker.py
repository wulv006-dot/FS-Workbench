"""Build a credential-free, hash-manifested game-picker staging archive."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    selected = list(ROOT.glob('*.py')) + list((ROOT / 'tests').rglob('*.py'))
    selected += list((ROOT / 'tests' / 'fixtures').rglob('*.json'))
    selected += list((ROOT / 'deploy').glob('*.py'))
    selected += [ROOT / 'ops' / name for name in
                 ('deploy_game_picker.py', 'publish_game_picker.py', 'discord_ops.py')]
    data = {str(path.relative_to(ROOT)).replace('\\', '/'): path.read_bytes() for path in selected}
    data['game-picker.config.json'] = Path(args.config).read_bytes()
    manifest = {name: hashlib.sha256(content).hexdigest() for name, content in data.items()}
    data['manifest.json'] = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    with tarfile.open(args.output, 'x:gz') as archive:
        for name, content in data.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(content))
    print(json.dumps({'archive': str(args.output), 'files': len(manifest),
                      'sha256': hashlib.sha256(Path(args.output).read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
