"""Build the current UI asset for both index.html and operations.html."""
import argparse
import hashlib
from pathlib import Path
import sys

MODULE = Path(__file__).resolve().parent
REPO = MODULE.parents[2]


def build():
    web = MODULE / 'web'
    html = (web / 'index.html').read_text(encoding='utf-8')
    css = '\n'.join((web / name).read_text(encoding='utf-8-sig') for name in ['tokens.css', 'styles.css'])
    css = '\n'.join(line for line in css.splitlines() if not line.startswith('@import'))
    html = html.replace('<link rel="stylesheet" href="styles.css">', '<style>\n' + css + '\n</style>')
    for name in ['catalog.js', 'source-model.js', 'app.js']:
        script = (web / name).read_text(encoding='utf-8')
        if '</script' in script.lower():
            raise ValueError('script_termination_in_source')
        if name == 'app.js':
            theme = (REPO / 'ui-system/adapters/fs-theme.js').read_text(encoding='utf-8')
            script = theme + '\n' + script
        html = html.replace('<script src="' + name + '"></script>', '<script>\n' + script + '\n</script>')
    if 'src="catalog.js"' in html or '@import' in html:
        raise ValueError('incomplete_asset_build')
    return html.encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    print('built', len(raw), hashlib.sha256(raw).hexdigest())


if __name__ == '__main__':
    main()
