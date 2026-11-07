"""Render selected public-reference assets with resvg-py 0.5.0 (tooling only)."""
import base64
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.render-deps'))
import resvg_py

SOURCES = {
    'sbc': ('images/sbc-purple.png', None),
    'packs': ('images/pack-4.png', None),
    'gallery': ('lucide/GalleryVerticalEnd.svg', '#48D9C9'),
    'evolutions': ('lucide/Dna.svg', '#6DE794'),
    'boosting': ('images/objective.png', None),
    'coins': ('images/coin-large.png', None),
    'clock': ('lucide/Clock.svg', '#ACD9FF'),
    'search': ('lucide/Search.svg', '#E6F3FF'),
    'external': ('lucide/ExternalLink.svg', '#ACD9FF'),
    'platform': ('lucide/Gamepad2.svg', '#ACD9FF'),
}


def main():
    output = ROOT / 'quote-icons'
    output.mkdir(exist_ok=True)
    manifest = []
    for key, (relative, color) in SOURCES.items():
        path = ROOT / relative
        raw = path.read_bytes()
        if color:
            svg = raw.decode('utf-8').replace('currentColor', color)
        else:
            encoded = base64.b64encode(raw).decode('ascii')
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">'
                   '<image x="4" y="4" width="120" height="120" preserveAspectRatio="xMidYMid meet" '
                   'href="data:image/png;base64,' + encoded + '"/></svg>')
        rendered = resvg_py.svg_to_bytes(svg_string=svg, width=128, height=128, skip_system_fonts=True)
        assert rendered[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II', rendered[16:24]) == (128, 128)
        assert len(rendered) < 256 * 1024
        target = output / (key + '.png')
        target.write_bytes(rendered)
        manifest.append({'key': key, 'emoji_name': 'fcq_' + key,
                         'file': target.relative_to(ROOT).as_posix(), 'source_file': relative,
                         'color': color, 'width': 128, 'height': 128,
                         'bytes': len(rendered), 'sha256': hashlib.sha256(rendered).hexdigest(),
                         'license': 'ISC (see LUCIDE-LICENSE)' if color else 'EA/EasySBC reference; license not established',
                         'render_tool': 'resvg-py 0.5.0'})
    (ROOT / 'proposal.json').write_text(json.dumps({'icons': manifest}, indent=2) + '\n', encoding='utf-8')
    cells = []
    for index, item in enumerate(manifest):
        x, y = (index % 5) * 160, (index // 5) * 172
        encoded = base64.b64encode((ROOT / item['file']).read_bytes()).decode('ascii')
        cells.append('<image x="{}" y="{}" width="128" height="128" href="data:image/png;base64,{}"/>'.format(x + 16, y + 8, encoded))
        cells.append('<text x="{}" y="{}" text-anchor="middle" fill="#dce6f3" font-family="Arial" font-size="15">{}</text>'.format(x + 80, y + 157, item['key']))
    sheet = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="344"><rect width="800" height="344" fill="#111820"/>' + ''.join(cells) + '</svg>'
    (ROOT / 'quote-icon-contact-sheet.png').write_bytes(resvg_py.svg_to_bytes(svg_string=sheet))
    print('Rendered and verified {} transparent 128px PNG icons.'.format(len(manifest)))


if __name__ == '__main__':
    main()
