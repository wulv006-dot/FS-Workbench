"""Prepare the 3C range API payload from its verified live baseline."""
from hashlib import sha256
from pathlib import Path
import argparse
import ast


def prepare_range_api(baseline, maintenance_source, before_sha256):
    if sha256(baseline).hexdigest() != before_sha256:
        raise ValueError('range_api_baseline_drift')
    before = baseline.decode('utf-8')
    after = maintenance_source.decode('utf-8')
    old_call = _top_level_call(before)
    new_call = _top_level_call(after)
    for anchor, replacement in (
        (old_call, new_call),
        ("existing_call('fs-order-browser','fc_category_reader.py'",
         "existing_call(None,'fc_category_reader.py'"),
        ("call('fc27-cloud-browser','primary_reader.py'",
         "call(None,'primary_reader.py'"),
    ):
        if before.count(anchor) != 1:
            raise ValueError('range_api_reader_anchor_drift')
        before = before.replace(anchor, replacement, 1)
    ast.parse(before)
    return before.encode('utf-8')


def _top_level_call(source):
    node, = [node for node in ast.parse(source).body
             if isinstance(node, ast.FunctionDef) and node.name == 'call']
    return ast.get_source_segment(source, node)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('maintenance_source', type=Path)
    parser.add_argument('before_sha256')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    payload = prepare_range_api(args.baseline.read_bytes(),
                                args.maintenance_source.read_bytes().replace(b'\r\n', b'\n'),
                                args.before_sha256)
    args.output.write_bytes(payload)


if __name__ == '__main__':
    main()
