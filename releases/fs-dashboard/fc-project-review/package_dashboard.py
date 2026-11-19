"""Build the FC review as a portable HTML file from a period data packet."""
import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ASSETS = {
    '<link rel="stylesheet" href="../../../ui-system/tokens/fs-tokens.css">':
        ("style", REPO / "ui-system/tokens/fs-tokens.css"),
    '<link rel="stylesheet" href="../../../ui-system/components/fs-ui.css">':
        ("style", REPO / "ui-system/components/fs-ui.css"),
    '<link rel="stylesheet" href="review.css">':
        ("style", HERE / "review.css"),
    '<script src="../../../ui-system/adapters/fs-theme.js"></script>':
        ("script", REPO / "ui-system/adapters/fs-theme.js"),
    '<script src="review.js" defer></script>':
        ("script", HERE / "review.js"),
}


def safe_json(value):
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
        .replace("&", r"\u0026")
    )


def read(path):
    return path.read_text(encoding="utf-8-sig").strip()


def replace_once(document, marker, replacement):
    if document.count(marker) != 1:
        raise ValueError(f"Expected one page marker {marker!r}")
    return document.replace(marker, replacement, 1)


def embed(page, data):
    world = read(HERE.parent / "channel-effects-20261021/ui/world-map.js")
    geometry = json.loads(world.split("export const WORLD = ", 1)[1].removesuffix(";"))
    for key, content in (("review-geometry", geometry), ("review-data", data)):
        marker = f'<script id="{key}" type="application/json">'
        page = replace_once(page, marker + "{}</script>", marker + safe_json(content) + "</script>")
    return page + "\n"


def build(data):
    if not isinstance(data, dict) or not isinstance(data.get("packets"), list):
        raise ValueError('The data file must be an object with a "packets" array.')
    page = read(HERE / "index.html")
    for marker, (tag, path) in ASSETS.items():
        body = read(path)
        if re.search(rf"</{tag}\b", body, re.IGNORECASE):
            raise ValueError(f"Unexpected closing {tag} tag in {path.name}")
        page = replace_once(page, marker, f"<{tag}>\n{body}\n</{tag}>")
    return embed(page, data)


def build_production(output):
    output.mkdir(parents=True)
    page = read(HERE / "index.html")
    for marker, (tag, path) in ASSETS.items():
        if tag == "style":
            replacement = f'<link rel="stylesheet" href="{path.name}">'
        else:
            defer = " defer" if " defer" in marker else ""
            replacement = f'<script src="{path.name}"{defer}></script>'
        page = replace_once(page, marker, replacement)
        (output / path.name).write_bytes(path.read_bytes())
    page = replace_once(page, '<body class="fs-ui-page">', '<body class="fs-ui-page fs-unified-navigation" data-page="fc-project-review">')
    (output / "index.html").write_text(embed(page, {
        "packets": [],
        "packetUrl": "/dashboard/fs-home/range.json?mode=fc-project-review",
        "nativeFs": True,
    }), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--production-dir", type=Path)
    args = parser.parse_args()
    if args.production_dir and not (args.data or args.output):
        build_production(args.production_dir)
        return
    if not args.data or not args.output or args.production_dir:
        parser.error("use --data with --output, or use --production-dir")
    data = json.loads(read(args.data))
    page = build(data)
    args.output.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
